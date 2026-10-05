"""Production-only updates preserve source HOLs and enforce Manager release approval."""
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import backup, config, db, lab_service as svc
from app.labs_template import UPDATE_PHASE_TEMPLATE
from app.models import (
    Approval, AuditLog, Lab, LabLink, MailConfig, PHASE_APPROVED,
    PHASE_AWAITING, PHASE_BLOCKED, PHASE_COMPLETED,
)
from conftest import FakeSMTP, login, make_user


@pytest.fixture()
def update_lab(db_session, member_user):
    source = svc.create_lab(db_session, name="Original HOL", owner_id=member_user.id,
                            course_id="123G", abstract="Original abstract")
    source.phases[0].notes = "Original work"
    db_session.commit()
    return svc.create_update(db_session, source)


def _task(lab, phase_position, task_position):
    return next(t for p in lab.phases if p.position == phase_position
                for t in p.tasks if t.position == task_position)


def _post_task(client, lab, phase, position, done=True):
    task = _task(lab, phase, position)
    return client.post(f"/labs/{lab.id}/tasks/{task.id}/complete",
                       data={"done": str(int(done))})


def test_update_button_creates_linked_record_without_changing_source(
    client, db_session, admin_user, member_user,
):
    source = svc.create_lab(db_session, name="Source", owner_id=member_user.id,
                            course_id="123G", abstract="Keep original")
    before = [(p.id, p.state, [(t.id, t.done) for t in p.tasks]) for p in source.phases]
    login(client, admin_user)
    response = client.post(f"/labs/{source.id}/update", follow_redirects=False)
    assert response.status_code == 303
    update = db_session.query(Lab).filter_by(parent_lab_id=source.id).one()
    assert response.headers["location"] == f"/labs/{update.id}"
    assert update.name == "Source - Update"
    assert update.owner_id == member_user.id
    assert update.abstract == "Keep original"
    assert update.course_id == "123G"
    assert update.target_release == ""
    assert [p.position for p in update.phases] == [4, 5, 6, 7]
    assert all(p.stage == "Production" for p in update.phases)
    assert [p.requires_approval for p in update.phases] == [True, False, False, False]
    assert [[t.title for t in p.tasks] for p in update.phases] == [
        phase["tasks"] for phase in UPDATE_PHASE_TEMPLATE
    ]
    assert all(not t.done for p in update.phases for t in p.tasks)
    assert [(p.id, p.state, [(t.id, t.done) for t in p.tasks]) for p in source.phases] == before
    db_session.expire_all()
    page = client.get(f"/labs/{source.id}")
    assert 'id="hol-updates"' in page.text
    assert f'href="/labs/{update.id}">Source - Update' in page.text
    assert db_session.query(AuditLog).filter_by(action="lab.update_create").count() == 1


def test_update_views_have_four_production_phases(client, db_session, update_lab, admin_user):
    login(client, admin_user)
    for path in ("/", "/mallmanac", f"/labs/{update_lab.id}", f"/labs/{update_lab.id}/calendar", "/metrics"):
        assert client.get(path).status_code == 200
    detail = client.get(f"/labs/{update_lab.id}").text
    assert "New Content" in detail
    assert 'id="new-content"' in detail
    assert "Mark completed" not in detail
    assert ">Submit for approval</button>" not in detail
    mall = client.get("/mallmanac").text
    update_card = mall.split(f'href="/labs/{update_lab.id}"', 1)[1].split("</section>", 1)[0]
    assert "dev-1" not in update_card
    assert "prod-1" in update_card and "prod-4" in update_card
    assert "production-only-grid" in update_card
    assert "data-warp-action" in update_card
    assert 'data-update="1"' in update_card


def test_updates_cannot_be_updated(client, db_session, update_lab, member_user):
    login(client, member_user)
    count = db_session.query(Lab).count()
    with pytest.raises(ValueError, match="An update cannot be updated"):
        svc.create_update(db_session, update_lab)
    response = client.post(f"/labs/{update_lab.id}/update")
    assert response.status_code == 200
    assert "An update cannot be updated" in response.text
    assert db_session.query(Lab).count() == count
    assert db_session.query(AuditLog).filter_by(action="lab.update_create").count() == 0
    assert 'id="hol-updates"' not in response.text
    for path in ("/", "/mallmanac", f"/labs/{update_lab.id}"):
        page = client.get(path).text
        assert f'action="/labs/{update_lab.id}/update"' not in page
    for path in ("/", "/mallmanac", f"/labs/{update_lab.parent_lab_id}"):
        assert f'action="/labs/{update_lab.parent_lab_id}/update"' in client.get(path).text


