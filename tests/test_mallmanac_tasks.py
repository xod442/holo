"""Independent task completion never bypasses phase/manager gates."""
import pytest

from app import lab_service as svc
from app.models import (
    Approval, AuditLog, GitHubManager, MailConfig, PHASE_APPROVED,
    PHASE_AWAITING, PHASE_BLOCKED, PHASE_COMPLETED, PHASE_IN_PROGRESS,
)
from conftest import FakeSMTP, login


@pytest.mark.parametrize("role", ["member_user", "manager_user", "admin_user"])
def test_every_role_can_complete_later_task_without_changing_gates(
    client, db_session, member_user, request, role,
):
    actor = request.getfixturevalue(role)
    lab = svc.create_lab(db_session, name="Parallel work", owner_id=member_user.id)
    lab.phases[0].state = PHASE_BLOCKED
    lab.phases[1].state = PHASE_AWAITING
    task = lab.phases[-1].tasks[-1]
    task.note = "Preserve this note"
    db_session.commit()
    before = [phase.state for phase in lab.phases]
    login(client, actor)
    mall = client.get("/mallmanac")
    assert f"/labs/{lab.id}/tasks/{task.id}/complete" in mall.text
    assert f"Complete {task.phase.name} / {task.title}" in mall.text
    response = client.post(
        f"/labs/{lab.id}/tasks/{task.id}/complete",
        data={"done": "1", "owner": str(member_user.id)}, follow_redirects=False,
    )
    assert response.status_code == 303
    assert f"owner={member_user.id}" in response.headers["location"]
    db_session.refresh(task)
    assert task.done and task.done_by_id == actor.id and task.done_at is not None
    assert task.note == "Preserve this note"
    assert [phase.state for phase in lab.phases] == before
    assert db_session.query(Approval).count() == 0
    assert svc.lab_status(lab) == "Blocked"
    assert not svc.can_start(lab.phases[-1], lab)
    assert db_session.query(AuditLog).filter_by(action="task.complete", target_id=task.id).count() == 1
    completed_at = task.done_at
    client.post(f"/labs/{lab.id}/tasks/{task.id}/complete", data={"done": "1"})
    assert task.done_at == completed_at
    assert db_session.query(AuditLog).filter_by(action="task.complete", target_id=task.id).count() == 1
    client.post(f"/labs/{lab.id}/tasks/{task.id}/complete", data={"done": "0"})
    assert not task.done and task.done_by_id is None and task.done_at is None
    assert [phase.state for phase in lab.phases] == before
    assert task.note == "Preserve this note"


def test_all_tasks_done_still_requires_manager_approval(client, db_session, member_user, manager_user):
    lab = svc.create_lab(db_session, name="All tasks done", owner_id=member_user.id)
    for phase in lab.phases:
        phase.state = PHASE_AWAITING if phase.requires_approval else PHASE_COMPLETED
    db_session.commit()
    login(client, member_user)
    for phase in lab.phases:
        for task in phase.tasks:
            assert client.post(
                f"/labs/{lab.id}/tasks/{task.id}/complete", data={"done": "1"},
                follow_redirects=False,
            ).status_code == 303
    assert all(t.done for p in lab.phases for t in p.tasks)
    assert svc.lab_status(lab) != "Complete"
    assert svc.progress(lab)["percent"] == 50
    approval_phases = [phase for phase in lab.phases if phase.requires_approval]
    phase = approval_phases[0]
    client.post(f"/labs/{lab.id}/phases/{phase.id}/approve")
    assert phase.state == PHASE_AWAITING
    login(client, manager_user)
    for phase in approval_phases[:-1]:
        client.post(f"/labs/{lab.id}/phases/{phase.id}/approve")
        assert phase.state == PHASE_APPROVED
        assert svc.lab_status(lab) != "Complete"
    client.post(f"/labs/{lab.id}/phases/{approval_phases[-1].id}/approve")
    assert svc.lab_status(lab) == "Complete"


@pytest.mark.parametrize("state", [PHASE_BLOCKED, PHASE_AWAITING])
def test_task_in_blocked_or_awaiting_phase_can_be_completed(
    client, db_session, member_user, state,
):
    lab = svc.create_lab(db_session, name="Blocked work", owner_id=member_user.id)
    phase = lab.phases[1]
    phase.state = state
    db_session.commit()
    login(client, member_user)
    client.post(f"/labs/{lab.id}/tasks/{phase.tasks[0].id}/complete", data={"done": "1"})
    assert phase.tasks[0].done
    assert phase.state == state


def test_request_task_emails_once_from_mallmanac(client, db_session, member_user, fake_smtp):
    lab = svc.create_lab(db_session, name="Repo request", owner_id=member_user.id)
    cfg = db_session.get(MailConfig, 1)
    cfg.host, cfg.mail_from = "smtp.test.local", "holo@test.local"
    db_session.add(GitHubManager(email="github@example.com"))
    db_session.commit()
    task = next(t for t in lab.phases[2].tasks if t.title == "Git Repo Request")
    login(client, member_user)
    url = f"/labs/{lab.id}/tasks/{task.id}/complete"
    page = client.post(url, data={"done": "1"})
    assert "GitHub repository request emailed" in page.text
    assert len(FakeSMTP.sent) == 1
    assert f"Requestor: {member_user.email}" in FakeSMTP.sent[0].get_content()
    client.post(url, data={"done": "0"})
    client.post(url, data={"done": "1"})
    assert len(FakeSMTP.sent) == 1
    assert lab.phases[0].state == PHASE_IN_PROGRESS


def test_invalid_and_cross_lab_requests_do_not_modify_tasks(client, db_session, member_user):
    lab = svc.create_lab(db_session, name="One", owner_id=member_user.id)
    other = svc.create_lab(db_session, name="Two", owner_id=member_user.id)
    task = other.phases[0].tasks[0]
    url = f"/labs/{lab.id}/tasks/{task.id}/complete"
    assert client.post(url, data={"done": "1"}, follow_redirects=False).headers["location"] == "/login"
    login(client, member_user)
    assert client.post(url, data={"done": "1"}).status_code == 404
    assert client.post(f"/labs/{other.id}/tasks/{task.id}/complete",
                       data={"done": "invalid"}).status_code == 400
    assert not task.done
