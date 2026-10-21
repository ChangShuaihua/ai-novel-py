"""离线评测。用生产里的文风组装函数，不写正式书目录。"""

import json
from pathlib import Path

from ainovel.store.decisions import DecisionStore
from ainovel.voice import build_writer_prompt, load_bundle


def compare_styles(book_dir: Path, left_style: str, right_style: str) -> dict:
    bundle = load_bundle("", book_dir, include_home=False)
    protocol = bundle.prompts["writer.md"]
    left = build_writer_prompt(protocol, bundle.voice, bundle.styles.get(left_style, left_style))
    right = build_writer_prompt(protocol, bundle.voice, bundle.styles.get(right_style, right_style))
    return {"same": left == right, "left": left, "right": right}


def replay_decisions(book_dir: Path, completer) -> list[dict]:
    """重放裁定。同一事实要通过同类校验；变了就记下来。不写书目录。"""
    from ainovel.arbiter.validate import validate_failure, validate_intervention, validate_plan_start

    notes = []
    for record in DecisionStore(book_dir).load():
        kind = str(record.get("kind") or "")
        original = record.get("decision") if isinstance(record.get("decision"), dict) else {}
        completion = completer.complete(
            [
                {"role": "system", "content": "按事实重放裁定，只返回 JSON。"},
                {"role": "user", "content": json.dumps({"kind": kind, "facts": record.get("facts"), "input": record.get("input")}, ensure_ascii=False)},
            ],
            [],
        )
        try:
            replayed = _object(completion.content)
            _validate(kind, replayed, record.get("facts") if isinstance(record.get("facts"), dict) else {})
            changed = _changed(kind, original, replayed)
            error = ""
        except (json.JSONDecodeError, ValueError) as exc:
            replayed = {}
            changed = True
            error = str(exc)
        notes.append({"id": record.get("id", ""), "kind": kind, "changed": changed, "error": error, "decision": replayed})
    return notes


def _validate(kind: str, decision: dict, facts: dict) -> None:
    from ainovel.arbiter.validate import validate_failure, validate_intervention, validate_plan_start

    if kind == "plan_start":
        validate_plan_start(decision)
        return
    if kind in ("worker_failure", "deadlock"):
        validate_failure(decision, facts or {"phase": "writing"})
        return
    if kind == "intervention":
        validate_intervention(decision, facts or {"phase": "writing", "completed_chapters": 0, "next_chapter": 1})
        return
    raise ValueError(f"不能重放的裁定类型 {kind}")


def _changed(kind: str, original: dict, replayed: dict) -> bool:
    if kind == "plan_start":
        return original.get("planner") != replayed.get("planner")
    if kind in ("worker_failure", "deadlock"):
        return original.get("action") != replayed.get("action")
    if kind == "intervention":
        return bool(original.get("dispatch")) != bool(replayed.get("dispatch"))
    return True


def _object(content: str) -> dict:
    text = content.strip()
    start = text.find("{")
    end = text.rfind("}")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("裁定必须是对象")
    return payload
