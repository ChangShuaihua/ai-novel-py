"""宿主快照。界面只渲染这里的结果，不自己读书目录。"""

import json
from pathlib import Path

from ainovel.domain.transitions import Phase
from ainovel.host.report import render_report
from ainovel.importers.pipeline import ImportError, next_action
from ainovel.store.book import Book
from ainovel.store.paths import chapter_number
from ainovel.tools.files import read_json

EXCERPT_LIMIT = 160


def shelf_row(root: Path | str, *, locked: bool, lock_path: str = "") -> dict:
    """书架一行。只读作品信息和进度，不打开章节正文。"""
    directory = Path(root)
    title = ""
    phase = ""
    completed = 0
    total = 0
    try:
        book = _view(directory)
        title = _title(book)
        progress = book.progress.load()
        if progress is not None:
            phase = progress.phase.value
            completed = len(progress.completed_chapters)
            total = progress.total_chapters
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        title = ""
    return {
        "directory": str(directory),
        "title": title,
        "phase": phase,
        "completed_count": completed,
        "total_chapters": total,
        "locked": locked,
        "lock_path": lock_path if locked else "",
        "has_progress": (directory / "meta" / "progress.json").is_file(),
    }


def build_snapshot(
    root: Path | str,
    *,
    book: Book | None = None,
    running: bool = False,
    paused: bool = False,
    pause_reason: str = "",
    events: list[str] | None = None,
    latest_task: str = "",
    latest_reason: str = "",
    queued_steer: str = "",
    error: str = "",
    locked: bool = False,
    config_ready: bool = False,
    config_dir: str = "",
    findings: list | None = None,
    skeleton: list | None = None,
    exported_path: str = "",
    context_usage: str | None = None,
    listing: dict | None = None,
) -> dict:
    directory = Path(root)
    view = book if book is not None else _view(directory)
    progress = _quiet(view.progress.load)
    meta = _quiet(view.run_meta.load)
    phase = progress.phase.value if progress is not None else ""
    completed = list(progress.completed_chapters) if progress is not None else []
    chapters = _chapters(directory, completed)
    last = completed[-1] if completed else 0
    latest = next((item for item in chapters if item["chapter"] == last), None)
    hold = None
    if meta is not None and meta.advance_hold is not None:
        hold = {
            "after": meta.advance_hold.after,
            "target_chapter": meta.advance_hold.target_chapter,
            "reason": meta.advance_hold.reason,
        }
    pending = queued_steer or (meta.pending_steer if meta is not None else "")
    import_status, import_detail, import_chapters = _import_view(directory)
    report = ""
    if phase == Phase.COMPLETE.value:
        try:
            report = render_report(view)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            report = ""
    instruction = None
    if latest_task or latest_reason:
        instruction = {"task": latest_task, "reason": latest_reason}
    return {
        "directory": str(directory),
        "title": _title(view),
        "phase": phase,
        "flow": progress.flow.value if progress is not None and progress.flow is not None else "",
        "current_chapter": progress.current_chapter if progress is not None else 0,
        "next_chapter": progress.next_chapter() if progress is not None else 0,
        "completed_chapters": completed,
        "total_chapters": progress.total_chapters if progress is not None else 0,
        "total_word_count": progress.total_word_count if progress is not None else 0,
        "pending_rewrites": list(progress.pending_rewrites) if progress is not None else [],
        "latest_instruction": instruction,
        "running": running,
        "paused": paused,
        "pause_reason": pause_reason,
        "advance_mode": meta.advance_mode if meta is not None else "",
        "advance_permit_chapter": meta.advance_permit_chapter if meta is not None else 0,
        "advance_hold": hold,
        "pending_steer": pending,
        "context_usage": context_usage,
        "report": report,
        "events": list(events or []),
        "locked": locked,
        "lock_path": str(directory / ".ainovel.lock") if locked else "",
        "config_ready": config_ready,
        "config_dir": config_dir,
        "chapters": chapters,
        "latest_excerpt": _excerpt(latest["body"]) if latest is not None else "",
        "import_status": import_status,
        "import_detail": import_detail,
        "import_chapters": import_chapters,
        "findings": list(findings or []),
        "skeleton": list(skeleton or []),
        "exported_path": exported_path,
        "listing": listing,
        "error": error,
        "has_progress": (directory / "meta" / "progress.json").is_file(),
    }


def has_progress(root: Path | str) -> bool:
    return (Path(root) / "meta" / "progress.json").is_file()


def _view(root: Path) -> Book:
    """只组装读取器。这一份是只读的，不挡住正在写的那一份。"""
    book = Book(root, readonly=True)
    error = book.checkpoints.load_error()
    if error is not None:
        raise error
    return book


def _quiet(load):
    try:
        return load()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _title(book: Book) -> str:
    try:
        info = book.info.load()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return ""
    if info is None:
        return ""
    return info.title


def _chapters(root: Path, completed: list[int]) -> list[dict]:
    titles = _outline_titles(root)
    projected = []
    for number in completed:
        if number <= 0:
            continue
        path = root / "chapters" / f"{chapter_number(number)}.md"
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.strip():
            continue
        title, body = _split_heading(text, titles.get(number, ""))
        projected.append({"chapter": number, "title": title, "body": body})
    return projected


def _outline_titles(root: Path) -> dict[int, str]:
    raw = read_json(root, "layered_outline.json")
    titles: dict[int, str] = {}
    if not isinstance(raw, list):
        return titles
    cursor = 1
    for volume in raw:
        if not isinstance(volume, dict):
            continue
        for arc in volume.get("arcs") or []:
            if not isinstance(arc, dict):
                continue
            for chapter in arc.get("chapters") or []:
                if isinstance(chapter, dict):
                    title = str(chapter.get("title") or "").strip()
                    if title:
                        titles[cursor] = title
                cursor += 1
    return titles


def _split_heading(text: str, outline_title: str) -> tuple[str, str]:
    stripped = text.strip("\n")
    lines = stripped.splitlines()
    if lines and lines[0].lstrip().startswith("#"):
        title = lines[0].lstrip("#").strip() or outline_title
        body = "\n".join(lines[1:]).strip()
        return title, body or stripped
    return outline_title, stripped


def _excerpt(body: str) -> str:
    compact = body.strip()
    if len(compact) <= EXCERPT_LIMIT:
        return compact
    return compact[:EXCERPT_LIMIT].rstrip() + "…"


def _import_view(root: Path) -> tuple[str, str, list[str]]:
    workspace = root / "meta" / "import"
    if not workspace.exists():
        return "", "", []
    titles = _import_titles(workspace / "segmentation.json")
    try:
        action = next_action(root)
    except (ImportError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return "failed", _short(exc), titles
    if action == "await_confirmation":
        return "await_confirmation", "待确认切分", titles
    if action == "done":
        return "published", "导入已发布，写作尚未继续", titles
    if action == "segment":
        return "working", "正在切分", titles
    if action == "synthesize":
        return "working", "正在综合", titles
    if action == "publish":
        return "working", "正在发布", titles
    if isinstance(action, tuple) and action[0] == "analyze":
        return "working", f"正在分析第 {action[1]} 章", titles
    if action == "ingest":
        return "", "", titles
    return "working", "导入仍在进行", titles


def _import_titles(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    chapters = payload.get("payload", {}).get("chapters") if isinstance(payload, dict) else None
    if not isinstance(chapters, list):
        return []
    return [str(item.get("title") or "").strip() for item in chapters if isinstance(item, dict)]


def _short(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    if len(text) > 160:
        return text[:160] + "…"
    return text
