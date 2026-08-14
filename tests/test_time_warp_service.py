"""Unit tests for app.lab_service.time_warp: fast-forwarding a lab that was
already completed/near-complete before it was tracked in HOLO."""
from app import lab_service as svc
from app.models import (
    PHASE_APPROVED,
    PHASE_COMPLETED,
    PHASE_IN_PROGRESS,
    PHASE_NOT_STARTED,
)

from conftest import make_user


def _phase(lab, name):
    return next(p for p in lab.phases if p.name == name)


def test_time_warp_marks_earlier_phases_done_and_activates_target(db_session):
    owner = make_user(db_session, email="owner@test.local")
    actor = make_user(db_session, email="actor@test.local")
    lab = svc.create_lab(db_session, name="Legacy Lab", owner_id=owner.id)

    # Publish is position 5 (0-based): Concept, Design, Develop, Video Demo,
    # Testing & Feedback, Publish.
    ok, message = svc.time_warp(db_session, lab, target_position=5, actor_id=actor.id)
    assert ok is True
    assert "Legacy Lab" in message and "Publish" in message

    for name in ("Concept", "Design", "Develop", "Video Demo", "Testing & Feedback"):
        phase = _phase(lab, name)
        assert phase.state in (PHASE_COMPLETED, PHASE_APPROVED)
        assert all(t.done for t in phase.tasks)

    publish = _phase(lab, "Publish")
    assert publish.state == PHASE_IN_PROGRESS
    assert not any(t.done for t in publish.tasks)  # target phase left untouched

    for name in ("Production", "Post-Production Acceptance"):
        assert _phase(lab, name).state == PHASE_NOT_STARTED


def test_time_warp_auto_approves_with_approval_record(db_session):
    owner = make_user(db_session, email="owner2@test.local")
    actor = make_user(db_session, email="actor2@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)

    svc.time_warp(db_session, lab, target_position=2, actor_id=actor.id)

    design = _phase(lab, "Design")  # an approval phase
    assert design.requires_approval is True
    assert design.state == PHASE_APPROVED
    assert design.approval is not None
    assert design.approval.approver_id == actor.id
    assert design.approval.note == svc.TIME_WARP_NOTE


def test_time_warp_marks_tasks_done_by_actor(db_session):
    owner = make_user(db_session, email="owner3@test.local")
    actor = make_user(db_session, email="actor3@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)

    svc.time_warp(db_session, lab, target_position=1, actor_id=actor.id)

    concept = _phase(lab, "Concept")
    for task in concept.tasks:
        assert task.done is True
        assert task.done_by_id == actor.id
        assert task.done_at is not None


def test_time_warp_rejects_target_at_or_before_current_phase(db_session):
    owner = make_user(db_session, email="owner4@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)

    # Current phase is Concept (position 0) — position 0 is not "forward".
    ok, message = svc.time_warp(db_session, lab, target_position=0, actor_id=owner.id)
    assert ok is False
    assert "forward" in message.lower()

    concept = _phase(lab, "Concept")
    assert concept.state == PHASE_IN_PROGRESS  # untouched


def test_time_warp_rejects_backward_after_progress(db_session):
    owner = make_user(db_session, email="owner5@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)
    svc.time_warp(db_session, lab, target_position=3, actor_id=owner.id)

    # Now try to warp "backward" to a position behind the new current phase.
    ok, message = svc.time_warp(db_session, lab, target_position=2, actor_id=owner.id)
    assert ok is False
    assert "forward" in message.lower()


def test_time_warp_rejects_out_of_range_position(db_session):
    owner = make_user(db_session, email="owner6@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)

    ok, message = svc.time_warp(db_session, lab, target_position=8, actor_id=owner.id)
    assert ok is False
    assert "invalid" in message.lower()

    ok, message = svc.time_warp(db_session, lab, target_position=-1, actor_id=owner.id)
    assert ok is False


def test_time_warp_rejects_already_complete_lab(db_session):
    owner = make_user(db_session, email="owner7@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)
    # Warp all the way to the last phase, then complete it manually.
    svc.time_warp(db_session, lab, target_position=7, actor_id=owner.id)
    last = _phase(lab, "Post-Production Acceptance")
    svc.complete_phase(db_session, last, lab)

    ok, message = svc.time_warp(db_session, lab, target_position=5, actor_id=owner.id)
    assert ok is False


def test_time_warp_sends_no_notifications(db_session, fake_smtp):
    from app.models import MailConfig, NotificationList, NotificationRecipient, PhaseSubscription

    owner = make_user(db_session, email="owner8@test.local")
    lab = svc.create_lab(db_session, name="Notify Lab", owner_id=owner.id)

    cfg = db_session.get(MailConfig, 1)
    cfg.host, cfg.mail_from, cfg.enabled = "smtp.test.local", "holo@test.local", True
    db_session.add(cfg)
    lst = NotificationList(name="Team")
    db_session.add(lst)
    db_session.flush()
    db_session.add(NotificationRecipient(list_id=lst.id, email="watcher@test.local"))
    for phase_name in ("Design", "Develop", "Testing & Feedback"):
        db_session.add(PhaseSubscription(list_id=lst.id, phase_name=phase_name, event="approved"))
        db_session.add(PhaseSubscription(list_id=lst.id, phase_name=phase_name, event="submitted"))
    db_session.commit()

    svc.time_warp(db_session, lab, target_position=5, actor_id=owner.id)

    assert fake_smtp.sent == []  # Time Warp is silent, unlike real transitions


def test_time_warp_does_not_touch_already_done_phase_state(db_session):
    """If part of the lab was warped/advanced already, re-running past it
    shouldn't clobber an existing Approval record with a second one."""
    owner = make_user(db_session, email="owner9@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)
    design = _phase(lab, "Design")

    concept = _phase(lab, "Concept")
    svc.complete_phase(db_session, concept, lab)
    svc.submit_phase(db_session, design, lab)
    svc.approve_phase(db_session, design, lab, approver_id=owner.id, note="real approval")

    svc.time_warp(db_session, lab, target_position=3, actor_id=owner.id)

    assert design.approval.note == "real approval"  # not overwritten by Time Warp
