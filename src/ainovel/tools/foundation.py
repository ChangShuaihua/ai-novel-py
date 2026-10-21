"""规划师的设定工具。完本条件由代码校验。"""

import json

from ainovel.domain.book import BookMetadata
from ainovel.domain.checkpoint import global_scope
from ainovel.domain.run_meta import PlanningTier
from ainovel.domain.progress import Progress
from ainovel.domain.transitions import FlowState, Phase, can_transition_phase
from ainovel.flow.outline import repair_indexes
from ainovel.store.book import Book
from ainovel.tools.errors import ToolArgsError, ToolConflict
from ainovel.tools.files import digest_text, read_json, read_text, remember, write_json, write_text

_TYPES = {
    "premise",
    "outline",
    "layered_outline",
    "characters",
    "world_rules",
    "append_volume",
    "update_compass",
    "complete_book",
}
_SCALES = {PlanningTier.SHORT, PlanningTier.MID, PlanningTier.LONG}


def save_book(book: Book, args: dict) -> dict:
    saved = book.info.save(BookMetadata(title=str(args.get("title") or ""), synopsis=str(args.get("synopsis") or "")))
    remember(book, global_scope(), "book", "meta/book.json", digest_text(saved.title + "\n" + saved.synopsis))
    return {"title": saved.title, "synopsis": saved.synopsis, "next_step": "save_foundation"}


def save_foundation(book: Book, args: dict) -> dict:
    kind = str(args.get("type") or "")
    if kind not in _TYPES:
        raise ToolArgsError(
            "unknown type, expected premise/outline/layered_outline/characters/world_rules/"
            "append_volume/update_compass/complete_book"
        )
    _apply_scale(book, args.get("scale"))
    if kind == "premise":
        content = args.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ToolArgsError("premise 的 content 必须是 Markdown 字符串")
        write_text(book.root, "premise.md", content)
        _advance_phase(book, Phase.PREMISE)
    elif kind == "outline":
        entries = _as_list(args.get("content"), "outline")
        write_json(book.root, "outline.json", entries)
        _set_total_chapters(book, len(entries), layered=False)
        _advance_phase(book, Phase.OUTLINE)
    elif kind == "layered_outline":
        volumes = repair_indexes(_as_list(args.get("content"), "layered_outline"))
        write_json(book.root, "layered_outline.json", volumes)
        _set_total_chapters(book, _expanded_count(volumes), layered=True)
        _advance_phase(book, Phase.OUTLINE)
    elif kind == "characters":
        characters = _as_list(args.get("content"), "characters")
        write_json(book.root, "characters.json", characters)
        write_text(book.root, "characters.md", _render_characters(characters))
    elif kind == "world_rules":
        write_json(book.root, "world_rules.json", _as_list(args.get("content"), "world_rules"))
    elif kind == "append_volume":
        _require_reason(args)
        volumes = _append_volume(book, args.get("content"))
        write_json(book.root, "layered_outline.json", volumes)
        _consume_immediate_feedback(book)
    elif kind == "update_compass":
        compass = args.get("content")
        if not isinstance(compass, dict):
            raise ToolArgsError("update_compass 的 content 必须是对象")
        progress = book.progress.load()
        stored = dict(compass)
        stored["last_updated"] = progress.latest_completed() if progress is not None else 0
        write_json(book.root, "meta/compass.json", stored)
        _consume_immediate_feedback(book)
    elif kind == "complete_book":
        _require_reason(args)
        _complete_book(book)
    remember(book, global_scope(), kind, _artifact(kind), digest_text(json.dumps(args.get("content"), ensure_ascii=False, sort_keys=True)))
    return {"type": kind, "saved": True, "next_step": "audit_foundation" if kind != "complete_book" else "novel_context"}


def audit_foundation(book: Book, args: dict) -> dict:
    from ainovel.flow.load import foundation_missing

    missing = [item for item in foundation_missing(book.root) if item != "foundation_audit"]
    if missing:
        raise ToolConflict("基础设定仍缺：" + "、".join(missing))
    record = {"notes": str(args.get("notes") or ""), "fingerprint": _fingerprint(book)}
    write_json(book.root, "meta/foundation_audit.json", record)
    remember(book, global_scope(), "foundation_audit", "meta/foundation_audit.json", digest_text(record["fingerprint"]))
    progress = book.progress.load() or Progress(phase=Phase.WRITING, flow=FlowState.WRITING)
    if progress.phase not in (Phase.WRITING, Phase.COMPLETE):
        progress.phase = Phase.WRITING
        if progress.flow is None:
            progress.flow = FlowState.WRITING
        book.progress.save(progress)
    return {
        "audited": True,
        "foundation_ready": True,
        "phase": Phase.WRITING.value,
        "fingerprint": record["fingerprint"],
        "next_step": "novel_context",
    }


