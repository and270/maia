"""Docker execution environment for sandboxed command execution.

Security hardened (cap-drop ALL, no-new-privileges, PID limits),
configurable resource limits (CPU, memory, disk), and optional filesystem
persistence via bind mounts.
"""

import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import uuid
from typing import Optional

from tools.environments.base import BaseEnvironment, _popen_bash
from tools.environments.local import _HERMES_PROVIDER_ENV_BLOCKLIST

logger = logging.getLogger(__name__)


DEFAULT_DOCKER_IMAGE = "nikolaik/python-nodejs:python3.11-nodejs20"
RUNTIME_IMAGE_SETUP_STATUSES = frozenset(
    {"image_missing", "image_unusable", "image_check_failed"}
)


# Common Docker Desktop install paths checked when 'docker' is not in PATH.
# macOS Intel: /usr/local/bin, macOS Apple Silicon (Homebrew): /opt/homebrew/bin,
# Docker Desktop app bundle: /Applications/Docker.app/Contents/Resources/bin
_DOCKER_SEARCH_PATHS = [
    "/usr/local/bin/docker",
    "/opt/homebrew/bin/docker",
    "/Applications/Docker.app/Contents/Resources/bin/docker",
]

_docker_executable: Optional[str] = None  # resolved once, cached
_ENV_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _normalize_forward_env_names(forward_env: list[str] | None) -> list[str]:
    """Return a deduplicated list of valid environment variable names."""
    normalized: list[str] = []
    seen: set[str] = set()

    for item in forward_env or []:
        if not isinstance(item, str):
            logger.warning("Ignoring non-string docker_forward_env entry: %r", item)
            continue

        key = item.strip()
        if not key:
            continue
        if not _ENV_VAR_NAME_RE.match(key):
            logger.warning("Ignoring invalid docker_forward_env entry: %r", item)
            continue
        if key in seen:
            continue

        seen.add(key)
        normalized.append(key)

    return normalized


def _normalize_env_dict(env: dict | None) -> dict[str, str]:
    """Validate and normalize a docker_env dict to {str: str}.

    Filters out entries with invalid variable names or non-string values.
    """
    if not env:
        return {}
    if not isinstance(env, dict):
        logger.warning("docker_env is not a dict: %r", env)
        return {}

    normalized: dict[str, str] = {}
    for key, value in env.items():
        if not isinstance(key, str) or not _ENV_VAR_NAME_RE.match(key.strip()):
            logger.warning("Ignoring invalid docker_env key: %r", key)
            continue
        key = key.strip()
        if not isinstance(value, str):
            # Coerce simple scalar types (int, bool, float) to string;
            # reject complex types.
            if isinstance(value, (int, float, bool)):
                value = str(value)
            else:
                logger.warning("Ignoring non-string docker_env value for %r: %r", key, value)
                continue
        normalized[key] = value

    return normalized


def _load_hermes_env_vars() -> dict[str, str]:
    """Load ~/.hermes/.env values without failing Docker command execution."""
    try:
        from hermes_cli.config import load_env

        return load_env() or {}
    except Exception:
        return {}


def find_docker() -> Optional[str]:
    """Locate the docker (or podman) CLI binary.

    Resolution order:
    1. ``HERMES_DOCKER_BINARY`` env var — explicit override (e.g. ``/usr/bin/podman``)
    2. ``docker`` on PATH via ``shutil.which``
    3. ``podman`` on PATH via ``shutil.which``
    4. Well-known macOS Docker Desktop install locations

    Returns the absolute path, or ``None`` if neither runtime can be found.
    """
    global _docker_executable
    if _docker_executable is not None:
        return _docker_executable

    # 1. Explicit override via env var (e.g. for Podman on immutable distros)
    override = os.getenv("HERMES_DOCKER_BINARY")
    if override and os.path.isfile(override) and os.access(override, os.X_OK):
        _docker_executable = override
        logger.info("Using HERMES_DOCKER_BINARY override: %s", override)
        return override

    # 2. docker on PATH
    found = shutil.which("docker")
    if found:
        _docker_executable = found
        return found

    # 3. podman on PATH (drop-in compatible for our use case)
    found = shutil.which("podman")
    if found:
        _docker_executable = found
        logger.info("Using podman as container runtime: %s", found)
        return found

    # 4. Well-known macOS Docker Desktop locations
    for path in _DOCKER_SEARCH_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            _docker_executable = path
            logger.info("Found docker at non-PATH location: %s", path)
            return path

    return None


def _docker_result_text(result: subprocess.CompletedProcess) -> str:
    return "\n".join(
        part.strip()
        for part in (getattr(result, "stdout", ""), getattr(result, "stderr", ""))
        if str(part or "").strip()
    )


def configured_runtime_image() -> str:
    """Return the sandbox image Maia will use for governed Docker sessions.

    ``config.yaml`` is authoritative when it explicitly contains
    ``terminal.docker_image``.  The environment variable remains supported for
    legacy and service deployments that do not persist that setting in YAML.
    Keeping this lookup here makes the readiness check and terminal runtime use
    the same configured image without importing ``terminal_tool`` (which would
    create a circular dependency).
    """

    try:
        from hermes_cli.config import read_raw_config

        raw = read_raw_config() or {}
        terminal = raw.get("terminal") if isinstance(raw, dict) else None
        configured = terminal.get("docker_image") if isinstance(terminal, dict) else None
        if isinstance(configured, str) and configured.strip():
            return os.path.expandvars(configured.strip())
    except Exception:
        logger.debug("Could not read terminal.docker_image for runtime check", exc_info=True)

    environment_image = os.getenv("TERMINAL_DOCKER_IMAGE", "").strip()
    return environment_image or DEFAULT_DOCKER_IMAGE


