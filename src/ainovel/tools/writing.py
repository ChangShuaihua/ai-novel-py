"""写作者工具。顺序由前置条件卡住，提交用冻结的在途意图恢复。"""

from ainovel.domain.checkpoint import chapter_scope
from ainovel.domain.commit import CommitStage, PendingCommit
from ainovel.domain.progress import Progress
from ainovel.domain.transitions import FlowState, Phase
from ainovel.flow.model import should_review
from ainovel.flow.outline import check_arc_boundary, repair_indexes
from ainovel.store.book import Book
from ainovel.tools.context import _chapter
from ainovel.tools.errors import ToolArgsError, ToolConflict
from ainovel.tools.files import (
    digest_text,
    replace_chapter_rows,
    draft_path,
    final_path,
    find_checkpoint,
    plan_path,
    read_json,
    read_text,
    remember,
    write_json,
    write_text,
)


def plan_chapter(book: Book, args: dict) -> dict:
    chapter = _chapter(args)
    goal = _required_text(args, "goal")
    payload = {
        "chapter": chapter,
        "goal": goal,
        "conflict": str(args.get("conflict") or ""),
        "emotion": str(args.get("emotion") or ""),
        "characters": list(args.get("characters") or []),
    }
    encoded = digest_text(str(payload))
    if find_checkpoint(book, chapter_scope(chapter), "plan", encoded) is None:
        write_json(book.root, plan_path(chapter), payload)
        remember(book, chapter_scope(chapter), "plan", plan_path(chapter), encoded)
    return {"chapter": chapter, "saved": True, "next_step": "draft_chapter"}


def draft_chapter(book: Book, args: dict) -> dict:
    chapter = _chapter(args)
    if read_text(book.root, plan_path(chapter)) is None:
        raise ToolConflict(f"第 {chapter} 章还没有计划，不能起草")
    content = args.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ToolArgsError("content 不能为空")
    digest = digest_text(content)
    if find_checkpoint(book, chapter_scope(chapter), "draft", digest) is None:
        write_text(book.root, draft_path(chapter), content)
        remember(book, chapter_scope(chapter), "draft", draft_path(chapter), digest)
    return {"chapter": chapter, "saved": True, "next_step": "check_consistency"}


def edit_chapter(book: Book, args: dict) -> dict:
    chapter = _chapter(args)
    progress = _require_progress(book)
    if chapter not in progress.completed_chapters:
        raise ToolConflict(f"第 {chapter} 章尚未完成，不能定点修改")
    if not progress.pending_rewrites or progress.pending_rewrites[0] != chapter:
        raise ToolConflict(f"第 {chapter} 章不在返工队列队首")
    content = args.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ToolArgsError("content 不能为空")
    digest = digest_text(content)
    if find_checkpoint(book, chapter_scope(chapter), "edit", digest) is None:
        write_text(book.root, draft_path(chapter), content)
        remember(book, chapter_scope(chapter), "edit", draft_path(chapter), digest)
    return {"chapter": chapter, "saved": True, "next_step": "check_consistency"}


def check_consistency(book: Book, args: dict) -> dict:
    chapter = _chapter(args)
    draft = read_text(book.root, draft_path(chapter))
    if draft is None:
        raise ToolConflict(f"第 {chapter} 章还没有草稿，不能做一致性检查")
    names = _character_names(book)
    missing = [name for name in names if name and name not in draft]
    digest = digest_text(draft)
    remember(book, chapter_scope(chapter), "consistency_check", "", digest)
    return {
        "chapter": chapter,
        "consistent": not missing,
        "missing_characters": missing,
        "next_step": "commit_chapter",
    }


def commit_chapter(book: Book, args: dict) -> dict:
    chapter = _chapter(args)
    pending = book.pending.load()
    if pending is not None and pending.chapter != chapter:
        raise ToolConflict(
            f"存在未恢复的章节提交：第 {pending.chapter} 章（阶段 {pending.stage}），请先恢复或重新提交该章"
        )
    if pending is None:
        replay = _replay_stable_commit(book, chapter)
        if replay is not None:
            final = read_text(book.root, final_path(chapter)) or ""
            from ainovel.stylestats import index_for

            index_for(book).upsert(book, chapter, final)
            return replay
        pending = _freeze_new_commit(book, chapter, args)
    return _resume(book, pending)


