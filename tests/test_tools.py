import json
from pathlib import Path

import pytest

from ainovel.domain.commit import CommitStage, PendingCommit
from ainovel.domain.progress import Progress
from ainovel.domain.transitions import FlowState, Phase
from ainovel.store.book import Book
from ainovel.tools import call_tool
from ainovel.tools.errors import ToolArgsError, ToolConflict


def _book(tmp_path: Path) -> Book:
    book = Book.open(tmp_path, writable=True)
    book.progress.save(Progress(phase=Phase.WRITING, total_chapters=3, flow=FlowState.WRITING))
    return book


def _write_chapter(book: Book, text: str = "林舟推开门。") -> dict:
    call_tool(book, "plan_chapter", {"chapter": 1, "goal": "进门", "conflict": "门关着"})
    call_tool(book, "draft_chapter", {"chapter": 1, "content": text})
    call_tool(book, "check_consistency", {"chapter": 1})
    return call_tool(
        book,
        "commit_chapter",
        {"chapter": 1, "summary": "林舟进了门", "hook_type": "question", "dominant_strand": "quest"},
    )


def test_writer_order_rejects_skipped_steps(tmp_path: Path):
    book = _book(tmp_path)
    with pytest.raises(ToolConflict, match="没有计划"):
        call_tool(book, "draft_chapter", {"chapter": 1, "content": "正文"})
    call_tool(book, "plan_chapter", {"chapter": 1, "goal": "进门"})
    with pytest.raises(ToolConflict, match="没有草稿"):
        call_tool(book, "check_consistency", {"chapter": 1})
    call_tool(book, "draft_chapter", {"chapter": 1, "content": "林舟推开门。"})
    with pytest.raises(ToolConflict, match="一致性检查"):
        call_tool(book, "commit_chapter", {"chapter": 1, "summary": "摘要"})


def test_commit_happy_path_and_stable_replay(tmp_path: Path):
    book = _book(tmp_path)
    result = _write_chapter(book)
    assert result["committed"] is True
    assert result["next_chapter"] == 2
    assert result["flow"] == "writing"
    assert (tmp_path / "chapters" / "01.md").read_text(encoding="utf-8") == "林舟推开门。"
    assert book.pending.load() is None
    again = call_tool(book, "commit_chapter", {"chapter": 1, "summary": "另一份摘要"})
    assert again["summary"] == "林舟进了门"
    assert (tmp_path / "chapters" / "01.md").read_text(encoding="utf-8") == "林舟推开门。"


