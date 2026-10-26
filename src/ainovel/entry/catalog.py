"""网页上新建的书存在 MySQL。对外只用 db:<id>，不让人挑选目录。"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ainovel.entry.spine_cache import drop_spines
from ainovel.store.io import add_write_hook

_SKIP = {".ainovel.lock", ".ainovel-db"}
_TRASH_KEEP = timedelta(days=3)
_PHASES = {"init", "premise", "outline", "writing", "complete"}
_BOUND: dict[str, tuple["BookCatalog", int]] = {}
_BOUND_LOCK = threading.Lock()
_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False

_FILES = """
CREATE TABLE IF NOT EXISTS book_files (
  book_id BIGINT UNSIGNED NOT NULL,
  relative_path VARCHAR(512) NOT NULL,
  body LONGBLOB NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (book_id, relative_path),
  CONSTRAINT fk_book_files_book
    FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE
) ENGINE=InnoDB COMMENT='书里的文件。网页新建的书整本存在这里'
"""


class CatalogError(RuntimeError):
    """数据库拒绝了这次书架操作。"""


def open_catalog(user: dict | None) -> BookCatalog | None:
    if not isinstance(user, dict) or not os.environ.get("AINOVEL_MYSQL_PASSWORD"):
        return None
    catalog = BookCatalog(user)
    catalog.prepare()
    return catalog


class BookCatalog:
    def __init__(self, user: dict) -> None:
        self.user_id = str(user.get("id") or "")
        self._user = user
        if len(self.user_id) != 16 or not self.user_id.isalnum():
            raise CatalogError("账号还不能写入数据库")

    def prepare(self) -> None:
        _ensure_schema()
        self._ensure_user()

    def create(self, requirement: str = "") -> Path:
        now = _now()
        pending = "pending:" + secrets.token_hex(16)
        prompt = requirement.strip()[:60000]

        def work(cur) -> int:
            cur.execute(
                """
                INSERT INTO books
                  (user_id, root_path, root_path_hash, synopsis, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (self.user_id, pending, _hash(pending), "", now, now),
            )
            book_id = int(cur.lastrowid)
            public = f"db:{book_id}"
            cur.execute(
                "UPDATE books SET root_path=%s, root_path_hash=%s WHERE id=%s AND user_id=%s",
                (public, _hash(public), book_id, self.user_id),
            )
            cur.execute(
                """
                INSERT INTO book_runs (book_id, start_prompt, pending_steer, updated_at)
                VALUES (%s, %s, %s, %s)
                """,
                (book_id, prompt, "", now),
            )
            return book_id

        book_id = self._run(work)
        root = self._dir(book_id)
        root.mkdir(parents=True, exist_ok=True)
        (root / ".ainovel-db").write_text(str(book_id), encoding="utf-8")
        self._bind(root, book_id)
        self._forget_shelf()
        return root

    def public_for(self, root: Path) -> str:
        found = _lookup(root)
        if found is None or found[0] is not self:
            return ""
        return f"db:{found[1]}"

    def workspace(self, public: str) -> Path:
        book_id = _book_id(public)
        root = self._dir(book_id)
        found = _lookup(root)
        if found is not None and found[0] is self and found[1] == book_id and (root / ".ainovel-db").is_file():
            return root
        if not self._owns(book_id):
            raise CatalogError("找不到这本书")
        root.mkdir(parents=True, exist_ok=True)
        self._bind(root, book_id)
        self._hydrate(book_id, root)
        return root

    def touch(self, root: Path) -> None:
        """只刷新书脊上的标题和进度。单个文件在写入时已经入库。"""
        found = _lookup(root)
        if found is None or found[0] is not self:
            return
        self._touch_meta(found[1], root.resolve())

    def shelves(self) -> tuple[list[str], list[str]]:
        self.purge_expired()

        def work(cur):
            cur.execute(
                """
                SELECT id, shelf_state FROM books
                WHERE user_id=%s
                ORDER BY updated_at DESC, id DESC
                """,
                (self.user_id,),
            )
            return list(cur.fetchall())

        books: list[str] = []
        trash: list[str] = []
        for row in self._run(work):
            public = f"db:{int(row['id'])}"
            if row["shelf_state"] == "trash":
                trash.append(public)
            else:
                books.append(public)
        return books, trash

    def shelf_spines(self) -> tuple[list[dict], list[dict]]:
        """书架和废纸篓的书脊。一次查询，不读取正文。"""
        self.purge_expired()

        def work(cur):
            cur.execute(
                """
                SELECT id, shelf_state, title, phase, total_chapters, completed_chapters, trashed_at
                FROM books
                WHERE user_id=%s
                ORDER BY updated_at DESC, id DESC
                """,
                (self.user_id,),
            )
            return list(cur.fetchall())

        books: list[dict] = []
        trash: list[dict] = []
        for row in self._run(work):
            spine = _spine_row(row)
            if row["shelf_state"] == "trash":
                trash.append(spine)
            else:
                books.append(spine)
        return books, trash

    def local_root(self, public: str) -> Path:
        """临时目录。只用来看锁，不把正文从数据库里拉出来。"""
        return self._dir(_book_id(public))

    def discard(self, public: str) -> None:
        self._move(public, "shelf", "trash", "书架上没有这本书")

    def restore(self, public: str) -> None:
        self._move(public, "trash", "shelf", "废纸篓里没有这本书")

    def empty_trash(self) -> None:
        def work(cur):
            cur.execute(
                "SELECT id FROM books WHERE user_id=%s AND shelf_state='trash'",
                (self.user_id,),
            )
            return [int(row["id"]) for row in cur.fetchall()]

        self._drop(self._run(work))

    def purge_expired(self, *, now: datetime | None = None) -> None:
        moment = _naive(now or _now())
        cutoff = moment - _TRASH_KEEP

        def read(cur):
            cur.execute(
                "SELECT id, trashed_at FROM books WHERE user_id=%s AND shelf_state='trash'",
                (self.user_id,),
            )
            return list(cur.fetchall())

        rows = self._run(read)
        missing = [int(row["id"]) for row in rows if row["trashed_at"] is None]
        expired = [
            int(row["id"])
            for row in rows
            if isinstance(row["trashed_at"], datetime) and row["trashed_at"] <= cutoff
        ]
        if missing:
            def stamp(cur) -> None:
                marks = ",".join(["%s"] * len(missing))
                cur.execute(
                    f"""
                    UPDATE books SET trashed_at=%s
                    WHERE user_id=%s AND shelf_state='trash' AND trashed_at IS NULL AND id IN ({marks})
                    """,
                    (moment, self.user_id, *missing),
                )

            self._run(stamp)
            self._forget_shelf()
        self._drop(expired)

    def trash_deadlines(self) -> dict[str, str]:
        def read(cur):
            cur.execute(
                """
                SELECT id, trashed_at FROM books
                WHERE user_id=%s AND shelf_state='trash' AND trashed_at IS NOT NULL
                """,
                (self.user_id,),
            )
            return list(cur.fetchall())

        marks: dict[str, str] = {}
        for row in self._run(read):
            moment = row["trashed_at"]
            if not isinstance(moment, datetime):
                continue
            due = (moment + _TRASH_KEEP).replace(tzinfo=timezone.utc)
            marks[f"db:{int(row['id'])}"] = due.isoformat().replace("+00:00", "Z")
        return marks

    def sync_tree(self, root: Path) -> None:
        found = _lookup(root)
        if found is None or found[0] is not self:
            return
        book_id = found[1]
        resolved = root.resolve()
        for path in resolved.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(resolved).as_posix()
            if relative in _SKIP:
                continue
            self.put_file(book_id, relative, path.read_bytes())
        self._touch_meta(book_id, resolved)

    def put_file(self, book_id: int, relative: str, body: bytes) -> None:
        safe = _safe_relative(relative)
        if safe is None:
            return
        now = _now()

        def work(cur) -> None:
            cur.execute(
                """
                INSERT INTO book_files (book_id, relative_path, body, updated_at)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE body=VALUES(body), updated_at=VALUES(updated_at)
                """,
                (book_id, safe, body, now),
            )
            cur.execute(
                "UPDATE books SET updated_at=%s WHERE id=%s AND user_id=%s",
                (now, book_id, self.user_id),
            )

        self._run(work)

    def delete_file(self, book_id: int, relative: str) -> None:
        safe = _safe_relative(relative)
        if safe is None:
            return

        def work(cur) -> None:
            cur.execute(
                "DELETE FROM book_files WHERE book_id=%s AND relative_path=%s",
                (book_id, safe),
            )

        self._run(work)

    def _move(self, public: str, source: str, target: str, missing: str) -> None:
        book_id = _book_id(public)
        now = _now()

        trashed_at = now if target == "trash" else None

        def work(cur) -> int:
            cur.execute(
                """
                UPDATE books SET shelf_state=%s, updated_at=%s, trashed_at=%s
                WHERE id=%s AND user_id=%s AND shelf_state=%s
                """,
                (target, now, trashed_at, book_id, self.user_id, source),
            )
            return int(cur.rowcount)

        if self._run(work) != 1:
            raise CatalogError(missing)
        self._forget_shelf()

    def _owns(self, book_id: int) -> bool:
        def work(cur):
            cur.execute(
                "SELECT id FROM books WHERE id=%s AND user_id=%s",
                (book_id, self.user_id),
            )
            return cur.fetchone()

        return self._run(work) is not None

    def _drop(self, ids: list[int]) -> None:
        if not ids:
            return
        marks = ",".join(["%s"] * len(ids))

        def delete(cur) -> None:
            cur.execute(
                f"DELETE FROM books WHERE user_id=%s AND shelf_state='trash' AND id IN ({marks})",
                (self.user_id, *ids),
            )

        self._run(delete)
        for book_id in ids:
            root = self._dir(book_id)
            _unbind(root)
            shutil.rmtree(root, ignore_errors=True)
        self._forget_shelf()

    def _hydrate(self, book_id: int, root: Path) -> None:
        def work(cur):
            cur.execute(
                "SELECT relative_path, body FROM book_files WHERE book_id=%s",
                (book_id,),
            )
            return list(cur.fetchall())

        for row in self._run(work):
            relative = _safe_relative(str(row["relative_path"]))
            if relative is None or relative in _SKIP:
                continue
            target = root / relative
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            body = row["body"]
            if isinstance(body, str):
                body = body.encode("utf-8")
            target.write_bytes(bytes(body))
        marker = root / ".ainovel-db"
        if not marker.exists():
            marker.write_text(str(book_id), encoding="utf-8")

    def _touch_meta(self, book_id: int, root: Path) -> None:
        assignments: list[str] = []
        params: list[object] = []
        info = _read_json(root / "meta" / "book.json")
        if info is not None:
            assignments.extend(["title=%s", "synopsis=%s"])
            params.extend([str(info.get("title") or "")[:200], str(info.get("synopsis") or "")])
        progress = _read_json(root / "meta" / "progress.json")
        if progress is not None:
            fields, values = _progress_fields(progress)
            assignments.extend(fields)
            params.extend(values)
        if not assignments:
            return
        assignments.append("updated_at=%s")
        params.extend([_now(), book_id, self.user_id])
        statement = f"UPDATE books SET {', '.join(assignments)} WHERE id=%s AND user_id=%s"

        def work(cur) -> None:
            cur.execute(statement, params)

        self._run(work)
        self._forget_shelf()

    def _forget_shelf(self) -> None:
        drop_spines(self.user_id)

    def _ensure_user(self) -> None:
        try:
            salt = base64.b64decode(str(self._user.get("salt") or ""), validate=True)
            digest = base64.b64decode(str(self._user.get("hash") or ""), validate=True)
        except (ValueError, TypeError) as exc:
            raise CatalogError("账号还不能写入数据库") from exc
        if len(salt) != 16 or len(digest) != 32:
            raise CatalogError("账号还不能写入数据库")
        now = _now()
        username = str(self._user.get("username") or "")[:40]
        generation = int(self._user.get("generation") or 1)
        scrypt_n = int(self._user.get("n") or 16384)

        def work(cur) -> None:
            cur.execute(
                """
                INSERT INTO users
                  (id, username, salt, password_hash, scrypt_n, generation, refresh_jti, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, %s)
                ON DUPLICATE KEY UPDATE username=VALUES(username), updated_at=VALUES(updated_at)
                """,
                (self.user_id, username, salt, digest, scrypt_n, generation, now, now),
            )

        self._run(work)

    def _dir(self, book_id: int) -> Path:
        return Path(tempfile.gettempdir()) / "ainovel-db" / self.user_id / str(book_id)

    def _bind(self, root: Path, book_id: int) -> None:
        with _BOUND_LOCK:
            _BOUND[str(root.resolve())] = (self, book_id)

    def _run(self, work):
        attempt = 0
        while True:
            attempt += 1
            connection = _connect()
            try:
                with connection.cursor() as cur:
                    result = work(cur)
                connection.commit()
                return result
            except CatalogError:
                connection.rollback()
                raise
            except Exception as exc:
                connection.rollback()
                if attempt < 3 and _deadlock(exc):
                    continue
                if type(exc).__module__.startswith("pymysql"):
                    raise CatalogError(_db_message(exc)) from exc
                raise
            finally:
                connection.close()


