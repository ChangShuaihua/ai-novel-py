"""阶段 8：导入、导出、评测和只订阅事件的界面。"""

import json
import shutil
from pathlib import Path

import pytest

from ainovel.domain.progress import Progress
from ainovel.domain.transitions import FlowState, Phase
from ainovel.entry.tui import format_events
from ainovel.evalrun import compare_styles, replay_decisions
from ainovel.exporting import export_txt
from ainovel.host.host import Host
from ainovel.importers.pipeline import accept_segmentation, ingest, run
from ainovel.llm.types import Completion
from ainovel.store.book import Book
from ainovel.tools import call_tool


SOURCE = "第一章\n林舟推开门。\n第二章\n他走上路。\n"


class _Importer:
    def __init__(self) -> None:
        self.segment_calls = 0
        self.fail_second = True

    def complete(self, messages, tools):
        text = messages[-1]["content"]
        if text.startswith("切分"):
            self.segment_calls += 1
            return Completion(content=json.dumps({"chapters": [{"title": "第一章"}, {"title": "第二章"}]}, ensure_ascii=False))
        if text.startswith("分析第 2") and self.fail_second:
            raise RuntimeError("分析中断")
        if text.startswith("分析第"):
            return Completion(content=json.dumps({"summary": "本章发生了"}, ensure_ascii=False))
        if text.startswith("综合"):
            return Completion(content=json.dumps({"title": "推门", "synopsis": "一个人推门上路", "premise": "回家"}, ensure_ascii=False))
        raise AssertionError(text)


def test_confirmed_split_survives_interruption(tmp_path: Path):
    root = tmp_path / "book"
    root.mkdir()
    model = _Importer()
    ingest(root, "sample.txt", SOURCE)
    assert run(root, model)["status"] == "await_confirmation"
    assert model.segment_calls == 1
    assert not (root / "chapters").exists()

    accept_segmentation(root)
    segmentation = (root / "meta" / "import" / "segmentation.json").read_bytes()
    with pytest.raises(RuntimeError, match="中断"):
        run(root, model)
    analysis = (root / "meta" / "import" / "analyses" / "000001.json").read_bytes()
    assert (root / "meta" / "import" / "segmentation.json").read_bytes() == segmentation
    assert not (root / "chapters").exists()

    model.fail_second = False
    result = run(root, model)
    assert result["status"] == "paused"
    assert model.segment_calls == 1
    assert (root / "meta" / "import" / "segmentation.json").read_bytes() == segmentation
    assert (root / "meta" / "import" / "analyses" / "000001.json").read_bytes() == analysis
    assert (root / "chapters" / "01.md").is_file()
    assert (root / "chapters" / "02.md").is_file()
    published = Book.open(root, writable=False)
    meta = published.run_meta.load()
    assert meta is not None and meta.advance_hold is None


def test_txt_export_follows_completed_chapter_order(tmp_path: Path):
    root = tmp_path / "book"
    book = Book.open(root, writable=True)
    book.progress.save(
        Progress(phase=Phase.WRITING, flow=FlowState.WRITING, total_chapters=2, completed_chapters=[2, 1])
    )
    (root / "chapters").mkdir()
    (root / "chapters" / "01.md").write_text("第一章正文\n", encoding="utf-8")
    (root / "chapters" / "02.md").write_text("第二章正文\n", encoding="utf-8")
    before = (root / "meta" / "progress.json").read_bytes()
    dest = tmp_path / "out.txt"
    export_txt(root, dest)
    text = dest.read_text(encoding="utf-8")
    assert text.index("第二章正文") < text.index("第一章正文")
    assert (root / "meta" / "progress.json").read_bytes() == before


def test_export_leaves_a_live_book_writable(tmp_path: Path):
    root = tmp_path / "book"
    live = Book.open(root, writable=True)
    live.progress.save(Progress(phase=Phase.WRITING, flow=FlowState.WRITING, total_chapters=1, completed_chapters=[1]))
    (root / "chapters").mkdir()
    (root / "chapters" / "01.md").write_text("第一章还在写。\n", encoding="utf-8")
    export_txt(root, tmp_path / "out.txt")
    live.progress.save(Progress(phase=Phase.WRITING, flow=FlowState.WRITING, total_chapters=1, completed_chapters=[1], current_chapter=1))
    assert live.progress.load().current_chapter == 1


