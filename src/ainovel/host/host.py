"""一本书的宿主：租约、启动、恢复、干预和引擎。"""

import os
from pathlib import Path

from ainovel.agents.workers import build_workers
from ainovel.arbiter.decide import ArbiterError, decide_intervention, decide_plan_start
from ainovel.domain.errors import UnsupportedAdvanceModeError
from ainovel.domain.progress import Progress
from ainovel.domain.run_meta import AdvanceHold, PlanStartRecord
from ainovel.domain.transitions import Phase
from ainovel.flow.load import foundation_missing
from ainovel.flow.model import Instruction
from ainovel.host.config import AppConfig, ConfigError, load_config
from ainovel.host.engine import Engine, RunResult
from ainovel.llm.litellm_client import LiteLLMTransport
from ainovel.llm.policy import RoleClient
from ainovel.llm.types import ModelRef, RoleModel
from ainovel.rules import save_runtime_rule
from ainovel.store.book import Book
from ainovel.store.decisions import DecisionStore
from ainovel.store.paths import chapter_number
from ainovel.voice import load_bundle


class HostError(RuntimeError):
    """宿主拒绝继续。已落盘的步骤保留。"""


class BookLock:
    def __init__(self, root: Path) -> None:
        self.path = root / ".ainovel.lock"
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        except FileExistsError as exc:
            raise HostError(f"这本书已有进程占用：{self.path}") from exc

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        if self.path.exists():
            self.path.unlink()


