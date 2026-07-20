"""Regression: V4A directives with NO space after `***` (e.g. `***Update File:`)
must still go through the governance write-access pre-check.

The authoritative parser (``tools/patch_parser.py``) accepts the no-space form, so
``patch_tool``'s pre-check must gate it too — otherwise the write is applied while the
governance / approval / sensitive-path guards are silently skipped. Before the fix,
``patch_tool`` extracted paths with a stricter ``\\s+`` regex than the parser's ``\\s*``,
so a no-space directive was invisible to the pre-check but fully applied.
"""


def test_no_space_update_directive_is_governance_checked(monkeypatch):
    import tools.file_tools as ft

    checked: list[tuple[str, str]] = []

    def fake_file_access_error(path, operation):
        checked.append((str(path), operation))
        if "governed" in str(path):
            return "Access denied by governance (test)."
        return None

    monkeypatch.setattr(ft, "file_access_error", fake_file_access_error)

    patch_body = (
        "*** Begin Patch\n"
        "***Update File: reports/governed.md\n"  # no space after ***
        "@@\n"
        "-old\n"
        "+new\n"
        "*** End Patch\n"
    )
    result = ft.patch_tool(mode="patch", patch=patch_body, task_id="default")

    checked_paths = [p for p, _ in checked]
    assert any("governed" in p for p in checked_paths), (
        f"no-space Update directive skipped the governance pre-check; checked={checked_paths}"
    )
    assert all(op == "write" for _, op in checked)
    assert "denied" in result.lower()


def test_no_space_move_directive_checks_both_paths(monkeypatch):
    import tools.file_tools as ft

    checked: list[str] = []

    def fake_file_access_error(path, operation):
        checked.append(str(path))
        if "exfil" in str(path):
            return "Access denied by governance (test)."
        return None

    monkeypatch.setattr(ft, "file_access_error", fake_file_access_error)

    patch_body = (
        "*** Begin Patch\n"
        "***Move File: reports/q3.md -> /tmp/exfil.md\n"  # no space after ***
        "*** End Patch\n"
    )
    result = ft.patch_tool(mode="patch", patch=patch_body, task_id="default")

    assert any("exfil" in p for p in checked), f"move destination not checked; {checked}"
    assert any("q3.md" in p for p in checked), f"move source not checked; {checked}"
    assert "denied" in result.lower()
