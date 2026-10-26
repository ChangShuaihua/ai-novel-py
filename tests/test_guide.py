"""题目、大纲和章节都要人确认后才进入下一步。"""

import json
from pathlib import Path

from ainovel.entry.guide import begin, confirm, load_guide, parse_outline, revise


def _script(replies: list[str]):
    pending = list(replies)

    def ask(_messages):
        if not pending:
            raise AssertionError("不该再问模型")
        return pending.pop(0)

    return ask


def test_reader_confirms_title_outline_and_chapter(tmp_path: Path):
    ask = _script(
        [
            json.dumps({"title": "雨夜", "synopsis": "一个人在雨夜里醒来，发现门外站着自己。"}, ensure_ascii=False),
            json.dumps(
                {
                    "chapters": [
                        {"title": "醒来", "summary": "他在雨里醒来。"},
                        {"title": "出门", "summary": "他推开门。"},
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps({"title": "醒来", "body": "雨打在窗上。"}, ensure_ascii=False),
            json.dumps({"title": "醒来", "body": "清晨的光打在窗上。"}, ensure_ascii=False),
            json.dumps({"title": "出门", "body": "门开了。"}, ensure_ascii=False),
        ]
    )
    begin(tmp_path, "雨夜醒来", ask)
    view = load_guide(tmp_path)
    assert view["stage"] == "title"
    assert view["title"] == "雨夜"

    confirm(tmp_path, {"title": "雨夜行", "synopsis": view["synopsis"]}, ask)
    view = load_guide(tmp_path)
    assert view["stage"] == "outline"
    assert view["title"] == "雨夜行"
    assert "醒来" in view["outline_text"]

    confirm(tmp_path, {"outline_text": "1. 醒来：他在雨里醒来。\n2. 出门：他推开门。"}, ask)
    view = load_guide(tmp_path)
    assert view["stage"] == "chapter"
    assert view["chapter"] == 1
    assert view["chapter_body"] == "雨打在窗上。"

    revise(tmp_path, {"text": "改成清晨", "chapter_body": "雨打在窗上。"}, ask)
    assert load_guide(tmp_path)["chapter_body"] == "清晨的光打在窗上。"

    confirm(tmp_path, {"chapter_title": "醒来", "chapter_body": "清晨的光打在窗上。"}, ask)
    view = load_guide(tmp_path)
    assert view["chapter"] == 2
    assert view["chapter_body"] == "门开了。"

    confirm(tmp_path, {"chapter_title": "出门", "chapter_body": "门开了。"}, ask)
    assert load_guide(tmp_path)["stage"] == "done"
    assert (tmp_path / "chapters" / "02.md").read_text(encoding="utf-8").startswith("# 出门")


def test_a_title_the_reader_already_wrote_is_kept(tmp_path: Path):
    def ask(_messages):
        raise AssertionError("不该再问模型")

    begin(tmp_path, "雨夜醒来", ask, title="雨夜", synopsis="一个人在雨里醒来。")
    view = load_guide(tmp_path)
    assert view["stage"] == "title"
    assert view["title"] == "雨夜"
    assert view["synopsis"] == "一个人在雨里醒来。"


def test_outline_lines_keep_the_chapter_order():
    outline = parse_outline("1. 醒来：雨\n2. 出门：门")
    assert [item["title"] for item in outline] == ["醒来", "出门"]
