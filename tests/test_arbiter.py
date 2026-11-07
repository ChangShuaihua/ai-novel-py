"""裁定的机械校验。不调用模型。"""

import pytest

from ainovel.arbiter.validate import (
    ArbiterValidationError,
    validate_failure,
    validate_intervention,
    validate_plan_start,
    validate_schedule,
)


def test_illegal_planner_is_rejected():
    with pytest.raises(ArbiterValidationError, match="planner"):
        validate_plan_start({"planner": "writer", "task": "写设定", "reason": "试一下"})


def test_complete_phase_cannot_dispatch():
    facts = {"phase": "complete", "completed_chapters": 2, "next_chapter": 3}
    decision = {
        "reason": "直接改",
        "dispatch": {"agent": "writer", "task": "重写第 1 章"},
    }
    with pytest.raises(ArbiterValidationError, match="完本期"):
        validate_intervention(decision, facts)


def test_reopen_chapter_must_be_inside_completed_range():
    facts = {"phase": "complete", "completed_chapters": 2, "next_chapter": 3}
    decision = {"reason": "返工", "reopen": {"chapters": [9], "reason": "改结局"}}
    with pytest.raises(ArbiterValidationError, match="越界"):
        validate_intervention(decision, facts)


def test_schedule_rejects_a_move_outside_the_menu():
    moves = [{"move_id": "arc_review", "agent": "editor", "duty": "arc_review", "chapter": 0, "task": "审", "reason": "缺"}]
    with pytest.raises(ArbiterValidationError, match="move_id"):
        validate_schedule(
            {"decision": "dispatch", "move_id": "write_chapter:23", "task": "写下一章", "reason": "想写"},
            moves,
        )


def test_plan_accepts_a_downstream_move_that_is_not_legal_yet():
    moves = [{"move_id": "global_review", "agent": "editor", "duty": "global_review", "chapter": 0}]
    validate_schedule(
        {
            "decision": "create_plan",
            "reason": "先审阅，弧审阅等写完再看",
            "tasks": [
                {"task_id": "t1", "move_id": "global_review", "task": "审阅", "depends_on": []},
                {"task_id": "t2", "move_id": "arc_review", "task": "弧审阅", "depends_on": ["t1"]},
            ],
        },
        moves,
    )


def test_plan_rejects_a_dependency_cycle():
    moves = [{"move_id": "global_review", "agent": "editor"}]
    with pytest.raises(ArbiterValidationError, match="环"):
        validate_schedule(
            {
                "decision": "create_plan",
                "reason": "互相等待",
                "tasks": [
                    {"task_id": "t1", "move_id": "global_review", "task": "审", "depends_on": ["t2"]},
                    {"task_id": "t2", "move_id": "write_chapter:6", "task": "写", "depends_on": ["t1"]},
                ],
            },
            moves,
        )


def test_failure_reroute_must_use_a_listed_move():
    facts = {"phase": "writing", "legal_moves": [{"move_id": "write_chapter:6", "agent": "writer"}]}
    with pytest.raises(ArbiterValidationError, match="move_id"):
        validate_failure(
            {"action": "reroute", "move_id": "expand_arc", "task": "展开", "reason": "换"},
            facts,
        )


def test_reroute_requires_dispatch():
    with pytest.raises(ArbiterValidationError, match="dispatch"):
        validate_failure({"action": "reroute", "reason": "换人"}, {"phase": "writing"})
