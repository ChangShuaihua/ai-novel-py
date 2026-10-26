"""网页新书的确认流程：题目、大纲、逐章。每一步停下来等人。"""

from __future__ import annotations

import json
from pathlib import Path

from ainovel.domain.book import BookMetadata
from ainovel.domain.progress import Progress
from ainovel.domain.transitions import FlowState, Phase
from ainovel.store.book import Book
from ainovel.store.paths import chapter_number

_GUIDE = "meta/guide.json"


class GuideError(RuntimeError):
    """这一步没有得到可用的结果。已经写下的内容保留。"""


def load_guide(root: Path) -> dict | None:
    path = root / _GUIDE
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    stage = str(payload.get("stage") or "")
    if stage not in {"title", "outline", "chapter", "done"}:
        return None
    chapter = int(payload.get("chapter") or 0)
    outline = _outline(root)
    title, synopsis = _book_fields(root)
    chapter_title, chapter_body = _chapter_text(root, chapter)
    return {
        "stage": stage,
        "requirement": str(payload.get("requirement") or ""),
        "revision": int(payload.get("revision") or 0),
        "chapter": chapter,
        "title": title,
        "synopsis": synopsis,
        "outline": outline,
        "outline_text": format_outline(outline),
        "chapter_title": chapter_title,
        "chapter_body": chapter_body,
        "remaining": max(0, len(outline) - chapter) if stage == "chapter" else 0,
    }


def begin(root: Path, requirement: str, ask, *, title: str = "", synopsis: str = "") -> None:
    given_title = title.strip()[:24]
    given_synopsis = synopsis.strip()[:1000]
    text = requirement.strip() or given_synopsis or given_title
    if not text:
        raise GuideError("先写下标题、简介，或要写的内容")
    _write_state(root, stage="title", requirement=text, chapter=0)
    _save_progress(root, phase=Phase.INIT, total=0, completed=[])
    if given_title and given_synopsis:
        _save_book(root, given_title, given_synopsis)
        _save_progress(root, phase=Phase.PREMISE, total=0, completed=[])
        _bump(root)
        return
    produced = _object(ask(_title_messages(text)))
    title = str(produced.get("title") or "").strip()
    synopsis = str(produced.get("synopsis") or "").strip()
    if not title or not synopsis:
        raise GuideError("题目没有生成出来")
    _save_book(root, title, synopsis)
    _save_progress(root, phase=Phase.PREMISE, total=0, completed=[])
    _bump(root)


def confirm(root: Path, payload: dict, ask) -> None:
    state = _state(root)
    stage = state["stage"]
    if stage == "title":
        _confirm_title(root, state, payload, ask)
        return
    if stage == "outline":
        _confirm_outline(root, state, payload, ask)
        return
    if stage == "chapter":
        _confirm_chapter(root, state, payload, ask)
        return
    raise GuideError("大纲里的章节都确认过了")


def revise(root: Path, payload: dict, ask) -> None:
    state = _state(root)
    if state["stage"] not in {"chapter", "done"}:
        raise GuideError("现在还没有可以交给模型改的章节")
    text = str(payload.get("text") or "").strip()
    if not text:
        raise GuideError("先写下要改的要求")
    chapter = int(state["chapter"])
    current_title, current_body = _chapter_text(root, chapter)
    edited_title = str(payload.get("chapter_title") or "").strip() or current_title
    edited_body = str(payload.get("chapter_body") or "").strip() or current_body
    if edited_body and edited_body != current_body:
        _write_chapter(root, chapter, edited_title, edited_body)
        current_title, current_body = edited_title, edited_body
    produced = _object(
        ask(
            _revise_messages(
                state["requirement"],
                _book_fields(root),
                _outline(root),
                chapter,
                current_title,
                current_body,
                text,
            )
        )
    )
    _write_chapter(root, chapter, str(produced.get("title") or current_title), str(produced.get("body") or ""))
    _bump(root)


def format_outline(outline: list[dict]) -> str:
    lines = []
    for item in outline:
        lines.append(f"{item['chapter']}. {item['title']}：{item['summary']}")
    return "\n".join(lines)


def parse_outline(text: str) -> list[dict]:
    outline = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        head, separator, tail = line.partition(".")
        if separator and head.strip().isdigit():
            line = tail.strip()
        title, separator, summary = line.partition("：")
        if not separator:
            title, separator, summary = line.partition(":")
        title = title.strip()
        summary = summary.strip()
        if not title:
            continue
        outline.append({"chapter": len(outline) + 1, "title": title, "summary": summary or title})
    if len(outline) < 1:
        raise GuideError("大纲至少要有一章")
    return outline


