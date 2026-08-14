"""HTTP-level tests for login, logout, invite-based registration, and the
forced-password-change enforcement middleware."""
from datetime import datetime, timedelta

from app.models import AuditLog, Invite, ROLE_MEMBER, User

from conftest import DEFAULT_PASSWORD, login, make_user


def test_login_page_renders(client):
    resp = client.get("/login")
    assert resp.status_code == 200


def test_successful_login_redirects_to_dashboard(client, member_user):
    resp = login(client, member_user)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_failed_login_returns_401_and_audits(client, db_session, member_user):
    resp = client.post(
        "/login",
        data={"email": member_user.email, "password": "wrong-password"},
        follow_redirects=False,
    )
    assert resp.status_code == 401

    failure = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "auth.login_failed")
        .first()
    )
    assert failure is not None
    assert failure.target_label == member_user.email
    assert failure.user_id is None


def test_login_unknown_user_returns_401(client):
    resp = client.post(
        "/login",
        data={"email": "nobody@test.local", "password": "whatever123"},
        follow_redirects=False,
    )
    assert resp.status_code == 401


def test_logout_clears_session(client, member_user):
    login(client, member_user)
    resp = client.post("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"

    # Session is gone: dashboard now bounces to /login.
    dash = client.get("/", follow_redirects=False)
    assert dash.status_code == 303
    assert dash.headers["location"] == "/login"


def test_must_change_password_redirects_everywhere_but_allowed_paths(client, db_session):
    user = make_user(db_session, email="mustchange@test.local", must_change_password=True)
    login(client, user)

    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/account/password"

    # The password-change page itself and logout stay reachable.
    assert client.get("/account/password", follow_redirects=False).status_code == 200


def test_change_password_clears_flag_and_unblocks_navigation(client, db_session):
    user = make_user(db_session, email="mustchange2@test.local", must_change_password=True)
    login(client, user)

    resp = client.post(
        "/account/password",
        data={
            "current_password": DEFAULT_PASSWORD,
            "new_password": "brand-new-password",
            "confirm_password": "brand-new-password",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    db_session.refresh(user)
    assert user.must_change_password is False

    # Dashboard is reachable now (no more forced redirect).
    assert client.get("/", follow_redirects=False).status_code == 200


def test_change_password_rejects_wrong_current_password(client, member_user):
    login(client, member_user)
    resp = client.post(
        "/account/password",
        data={
            "current_password": "totally-wrong",
            "new_password": "brand-new-password",
            "confirm_password": "brand-new-password",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_change_password_rejects_short_new_password(client, member_user):
    login(client, member_user)
    resp = client.post(
        "/account/password",
        data={
            "current_password": DEFAULT_PASSWORD,
            "new_password": "short",
            "confirm_password": "short",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_register_with_valid_invite_creates_user(client, db_session):
    invite = Invite(
        email="new.hire@test.local",
        role=ROLE_MEMBER,
        token="valid-token-123",
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db_session.add(invite)
    db_session.commit()

    resp = client.post(
        "/register",
        data={"token": "valid-token-123", "password": "a-fresh-password"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    created = db_session.query(User).filter(User.email == "new.hire@test.local").first()
    assert created is not None
    assert created.role == ROLE_MEMBER

    db_session.refresh(invite)
    assert invite.used_at is not None


def test_register_with_expired_invite_rejected(client, db_session):
    invite = Invite(
        email="late.hire@test.local",
        role=ROLE_MEMBER,
        token="expired-token",
        expires_at=datetime.utcnow() - timedelta(days=1),
    )
    db_session.add(invite)
    db_session.commit()

    resp = client.post(
        "/register",
        data={"token": "expired-token", "password": "a-fresh-password"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert db_session.query(User).filter(User.email == "late.hire@test.local").first() is None


def test_register_with_used_invite_rejected(client, db_session):
    invite = Invite(
        email="reused@test.local",
        role=ROLE_MEMBER,
        token="reused-token",
        expires_at=datetime.utcnow() + timedelta(days=7),
        used_at=datetime.utcnow(),
    )
    db_session.add(invite)
    db_session.commit()

    resp = client.post(
        "/register",
        data={"token": "reused-token", "password": "a-fresh-password"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_register_rejects_short_password(client, db_session):
    invite = Invite(
        email="short.pw@test.local",
        role=ROLE_MEMBER,
        token="short-pw-token",
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db_session.add(invite)
    db_session.commit()

    resp = client.post(
        "/register",
        data={"token": "short-pw-token", "password": "short"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert db_session.query(User).filter(User.email == "short.pw@test.local").first() is None
