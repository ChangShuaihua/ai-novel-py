from datetime import datetime, timezone

import pytest

from ainovel.domain.context import chapter_memory_policy, context_profile
from ainovel.domain.errors import FlowTransitionError, PhaseTransitionError
from ainovel.domain.progress import Progress
from ainovel.domain.run_meta import (
    AdvanceHold,
    planner_for_tier,
    validate_advance_control,
)
from ainovel.domain.run_meta import RunMeta
from ainovel.domain.transitions import FlowState, Phase, can_transition_flow, can_transition_phase
from ainovel.domain.json_time import parse_time


@pytest.mark.parametrize(
    ("source", "target", "allowed"),
    [
        ("", Phase.WRITING, True),
        (Phase.INIT, Phase.OUTLINE, True),
        (Phase.INIT, Phase.WRITING, True),
        (Phase.PREMISE, Phase.OUTLINE, True),
        (Phase.OUTLINE, Phase.WRITING, True),
        (Phase.WRITING, Phase.WRITING, True),
        (Phase.WRITING, Phase.COMPLETE, True),
        (Phase.WRITING, Phase.PREMISE, False),
        (Phase.COMPLETE, Phase.WRITING, False),
        (Phase.OUTLINE, "", False),
        ("nope", Phase.WRITING, False),
    ],
)
def test_phase_transitions(source, target, allowed):
    assert can_transition_phase(source, target) is allowed
    if allowed:
        return
    with pytest.raises(PhaseTransitionError):
        from ainovel.domain.transitions import validate_phase_transition

        validate_phase_transition(source, target)


@pytest.mark.parametrize(
    ("source", "target", "allowed"),
    [
        ("", FlowState.STEERING, True),
        (FlowState.WRITING, FlowState.REVIEWING, True),
        (FlowState.REVIEWING, FlowState.POLISHING, True),
        (FlowState.REWRITING, FlowState.WRITING, True),
        (FlowState.REWRITING, FlowState.REVIEWING, False),
        (FlowState.POLISHING, FlowState.REWRITING, False),
        (FlowState.STEERING, FlowState.REWRITING, True),
        (FlowState.WRITING, "", False),
    ],
)
def test_flow_transitions(source, target, allowed):
    assert can_transition_flow(source, target) is allowed
    if not allowed:
        with pytest.raises(FlowTransitionError):
            from ainovel.domain.transitions import validate_flow_transition

            validate_flow_transition(source, target)


def test_context_profile_boundaries():
    assert context_profile(15).summary_window == 10
    assert context_profile(15).layered is False
    assert context_profile(16).summary_window == 5
    assert context_profile(50).timeline_window == 8
    wide = context_profile(51)
    assert wide.summary_window == 3
    assert wide.timeline_window == 5
    assert wide.layered is True


def test_memory_policy_follow_progress():
    progress = Progress(
        phase=Phase.WRITING,
        total_chapters=40,
        layered=True,
        completed_chapters=list(range(1, 7)),
        flow=FlowState.WRITING,
    )
    policy = chapter_memory_policy(progress, context_profile(40), current_outline_bound=True)
    assert policy.related_chapter_lookup is True
    assert policy.handoff_preferred is True
    assert policy.read_only_threshold == 4


def test_planner_requires_saved_tier():
    with pytest.raises(ValueError):
        planner_for_tier("")
    assert planner_for_tier("short") == "architect_short"
    assert planner_for_tier("mid") == "architect_long"
    assert planner_for_tier("long") == "architect_long"


def test_advance_hold_shape():
    AdvanceHold(after="chapter", target_chapter=3, reason="看一章").validate_shape()
    with pytest.raises(ValueError):
        AdvanceHold(after="boundary", target_chapter=3, reason="停").validate_shape()
    meta = RunMeta(advance_mode="auto", advance_permit_chapter=2)
    with pytest.raises(ValueError):
        validate_advance_control(meta)


def test_progress_json_matches_go_names():
    progress = Progress(
        phase=Phase.WRITING,
        current_chapter=2,
        total_chapters=10,
        completed_chapters=[1],
        total_word_count=3000,
        chapter_word_counts={1: 3000},
        flow=FlowState.WRITING,
    )
    disk = progress.to_disk()
    assert disk["chapter_word_counts"] == {"1": 3000}
    assert "reopen_count" not in disk
    loaded = Progress.model_validate(
        {
            "phase": "writing",
            "current_chapter": 2,
            "completed_chapters": None,
            "chapter_word_counts": {"1": 3000, "2": 100},
        }
    )
    assert loaded.completed_chapters == []
    assert loaded.chapter_word_counts == {1: 3000, 2: 100}
    assert loaded.latest_completed() == 0
    assert progress.next_chapter() == 2


def test_parse_go_nanosecond_timestamp():
    parsed = parse_time("2026-10-17T00:00:00.123456789Z")
    assert parsed == datetime(2026, 10, 17, 0, 0, 0, 123456, tzinfo=timezone.utc)
