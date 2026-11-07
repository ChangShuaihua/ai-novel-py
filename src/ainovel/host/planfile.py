"""当前任务计划。一份文件，完成或作废后删除。不是任务队列。"""

from ainovel.store.book import Book
from ainovel.store.io import IO

_RELATIVE = "meta/plan.json"


def load_plan(book: Book) -> dict | None:
    path = book.root / "meta" / "plan.json"
    if not path.is_file():
        return None
    payload = IO(book.root).read_json(_RELATIVE)
    if not isinstance(payload, dict):
        return None
    return payload


def save_plan(book: Book, plan: dict) -> None:
    IO(book.root).write_json(_RELATIVE, plan)


def clear_plan(book: Book) -> None:
    IO(book.root).remove(_RELATIVE)