def _wsl_integration_disabled(text: str) -> bool:
    normalized = str(text or "").casefold()
    return (
        "wsl integration" in normalized
        or "activate the wsl integration" in normalized
        or "could not be found in this wsl" in normalized
    )


_SECURE_RUNTIME_DOCS_URL = (
    "https://ampliia.com/en/maia/docs/getting-started/secure-runtime/"
)
_SECURE_RUNTIME_WHY = (
    "Maia uses a Linux container as the security boundary for terminal, code, "
    "Office/Python automation, and delegated command execution requested by "
    "governed gateway users. The container receives only the paths that "
    "Governance grants to that identity."
)
_RESTRICTED_AVAILABLE = [
    "Chat, messaging gateways, Governance, approvals, and audit logging",
    "Path-checked file reads and supported staged file changes",
]
_FULL_AVAILABLE = [
    *_RESTRICTED_AVAILABLE,
    "Governed terminal, Python/code, and Office automation",
    "Delegated agents that need terminal or code execution",
]
_RESTRICTED_BLOCKED = [
    "Gateway terminal and arbitrary shell commands",
    "Python/code execution and Office automation that require a command runtime",
    "Delegated agents that need terminal or code execution",
]


def _read_linux_distro() -> str:
    try:
        values: dict[str, str] = {}
        with open("/etc/os-release", encoding="utf-8") as handle:
            for raw_line in handle:
                key, separator, value = raw_line.strip().partition("=")
                if separator:
                    values[key] = value.strip().strip('"')
        return (values.get("ID") or "linux").casefold()
    except OSError:
        return "linux"


def _running_in_wsl() -> bool:
    if os.getenv("WSL_DISTRO_NAME") or os.getenv("WSL_INTEROP"):
        return True
    try:
        with open("/proc/version", encoding="utf-8") as handle:
            return "microsoft" in handle.read().casefold()
    except OSError:
        return False


def _secure_runtime_platform() -> tuple[str, str, str]:
    system = platform.system().casefold()
    if system == "linux" and _running_in_wsl():
        return (
            "windows_wsl",
            "Windows with WSL2",
            os.getenv("WSL_DISTRO_NAME") or _read_linux_distro(),
        )
    if system == "linux":
        distro = _read_linux_distro()
        if os.getenv("TERMUX_VERSION"):
            return "android_termux", "Android with Termux", "termux"
        return "linux", "Linux", distro
    if system == "darwin":
        return "macos", "macOS", "macos"
    if system == "windows":
        return "windows_native", "Windows", "windows"
    return "unknown", platform.system() or "Unknown platform", system or "unknown"


def _runtime_name(executable: Optional[str], output: str = "") -> Optional[str]:
    combined = f"{os.path.basename(executable or '')} {output}".casefold()
    if "podman" in combined:
        return "podman"
    return "docker" if executable else None


def _linux_podman_install_command(distro: str) -> Optional[str]:
    if distro in {"ubuntu", "debian", "linuxmint", "raspbian"}:
        return "sudo apt-get update && sudo apt-get -y install podman"
    if distro in {"fedora", "centos", "rhel", "rocky", "almalinux"}:
        return "sudo dnf -y install podman"
    if distro in {"arch", "manjaro"}:
        return "sudo pacman -S --noconfirm podman"
    if distro in {"opensuse", "opensuse-leap", "opensuse-tumbleweed", "sles"}:
        return "sudo zypper --non-interactive install podman"
    if distro == "alpine":
        return "sudo apk add podman"
    return None


