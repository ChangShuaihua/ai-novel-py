import json
from pathlib import Path

import pytest

from ainovel.agents import AgentLoopError, CheckpointGuardError, run_agent
from ainovel.domain.progress import Progress
from ainovel.domain.transitions import FlowState, Phase
from ainovel.llm.errors import ProviderError
from ainovel.llm.policy import RoleClient
from ainovel.llm.types import Completion, ModelRef, RoleModel, ToolCall, ToolSpec
from ainovel.store.book import Book
from ainovel.tools import call_tool


class _Steps:
    def __init__(self) -> None:
        self.rows: list = []

    def all(self):
        return list(self.rows)

    def add(self, step: str) -> None:
        self.rows.append(type("Row", (), {"seq": len(self.rows) + 1, "step": step})())


class _Script:
    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.calls = 0
        self.seen: list[list[dict]] = []
        self.tools: list[list[str]] = []

    def complete(self, messages: list[dict], tools: list[dict]):
        self.calls += 1
        self.seen.append(list(messages))
        self.tools.append([item["function"]["name"] for item in tools])
        if not self.replies:
            raise AssertionError("脚本已用完")
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _call(name: str, arguments: dict, call_id: str) -> Completion:
    return Completion(tool_calls=[ToolCall(id=call_id, name=name, arguments=json.dumps(arguments, ensure_ascii=False))])


def _book(tmp_path: Path) -> Book:
    book = Book.open(tmp_path, writable=True)
    book.progress.save(Progress(phase=Phase.WRITING, total_chapters=3, flow=FlowState.WRITING))
    return book


def _specs(*names: str) -> list[ToolSpec]:
    return [ToolSpec(name=name, description=name) for name in names]


def test_scripted_model_stops_after_successful_commit(tmp_path: Path):
    book = _book(tmp_path)
    script = _Script(
        [
            _call("draft_chapter", {"chapter": 1, "content": "还没计划"}, "bad"),
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
    result = run_agent(
        script,
        system_prompt="测试用的短提示词",
        task="写第 1 章",
        tool_specs=_specs("plan_chapter", "draft_chapter", "check_consistency", "commit_chapter"),
        call_tool=lambda name, args: call_tool(book, name, args),
        checkpoints=book.checkpoints,
        stop_after=("commit_chapter",),
        required_steps=("commit",),
        block_message="还没提交",
    )
    assert result.stop_tool == "commit_chapter"
    assert script.calls == 5
    assert script.seen[0][0]["content"] == "测试用的短提示词"
    assert script.tools[0] == ["check_consistency", "commit_chapter", "draft_chapter", "plan_chapter"]
    assert "没有计划" in script.seen[1][-1]["content"]
    assert (tmp_path / "chapters" / "01.md").read_text(encoding="utf-8") == "林舟推开门。"
    assert any(row.step == "commit" for row in book.checkpoints.all())


def test_ending_without_checkpoint_is_refused(tmp_path: Path):
    book = _book(tmp_path)
    script = _Script([Completion(content="我写完了")] * 3)
    with pytest.raises(CheckpointGuardError, match="还没提交") as caught:
        run_agent(
            script,
            system_prompt="短提示",
            task="写一章",
            tool_specs=_specs("plan_chapter"),
            call_tool=lambda name, args: call_tool(book, name, args),
            checkpoints=book.checkpoints,
            stop_after=("commit_chapter",),
            required_steps=("commit",),
            block_message="还没提交",
        )
    assert caught.value.consecutive == 3
    assert script.calls == 3
    assert book.checkpoints.all() == []
    assert "还没提交" in script.seen[1][-1]["content"]
    assert "还没提交" in script.seen[2][-1]["content"]


def test_stop_tool_without_checkpoint_is_also_refused():
    steps = _Steps()
    script = _Script([_call("finish", {}, "1")] * 3)

    def call(name: str, args: dict) -> dict:
        return {"ok": True}

    with pytest.raises(CheckpointGuardError) as caught:
        run_agent(
            script,
            system_prompt="短提示",
            task="收尾",
            tool_specs=_specs("finish"),
            call_tool=call,
            checkpoints=steps,
            stop_after=("finish",),
            required_steps=("commit",),
            block_message="还没提交",
        )
    assert caught.value.consecutive == 3
    assert script.calls == 3


def test_new_checkpoint_resets_consecutive_blocks():
    steps = _Steps()
    script = _Script(
        [
            Completion(content="结束"),
            _call("note", {}, "note"),
            Completion(content="结束"),
            Completion(content="结束"),
            Completion(content="结束"),
        ]
    )

    def call(name: str, args: dict) -> dict:
        steps.add("plan")
        return {"saved": True}

    with pytest.raises(CheckpointGuardError) as caught:
        run_agent(
            script,
            system_prompt="短提示",
            task="继续",
            tool_specs=_specs("note"),
            call_tool=call,
            checkpoints=steps,
            required_steps=("commit",),
            block_message="还没提交",
        )
    assert caught.value.consecutive == 3
    assert script.calls == 5


def test_stream_idle_stays_inside_the_loop_until_limit():
    role = RoleModel(
        primary=ModelRef(provider="primary", model="main"),
        fallbacks=[ModelRef(provider="backup", model="spare")],
    )

    class Transport:
        def __init__(self, replies: list) -> None:
            self.replies = list(replies)
            self.models: list[str] = []

        def complete(self, model: ModelRef, messages: list[dict], tools: list[dict]) -> Completion:
            self.models.append(model.model)
            item = self.replies.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    recovered = Transport([ProviderError("空闲", kind="stream_idle")] * 6 + [Completion(content="好")])
    client = RoleClient(role, recovered, sleep=lambda _: None)
    result = run_agent(
        client,
        system_prompt="短提示",
        task="说一句",
        tool_specs=[],
        call_tool=lambda name, args: {},
        checkpoints=_Steps(),
        required_steps=(),
    )
    assert result.stop_reason == "stop"
    assert recovered.models == ["main"] * 7

    exhausted = Transport([ProviderError("空闲", kind="stream_idle")] * 7)
    client = RoleClient(role, exhausted, sleep=lambda _: None)
    with pytest.raises(AgentLoopError, match="流空闲"):
        run_agent(
            client,
            system_prompt="短提示",
            task="说一句",
            tool_specs=[],
            call_tool=lambda name, args: {},
            checkpoints=_Steps(),
            required_steps=(),
        )
    assert exhausted.models == ["main"] * 7


def test_max_turns_ends_the_loop():
    script = _Script([_call("echo", {}, "1")] * 4)

    def call(name: str, args: dict) -> dict:
        return {"ok": True}

    with pytest.raises(AgentLoopError, match="超过 2 轮"):
        run_agent(
            script,
            system_prompt="短提示",
            task="重复",
            tool_specs=_specs("echo"),
            call_tool=call,
            checkpoints=_Steps(),
            max_turns=2,
        )
    assert script.calls == 2
