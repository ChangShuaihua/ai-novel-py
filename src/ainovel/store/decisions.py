"""裁定审计。追加日志，不是恢复数据源。"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ainovel.store.io import IO

_LIMIT = 8 * 1024


class DecisionStore:
    def __init__(self, root: Path) -> None:
        self._io = IO(root)

    def append(self, record: dict) -> dict:
        stored = {
            "schema_version": 1,
            "id": str(record.get("id") or uuid.uuid4().hex),
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "kind": str(record.get("kind") or ""),
            "decider": str(record.get("decider") or "arbiter"),
        }
        text = str(record.get("input") or "")
        if len(text.encode("utf-8")) > _LIMIT:
            text = text.encode("utf-8")[:_LIMIT].decode("utf-8", errors="ignore")
            stored["input_truncated"] = True
        if text:
            stored["input"] = text
        if record.get("facts") is not None:
            stored["facts"] = record["facts"]
        if record.get("decision") is not None:
            stored["decision"] = record["decision"]
        if record.get("reason"):
            stored["reason"] = record["reason"]
        if record.get("error"):
            stored["error"] = record["error"]
        line = json.dumps(stored, ensure_ascii=False).encode("utf-8") + b"\n"
        self._io.append_line("meta/decisions.jsonl", line)
        return stored

    def load(self) -> list[dict]:
        path = self._io.path("meta/decisions.jsonl")
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows
