"""打开一本书的目录。损坏的检查点不能当成空书。"""

from pathlib import Path

from ainovel.store.checkpoints import CheckpointStore
from ainovel.store.io import IO, mark_readonly, mark_writable
from ainovel.store.records import (
    BookInfoStore,
    PendingCommitStore,
    ProgressStore,
    RunMetaStore,
    refuse_unknown_advance_mode,
)


class Book:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.progress = ProgressStore(IO(root))
        self.run_meta = RunMetaStore(IO(root))
        self.info = BookInfoStore(IO(root))
        self.pending = PendingCommitStore(IO(root))
        self.checkpoints = CheckpointStore(IO(root))
        self.writable = False

    @classmethod
    def open(cls, root: Path | str, *, writable: bool) -> "Book":
        book = cls(Path(root))
        error = book.checkpoints.load_error()
        if error is not None:
            raise error
        if writable:
            mark_writable(book.root)
            refuse_unknown_advance_mode(book.run_meta.load())
        else:
            mark_readonly(book.root)
        book.writable = writable
        return book
