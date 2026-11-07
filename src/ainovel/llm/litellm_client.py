"""LiteLLM 流式适配。业务代码不直接调用 LiteLLM。"""

from collections.abc import Callable, Iterator
from typing import Any

from ainovel.llm.classify import classify_exception
from ainovel.llm.errors import ProviderError
from ainovel.llm.stream import ArticleTap, ProseTap, aggregate_chunks, read_until_idle
from ainovel.llm.types import Completion, ModelRef


class LiteLLMTransport:
    streams = True

    def __init__(
        self,
        *,
        completion: Callable[..., Any] | None = None,
        idle_timeout: float | None = 120,
        on_delta: Callable[[str], None] | None = None,
    ) -> None:
        self._completion = completion
        self.idle_timeout = idle_timeout
        self.on_delta = on_delta

    def complete(
        self,
        model: ModelRef,
        messages: list[dict],
        tools: list[dict],
        *,
        max_tokens: int | None = None,
        on_text=None,
        on_begin=None,
        stream_mode: str = "article",
        stream_fields=None,
    ) -> Completion:
        kwargs: dict[str, Any] = {
            "model": model.litellm_model(),
            "messages": messages,
            "stream": True,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools
        if model.api_key:
            kwargs["api_key"] = model.api_key
        if model.api_base:
            kwargs["api_base"] = model.api_base
        try:
            raw = self._call(kwargs)
            tap = _tap(on_text, on_begin, stream_mode, stream_fields)
            chunks = read_until_idle(
                _iter_response(raw),
                self.idle_timeout,
                on_chunk=None if tap is None else tap.feed,
            )
            return aggregate_chunks(chunks, on_delta=self.on_delta)
        except ProviderError:
            raise
        except Exception as exc:
            raise classify_exception(exc) from exc

    def _call(self, kwargs: dict[str, Any]) -> Any:
        if self._completion is not None:
            return self._completion(**kwargs)
        import litellm

        return litellm.completion(**kwargs)


def _tap(on_text, on_begin, stream_mode: str, stream_fields=None):
    if on_text is None:
        return None
    if stream_mode == "prose":
        return ProseTap(on_text, on_begin)
    return ArticleTap(on_text, on_begin, fields=stream_fields)


def _iter_response(raw: Any) -> Iterator[Any]:
    if raw is None:
        return
    if isinstance(raw, (str, bytes, dict)):
        yield raw
        return
    yield from raw
