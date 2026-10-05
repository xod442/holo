"""Repository requests on saved Dev 3 checkboxes (no real email)."""
import pytest
from datetime import datetime
from sqlalchemy.orm import Session

from app import backup, db, lab_service, notifier
from app.models import AuditLog, GitHubManager, Lab, MailConfig
from conftest import FakeSMTP, login


@pytest.fixture()
def request_lab(db_session, member_user, fake_smtp):
    lab = lab_service.create_lab(db_session, name="Automation HOL", owner_id=member_user.id)
    cfg = db_session.get(MailConfig, 1)
    cfg.host = "smtp.test.local"
    cfg.mail_from = "holo@test.local"
    cfg.enabled = False
    cfg.app_base_url = "https://example.com/holo"
    db_session.add_all([
        GitHubManager(email="first@example.com"), GitHubManager(email="second@example.com"),
    ])
    db_session.commit()
    return lab


def _save(client, lab, checked=True):
    phase = lab.phases[2]
    task = next(t for t in phase.tasks if t.title == "Git Repo Request")
    data = {f"done_{task.id}": "on"} if checked else {}
    return client.post(f"/labs/{lab.id}/phases/{phase.id}/save", data=data)


def test_request_emails_managers_with_owner_not_actor(client, db_session, request_lab,
                                                      admin_user, member_user):
    login(client, admin_user)
    response = _save(client, request_lab)
    assert response.status_code == 200
    assert "GitHub repository request emailed" in response.text
    assert len(FakeSMTP.sent) == 1
    sent = FakeSMTP.sent[0]
    assert sent["To"] == "first@example.com, second@example.com"
    assert sent["From"] == "holo@test.local"
    assert "Automation HOL" in sent["Subject"]
    assert "Please prepare a GitHub repository for a new Hands On Lab." in sent.get_content()
    assert f"Requestor: {member_user.email}" in sent.get_content()
    assert admin_user.email not in sent.get_content()
    assert f"https://example.com/holo/labs/{request_lab.id}" in sent.get_content()
    db_session.expire_all()
    assert db_session.get(Lab, request_lab.id).github_request_sent_at is not None
    assert db_session.query(AuditLog).filter_by(action="lab.github_request_send").count() == 1
    _save(client, request_lab)
    _save(client, request_lab, checked=False)
    _save(client, request_lab)
    assert len(FakeSMTP.sent) == 1


@pytest.mark.parametrize("failure", ["recipients", "host", "from", "owner", "relay"])
def test_failure_is_visible_and_can_be_retried(client, db_session, request_lab, member_user,
                                               failure):
    login(client, member_user)
    cfg = db_session.get(MailConfig, 1)
    if failure == "recipients":
        db_session.query(GitHubManager).delete()
    elif failure == "host":
        cfg.host = ""
    elif failure == "from":
        cfg.mail_from = ""
    elif failure == "owner":
        request_lab.owner = None
    else:
        FakeSMTP.connect_error = True
    db_session.commit()
    response = _save(client, request_lab)
    assert "Task saved, but the GitHub repository request was not sent." in response.text
    assert request_lab.github_request_sent_at is None
    assert next(t for t in request_lab.phases[2].tasks if t.title == "Git Repo Request").done
    assert db_session.query(AuditLog).filter_by(action="lab.github_request_failed").count() == 1

    if failure == "recipients":
        db_session.add(GitHubManager(email="retry@example.com"))
    cfg.host, cfg.mail_from = "smtp.test.local", "holo@test.local"
    request_lab.owner = member_user
    FakeSMTP.connect_error = False
    db_session.commit()
    assert "GitHub repository request emailed" in _save(client, request_lab).text
    assert request_lab.github_request_sent_at is not None


def test_unchecked_and_other_tasks_do_not_send(client, request_lab, member_user):
    login(client, member_user)
    _save(client, request_lab, checked=False)
    phase = request_lab.phases[2]
    client.post(f"/labs/{request_lab.id}/phases/{phase.id}/save",
                data={f"done_{phase.tasks[0].id}": "on"})
    phase = request_lab.phases[0]
    phase.tasks[0].title = "Git Repo Request"
    client.post(f"/labs/{request_lab.id}/phases/{phase.id}/save",
                data={f"done_{phase.tasks[0].id}": "on"})
    assert FakeSMTP.sent == []


def test_time_warp_is_silent(db_session, request_lab, admin_user):
    target = request_lab.phases[2].tasks[-1]
    assert lab_service.time_warp_to_task(db_session, request_lab, target.id, admin_user.id)[0]
    assert FakeSMTP.sent == []
    assert request_lab.github_request_sent_at is None


def test_partial_recipient_refusal_is_not_reported_as_success(
    db_session, request_lab, monkeypatch,
):
    monkeypatch.setattr(FakeSMTP, "send_message",
                        lambda self, msg: {"first@example.com": (550, b"Rejected")})
    ok, message = notifier.send_github_request(db_session, request_lab)
    assert not ok
    assert "Mail forwarder failed" in message
    assert request_lab.github_request_sent_at is None


def test_anonymous_save_does_not_send(client, request_lab):
    phase = request_lab.phases[2]
    task = next(t for t in phase.tasks if t.title == "Git Repo Request")
    response = client.post(
        f"/labs/{request_lab.id}/phases/{phase.id}/save",
        data={f"done_{task.id}": "on"}, follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert FakeSMTP.sent == []
    assert not task.done


def test_sent_marker_survives_backup_restore(backup_env):
    sent_at = datetime(2026, 10, 5, 12, 30)
    with Session(db.engine) as session:
        lab = lab_service.create_lab(session, name="Requested HOL", owner_id=None)
        lab.github_request_sent_at = sent_at
        session.commit()
        lab_id = lab.id
    snapshot = backup.make_backup()
    with Session(db.engine) as session:
        lab = session.get(Lab, lab_id)
        lab.github_request_sent_at = None
        session.commit()
    backup.restore_from(snapshot)
    with Session(db.engine) as session:
        lab = session.get(Lab, lab_id)
        assert lab.github_request_sent_at == sent_at
        assert notifier.send_github_request(session, lab) == (
            True, "GitHub repository request was already sent.",
        )
