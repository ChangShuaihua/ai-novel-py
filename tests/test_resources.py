from ainovel.resources import package_dir
from ainovel.voice import assets_root, load_bundle


def test_assets_and_static_come_from_the_package():
    root = assets_root()
    package = package_dir("assets").parent
    assert root == package_dir("assets")
    assert (package / "__init__.py").is_file()
    assert (root / "voice.md").is_file()
    assert (root / "prompts" / "writer.md").is_file()
    bundle = load_bundle(include_home=False)
    assert "{{VOICE}}" in bundle.prompts["writer.md"]
