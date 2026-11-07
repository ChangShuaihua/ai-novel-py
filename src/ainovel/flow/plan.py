"""主代理提交的任务计划。纯函数，不读盘。

没有依赖的任务必须落在当前合法菜单里。下游任务先只检查依赖，轮到时再对菜单。
"""

import uuid

from ainovel.flow.model import Instruction


class PlanError(ValueError):
    """计划结构或当前菜单对不上。原因可以送回模型。"""


def normalize_schedule(decision: dict, moves: list[dict]) -> dict:
    """把 dispatch 或 create_plan 收成一份计划。代理、职责和章节号从菜单拷贝。"""
    kind = str(decision.get("decision") or "")
    reason = str(decision.get("reason") or "").strip()
    if not reason:
        raise PlanError("reason 不能为空")
    if kind == "dispatch":
        raw_tasks = [
            {
                "task_id": "t1",
                "move_id": decision.get("move_id"),
                "task": decision.get("task"),
                "depends_on": [],
                "agent": decision.get("agent"),
            }
        ]
    elif kind == "create_plan":
        raw = decision.get("tasks")
        if not isinstance(raw, list) or not raw:
            raise PlanError("tasks 不能为空")
        raw_tasks = []
        for item in raw:
            if not isinstance(item, dict):
                raise PlanError("task 必须是对象")
            depends = item.get("depends_on") or []
            if not isinstance(depends, list):
                raise PlanError("depends_on 必须是数组")
            raw_tasks.append(
                {
                    "task_id": item.get("task_id"),
                    "move_id": item.get("move_id"),
                    "task": item.get("task"),
                    "depends_on": depends,
                    "agent": item.get("agent"),
                }
            )
    else:
        raise PlanError("调度决定只能是 dispatch 或 create_plan")

    tasks = [_clean_task(item) for item in raw_tasks]
    _reject_structure(tasks)
    menu = {str(item.get("move_id") or ""): item for item in moves}
    ready = _initially_ready(tasks)
    if not ready:
        raise PlanError("计划没有当前可执行的任务")
    for item in tasks:
        if item["task_id"] not in ready:
            continue
        move = menu.get(item["move_id"])
        if move is None:
            raise PlanError(f"move_id 不在合法菜单里: {item['move_id']}")
        supplied = item.pop("_agent", None)
        if supplied not in (None, "") and str(supplied) != str(move.get("agent") or ""):
            raise PlanError("agent 由菜单决定，调度不能修改")
        item["agent"] = str(move.get("agent") or "")
        item["duty"] = str(move.get("duty") or "")
        item["chapter"] = int(move.get("chapter") or 0)
    for item in tasks:
        item.pop("_agent", None)
    return {"plan_id": uuid.uuid4().hex, "reason": reason, "tasks": tasks}


def open_tasks(plan: dict) -> list[dict]:
    """正在执行的任务优先。否则返回依赖已满足、尚未开始的任务。"""
    tasks = list(plan.get("tasks") or [])
    running = [task for task in tasks if task.get("status") == "running"]
    if running:
        return running[:1]
    done = {str(task.get("task_id") or "") for task in tasks if task.get("status") == "done"}
    ready = []
    for task in tasks:
        if task.get("status") != "pending":
            continue
        if all(dep in done for dep in task.get("depends_on") or []):
            ready.append(task)
    return ready


def block_dependents(plan: dict, task_id: str) -> None:
    """依赖这条任务的下游改为 blocked，并继续传递。"""
    poisoned = {task_id}
    changed = True
    while changed:
        changed = False
        for task in plan.get("tasks") or []:
            current = str(task.get("task_id") or "")
            if current in poisoned or task.get("status") in ("done", "failed"):
                continue
            if any(dep in poisoned for dep in task.get("depends_on") or []):
                task["status"] = "blocked"
                poisoned.add(current)
                changed = True


def instruction_for(task: dict, reason: str) -> Instruction:
    return Instruction(
        agent=str(task.get("agent") or ""),
        task=str(task.get("task") or ""),
        reason=reason,
        chapter=int(task.get("chapter") or 0),
        duty=str(task.get("duty") or ""),
    )


def _clean_task(item: dict) -> dict:
    return {
        "task_id": str(item.get("task_id") or "").strip(),
        "move_id": str(item.get("move_id") or "").strip(),
        "agent": "",
        "duty": "",
        "chapter": 0,
        "task": str(item.get("task") or "").strip(),
        "depends_on": [str(dep) for dep in item.get("depends_on") or []],
        "status": "pending",
        "_agent": item.get("agent"),
    }


def _reject_structure(tasks: list[dict]) -> None:
    ids = [task["task_id"] for task in tasks]
    if any(not task_id for task_id in ids):
        raise PlanError("task_id 不能为空")
    if len(ids) != len(set(ids)):
        raise PlanError("task_id 重复")
    move_ids = [task["move_id"] for task in tasks]
    if any(not move_id for move_id in move_ids):
        raise PlanError("move_id 不能为空")
    if len(move_ids) != len(set(move_ids)):
        raise PlanError("move_id 重复")
    known = set(ids)
    for task in tasks:
        if not task["task"]:
            raise PlanError("task 不能为空")
        for dep in task["depends_on"]:
            if dep == task["task_id"]:
                raise PlanError("任务不能依赖自己")
            if dep not in known:
                raise PlanError(f"依赖不存在: {dep}")
    if _has_cycle(tasks):
        raise PlanError("任务依赖存在环")


def _initially_ready(tasks: list[dict]) -> set[str]:
    return {task["task_id"] for task in tasks if not task["depends_on"]}


def _has_cycle(tasks: list[dict]) -> bool:
    deps = {task["task_id"]: task["depends_on"] for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def walk(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dep in deps.get(node, []):
            if walk(dep):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(walk(task_id) for task_id in deps)
