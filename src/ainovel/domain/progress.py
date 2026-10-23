"""进度事实，落在 meta/progress.json。"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ainovel.domain.transitions import FlowState, Phase


def _blank_list(value: object) -> list[object]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("期望数组")
    return value


def _word_counts(value: object) -> dict[int, int]:
    if not value:
        return {}
    if not isinstance(value, dict):
        raise TypeError("chapter_word_counts 必须是对象")
    return {int(key): int(count) for key, count in value.items()}


class Progress(BaseModel):
    model_config = ConfigDict(extra="ignore")

    phase: Phase = Phase.INIT
    current_chapter: int = 0
    total_chapters: int = 0
    completed_chapters: list[int] = Field(default_factory=list)
    total_word_count: int = 0
    chapter_word_counts: dict[int, int] = Field(default_factory=dict)
    in_progress_chapter: int = 0
    completed_scenes: list[int] = Field(default_factory=list)
    flow: FlowState | None = None
    pending_rewrites: list[int] = Field(default_factory=list)
    rewrite_reason: str = ""
    strand_history: list[str] = Field(default_factory=list)
    hook_history: list[str] = Field(default_factory=list)
    current_volume: int = 0
    current_arc: int = 0
    layered: bool = False
    reopened_from_complete: bool = False
    reopen_count: int = 0

    @field_validator("completed_chapters", "completed_scenes", "pending_rewrites", "strand_history", "hook_history", mode="before")
    @classmethod
    def _none_list(cls, value: object) -> list[object]:
        return _blank_list(value)

    @field_validator("chapter_word_counts", mode="before")
    @classmethod
    def _counts(cls, value: object) -> dict[int, int]:
        return _word_counts(value)

    @field_validator("flow", mode="before")
    @classmethod
    def _blank_flow(cls, value: object) -> object:
        if value in (None, ""):
            return None
        return value

    def latest_completed(self) -> int:
        if not self.completed_chapters:
            return 0
        return max(self.completed_chapters)

    def next_chapter(self) -> int:
        return self.latest_completed() + 1

    def to_disk(self) -> dict[str, object]:
        """空的可选字段不写出。必填字段始终保留。"""
        payload: dict[str, object] = {
            "phase": self.phase.value,
            "current_chapter": self.current_chapter,
            "total_chapters": self.total_chapters,
            "completed_chapters": list(self.completed_chapters),
            "total_word_count": self.total_word_count,
        }
        if self.chapter_word_counts:
            payload["chapter_word_counts"] = {
                str(chapter): count
                for chapter, count in sorted(self.chapter_word_counts.items())
            }
        if self.in_progress_chapter:
            payload["in_progress_chapter"] = self.in_progress_chapter
        if self.completed_scenes:
            payload["completed_scenes"] = list(self.completed_scenes)
        if self.flow is not None:
            payload["flow"] = self.flow.value
        if self.pending_rewrites:
            payload["pending_rewrites"] = list(self.pending_rewrites)
        if self.rewrite_reason:
            payload["rewrite_reason"] = self.rewrite_reason
        if self.strand_history:
            payload["strand_history"] = list(self.strand_history)
        if self.hook_history:
            payload["hook_history"] = list(self.hook_history)
        if self.current_volume:
            payload["current_volume"] = self.current_volume
        if self.current_arc:
            payload["current_arc"] = self.current_arc
        if self.layered:
            payload["layered"] = True
        if self.reopened_from_complete:
            payload["reopened_from_complete"] = True
        if self.reopen_count:
            payload["reopen_count"] = self.reopen_count
        return payload
