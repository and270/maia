"""Secure container runtime diagnostics and guided setup for Maia."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import Any

from tools.environments.docker import (
    RUNTIME_IMAGE_SETUP_STATUSES,
    configured_runtime_image,
    find_docker,
    secure_runtime_status,
)


def _print_list(title: str, items: list[str]) -> None:
    if not items:
        return
    print(title)
    for item in items:
        print(f"  - {item}")


def print_secure_runtime_status(status: dict[str, Any] | None = None) -> dict[str, Any]:
    """Print a concise operational status and return the underlying payload."""

    current = status or secure_runtime_status()
    ready = bool(current.get("ready"))
    mode = "Full automation" if ready else "Restricted mode"
    marker = "✓" if ready else "◇"
    runtime = current.get("runtime")
    runtime_text = f" · {str(runtime).title()}" if runtime else ""

    print(f"{marker} Secure runtime: {mode}{runtime_text}")
    print(f"  Host: {current.get('platform_label', 'Unknown platform')}")
    if current.get("image"):
        print(f"  Image: {current.get('image')}")
    print(f"  {current.get('message', '')}")
    print()
    print("Why this matters")
    print(f"  {current.get('why', '')}")
    print()
    _print_list("Available now", list(current.get("available_capabilities") or []))
    blocked = list(current.get("blocked_capabilities") or [])
    if blocked:
        print()
        _print_list("Blocked until the secure runtime is ready", blocked)

    if not ready:
        print()
        print("What to do")
        for index, step in enumerate(current.get("steps") or [], start=1):
            print(f"  {index}. {step.get('title', 'Next step')}")
            detail = str(step.get("detail") or "").strip()
            command = str(step.get("command") or "").strip()
            url = str(step.get("url") or "").strip()
            if detail:
                print(f"     {detail}")
            if command:
                print(f"     $ {command}")
            if url:
                print(f"     {url}")
        print()
        print(f"Detailed guide: {current.get('docs_url')}")

    return current


def _confirm(question: str, *, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    answer = input(f"{question} [Y/n] ").strip().casefold()
    return answer in {"", "y", "yes"}


def _run(command: list[str]) -> bool:
    print(f"→ {' '.join(command)}")
    try:
        return subprocess.run(command, check=False).returncode == 0
    except (FileNotFoundError, OSError) as exc:
        print(f"  Could not run the command: {exc}")
        return False


def _image_setup(status: dict[str, Any], *, assume_yes: bool) -> bool:
    """Download the configured sandbox image before claiming full readiness."""

    runtime_executable = find_docker()
    if not runtime_executable:
        print("No supported container runtime is available to provision the image.")
        return False

    image = str(status.get("image") or configured_runtime_image()).strip()
    if not image:
        print("No sandbox image is configured under terminal.docker_image.")
        return False
    if not _confirm(
        f"Download and validate Maia's sandbox image {image}?",
        assume_yes=assume_yes,
    ):
        print("Continuing in Restricted mode. You can run this setup again later.")
        return False

    print()
    print(f"Provisioning Maia sandbox image: {image}")
    if _run([runtime_executable, "pull", image]):
        return True
    print()
    print(
        "The sandbox image could not be downloaded. Maia remains in Restricted "
        "mode; review the Docker error above, then rerun this setup."
    )
    return False


def _linux_setup(status: dict[str, Any], *, assume_yes: bool) -> bool:
    distro = str(status.get("distro") or "").casefold()
    install_commands: list[list[str]] = []
    if distro in {"ubuntu", "debian", "linuxmint", "raspbian"}:
        install_commands = [
            ["apt-get", "update"],
            ["apt-get", "-y", "install", "podman"],
        ]
    elif distro in {"fedora", "centos", "rhel", "rocky", "almalinux"}:
        install_commands = [["dnf", "-y", "install", "podman"]]
    elif distro in {"arch", "manjaro"}:
        install_commands = [["pacman", "-S", "--noconfirm", "podman"]]
    elif distro in {"opensuse", "opensuse-leap", "opensuse-tumbleweed", "sles"}:
        install_commands = [["zypper", "--non-interactive", "install", "podman"]]
    elif distro == "alpine":
        install_commands = [["apk", "add", "podman"]]

    if not install_commands:
        print("Automatic setup is not available for this Linux distribution.")
        print("Use the package-manager command shown above, then run:")
        print("  maia secure-runtime status")
        return False
    if not _confirm("Install rootless Podman for full governed automation?", assume_yes=assume_yes):
        print("Continuing in Restricted mode. You can run this setup again later.")
        return False

    prefix: list[str] = []
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        sudo = shutil.which("sudo")
        if not sudo:
            print("sudo is required to install Podman with the system package manager.")
            return False
        prefix = [sudo]

    for command in install_commands:
        if not _run(prefix + command):
            print("Podman installation did not complete. Maia remains in Restricted mode.")
            return False
    return True


def _macos_podman_setup(status: dict[str, Any], *, assume_yes: bool) -> bool:
    if status.get("runtime") != "podman":
        print("Install Podman with the official macOS installer, then run this command again.")
        print("  https://podman.io/docs/installation")
        print("Docker Desktop is also supported:")
        print("  https://docs.docker.com/desktop/setup/install/mac-install/")
        return False
    if not _confirm("Start the Podman Linux machine now?", assume_yes=assume_yes):
        print("Continuing in Restricted mode. You can run this setup again later.")
        return False

    podman = shutil.which("podman") or "podman"
    if _run([podman, "machine", "start"]):
        return True
    print("No startable Podman machine was found; creating one.")
    return _run([podman, "machine", "init"]) and _run([podman, "machine", "start"])


def setup_secure_runtime(*, assume_yes: bool = False) -> bool:
    """Perform safe setup where possible, otherwise print exact manual steps."""

    current = print_secure_runtime_status()
    if current.get("ready"):
        return True

    image_statuses = RUNTIME_IMAGE_SETUP_STATUSES
    provisioning_image = current.get("status") in image_statuses
    platform_key = current.get("platform")
    changed = False
    if provisioning_image:
        changed = _image_setup(current, assume_yes=assume_yes)
    elif platform_key == "linux" and not current.get("runtime"):
        changed = _linux_setup(current, assume_yes=assume_yes)
    elif platform_key == "macos" and current.get("runtime") == "podman":
        changed = _macos_podman_setup(current, assume_yes=assume_yes)
    elif platform_key == "windows_wsl":
        print()
        print("Docker Desktop and WSL Integration are managed from Windows.")
        print("Complete the numbered steps above, then run this command again.")
    elif current.get("runtime"):
        print()
        print("The runtime is installed but not ready. Complete the repair steps above.")

    if not changed:
        return False

    print()
    print("Rechecking secure runtime...")
    refreshed = print_secure_runtime_status()
    if refreshed.get("ready"):
        return True
    if not provisioning_image and refreshed.get("status") in image_statuses:
        if not _image_setup(refreshed, assume_yes=assume_yes):
            return False
        print()
        print("Rechecking secure runtime...")
        refreshed = print_secure_runtime_status()
    return bool(refreshed.get("ready"))


def print_update_secure_runtime_summary() -> None:
    """Non-blocking post-update capability summary."""

    try:
        current = secure_runtime_status()
    except Exception as exc:  # pragma: no cover - defensive update path
        print(f"◇ Secure runtime: status check failed ({exc})")
        print("  Run `maia secure-runtime status` after the update.")
        return

    print()
    if current.get("ready"):
        runtime = str(current.get("runtime") or "container runtime").title()
        print(f"✓ Secure runtime: Full automation ready through {runtime}.")
        return
    print("◇ Secure runtime: Restricted mode")
    print(f"  {current.get('message')}")
    print("  Maia remains usable, but governed terminal/code automation is blocked.")
    print("  Run `maia secure-runtime setup` for guided operating-system steps.")


def cmd_secure_runtime(args: Any) -> None:
    action = getattr(args, "secure_runtime_action", None) or "status"
    if action == "setup":
        if not setup_secure_runtime(assume_yes=bool(getattr(args, "yes", False))):
            raise SystemExit(1)
        return

    current = secure_runtime_status()
    if getattr(args, "json", False):
        print(json.dumps(current, indent=2))
    elif not getattr(args, "quiet", False):
        print_secure_runtime_status(current)
    if getattr(args, "quiet", False) and not current.get("ready"):
        raise SystemExit(1)


__all__ = [
    "cmd_secure_runtime",
    "print_secure_runtime_status",
    "print_update_secure_runtime_summary",
    "setup_secure_runtime",
]
