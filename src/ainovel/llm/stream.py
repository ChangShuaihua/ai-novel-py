"""把流式分片收成一次补全，并在分片之间检测空闲。"""

import threading
from collections.abc import Iterator
from typing import Any

from ainovel.llm.errors import ProviderError
from ainovel.llm.types import Completion, ToolCall


def read_until_idle(source: Iterator[Any], idle_timeout: float | None) -> list[Any]:
    """idle_timeout 为空时原样读完。超时则抛出 kind=stream_idle，调用方决定是否重试。"""
    if idle_timeout is None or idle_timeout <= 0:
        return list(source)
    chunks: list[Any] = []
    while True:
        try:
            chunk = _next_within(source, idle_timeout)
        except StopIteration:
            return chunks
        chunks.append(chunk)


def aggregate_chunks(chunks: list[Any], on_delta=None) -> Completion:
    content: list[str] = []
    calls: dict[int, dict[str, str]] = {}
    stop_reason = ""
    for chunk in chunks:
        choice = _first_choice(chunk)
        if choice is None:
            continue
        reason = _get(choice, "finish_reason")
        if reason:
            stop_reason = str(reason)
        delta = _get(choice, "delta")
        if delta is None:
            message = _get(choice, "message")
            if message is not None:
                text = _get(message, "content")
                if text:
                    content.append(str(text))
                _absorb_calls(calls, _get(message, "tool_calls"))
            continue
        text = _get(delta, "content")
        if text:
            content.append(str(text))
            if on_delta is not None:
                on_delta(str(text))
        _absorb_calls(calls, _get(delta, "tool_calls"))
    tool_calls = [
        ToolCall(id=item["id"], name=item["name"], arguments=item["arguments"])
        for _, item in sorted(calls.items())
        if item["name"]
    ]
    return Completion(content="".join(content), tool_calls=tool_calls, stop_reason=stop_reason)


def _next_within(source: Iterator[Any], timeout: float) -> Any:
    outcome: dict[str, Any] = {}

    def pull() -> None:
        try:
            outcome["value"] = next(source)
        except StopIteration:
            outcome["stop"] = True
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=pull, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise ProviderError("流空闲过久", kind="stream_idle")
    if "error" in outcome:
        raise outcome["error"]
    if outcome.get("stop"):
        raise StopIteration
    return outcome.get("value")


def _first_choice(chunk: Any) -> Any:
    choices = _get(chunk, "choices")
    if not choices:
        return None
    return choices[0]


def _absorb_calls(calls: dict[int, dict[str, str]], raw: Any) -> None:
    if not raw:
        return
    for index, item in enumerate(raw):
        slot = _get(item, "index")
        key = int(slot) if isinstance(slot, int) else index
        current = calls.setdefault(key, {"id": "", "name": "", "arguments": ""})
        call_id = _get(item, "id")
        if call_id:
            current["id"] = str(call_id)
        function = _get(item, "function")
        if function is None:
            continue
        name = _get(function, "name")
        if name:
            current["name"] = str(name)
        arguments = _get(function, "arguments")
        if arguments:
            current["arguments"] += str(arguments)


def _get(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