def _on_io(root: Path, relative: str, kind: str) -> None:
    found = _lookup(root)
    if found is None:
        return
    catalog, book_id = found
    safe = _safe_relative(relative)
    if safe is None or safe in _SKIP:
        return
    if kind == "remove":
        catalog.delete_file(book_id, safe)
        return
    target = (root / safe)
    if target.is_file():
        catalog.put_file(book_id, safe, target.read_bytes())


def _lookup(root: Path) -> tuple[BookCatalog, int] | None:
    with _BOUND_LOCK:
        return _BOUND.get(str(root.resolve()))


def _unbind(root: Path) -> None:
    with _BOUND_LOCK:
        _BOUND.pop(str(root.resolve()), None)


def _ensure_schema() -> None:
    global _SCHEMA_READY
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        connection = _connect()
        try:
            with connection.cursor() as cur:
                cur.execute(_FILES)
                _add_trashed_at(cur)
            connection.commit()
        except Exception as exc:
            connection.rollback()
            raise CatalogError(_db_message(exc)) from exc
        finally:
            connection.close()
        _SCHEMA_READY = True


def _connect():
    try:
        import pymysql
        from pymysql.cursors import DictCursor
    except ImportError as exc:
        raise CatalogError("缺少数据库驱动") from exc
    password = os.environ.get("AINOVEL_MYSQL_PASSWORD", "")
    if not password:
        raise CatalogError("还没有数据库配置")
    try:
        return pymysql.connect(
            host=os.environ.get("AINOVEL_MYSQL_HOST", "127.0.0.1"),
            port=int(os.environ.get("AINOVEL_MYSQL_PORT", "3306")),
            user=os.environ.get("AINOVEL_MYSQL_USER", "root"),
            password=password,
            database=os.environ.get("AINOVEL_MYSQL_DATABASE", "ainovel"),
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
        )
    except Exception as exc:
        raise CatalogError(_db_message(exc)) from exc


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _progress_fields(payload: dict) -> tuple[list[str], list[object]]:
    """进度文件里和书脊有关的列。写出空的已完成列表，表示这本书已经有进度。"""
    phase = str(payload.get("phase") or "")
    if phase not in _PHASES:
        return [], []
    numbers: list[int] = []
    raw = payload.get("completed_chapters")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, bool):
                continue
            if isinstance(item, int):
                numbers.append(item)
            elif isinstance(item, str) and item.isdigit():
                numbers.append(int(item))
    try:
        total = int(payload.get("total_chapters") or 0)
    except (TypeError, ValueError):
        total = 0
    if total < 0:
        total = 0
    return (
        ["phase=%s", "total_chapters=%s", "completed_chapters=%s"],
        [phase, total, json.dumps(numbers)],
    )


