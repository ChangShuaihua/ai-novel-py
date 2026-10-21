import json
from pathlib import Path

import pytest

from ainovel.agents import AgentLoopError, CheckpointGuardError, build_workers
from ainovel.agents.catalog import ARCHITECT_TOOLS, EDITOR_TOOLS, WRITER_TOOLS
from ainovel.agents.workers import editor_steps
from ainovel.domain.progress import Progress
from ainovel.domain.transitions import FlowState, Phase
from ainovel.llm.types import Completion, ToolCall
from ainovel.store.book import Book
from ainovel.tools import call_tool
from ainovel.voice import build_writer_prompt, load_bundle


class _Script:
    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.calls = 0
        self.tools: list[list[str]] = []

    def complete(self, messages: list[dict], tools: list[dict]):
        self.calls += 1
        self.tools.append([item["function"]["name"] for item in tools])
        if not self.replies:
            raise AssertionError("脚本已用完")
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _call(name: str, arguments: dict, call_id: str) -> Completion:
    return Completion(tool_calls=[ToolCall(id=call_id, name=name, arguments=json.dumps(arguments, ensure_ascii=False))])


def _workers(tmp_path: Path, style: str = ""):
    bundle = load_bundle(style, tmp_path, include_home=False)
    return build_workers(tmp_path, style=style, bundle=bundle, include_home=False)


def test_tool_sets_match_the_three_roles(tmp_path: Path):
    workers = _workers(tmp_path)
    assert workers["architect_short"].tool_names == ARCHITECT_TOOLS
    assert workers["architect_long"].tool_names == ARCHITECT_TOOLS
    assert workers["writer"].tool_names == WRITER_TOOLS
    assert workers["editor"].tool_names == EDITOR_TOOLS
    assert "commit_chapter" not in workers["architect_short"].tool_names
    assert "save_foundation" not in workers["writer"].tool_names
    assert "draft_chapter" not in workers["editor"].tool_names
    assert editor_steps("审阅这一章") == ("review",)
    assert editor_steps("请 save_arc_summary") == ("arc_summary",)
    assert editor_steps("写卷摘要") == ("volume_summary",)


def test_foreign_tool_cannot_enter_the_agent(tmp_path: Path):
    book = Book.open(tmp_path, writable=True)
    workers = _workers(tmp_path)
    cases = (
        ("architect_short", "commit_chapter", {"chapter": 1, "summary": "不该写"}),
        ("writer", "save_foundation", {"type": "premise", "content": "不该规划"}),
        ("editor", "draft_chapter", {"chapter": 1, "content": "不该起草"}),
    )
    for name, tool, args in cases:
        script = _Script([_call(tool, args, "x")])
        with pytest.raises(AgentLoopError, match="超过 1 轮") as caught:
            workers[name].run(script, book, "只做本职", max_turns=1)
        assert "不在本轮允许列表" in json.dumps(caught.value.messages, ensure_ascii=False)


def test_architect_save_ends_the_run(tmp_path: Path):
    book = Book.open(tmp_path, writable=True)
    worker = _workers(tmp_path)["architect_short"]
    script = _Script([_call("save_foundation", {"type": "premise", "content": "雨夜来客。"}, "save")])
    result = worker.run(script, book, "保存前提")
    assert result.stop_tool == "save_foundation"
    assert script.calls == 1
    assert script.tools[0] == sorted(ARCHITECT_TOOLS)
    assert (tmp_path / "premise.md").read_text(encoding="utf-8") == "雨夜来客。"
    assert any(row.step == "premise" for row in book.checkpoints.all())


def test_writer_commit_ends_the_run(tmp_path: Path):
    book = Book.open(tmp_path, writable=True)
    book.progress.save(Progress(phase=Phase.WRITING, total_chapters=3, flow=FlowState.WRITING))
    bundle = load_bundle("fantasy", tmp_path, include_home=False)
    worker = build_workers(tmp_path, style="fantasy", bundle=bundle, include_home=False)["writer"]
    assert worker.system_prompt == build_writer_prompt(bundle.prompts["writer.md"], bundle.voice, bundle.styles["fantasy"])
    assert "{{VOICE}}" not in worker.system_prompt
    assert "奇幻冒险风格" in worker.system_prompt
    script = _Script(
        [
            _call("plan_chapter", {"chapter": 1, "goal": "进门", "conflict": "门关着"}, "plan"),
            _call("draft_chapter", {"chapter": 1, "content": "林舟推开门。"}, "draft"),
            _call("check_consistency", {"chapter": 1}, "check"),
            _call(
                "commit_chapter",
                {"chapter": 1, "summary": "林舟进了门", "hook_type": "question", "dominant_strand": "quest"},
                "commit",
            ),
        ]
    )
    result = worker.run(script, book, "写第 1 章")
    assert result.stop_tool == "commit_chapter"
    assert script.calls == 4
    assert script.tools[0] == sorted(WRITER_TOOLS)
    assert (tmp_path / "chapters" / "01.md").read_text(encoding="utf-8") == "林舟推开门。"


def test_editor_arc_review_ends_the_run(tmp_path: Path):
    book = Book.open(tmp_path, writable=True)
    book.progress.save(Progress(phase=Phase.WRITING, total_chapters=2, flow=FlowState.WRITING))
    call_tool(
        book,
        "save_foundation",
        {"type": "layered_outline", "content": [{"arcs": [{"chapters": [{}, {}]}, {"chapters": []}]}]},
    )
    worker = _workers(tmp_path)["editor"]
    script = _Script(
        [
            _call(
                "save_review",
                {"chapter": 2, "scope": "arc", "verdict": "accept", "summary": "这一弧成立", "issues": []},
                "review",
            )
        ]
    )
    result = worker.run(script, book, "审阅刚结束的这一弧")
    assert result.stop_tool == "save_review"
    assert script.calls == 1
    assert script.tools[0] == sorted(EDITOR_TOOLS)
    assert json.loads((tmp_path / "reviews" / "02.json").read_text(encoding="utf-8"))["scope"] == "arc"


def test_arc_summary_task_rejects_review_only(tmp_path: Path):
    book = Book.open(tmp_path, writable=True)
    book.progress.save(Progress(phase=Phase.WRITING, total_chapters=2, flow=FlowState.WRITING))
    call_tool(
        book,
        "save_foundation",
        {"type": "layered_outline", "content": [{"arcs": [{"chapters": [{}, {}]}]}]},
    )
    worker = _workers(tmp_path)["editor"]
    review = _call(
        "save_review",
        {"chapter": 2, "scope": "arc", "verdict": "accept", "summary": "先复核", "issues": []},
        "review",
    )
    script = _Script([review, review, review])
    with pytest.raises(CheckpointGuardError, match="弧摘要") as caught:
        worker.run(script, book, "请调用 save_arc_summary 写下弧摘要")
    assert caught.value.consecutive == 3
    assert not list((tmp_path / "summaries").glob("*.json"))


def test_prompt_cache_key_is_frozen_for_the_run(tmp_path: Path):
    first = _workers(tmp_path)
    second = build_workers(tmp_path, run_seq=1, bundle=load_bundle(include_home=False), include_home=False)
    assert first["writer"].prompt_cache_key == second["writer"].prompt_cache_key
    assert "writer" in first["writer"].prompt_cache_key
    third = build_workers(tmp_path, run_seq=2, bundle=load_bundle(include_home=False), include_home=False)
    assert third["writer"].prompt_cache_key != first["writer"].prompt_cache_key
    assert first["architect_short"].prompt_cache_key != first["writer"].prompt_cache_key
