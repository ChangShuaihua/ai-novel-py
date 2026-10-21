"""Route 的固定夹具与组合规格。规格函数不调用 route。"""

from dataclasses import replace
from pathlib import Path

import pytest

from ainovel.domain.progress import Progress
from ainovel.domain.transitions import FlowState, Phase
from ainovel.flow.model import AggregateKind, AggregateRefresh, ArcBoundary, RouteState
from ainovel.flow.route import route

NIL = "nil"
REWRITE = "rewrite"
ARC_REVIEW = "arc_review"
ARC_SUMMARY = "arc_summary"
VOLUME_SUMMARY = "volume_summary"
EXPAND = "expand"
NEW_VOLUME = "new_volume"
NEXT = "next"
FILL = "fill"
GLOBAL = "global"
FEEDBACK = "feedback"
EXHAUSTED = "exhausted"


def test_route_module_does_not_touch_files():
    source = Path("src/ainovel/flow/route.py").read_text(encoding="utf-8")
    assert "ainovel.store" not in source
    assert "open(" not in source
    assert "Path(" not in source


def test_missing_foundation_dispatches_saved_planner():
    state = RouteState(
        progress=Progress(phase=Phase.OUTLINE),
        foundation_missing=["characters", "world_rules"],
        planning_tier="short",
    )
    got = route(state)
    assert got is not None
    assert got.agent == "architect_short"
    assert got.chapter == 0
    assert "characters" in got.task and "world_rules" in got.task
    assert "save_foundation" in got.task

    state.planning_tier = ""
    assert route(state) is None

    audit = replace(state, planning_tier="long", foundation_missing=["foundation_audit"])
    audited = route(audit)
    assert audited is not None and audited.agent == "architect_long"
    assert "audit_foundation" in audited.task


def test_rewrite_queue_beats_arc_end():
    state = RouteState(
        progress=Progress(
            phase=Phase.WRITING,
            flow=FlowState.REWRITING,
            layered=True,
            completed_chapters=[1, 2],
            pending_rewrites=[3, 5],
        ),
        arc_boundary=ArcBoundary(is_arc_end=True, volume=1, arc=1, start_chapter=1, end_chapter=2),
    )
    got = route(state)
    assert got is not None
    assert got.agent == "writer"
    assert got.chapter == 3
    assert got.task == "重写第 3 章"
    state.progress.flow = FlowState.POLISHING
    assert route(state).task == "打磨第 3 章"


def test_layered_arc_end_review_before_summary_and_expansion():
    boundary = ArcBoundary(
        is_arc_end=True,
        volume=1,
        arc=2,
        start_chapter=11,
        end_chapter=22,
        next_volume=1,
        next_arc=3,
        needs_expansion=True,
    )
    progress = Progress(phase=Phase.WRITING, flow=FlowState.WRITING, layered=True, completed_chapters=[22])
    state = RouteState(progress=progress, last_completed=22, arc_boundary=boundary)
    review = route(state)
    assert review is not None and review.agent == "editor"
    assert review.reason == "弧末评审未完成"
    assert "第 11-22 章" in review.task and "chapter=22" in review.task

    state.has_arc_review = True
    summary = route(state)
    assert summary is not None and summary.reason == "弧摘要未完成"

    state.has_arc_summary = True
    expanded = route(state)
    assert expanded is not None and expanded.agent == "architect_long"
    assert "expand_next_arc" in expanded.task


def test_global_review_and_outline_exhaustion():
    progress = Progress(
        phase=Phase.WRITING,
        flow=FlowState.WRITING,
        completed_chapters=[1, 2, 3, 4, 5],
        total_chapters=8,
    )
    state = RouteState(progress=progress, last_completed=5)
    got = route(state)
    assert got is not None and got.agent == "editor"
    assert got.reason == "已完成 5 章，触发全局审阅"
    assert "chapter=5" in got.task

    state.has_global_review = True
    assert route(state).task == "写第 6 章"

    progress.total_chapters = 5
    progress.completed_chapters = [1, 2, 3, 4, 5]
    exhausted = route(RouteState(progress=progress, last_completed=5, has_global_review=True, planning_tier="long"))
    assert exhausted is not None and exhausted.agent == "architect_long"
    assert "complete_book" in exhausted.task
    assert "第 6 章" in exhausted.task


def _expected(state: RouteState) -> str:
    progress = state.progress
    if progress is None or progress.phase == Phase.COMPLETE:
        return NIL
    if progress.phase != Phase.WRITING:
        if state.foundation_missing and state.planning_tier:
            return FILL
        return NIL
    if progress.pending_rewrites:
        return REWRITE
    if progress.flow in (FlowState.REVIEWING, FlowState.STEERING):
        return NIL
    if state.aggregate_refresh is not None:
        return ARC_SUMMARY
    if state.immediate_feedback_count > 0:
        return FEEDBACK
    boundary = state.arc_boundary
    if progress.layered and boundary is not None and boundary.is_arc_end:
        if not state.has_arc_review:
            return ARC_REVIEW
        if not state.has_arc_summary:
            return ARC_SUMMARY
        if boundary.is_volume_end and not state.has_volume_summary:
            return VOLUME_SUMMARY
        if boundary.needs_expansion and boundary.next_arc > 0:
            return EXPAND
        if boundary.needs_new_volume:
            return NEW_VOLUME
    if not progress.layered and state.last_completed > 0:
        if len(progress.completed_chapters) % 5 == 0 and not state.has_global_review:
            return GLOBAL
    if (
        not progress.layered
        and progress.total_chapters > 0
        and progress.next_chapter() > progress.total_chapters
    ):
        return EXHAUSTED
    return NEXT


