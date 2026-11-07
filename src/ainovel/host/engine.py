"""串行引擎。循环结束就是停，这里不会再把自己启动一次。"""

from dataclasses import dataclass, field

from ainovel.agents.loop import AgentLoopError, CheckpointGuardError
from ainovel.arbiter.decide import ArbiterError, decide_failure, decide_plan_start, decide_schedule
from ainovel.domain.run_meta import PlanStartRecord
from ainovel.domain.transitions import Phase
from ainovel.flow.load import foundation_missing, load_state
from ainovel.flow.model import Duty, Instruction, describe_move
from ainovel.flow.outline import repair_indexes
from ainovel.flow.plan import PlanError, block_dependents, instruction_for, normalize_schedule, open_tasks
from ainovel.flow.route import legal_moves, route
from ainovel.host.gate import ChapterAdvanceGate
from ainovel.host.inflight import (
    checkpoint_baseline,
    clear_inflight,
    clear_parked,
    duty_advanced,
    inflight_from,
    instruction_from_inflight,
    load_inflight,
    load_parked,
    same_dispatch,
    save_inflight,
    save_parked,
    worker_report,
)
from ainovel.host.stall import load_stall, save_stall
from ainovel.host.planfile import clear_plan, load_plan, save_plan
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
        self.latest_instruction: Instruction | None = None
        self.context_usage = ""
        self._yield = False
        self.last_report: dict | None = None
        self._active_task_id = ""
        self._detached = False
        self._stall_loaded = False

    def enqueue(self, instruction: Instruction) -> None:
        self._queued = instruction

    def abort(self) -> None:
        self.cancelled = True

    def request_yield(self) -> None:
        """当前指令结束后退出循环，不记成暂停。界面借这个边界插入干预。"""
        self._yield = True

    def subscribe(self, listener) -> None:
        self.listeners.append(listener)

    def emit(self, text: str) -> None:
        self.events.append(text)
        for listener in list(self.listeners):
            listener(text)

    def run(self, *, max_rounds: int | None = None) -> RunResult:
        rounds = 0
        while not self.cancelled and not self.paused:
            if self._yield:
                self._yield = False
                break
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
            self.latest_instruction = instruction
            inflight = self._begin_inflight(instruction)
            baseline = int(inflight["baseline_checkpoint"])
            try:
                result = self.workers[instruction.agent].run(
                    self.completer,
                    self.book,
                    instruction.task,
                    duty=instruction.duty,
                )
            except KeyError:
                self._pause(f"未知代理 {instruction.agent}，已暂停")
                break
            except (CheckpointGuardError, AgentLoopError, ArbiterError) as exc:
                self._capture_context(instruction.agent)
                self._remember_failure(instruction, exc)
                self.last_report = worker_report(
                    self.book,
                    instruction,
                    None,
                    baseline=baseline,
                    failure=str(exc),
                    task_id=str(inflight.get("task_id") or ""),
                    required=self._required_steps(instruction),
                )
                if self._handle_worker_error(instruction, exc):
                    break
            else:
                self._capture_context(instruction.agent)
                self._failed_key = ""
                self.last_report = worker_report(
                    self.book,
                    instruction,
                    result,
                    baseline=baseline,
                    failure=None,
                    task_id=str(inflight.get("task_id") or ""),
                    required=self._required_steps(instruction),
                )
                if duty_advanced(self.book, baseline, self._required_steps(instruction)):
                    task_id = str(inflight.get("task_id") or "")
                    clear_inflight(self.book)
                    if self._detached:
                        self._restore_parked_inflight()
                    else:
                        self._complete_plan_task(task_id)
                        self._record(
                            "dispatch_settled",
                            instruction.task,
                            decision=self.last_report,
                            reason=instruction.reason,
                        )
                self._detached = False
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
        self._settle_finished_inflight()
        self._restore_parked_inflight()
        inflight = load_inflight(self.book)
        if self._queued is not None:
            instruction = self._queued
            self._queued = None
            self._detached = True
            self._active_task_id = ""
            return self._precheck(instruction)
        self._detached = load_parked(self.book) is not None
        if inflight is not None:
            self._active_task_id = str(inflight.get("task_id") or "")
            return self._precheck(instruction_from_inflight(inflight))
        try:
            state = load_state(self.book)
        except Exception as exc:
            self._pause(f"读取进度失败，已暂停：{exc}")
            return None
        if self._schedule_enabled():
            planned = self._from_saved_plan(state)
            if planned is not None or self.paused:
                return self._precheck(planned) if planned is not None else None
        instruction = self._choose(state)
        if instruction is None:
            return None
        return self._precheck(instruction)

    def _choose(self, state) -> Instruction | None:
        moves = legal_moves(state)
        if not moves:
            return self._plan_start_fallback()
        if not self._schedule_enabled():
            self._active_task_id = ""
            return route(state)
        described = [describe_move(move) for move in moves]
        try:
            decision = decide_schedule(self.completer, self.prompts.get("arbiter-schedule.md", ""), described, self.last_report)
        except ArbiterError as exc:
            self._record("schedule", "", error=str(exc))
            self._pause(f"调度裁定失败，已暂停：{exc}")
            return None
        try:
            plan = normalize_schedule(decision, described)
        except PlanError as exc:
            self._record("schedule", "", error=str(exc))
            self._pause(f"调度裁定失败，已暂停：{exc}")
            return None
        task = open_tasks(plan)[0]
        self._active_task_id = str(task["task_id"])
        save_plan(self.book, plan)
        self._record("schedule", str(task["task"]), decision=plan, reason=str(plan["reason"]))
        return instruction_for(task, str(plan["reason"]))

    def _schedule_enabled(self) -> bool:
        return bool(self.prompts.get("arbiter-schedule.md", "").strip())

    def _settle_finished_inflight(self) -> None:
        inflight = load_inflight(self.book)
        if inflight is None or not self._inflight_settled(inflight):
            return
        task_id = str(inflight.get("task_id") or "")
        clear_inflight(self.book)
        self._complete_plan_task(task_id)

    def _from_saved_plan(self, state) -> Instruction | None:
        plan = load_plan(self.book)
        if plan is None:
            return None
        menu = {str(item["move_id"]): item for item in (describe_move(move) for move in legal_moves(state))}
        ready = open_tasks(plan)
        if not ready:
            pending = any(task.get("status") == "pending" for task in plan.get("tasks") or [])
            if pending:
                self._pause("计划里没有当前可执行的任务")
                return None
            self._drop_stopped_plan(plan)
            return None
        task = ready[0]
        move = menu.get(str(task.get("move_id") or ""))
        if move is None:
            task["status"] = "blocked"
            block_dependents(plan, str(task.get("task_id") or ""))
            save_plan(self.book, plan)
            self._pause(f"计划任务已不在合法菜单里：{task.get('move_id')}")
            return None
        task["agent"] = str(move.get("agent") or "")
        task["duty"] = str(move.get("duty") or "")
        task["chapter"] = int(move.get("chapter") or 0)
        self._active_task_id = str(task.get("task_id") or "")
        save_plan(self.book, plan)
        return instruction_for(task, str(plan.get("reason") or ""))

    def _complete_plan_task(self, task_id: str) -> None:
        if not task_id:
            return
        plan = load_plan(self.book)
        if plan is None:
            return
        for task in plan.get("tasks") or []:
            if str(task.get("task_id") or "") == task_id and task.get("status") != "done":
                task["status"] = "done"
        if plan.get("tasks") and all(task.get("status") == "done" for task in plan["tasks"]):
            clear_plan(self.book)
            return
        save_plan(self.book, plan)

    def _drop_stopped_plan(self, plan: dict) -> None:
        """计划里没有还能做的任务时清掉，并把挡住的原因留给下一次调度。"""
        tasks = list(plan.get("tasks") or [])
        blocked = [str(task.get("move_id") or "") for task in tasks if task.get("status") == "blocked"]
        failed = [str(task.get("move_id") or "") for task in tasks if task.get("status") == "failed"]
        clear_plan(self.book)
        if not blocked and not failed:
            return
        parts = []
        if blocked:
            parts.append("已不在菜单里：" + "、".join(item for item in blocked if item))
        if failed:
            parts.append("已失败：" + "、".join(item for item in failed if item))
        self.last_report = {
            "agent": "",
            "duty": "",
            "status": "blocked",
            "last_tool": "",
            "checkpoint_step": "",
            "chapter": 0,
            "failure": "上一份计划停住，" + "；".join(parts),
            "suggested_next_action": None,
        }

    def _fail_active_plan_task(self) -> None:
        task_id = self._active_task_id
        plan = load_plan(self.book)
        if not plan or not task_id:
            return
        found = False
        for task in plan.get("tasks") or []:
            if str(task.get("task_id") or "") == task_id and task.get("status") != "done":
                task["status"] = "failed"
                found = True
        if not found:
            return
        block_dependents(plan, task_id)
        if open_tasks(plan):
            save_plan(self.book, plan)
        else:
            clear_plan(self.book)

    def _mark_plan_running(self, task_id: str) -> None:
        if not task_id:
            return
        plan = load_plan(self.book)
        if plan is None:
            return
        for task in plan.get("tasks") or []:
            if str(task.get("task_id") or "") == task_id:
                task["status"] = "running"
        save_plan(self.book, plan)

    def _instruction_from_move(self, decision: dict, moves: list[dict]) -> Instruction:
        move_id = str(decision.get("move_id") or "")
        chosen = next(item for item in moves if str(item.get("move_id") or "") == move_id)
        task = str(decision.get("task") or chosen["task"]).strip()
        return Instruction(
            agent=str(chosen["agent"]),
            task=task,
            reason=str(decision.get("reason") or chosen["reason"]),
            chapter=int(chosen.get("chapter") or 0),
            duty=str(chosen.get("duty") or ""),
        )

    def _precheck(self, instruction: Instruction) -> Instruction | None:
        progress = self.book.progress.load()
        if progress is not None and progress.phase == Phase.COMPLETE:
            self.emit("完本期派发已丢弃")
            return None
        if instruction.agent == "writer" and _chapter_needs_expansion(self.book, instruction.chapter or (progress.next_chapter() if progress else 0)):
            self._active_task_id = ""
            return Instruction(
                agent="architect_long",
                task="下一弧仍是骨架。调用 expand_next_arc 展开下一弧。",
                reason="写作目标章未展开，先展开再续写",
                duty=Duty.EXPAND_ARC,
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
        self._load_stall()
        key = self._instruction_key(instruction)
        if key == self._last_key:
            self._repeats += 1
        else:
            self._last_key = key
            self._repeats = 1
        self._save_stall()
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
            replacement = self._reroute(decision, facts)
            if replacement is None:
                return None
            self._fail_active_plan_task()
            self._active_task_id = ""
            self._last_key = self._instruction_key(replacement)
            self._repeats = 1
            self._save_stall()
            return replacement
        self._pause(f"僵局裁定：{decision['reason']}")
        return None

    def _remember_failure(self, instruction: Instruction, exc: Exception) -> None:
        self.emit(f"{instruction.agent} 失败：{exc}")

    def _handle_worker_error(self, instruction: Instruction, exc: Exception) -> bool:
        key = self._instruction_key(instruction)
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
            replacement = self._reroute(decision, facts)
            if replacement is None:
                return True
            self._fail_active_plan_task()
            self._active_task_id = ""
            self._failed_key = ""
            self._queued = replacement
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
            "legal_moves": self._menu(),
        }

    def _menu(self) -> list[dict]:
        try:
            return [describe_move(move) for move in legal_moves(load_state(self.book))]
        except Exception:
            return []

    def _reroute(self, decision: dict, facts: dict) -> Instruction | None:
        moves = [item for item in (facts.get("legal_moves") or []) if isinstance(item, dict)]
        move_id = str(decision.get("move_id") or "")
        if move_id:
            try:
                return self._instruction_from_move(decision, moves)
            except StopIteration:
                self._pause(f"失败改派的 move_id 已不在菜单里：{move_id}")
                return None
        dispatch = decision.get("dispatch") or {}
        return Instruction(agent=dispatch["agent"], task=dispatch["task"], reason=decision["reason"])

    def _instruction_key(self, instruction: Instruction) -> str:
        mark = self._duty_mark(instruction)
        if instruction.duty:
            return f"{instruction.agent}\n{instruction.duty}\n{instruction.chapter}\n{mark}"
        return f"{instruction.agent}\n{instruction.task}\n{mark}"

    def _duty_mark(self, instruction: Instruction) -> int:
        """只看本职责要求的检查点。plan、draft 这类中间步骤不把僵局计数清零。"""
        required = self._required_steps(instruction)
        newest = 0
        if not required:
            return newest
        for row in self.book.checkpoints.all():
            if row.step in required and row.seq > newest:
                newest = row.seq
        return newest

    def _required_steps(self, instruction: Instruction) -> set[str]:
        worker = self.workers.get(instruction.agent)
        steps_for = getattr(worker, "steps_for", None)
        if steps_for is None:
            return set()
        return set(steps_for(instruction.task, instruction.duty))

    def _inflight_settled(self, payload: dict) -> bool:
        instruction = instruction_from_inflight(payload)
        baseline = int(payload.get("baseline_checkpoint") or 0)
        return duty_advanced(self.book, baseline, self._required_steps(instruction))

    def _load_stall(self) -> None:
        if self._stall_loaded:
            return
        self._stall_loaded = True
        stored = load_stall(self.book)
        if stored is None:
            return
        self._last_key = str(stored.get("key") or "")
        self._repeats = int(stored.get("repeats") or 0)

    def _save_stall(self) -> None:
        save_stall(self.book, self._last_key, self._repeats)

    def _restore_parked_inflight(self) -> None:
        if load_inflight(self.book) is not None:
            return
        parked = load_parked(self.book)
        if parked is None:
            return
        save_inflight(self.book, parked)
        clear_parked(self.book)
        self._active_task_id = str(parked.get("task_id") or "")

    def _begin_inflight(self, instruction: Instruction) -> dict:
        existing = load_inflight(self.book)
        if self._detached:
            if existing is not None and not same_dispatch(existing, instruction) and load_parked(self.book) is None:
                save_parked(self.book, existing)
            if existing is not None and same_dispatch(existing, instruction) and not self._inflight_settled(existing):
                return existing
            payload = inflight_from(instruction, baseline=checkpoint_baseline(self.book), task_id="")
            save_inflight(self.book, payload)
            return payload
        if existing is not None and same_dispatch(existing, instruction):
            if not self._inflight_settled(existing):
                return existing
        payload = inflight_from(
            instruction,
            baseline=checkpoint_baseline(self.book),
            task_id=self._active_task_id,
        )
        save_inflight(self.book, payload)
        self._mark_plan_running(self._active_task_id)
        return payload

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

    def _capture_context(self, agent: str) -> None:
        worker = self.workers.get(agent)
        usage = getattr(worker, "usage", None) if worker is not None else None
        text = str(getattr(usage, "text", "") or "")
        if text:
            self.context_usage = text

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
