"""单文件原子写。失败时保留旧内容。"""

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


class ReadOnlyError(PermissionError):
    """这本书是只读打开的。诊断和导出不能写回。"""


_READONLY_ROOTS: set[str] = set()


def mark_readonly(root: Path) -> None:
    _READONLY_ROOTS.add(str(Path(root).resolve()))


def mark_writable(root: Path) -> None:
    _READONLY_ROOTS.discard(str(Path(root).resolve()))


class IO:
    """一本书目录上的读写锁。子存储可以各持一份，锁不跨目录。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.RLock()

    def _refuse_when_readonly(self) -> None:
        if str(self.root.resolve()) in _READONLY_ROOTS:
            raise ReadOnlyError(f"只读打开，拒绝写入 {self.root}")

    def exclusive(self) -> threading.RLock:
        return self._lock

    def path(self, relative: str) -> Path:
        return self.root / relative

    def read_bytes(self, relative: str) -> bytes:
        with self._lock:
            return self.read_bytes_unlocked(relative)

    def read_bytes_unlocked(self, relative: str) -> bytes:
        return self.path(relative).read_bytes()

    def read_json(self, relative: str) -> Any:
        with self._lock:
            return self.read_json_unlocked(relative)

    def read_json_unlocked(self, relative: str) -> Any:
        data = self.read_bytes_unlocked(relative)
        return json.loads(data.decode("utf-8"))

    def write_bytes(self, relative: str, data: bytes) -> None:
        with self._lock:
            self.write_bytes_unlocked(relative, data)

    def write_bytes_unlocked(self, relative: str, data: bytes) -> None:
        self._refuse_when_readonly()
        atomic_replace(self.path(relative), data)

    def write_json(self, relative: str, payload: Any) -> None:
        with self._lock:
            self.write_json_unlocked(relative, payload)

    def write_json_unlocked(self, relative: str, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.write_bytes_unlocked(relative, data)

    def write_text(self, relative: str, content: str) -> None:
        with self._lock:
            self.write_bytes_unlocked(relative, content.encode("utf-8"))

    def append_line(self, relative: str, line: bytes) -> None:
        with self._lock:
            self.append_line_unlocked(relative, line)

    def append_line_unlocked(self, relative: str, line: bytes) -> None:
        self._refuse_when_readonly()
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("ab") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def remove(self, relative: str) -> None:
        with self._lock:
            self.remove_unlocked(relative)

    def remove_unlocked(self, relative: str) -> None:
        self._refuse_when_readonly()
        try:
            self.path(relative).unlink()
        except FileNotFoundError:
            return


def atomic_replace(path: Path, data: bytes) -> None:
    """写入同目录临时文件，刷盘，再覆盖目标。Windows 上替换已存在的文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.tmp-", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    try:
        _fsync_dir(path.parent)
    except OSError:
        return


def _fsync_dir(directory: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(directory, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
