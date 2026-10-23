import json
from pathlib import Path

import pytest

from ainovel.domain.progress import Progress
from ainovel.domain.run_meta import RunMeta
from ainovel.domain.transitions import Phase
from ainovel.flow.load import LoadStateError, load_state
from ainovel.flow.model import AggregateKind
from ainovel.flow.route import route
from ainovel.store.book import Book


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_corrupt_progress_blocks_routing(tmp_path: Path):
    _write(tmp_path / "meta" / "progress.json", "{")
    book = Book.open(tmp_path, writable=False)
    with pytest.raises(LoadStateError, match="progress"):
        load_state(book)


def test_load_state_ignores_ordinary_feedback(tmp_path: Path):
    book = Book.open(tmp_path, writable=True)
    book.progress.save(
        Progress(phase=Phase.WRITING, completed_chapters=[1], total_chapters=10)
    )
    book.run_meta.save(
        __import__("ainovel.domain.run_meta", fromlist=["RunMeta"]).RunMeta(
            style="fantasy",
            model="m",
            advance_mode="auto",
            planning_tier="long",
        )
    )
    _write(
        tmp_path / "meta" / "outline_feedback.jsonl",
        json.dumps({"chapter": 1, "deviation": "无明显偏离", "suggestion": "继续"}) + "\n",
    )
    state = load_state(book)
    assert state.immediate_feedback_count == 0
    got = route(state)
    assert got is not None and got.agent == "writer"

    with (tmp_path / "meta" / "outline_feedback.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"chapter": 1, "story_changed": True, "change_summary": "结局改了"}) + "\n")
    state = load_state(book)
    assert state.immediate_feedback_count == 1
    got = route(state)
    assert got is not None and got.agent == "architect_long"
    assert "writer_feedback" in got.task


def test_layered_outline_stands_in_for_flat_outline(tmp_path: Path):
    _write(tmp_path / "meta" / "book.json", json.dumps({"title": "赊命长生", "synopsis": "雨天醒来。"}))
    _write(tmp_path / "premise.md", "雨天醒来。")
    _write(tmp_path / "characters.json", json.dumps([{"name": "他"}]))
    _write(tmp_path / "world_rules.json", json.dumps([{"rule": "雨声不断"}]))
    _write(tmp_path / "layered_outline.json", json.dumps([{"arcs": [{"chapters": [{}, {}]}]}]))
    _write(tmp_path / "meta" / "compass.json", json.dumps({"ending_direction": "雨停"}))
    _write(tmp_path / "meta" / "progress.json", json.dumps({
        "phase": "outline",
        "layered": True,
        "total_chapters": 12,
        "completed_chapters": [],
        "current_chapter": 0,
        "total_word_count": 0,
    }))
    book = Book.open(tmp_path, writable=True)
    book.run_meta.save(RunMeta(planning_tier="long", advance_mode="auto"))
    state = load_state(book)
    assert state.foundation_missing == ["foundation_audit"]
    got = route(state)
    assert got is not None
    assert got.agent == "architect_long"
    assert "audit_foundation" in got.task
    assert "outline" not in got.task


def test_load_state_layered_arc_end_and_foundation(tmp_path: Path):
    _write(
        tmp_path / "layered_outline.json",
        json.dumps(
            [
                {
                    "index": 1,
                    "arcs": [
                        {"index": 1, "chapters": [{}, {}]},
                        {"index": 2, "chapters": []},
                    ],
                }
            ]
        ),
    )
    _write(tmp_path / "meta" / "progress.json", json.dumps({
        "phase": "writing",
        "layered": True,
        "completed_chapters": [1, 2],
        "total_chapters": 4,
        "current_chapter": 2,
        "total_word_count": 10,
    }))
    book = Book.open(tmp_path, writable=False)
    state = load_state(book)
    assert "book" in state.foundation_missing
    assert state.arc_boundary is not None
    assert state.arc_boundary.is_arc_end is True
    assert state.arc_boundary.needs_expansion is True
    assert state.arc_boundary.next_arc == 2
    assert state.aggregate_refresh is not None
    assert state.aggregate_refresh.kind == AggregateKind.ARC_REVIEW
    got = route(state)
    assert got is not None and got.reason == "弧级审阅缺失"
