"""导入工作区。切分确认之后才允许发布，中断不重做已确认的切分。"""

import hashlib
import json
from pathlib import Path


class ImportError(RuntimeError):
    """导入停在当前阶段。已确认的切分保留。"""


def normalize(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized and not normalized.endswith("\n"):
        normalized += "\n"
    return normalized


def ingest(root: Path, source_name: str, text: str, *, auto_confirm: bool = False) -> None:
    workspace = root / "meta" / "import"
    if workspace.exists():
        raise ImportError("导入工作区已存在，请继续未完成的导入")
    workspace.mkdir(parents=True)
    normalized = normalize(text)
    (workspace / "source.txt").write_text(normalized, encoding="utf-8")
    (workspace / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "source_name": source_name,
                "normalized_sha256": _digest(normalized),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (workspace / "intent.json").write_text(
        json.dumps({"version": 1, "auto_confirm": auto_confirm}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run(root: Path, completer, *, accept: bool = False) -> dict:
    """每次只做下一件由工件推导出的事。确认件还在，就不会重做切分。"""
    for _ in range(100):
        action = next_action(root)
        if action == "await_confirmation":
            if accept or _auto_confirm(root):
                accept_segmentation(root)
                continue
            return {"status": "await_confirmation", "chapters": [item["title"] for item in _segmentation(root)["payload"]["chapters"]]}
        if action == "done":
            return {"status": "done"}
        if action == "segment":
            _segment(root, completer)
            continue
        if action == "synthesize":
            _synthesize(root, completer)
            continue
        if action == "publish":
            _publish(root)
            return {"status": "paused"}
        if isinstance(action, tuple) and action[0] == "analyze":
            _analyze(root, completer, action[1])
            continue
        raise ImportError(f"未知导入动作 {action}")
    raise ImportError("导入步骤过多，已停下")


def accept_segmentation(root: Path, method: str = "user_confirmed") -> None:
    segmentation = _segmentation(root)
    _write_artifact(
        root / "meta" / "import" / "confirmation.json",
        segmentation["input_digest"],
        {"method": method},
    )


def next_action(root: Path) -> str | tuple:
    workspace = root / "meta" / "import"
    source = _read(workspace / "source.txt")
    if source is None:
        return "ingest"
    expected = _digest(source, _read(workspace / "guidance.txt") or "")
    segmentation = _load(workspace / "segmentation.json")
    if segmentation is None or segmentation.get("input_digest") != expected:
        return "segment"
    confirmation = _load(workspace / "confirmation.json")
    if confirmation is None or confirmation.get("input_digest") != segmentation["input_digest"]:
        return "await_confirmation"
    for chapter in segmentation["payload"]["chapters"]:
        path = workspace / "analyses" / f"{int(chapter['index']):06d}.json"
        chapter_digest = _digest(segmentation["input_digest"], str(chapter["index"]), chapter["text"])
        analysis = _load(path)
        if analysis is None or analysis.get("input_digest") != chapter_digest:
            return ("analyze", int(chapter["index"]))
    synthesis_digest = _digest(*(
        _load(workspace / "analyses" / f"{int(chapter['index']):06d}.json")["input_digest"]
        for chapter in segmentation["payload"]["chapters"]
    ))
    synthesis = _load(workspace / "synthesis.json")
    if synthesis is None or synthesis.get("input_digest") != synthesis_digest:
        return "synthesize"
    if not _published(root, segmentation["payload"]["chapters"]):
        return "publish"
    return "done"


def _segment(root: Path, completer) -> None:
    workspace = root / "meta" / "import"
    source = _read(workspace / "source.txt") or ""
    guidance = _read(workspace / "guidance.txt") or ""
    digest = _digest(source, guidance)
    completion = completer.complete(
        [
            {"role": "system", "content": "只返回 JSON：{\"chapters\":[{\"title\":\"标题\"}]}。标题必须是源文中的独立行。"},
            {"role": "user", "content": "切分\n" + source},
        ],
        [],
    )
    try:
        payload = _object(completion.content)
        chapters = _cover(source, payload.get("chapters") or [])
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        failure = workspace / "failures"
        failure.mkdir(parents=True, exist_ok=True)
        (failure / "last-response.txt").write_text(completion.content, encoding="utf-8")
        raise ImportError(f"切分没有通过覆盖校验：{exc}") from exc
    _write_artifact(workspace / "segmentation.json", digest, {"chapters": chapters})


def _analyze(root: Path, completer, index: int) -> None:
    workspace = root / "meta" / "import"
    segmentation = _segmentation(root)
    chapter = next(item for item in segmentation["payload"]["chapters"] if int(item["index"]) == index)
    digest = _digest(segmentation["input_digest"], str(index), chapter["text"])
    completion = completer.complete(
        [
            {"role": "system", "content": "只返回 JSON：{\"summary\":\"本章事实\"}"},
            {"role": "user", "content": f"分析第 {index} 章\n{chapter['text']}"},
        ],
        [],
    )
    payload = _object(completion.content)
    if not str(payload.get("summary") or "").strip():
        raise ImportError(f"第 {index} 章分析缺少 summary")
    _write_artifact(workspace / "analyses" / f"{index:06d}.json", digest, payload)


def _synthesize(root: Path, completer) -> None:
    workspace = root / "meta" / "import"
    segmentation = _segmentation(root)
    digests = []
    summaries = []
    for chapter in segmentation["payload"]["chapters"]:
        analysis = _load(workspace / "analyses" / f"{int(chapter['index']):06d}.json")
        digests.append(analysis["input_digest"])
        summaries.append(analysis["payload"]["summary"])
    completion = completer.complete(
        [
            {"role": "system", "content": "只返回 JSON：{\"title\":\"书名\",\"synopsis\":\"简介\",\"premise\":\"前提\"}"},
            {"role": "user", "content": "综合\n" + "\n".join(summaries)},
        ],
        [],
    )
    payload = _object(completion.content)
    _write_artifact(workspace / "synthesis.json", _digest(*digests), payload)


def _publish(root: Path) -> None:
    """发布是唯一写正式章节目录的步骤。已有相同正文的章节不重写。"""
    from ainovel.domain.progress import Progress
    from ainovel.domain.run_meta import AdvanceHold
    from ainovel.domain.transitions import FlowState, Phase
    from ainovel.store.book import Book
    from ainovel.store.paths import chapter_number

    segmentation = _segmentation(root)
    chapters = segmentation["payload"]["chapters"]
    for chapter in chapters:
        relative = root / "chapters" / f"{chapter_number(int(chapter['index']))}.md"
        relative.parent.mkdir(parents=True, exist_ok=True)
        if relative.is_file():
            if relative.read_text(encoding="utf-8") != chapter["text"]:
                raise ImportError(f"第 {chapter['index']} 章已经发布且正文不同，拒绝覆盖")
            continue
        relative.write_text(chapter["text"], encoding="utf-8")
    book = Book.open(root, writable=True)
    progress = book.progress.load() or Progress()
    numbers = [int(chapter["index"]) for chapter in chapters]
    for number in numbers:
        if number not in progress.completed_chapters:
            progress.completed_chapters.append(number)
    progress.phase = Phase.WRITING
    progress.flow = FlowState.WRITING
    progress.total_chapters = max(progress.total_chapters, len(numbers))
    progress.current_chapter = max(numbers)
    book.progress.save(progress)
    meta = book.run_meta.load() or book.run_meta.init(style="", provider="", model="")
    if not _auto_continue(root) and meta.advance_hold is None:
        meta.advance_hold = AdvanceHold(after="boundary", reason="导入完成，等待用户继续")
        book.run_meta.save(meta)


def _published(root: Path, chapters: list[dict]) -> bool:
    from ainovel.store.paths import chapter_number

    for chapter in chapters:
        path = root / "chapters" / f"{chapter_number(int(chapter['index']))}.md"
        if not path.is_file() or path.read_text(encoding="utf-8") != chapter["text"]:
            return False
    return True


def _cover(source: str, requested: list) -> list[dict]:
    if not requested:
        raise ValueError("没有章节标题")
    lines = source.splitlines(keepends=True)
    positions = []
    cursor = 0
    for item in requested:
        title = str(item.get("title") or "").strip()
        if not title:
            raise ValueError("章节标题为空")
        found = None
        for index in range(cursor, len(lines)):
            if lines[index].strip() == title:
                found = index
                break
        if found is None:
            raise ValueError(f"找不到标题 {title}")
        positions.append((title, found))
        cursor = found + 1
    spans = []
    for index, (title, start) in enumerate(positions):
        end = positions[index + 1][1] if index + 1 < len(positions) else len(lines)
        begin = 0 if index == 0 else start
        spans.append({"index": index + 1, "title": title, "text": "".join(lines[begin:end])})
    if "".join(item["text"] for item in spans) != source:
        raise ValueError("切分没有覆盖全文")
    return spans


def _object(content: str) -> dict:
    text = content.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise json.JSONDecodeError("没有 JSON 对象", text, 0)
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("响应必须是对象")
    return payload


def _segmentation(root: Path) -> dict:
    payload = _load(root / "meta" / "import" / "segmentation.json")
    if payload is None:
        raise ImportError("还没有切分")
    return payload


def _auto_confirm(root: Path) -> bool:
    intent = _load(root / "meta" / "import" / "intent.json") or {}
    return bool(intent.get("auto_confirm"))


def _auto_continue(root: Path) -> bool:
    intent = _load(root / "meta" / "import" / "intent.json") or {}
    return bool(intent.get("continue_after_import"))


def _write_artifact(path: Path, digest: str, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "input_digest": digest, "payload": payload}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load(path: Path) -> dict | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ImportError(f"{path.name} 不是对象")
    return payload


def _read(path: Path) -> str | None:
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _digest(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()
