"""GitHub contact settings, permissions, validation, and backup persistence."""
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import backup, db
from app.models import AuditLog, GitHubManager, User
from conftest import login


@pytest.mark.parametrize("role_fixture", ["admin_user", "manager_user"])
def test_staff_can_save_and_edit_list(client, db_session, request, role_fixture):
    user = request.getfixturevalue(role_fixture)
    login(client, user)
    before_users = db_session.query(User).count()
    response = client.post(
        "/admin/github-managers",
        data={"emails": " FIRST@Example.com \r\nsecond@example.com; first@example.com,third@example.com\n"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("#github-managers")
    managers = db_session.query(GitHubManager).order_by(GitHubManager.email).all()
    assert [manager.email for manager in managers] == [
        "first@example.com", "second@example.com", "third@example.com",
    ]
    retained_id = managers[0].id
    assert db_session.query(User).count() == before_users
    entry = db_session.query(AuditLog).filter_by(action="admin.github_managers_save").one()
    assert entry.user_id == user.id
    assert entry.details == "count=3"

    page = client.get("/admin")
    assert "GitHub managers" in page.text
    assert "first@example.com\nsecond@example.com\nthird@example.com" in page.text
    client.post("/admin/github-managers", data={"emails": "first@example.com\nnew@example.com"})
    managers = db_session.query(GitHubManager).order_by(GitHubManager.email).all()
    assert [manager.email for manager in managers] == ["first@example.com", "new@example.com"]
    assert managers[0].id == retained_id

    client.post("/admin/github-managers", data={"emails": ""})
    assert db_session.query(GitHubManager).count() == 0
    assert "GitHub manager email addresses" in client.get("/admin").text


@pytest.mark.parametrize("invalid", [
    "not-an-email", "a@@example.com", "a@localhost", "a@-example.com",
    ".a@example.com", "a..b@example.com", "Name <a@example.com>",
    "a@example.com b@example.com", "a@" + "x" * 64 + ".com",
    "x" * 65 + "@example.com", "</textarea><script>alert(1)</script>",
])
def test_invalid_list_retains_input_without_changing_saved_contacts(
    client, db_session, admin_user, invalid,
):
    login(client, admin_user)
    db_session.add(GitHubManager(email="saved@example.com"))
    db_session.commit()
    response = client.post(
        "/admin/github-managers",
        data={"emails": f"valid@example.com\n{invalid}"},
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert "Invalid email address" in response.text
    assert "valid@example.com" in response.text
    assert "<script>alert(1)</script>" not in response.text
    assert [manager.email for manager in db_session.query(GitHubManager)] == ["saved@example.com"]
    assert db_session.query(AuditLog).filter_by(action="admin.github_managers_save").count() == 0


@pytest.mark.parametrize("signed_in", [False, True])
def test_anonymous_and_members_cannot_modify_list(client, db_session, member_user, signed_in):
    if signed_in:
        login(client, member_user)
    response = client.post(
        "/admin/github-managers", data={"emails": "blocked@example.com"}, follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert db_session.query(GitHubManager).count() == 0


def test_contacts_survive_backup_restore(backup_env):
    with Session(db.engine) as session:
        session.add(GitHubManager(email="saved@example.com"))
        session.commit()
    snapshot = backup.make_backup()
    with Session(db.engine) as session:
        session.query(GitHubManager).delete()
        session.commit()
    backup.restore_from(snapshot)
    with Session(db.engine) as session:
        assert [manager.email for manager in session.query(GitHubManager)] == ["saved@example.com"]


def test_restoring_old_backup_creates_empty_contact_table(backup_env):
    with db.engine.begin() as conn:
        conn.execute(text("DROP TABLE github_managers"))
    snapshot = backup.make_backup()
    backup.restore_from(snapshot)
    with Session(db.engine) as session:
        assert session.query(GitHubManager).count() == 0
