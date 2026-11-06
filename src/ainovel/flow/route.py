"""纯函数路由。禁止在这里读文件或调用模型。

这里只决定代理、职责和原因。任务正文在 flow/tasks.py。
"""

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
    """按事实返回下一条指令。空表示没有可由查表推出的创作任务。"""
    progress = state.progress
    if progress is None or progress.phase == Phase.COMPLETE:
        return None

    if progress.phase != Phase.WRITING:
        if state.foundation_missing and state.planning_tier:
            if state.foundation_missing == ["foundation_audit"]:
                return _issue(
                    Duty.AUDIT_FOUNDATION,
                    agent=_planner(state.planning_tier),
                    task=tasks.audit_foundation(),
                    reason="基础设定缺项未齐，照缺项续派同一规划师",
                )
            return _issue(
                Duty.FILL_FOUNDATION,
                agent=_planner(state.planning_tier),
                task=tasks.fill_foundation(state.foundation_missing),
                reason="基础设定缺项未齐，照缺项续派同一规划师",
            )
        return None

    if progress.pending_rewrites:
        chapter = progress.pending_rewrites[0]
        polish = progress.flow == FlowState.POLISHING
        return _issue(
            Duty.POLISH if polish else Duty.REWRITE,
            agent="writer",
            task=tasks.revise_chapter(chapter, polish=polish),
            reason=f"PendingRewrites 队列剩余 {len(progress.pending_rewrites)} 章",
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
            reason=f"有 {state.immediate_feedback_count} 条外部修订影响尚未传播到后续规划",
        )

    boundary = state.arc_boundary
    if progress.layered and boundary is not None and boundary.is_arc_end:
        if not state.has_arc_review:
            return _issue(
                Duty.ARC_REVIEW,
                agent="editor",
                task=tasks.arc_review(boundary.volume, boundary.arc, boundary.start_chapter, boundary.end_chapter),
                reason="弧末评审未完成",
            )
        if not state.has_arc_summary:
            return _issue(
                Duty.ARC_SUMMARY,
                agent="editor",
                task=tasks.arc_summary(boundary.volume, boundary.arc),
                reason="弧摘要未完成",
            )
        if boundary.is_volume_end and not state.has_volume_summary:
            return _issue(
                Duty.VOLUME_SUMMARY,
                agent="editor",
                task=tasks.volume_summary(boundary.volume),
                reason="卷摘要未完成",
            )
        if boundary.needs_expansion and boundary.next_arc > 0:
            return _issue(
                Duty.EXPAND_ARC,
                agent="architect_long",
                task=tasks.expand_arc(boundary.next_volume, boundary.next_arc),
                reason="下一弧骨架待展开",
            )
        if boundary.needs_new_volume:
            return _issue(
                Duty.NEW_VOLUME,
                agent="architect_long",
                task=tasks.new_volume(),
                reason="卷末需决定追加新卷、收官卷或结束全书",
            )

    if not progress.layered and state.last_completed > 0:
        due, reason = should_review(len(progress.completed_chapters))
        if due and not state.has_global_review:
            return _issue(
                Duty.GLOBAL_REVIEW,
                agent="editor",
                task=tasks.global_review(state.last_completed),
                reason=reason,
            )

    next_chapter = progress.next_chapter()
    if next_chapter <= 0:
        return None
    if not progress.layered and progress.total_chapters > 0 and next_chapter > progress.total_chapters:
        return _issue(
            Duty.OUTLINE_EXHAUSTED,
            agent=_planner(state.planning_tier),
            task=tasks.outline_exhausted(len(progress.completed_chapters), progress.total_chapters, next_chapter),
            reason="非分层大纲已耗尽，需决定完结或续接",
        )

    return _issue(
        Duty.WRITE_CHAPTER,
        agent="writer",
        task=tasks.write_chapter(next_chapter),
        reason="续写下一章",
        chapter=next_chapter,
    )


def _planner(tier: str) -> str:
    """只有 short 用短篇规划师，其余（含尚未落盘的空值）用长篇规划师。"""
    if tier == "short":
        return "architect_short"
    return "architect_long"


def _issue(duty: str, *, agent: str, task: str, reason: str, chapter: int = 0) -> Instruction:
    return Instruction(agent=agent, task=task, reason=reason, chapter=chapter, duty=duty)


def _aggregate_instruction(refresh) -> Instruction | None:
    if refresh.kind == AggregateKind.ARC_REVIEW:
        return _issue(
            Duty.ARC_REVIEW,
            agent="editor",
            task=tasks.arc_review_refresh(refresh.volume, refresh.arc, refresh.start_chapter, refresh.end_chapter),
            reason="弧级审阅缺失",
        )
    if refresh.kind == AggregateKind.ARC_SUMMARY:
        return _issue(
            Duty.ARC_SUMMARY,
            agent="editor",
            task=tasks.arc_summary(refresh.volume, refresh.arc),
            reason="弧级摘要缺失",
        )
    if refresh.kind == AggregateKind.VOLUME_SUMMARY:
        return _issue(
            Duty.VOLUME_SUMMARY,
            agent="editor",
            task=tasks.volume_summary(refresh.volume),
            reason="卷摘要缺失",
        )
    if refresh.kind == AggregateKind.GLOBAL_REVIEW:
        return _issue(
            Duty.GLOBAL_REVIEW,
            agent="editor",
            task=tasks.global_review_refresh(refresh.end_chapter),
            reason="全局审阅缺失",
        )
    return None
