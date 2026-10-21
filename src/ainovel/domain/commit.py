"""在途章节提交。恢复时只认这份冻结意图。"""

from typing import Any

from pydantic import BaseModel, ConfigDict

class CommitStage:
    STARTED = "started"
    STATE_APPLIED = "state_applied"
    PROGRESS_MARKED = "progress_marked"
    SIGNAL_SAVED = "signal_saved"


_STAGE_ORDER = (
    CommitStage.STARTED,
    CommitStage.STATE_APPLIED,
    CommitStage.PROGRESS_MARKED,
    CommitStage.SIGNAL_SAVED,
)


class PendingCommitConflict(ValueError):
    """在途提交与本次意图冲突，或阶段非法。"""


class PendingCommit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chapter: int
    stage: str
    rewrite: bool = False
    rewrite_mode: str = ""
    payload: Any = None
    draft_content: str = ""
    output: Any = None
    summary: str = ""
    hook_type: str = ""
    dominant_strand: str = ""
    result: Any = None
    started_at: str = ""
    updated_at: str = ""

    def to_disk(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chapter": self.chapter,
            "stage": self.stage,
        }
        if self.rewrite:
            payload["rewrite"] = True
        if self.rewrite_mode:
            payload["rewrite_mode"] = self.rewrite_mode
        if self.payload is not None:
            payload["payload"] = self.payload
        if self.draft_content:
            payload["draft_content"] = self.draft_content
        if self.output is not None:
            payload["output"] = self.output
        if self.summary:
            payload["summary"] = self.summary
        if self.hook_type:
            payload["hook_type"] = self.hook_type
        if self.dominant_strand:
            payload["dominant_strand"] = self.dominant_strand
        if self.result is not None:
            payload["result"] = self.result
        if self.started_at:
            payload["started_at"] = self.started_at
        if self.updated_at:
            payload["updated_at"] = self.updated_at
        return payload


def prepare_pending_commit(
    existing: PendingCommit | None,
    incoming: PendingCommit,
) -> PendingCommit:
    """同一时刻只有一个在途提交，阶段只允许向前。"""
    if incoming.stage not in _STAGE_ORDER:
        raise PendingCommitConflict(f"pending commit 阶段非法: {incoming.stage!r}")
    if incoming.chapter <= 0:
        raise PendingCommitConflict("chapter 必须大于 0")
    if existing is None:
        return incoming
    if existing.stage not in _STAGE_ORDER:
        raise PendingCommitConflict(f"pending commit 阶段非法: {existing.stage!r}")
    if existing.chapter != incoming.chapter:
        raise PendingCommitConflict(
            f"存在未恢复的章节提交：第 {existing.chapter} 章（阶段 {existing.stage}），请先恢复或重新提交该章"
        )
    if _STAGE_ORDER.index(incoming.stage) < _STAGE_ORDER.index(existing.stage):
        raise PendingCommitConflict(
            f"pending commit 阶段不能回退: {existing.stage} -> {incoming.stage}"
        )
    return incoming
