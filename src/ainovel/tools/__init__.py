"""按名字调用工具。模型不在这一层。"""

from ainovel.store.book import Book
from ainovel.tools.context import novel_context, read_chapter
from ainovel.tools.errors import ToolArgsError
from ainovel.tools.foundation import (
    audit_foundation,
    expand_next_arc,
    resolve_outline_feedback,
    revise_outline,
    save_book,
    save_foundation,
)
from ainovel.tools.review import save_arc_summary, save_review, save_volume_summary
from ainovel.tools.writing import (
    check_consistency,
    commit_chapter,
    draft_chapter,
    edit_chapter,
    plan_chapter,
)

TOOLS = {
    "novel_context": novel_context,
    "read_chapter": read_chapter,
    "save_book": save_book,
    "save_foundation": save_foundation,
    "audit_foundation": audit_foundation,
    "plan_chapter": plan_chapter,
    "draft_chapter": draft_chapter,
    "edit_chapter": edit_chapter,
    "check_consistency": check_consistency,
    "commit_chapter": commit_chapter,
    "save_review": save_review,
    "save_arc_summary": save_arc_summary,
    "save_volume_summary": save_volume_summary,
    "expand_next_arc": expand_next_arc,
    "revise_outline": revise_outline,
    "resolve_outline_feedback": resolve_outline_feedback,
}


def call_tool(book: Book, name: str, args: dict | None = None) -> dict:
    try:
        tool = TOOLS[name]
    except KeyError as exc:
        raise ToolArgsError(f"未知工具: {name}") from exc
    return tool(book, args or {})
