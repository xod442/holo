"""HTTP-level tests for the Time Warp admin page and action."""
from app import lab_service as svc
from app.models import AuditLog, PHASE_IN_PROGRESS

from conftest import login


def _phase(lab, name):
    return next(p for p in lab.phases if p.name == name)


def test_member_redirected_away(client, db_session, member_user):
    lab = svc.create_lab(db_session, name="Lab", owner_id=member_user.id)
    login(client, member_user)

    resp = client.get("/admin/time-warp", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    resp = client.post(f"/admin/time-warp/{lab.id}", data={"target_position": "3"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_anonymous_redirected_to_login(client):
    resp = client.get("/admin/time-warp", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_page_lists_labs_with_current_phase_and_options(client, db_session, admin_user,
                                                        member_user):
    svc.create_lab(db_session, name="Fresh Lab", owner_id=member_user.id)
    login(client, admin_user)

    resp = client.get("/admin/time-warp", follow_redirects=False)
    assert resp.status_code == 200
    assert "Fresh Lab" in resp.text
    assert "dev-2" in resp.text  # Design's axis code, a valid forward option


def test_manager_cannot_use_time_warp(client, db_session, manager_user, member_user):
    lab = svc.create_lab(db_session, name="Manager Lab", owner_id=member_user.id)
    login(client, manager_user)

    resp = client.get("/admin/time-warp", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    resp = client.post(f"/admin/time-warp/{lab.id}", data={"target_position": "4"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    db_session.refresh(lab)
    concept = _phase(lab, "Concept")
    assert concept.state == "in_progress"  # untouched


def test_warp_end_to_end_reflects_on_mallmanac_and_audits(client, db_session, admin_user,
                                                          member_user):
    lab = svc.create_lab(db_session, name="Legacy Course", owner_id=member_user.id)
    login(client, admin_user)

    resp = client.post(f"/admin/time-warp/{lab.id}", data={"target_position": "5"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/admin/time-warp?ok=1")

    db_session.refresh(lab)
    publish = _phase(lab, "Publish")
    assert publish.state == PHASE_IN_PROGRESS
    concept = _phase(lab, "Concept")
    assert concept.state != "not_started"

    entry = db_session.query(AuditLog).filter(AuditLog.action == "lab.time_warp").first()
    assert entry is not None
    assert entry.target_label == "Legacy Course"

    mall = client.get("/mallmanac", follow_redirects=False)
    assert mall.status_code == 200
    assert "Legacy Course" in mall.text

    detail = client.get(f"/labs/{lab.id}", follow_redirects=False)
    assert detail.status_code == 200
    assert "Publish" in detail.text


def test_warp_rejects_backward_target_shows_error(client, db_session, admin_user, member_user):
    lab = svc.create_lab(db_session, name="Lab", owner_id=member_user.id)
    login(client, admin_user)

    resp = client.post(f"/admin/time-warp/{lab.id}", data={"target_position": "0"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/admin/time-warp?ok=0")

    entry = db_session.query(AuditLog).filter(AuditLog.action == "lab.time_warp").first()
    assert entry is None  # rejected attempts aren't audited as successes


def test_warp_unknown_lab(client, admin_user):
    login(client, admin_user)
    resp = client.post("/admin/time-warp/999999", data={"target_position": "3"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/admin/time-warp?ok=0")


def test_already_complete_lab_shows_no_warp_options(client, db_session, admin_user,
                                                    member_user):
    lab = svc.create_lab(db_session, name="Done Lab", owner_id=member_user.id)
    svc.time_warp(db_session, lab, target_position=7, actor_id=member_user.id)
    last = _phase(lab, "Post-Production Acceptance")
    svc.complete_phase(db_session, last, lab)

    login(client, admin_user)
    resp = client.get("/admin/time-warp", follow_redirects=False)
    assert resp.status_code == 200
    assert "Already complete" in resp.text
