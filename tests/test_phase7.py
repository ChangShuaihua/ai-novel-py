"""阶段 7：分层上下文、压缩、逐章验收、用户规则。"""

import json
from pathlib import Path

import pytest

from ainovel.agents.loop import AgentLoopError
from ainovel.agents.workers import build_workers
from ainovel.domain.checkpoint import chapter_scope
from ainovel.domain.commit import CommitStage, PendingCommit
from ainovel.domain.progress import Progress
from ainovel.domain.transitions import FlowState, Phase
from ainovel.entry.headless import main
from ainovel.host.engine import Engine
from ainovel.host.host import Host
from ainovel.llm.types import Completion
from ainovel.store.book import Book
from ainovel.store.paths import chapter_number
from ainovel.contextpack import ContextUsage, WriterContext, format_context_usage
from ainovel.tools.context import novel_context


class _Worker:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, completer, book, task, max_turns=None, context_budget=None):
        self.calls += 1
        return None


def _writing_book(root: Path, **progress) -> Book:
    book = Book.open(root, writable=True)
    fields = {"phase": Phase.WRITING, "flow": FlowState.WRITING}
    fields.update(progress)
    book.progress.save(Progress(**fields))
    book.run_meta.init(style="", provider="", model="")
    return book


def test_more_than_fifty_chapters_use_layered_window(tmp_path: Path):
    book = _writing_book(tmp_path / "book", total_chapters=51, layered=True, completed_chapters=[50])
    chapters = [{"title": f"第{index}章"} for index in range(1, 41)]
    later = [{"title": f"第{index}章"} for index in range(41, 61)]
    (book.root / "layered_outline.json").write_text(
        json.dumps(
            [
                {
                    "index": 1,
                    "arcs": [
                        {"index": 1, "chapters": chapters},
                        {"index": 2, "chapters": later},
                    ],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    summary_dir = book.root / "summaries"
    summary_dir.mkdir()
    for number in (47, 48, 49, 50):
        (summary_dir / f"{chapter_number(number)}.json").write_text(
            json.dumps({"chapter": number, "summary": f"摘要{number}"}, ensure_ascii=False),
            encoding="utf-8",
        )
    (summary_dir / "vol-v01.json").write_text(
        json.dumps({"volume": 1, "summary": "卷一走过门口"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (summary_dir / "arc-v01a01.json").write_text(
        json.dumps(
            {
                "volume": 1,
                "arc": 1,
                "summary": "第一弧",
                "character_snapshots": [{"name": "林舟", "state": "紧张"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (book.root / "meta" / "foreshadow.jsonl").write_text(
        json.dumps({"chapter": 2, "reason": "门后还有路"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    payload = novel_context(book, {"chapter": 51})
    assert payload["layered"] is True
    assert payload["summary_window"] == 3
    assert payload["volume_summaries"][0]["summary"] == "卷一走过门口"
    assert payload["arc_summaries"][0]["arc"] == 1
    assert [item["chapter"] for item in payload["recent_summaries"]] == [48, 49, 50]
    assert payload["character_snapshots"][0]["name"] == "林舟"
    assert payload["related_chapters"][0]["chapter"] == 2

    short = _writing_book(tmp_path / "short", total_chapters=30, completed_chapters=[1])
    assert novel_context(short, {"chapter": 2})["related_chapters"] == []


def test_compacted_writer_messages_keep_plan_and_snapshots(tmp_path: Path):
    root = tmp_path / "book"
    book = _writing_book(root, total_chapters=3)
    (root / "drafts").mkdir()
    (root / "drafts" / "01.plan.json").write_text(
        json.dumps({"chapter": 1, "goal": "把门锁上"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "summaries").mkdir()
    (root / "summaries" / "arc-v01a01.json").write_text(
        json.dumps({"character_snapshots": [{"name": "林舟", "state": "紧张"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    seen: list[str] = []

    class Recorder:
        def complete(self, messages, tools):
            seen.append("\n".join(str(item.get("content") or "") for item in messages))
            if not tools:
                return Completion(content="角色状态仍是紧张，门后的伏笔未收。")
            return Completion(content="先停一下")

    worker = build_workers(root, include_home=False)["writer"]
    with pytest.raises(AgentLoopError):
        worker.run(Recorder(), book, "写第 1 章", max_turns=1, context_budget=1)
    assert "把门锁上" in seen[-1]
    assert "紧张" in seen[-1]
    assert "当前章计划" in seen[-1]
    assert "角色快照" in seen[-1]


def test_review_mode_blocks_new_chapters_but_not_rewrites(tmp_path: Path):
    book = _writing_book(tmp_path / "book", total_chapters=3)
    book.run_meta.set_advance_mode("review")
    worker = _Worker()
    result = Engine(book, {"writer": worker}, None, {}).run(max_rounds=1)
    assert worker.calls == 0
    assert "/next" in result.reason

    rewrite = _writing_book(
        tmp_path / "rewrite",
        total_chapters=3,
        completed_chapters=[1],
        pending_rewrites=[1],
        flow=FlowState.REWRITING,
    )
    rewrite.run_meta.set_advance_mode("review")
    worker = _Worker()
    Engine(rewrite, {"writer": worker}, None, {}).run(max_rounds=1)
    assert worker.calls == 1
    assert rewrite.run_meta.load().advance_permit_chapter == 0


def test_crashed_commit_does_not_spend_permit_on_the_next_chapter(tmp_path: Path):
    book = _writing_book(tmp_path / "book", total_chapters=3, completed_chapters=[1])
    book.run_meta.set_advance_mode("review")
    book.run_meta.grant_advance_permit(1)
    book.pending.save(PendingCommit(chapter=1, stage=CommitStage.PROGRESS_MARKED, draft_content="林舟推开门。", summary="进门"))
    worker = _Worker()
    engine = Engine(book, {"writer": worker}, None, {})
    engine.run(max_rounds=1)
    assert book.run_meta.load().advance_permit_chapter == 1

    book.pending.clear()
    book.checkpoints.append(chapter_scope(1), "commit", "chapters/01.md", "digest")
    result = engine.run(max_rounds=1)
    assert worker.calls == 1
    assert book.run_meta.load().advance_permit_chapter == 0
    assert "/next" in result.reason


def test_style_stats_count_completed_chapters(tmp_path: Path):
    book = _writing_book(tmp_path / "book", total_chapters=5, completed_chapters=[1, 2, 3, 4, 5])
    chapter_dir = book.root / "chapters"
    chapter_dir.mkdir()
    for number in range(1, 6):
        (chapter_dir / f"{chapter_number(number)}.md").write_text(
            "他推开了那扇旧门。仿佛有人在等。仿佛灯还亮着。\n夜色很短。\n",
            encoding="utf-8",
        )
    payload = novel_context(book, {"chapter": 5})
    stats = payload["style_stats"]
    assert stats["chapters"] == 5
    assert stats["patterns"]
    assert any(item["text"] == "他推开了那扇旧门" for item in stats["repeated_sentences"])


def test_steer_rules_survive_reopen(tmp_path: Path):
    root = tmp_path / "book"

    class Rules:
        def complete(self, messages, tools):
            return Completion(content=json.dumps({"reason": "记下长期要求", "rules": "不要写上帝视角"}, ensure_ascii=False))

    host = Host.open(root, completer=Rules(), require_config=False, include_home=False)
    try:
        host.steer("以后不要上帝视角")
        payload = novel_context(host.book, {})
        assert "不要写上帝视角" in payload["user_rules"]["preferences"]
        assert "某种程度上" in payload["user_rules"]["structured"]["forbidden_phrases"]
    finally:
        host.close()

    reopened = Book.open(root, writable=False)
    again = novel_context(reopened, {})
    assert "不要写上帝视角" in again["user_rules"]["preferences"]


def test_writer_context_usage_uses_character_budget(tmp_path: Path):
    assert format_context_usage(69, 100) == "69% · 正常"
    assert format_context_usage(70, 100) == "70% · 警告"
    assert format_context_usage(85, 100) == "85% · 警告"
    assert format_context_usage(86, 100) == "86% · 危险"

    class Inner:
        def complete(self, messages, tools):
            return Completion(content="好")

    usage = ContextUsage()
    book = Book.open(tmp_path, writable=True)
    WriterContext(Inner(), book, 100, usage).complete([{"role": "user", "content": "字" * 80}], [])
    assert usage.text.endswith("警告") or usage.text.endswith("危险")


def test_review_command_switches_mode(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    (home / ".ainovel").mkdir(parents=True)
    (home / ".ainovel" / "config.json").write_text(
        json.dumps({"provider": "demo", "model": "demo"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: home)
    root = tmp_path / "book"
    book = _writing_book(root, total_chapters=2)
    book.run_meta  # 已初始化
    assert main(["review", str(root), "on"]) == 0
    assert Book.open(root, writable=False).run_meta.load().advance_mode == "review"
