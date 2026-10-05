"""Abstract editor permissions and persistence."""
import pytest

from app.lab_service import create_lab
from conftest import login


@pytest.mark.parametrize("editor", ["member_user", "admin_user", "manager_user"])
def test_owner_and_staff_get_populated_editor(client, db_session, member_user, request, editor):
    lab = create_lab(db_session, name="Abstract lab", owner_id=member_user.id,
                     abstract="Existing abstract")
    login(client, request.getfixturevalue(editor))
    page = client.get(f"/labs/{lab.id}")
    assert 'id="edit-abstract"' in page.text
    assert 'aria-controls="abstract-form"' in page.text
    assert 'id="abstract-input"' in page.text
    assert "Existing abstract</textarea>" in page.text
    assert "Save abstract" in page.text
    response = client.post(f"/labs/{lab.id}/abstract", data={"abstract": "Updated abstract"})
    assert response.status_code == 200
    db_session.refresh(lab)
    assert lab.abstract == "Updated abstract"


def test_non_owner_only_sees_abstract_once(client, db_session, member_user, manager_user):
    lab = create_lab(db_session, name="Other lab", owner_id=manager_user.id,
                     abstract="Read-only abstract")
    login(client, member_user)
    page = client.get(f"/labs/{lab.id}")
    assert page.text.count("Read-only abstract") == 1
    assert 'id="edit-abstract"' not in page.text
    assert 'id="abstract-form"' not in page.text


def test_empty_abstract_has_editor(client, db_session, member_user):
    lab = create_lab(db_session, name="Empty abstract", owner_id=member_user.id)
    login(client, member_user)
    page = client.get(f"/labs/{lab.id}")
    assert "No abstract yet." in page.text
    assert 'id="edit-abstract"' in page.text
