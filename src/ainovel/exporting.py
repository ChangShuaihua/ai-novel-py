"""只读导出。不改进度，不触发路由。"""

from pathlib import Path

from ainovel.store.book import Book
from ainovel.store.paths import chapter_number


def export_txt(root: Path | str, dest: Path | str) -> Path:
    book_root = Path(root)
    target = Path(dest)
    book = Book.open(book_root, writable=False)
    progress = book.progress.load()
    if progress is None or not progress.completed_chapters:
        raise ValueError("尚无已完成章节，无内容可导出")
    info = None
    try:
        info = book.info.load()
    except ValueError:
        info = None
    title = info.title if info is not None else ""
    chunks = [f"《{title}》\n\n"] if title else []
    for index, chapter in enumerate(progress.completed_chapters):
        path = book_root / "chapters" / f"{chapter_number(chapter)}.md"
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            raise ValueError(f"progress 标记第 {chapter} 章已完成，但正文缺失或为空")
        body = path.read_text(encoding="utf-8").strip()
        chunks.append(f"第 {chapter} 章\n\n{body}")
        if index < len(progress.completed_chapters) - 1:
            chunks.append("\n\n\n")
        else:
            chunks.append("\n")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(chunks), encoding="utf-8")
    return target
