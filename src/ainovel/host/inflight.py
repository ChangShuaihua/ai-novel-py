"""在途派单。崩溃后续跑这一条，不把审计日志当成可回写的状态。"""

import uuid

from ainovel.flow.model import Instruction
from ainovel.store.book import Book
from ainovel.store.io import IO

_RELATIVE = "meta/inflight_dispatch.json"
_PARKED = "meta/inflight_parked.json"


def load_inflight(book: Book) -> dict | None:
    path = book.root / "meta" / "inflight_dispatch.json"
    if not path.is_file():
        return None
    payload = IO(book.root).read_json(_RELATIVE)
    if not isinstance(payload, dict):
        return None
    return payload


def save_inflight(book: Book, payload: dict) -> None:
    IO(book.root).write_json(_RELATIVE, payload)


def clear_inflight(book: Book) -> None:
    IO(book.root).remove(_RELATIVE)


def load_parked(book: Book) -> dict | None:
    path = book.root / "meta" / "inflight_parked.json"
    if not path.is_file():
        return None
    payload = IO(book.root).read_json(_PARKED)
    if not isinstance(payload, dict):
        return None
    return payload


def save_parked(book: Book, payload: dict) -> None:
    IO(book.root).write_json(_PARKED, payload)


def clear_parked(book: Book) -> None:
    IO(book.root).remove(_PARKED)


def checkpoint_baseline(book: Book) -> int:
    rows = book.checkpoints.all()
    return max((row.seq for row in rows), default=0)


def inflight_from(instruction: Instruction, *, baseline: int, decision_id: str = "", task_id: str = "") -> dict:
    return {
        "decision_id": decision_id or uuid.uuid4().hex,
        "task_id": task_id,
        "move_id": instruction.move_id(),
        "agent": instruction.agent,
        "duty": instruction.duty,
        "task": instruction.task,
        "reason": instruction.reason,
        "chapter": instruction.chapter,
        "attempt": 1,
        "baseline_checkpoint": baseline,
    }


def instruction_from_inflight(payload: dict) -> Instruction:
    return Instruction(
        agent=str(payload.get("agent") or ""),
        task=str(payload.get("task") or ""),
        reason=str(payload.get("reason") or ""),
        chapter=int(payload.get("chapter") or 0),
        duty=str(payload.get("duty") or ""),
    )


def same_dispatch(payload: dict, instruction: Instruction) -> bool:
    return (
        str(payload.get("agent") or "") == instruction.agent
        and str(payload.get("duty") or "") == instruction.duty
        and str(payload.get("task") or "") == instruction.task
        and int(payload.get("chapter") or 0) == instruction.chapter
    )


def duty_advanced(book: Book, baseline: int, required: set[str]) -> bool:
    """要求的检查点出现在基线之后，才算这张派单已经落地。"""
    if not required:
        return False
    for row in book.checkpoints.all():
        if row.seq > baseline and row.step in required:
            return True
    return False


def newest_step(book: Book, baseline: int) -> str:
    newest = None
    for row in book.checkpoints.all():
        if row.seq <= baseline:
            continue
        if newest is None or row.seq > newest.seq:
            newest = row
    if newest is None:
        return ""
    return newest.step


def worker_report(
    book: Book,
    instruction: Instruction,
    result,
    *,
    baseline: int,
    failure: str | None,
    task_id: str = "",
    required: set[str] | None = None,
) -> dict:
    """短报告只告诉主代理这一轮发生了什么。建议下一步不进入菜单计算。"""
    needed = required or set()
    if failure:
        status = "failed"
    elif needed and not duty_advanced(book, baseline, needed):
        status = "stalled"
    else:
        status = "completed"
    payload = {
        "agent": instruction.agent,
        "duty": instruction.duty,
        "status": status,
        "last_tool": str(getattr(result, "stop_tool", "") or ""),
        "checkpoint_step": newest_step(book, baseline),
        "chapter": instruction.chapter,
        "failure": failure,
        "suggested_next_action": None,
    }
    if task_id:
        payload["task_id"] = task_id
    return payload