def expand_next_arc(book: Book, args: dict) -> dict:
    title = str(args.get("title") or "").strip()
    goal = str(args.get("goal") or "").strip()
    chapters = args.get("chapters")
    if not title or not goal or not isinstance(chapters, list) or not chapters:
        raise ToolArgsError("展开弧必须提供 title、goal 和至少一章")
    raw = read_json(book.root, "layered_outline.json")
    if not isinstance(raw, list) or not raw:
        raise ToolConflict("没有分层大纲，不能展开下一弧")
    volumes = repair_indexes(raw)
    target = None
    for volume in volumes:
        for arc in volume.get("arcs") or []:
            if not (arc.get("chapters") or []):
                target = arc
                break
        if target is not None:
            break
    if target is None:
        raise ToolConflict("没有待展开的骨架弧")
    target["title"] = title
    target["goal"] = goal
    target["chapters"] = chapters
    target["estimated_chapters"] = 0
    write_json(book.root, "layered_outline.json", volumes)
    _consume_immediate_feedback(book)
    remember(book, global_scope(), "expand_next_arc", "layered_outline.json", digest_text(title + goal))
    return {
        "volume": _volume_of(volumes, target),
        "arc": int(target.get("index") or 0),
        "expanded": True,
        "next_step": "novel_context",
    }


def revise_outline(book: Book, args: dict) -> dict:
    entries = _as_list(args.get("content"), "outline")
    write_json(book.root, "outline.json", entries)
    removed = _consume_immediate_feedback(book)
    remember(book, global_scope(), "outline", "outline.json", digest_text(json.dumps(entries, ensure_ascii=False)))
    return {"revised": True, "consumed_feedback": removed, "next_step": "novel_context"}


def resolve_outline_feedback(book: Book, _args: dict) -> dict:
    removed = _consume_immediate_feedback(book)
    remember(
        book,
        global_scope(),
        "resolve_outline_feedback",
        "meta/outline_feedback_resolution.json",
        digest_text(str(removed)),
    )
    return {"resolved": True, "consumed_feedback": removed, "next_step": "novel_context"}


def _complete_book(book: Book) -> None:
    progress = book.progress.load()
    if progress is None:
        raise ToolConflict("progress 未初始化")
    if progress.phase != Phase.WRITING:
        raise ToolConflict(f"complete_book 仅在 writing 阶段可调用（当前 phase={progress.phase}）")
    if progress.pending_rewrites:
        raise ToolConflict(f"还有 {len(progress.pending_rewrites)} 章在返工队列中，处理完再调 complete_book")
    if not progress.completed_chapters:
        raise ToolConflict("一章未写不可完本")
    if progress.layered and _has_skeleton(book):
        raise ToolConflict("还有未展开的骨架弧，不可完本")
    outlined = _outlined_count(book, progress.layered)
    if progress.next_chapter() <= outlined:
        raise ToolConflict(f"大纲内还有未写章节（下一章 {progress.next_chapter()}/已细化 {outlined}），不可完本")
    if not progress.layered and progress.total_chapters > 0 and progress.next_chapter() <= progress.total_chapters:
        raise ToolConflict(f"大纲内还有未写章节（下一章 {progress.next_chapter()}/共 {progress.total_chapters}），不可完本")
    compass = read_json(book.root, "meta/compass.json")
    threads = []
    if isinstance(compass, dict):
        threads = [item for item in compass.get("open_threads") or [] if str(item).strip()]
    if threads:
        raise ToolConflict(
            f"compass 还有 {len(threads)} 条活跃长线未收束（如：{threads[0]}），不可完本。"
            "确认已全部收束请先 update_compass 清空 open_threads"
        )
    book.progress.mark_complete()


