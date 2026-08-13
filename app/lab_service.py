"""Lab lifecycle: create-from-template, gated transitions, and progress helpers.

Two kinds of phase:
- requires_approval=True  → Start → Submit → admin Approve  (Design, Develop,
  Testing & Feedback, Production)
- requires_approval=False → Start → user clicks Completed    (Concept, Video Demo,
  Publish, Post-Production Acceptance)
Both "approved" and "completed" count as done for gating and progress.
"""
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from . import notifier
from .labs_template import PHASE_TEMPLATE
from .models import (
    Approval,
    Lab,
    LabLink,
    Phase,
    Task,
    NOTIFY_APPROVED,
    NOTIFY_COMPLETED,
    NOTIFY_SUBMITTED,
    PHASE_APPROVED,
    PHASE_AWAITING,
    PHASE_BLOCKED,
    PHASE_COMPLETED,
    PHASE_DONE_STATES,
    PHASE_IN_PROGRESS,
    PHASE_NOT_STARTED,
)


def create_lab(db: Session, *, name: str, owner_id: int | None,
               description: str = "", target_release: str = "",
               course_id: str = "") -> Lab:
    """Create a lab and clone the phase template onto it (first phase active)."""
    lab = Lab(
        name=name.strip(),
        owner_id=owner_id,
        course_id=course_id.strip(),
        description=description.strip(),
        target_release=target_release.strip(),
    )
    db.add(lab)
    db.flush()  # assign lab.id

    for i, tpl in enumerate(PHASE_TEMPLATE):
        phase = Phase(
            lab_id=lab.id,
            position=i,
            stage=tpl["stage"],
            name=tpl["name"],
            estimated_hours=tpl["estimated_hours"],
            requires_approval=tpl["requires_approval"],
            state=PHASE_IN_PROGRESS if i == 0 else PHASE_NOT_STARTED,
        )
        db.add(phase)
        db.flush()
        for j, title in enumerate(tpl["tasks"]):
            db.add(Task(phase_id=phase.id, position=j, title=title))

    db.commit()
    db.refresh(lab)
    return lab


# --- Read helpers -----------------------------------------------------------

def progress(lab: Lab) -> dict:
    total = len(lab.phases)
    done = sum(1 for p in lab.phases if p.state in PHASE_DONE_STATES)
    return {
        "done": done,
        "total": total,
        "percent": round(100 * done / total) if total else 0,
    }


def current_phase(lab: Lab) -> Phase | None:
    """First phase not yet done — the one the lab is 'on'."""
    for p in lab.phases:
        if p.state not in PHASE_DONE_STATES:
            return p
    return None


def lab_status(lab: Lab) -> str:
    if any(p.state == PHASE_BLOCKED for p in lab.phases):
        return "Blocked"
    if lab.phases and all(p.state in PHASE_DONE_STATES for p in lab.phases):
        return "Complete"
    return "In Progress"


def hours_summary(lab: Lab) -> dict:
    est = sum(p.estimated_hours or 0 for p in lab.phases)
    act = sum(p.actual_hours or 0 for p in lab.phases)
    return {"estimated": est, "actual": act}


def can_start(phase: Phase, lab: Lab) -> bool:
    """A phase may start only once every earlier phase is done."""
    if phase.state != PHASE_NOT_STARTED:
        return False
    earlier = [p for p in lab.phases if p.position < phase.position]
    return all(p.state in PHASE_DONE_STATES for p in earlier)


# --- Transitions (return True if applied) -----------------------------------

def _activate_next(db: Session, phase: Phase, lab: Lab) -> None:
    nxt = next((p for p in lab.phases if p.position == phase.position + 1), None)
    if nxt is not None and nxt.state == PHASE_NOT_STARTED:
        nxt.state = PHASE_IN_PROGRESS
        db.add(nxt)


def start_phase(db: Session, phase: Phase, lab: Lab) -> bool:
    if not can_start(phase, lab):
        return False
    phase.state = PHASE_IN_PROGRESS
    db.add(phase)
    db.commit()
    return True


