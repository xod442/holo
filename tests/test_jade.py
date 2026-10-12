import io
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app import config, jade, lab_service
from app.models import JadeRegistration, Lab, PHASE_COMPLETED
from conftest import login, make_user


@pytest.fixture
def configured(monkeypatch):
    for name, value in {
        "JADE_API_URL": "http://jade.example", "JADE_PUBLIC_URL": "https://example.com/jade",
        "PUBLIC_URL": "https://example.com/holo", "JADE_TOKEN": "test-token-" * 4,
        "JADE_SOURCE_ID": "test-installation",
    }.items():
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(jade, "run_loop", lambda stop: stop.wait())


def create(db, owner):
    return lab_service.create_lab(db, name="Test HOL", abstract="Useful lab", owner_id=owner.id)


def success(payload):
    return {
        "id": 42, "record_path": "/assets/42", "source": "HOLO",
        "external_id": payload["external_id"],
    }


def test_disabled_preserves_original_creation(db_session, member_user, monkeypatch):
    monkeypatch.setattr(config, "JADE_API_URL", "")
    monkeypatch.setattr(config, "JADE_TOKEN", "")
    lab = create(db_session, member_user)
    assert db_session.get(Lab, lab.id)
    assert db_session.query(JadeRegistration).count() == 0


def test_atomic_creation_and_updates_excluded(db_session, member_user, configured):
    lab = create(db_session, member_user)
    job = db_session.get(JadeRegistration, lab.id)
    assert job.external_id == f"test-installation:{lab.id}"
    assert job.state == "pending"
    lab_service.create_update(db_session, lab)
    assert db_session.query(JadeRegistration).count() == 1


def test_failed_commit_rolls_back_hol_and_outbox(db_session, member_user, configured, monkeypatch):
    original = db_session.commit
    monkeypatch.setattr(db_session, "commit", Mock(side_effect=SQLAlchemyError("commit failed")))
    with pytest.raises(SQLAlchemyError):
        create(db_session, member_user)
    db_session.rollback()
    monkeypatch.setattr(db_session, "commit", original)
    assert db_session.query(Lab).count() == 0
    assert db_session.query(JadeRegistration).count() == 0


def test_payload_mapping_and_lifecycle(db_session, member_user, configured):
    lab = create(db_session, member_user)
    job = db_session.get(JadeRegistration, lab.id)
    payload = jade.build_payload(lab, job)
    assert payload["creating_team"] == "TRIG"
    assert payload["technology"] == "Mist, Central and OS-CX"
    assert payload["audience"] == ["Systems Engineer"]
    assert payload["access_level"] == "Internal"
    assert payload["owner"] == member_user.email
    assert payload["description"] == lab.abstract
    assert payload["lifecycle_status"] == "Ideation"
    assert payload["content_links"][0]["url"] == f"https://example.com/holo/labs/{lab.id}"
    lab.phases[0].state = PHASE_COMPLETED
    assert jade.build_payload(lab, job)["lifecycle_status"] == "Development"
    for phase in lab.phases:
        phase.state = PHASE_COMPLETED
    assert jade.build_payload(lab, job)["lifecycle_status"] == "Published"
    lab.archived_at = datetime.utcnow()
    assert jade.build_payload(lab, job)["lifecycle_status"] == "Retired"


def test_success_stops_all_future_delivery(db_session, member_user, configured, monkeypatch):
    lab = create(db_session, member_user)
    send = Mock(side_effect=success)
    monkeypatch.setattr(jade, "post_asset", send)
    assert jade.process_one(db_session)
    job = db_session.get(JadeRegistration, lab.id)
    assert job.state == "registered"
    assert job.record_url == "https://example.com/jade/assets/42"
    assert not jade.process_one(db_session)
    assert not jade.retry(db_session, job)
    assert send.call_count == 1


@pytest.mark.parametrize("failure", [
    URLError("offline"),
    HTTPError("http://jade.example", 503, "unavailable", {}, None),
    HTTPError("http://jade.example", 429, "limited", {}, None),
])
def test_transient_failure_retry_after_restart(db_session, member_user, configured, monkeypatch, failure):
    lab = create(db_session, member_user)
    send = Mock(side_effect=failure)
    monkeypatch.setattr(jade, "post_asset", send)
    assert jade.process_one(db_session)
    job = db_session.get(JadeRegistration, lab.id)
    assert job.state == "pending" and job.attempts == 1
    assert job.next_attempt_at > datetime.utcnow()
    assert not jade.process_one(db_session)
    db_session.expire_all()
    job = db_session.get(JadeRegistration, lab.id)
    job.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()
    send.side_effect = success
    assert jade.process_one(db_session)
    assert job.state == "registered" and job.attempts == 2


