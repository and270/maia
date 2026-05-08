"""Dashboard authentication and network binding tests."""

from __future__ import annotations

import sys
import types

import pytest
import yaml


def _write_config(config: dict) -> None:
    from hermes_constants import get_hermes_home

    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")


def _client(monkeypatch):
    from fastapi.testclient import TestClient
    from hermes_cli import web_server

    web_server._DASHBOARD_AUTH_SESSIONS.clear()
    if hasattr(web_server.app.state, "bound_host"):
        del web_server.app.state.bound_host
    monkeypatch.delenv("COORPORATE_DASHBOARD_TOKEN", raising=False)
    return TestClient(web_server.app), web_server


def test_protected_dashboard_login_issues_role_session(monkeypatch, _isolate_hermes_home):
    client, web_server = _client(monkeypatch)
    monkeypatch.setenv("COORPORATE_DASHBOARD_TOKEN", "test-dashboard-token-12345")
    _write_config(
        {
            "dashboard": {
                "auth": {
                    "enabled": True,
                    "token_env": "COORPORATE_DASHBOARD_TOKEN",
                    "local_token_roles": ["admin"],
                },
            },
        },
    )

    status = client.get("/api/dashboard/auth/status").json()
    assert status["auth_required"] is True
    assert status["authenticated"] is False

    assert client.get("/api/config").status_code == 401
    assert client.post("/api/dashboard/auth/login", json={"token": "wrong"}).status_code == 401

    login = client.post(
        "/api/dashboard/auth/login",
        json={"token": "test-dashboard-token-12345"},
    )
    assert login.status_code == 200
    session_token = login.json()["token"]
    assert "admin" in login.json()["roles"]

    resp = client.get(
        "/api/config",
        headers={web_server._SESSION_HEADER_NAME: session_token},
    )
    assert resp.status_code == 200


def test_dashboard_read_role_cannot_mutate_config(monkeypatch, _isolate_hermes_home):
    client, web_server = _client(monkeypatch)
    monkeypatch.setenv("COORPORATE_DASHBOARD_TOKEN", "test-dashboard-token-12345")
    _write_config(
        {
            "dashboard": {
                "auth": {
                    "enabled": True,
                    "token_env": "COORPORATE_DASHBOARD_TOKEN",
                    "local_token_roles": ["auditor"],
                    "read_roles": ["auditor", "manager", "admin"],
                    "manage_roles": ["manager", "admin"],
                    "admin_roles": ["admin"],
                },
            },
        },
    )

    login = client.post(
        "/api/dashboard/auth/login",
        json={"token": "test-dashboard-token-12345"},
    )
    assert login.status_code == 200
    session_token = login.json()["token"]

    headers = {web_server._SESSION_HEADER_NAME: session_token}
    assert client.get("/api/config", headers=headers).status_code == 200
    denied = client.put("/api/config", json={"config": {}}, headers=headers)
    assert denied.status_code == 403


def test_channel_dashboard_token_logs_in_mapped_user(monkeypatch, _isolate_hermes_home):
    client, web_server = _client(monkeypatch)
    _write_config(
        {
            "dashboard": {
                "auth": {
                    "enabled": True,
                    "channel_tokens": {"enabled": True, "ttl_minutes": 10},
                    "read_roles": ["auditor", "manager", "admin"],
                    "manage_roles": ["manager", "admin"],
                    "admin_roles": ["admin"],
                },
            },
            "governance": {
                "enabled": True,
                "role_hierarchy": ["viewer", "operator", "manager", "admin"],
                "users": {
                    "discord:99887766": {
                        "name": "Marketing Lead",
                        "roles": ["manager"],
                        "teams": ["marketing"],
                    }
                },
            },
        },
    )

    from agent.governance import Actor
    from hermes_cli.dashboard_tokens import issue_channel_dashboard_token

    token = issue_channel_dashboard_token(
        actor=Actor(platform="discord", user_id="99887766", user_name="Marketing Lead"),
        roles=["manager"],
        ttl_seconds=600,
    )

    login = client.post("/api/dashboard/auth/login", json={"token": token})
    assert login.status_code == 200
    payload = login.json()
    assert payload["source"] == "channel_token"
    assert payload["actor"]["id"] == "discord:99887766"
    assert "manager" in payload["roles"]

    session_token = payload["token"]
    headers = {web_server._SESSION_HEADER_NAME: session_token}
    assert client.get("/api/governance/folder-policies", headers=headers).status_code == 200

    reused = client.post("/api/dashboard/auth/login", json={"token": token})
    assert reused.status_code == 401


