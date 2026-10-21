"""长跑前要留下的稳定性记录。模型都是假的。"""

import json
from pathlib import Path

from ainovel.agents.workers import build_workers
from ainovel.domain.commit import CommitStage, PendingCommit
from ainovel.domain.progress import Progress
from ainovel.domain.transitions import FlowState, Phase
from ainovel.host.engine import Engine
from ainovel.host.host import Host
from ainovel.llm.errors import ProviderError
from ainovel.llm.policy import RoleClient
from ainovel.llm.types import Completion, ModelRef, RoleModel, ToolCall
from ainovel.store.book import Book
from ainovel.tools import call_tool


def _writing(root: Path, **fields) -> Book:
    book = Book.open(root, writable=True)
    payload = {"phase": Phase.WRITING, "flow": FlowState.WRITING}
    payload.update(fields)
    book.progress.save(Progress(**payload))
    return book


def _tool(name: str, arguments: dict, call_id: str) -> Completion:
    return Completion(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=json.dumps(arguments, ensure_ascii=False))],
        stop_reason="tool_calls",
    )


class _Failover:
    def __init__(self) -> None:
        self.models: list[str] = []
        self.calls = 0

    def complete(self, model: ModelRef, messages: list[dict], tools: list[dict]) -> Completion:
        self.models.append(model.model)
        self.calls += 1
        if self.calls == 1:
            raise ProviderError("服务暂时不可用", kind="unavailable", status=503)
        names = {item["function"]["name"] for item in tools}
        if "save_foundation" in names:
            return _tool("save_foundation", {"type": "complete_book", "content": {}, "reason": "短篇已经收束"}, "done")
        if "commit_chapter" in names:
            return self._write(messages)
        return Completion(content="好")

    def _write(self, messages: list[dict]) -> Completion:
        root_hint = ""
        for message in messages:
            root_hint += str(message.get("content") or "")
        if "drafts/01.plan.json" in root_hint or "plan_chapter" in root_hint and "draft_chapter" not in root_hint:
            pass
        return _tool("plan_chapter", {"chapter": 1, "goal": "推门"}, f"w-{self.calls}")


def _role() -> RoleModel:
    return RoleModel(
        primary=ModelRef(provider="primary", model="main"),
        fallbacks=[ModelRef(provider="backup", model="spare")],
    )


def test_short_book_completes_and_does_not_resume_itself(tmp_path: Path):
    book = _writing(tmp_path / "book", total_chapters=1, completed_chapters=[1], current_chapter=1)
    (book.root / "chapters").mkdir()
    (book.root / "chapters" / "01.md").write_text("林舟推开门。\n", encoding="utf-8")
    (book.root / "outline.json").write_text(json.dumps([{"title": "推门"}], ensure_ascii=False), encoding="utf-8")
    transport = _Failover()
    client = RoleClient(_role(), transport, sleep=lambda _: None)
    engine = Engine(book, build_workers(book.root, include_home=False), client, {})
    result = engine.run()
    assert result.status == "completed"
    assert book.progress.load().phase == Phase.COMPLETE
    assert transport.models[0] == "main"
    assert "spare" in transport.models
    calls = transport.calls
    again = engine.run()
    assert again.status == "completed"
    assert transport.calls == calls


class _WriterFailover:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.models: list[str] = []
        self.calls = 0
        self.checked = False

    def complete(self, model: ModelRef, messages: list[dict], tools: list[dict]) -> Completion:
        self.models.append(model.model)
        self.calls += 1
        if self.calls == 1:
            raise ProviderError("服务暂时不可用", kind="unavailable", status=503)
        if not (self.root / "drafts" / "01.plan.json").is_file():
            return _tool("plan_chapter", {"chapter": 1, "goal": "推门"}, f"w-{self.calls}")
        if not (self.root / "drafts" / "01.draft.md").is_file():
            return _tool("draft_chapter", {"chapter": 1, "content": "林舟推开门。"}, f"w-{self.calls}")
        if not self.checked:
            self.checked = True
            return _tool("check_consistency", {"chapter": 1}, f"w-{self.calls}")
        return _tool("commit_chapter", {"chapter": 1, "summary": "林舟推开门。"}, f"w-{self.calls}")


def test_writer_does_not_see_a_transient_503(tmp_path: Path):
    root = tmp_path / "book"
    book = _writing(root, total_chapters=1)
    transport = _WriterFailover(root)
    worker = build_workers(root, include_home=False)["writer"]
    result = worker.run(RoleClient(_role(), transport, sleep=lambda _: None), book, "写第 1 章")
    assert (root / "chapters" / "01.md").read_text(encoding="utf-8") == "林舟推开门。"
    assert transport.models[0] == "main"
    assert transport.models[1] == "spare"
    text = json.dumps(result.messages, ensure_ascii=False)
    assert "503" not in text
    assert "服务暂时不可用" not in text


