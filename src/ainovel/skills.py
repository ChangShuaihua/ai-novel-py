"""按代理装入技能正文。技能只补充做法，不改工具权限。"""

from ainovel.resources import package_dir

_AGENT_SKILLS = {
    "architect_short": ("story-planning.md",),
    "architect_long": ("story-planning.md",),
    "character": ("character-design.md",),
    "writer": ("chapter-craft.md",),
    "editor": ("continuity-review.md",),
}


def skill_text(agent: str) -> str:
    names = _AGENT_SKILLS.get(agent, ())
    if not names:
        return ""
    root = package_dir("assets") / "skills"
    parts = []
    for name in names:
        path = root / name
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                parts.append(text)
    if not parts:
        return ""
    return "# 技能\n\n" + "\n\n".join(parts)
