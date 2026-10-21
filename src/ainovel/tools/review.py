"""审阅工具。结论只映射成流程和返工队列，不替模型打分。"""

from ainovel.domain.checkpoint import Scope, arc_scope, chapter_scope, global_scope
from ainovel.domain.transitions import FlowState, validate_flow_transition
from ainovel.flow.outline import check_arc_boundary, repair_indexes
from ainovel.store.book import Book
from ainovel.store.paths import chapter_number
from ainovel.tools.errors import ToolArgsError, ToolConflict
from ainovel.tools.files import digest_text, read_json, read_text, remember, write_json

_VERDICTS = {"accept": FlowState.WRITING, "polish": FlowState.POLISHING, "rewrite": FlowState.REWRITING}


def save_review(book: Book, args: dict) -> dict:
    chapter = int(args.get("chapter") or 0)
    scope = str(args.get("scope") or "chapter")
    verdict = str(args.get("verdict") or "")
    if chapter <= 0:
        raise ToolArgsError("chapter 必须大于 0")
    if scope not in ("chapter", "global", "arc"):
        raise ToolArgsError(f"invalid review scope: {scope!r}")
    if verdict not in _VERDICTS:
        raise ToolArgsError("verdict 只能是 accept / polish / rewrite")
    summary = str(args.get("summary") or "").strip()
    if not summary:
        raise ToolArgsError("summary 不能为空")
    issues = args.get("issues") or []
    if not isinstance(issues, list):
        raise ToolArgsError("issues 必须是数组")
    boundary = _arc_boundary(book, chapter) if scope == "arc" else None
    if scope == "arc" and (boundary is None or not boundary.is_arc_end or boundary.end_chapter != chapter):
        raise ToolConflict("弧级审阅的 chapter 必须是弧末章")
    affected: list[int] = []
    for issue in issues:
        if not isinstance(issue, dict):
            raise ToolArgsError("issue 必须是对象")
        chapters = list(issue.get("chapters") or [])
        if scope == "chapter" and not chapters:
            chapters = [chapter]
        if not chapters:
            raise ToolArgsError("issue chapters 不能为空")
        for number in chapters:
            number = int(number)
            if scope == "chapter" and number != chapter:
                raise ToolArgsError(f"章审阅的问题只能指向第 {chapter} 章")
            if scope == "global" and (number <= 0 or number > chapter):
                raise ToolArgsError(f"全局审阅的问题章节 {number} 超出 1-{chapter}")
            if scope == "arc" and boundary is not None and (number < boundary.start_chapter or number > boundary.end_chapter):
                raise ToolArgsError(f"弧级审阅的问题章节 {number} 超出 {boundary.start_chapter}-{boundary.end_chapter}")
            if issue.get("requires_change") and number not in affected:
                affected.append(number)
    affected.sort()
    if verdict == "accept" and affected:
        raise ToolArgsError("accept 不能包含 requires_change 的问题")
    if verdict in ("rewrite", "polish") and not affected:
        raise ToolArgsError(f"verdict={verdict} 至少要有一个 requires_change 的问题")
    progress = book.progress.load()
    if progress is None:
        raise ToolConflict("progress 未初始化")
    target_flow = _VERDICTS[verdict]
    if progress.flow is not None and progress.flow != target_flow:
        validate_flow_transition(progress.flow, target_flow)
    progress.flow = target_flow
    progress.pending_rewrites = [] if verdict == "accept" else affected
    progress.rewrite_reason = "" if verdict == "accept" else summary
    book.progress.save(progress)
    record = {
        "chapter": chapter,
        "scope": scope,
        "verdict": verdict,
        "summary": summary,
        "issues": issues,
        "affected_chapters": affected,
    }
    relative = _review_path(chapter, scope)
    write_json(book.root, relative, record)
    checkpoint_scope = _review_scope(scope, chapter, boundary)
    remember(book, checkpoint_scope, "review", relative, digest_text(verdict + summary))
    return {
        "saved": True,
        "chapter": chapter,
        "scope": scope,
        "verdict": verdict,
        "affected_chapters": affected,
        "next_flow": target_flow.value,
        "next_chapter": progress.next_chapter(),
        "next_step": "save_arc_summary" if scope == "arc" else "novel_context",
    }


