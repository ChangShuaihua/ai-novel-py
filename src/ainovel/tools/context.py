"""读工具。不改文件，不写检查点。"""

from ainovel.domain.context import context_profile
from ainovel.flow.load import foundation_missing
from ainovel.flow.outline import check_arc_boundary, repair_indexes
from ainovel.store.book import Book
from ainovel.store.paths import chapter_number
from ainovel.tools.errors import ToolArgsError, ToolConflict
from ainovel.tools.files import final_path, read_json, read_text


def novel_context(book: Book, args: dict) -> dict:
    progress = book.progress.load()
    total = progress.total_chapters if progress is not None else 0
    profile = context_profile(total)
    chapter = int(args.get("chapter") or 0)
    volume = args.get("volume")
    arc = args.get("arc")
    payload = {
        "foundation_status": {"missing": foundation_missing(book.root)},
        "user_rules": read_json(book.root, "meta/user_rules.json"),
        "summary_window": profile.summary_window,
        "layered": profile.layered,
        "related_chapters": _related(book, total) if total > 30 else [],
    }
    if volume is not None and arc is not None:
        payload["arc"] = _arc_view(book, int(volume), int(arc))
        payload["next_step"] = "save_foundation"
        return payload
    if chapter > 0:
        payload["chapter"] = chapter
        payload["recent_summaries"] = _recent_summaries(book, chapter, profile.summary_window)
        payload["next_outline"] = _outline_entry(book, chapter + 1)
        payload["next_step"] = "read_chapter" if chapter > 1 else "plan_chapter"
    else:
        payload["outline_feedback"] = _feedback(book)
        payload["next_step"] = "save_book"
    return payload


def read_chapter(book: Book, args: dict) -> dict:
    chapter = _chapter(args)
    text = read_text(book.root, final_path(chapter))
    if not text:
        raise ToolConflict(f"第 {chapter} 章终稿不存在")
    return {"chapter": chapter, "content": text, "next_step": "plan_chapter"}


def _chapter(args: dict) -> int:
    try:
        chapter = int(args["chapter"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolArgsError("chapter 必须是正整数") from exc
    if chapter <= 0:
        raise ToolArgsError("chapter 必须是正整数")
    return chapter


def _recent_summaries(book: Book, chapter: int, window: int) -> list[dict]:
    rows = []
    start = max(1, chapter - window)
    for number in range(start, chapter):
        payload = read_json(book.root, f"summaries/{chapter_number(number)}.json")
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _outline_entry(book: Book, chapter: int):
    outline = read_json(book.root, "outline.json")
    if not isinstance(outline, list):
        return None
    for entry in outline:
        if isinstance(entry, dict) and int(entry.get("chapter") or 0) == chapter:
            return entry
    return None


def _feedback(book: Book) -> list[dict]:
    text = read_text(book.root, "meta/outline_feedback.jsonl")
    if not text:
        return []
    rows = []
    for line in text.splitlines():
        if line.strip():
            rows.append(json_line(line))
    return rows


def json_line(line: str) -> dict:
    import json

    payload = json.loads(line)
    if not isinstance(payload, dict):
        raise ToolConflict("大纲反馈必须是对象")
    return payload


def _related(book: Book, _total: int) -> list[dict]:
    found: list[dict] = []
    for kind, relative in (
        ("foreshadow", "meta/foreshadow.jsonl"),
        ("appearance", "meta/appearances.jsonl"),
        ("state_change", "meta/state_changes.jsonl"),
        ("relation", "meta/relations.jsonl"),
    ):
        text = read_text(book.root, relative)
        if not text:
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            item = json_line(line)
            chapter = int(item.get("chapter") or 0)
            if chapter > 0:
                found.append({"kind": kind, "chapter": chapter, "reason": item.get("reason") or kind})
    return found


def _arc_view(book: Book, volume: int, arc: int) -> dict:
    raw = read_json(book.root, "layered_outline.json")
    volumes = repair_indexes(raw) if isinstance(raw, list) else []
    for item in volumes:
        if int(item.get("index") or 0) != volume:
            continue
        for candidate in item.get("arcs") or []:
            if int(candidate.get("index") or 0) != arc:
                continue
            chapters = candidate.get("chapters") or []
            if chapters:
                return {"volume": volume, "arc": arc, "expanded": True, "chapters": chapters}
            return {
                "volume": volume,
                "arc": arc,
                "expanded": False,
                "title": candidate.get("title") or "",
                "goal": candidate.get("goal") or "",
            }
    boundary = check_arc_boundary(volumes, 1)
    raise ToolConflict(f"没有第 {volume} 卷第 {arc} 弧" if boundary is not None or volumes else f"没有第 {volume} 卷第 {arc} 弧")
