"""A cron job must run under the SCHEDULING user's governance identity, not
the local/service account — otherwise a low-privilege user could schedule a
job that later touches folders their own role forbids.

Covers: origin capture records user_id/user_name at create time, and the
run-time session-var setup makes current_actor() resolve to that user.
"""


def test_origin_captures_scheduling_user_identity():
    from gateway.session_context import set_session_vars, clear_session_vars
    from tools.cronjob_tools import _origin_from_env

    tokens = set_session_vars(
        platform="slack", chat_id="C1", chat_name="ops",
        user_id="U123", user_name="Ana",
    )
    try:
        origin = _origin_from_env()
    finally:
        clear_session_vars(tokens)

    assert origin is not None
    assert origin["user_id"] == "U123"
    assert origin["user_name"] == "Ana"


def test_run_time_actor_resolves_to_scheduling_user():
    """Re-establishing the stored origin at run time makes current_actor()
    (which governance uses) resolve to the scheduling user."""
    from gateway.session_context import set_session_vars, clear_session_vars
    from agent.governance import current_actor

    origin = {"platform": "slack", "chat_id": "C1",
              "user_id": "U123", "user_name": "Ana"}
    tokens = set_session_vars(
        platform=origin["platform"],
        chat_id=origin["chat_id"],
        user_id=str(origin.get("user_id") or ""),
        user_name=str(origin.get("user_name") or ""),
    )
    try:
        actor = current_actor()
    finally:
        clear_session_vars(tokens)

    assert actor.platform == "slack"
    assert actor.user_id == "U123"


def test_local_job_without_user_id_stays_local():
    """A job with no captured user (local/CLI-created) resolves to the local
    actor — unchanged behavior, no regression."""
    from gateway.session_context import set_session_vars, clear_session_vars
    from agent.governance import current_actor

    tokens = set_session_vars(platform="", chat_id="", user_id="", user_name="")
    try:
        actor = current_actor()
    finally:
        clear_session_vars(tokens)

    assert actor.platform == "local"
    assert not actor.user_id
