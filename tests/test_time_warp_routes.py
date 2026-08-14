"""HTTP-level tests for the granular, per-task Time Warp flow on the
Mallmanac: admin-only clickable pills."""
from app import lab_service as svc
from app.models import AuditLog, PHASE_COMPLETED, PHASE_IN_PROGRESS

from conftest import login


def _phase(lab, name):
    return next(p for p in lab.phases if p.name == name)


def _task(phase, title):
    return next(t for t in phase.tasks if t.title == title)


def test_mallmanac_admin_sees_warp_mode_toggle_and_task_forms(client, db_session, admin_user,
                                                              member_user):
    lab = svc.create_lab(db_session, name="Fresh Lab", owner_id=member_user.id)
    login(client, admin_user)

    resp = client.get("/mallmanac", follow_redirects=False)
    assert resp.status_code == 200
    assert "Time Warp mode" in resp.text
    assert f"/admin/time-warp/{lab.id}/" in resp.text


def test_mallmanac_member_does_not_see_warp_ui(client, db_session, member_user):
    svc.create_lab(db_session, name="Fresh Lab", owner_id=member_user.id)
    login(client, member_user)

    resp = client.get("/mallmanac", follow_redirects=False)
    assert resp.status_code == 200
    assert "Time Warp mode" not in resp.text
    assert "/admin/time-warp/" not in resp.text


def test_mallmanac_manager_does_not_see_warp_ui(client, db_session, manager_user, member_user):
    svc.create_lab(db_session, name="Fresh Lab", owner_id=member_user.id)
    login(client, manager_user)

    resp = client.get("/mallmanac", follow_redirects=False)
    assert resp.status_code == 200
    assert "Time Warp mode" not in resp.text


def test_member_cannot_post_a_warp(client, db_session, member_user):
    lab = svc.create_lab(db_session, name="Lab", owner_id=member_user.id)
    concept = _phase(lab, "Concept")
    task = _task(concept, "Stakeholder Discussion")
    login(client, member_user)

    resp = client.post(f"/admin/time-warp/{lab.id}/{task.id}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    db_session.refresh(task)
    assert task.done is False


def test_manager_cannot_post_a_warp(client, db_session, manager_user, member_user):
    lab = svc.create_lab(db_session, name="Lab", owner_id=member_user.id)
    concept = _phase(lab, "Concept")
    task = _task(concept, "Stakeholder Discussion")
    login(client, manager_user)

    resp = client.post(f"/admin/time-warp/{lab.id}/{task.id}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    db_session.refresh(task)
    assert task.done is False


def test_anonymous_redirected_to_login(client, db_session, member_user):
    lab = svc.create_lab(db_session, name="Lab", owner_id=member_user.id)
    task = lab.phases[0].tasks[0]

    resp = client.post(f"/admin/time-warp/{lab.id}/{task.id}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_admin_warp_end_to_end_reflects_on_mallmanac_and_audits(client, db_session, admin_user,
                                                                member_user):
    lab = svc.create_lab(db_session, name="Legacy Course", owner_id=member_user.id)
    design = _phase(lab, "Design")
    target = _task(design, "Hardware & Software Requirements")
    login(client, admin_user)

    resp = client.post(f"/admin/time-warp/{lab.id}/{target.id}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/mallmanac?ok=1")

    db_session.refresh(lab)
    concept = _phase(lab, "Concept")
    assert concept.state == PHASE_COMPLETED
    assert design.state == PHASE_IN_PROGRESS
    db_session.refresh(target)
    assert target.done is True

    entry = db_session.query(AuditLog).filter(AuditLog.action == "lab.time_warp").first()
    assert entry is not None
    assert entry.target_label == "Legacy Course"

    mall = client.get("/mallmanac", follow_redirects=False)
    assert mall.status_code == 200
    assert "Legacy Course" in mall.text

    detail = client.get(f"/labs/{lab.id}", follow_redirects=False)
    assert detail.status_code == 200


def test_warp_shows_error_banner_on_backward_target(client, db_session, admin_user,
                                                     member_user):
    lab = svc.create_lab(db_session, name="Lab", owner_id=member_user.id)
    concept = _phase(lab, "Concept")
    first = _task(concept, "Topic / High-Level Overview")
    login(client, admin_user)

    resp = client.post(f"/admin/time-warp/{lab.id}/{first.id}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/mallmanac?ok=1")  # first task is a valid target

    # Now re-targeting that same task must fail.
    resp = client.post(f"/admin/time-warp/{lab.id}/{first.id}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/mallmanac?ok=0")

    banner = client.get("/mallmanac", follow_redirects=False)
    assert banner.status_code == 200


def test_warp_unknown_task(client, db_session, admin_user, member_user):
    lab = svc.create_lab(db_session, name="Lab", owner_id=member_user.id)
    login(client, admin_user)

    resp = client.post(f"/admin/time-warp/{lab.id}/999999", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/mallmanac?ok=0")


def test_warp_task_belonging_to_a_different_lab_is_rejected(client, db_session, admin_user,
                                                            member_user):
    lab_a = svc.create_lab(db_session, name="Lab A", owner_id=member_user.id)
    lab_b = svc.create_lab(db_session, name="Lab B", owner_id=member_user.id)
    task_from_b = lab_b.phases[0].tasks[0]
    login(client, admin_user)

    resp = client.post(f"/admin/time-warp/{lab_a.id}/{task_from_b.id}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/mallmanac?ok=0")

    db_session.refresh(task_from_b)
    assert task_from_b.done is False
