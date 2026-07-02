"""
Backup and import commands for the Maia CLI.

`maia backup` creates a zip archive of the entire HERMES_HOME directory
(excluding the codebase repo and transient files).

`maia import` restores from a backup zip, overlaying onto the current
HERMES_HOME root.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional

from hermes_constants import get_default_hermes_root, get_hermes_home, display_hermes_home

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exclusion rules
# ---------------------------------------------------------------------------

# Directory names to skip entirely (matched against each path component)
_EXCLUDED_DIRS = {
    "hermes-agent",     # the codebase repo — re-clone instead
    "__pycache__",      # bytecode caches — regenerated on import
    ".git",             # nested git dirs (profiles shouldn't have these, but safety)
    "node_modules",     # js deps if website/ somehow leaks in
    "backups",          # prior auto-backups — don't nest backups exponentially
    "checkpoints",      # session-local trajectory caches — regenerated per-session,
                        # session-hash-keyed so they don't port to another machine anyway
}

# File-name suffixes to skip
_EXCLUDED_SUFFIXES = (
    ".pyc",
    ".pyo",
    # SQLite sidecar files — the backup takes a consistent snapshot of ``*.db``
    # via ``sqlite3.backup()``, so shipping the live WAL / shared-memory /
    # rollback-journal alongside would pair a fresh snapshot with stale sidecar
    # state and produce a torn restore on the next open. They're transient and
    # regenerated on first connection anyway.
    ".db-wal",
    ".db-shm",
    ".db-journal",
)

# File names to skip (runtime state that's meaningless on another machine)
_EXCLUDED_NAMES = {
    "gateway.pid",
    "cron.pid",
}

# zipfile.open() drops Unix mode bits on extract; restore tightens these to 0600.
_SECRET_FILE_NAMES = {".env", "auth.json", "state.db"}
_MIGRATION_REVIEW_DIR = "migration"
_MIGRATION_SENSITIVE_KEYS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
)


@dataclass(frozen=True)
class _ArchiveEntry:
    name: str
    size: int
    member: Any


class _ReadableArchive:
    """Small safe reader facade over zip and tar/tar.gz archives."""

    def __init__(self, path: Path):
        self.path = path
        self.kind = ""
        self._handle: zipfile.ZipFile | tarfile.TarFile | None = None
        self._entries: list[_ArchiveEntry] = []

    def __enter__(self) -> "_ReadableArchive":
        if zipfile.is_zipfile(self.path):
            zf = zipfile.ZipFile(self.path, "r")
            self.kind = "zip"
            self._handle = zf
            self._entries = [
                _ArchiveEntry(info.filename, info.file_size, info)
                for info in zf.infolist()
                if not info.is_dir()
            ]
            return self

        if tarfile.is_tarfile(self.path):
            tf = tarfile.open(self.path, "r:*")
            self.kind = "tar"
            self._handle = tf
            # Only regular files are migrated.  Symlinks, hardlinks, devices,
            # fifos, and other special members are ignored to prevent archive
            # tricks from escaping the review workflow.
            self._entries = [
                _ArchiveEntry(member.name, int(member.size or 0), member)
                for member in tf.getmembers()
                if member.isfile()
            ]
            return self

        raise ValueError("archive must be a zip, tar, tar.gz, or tgz file")

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is not None:
            self._handle.close()

    @property
    def entries(self) -> list[_ArchiveEntry]:
        return self._entries

    def open(self, entry: _ArchiveEntry):
        if self._handle is None:
            raise RuntimeError("archive is not open")
        if self.kind == "zip":
            return self._handle.open(entry.member)  # type: ignore[union-attr]
        extracted = self._handle.extractfile(entry.member)  # type: ignore[union-attr]
        if extracted is None:
            raise OSError(f"could not read archive member {entry.name!r}")
        return extracted


def _should_exclude(rel_path: Path) -> bool:
    """Return True if *rel_path* (relative to hermes root) should be skipped."""
    parts = rel_path.parts

    # Any path component matches an excluded dir name
    for part in parts:
        if part in _EXCLUDED_DIRS:
            return True

    name = rel_path.name

    if name in _EXCLUDED_NAMES:
        return True

    if name.endswith(_EXCLUDED_SUFFIXES):
        return True

    return False


def _common_archive_prefix(names: Iterable[str]) -> str:
    files = [n.replace("\\", "/") for n in names if n and not n.endswith("/")]
    if not files:
        return ""
    parts_list = [PurePosixPath(n).parts for n in files]
    first_parts = {p[0] for p in parts_list if len(p) > 1}
    if len(first_parts) == 1:
        prefix = first_parts.pop()
        if prefix in (".hermes", "hermes"):
            return prefix + "/"
    return ""


def _safe_archive_relative_path(raw_name: str, prefix: str = "") -> tuple[Optional[Path], str]:
    """Return a safe relative path for an archive member.

    Archive names are POSIX-style even on Windows.  This routine rejects
    absolute paths, drive-like prefixes, and ``..`` traversal before converting
    to a local ``Path``.
    """

    name = raw_name.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    if prefix and name.startswith(prefix):
        name = name[len(prefix):]
    while name.startswith("./"):
        name = name[2:]
    if not name:
        return None, "empty path"

    posix = PurePosixPath(name)
    parts = posix.parts
    if parts and parts[0] in (".hermes", "hermes") and len(parts) > 1:
        parts = parts[1:]
        posix = PurePosixPath(*parts)
    if posix.is_absolute() or not parts:
        return None, "absolute path blocked"
    if parts[0].endswith(":"):
        return None, "drive path blocked"
    if any(part in ("", ".", "..") for part in parts):
        return None, "path traversal blocked"
    return Path(*parts), ""


def _rel_under(rel: Path, dirname: str) -> Optional[Path]:
    parts = rel.parts
    if not parts or parts[0] != dirname:
        return None
    if len(parts) == 1:
        return None
    return Path(*parts[1:])


def _copy_archive_entry(reader: _ReadableArchive, entry: _ArchiveEntry, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with reader.open(entry) as src, open(target, "wb") as dst:
        shutil.copyfileobj(src, dst)
    if target.name in _SECRET_FILE_NAMES:
        os.chmod(target, 0o600)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _MIGRATION_SENSITIVE_KEYS)


def _redact_imported_value(key: str, value: Any) -> Any:
    if _is_sensitive_key(key):
        return ""
    if isinstance(value, dict):
        return {str(k): _redact_imported_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_imported_value(key, item) for item in value]
    return value


def _safe_imported_mcp_config(server_config: Any, imported_at: str) -> Optional[dict[str, Any]]:
    if not isinstance(server_config, dict):
        return None
    sanitized = {
        str(key): _redact_imported_value(str(key), value)
        for key, value in server_config.items()
    }
    sanitized["enabled"] = False
    sanitized["migration_review_required"] = True
    sanitized["migration"] = {
        "source": "upstream-hermes-export",
        "imported_at": imported_at,
        "review_required": True,
    }
    return sanitized


def _load_yaml_member(reader: _ReadableArchive, entry: _ArchiveEntry) -> dict[str, Any]:
    try:
        import yaml

        with reader.open(entry) as src:
            raw = src.read()
        parsed = yaml.safe_load(raw.decode("utf-8", errors="replace")) or {}
        return parsed if isinstance(parsed, dict) else {}
    except Exception as exc:
        logger.warning("Could not parse imported YAML %s: %s", entry.name, exc)
        return {}


def _merge_imported_mcp_servers(
    imported_servers: dict[str, Any],
    *,
    imported_at: str,
) -> list[str]:
    if not imported_servers:
        return []

    from hermes_cli.config import load_config, save_config

    cfg = load_config()
    current = cfg.setdefault("mcp_servers", {})
    if not isinstance(current, dict):
        current = {}
        cfg["mcp_servers"] = current

    imported_names: list[str] = []
    for raw_name, server_config in sorted(imported_servers.items()):
        name = str(raw_name).strip()
        if not name:
            continue
        sanitized = _safe_imported_mcp_config(server_config, imported_at)
        if sanitized is None:
            continue
        target_name = name
        suffix = 2
        while target_name in current:
            target_name = f"{name}-imported-{suffix}"
            suffix += 1
        current[target_name] = sanitized
        imported_names.append(target_name)

    if imported_names:
        save_config(cfg)
    return imported_names


def _run_hermes_export_migration(args) -> None:
    """Stage an upstream Hermes export without overwriting guardrails."""

    archive_path = Path(args.zipfile).expanduser().resolve()
    if not archive_path.is_file():
        print(f"Error: File not found: {archive_path}")
        sys.exit(1)

    hermes_root = get_default_hermes_root()
    hermes_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    migration_root = hermes_root / _MIGRATION_REVIEW_DIR / f"hermes-import-{stamp}"
    memories_root = migration_root / "memories"
    skills_root = migration_root / "skills-review"
    review_root = migration_root / "review"
    report_path = migration_root / "report.json"

    report: dict[str, Any] = {
        "archive": str(archive_path),
        "mode": "from_hermes_export",
        "imported_at": stamp,
        "guardrails": {
            "existing_config_preserved": True,
            "skills_staged_for_review": True,
            "mcp_servers_disabled_by_default": True,
            "secrets_not_activated": True,
        },
        "memories": [],
        "skills": [],
        "review_files": [],
        "mcp_servers": [],
        "skipped": [],
    }

    imported_config_servers: dict[str, Any] = {}

    try:
        with _ReadableArchive(archive_path) as archive:
            prefix = _common_archive_prefix(entry.name for entry in archive.entries)
            for entry in archive.entries:
                rel, reason = _safe_archive_relative_path(entry.name, prefix)
                if rel is None:
                    report["skipped"].append({"path": entry.name, "reason": reason})
                    continue

                memory_rel = _rel_under(rel, "memories")
                if memory_rel is not None:
                    target = memories_root / memory_rel
                    _copy_archive_entry(archive, entry, target)
                    report["memories"].append(str(target.relative_to(migration_root)))
                    continue

                skill_rel = _rel_under(rel, "skills")
                if skill_rel is not None:
                    target = skills_root / skill_rel
                    _copy_archive_entry(archive, entry, target)
                    report["skills"].append(str(target.relative_to(migration_root)))
                    continue

                if rel == Path("config.yaml"):
                    cfg = _load_yaml_member(archive, entry)
                    servers = cfg.get("mcp_servers")
                    if isinstance(servers, dict):
                        imported_config_servers.update(servers)
                    target = review_root / "config.yaml"
                    _copy_archive_entry(archive, entry, target)
                    report["review_files"].append(str(target.relative_to(migration_root)))
                    continue

                if rel.name in {".env", "auth.json"} or rel.parts[:1] == ("mcp-tokens",):
                    target = review_root / rel
                    _copy_archive_entry(archive, entry, target)
                    report["review_files"].append(str(target.relative_to(migration_root)))
                    continue

                report["skipped"].append({
                    "path": str(rel),
                    "reason": "not part of the guarded Hermes export migration allowlist",
                })
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    imported_mcp = _merge_imported_mcp_servers(
        imported_config_servers,
        imported_at=stamp,
    )
    report["mcp_servers"] = imported_mcp

    migration_root.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    try:
        from agent.audit_log import record_audit_event

        record_audit_event(
            "migration.hermes_export_staged",
            action="migration.stage",
            resource=str(archive_path),
            outcome="staged",
            metadata={
                "migration_root": str(migration_root),
                "report": str(report_path),
                "memories": len(report["memories"]),
                "skills": len(report["skills"]),
                "review_files": len(report["review_files"]),
                "mcp_servers": len(imported_mcp),
                "skipped": len(report["skipped"]),
            },
        )
    except Exception:
        pass

    print("Hermes export migration staged.")
    print(f"  Archive:       {archive_path}")
    print(f"  Review folder: {migration_root}")
    print(f"  Report:        {report_path}")
    print(f"  Memories:      {len(report['memories'])} staged")
    print(f"  Skills:        {len(report['skills'])} staged for review")
    print(f"  MCP servers:   {len(imported_mcp)} imported disabled")
    if report["review_files"]:
        print(f"  Review files:  {len(report['review_files'])} copied but not activated")
    if report["skipped"]:
        print(f"  Skipped:       {len(report['skipped'])} entries")
    print()
    print("Next steps:")
    print("  1. Review the migration report and staged skills before activation.")
    print("  2. Re-enter any secrets in .env or MCP server env blocks through the Keys panel.")
    print("  3. Keep governance.default_file_policy: deny for production folder access.")


# ---------------------------------------------------------------------------
# SQLite safe copy
# ---------------------------------------------------------------------------

def _safe_copy_db(src: Path, dst: Path) -> bool:
    """Copy a SQLite database safely using the backup() API.

    Handles WAL mode — produces a consistent snapshot even while
    the DB is being written to.  Falls back to raw copy on failure.
    """
    try:
        conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        backup_conn = sqlite3.connect(str(dst))
        conn.backup(backup_conn)
        backup_conn.close()
        conn.close()
        return True
    except Exception as exc:
        logger.warning("SQLite safe copy failed for %s: %s", src, exc)
        try:
            shutil.copy2(src, dst)
            return True
        except Exception as exc2:
            logger.error("Raw copy also failed for %s: %s", src, exc2)
            return False


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def _format_size(nbytes: int) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}" if unit != "B" else f"{nbytes} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def run_backup(args) -> None:
    """Create a zip backup of the Hermes home directory."""
    hermes_root = get_default_hermes_root()

    if not hermes_root.is_dir():
        print(f"Error: Hermes home directory not found at {hermes_root}")
        sys.exit(1)

    # Determine output path
    if args.output:
        out_path = Path(args.output).expanduser().resolve()
        # If user gave a directory, put the zip inside it
        if out_path.is_dir():
            stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
            out_path = out_path / f"hermes-backup-{stamp}.zip"
    else:
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        out_path = Path.home() / f"hermes-backup-{stamp}.zip"

    # Ensure the suffix is .zip
    if out_path.suffix.lower() != ".zip":
        out_path = out_path.with_suffix(out_path.suffix + ".zip")

    # Ensure parent directory exists
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Collect files
    print(f"Scanning {display_hermes_home()} ...")
    files_to_add: list[tuple[Path, Path]] = []  # (absolute, relative)
    skipped_dirs = set()

    for dirpath, dirnames, filenames in os.walk(hermes_root, followlinks=False):
        dp = Path(dirpath)
        rel_dir = dp.relative_to(hermes_root)

        # Prune excluded directories in-place so os.walk doesn't descend
        orig_dirnames = dirnames[:]
        dirnames[:] = [
            d for d in dirnames
            if d not in _EXCLUDED_DIRS
        ]
        for removed in set(orig_dirnames) - set(dirnames):
            skipped_dirs.add(str(rel_dir / removed))

        for fname in filenames:
            fpath = dp / fname
            rel = fpath.relative_to(hermes_root)

            if _should_exclude(rel):
                continue

            # Skip the output zip itself if it happens to be inside hermes root
            try:
                if fpath.resolve() == out_path.resolve():
                    continue
            except (OSError, ValueError):
                pass

            files_to_add.append((fpath, rel))

    if not files_to_add:
        print("No files to back up.")
        return

    # Create the zip
    file_count = len(files_to_add)
    print(f"Backing up {file_count} files ...")

    total_bytes = 0
    errors = []
    t0 = time.monotonic()

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for i, (abs_path, rel_path) in enumerate(files_to_add, 1):
            try:
                # Safe copy for SQLite databases (handles WAL mode)
                if abs_path.suffix == ".db":
                    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                        tmp_db = Path(tmp.name)
                    if _safe_copy_db(abs_path, tmp_db):
                        zf.write(tmp_db, arcname=str(rel_path))
                        total_bytes += tmp_db.stat().st_size
                        tmp_db.unlink(missing_ok=True)
                    else:
                        tmp_db.unlink(missing_ok=True)
                        errors.append(f"  {rel_path}: SQLite safe copy failed")
                        continue
                else:
                    zf.write(abs_path, arcname=str(rel_path))
                    total_bytes += abs_path.stat().st_size
            except (PermissionError, OSError, ValueError) as exc:
                errors.append(f"  {rel_path}: {exc}")
                continue

            # Progress every 500 files
            if i % 500 == 0:
                print(f"  {i}/{file_count} files ...")

    elapsed = time.monotonic() - t0
    zip_size = out_path.stat().st_size

    # Summary
    print()
    print(f"Backup complete: {out_path}")
    print(f"  Files:       {file_count}")
    print(f"  Original:    {_format_size(total_bytes)}")
    print(f"  Compressed:  {_format_size(zip_size)}")
    print(f"  Time:        {elapsed:.1f}s")

    if skipped_dirs:
        print(f"\n  Excluded directories:")
        for d in sorted(skipped_dirs):
            print(f"    {d}/")

    if errors:
        print(f"\n  Warnings ({len(errors)} files skipped):")
        for e in errors[:10]:
            print(e)
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")

    print(f"\nRestore with: maia import {out_path.name}")


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def _validate_backup_zip(zf: zipfile.ZipFile) -> tuple[bool, str]:
    """Check that a zip looks like a Hermes backup.

    Returns (ok, reason).
    """
    names = zf.namelist()
    if not names:
        return False, "zip archive is empty"

    # Look for telltale files that a hermes home would have
    markers = {"config.yaml", ".env", "state.db"}
    found = set()
    for n in names:
        # Could be at the root or one level deep (if someone zipped the directory)
        basename = Path(n).name
        if basename in markers:
            found.add(basename)

    if not found:
        return False, (
            "zip does not appear to be a Hermes backup "
            "(no config.yaml, .env, or state databases found)"
        )

    return True, ""


def _detect_prefix(zf: zipfile.ZipFile) -> str:
    """Detect if the zip has a common directory prefix wrapping all entries.

    Some tools zip as `.hermes/config.yaml` instead of `config.yaml`.
    Returns the prefix to strip (empty string if none).
    """
    names = [n for n in zf.namelist() if not n.endswith("/")]
    if not names:
        return ""

    # Find common prefix
    parts_list = [Path(n).parts for n in names]

    # Check if all entries share a common first directory
    first_parts = {p[0] for p in parts_list if len(p) > 1}
    if len(first_parts) == 1:
        prefix = first_parts.pop()
        # Only strip if it looks like a hermes dir name
        if prefix in (".hermes", "hermes"):
            return prefix + "/"

    return ""


def run_import(args) -> None:
    """Restore a Maia backup or migrate an upstream Hermes export."""
    if getattr(args, "from_hermes_export", False):
        _run_hermes_export_migration(args)
        return

    zip_path = Path(args.zipfile).expanduser().resolve()

    if not zip_path.is_file():
        print(f"Error: File not found: {zip_path}")
        sys.exit(1)

    if not zipfile.is_zipfile(zip_path):
        if tarfile.is_tarfile(zip_path):
            print("Error: tar archives are supported only for guarded Hermes export migration.")
            print(f"Run: maia import {zip_path} --from-hermes-export")
            sys.exit(1)
        print(f"Error: Not a valid zip file: {zip_path}")
        sys.exit(1)

    hermes_root = get_default_hermes_root()

    with zipfile.ZipFile(zip_path, "r") as zf:
        # Validate
        ok, reason = _validate_backup_zip(zf)
        if not ok:
            print(f"Error: {reason}")
            sys.exit(1)

        prefix = _detect_prefix(zf)
        members = [n for n in zf.namelist() if not n.endswith("/")]
        file_count = len(members)

        print(f"Backup contains {file_count} files")
        print(f"Target: {display_hermes_home()}")

        if prefix:
            print(f"Detected archive prefix: {prefix!r} (will be stripped)")

        # Check for existing installation
        has_config = (hermes_root / "config.yaml").exists()
        has_env = (hermes_root / ".env").exists()

        if (has_config or has_env) and not args.force:
            print()
            print("Warning: Target directory already has Maia configuration.")
            print("Importing will overwrite existing files with backup contents.")
            print()
            try:
                answer = input("Continue? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.")
                sys.exit(1)
            if answer not in ("y", "yes"):
                print("Aborted.")
                return

        # Extract
        print(f"\nImporting {file_count} files ...")
        hermes_root.mkdir(parents=True, exist_ok=True)

        errors = []
        restored = 0
        t0 = time.monotonic()

        for member in members:
            # Strip prefix if detected
            if prefix and member.startswith(prefix):
                rel = member[len(prefix):]
            else:
                rel = member

            if not rel:
                continue

            target = hermes_root / rel

            # Security: reject absolute paths and traversals
            try:
                target.resolve().relative_to(hermes_root.resolve())
            except ValueError:
                errors.append(f"  {rel}: path traversal blocked")
                continue

            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                if target.name in _SECRET_FILE_NAMES:
                    os.chmod(target, 0o600)
                restored += 1
            except (PermissionError, OSError) as exc:
                errors.append(f"  {rel}: {exc}")

            if restored % 500 == 0:
                print(f"  {restored}/{file_count} files ...")

        elapsed = time.monotonic() - t0

        # Summary
        print()
        print(f"Import complete: {restored} files restored in {elapsed:.1f}s")
        print(f"  Target: {display_hermes_home()}")

        if errors:
            print(f"\n  Warnings ({len(errors)} files skipped):")
            for e in errors[:10]:
                print(e)
            if len(errors) > 10:
                print(f"  ... and {len(errors) - 10} more")

        # Post-import: restore profile wrapper scripts
        profiles_dir = hermes_root / "profiles"
        restored_profiles = []
        if profiles_dir.is_dir():
            try:
                from hermes_cli.profiles import (
                    create_wrapper_script, check_alias_collision,
                    _is_wrapper_dir_in_path, _get_wrapper_dir,
                )
                for entry in sorted(profiles_dir.iterdir()):
                    if not entry.is_dir():
                        continue
                    profile_name = entry.name
                    # Only create wrappers for directories with config
                    if not (entry / "config.yaml").exists() and not (entry / ".env").exists():
                        continue
                    collision = check_alias_collision(profile_name)
                    if collision:
                        print(f"  Skipped alias '{profile_name}': {collision}")
                        restored_profiles.append((profile_name, False))
                    else:
                        wrapper = create_wrapper_script(profile_name)
                        restored_profiles.append((profile_name, wrapper is not None))

                if restored_profiles:
                    created = [n for n, ok in restored_profiles if ok]
                    skipped = [n for n, ok in restored_profiles if not ok]
                    if created:
                        print(f"\n  Profile aliases restored: {', '.join(created)}")
                    if skipped:
                        print(f"  Profile aliases skipped:  {', '.join(skipped)}")
                    if not _is_wrapper_dir_in_path():
                        print(f"\n  Note: {_get_wrapper_dir()} is not in your PATH.")
                        print('  Add to your shell config (~/.bashrc or ~/.zshrc):')
                        print('    export PATH="$HOME/.local/bin:$PATH"')
            except ImportError:
                # hermes_cli.profiles might not be available (fresh install)
                if any(profiles_dir.iterdir()):
                    print(f"\n  Profiles detected but aliases could not be created.")
                    print("  Run: maia profile list  (after installing Maia)")

        # Guidance
        print()
        if not (hermes_root / "hermes-agent").is_dir():
            print("Note: The codebase was not included in the backup.")
            print("  If this is a fresh install, run: maia update")

        if restored_profiles:
            gw_profiles = [n for n, _ in restored_profiles]
            print("\nTo re-enable gateway services for profiles:")
            for pname in gw_profiles:
                print(f"  maia -p {pname} gateway install")

        print("Done. Your Maia configuration has been restored.")


# ---------------------------------------------------------------------------
# Quick state snapshots (used by /snapshot slash command and maia backup --quick)
# ---------------------------------------------------------------------------

# Critical state files to include in quick snapshots (relative to HERMES_HOME).
# Everything else is either regeneratable (logs, cache) or managed separately
# (skills, repo, sessions/).
#
# Entries may be individual files OR directories.  Directories are captured
# recursively; missing entries are silently skipped.  Pairing data lives in
# platform-specific JSON blobs outside state.db, so it's listed here explicitly
# — `hermes update` snapshots this set before pulling so approved-user lists
# are recoverable if anything goes wrong (issue #15733).
_QUICK_STATE_FILES = (
    "state.db",
    "config.yaml",
    ".env",
    "auth.json",
    "cron/jobs.json",
    "gateway_state.json",
    "channel_directory.json",
    "processes.json",
    # Pairing stores (generic + per-platform JSONs outside state.db)
    "pairing",                          # legacy location (gateway/pairing.py)
    "platforms/pairing",                # new location (gateway/pairing.py)
    "feishu_comment_pairing.json",      # Feishu comment subscription pairings
)

_QUICK_SNAPSHOTS_DIR = "state-snapshots"
_QUICK_DEFAULT_KEEP = 20


def _quick_snapshot_root(hermes_home: Optional[Path] = None) -> Path:
    home = hermes_home or get_hermes_home()
    return home / _QUICK_SNAPSHOTS_DIR


def create_quick_snapshot(
    label: Optional[str] = None,
    hermes_home: Optional[Path] = None,
) -> Optional[str]:
    """Create a quick state snapshot of critical files.

    Copies STATE_FILES to a timestamped directory under state-snapshots/.
    Auto-prunes old snapshots beyond the keep limit.

    Returns:
        Snapshot ID (timestamp-based), or None if no files found.
    """
    home = hermes_home or get_hermes_home()
    root = _quick_snapshot_root(home)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    snap_id = f"{ts}-{label}" if label else ts
    snap_dir = root / snap_id
    snap_dir.mkdir(parents=True, exist_ok=True)

    manifest: Dict[str, int] = {}  # rel_path -> file size

    for rel in _QUICK_STATE_FILES:
        src = home / rel
        if not src.exists():
            continue

        if src.is_dir():
            # Walk the directory and record each file individually in the
            # manifest so restore can treat them uniformly.  Empty dirs are
            # skipped (nothing to snapshot).
            for sub in src.rglob("*"):
                if not sub.is_file():
                    continue
                sub_rel = sub.relative_to(home).as_posix()
                dst = snap_dir / sub_rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(sub, dst)
                    manifest[sub_rel] = dst.stat().st_size
                except (OSError, PermissionError) as exc:
                    logger.warning("Could not snapshot %s: %s", sub_rel, exc)
            continue

        if not src.is_file():
            continue

        dst = snap_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        try:
            if src.suffix == ".db":
                if not _safe_copy_db(src, dst):
                    continue
            else:
                shutil.copy2(src, dst)
            manifest[rel] = dst.stat().st_size
        except (OSError, PermissionError) as exc:
            logger.warning("Could not snapshot %s: %s", rel, exc)

    if not manifest:
        shutil.rmtree(snap_dir, ignore_errors=True)
        return None

    # Write manifest
    meta = {
        "id": snap_id,
        "timestamp": ts,
        "label": label,
        "file_count": len(manifest),
        "total_size": sum(manifest.values()),
        "files": manifest,
    }
    with open(snap_dir / "manifest.json", "w") as f:
        json.dump(meta, f, indent=2)

    # Auto-prune
    _prune_quick_snapshots(root, keep=_QUICK_DEFAULT_KEEP)

    logger.info("State snapshot created: %s (%d files)", snap_id, len(manifest))
    return snap_id


def list_quick_snapshots(
    limit: int = 20,
    hermes_home: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """List existing quick state snapshots, most recent first."""
    root = _quick_snapshot_root(hermes_home)
    if not root.exists():
        return []

    results = []
    for d in sorted(root.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        manifest_path = d / "manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path) as f:
                    results.append(json.load(f))
            except (json.JSONDecodeError, OSError):
                results.append({"id": d.name, "file_count": 0, "total_size": 0})
        if len(results) >= limit:
            break

    return results


def restore_quick_snapshot(
    snapshot_id: str,
    hermes_home: Optional[Path] = None,
) -> bool:
    """Restore state from a quick snapshot.

    Overwrites current state files with the snapshot's copies.
    Returns True if at least one file was restored.
    """
    home = hermes_home or get_hermes_home()
    root = _quick_snapshot_root(home)
    snap_dir = root / snapshot_id

    if not snap_dir.is_dir():
        return False

    manifest_path = snap_dir / "manifest.json"
    if not manifest_path.exists():
        return False

    with open(manifest_path) as f:
        meta = json.load(f)

    restored = 0
    for rel in meta.get("files", {}):
        src = snap_dir / rel
        if not src.exists():
            continue

        dst = home / rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        try:
            if dst.suffix == ".db":
                # Atomic-ish replace for databases
                tmp = dst.parent / f".{dst.name}.snap_restore"
                shutil.copy2(src, tmp)
                dst.unlink(missing_ok=True)
                shutil.move(str(tmp), str(dst))
            else:
                shutil.copy2(src, dst)
            restored += 1
        except (OSError, PermissionError) as exc:
            logger.error("Failed to restore %s: %s", rel, exc)

    logger.info("Restored %d files from snapshot %s", restored, snapshot_id)
    return restored > 0


def _prune_quick_snapshots(root: Path, keep: int = _QUICK_DEFAULT_KEEP) -> int:
    """Remove oldest quick snapshots beyond the keep limit. Returns count deleted."""
    if not root.exists():
        return 0

    dirs = sorted(
        (d for d in root.iterdir() if d.is_dir()),
        key=lambda d: d.name,
        reverse=True,
    )

    deleted = 0
    for d in dirs[keep:]:
        try:
            shutil.rmtree(d)
            deleted += 1
        except OSError as exc:
            logger.warning("Failed to prune snapshot %s: %s", d.name, exc)

    return deleted


def prune_quick_snapshots(
    keep: int = _QUICK_DEFAULT_KEEP,
    hermes_home: Optional[Path] = None,
) -> int:
    """Manually prune quick snapshots. Returns count deleted."""
    return _prune_quick_snapshots(_quick_snapshot_root(hermes_home), keep=keep)


def run_quick_backup(args) -> None:
    """CLI entry point for hermes backup --quick."""
    label = getattr(args, "label", None)
    snap_id = create_quick_snapshot(label=label)
    if snap_id:
        print(f"State snapshot created: {snap_id}")
        snaps = list_quick_snapshots()
        print(f"  {len(snaps)} snapshot(s) stored in {display_hermes_home()}/state-snapshots/")
        print(f"  Restore with: /snapshot restore {snap_id}")
    else:
        print("No state files found to snapshot.")


# ---------------------------------------------------------------------------
# Shared full-zip backup helper
# ---------------------------------------------------------------------------

def _write_full_zip_backup(out_path: Path, hermes_root: Path) -> Optional[Path]:
    """Write a full zip snapshot of ``hermes_root`` to ``out_path``.

    Uses the same exclusion rules and SQLite safe-copy as :func:`run_backup`.
    Returns the output path on success, None on failure (nothing to back up,
    or write error — caller should surface the outcome but not raise).
    """
    files_to_add: list[tuple[Path, Path]] = []
    try:
        for dirpath, dirnames, filenames in os.walk(hermes_root, followlinks=False):
            dp = Path(dirpath)
            # Prune excluded directories in-place so os.walk doesn't descend
            dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIRS]

            for fname in filenames:
                fpath = dp / fname
                try:
                    rel = fpath.relative_to(hermes_root)
                except ValueError:
                    continue

                if _should_exclude(rel):
                    continue

                # Skip the output zip itself if it already exists inside root.
                try:
                    if fpath.resolve() == out_path.resolve():
                        continue
                except (OSError, ValueError):
                    pass

                files_to_add.append((fpath, rel))
    except OSError as exc:
        logger.warning("Full-zip backup: walk failed: %s", exc)
        return None

    if not files_to_add:
        return None

    try:
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for abs_path, rel_path in files_to_add:
                try:
                    if abs_path.suffix == ".db":
                        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                            tmp_db = Path(tmp.name)
                        try:
                            if _safe_copy_db(abs_path, tmp_db):
                                zf.write(tmp_db, arcname=str(rel_path))
                        finally:
                            tmp_db.unlink(missing_ok=True)
                    else:
                        zf.write(abs_path, arcname=str(rel_path))
                except (PermissionError, OSError, ValueError) as exc:
                    logger.debug("Skipping %s in zip backup: %s", rel_path, exc)
                    continue
    except OSError as exc:
        logger.warning("Full-zip backup: zip write failed: %s", exc)
        # Best-effort cleanup of partial file
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None

    return out_path


# ---------------------------------------------------------------------------
# Pre-update auto-backup
# ---------------------------------------------------------------------------

_PRE_UPDATE_BACKUPS_DIR = "backups"
_PRE_UPDATE_PREFIX = "pre-update-"
_PRE_UPDATE_DEFAULT_KEEP = 5


def _pre_update_backup_dir(hermes_home: Optional[Path] = None) -> Path:
    home = hermes_home or get_hermes_home()
    return home / _PRE_UPDATE_BACKUPS_DIR


def _prune_pre_update_backups(backup_dir: Path, keep: int) -> int:
    """Remove oldest pre-update backups beyond the keep limit.

    Returns the number of files deleted.  Only touches files matching
    ``pre-update-*.zip`` so hand-made zips dropped in the same directory
    are never touched.

    ``keep`` is floored to 1 because this helper is only called immediately
    after a fresh backup is written: deleting that backup right after the
    user paid the disk/CPU cost to create it would leave them worse off
    than no backup at all (and the wrapper in ``main.py`` would still print
    a misleading ``Saved: <path>`` line for a file that no longer exists).
    Operators who genuinely don't want a backup should set
    ``updates.pre_update_backup: false`` in config — that gates creation.
    """
    if keep < 1:
        keep = 1
    if not backup_dir.exists():
        return 0

    backups = sorted(
        (p for p in backup_dir.iterdir()
         if p.is_file() and p.name.startswith(_PRE_UPDATE_PREFIX) and p.suffix.lower() == ".zip"),
        key=lambda p: p.name,
        reverse=True,
    )

    deleted = 0
    for p in backups[keep:]:
        try:
            p.unlink()
            deleted += 1
        except OSError as exc:
            logger.warning("Failed to prune backup %s: %s", p.name, exc)

    return deleted


def create_pre_update_backup(
    hermes_home: Optional[Path] = None,
    keep: int = _PRE_UPDATE_DEFAULT_KEEP,
) -> Optional[Path]:
    """Create a full zip backup of HERMES_HOME under ``backups/``.

    Mirrors :func:`run_backup` (same exclusion rules, same SQLite safe-copy)
    but writes to ``<HERMES_HOME>/backups/pre-update-<timestamp>.zip`` and
    auto-prunes old pre-update backups.

    Returns the path to the created zip, or ``None`` if no files were
    found or the backup could not be created.  Never raises — the caller
    (``hermes update``) should continue even if the backup fails.
    """
    hermes_root = hermes_home or get_default_hermes_root()
    if not hermes_root.is_dir():
        return None

    backup_dir = _pre_update_backup_dir(hermes_root)
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Could not create pre-update backup dir %s: %s", backup_dir, exc)
        return None

    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out_path = backup_dir / f"{_PRE_UPDATE_PREFIX}{stamp}.zip"

    result = _write_full_zip_backup(out_path, hermes_root)
    if result is None:
        return None

    _prune_pre_update_backups(backup_dir, keep=keep)
    return out_path


# ---------------------------------------------------------------------------
# Pre-migration auto-backup (used by `maia claw migrate`)
# ---------------------------------------------------------------------------

_PRE_MIGRATION_PREFIX = "pre-migration-"
_PRE_MIGRATION_DEFAULT_KEEP = 5


def _prune_pre_migration_backups(backup_dir: Path, keep: int) -> int:
    """Remove oldest pre-migration backups beyond the keep limit.

    Only touches files matching ``pre-migration-*.zip`` so other backups in
    the same directory are never touched.
    """
    if keep < 0:
        keep = 0
    if not backup_dir.exists():
        return 0

    backups = sorted(
        (p for p in backup_dir.iterdir()
         if p.is_file() and p.name.startswith(_PRE_MIGRATION_PREFIX) and p.suffix.lower() == ".zip"),
        key=lambda p: p.name,
        reverse=True,
    )

    deleted = 0
    for p in backups[keep:]:
        try:
            p.unlink()
            deleted += 1
        except OSError as exc:
            logger.warning("Failed to prune pre-migration backup %s: %s", p.name, exc)

    return deleted


def create_pre_migration_backup(
    hermes_home: Optional[Path] = None,
    keep: int = _PRE_MIGRATION_DEFAULT_KEEP,
) -> Optional[Path]:
    """Create a full zip backup of HERMES_HOME under ``backups/`` before a
    ``maia claw migrate`` apply.

    Shares implementation with :func:`create_pre_update_backup` via
    ``_write_full_zip_backup`` — same exclusions, same SQLite safe-copy,
    restorable with ``maia import <archive>``.  Writes to
    ``<HERMES_HOME>/backups/pre-migration-<timestamp>.zip`` and auto-prunes
    old pre-migration backups.

    Returns the path to the created zip, or ``None`` if nothing was found
    to back up (fresh install) or the write failed.  Never raises — the
    caller decides whether to abort or proceed.
    """
    hermes_root = hermes_home or get_default_hermes_root()
    if not hermes_root.is_dir():
        return None

    # Reuses the shared backups/ directory so `maia import` and the
    # update-backup listing pick up pre-migration archives too.
    backup_dir = _pre_update_backup_dir(hermes_root)
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Could not create pre-migration backup dir %s: %s", backup_dir, exc)
        return None

    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out_path = backup_dir / f"{_PRE_MIGRATION_PREFIX}{stamp}.zip"

    result = _write_full_zip_backup(out_path, hermes_root)
    if result is None:
        return None

    _prune_pre_migration_backups(backup_dir, keep=keep)
    return out_path
