"""Regression coverage for writable user-bin selection in install.sh."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"


def _content() -> str:
    return INSTALL_SH.read_text(encoding="utf-8")


def _function_body(content: str, name: str, next_name: str) -> str:
    start = content.index(f"{name}() {{")
    end = content.index(f"{next_name}() {{", start)
    return content[start:end]


def _bash_executable() -> str | None:
    candidates = []
    if os.name == "nt":
        candidates.extend(
            [
                Path("C:/Program Files/Git/bin/bash.exe"),
                Path("C:/Program Files/Git/usr/bin/bash.exe"),
            ]
        )
    candidates.extend(Path(path) for path in [shutil.which("bash")] if path)
    return str(next((path for path in candidates if path.is_file()), "")) or None


def _run_resolver_scenario(setup: str) -> list[str]:
    bash = _bash_executable()
    if bash is None:
        pytest.skip("bash is required to exercise install.sh resolver functions")

    content = _content()
    start = content.index("ensure_writable_dir() {")
    end = content.index("# System detection", start)
    resolver_functions = content[start:end]
    script = f"""
set -e
{resolver_functions}
{setup}
printf '%s\n' "$(get_command_link_dir)"
printf '%s\n' "$(get_uv_install_dir)"
printf '%s\n' "$(get_command_link_display_dir \"$(get_command_link_dir)\")"
"""
    result = subprocess.run(
        [bash, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.splitlines()


def _run_bash(script: str) -> subprocess.CompletedProcess[str]:
    bash = _bash_executable()
    if bash is None:
        pytest.skip("bash is required to exercise install.sh functions")
    try:
        return subprocess.run(
            [bash, "-s"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            input=script,
        )
    except subprocess.CalledProcessError as exc:
        numbered_script = "\n".join(
            f"{line_number:04d}: {line}"
            for line_number, line in enumerate(script.splitlines(), start=1)
        )
        raise AssertionError(f"{exc.stderr}\n{numbered_script}") from exc


def test_user_bin_prefers_local_and_falls_back_to_maia_home() -> None:
    content = _content()
    body = _function_body(content, "get_user_bin_dir", "get_uv_install_dir")

    assert 'preferred_dir="$HOME/.local/bin"' in body
    assert 'fallback_dir="$MAIA_HOME/bin"' in body
    assert 'ensure_writable_dir "$preferred_dir"' in body
    assert 'ensure_writable_dir "$fallback_dir"' in body
    assert body.index('ensure_writable_dir "$preferred_dir"') < body.index(
        'ensure_writable_dir "$fallback_dir"'
    )


def test_platform_specific_command_paths_remain_unchanged() -> None:
    content = _content()
    body = _function_body(
        content, "get_command_link_dir", "get_command_link_display_dir"
    )

    assert 'echo "$PREFIX/bin"' in body
    assert 'echo "/usr/local/bin"' in body
    assert "get_user_bin_dir" in body
    assert body.index('echo "$PREFIX/bin"') < body.index("get_user_bin_dir")
    assert body.index('echo "/usr/local/bin"') < body.index("get_user_bin_dir")


def test_uv_node_and_maia_launcher_share_the_writable_bin_policy() -> None:
    content = _content()
    install_uv = _function_body(content, "install_uv", "check_python")
    install_node = _function_body(content, "install_node", "install_system_packages")
    setup_path = _function_body(content, "setup_path", "configure_secure_runtime")

    assert 'UV_INSTALL_DIR="$uv_install_dir"' in install_uv
    assert 'elif [ -x "$MAIA_HOME/bin/uv" ]' in install_uv
    assert 'user_bin_dir="$(get_user_bin_dir)"' in install_node
    assert 'command_link_dir="$(get_command_link_dir)"' in setup_path
    assert 'PATH_EXPORT_DIR="\\$HOME/${command_link_dir#$HOME/}"' in setup_path
    assert 'PATH_LINE="export PATH=\\"$PATH_EXPORT_DIR:\\$PATH\\""' in setup_path
    assert 'mkdir -p "$HOME/.local/bin"' not in content


def test_installer_explains_automatic_fallback_instead_of_failing() -> None:
    content = _content()

    assert (
        'log_warn "~/.local/bin is not writable; using '
        '$command_link_display_dir automatically"'
    ) in content
    assert (
        'log_error "Could not create a writable directory for the maia command"'
        in content
    )
    assert 'log_info "Checked: $HOME/.local/bin and $MAIA_HOME/bin"' in content


def test_resolver_functions_choose_maia_fallback_in_bash() -> None:
    output = _run_resolver_scenario(
        """
