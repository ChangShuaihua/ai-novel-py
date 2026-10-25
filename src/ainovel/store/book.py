"""打开一本书的目录。损坏的检查点不能当成空书。"""

from pathlib import Path

from ainovel.store.checkpoints import CheckpointStore
from ainovel.store.io import IO
from ainovel.store.records import (
    BookInfoStore,
    PendingCommitStore,
    ProgressStore,
    RunMetaStore,
    refuse_unknown_advance_mode,
)


class Book:
    def __init__(self, root: Path, *, readonly: bool = False) -> None:
        self.root = root
        self.progress = ProgressStore(IO(root, readonly=readonly))
        self.run_meta = RunMetaStore(IO(root, readonly=readonly))
        self.info = BookInfoStore(IO(root, readonly=readonly))
        self.pending = PendingCommitStore(IO(root, readonly=readonly))
        self.checkpoints = CheckpointStore(IO(root, readonly=readonly))
        self.writable = not readonly

    @classmethod
    def open(cls, root: Path | str, *, writable: bool) -> "Book":
        book = cls(Path(root), readonly=not writable)
        error = book.checkpoints.load_error()
        if error is not None:
            raise error
        if writable:
            refuse_unknown_advance_mode(book.run_meta.load())
        return book