def _secure_runtime_steps(
    platform_key: str,
    status: str,
    runtime: Optional[str],
    distro: str,
    image: Optional[str] = None,
) -> list[dict[str, str]]:
    if status in RUNTIME_IMAGE_SETUP_STATUSES:
        image_text = image or "the configured sandbox image"
        return [
            {
                "title": "Provision Maia's sandbox image",
                "detail": (
                    f"Maia needs {image_text} locally before governed terminal, "
                    "Python, Office, or delegated commands can run. Setup downloads "
                    "the image and validates it with a disposable container."
                ),
                "command": "maia secure-runtime setup",
            },
            {
                "title": "Retry the original request",
                "detail": (
                    "When setup reports Full automation, retry the same request. "
                    "No gateway restart or new file grant is required."
                ),
                "command": "maia secure-runtime status",
            },
        ]

    if platform_key == "windows_wsl":
        return [
            {
                "title": "Install and start Docker Desktop in Windows",
                "detail": (
                    "Use the WSL 2 backend. Docker Desktop is installed and opened "
                    "from Windows, not from inside the Maia Linux terminal."
                ),
                "url": "https://docs.docker.com/desktop/setup/install/windows-install/",
            },
            {
                "title": "Enable this Maia distribution",
                "detail": (
                    "In Docker Desktop, open Settings > Resources > WSL Integration, "
                    "enable the distribution that runs Maia, then choose Apply & restart."
                ),
            },
            {
                "title": "Verify from the Maia terminal",
                "detail": "Both the Docker client and server must respond inside WSL.",
                "command": "docker version",
            },
            {
                "title": "Recheck Maia",
                "detail": "No gateway restart or new file grant is required.",
                "command": "maia secure-runtime status",
            },
        ]

    if platform_key == "linux":
        install_command = _linux_podman_install_command(distro)
        if not runtime:
            steps = [
                {
                    "title": "Install rootless Podman",
                    "detail": (
                        "Podman is the preferred Linux option because it can run "
                        "without a permanent root daemon."
                    ),
                    "url": "https://podman.io/docs/installation",
                }
            ]
            if install_command:
                steps[0]["command"] = install_command
        elif runtime == "docker":
            steps = [
                {
                    "title": "Start the Docker engine",
                    "detail": (
                        "Start or repair Docker Engine, then make sure this user can "
                        "run Docker without an authorization error."
                    ),
                    "command": "sudo systemctl enable --now docker",
                    "url": "https://docs.docker.com/engine/install/",
                }
            ]
        else:
            steps = [
                {
                    "title": "Repair rootless Podman",
                    "detail": "Run Podman as the same user that runs Maia and resolve the reported error.",
                    "command": "podman info",
                    "url": "https://podman.io/docs/installation",
                }
            ]
        steps.extend(
            [
                {
                    "title": "Verify the runtime",
                    "detail": "The client must be able to create Linux containers.",
                    "command": f"{runtime or 'podman'} version",
                },
                {
                    "title": "Recheck Maia",
                    "detail": "Retry the original request after this reports Full automation.",
                    "command": "maia secure-runtime status",
                },
            ]
        )
        return steps

    if platform_key == "macos":
        if runtime == "docker":
            steps = [
                {
                    "title": "Start Docker Desktop",
                    "detail": "Wait until Docker Desktop reports that its engine is running.",
                    "url": "https://docs.docker.com/desktop/setup/install/mac-install/",
                }
            ]
        else:
            steps = [
                {
                    "title": "Install Podman for macOS",
                    "detail": (
                        "Use the official Podman installer. macOS needs a small Linux "
                        "virtual machine because containers use the Linux kernel."
                    ),
                    "url": "https://podman.io/docs/installation",
                },
                {
                    "title": "Create and start the Podman machine",
                    "detail": "Run init once; later sessions normally need only start.",
                    "command": "podman machine init && podman machine start",
                },
            ]
        steps.extend(
            [
                {
                    "title": "Verify the runtime",
                    "detail": "The Linux container engine must answer from the Maia terminal.",
                    "command": f"{runtime or 'podman'} version",
                },
                {
                    "title": "Recheck Maia",
                    "detail": "No additional file grant is required.",
                    "command": "maia secure-runtime status",
                },
            ]
        )
        return steps

    return [
        {
            "title": "Use a supported Maia host",
            "detail": (
                "Full governed command automation is supported on Linux, macOS, "
                "and Windows through WSL2. This installation remains in Restricted mode."
            ),
            "url": _SECURE_RUNTIME_DOCS_URL,
        }
    ]


def _secure_runtime_payload(
    *,
    ready: bool,
    status: str,
    message: str,
    remediation: str,
    platform_key: str,
    platform_label: str,
    distro: str,
    runtime: Optional[str],
    image: Optional[str] = None,
) -> dict[str, object]:
    install_command = _linux_podman_install_command(distro)
    can_auto_setup = (
        (platform_key == "linux" and not runtime and bool(install_command))
        or (platform_key == "macos" and runtime == "podman" and not ready)
        or (
            bool(runtime)
            and status in RUNTIME_IMAGE_SETUP_STATUSES
        )
    )
    return {
        "ready": ready,
        "mode": "full" if ready else "restricted",
        "status": status,
        "platform": platform_key,
        "platform_label": platform_label,
        "distro": distro,
        "runtime": runtime,
        "image": image,
        "message": message,
        "remediation": remediation,
        "why": _SECURE_RUNTIME_WHY,
        "available_capabilities": list(
            _FULL_AVAILABLE if ready else _RESTRICTED_AVAILABLE
        ),
        "blocked_capabilities": [] if ready else list(_RESTRICTED_BLOCKED),
        "steps": []
        if ready
        else _secure_runtime_steps(platform_key, status, runtime, distro, image),
        "can_auto_setup": can_auto_setup,
        "setup_command": "maia secure-runtime setup",
        "verify_command": "maia secure-runtime status",
        "docs_url": _SECURE_RUNTIME_DOCS_URL,
    }


