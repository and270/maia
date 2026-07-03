"""Regression: V4A `Move File:` directives must go through the governance
write-access pre-check for BOTH source and destination.

Before the fix, patch_tool's path-extraction regex only matched
Update/Add/Delete directives, so `*** Move File: governed -> /tmp/exfil`
skipped the governance check entirely.
"""

from unittest.mock import patch


def test_move_file_checks_both_paths_for_write_access(monkeypatch):
    import tools.file_tools as ft

    checked: list[tuple[str, str]] = []

    def fake_file_access_error(path, operation):
        checked.append((str(path), operation))
        # Deny the destination to prove the guard actually blocks the move.
        if "exfil" in str(path):
            return "Access denied by governance (test)."
        return None

    monkeypatch.setattr(ft, "file_access_error", fake_file_access_error)

    patch_body = (
        "*** Begin Patch\n"
        "*** Move File: reports/q3.md -> /tmp/exfil.md\n"
        "*** End Patch\n"
    )
    result = ft.patch_tool(mode="patch", patch=patch_body, task_id="default")

    # The destination was governance-checked and the move was blocked.
    checked_paths = [p for p, _ in checked]
    assert any("exfil" in p for p in checked_paths), (
        f"destination not governance-checked; checked={checked_paths}"
    )
    assert any("q3.md" in p for p in checked_paths), (
        f"source not governance-checked; checked={checked_paths}"
    )
    assert all(op == "write" for _, op in checked)
    assert "denied" in result.lower()
