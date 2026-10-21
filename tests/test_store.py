import json
import os
from pathlib import Path

import pytest

from ainovel.domain.book import BookMetadata
from ainovel.domain.checkpoint import chapter_scope
from ainovel.domain.commit import CommitStage, PendingCommit, PendingCommitConflict
from ainovel.domain.errors import UnsupportedAdvanceModeError
from ainovel.domain.progress import Progress
from ainovel.domain.run_meta import AdvanceHold, PlanStartRecord, RunMeta
from ainovel.domain.transitions import Phase, validate_phase_transition
from ainovel.store.book import Book
from ainovel.store.io import atomic_replace
from ainovel.store.paths import chapter_number


def test_chapter_numbers_match_go_width():
    assert chapter_number(1) == "01"
    assert chapter_number(10) == "10"
    assert chapter_number(100) == "100"


def test_atomic_replace_keeps_old_bytes_when_replace_fails(tmp_path: Path, monkeypatch):
    target = tmp_path / "meta" / "progress.json"
    atomic_replace(target, b'{"phase":"init"}')

    def fail_replace(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        atomic_replace(target, b'{"phase":"writing"}')
    assert target.read_bytes() == b'{"phase":"init"}'
    leftovers = list(target.parent.glob("progress.json.tmp-*"))
    assert leftovers == []


def test_atomic_replace_overwrites_existing_file(tmp_path: Path):
    target = tmp_path / "note.txt"
    atomic_replace(target, b"old")
    atomic_replace(target, b"new")
    assert target.read_bytes() == b"new"


def test_checkpoint_same_digest_is_idempotent(tmp_path: Path):
    book = Book.open(tmp_path, writable=True)
    scope = chapter_scope(3)
    first = book.checkpoints.append(scope, "draft", "drafts/03.draft.md", "sha256:abc")
    second = book.checkpoints.append(scope, "draft", "drafts/03.draft.md", "sha256:abc")
    assert second.seq == first.seq == 1
    other = book.checkpoints.append(scope, "draft", "drafts/03.draft.md", "sha256:def")
    assert other.seq == 2
    lines = (tmp_path / "meta" / "checkpoints.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    empty_a = book.checkpoints.append(scope, "plan", "drafts/03.plan.json", "")
    empty_b = book.checkpoints.append(scope, "plan", "drafts/03.plan.json", "")
    assert empty_b.seq == empty_a.seq + 1


def test_corrupt_checkpoint_is_not_treated_as_empty(tmp_path: Path):
    meta = tmp_path / "meta"
    meta.mkdir()
    (meta / "checkpoints.jsonl").write_text("{broken}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        Book.open(tmp_path, writable=False)


def test_readonly_loads_go_shaped_book(tmp_path: Path):
    meta = tmp_path / "meta"
    meta.mkdir()
    (meta / "progress.json").write_text(
        json.dumps(
            {
                "phase": "writing",
                "current_chapter": 2,
                "total_chapters": 8,
                "completed_chapters": [1],
                "total_word_count": 1200,
                "chapter_word_counts": {"1": 1200},
                "flow": "writing",
            }
        ),
        encoding="utf-8",
    )
    (meta / "run.json").write_text(
        json.dumps(
            {
                "started_at": "2026-10-17T00:00:00Z",
                "style": "fantasy",
                "model": "writer-model",
                "advance_mode": "review",
                "advance_permit_chapter": 2,
                "pending_steer": "把主角改成女性",
                "planning_tier": "long",
                "start_prompt": "写一本修仙",
                "plan_start": {
                    "raw_prompt": "写一本修仙",
                    "planner": "architect_long",
                    "planner_task": "规划长篇",
                },
            }
        ),
        encoding="utf-8",
    )
    (meta / "book.json").write_text(
        json.dumps({"title": "凡骨", "synopsis": "一个凡人修仙。"}),
        encoding="utf-8",
    )
    (meta / "checkpoints.jsonl").write_text(
        json.dumps(
            {
                "seq": 4,
                "scope": {"kind": "chapter", "chapter": 1},
                "step": "commit",
                "artifact": "chapters/01.md",
                "digest": "sha256:abc",
                "occurred_at": "2026-10-17T01:02:03.123456789Z",
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    book = Book.open(tmp_path, writable=True)
    progress = book.progress.load()
    assert progress is not None
    assert progress.phase == Phase.WRITING
    assert progress.chapter_word_counts[1] == 1200
    assert progress.next_chapter() == 2
    meta_loaded = book.run_meta.load()
    assert meta_loaded is not None
    assert meta_loaded.pending_steer == "把主角改成女性"
    assert meta_loaded.plan_start is not None
    assert meta_loaded.plan_start.planner == "architect_long"
    info = book.info.load()
    assert info is not None and info.title == "凡骨"
    latest = book.checkpoints.latest(chapter_scope(1))
    assert latest is not None and latest.seq == 4


def test_unknown_advance_mode_blocks_writable_open(tmp_path: Path):
    meta = tmp_path / "meta"
    meta.mkdir()
    original = json.dumps(
        {"started_at": "t", "style": "old", "model": "m", "advance_mode": "future"}
    )
    (meta / "run.json").write_text(original, encoding="utf-8")
    readonly = Book.open(tmp_path, writable=False)
    loaded = readonly.run_meta.load()
    assert loaded is not None and loaded.advance_mode == "future"
    with pytest.raises(UnsupportedAdvanceModeError):
        Book.open(tmp_path, writable=True)
    assert (meta / "run.json").read_text(encoding="utf-8") == original


def test_init_preserves_intent_and_rejects_unknown_mode(tmp_path: Path):
    book = Book.open(tmp_path, writable=True)
    book.run_meta.save(
        RunMeta(
            started_at="2026-01-01T00:00:00Z",
            style="old",
            model="old-model",
            advance_mode="review",
            advance_permit_chapter=3,
            pending_steer="保留这条干预",
            planning_tier="long",
            start_prompt="一句话",
            plan_start=PlanStartRecord(
                raw_prompt="一句话",
                planner="architect_long",
                planner_task="展开",
                decision_id="d1",
            ),
            advance_hold=AdvanceHold(after="chapter", target_chapter=4, reason="看到第四章"),
        )
    )
    updated = book.run_meta.init(style="fantasy", provider="openrouter", model="new-model")
    assert updated.pending_steer == "保留这条干预"
    assert updated.advance_mode == "review"
    assert updated.advance_permit_chapter == 3
    assert updated.planning_tier == "long"
    assert updated.start_prompt == "一句话"
    assert updated.plan_start is not None and updated.plan_start.decision_id == "d1"
    assert updated.advance_hold is not None and updated.advance_hold.target_chapter == 4
    assert updated.model == "new-model"
    assert updated.provider == "openrouter"

    raw_path = tmp_path / "meta" / "run.json"
    raw_path.write_text(
        json.dumps({"started_at": "t", "style": "old", "model": "m", "advance_mode": "future"}),
        encoding="utf-8",
    )
    before = raw_path.read_bytes()
    reopened = Book.open(tmp_path, writable=False)
    with pytest.raises(UnsupportedAdvanceModeError):
        reopened.run_meta.init(style="x", provider="y", model="z")
    assert raw_path.read_bytes() == before


def test_reopen_is_the_only_way_out_of_complete(tmp_path: Path):
    book = Book.open(tmp_path, writable=True)
    book.progress.save(
        Progress(phase=Phase.COMPLETE, completed_chapters=[1, 2], total_chapters=2)
    )
    with pytest.raises(Exception):
        validate_phase_transition(Phase.COMPLETE, Phase.WRITING)
    rewritten = book.progress.reopen([2, 2, 1], "改结局")
    assert rewritten.phase == Phase.WRITING
    assert rewritten.flow is not None and rewritten.flow.value == "rewriting"
    assert rewritten.pending_rewrites == [2, 1]
    assert rewritten.reopened_from_complete is True
    assert rewritten.reopen_count == 0

    book.progress.save(
        Progress(phase=Phase.COMPLETE, completed_chapters=[1], reopen_count=1)
    )
    continued = book.progress.reopen_continue()
    assert continued.phase == Phase.WRITING
    assert continued.reopened_from_complete is False
    assert continued.reopen_count == 2


def test_pending_commit_rejects_other_chapter_and_backward_stage(tmp_path: Path):
    book = Book.open(tmp_path, writable=True)
    book.pending.save(PendingCommit(chapter=3, stage=CommitStage.STATE_APPLIED, draft_content="正文"))
    with pytest.raises(PendingCommitConflict, match="第 3 章"):
        book.pending.save(PendingCommit(chapter=4, stage=CommitStage.STARTED))
    with pytest.raises(PendingCommitConflict, match="不能回退"):
        book.pending.save(PendingCommit(chapter=3, stage=CommitStage.STARTED))
    moved = book.pending.save(
        PendingCommit(chapter=3, stage=CommitStage.PROGRESS_MARKED, draft_content="正文")
    )
    assert moved.stage == CommitStage.PROGRESS_MARKED
    book.pending.clear()
    assert book.pending.load() is None


def test_book_projection_and_missing_files(tmp_path: Path):
    book = Book.open(tmp_path, writable=True)
    assert book.progress.load() is None
    assert book.run_meta.load() is None
    saved = book.info.save(BookMetadata(title=" 山海 ", synopsis=" 简介 "))
    assert saved.title == "山海"
    disk = json.loads((tmp_path / "meta" / "book.json").read_text(encoding="utf-8"))
    assert disk == {"title": "山海", "synopsis": "简介"}
    assert (tmp_path / "book.md").read_text(encoding="utf-8").startswith("# 《山海》")
