"""书脊缓存只记标题和进度。未命中才查书表，失效后重新查。"""

import json
from datetime import datetime
from pathlib import Path

from ainovel.entry.catalog import _progress_fields, _spine_row
from ainovel.entry.desk import Desk
from ainovel.entry.spine_cache import bind, drop_spines, reset


class _MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttl = None

    def get(self, key: str):
        return self.values.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.ttl = ttl
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


class _DownRedis:
    def get(self, key: str):
        raise OSError("down")

    def setex(self, key: str, ttl: int, value: str) -> None:
        raise OSError("down")

    def delete(self, key: str) -> None:
        raise OSError("down")


class _Spines:
    def __init__(self, root: Path) -> None:
        self.user_id = "a" * 16
        self.root = root
        self.reads = 0
        self.opened = 0
        self.books = [_row()]
        self.trash: list[dict] = []

    def shelf_spines(self):
        self.reads += 1
        return [dict(item) for item in self.books], [dict(item) for item in self.trash]

    def local_root(self, public: str) -> Path:
        return self.root

    def workspace(self, public: str) -> Path:
        self.opened += 1
        raise AssertionError("列表不该打开正文")


def _row() -> dict:
    return {
        "directory": "db:7",
        "title": "雨",
        "phase": "writing",
        "completed_count": 2,
        "total_chapters": 8,
        "has_progress": True,
    }


def _desk(tmp_path: Path, shelf: _Spines) -> Desk:
    return Desk(
        library_path=tmp_path / "library.json",
        config_path=tmp_path / "config.json",
        books_root=tmp_path / "books",
        catalog=shelf,
    )


def test_spine_row_uses_chapter_counts_and_marks_unstarted_books():
    started = _spine_row({
        "id": 3,
        "shelf_state": "shelf",
        "title": "雨",
        "phase": "writing",
        "total_chapters": 10,
        "completed_chapters": "[1, 2, 3]",
        "trashed_at": None,
    })
    assert started["directory"] == "db:3"
    assert started["completed_count"] == 3
    assert started["has_progress"] is True
    assert "purge_at" not in started

    fresh = _spine_row({
        "id": 4,
        "shelf_state": "shelf",
        "title": "",
        "phase": "init",
        "total_chapters": 0,
        "completed_chapters": None,
        "trashed_at": None,
    })
    assert fresh["has_progress"] is False
    assert fresh["completed_count"] == 0

    trashed = _spine_row({
        "id": 9,
        "shelf_state": "trash",
        "title": "旧",
        "phase": "init",
        "total_chapters": 0,
        "completed_chapters": None,
        "trashed_at": datetime(2026, 10, 26, 2, 0, 0),
    })
    assert trashed["purge_at"].startswith("2026-10-29")


def test_progress_fields_keep_an_empty_completed_list():
    fields, params = _progress_fields({
        "phase": "init",
        "total_chapters": 0,
        "completed_chapters": [],
    })
    assert fields == ["phase=%s", "total_chapters=%s", "completed_chapters=%s"]
    assert params[0] == "init"
    assert params[1] == 0
    assert json.loads(params[2]) == []

    writing, values = _progress_fields({
        "phase": "writing",
        "total_chapters": 20,
        "completed_chapters": [1, 2],
    })
    assert "completed_chapters=%s" in writing
    assert json.loads(values[2]) == [1, 2]
    assert _progress_fields({"phase": "nope"}) == ([], [])


def test_shelf_cache_skips_the_query_until_the_key_is_dropped(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("AINOVEL_REDIS_URL", raising=False)
    memory = _MemoryRedis()
    shelf = _Spines(tmp_path / "book")
    bind(memory)
    desk = _desk(tmp_path, shelf)
    try:
        first = desk.library()
        second = desk.library()
        assert shelf.reads == 1
        assert shelf.opened == 0
        assert memory.ttl == 20
        assert first["books"][0]["title"] == "雨"
        assert second["books"][0]["completed_count"] == 2
        stored = json.loads(next(iter(memory.values.values())))
        assert "locked" not in stored["books"][0]

        (shelf.root).mkdir(parents=True, exist_ok=True)
        (shelf.root / ".ainovel.lock").write_text("1", encoding="utf-8")
        assert desk.library()["books"][0]["locked"] is True
        assert shelf.reads == 1
        (shelf.root / ".ainovel.lock").unlink()
        assert desk.library()["books"][0]["locked"] is False
        assert shelf.reads == 1

        drop_spines(shelf.user_id)
        shelf.books[0]["title"] = "改过"
        third = desk.library()
        assert shelf.reads == 2
        assert third["books"][0]["title"] == "改过"
        assert "secret" not in json.dumps(third)
    finally:
        reset()
        desk.shutdown()


def test_missing_redis_reads_the_shelf_every_time(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("AINOVEL_REDIS_URL", raising=False)
    reset()
    shelf = _Spines(tmp_path / "book")
    desk = _desk(tmp_path, shelf)
    try:
        desk.library()
        desk.library()
        assert shelf.reads == 2
        assert shelf.opened == 0
    finally:
        desk.shutdown()


def test_redis_outage_falls_back_to_the_query(tmp_path: Path):
    shelf = _Spines(tmp_path / "book")
    bind(_DownRedis())
    desk = _desk(tmp_path, shelf)
    try:
        assert desk.library()["books"][0]["directory"] == "db:7"
        assert desk.library()["books"][0]["title"] == "雨"
        assert shelf.reads == 2
        assert shelf.opened == 0
    finally:
        reset()
        desk.shutdown()