def save_arc_summary(book: Book, args: dict) -> dict:
    volume = int(args.get("volume") or 0)
    arc = int(args.get("arc") or 0)
    summary = str(args.get("summary") or "").strip()
    if volume <= 0 or arc <= 0 or not summary:
        raise ToolArgsError("volume、arc 和 summary 都不能为空")
    end_chapter = _arc_end_chapter(book, volume, arc)
    review = read_json(book.root, f"reviews/{chapter_number(end_chapter)}.json")
    if not isinstance(review, dict) or review.get("scope") != "arc":
        raise ToolConflict(f"第 {volume} 卷第 {arc} 弧的审阅还没完成")
    payload = {
        "volume": volume,
        "arc": arc,
        "summary": summary,
        "character_snapshots": args.get("character_snapshots") or [],
        "writing_rules": args.get("writing_rules") or [],
    }
    relative = f"summaries/arc-v{volume:02d}a{arc:02d}.json"
    write_json(book.root, relative, payload)
    remember(book, arc_scope(volume, arc), "arc_summary", relative, digest_text(summary))
    return {"volume": volume, "arc": arc, "saved": True, "next_step": "save_volume_summary"}


def save_volume_summary(book: Book, args: dict) -> dict:
    volume = int(args.get("volume") or 0)
    summary = str(args.get("summary") or "").strip()
    if volume <= 0 or not summary:
        raise ToolArgsError("volume 和 summary 都不能为空")
    last_arc = _last_arc(book, volume)
    if read_text(book.root, f"summaries/arc-v{volume:02d}a{last_arc:02d}.json") is None:
        raise ToolConflict(f"第 {volume} 卷的弧摘要还没完成")
    payload = {"volume": volume, "summary": summary}
    relative = f"summaries/vol-v{volume:02d}.json"
    write_json(book.root, relative, payload)
    from ainovel.domain.checkpoint import volume_scope

    remember(book, volume_scope(volume), "volume_summary", relative, digest_text(summary))
    return {"volume": volume, "saved": True, "next_step": "novel_context"}


def _review_path(chapter: int, scope: str) -> str:
    if scope == "global":
        return f"reviews/{chapter_number(chapter)}-global.json"
    return f"reviews/{chapter_number(chapter)}.json"


def _review_scope(scope: str, chapter: int, boundary) -> Scope:
    if scope == "global":
        return global_scope()
    if scope == "arc" and boundary is not None:
        return arc_scope(boundary.volume, boundary.arc)
    return chapter_scope(chapter)


def _arc_boundary(book: Book, chapter: int):
    raw = read_json(book.root, "layered_outline.json")
    if not isinstance(raw, list):
        return None
    return check_arc_boundary(repair_indexes(raw), chapter)


def _arc_end_chapter(book: Book, volume: int, arc: int) -> int:
    raw = read_json(book.root, "layered_outline.json")
    if not isinstance(raw, list):
        raise ToolConflict("没有分层大纲")
    cursor = 1
    for item in repair_indexes(raw):
        for candidate in item.get("arcs") or []:
            chapters = candidate.get("chapters") or []
            start = cursor
            end = start + len(chapters) - 1 if chapters else start - 1
            cursor = end + 1 if chapters else cursor
            if int(item.get("index") or 0) == volume and int(candidate.get("index") or 0) == arc:
                if not chapters:
                    raise ToolConflict("未展开的弧不能写摘要")
                return end
    raise ToolConflict(f"没有第 {volume} 卷第 {arc} 弧")


def _last_arc(book: Book, volume: int) -> int:
    raw = read_json(book.root, "layered_outline.json")
    if not isinstance(raw, list):
        raise ToolConflict("没有分层大纲")
    for item in repair_indexes(raw):
        if int(item.get("index") or 0) == volume:
            arcs = item.get("arcs") or []
            if not arcs:
                raise ToolConflict(f"第 {volume} 卷没有弧")
            return int(arcs[-1].get("index") or len(arcs))
    raise ToolConflict(f"没有第 {volume} 卷")
