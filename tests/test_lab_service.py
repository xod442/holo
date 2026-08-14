"""Unit tests for the gated lab lifecycle in app.lab_service."""
import pytest

from app import lab_service as svc
from app.labs_template import PHASE_TEMPLATE
from app.models import (
    PHASE_APPROVED,
    PHASE_AWAITING,
    PHASE_BLOCKED,
    PHASE_COMPLETED,
    PHASE_IN_PROGRESS,
    PHASE_NOT_STARTED,
)

from conftest import make_user


def _phase(lab, name):
    return next(p for p in lab.phases if p.name == name)


def test_create_lab_clones_template_with_first_phase_active(db_session):
    owner = make_user(db_session, email="owner@test.local")
    lab = svc.create_lab(db_session, name="  My Lab  ", owner_id=owner.id)

    assert lab.name == "My Lab"  # stripped
    assert len(lab.phases) == len(PHASE_TEMPLATE)
    assert lab.phases[0].state == PHASE_IN_PROGRESS
    assert all(p.state == PHASE_NOT_STARTED for p in lab.phases[1:])
    # Tasks cloned for the first phase.
    assert len(lab.phases[0].tasks) == len(PHASE_TEMPLATE[0]["tasks"])


def test_progress_and_status_start_empty(db_session):
    owner = make_user(db_session, email="owner2@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)

    progress = svc.progress(lab)
    assert progress == {"done": 0, "total": len(PHASE_TEMPLATE), "percent": 0}
    assert svc.lab_status(lab) == "In Progress"
    assert svc.current_phase(lab).name == "Concept"


def test_completion_phase_flow_activates_next(db_session):
    owner = make_user(db_session, email="owner3@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)
    concept = _phase(lab, "Concept")  # non-approval phase

    assert concept.requires_approval is False
    # Cannot submit a completion phase (wrong action for its type).
    assert svc.submit_phase(db_session, concept, lab) is False
    assert svc.complete_phase(db_session, concept, lab) is True
    assert concept.state == PHASE_COMPLETED

    design = _phase(lab, "Design")
    assert design.state == PHASE_IN_PROGRESS  # auto-activated
    progress = svc.progress(lab)
    assert progress["done"] == 1


def test_approval_phase_requires_submit_then_manager_approve(db_session):
    owner = make_user(db_session, email="owner4@test.local")
    manager = make_user(db_session, email="mgr@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)
    concept = _phase(lab, "Concept")
    svc.complete_phase(db_session, concept, lab)

    design = _phase(lab, "Design")
    assert design.requires_approval is True
    # Cannot "complete" an approval phase directly.
    assert svc.complete_phase(db_session, design, lab) is False
    assert svc.submit_phase(db_session, design, lab) is True
    assert design.state == PHASE_AWAITING

    # A phase awaiting approval can't be re-submitted.
    assert svc.submit_phase(db_session, design, lab) is False

    assert svc.approve_phase(db_session, design, lab, approver_id=manager.id, note="lgtm") is True
    assert design.state == PHASE_APPROVED
    assert design.approval is not None
    assert design.approval.approver_id == manager.id

    develop = _phase(lab, "Develop")
    assert develop.state == PHASE_IN_PROGRESS  # next phase auto-activated


def test_can_start_requires_all_earlier_phases_done(db_session):
    owner = make_user(db_session, email="owner5@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)
    design = _phase(lab, "Design")
    develop = _phase(lab, "Develop")

    # Design is not_started but Concept (earlier) isn't done yet.
    assert svc.can_start(design, lab) is False
    assert svc.can_start(develop, lab) is False

    concept = _phase(lab, "Concept")
    svc.complete_phase(db_session, concept, lab)
    assert svc.can_start(design, lab) is False  # Design got auto-activated, not "not_started"
    assert design.state == PHASE_IN_PROGRESS


def test_set_blocked_and_unblock(db_session):
    owner = make_user(db_session, email="owner6@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)
    concept = _phase(lab, "Concept")

    assert svc.set_blocked(db_session, concept, True) is True
    assert concept.state == PHASE_BLOCKED
    # Can't block an already-blocked phase.
    assert svc.set_blocked(db_session, concept, True) is False
    # Can't complete a blocked phase.
    assert svc.complete_phase(db_session, concept, lab) is False

    assert svc.set_blocked(db_session, concept, False) is True
    assert concept.state == PHASE_IN_PROGRESS
    # Can't unblock a phase that isn't blocked.
    assert svc.set_blocked(db_session, concept, False) is False


def test_set_blocked_rejects_done_phase(db_session):
    owner = make_user(db_session, email="owner7@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)
    concept = _phase(lab, "Concept")
    svc.complete_phase(db_session, concept, lab)

    assert svc.set_blocked(db_session, concept, True) is False


def test_archive_and_unarchive_lab(db_session):
    owner = make_user(db_session, email="owner8@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)

    assert svc.archive_lab(db_session, lab, owner.id) is True
    assert lab.archived_at is not None
    assert lab.archived_by_id == owner.id

    assert svc.unarchive_lab(db_session, lab) is True
    assert lab.archived_at is None
    assert lab.archived_by_id is None


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://example.com/doc", True),
        ("http://example.com", True),
        ("javascript:alert(1)", False),
        ("data:text/html,<script>1</script>", False),
        ("not a url", False),
        ("", False),
        ("ftp://example.com/file", False),
    ],
)
def test_is_safe_url(url, expected):
    assert svc.is_safe_url(url) is expected


def test_add_link_rejects_unsafe_url(db_session):
    owner = make_user(db_session, email="owner9@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)

    assert svc.add_link(db_session, lab, url="javascript:alert(1)", label="x",
                        user_id=owner.id) is False
    db_session.refresh(lab)
    assert len(lab.links) == 0

    assert svc.add_link(db_session, lab, url="https://example.com/doc", label="Doc",
                        user_id=owner.id) is True
    db_session.refresh(lab)
    assert len(lab.links) == 1
    assert lab.links[0].label == "Doc"


def test_save_phase_updates_hours_notes_and_tasks(db_session):
    owner = make_user(db_session, email="owner10@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)
    concept = _phase(lab, "Concept")
    task = concept.tasks[0]

    ok = svc.save_phase(
        db_session,
        concept,
        actual_hours=4.5,
        notes="halfway there",
        target_date="2026-01-01",
        task_updates={task.id: {"note": "done via automation", "done": True}},
        user_id=owner.id,
    )
    assert ok is True
    assert concept.actual_hours == 4.5
    assert concept.notes == "halfway there"
    assert concept.target_date == "2026-01-01"
    assert task.done is True
    assert task.done_by_id == owner.id
    assert task.note == "done via automation"

    # Un-checking clears done_by/done_at.
    svc.save_phase(
        db_session, concept, actual_hours=None, notes="", target_date="",
        task_updates={task.id: {"note": "", "done": False}}, user_id=owner.id,
    )
    assert task.done is False
    assert task.done_by_id is None
    assert task.done_at is None
    # actual_hours untouched when None is passed.
    assert concept.actual_hours == 4.5


def test_negative_actual_hours_ignored(db_session):
    owner = make_user(db_session, email="owner11@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)
    concept = _phase(lab, "Concept")

    svc.save_phase(db_session, concept, actual_hours=-5, notes="", target_date="",
                   task_updates={}, user_id=owner.id)
    assert concept.actual_hours == 0.0  # default, unchanged since -5 was rejected