def _spine_row(row: dict) -> dict:
    completed_count, started = _completed_count(row.get("completed_chapters"))
    try:
        total = int(row.get("total_chapters") or 0)
    except (TypeError, ValueError):
        total = 0
    spine = {
        "directory": f"db:{int(row['id'])}",
        "title": str(row.get("title") or ""),
        "phase": str(row.get("phase") or ""),
        "completed_count": completed_count,
        "total_chapters": total if total > 0 else 0,
        "has_progress": started,
    }
    if row.get("shelf_state") == "trash":
        due = _purge_at(row.get("trashed_at"))
        if due:
            spine["purge_at"] = due
    return spine


def _completed_count(raw: object) -> tuple[int, bool]:
    """NULL 表示进度还没同步过。空列表也算已经有进度。"""
    if raw is None:
        return 0, False
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return 0, True
    if not isinstance(raw, list):
        return 0, True
    count = 0
    for item in raw:
        if isinstance(item, bool):
            continue
        if isinstance(item, int) or (isinstance(item, str) and str(item).isdigit()):
            count += 1
    return count, True


def _purge_at(moment: object) -> str:
    if not isinstance(moment, datetime):
        return ""
    due = (moment + _TRASH_KEEP).replace(tzinfo=timezone.utc)
    return due.isoformat().replace("+00:00", "Z")


