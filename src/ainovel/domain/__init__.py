"""领域数据与迁移规则。本包不做文件读写。"""

from ainovel.domain.book import BookMetadata
from ainovel.domain.checkpoint import (
    Checkpoint,
    Scope,
    ScopeKind,
    arc_scope,
    chapter_scope,
    global_scope,
    volume_scope,
)
from ainovel.domain.commit import (
    CommitStage,
    PendingCommit,
    PendingCommitConflict,
    prepare_pending_commit,
)
from ainovel.domain.context import (
    ContextProfile,
    MemoryPolicy,
    architect_memory_policy,
    chapter_memory_policy,
    context_profile,
)
from ainovel.domain.errors import (
    FlowTransitionError,
    PhaseTransitionError,
    UnsupportedAdvanceModeError,
)
from ainovel.domain.progress import Progress
from ainovel.domain.run_meta import (
    AdvanceHold,
    AdvanceHoldAfter,
    ChapterAdvanceMode,
    PlanStartRecord,
    PlanningTier,
    RunMeta,
    planner_for_tier,
    validate_advance_control,
)
from ainovel.domain.transitions import (
    FlowState,
    Phase,
    can_transition_flow,
    can_transition_phase,
    validate_flow_transition,
    validate_phase_transition,
)

__all__ = [
    "AdvanceHold",
    "AdvanceHoldAfter",
    "BookMetadata",
    "ChapterAdvanceMode",
    "Checkpoint",
    "CommitStage",
    "ContextProfile",
    "FlowState",
    "FlowTransitionError",
    "MemoryPolicy",
    "PendingCommit",
    "PendingCommitConflict",
    "Phase",
    "PhaseTransitionError",
    "PlanStartRecord",
    "PlanningTier",
    "Progress",
    "RunMeta",
    "Scope",
    "ScopeKind",
    "UnsupportedAdvanceModeError",
    "architect_memory_policy",
    "arc_scope",
    "can_transition_flow",
    "can_transition_phase",
    "chapter_memory_policy",
    "chapter_scope",
    "context_profile",
    "global_scope",
    "planner_for_tier",
    "prepare_pending_commit",
    "validate_advance_control",
    "validate_flow_transition",
    "validate_phase_transition",
    "volume_scope",
]
