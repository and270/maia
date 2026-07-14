"""Installer wiring for secure-runtime readiness and restricted mode."""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"


def _function_body(name: str) -> str:
    text = INSTALL_SH.read_text()
    match = re.search(
        rf"^{re.escape(name)}\(\)\s*\{{\s*\n(?P<body>.*?)^\}}",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None
    return match["body"]


def test_installer_checks_runtime_after_launcher_is_available() -> None:
    main = _function_body("main")
    assert main.index("setup_path") < main.index("configure_secure_runtime")
    assert main.index("configure_secure_runtime") < main.index("run_setup_wizard")


def test_installer_keeps_restricted_mode_non_fatal() -> None:
    body = _function_body("configure_secure_runtime")
    assert "secure-runtime status --quiet" in body
    assert "secure-runtime setup --yes" in body
    assert "Maia is installed and safe in Restricted mode" in body
    assert "Finish later with: maia secure-runtime setup" in body
