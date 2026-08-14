"""HTTP-level tests for the admin console: staff-only guard, invites,
password reset, and DB backup/restore."""
import io

from app.models import AuditLog, Invite

from conftest import login


def test_member_redirected_away_from_admin_routes(client, member_user):
    login(client, member_user)

    # GET /admin bounces an authenticated non-staff user to the dashboard.
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    # The action routes all bounce to /login instead (their guard doesn't
    # distinguish "no session" from "wrong role").
    for method, path, kwargs in [
        ("post", "/admin/backup", {}),
        ("get", "/admin/backup/download/holo-20260101-000000.db", {}),
        ("post", "/admin/restore/holo-20260101-000000.db", {}),
        ("post", "/admin/users/1/reset-password", {}),
        ("post", "/admin/invite", {"data": {"email": "x@test.local"}}),
        ("post", "/admin/invite/1/email", {}),
    ]:
        resp = getattr(client, method)(path, follow_redirects=False, **kwargs)
        assert resp.status_code == 303, f"{method} {path}"
        assert resp.headers["location"] == "/login", f"{method} {path}"


def test_anonymous_redirected_to_login(client):
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_admin_and_manager_can_reach_admin_console(client, admin_user, manager_user):
    login(client, admin_user)
    assert client.get("/admin", follow_redirects=False).status_code == 200

    login(client, manager_user)
    assert client.get("/admin", follow_redirects=False).status_code == 200


def test_create_invite_generates_register_link_and_audits(client, db_session, admin_user):
    login(client, admin_user)
    resp = client.post(
        "/admin/invite",
        data={"email": "new.person@test.local", "role": "member"},
        follow_redirects=False,
    )
    assert resp.status_code == 200  # renders admin home with the new link

    invite = db_session.query(Invite).filter(Invite.email == "new.person@test.local").first()
    assert invite is not None
    assert invite.role == "member"
    assert "/register?token=" + invite.token in resp.text

    entry = db_session.query(AuditLog).filter(AuditLog.action == "admin.invite_create").first()
    assert entry is not None
    assert entry.target_label == "new.person@test.local"


def test_create_invite_rejects_invalid_role_falls_back_to_member(client, db_session, admin_user):
    login(client, admin_user)
    client.post(
        "/admin/invite",
        data={"email": "sneaky@test.local", "role": "superuser"},
        follow_redirects=False,
    )
    invite = db_session.query(Invite).filter(Invite.email == "sneaky@test.local").first()
    assert invite.role == "member"


def test_reset_password_issues_temp_password_and_forces_change(client, db_session, admin_user,
                                                               member_user):
    login(client, admin_user)
    old_hash = member_user.password_hash

    resp = client.post(f"/admin/users/{member_user.id}/reset-password", follow_redirects=False)
    assert resp.status_code == 200
    assert member_user.email in resp.text

    db_session.refresh(member_user)
    assert member_user.password_hash != old_hash
    assert member_user.must_change_password is True

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "admin.password_reset")
        .first()
    )
    assert entry is not None
    assert entry.target_id == member_user.id


def test_reset_password_unknown_user_shows_error(client, admin_user):
    login(client, admin_user)
    resp = client.post("/admin/users/999999/reset-password", follow_redirects=False)
    assert resp.status_code == 200
    assert "User not found" in resp.text


def test_backup_now_creates_a_downloadable_backup(client, admin_user, backup_env):
    login(client, admin_user)
    resp = client.post("/admin/backup", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/admin?ok=1")

    from app import backup as backup_module
    entries = backup_module.list_backups()
    assert len(entries) == 1
    name = entries[0]["name"]

    dl = client.get(f"/admin/backup/download/{name}", follow_redirects=False)
    assert dl.status_code == 200
    assert dl.content  # non-empty file body


def test_download_backup_rejects_unknown_name(client, admin_user, backup_env):
    login(client, admin_user)
    resp = client.get("/admin/backup/download/../../etc/passwd", follow_redirects=False)
    assert resp.status_code in (303, 404)  # never serves an arbitrary path


def test_restore_upload_rejects_invalid_file(client, admin_user, backup_env):
    login(client, admin_user)
    resp = client.post(
        "/admin/restore",
        files={"file": ("bad.db", io.BytesIO(b"not a database"), "application/octet-stream")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/admin?ok=0")


def test_restore_upload_accepts_valid_backup(client, admin_user, backup_env):
    from app import backup as backup_module
    snapshot_path = backup_module.make_backup()
    with open(snapshot_path, "rb") as fh:
        data = fh.read()

    login(client, admin_user)
    resp = client.post(
        "/admin/restore",
        files={"file": ("holo-snapshot.db", io.BytesIO(data), "application/octet-stream")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/admin?ok=1")


def test_email_invite_requires_mail_config(client, db_session, admin_user):
    login(client, admin_user)
    client.post("/admin/invite", data={"email": "invitee@test.local"}, follow_redirects=False)
    invite = db_session.query(Invite).filter_by(email="invitee@test.local").first()

    resp = client.post(f"/admin/invite/{invite.id}/email", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/admin?ok=0")  # no mail forwarder configured


def test_email_invite_success(client, db_session, admin_user, fake_smtp):
    from app.models import MailConfig
    cfg = db_session.get(MailConfig, 1)
    cfg.host, cfg.mail_from = "smtp.example.com", "holo@example.com"
    db_session.add(cfg)
    db_session.commit()

    login(client, admin_user)
    client.post("/admin/invite", data={"email": "invitee2@test.local"}, follow_redirects=False)
    invite = db_session.query(Invite).filter_by(email="invitee2@test.local").first()

    resp = client.post(f"/admin/invite/{invite.id}/email", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/admin?ok=1")
    assert len(fake_smtp.sent) == 1
    assert fake_smtp.sent[0]["To"] == "invitee2@test.local"


def test_email_invite_unknown_invite(client, admin_user):
    login(client, admin_user)
    resp = client.post("/admin/invite/999999/email", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/admin?ok=0")
