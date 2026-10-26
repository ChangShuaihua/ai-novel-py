"""网页新书写进数据库，不再分配系统目录。"""

import base64
import json
import os
import secrets
import shutil
from datetime import timedelta
from pathlib import Path

import pytest

from ainovel.entry.catalog import BookCatalog, CatalogError, _connect, _now, _unbind
from ainovel.entry.desk import Desk, DeskError
from ainovel.entry.envfile import load_env
from ainovel.entry.spine_cache import bind, load_spines, reset, store_spines


class _Shelf:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir()
        self.created = 0
        self.public = "db:7"
        self.state = "shelf"

    def create(self, requirement: str = "") -> Path:
        self.created += 1
        self.prompt = requirement
        return self.root

    def workspace(self, public: str) -> Path:
        if public != self.public or self.state == "gone":
            raise CatalogError("找不到这本书")
        return self.root

    def public_for(self, root: Path) -> str:
        if Path(root).resolve() == self.root.resolve():
            return self.public
        return ""

    def sync_tree(self, root: Path) -> None:
        return None

    def shelves(self) -> tuple[list[str], list[str]]:
        if self.state == "shelf":
            return [self.public], []
        if self.state == "trash":
            return [], [self.public]
        return [], []

    def discard(self, public: str) -> None:
        if public != self.public or self.state != "shelf":
            raise CatalogError("书架上没有这本书")
        self.state = "trash"

    def restore(self, public: str) -> None:
        if public != self.public or self.state != "trash":
            raise CatalogError("废纸篓里没有这本书")
        self.state = "shelf"

    def empty_trash(self) -> None:
        if self.state == "trash":
            self.state = "gone"


def _stop_model():
    class _Stopped:
        def complete(self, *_args, **_kwargs):
            raise RuntimeError("停")

    return _Stopped()


def test_snapshot_does_not_upload_the_book(tmp_path: Path):
    shelf = _Shelf(tmp_path / "cache")
    shelf.uploads = 0

    def counting(root: Path) -> None:
        shelf.uploads += 1

    shelf.sync_tree = counting
    desk = Desk(
        library_path=tmp_path / "library.json",
        config_path=tmp_path / "config.json",
        books_root=tmp_path / "new",
        catalog=shelf,
    )
    assert desk.snapshot("db:7")["directory"] == "db:7"
    assert desk.snapshot("db:7")["directory"] == "db:7"
    assert shelf.uploads == 0
    desk.shutdown()


def test_database_deadlock_is_retried(monkeypatch):
    import pymysql.err

    from ainovel.entry import catalog as catalog_mod

    catalog = BookCatalog({
        "id": "cd" * 8,
        "username": "retry",
        "salt": base64.b64encode(b"0123456789abcdef").decode("ascii"),
        "hash": base64.b64encode(b"h" * 32).decode("ascii"),
        "n": 1024,
        "generation": 1,
    })
    attempts = {"n": 0}

    class _Connection:
        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

    def connect():
        return _Connection()

    def work(_cur):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise pymysql.err.OperationalError(1213, "Deadlock found when trying to get lock")
        return "saved"

    monkeypatch.setattr(catalog_mod, "_connect", connect)
    assert catalog._run(work) == "saved"
    assert attempts["n"] == 2


def test_open_book_is_not_loaded_again():
    catalog = BookCatalog({
        "id": "ab" * 8,
        "username": "reader",
        "salt": base64.b64encode(b"0123456789abcdef").decode("ascii"),
        "hash": base64.b64encode(b"h" * 32).decode("ascii"),
        "n": 1024,
        "generation": 1,
    })
    root = catalog._dir(9)
    root.mkdir(parents=True, exist_ok=True)
    (root / ".ainovel-db").write_text("9", encoding="utf-8")
    catalog._bind(root, 9)

    def refuse(work):
        raise AssertionError("已经打开的书不该再查数据库")

    catalog._run = refuse
    try:
        assert catalog.workspace("db:9") == root
    finally:
        _unbind(root)
        shutil.rmtree(root, ignore_errors=True)