def _deadlock(exc: BaseException) -> bool:
    args = getattr(exc, "args", ())
    return bool(args) and args[0] == 1213


def _book_id(public: str) -> int:
    text = str(public or "")
    if not text.startswith("db:"):
        raise CatalogError("找不到这本书")
    raw = text[3:]
    if not raw.isdigit() or int(raw) < 1:
        raise CatalogError("找不到这本书")
    return int(raw)


def _safe_relative(relative: str) -> str | None:
    text = str(relative or "").replace("\\", "/").strip()
    if text.startswith("/"):
        return None
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    if len("/".join(parts)) > 512:
        return None
    return "/".join(parts)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def _add_trashed_at(cur) -> None:
    cur.execute(
        """
        SELECT COUNT(*) AS n FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'books' AND COLUMN_NAME = 'trashed_at'
        """
    )
    row = cur.fetchone()
    if int(row["n"]) > 0:
        return
    cur.execute("ALTER TABLE books ADD COLUMN trashed_at DATETIME(6) NULL")


def _db_message(exc: BaseException) -> str:
    detail = " ".join(str(item) for item in getattr(exc, "args", ())[:1])
    if not detail:
        detail = "数据库没连上"
    if len(detail) > 180:
        detail = detail[:180] + "…"
    return detail


add_write_hook(_on_io)