def test_additional_updates_link_to_original(client, db_session, update_lab, member_user):
    login(client, member_user)
    source_id = update_lab.parent_lab_id
    response = client.post(f"/labs/{source_id}/update", follow_redirects=False)
    assert response.status_code == 303
    updates = db_session.query(Lab).filter_by(parent_lab_id=source_id).all()
    assert len(updates) == 2
    assert all(update.name == "Original HOL - Update" for update in updates)
    page = client.get(f"/labs/{source_id}").text
    for update in updates:
        assert f'href="/labs/{update.id}">Original HOL - Update' in page
        assert db_session.query(Lab).filter_by(parent_lab_id=update.id).count() == 0


def test_owner_can_save_revision_and_clear_it(client, db_session, update_lab, member_user):
    login(client, member_user)
    url = f"/labs/{update_lab.id}/revision"
    assert "Revision: Not set" in client.get(f"/labs/{update_lab.id}").text
    assert "Revision: v2.1" in client.post(url, data={"revision": "  v2.1  "}).text
    db_session.expire_all()
    assert db_session.get(Lab, update_lab.id).revision == "v2.1"
    for path in ("/", "/mallmanac", f"/labs/{update_lab.parent_lab_id}"):
        assert "Revision: v2.1" in client.get(path).text
    assert db_session.get(Lab, update_lab.parent_lab_id).revision == ""
    assert db_session.query(AuditLog).filter_by(action="lab.revision_set").count() == 1
    assert "80 characters or fewer" in client.post(url, data={"revision": "x" * 81}).text
    assert update_lab.revision == "v2.1"
    assert client.post(url, data={"revision": "x" * 80}).status_code == 200
    assert update_lab.revision == "x" * 80
    assert "Revision: Not set" in client.post(url, data={"revision": "  "}).text
    assert update_lab.revision == ""


def test_revision_edit_permissions_and_scope(client, db_session, update_lab, member_user, admin_user):
    url = f"/labs/{update_lab.id}/revision"
    assert client.post(url, data={"revision": "1"}, follow_redirects=False).headers["location"] == "/login"
    outsider = make_user(db_session, email="outsider@test.local")
    login(client, outsider)
    assert "Edit revision" not in client.get(f"/labs/{update_lab.id}").text
    assert client.post(url, data={"revision": "1"}).status_code == 403
    assert update_lab.revision == ""
    login(client, admin_user)
    assert client.post(url, data={"revision": "1"}).status_code == 200
    assert update_lab.revision == "1"
    assert client.post(f"/labs/{update_lab.parent_lab_id}/revision",
                       data={"revision": "2"}).status_code == 400
    assert client.post("/labs/999999/revision", data={"revision": "2"}).status_code == 404
    assert "Edit revision" not in client.get(f"/labs/{update_lab.parent_lab_id}").text


def test_submission_sends_manager_email_and_gates_final_completion(
    client, db_session, update_lab, member_user, manager_user, admin_user, fake_smtp,
):
    cfg = db_session.get(MailConfig, 1)
    cfg.host, cfg.mail_from = "smtp.test.local", "holo@test.local"
    cfg.enabled, cfg.manager_email = True, manager_user.email
    db_session.commit()
    login(client, member_user)
    response = _post_task(client, update_lab, 7, 2)
    assert "A Manager must approve prod-1" in response.text
    assert not _task(update_lab, 7, 2).done
    # Work ahead in all production phases without approval.
    for phase in update_lab.phases:
        for task in phase.tasks:
            if (phase.position, task.position) != (7, 2):
                _post_task(client, update_lab, phase.position, task.position)
    assert update_lab.phases[0].state == PHASE_AWAITING
    assert update_lab.phases[1].state == PHASE_COMPLETED
    assert update_lab.phases[2].state == PHASE_COMPLETED
    assert svc.lab_status(update_lab) != "Complete"
    assert FakeSMTP.sent[0]["To"] == manager_user.email
    assert "Update Preparation" in FakeSMTP.sent[0].get_content()
    _post_task(client, update_lab, 4, 3)
    assert len(FakeSMTP.sent) == 1
    phase = update_lab.phases[0]
    login(client, admin_user)
    client.post(f"/labs/{update_lab.id}/phases/{phase.id}/approve")
    assert phase.state == PHASE_AWAITING
    ok, message = svc.time_warp_to_task(db_session, update_lab, _task(update_lab, 7, 2).id, admin_user.id)
    assert not ok and "Manager" in message
    assert not svc.complete_phase(db_session, update_lab.phases[-1], update_lab)
    login(client, manager_user)
    client.post(f"/labs/{update_lab.id}/phases/{phase.id}/approve")
    assert phase.state == PHASE_APPROVED
    assert phase.approval.approver_id == manager_user.id
    assert svc.lab_status(update_lab) != "Complete"
    login(client, member_user)
    _post_task(client, update_lab, 7, 2)
    assert svc.lab_status(update_lab) == "Complete"
    assert svc.progress(update_lab) == {"done": 4, "total": 4, "percent": 100}
    _post_task(client, update_lab, 7, 2, done=False)
    assert svc.lab_status(update_lab) != "Complete"
    assert phase.state == PHASE_APPROVED


