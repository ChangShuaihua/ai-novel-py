"""写作者上下文压缩。先丢旧工具结果，再用文件事实替换，最后才问模型。"""

import json
import re

from ainovel.store.book import Book
from ainovel.store.paths import chapter_number
from ainovel.tools.files import read_json, read_text

_CHAPTER = re.compile(r"第\s*(\d+)\s*章")


def compact_writer_messages(
    messages: list[dict],
    *,
    budget: int,
    restore: str,
    file_summary: str = "",
    summarize=None,
) -> list[dict]:
    """超窗时压缩。无论哪一步，结果里都重新放回当前计划和角色快照。"""
    if _chars(messages) <= budget:
        return list(messages)
    compacted = _truncate(_drop_old_tools(messages), 800)
    warning = ""
    if _chars(compacted) > budget:
        compacted = _replace_middle(compacted, file_summary)
    if _chars(compacted) > budget and summarize is not None:
        try:
            summary = str(summarize(compacted) or "").strip()
            if summary:
                compacted = _replace_middle(compacted, summary)
        except Exception as exc:
            warning = f"上下文压缩失败，本轮跳过，下一轮再试：{exc}"
    compacted = _with_restore(compacted, restore)
    if warning:
        compacted.append({"role": "user", "content": warning})
    return compacted


def writer_restore_text(book: Book, chapter: int) -> str:
    plan = read_json(book.root, f"drafts/{chapter_number(chapter)}.plan.json") if chapter > 0 else None
    lines = ["<post-compact-context>", "## 当前章计划"]
    if isinstance(plan, dict) and plan:
        lines.append(json.dumps(plan, ensure_ascii=False))
    else:
        lines.append("（没有已落盘的章计划）")
    lines.append("## 角色快照")
    snapshots = _snapshots(book)
    if snapshots:
        lines.append(json.dumps(snapshots, ensure_ascii=False))
    else:
        lines.append("（没有角色快照）")
    lines.append("</post-compact-context>")
    return "\n".join(lines)


def file_memory_text(book: Book, chapter: int) -> str:
    """用已经落盘的摘要替换旧对话，不调用模型。"""
    rows = []
    if chapter > 1:
        summary = read_json(book.root, f"summaries/{chapter_number(chapter - 1)}.json")
        if isinstance(summary, dict):
            rows.append("最近章摘要：" + json.dumps(summary, ensure_ascii=False))
    snapshots = _snapshots(book)
    if snapshots:
        rows.append("角色快照：" + json.dumps(snapshots, ensure_ascii=False))
    foreshadow = read_text(book.root, "meta/foreshadow.jsonl")
    if foreshadow:
        rows.append("伏笔台账：" + foreshadow[-800:])
    return "\n".join(rows) or "（文件里还没有可替换的叙事摘要）"


def chapter_from_messages(messages: list[dict], book: Book) -> int:
    for message in messages:
        if message.get("role") != "user":
            continue
        found = _CHAPTER.search(str(message.get("content") or ""))
        if found:
            return int(found.group(1))
    progress = book.progress.load()
    if progress is None:
        return 1
    if progress.in_progress_chapter:
        return progress.in_progress_chapter
    return progress.next_chapter()


class ContextUsage:
    """写作者最近一轮送进模型的占用。显示用，不参与调度。"""

    def __init__(self) -> None:
        self.text = ""


def format_context_usage(used: int, budget: int) -> str:
    if budget <= 0:
        return ""
    percent = round(used * 100 / budget)
    if percent < 70:
        band = "正常"
    elif percent <= 85:
        band = "警告"
    else:
        band = "危险"
    return f"{percent}% · {band}"


class WriterContext:
    """包在写作者补全器外面。窗口按字符数估算。"""

    def __init__(self, inner, book: Book, budget: int, usage: ContextUsage | None = None) -> None:
        self.inner = inner
        self.book = book
        self.budget = budget
        self.usage = usage
        self._failed = False

    def complete(self, messages, tools):
        chapter = chapter_from_messages(messages, self.book)
        restore = writer_restore_text(self.book, chapter)
        summary = file_memory_text(self.book, chapter)

        def summarize(current):
            if self._failed:
                raise RuntimeError("上一轮压缩已经失败")
            try:
                completion = self.inner.complete(
                    [
                        {
                            "role": "system",
                            "content": "只输出叙事摘要。必须保留角色状态、未收伏笔、审稿待修和文风锚点。",
                        },
                        {"role": "user", "content": _plain(current)[-4000:]},
                    ],
                    [],
                )
            except Exception:
                self._failed = True
                raise
            return completion.content

        compacted = compact_writer_messages(
            messages,
            budget=self.budget,
            restore=restore,
            file_summary=summary,
            summarize=summarize,
        )
        messages[:] = compacted
        if self.usage is not None:
            self.usage.text = format_context_usage(_chars(compacted), self.budget)
        return self.inner.complete(messages, tools)


def _chars(messages: list[dict]) -> int:
    return sum(len(str(message.get("content") or "")) for message in messages)


def _drop_old_tools(messages: list[dict]) -> list[dict]:
    tool_indexes = [index for index, message in enumerate(messages) if message.get("role") == "tool"]
    stale = set(tool_indexes[:-2])
    copied = []
    for index, message in enumerate(messages):
        item = dict(message)
        if index in stale:
            item["content"] = "[工具结果已省略]"
        copied.append(item)
    return copied


def _truncate(messages: list[dict], limit: int) -> list[dict]:
    copied = []
    for message in messages:
        item = dict(message)
        text = str(item.get("content") or "")
        if len(text) > limit:
            item["content"] = text[: limit // 2] + "\n…\n" + text[-limit // 2 :]
        copied.append(item)
    return copied


def _replace_middle(messages: list[dict], summary: str) -> list[dict]:
    if not messages:
        return [{"role": "user", "content": summary}] if summary else []
    head = [dict(messages[0])] if messages[0].get("role") == "system" else []
    tail = dict(messages[-1])
    middle = {"role": "user", "content": summary or "（旧对话已用文件摘要替换）"}
    if not head:
        return [middle, tail]
    if messages[-1] is messages[0]:
        return [*head, middle]
    return [*head, middle, tail]


def _with_restore(messages: list[dict], restore: str) -> list[dict]:
    copied = [dict(message) for message in messages]
    if restore and not any(restore in str(message.get("content") or "") for message in copied):
        copied.append({"role": "user", "content": restore})
    return copied


def _plain(messages: list[dict]) -> str:
    return "\n".join(str(message.get("content") or "") for message in messages)


def _snapshots(book: Book) -> list:
    root = book.root / "summaries"
    if not root.is_dir():
        return []
    snapshots = []
    for path in sorted(root.glob("arc-*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("character_snapshots"):
            snapshots = list(payload["character_snapshots"])
    return snapshots
