"""把流式分片收成一次补全，并在分片之间检测空闲。"""

import threading
from collections.abc import Iterator
from typing import Any

from ainovel.llm.errors import ProviderError
from ainovel.llm.types import Completion, ToolCall


def read_until_idle(source: Iterator[Any], idle_timeout: float | None, on_chunk=None) -> list[Any]:
    """idle_timeout 为空时原样读完。超时则抛出 kind=stream_idle，调用方决定是否重试。

    on_chunk 在每个分片到达时调用，不等整段收完。
    """
    if idle_timeout is None or idle_timeout <= 0:
        chunks = []
        for chunk in source:
            chunks.append(chunk)
            if on_chunk is not None:
                on_chunk(chunk)
        return chunks
    chunks: list[Any] = []
    while True:
        try:
            chunk = _next_within(source, idle_timeout)
        except StopIteration:
            return chunks
        chunks.append(chunk)
        if on_chunk is not None:
            on_chunk(chunk)


def aggregate_chunks(chunks: list[Any], on_delta=None) -> Completion:
    content: list[str] = []
    reasoning: list[str] = []
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
                thought = _thought(message)
                if thought:
                    reasoning.append(thought)
                _absorb_calls(calls, _get(message, "tool_calls"))
            continue
        text = _get(delta, "content")
        if text:
            content.append(str(text))
            if on_delta is not None:
                on_delta(str(text))
        thought = _thought(delta)
        if thought:
            reasoning.append(thought)
        _absorb_calls(calls, _get(delta, "tool_calls"))
    tool_calls = [
        ToolCall(id=item["id"], name=item["name"], arguments=item["arguments"])
        for _, item in sorted(calls.items())
        if item["name"]
    ]
    return Completion(
        content="".join(content),
        reasoning="".join(reasoning),
        tool_calls=tool_calls,
        stop_reason=stop_reason,
    )


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


def _thought(obj: Any) -> str:
    for key in ("reasoning_content", "reasoning"):
        text = _get(obj, key)
        if text:
            return str(text)
    return ""


_ARTICLE_FIELDS = {
    "draft_chapter": {"content"},
    "edit_chapter": {"content"},
    "save_book": {"synopsis"},
    "save_foundation": {"content"},
}


class ArticleTap:
    """章节和设定工具的参数是 JSON。正文到一段就送一段，不等工具调用结束。"""

    def __init__(self, on_text, on_begin=None, *, fields=None) -> None:
        self._on_text = on_text
        self._on_begin = on_begin
        self._readers: dict[int, ContentStrings] = {}
        self._begun = False
        self._fields = fields or _ARTICLE_FIELDS

    def feed(self, chunk: Any) -> None:
        message = _delta_or_message(chunk)
        if message is None:
            return
        raw = _get(message, "tool_calls")
        if not raw:
            return
        for index, item in enumerate(raw):
            slot = _get(item, "index")
            key = int(slot) if isinstance(slot, int) else index
            function = _get(item, "function")
            if function is None:
                continue
            name = _get(function, "name")
            tool_name = str(name or "")
            if tool_name and key not in self._readers and tool_name in self._fields:
                if not self._begun:
                    self._begun = True
                    if self._on_begin is not None:
                        self._on_begin()
                self._readers[key] = ContentStrings(content_only=True, fields=self._fields[tool_name])
            arguments = _get(function, "arguments")
            reader = self._readers.get(key)
            if reader is not None and arguments:
                text = reader.feed(str(arguments))
                if text:
                    self._on_text(text)


class ProseTap:
    """没有工具的回答。纯文本直接送出；如果是 JSON，只送里面的字符串。"""

    def __init__(self, on_text, on_begin=None) -> None:
        self._on_text = on_text
        self._on_begin = on_begin
        self._mode = ""
        self._json = ContentStrings(content_only=False)
        self._begun = False

    def feed(self, chunk: Any) -> None:
        message = _delta_or_message(chunk)
        if message is None:
            return
        text = _get(message, "content")
        if not text:
            return
        text = str(text)
        if not self._mode:
            stripped = text.lstrip()
            if not stripped:
                return
            if stripped[0] in "{[":
                self._mode = "json"
                text = stripped
            else:
                self._mode = "raw"
        if self._mode == "json":
            text = self._json.feed(text)
        self._send(text)

    def _send(self, text: str) -> None:
        if not text:
            return
        if not self._begun:
            self._begun = True
            if self._on_begin is not None:
                self._on_begin()
        self._on_text(text)


class ContentStrings:
    """从流式 JSON 里抽出字符串值。content_only 时只留 content 以及它里面的字符串。"""

    def __init__(self, *, content_only: bool, fields: set[str] | None = None) -> None:
        self.content_only = content_only
        self.fields = fields or {"content"}
        self._frames: list[tuple[str, str]] = [("array", "")]
        self._expect = "value"
        self._in_string = False
        self._escape = False
        self._unicode = None
        self._building_key = False
        self._key = ""
        self._emit = False
        self._gap = False
        self._out: list[str] = []

    def feed(self, text: str) -> str:
        self._out = []
        for char in text:
            self._take(char)
        return "".join(self._out)

    def _under_content(self) -> bool:
        if not self.content_only:
            return True
        if self._key in self.fields:
            return True
        return any(key in self.fields for _, key in self._frames)

    def _take(self, char: str) -> None:
        if self._in_string:
            self._inside(char)
            return
        if char.isspace():
            return
        if char == '"':
            self._in_string = True
            self._building_key = self._expect == "key"
            self._emit = (not self._building_key) and self._under_content()
            if self._building_key:
                self._key = ""
            elif self._emit and self._gap:
                self._out.append("\n")
                self._gap = False
            return
        if char == "{":
            owner = self._key if self._expect == "value" else ""
            self._frames.append(("object", owner))
            self._expect = "key"
            self._key = ""
            return
        if char == "[":
            owner = self._key if self._expect == "value" else ""
            self._frames.append(("array", owner))
            self._expect = "value"
            self._key = ""
            return
        if char in "}]":
            if len(self._frames) > 1:
                self._frames.pop()
            self._key = ""
            self._expect = "comma"
            return
        if char == ":":
            self._expect = "value"
            return
        if char == ",":
            kind, _ = self._frames[-1]
            self._expect = "key" if kind == "object" else "value"
            return
        self._expect = "comma"

    def _inside(self, char: str) -> None:
        if self._unicode is not None:
            self._unicode += char
            if len(self._unicode) == 4:
                try:
                    decoded = chr(int(self._unicode, 16))
                except ValueError:
                    decoded = ""
                self._unicode = None
                if decoded:
                    self._emit_char(decoded)
            return
        if self._escape:
            self._escape = False
            if char == "u":
                self._unicode = ""
                return
            self._emit_char({"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\", "/": "/"}.get(char, char))
            return
        if char == "\\":
            self._escape = True
            return
        if char == '"':
            self._in_string = False
            if self._emit:
                self._gap = True
            self._expect = "colon" if self._building_key else "comma"
            return
        if self._building_key:
            self._key += char
            return
        self._emit_char(char)

    def _emit_char(self, char: str) -> None:
        if self._emit:
            self._out.append(char)


def _delta_or_message(chunk: Any) -> Any:
    choice = _first_choice(chunk)
    if choice is None:
        return None
    delta = _get(choice, "delta")
    if delta is not None:
        return delta
    return _get(choice, "message")


def _get(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