def _append_volume(book: Book, content) -> list:
    if not isinstance(content, dict):
        raise ToolArgsError("append_volume 的 content 必须是卷对象")
    raw = read_json(book.root, "layered_outline.json")
    volumes = repair_indexes(raw) if isinstance(raw, list) else []
    nxt = max((int(item.get("index") or 0) for item in volumes), default=0) + 1
    volume = dict(content)
    volume.pop("index", None)
    volume["index"] = nxt
    volume["final"] = bool(content.get("final"))
    arcs = []
    for arc_index, arc in enumerate(volume.get("arcs") or [], start=1):
        if not isinstance(arc, dict):
            raise ToolArgsError("卷内的弧必须是对象")
        copied = dict(arc)
        copied.pop("index", None)
        copied["index"] = arc_index
        arcs.append(copied)
    volume["arcs"] = arcs
    volumes.append(volume)
    return volumes


def _apply_scale(book: Book, scale) -> None:
    if scale in (None, ""):
        return
    if scale not in _SCALES:
        raise ToolArgsError("scale 只允许 short / mid / long")
    meta = book.run_meta.load()
    if meta is None:
        from ainovel.domain.run_meta import RunMeta

        meta = RunMeta(style="", model="", advance_mode="auto", planning_tier=str(scale))
    else:
        meta.planning_tier = str(scale)
    book.run_meta.save(meta)


def _advance_phase(book: Book, target: Phase) -> None:
    progress = book.progress.load()
    if progress is None:
        from ainovel.domain.progress import Progress

        progress = Progress(phase=target)
        book.progress.save(progress)
        return
    if progress.phase == target:
        return
    if not can_transition_phase(progress.phase, target):
        return
    progress.phase = target
    book.progress.save(progress)


def _set_total_chapters(book: Book, total: int, *, layered: bool) -> None:
    progress = book.progress.load()
    if progress is None:
        return
    progress.total_chapters = total
    progress.layered = layered
    book.progress.save(progress)


def _as_list(content, label: str) -> list:
    if not isinstance(content, list):
        raise ToolArgsError(f"{label} 的 content 必须是数组")
    return content


def _require_reason(args: dict) -> None:
    reason = args.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ToolArgsError("reason 不能为空")


def _consume_immediate_feedback(book: Book) -> int:
    text = read_text(book.root, "meta/outline_feedback.jsonl")
    if not text:
        return 0
    kept = []
    removed = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        summary = str(item.get("change_summary") or "").strip() if isinstance(item, dict) else ""
        issues = item.get("downstream_issues") if isinstance(item, dict) else None
        if isinstance(item, dict) and (item.get("story_changed") or summary or issues):
            removed += 1
            continue
        kept.append(line)
    write_text(book.root, "meta/outline_feedback.jsonl", ("\n".join(kept) + "\n") if kept else "")
    write_json(book.root, "meta/outline_feedback_resolution.json", {"consumed": removed})
    return removed


def _render_characters(characters: list) -> str:
    lines = ["# 角色", ""]
    for item in characters:
        if isinstance(item, dict):
            lines.append(f"- {item.get('name') or '未命名'}：{item.get('role') or ''}")
    return "\n".join(lines) + "\n"


def _artifact(kind: str) -> str:
    return {
        "premise": "premise.md",
        "outline": "outline.json",
        "layered_outline": "layered_outline.json",
        "characters": "characters.json",
        "world_rules": "world_rules.json",
        "append_volume": "layered_outline.json",
        "update_compass": "meta/compass.json",
        "complete_book": "meta/progress.json",
    }[kind]


def _fingerprint(book: Book) -> str:
    chunks = []
    for relative in ("meta/book.json", "premise.md", "outline.json", "characters.json", "world_rules.json"):
        chunks.append(read_text(book.root, relative) or "")
    return digest_text("\n".join(chunks))


def _has_skeleton(book: Book) -> bool:
    raw = read_json(book.root, "layered_outline.json")
    if not isinstance(raw, list):
        return False
    for volume in raw:
        for arc in volume.get("arcs") or []:
            if not (arc.get("chapters") or []):
                return True
    return False


def _outlined_count(book: Book, layered: bool) -> int:
    if layered:
        return _expanded_count(read_json(book.root, "layered_outline.json") or [])
    outline = read_json(book.root, "outline.json")
    return len(outline) if isinstance(outline, list) else 0


def _expanded_count(volumes) -> int:
    total = 0
    if not isinstance(volumes, list):
        return 0
    for volume in volumes:
        for arc in volume.get("arcs") or []:
            total += len(arc.get("chapters") or [])
    return total


def _volume_of(volumes: list, target: dict) -> int:
    for volume in volumes:
        if target in (volume.get("arcs") or []):
            return int(volume.get("index") or 0)
    return 0
