"""从已有书目生成创建作品要填的资料。只读，不改书。"""

import json
import re
from pathlib import Path

from ainovel.store.paths import chapter_number

_TITLE_LIMIT = 15
_NAME_LIMIT = 5
_SYNOPSIS_MIN = 50
_SYNOPSIS_MAX = 500
_SOFTEN = {"血腥": "惨烈", "暴力": "冲突", "低俗": ""}
_NAME_PATTERNS = (
    re.compile(r"[，,、]([一-龥]{2,3})又"),
    re.compile(r"(?:名叫|名为|叫做|叫作)([一-龥]{2,3})"),
    re.compile(r"的([一-龥]{2,3})(?:在|把|对|又|总)"),
)
_STOP_NAMES = {
    "父亲", "母亲", "爸爸", "妈妈", "爷爷", "奶奶", "哥哥", "姐姐", "弟弟", "妹妹",
    "他们", "她们", "我们", "自己", "什么", "这个", "那个", "一个", "这里", "那里",
    "贝壳", "海螺", "海浪", "沙滩", "海边", "渔船", "声音", "今天", "每天", "村里",
    "别人", "众人", "退潮", "台风",
}


def build_listing(root: Path | str) -> dict:
    directory = Path(root)
    info = _json(directory / "meta" / "book.json")
    characters = _json(directory / "characters.json")
    premise = _text(directory / "premise.md")
    title = _clip(_text_field(info, "title"), _TITLE_LIMIT)
    chapter_plain, summaries = _written(directory)
    stored = _text_field(info, "synopsis")
    sheet_names = _protagonists(characters)
    names = sheet_names or _article_names(chapter_plain, "\n".join(summaries))
    # 开书时存的简介会把还没写到的情节也写进去。有正文时只摘已写的章节。
    if chapter_plain.strip():
        synopsis = _from_written(chapter_plain, summaries)
        about = "\n".join(summaries) or stored
        audience = _audience(chapter_plain, about + "\n" + premise)
        reading, content = _genre(premise + "\n" + chapter_plain + "\n" + "\n".join(summaries))
        cover_text = chapter_plain
    else:
        synopsis = _synopsis(stored, premise, names)
        audience, reading, content = _tags(premise + "\n" + synopsis)
        cover_text = premise
    note = ""
    if sheet_names and sheet_names[0] not in synopsis:
        note = "简介里的人名和人物表里的主角不一致，贴出去之前对一下。"
    ranked = _ranked(characters)
    if not ranked and names:
        ranked = [(2, {"name": names[0]})]
    return {
        "title": title,
        "audience": audience,
        "reading_tag": reading,
        "content_tag": content,
        "protagonists": names,
        "synopsis": synopsis,
        "synopsis_count": len(synopsis),
        "cover_prompt": _cover_prompt(title, ranked, synopsis, cover_text, reading),
        "note": note,
    }