def submit_phase(db: Session, phase: Phase, lab: Lab) -> bool:
    """Send an approval-phase for admin sign-off."""
    if phase.state != PHASE_IN_PROGRESS or not phase.requires_approval:
        return False
    phase.state = PHASE_AWAITING
    db.add(phase)
    db.commit()
    notifier.notify_phase_event(db, lab, phase, NOTIFY_SUBMITTED)
    return True


def complete_phase(db: Session, phase: Phase, lab: Lab) -> bool:
    """Mark a non-approval phase done and activate the next phase."""
    if phase.state != PHASE_IN_PROGRESS or phase.requires_approval:
        return False
    phase.state = PHASE_COMPLETED
    db.add(phase)
    _activate_next(db, phase, lab)
    db.commit()
    notifier.notify_phase_event(db, lab, phase, NOTIFY_COMPLETED)
    return True


def approve_phase(db: Session, phase: Phase, lab: Lab, approver_id: int,
                  note: str = "") -> bool:
    """Approve a phase awaiting sign-off and activate the next one (the gate)."""
    if phase.state != PHASE_AWAITING:
        return False
    phase.state = PHASE_APPROVED
    db.add(phase)
    db.add(Approval(phase_id=phase.id, approver_id=approver_id, note=note.strip()))
    _activate_next(db, phase, lab)
    db.commit()
    notifier.notify_phase_event(db, lab, phase, NOTIFY_APPROVED)
    return True


def set_blocked(db: Session, phase: Phase, blocked: bool) -> bool:
    if blocked:
        if phase.state in PHASE_DONE_STATES or phase.state == PHASE_BLOCKED:
            return False
        phase.state = PHASE_BLOCKED
    else:
        if phase.state != PHASE_BLOCKED:
            return False
        phase.state = PHASE_IN_PROGRESS
    db.add(phase)
    db.commit()
    return True


def set_course_id(db: Session, lab: Lab, course_id: str) -> bool:
    """Set/clear the HPE course ID on a lab."""
    lab.course_id = course_id.strip()
    db.add(lab)
    db.commit()
    return True


def archive_lab(db: Session, lab: Lab, user_id: int) -> bool:
    lab.archived_at = datetime.utcnow()
    lab.archived_by_id = user_id
    db.add(lab)
    db.commit()
    return True


def unarchive_lab(db: Session, lab: Lab) -> bool:
    lab.archived_at = None
    lab.archived_by_id = None
    db.add(lab)
    db.commit()
    return True


def set_owner(db: Session, lab: Lab, owner_id: int | None) -> bool:
    lab.owner_id = owner_id
    db.add(lab)
    db.commit()
    return True


def save_phase(db: Session, phase: Phase, *, actual_hours: float | None,
               notes: str, target_date: str, task_updates: dict[int, dict],
               user_id: int) -> bool:
    """Save the whole pill in one shot: target date, hours, phase notes, and
    every step's checkbox + note. `task_updates` maps task id -> {note, done}."""
    if actual_hours is not None and actual_hours >= 0:
        phase.actual_hours = float(actual_hours)
    phase.notes = (notes or "").strip()
    phase.target_date = (target_date or "").strip()

    for task in phase.tasks:
        upd = task_updates.get(task.id)
        if upd is None:
            continue
        task.note = (upd.get("note") or "").strip()
        new_done = bool(upd.get("done"))
        if new_done and not task.done:
            task.done = True
            task.done_by_id = user_id
            task.done_at = datetime.utcnow()
        elif not new_done and task.done:
            task.done = False
            task.done_by_id = None
            task.done_at = None
        db.add(task)

    db.add(phase)
    db.commit()
    return True


# --- Document / resource links ----------------------------------------------

def is_safe_url(url: str) -> bool:
    """Only allow real http(s) links (blocks javascript:, data:, etc.)."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def add_link(db: Session, lab: Lab, *, url: str, label: str, user_id: int) -> bool:
    url = url.strip()
    if not is_safe_url(url):
        return False
    label = (label or "").strip() or url
    db.add(LabLink(lab_id=lab.id, url=url, label=label, added_by_id=user_id))
    db.commit()
    return True


def delete_link(db: Session, link: LabLink) -> bool:
    db.delete(link)
    db.commit()
    return True
