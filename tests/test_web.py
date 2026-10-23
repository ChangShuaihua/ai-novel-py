"""写作控制室：快照不改存储标记，书架不读正文，状态表按规格取第一条。"""

import json
from pathlib import Path

import pytest

from ainovel.domain.book import BookMetadata
from ainovel.domain.progress import Progress
from ainovel.domain.run_meta import AdvanceHold
from ainovel.domain.transitions import FlowState, Phase
from ainovel.entry.desk import Desk, DeskError
from ainovel.flow.model import Instruction
from ainovel.host.engine import Engine
from ainovel.host.snapshot import build_snapshot, shelf_row
from ainovel.importers.pipeline import ingest, run
from ainovel.llm.types import Completion
from ainovel.store.book import Book


def _book(root: Path) -> Book:
    book = Book.open(root, writable=True)
    book.info.save(BookMetadata(title="推门", synopsis="林舟推开一扇门。"))
    book.progress.save(
        Progress(
            phase=Phase.WRITING,
            flow=FlowState.WRITING,
            completed_chapters=[2, 1],
            total_chapters=4,
            total_word_count=12,
            current_chapter=2,
        )
    )
    (root / "chapters").mkdir()
    (root / "chapters" / "01.md").write_text("第一章正文，很短。\n", encoding="utf-8")
    (root / "chapters" / "02.md").write_text("# 上路\n\n" + ("雨" * 200) + "\n", encoding="utf-8")
    (root / "layered_outline.json").write_text(
        json.dumps([{"arcs": [{"chapters": [{"title": "推门"}, {"title": "大纲标题"}]}]}], ensure_ascii=False),
        encoding="utf-8",
    )
    return book


def test_snapshot_follows_completed_order_and_truncates_excerpt(tmp_path: Path):
    root = tmp_path / "book"
    _book(root)
    (root / "chapters" / "01.md").unlink()
    snap = build_snapshot(root, config_ready=True, config_dir=str(tmp_path))
    assert snap["completed_chapters"] == [2, 1]
    assert snap["total_chapters"] == 4
    assert [item["chapter"] for item in snap["chapters"]] == [2]
    assert snap["chapters"][0]["title"] == "上路"
    assert snap["latest_excerpt"] == ""
    assert "雨" * 40 not in json.dumps({key: snap[key] for key in ("title", "phase", "events")})


def test_excerpt_comes_from_the_last_completed_chapter(tmp_path: Path):
    root = tmp_path / "book"
    book = _book(root)
    progress = book.progress.load()
    progress.completed_chapters = [1, 2]
    book.progress.save(progress)
    snap = build_snapshot(root)
    assert [item["chapter"] for item in snap["chapters"]] == [1, 2]
    assert snap["chapters"][0]["title"] == "推门"
    assert snap["latest_excerpt"].endswith("…")
    assert len(snap["latest_excerpt"]) < len(snap["chapters"][1]["body"])


def test_snapshot_does_not_freeze_a_writable_book(tmp_path: Path):
    root = tmp_path / "book"
    book = _book(root)
    build_snapshot(root)
    book.progress.save(Progress(phase=Phase.PREMISE))
    assert book.progress.load().phase == Phase.PREMISE


def test_shelf_row_does_not_include_chapter_text(tmp_path: Path):
    root = tmp_path / "book"
    _book(root)
    marker = "书架不该看见的句子"
    (root / "chapters" / "01.md").write_text(marker + "\n", encoding="utf-8")
    row = shelf_row(root, locked=True, lock_path=str(root / ".ainovel.lock"))
    assert row["title"] == "推门"
    assert row["phase"] == "writing"
    assert row["completed_count"] == 2
    assert row["total_chapters"] == 4
    assert row["locked"] is True
    assert marker not in json.dumps(row)


def test_import_snapshot_lists_titles_without_publishing(tmp_path: Path):
    root = tmp_path / "book"
    root.mkdir()

    class Model:
        def complete(self, messages, tools):
            return Completion(content=json.dumps({"chapters": [{"title": "第一章"}, {"title": "第二章"}]}))

    ingest(root, "sample.txt", "第一章\n林舟。\n第二章\n上路。\n")
    assert run(root, Model())["status"] == "await_confirmation"
    snap = build_snapshot(root)
    assert snap["import_status"] == "await_confirmation"
    assert snap["import_chapters"] == ["第一章", "第二章"]
    assert snap["chapters"] == []


def test_report_only_when_complete(tmp_path: Path):
    root = tmp_path / "book"
    book = _book(root)
    assert build_snapshot(root)["report"] == ""
    progress = book.progress.load()
    progress.phase = Phase.COMPLETE
    book.progress.save(progress)
    report = build_snapshot(root)["report"]
    assert "章数：2" in report
    assert "字数：12" in report


