"""模型提供方错误。种类决定重试还是换备用。"""


class ProviderError(RuntimeError):
    """一次模型请求失败。

    kind:
    - timeout / stream_interrupted：同一提供方就近重试
    - rate_limit / unavailable：429 / 503，交给备用提供方
    - stream_idle：流空闲，由代理循环处理，适配层不重试
    - auth / model_not_found：立刻上抛
    - unknown：立刻上抛
    """

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after
