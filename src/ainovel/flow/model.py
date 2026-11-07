"""路由用的事实和指令。Route 只读这些对象。"""

from dataclasses import dataclass, field

from ainovel.domain.progress import Progress

REVIEW_INTERVAL = 5


class Duty:
    """路由交给代理的职责。自由派单没有职责码，任务正文由裁定写成。"""

    FILL_FOUNDATION = "fill_foundation"
    AUDIT_FOUNDATION = "audit_foundation"
    REWRITE = "rewrite"
    POLISH = "polish"
    OUTLINE_FEEDBACK = "outline_feedback"
    ARC_REVIEW = "arc_review"
    ARC_SUMMARY = "arc_summary"
    VOLUME_SUMMARY = "volume_summary"
    EXPAND_ARC = "expand_arc"
    NEW_VOLUME = "new_volume"
    GLOBAL_REVIEW = "global_review"
    OUTLINE_EXHAUSTED = "outline_exhausted"
    WRITE_CHAPTER = "write_chapter"
    DESIGN_CHARACTERS = "design_characters"


@dataclass(frozen=True)
class Instruction:
    agent: str
    task: str
    reason: str
    chapter: int = 0
    duty: str = ""

    def move_id(self) -> str:
        """菜单项标识。章节类职责带章节号，避免两章返工撞成同一项。"""
        if self.duty and self.chapter:
            return f"{self.duty}:{self.chapter}"
        if self.duty:
            return self.duty
        return self.agent


class AggregateKind:
    ARC_REVIEW = "arc_review"
    ARC_SUMMARY = "arc_summary"
    VOLUME_SUMMARY = "volume_summary"
    GLOBAL_REVIEW = "global_review"


@dataclass(frozen=True)
class AggregateRefresh:
    kind: str
    volume: int = 0
    arc: int = 0
    start_chapter: int = 0
    end_chapter: int = 0


@dataclass(frozen=True)
class ArcBoundary:
    is_arc_end: bool = False
    is_volume_end: bool = False
    volume: int = 0
    arc: int = 0
    start_chapter: int = 0
    end_chapter: int = 0
    next_volume: int = 0
    next_arc: int = 0
    needs_expansion: bool = False
    needs_new_volume: bool = False


@dataclass
class RouteState:
    progress: Progress | None = None
    last_completed: int = 0
    arc_boundary: ArcBoundary | None = None
    has_arc_review: bool = False
    has_arc_summary: bool = False
    has_volume_summary: bool = False
    foundation_missing: list[str] = field(default_factory=list)
    planning_tier: str = ""
    has_global_review: bool = False
    immediate_feedback_count: int = 0
    aggregate_refresh: AggregateRefresh | None = None


def describe_move(instruction: Instruction) -> dict[str, object]:
    """交给主代理的菜单项。代理、职责和章节号由引擎固定。"""
    return {
        "move_id": instruction.move_id(),
        "agent": instruction.agent,
        "duty": instruction.duty,
        "chapter": instruction.chapter,
        "task": instruction.task,
        "reason": instruction.reason,
    }


def should_review(completed_count: int) -> tuple[bool, str]:
    if completed_count > 0 and completed_count % REVIEW_INTERVAL == 0:
        return True, f"已完成 {completed_count} 章，触发全局审阅"
    return False, ""