def test_start_refuses_a_book_that_already_has_progress(tmp_path: Path):
    root = tmp_path / "book"
    book = _book(root)
    desk = Desk(library_path=tmp_path / "library.json", config_path=tmp_path / "config.json", books_root=tmp_path / "new")
    (tmp_path / "config.json").write_text(
        json.dumps({"provider": "openai", "model": "test", "api_key": "secret-key"}),
        encoding="utf-8",
    )
    snap = desk.intent({"action": "start", "directory": str(root), "requirement": "再写一本"})
    assert "继续" in snap["error"]
    assert book.progress.load().completed_chapters == [2, 1]
    assert "secret-key" not in json.dumps(snap)
    library = json.dumps(desk.library(), ensure_ascii=False)
    assert "secret-key" not in library
    assert "第一章正文" not in library


def test_missing_config_blocks_resume_without_calling_a_model(tmp_path: Path):
    root = tmp_path / "book"
    _book(root)
    desk = Desk(library_path=tmp_path / "library.json", config_path=tmp_path / "missing.json", books_root=tmp_path / "new")
    snap = desk.intent({"action": "resume", "directory": str(root)})
    assert snap["config_ready"] is False
    assert snap["error"] == "还没接入模型。"
    assert snap["running"] is False


def test_diag_and_export_work_without_config(tmp_path: Path):
    root = tmp_path / "book"
    _book(root)
    desk = Desk(library_path=tmp_path / "library.json", config_path=tmp_path / "missing.json", books_root=tmp_path / "new")
    diagnosed = desk.intent({"action": "diag", "directory": str(root)})
    assert diagnosed["config_ready"] is False
    assert diagnosed["error"] == ""
    assert any(item["rule"] == "MissingChapter" for item in diagnosed["findings"]) is False
    exported = desk.intent({"action": "export", "directory": str(root), "dest": str(tmp_path / "out.txt")})
    text = Path(exported["exported_path"]).read_text(encoding="utf-8")
    assert text.index("雨") < text.index("第一章正文")


def test_export_does_not_freeze_the_open_book(tmp_path: Path):
    root = tmp_path / "book"
    book = _book(root)
    book.run_meta.init(style="", provider="", model="")
    desk = Desk(
        library_path=tmp_path / "library.json",
        config_path=tmp_path / "missing.json",
        books_root=tmp_path / "new",
    )
    host = desk._ensure_host(root, require_config=False)
    try:
        exported = desk.intent({"action": "export", "directory": str(root), "dest": str(tmp_path / "book.txt")})
        assert exported["exported_path"]
        meta = host.book.run_meta.load() or host.book.run_meta.init(style="", provider="", model="")
        meta.advance_hold = AdvanceHold(after="boundary", reason="停一下")
        host.book.run_meta.save(meta)
        assert host.book.run_meta.load().advance_hold.reason == "停一下"
    finally:
        host.close()


def test_yield_returns_before_the_next_instruction(tmp_path: Path):
    book = Book.open(tmp_path, writable=True)
    engine = Engine(book, {}, None, {})
    engine.enqueue(Instruction(agent="writer", task="写一章", reason="因为该写了"))
    engine.request_yield()
    result = engine.run()
    assert result.status == "idle"
    assert engine.latest_instruction is None


def test_latest_instruction_is_the_one_that_started(tmp_path: Path):
    book = Book.open(tmp_path, writable=True)

    class Stop:
        def run(self, completer, store, task):
            store.progress.save(Progress(phase=Phase.COMPLETE))

    engine = Engine(book, {"writer": Stop()}, None, {})
    engine.enqueue(Instruction(agent="writer", task="写完就停", reason="试验"))
    engine.run()
    assert engine.latest_instruction is not None
    assert engine.latest_instruction.task == "写完就停"
    assert engine.latest_instruction.reason == "试验"


def test_pick_save_file_returns_a_txt_path(tmp_path: Path):
    seen = {}

    def choose(name: str) -> str:
        seen["name"] = name
        return str(tmp_path / "雨夜")

    desk = Desk(
        library_path=tmp_path / "library.json",
        config_path=tmp_path / "missing.json",
        books_root=tmp_path / "new",
        save_picker=choose,
    )
    picked = desk.pick_save_file("雨/夜.txt")
    assert seen["name"] == "雨夜.txt"
    assert picked == {"path": str((tmp_path / "雨夜.txt").resolve()), "cancelled": False}
    cancelled = Desk(
        library_path=tmp_path / "library.json",
        config_path=tmp_path / "missing.json",
        books_root=tmp_path / "new",
        save_picker=lambda _name: "",
    ).pick_save_file("小说")
    assert cancelled == {"path": "", "cancelled": True}
    with pytest.raises(DeskError, match="要是一个文件"):
        Desk(
            library_path=tmp_path / "library.json",
            config_path=tmp_path / "missing.json",
            books_root=tmp_path / "new",
            save_picker=lambda _name: str(tmp_path),
        ).pick_save_file("小说")


