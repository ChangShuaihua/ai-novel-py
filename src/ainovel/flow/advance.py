"""章节推进的机械判断。不读文件，也不解释任务文案。"""

from ainovel.domain.commit import PendingCommit
from ainovel.domain.progress import Progress
from ainovel.domain.run_meta import AdvanceHold, AdvanceHoldAfter
from ainovel.domain.transitions import Phase
from ainovel.flow.model import Instruction

KEEP = "keep"
CONSUME = "consume"
CONSUME_AND_STOP = "consume_and_stop"


def starts_forward_chapter(
    instruction: Instruction | None,
    progress: Progress | None,
    pending: PendingCommit | None,
) -> bool:
    """只有尚未开始的正向新章才需要逐章许可。返工和提交恢复不算。"""
    if instruction is None or instruction.agent != "writer" or progress is None:
        return False
    if progress.phase != Phase.WRITING:
        return False
    if pending is not None or progress.pending_rewrites or progress.in_progress_chapter:
        return False
    target = instruction.chapter or progress.next_chapter()
    return target > 0 and target == progress.next_chapter()


def resolve_advance_hold(hold: AdvanceHold | None, progress: Progress | None) -> str:
    if hold is None:
        return KEEP
    hold.validate_shape()
    if progress is None:
        raise ValueError("缺少 Progress，无法解析一次性暂停")
    if progress.phase == Phase.COMPLETE:
        return CONSUME
    if progress.phase != Phase.WRITING:
        raise ValueError(f"一次性暂停仅适用于 writing/complete 阶段（当前 {progress.phase}）")
    if hold.after == AdvanceHoldAfter.BOUNDARY:
        return CONSUME_AND_STOP
    if hold.after == AdvanceHoldAfter.REWRITES_DRAINED:
        if progress.pending_rewrites:
            return KEEP
        return CONSUME_AND_STOP
    if hold.after == AdvanceHoldAfter.CHAPTER:
        if progress.latest_completed() < hold.target_chapter:
            return KEEP
        return CONSUME_AND_STOP
    raise ValueError(f"不支持的一次性暂停条件 {hold.after!r}")
