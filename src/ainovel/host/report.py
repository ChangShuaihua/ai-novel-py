"""完本报告只读已有事实。"""

import json
from pathlib import Path

from ainovel.store.book import Book


def render_report(book: Book) -> str:
    progress = book.progress.load()
    chapters = list(progress.completed_chapters) if progress is not None else []
    words = progress.total_word_count if progress is not None else 0
    volume = progress.current_volume if progress is not None else 0
    arc = progress.current_arc if progress is not None else 0
    threads = _open_threads(book.root)
    lines = [
        "完本报告",
        f"章数：{len(chapters)}",
        f"字数：{words}",
        f"卷：{volume}",
        f"弧：{arc}",
        f"未收伏笔：{len(threads)}",
    ]
    if threads:
        lines.append("长线：" + "、".join(threads))
    return "\n".join(lines)


def _open_threads(root: Path) -> list[str]:
    path = root / "meta" / "compass.json"
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    return [str(item) for item in payload.get("open_threads") or [] if str(item).strip()]
