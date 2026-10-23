"""纯函数路由。禁止在这里读文件或调用模型。"""

from ainovel.domain.transitions import FlowState, Phase
from ainovel.flow.model import (
    AggregateKind,
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
            task = (
                "补齐基础设定与作品信息缺项："
                + "、".join(state.foundation_missing)
                + "；book 使用 save_book，其余基础设定使用 save_foundation 落盘"
            )
            if state.foundation_missing == ["foundation_audit"]:
                task = (
                    "基础设定已齐全：重新调用 novel_context 读取全部已落盘工件与 "
                    "foundation_status.fingerprint，审查跨文件语义一致性后调用 audit_foundation；"
                    "有问题先修正并重新审查"
                )
            return Instruction(
                agent=_planner(state.planning_tier),
                task=task,
                reason="基础设定缺项未齐，照缺项续派同一规划师",
            )
        return None

    if progress.pending_rewrites:
        chapter = progress.pending_rewrites[0]
        verb = "打磨" if progress.flow == FlowState.POLISHING else "重写"
        return Instruction(
            agent="writer",
            task=f"{verb}第 {chapter} 章",
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
        return Instruction(
            agent=_planner(state.planning_tier),
            task=(
                "仅处理 novel_context 中的外部修订 writer_feedback：核对已发生剧情与后续计划，"
                "需要调整时调用 revise_outline 或相应结构工具，无需调整时调用 resolve_outline_feedback；"
                "不得处理 foundation_status 或其它规划，落盘后用一句话结束"
            ),
            reason=f"有 {state.immediate_feedback_count} 条外部修订影响尚未传播到后续规划",
        )

    boundary = state.arc_boundary
    if progress.layered and boundary is not None and boundary.is_arc_end:
        if not state.has_arc_review:
            return Instruction(
                agent="editor",
                task=(
                    f"对第 {boundary.volume} 卷第 {boundary.arc} 弧"
                    f"（第 {boundary.start_chapter}-{boundary.end_chapter} 章）做弧级评审："
                    f"调用 novel_context(chapter={boundary.end_chapter})，"
                    f"save_review 使用 scope=arc、chapter={boundary.end_chapter}；"
                    "issues[].chapters 只能落在该区间"
                ),
                reason="弧末评审未完成",
            )
        if not state.has_arc_summary:
            return Instruction(
                agent="editor",
                task=f"生成第 {boundary.volume} 卷第 {boundary.arc} 弧摘要、角色快照与写作规则（save_arc_summary）",
                reason="弧摘要未完成",
            )
        if boundary.is_volume_end and not state.has_volume_summary:
            return Instruction(
                agent="editor",
                task=f"生成第 {boundary.volume} 卷卷摘要（save_volume_summary）",
                reason="卷摘要未完成",
            )
        if boundary.needs_expansion and boundary.next_arc > 0:
            return Instruction(
                agent="architect_long",
                task=f"展开第 {boundary.next_volume} 卷第 {boundary.next_arc} 弧（expand_next_arc）",
                reason="下一弧骨架待展开",
            )
        if boundary.needs_new_volume:
            return Instruction(
                agent="architect_long",
                task=(
                    "创建下一卷：按完结判定清单评估后调用 save_foundation——"
                    "故事继续 → type=append_volume；故事接近终点 → type=append_volume 且卷 JSON 顶层带 "
                    '"final": true（收官卷，整卷收线，写完自动完结）；'
                    "全部完结条件当下已满足 → type=complete_book。三选一均须附 reason 参数写明判定理由"
                ),
                reason="卷末需决定追加新卷、收官卷或结束全书",
            )

    if not progress.layered and state.last_completed > 0:
        due, reason = should_review(len(progress.completed_chapters))
        if due and not state.has_global_review:
            return Instruction(
                agent="editor",
                task=(
                    f"对前 {state.last_completed} 章做全局审阅"
                    f"（save_review scope=global, chapter={state.last_completed}）"
                ),
                reason=reason,
            )

    next_chapter = progress.next_chapter()
    if next_chapter <= 0:
        return None
    if not progress.layered and progress.total_chapters > 0 and next_chapter > progress.total_chapters:
        return Instruction(
            agent=_planner(state.planning_tier),
            task=(
                f"非分层大纲已写完（已完成 {len(progress.completed_chapters)} 章，共 {progress.total_chapters} 章）："
                "若故事已收束，调用 save_foundation(type=complete_book)；"
                f"若仍需继续，用 revise_outline 从第 {next_chapter} 章续接后续计划"
            ),
            reason="非分层大纲已耗尽，需决定完结或续接",
        )

    return Instruction(
        agent="writer",
        task=f"写第 {next_chapter} 章",
        reason="续写下一章",
        chapter=next_chapter,
    )


def _planner(tier: str) -> str:
    """只有 short 用短篇规划师，其余（含尚未落盘的空值）用长篇规划师。"""
    if tier == "short":
        return "architect_short"
    return "architect_long"


def _aggregate_instruction(refresh) -> Instruction | None:
    if refresh.kind == AggregateKind.ARC_REVIEW:
        return Instruction(
            agent="editor",
            task=(
                f"审阅第 {refresh.volume} 卷第 {refresh.arc} 弧"
                f"（第 {refresh.start_chapter}-{refresh.end_chapter} 章）："
                f"调用 novel_context(chapter={refresh.end_chapter})，"
                f"save_review 使用 scope=arc、chapter={refresh.end_chapter}"
            ),
            reason="弧级审阅缺失",
        )
    if refresh.kind == AggregateKind.ARC_SUMMARY:
        return Instruction(
            agent="editor",
            task=f"生成第 {refresh.volume} 卷第 {refresh.arc} 弧摘要、角色快照与写作规则（save_arc_summary）",
            reason="弧级摘要缺失",
        )
    if refresh.kind == AggregateKind.VOLUME_SUMMARY:
        return Instruction(
            agent="editor",
            task=f"生成第 {refresh.volume} 卷卷摘要（save_volume_summary）",
            reason="卷摘要缺失",
        )
    if refresh.kind == AggregateKind.GLOBAL_REVIEW:
        return Instruction(
            agent="editor",
            task=(
                f"审阅前 {refresh.end_chapter} 章：调用 novel_context(chapter={refresh.end_chapter})，"
                f"save_review 使用 scope=global、chapter={refresh.end_chapter}"
            ),
            reason="全局审阅缺失",
        )
    return None