def _classify(instruction) -> str:
    if instruction is None:
        return NIL
    task = instruction.task
    if instruction.agent == "writer":
        if "重写" in task or "打磨" in task:
            return REWRITE
        if "写第" in task:
            return NEXT
    if instruction.agent == "editor":
        if "弧级评审" in task:
            return ARC_REVIEW
        if "全局审阅" in task:
            return GLOBAL
        if "save_arc_summary" in task:
            return ARC_SUMMARY
        if "save_volume_summary" in task:
            return VOLUME_SUMMARY
    if instruction.agent in ("architect_long", "architect_short"):
        if "补齐基础设定" in task:
            return FILL
        if "writer_feedback" in task:
            return FEEDBACK
        if "expand_next_arc" in task:
            return EXPAND
        if "append_volume" in task:
            return NEW_VOLUME
        if "非分层大纲已写完" in task:
            return EXHAUSTED
    raise AssertionError(f"无法归类: {instruction}")


def _boundaries():
    cases = [(None, False, False, False)]
    cases.append((ArcBoundary(volume=1, arc=1), False, False, False))
    volume_cases = [(False, False), (True, False), (True, True)]
    follow_cases = [
        (False, 0, False),
        (True, 4, False),
        (True, 0, False),
        (False, 0, True),
    ]
    for review in (False, True):
        for summary in (False, True):
            for volume_end, volume_summary in volume_cases:
                for expansion, next_arc, new_volume in follow_cases:
                    cases.append(
                        (
                            ArcBoundary(
                                is_arc_end=True,
                                is_volume_end=volume_end,
                                volume=2,
                                arc=3,
                                next_volume=2,
                                next_arc=next_arc,
                                needs_expansion=expansion,
                                needs_new_volume=new_volume,
                            ),
                            review,
                            summary,
                            volume_summary,
                        )
                    )
    return cases


def test_route_exhaustive_priority_and_purity():
    phases = [Phase.INIT, Phase.PREMISE, Phase.OUTLINE, Phase.WRITING, Phase.COMPLETE]
    flows = [
        FlowState.WRITING,
        FlowState.REVIEWING,
        FlowState.REWRITING,
        FlowState.POLISHING,
        FlowState.STEERING,
    ]
    queues = [[], [7, 9]]
    completed_sets = [[], [1, 2, 3], [1, 2, 3, 4, 5]]
    missing_sets = [[], ["characters", "world_rules"]]
    tiers = ["", "short", "long"]
    aggregates = [None, AggregateRefresh(kind=AggregateKind.ARC_SUMMARY, volume=1, arc=1, end_chapter=5)]
    total = 0
    for phase in phases:
        for flow in flows:
            for queue in queues:
                for layered in (False, True):
                    for completed in completed_sets:
                        for missing in missing_sets:
                            for tier in tiers:
                                for has_global in (False, True):
                                    for feedback in (0, 1):
                                        for aggregate in aggregates:
                                            for boundary, review, summary, volume_summary in _boundaries():
                                                total += 1
                                                progress = Progress(
                                                    phase=phase,
                                                    flow=flow,
                                                    layered=layered,
                                                    completed_chapters=list(completed),
                                                    pending_rewrites=list(queue),
                                                )
                                                state = RouteState(
                                                    progress=progress,
                                                    last_completed=completed[-1] if completed else 0,
                                                    arc_boundary=boundary,
                                                    has_arc_review=review,
                                                    has_arc_summary=summary,
                                                    has_volume_summary=volume_summary,
                                                    foundation_missing=list(missing),
                                                    planning_tier=tier,
                                                    has_global_review=has_global,
                                                    immediate_feedback_count=feedback,
                                                    aggregate_refresh=aggregate,
                                                )
                                                before = progress.model_dump()
                                                got = route(state)
                                                assert _classify(got) == _expected(state)
                                                assert progress.model_dump() == before
                                                assert route(state) == got
                                                if got is None:
                                                    continue
                                                assert got.task and got.reason
                                                if phase != Phase.WRITING:
                                                    assert got.chapter == 0
                                                    assert "补齐基础设定" in got.task
                                                elif got.agent == "writer":
                                                    assert got.chapter > 0
                                                    if queue:
                                                        assert got.chapter == queue[0]
                                                    else:
                                                        assert got.chapter == progress.next_chapter()
                                                else:
                                                    assert got.chapter == 0
    assert total >= 5000
