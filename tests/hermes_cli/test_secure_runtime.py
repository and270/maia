from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hermes_cli import secure_runtime


def _restricted_status(**overrides):
    status = {
        "ready": False,
        "mode": "restricted",
        "status": "not_found",
        "platform": "linux",
        "platform_label": "Linux",
        "distro": "ubuntu",
        "runtime": None,
        "message": "No supported secure runtime is available to Maia.",
        "remediation": "Install Podman.",
        "why": "Commands need an isolated boundary.",
        "available_capabilities": ["Chat", "Safe files"],
        "blocked_capabilities": ["Terminal", "Code"],
        "steps": [
            {
                "title": "Install Podman",
                "detail": "Use the package manager.",
                "command": "sudo apt-get -y install podman",
            }
        ],
        "can_auto_setup": True,
        "setup_command": "maia secure-runtime setup",
        "verify_command": "maia secure-runtime status",
        "docs_url": "https://ampliia.com/en/maia/docs/getting-started/secure-runtime/",
    }
    status.update(overrides)
    return status


def test_status_explains_restricted_mode_and_consequences(capsys):
    secure_runtime.print_secure_runtime_status(_restricted_status())

    output = capsys.readouterr().out
    assert "Restricted mode" in output
    assert "Why this matters" in output
    assert "Available now" in output
    assert "Blocked until the secure runtime is ready" in output
    assert "sudo apt-get -y install podman" in output


def test_quiet_status_exits_nonzero_when_restricted():
    with patch.object(secure_runtime, "secure_runtime_status", return_value=_restricted_status()):
        with pytest.raises(SystemExit) as exc:
            secure_runtime.cmd_secure_runtime(
                SimpleNamespace(secure_runtime_action="status", quiet=True, json=False)
            )

    assert exc.value.code == 1


def test_linux_setup_installs_podman_with_supported_package_manager(monkeypatch):
    calls = []
    monkeypatch.setattr(secure_runtime.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        secure_runtime.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command)
        or SimpleNamespace(returncode=0),
    )

    assert secure_runtime._linux_setup(_restricted_status(), assume_yes=True) is True
    assert calls == [
        ["apt-get", "update"],
        ["apt-get", "-y", "install", "podman"],
    ]


def test_setup_pulls_and_validates_missing_sandbox_image(monkeypatch):
    missing = _restricted_status(
        status="image_missing",
        runtime="docker",
        image="example/maia-sandbox:test",
        can_auto_setup=True,
    )
    ready = _restricted_status(
        ready=True,
        mode="full",
        status="ready",
        runtime="docker",
        image="example/maia-sandbox:test",
        blocked_capabilities=[],
        steps=[],
    )
    statuses = iter([missing, ready])
    commands = []

    monkeypatch.setattr(secure_runtime, "secure_runtime_status", lambda: next(statuses))
    monkeypatch.setattr(secure_runtime, "find_docker", lambda: "/usr/bin/docker")
    monkeypatch.setattr(
        secure_runtime,
        "_run",
        lambda command: commands.append(command) or True,
    )

    assert secure_runtime.setup_secure_runtime(assume_yes=True) is True
    assert commands == [
        ["/usr/bin/docker", "pull", "example/maia-sandbox:test"]
    ]


def test_setup_stays_restricted_when_image_pull_fails(monkeypatch):
    missing = _restricted_status(
        status="image_missing",
        runtime="docker",
        image="example/maia-sandbox:test",
        can_auto_setup=True,
    )

    monkeypatch.setattr(secure_runtime, "secure_runtime_status", lambda: missing)
    monkeypatch.setattr(secure_runtime, "find_docker", lambda: "/usr/bin/docker")
    monkeypatch.setattr(secure_runtime, "_run", lambda command: False)

    assert secure_runtime.setup_secure_runtime(assume_yes=True) is False


def test_update_summary_does_not_treat_restricted_mode_as_failed_update(capsys):
    with patch.object(secure_runtime, "secure_runtime_status", return_value=_restricted_status()):
        secure_runtime.print_update_secure_runtime_summary()

    output = capsys.readouterr().out
    assert "Restricted mode" in output
    assert "Maia remains usable" in output
    assert "maia secure-runtime setup" in output