def test_go_book_round_trip_on_a_copy(tmp_path: Path):
    source = tmp_path / "go-book"
    meta = source / "meta"
    meta.mkdir(parents=True)
    (meta / "progress.json").write_text(
        json.dumps(
            {
                "phase": "writing",
                "current_chapter": 1,
                "total_chapters": 2,
                "completed_chapters": [1],
                "total_word_count": 6,
                "chapter_word_counts": {"1": 6},
                "flow": "writing",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (meta / "checkpoints.jsonl").write_text(
        json.dumps(
            {
                "seq": 1,
                "scope": {"kind": "chapter", "chapter": 1},
                "step": "commit",
                "artifact": "chapters/01.md",
                "digest": "abc",
                "occurred_at": "2026-01-02T03:04:05Z",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    (source / "outline.json").write_text(
        json.dumps([{"chapter": 1, "title": "推门"}, {"chapter": 2, "title": "上路"}], ensure_ascii=False),
        encoding="utf-8",
    )
    (source / "chapters").mkdir()
    original = "林舟推门。\n"
    (source / "chapters" / "01.md").write_text(original, encoding="utf-8")

    readonly = Book.open(source, writable=False)
    assert readonly.progress.load().completed_chapters == [1]
    assert readonly.checkpoints.all()[0].step == "commit"
    assert json.loads((source / "outline.json").read_text(encoding="utf-8"))[1]["title"] == "上路"

    copy = tmp_path / "copy"
    shutil.copytree(source, copy)
    writable = Book.open(copy, writable=True)
    call_tool(writable, "plan_chapter", {"chapter": 2, "goal": "上路"})
    call_tool(writable, "draft_chapter", {"chapter": 2, "content": "林舟上路。"})
    call_tool(writable, "check_consistency", {"chapter": 2})
    call_tool(writable, "commit_chapter", {"chapter": 2, "summary": "林舟上路。"})

    assert (copy / "chapters" / "01.md").read_text(encoding="utf-8") == original
    assert (copy / "chapters" / "02.md").read_text(encoding="utf-8") == "林舟上路。"
    progress = json.loads((copy / "meta" / "progress.json").read_text(encoding="utf-8"))
    assert progress["completed_chapters"] == [1, 2]
    assert progress["phase"] == "writing"
    lines = (copy / "meta" / "checkpoints.jsonl").read_text(encoding="utf-8").splitlines()
    added = json.loads(lines[-1])
    assert added["step"] == "commit"
    assert added["scope"] == {"kind": "chapter", "chapter": 2}
    assert "occurred_at" in added
    reopened = Book.open(copy, writable=False)
    assert reopened.progress.load().completed_chapters == [1, 2]
    assert reopened.checkpoints.all()[-1].scope.chapter == 2


def test_eval_uses_writer_prompt_and_does_not_write_the_book(tmp_path: Path):
    root = tmp_path / "book"
    root.mkdir()
    (root / "meta").mkdir()
    (root / "meta" / "decisions.jsonl").write_text(
        json.dumps(
            {
                "id": "d1",
                "kind": "plan_start",
                "decision": {"planner": "architect_long", "task": "写设定", "reason": "长篇"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    before = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    compared = compare_styles(root, "冷一些", "热一些")
    assert compared["left"] != compared["right"]
    assert "冷一些" in compared["left"]
    assert "{{VOICE}}" not in compared["left"]

    class Same:
        def complete(self, messages, tools):
            return Completion(content=json.dumps({"planner": "architect_long", "task": "写设定", "reason": "长篇"}, ensure_ascii=False))

    notes = replay_decisions(root, Same())
    assert notes[0]["changed"] is False
    after = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert after == before


def test_tui_only_subscribes_to_events(tmp_path: Path):
    source = Path(__file__).parents[1] / "src" / "ainovel" / "entry" / "tui.py"
    text = source.read_text(encoding="utf-8")
    assert "ainovel.tools" not in text
    assert "ainovel.flow" not in text
    assert format_events(["已暂停"]) == "已暂停"

    host = Host.open(tmp_path / "book", completer=object(), require_config=False, include_home=False)
    try:
        seen = []
        host.subscribe(seen.append)
        host.engine.emit("已放行第 1 章")
        assert seen == ["已放行第 1 章"]
    finally:
        host.close()
