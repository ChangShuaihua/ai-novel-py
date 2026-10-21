"""检查点。恢复和“这一步已经做完”的唯一证据。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ainovel.domain.json_time import dump_time, parse_time


class ScopeKind:
    CHAPTER = "chapter"
    ARC = "arc"
    VOLUME = "volume"
    GLOBAL = "global"


class Scope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: str
    chapter: int = 0
    volume: int = 0
    arc: int = 0

    def matches(self, other: "Scope") -> bool:
        if self.kind != other.kind:
            return False
        if self.kind == ScopeKind.CHAPTER:
            return self.chapter == other.chapter
        if self.kind == ScopeKind.ARC:
            return self.volume == other.volume and self.arc == other.arc
        if self.kind == ScopeKind.VOLUME:
            return self.volume == other.volume
        return self.kind == ScopeKind.GLOBAL

    def to_disk(self) -> dict[str, object]:
        payload: dict[str, object] = {"kind": self.kind}
        if self.kind == ScopeKind.CHAPTER and self.chapter:
            payload["chapter"] = self.chapter
        elif self.kind == ScopeKind.ARC:
            if self.volume:
                payload["volume"] = self.volume
            if self.arc:
                payload["arc"] = self.arc
        elif self.kind == ScopeKind.VOLUME and self.volume:
            payload["volume"] = self.volume
        return payload


def chapter_scope(chapter: int) -> Scope:
    return Scope(kind=ScopeKind.CHAPTER, chapter=chapter)


def arc_scope(volume: int, arc: int) -> Scope:
    return Scope(kind=ScopeKind.ARC, volume=volume, arc=arc)


def volume_scope(volume: int) -> Scope:
    return Scope(kind=ScopeKind.VOLUME, volume=volume)


def global_scope() -> Scope:
    return Scope(kind=ScopeKind.GLOBAL)


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    seq: int
    scope: Scope
    step: str
    artifact: str = ""
    digest: str = ""
    occurred_at: datetime = Field(default_factory=datetime.now)

    def to_disk(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "seq": self.seq,
            "scope": self.scope.to_disk(),
            "step": self.step,
            "occurred_at": dump_time(self.occurred_at),
        }
        if self.artifact:
            payload["artifact"] = self.artifact
        if self.digest:
            payload["digest"] = self.digest
        return payload

    @classmethod
    def from_disk(cls, raw: object) -> "Checkpoint":
        if not isinstance(raw, dict):
            raise TypeError("checkpoint 必须是对象")
        scope_raw = raw.get("scope")
        if not isinstance(scope_raw, dict):
            raise TypeError("checkpoint.scope 必须是对象")
        occurred = raw.get("occurred_at")
        return cls(
            seq=int(raw["seq"]),
            scope=Scope.model_validate(scope_raw),
            step=str(raw["step"]),
            artifact=str(raw.get("artifact") or ""),
            digest=str(raw.get("digest") or ""),
            occurred_at=parse_time(str(occurred)) if occurred else datetime.now().astimezone(),
        )
