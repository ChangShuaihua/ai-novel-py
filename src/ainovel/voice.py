"""文风组装。`{{VOICE}}` 只在这里替换。"""

import re
from dataclasses import dataclass, field
from pathlib import Path

_PLACEHOLDER = "{{VOICE}}"
_STYLE_NAME = re.compile(r"^[a-z0-9-]+$")
_PROMPT_FILES = (
    "architect-short.md",
    "architect-long.md",
    "writer.md",
    "editor.md",
    "arbiter-plan-start.md",
    "arbiter-intervention.md",
    "arbiter-failure.md",
)
_GLOBAL_HEADING = "## 用户全局文风覆盖（以下要求优先于项目默认）"
_BOOK_HEADING = "## 本书文风覆盖（以下要求优先于以上全部）"


@dataclass
class Bundle:
    prompts: dict[str, str]
    voice: str
    styles: dict[str, str]
    references: dict[str, str] = field(default_factory=dict)


def assets_root() -> Path:
    return Path(__file__).resolve().parents[2] / "assets"


def build_writer_prompt(protocol: str, voice: str, style: str = "") -> str:
    """协议里的占位符原位换成文风，再接上风格预设。生产、评测和测试都走这里。"""
    text = protocol.replace(_PLACEHOLDER, voice.strip(), 1)
    if style.strip():
        text += "\n\n" + style.strip()
    return text


def load_bundle(
    style: str = "",
    book_dir: Path | None = None,
    *,
    home_style_dir: Path | None = None,
    include_home: bool = True,
) -> Bundle:
    """内置资产优先被读入。全局和本书的文风以带标题的段落追加；同名风格预设整文件替换。"""
    root = assets_root()
    home = home_style_dir
    if include_home and home is None:
        home = Path.home() / ".ainovel" / "style"
    if not include_home and home_style_dir is None:
        home = None
    book = book_dir / "style" if book_dir is not None else None
    prompts = {name: (root / "prompts" / name).read_text(encoding="utf-8") for name in _PROMPT_FILES}
    voice = _append((root / "voice.md").read_text(encoding="utf-8"), "voice.md", home, book)
    styles = _load_styles(root / "styles", home, book)
    references = _load_references(root / "references", style, home, book)
    return Bundle(prompts=prompts, voice=voice, styles=styles, references=references)


def _append(builtin: str, name: str, home: Path | None, book: Path | None) -> str:
    text = builtin
    home_text = _override(home, name)
    if home_text:
        text += f"\n\n{_GLOBAL_HEADING}\n\n{home_text}"
    book_text = _override(book, name)
    if book_text:
        text += f"\n\n{_BOOK_HEADING}\n\n{book_text}"
    return text


def _override(directory: Path | None, relative: str) -> str:
    if directory is None:
        return ""
    path = directory / relative
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _load_styles(builtin_dir: Path, home: Path | None, book: Path | None) -> dict[str, str]:
    styles = {path.stem: path.read_text(encoding="utf-8") for path in sorted(builtin_dir.glob("*.md"))}
    for directory in (home, book):
        if directory is None:
            continue
        folder = directory / "styles"
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            if _STYLE_NAME.match(path.stem):
                styles[path.stem] = path.read_text(encoding="utf-8")
    return styles


def _load_references(builtin_dir: Path, style: str, home: Path | None, book: Path | None) -> dict[str, str]:
    references = {
        path.relative_to(builtin_dir).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(builtin_dir.rglob("*.md"))
    }
    if "anti-ai-tone.md" in references:
        references["anti-ai-tone.md"] = _append(references["anti-ai-tone.md"], "anti-ai-tone.md", home, book)
    if style and style != "default":
        relative = f"genres/{style}/style-references.md"
        for directory in (home, book):
            override = _override(directory, relative)
            if override:
                references[relative] = override
    return references
