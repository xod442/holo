"""Dashboard filters use current-phase state and preserve owner filtering."""
from datetime import datetime

import pytest

from app.lab_service import create_lab
from app.models import PHASE_APPROVED, PHASE_COMPLETED
from conftest import login


@pytest.fixture()
def portfolio(db_session, member_user, manager_user):
    labs = {}
    for state in ("approved", "completed", "awaiting_approval", "in_progress", "not_started", "blocked"):
        lab = create_lab(db_session, name=f"FilterLab-{state}", owner_id=member_user.id)
        if state in ("approved", "completed"):
            for phase in lab.phases:
                phase.state = PHASE_APPROVED if phase.requires_approval else PHASE_COMPLETED
            lab.phases[-1].state = state
        else:
            lab.phases[0].state = PHASE_COMPLETED
            lab.phases[1].state = state
        labs[state] = lab
    other = create_lab(db_session, name="OtherOwnerLab", owner_id=manager_user.id)
    other.phases[0].state = "blocked"
    archived = create_lab(db_session, name="ArchivedFilterLab", owner_id=member_user.id)
    archived.archived_at = datetime(2026, 10, 5)
    archived.phases[0].state = "blocked"
    db_session.commit()
    return labs


@pytest.mark.parametrize("state", [
    "approved", "completed", "awaiting_approval", "in_progress", "not_started", "blocked",
])
def test_status_matches_only_current_or_final_phase(client, portfolio, member_user, state):
    login(client, member_user)
    response = client.get("/", params={"owner": member_user.id, "phase_state": state})
    assert response.status_code == 200
    for candidate in portfolio:
        assert (f"FilterLab-{candidate}" in response.text) == (candidate == state)
    assert "OtherOwnerLab" not in response.text
    assert "ArchivedFilterLab" not in response.text
    assert "1 of 7 labs" in response.text
    assert f'value="{state}" selected' in response.text


def test_unfinished_excludes_only_fully_finished_labs(client, portfolio, member_user):
    login(client, member_user)
    response = client.get("/", params={"phase_state": "unfinished"})
    assert "FilterLab-approved" not in response.text
    assert "FilterLab-completed" not in response.text
    for state in ("awaiting_approval", "in_progress", "not_started", "blocked"):
        assert f"FilterLab-{state}" in response.text
    assert "OtherOwnerLab" in response.text
    assert "5 of 7 labs" in response.text
    assert "ArchivedFilterLab" not in response.text
    all_labs = client.get("/")
    assert "7 of 7 labs" in all_labs.text


def test_unassigned_and_empty_results(client, db_session, member_user):
    lab = create_lab(db_session, name="UnassignedBlocked", owner_id=None)
    lab.phases[0].state = "blocked"
    db_session.commit()
    login(client, member_user)
    assert "UnassignedBlocked" in client.get(
        "/", params={"owner": "unassigned", "phase_state": "blocked"},
    ).text
    page = client.get("/", params={"owner": "unassigned", "phase_state": "completed"})
    assert "No labs match these filters." in page.text
    assert "Show all labs" in page.text


def test_invalid_filter_is_rejected(client, member_user):
    login(client, member_user)
    assert client.get("/", params={"phase_state": "invalid"}).status_code == 400
