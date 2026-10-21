"""裁定的机械校验。这里不读盘，也不调用模型。"""

from ainovel.domain.run_meta import AdvanceHold, AdvanceHoldAfter
from ainovel.domain.transitions import Phase

WORKERS = ("architect_long", "architect_short", "writer", "editor")


class ArbiterValidationError(ValueError):
    """结构或事实校验没过。可以把原因送回模型。"""


def validate_plan_start(decision: dict) -> None:
    planner = str(decision.get("planner") or "")
    if planner not in ("architect_long", "architect_short"):
        raise ArbiterValidationError("planner 非法，只能是 architect_long 或 architect_short")
    if not str(decision.get("task") or "").strip():
        raise ArbiterValidationError("task 不能为空")
    if not str(decision.get("reason") or "").strip():
        raise ArbiterValidationError("reason 不能为空")


def validate_failure(decision: dict, facts: dict) -> None:
    if not str(decision.get("reason") or "").strip():
        raise ArbiterValidationError("reason 不能为空")
    action = str(decision.get("action") or "")
    dispatch = decision.get("dispatch")
    if action in ("retry", "abort"):
        if dispatch not in (None, {}):
            raise ArbiterValidationError(f"{action} 不带派单")
        return
    if action != "reroute":
        raise ArbiterValidationError("action 非法，只能是 retry、reroute 或 abort")
    if not isinstance(dispatch, dict):
        raise ArbiterValidationError("reroute 必须附 dispatch")
    _validate_dispatch(dispatch, str(facts.get("phase") or ""))


def validate_intervention(decision: dict, facts: dict) -> None:
    if not str(decision.get("reason") or "").strip():
        raise ArbiterValidationError("reason 不能为空")
    answer = str(decision.get("answer") or "")
    rules = str(decision.get("rules") or "")
    hold = decision.get("hold")
    reopen = decision.get("reopen")
    dispatch = decision.get("dispatch")
    if not answer and not rules and hold in (None, {}) and reopen in (None, {}) and dispatch in (None, {}):
        raise ArbiterValidationError("空决策：至少要有一个动作或 answer")
    phase = str(facts.get("phase") or "")
    if dispatch not in (None, {}):
        if not isinstance(dispatch, dict):
            raise ArbiterValidationError("dispatch 必须是对象")
        _validate_dispatch(dispatch, phase)
    if phase == Phase.COMPLETE and dispatch not in (None, {}):
        raise ArbiterValidationError("完本期禁止直接派单；返工用 reopen")
    if reopen not in (None, {}):
        if not isinstance(reopen, dict):
            raise ArbiterValidationError("reopen 必须是对象")
        if phase != Phase.COMPLETE:
            raise ArbiterValidationError(f"reopen 仅限完本期（当前 phase={phase}）")
        chapters = reopen.get("chapters") or []
        if not chapters:
            raise ArbiterValidationError("reopen.chapters 不能为空")
        completed = int(facts.get("completed_chapters") or 0)
        for chapter in chapters:
            number = int(chapter)
            if number < 1 or number > completed:
                raise ArbiterValidationError(f"reopen 章节 {number} 越界（已完成 {completed} 章）")
    if hold not in (None, {}):
        if not isinstance(hold, dict):
            raise ArbiterValidationError("hold 必须是对象")
        if not hold.get("cancel"):
            if phase != Phase.WRITING:
                raise ArbiterValidationError(f"一次性暂停仅限写作期（当前 phase={phase}）")
            after = str(hold.get("after") or "")
            target = int(hold.get("target_chapter") or 0)
            AdvanceHold(after=after, target_chapter=target, reason=str(hold.get("reason") or "")).validate_shape()
            next_chapter = int(facts.get("next_chapter") or 0) or int(facts.get("completed_chapters") or 0) + 1
            if after == AdvanceHoldAfter.CHAPTER and target < next_chapter:
                raise ArbiterValidationError(f"目标章节 {target} 早于当前下一章 {next_chapter}")


def _validate_dispatch(dispatch: dict, phase: str) -> None:
    agent = str(dispatch.get("agent") or "")
    if agent not in WORKERS:
        raise ArbiterValidationError(f"dispatch.agent 非法: {agent}")
    if not str(dispatch.get("task") or "").strip():
        raise ArbiterValidationError("dispatch.task 不能为空")
    if not phase:
        raise ArbiterValidationError("缺少 phase，禁止执行派单")
    if phase == Phase.COMPLETE:
        raise ArbiterValidationError("完本期禁止直接派单")
    if agent in ("writer", "editor") and phase != Phase.WRITING:
        raise ArbiterValidationError(f"{agent} 仅能在 writing 阶段派发（当前 phase={phase}）")
