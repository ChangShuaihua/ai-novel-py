"""路由的读盘边界。Route 不调用这里。"""

import json
from pathlib import Path

from ainovel.domain.transitions import Phase
from ainovel.flow.model import REVIEW_INTERVAL, AggregateKind, AggregateRefresh, RouteState
from ainovel.flow.outline import check_arc_boundary, completed_arc_boundaries, repair_indexes
from ainovel.store.book import Book
from ainovel.store.paths import chapter_number


class LoadStateError(ValueError):
    """工件损坏。不能把读失败当成“还没有这个文件”。"""


def load_state(book: Book) -> RouteState:
    state = RouteState()
    state.foundation_missing = foundation_missing(book.root)
    meta = book.run_meta.load()
    if meta is not None:
        state.planning_tier = meta.planning_tier
    try:
        progress = book.progress.load()
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise LoadStateError(f"load progress: {exc}") from exc
    if progress is None:
        return state
    state.progress = progress
    state.immediate_feedback_count = _immediate_feedback_count(book.root)
    state.last_completed = progress.latest_completed()

    if progress.layered and state.last_completed > 0:
        volumes = _layered_volumes(book.root)
        for boundary in completed_arc_boundaries(volumes, state.last_completed):
            if not _has_arc_review(book.root, boundary.end_chapter):
                state.aggregate_refresh = _refresh(AggregateKind.ARC_REVIEW, boundary)
                break
            if not _file_exists(book.root / f"summaries/arc-v{boundary.volume:02d}a{boundary.arc:02d}.json"):
                state.aggregate_refresh = _refresh(AggregateKind.ARC_SUMMARY, boundary)
                break
            if boundary.is_volume_end and not _file_exists(book.root / f"summaries/vol-v{boundary.volume:02d}.json"):
                state.aggregate_refresh = _refresh(AggregateKind.VOLUME_SUMMARY, boundary)
                break
        boundary = check_arc_boundary(volumes, state.last_completed)
        state.arc_boundary = boundary
        if boundary is not None and boundary.is_arc_end:
            state.has_arc_review = _has_arc_review(book.root, state.last_completed)
            state.has_arc_summary = _file_exists(
                book.root / f"summaries/arc-v{boundary.volume:02d}a{boundary.arc:02d}.json"
            )
            if boundary.is_volume_end:
                state.has_volume_summary = _file_exists(book.root / f"summaries/vol-v{boundary.volume:02d}.json")

    if not progress.layered and state.last_completed > 0:
        completed = progress.completed_chapters
        for count in range(REVIEW_INTERVAL, len(completed) + 1, REVIEW_INTERVAL):
            chapter = completed[count - 1]
            if not _has_global_review(book.root, chapter):
                state.aggregate_refresh = AggregateRefresh(
                    kind=AggregateKind.GLOBAL_REVIEW,
                    end_chapter=chapter,
                )
                break
        if len(completed) > 0 and len(completed) % REVIEW_INTERVAL == 0:
            state.has_global_review = _has_global_review(book.root, state.last_completed)
    return state


def foundation_missing(root: Path) -> list[str]:
    missing: list[str] = []
    book = _optional_json(root / "meta" / "book.json")
    if book is None:
        missing.append("book")
    elif not isinstance(book, dict) or not str(book.get("title") or "").strip() or not str(book.get("synopsis") or "").strip():
        raise LoadStateError("load book metadata: title 和 synopsis 不能为空")
    premise = _optional_text(root / "premise.md")
    if premise is None or premise == "":
        missing.append("premise")
    outline = _optional_json(root / "outline.json")
    if not isinstance(outline, list) or len(outline) == 0:
        if outline is not None and not isinstance(outline, list):
            raise LoadStateError("load outline: outline.json 必须是数组")
        missing.append("outline")
    characters = _optional_json(root / "characters.json")
    if not isinstance(characters, list) or len(characters) == 0:
        if characters is not None and not isinstance(characters, list):
            raise LoadStateError("load characters: characters.json 必须是数组")
        missing.append("characters")
    rules = _optional_json(root / "world_rules.json")
    if not isinstance(rules, list) or len(rules) == 0:
        if rules is not None and not isinstance(rules, list):
            raise LoadStateError("load world rules: world_rules.json 必须是数组")
        missing.append("world_rules")
    layered = _optional_json(root / "layered_outline.json")
    if isinstance(layered, list) and layered:
        if _optional_json(root / "meta" / "compass.json") is None:
            missing.append("compass")
    elif layered is not None and not isinstance(layered, list):
        raise LoadStateError("load layered outline: layered_outline.json 必须是数组")
    if missing:
        return missing
    progress = _optional_json(root / "meta" / "progress.json")
    phase = ""
    if isinstance(progress, dict):
        phase = str(progress.get("phase") or "")
    if phase not in (Phase.WRITING, Phase.COMPLETE) and not (root / "meta" / "foundation_audit.json").exists():
        missing.append("foundation_audit")
    return missing


def _refresh(kind: str, boundary) -> AggregateRefresh:
    return AggregateRefresh(
        kind=kind,
        volume=boundary.volume,
        arc=boundary.arc,
        start_chapter=boundary.start_chapter,
        end_chapter=boundary.end_chapter,
    )


def _layered_volumes(root: Path) -> list[dict]:
    raw = _optional_json(root / "layered_outline.json")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise LoadStateError("load layered outline: layered_outline.json 必须是数组")
    return repair_indexes(raw)


def _immediate_feedback_count(root: Path) -> int:
    path = root / "meta" / "outline_feedback.jsonl"
    if not path.exists():
        return 0
    count = 0
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LoadStateError(f"load outline feedback line {line_no}: {exc}") from exc
        if not isinstance(item, dict):
            raise LoadStateError(f"load outline feedback line {line_no}: 必须是对象")
        summary = str(item.get("change_summary") or "").strip()
        issues = item.get("downstream_issues") or []
        if item.get("story_changed") or summary or issues:
            count += 1
    return count


def _has_arc_review(root: Path, chapter: int) -> bool:
    payload = _optional_json(root / "reviews" / f"{chapter_number(chapter)}.json")
    return isinstance(payload, dict) and payload.get("scope") == "arc"


def _has_global_review(root: Path, chapter: int) -> bool:
    payload = _optional_json(root / "reviews" / f"{chapter_number(chapter)}-global.json")
    return isinstance(payload, dict) and payload.get("scope") == "global"


def _file_exists(path: Path) -> bool:
    if not path.exists():
        return False
    _optional_json(path)
    return True


def _optional_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LoadStateError(f"parse {path.name}: {exc}") from exc


def _optional_text(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")
