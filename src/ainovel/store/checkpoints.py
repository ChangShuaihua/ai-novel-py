"""检查点只追加。相同范围、步骤和摘要不产生新行。"""

import json
from datetime import datetime, timezone

from ainovel.domain.checkpoint import Checkpoint, Scope
from ainovel.store.io import IO


class CheckpointLoadError(ValueError):
    """jsonl 损坏。禁止把它当成没有检查点。"""


class CheckpointStore:
    def __init__(self, io: IO) -> None:
        self._io = io
        self._cache: list[Checkpoint] = []
        self._seq = 0
        self._load_error: CheckpointLoadError | None = None
        self._load()

    def _load(self) -> None:
        path = self._io.path("meta/checkpoints.jsonl")
        if not path.exists():
            return
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            self._load_error = CheckpointLoadError(f"读取 meta/checkpoints.jsonl 失败: {exc}")
            return
        rows: list[Checkpoint] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(Checkpoint.from_disk(json.loads(line)))
            except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
                self._load_error = CheckpointLoadError(
                    f"parse meta/checkpoints.jsonl line {line_no}: {exc}"
                )
                return
        self._cache = rows
        self._seq = max((row.seq for row in rows), default=0)

    def load_error(self) -> CheckpointLoadError | None:
        return self._load_error

    def append(self, scope: Scope, step: str, artifact: str = "", digest: str = "") -> Checkpoint:
        with self._io.exclusive():
            if self._load_error is not None:
                raise self._load_error
            if digest:
                for existing in reversed(self._cache):
                    if existing.scope.matches(scope) and existing.step == step and existing.digest == digest:
                        return existing
            seq = self._seq + 1
            checkpoint = Checkpoint(
                seq=seq,
                scope=scope,
                step=step,
                artifact=artifact,
                digest=digest,
                occurred_at=datetime.now(timezone.utc),
            )
            line = json.dumps(checkpoint.to_disk(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._io.append_line_unlocked("meta/checkpoints.jsonl", line + b"\n")
            self._seq = seq
            self._cache.append(checkpoint)
            return checkpoint

    def latest(self, scope: Scope) -> Checkpoint | None:
        for existing in reversed(self._cache):
            if existing.scope.matches(scope):
                return existing
        return None

    def all(self) -> list[Checkpoint]:
        return list(self._cache)

    def reset(self) -> None:
        with self._io.exclusive():
            self._io.remove_unlocked("meta/checkpoints.jsonl")
            self._cache = []
            self._seq = 0
            self._load_error = None
