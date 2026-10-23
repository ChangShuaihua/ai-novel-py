import json
from pathlib import Path

from ainovel.entry.desk import Desk
from ainovel.listing import build_listing


def test_listing_fits_the_create_work_form(tmp_path: Path):
    root = tmp_path / "book"
    (root / "meta").mkdir(parents=True)
    (root / "meta" / "book.json").write_text(
        json.dumps(
            {
                "title": "这是一个超过十五个字的很长书名还要再长一点",
                "synopsis": "守墓人在棺下翻出账簿，从此境界能赊，丹药能赊，连命都能先借后还。追债人敲响门的那天，账簿最后一页已经写好了他的死期。",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / "characters.json").write_text(
        json.dumps(
            [
                {"name": "沈烬长生客人", "role": "主角", "tier": "core"},
                {"name": "苏砚", "role": "配角", "tier": "important"},
                {"name": "裴照", "role": "反派", "tier": "core"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / "premise.md").write_text("目标读者是仙侠修真连载读者。\n", encoding="utf-8")
    card = build_listing(root)
    assert card["title"] == "这是一个超过十五个字的很长书名"
    assert len(card["title"]) == 15
    assert card["audience"] == "男频"
    assert card["reading_tag"] == "仙侠"
    assert card["content_tag"] == "古典仙侠"
    assert card["protagonists"] == ["沈烬长生客", "裴照"]
    assert 50 <= card["synopsis_count"] <= 500
    assert "血腥" not in card["synopsis"]
    assert card["cover_prompt"].startswith("竖版小说封面")
    assert "沈烬长生客人" in card["cover_prompt"]
    assert card["title"] in card["cover_prompt"]
    assert "账簿" in card["cover_prompt"]
    assert "血腥" not in card["cover_prompt"]


def test_short_synopsis_borrows_the_premise(tmp_path: Path):
    root = tmp_path / "book"
    (root / "meta").mkdir(parents=True)
    (root / "meta" / "book.json").write_text(
        json.dumps({"title": "推门", "synopsis": "太短。"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "characters.json").write_text(
        json.dumps([{"name": "林舟", "role": "主角"}], ensure_ascii=False),
        encoding="utf-8",
    )
    premise = "林舟推开一扇不会再关上的门，门外是一座把记忆当成货币的城，他每走一步都要交出一段不肯忘的事，直到自己的名字也开始模糊。"
    (root / "premise.md").write_text(f"# 前提\n\n{premise}\n", encoding="utf-8")
    card = build_listing(root)
    assert card["protagonists"] == ["林舟"]
    assert card["synopsis_count"] >= 50
    assert "林舟" in card["synopsis"]
    assert card["note"] == ""


def test_listing_intent_does_not_need_a_model(tmp_path: Path):
    root = tmp_path / "book"
    (root / "meta").mkdir(parents=True)
    (root / "meta" / "book.json").write_text(
        json.dumps({"title": "赊命长生", "synopsis": "守墓人沈砚翻出账簿，从此命可以先借后还，直到追债人按页上的死期上门。"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "characters.json").write_text(
        json.dumps([{"name": "沈烬", "role": "主角", "tier": "core"}], ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "premise.md").write_text("女主言情向的都市故事。\n", encoding="utf-8")
    desk = Desk(library_path=tmp_path / "library.json", config_path=tmp_path / "missing.json", books_root=tmp_path / "new")
    snap = desk.intent({"action": "listing", "directory": str(root)})
    assert snap["error"] == ""
    assert snap["config_ready"] is False
    assert snap["listing"]["audience"] == "女频"
    assert snap["listing"]["reading_tag"] == "都市"
    assert snap["listing"]["note"]
    assert not (root / "meta" / "progress.json").exists()
