"""RBAC tests: the manager-only approval gate and staff-only routes."""
from app import lab_service as svc
from app.models import PHASE_APPROVED, PHASE_AWAITING, PHASE_IN_PROGRESS

from conftest import login


def _create_lab_and_advance_to_awaiting(db_session, owner):
    """Create a lab and get its Design phase (approval) into 'awaiting_approval'."""
    lab = svc.create_lab(db_session, name="RBAC Lab", owner_id=owner.id)
    concept = next(p for p in lab.phases if p.name == "Concept")
    svc.complete_phase(db_session, concept, lab)
    design = next(p for p in lab.phases if p.name == "Design")
    svc.submit_phase(db_session, design, lab)
    return lab, design


def test_member_cannot_approve_a_submitted_phase(client, db_session, member_user):
    lab, design = _create_lab_and_advance_to_awaiting(db_session, member_user)
    login(client, member_user)

    resp = client.post(
        f"/labs/{lab.id}/phases/{design.id}/approve",
        data={"note": "trying to approve my own phase"},
        follow_redirects=False,
    )
    assert resp.status_code == 303  # no-op, but still redirects back
    db_session.refresh(design)
    assert design.state == PHASE_AWAITING  # unchanged


def test_admin_cannot_approve_a_submitted_phase(client, db_session, admin_user, member_user):
    lab, design = _create_lab_and_advance_to_awaiting(db_session, member_user)
    login(client, admin_user)

    resp = client.post(
        f"/labs/{lab.id}/phases/{design.id}/approve",
        data={"note": "admin trying to approve"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db_session.refresh(design)
    assert design.state == PHASE_AWAITING  # admin is not the approval gate


def test_manager_can_approve_a_submitted_phase(client, db_session, manager_user, member_user):
    lab, design = _create_lab_and_advance_to_awaiting(db_session, member_user)
    login(client, manager_user)

    resp = client.post(
        f"/labs/{lab.id}/phases/{design.id}/approve",
        data={"note": "looks good"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db_session.refresh(design)
    assert design.state == PHASE_APPROVED
    assert design.approval.approver_id == manager_user.id

    develop = next(p for p in lab.phases if p.name == "Develop")
    assert develop.state == PHASE_IN_PROGRESS


def test_member_cannot_reach_admin_labs_console(client, member_user):
    login(client, member_user)
    resp = client.get("/admin/labs", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_staff_can_reach_admin_labs_console(client, admin_user, manager_user):
    login(client, admin_user)
    assert client.get("/admin/labs", follow_redirects=False).status_code == 200

    login(client, manager_user)
    assert client.get("/admin/labs", follow_redirects=False).status_code == 200


def test_anonymous_redirected_to_login(client):
    resp = client.get("/admin/labs", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"

    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_member_cannot_archive_a_lab(client, db_session, member_user):
    lab = svc.create_lab(db_session, name="To Archive", owner_id=member_user.id)
    login(client, member_user)

    resp = client.post(f"/labs/{lab.id}/archive", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"  # bounced, not the admin console

    db_session.refresh(lab)
    assert lab.archived_at is None


def test_admin_can_archive_a_lab(client, db_session, admin_user, member_user):
    lab = svc.create_lab(db_session, name="To Archive", owner_id=member_user.id)
    login(client, admin_user)

    resp = client.post(f"/labs/{lab.id}/archive", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/labs"

    db_session.refresh(lab)
    assert lab.archived_at is not None


def test_docs_and_openapi_are_staff_only(client, member_user, admin_user):
    login(client, member_user)
    assert client.get("/docs", follow_redirects=False).status_code == 303

    login(client, admin_user)
    assert client.get("/docs", follow_redirects=False).status_code == 200
