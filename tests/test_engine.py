"""引擎、宿主和无界面入口。模型全部是假的。"""

import inspect
import json
from pathlib import Path

from ainovel.agents.loop import AgentResult
from ainovel.domain.progress import Progress
from ainovel.domain.transitions import FlowState, Phase
from ainovel.entry.headless import main
from ainovel.host.config import ConfigError
from ainovel.host.engine import Engine
from ainovel.host.host import Host, HostError
from ainovel.llm.types import Completion, ToolCall
from ainovel.store.book import Book
from ainovel.store.decisions import DecisionStore

import pytest


def _tool(name: str, arguments: dict, call_id: str) -> Completion:
    return Completion(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=json.dumps(arguments, ensure_ascii=False))],
        stop_reason="tool_calls",
    )


def _names(tools: list[dict]) -> set[str]:
    return {item["function"]["name"] for item in tools}


class Script:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.arbiter_calls = 0
        self.calls = 0
        self.plan_start_before_worker = False
        self.checked = False

    def complete(self, messages, tools):
        self.calls += 1
        if not tools:
            self.arbiter_calls += 1
            return Completion(
                content=json.dumps(
                    {
                        "planner": "architect_long",
                        "task": "先把作品信息和基础设定落盘",
                        "reason": "这是长篇",
                    },
                    ensure_ascii=False,
                )
            )
        names = _names(tools)
        self.calls += 0
        if "save_foundation" in names:
            run = json.loads((self.root / "meta" / "run.json").read_text(encoding="utf-8"))
            if run.get("plan_start"):
                self.plan_start_before_worker = True
            return _tool(*self._architect(), f"arch-{self.calls}")
        if "commit_chapter" in names:
            return _tool(*self._writer(), f"write-{self.calls}")
        task = next(item["content"] for item in messages if item["role"] == "user")
        if "save_arc_summary" in task or "弧摘要" in task:
            return _tool(
                "save_arc_summary",
                {"volume": 1, "arc": 1, "summary": "林舟推门，故事开始。"},
                f"edit-{self.calls}",
            )
        return _tool(
            "save_review",
            {
                "chapter": 1,
                "scope": "arc",
                "verdict": "accept",
                "summary": "弧末可以接受。",
                "issues": [],
            },
            f"edit-{self.calls}",
        )

    def _architect(self) -> tuple[str, dict]:
        root = self.root
        if not (root / "meta" / "book.json").is_file():
            return "save_book", {"title": "推门", "synopsis": "林舟推开一扇门。"}
        if not (root / "premise.md").is_file():
            return "save_foundation", {"type": "premise", "content": "林舟要回家。", "scale": "long"}
        if not (root / "outline.json").is_file():
            return "save_foundation", {"type": "outline", "content": [{"title": "开端"}]}
        if not (root / "layered_outline.json").is_file():
            return "save_foundation", {
                "type": "layered_outline",
                "content": [
                    {
                        "title": "卷一",
                        "arcs": [
                            {"title": "起", "goal": "进门", "chapters": [{"title": "推门"}]},
                            {"title": "承", "goal": "未展开", "chapters": []},
                        ],
                    }
                ],
            }
        if not (root / "characters.json").is_file():
            return "save_foundation", {"type": "characters", "content": [{"name": "林舟"}]}
        if not (root / "world_rules.json").is_file():
            return "save_foundation", {"type": "world_rules", "content": [{"rule": "门后有路"}]}
        if not (root / "meta" / "compass.json").is_file():
            return "save_foundation", {
                "type": "update_compass",
                "content": {"ending_direction": "回家", "open_threads": ["门后的路"]},
            }
        if not (root / "meta" / "foundation_audit.json").is_file():
            return "audit_foundation", {"notes": "设定一致"}
        return "expand_next_arc", {
            "title": "上路",
            "goal": "离开门口",
            "chapters": [{"title": "第一步"}],
        }

    def _writer(self) -> tuple[str, dict]:
        root = self.root
        if not (root / "drafts" / "01.plan.json").is_file():
            return "plan_chapter", {"chapter": 1, "goal": "推门"}
        if not (root / "drafts" / "01.draft.md").is_file():
            return "draft_chapter", {"chapter": 1, "content": "林舟推开门。"}
        if not self.checked:
            self.checked = True
            return "check_consistency", {"chapter": 1}
        return "commit_chapter", {"chapter": 1, "summary": "林舟推开门。"}


