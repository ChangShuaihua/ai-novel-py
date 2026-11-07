"""僵局计数。写在书目录里，换一次进程也不会从 1 重新数。"""

from ainovel.store.book import Book
from ainovel.store.io import IO

_RELATIVE = "meta/stall.json"


def load_stall(book: Book) -> dict | None:
    path = book.root / "meta" / "stall.json"
    if not path.is_file():
        return None
    payload = IO(book.root).read_json(_RELATIVE)
    if not isinstance(payload, dict):
        return None
    return payload


def save_stall(book: Book, key: str, repeats: int) -> None:
    IO(book.root).write_json(_RELATIVE, {"key": key, "repeats": repeats})