def _replay_stable_commit(book: Book, chapter: int) -> dict | None:
    progress = book.progress.load()
    if progress is None or chapter not in progress.completed_chapters:
        return None
    if chapter in progress.pending_rewrites:
        return None
    final = read_text(book.root, final_path(chapter))
    if not final:
        return None
    if find_checkpoint(book, chapter_scope(chapter), "commit", digest_text(final)) is None:
        return None
    last = read_json(book.root, "meta/last_commit.json")
    if isinstance(last, dict) and int(last.get("chapter") or 0) == chapter:
        return last
    return None


def _freeze_new_commit(book: Book, chapter: int, args: dict) -> PendingCommit:
    progress = _require_progress(book)
    _require_commit_target(progress, chapter)
    draft = read_text(book.root, draft_path(chapter))
    if draft is None or not draft.strip():
        raise ToolConflict(f"第 {chapter} 章没有可提交的草稿")
    if find_checkpoint(book, chapter_scope(chapter), "consistency_check", digest_text(draft)) is None:
        raise ToolConflict(f"第 {chapter} 章尚未做一致性检查，不能提交")
    payload = {
        "chapter": chapter,
        "summary": _required_text(args, "summary"),
        "hook_type": str(args.get("hook_type") or ""),
        "dominant_strand": str(args.get("dominant_strand") or ""),
        "timeline": list(args.get("timeline") or []),
        "foreshadow": list(args.get("foreshadow") or []),
        "relations": list(args.get("relations") or []),
        "state_changes": list(args.get("state_changes") or []),
    }
    pending = PendingCommit(
        chapter=chapter,
        stage=CommitStage.STARTED,
        payload=payload,
        draft_content=draft,
        summary=payload["summary"],
        hook_type=payload["hook_type"],
        dominant_strand=payload["dominant_strand"],
        rewrite=chapter in progress.completed_chapters,
    )
    return book.pending.save(pending)


def _resume(book: Book, pending: PendingCommit) -> dict:
    """从当前阶段往后做。已冻结的正文和参数不会被新调用覆盖。"""
    stage = pending.stage
    if stage == CommitStage.STARTED:
        _apply_state(book, pending)
        pending.stage = CommitStage.STATE_APPLIED
        pending = book.pending.save(pending)
        stage = pending.stage
    if stage == CommitStage.STATE_APPLIED:
        result = _mark_progress(book, pending)
        pending.stage = CommitStage.PROGRESS_MARKED
        pending.output = result
        pending = book.pending.save(pending)
        stage = pending.stage
    if stage == CommitStage.PROGRESS_MARKED:
        result = dict(pending.output or _result_from_pending(book, pending))
        write_json(book.root, "meta/last_commit.json", result)
        remember(
            book,
            chapter_scope(pending.chapter),
            "commit",
            final_path(pending.chapter),
            digest_text(pending.draft_content),
        )
        write_json(book.root, f"summaries/{_summary_name(pending.chapter)}", {
            "chapter": pending.chapter,
            "summary": pending.summary,
        })
        pending.stage = CommitStage.SIGNAL_SAVED
        pending.output = result
        pending = book.pending.save(pending)
        stage = pending.stage
    if stage == CommitStage.SIGNAL_SAVED:
        result = dict(pending.output or {})
        book.pending.clear()
        result["next_step"] = "novel_context"
        return result
    raise ToolConflict(f"pending commit 阶段非法: {stage!r}")


def _apply_state(book: Book, pending: PendingCommit) -> None:
    write_text(book.root, final_path(pending.chapter), pending.draft_content)
    payload = pending.payload if isinstance(pending.payload, dict) else {}
    for relative, key in (
        ("timeline.jsonl", "timeline"),
        ("meta/foreshadow.jsonl", "foreshadow"),
        ("meta/relations.jsonl", "relations"),
        ("meta/state_changes.jsonl", "state_changes"),
    ):
        replace_chapter_rows(book.root, relative, pending.chapter, _tagged(payload.get(key), pending.chapter))


