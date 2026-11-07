"""Pure-function routing. This module only chooses agents, duties, and reasons."""

import ainovel.flow.tasks as tasks
from ainovel.domain.transitions import FlowState, Phase
from ainovel.flow.model import (
    AggregateKind,
    Duty,
    Instruction,
    RouteState,
    should_review,
)


def route(state: RouteState) -> Instruction | None:
    moves = legal_moves(state)
    return moves[0] if moves else None


def legal_moves(state: RouteState) -> list[Instruction]:
    primary = _primary(state)
    if primary is None:
        return []
    companion = _unordered_companion(state, primary)
    return [primary, companion] if companion is not None else [primary]


def _primary(state: RouteState) -> Instruction | None:
    progress = state.progress
    if progress is None or progress.phase == Phase.COMPLETE:
        return None

    if progress.phase != Phase.WRITING:
        if state.foundation_missing and state.planning_tier:
            missing = set(state.foundation_missing)
            sequence = ["book", "premise", "outline"]
            step = next((item for item in sequence if item in missing and state.planning_approval != item), "")
            if step:
                return _issue(
                    Duty.FILL_FOUNDATION,
                    agent=_planner(state.planning_tier),
                    task=tasks.fill_foundation_step(step, state.planning_tier),
                    reason=f"Generate {step} and wait for approval",
                )
            if state.planning_approval:
                return None
            if state.foundation_missing == ["foundation_audit"]:
                return _issue(
                    Duty.AUDIT_FOUNDATION,
                    agent=_planner(state.planning_tier),
                    task=tasks.audit_foundation(),
                    reason="Foundation audit is pending",
                )
            if state.foundation_missing == ["characters"]:
                return _issue(
                    Duty.DESIGN_CHARACTERS,
                    agent="character",
                    task=tasks.design_characters(),
                    reason="Character records are missing",
                )
            return _issue(
                Duty.FILL_FOUNDATION,
                agent=_planner(state.planning_tier),
                task=tasks.fill_foundation(state.foundation_missing),
                reason="Complete remaining foundation items",
            )
        return None

    if progress.pending_rewrites:
        chapter = progress.pending_rewrites[0]
        polish = progress.flow == FlowState.POLISHING
        return _issue(
            Duty.POLISH if polish else Duty.REWRITE,
            agent="writer",
            task=tasks.revise_chapter(chapter, polish=polish),
            reason=f"{len(progress.pending_rewrites)} rewrites remain",
            chapter=chapter,
        )
    if progress.flow in (FlowState.REVIEWING, FlowState.STEERING):
        return None

    refresh = state.aggregate_refresh
    if refresh is not None:
        rebuilt = _aggregate_instruction(refresh)
        if rebuilt is not None:
            return rebuilt
    if state.immediate_feedback_count > 0:
        return _issue(
            Duty.OUTLINE_FEEDBACK,
            agent=_planner(state.planning_tier),
            task=tasks.outline_feedback(),
            reason=f"{state.immediate_feedback_count} external outline revisions need propagation",
        )

    boundary = state.arc_boundary
    if progress.layered and boundary is not None and boundary.is_arc_end:
        if not state.has_arc_review:
            return _issue(Duty.ARC_REVIEW, agent="editor", task=tasks.arc_review(boundary.volume, boundary.arc, boundary.start_chapter, boundary.end_chapter), reason="Arc review is pending")
        if not state.has_arc_summary:
            return _issue(Duty.ARC_SUMMARY, agent="editor", task=tasks.arc_summary(boundary.volume, boundary.arc), reason="Arc summary is pending")
        if boundary.is_volume_end and not state.has_volume_summary:
            return _issue(Duty.VOLUME_SUMMARY, agent="editor", task=tasks.volume_summary(boundary.volume), reason="Volume summary is pending")
        if boundary.needs_expansion and boundary.next_arc > 0:
            return _issue(Duty.EXPAND_ARC, agent="architect_long", task=tasks.expand_arc(boundary.next_volume, boundary.next_arc), reason="The next arc needs expansion")
        if boundary.needs_new_volume:
            return _issue(Duty.NEW_VOLUME, agent="architect_long", task=tasks.new_volume(), reason="A new volume or ending must be planned")

    if not progress.layered and state.last_completed > 0:
        due, reason = should_review(len(progress.completed_chapters))
        if due and not state.has_global_review:
            return _issue(Duty.GLOBAL_REVIEW, agent="editor", task=tasks.global_review(state.last_completed), reason=reason)

    next_chapter = progress.next_chapter()
    if next_chapter <= 0:
        return None
    if not progress.layered and progress.total_chapters > 0 and next_chapter > progress.total_chapters:
        return _issue(Duty.OUTLINE_EXHAUSTED, agent=_planner(state.planning_tier), task=tasks.outline_exhausted(len(progress.completed_chapters), progress.total_chapters, next_chapter), reason="The flat outline is exhausted")
    return _issue(Duty.WRITE_CHAPTER, agent="writer", task=tasks.write_chapter(next_chapter), reason="Write the next chapter", chapter=next_chapter)


def _unordered_companion(state: RouteState, primary: Instruction) -> Instruction | None:
    if primary.duty != Duty.GLOBAL_REVIEW:
        return None
    refresh = state.aggregate_refresh
    if refresh is not None and refresh.kind == AggregateKind.GLOBAL_REVIEW and refresh.end_chapter < state.last_completed:
        return None
    progress = state.progress
    if progress is None or progress.layered:
        return None
    next_chapter = progress.next_chapter()
    if next_chapter <= 0 or (progress.total_chapters > 0 and next_chapter > progress.total_chapters):
        return None
    return _issue(Duty.WRITE_CHAPTER, agent="writer", task=tasks.write_chapter(next_chapter), reason="Write while global review runs", chapter=next_chapter)


def _planner(tier: str) -> str:
    return "architect_short" if tier == "short" else "architect_long"


def _issue(duty: str, *, agent: str, task: str, reason: str, chapter: int = 0) -> Instruction:
    return Instruction(agent=agent, task=task, reason=reason, chapter=chapter, duty=duty)


def _aggregate_instruction(refresh) -> Instruction | None:
    if refresh.kind == AggregateKind.ARC_REVIEW:
        return _issue(Duty.ARC_REVIEW, agent="editor", task=tasks.arc_review_refresh(refresh.volume, refresh.arc, refresh.start_chapter, refresh.end_chapter), reason="Arc review is missing")
    if refresh.kind == AggregateKind.ARC_SUMMARY:
        return _issue(Duty.ARC_SUMMARY, agent="editor", task=tasks.arc_summary(refresh.volume, refresh.arc), reason="Arc summary is missing")
    if refresh.kind == AggregateKind.VOLUME_SUMMARY:
        return _issue(Duty.VOLUME_SUMMARY, agent="editor", task=tasks.volume_summary(refresh.volume), reason="Volume summary is missing")
    if refresh.kind == AggregateKind.GLOBAL_REVIEW:
        return _issue(Duty.GLOBAL_REVIEW, agent="editor", task=tasks.global_review_refresh(refresh.end_chapter), reason="Global review is missing")
    return None
