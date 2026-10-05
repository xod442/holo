"""New-lab and existing-record coverage for the Dev 3 task."""
from datetime import datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import backup, db
from app.lab_service import create_lab
from app.models import Approval, Lab, PHASE_APPROVED, Task


TITLES = [
    "Prototype", "Automation Pre-Requirements", "Git Repo Request",
    "Lab Guide Development", "Objective Mapping and Timing", "Development Approval",
]


def test_new_lab_has_ordered_git_repo_task(db_session):
    lab = create_lab(db_session, name="New lab", owner_id=None)
    tasks = lab.phases[2].tasks
    assert [task.title for task in tasks] == TITLES
    assert [task.position for task in tasks] == list(range(6))
    assert not tasks[2].done


def _make_legacy_lab(session, *, archived=False):
    lab = create_lab(session, name="Legacy lab", owner_id=None)
    phase = lab.phases[2]
    for task in phase.tasks:
        if task.title == "Git Repo Request":
            session.delete(task)
        else:
            if task.position > 2:
                task.position -= 1
            task.note = f"Preserved note {task.id}"
            task.done = True
            task.done_at = datetime(2026, 1, 2)
    phase.state = PHASE_APPROVED
    phase.actual_hours = 17
    phase.notes = "Preserved phase note"
    session.add(Approval(phase_id=phase.id, note="Preserved approval"))
    if archived:
        lab.archived_at = datetime(2026, 1, 3)
    session.commit()
    session.expire_all()
    return lab


def _snapshot(session):
    return [
        (t.id, t.phase_id, t.title, t.note, t.done, t.done_by_id, t.done_at)
        for t in session.scalars(select(Task).order_by(Task.id))
    ]


@pytest.mark.parametrize("archived", [False, True])
def test_backfill_preserves_records_and_is_idempotent(db_session, monkeypatch, archived):
    lab = _make_legacy_lab(db_session, archived=archived)
    phase = lab.phases[2]
    previous = _snapshot(db_session)
    monkeypatch.setattr(db, "engine", db_session.get_bind())

    db._ensure_columns()
    db_session.expire_all()
    assert [t.title for t in phase.tasks] == TITLES
    assert [t.position for t in phase.tasks] == list(range(6))
    task = phase.tasks[2]
    assert (task.done, task.note, task.done_by_id, task.done_at) == (False, "", None, None)
    assert [row for row in _snapshot(db_session) if row[0] != task.id] == previous
    assert phase.state == PHASE_APPROVED
    assert phase.actual_hours == 17
    assert phase.notes == "Preserved phase note"
    assert phase.approval.note == "Preserved approval"
    assert bool(lab.archived_at) == archived

    after = _snapshot(db_session)
    db._ensure_columns()
    db_session.expire_all()
    assert _snapshot(db_session) == after
    assert [t.position for t in phase.tasks] == list(range(6))


def test_restore_backfills_old_backup(backup_env):
    with Session(db.engine) as session:
        lab_id = _make_legacy_lab(session, archived=True).id
    snapshot = backup.make_backup()
    with db.engine.begin() as conn:
        conn.execute(delete(Lab))
    backup.restore_from(snapshot)
    with Session(db.engine) as session:
        lab = session.get(Lab, lab_id)
        assert lab is not None
        assert lab.archived_at is not None
        assert [t.title for t in lab.phases[2].tasks] == TITLES
        assert not lab.phases[2].tasks[2].done
