"""全书文风统计。代码只计数，好不好留给模型。"""

import re
from pathlib import Path

from ainovel.store.book import Book
from ainovel.store.paths import chapter_number

_MIN_CHAPTERS = 5
_PHRASE_WINDOW = 20
_PATTERNS = (
    ("明喻『像一/仿佛/如同/宛如』", re.compile("像一|仿佛|如同|宛如")),
    ("沉默节拍『沉默了/没有说话』", re.compile("沉默了|没有说话")),
    ("思维标记『心想/意识到/感到/觉得』", re.compile("心想|意识到|感到|觉得")),
)
_SENTENCE = re.compile(r"[。！？\n]+")


class StyleIndex:
    """同一进程里和提交共享。进程重启后按已完成章重建。"""

    def __init__(self) -> None:
        self.texts: dict[int, str] = {}
        self.loaded = False

    def upsert(self, book: Book, chapter: int, text: str) -> None:
        self.sync(book)
        self.texts[chapter] = text

    def sync(self, book: Book) -> dict | None:
        progress = book.progress.load()
        completed = list(progress.completed_chapters) if progress is not None else []
        wanted = set(completed)
        if not self.loaded:
            self.texts = {chapter: _read_chapter(book.root, chapter) for chapter in completed}
            self.loaded = True
        else:
            for chapter in completed:
                if chapter not in self.texts:
                    self.texts[chapter] = _read_chapter(book.root, chapter)
            for chapter in list(self.texts):
                if chapter not in wanted:
                    del self.texts[chapter]
        ordered = [self.texts.get(chapter, "") for chapter in completed]
        return compute(ordered, _stopwords(book))


_INDEXES: dict[str, StyleIndex] = {}


def index_for(book: Book) -> StyleIndex:
    key = str(book.root.resolve())
    index = _INDEXES.get(key)
    if index is None:
        index = StyleIndex()
        _INDEXES[key] = index
    return index


def compute(chapters: list[str], stopwords: list[str] | None = None) -> dict | None:
    if len(chapters) < _MIN_CHAPTERS:
        return None
    joined = "\n".join(chapters)
    patterns = []
    for name, pattern in _PATTERNS:
        total = len(pattern.findall(joined))
        if total:
            patterns.append({"name": name, "total": total, "per_chapter": round(total / len(chapters), 1)})
    return {
        "chapters": len(chapters),
        "patterns": patterns,
        "top_phrases": _phrases(chapters[-_PHRASE_WINDOW:], stopwords or []),
        "repeated_sentences": _repeated(chapters),
        "ending": _endings(chapters),
    }


def _read_chapter(root: Path, chapter: int) -> str:
    path = root / "chapters" / f"{chapter_number(chapter)}.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _stopwords(book: Book) -> list[str]:
    from ainovel.tools.files import read_json

    raw = read_json(book.root, "characters.json")
    if not isinstance(raw, list):
        return []
    return [str(item.get("name") or "") for item in raw if isinstance(item, dict) and item.get("name")]


def _phrases(chapters: list[str], stopwords: list[str]) -> list[dict]:
    counts: dict[str, int] = {}
    for text in chapters:
        seen: set[str] = set()
        compact = re.sub(r"\s+", "", text)
        for index in range(0, max(0, len(compact) - 3)):
            phrase = compact[index : index + 4]
            if not re.fullmatch(r"[\u4e00-\u9fff]{4}", phrase):
                continue
            if any(word and word in phrase for word in stopwords):
                continue
            if phrase in seen:
                continue
            seen.add(phrase)
            counts[phrase] = counts.get(phrase, 0) + 1
    ranked = sorted(((text, count) for text, count in counts.items() if count >= 3), key=lambda item: (-item[1], item[0]))
    return [{"text": text, "count": count} for text, count in ranked[:5]]


def _repeated(chapters: list[str]) -> list[dict]:
    hits: dict[str, set[int]] = {}
    counts: dict[str, int] = {}
    for index, text in enumerate(chapters, start=1):
        for sentence in _SENTENCE.split(text):
            sentence = sentence.strip()
            if len(sentence) < 8:
                continue
            hits.setdefault(sentence, set()).add(index)
            counts[sentence] = counts.get(sentence, 0) + 1
    rows = [
        {"text": text, "chapters": len(chapters_hit), "count": counts[text]}
        for text, chapters_hit in hits.items()
        if len(chapters_hit) >= 2
    ]
    rows.sort(key=lambda item: (-item["chapters"], -item["count"], item["text"]))
    return rows[:5]


def _endings(chapters: list[str]) -> dict:
    lengths = []
    short = 0
    for text in chapters:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        last = lines[-1] if lines else ""
        lengths.append(len(last))
        if len(last) <= 30:
            short += 1
    lengths.sort()
    median = lengths[len(lengths) // 2] if lengths else 0
    return {"short_ratio": round(short / len(chapters), 2) if chapters else 0, "median_runes": median}