_PROP_GROUPS = (
    (("贝壳", "海螺", "螺壳"), "一枚螺壳"),
    (("账簿", "账本", "账册"), "一本摊开的旧账簿"),
    (("借火", "火种", "以火"), "掌心一簇火"),
    (("棺", "墓"), "幽暗墓室"),
    (("敲门", "门口", "开门", "门前", "门缝", "关门", "房门"), "一扇半开的门"),
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
    return _cut_phrase(source, 36)


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
    reading, content = _genre(text)
    return _audience("", text), reading, content


def _audience(chapter: str, about: str) -> str:
    blob = f"{chapter}\n{about}"
    if any(word in blob for word in ("女频", "女主", "言情", "姑娘", "女孩", "少女")):
        return "女频"
    if any(word in blob for word in ("男频", "男主")):
        return "男频"
    hers = about.count("她")
    his = about.count("他") - hers
    if hers > 0 and hers >= his:
        return "女频"
    return "男频"


def _genre(text: str) -> tuple[str, str]:
    if any(word in text for word in ("仙侠", "修仙", "修真")):
        return "仙侠", "古典仙侠"
    if "都市" in text:
        return "都市", "都市日常"
    if any(word in text for word in ("悬疑", "失踪", "凶手", "案件")):
        return "悬疑", "悬疑脑洞"
    if "科幻" in text:
        return "科幻", "未来世界"
    if "历史" in text:
        return "历史", "历史古代"
    return "玄幻", "东方玄幻"


def _written(root: Path) -> tuple[str, list[str]]:
    outline = _outline_map(root)
    bodies: list[str] = []
    summaries: list[str] = []
    for number in _completed(root):
        body = _plain(_chapter_text(root, number))
        if not body:
            continue
        bodies.append(body)
        summary = outline.get(number, "")
        if summary:
            summaries.append(summary)
    return "".join(bodies), summaries


def _completed(root: Path) -> list[int]:
    progress = _json(root / "meta" / "progress.json")
    if isinstance(progress, dict) and "completed_chapters" in progress:
        numbers: list[int] = []
        for item in progress.get("completed_chapters") or []:
            try:
                number = int(item)
            except (TypeError, ValueError):
                continue
            if number > 0:
                numbers.append(number)
        return numbers
    folder = root / "chapters"
    if not folder.is_dir():
        return []
    found: list[int] = []
    for path in sorted(folder.glob("*.md")):
        if path.stem.isdigit():
            found.append(int(path.stem))
    return found


def _outline_map(root: Path) -> dict[int, str]:
    raw = _json(root / "outline.json")
    found: dict[int, str] = {}
    if not isinstance(raw, list):
        return found
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("chapter") or 0)
        except (TypeError, ValueError):
            continue
        summary = str(item.get("summary") or "").strip()
        if number > 0 and summary:
            found[number] = summary
    return found


def _chapter_text(root: Path, number: int) -> str:
    return _text(root / "chapters" / f"{chapter_number(number)}.md")


def _article_names(chapter: str, summary: str) -> list[str]:
    found: list[str] = []
    for source in (summary, chapter):
        for pattern in _NAME_PATTERNS:
            for match in pattern.finditer(source):
                name = match.group(1).strip()[:_NAME_LIMIT]
                if len(name) < 2 or name in _STOP_NAMES or name not in chapter:
                    continue
                if name not in found:
                    found.append(name)
                if len(found) == 2:
                    return found
    return found


def _from_written(chapter: str, summaries: list[str]) -> str:
    parts: list[str] = []
    for item in summaries:
        cleaned = _without_absent_age(item, chapter).strip("，。；、 ")
        if cleaned:
            parts.append(cleaned.strip("。"))
    text = "。".join(parts)
    if text and not text.endswith(("。", "！", "？")):
        text += "。"
    if len(text) < _SYNOPSIS_MIN and chapter and chapter not in text:
        text = (text + chapter).strip()
    return _bound(text)


_AGE = re.compile(r"[零〇一二三四五六七八九十百两\d]{1,3}岁的?")


def _without_absent_age(text: str, chapter: str) -> str:
    def replace(match: re.Match[str]) -> str:
        phrase = match.group(0)
        return phrase if phrase in chapter else ""

    return _AGE.sub(replace, text)


def _bound(text: str) -> str:
    text = _soften(text.strip())
    if len(text) <= _SYNOPSIS_MAX:
        return text
    cut = text[:_SYNOPSIS_MAX]
    end = max(cut.rfind("。"), cut.rfind("！"), cut.rfind("？"))
    if end >= _SYNOPSIS_MIN - 1:
        return cut[: end + 1]
    clipped = cut.rstrip("，。；、")
    if clipped and not clipped.endswith("。"):
        clipped += "。"
    return clipped


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


def _cut_phrase(text: str, limit: int) -> str:
    text = text.strip().rstrip("。")
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(mark) for mark in ("，", "；", "、", "。", "！", "？"))
    if end >= 8:
        return cut[:end]
    return cut


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