def _mark_progress(book: Book, pending: PendingCommit) -> dict:
    progress = _require_progress(book)
    words = len(pending.draft_content)
    previous = progress.chapter_word_counts.get(pending.chapter, 0)
    if pending.chapter not in progress.completed_chapters:
        progress.completed_chapters.append(pending.chapter)
    progress.chapter_word_counts[pending.chapter] = words
    progress.total_word_count += words - previous
    progress.current_chapter = pending.chapter
    progress.in_progress_chapter = 0
    _set_history(progress.strand_history, progress.completed_chapters, pending.chapter, pending.dominant_strand)
    _set_history(progress.hook_history, progress.completed_chapters, pending.chapter, pending.hook_type)
    if pending.chapter in progress.pending_rewrites:
        progress.pending_rewrites = [item for item in progress.pending_rewrites if item != pending.chapter]
        progress.flow = progress.flow if progress.pending_rewrites else FlowState.WRITING
    elif progress.flow is None:
        progress.flow = FlowState.WRITING
    boundary = _boundary(book, pending.chapter) if progress.layered else None
    if boundary is not None:
        progress.current_volume = boundary.volume
        progress.current_arc = boundary.arc
    if progress.phase != Phase.WRITING:
        progress.phase = Phase.WRITING
    book.progress.save(progress)
    return _result_from_pending(book, pending, progress=progress, boundary=boundary)


def _result_from_pending(book: Book, pending: PendingCommit, progress: Progress | None = None, boundary=None) -> dict:
    progress = progress or _require_progress(book)
    if boundary is None and progress.layered:
        boundary = _boundary(book, pending.chapter)
    due, _reason = should_review(len(progress.completed_chapters))
    result = {
        "chapter": pending.chapter,
        "committed": True,
        "word_count": len(pending.draft_content),
        "next_chapter": progress.next_chapter(),
        "flow": progress.flow.value if progress.flow else FlowState.WRITING.value,
        "arc_end": bool(boundary and boundary.is_arc_end),
        "volume_end": bool(boundary and boundary.is_volume_end),
        "needs_expansion": bool(boundary and boundary.needs_expansion),
        "review_required": (not progress.layered) and due,
        "book_complete": progress.phase == Phase.COMPLETE,
        "rule_violations": _rule_violations(book, pending.draft_content),
        "summary": pending.summary,
    }
    from ainovel.stylestats import index_for

    index_for(book).upsert(book, pending.chapter, pending.draft_content)
    return result


def _set_history(history: list[str], completed: list[int], chapter: int, value: str) -> None:
    """一章一个位置。返工和提交重放都改这一格，不在末尾再加一条。"""
    if not value or chapter not in completed:
        return
    index = completed.index(chapter)
    if index < len(history):
        history[index] = value
        return
    if index > len(history):
        history.extend([""] * (index - len(history)))
    history.append(value)


def _require_commit_target(progress: Progress, chapter: int) -> None:
    if progress.phase not in (Phase.WRITING, Phase.OUTLINE):
        raise ToolConflict(f"当前阶段 {progress.phase} 不能提交章节")
    if progress.pending_rewrites:
        if progress.pending_rewrites[0] != chapter:
            raise ToolConflict(f"返工队列队首是第 {progress.pending_rewrites[0]} 章")
        return
    if chapter in progress.completed_chapters:
        raise ToolConflict(f"第 {chapter} 章已完成，且不在返工队列中")
    expected = progress.next_chapter()
    if chapter != expected:
        raise ToolConflict(f"正常续写只能提交下一章 {expected}，收到第 {chapter} 章")


def _rule_violations(book: Book, text: str) -> list[dict]:
    from ainovel.rules import check_text, load_snapshot

    return check_text(text, load_snapshot(book.root))


def _require_progress(book: Book) -> Progress:
    progress = book.progress.load()
    if progress is None:
        raise ToolConflict("progress 未初始化")
    return progress


def _required_text(args: dict, key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolArgsError(f"{key} 不能为空")
    return value.strip()


def _character_names(book: Book) -> list[str]:
    raw = read_json(book.root, "characters.json")
    if not isinstance(raw, list):
        return []
    return [str(item.get("name") or "") for item in raw if isinstance(item, dict)]


def _tagged(rows, chapter: int) -> list[dict]:
    tagged = []
    for row in rows or []:
        if isinstance(row, dict):
            item = dict(row)
            item.setdefault("chapter", chapter)
            tagged.append(item)
    return tagged


def _boundary(book: Book, chapter: int):
    raw = read_json(book.root, "layered_outline.json")
    if not isinstance(raw, list):
        return None
    return check_arc_boundary(repair_indexes(raw), chapter)


def _summary_name(chapter: int) -> str:
    from ainovel.store.paths import chapter_number

    return f"{chapter_number(chapter)}.json"
