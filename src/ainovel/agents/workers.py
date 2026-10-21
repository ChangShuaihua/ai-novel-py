"""装配规划师、写作者和审阅者。循环本身仍然不认识这些角色。"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ainovel.agents.catalog import (
    ARCHITECT_STEPS,
    ARCHITECT_STOP,
    ARCHITECT_TOOLS,
    EDITOR_STOP,
    EDITOR_TOOLS,
    WRITER_STEPS,
    WRITER_STOP,
    WRITER_TOOLS,
    specs_for,
)
from ainovel.agents.loop import AgentResult, run_agent
from ainovel.llm.types import ToolSpec
from ainovel.contextpack import WriterContext
from ainovel.store.book import Book
from ainovel.tools import call_tool
from ainovel.voice import Bundle, build_writer_prompt, load_bundle

_WRITER_BUDGET = 120_000

_ARCHITECT_BLOCK = (
    "你必须调用 save_book、save_foundation、expand_next_arc、revise_outline、"
    "resolve_outline_feedback 或 audit_foundation 将产出落盘后才能结束。"
    "只输出 Markdown/JSON 文字等于丢失。"
)
_WRITER_BLOCK = "禁止结束：本章尚未提交。正文必须通过工具落盘，并调用 commit_chapter。"


@dataclass(frozen=True)
class Worker:
    name: str
    system_prompt: str
    tool_specs: tuple[ToolSpec, ...]
    stop_after: tuple[str, ...]
    steps_for: Callable[[str], tuple[str, ...]]
    message_for: Callable[[str], str]
    prompt_cache_key: str
    max_turns: int

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.tool_specs)

    def run(self, completer, book: Book, task: str, *, max_turns: int | None = None, context_budget: int | None = None) -> AgentResult:
        if self.name == "writer":
            completer = WriterContext(completer, book, _WRITER_BUDGET if context_budget is None else context_budget)
        return run_agent(
            completer,
            system_prompt=self.system_prompt,
            task=task,
            tool_specs=list(self.tool_specs),
            call_tool=lambda name, args: call_tool(book, name, args),
            checkpoints=book.checkpoints,
            stop_after=self.stop_after,
            required_steps=self.steps_for(task),
            block_message=self.message_for(task),
            max_turns=self.max_turns if max_turns is None else max_turns,
        )


def build_workers(
    book_dir: Path,
    *,
    style: str = "",
    run_seq: int = 1,
    bundle: Bundle | None = None,
    include_home: bool = True,
) -> dict[str, Worker]:
    loaded = bundle if bundle is not None else load_bundle(style, book_dir, include_home=include_home)
    style_text = loaded.styles.get(style, "") if style else ""
    writer_prompt = build_writer_prompt(loaded.prompts["writer.md"], loaded.voice, style_text)
    base = hashlib.sha256(str(Path(book_dir).resolve()).encode("utf-8")).hexdigest()[:16]
    seq = run_seq

    def cache_key(role: str) -> str:
        return f"{base}-{role}-{seq}"

    def architect(name: str, prompt_file: str, max_turns: int) -> Worker:
        return Worker(
            name=name,
            system_prompt=loaded.prompts[prompt_file],
            tool_specs=specs_for(ARCHITECT_TOOLS),
            stop_after=ARCHITECT_STOP,
            steps_for=lambda _task: ARCHITECT_STEPS,
            message_for=lambda _task: _ARCHITECT_BLOCK,
            prompt_cache_key=cache_key(name),
            max_turns=max_turns,
        )

    return {
        "architect_short": architect("architect_short", "architect-short.md", 15),
        "architect_long": architect("architect_long", "architect-long.md", 20),
        "writer": Worker(
            name="writer",
            system_prompt=writer_prompt,
            tool_specs=specs_for(WRITER_TOOLS),
            stop_after=WRITER_STOP,
            steps_for=lambda _task: WRITER_STEPS,
            message_for=lambda _task: _WRITER_BLOCK,
            prompt_cache_key=cache_key("writer"),
            max_turns=30,
        ),
        "editor": Worker(
            name="editor",
            system_prompt=loaded.prompts["editor.md"],
            tool_specs=specs_for(EDITOR_TOOLS),
            stop_after=EDITOR_STOP,
            steps_for=editor_steps,
            message_for=editor_message,
            prompt_cache_key=cache_key("editor"),
            max_turns=20,
        ),
    }


def editor_steps(task: str) -> tuple[str, ...]:
    if "save_volume_summary" in task or "卷摘要" in task:
        return ("volume_summary",)
    if "save_arc_summary" in task or "弧摘要" in task:
        return ("arc_summary",)
    return ("review",)


def editor_message(task: str) -> str:
    if "save_volume_summary" in task or "卷摘要" in task:
        return "本次任务是生成卷摘要：你必须调用 save_volume_summary 落盘后才能结束，save_review 复核不算完成。"
    if "save_arc_summary" in task or "弧摘要" in task:
        return "本次任务是生成弧摘要：你必须调用 save_arc_summary 落盘后才能结束，save_review 复核不算完成。"
    return "你必须调用 save_review 落盘审阅后才能结束。只写摘要不算完成。"
