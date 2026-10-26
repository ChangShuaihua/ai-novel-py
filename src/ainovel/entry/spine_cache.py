"""书架书脊缓存。只放标题和进度，正文仍在数据库里。"""

from __future__ import annotations

import json
import os
import time

_TTL = 20
_DOWN_FOR = 5.0
_UNSET = object()

_forced = _UNSET
_client_obj = None
_client_url = ""
_down_until = 0.0


def bind(client) -> None:
    """测试里换上假的 Redis。传入 None 表示这次不使用缓存。"""
    global _forced, _down_until
    _forced = client
    _down_until = 0.0


def reset() -> None:
    global _forced, _client_obj, _client_url, _down_until
    _forced = _UNSET
    _client_obj = None
    _client_url = ""
    _down_until = 0.0


def load_spines(user_id: str) -> dict | None:
    if not user_id:
        return None
    client = _client()
    if client is None:
        return None
    try:
        raw = client.get(_key(user_id))
    except Exception:
        _mark_down()
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    books = _rows(payload.get("books"))
    trash = _rows(payload.get("trash"))
    if books is None or trash is None:
        return None
    return {"books": books, "trash": trash}


def store_spines(user_id: str, books: list[dict], trash: list[dict]) -> None:
    if not user_id:
        return
    client = _client()
    if client is None:
        return
    body = json.dumps({"books": books, "trash": trash}, ensure_ascii=False)
    try:
        client.setex(_key(user_id), _TTL, body)
    except Exception:
        _mark_down()


def drop_spines(user_id: str) -> None:
    if not user_id:
        return
    client = _client()
    if client is None:
        return
    try:
        client.delete(_key(user_id))
    except Exception:
        _mark_down()


def _key(user_id: str) -> str:
    return f"ainovel:shelf:{user_id}"


def _rows(value: object) -> list[dict] | None:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        return None
    return value


def _client():
    global _client_obj, _client_url
    if time.monotonic() < _down_until:
        return None
    if _forced is not _UNSET:
        return _forced
    url = os.environ.get("AINOVEL_REDIS_URL", "").strip()
    if not url:
        return None
    if _client_obj is not None and _client_url == url:
        return _client_obj
    try:
        import redis
    except ImportError:
        _mark_down()
        return None
    try:
        client = redis.Redis.from_url(
            url,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
            decode_responses=True,
        )
    except Exception:
        _mark_down()
        return None
    _client_obj = client
    _client_url = url
    return client


def _mark_down() -> None:
    global _down_until
    _down_until = time.monotonic() + _DOWN_FOR