class Host:
    def __init__(self, book: Book, completer, prompts: dict[str, str], workers: dict, lock: BookLock) -> None:
        self.book = book
        self.completer = completer
        self.prompts = prompts
        self.workers = workers
        self.lock = lock
        self.engine = Engine(book, workers, completer, prompts)
        self.decisions = DecisionStore(book.root)

    @classmethod
    def open(
        cls,
        directory: Path | str,
        *,
        completer=None,
        require_config: bool = True,
        config_path: Path | None = None,
        include_home: bool = True,
    ) -> "Host":
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        lock = BookLock(root)
        lock.acquire()
        try:
            config = load_config(config_path) if require_config else None
            if completer is None:
                if config is None:
                    raise ConfigError("缺少模型配置。请在 ~/.ainovel/ 放置 config.json。")
                completer = completer_from_config(config)
            book = Book.open(root, writable=True)
            style = config.style if config is not None else ""
            bundle = load_bundle(style, root, include_home=include_home)
            workers = build_workers(root, style=style, bundle=bundle, include_home=include_home)
            return cls(book, completer, bundle.prompts, workers, lock)
        except Exception:
            lock.release()
            raise

    def close(self) -> None:
        self.lock.release()

    def subscribe(self, listener) -> None:
        self.engine.subscribe(listener)

    def start(self, requirement: str, *, max_rounds: int | None = None) -> RunResult:
        self.book.progress.save(Progress(phase=Phase.INIT))
        self.book.checkpoints.reset()
        meta = self.book.run_meta.init(style="", provider="", model="")
        meta.start_prompt = requirement
        self.book.run_meta.save(meta)
        try:
            decision = decide_plan_start(
                self.completer,
                self.prompts.get("arbiter-plan-start.md", ""),
                requirement,
                meta.style,
            )
        except ArbiterError as exc:
            self.decisions.append({"kind": "plan_start", "input": requirement, "error": str(exc)})
            raise HostError(f"启动裁定失败：{exc}") from exc
        record = self.decisions.append(
            {"kind": "plan_start", "input": requirement, "decision": decision, "reason": decision["reason"]}
        )
        meta = self.book.run_meta.load() or meta
        meta.plan_start = PlanStartRecord(
            raw_prompt=requirement,
            planner=decision["planner"],
            planner_task=decision["task"],
            decision_id=record["id"],
        )
        meta.planning_tier = "short" if decision["planner"] == "architect_short" else "long"
        self.book.run_meta.save(meta)
        self.engine.enqueue(
            Instruction(agent=decision["planner"], task=decision["task"], reason=decision["reason"])
        )
        return self.engine.run(max_rounds=max_rounds)

    def resume(self, *, max_rounds: int | None = None) -> RunResult:
        for warning in consistency_warnings(self.book):
            self.engine.emit(warning)
        meta = self.book.run_meta.load()
        if meta is not None and meta.pending_steer:
            return self.steer(meta.pending_steer, max_rounds=max_rounds)
        return self.engine.run(max_rounds=max_rounds)

    def continue_book(self, *, max_rounds: int | None = None) -> RunResult:
        return self.resume(max_rounds=max_rounds)

    def abort(self) -> None:
        self.engine.abort()

    def set_advance_mode(self, mode: str) -> None:
        try:
            self.book.run_meta.set_advance_mode(mode)
        except (ValueError, UnsupportedAdvanceModeError) as exc:
            raise HostError(str(exc)) from exc
        label = "逐章验收" if mode == "review" else "自动推进"
        self.engine.emit(f"章节推进模式已切换为{label}")

    def advance_one_chapter(self, *, max_rounds: int | None = None) -> RunResult:
        meta = self.book.run_meta.load()
        if meta is None:
            raise HostError("RunMeta 未初始化")
        if meta.advance_mode != "review":
            raise HostError("/next 仅用于逐章验收模式，请先执行 /review on")
        if meta.advance_hold is not None:
            raise HostError(f"仍有一次性暂停意图待处理（{meta.advance_hold.reason}），请先恢复或完成当前干预")
        progress = self.book.progress.load()
        if progress is None or progress.phase != Phase.WRITING:
            phase = progress.phase.value if progress is not None else "<nil>"
            raise HostError(f"当前阶段不能授权新章（phase={phase}）")
        target = progress.next_chapter()
        if target <= 0:
            raise HostError("无法从当前进度推导下一章")
        try:
            self.book.run_meta.grant_advance_permit(target)
        except ValueError as exc:
            raise HostError(str(exc)) from exc
        self.engine.emit(f"已放行第 {target} 章")
        return self.engine.run(max_rounds=max_rounds)

    def steer(self, text: str, *, max_rounds: int | None = None) -> RunResult:
        meta = self.book.run_meta.load() or self.book.run_meta.init(style="", provider="", model="")
        meta.pending_steer = text
        self.book.run_meta.save(meta)
        facts = _intervention_facts(self.book)
        try:
            decision = decide_intervention(
                self.completer,
                self.prompts.get("arbiter-intervention.md", ""),
                facts,
                text,
            )
        except ArbiterError as exc:
            self.decisions.append({"kind": "intervention", "input": text, "facts": facts, "error": str(exc)})
            raise HostError(f"干预裁定失败：{exc}") from exc
        self.decisions.append(
            {
                "kind": "intervention",
                "input": text,
                "facts": facts,
                "decision": decision,
                "reason": decision["reason"],
            }
        )
        follow = self._apply_intervention(decision)
        meta = self.book.run_meta.load() or meta
        meta.pending_steer = ""
        self.book.run_meta.save(meta)
        if follow:
            return self.engine.run(max_rounds=max_rounds)
        progress = self.book.progress.load()
        if progress is not None and progress.phase == Phase.COMPLETE:
            return self.engine.settle()
        return RunResult("idle", events=list(self.engine.events))

    def _apply_intervention(self, decision: dict) -> bool:
        answer = str(decision.get("answer") or "").strip()
        if answer:
            self.engine.emit(answer)
        rules = str(decision.get("rules") or "").strip()
        if rules:
            save_runtime_rule(self.book.root, rules)
        dispatch = decision.get("dispatch")
        hold = decision.get("hold")
        if isinstance(dispatch, dict) and isinstance(hold, dict) and not hold.get("cancel"):
            self.engine.defer_gate = True
        hold = decision.get("hold")
        if isinstance(hold, dict):
            meta = self.book.run_meta.load()
            if meta is not None:
                if hold.get("cancel"):
                    meta.advance_hold = None
                else:
                    meta.advance_hold = AdvanceHold(
                        after=str(hold.get("after") or ""),
                        target_chapter=int(hold.get("target_chapter") or 0),
                        reason=str(hold.get("reason") or ""),
                    )
                self.book.run_meta.save(meta)
        reopen = decision.get("reopen")
        if isinstance(reopen, dict):
            self.book.progress.reopen([int(chapter) for chapter in reopen.get("chapters") or []], str(reopen.get("reason") or decision["reason"]))
        dispatch = decision.get("dispatch")
        if isinstance(dispatch, dict):
            self.engine.enqueue(
                Instruction(agent=dispatch["agent"], task=dispatch["task"], reason=decision["reason"])
            )
            return True
        return isinstance(reopen, dict)


def completer_from_config(config: AppConfig):
    primary = ModelRef(
        provider=config.provider,
        model=config.model,
        api_key=config.api_key,
        api_base=config.api_base,
    )
    return RoleClient(RoleModel(primary=primary), LiteLLMTransport())


def consistency_warnings(book: Book) -> list[str]:
    progress = book.progress.load()
    if progress is None:
        return []
    warnings = []
    for chapter in progress.completed_chapters:
        path = book.root / "chapters" / f"{chapter_number(chapter)}.md"
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            warnings.append(f"进度记录第 {chapter} 章已完成，但正文缺失或为空")
    return warnings


def _intervention_facts(book: Book) -> dict:
    progress = book.progress.load()
    meta = book.run_meta.load()
    title = ""
    try:
        info = book.info.load()
    except ValueError:
        info = None
    if info is not None:
        title = info.title
    return {
        "phase": progress.phase.value if progress is not None else "",
        "flow": progress.flow.value if progress is not None and progress.flow is not None else "",
        "title": title,
        "completed_chapters": len(progress.completed_chapters) if progress is not None else 0,
        "next_chapter": progress.next_chapter() if progress is not None else 0,
        "pending_rewrites": list(progress.pending_rewrites) if progress is not None else [],
        "foundation_missing": foundation_missing(book.root),
        "planning_tier": meta.planning_tier if meta is not None else "",
    }
