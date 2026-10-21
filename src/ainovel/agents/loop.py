"""薄代理循环：派发工具、按配置停、用检查点判断能不能结束。

这里不出现小说角色、路由或具体工具名。停哪些工具、要求哪个检查点步骤，由调用方传入。
"""

import json
from collections.abc import Callable
from dataclasses import dataclass

from ainovel.agents.guard import CheckpointGuard
from ainovel.llm.errors import ProviderError
from ainovel.llm.types import Completion, ToolSpec
from ainovel.tools.errors import ToolArgsError, ToolConflict

_HARD_STOP = {"safety", "content_filter"}


class AgentLoopError(RuntimeError):
    def __init__(self, message: str, *, messages: list[dict] | None = None) -> None:
        super().__init__(message)
        self.messages = messages or []


class CheckpointGuardError(AgentLoopError):
    def __init__(self, message: str, *, consecutive: int, messages: list[dict] | None = None) -> None:
        super().__init__(message, messages=messages)
        self.consecutive = consecutive


@dataclass
class AgentResult:
    messages: list[dict]
    stop_tool: str = ""
    stop_reason: str = ""


def run_agent(
    completer,
    *,
    system_prompt: str,
    task: str,
    tool_specs: list[ToolSpec],
    call_tool: Callable[[str, dict], dict],
    checkpoints,
    stop_after: tuple[str, ...] = (),
    required_steps: tuple[str, ...] = (),
    block_message: str = "本轮还没有要求的检查点，不能结束。",
    max_turns: int = 32,
    max_consecutive_blocks: int = 3,
    max_stream_idle: int = 7,
) -> AgentResult:
    allowed = {spec.name for spec in tool_specs}
    tools = [spec.to_openai() for spec in sorted(tool_specs, key=lambda spec: spec.name)]
    guard = CheckpointGuard(
        checkpoints,
        required_steps,
        block_message,
        max_consecutive=max_consecutive_blocks,
    )
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task},
    ]
    idle_count = 0
    turns = 0
    while turns < max_turns:
        try:
            completion = completer.complete(messages, tools)
        except ProviderError as exc:
            if exc.kind != "stream_idle":
                raise
            idle_count += 1
            if idle_count >= max_stream_idle:
                raise AgentLoopError(f"流空闲已达 {max_stream_idle} 次", messages=messages) from exc
            continue
        idle_count = 0
        turns += 1
        if completion.stop_reason in _HARD_STOP:
            messages.append(_assistant(completion))
            raise AgentLoopError(f"模型拒绝继续: {completion.stop_reason}", messages=messages)
        messages.append(_assistant(completion))
        stop_tool = ""
        if completion.tool_calls:
            stop_tool = _run_tools(completion, allowed, call_tool, messages, stop_after)
            if not stop_tool:
                continue
        try:
            _finish_or_continue(guard, messages)
        except _Continue:
            continue
        if stop_tool:
            return AgentResult(messages=messages, stop_tool=stop_tool, stop_reason="tool")
        return AgentResult(messages=messages, stop_reason=completion.stop_reason or "stop")
    raise AgentLoopError(f"超过 {max_turns} 轮仍未结束", messages=messages)


def _finish_or_continue(guard: CheckpointGuard, messages: list[dict]) -> None:
    decision = guard.allow_stop()
    if decision.allow:
        return
    if decision.escalate:
        raise CheckpointGuardError(decision.message, consecutive=decision.consecutive, messages=messages)
    messages.append({"role": "user", "content": decision.message})
    raise _Continue()


def _run_tools(completion: Completion, allowed: set[str], call_tool, messages: list[dict], stop_after: tuple[str, ...]) -> str:
    stop_tool = ""
    for call in completion.tool_calls:
        if call.name not in allowed:
            payload = {"error": f"工具不在本轮允许列表: {call.name}"}
            ok = False
        else:
            payload, ok = _invoke(call_tool, call.name, call.arguments)
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(payload, ensure_ascii=False),
            }
        )
        if ok and call.name in stop_after:
            stop_tool = call.name
    return stop_tool


def _invoke(call_tool, name: str, arguments: str) -> tuple[dict, bool]:
    try:
        args = _parse_args(arguments)
        result = call_tool(name, args)
    except (ToolArgsError, ToolConflict, json.JSONDecodeError) as exc:
        return {"error": str(exc)}, False
    if not isinstance(result, dict):
        return {"error": "工具必须返回对象"}, False
    return result, True


def _parse_args(arguments: str) -> dict:
    if not arguments:
        return {}
    parsed = json.loads(arguments)
    if not isinstance(parsed, dict):
        raise ToolArgsError("工具参数必须是对象")
    return parsed


def _assistant(completion: Completion) -> dict:
    message: dict = {"role": "assistant", "content": completion.content}
    if completion.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in completion.tool_calls
        ]
    return message


class _Continue(Exception):
    """护栏拒绝结束，回到循环再问一次模型。"""
