"""写作控制室的入口。一次只跑一本书，界面拿快照、交意图。"""

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path

from ainovel.entry.catalog import CatalogError
from ainovel.entry.spine_cache import load_spines, store_spines
from ainovel.entry.guide import GuideError, begin as guide_begin, confirm as guide_confirm, load_guide, revise as guide_revise
from ainovel.exporting import export_txt
from ainovel.llm.policy import RoleClient
from ainovel.llm.types import ModelRef, RoleModel
from ainovel.host.config import ConfigError, config_dir, describe_model, load_config, store_config
from ainovel.host.host import Host, HostError
from ainovel.llm.errors import ProviderError
from ainovel.llm.litellm_client import LiteLLMTransport
from ainovel.host.snapshot import build_snapshot, has_progress, shelf_row
from ainovel.importers.pipeline import ImportError, accept_segmentation, ingest, run
from ainovel.listing import build_listing
from ainovel.store.io import atomic_replace

logger = logging.getLogger(__name__)


class _IdleCompleter:
    """推进方式切换不调用模型。真的要用模型时，缺配置已经在外面挡住。"""

    def complete(self, messages, tools):
        raise ConfigError("缺少模型配置。")

_MODEL_ACTIONS = {"start", "resume", "steer", "next", "import", "import_confirm"}
_WRITE_ACTIONS = _MODEL_ACTIONS | {"review_on", "review_off", "abort"}
_MISSING_MODEL = "还没接入模型。"
_STYLE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class DeskError(RuntimeError):
    """入口拒绝这次意图。书目录保持原样。"""


