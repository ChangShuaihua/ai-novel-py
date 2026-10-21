"""裁定的机械校验。不调用模型。"""

import pytest

from ainovel.arbiter.validate import (
    ArbiterValidationError,
    validate_failure,
    validate_intervention,
    validate_plan_start,
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


def test_reroute_requires_dispatch():
    with pytest.raises(ArbiterValidationError, match="dispatch"):
        validate_failure({"action": "reroute", "reason": "换人"}, {"phase": "writing"})
