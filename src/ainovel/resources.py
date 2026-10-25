"""包内数据。文风和界面构建结果都从安装包读取。"""

from importlib.resources import as_file, files
from pathlib import Path

_held: list[object] = []


def package_dir(name: str) -> Path:
    """返回包内目录。普通安装是真实路径；压缩包安装会保持解压结果到进程结束。"""
    resource = files("ainovel").joinpath(name)
    if isinstance(resource, Path):
        return resource
    context = as_file(resource)
    path = context.__enter__()
    _held.append(context)
    return Path(path)
