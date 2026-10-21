from pathlib import Path

from ainovel.voice import assets_root, build_writer_prompt, load_bundle


def test_placeholder_is_replaced_once_then_style_is_appended():
    text = build_writer_prompt("前 {{VOICE}} 中 {{VOICE}}", "文风正文", "风格正文")
    assert text == "前 文风正文 中 {{VOICE}}\n\n风格正文"
    assert build_writer_prompt("没有占位符", "文风", "") == "没有占位符"


def test_shipped_writer_prompt_uses_the_single_entry():
    bundle = load_bundle(include_home=False)
    protocol = bundle.prompts["writer.md"]
    assert "{{VOICE}}" in protocol
    built = build_writer_prompt(protocol, bundle.voice, bundle.styles["default"])
    assert "{{VOICE}}" not in built
    assert "写作标准" in built
    assert "通用写作风格" in built
    assert built.index("写作标准") < built.index("通用写作风格")


def test_voice_placeholder_token_lives_in_one_module():
    root = Path(__file__).parents[1] / "src"
    hits = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if "{{VOICE}}" in path.read_text(encoding="utf-8")
    ]
    assert hits == ["ainovel/voice.py"]
    definitions = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if "def build_writer_prompt" in path.read_text(encoding="utf-8")
    ]
    assert definitions == ["ainovel/voice.py"]


def test_voice_overrides_append_and_styles_replace(tmp_path: Path):
    home = tmp_path / "home"
    book = tmp_path / "book"
    (home).mkdir()
    (home / "voice.md").write_text("  全局文风  ", encoding="utf-8")
    (home / "anti-ai-tone.md").write_text("全局去腔", encoding="utf-8")
    (book / "style").mkdir(parents=True)
    (book / "style" / "voice.md").write_text("本书文风", encoding="utf-8")
    (book / "style" / "styles").mkdir()
    (book / "style" / "styles" / "fantasy.md").write_text("本书奇幻", encoding="utf-8")
    (book / "style" / "styles" / "Bad_Name.md").write_text("非法名字", encoding="utf-8")
    (book / "style" / "genres" / "fantasy").mkdir(parents=True)
    (book / "style" / "genres" / "fantasy" / "style-references.md").write_text("本书参照", encoding="utf-8")
    (book / "style" / "genres" / "custom-west").mkdir(parents=True)
    (book / "style" / "genres" / "custom-west" / "style-references.md").write_text("西部参照", encoding="utf-8")

    builtin_voice = (assets_root() / "voice.md").read_text(encoding="utf-8")
    plain = load_bundle(include_home=False)
    assert plain.voice == builtin_voice

    bundle = load_bundle("fantasy", book, home_style_dir=home, include_home=False)
    assert bundle.voice.index("全局文风") < bundle.voice.index("本书文风")
    assert "用户全局文风覆盖" in bundle.voice
    assert "本书文风覆盖" in bundle.voice
    assert bundle.styles["fantasy"] == "本书奇幻"
    assert "非法名字" not in bundle.styles.values()
    assert bundle.references["genres/fantasy/style-references.md"] == "本书参照"
    assert "全局去腔" in bundle.references["anti-ai-tone.md"]

    custom = load_bundle("custom-west", book, home_style_dir=home, include_home=False)
    assert custom.references["genres/custom-west/style-references.md"] == "西部参照"
    assert "genres/custom-west/style-references.md" not in plain.references
    assert plain.styles["fantasy"] != "本书奇幻"