def test_detail_save_cannot_bypass_release_gate(client, update_lab, member_user):
    login(client, member_user)
    phase = update_lab.phases[-1]
    response = client.post(
        f"/labs/{update_lab.id}/phases/{phase.id}/save",
        data={**{f"done_{t.id}": "on" for t in phase.tasks}, "notes": "Do not save on rejection"},
    )
    assert "A Manager must approve prod-1" in response.text
    assert all(not t.done for t in phase.tasks)
    assert phase.notes == ""


def test_release_requires_all_tasks_and_no_blocks(client, db_session, update_lab, manager_user):
    phase = update_lab.phases[0]
    phase.state = PHASE_APPROVED
    phase.approval = Approval(phase_id=phase.id, approver_id=manager_user.id)
    db_session.commit()
    login(client, manager_user)
    assert "Complete all other update tasks" in _post_task(client, update_lab, 7, 2).text
    for p in update_lab.phases:
        for t in p.tasks:
            if (p.position, t.position) != (7, 2):
                svc.set_task_done(db_session, t, done=True, user_id=manager_user.id)
    update_lab.phases[1].state = PHASE_BLOCKED
    db_session.commit()
    assert "Resolve all blocked phases" in _post_task(client, update_lab, 7, 2).text
    assert not _task(update_lab, 7, 2).done


def test_content_links_persist_and_are_scoped(client, db_session, update_lab, member_user):
    login(client, member_user)
    task = _task(update_lab, 5, 0)
    path = f"/labs/{update_lab.id}/tasks/{task.id}/content"
    response = client.post(path, data={"url": "https://example.sharepoint.com/new-guide", "label": "New guide"})
    assert "New guide" in response.text
    link = db_session.query(LabLink).filter_by(task_id=task.id).one()
    assert link.lab_id == update_lab.id
    assert not task.done
    assert client.post(path, data={"url": "javascript:alert(1)"}).status_code == 200
    assert db_session.query(LabLink).count() == 1
    wrong_task = _task(update_lab, 4, 0)
    assert client.post(f"/labs/{update_lab.id}/tasks/{wrong_task.id}/content",
                       data={"url": "https://example.com"}).status_code == 404
    assert client.post(f"/labs/{update_lab.parent_lab_id}/tasks/{task.id}/content",
                       data={"url": "https://example.com"}).status_code == 404
    client.post(f"/labs/{update_lab.id}/links/{link.id}/delete")
    assert db_session.query(LabLink).count() == 0


def test_creation_requires_login_and_source(client, db_session, member_user):
    source = svc.create_lab(db_session, name="Source", owner_id=member_user.id)
    response = client.post(f"/labs/{source.id}/update", follow_redirects=False)
    assert response.headers["location"] == "/login"
    login(client, member_user)
    assert client.post("/labs/999999/update").status_code == 404


def test_metrics_and_api_count_actual_phases(
    client, db_session, update_lab, admin_user, monkeypatch,
):
    source = update_lab.parent_lab
    for phase in source.phases:
        phase.state = PHASE_APPROVED if phase.requires_approval else PHASE_COMPLETED
    db_session.commit()
    login(client, admin_user)
    metrics = client.get("/metrics")
    assert metrics.context["m"]["pipeline_pct"] == 67  # 8 done of 12 total phases.
    assert metrics.context["m"]["prod_ct"] == 1
    monkeypatch.setattr(config, "API_KEY", "update-test-key")
    summary = client.get("/api/v1/summary", headers={"X-API-Key": "update-test-key"}).json()
    assert summary["pipeline_pct"] == 67
    assert summary["production_ct"] == 1
    labs = client.get("/api/v1/labs", headers={"X-API-Key": "update-test-key"}).json()["labs"]
    update_row = next(row for row in labs if row["id"] == update_lab.id)
    assert update_row["parent_lab_id"] == source.id
    assert update_row["percent"] == 0
    assert update_row["current_phase"] == "Update Preparation"


def test_blocked_submission_is_rejected_without_changing_task(client, db_session, update_lab, member_user):
    update_lab.phases[0].state = PHASE_BLOCKED
    db_session.commit()
    login(client, member_user)
    assert "Unblock prod-1" in _post_task(client, update_lab, 4, 3).text
    assert not _task(update_lab, 4, 3).done
    assert update_lab.phases[0].state == PHASE_BLOCKED
    _post_task(client, update_lab, 6, 0)
    assert _task(update_lab, 6, 0).done
    assert update_lab.phases[0].state == PHASE_BLOCKED


