"""进度、运行意图、作品信息和在途提交。"""

from datetime import datetime, timezone
from typing import Any

from ainovel.domain.book import BookMetadata
from ainovel.domain.commit import PendingCommit, prepare_pending_commit
from ainovel.domain.progress import Progress
from ainovel.domain.run_meta import (
    ChapterAdvanceMode,
    RunMeta,
    validate_advance_control,
)
from ainovel.domain.transitions import FlowState, Phase, validate_phase_transition
from ainovel.store.io import IO


def _load_json(io: IO, relative: str) -> Any | None:
    try:
        return io.read_json(relative)
    except FileNotFoundError:
        return None


class ProgressStore:
    def __init__(self, io: IO) -> None:
        self._io = io

    def load(self) -> Progress | None:
        raw = _load_json(self._io, "meta/progress.json")
        if raw is None:
            return None
        return Progress.model_validate(raw)

    def save(self, progress: Progress) -> None:
        self._io.write_json("meta/progress.json", progress.to_disk())

    def mark_complete(self) -> Progress:
        with self._io.exclusive():
            current = self._load_unlocked() or Progress()
            validate_phase_transition(current.phase, Phase.COMPLETE)
            current.phase = Phase.COMPLETE
            current.reopened_from_complete = False
            self._io.write_json_unlocked("meta/progress.json", current.to_disk())
            return current

    def reopen(self, chapters: list[int], reason: str) -> Progress:
        """完本后改旧章。这是离开 complete 的返工出口。"""
        with self._io.exclusive():
            current = self._require_complete()
            current.phase = Phase.WRITING
            current.pending_rewrites = _normalize_rewrites(chapters, current.completed_chapters)
            current.rewrite_reason = reason
            current.flow = FlowState.REWRITING
            current.reopened_from_complete = True
            self._io.write_json_unlocked("meta/progress.json", current.to_disk())
            return current

    def reopen_continue(self) -> Progress:
        """完本后继续加结构。只回退阶段并增加重开计数。"""
        with self._io.exclusive():
            current = self._require_complete()
            current.phase = Phase.WRITING
            current.reopen_count += 1
            self._io.write_json_unlocked("meta/progress.json", current.to_disk())
            return current

    def _require_complete(self) -> Progress:
        current = self._load_unlocked()
        if current is None:
            raise ValueError("progress 未初始化")
        if current.phase != Phase.COMPLETE:
            raise ValueError(f"reopen 仅适用于已完结的书（当前 phase={current.phase}）")
        return current

    def _load_unlocked(self) -> Progress | None:
        try:
            raw = self._io.read_json_unlocked("meta/progress.json")
        except FileNotFoundError:
            return None
        return Progress.model_validate(raw)


def _normalize_rewrites(chapters: list[int], completed: list[int]) -> list[int]:
    if not chapters:
        return []
    completed_set = set(completed)
    seen: set[int] = set()
    normalized: list[int] = []
    invalid: list[int] = []
    for chapter in chapters:
        if chapter <= 0 or chapter not in completed_set:
            invalid.append(chapter)
            continue
        if chapter in seen:
            continue
        seen.add(chapter)
        normalized.append(chapter)
    if invalid:
        raise ValueError(
            f"pending_rewrites 只能包含已完成章节，非法章节：{invalid}，completed_chapters={completed}"
        )
    return normalized


class RunMetaStore:
    def __init__(self, io: IO) -> None:
        self._io = io

    def load(self) -> RunMeta | None:
        raw = _load_json(self._io, "meta/run.json")
        if raw is None:
            return None
        return RunMeta.model_validate(raw)

    def save(self, meta: RunMeta) -> None:
        self._io.write_json("meta/run.json", meta.to_disk())

    def init(self, *, style: str, provider: str, model: str) -> RunMeta:
        """刷新本次运行的模型信息，并保留已落盘的意图。"""
        with self._io.exclusive():
            existing = self._load_unlocked()
            meta = RunMeta(
                started_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                provider=provider,
                style=style,
                model=model,
            )
            if existing is not None:
                meta.pending_steer = existing.pending_steer
                meta.planning_tier = existing.planning_tier
                meta.plan_start = existing.plan_start
                meta.start_prompt = existing.start_prompt
                meta.advance_mode = existing.advance_mode
                meta.advance_permit_chapter = existing.advance_permit_chapter
                meta.advance_hold = existing.advance_hold
            if not meta.advance_mode:
                meta.advance_mode = ChapterAdvanceMode.AUTO
            validate_advance_control(meta)
            self._io.write_json_unlocked("meta/run.json", meta.to_disk())
            return meta

    def _load_unlocked(self) -> RunMeta | None:
        try:
            raw = self._io.read_json_unlocked("meta/run.json")
        except FileNotFoundError:
            return None
        return RunMeta.model_validate(raw)


class BookInfoStore:
    def __init__(self, io: IO) -> None:
        self._io = io

    def load(self) -> BookMetadata | None:
        raw = _load_json(self._io, "meta/book.json")
        if raw is None:
            return None
        book = BookMetadata.model_validate(raw).validate_required()
        return book

    def save(self, book: BookMetadata) -> BookMetadata:
        ready = book.validate_required()
        with self._io.exclusive():
            self._io.write_json_unlocked("meta/book.json", ready.to_disk())
            self._io.write_bytes_unlocked("book.md", ready.render_markdown().encode("utf-8"))
        return ready


class PendingCommitStore:
    def __init__(self, io: IO) -> None:
        self._io = io

    def load(self) -> PendingCommit | None:
        raw = _load_json(self._io, "meta/pending_commit.json")
        if raw is None:
            return None
        pending = PendingCommit.model_validate(raw)
        prepare_pending_commit(None, pending)
        return pending

    def save(self, incoming: PendingCommit) -> PendingCommit:
        with self._io.exclusive():
            existing = self._load_unlocked()
            ready = prepare_pending_commit(existing, incoming)
            self._io.write_json_unlocked("meta/pending_commit.json", ready.to_disk())
            return ready

    def clear(self) -> None:
        self._io.remove("meta/pending_commit.json")

    def _load_unlocked(self) -> PendingCommit | None:
        try:
            raw = self._io.read_json_unlocked("meta/pending_commit.json")
        except FileNotFoundError:
            return None
        pending = PendingCommit.model_validate(raw)
        prepare_pending_commit(None, pending)
        return pending


def refuse_unknown_advance_mode(meta: RunMeta | None) -> None:
    """可写打开前调用。没有 run.json 时还没有模式，允许创建。"""
    if meta is None or not meta.advance_mode:
        return
    validate_advance_control(meta)