class Desk:
    def __init__(
        self,
        *,
        library_path: Path | None = None,
        config_path: Path | None = None,
        books_root: Path | None = None,
        completer_factory=None,
        picker=None,
        save_picker=None,
        catalog=None,
    ) -> None:
        self._library_path = library_path or (config_dir() / "library.json")
        self._config_path = config_path
        self._books_root = books_root or (config_dir() / "books")
        self._bookdb = catalog
        self._completer_factory = completer_factory
        self._picker = picker
        self._save_picker = save_picker
        self._guard = threading.Lock()
        self._catalog_lock = threading.Lock()
        self._pick_guard = threading.Lock()
        self._active: Path | None = None
        self._host: Host | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._error = ""
        self._queued_steer = ""
        self._exported: dict[str, str] = {}
        self._listings: dict[str, dict] = {}
        self._drop_host_when_idle = False

    def config_ready(self) -> bool:
        try:
            load_config(self._config_path)
        except ConfigError:
            return False
        return True

    def _config_file(self) -> Path:
        return self._config_path or (config_dir() / "config.json")

    def _existing_key(self) -> str:
        try:
            return load_config(self._config_file()).api_key
        except ConfigError:
            return ""

    def _drop_current_host(self) -> None:
        """当前这次写作继续用已打开的模型。空闲时立刻丢掉，下一轮按新配置打开。"""
        with self._guard:
            if self._running:
                self._drop_host_when_idle = True
                return
            host = self._host
            self._host = None
            self._active = None
        if host is not None:
            host.close()

    def _retire_host_if_stale(self) -> None:
        with self._guard:
            if not self._drop_host_when_idle:
                return
            self._drop_host_when_idle = False
            host = self._host
            self._host = None
            self._active = None
        if host is not None:
            host.close()

    def config_directory(self) -> str:
        if self._config_path is not None:
            return str(self._config_path.parent)
        return str(config_dir())

    def library(self) -> dict:
        status = self.model_settings()
        if self._bookdb is not None and getattr(self._bookdb, "shelf_spines", None) is not None:
            books, trash = self._cached_spines()
            return {
                "config_ready": status["ready"],
                "config_dir": status["config_dir"],
                "model_label": status["model_label"],
                "books": books,
                "trash": trash,
            }
        if self._bookdb is not None:
            directories, trash = self._catalog_call(self._bookdb.shelves)
            deadlines = {}
            marks = getattr(self._bookdb, "trash_deadlines", None)
            if marks is not None:
                deadlines = self._catalog_call(marks)
            discarded = []
            for item in trash:
                row = self._shelf(self._open_saved(item), public=item)
                if item in deadlines:
                    row["purge_at"] = deadlines[item]
                discarded.append(row)
            return {
                "config_ready": status["ready"],
                "config_dir": status["config_dir"],
                "model_label": status["model_label"],
                "books": [self._shelf(self._open_saved(item), public=item) for item in directories],
                "trash": discarded,
            }
        directories, trash = self._catalog()
        return {
            "config_ready": status["ready"],
            "config_dir": status["config_dir"],
            "model_label": status["model_label"],
            "books": [self._shelf(Path(item)) for item in directories],
            "trash": [self._shelf(Path(item)) for item in trash],
        }

    def model_settings(self) -> dict:
        target = self._config_file()
        try:
            view = describe_model(load_config(target))
        except ConfigError as exc:
            view = describe_model(None)
            if target.is_file():
                view["error"] = _short(exc)
        except OSError as exc:
            view = describe_model(None)
            view["error"] = _short(exc)
        view["config_dir"] = self.config_directory()
        view["model_label"] = _model_label(view)
        with self._guard:
            view["live_stale"] = self._drop_host_when_idle
        return view

    def save_model(self, payload: dict) -> dict:
        fields = _model_fields(payload)
        if not fields["api_key"]:
            if payload.get("clear_key"):
                fields["api_key"] = ""
            else:
                fields["api_key"] = self._existing_key()
        store_config(self._config_file(), **fields)
        self._drop_current_host()
        return self.model_settings()

    def probe_model(self, payload: dict, transport=None) -> dict:
        """问模型一句短话。不写配置，密钥留在账号文件里。"""
        fields = _model_fields(payload)
        if not fields["api_key"]:
            fields["api_key"] = self._existing_key()
        label = _model_label({"ready": True, "provider": fields["provider"], "model": fields["model"]})
        client = transport or LiteLLMTransport(idle_timeout=20)
        try:
            result = client.complete(
                ModelRef(
                    provider=fields["provider"],
                    model=fields["model"],
                    api_key=fields["api_key"],
                    api_base=fields["api_base"],
                ),
                [{"role": "user", "content": "只回复一个字：好"}],
                [],
                max_tokens=16,
            )
        except ProviderError as exc:
            return {"ok": False, "model_label": label, "error": _probe_error(exc, fields["api_key"])}
        reply = " ".join((result.content or "").split())
        if len(reply) > 80:
            reply = reply[:80] + "…"
        return {"ok": True, "model_label": label, "reply": reply}

    def pick_directory(self) -> dict:
        if not self._pick_guard.acquire(blocking=False):
            raise DeskError("选择窗口已经打开")
        try:
            if self._picker is not None:
                chosen = self._picker()
            else:
                from ainovel.entry.picker import ask_directory

                initial = self._books_root if self._books_root.is_dir() else None
                chosen = ask_directory("选择书目录", initial)
        finally:
            self._pick_guard.release()
        text = str(chosen or "").strip()
        if not text:
            return {"directory": "", "cancelled": True}
        root = Path(text).expanduser().resolve()
        if not root.is_dir():
            raise DeskError(f"找不到目录：{root}")
        return {"directory": str(root), "cancelled": False}

    def pick_save_file(self, name: str = "") -> dict:
        if not self._pick_guard.acquire(blocking=False):
            raise DeskError("选择窗口已经打开")
        try:
            suggested = _export_name(name)
            if self._save_picker is not None:
                chosen = self._save_picker(suggested)
            else:
                from ainovel.entry.picker import ask_save_file

                initial = self._books_root if self._books_root.is_dir() else None
                chosen = ask_save_file("导出为文本", initial, suggested)
        finally:
            self._pick_guard.release()
        text = str(chosen or "").strip()
        if not text:
            return {"path": "", "cancelled": True}
        target = Path(text).expanduser()
        if target.exists() and target.is_dir():
            raise DeskError("导出目标要是一个文件")
        if target.suffix.lower() != ".txt":
            target = target.with_suffix(".txt")
        return {"path": str(target.resolve()), "cancelled": False}

    def attach(self, directory: str) -> dict:
        if self._bookdb is not None:
            raise DeskError("新书记在数据库里，不用选目录")
        root = self._existing_directory(directory)
        self._remember(root)
        row = self._shelf(root)
        row["has_progress"] = has_progress(root)
        return row

    def discard(self, directory: str) -> dict:
        if self._bookdb is not None:
            root = self._existing_directory(directory)
            if self._busy(root):
                raise DeskError("这本书还在写或被占用，不能丢进废纸篓")
            self._catalog_call(lambda: self._bookdb.discard(directory))
            return self.library()
        root = self._existing_directory(directory)
        if self._busy(root):
            raise DeskError("这本书还在写或被占用，不能丢进废纸篓")
        resolved = str(root)

        def mutate(directories: list[str], trash: list[str]) -> tuple[list[str], list[str]]:
            if resolved not in directories:
                raise DeskError("书架上没有这本书")
            directories = [item for item in directories if item != resolved]
            if resolved not in trash:
                trash.insert(0, resolved)
            return directories, trash

        self._update_catalog(mutate)
        return self.library()

    def restore(self, directory: str) -> dict:
        if self._bookdb is not None:
            self._catalog_call(lambda: self._bookdb.restore(directory))
            return self.library()
        root = self._existing_directory(directory)
        resolved = str(root)

        def mutate(directories: list[str], trash: list[str]) -> tuple[list[str], list[str]]:
            if resolved not in trash:
                raise DeskError("废纸篓里没有这本书")
            trash = [item for item in trash if item != resolved]
            if resolved not in directories:
                directories.append(resolved)
            return directories, trash

        self._update_catalog(mutate)
        return self.library()

    def empty_trash(self) -> dict:
        if self._bookdb is not None:
            _, trash = self._catalog_call(self._bookdb.shelves)
            for item in trash:
                if self._busy(self._open_saved(item)):
                    raise DeskError("废纸篓里还有正在写或被占用的书，不能清空")
            self._catalog_call(self._bookdb.empty_trash)
            return self.library()
        _, trash = self._catalog()
        for item in trash:
            if self._busy(Path(item)):
                raise DeskError("废纸篓里还有正在写或被占用的书，不能清空")
        self._update_catalog(lambda directories, _trash: (directories, []))
        return self.library()

    def snapshot(self, directory: str) -> dict:
        root = self._existing_directory(directory)
        return self._snapshot(root)

    def intent(self, payload: dict) -> dict:
        action = str(payload.get("action") or "")
        if action == "start":
            return self._start(payload)
        directory = str(payload.get("directory") or "")
        if not directory:
            raise DeskError("缺少书目录")
        root = self._existing_directory(directory)
        if action == "export":
            return self._export(root, str(payload.get("dest") or ""))
        if action == "listing":
            return self._listing(root)
        if action == "abort":
            return self._abort(root)
        if load_guide(root) is not None and action in {"resume", "steer", "next", "review_on", "review_off", "import", "import_confirm"}:
            snap = self._snapshot(root)
            snap["error"] = "先确认当前这一步。"
            return snap
        if action == "guide_confirm":
            return self._guide_call(root, lambda: guide_confirm(root, payload, self._model_text))
        if action == "guide_revise":
            return self._guide_call(root, lambda: guide_revise(root, payload, self._model_text))
        if action in ("review_on", "review_off"):
            return self._review(root, "review" if action == "review_on" else "auto")
        if action in ("resume", "steer", "next", "import", "import_confirm"):
            return self._submit(root, action, payload)
        raise DeskError(f"未知意图 {action}")

    def shutdown(self) -> None:
        with self._guard:
            host = self._host
            thread = self._thread
        if host is not None and self._running:
            host.engine.abort()
        if thread is not None:
            thread.join(timeout=2)
        self._close_host()

    def _start(self, payload: dict) -> dict:
        title = str(payload.get("title") or "").strip()[:24]
        synopsis = str(payload.get("synopsis") or "").strip()[:1000]
        requirement = str(payload.get("requirement") or "").strip() or synopsis or title
        if not requirement:
            raise DeskError("先写下标题、简介，或要写的内容")
        if not self.config_ready():
            raise DeskError(_MISSING_MODEL)
        raw = str(payload.get("directory") or "").strip()
        if self._bookdb is not None:
            try:
                root = self._bookdb.workspace(raw) if raw else self._bookdb.create(requirement)
            except CatalogError as exc:
                raise DeskError(str(exc)) from exc
        elif raw:
            root = Path(raw).expanduser().resolve()
            root.mkdir(parents=True, exist_ok=True)
        else:
            root = self._allocate()
        if has_progress(root):
            if self._bookdb is None:
                self._remember(root)
            snap = self._snapshot(root)
            snap["error"] = "这本已经有进度。回到写作现场，用继续。"
            return snap
        if self._bookdb is not None:
            return self._guide_call(
                root,
                lambda: guide_begin(root, requirement, self._model_text, title=title, synopsis=synopsis),
            )
        self._remember(root)
        return self._submit(root, "start", {"requirement": requirement})

    def _submit(self, root: Path, action: str, payload: dict) -> dict:
        if action in _MODEL_ACTIONS and not self.config_ready():
            snap = self._snapshot(root)
            snap["error"] = _MISSING_MODEL
            return snap
        if self._is_locked(root) and action in _WRITE_ACTIONS:
            snap = self._snapshot(root)
            snap["error"] = f"这本书已有进程占用：{root / '.ainovel.lock'}"
            return snap
        with self._guard:
            if self._running and self._active != root:
                snap = self._snapshot_unlocked(root)
                snap["error"] = "另一本书正在写，这本先看着。"
                return snap
            if action == "steer" and self._running and self._active == root:
                return self._queue_steer(root, str(payload.get("text") or ""))
            if self._running:
                snap = self._snapshot_unlocked(root)
                snap["error"] = "引擎还在跑。"
                return snap
            text = str(payload.get("text") or "")
            if action == "steer" and not text.strip():
                raise DeskError("干预内容是空的")
            if action == "steer" and self._pending_unlocked(root):
                return self._snapshot_unlocked(root)
            if action == "import" and not (root / "meta" / "import").exists() and not str(payload.get("source") or "").strip():
                raise DeskError("先填写要导入的文本路径")
            self._error = ""
            self._running = True
            self._thread = threading.Thread(target=self._worker, args=(root, action, dict(payload)), daemon=True)
            self._thread.start()
        return self._snapshot(root)

    def _queue_steer(self, root: Path, text: str) -> dict:
        cleaned = text.strip()
        if not cleaned:
            raise DeskError("干预内容是空的")
        if self._queued_steer or self._pending_unlocked(root):
            return self._snapshot_unlocked(root)
        self._queued_steer = cleaned
        host = self._host
        if host is not None:
            host.engine.request_yield()
            host.engine.emit("干预已收下，当前步骤结束后裁定")
        return self._snapshot_unlocked(root)

    def _worker(self, root: Path, action: str, payload: dict) -> None:
        try:
            host = self._ensure_host(root, require_config=action in _MODEL_ACTIONS)
            self._release_pause(host)
            if action == "start":
                host.start(payload["requirement"])
            elif action == "resume":
                host.resume()
            elif action == "steer":
                host.steer(str(payload.get("text") or ""))
            elif action == "next":
                host.advance_one_chapter()
            elif action == "import":
                self._run_import(root, str(payload.get("source") or ""))
            elif action == "import_confirm":
                accept_segmentation(root)
                run(root, self._completer(), accept=True)
            self._finish_queued_steer(host)
        except Exception as exc:
            logger.exception("意图 %s 失败", action)
            with self._guard:
                self._error = _short(exc)
                text = self._queued_steer
                host = self._host
            if text and host is not None:
                self._keep_steer(host, text)
        finally:
            if self._bookdb is not None:
                try:
                    self._bookdb.sync_tree(root)
                except CatalogError:
                    logger.exception("写回数据库失败")
            with self._guard:
                self._running = False
            self._retire_host_if_stale()

    def _finish_queued_steer(self, host: Host) -> None:
        with self._guard:
            text = self._queued_steer
            self._queued_steer = ""
            cancelled = host.engine.cancelled
        if not text:
            return
        if cancelled:
            self._keep_steer(host, text)
            return
        self._release_pause(host)
        host.steer(text)

    def _keep_steer(self, host: Host, text: str) -> None:
        try:
            meta = host.book.run_meta.load() or host.book.run_meta.init(style="", provider="", model="")
            meta.pending_steer = text
            host.book.run_meta.save(meta)
        except (OSError, ValueError, TypeError):
            logger.exception("未能留下干预")
            return
        with self._guard:
            if self._queued_steer == text:
                self._queued_steer = ""

    def _abort(self, root: Path) -> dict:
        with self._guard:
            host = self._host if self._active == root else None
        if host is not None and self._running:
            host.engine.abort()
            host.engine.emit("已请求暂停")
        return self._snapshot(root)

    def _review(self, root: Path, mode: str) -> dict:
        if self._is_locked(root):
            snap = self._snapshot(root)
            snap["error"] = f"这本书已有进程占用：{root / '.ainovel.lock'}"
            return snap
        try:
            with self._guard:
                if self._running and self._active != root:
                    snap = self._snapshot_unlocked(root)
                    snap["error"] = "另一本书正在写，这本先看着。"
                    return snap
                live = self._host if self._active == root else None
            if live is None:
                self._close_host()
                completer = self._completer() if self.config_ready() else _IdleCompleter()
                host = Host.open(root, require_config=False, config_path=self._config_path, completer=completer)
                try:
                    host.set_advance_mode(mode)
                finally:
                    host.close()
            else:
                live.set_advance_mode(mode)
        except (HostError, ConfigError, OSError, ValueError) as exc:
            logger.exception("切换推进方式失败")
            snap = self._snapshot(root)
            snap["error"] = _short(exc)
            return snap
        self._note_book(root)
        return self._snapshot(root)

    def _listing(self, root: Path) -> dict:
        try:
            card = build_listing(root)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.exception("生成投稿资料失败")
            snap = self._snapshot(root)
            snap["error"] = _short(exc)
            return snap
        with self._guard:
            self._listings[str(root)] = card
        return self._snapshot(root)

    def _export(self, root: Path, dest: str) -> dict:
        target = dest.strip()
        if not target:
            raise DeskError("先选择导出文件")
        try:
            written = export_txt(root, target)
        except (OSError, ValueError, TypeError) as exc:
            logger.exception("导出失败")
            snap = self._snapshot(root)
            snap["error"] = _short(exc)
            return snap
        with self._guard:
            self._exported[str(root)] = str(written)
        return self._snapshot(root)

    def _run_import(self, root: Path, source: str) -> None:
        workspace = root / "meta" / "import" / "source.txt"
        if not workspace.is_file():
            origin = Path(source).expanduser().resolve()
            if not origin.is_file():
                raise DeskError(f"找不到导入文本：{origin}")
            ingest(root, origin.name, origin.read_text(encoding="utf-8"))
        run(root, self._completer(), accept=False)

    def _ensure_host(self, root: Path, *, require_config: bool) -> Host:
        with self._guard:
            if self._host is not None and self._active == root:
                return self._host
            previous = self._host
            self._host = None
            self._active = root
        if previous is not None:
            previous.close()
        completer = self._completer() if require_config or self.config_ready() else _IdleCompleter()
        host = Host.open(
            root,
            require_config=require_config,
            config_path=self._config_path,
            completer=completer,
        )
        with self._guard:
            self._host = host
            self._active = root
        return host

    def _close_host(self) -> None:
        with self._guard:
            host = self._host
            self._host = None
            self._active = None
        if host is not None:
            host.close()

    def _snapshot(self, root: Path) -> dict:
        with self._guard:
            return self._snapshot_unlocked(root)

    def _snapshot_unlocked(self, root: Path) -> dict:
        live = self._host if self._active == root else None
        engine = live.engine if live is not None else None
        latest = engine.latest_instruction if engine is not None else None
        usage = getattr(engine, "context_usage", None) if engine is not None else None
        if usage is not None:
            usage = str(usage)
        try:
            snap = build_snapshot(
                root,
                book=live.book if live is not None else None,
                running=self._running and self._active == root,
                paused=bool(engine.paused) if engine is not None else False,
                pause_reason=engine.pause_reason if engine is not None else "",
                events=list(engine.events) if engine is not None else [],
                latest_task=latest.task if latest is not None else "",
                latest_reason=latest.reason if latest is not None else "",
                queued_steer=self._queued_steer if self._active == root else "",
                error=self._error if self._active == root else "",
                locked=self._locked_unlocked(root),
                config_ready=self.config_ready(),
                config_dir=self.config_directory(),
                exported_path=self._exported.get(str(root), ""),
                listing=self._listings.get(str(root)),
                context_usage=usage,
            )
            return self._publish(root, snap)
        except Exception as exc:
            logger.exception("读取快照失败")
            failed = {
                "directory": str(root),
                "title": "",
                "phase": "",
                "flow": "",
                "current_chapter": 0,
                "next_chapter": 0,
                "completed_chapters": [],
                "total_chapters": 0,
                "total_word_count": 0,
                "pending_rewrites": [],
                "latest_instruction": None,
                "running": False,
                "paused": False,
                "pause_reason": "",
                "advance_mode": "",
                "advance_permit_chapter": 0,
                "advance_hold": None,
                "pending_steer": "",
                "context_usage": None,
                "report": "",
                "events": [],
                "locked": self._locked_unlocked(root),
                "lock_path": str(root / ".ainovel.lock") if self._locked_unlocked(root) else "",
                "config_ready": self.config_ready(),
                "config_dir": self.config_directory(),
                "chapters": [],
                "latest_excerpt": "",
                "import_status": "",
                "import_detail": "",
                "import_chapters": [],
                "exported_path": "",
                "listing": self._listings.get(str(root)),
                "error": _short(exc),
                "has_progress": False,
            }
            return self._publish(root, failed)

    def _publish(self, root: Path, snap: dict) -> dict:
        guide = load_guide(root)
        if guide is not None:
            snap["guide"] = guide
        if self._bookdb is None:
            return snap
        public = self._bookdb.public_for(root)
        if public:
            snap["directory"] = public
            snap["lock_path"] = ""
        return snap

    def _cached_spines(self) -> tuple[list[dict], list[dict]]:
        user_id = str(getattr(self._bookdb, "user_id", "") or "")
        if user_id:
            cached = load_spines(user_id)
            if cached is not None:
                return self._lock_rows(cached["books"]), self._lock_rows(cached["trash"])
        books, trash = self._catalog_call(self._bookdb.shelf_spines)
        if user_id:
            store_spines(user_id, books, trash)
        return self._lock_rows(books), self._lock_rows(trash)

    def _lock_rows(self, rows: list[dict]) -> list[dict]:
        marked = []
        for row in rows:
            item = dict(row)
            item["locked"] = self._row_locked(str(item.get("directory") or ""))
            item["lock_path"] = ""
            marked.append(item)
        return marked

    def _row_locked(self, public: str) -> bool:
        finder = getattr(self._bookdb, "local_root", None)
        if finder is None or not public:
            return False
        try:
            root = Path(finder(public))
        except (CatalogError, OSError, TypeError, ValueError):
            return False
        with self._guard:
            return self._locked_unlocked(root)

    def _catalog_call(self, fn):
        try:
            return fn()
        except CatalogError as exc:
            raise DeskError(str(exc)) from exc

    def _shelf(self, root: Path, public: str = "") -> dict:
        with self._guard:
            locked = self._locked_unlocked(root)
        row = shelf_row(root, locked=locked, lock_path=str(root / ".ainovel.lock"))
        if public:
            row["directory"] = public
            row["lock_path"] = ""
        return row

    def _locked_unlocked(self, root: Path) -> bool:
        if not (root / ".ainovel.lock").exists():
            return False
        host = self._host if self._active == root else None
        return not (host is not None and host.lock.held)

    def _is_locked(self, root: Path) -> bool:
        with self._guard:
            return self._locked_unlocked(root)

    def _busy(self, root: Path) -> bool:
        with self._guard:
            writing = self._running and self._active == root
        return writing or self._is_locked(root)

    def _pending_on_disk(self, root: Path) -> bool:
        with self._guard:
            return self._pending_unlocked(root)

    def _pending_unlocked(self, root: Path) -> bool:
        live = self._host if self._active == root else None
        book = live.book if live is not None else None
        if book is None:
            from ainovel.store.book import Book

            try:
                book = Book(root, readonly=True)
            except (OSError, ValueError):
                return False
        try:
            meta = book.run_meta.load()
        except (OSError, ValueError, TypeError):
            return False
        return bool(meta is not None and meta.pending_steer)

    def _guide_call(self, root: Path, work) -> dict:
        with self._guard:
            if self._running:
                snap = self._snapshot_unlocked(root)
                snap["error"] = "引擎还在跑。"
                return snap
            self._running = True
            self._active = root
            self._error = ""
        try:
            work()
        except GuideError as exc:
            with self._guard:
                self._error = str(exc)
        except Exception as exc:
            logger.exception("确认流程失败")
            with self._guard:
                self._error = _short(exc)
        finally:
            with self._guard:
                self._running = False
            self._note_book(root)
        return self._snapshot(root)

    def _note_book(self, root: Path) -> None:
        if self._bookdb is None:
            return
        note = getattr(self._bookdb, "touch", None)
        if note is None:
            return
        try:
            note(root)
        except CatalogError:
            logger.exception("写回书脊失败")

    def _model_text(self, messages: list[dict]) -> str:
        client = self._completer()
        try:
            result = client.complete(messages, [])
        except TypeError:
            try:
                config = load_config(self._config_file())
            except ConfigError as exc:
                raise GuideError(str(exc)) from exc
            result = RoleClient(
                RoleModel(
                    primary=ModelRef(
                        provider=config.provider,
                        model=config.model,
                        api_key=config.api_key,
                        api_base=config.api_base,
                    )
                ),
                client,
            ).complete(messages, [])
        text = str(getattr(result, "content", "") or "").strip()
        if not text:
            raise GuideError("模型没有返回内容")
        return text

    def _completer(self):
        if self._completer_factory is not None:
            return self._completer_factory()
        from ainovel.host.host import completer_from_config

        return completer_from_config(load_config(self._config_path))

    def _directories(self) -> list[Path]:
        return [Path(item) for item in self._catalog()[0]]

    def _catalog(self) -> tuple[list[str], list[str]]:
        with self._catalog_lock:
            return self._read_catalog()

    def _read_catalog(self) -> tuple[list[str], list[str]]:
        if not self._library_path.is_file():
            return [], []
        try:
            payload = json.loads(self._library_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.error("书架文件读不了，先显示空架：%s", self._library_path)
            return [], []
        if not isinstance(payload, dict):
            return [], []
        return self._existing_paths(payload.get("directories")), self._existing_paths(payload.get("trash"))

    @staticmethod
    def _existing_paths(raw: object) -> list[str]:
        if not isinstance(raw, list):
            return []
        found = []
        for item in raw:
            path = Path(str(item)).expanduser()
            try:
                path = path.resolve()
            except OSError:
                continue
            if path.is_dir() and str(path) not in found:
                found.append(str(path))
        return found

    def _remember(self, root: Path) -> None:
        resolved = str(root)

        def mutate(directories: list[str], trash: list[str]) -> tuple[list[str], list[str]]:
            trash = [item for item in trash if item != resolved]
            if resolved not in directories:
                directories.append(resolved)
            return directories, trash

        self._update_catalog(mutate)

    def _update_catalog(self, mutate) -> None:
        with self._catalog_lock:
            directories, trash = mutate(*self._read_catalog())
            self._write_catalog(directories, trash)

    def _write_catalog(self, directories: list[str], trash: list[str]) -> None:
        self._library_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_replace(
            self._library_path,
            (json.dumps({"directories": directories, "trash": trash}, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )

    def _allocate(self) -> Path:
        self._books_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        root = self._books_root / stamp
        suffix = 0
        while root.exists():
            suffix += 1
            root = self._books_root / f"{stamp}-{suffix}"
        root.mkdir()
        return root

    def _open_saved(self, public: str) -> Path:
        return self._catalog_call(lambda: self._bookdb.workspace(public))

    def _existing_directory(self, directory: str) -> Path:
        if self._bookdb is not None:
            return self._open_saved(directory)
        root = Path(directory).expanduser().resolve()
        if not root.is_dir():
            raise DeskError(f"找不到书目录：{root}")
        return root

    @staticmethod
    def _release_pause(host: Host) -> None:
        host.engine.paused = False
        host.engine.cancelled = False
        host.engine.pause_reason = ""


def _model_fields(payload: dict) -> dict:
    provider = str(payload.get("provider") or "").strip()
    model = str(payload.get("model") or "").strip()
    api_key = str(payload.get("api_key") or "").strip()
    api_base = str(payload.get("api_base") or "").strip()
    style = str(payload.get("style") or "").strip()
    if any("\n" in item or "\r" in item for item in (provider, model, api_key, api_base, style)):
        raise DeskError("模型配置不能换行")
    if not provider or not model:
        raise DeskError("提供方和模型名都要填写")
    if len(provider) > 80 or len(model) > 200 or len(api_key) > 512 or len(api_base) > 300:
        raise DeskError("模型配置里有一项太长")
    if api_base and not api_base.startswith(("http://", "https://")):
        raise DeskError("接口地址要以 http:// 或 https:// 开头")
    if style and _STYLE_NAME.fullmatch(style) is None:
        raise DeskError("文风只能使用字母、数字、短横线，或留空")
    return {"provider": provider, "model": model, "api_key": api_key, "api_base": api_base, "style": style}


def _export_name(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', "", str(name or "")).strip().strip(".")
    stem = cleaned[:-4] if cleaned.lower().endswith(".txt") else cleaned
    stem = stem.strip().strip(".") or "小说"
    return f"{stem[:60]}.txt"


def _probe_error(exc: ProviderError, api_key: str) -> str:
    known = {
        "auth": "密钥不对，或这个账号没有调用权限。",
        "model_not_found": "找不到这个模型。",
        "timeout": "模型没有在时间内应答。",
        "stream_idle": "模型没有在时间内应答。",
        "stream_interrupted": "模型应答中断了。",
        "rate_limit": "调用太频繁，过一会儿再检测。",
        "unavailable": "模型服务暂时不可用。",
    }
    text = known.get(exc.kind)
    if text:
        return text
    detail = _short(exc)
    if api_key:
        detail = detail.replace(api_key, "····")
    return detail or "检测没有通过。"


def _model_label(status: dict) -> str:
    if not status.get("ready"):
        return ""
    model = str(status.get("model") or "")
    provider = str(status.get("provider") or "")
    if not provider or "/" in model:
        return model
    return f"{provider}/{model}"


def _short(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    if len(text) > 160:
        return text[:160] + "…"
    return text