def test_dashboard_access_request_approval_and_revocation(monkeypatch, _isolate_hermes_home):
    client, web_server = _client(monkeypatch)
    monkeypatch.setenv("COORPORATE_DASHBOARD_TOKEN", "test-dashboard-token-12345")
    _write_config(
        {
            "dashboard": {
                "auth": {
                    "enabled": True,
                    "token_env": "COORPORATE_DASHBOARD_TOKEN",
                    "local_token_roles": ["admin"],
                    "channel_tokens": {
                        "enabled": True,
                        "ttl_minutes": 10,
                        "approval_required": True,
                    },
                    "read_roles": ["auditor", "manager", "admin"],
                    "manage_roles": ["manager", "admin"],
                    "admin_roles": ["admin"],
                },
            },
            "governance": {
                "enabled": True,
                "role_hierarchy": ["viewer", "operator", "manager", "admin"],
                "users": {},
            },
        },
    )

    admin_login = client.post(
        "/api/dashboard/auth/login",
        json={"token": "test-dashboard-token-12345"},
    )
    assert admin_login.status_code == 200
    admin_headers = {web_server._SESSION_HEADER_NAME: admin_login.json()["token"]}

    from agent.governance import Actor
    from hermes_cli.dashboard_tokens import (
        issue_channel_dashboard_token,
        request_dashboard_access,
    )

    actor = Actor(platform="discord", user_id="99887766", user_name="Marketing Lead")
    access_request, created = request_dashboard_access(actor=actor)
    assert created is True

    listing = client.get("/api/dashboard/access/requests", headers=admin_headers)
    assert listing.status_code == 200
    assert listing.json()["requests"][0]["status"] == "pending"

    approval = client.post(
        f"/api/dashboard/access/requests/{access_request['id']}/approve",
        json={
            "name": "Marketing Lead",
            "roles": ["manager"],
            "teams": ["marketing"],
        },
        headers=admin_headers,
    )
    assert approval.status_code == 200

    from hermes_constants import get_hermes_home

    saved = yaml.safe_load((get_hermes_home() / "config.yaml").read_text(encoding="utf-8"))
    user = saved["governance"]["users"]["discord:99887766"]
    assert user["roles"] == ["manager"]
    assert user["teams"] == ["marketing"]

    token = issue_channel_dashboard_token(actor=actor, roles=["manager"], ttl_seconds=600)
    channel_login = client.post("/api/dashboard/auth/login", json={"token": token})
    assert channel_login.status_code == 200
    channel_headers = {web_server._SESSION_HEADER_NAME: channel_login.json()["token"]}
    assert client.get("/api/governance/folder-policies", headers=channel_headers).status_code == 200

    revoke = client.post(
        "/api/dashboard/access/revoke",
        json={"actor_key": "discord:99887766", "reason": "role changed"},
        headers=admin_headers,
    )
    assert revoke.status_code == 200
    assert revoke.json()["dropped_sessions"] >= 1
    assert client.get("/api/governance/folder-policies", headers=channel_headers).status_code == 401

    blocked_token = issue_channel_dashboard_token(actor=actor, roles=["manager"], ttl_seconds=600)
    assert client.post("/api/dashboard/auth/login", json={"token": blocked_token}).status_code == 401

    restore = client.post(
        "/api/dashboard/access/restore",
        json={"actor_key": "discord:99887766"},
        headers=admin_headers,
    )
    assert restore.status_code == 200
    restored_listing = client.get("/api/dashboard/access/requests", headers=admin_headers)
    restored_request = next(
        item
        for item in restored_listing.json()["requests"]
        if item["actor_key"] == "discord:99887766"
    )
    assert restored_request["status"] == "approved"
    restored_token = issue_channel_dashboard_token(actor=actor, roles=["manager"], ttl_seconds=600)
    assert client.post("/api/dashboard/auth/login", json={"token": restored_token}).status_code == 200


def test_non_loopback_bind_refuses_without_dashboard_auth(monkeypatch, _isolate_hermes_home):
    _, web_server = _client(monkeypatch)
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        types.SimpleNamespace(run=lambda *args, **kwargs: None),
    )
    _write_config({"dashboard": {"auth": {"enabled": False}}})

    with pytest.raises(SystemExit) as exc:
        web_server.start_server(host="0.0.0.0", port=9119, open_browser=False)

    assert "Enable dashboard.auth" in str(exc.value)


def test_non_loopback_bind_allows_configured_dashboard_auth(monkeypatch, _isolate_hermes_home):
    _, web_server = _client(monkeypatch)
    calls: list[dict] = []
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        types.SimpleNamespace(run=lambda app, **kwargs: calls.append(kwargs)),
    )
    monkeypatch.setenv("COORPORATE_DASHBOARD_TOKEN", "test-dashboard-token-12345")
    _write_config(
        {
            "dashboard": {
                "auth": {
                    "enabled": True,
                    "token_env": "COORPORATE_DASHBOARD_TOKEN",
                },
            },
        },
    )

    web_server.start_server(host="0.0.0.0", port=9123, open_browser=False)

    assert calls == [{"host": "0.0.0.0", "port": 9123, "log_level": "warning"}]


def test_non_loopback_bind_allows_channel_dashboard_tokens(monkeypatch, _isolate_hermes_home):
    _, web_server = _client(monkeypatch)
    calls: list[dict] = []
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        types.SimpleNamespace(run=lambda app, **kwargs: calls.append(kwargs)),
    )
    _write_config(
        {
            "dashboard": {
                "auth": {
                    "enabled": True,
                    "channel_tokens": {"enabled": True},
                },
            },
        },
    )

    web_server.start_server(host="0.0.0.0", port=9124, open_browser=False)

    assert calls == [{"host": "0.0.0.0", "port": 9124, "log_level": "warning"}]
