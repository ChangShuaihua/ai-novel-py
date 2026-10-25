"""读取项目根目录的 .env。已经存在的环境变量优先。"""

import os
from pathlib import Path


def load_env() -> None:
    for directory in [Path.cwd(), *Path.cwd().parents]:
        env_file = directory / ".env"
        if env_file.is_file():
            _apply(env_file)
            return
        if (directory / "pyproject.toml").is_file():
            return


def _apply(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")