def _remove_probe_container(docker_exe: str, container_name: str) -> None:
    """Best-effort cleanup for a timed-out or failed readiness probe."""

    try:
        subprocess.run(
            [docker_exe, "rm", "-f", container_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        logger.debug(
            "Could not remove secure-runtime probe container %s",
            container_name,
            exc_info=True,
        )


def _probe_runtime_image(
    docker_exe: str,
    image: str,
    *,
    timeout: int,
) -> tuple[str, str]:
    """Check that *image* is local and can start under Maia's isolation flags.

    The inspect step deliberately precedes ``docker run --pull=never`` so a
    status request never performs a surprise network download.  Provisioning is
    handled explicitly by ``maia secure-runtime setup`` and by the installer.
    """

    try:
        inspected = subprocess.run(
            [docker_exe, "image", "inspect", "--format", "{{.Id}}", image],
            capture_output=True,
            text=True,
            timeout=max(5, timeout),
        )
    except subprocess.TimeoutExpired:
        return "image_check_failed", "Timed out while checking the sandbox image."
    except (FileNotFoundError, OSError) as exc:
        return "image_check_failed", str(exc)

    inspect_output = _docker_result_text(inspected)
    if inspected.returncode != 0:
        return "image_missing", inspect_output

    container_name = f"maia-runtime-check-{uuid.uuid4().hex[:8]}"
    smoke_command = [
        docker_exe,
        "run",
        "--rm",
        "--pull=never",
        "--name",
        container_name,
        "--init",
        "--network=none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "16",
        image,
        "sleep",
        "0",
    ]
    try:
        smoke = subprocess.run(
            smoke_command,
            capture_output=True,
            text=True,
            timeout=max(15, timeout),
        )
    except subprocess.TimeoutExpired:
        _remove_probe_container(docker_exe, container_name)
        return "image_unusable", "The sandbox image startup check timed out."
    except (FileNotFoundError, OSError) as exc:
        _remove_probe_container(docker_exe, container_name)
        return "image_check_failed", str(exc)

    if smoke.returncode != 0:
        detail = _docker_result_text(smoke)
        _remove_probe_container(docker_exe, container_name)
        return "image_unusable", detail
    return "ready", ""


def secure_runtime_status(timeout: int = 3) -> dict[str, object]:
    """Return an actionable, non-throwing secure-container readiness snapshot."""

    platform_key, platform_label, distro = _secure_runtime_platform()
    if platform_key in {"windows_native", "android_termux", "unknown"}:
        return _secure_runtime_payload(
            ready=False,
            status="unsupported_platform",
            message=(
                f"Full governed command automation is not available on {platform_label}."
            ),
            remediation=(
                "Run Maia on Linux, macOS, or Windows through WSL2, or continue "
                "with the safe capabilities available in Restricted mode."
            ),
            platform_key=platform_key,
            platform_label=platform_label,
            distro=distro,
            runtime=None,
        )

    # Docker Desktop can enable WSL integration while Maia is running and may
    # replace its helper path with /usr/bin/docker. Rediscover the executable
    # so the dashboard's "Check again" action never needs a process restart.
    global _docker_executable
    _docker_executable = None
    docker_exe = find_docker()
    if not docker_exe:
        return _secure_runtime_payload(
            ready=False,
            status="not_found",
            message="No supported secure runtime is available to Maia.",
            remediation=(
                "Set up Podman or Docker for this operating system, then recheck. "
                "Maia can continue in Restricted mode until then."
            ),
            platform_key=platform_key,
            platform_label=platform_label,
            distro=distro,
            runtime=None,
        )
    runtime = _runtime_name(docker_exe)
    try:
        result = subprocess.run(
            [docker_exe, "version"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return _secure_runtime_payload(
            ready=False,
            status="daemon_timeout",
            message=f"{(runtime or 'container').title()} is installed, but its engine is not responding.",
            remediation="Start or repair the secure runtime, wait until it is ready, then recheck.",
            platform_key=platform_key,
            platform_label=platform_label,
            distro=distro,
            runtime=runtime,
        )
    except (FileNotFoundError, OSError):
        return _secure_runtime_payload(
            ready=False,
            status="not_executable",
            message="Maia found a secure runtime, but could not execute it.",
            remediation="Repair the runtime installation or executable path, then recheck.",
            platform_key=platform_key,
            platform_label=platform_label,
            distro=distro,
            runtime=runtime,
        )

    output = _docker_result_text(result)
    runtime = _runtime_name(docker_exe, output)
    if result.returncode == 0:
        image = configured_runtime_image()
        image_status, image_detail = _probe_runtime_image(
            docker_exe,
            image,
            timeout=timeout,
        )
        detail_suffix = (
            f" Runtime reported: {image_detail[:800]}" if image_detail.strip() else ""
        )
        if image_status == "image_missing":
            return _secure_runtime_payload(
                ready=False,
                status=image_status,
                message=(
                    f"{(runtime or 'The secure runtime').title()} is running, but "
                    f"Maia's sandbox image {image} is not installed."
                ),
                remediation=(
                    "Run `maia secure-runtime setup` to download and validate the "
                    f"configured image.{detail_suffix}"
                ),
                platform_key=platform_key,
                platform_label=platform_label,
                distro=distro,
                runtime=runtime,
                image=image,
            )
        if image_status != "ready":
            return _secure_runtime_payload(
                ready=False,
                status=image_status,
                message=(
                    f"{(runtime or 'The secure runtime').title()} can see Maia's "
                    f"sandbox image {image}, but cannot start it safely."
                ),
                remediation=(
                    "Run `maia secure-runtime setup` to refresh the image and repeat "
                    f"the startup check.{detail_suffix}"
                ),
                platform_key=platform_key,
                platform_label=platform_label,
                distro=distro,
                runtime=runtime,
                image=image,
            )
        return _secure_runtime_payload(
            ready=True,
            status="ready",
            message=(
                "Full governed automation is ready through "
                f"{(runtime or 'the secure runtime').title()} using {image}."
            ),
            remediation="",
            platform_key=platform_key,
            platform_label=platform_label,
            distro=distro,
            runtime=runtime,
            image=image,
        )
    if _wsl_integration_disabled(output):
        _docker_executable = None
        return _secure_runtime_payload(
            ready=False,
            status="wsl_integration_disabled",
            message=(
                "Docker Desktop is running, but its WSL integration is not enabled "
                "for the Linux distribution running Maia."
            ),
            remediation=(
                "In Docker Desktop, open Settings > Resources > WSL Integration, "
                "enable the Maia distribution, choose Apply & restart, then recheck."
            ),
            platform_key=platform_key,
            platform_label=platform_label,
            distro=distro,
            runtime="docker",
        )
    return _secure_runtime_payload(
        ready=False,
        status="daemon_unavailable",
        message=f"{(runtime or 'The secure runtime').title()} is installed, but Maia cannot reach its engine.",
        remediation="Start or repair the secure runtime, wait until it is ready, then recheck.",
        platform_key=platform_key,
        platform_label=platform_label,
        distro=distro,
        runtime=runtime,
    )


def docker_runtime_status(timeout: int = 3) -> dict[str, object]:
    """Backward-compatible alias for the product-level secure runtime status."""

    return secure_runtime_status(timeout=timeout)


def provision_runtime_image(
    *,
    pull_timeout: int = 900,
    status_timeout: int = 15,
) -> dict[str, object]:
    """Pull and validate Maia's configured sandbox image.

    This is the mutation used by the guided CLI setup and dashboard completion
    flow after the container engine itself is available.  It deliberately
    refuses to install or reconfigure Docker/Podman; operating-system setup
    remains an explicit administrator action.
    """

    current = secure_runtime_status(timeout=status_timeout)
    if current.get("ready"):
        return current
    if current.get("status") not in RUNTIME_IMAGE_SETUP_STATUSES:
        raise RuntimeError(
            str(current.get("remediation") or current.get("message") or "")
            or "The secure container engine must be repaired before provisioning."
        )

    docker_exe = find_docker()
    if not docker_exe:
        raise RuntimeError("No supported container runtime is available.")
    image = str(current.get("image") or configured_runtime_image()).strip()
    if not image:
        raise RuntimeError("No sandbox image is configured under terminal.docker_image.")

    logger.info("Provisioning secure-runtime image %s", image)
    try:
        pulled = subprocess.run(
            [docker_exe, "pull", image],
            capture_output=True,
            text=True,
            timeout=pull_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Timed out while downloading Maia's sandbox image {image}."
        ) from exc
    except (FileNotFoundError, OSError) as exc:
        raise RuntimeError(f"Could not run the container runtime: {exc}") from exc

    if pulled.returncode != 0:
        detail = _docker_result_text(pulled) or (
            f"container runtime exited with code {pulled.returncode}"
        )
        raise RuntimeError(
            f"Could not download Maia's sandbox image {image}. "
            f"Docker reported: {detail[:2000]}"
        )

    refreshed = secure_runtime_status(timeout=status_timeout)
    if not refreshed.get("ready"):
        raise RuntimeError(
            "The sandbox image downloaded, but Maia's startup validation failed. "
            + str(refreshed.get("remediation") or refreshed.get("message") or "")
        )
    return refreshed


# Security flags applied to every container.
# The container itself is the security boundary (isolated from host).
# We drop all capabilities then add back the minimum needed:
#   DAC_OVERRIDE - root can write to bind-mounted dirs owned by host user
#   CHOWN/FOWNER - package managers (pip, npm, apt) need to set file ownership
#   SETUID/SETGID - the image entrypoint drops from root to the 'hermes'
#       user via `gosu`, which requires these caps. Combined with
#       `no-new-privileges`, gosu still cannot escalate back to root after
#       the drop, so the security posture is preserved. Omitted entirely
#       when the container starts as a non-root user via --user, since
#       no gosu drop is needed in that mode.
# Block privilege escalation and limit PIDs.
# /tmp is size-limited and nosuid but allows exec (needed by pip/npm builds).
_BASE_SECURITY_ARGS = [
    "--cap-drop", "ALL",
    "--cap-add", "DAC_OVERRIDE",
    "--cap-add", "CHOWN",
    "--cap-add", "FOWNER",
    "--security-opt", "no-new-privileges",
    "--pids-limit", "256",
    "--tmpfs", "/tmp:rw,nosuid,size=512m",
    "--tmpfs", "/var/tmp:rw,noexec,nosuid,size=256m",
    "--tmpfs", "/run:rw,noexec,nosuid,size=64m",
]

# Extra caps needed when the container starts as root and an entrypoint
# must drop privileges via gosu/su. Skipped when --user is passed because
# the container already starts unprivileged and never needs to switch.
_GOSU_CAP_ARGS = [
    "--cap-add", "SETUID",
    "--cap-add", "SETGID",
]


def _build_security_args(run_as_host_user: bool) -> list[str]:
    """Return the security/cap/tmpfs args tailored to the privilege mode."""
    if run_as_host_user:
        return list(_BASE_SECURITY_ARGS)
    return list(_BASE_SECURITY_ARGS) + list(_GOSU_CAP_ARGS)


def _resolve_host_user_spec() -> Optional[str]:
    """Return ``<uid>:<gid>`` for the current host user, or ``None`` on platforms
    where this is not meaningful (e.g. Windows without posix ids).

    We intentionally read ``os.getuid()``/``os.getgid()`` directly rather than
    going through ``getpass``/``pwd`` so this stays cheap and never raises on
    nameless UIDs (nss lookups can fail inside sandboxed launchers).
    """
    get_uid = getattr(os, "getuid", None)
    get_gid = getattr(os, "getgid", None)
    if get_uid is None or get_gid is None:
        return None
    try:
        return f"{get_uid()}:{get_gid()}"
    except Exception:  # pragma: no cover - defensive
        return None


_storage_opt_ok: Optional[bool] = None  # cached result across instances


def _ensure_docker_available() -> None:
    """Best-effort check that the docker CLI is available before use.

    Reuses ``find_docker()`` so this preflight stays consistent with the rest of
    the Docker backend, including known non-PATH Docker Desktop locations.
    """
    docker_exe = find_docker()
    if not docker_exe:
        logger.error(
            "Docker backend selected but no docker executable was found in PATH "
            "or known install locations. Install Docker Desktop and ensure the "
            "CLI is available."
        )
        raise RuntimeError(
            "Docker executable not found in PATH or known install locations. "
            "Install Docker and ensure the 'docker' command is available."
        )

    try:
        result = subprocess.run(
            [docker_exe, "version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        logger.error(
            "Docker backend selected but the resolved docker executable '%s' could "
            "not be executed.",
            docker_exe,
            exc_info=True,
        )
        raise RuntimeError(
            "Docker executable could not be executed. Check your Docker installation."
        )
    except subprocess.TimeoutExpired:
        logger.error(
            "Docker backend selected but '%s version' timed out. "
            "The Docker daemon may not be running.",
            docker_exe,
            exc_info=True,
        )
        raise RuntimeError(
            "Docker daemon is not responding. Ensure Docker is running and try again."
        )
    except Exception:
        logger.error(
            "Unexpected error while checking Docker availability.",
            exc_info=True,
        )
        raise
    else:
        if result.returncode != 0:
            result_text = _docker_result_text(result)
            logger.error(
                "Docker backend selected but '%s version' failed "
                "(exit code %d, output=%s)",
                docker_exe,
                result.returncode,
                result_text,
            )
            if _wsl_integration_disabled(result_text):
                global _docker_executable
                _docker_executable = None
                raise RuntimeError(
                    "Docker Desktop WSL integration is disabled for the Linux "
                    "distribution running Maia. In Docker Desktop, open Settings "
                    "> Resources > WSL Integration, enable this distribution, "
                    "choose Apply & restart, then retry."
                )
            raise RuntimeError(
                "Docker command is available but 'docker version' failed. "
                "Check your Docker installation."
            )


class DockerEnvironment(BaseEnvironment):
    """Hardened Docker container execution with resource limits and persistence.

    Security: all capabilities dropped, no privilege escalation, PID limits,
    size-limited tmpfs for scratch dirs. The container itself is the security
    boundary — the filesystem inside is writable so agents can install packages
    (pip, npm, apt) as needed. Writable workspace via tmpfs or bind mounts.

    Persistence: when enabled, bind mounts preserve /workspace and /root
    across container restarts.
    """

    def __init__(
        self,
        image: str,
        cwd: str = "/root",
        timeout: int = 60,
        cpu: float = 0,
        memory: int = 0,
        disk: int = 0,
        persistent_filesystem: bool = False,
        task_id: str = "default",
        volumes: list = None,
        forward_env: list[str] | None = None,
        env: dict | None = None,
        network: bool = True,
        host_cwd: str = None,
        auto_mount_cwd: bool = False,
        run_as_host_user: bool = False,
    ):
        if cwd == "~":
            cwd = "/root"
        super().__init__(cwd=cwd, timeout=timeout)
        self._persistent = persistent_filesystem
        self._task_id = task_id
        self._forward_env = _normalize_forward_env_names(forward_env)
        self._env = _normalize_env_dict(env)
        self._container_id: Optional[str] = None
        logger.info(f"DockerEnvironment volumes: {volumes}")
        # Ensure volumes is a list (config.yaml could be malformed)
        if volumes is not None and not isinstance(volumes, list):
            logger.warning(f"docker_volumes config is not a list: {volumes!r}")
            volumes = []

        # Fail fast if Docker is not available.
        _ensure_docker_available()

        # Build resource limit args
        resource_args = []
        if cpu > 0:
            resource_args.extend(["--cpus", str(cpu)])
        if memory > 0:
            resource_args.extend(["--memory", f"{memory}m"])
        if disk > 0 and sys.platform != "darwin":
            if self._storage_opt_supported():
                resource_args.extend(["--storage-opt", f"size={disk}m"])
            else:
                logger.warning(
                    "Docker storage driver does not support per-container disk limits "
                    "(requires overlay2 on XFS with pquota). Container will run without disk quota."
                )
        if not network:
            resource_args.append("--network=none")

        # Persistent workspace via bind mounts from a configurable host directory
        # (TERMINAL_SANDBOX_DIR, default ~/.hermes/sandboxes/). Non-persistent
        # mode uses tmpfs (ephemeral, fast, gone on cleanup).
        from tools.environments.base import get_sandbox_dir

        # User-configured volume mounts (from config.yaml docker_volumes)
        volume_args = []
        workspace_explicitly_mounted = False
        for vol in (volumes or []):
            if not isinstance(vol, str):
                logger.warning(f"Docker volume entry is not a string: {vol!r}")
                continue
            vol = vol.strip()
            if not vol:
                continue
            if ":" in vol:
                volume_args.extend(["-v", vol])
                if ":/workspace" in vol:
                    workspace_explicitly_mounted = True
            else:
                logger.warning(f"Docker volume '{vol}' missing colon, skipping")

        host_cwd_abs = os.path.abspath(os.path.expanduser(host_cwd)) if host_cwd else ""
        bind_host_cwd = (
            auto_mount_cwd
            and bool(host_cwd_abs)
            and os.path.isdir(host_cwd_abs)
            and not workspace_explicitly_mounted
        )
        if auto_mount_cwd and host_cwd and not os.path.isdir(host_cwd_abs):
            logger.debug(f"Skipping docker cwd mount: host_cwd is not a valid directory: {host_cwd}")

        self._workspace_dir: Optional[str] = None
        self._home_dir: Optional[str] = None
        writable_args = []
        if self._persistent:
            sandbox = get_sandbox_dir() / "docker" / task_id
            self._home_dir = str(sandbox / "home")
            os.makedirs(self._home_dir, exist_ok=True)
            writable_args.extend([
                "-v", f"{self._home_dir}:/root",
            ])
            if not bind_host_cwd and not workspace_explicitly_mounted:
                self._workspace_dir = str(sandbox / "workspace")
                os.makedirs(self._workspace_dir, exist_ok=True)
                writable_args.extend([
                    "-v", f"{self._workspace_dir}:/workspace",
                ])
        else:
            if not bind_host_cwd and not workspace_explicitly_mounted:
                writable_args.extend([
                    "--tmpfs", "/workspace:rw,exec,size=10g",
                ])
            writable_args.extend([
                "--tmpfs", "/home:rw,exec,size=1g",
                "--tmpfs", "/root:rw,exec,size=1g",
            ])

        if bind_host_cwd:
            logger.info(f"Mounting configured host cwd to /workspace: {host_cwd_abs}")
            volume_args = ["-v", f"{host_cwd_abs}:/workspace", *volume_args]
        elif workspace_explicitly_mounted:
            logger.debug("Skipping docker cwd mount: /workspace already mounted by user config")

        # Mount credential files (OAuth tokens, etc.) declared by skills.
        # Read-only so the container can authenticate but not modify host creds.
        try:
            from tools.credential_files import (
                get_credential_file_mounts,
                get_skills_directory_mount,
                get_cache_directory_mounts,
            )

            for mount_entry in get_credential_file_mounts():
                volume_args.extend([
                    "-v",
                    f"{mount_entry['host_path']}:{mount_entry['container_path']}:ro",
                ])
                logger.info(
                    "Docker: mounting credential %s -> %s",
                    mount_entry["host_path"],
                    mount_entry["container_path"],
                )

            # Mount skill directories (local + external) so skill
            # scripts/templates are available inside the container.
            for skills_mount in get_skills_directory_mount():
                volume_args.extend([
                    "-v",
                    f"{skills_mount['host_path']}:{skills_mount['container_path']}:ro",
                ])
                logger.info(
                    "Docker: mounting skills dir %s -> %s",
                    skills_mount["host_path"],
                    skills_mount["container_path"],
                )

            # Mount host-side cache directories (documents, images, audio,
            # screenshots) so the agent can access uploaded files and other
            # cached media from inside the container.  Read-only — the
            # container reads these but the host gateway manages writes.
            for cache_mount in get_cache_directory_mounts():
                volume_args.extend([
                    "-v",
                    f"{cache_mount['host_path']}:{cache_mount['container_path']}:ro",
                ])
                logger.info(
                    "Docker: mounting cache dir %s -> %s",
                    cache_mount["host_path"],
                    cache_mount["container_path"],
                )
        except Exception as e:
            logger.debug("Docker: could not load credential file mounts: %s", e)

        # Explicit environment variables (docker_env config) — set at container
        # creation so they're available to all processes (including entrypoint).
        env_args = []
        for key in sorted(self._env):
            env_args.extend(["-e", f"{key}={self._env[key]}"])

        # Optional: run the container as the host user so files written into
        # bind-mounted dirs (/workspace, /root, docker_volumes entries) are
        # owned by that user on the host instead of by root. Skip cleanly on
        # platforms without POSIX uid/gid (e.g. native Windows Docker).
        user_args: list[str] = []
        if run_as_host_user:
            user_spec = _resolve_host_user_spec()
            if user_spec is not None:
                user_args = ["--user", user_spec]
                logger.info("Docker: running container as host user %s", user_spec)
            else:
                logger.warning(
                    "docker_run_as_host_user is enabled but this platform does "
                    "not expose POSIX uid/gid; container will start as its "
                    "image default user."
                )
                # Fall back to the full cap set — without --user, an image's
                # entrypoint may still need gosu/su to drop privileges.
        security_args = _build_security_args(run_as_host_user and bool(user_args))

        logger.info(f"Docker volume_args: {volume_args}")
        all_run_args = (
            security_args
            + user_args
            + writable_args
            + resource_args
            + volume_args
            + env_args
        )
        logger.info(f"Docker run_args: {all_run_args}")

        # Resolve the docker executable once so it works even when
        # /usr/local/bin is not in PATH (common on macOS gateway/service).
        self._docker_exe = find_docker() or "docker"

        # Start the container directly via `docker run -d`.
        container_name = f"hermes-{uuid.uuid4().hex[:8]}"
        run_cmd = [
            self._docker_exe, "run", "-d",
            "--init",           # tini/catatonit as PID 1 — reaps zombie children
            "--name", container_name,
            "-w", cwd,
            *all_run_args,
            image,
            "sleep", "infinity",  # no fixed lifetime — idle reaper handles cleanup
        ]
        logger.debug(f"Starting container: {' '.join(run_cmd)}")
        try:
            result = subprocess.run(
                run_cmd,
                capture_output=True,
                text=True,
                timeout=120,  # image pull may take a while
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Timed out while starting governed container with image {image}. "
                "Run `maia secure-runtime status` to check the configured image "
                "and container engine."
            ) from exc
        if result.returncode != 0:
            detail = _docker_result_text(result) or (
                f"container runtime exited with code {result.returncode}"
            )
            raise RuntimeError(
                f"Could not start governed container with image {image}. "
                f"Docker reported: {detail[:2000]} Run `maia secure-runtime setup` "
                "to provision and validate the sandbox image."
            )
        self._container_id = result.stdout.strip()
        logger.info(f"Started container {container_name} ({self._container_id[:12]})")

        # Build the init-time env forwarding args (used only by init_session
        # to inject host env vars into the snapshot; subsequent commands get
        # them from the snapshot file).
        self._init_env_args = self._build_init_env_args()

        # Initialize session snapshot inside the container
        self.init_session()

    def _build_init_env_args(self) -> list[str]:
        """Build -e KEY=VALUE args for injecting host env vars into init_session.

        These are used once during init_session() so that export -p captures
        them into the snapshot.  Subsequent execute() calls don't need -e flags.
        """
        exec_env: dict[str, str] = dict(self._env)

        explicit_forward_keys = set(self._forward_env)
        passthrough_keys: set[str] = set()
        try:
            from tools.env_passthrough import get_all_passthrough
            passthrough_keys = set(get_all_passthrough())
        except Exception:
            pass
        # Explicit docker_forward_env entries are an intentional opt-in and must
        # win over the generic Hermes secret blocklist. Only implicit passthrough
        # keys are filtered.
        forward_keys = explicit_forward_keys | (passthrough_keys - _HERMES_PROVIDER_ENV_BLOCKLIST)
        hermes_env = _load_hermes_env_vars() if forward_keys else {}
        for key in sorted(forward_keys):
            value = os.getenv(key)
            if value is None:
                value = hermes_env.get(key)
            if value is not None:
                exec_env[key] = value

        args = []
        for key in sorted(exec_env):
            args.extend(["-e", f"{key}={exec_env[key]}"])
        return args

    def _run_bash(self, cmd_string: str, *, login: bool = False,
                  timeout: int = 120,
                  stdin_data: str | None = None) -> subprocess.Popen:
        """Spawn a bash process inside the Docker container."""
        assert self._container_id, "Container not started"
        cmd = [self._docker_exe, "exec"]
        if stdin_data is not None:
            cmd.append("-i")

        # Only inject -e env args during init_session (login=True).
        # Subsequent commands get env vars from the snapshot.
        if login:
            cmd.extend(self._init_env_args)

        cmd.extend([self._container_id])

        if login:
            cmd.extend(["bash", "-l", "-c", cmd_string])
        else:
            cmd.extend(["bash", "-c", cmd_string])

        return _popen_bash(cmd, stdin_data)

    @staticmethod
    def _storage_opt_supported() -> bool:
        """Check if Docker's storage driver supports --storage-opt size=.
        
        Only overlay2 on XFS with pquota supports per-container disk quotas.
        Ubuntu (and most distros) default to ext4, where this flag errors out.
        """
        global _storage_opt_ok
        if _storage_opt_ok is not None:
            return _storage_opt_ok
        try:
            docker = find_docker() or "docker"
            result = subprocess.run(
                [docker, "info", "--format", "{{.Driver}}"],
                capture_output=True, text=True, timeout=10,
            )
            driver = result.stdout.strip().lower()
            if driver != "overlay2":
                _storage_opt_ok = False
                return False
            # overlay2 only supports storage-opt on XFS with pquota.
            # Probe by attempting a dry-ish run — the fastest reliable check.
            probe = subprocess.run(
                [docker, "create", "--storage-opt", "size=1m", "hello-world"],
                capture_output=True, text=True, timeout=15,
            )
            if probe.returncode == 0:
                # Clean up the created container
                container_id = probe.stdout.strip()
                if container_id:
                    subprocess.run([docker, "rm", container_id],
                                   capture_output=True, timeout=5)
                _storage_opt_ok = True
            else:
                _storage_opt_ok = False
        except Exception:
            _storage_opt_ok = False
        logger.debug("Docker --storage-opt support: %s", _storage_opt_ok)
        return _storage_opt_ok

    def cleanup(self):
        """Stop and remove the container. Bind-mount dirs persist if persistent=True."""
        if self._container_id:
            try:
                # Stop in background so cleanup doesn't block
                stop_cmd = (
                    f"(timeout 60 {self._docker_exe} stop {self._container_id} || "
                    f"{self._docker_exe} rm -f {self._container_id}) >/dev/null 2>&1 &"
                )
                subprocess.Popen(stop_cmd, shell=True)
            except Exception as e:
                logger.warning("Failed to stop container %s: %s", self._container_id, e)

            if not self._persistent:
                # Also schedule removal (stop only leaves it as stopped)
                try:
                    subprocess.Popen(
                        f"sleep 3 && {self._docker_exe} rm -f {self._container_id} >/dev/null 2>&1 &",
                        shell=True,
                    )
                except Exception:
                    pass
            self._container_id = None

        if not self._persistent:
            for d in (self._workspace_dir, self._home_dir):
                if d:
                    shutil.rmtree(d, ignore_errors=True)

    def discard(self):
        """Synchronously remove the container before replacing security mounts."""

        container_id = self._container_id
        if not container_id:
            return
        result = subprocess.run(
            [self._docker_exe, "rm", "-f", container_id],
            capture_output=True,
            text=True,
            timeout=65,
        )
        output = _docker_result_text(result)
        if result.returncode != 0 and "no such container" not in output.casefold():
            raise RuntimeError(
                f"Could not remove the previous governed container: {output or 'docker rm failed'}"
            )
        self._container_id = None
        if not self._persistent:
            for directory in (self._workspace_dir, self._home_dir):
                if directory:
                    shutil.rmtree(directory, ignore_errors=True)
