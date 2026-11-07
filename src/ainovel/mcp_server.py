"""只读 MCP 入口。创作代理仍走进程内工具，这里给外部客户端读一本书。"""

import json

from ainovel.store.book import Book
from ainovel.tools import call_tool

MCP_TOOLS = ("novel_context", "read_chapter")


def read_book_tool(book_dir: str, name: str, args: dict | None = None) -> str:
    if name not in MCP_TOOLS:
        raise ValueError(f"MCP 不提供写工具: {name}")
    book = Book.open(book_dir, writable=False)
    payload = call_tool(book, name, args or {})
    return json.dumps(payload, ensure_ascii=False)


def main() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise SystemExit("缺少 mcp。请安装 ainovel 的 llm 可选依赖。") from exc

    server = FastMCP("ainovel")

    @server.tool()
    def novel_context(book_dir: str, chapter: int = 0) -> str:
        """读取一本书当前任务需要的事实。不修改文件。"""
        return read_book_tool(book_dir, "novel_context", {"chapter": chapter})

    @server.tool()
    def read_chapter(book_dir: str, chapter: int) -> str:
        """读取已提交的章节正文。不修改文件。"""
        return read_book_tool(book_dir, "read_chapter", {"chapter": chapter})

    server.run()


if __name__ == "__main__":
    main()