def test_update_time_warp_preserves_gates_and_is_silent(
    client, db_session, update_lab, admin_user, manager_user, fake_smtp,
):
    cfg = db_session.get(MailConfig, 1)
    cfg.host, cfg.mail_from = "smtp.test.local", "holo@test.local"
    cfg.enabled, cfg.manager_email = True, manager_user.email
    update_lab.phases[1].state = PHASE_BLOCKED
    db_session.commit()
    login(client, admin_user)
    target = _task(update_lab, 7, 1)
    response = client.post(f"/admin/time-warp/{update_lab.id}/{target.id}",
                           data={"phase_state": "unfinished"}, follow_redirects=False)
    assert response.status_code == 303
    assert "ok=1" in response.headers["location"]
    assert "phase_state=unfinished" in response.headers["location"]
    assert all(t.done for p in update_lab.phases for t in p.tasks
               if (p.position, t.position) != (7, 2))
    assert update_lab.phases[0].state == PHASE_AWAITING
    assert update_lab.phases[0].approval is None
    assert update_lab.phases[1].state == PHASE_BLOCKED
    assert update_lab.phases[2].state == PHASE_COMPLETED
    assert target.done_by_id == admin_user.id and target.done_at is not None
    assert FakeSMTP.sent == []
    assert db_session.query(AuditLog).filter_by(action="lab.time_warp").count() == 1
    assert not svc.time_warp_to_task(db_session, update_lab, target.id, admin_user.id)[0]
    final = _task(update_lab, 7, 2)
    ok, message = svc.time_warp_to_task(db_session, update_lab, final.id, admin_user.id)
    assert not ok and "Manager" in message
    svc.approve_phase(db_session, update_lab.phases[0], update_lab, manager_user.id)
    ok, message = svc.time_warp_to_task(db_session, update_lab, final.id, admin_user.id)
    assert not ok and "blocked" in message
    assert not final.done
    svc.set_blocked(db_session, update_lab.phases[1], False)
    ok, _ = svc.time_warp_to_task(db_session, update_lab, final.id, admin_user.id)
    assert ok and svc.lab_status(update_lab) == "Complete"
    assert update_lab.phases[0].approval.approver_id == manager_user.id
    assert FakeSMTP.sent == []


def test_update_time_warp_rejects_blocked_submission_atomically(db_session, update_lab, admin_user):
    update_lab.phases[0].state = PHASE_BLOCKED
    db_session.commit()
    ok, message = svc.time_warp_to_task(
        db_session, update_lab, _task(update_lab, 6, 0).id, admin_user.id,
    )
    assert not ok and "Unblock prod-1" in message
    assert all(not t.done for p in update_lab.phases for t in p.tasks)
    assert update_lab.phases[0].state == PHASE_BLOCKED


def test_legacy_migration_and_update_backup(backup_env):
    with db.engine.begin() as conn:
        conn.execute(text("DROP TABLE lab_links"))
        conn.execute(text("DROP TABLE labs"))
        conn.execute(text(
            "CREATE TABLE labs (id INTEGER PRIMARY KEY, name VARCHAR, course_id VARCHAR, "
            "abstract TEXT, target_release VARCHAR, owner_id INTEGER, github_request_sent_at DATETIME, "
            "created_at DATETIME, archived_at DATETIME, archived_by_id INTEGER)"
        ))
        conn.execute(text(
            "CREATE TABLE lab_links (id INTEGER PRIMARY KEY, lab_id INTEGER, label VARCHAR, "
            "url TEXT, added_by_id INTEGER, created_at DATETIME)"
        ))
    db._ensure_columns()
    db._ensure_columns()
    with Session(db.engine) as session:
        original = svc.create_lab(session, name="Backed up HOL", owner_id=None)
        update = svc.create_update(session, original)
        assert update.revision == ""
        update.revision = "3.0"
        update_id, original_id = update.id, original.id
        task = _task(update, 5, 0)
        task_id = task.id
        session.add(LabLink(lab_id=update.id, task_id=task.id, label="Content",
                            url="https://example.sharepoint.com/doc"))
        session.commit()
    snapshot = backup.make_backup()
    backup.restore_from(snapshot)
    with Session(db.engine) as session:
        update = session.get(Lab, update_id)
        assert update.parent_lab_id == original_id
        assert update.revision == "3.0"
        assert len(update.phases) == 4
        assert update.links[0].task_id == task_id
        assert session.get(Lab, original_id).updates[0].id == update_id
