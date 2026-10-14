"""Expanded phase editors reuse the complete, persistent inline pill form."""
from html.parser import HTMLParser

import pytest

from app import lab_service as svc
from conftest import login


class EditorParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


@pytest.mark.parametrize("production_only", [False, True])
@pytest.mark.parametrize("editor", ["member_user", "admin_user", "manager_user"])
def test_every_pill_has_expand_and_complete_save_form(
    client, db_session, member_user, request, production_only, editor,
):
    source = svc.create_lab(db_session, name="Expanded editor", owner_id=member_user.id)
    lab = svc.create_update(db_session, source) if production_only else source
    login(client, request.getfixturevalue(editor))
    response = client.get(f"/labs/{lab.id}")
    assert response.status_code == 200
    parser = EditorParser()
    parser.feed(response.text)
    buttons = [attrs for tag, attrs in parser.elements
               if tag == "button" and "expand-pill" in attrs.get("class", "").split()]
    assert len(buttons) == (4 if production_only else 8)
    assert all(button["type"] == "button" and button["aria-haspopup"] == "dialog"
               and button["aria-controls"] == "pill-dialog" for button in buttons)
    assert sum(tag == "dialog" and attrs.get("id") == "pill-dialog"
               for tag, attrs in parser.elements) == 1
    for phase in lab.phases:
        action = f"/labs/{lab.id}/phases/{phase.id}/save"
        assert sum(tag == "form" and attrs.get("action") == action
                   for tag, attrs in parser.elements) == 1
        form = response.text.split(f'action="{action}"', 1)[1].split("</form>", 1)[0]
        assert 'type="submit">Save</button>' in form
        for name in ("notes", "actual_hours", "target_date"):
            assert f'name="{name}"' in form
        for task in phase.tasks:
            assert f'name="done_{task.id}"' in form
            assert f'<textarea class="task-note" name="note_{task.id}"' in form
    assert 'src="/assets/phase-editor.js?v=' in response.text


@pytest.mark.parametrize("production_only", [False, True])
def test_expanded_save_persists_multiline_notes_and_other_fields(
    client, db_session, member_user, production_only,
):
    source = svc.create_lab(db_session, name="Save expanded notes", owner_id=member_user.id)
    lab = svc.create_update(db_session, source) if production_only else source
    login(client, member_user)
    for phase in lab.phases:
        notes = f"{phase.name}\nLong phase notes with <markup> & details."
        task_notes = {task.id: f"{task.title}\nTask details & <notes>."
                      for task in phase.tasks}
        data = {"notes": notes, "actual_hours": "2.5", "target_date": "2026-11-15"}
        data.update({f"note_{task_id}": note for task_id, note in task_notes.items()})
        response = client.post(f"/labs/{lab.id}/phases/{phase.id}/save",
                               data=data, follow_redirects=False)
        assert response.status_code == 303
        db_session.refresh(phase)
        assert phase.notes == notes
        assert phase.actual_hours == 2.5
        assert phase.target_date == "2026-11-15"
        assert all(task.note == task_notes[task.id] and not task.done for task in phase.tasks)
    page = client.get(f"/labs/{lab.id}").text
    assert "&lt;markup&gt; &amp; details." in page
    assert "&amp; &lt;notes&gt;." in page