def test_rewrite_replaces_chapter_facts_without_duplicating(tmp_path: Path):
    book = _book(tmp_path)
    _commit(book, 1, "甲章", event="旧事", strand="quest", hook="question")
    _commit(book, 2, "乙章", event="后事", strand="intrigue", hook="danger")
    progress = book.progress.load()
    assert progress is not None
    progress.pending_rewrites = [1]
    progress.flow = FlowState.REWRITING
    book.progress.save(progress)
    call_tool(book, "edit_chapter", {"chapter": 1, "content": "甲章改过"})
    call_tool(book, "check_consistency", {"chapter": 1})
    call_tool(
        book,
        "commit_chapter",
        {
            "chapter": 1,
            "summary": "改过",
            "timeline": [{"event": "新事"}],
            "dominant_strand": "bond",
            "hook_type": "image",
        },
    )
    events = [json.loads(line)["event"] for line in (tmp_path / "timeline.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events == ["新事", "后事"]
    progress = book.progress.load()
    assert progress is not None
    assert progress.strand_history == ["bond", "intrigue"]
    assert progress.hook_history == ["image", "danger"]

    (tmp_path / "timeline.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"chapter": 1, "event": "新事"}, ensure_ascii=False),
                json.dumps({"chapter": 1, "event": "新事"}, ensure_ascii=False),
                json.dumps({"chapter": 2, "event": "后事"}, ensure_ascii=False),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    book.pending.save(
        PendingCommit(
            chapter=1,
            stage=CommitStage.STARTED,
            payload={"chapter": 1, "summary": "改过", "timeline": [{"event": "新事"}]},
            draft_content="甲章改过",
            summary="改过",
            dominant_strand="bond",
            hook_type="image",
            rewrite=True,
        )
    )
    call_tool(book, "commit_chapter", {"chapter": 1, "summary": "不该再记一条"})
    events = [json.loads(line)["event"] for line in (tmp_path / "timeline.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events == ["新事", "后事"]
    progress = book.progress.load()
    assert progress is not None
    assert progress.strand_history == ["bond", "intrigue"]
    assert progress.hook_history == ["image", "danger"]


def _commit(book: Book, chapter: int, text: str, *, event: str, strand: str, hook: str) -> None:
    call_tool(book, "plan_chapter", {"chapter": chapter, "goal": event})
    call_tool(book, "draft_chapter", {"chapter": chapter, "content": text})
    call_tool(book, "check_consistency", {"chapter": chapter})
    call_tool(
        book,
        "commit_chapter",
        {
            "chapter": chapter,
            "summary": event,
            "timeline": [{"event": event}],
            "dominant_strand": strand,
            "hook_type": hook,
        },
    )


def test_pending_commit_resumes_from_each_stage_and_ignores_new_text(tmp_path: Path):
    book = _book(tmp_path)
    call_tool(book, "plan_chapter", {"chapter": 1, "goal": "进门"})
    call_tool(book, "draft_chapter", {"chapter": 1, "content": "冻结正文"})
    call_tool(book, "check_consistency", {"chapter": 1})
    book.pending.save(
        PendingCommit(
            chapter=1,
            stage=CommitStage.STARTED,
            payload={"chapter": 1, "summary": "冻结摘要", "timeline": [{"event": "进门"}]},
            draft_content="冻结正文",
            summary="冻结摘要",
        )
    )
    (tmp_path / "drafts" / "01.draft.md").write_text("新正文", encoding="utf-8")
    started = call_tool(book, "commit_chapter", {"chapter": 1, "summary": "新摘要"})
    assert started["summary"] == "冻结摘要"
    assert (tmp_path / "chapters" / "01.md").read_text(encoding="utf-8") == "冻结正文"
    assert "进门" in (tmp_path / "timeline.jsonl").read_text(encoding="utf-8")

    book = Book.open(tmp_path, writable=True)
    (tmp_path / "chapters" / "01.md").write_text("冻结正文", encoding="utf-8")
    book.progress.save(Progress(phase=Phase.WRITING, total_chapters=3, completed_chapters=[], flow=FlowState.WRITING))
    book.pending.save(
        PendingCommit(
            chapter=1,
            stage=CommitStage.STATE_APPLIED,
            payload={"chapter": 1},
            draft_content="冻结正文",
            summary="阶段摘要",
        )
    )
    applied = call_tool(book, "commit_chapter", {"chapter": 1, "summary": "不该采用"})
    assert applied["summary"] == "阶段摘要"
    assert (tmp_path / "chapters" / "01.md").read_text(encoding="utf-8") == "冻结正文"
    progress = book.progress.load()
    assert progress is not None and 1 in progress.completed_chapters

    book.pending.save(
        PendingCommit(
            chapter=1,
            stage=CommitStage.PROGRESS_MARKED,
            draft_content="冻结正文",
            summary="进度后摘要",
            output={"chapter": 1, "summary": "进度后摘要", "committed": True, "next_chapter": 2},
        )
    )
    marked = call_tool(book, "commit_chapter", {"chapter": 1, "summary": "仍不采用"})
    assert marked["summary"] == "进度后摘要"
    assert book.pending.load() is None

    book.pending.save(
        PendingCommit(
            chapter=1,
            stage=CommitStage.SIGNAL_SAVED,
            draft_content="冻结正文",
            summary="信号摘要",
            output={"chapter": 1, "summary": "信号摘要", "committed": True},
        )
    )
    saved = call_tool(book, "commit_chapter", {"chapter": 1, "summary": "最后一次新参数"})
    assert saved["summary"] == "信号摘要"
    assert book.pending.load() is None


def test_save_review_maps_verdict_to_flow_and_queue(tmp_path: Path):
    book = _book(tmp_path)
    _write_chapter(book)
    accepted = call_tool(
        book,
        "save_review",
        {"chapter": 1, "scope": "chapter", "verdict": "accept", "summary": "通过", "issues": []},
    )
    assert accepted["next_flow"] == "writing"
    progress = book.progress.load()
    assert progress is not None and progress.pending_rewrites == []

    polished = call_tool(
        book,
        "save_review",
        {
            "chapter": 1,
            "scope": "chapter",
            "verdict": "polish",
            "summary": "打磨结尾",
            "issues": [{"chapters": [1], "requires_change": True, "description": "结尾弱"}],
        },
    )
    assert polished["next_flow"] == "polishing"
    progress = book.progress.load()
    assert progress is not None
    assert progress.flow == FlowState.POLISHING
    assert progress.pending_rewrites == [1]
    progress.flow = FlowState.WRITING
    book.progress.save(progress)

    rewritten = call_tool(
        book,
        "save_review",
        {
            "chapter": 1,
            "verdict": "rewrite",
            "summary": "重写冲突",
            "issues": [{"requires_change": True, "description": "冲突不够"}],
        },
    )
    assert rewritten["next_flow"] == "rewriting"
    progress = book.progress.load()
    assert progress is not None and progress.pending_rewrites == [1]
    with pytest.raises(ToolConflict):
        call_tool(book, "edit_chapter", {"chapter": 2, "content": "不该改"})
    call_tool(book, "edit_chapter", {"chapter": 1, "content": "林舟撞开了门。"})


def test_save_foundation_types_and_complete_conditions(tmp_path: Path):
    book = _book(tmp_path)
    with pytest.raises(ToolArgsError, match="unknown type"):
        call_tool(book, "save_foundation", {"type": "epilogue", "content": {}})
    call_tool(book, "save_book", {"title": "山海", "synopsis": "一个人出门。"})
    call_tool(book, "save_foundation", {"type": "premise", "content": "一个人要出门。", "scale": "short"})
    call_tool(
        book,
        "save_foundation",
        {"type": "outline", "content": [{"chapter": 1, "title": "门"}]},
    )
    call_tool(book, "save_foundation", {"type": "characters", "content": [{"name": "林舟", "role": "主角"}]})
    call_tool(book, "save_foundation", {"type": "world_rules", "content": [{"rule": "没有仙术"}]})
    meta = book.run_meta.load()
    assert meta is not None and meta.planning_tier == "short"
    assert (tmp_path / "characters.md").read_text(encoding="utf-8").startswith("# 角色")

    _write_chapter(book, "林舟推开门。")
    call_tool(
        book,
        "save_foundation",
        {"type": "update_compass", "content": {"ending_direction": "回家", "open_threads": ["门后是谁"]}},
    )
    with pytest.raises(ToolConflict, match="open_threads"):
        call_tool(book, "save_foundation", {"type": "complete_book", "content": {}, "reason": "写完了"})
    call_tool(
        book,
        "save_foundation",
        {"type": "update_compass", "content": {"ending_direction": "回家", "open_threads": []}},
    )
    # 大纲只有 1 章，已经写完；total_chapters 会被 outline 保存改成 1。
    done = call_tool(book, "save_foundation", {"type": "complete_book", "content": {}, "reason": "故事收束"})
    assert done["type"] == "complete_book"
    progress = book.progress.load()
    assert progress is not None and progress.phase == Phase.COMPLETE

    fresh = Book.open(tmp_path / "other", writable=True)
    fresh.progress.save(
        Progress(phase=Phase.WRITING, total_chapters=2, completed_chapters=[1], flow=FlowState.WRITING)
    )
    with pytest.raises(ToolConflict, match="未写章节"):
        call_tool(fresh, "save_foundation", {"type": "complete_book", "content": {}, "reason": "太早"})


def test_arc_review_rejects_chapters_outside_span(tmp_path: Path):
    book = _book(tmp_path)
    call_tool(
        book,
        "save_foundation",
        {
            "type": "layered_outline",
            "content": [{"arcs": [{"chapters": [{}, {}]}, {"chapters": []}]}],
        },
    )
    with pytest.raises(ToolArgsError, match="超出"):
        call_tool(
            book,
            "save_review",
            {
                "chapter": 2,
                "scope": "arc",
                "verdict": "rewrite",
                "summary": "越界",
                "issues": [{"chapters": [3], "requires_change": True, "description": "不在本弧"}],
            },
        )