def _confirm_title(root: Path, state: dict, payload: dict, ask) -> None:
    title = str(payload.get("title") or "").strip()
    synopsis = str(payload.get("synopsis") or "").strip()
    current_title, current_synopsis = _book_fields(root)
    title = title or current_title
    synopsis = synopsis or current_synopsis
    if not title or not synopsis:
        produced = _object(ask(_title_messages(state["requirement"])))
        title = str(produced.get("title") or "").strip()
        synopsis = str(produced.get("synopsis") or "").strip()
        if not title or not synopsis:
            raise GuideError("题目没有生成出来")
        _save_book(root, title, synopsis)
        _save_progress(root, phase=Phase.PREMISE, total=0, completed=[])
        _bump(root)
        return
    _save_book(root, title, synopsis)
    produced = _object(ask(_outline_messages(state["requirement"], title, synopsis)))
    chapters = produced.get("chapters")
    if not isinstance(chapters, list):
        raise GuideError("大纲没有生成出来")
    outline = []
    for item in chapters:
        if not isinstance(item, dict):
            continue
        name = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        if not name:
            continue
        outline.append({"chapter": len(outline) + 1, "title": name, "summary": summary or name})
    if not outline:
        raise GuideError("大纲没有生成出来")
    _save_outline(root, outline)
    _save_progress(root, phase=Phase.OUTLINE, total=len(outline), completed=[])
    _write_state(root, stage="outline", requirement=state["requirement"], chapter=0)


def _confirm_outline(root: Path, state: dict, payload: dict, ask) -> None:
    text = str(payload.get("outline_text") if payload.get("outline_text") is not None else format_outline(_outline(root)))
    outline = parse_outline(text)
    _save_outline(root, outline)
    _save_progress(root, phase=Phase.OUTLINE, total=len(outline), completed=[])
    _write_chapter_from_model(root, state["requirement"], outline, 1, ask)
    _write_state(root, stage="chapter", requirement=state["requirement"], chapter=1)


def _confirm_chapter(root: Path, state: dict, payload: dict, ask) -> None:
    chapter = int(state["chapter"])
    outline = _outline(root)
    if chapter < 1 or chapter > len(outline):
        raise GuideError("这一章不在大纲里")
    title = str(payload.get("chapter_title") or "").strip()
    body = str(payload.get("chapter_body") or "").strip()
    if title or body:
        current_title, current_body = _chapter_text(root, chapter)
        _write_chapter(root, chapter, title or current_title, body or current_body)
    if chapter >= len(outline):
        _save_progress(root, phase=Phase.WRITING, total=len(outline), completed=list(range(1, chapter + 1)))
        _write_state(root, stage="done", requirement=state["requirement"], chapter=chapter)
        return
    nxt = chapter + 1
    _write_chapter_from_model(root, state["requirement"], outline, nxt, ask)
    _write_state(root, stage="chapter", requirement=state["requirement"], chapter=nxt)


def _write_chapter_from_model(root: Path, requirement: str, outline: list[dict], chapter: int, ask) -> None:
    previous = ""
    if chapter > 1:
        _, previous = _chapter_text(root, chapter - 1)
        previous = previous[-800:]
    produced = _object(ask(_chapter_messages(requirement, _book_fields(root), outline, chapter, previous)))
    body = str(produced.get("body") or "").strip()
    if not body:
        raise GuideError(f"第 {chapter} 章没有写出来")
    title = str(produced.get("title") or outline[chapter - 1]["title"]).strip()
    _write_chapter(root, chapter, title, body)
    _save_progress(root, phase=Phase.WRITING, total=len(outline), completed=list(range(1, chapter + 1)))


def _title_messages(requirement: str) -> list[dict]:
    return [
        {"role": "system", "content": "你在为一部中文小说起名。只返回 JSON，对象含 title 和 synopsis。title 不超过 15 个字。synopsis 用 80 到 160 个字写出人物和冲突。不要 Markdown。"},
        {"role": "user", "content": requirement},
    ]


def _outline_messages(requirement: str, title: str, synopsis: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": "你在写中文小说大纲。只返回 JSON，对象含 chapters 数组。每项含 title 和 summary。短篇 4 到 8 章，长篇 8 到 16 章。summary 用一两句写出这一章发生的事。不要 Markdown。",
        },
        {"role": "user", "content": f"书名：{title}\n简介：{synopsis}\n需求：{requirement}"},
    ]


def _chapter_messages(requirement: str, book: tuple[str, str], outline: list[dict], chapter: int, previous: str) -> list[dict]:
    title, synopsis = book
    plan = outline[chapter - 1]
    lines = [f"{item['chapter']}. {item['title']}：{item['summary']}" for item in outline]
    earlier = f"\n上一章结尾：{previous}" if previous else ""
    return [
        {
            "role": "system",
            "content": "你在写中文小说的一章。只返回 JSON，对象含 title 和 body。body 是这一章的正文，不要重复标题，不要写大纲说明。篇幅按这一章的情节自然展开。",
        },
        {
            "role": "user",
            "content": (
                f"书名：{title}\n简介：{synopsis}\n需求：{requirement}\n大纲：\n"
                + "\n".join(lines)
                + f"\n现在写第 {chapter} 章。标题可以用「{plan['title']}」。这一章要写：{plan['summary']}{earlier}"
            ),
        },
    ]


