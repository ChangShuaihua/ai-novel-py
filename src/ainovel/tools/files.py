"""工具共用的原子写、摘要和检查点。"""

import hashlib
import json
from pathlib import Path

from ainovel.domain.checkpoint import Scope, chapter_scope, global_scope
from ainovel.store.book import Book
from ainovel.store.io import IO
from ainovel.store.paths import chapter_number


def digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def digest_text(text: str) -> str:
    return digest_bytes(text.encode("utf-8"))


def chapter_file(chapter: int, suffix: str) -> str:
    return f"{suffix}/{chapter_number(chapter)}"


def draft_path(chapter: int) -> str:
    return f"drafts/{chapter_number(chapter)}.draft.md"


def plan_path(chapter: int) -> str:
    return f"drafts/{chapter_number(chapter)}.plan.json"


def final_path(chapter: int) -> str:
    return f"chapters/{chapter_number(chapter)}.md"


def read_text(root: Path, relative: str) -> str | None:
    path = root / relative
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def read_json(root: Path, relative: str):
    text = read_text(root, relative)
    if text is None:
        return None
    return json.loads(text)


def write_text(root: Path, relative: str, content: str) -> None:
    IO(root).write_bytes(relative, content.encode("utf-8"))


def write_json(root: Path, relative: str, payload) -> None:
    IO(root).write_json(relative, payload)


def append_jsonl(root: Path, relative: str, rows: list) -> None:
    if not rows:
        return
    blob = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")
    IO(root).append_line(relative, blob)


def find_checkpoint(book: Book, scope: Scope, step: str, digest: str):
    if not digest:
        return None
    for existing in reversed(book.checkpoints.all()):
        if existing.scope.matches(scope) and existing.step == step and existing.digest == digest:
            return existing
    return None


def remember(book: Book, scope: Scope, step: str, artifact: str, digest: str) -> bool:
    """相同范围、步骤和摘要不重复写检查点。返回是否新写入。"""
    if find_checkpoint(book, scope, step, digest) is not None:
        return False
    book.checkpoints.append(scope, step, artifact, digest)
    return True


def chapter_scope_of(chapter: int) -> Scope:
    return chapter_scope(chapter)


def global_scope_of() -> Scope:
    return global_scope()
