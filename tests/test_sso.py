"""Single sign-on hand-off FROM FOCUS: token verification, account matching,
and the forced-password-change interaction."""
from itsdangerous import URLSafeTimedSerializer

from app import config
from app.models import AuditLog, ROLE_MEMBER

from conftest import login, make_user


def _token_for(email: str, secret: str = "shared-test-secret") -> str:
    serializer = URLSafeTimedSerializer(secret, salt=config.SSO_SALT)
    return serializer.dumps({"email": email})


def test_sso_disabled_without_shared_secret(client, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "")
    resp = client.get("/sso/focus?token=whatever", follow_redirects=False)
    assert resp.status_code == 303
    from urllib.parse import unquote
    location = unquote(resp.headers["location"])
    assert location.startswith("/login?error=")
    assert "not enabled" in location


def test_sso_logs_in_matching_user(client, db_session, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "shared-test-secret")
    user = make_user(db_session, email="matched@test.local", role=ROLE_MEMBER)

    token = _token_for("matched@test.local")
    resp = client.get(f"/sso/focus?token={token}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    # The session is really established — a follow-up request works as that user.
    resp2 = client.get("/", follow_redirects=False)
    assert resp2.status_code == 200

    entry = db_session.query(AuditLog).filter(AuditLog.action == "sso.login_from_focus").first()
    assert entry is not None
    assert entry.user_id == user.id
    assert entry.user_email == user.email


def test_sso_rejects_unknown_email(client, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "shared-test-secret")
    token = _token_for("nobody-here@test.local")
    resp = client.get(f"/sso/focus?token={token}", follow_redirects=False)
    assert resp.status_code == 303
    from urllib.parse import unquote
    location = unquote(resp.headers["location"])
    assert location.startswith("/login?error=")
    assert "No HOLO account" in location


def test_sso_rejects_wrong_secret(client, db_session, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "correct-secret")
    make_user(db_session, email="matched2@test.local", role=ROLE_MEMBER)

    token = _token_for("matched2@test.local", secret="wrong-secret")
    resp = client.get(f"/sso/focus?token={token}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login?error=")
    assert "Invalid" in resp.headers["location"]


def test_sso_rejects_missing_token(client, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "shared-test-secret")
    resp = client.get("/sso/focus", follow_redirects=False)
    assert resp.status_code == 303
    assert "Missing" in resp.headers["location"]


def test_sso_bypasses_forced_password_change_of_a_stale_session(client, db_session,
                                                                  monkeypatch):
    """A user forced to change their HOLO password is currently logged in;
    a fresh SSO hand-off for a *different* user must still be able to swap
    the session, rather than getting trapped on /account/password first."""
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "shared-test-secret")
    stale_user = make_user(db_session, email="stale@test.local", role=ROLE_MEMBER,
                           must_change_password=True)
    login(client, stale_user)

    make_user(db_session, email="fresh@test.local", role=ROLE_MEMBER)
    token = _token_for("fresh@test.local")
    resp = client.get(f"/sso/focus?token={token}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    # Confirm we're now the fresh (non-flagged) user, not stuck on password change.
    resp2 = client.get("/", follow_redirects=False)
    assert resp2.status_code == 200


def test_go_focus_redirects_with_valid_token(client, member_user, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "shared-test-secret")
    monkeypatch.setattr(config, "FOCUS_BASE_URL", "http://localhost:9094")
    login(client, member_user)

    resp = client.get("/go/focus", follow_redirects=False)
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("http://localhost:9094/sso/holo?token=")

    token = location.split("token=", 1)[1]
    serializer = URLSafeTimedSerializer("shared-test-secret", salt=config.SSO_SALT)
    payload = serializer.loads(token, max_age=config.SSO_TOKEN_MAX_AGE)
    assert payload["email"] == member_user.email


def test_go_focus_requires_login(client):
    resp = client.get("/go/focus", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_go_focus_disabled_redirects_home_when_no_secret(client, member_user, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "")
    login(client, member_user)
    resp = client.get("/go/focus", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_focus_button_hidden_when_sso_not_configured(client, member_user, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "")
    login(client, member_user)
    resp = client.get("/")
    assert "focus-link" not in resp.text
    assert "/go/focus" not in resp.text


def test_focus_button_shown_when_sso_configured(client, member_user, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "shared-test-secret")
    login(client, member_user)
    resp = client.get("/")
    assert "focus-link" in resp.text
    assert "/go/focus" in resp.text