is_termux() { return 1; }
HOME=/Users/client
MAIA_HOME="$HOME/.maia"
ROOT_FHS_LAYOUT=false
ensure_writable_dir() { [ "$1" = "$MAIA_HOME/bin" ]; }
"""
    )

    assert output == [
        "/Users/client/.maia/bin",
        "/Users/client/.maia/bin",
        "~/.maia/bin",
    ]


def test_resolver_functions_preserve_wsl_root_and_termux_paths_in_bash() -> None:
    preferred = _run_resolver_scenario(
        """
is_termux() { return 1; }
HOME=/home/client
MAIA_HOME="$HOME/.maia"
ROOT_FHS_LAYOUT=false
ensure_writable_dir() { [ "$1" = "$HOME/.local/bin" ]; }
"""
    )
    root = _run_resolver_scenario(
        """
is_termux() { return 1; }
HOME=/root
MAIA_HOME="$HOME/.maia"
ROOT_FHS_LAYOUT=true
ensure_writable_dir() { [ "$1" = "$HOME/.local/bin" ]; }
"""
    )
    termux = _run_resolver_scenario(
        """
is_termux() { return 0; }
HOME=/data/data/com.termux/files/home
MAIA_HOME="$HOME/.maia"
PREFIX=/data/data/com.termux/files/usr
ROOT_FHS_LAYOUT=false
ensure_writable_dir() { [ "$1" = "$HOME/.local/bin" ]; }
"""
    )

    assert preferred == [
        "/home/client/.local/bin",
        "/home/client/.local/bin",
        "~/.local/bin",
    ]
    assert root == ["/usr/local/bin", "/root/.local/bin", "/usr/local/bin"]
    assert termux == [
        "/data/data/com.termux/files/usr/bin",
        "/data/data/com.termux/files/home/.local/bin",
        "$PREFIX/bin",
    ]


def test_setup_path_writes_mac_zsh_fallback_launcher_and_path() -> None:
    content = _content()
    resolver_start = content.index("ensure_writable_dir() {")
    resolver_end = content.index("# System detection", resolver_start)
    resolver_functions = content[resolver_start:resolver_end]
    setup_path = _function_body(content, "setup_path", "configure_secure_runtime")

    _run_bash(
        f"""
set -e
{resolver_functions}
{setup_path}
is_termux() {{ return 1; }}
log_info() {{ :; }}
log_success() {{ :; }}
log_warn() {{ :; }}
log_error() {{ printf '%s\n' "$*" >&2; }}
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
HOME="$tmp_dir/home"
MAIA_HOME="$HOME/.maia"
INSTALL_DIR="$MAIA_HOME/maia"
USE_VENV=true
DISTRO=macos
ROOT_FHS_LAYOUT=false
SHELL=/bin/zsh
PATH=/usr/bin:/bin
mkdir -p "$INSTALL_DIR/venv/bin"
printf '#!/usr/bin/env bash\nprintf "maia-ok\\n"\n' > "$INSTALL_DIR/venv/bin/maia"
chmod +x "$INSTALL_DIR/venv/bin/maia"
touch "$HOME/.zshrc"
ensure_writable_dir() {{
    [ "$1" = "$HOME/.local/bin" ] && return 1
    mkdir -p "$1" 2>/dev/null && [ -w "$1" ]
}}
setup_path
test -x "$HOME/.maia/bin/maia"
test "$("$HOME/.maia/bin/maia")" = "maia-ok"
grep -Fq 'export PATH="$HOME/.maia/bin:$PATH"' "$HOME/.zshrc"
"""
    )