def test_one_sentence_reaches_next_arc(tmp_path: Path):
    root = tmp_path / "book"
    script = Script(root)
    host = Host.open(root, completer=script, require_config=False, include_home=False)
    try:
        result = host.start("写一个推门回家的故事", max_rounds=12)
    finally:
        host.close()
    assert script.plan_start_before_worker
    assert result.status == "idle"
    assert (root / "chapters" / "01.md").read_text(encoding="utf-8") == "林舟推开门。"
    review = json.loads((root / "reviews" / "01.json").read_text(encoding="utf-8"))
    assert review["scope"] == "arc"
    assert (root / "summaries" / "arc-v01a01.json").is_file()
    layered = json.loads((root / "layered_outline.json").read_text(encoding="utf-8"))
    assert layered[0]["arcs"][1]["chapters"]
    assert not (root / "chapters" / "02.md").exists()


def test_plan_start_is_reused_until_both_records_are_removed(tmp_path: Path):
    root = tmp_path / "book"
    script = Script(root)
    host = Host.open(root, completer=script, require_config=False, include_home=False)
    try:
        host.start("写一个推门回家的故事", max_rounds=1)
    finally:
        host.close()
    assert script.arbiter_calls == 1
    run = json.loads((root / "meta" / "run.json").read_text(encoding="utf-8"))
    assert run["plan_start"]["planner"] == "architect_long"

    host = Host.open(root, completer=script, require_config=False, include_home=False)
    try:
        host.resume(max_rounds=1)
    finally:
        host.close()
    assert script.arbiter_calls == 1

    run.pop("plan_start")
    run.pop("planning_tier", None)
    (root / "meta" / "run.json").write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    host = Host.open(root, completer=script, require_config=False, include_home=False)
    try:
        host.resume(max_rounds=1)
    finally:
        host.close()
    assert script.arbiter_calls == 2


class _CountingWorker:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, completer, book, task, max_turns=None):
        self.calls += 1
        return AgentResult(messages=[])


def test_same_instruction_pauses_on_the_fifth_selection(tmp_path: Path):
    book = Book.open(tmp_path / "book", writable=True)
    book.progress.save(Progress(phase=Phase.WRITING, flow=FlowState.WRITING, total_chapters=3))
    worker = _CountingWorker()
    decisions = []

    class Retry:
        def complete(self, messages, tools):
            decisions.append(tools)
            return Completion(content=json.dumps({"action": "retry", "reason": "再试一次"}, ensure_ascii=False))

    engine = Engine(book, {"writer": worker}, Retry(), {})
    result = engine.run()
    assert worker.calls == 4
    assert result.status == "paused"
    assert "5" in result.reason
    records = [item for item in DecisionStore(book.root).load() if item["kind"] == "deadlock"]
    assert len(records) == 2
    assert len(decisions) == 2


def test_completion_report_does_not_call_the_model(tmp_path: Path):
    book = Book.open(tmp_path / "book", writable=True)
    book.progress.save(
        Progress(
            phase=Phase.COMPLETE,
            completed_chapters=[1],
            total_word_count=12,
            current_volume=1,
            current_arc=1,
        )
    )
    (book.root / "meta").mkdir(parents=True, exist_ok=True)
    (book.root / "meta" / "compass.json").write_text(
        json.dumps({"open_threads": ["门后的路"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    called = {"n": 0}

    class Silent:
        def complete(self, messages, tools):
            called["n"] += 1
            return Completion(content="{}")

    result = Engine(book, {}, Silent(), {}).run()
    assert called["n"] == 0
    assert result.status == "completed"
    assert "章数：1" in result.report
    assert "未收伏笔：1" in result.report
    source = inspect.getsource(Engine.settle)
    assert ".run(" not in source
    assert "start(" not in source


def test_missing_config_points_at_ainovel_home(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    code = main(["start", str(tmp_path / "book"), "写一个故事"])
    assert code == 1
    captured = capsys.readouterr()
    assert ".ainovel" in captured.err


def test_failed_steer_keeps_pending_text(tmp_path: Path):
    root = tmp_path / "book"
    class Broken:
        def complete(self, messages, tools):
            return Completion(content="不是 JSON")

    host = Host.open(root, completer=Broken(), require_config=False, include_home=False)
    try:
        with pytest.raises(HostError):
            host.steer("把结局改亮一点")
        meta = host.book.run_meta.load()
        assert meta is not None and meta.pending_steer == "把结局改亮一点"
        assert not (root / "meta" / "user_rules.json").exists()
    finally:
        host.close()


def test_config_error_is_exported():
    assert issubclass(ConfigError, RuntimeError)
