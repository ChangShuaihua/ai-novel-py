"""从已有书目生成创建作品要填的资料。只读，不改书。"""

import json
from pathlib import Path

_TITLE_LIMIT = 15
_NAME_LIMIT = 5
_SYNOPSIS_MIN = 50
_SYNOPSIS_MAX = 500
_SOFTEN = {"血腥": "惨烈", "暴力": "冲突", "低俗": ""}


def build_listing(root: Path | str) -> dict:
    directory = Path(root)
    info = _json(directory / "meta" / "book.json")
    characters = _json(directory / "characters.json")
    premise = _text(directory / "premise.md")
    title = _clip(_text_field(info, "title"), _TITLE_LIMIT)
    names = _protagonists(characters)
    synopsis = _synopsis(_text_field(info, "synopsis"), premise, names)
    audience, reading, content = _tags(premise + "\n" + synopsis)
    note = ""
    if names and names[0] not in synopsis:
        note = "简介里的人名和人物表里的主角不一致，贴出去之前对一下。"
    return {
        "title": title,
        "audience": audience,
        "reading_tag": reading,
        "content_tag": content,
        "protagonists": names,
        "synopsis": synopsis,
        "synopsis_count": len(synopsis),
        "cover_prompt": _cover_prompt(title, _ranked(characters), synopsis, premise, reading),
        "note": note,
    }


_PROP_GROUPS = (
    (("账簿", "账本", "账册"), "一本摊开的旧账簿"),
    (("借火", "火种", "以火"), "掌心一簇火"),
    (("棺", "墓"), "幽暗墓室"),
    (("门",), "一扇半开的门"),
)

_COVER_STYLE = {
    "仙侠": "古典仙侠网文封面，水墨底，金红光，衣袂和远山",
    "都市": "现代都市网文封面，夜色，霓虹只留在背景里",
    "悬疑": "悬疑网文封面，冷青背景，一束窄光打在脸上",
    "科幻": "科幻网文封面，冷金属和远处的结构",
    "历史": "历史网文封面，绢本色和旧纸纹理",
    "玄幻": "东方玄幻网文封面，云雾和一件醒目的器物",
}


def _protagonists(raw: object) -> list[str]:
    names: list[str] = []
    for _score, item in _ranked(raw):
        name = str(item.get("name") or "").strip()[:_NAME_LIMIT]
        if name and name not in names:
            names.append(name)
        if len(names) == 2:
            break
    return names


def _ranked(raw: object) -> list[tuple[int, dict]]:
    if not isinstance(raw, list):
        return []
    ranked: list[tuple[int, dict]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        role = str(item.get("role") or "")
        tier = str(item.get("tier") or "")
        score = (2 if "主角" in role else 0) + (1 if tier == "core" else 0)
        ranked.append((score, item))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return ranked


def _cover_prompt(title: str, ranked: list[tuple[int, dict]], synopsis: str, premise: str, reading: str) -> str:
    lead = ranked[0][1] if ranked else None
    name = str(lead.get("name") or "").strip() if lead else ""
    look = _look(lead, synopsis)
    props = _props(premise + "\n" + synopsis + "\n" + look)
    style = _COVER_STYLE.get(reading, _COVER_STYLE["玄幻"])
    subject = f"画面只有一个主体：{name}。" if name else "画面只有一个主体人物。"
    detail = f"{look}。" if look else ""
    prop = f"身边放着{'、'.join(props)}。" if props else ""
    heading = f"上方留白只写书名「{title}」，不要其他文字。" if title else "上方留白，不要写任何文字。"
    return (
        f"竖版小说封面，比例 3:4。{subject}{detail}{prop}"
        f"气质是{style}。{heading}"
        "人物五官清楚，光线集中在脸上。不要见血，不要露骨，不要水印，不要第二个人物抢画面。"
    )


def _look(character: dict | None, synopsis: str) -> str:
    source = ""
    if character is not None:
        source = _first_sentence(_soften(str(character.get("description") or "")))
    if not source:
        source = _first_sentence(_soften(synopsis))
    return _clip(source.rstrip("。"), 36)


def _props(text: str) -> list[str]:
    found: list[str] = []
    for needles, phrase in _PROP_GROUPS:
        if any(needle in text for needle in needles):
            found.append(phrase)
        if len(found) == 2:
            break
    return found


def _first_sentence(text: str) -> str:
    for mark in ("。", "！", "？"):
        if mark in text:
            return text.split(mark, 1)[0].strip()
    return text.strip()


def _synopsis(stored: str, premise: str, names: list[str]) -> str:
    text = _soften(stored.strip())
    if len(text) < _SYNOPSIS_MIN:
        extra = _soften(_plain(premise))
        if names and names[0] not in text and names[0] in extra:
            text = extra
        elif extra and extra not in text:
            text = (text + extra).strip()
    if len(text) > _SYNOPSIS_MAX:
        text = text[:_SYNOPSIS_MAX].rstrip("，。；、")
        if not text.endswith("。"):
            text += "。"
    return text


def _tags(text: str) -> tuple[str, str, str]:
    audience = "女频" if any(word in text for word in ("女频", "女主", "言情")) else "男频"
    if any(word in text for word in ("仙侠", "修仙", "修真")):
        return audience, "仙侠", "古典仙侠"
    if "都市" in text:
        return audience, "都市", "都市日常"
    if "悬疑" in text:
        return audience, "悬疑", "悬疑脑洞"
    if "科幻" in text:
        return audience, "科幻", "未来世界"
    if "历史" in text:
        return audience, "历史", "历史古代"
    return audience, "玄幻", "东方玄幻"


def _plain(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return "".join(lines)


def _soften(text: str) -> str:
    for source, target in _SOFTEN.items():
        text = text.replace(source, target)
    return text


def _clip(text: str, limit: int) -> str:
    return text.strip()[:limit]


def _text_field(raw: object, key: str) -> str:
    if not isinstance(raw, dict):
        return ""
    return str(raw.get(key) or "").strip()


def _json(path: Path):
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")
