"""用户规则快照。注入和提交检查只读这一份。"""

import json
from pathlib import Path

_FORBIDDEN = ["某种程度上", "值得注意的是", "不知为何", "五味杂陈"]
_FATIGUE = {
    "不禁": 1,
    "竟然": 1,
    "仿佛": 2,
    "此外": 1,
    "然而": 2,
    "一丝": 2,
    "一抹": 2,
    "一缕": 2,
    "宛如": 1,
    "不由得": 1,
    "像一": 3,
    "沉默了": 2,
    "没有说话": 2,
    "几息": 3,
    "一息": 3,
    "数息": 2,
}


def system_snapshot() -> dict:
    return {
        "version": 2,
        "status": "ready",
        "structured": {
            "genre": "",
            "forbidden_chars": [],
            "forbidden_phrases": list(_FORBIDDEN),
            "fatigue_words": dict(_FATIGUE),
        },
        "preferences": "",
        "sources": ["system_defaults"],
        "uncertain": [],
    }


def payload(snapshot: dict) -> dict:
    structured = snapshot.get("structured") if isinstance(snapshot.get("structured"), dict) else {}
    return {
        "structured": {
            "genre": str(structured.get("genre") or ""),
            "forbidden_chars": list(structured.get("forbidden_chars") or []),
            "forbidden_phrases": list(structured.get("forbidden_phrases") or []),
            "fatigue_words": dict(structured.get("fatigue_words") or {}),
        },
        "preferences": str(snapshot.get("preferences") or ""),
    }


def load_snapshot(root: Path) -> dict:
    path = root / "meta" / "user_rules.json"
    if not path.is_file():
        return system_snapshot()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return system_snapshot()
    if not isinstance(raw, dict):
        return system_snapshot()
    if "version" not in raw and "text" in raw:
        return overlay(system_snapshot(), str(raw.get("text") or ""), source="legacy")
    base = system_snapshot()
    structured = raw.get("structured") if isinstance(raw.get("structured"), dict) else {}
    merged = overlay_structured(base["structured"], structured)
    base["structured"] = merged
    base["preferences"] = str(raw.get("preferences") or "")
    base["sources"] = list(raw.get("sources") or base["sources"])
    base["status"] = str(raw.get("status") or "ready")
    base["uncertain"] = list(raw.get("uncertain") or [])
    return base


def overlay(snapshot: dict, text: str, *, source: str = "runtime") -> dict:
    updated = json.loads(json.dumps(snapshot, ensure_ascii=False))
    body = text.strip()
    if body:
        section = f"## [{source}]\n\n{body}" if source else body
        current = str(updated.get("preferences") or "").strip()
        updated["preferences"] = section if not current else current + "\n\n" + section
    sources = list(updated.get("sources") or [])
    if source and source not in sources:
        sources.append(source)
    updated["sources"] = sources
    updated["version"] = 2
    return updated


def overlay_structured(base: dict, incoming: dict) -> dict:
    merged = {
        "genre": str(base.get("genre") or ""),
        "forbidden_chars": list(base.get("forbidden_chars") or []),
        "forbidden_phrases": list(base.get("forbidden_phrases") or []),
        "fatigue_words": dict(base.get("fatigue_words") or {}),
    }
    genre = str(incoming.get("genre") or "").strip()
    if genre:
        merged["genre"] = genre
    chars = [str(item).strip() for item in incoming.get("forbidden_chars") or [] if str(item).strip()]
    if chars:
        merged["forbidden_chars"] = chars
    phrases = [str(item).strip() for item in incoming.get("forbidden_phrases") or [] if str(item).strip()]
    if phrases:
        merged["forbidden_phrases"] = phrases
    fatigue = incoming.get("fatigue_words") or {}
    if isinstance(fatigue, dict):
        for word, limit in fatigue.items():
            name = str(word).strip()
            if name and int(limit) > 0:
                merged["fatigue_words"][name] = int(limit)
    return merged


def save_runtime_rule(root: Path, text: str) -> dict:
    snapshot = overlay(load_snapshot(root), text, source="runtime")
    path = root / "meta" / "user_rules.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot


def check_text(text: str, snapshot: dict) -> list[dict]:
    structured = payload(snapshot)["structured"]
    violations = []
    for name, rule in (
        ("forbidden_chars", structured["forbidden_chars"]),
        ("forbidden_phrases", structured["forbidden_phrases"]),
    ):
        for item in rule:
            count = text.count(item)
            if count:
                violations.append({"rule": name, "target": item, "actual": count, "severity": "error"})
    for word, limit in structured["fatigue_words"].items():
        count = text.count(word)
        if limit > 0 and count > limit:
            violations.append({"rule": "fatigue_words", "target": word, "actual": count, "limit": limit, "severity": "warning"})
    return violations
