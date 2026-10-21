"""路由用的事实和指令。Route 只读这些对象。"""

from dataclasses import dataclass, field

from ainovel.domain.progress import Progress

REVIEW_INTERVAL = 5


@dataclass(frozen=True)
class Instruction:
    agent: str
    task: str
    reason: str
    chapter: int = 0


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


def should_review(completed_count: int) -> tuple[bool, str]:
    if completed_count > 0 and completed_count % REVIEW_INTERVAL == 0:
        return True, f"已完成 {completed_count} 章，触发全局审阅"
    return False, ""
