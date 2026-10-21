"""阶段与流程的迁移规则。"""

from enum import StrEnum

from ainovel.domain.errors import FlowTransitionError, PhaseTransitionError


class Phase(StrEnum):
    INIT = "init"
    PREMISE = "premise"
    OUTLINE = "outline"
    WRITING = "writing"
    COMPLETE = "complete"


class FlowState(StrEnum):
    WRITING = "writing"
    REVIEWING = "reviewing"
    REWRITING = "rewriting"
    POLISHING = "polishing"
    STEERING = "steering"


_PHASE_ORDER = {
    Phase.INIT: 1,
    Phase.PREMISE: 2,
    Phase.OUTLINE: 3,
    Phase.WRITING: 4,
    Phase.COMPLETE: 5,
}

_FLOW_TARGETS: dict[FlowState, frozenset[FlowState]] = {
    FlowState.WRITING: frozenset(
        {
            FlowState.REVIEWING,
            FlowState.REWRITING,
            FlowState.POLISHING,
            FlowState.STEERING,
        }
    ),
    FlowState.REVIEWING: frozenset(
        {
            FlowState.WRITING,
            FlowState.REWRITING,
            FlowState.POLISHING,
            FlowState.STEERING,
        }
    ),
    FlowState.REWRITING: frozenset({FlowState.WRITING, FlowState.STEERING}),
    FlowState.POLISHING: frozenset({FlowState.WRITING, FlowState.STEERING}),
    FlowState.STEERING: frozenset(
        {
            FlowState.WRITING,
            FlowState.REVIEWING,
            FlowState.REWRITING,
            FlowState.POLISHING,
        }
    ),
}


def can_transition_phase(source: Phase | str | None, target: Phase | str | None) -> bool:
    """允许同态和前进。空来源视为未初始化。目标为空非法。

    离开 complete 不走这条规则，只能经存储层的 reopen。
    """
    if not target:
        return False
    if not source or source == target:
        return True
    try:
        source_phase = Phase(source)
        target_phase = Phase(target)
    except ValueError:
        return False
    return _PHASE_ORDER[target_phase] >= _PHASE_ORDER[source_phase]


def validate_phase_transition(source: Phase | str | None, target: Phase | str | None) -> None:
    if can_transition_phase(source, target):
        return
    raise PhaseTransitionError(f"非法阶段迁移: {source!r} -> {target!r}")


def can_transition_flow(source: FlowState | str | None, target: FlowState | str | None) -> bool:
    """空来源可以进入任意合法流程。同态允许。"""
    if not target:
        return False
    if not source or source == target:
        return True
    try:
        source_flow = FlowState(source)
        target_flow = FlowState(target)
    except ValueError:
        return False
    return target_flow in _FLOW_TARGETS[source_flow]


def validate_flow_transition(source: FlowState | str | None, target: FlowState | str | None) -> None:
    if can_transition_flow(source, target):
        return
    raise FlowTransitionError(f"非法流程迁移: {source!r} -> {target!r}")
