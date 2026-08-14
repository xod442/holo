"""HTTP-level tests for the remaining labs.py routes: dashboard filtering,
mallmanac, metrics, calendar, lab creation, links, owner reassignment,
course-id, and the save-pill audit diffing."""
from app import lab_service as svc
from app.models import AuditLog, Lab

from conftest import login, make_user


def test_dashboard_requires_login(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_create_lab_requires_name(client, member_user):
    login(client, member_user)
    resp = client.post("/labs", data={"name": "   "}, follow_redirects=False)
    assert resp.status_code == 400


def test_create_lab_success_becomes_owner(client, db_session, member_user):
    login(client, member_user)
    resp = client.post("/labs", data={"name": "My New Lab", "course_id": "01234G"},
                       follow_redirects=False)
    assert resp.status_code == 303

    lab = db_session.query(Lab).filter_by(name="My New Lab").first()
    assert lab is not None
    assert lab.owner_id == member_user.id
    assert lab.course_id == "01234G"
    assert resp.headers["location"] == f"/labs/{lab.id}"


def test_dashboard_owner_filter(client, db_session, member_user):
    other = make_user(db_session, email="other@test.local")
    svc.create_lab(db_session, name="Mine", owner_id=member_user.id)
    svc.create_lab(db_session, name="Theirs", owner_id=other.id)
    login(client, member_user)

    resp = client.get("/", params={"owner": str(member_user.id)}, follow_redirects=False)
    assert resp.status_code == 200
    assert "Mine" in resp.text
    assert "Theirs" not in resp.text

    resp_all = client.get("/", follow_redirects=False)
    assert "Mine" in resp_all.text and "Theirs" in resp_all.text


def test_dashboard_unassigned_filter(client, db_session, member_user):
    svc.create_lab(db_session, name="Orphan Lab", owner_id=None)
    svc.create_lab(db_session, name="Owned Lab", owner_id=member_user.id)
    login(client, member_user)

    resp = client.get("/", params={"owner": "unassigned"}, follow_redirects=False)
    assert "Orphan Lab" in resp.text
    assert "Owned Lab" not in resp.text


def test_manager_sees_awaiting_approval_queue(client, db_session, manager_user, member_user):
    lab = svc.create_lab(db_session, name="Lab", owner_id=member_user.id)
    concept = next(p for p in lab.phases if p.name == "Concept")
    svc.complete_phase(db_session, concept, lab)
    design = next(p for p in lab.phases if p.name == "Design")
    svc.submit_phase(db_session, design, lab)

    login(client, manager_user)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    assert "Lab" in resp.text  # awaiting queue rendered without error


def test_mallmanac_renders_for_logged_in_user(client, db_session, member_user):
    svc.create_lab(db_session, name="Mallmanac Lab", owner_id=member_user.id)
    login(client, member_user)
    resp = client.get("/mallmanac", follow_redirects=False)
    assert resp.status_code == 200
    assert "Mallmanac Lab" in resp.text


def test_mallmanac_requires_login(client):
    resp = client.get("/mallmanac", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_metrics_is_staff_only(client, db_session, member_user, admin_user):
    svc.create_lab(db_session, name="Metrics Lab", owner_id=member_user.id)

    login(client, member_user)
    resp = client.get("/metrics", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    login(client, admin_user)
    resp = client.get("/metrics", follow_redirects=False)
    assert resp.status_code == 200
    assert "Metrics Lab" in resp.text


def test_calendar_renders_with_unscheduled_and_scheduled_phases(client, db_session, member_user):
    lab = svc.create_lab(db_session, name="Cal Lab", owner_id=member_user.id)
    concept = next(p for p in lab.phases if p.name == "Concept")
    svc.save_phase(db_session, concept, actual_hours=None, notes="", target_date="2026-06-15",
                  task_updates={}, user_id=member_user.id)

    login(client, member_user)
    resp = client.get(f"/labs/{lab.id}/calendar", params={"month": "2026-06"},
                      follow_redirects=False)
    assert resp.status_code == 200


def test_calendar_unknown_lab_redirects_home(client, member_user):
    login(client, member_user)
    resp = client.get("/labs/999999/calendar", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_add_and_delete_link(client, db_session, member_user):
    lab = svc.create_lab(db_session, name="Link Lab", owner_id=member_user.id)
    login(client, member_user)

    resp = client.post(f"/labs/{lab.id}/links",
                       data={"url": "https://example.com/doc", "label": "Doc"},
                       follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(lab)
    assert len(lab.links) == 1
    link_id = lab.links[0].id

    entry = db_session.query(AuditLog).filter(AuditLog.action == "lab.link_add").first()
    assert entry is not None

    resp = client.post(f"/labs/{lab.id}/links/{link_id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(lab)
    assert len(lab.links) == 0


def test_add_link_rejects_unsafe_url_via_http(client, db_session, member_user):
    lab = svc.create_lab(db_session, name="Link Lab 2", owner_id=member_user.id)
    login(client, member_user)

    client.post(f"/labs/{lab.id}/links", data={"url": "javascript:alert(1)"},
               follow_redirects=False)
    db_session.refresh(lab)
    assert len(lab.links) == 0


def test_owner_can_reassign_owner(client, db_session, member_user):
    other = make_user(db_session, email="newowner@test.local")
    lab = svc.create_lab(db_session, name="Reassign Lab", owner_id=member_user.id)
    login(client, member_user)

    resp = client.post(f"/labs/{lab.id}/owner", data={"owner_id": str(other.id)},
                       follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(lab)
    assert lab.owner_id == other.id


def test_non_owner_non_staff_cannot_reassign_owner(client, db_session, member_user):
    other = make_user(db_session, email="bystander@test.local")
    lab = svc.create_lab(db_session, name="Protected Lab", owner_id=other.id)
    login(client, member_user)  # not the owner, not staff

    client.post(f"/labs/{lab.id}/owner", data={"owner_id": str(member_user.id)},
               follow_redirects=False)
    db_session.refresh(lab)
    assert lab.owner_id == other.id  # unchanged


def test_staff_can_reassign_any_lab_owner(client, db_session, admin_user, member_user):
    lab = svc.create_lab(db_session, name="Staff Reassign Lab", owner_id=member_user.id)
    login(client, admin_user)

    resp = client.post(f"/labs/{lab.id}/owner", data={"owner_id": ""}, follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(lab)
    assert lab.owner_id is None


def test_set_course_id_by_owner(client, db_session, member_user):
    lab = svc.create_lab(db_session, name="Course Lab", owner_id=member_user.id)
    login(client, member_user)

    resp = client.post(f"/labs/{lab.id}/course-id", data={"course_id": "98765X"},
                       follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(lab)
    assert lab.course_id == "98765X"


def test_set_course_id_rejected_for_non_owner_non_staff(client, db_session, member_user):
    other = make_user(db_session, email="another@test.local")
    lab = svc.create_lab(db_session, name="Course Lab 2", owner_id=other.id)
    login(client, member_user)

    client.post(f"/labs/{lab.id}/course-id", data={"course_id": "SHOULDNOTSET"},
               follow_redirects=False)
    db_session.refresh(lab)
    assert lab.course_id == ""


def test_save_pill_updates_and_audits_only_on_change(client, db_session, member_user):
    lab = svc.create_lab(db_session, name="Save Lab", owner_id=member_user.id)
    concept = next(p for p in lab.phases if p.name == "Concept")
    task = concept.tasks[0]
    login(client, member_user)

    resp = client.post(
        f"/labs/{lab.id}/phases/{concept.id}/save",
        data={
            "actual_hours": "3.5",
            "notes": "making progress",
            "target_date": "2026-03-01",
            f"note_{task.id}": "done via UI",
            f"done_{task.id}": "on",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db_session.refresh(concept)
    assert concept.actual_hours == 3.5
    assert concept.notes == "making progress"

    entry = db_session.query(AuditLog).filter(AuditLog.action == "phase.save").first()
    assert entry is not None
    assert "hours" in entry.details or "tasks toggled" in entry.details


def test_block_and_unblock_phase_via_http(client, db_session, member_user):
    lab = svc.create_lab(db_session, name="Block Lab", owner_id=member_user.id)
    concept = next(p for p in lab.phases if p.name == "Concept")
    login(client, member_user)

    resp = client.post(f"/labs/{lab.id}/phases/{concept.id}/block", follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(concept)
    from app.models import PHASE_BLOCKED, PHASE_IN_PROGRESS
    assert concept.state == PHASE_BLOCKED

    resp = client.post(f"/labs/{lab.id}/phases/{concept.id}/unblock", follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(concept)
    assert concept.state == PHASE_IN_PROGRESS


def test_lab_detail_unknown_lab_redirects_home(client, member_user):
    login(client, member_user)
    resp = client.get("/labs/999999", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_lab_detail_shows_approve_flag_only_for_manager(client, db_session, member_user,
                                                        manager_user):
    lab = svc.create_lab(db_session, name="Detail Lab", owner_id=member_user.id)

    login(client, member_user)
    resp = client.get(f"/labs/{lab.id}", follow_redirects=False)
    assert resp.status_code == 200

    login(client, manager_user)
    resp = client.get(f"/labs/{lab.id}", follow_redirects=False)
    assert resp.status_code == 200


def test_start_submit_complete_phase_via_http(client, db_session, member_user):
    lab = svc.create_lab(db_session, name="Flow Lab", owner_id=member_user.id)
    concept = next(p for p in lab.phases if p.name == "Concept")
    login(client, member_user)

    # Already in_progress on creation — completing it (a non-approval phase).
    resp = client.post(f"/labs/{lab.id}/phases/{concept.id}/complete", follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(concept)
    from app.models import PHASE_AWAITING, PHASE_COMPLETED, PHASE_IN_PROGRESS
    assert concept.state == PHASE_COMPLETED

    design = next(p for p in lab.phases if p.name == "Design")
    assert design.state == PHASE_IN_PROGRESS  # auto-activated

    resp = client.post(f"/labs/{lab.id}/phases/{design.id}/submit", follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(design)
    assert design.state == PHASE_AWAITING


def test_start_phase_rejected_when_earlier_phase_not_done(client, db_session, member_user):
    lab = svc.create_lab(db_session, name="Flow Lab 2", owner_id=member_user.id)
    design = next(p for p in lab.phases if p.name == "Design")
    login(client, member_user)

    # Design can't start yet — Concept isn't done.
    resp = client.post(f"/labs/{lab.id}/phases/{design.id}/start", follow_redirects=False)
    assert resp.status_code == 303
    from app.models import PHASE_NOT_STARTED
    db_session.refresh(design)
    assert design.state == PHASE_NOT_STARTED


def test_admin_labs_console_and_archived_page(client, db_session, admin_user, member_user):
    lab = svc.create_lab(db_session, name="Archivable Lab", owner_id=member_user.id)
    login(client, admin_user)

    resp = client.get("/admin/labs", follow_redirects=False)
    assert resp.status_code == 200
    assert "Archivable Lab" in resp.text

    client.post(f"/labs/{lab.id}/archive", follow_redirects=False)

    resp = client.get("/archived", follow_redirects=False)
    assert resp.status_code == 200
    assert "Archivable Lab" in resp.text

    resp = client.post(f"/labs/{lab.id}/unarchive", follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(lab)
    assert lab.archived_at is None


def test_member_cannot_view_archived_page(client, member_user):
    login(client, member_user)
    resp = client.get("/archived", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
