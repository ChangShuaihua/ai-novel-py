"""本轮开始之后必须出现指定检查点，否则拒绝结束。"""

from dataclasses import dataclass


@dataclass
class GuardDecision:
    allow: bool
    message: str = ""
    escalate: bool = False
    consecutive: int = 0


class CheckpointGuard:
    """以运行开始时的检查点序号为界。有新检查点就重置连续拦截。"""

    def __init__(self, checkpoints, required_steps: tuple[str, ...], message: str, *, max_consecutive: int = 3) -> None:
        rows = list(checkpoints.all())
        self._checkpoints = checkpoints
        self.baseline = max((row.seq for row in rows), default=0)
        self.required = set(required_steps)
        self.message = message
        self.max_consecutive = max_consecutive
        self.consecutive = 0
        self._last_block_seq: int | None = None

    def allow_stop(self) -> GuardDecision:
        if not self.required:
            self.consecutive = 0
            return GuardDecision(allow=True)
        seen: set[str] = set()
        latest = self.baseline
        for row in self._checkpoints.all():
            if row.seq <= self.baseline:
                continue
            if row.seq > latest:
                latest = row.seq
            seen.add(row.step)
        if self.required & seen:
            self.consecutive = 0
            return GuardDecision(allow=True)
        if self._last_block_seq is not None and latest > self._last_block_seq:
            self.consecutive = 0
        self._last_block_seq = latest
        self.consecutive += 1
        if self.consecutive >= self.max_consecutive:
            return GuardDecision(
                allow=False,
                escalate=True,
                message=self.message,
                consecutive=self.consecutive,
            )
        return GuardDecision(allow=False, message=self.message, consecutive=self.consecutive)