def test_resume_keeps_committed_text_and_checkpoint_digest(tmp_path: Path):
    root = tmp_path / "book"
    book = _writing(root, total_chapters=2)
    call_tool(book, "plan_chapter", {"chapter": 1, "goal": "推门"})
    call_tool(book, "draft_chapter", {"chapter": 1, "content": "林舟推开门。"})
    call_tool(book, "check_consistency", {"chapter": 1})
    call_tool(book, "commit_chapter", {"chapter": 1, "summary": "林舟推开门。"})
    original = (root / "chapters" / "01.md").read_text(encoding="utf-8")
    call_tool(book, "plan_chapter", {"chapter": 2, "goal": "上路"})
    plan_lines = [
        line
        for line in (root / "meta" / "checkpoints.jsonl").read_text(encoding="utf-8").splitlines()
        if '"step":"plan"' in line and '"chapter":2' in line
    ]
    call_tool(book, "plan_chapter", {"chapter": 2, "goal": "上路"})
    plan_again = [
        line
        for line in (root / "meta" / "checkpoints.jsonl").read_text(encoding="utf-8").splitlines()
        if '"step":"plan"' in line and '"chapter":2' in line
    ]
    assert plan_again == plan_lines

    book.pending.save(
        PendingCommit(
            chapter=2,
            stage=CommitStage.STARTED,
            payload={"chapter": 2, "summary": "冻结", "timeline": [], "foreshadow": [], "relations": [], "state_changes": []},
            draft_content="冻结正文",
            summary="冻结",
        )
    )
    call_tool(book, "commit_chapter", {"chapter": 2, "summary": "这是新参数，不能采用"})
    assert (root / "chapters" / "02.md").read_text(encoding="utf-8") == "冻结正文"
    assert (root / "chapters" / "01.md").read_text(encoding="utf-8") == original
    commit_lines = [
        line
        for line in (root / "meta" / "checkpoints.jsonl").read_text(encoding="utf-8").splitlines()
        if '"step":"commit"' in line and '"chapter":2' in line
    ]
    call_tool(book, "commit_chapter", {"chapter": 2, "summary": "再交一次"})
    commit_again = [
        line
        for line in (root / "meta" / "checkpoints.jsonl").read_text(encoding="utf-8").splitlines()
        if '"step":"commit"' in line and '"chapter":2' in line
    ]
    assert commit_again == commit_lines


class _Steer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.tasks: list[str] = []
        self.checked = False

    def complete(self, messages, tools):
        if not tools:
            return Completion(
                content=json.dumps(
                    {
                        "reason": "改完再看",
                        "answer": "先改第 1 章，改完停下来",
                        "hold": {"after": "rewrites_drained", "reason": "改完让我看"},
                        "dispatch": {"agent": "editor", "task": "复核第 1 章并调用 save_review"},
                    },
                    ensure_ascii=False,
                )
            )
        names = {item["function"]["name"] for item in tools}
        task = next(item["content"] for item in messages if item["role"] == "user")
        if "save_review" in names:
            return _tool(
                "save_review",
                {
                    "chapter": 1,
                    "scope": "chapter",
                    "verdict": "rewrite",
                    "summary": "开门太平",
                    "issues": [{"chapters": [1], "requires_change": True}],
                },
                "review",
            )
        self.tasks.append(task)
        if not (self.root / "drafts" / "01.plan.json").is_file():
            return _tool("plan_chapter", {"chapter": 1, "goal": "重写开门"}, "rw-plan")
        if not (self.root / "drafts" / "01.draft.md").is_file():
            return _tool("draft_chapter", {"chapter": 1, "content": "林舟重重推开门。"}, "rw-draft")
        if not self.checked:
            self.checked = True
            return _tool("check_consistency", {"chapter": 1}, "rw-check")
        return _tool("commit_chapter", {"chapter": 1, "summary": "重写了开门"}, "rw-commit")


def test_stopped_steer_replays_after_crash_and_rewrite_waits_at_the_boundary(tmp_path: Path):
    root = tmp_path / "book"
    book = _writing(root, total_chapters=3, completed_chapters=[1], current_chapter=1)
    (root / "chapters").mkdir()
    (root / "chapters" / "01.md").write_text("林舟推开门。\n", encoding="utf-8")
    book.run_meta.init(style="", provider="", model="")
    meta = book.run_meta.load()
    meta.pending_steer = "把第 1 章改得更用力"
    book.run_meta.save(meta)

    host = Host.open(root, completer=_Steer(root), require_config=False, include_home=False)
    try:
        result = host.resume()
    finally:
        host.close()
    assert host.book.run_meta.load().pending_steer == ""
    assert any("先改第 1 章" in event for event in result.events)
    assert result.status == "paused"
    assert "返工" in result.reason
    assert any("重写" in task for task in _tasks_from(host))
    assert not (root / "chapters" / "02.md").exists()


def _tasks_from(host: Host) -> list[str]:
    completer = host.completer
    if isinstance(completer, _Steer):
        return completer.tasks
    return []
