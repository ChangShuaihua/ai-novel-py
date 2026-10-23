from pathlib import Path

from ainovel.entry.picker import _read_result


def test_picked_path_keeps_unicode(tmp_path: Path):
    result = tmp_path / "picked.txt"
    result.write_text(r"C:\Users\常帅华\一部小说", encoding="utf-8")
    assert _read_result(result) == r"C:\Users\常帅华\一部小说"
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    assert _read_result(empty) == ""
