"""串行引擎。循环结束就是停，这里不会再把自己启动一次。"""

from dataclasses import dataclass, field

from ainovel.agents.loop import AgentLoopError, CheckpointGuardError
from ainovel.arbiter.decide import ArbiterError, decide_failure, decide_plan_start
from ainovel.domain.run_meta import PlanStartRecord
from ainovel.domain.transitions import Phase
from ainovel.flow.load import foundation_missing, load_state
from ainovel.flow.model import Instruction
from ainovel.flow.outline import repair_indexes
from ainovel.flow.route import route
from ainovel.host.gate import ChapterAdvanceGate
from ainovel.host.report import render_report
from ainovel.store.book import Book
from ainovel.store.decisions import DecisionStore
from ainovel.tools.files import read_json

_CONSULT_AT = 3
_ABORT_AT = 5


@dataclass
class RunResult:
    status: str
    report: str = ""
    reason: str = ""
    events: list[str] = field(default_factory=list)


class Engine:
    def __init__(self, book: Book, workers: dict, completer, prompts: dict[str, str]) -> None:
        self.book = book
        self.workers = workers
        self.completer = completer
        self.prompts = prompts
        self.decisions = DecisionStore(book.root)
        self.events: list[str] = []
        self.listeners: list = []
        self.paused = False
        self.pause_reason = ""
        self.cancelled = False
        self._queued: Instruction | None = None
        self._last_key = ""
        self._repeats = 0
        self._failed_key = ""
        self.defer_gate = False
        self.gate = ChapterAdvanceGate(book, self._pause)

    def enqueue(self, instruction: Instruction) -> None:
        self._queued = instruction

    def abort(self) -> None:
        self.cancelled = True

    def subscribe(self, listener) -> None:
        self.listeners.append(listener)

    def emit(self, text: str) -> None:
        self.events.append(text)
        for listener in list(self.listeners):
            listener(text)

    def run(self, *, max_rounds: int | None = None) -> RunResult:
        rounds = 0
        while not self.cancelled and not self.paused:
            if max_rounds is not None and rounds >= max_rounds:
                break
            defer_gate = self.defer_gate
            self.defer_gate = False
            if not defer_gate and self.gate.handle_boundary():
                break
            instruction = self._next_instruction()
            if instruction is None:
                break
            instruction = self._track_deadlock(instruction)
            if instruction is None:
                break
            if not self.gate.allow(instruction):
                break
            try:
                self.workers[instruction.agent].run(self.completer, self.book, instruction.task)
            except KeyError:
                self._pause(f"未知代理 {instruction.agent}，已暂停")
                break
            except (CheckpointGuardError, AgentLoopError, ArbiterError) as exc:
                self._remember_failure(instruction, exc)
                if self._handle_worker_error(instruction, exc):
                    break
            else:
                self._failed_key = ""
            rounds += 1
        return self.settle()

    def settle(self) -> RunResult:
        if self.paused:
            return RunResult("paused", reason=self.pause_reason, events=list(self.events))
        progress = self.book.progress.load()
        if progress is not None and progress.phase == Phase.COMPLETE:
            return RunResult("completed", report=render_report(self.book), events=list(self.events))
        return RunResult("idle", events=list(self.events))

    def _next_instruction(self) -> Instruction | None:
        if self._queued is not None:
            instruction = self._queued
            self._queued = None
            return self._precheck(instruction)
        try:
            state = load_state(self.book)
        except Exception as exc:
            self._pause(f"读取进度失败，已暂停：{exc}")
            return None
        instruction = route(state)
        if instruction is None:
            instruction = self._plan_start_fallback()
        if instruction is None:
            return None
        return self._precheck(instruction)

    def _precheck(self, instruction: Instruction) -> Instruction | None:
        progress = self.book.progress.load()
        if progress is not None and progress.phase == Phase.COMPLETE:
            self.emit("完本期派发已丢弃")
            return None
        if instruction.agent == "writer" and _chapter_needs_expansion(self.book, instruction.chapter or (progress.next_chapter() if progress else 0)):
            return Instruction(
                agent="architect_long",
                task="下一弧仍是骨架。调用 expand_next_arc 展开下一弧。",
                reason="写作目标章未展开，先展开再续写",
            )
        return instruction

    def _plan_start_fallback(self) -> Instruction | None:
        progress = self.book.progress.load()
        if progress is None or progress.phase in (Phase.WRITING, Phase.COMPLETE):
            return None
        meta = self.book.run_meta.load()
        if meta is None or meta.planning_tier or not foundation_missing(self.book.root):
            return None
        if meta.plan_start is not None:
            return Instruction(
                agent=meta.plan_start.planner,
                task=meta.plan_start.planner_task,
                reason="按已固化的启动裁定开始规划",
            )
        if not meta.start_prompt:
            return None
        try:
            decision = decide_plan_start(
                self.completer,
                self.prompts.get("arbiter-plan-start.md", ""),
                meta.start_prompt,
                meta.style,
            )
        except ArbiterError as exc:
            self._record("plan_start", meta.start_prompt, error=str(exc))
            self._pause(f"启动裁定失败，已暂停：{exc}")
            return None
        record = self._record("plan_start", meta.start_prompt, decision=decision, reason=decision["reason"])
        meta.plan_start = PlanStartRecord(
            raw_prompt=meta.start_prompt,
            planner=decision["planner"],
            planner_task=decision["task"],
            decision_id=record["id"],
        )
        meta.planning_tier = "short" if decision["planner"] == "architect_short" else "long"
        self.book.run_meta.save(meta)
        self.emit(f"启动裁定已补齐：{decision['planner']}")
        return Instruction(agent=decision["planner"], task=decision["task"], reason=decision["reason"])

    def _track_deadlock(self, instruction: Instruction) -> Instruction | None:
        key = f"{instruction.agent}\n{instruction.task}"
        if key == self._last_key:
            self._repeats += 1
        else:
            self._last_key = key
            self._repeats = 1
        if self._repeats < _CONSULT_AT:
            return instruction
        if self._repeats >= _ABORT_AT:
            self._pause(f"僵局熔断：指令连续 {self._repeats} 次无进展（{instruction.agent}），已暂停")
            return None
        facts = self._failure_facts("deadlock", instruction, "")
        try:
            decision = decide_failure(self.completer, self.prompts.get("arbiter-failure.md", ""), facts)
        except ArbiterError as exc:
            self._record("deadlock", instruction.task, facts=facts, error=str(exc))
            self._pause(f"僵局裁定失败，已暂停：{exc}")
            return None
        self._record("deadlock", instruction.task, facts=facts, decision=decision, reason=decision["reason"])
        action = decision["action"]
        if action == "retry":
            return instruction
        if action == "reroute":
            dispatch = decision["dispatch"]
            replacement = Instruction(agent=dispatch["agent"], task=dispatch["task"], reason=decision["reason"])
            self._last_key = f"{replacement.agent}\n{replacement.task}"
            self._repeats = 1
            return replacement
        self._pause(f"僵局裁定：{decision['reason']}")
        return None

    def _remember_failure(self, instruction: Instruction, exc: Exception) -> None:
        self.emit(f"{instruction.agent} 失败：{exc}")

    def _handle_worker_error(self, instruction: Instruction, exc: Exception) -> bool:
        key = f"{instruction.agent}\n{instruction.task}"
        if self._failed_key != key:
            self._failed_key = key
            self.emit("同一指令将再跑一次")
            return False
        facts = self._failure_facts("worker_failure", instruction, str(exc))
        try:
            decision = decide_failure(self.completer, self.prompts.get("arbiter-failure.md", ""), facts)
        except ArbiterError as err:
            self._record("worker_failure", instruction.task, facts=facts, error=str(err))
            self._pause(f"失败裁定失败，已暂停：{err}")
            return True
        self._record("worker_failure", instruction.task, facts=facts, decision=decision, reason=decision["reason"])
        if decision["action"] == "retry":
            self._failed_key = ""
            return False
        if decision["action"] == "reroute":
            dispatch = decision["dispatch"]
            self._failed_key = ""
            self._queued = Instruction(agent=dispatch["agent"], task=dispatch["task"], reason=decision["reason"])
            return False
        self._pause(f"失败裁定：{decision['reason']}")
        return True

    def _failure_facts(self, kind: str, instruction: Instruction, error: str) -> dict:
        progress = self.book.progress.load()
        return {
            "kind": kind,
            "agent": instruction.agent,
            "task": instruction.task,
            "error": error,
            "repeats": self._repeats,
            "phase": progress.phase.value if progress is not None else "",
            "next_chapter": progress.next_chapter() if progress is not None else 0,
            "pending_rewrites": list(progress.pending_rewrites) if progress is not None else [],
            "foundation_missing": foundation_missing(self.book.root),
        }

    def _record(self, kind: str, text: str, *, decision=None, facts=None, reason: str = "", error: str = "") -> dict:
        return self.decisions.append(
            {
                "kind": kind,
                "input": text,
                "decision": decision,
                "facts": facts,
                "reason": reason,
                "error": error,
            }
        )

    def _pause(self, reason: str) -> None:
        self.paused = True
        self.pause_reason = reason
        self.emit(reason)


def _chapter_needs_expansion(book: Book, chapter: int) -> bool:
    if chapter <= 0:
        return False
    raw = read_json(book.root, "layered_outline.json")
    if not isinstance(raw, list) or not raw:
        return False
    covered = 0
    for volume in repair_indexes(raw):
        for arc in volume.get("arcs") or []:
            chapters = arc.get("chapters") or []
            if not chapters:
                return chapter > covered
            covered += len(chapters)
    return False