@pytest.mark.parametrize("status", [301, 401, 403, 404, 422])
def test_permanent_errors_visible_and_retryable(db_session, member_user, configured, monkeypatch, status):
    lab = create(db_session, member_user)
    failure = HTTPError("http://jade.example", status, "rejected", {},
                        io.BytesIO(b'{"detail":"Choose a registered owner"}'))
    monkeypatch.setattr(jade, "post_asset", Mock(side_effect=failure))
    jade.process_one(db_session)
    job = db_session.get(JadeRegistration, lab.id)
    assert job.state == "needs_attention" and job.last_error
    assert config.JADE_TOKEN not in job.last_error
    assert jade.retry(db_session, job)
    db_session.refresh(job)
    assert job.state == "pending"


def test_missing_abstract_recovered_using_current_metadata(db_session, member_user, configured, monkeypatch):
    lab = lab_service.create_lab(db_session, name="Test", owner_id=member_user.id)
    send = Mock(side_effect=success)
    monkeypatch.setattr(jade, "post_asset", send)
    jade.process_one(db_session)
    job = db_session.get(JadeRegistration, lab.id)
    assert job.state == "needs_attention"
    assert "abstract" in job.last_error
    send.assert_not_called()
    lab.abstract = "Now complete"
    db_session.commit()
    jade.retry(db_session, job)
    jade.process_one(db_session)
    assert job.state == "registered"
    assert send.call_args.args[0]["description"] == "Now complete"


def test_expired_lease_reclaimed(db_session, member_user, configured, monkeypatch):
    lab = create(db_session, member_user)
    job = db_session.get(JadeRegistration, lab.id)
    job.state = "processing"
    job.lease_until = datetime.utcnow() + timedelta(minutes=1)
    db_session.commit()
    monkeypatch.setattr(jade, "post_asset", success)
    assert not jade.process_one(db_session)
    job.lease_until = datetime.utcnow() - timedelta(minutes=1)
    db_session.commit()
    assert jade.process_one(db_session)
    assert job.state == "registered"


def test_retry_permissions_and_status_panel(client, db_session, member_user, configured):
    lab = create(db_session, member_user)
    login(client, member_user)
    html = client.get(f"/labs/{lab.id}").text
    assert "Pending JADE registration" in html
    assert "Retry JADE registration" in html
    assert client.post(f"/labs/{lab.id}/jade/retry", follow_redirects=False).status_code == 303
    stranger = make_user(db_session, email="stranger@test.local")
    login(client, stranger)
    assert client.post(f"/labs/{lab.id}/jade/retry").status_code == 403
    assert "Retry JADE registration" not in client.get(f"/labs/{lab.id}").text


@pytest.mark.parametrize("state", ["needs_attention", "registered"])
def test_final_status_panels(client, db_session, member_user, configured, state):
    lab = create(db_session, member_user)
    job = db_session.get(JadeRegistration, lab.id)
    job.state = state
    job.last_error = "Please add an abstract <script>"
    job.jade_asset_id = 42
    job.record_url = "https://example.com/jade/assets/42"
    db_session.commit()
    login(client, member_user)
    html = client.get(f"/labs/{lab.id}").text
    if state == "registered":
        assert "Registered" in html and "EA-00042" in html
        assert 'href="https://example.com/jade/assets/42"' in html
        assert "Retry JADE registration" not in html
    else:
        assert "needs attention" in html
        assert "Please add an abstract &lt;script&gt;" in html
        assert "Retry JADE registration" in html


@pytest.mark.parametrize("url", ["", "file:///tmp/jade", "http://bad host", "http://host:bad",
                                "http://user:secret@host", "https://host?token=bad"])
def test_invalid_configuration_needs_attention(db_session, member_user, configured, monkeypatch, url):
    lab = create(db_session, member_user)
    monkeypatch.setattr(config, "JADE_API_URL", url)
    send = Mock(side_effect=success)
    monkeypatch.setattr(jade, "post_asset", send)
    jade.process_one(db_session)
    assert db_session.get(JadeRegistration, lab.id).state == "needs_attention"
    send.assert_not_called()


def test_delete_hol_cleans_outbox(db_session, member_user, configured):
    lab = create(db_session, member_user)
    lab_id = lab.id
    db_session.delete(lab)
    db_session.commit()
    assert db_session.get(JadeRegistration, lab_id) is None


def test_redirects_refused():
    assert jade.NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere") is None


@pytest.mark.parametrize("body", [b"[]", b"{}", b"not json", b'{"id":true}', b"x" * 65537])
def test_invalid_http_response_rejected(configured, monkeypatch, body):
    response = Mock()
    response.status = 201
    response.read.return_value = body
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(jade, "build_opener", Mock(return_value=opener))
    with pytest.raises(ValueError):
        jade.post_asset({"external_id": "test:1"})
