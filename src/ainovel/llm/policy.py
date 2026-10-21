"""角色模型的重试和备用提供方。代理循环看不到可重试错误。"""

import time
from collections.abc import Callable

from ainovel.llm.errors import ProviderError
from ainovel.llm.types import Completion, ModelRef, RoleModel

_SAME_PROVIDER = {"timeout", "stream_interrupted"}
_FAILOVER = {"rate_limit", "unavailable"}
_TERMINAL = {"auth", "model_not_found", "unknown", "stream_idle"}


class Transport:
    def complete(self, model: ModelRef, messages: list[dict], tools: list[dict]) -> Completion:
        raise NotImplementedError


class RoleClient:
    """对一个角色：超时在当前提供方重试，429/503 切到下一个备用。"""

    def __init__(
        self,
        role: RoleModel,
        transport: Transport,
        *,
        max_attempts: int = 3,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.role = role
        self.transport = transport
        self.max_attempts = max_attempts
        self.sleep = sleep if sleep is not None else time.sleep

    def complete(self, messages: list[dict], tools: list[dict]) -> Completion:
        models = [self.role.primary, *self.role.fallbacks]
        index = 0
        attempt = 1
        while True:
            model = models[index]
            try:
                return self.transport.complete(model, messages, tools)
            except ProviderError as exc:
                if exc.kind in _TERMINAL or exc.kind not in _SAME_PROVIDER | _FAILOVER:
                    raise
                if exc.kind in _FAILOVER:
                    if index + 1 >= len(models):
                        raise
                    index += 1
                    attempt = 1
                    continue
                if attempt >= self.max_attempts:
                    raise
                delay = exc.retry_after if exc.retry_after and exc.retry_after > 0 else 0.5 * (2 ** (attempt - 1))
                attempt += 1
                self.sleep(delay)