def test_new_book_uses_the_database_id_instead_of_a_folder(tmp_path: Path):
    shelf = _Shelf(tmp_path / "cache")
    desk = Desk(
        library_path=tmp_path / "library.json",
        config_path=tmp_path / "config.json",
        books_root=tmp_path / "new",
        catalog=shelf,
        completer_factory=_stop_model,
    )
    with pytest.raises(DeskError, match="接入模型"):
        desk.intent({"action": "start", "requirement": "雨夜醒来"})
    assert shelf.created == 0
    assert not (tmp_path / "new").exists()

    (tmp_path / "config.json").write_text(
        json.dumps({"provider": "openai", "model": "test", "api_key": "secret-key"}),
        encoding="utf-8",
    )
    snap = desk.intent({"action": "start", "requirement": "雨夜醒来", "directory": ""})
    assert snap["directory"] == "db:7"
    assert shelf.created == 1
    assert shelf.prompt == "雨夜醒来"
    assert not (tmp_path / "new").exists()
    assert "secret-key" not in json.dumps(desk.library(), ensure_ascii=False)
    assert desk.library()["books"][0]["directory"] == "db:7"
    with pytest.raises(DeskError, match="不用选目录"):
        desk.attach(str(tmp_path))
    desk.shutdown()


def test_saved_book_round_trip(tmp_path: Path):
    keys = (
        "AINOVEL_MYSQL_HOST",
        "AINOVEL_MYSQL_PORT",
        "AINOVEL_MYSQL_USER",
        "AINOVEL_MYSQL_PASSWORD",
        "AINOVEL_MYSQL_DATABASE",
    )
    before = {key: os.environ.get(key) for key in keys}
    load_env()
    user_id = secrets.token_hex(8)
    catalog = None
    try:
        if not os.environ.get("AINOVEL_MYSQL_PASSWORD"):
            pytest.skip("没有数据库配置")
        user = {
            "id": user_id,
            "username": "t" + secrets.token_hex(6),
            "salt": base64.b64encode(b"0123456789abcdef").decode("ascii"),
            "hash": base64.b64encode(b"h" * 32).decode("ascii"),
            "n": 1024,
            "generation": 1,
        }
        try:
            catalog = BookCatalog(user)
            catalog.prepare()
        except CatalogError as exc:
            pytest.skip(str(exc))
        memory = _MemoryRedis()
        bind(memory)
        root = catalog.create("雨夜醒来")
        public = catalog.public_for(root)
        fresh, _trash = catalog.shelf_spines()
        assert fresh[0]["directory"] == public
        assert fresh[0]["has_progress"] is False
        chapter = root / "chapters" / "01.md"
        chapter.parent.mkdir()
        chapter.write_text("正文", encoding="utf-8")
        meta = root / "meta"
        meta.mkdir()
        (meta / "book.json").write_text(
            json.dumps({"title": "雨夜", "synopsis": "短"}, ensure_ascii=False),
            encoding="utf-8",
        )
        (meta / "progress.json").write_text(
            json.dumps({
                "phase": "writing",
                "total_chapters": 4,
                "completed_chapters": [1],
                "current_chapter": 1,
                "total_word_count": 2,
            }),
            encoding="utf-8",
        )
        catalog.sync_tree(root)
        listed, _waiting = catalog.shelf_spines()
        assert listed[0]["title"] == "雨夜"
        assert listed[0]["phase"] == "writing"
        assert listed[0]["completed_count"] == 1
        assert listed[0]["total_chapters"] == 4
        assert listed[0]["has_progress"] is True
        store_spines(user_id, listed, [])
        assert load_spines(user_id) is not None
        shutil.rmtree(root)
        restored = BookCatalog(user).workspace(public)
        assert (restored / "chapters" / "01.md").read_text(encoding="utf-8") == "正文"
        assert catalog.shelves()[0] == [public]
        catalog.discard(public)
        assert load_spines(user_id) is None
        assert catalog.shelves() == ([], [public])
        catalog.restore(public)
        catalog.purge_expired(now=_now() + timedelta(days=4))
        assert catalog.shelves()[0] == [public]
        catalog.discard(public)
        _clear_trashed_at(user_id)
        catalog.purge_expired()
        assert catalog.shelves() == ([], [public])
        catalog.purge_expired(now=_now() + timedelta(days=3, seconds=2))
        assert catalog.shelves() == ([], [])
        with pytest.raises(CatalogError, match="找不到这本书"):
            catalog.workspace(public)
        kept = catalog.create("留在书架")
        kept_public = catalog.public_for(kept)
        catalog.discard(kept_public)
        catalog.empty_trash()
        assert catalog.shelves() == ([], [])
    finally:
        reset()
        if os.environ.get("AINOVEL_MYSQL_PASSWORD"):
            _delete_user(user_id)
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class _MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str):
        return self.values.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def _clear_trashed_at(user_id: str) -> None:
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE books SET trashed_at=NULL WHERE user_id=%s AND shelf_state='trash'",
                (user_id,),
            )
        connection.commit()
    finally:
        connection.close()


def _delete_user(user_id: str) -> None:
    try:
        from ainovel.entry.catalog import _connect

        connection = _connect()
    except Exception:
        return
    try:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
        connection.commit()
    finally:
        connection.close()
