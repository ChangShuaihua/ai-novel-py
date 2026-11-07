from pathlib import Path

import pytest

from ainovel.mcp_server import MCP_TOOLS, read_book_tool
from ainovel.store.book import Book
from ainovel.tools import call_tool


def test_mcp_surface_is_read_only(tmp_path: Path):
    assert MCP_TOOLS == ("novel_context", "read_chapter")
    book = Book.open(tmp_path, writable=True)
    call_tool(book, "save_book", {"title": "山海", "synopsis": "出门"})
    closed = Book.open(tmp_path, writable=False)
    text = read_book_tool(str(closed.root), "novel_context", {})
    assert "foundation_status" in text
    with pytest.raises(ValueError, match="写工具"):
        read_book_tool(str(closed.root), "save_book", {"title": "不该写"})
