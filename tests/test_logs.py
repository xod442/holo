"""HTTP-level tests for /admin/log: the System Log — staff guard, filtering,
and pagination."""
from app import audit
from app.models import AuditLog

from conftest import login


def _seed_entries(db_session, count: int, *, action="lab.create", user_email="seed@test.local"):
    for i in range(count):
        db_session.add(AuditLog(action=action, user_email=user_email,
                                target_label=f"item-{i}"))
    db_session.commit()


def test_member_redirected_to_dashboard(client, member_user):
    login(client, member_user)
    resp = client.get("/admin/log", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_anonymous_redirected_to_login(client):
    resp = client.get("/admin/log", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_staff_can_view_log(client, db_session, admin_user):
    _seed_entries(db_session, 3)
    login(client, admin_user)
    resp = client.get("/admin/log", follow_redirects=False)
    assert resp.status_code == 200
    assert "seed@test.local" in resp.text


def test_filter_by_action(client, db_session, admin_user):
    _seed_entries(db_session, 2, action="lab.create")
    _seed_entries(db_session, 3, action="phase.approve")
    login(client, admin_user)

    resp = client.get("/admin/log", params={"action": "phase.approve"}, follow_redirects=False)
    assert resp.status_code == 200
    # Only the matching-action rows render; the other action's label doesn't leak in.
    assert resp.text.count("item-") == 3


def test_filter_by_user_email(client, db_session, admin_user):
    _seed_entries(db_session, 2, user_email="alice@test.local")
    _seed_entries(db_session, 4, user_email="bob@test.local")
    login(client, admin_user)

    resp = client.get("/admin/log", params={"user_email": "alice@test.local"},
                      follow_redirects=False)
    assert resp.status_code == 200
    assert resp.text.count("item-") == 2


def test_pagination_clamps_page_number(client, db_session, admin_user):
    _seed_entries(db_session, 5)
    login(client, admin_user)

    # Way beyond the last page — should clamp to the last valid page, not 404/error.
    resp = client.get("/admin/log", params={"page": "999"}, follow_redirects=False)
    assert resp.status_code == 200

    resp = client.get("/admin/log", params={"page": "0"}, follow_redirects=False)
    assert resp.status_code == 200


def test_audit_log_entries_created_by_real_actions_are_visible(client, db_session, admin_user,
                                                               member_user):
    login(client, member_user)
    audit.log(db_session, member_user, "auth.login", target_type="user",
              target_id=member_user.id, target_label=member_user.email)

    login(client, admin_user)
    resp = client.get("/admin/log", follow_redirects=False)
    assert resp.status_code == 200
    assert member_user.email in resp.text
