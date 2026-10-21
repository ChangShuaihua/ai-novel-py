"""运行意图。未知推进模式可以读，不能进入可写存储。"""

from pydantic import BaseModel, ConfigDict, field_validator

from ainovel.domain.errors import UnsupportedAdvanceModeError


class PlanningTier:
    SHORT = "short"
    MID = "mid"
    LONG = "long"


class ChapterAdvanceMode:
    AUTO = "auto"
    REVIEW = "review"


class AdvanceHoldAfter:
    BOUNDARY = "boundary"
    REWRITES_DRAINED = "rewrites_drained"
    CHAPTER = "chapter"


def planner_for_tier(tier: str) -> str:
    """空级别还不能查表。short 用短篇规划师，其余用长篇规划师。"""
    if not tier:
        raise ValueError("规划级别尚未落盘，不能决定规划师")
    if tier == PlanningTier.SHORT:
        return "architect_short"
    if tier in (PlanningTier.MID, PlanningTier.LONG):
        return "architect_long"
    raise ValueError(f"未知规划级别: {tier!r}")


class AdvanceHold(BaseModel):
    model_config = ConfigDict(extra="ignore")

    after: str
    target_chapter: int = 0
    reason: str

    def validate_shape(self) -> None:
        if self.after not in (
            AdvanceHoldAfter.BOUNDARY,
            AdvanceHoldAfter.REWRITES_DRAINED,
            AdvanceHoldAfter.CHAPTER,
        ):
            raise ValueError(f"不支持的一次性暂停条件 {self.after!r}")
        if self.after == AdvanceHoldAfter.CHAPTER:
            if self.target_chapter <= 0:
                raise ValueError("目标章节必须大于 0")
        elif self.target_chapter != 0:
            raise ValueError(f"暂停条件 {self.after!r} 不能设置目标章节")
        if not self.reason.strip():
            raise ValueError("一次性暂停原因不能为空")

    def to_disk(self) -> dict[str, object]:
        payload: dict[str, object] = {"after": self.after, "reason": self.reason}
        if self.target_chapter:
            payload["target_chapter"] = self.target_chapter
        return payload


class PlanStartRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    raw_prompt: str
    planner: str
    planner_task: str
    decision_id: str = ""

    def to_disk(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "raw_prompt": self.raw_prompt,
            "planner": self.planner,
            "planner_task": self.planner_task,
        }
        if self.decision_id:
            payload["decision_id"] = self.decision_id
        return payload


class RunMeta(BaseModel):
    """advance_mode 保持原始字符串，这样只读打开仍能看见未知值。"""

    model_config = ConfigDict(extra="ignore")

    started_at: str = ""
    provider: str = ""
    style: str = ""
    model: str = ""
    planning_tier: str = ""
    start_prompt: str = ""
    plan_start: PlanStartRecord | None = None
    pending_steer: str = ""
    advance_mode: str = ""
    advance_permit_chapter: int = 0
    advance_hold: AdvanceHold | None = None

    @field_validator("plan_start", "advance_hold", mode="before")
    @classmethod
    def _null_object(cls, value: object) -> object:
        if value in (None, {}):
            return None
        return value

    def to_disk(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "started_at": self.started_at,
            "style": self.style,
            "model": self.model,
            "advance_mode": self.advance_mode,
        }
        if self.provider:
            payload["provider"] = self.provider
        if self.planning_tier:
            payload["planning_tier"] = self.planning_tier
        if self.start_prompt:
            payload["start_prompt"] = self.start_prompt
        if self.plan_start is not None:
            payload["plan_start"] = self.plan_start.to_disk()
        if self.pending_steer:
            payload["pending_steer"] = self.pending_steer
        if self.advance_permit_chapter:
            payload["advance_permit_chapter"] = self.advance_permit_chapter
        if self.advance_hold is not None:
            payload["advance_hold"] = self.advance_hold.to_disk()
        return payload


def advance_mode_supported(mode: str) -> bool:
    return mode in (ChapterAdvanceMode.AUTO, ChapterAdvanceMode.REVIEW)


def validate_advance_control(meta: RunMeta) -> None:
    """可写路径上的机械校验。空模式应由调用方先补成 auto。"""
    if not advance_mode_supported(meta.advance_mode):
        raise UnsupportedAdvanceModeError(meta.advance_mode)
    if meta.advance_permit_chapter < 0:
        raise ValueError(f"章节许可不能为负数: {meta.advance_permit_chapter}")
    if meta.advance_mode == ChapterAdvanceMode.AUTO and meta.advance_permit_chapter != 0:
        raise ValueError(f"auto 模式不能保留章节许可: {meta.advance_permit_chapter}")
    if meta.advance_hold is not None:
        meta.advance_hold.validate_shape()
