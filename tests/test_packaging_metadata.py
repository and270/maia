from pathlib import Path
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_project_does_not_expose_legacy_console_scripts():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]

    assert {"maia", "maia-agent", "maia-acp"}.issubset(scripts)
    assert not any(name.startswith("coorporate") for name in scripts)
    assert not (REPO_ROOT / "coorporate").exists()


def test_installers_do_not_create_legacy_console_alias():
    setup_script = (REPO_ROOT / "setup-maia.sh").read_text(encoding="utf-8")
    install_script = (REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    formula = (REPO_ROOT / "packaging" / "homebrew" / "maia.rb").read_text(encoding="utf-8")

    for content in (setup_script, install_script, formula):
        assert "coorporate" not in content.lower()


def test_faster_whisper_is_not_a_base_dependency():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]

    assert not any(dep.startswith("faster-whisper") for dep in deps)

    voice_extra = data["project"]["optional-dependencies"]["voice"]
    assert any(dep.startswith("faster-whisper") for dep in voice_extra)


def test_manifest_includes_bundled_skills():
    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "graft skills" in manifest
    assert "graft optional-skills" in manifest