def test_pick_directory_returns_the_chosen_folder(tmp_path: Path):
    chosen = tmp_path / "book"
    chosen.mkdir()
    desk = Desk(
        library_path=tmp_path / "library.json",
        config_path=tmp_path / "missing.json",
        books_root=tmp_path / "new",
        picker=lambda: str(chosen),
    )
    picked = desk.pick_directory()
    assert picked["cancelled"] is False
    assert picked["directory"] == str(chosen.resolve())
    cancelled = Desk(
        library_path=tmp_path / "library.json",
        config_path=tmp_path / "missing.json",
        books_root=tmp_path / "new",
        picker=lambda: "",
    ).pick_directory()
    assert cancelled == {"directory": "", "cancelled": True}
    with pytest.raises(DeskError, match="找不到目录"):
        Desk(
            library_path=tmp_path / "library.json",
            config_path=tmp_path / "missing.json",
            books_root=tmp_path / "new",
            picker=lambda: str(tmp_path / "missing-folder"),
        ).pick_directory()


def test_model_screen_saves_without_returning_the_key(tmp_path: Path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {"provider": "openai", "model": "old", "api_key": "keep-this-secret", "roles": {"writer": {"model": "spare"}}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    desk = Desk(library_path=tmp_path / "library.json", config_path=config, books_root=tmp_path / "new")
    saved = desk.save_model(
        {"provider": "openai", "model": "gpt-4.1", "api_key": "", "api_base": "https://example.test/v1", "style": "fantasy"}
    )
    raw = json.loads(config.read_text(encoding="utf-8"))
    assert raw["api_key"] == "keep-this-secret"
    assert raw["roles"]["writer"]["model"] == "spare"
    assert raw["style"] == "fantasy"
    assert "keep-this-secret" not in json.dumps(saved)
    assert saved["key_hint"].endswith("cret")
    assert saved["model_label"] == "openai/gpt-4.1"
    assert "keep-this-secret" not in json.dumps(desk.library())

    replaced = desk.save_model({"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-secret-value", "api_base": "", "style": ""})
    assert json.loads(config.read_text(encoding="utf-8"))["api_key"] == "sk-test-secret-value"
    assert "sk-test-secret-value" not in json.dumps(replaced)

    cleared = desk.save_model({"provider": "anthropic", "model": "claude", "api_key": "", "clear_key": True, "style": ""})
    stored = json.loads(config.read_text(encoding="utf-8"))
    assert stored["api_key"] == ""
    assert stored["roles"]["writer"]["model"] == "spare"
    assert cleared["api_key_set"] is False
    assert cleared["model_label"] == "anthropic/claude"

    with pytest.raises(DeskError, match="http://"):
        desk.save_model({"provider": "openai", "model": "gpt-4.1", "api_base": "ftp://nope"})
    assert json.loads(config.read_text(encoding="utf-8"))["provider"] == "anthropic"

    desk._running = True
    stale = desk.save_model({"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-secret-value"})
    assert stale["live_stale"] is True
    desk._running = False
    desk._retire_host_if_stale()
    assert desk.model_settings()["live_stale"] is False
    assert desk.config_ready() is True


def test_discard_puts_a_book_in_the_wastebasket_without_deleting_files(tmp_path: Path):
    root = tmp_path / "book"
    _book(root)
    other = tmp_path / "other"
    other.mkdir()
    desk = Desk(library_path=tmp_path / "library.json", config_path=tmp_path / "missing.json", books_root=tmp_path / "new")
    desk.attach(str(root))
    discarded = desk.discard(str(root))
    assert discarded["books"] == []
    assert discarded["trash"][0]["directory"] == str(root.resolve())
    assert discarded["trash"][0]["title"] == "推门"
    assert (root / "chapters" / "01.md").is_file()

    desk.attach(str(other))
    kept = desk.library()
    assert [item["directory"] for item in kept["trash"]] == [str(root.resolve())]
    assert [item["directory"] for item in kept["books"]] == [str(other.resolve())]

    restored = desk.restore(str(root))
    assert [item["directory"] for item in restored["books"]] == [str(other.resolve()), str(root.resolve())]
    assert restored["books"][1]["title"] == "推门"
    assert restored["trash"] == []
    assert (root / "chapters" / "01.md").is_file()


def test_discard_refuses_a_locked_book(tmp_path: Path):
    root = tmp_path / "book"
    root.mkdir()
    (root / ".ainovel.lock").write_text("busy", encoding="utf-8")
    desk = Desk(library_path=tmp_path / "library.json", config_path=tmp_path / "missing.json", books_root=tmp_path / "new")
    desk.attach(str(root))
    with pytest.raises(DeskError, match="占用"):
        desk.discard(str(root))
    assert desk.library()["books"][0]["directory"] == str(root.resolve())
    assert desk.library()["trash"] == []