def _revise_messages(requirement: str, book: tuple[str, str], outline: list[dict], chapter: int, title: str, body: str, instruction: str) -> list[dict]:
    plan = outline[chapter - 1] if 0 < chapter <= len(outline) else {"title": title, "summary": ""}
    return [
        {
            "role": "system",
            "content": "你在按读者的要求修改中文小说的一章。只返回 JSON，对象含 title 和 body。保留没有被要求改动的情节。body 是改后的正文。",
        },
        {
            "role": "user",
            "content": (
                f"书名：{book[0]}\n需求：{requirement}\n第 {chapter} 章原标题：{title}\n这一章原计划：{plan.get('summary') or ''}\n"
                f"修改要求：{instruction}\n当前正文：\n{body}"
            ),
        },
    ]


def _object(text: str) -> dict:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise GuideError("模型没有返回可读取的结果")
    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise GuideError("模型没有返回可读取的结果") from exc
    if not isinstance(payload, dict):
        raise GuideError("模型没有返回可读取的结果")
    return payload


def _state(root: Path) -> dict:
    path = root / _GUIDE
    if not path.is_file():
        raise GuideError("这本不在确认流程里")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GuideError("确认进度读不出来") from exc
    if not isinstance(payload, dict) or str(payload.get("stage") or "") not in {"title", "outline", "chapter", "done"}:
        raise GuideError("这本不在确认流程里")
    return payload


def _write_state(root: Path, *, stage: str, requirement: str, chapter: int) -> None:
    current = {}
    path = root / _GUIDE
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            current = loaded
    revision = int(current.get("revision") or 0) + 1
    payload = {"stage": stage, "requirement": requirement, "chapter": chapter, "revision": revision}
    from ainovel.store.io import IO

    IO(root).write_json(_GUIDE, payload)


def _bump(root: Path) -> None:
    state = _state(root)
    _write_state(root, stage=str(state["stage"]), requirement=str(state.get("requirement") or ""), chapter=int(state.get("chapter") or 0))


def _save_book(root: Path, title: str, synopsis: str) -> None:
    book = Book.open(root, writable=True)
    book.info.save(BookMetadata(title=title[:200], synopsis=synopsis))


def _save_outline(root: Path, outline: list[dict]) -> None:
    from ainovel.store.io import IO

    IO(root).write_json("outline.json", outline)


def _save_progress(root: Path, *, phase: Phase, total: int, completed: list[int]) -> None:
    book = Book.open(root, writable=True)
    current = book.progress.load() or Progress()
    current.phase = phase
    current.total_chapters = total
    current.completed_chapters = completed
    current.current_chapter = completed[-1] if completed else 0
    counts = dict(current.chapter_word_counts)
    for number in completed:
        _, body = _chapter_text(root, number)
        if body:
            counts[number] = len(body)
    current.chapter_word_counts = counts
    current.total_word_count = sum(counts.get(number, 0) for number in completed)
    if phase == Phase.WRITING and current.flow is None:
        current.flow = FlowState.WRITING
    book.progress.save(current)


def _write_chapter(root: Path, chapter: int, title: str, body: str) -> None:
    text = body.strip()
    if not text:
        raise GuideError("正文是空的")
    name = title.strip() or f"第 {chapter} 章"
    relative = f"chapters/{chapter_number(chapter)}.md"
    from ainovel.store.io import IO

    IO(root).write_text(relative, f"# {name}\n\n{text}\n")
    outline = _outline(root)
    if outline:
        _save_progress(root, phase=Phase.WRITING, total=len(outline), completed=list(range(1, chapter + 1)))


def _outline(root: Path) -> list[dict]:
    path = root / "outline.json"
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    outline = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        outline.append(
            {
                "chapter": len(outline) + 1,
                "title": title,
                "summary": str(item.get("summary") or "").strip() or title,
            }
        )
    return outline


def _book_fields(root: Path) -> tuple[str, str]:
    path = root / "meta" / "book.json"
    if not path.is_file():
        return "", ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "", ""
    if not isinstance(payload, dict):
        return "", ""
    return str(payload.get("title") or "").strip(), str(payload.get("synopsis") or "").strip()


def _chapter_text(root: Path, chapter: int) -> tuple[str, str]:
    if chapter < 1:
        return "", ""
    path = root / "chapters" / f"{chapter_number(chapter)}.md"
    if not path.is_file():
        return "", ""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return "", ""
    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith("#"):
        title = lines[0].lstrip("#").strip()
        body = "\n".join(lines[1:]).strip()
        return title, body
    return "", text
