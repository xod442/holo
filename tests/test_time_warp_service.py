"""Unit tests for app.lab_service.time_warp_to_task: fast-forwarding a lab
that was already completed/near-complete before it was tracked in HOLO, to
any sub-process pill on the Mallmanac (not just a whole phase)."""
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


def _task(phase, title):
    return next(t for t in phase.tasks if t.title == title)


def test_warp_partway_through_a_phase_leaves_it_in_progress(db_session):
    owner = make_user(db_session, email="owner@test.local")
    actor = make_user(db_session, email="actor@test.local")
    lab = svc.create_lab(db_session, name="Legacy Lab", owner_id=owner.id)

    design = _phase(lab, "Design")
    target = _task(design, "Hardware & Software Requirements")  # 2nd of 4 tasks
    ok, message = svc.time_warp_to_task(db_session, lab, target.id, actor_id=actor.id)
    assert ok is True
    assert "Legacy Lab" in message and "Design" in message and target.title in message

    concept = _phase(lab, "Concept")
    assert concept.state == PHASE_COMPLETED
    assert all(t.done for t in concept.tasks)

    assert design.state == PHASE_IN_PROGRESS  # not auto-approved — landed mid-phase
    ordered = sorted(design.tasks, key=lambda t: t.position)
    assert ordered[0].done is True
    assert ordered[1].done is True   # the target itself
    assert ordered[2].done is False  # later tasks in the same phase untouched
    assert ordered[3].done is False

    for name in ("Develop", "Video Demo"):
        assert _phase(lab, name).state == PHASE_NOT_STARTED


def test_warp_to_a_task_in_a_later_phase_auto_approves_everything_before(db_session):
    owner = make_user(db_session, email="owner2@test.local")
    actor = make_user(db_session, email="actor2@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)

    publish = _phase(lab, "Publish")
    target = _task(publish, "Course Documentation")
    ok, _ = svc.time_warp_to_task(db_session, lab, target.id, actor_id=actor.id)
    assert ok is True

    for name in ("Concept", "Design", "Develop", "Video Demo", "Testing & Feedback"):
        phase = _phase(lab, name)
        assert phase.state in (PHASE_COMPLETED, PHASE_APPROVED)
        assert all(t.done for t in phase.tasks)

    design = _phase(lab, "Design")  # an approval phase auto-closed along the way
    assert design.approval is not None
    assert design.approval.approver_id == actor.id
    assert design.approval.note == svc.TIME_WARP_NOTE

    assert publish.state == PHASE_IN_PROGRESS
    ordered = sorted(publish.tasks, key=lambda t: t.position)
    assert ordered[0].done and ordered[1].done and ordered[2].done  # up through target
    assert ordered[3].done is False  # "Publishing Approval" — after the target


def test_warp_marks_tasks_done_by_actor_with_timestamp(db_session):
    owner = make_user(db_session, email="owner3@test.local")
    actor = make_user(db_session, email="actor3@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)

    concept = _phase(lab, "Concept")
    target = _task(concept, "Stakeholder Discussion")
    svc.time_warp_to_task(db_session, lab, target.id, actor_id=actor.id)

    for task in concept.tasks:
        if task.position <= target.position:
            assert task.done is True
            assert task.done_by_id == actor.id
            assert task.done_at is not None


def test_warp_to_very_first_task_on_a_fresh_lab_is_valid(db_session):
    """Nothing done yet (current index -1) — the first pill is a legitimate
    forward target, e.g. marking "we've at least started this."""
    owner = make_user(db_session, email="owner4b@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)
    concept = _phase(lab, "Concept")
    first = _task(concept, "Topic / High-Level Overview")

    ok, _ = svc.time_warp_to_task(db_session, lab, first.id, actor_id=owner.id)
    assert ok is True
    assert first.done is True
    assert concept.state == PHASE_IN_PROGRESS


def test_warp_rejects_same_or_earlier_task(db_session):
    owner = make_user(db_session, email="owner4@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)
    concept = _phase(lab, "Concept")
    first = _task(concept, "Topic / High-Level Overview")
    second = _task(concept, "Stakeholder Discussion")

    # Warp forward once...
    ok, _ = svc.time_warp_to_task(db_session, lab, second.id, actor_id=owner.id)
    assert ok is True

    # ...then re-targeting the same task, or an earlier one, must be rejected.
    ok, message = svc.time_warp_to_task(db_session, lab, second.id, actor_id=owner.id)
    assert ok is False
    assert "forward" in message.lower()

    ok, message = svc.time_warp_to_task(db_session, lab, first.id, actor_id=owner.id)
    assert ok is False
    assert "forward" in message.lower()


def test_warp_rejects_backward_after_progress(db_session):
    owner = make_user(db_session, email="owner5@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)
    develop = _phase(lab, "Develop")
    target = _task(develop, "Prototype")
    svc.time_warp_to_task(db_session, lab, target.id, actor_id=owner.id)

    # Try to warp "backward" into the already-closed Design phase.
    design = _phase(lab, "Design")
    earlier = _task(design, "Objectives")
    ok, message = svc.time_warp_to_task(db_session, lab, earlier.id, actor_id=owner.id)
    assert ok is False
    assert "forward" in message.lower() or "complete" in message.lower()


def test_warp_rejects_invalid_task_id(db_session):
    owner = make_user(db_session, email="owner6@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)

    ok, message = svc.time_warp_to_task(db_session, lab, 999999, actor_id=owner.id)
    assert ok is False
    assert "invalid" in message.lower()


def test_warp_rejects_task_in_already_complete_phase(db_session):
    owner = make_user(db_session, email="owner7@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)
    last = _phase(lab, "Post-Production Acceptance")
    last_task = _task(last, "Course Complete")
    svc.time_warp_to_task(db_session, lab, last_task.id, actor_id=owner.id)
    svc.complete_phase(db_session, last, lab)

    # Re-targeting an earlier, unchecked task in that now-complete phase
    # must not reopen it.
    earlier_task = _task(last, "Train-the-Trainer")
    ok, message = svc.time_warp_to_task(db_session, lab, earlier_task.id, actor_id=owner.id)
    assert ok is False


def test_warp_sends_no_notifications(db_session, fake_smtp):
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

    publish = _phase(lab, "Publish")
    target = _task(publish, "Digital Lab Guide")
    svc.time_warp_to_task(db_session, lab, target.id, actor_id=owner.id)

    assert fake_smtp.sent == []  # Time Warp is silent, unlike real transitions


def test_warp_does_not_clobber_a_real_approval_record(db_session):
    """If part of the lab already progressed for real, warping past it
    shouldn't overwrite an existing Approval record with an auto one."""
    owner = make_user(db_session, email="owner9@test.local")
    lab = svc.create_lab(db_session, name="Lab", owner_id=owner.id)
    design = _phase(lab, "Design")

    concept = _phase(lab, "Concept")
    svc.complete_phase(db_session, concept, lab)
    svc.submit_phase(db_session, design, lab)
    svc.approve_phase(db_session, design, lab, approver_id=owner.id, note="real approval")

    develop = _phase(lab, "Develop")
    target = _task(develop, "Prototype")
    svc.time_warp_to_task(db_session, lab, target.id, actor_id=owner.id)

    assert design.approval.note == "real approval"  # not overwritten by Time Warp
