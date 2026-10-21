"""LiteLLM 流式适配。业务代码不直接调用 LiteLLM。"""

from collections.abc import Callable, Iterator
from typing import Any

from ainovel.llm.classify import classify_exception
from ainovel.llm.errors import ProviderError
from ainovel.llm.stream import aggregate_chunks, read_until_idle
from ainovel.llm.types import Completion, ModelRef


class LiteLLMTransport:
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

    def complete(self, model: ModelRef, messages: list[dict], tools: list[dict]) -> Completion:
        kwargs: dict[str, Any] = {
            "model": model.litellm_model(),
            "messages": messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
        if model.api_key:
            kwargs["api_key"] = model.api_key
        if model.api_base:
            kwargs["api_base"] = model.api_base
        try:
            raw = self._call(kwargs)
            chunks = read_until_idle(_iter_response(raw), self.idle_timeout)
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


def _iter_response(raw: Any) -> Iterator[Any]:
    if raw is None:
        return
    if isinstance(raw, (str, bytes, dict)):
        yield raw
        return
    yield from raw
