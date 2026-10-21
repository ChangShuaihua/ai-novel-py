"""上下文窗口策略。只由章节规模推导，不落盘。"""

from pydantic import BaseModel, ConfigDict

from ainovel.domain.progress import Progress
from ainovel.domain.transitions import FlowState


class ContextProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary_window: int
    timeline_window: int
    layered: bool = False


class MemoryPolicy(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: str = ""
    summary_window: int = 0
    timeline_window: int = 0
    layered_summaries: bool = False
    summary_strategy: str = ""
    working_refresh: str = ""
    episodic_refresh: str = ""
    planning_refresh: str = ""
    foundation_refresh: str = ""
    planning_focus: str = ""
    foundation_focus: str = ""
    previous_tail_chars: int = 0
    chapter_plan_enabled: bool = False
    related_chapter_lookup: bool = False
    current_outline_bound: bool = False
    handoff_preferred: bool = False
    read_only_threshold: int = 0


def context_profile(total_chapters: int) -> ContextProfile:
    if total_chapters <= 15:
        return ContextProfile(summary_window=10, timeline_window=10)
    if total_chapters <= 50:
        return ContextProfile(summary_window=5, timeline_window=8)
    return ContextProfile(summary_window=3, timeline_window=5, layered=True)


def chapter_memory_policy(
    progress: Progress | None,
    profile: ContextProfile,
    *,
    current_outline_bound: bool,
) -> MemoryPolicy:
    policy = MemoryPolicy(
        mode="chapter",
        summary_window=profile.summary_window,
        timeline_window=profile.timeline_window,
        layered_summaries=profile.layered,
        summary_strategy="卷摘要+弧摘要+最近章节摘要" if profile.layered else "最近章节摘要",
        working_refresh="每次按章节加载时刷新",
        episodic_refresh="随章节提交、评审和长篇状态变更刷新",
        previous_tail_chars=800,
        chapter_plan_enabled=True,
        current_outline_bound=current_outline_bound,
        read_only_threshold=5,
    )
    if progress is None:
        return policy
    if progress.total_chapters > 30:
        policy.related_chapter_lookup = True
    if progress.flow in (FlowState.REVIEWING, FlowState.REWRITING, FlowState.POLISHING):
        policy.handoff_preferred = True
    completed = len(progress.completed_chapters)
    if progress.layered and completed >= 6:
        policy.handoff_preferred = True
        policy.read_only_threshold = 4
    if completed >= 12:
        policy.handoff_preferred = True
        policy.read_only_threshold = 4
    return policy


def architect_memory_policy() -> MemoryPolicy:
    return MemoryPolicy(
        mode="architect",
        planning_refresh="卷弧结构、指南针或摘要更新时刷新",
        foundation_refresh="角色、伏笔、设定变更时刷新",
        planning_focus="分层大纲、指南针、卷摘要",
        foundation_focus="角色设定、角色快照、伏笔台账",
        handoff_preferred=True,
        chapter_plan_enabled=False,
        read_only_threshold=4,
    )
