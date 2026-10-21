"""用户目录里的模型配置。缺配置时直接失败。"""

import json
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
