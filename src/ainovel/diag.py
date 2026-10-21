"""只读诊断。可以指出问题，不能改文件、续跑或改流程。"""

from pathlib import Path

from ainovel.rules import check_text, load_snapshot
from ainovel.store.book import Book
from ainovel.store.paths import chapter_number


def diagnose(root: Path | str) -> dict:
    book = Book.open(root, writable=False)
    progress = book.progress.load()
    completed = list(progress.completed_chapters) if progress is not None else []
    snapshot = load_snapshot(book.root)
    findings = []
    for chapter in completed:
        path = book.root / "chapters" / f"{chapter_number(chapter)}.md"
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            findings.append({"rule": "MissingChapter", "severity": "critical", "chapter": chapter, "title": "进度里的章节没有正文"})
            continue
        for violation in check_text(path.read_text(encoding="utf-8"), snapshot):
            findings.append(
                {
                    "rule": violation["rule"],
                    "severity": violation["severity"],
                    "chapter": chapter,
                    "title": violation["target"],
                }
            )
    skeleton = [
        {
            "seq": item.seq,
            "step": item.step,
            "scope": item.scope.kind,
            "chapter": item.scope.chapter,
        }
        for item in book.checkpoints.all()
    ]
    return {
        "writable": book.writable,
        "findings": findings,
        "skeleton": skeleton,
        "stats": {"completed_chapters": len(completed), "phase": progress.phase.value if progress is not None else ""},
    }


def render_diagnosis(report: dict) -> str:
    lines = [
        f"只读诊断：writable={report['writable']}",
        f"阶段：{report['stats']['phase']}",
        f"已完成章：{report['stats']['completed_chapters']}",
        f"检查点：{len(report['skeleton'])}",
    ]
    if not report["findings"]:
        lines.append("没有发现")
    for finding in report["findings"]:
        lines.append(f"- [{finding['severity']}] {finding['rule']} 第{finding.get('chapter', '')}章 {finding['title']}")
    return "\n".join(lines)
