"""用户目录里的模型配置。缺配置时直接失败。"""

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field


class ConfigError(RuntimeError):
    """无界面模式不进入向导。"""


class RoleConfig(BaseModel):
    provider: str = ""
    model: str = ""
    api_key: str = ""
    api_base: str = ""
    fallbacks: list[dict] = Field(default_factory=list)


class AppConfig(BaseModel):
    provider: str
    model: str
    api_key: str = ""
    api_base: str = ""
    style: str = ""
    roles: dict[str, RoleConfig] = Field(default_factory=dict)


def config_dir() -> Path:
    return Path.home() / ".ainovel"


def load_config(path: Path | None = None) -> AppConfig:
    target = path or (config_dir() / "config.json")
    home = config_dir()
    if not target.is_file():
        raise ConfigError(f"缺少模型配置：{target}。请在 {home} 放置 config.json，写明 provider、model 和 api_key。")
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"无法读取 {home} 的 config.json：{exc}") from exc
    if not isinstance(raw, dict) or not str(raw.get("provider") or "").strip() or not str(raw.get("model") or "").strip():
        raise ConfigError(f"{home} 的 config.json 必须写明 provider 和 model。")
    return AppConfig.model_validate(raw)


def describe_model(config: AppConfig | None) -> dict:
    """给界面的模型状态。不含密钥正文。"""
    if config is None:
        return {
            "ready": False,
            "provider": "",
            "model": "",
            "api_base": "",
            "style": "",
            "api_key_set": False,
            "key_hint": "",
        }
    key = config.api_key or ""
    return {
        "ready": bool(config.provider.strip() and config.model.strip()),
        "provider": config.provider,
        "model": config.model,
        "api_base": config.api_base,
        "style": config.style,
        "api_key_set": bool(key),
        "key_hint": f"····{key[-4:]}" if len(key) >= 8 else "",
    }


def store_config(
    path: Path,
    *,
    provider: str,
    model: str,
    api_key: str,
    api_base: str,
    style: str,
) -> None:
    """写回配置。原文件里的其他字段（例如 roles）保留。"""
    raw: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = None
        if isinstance(loaded, dict):
            raw = loaded
    raw["provider"] = provider
    raw["model"] = model
    raw["api_key"] = api_key
    raw["api_base"] = api_base
    raw["style"] = style
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    text = json.dumps(raw, ensure_ascii=False, indent=2) + "\n"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
