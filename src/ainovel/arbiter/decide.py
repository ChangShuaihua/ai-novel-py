"""单次裁定。事实由调用方收齐，本模块除这一次模型请求外不读盘。"""

import json

from ainovel.arbiter.validate import (
    validate_failure,
    validate_intervention,
    validate_plan_start,
)
from ainovel.llm.errors import ProviderError

_HARD_STOP = {"safety", "content_filter", "length"}


class ArbiterError(RuntimeError):
    """裁定失败。启动失败要报出来；失败和僵局裁定失败则暂停。"""


def decide_plan_start(completer, system: str, requirement: str, style: str = "") -> dict:
    payload = {"requirement": requirement, "style": style}
    return _decide(completer, system, payload, validate_plan_start)


def decide_intervention(completer, system: str, facts: dict, text: str) -> dict:
    payload = {"intervention": text, "facts": facts}
    return _decide(completer, system, payload, lambda decision: validate_intervention(decision, facts))


def decide_failure(completer, system: str, facts: dict) -> dict:
    return _decide(completer, system, facts, lambda decision: validate_failure(decision, facts))


def _decide(completer, system: str, payload: dict, validate, attempts: int = 4) -> dict:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    for _ in range(attempts):
        try:
            completion = completer.complete(messages, [])
        except ProviderError as exc:
            if exc.kind in ("auth", "model_not_found", "unknown"):
                raise ArbiterError(str(exc)) from exc
            raise
        if completion.stop_reason in _HARD_STOP:
            raise ArbiterError(f"模型拒绝继续: {completion.stop_reason}")
        try:
            decision = _extract_object(completion.content)
            validate(decision)
            return decision
        except (json.JSONDecodeError, ValueError) as exc:
            messages.append({"role": "assistant", "content": completion.content})
            messages.append({"role": "user", "content": f"校验失败：{exc}"})
    raise ArbiterError("裁定未能在上下文内通过校验")


def _extract_object(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise json.JSONDecodeError("没有 JSON 对象", text, 0)
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("裁定必须是对象")
    return parsed
