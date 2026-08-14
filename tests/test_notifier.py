"""Unit tests for app.notifier: SMTP forwarding and phase-event dispatch.

`smtplib.SMTP` is monkeypatched (via the shared `fake_smtp` fixture) with an
in-memory fake so no real network connection is attempted.
"""
import pytest

from app import notifier
from app.models import MailConfig, NotificationList, NotificationRecipient, PhaseSubscription

from conftest import FakeSMTP


@pytest.fixture(autouse=True)
def _smtp(fake_smtp):
    return fake_smtp


def _configured_cfg(db_session, **overrides) -> MailConfig:
    cfg = db_session.get(MailConfig, 1)
    cfg.host = "smtp.test.local"
    cfg.mail_from = "holo@test.local"
    cfg.default_to = "default@test.local"
    for key, value in overrides.items():
        setattr(cfg, key, value)
    db_session.add(cfg)
    db_session.commit()
    return cfg


def test_send_test_requires_host(db_session):
    ok, message = notifier.send_test(db_session, "someone@test.local")
    assert ok is False
    assert "forwarder host" in message


def test_send_test_requires_mail_from(db_session):
    cfg = db_session.get(MailConfig, 1)
    cfg.host = "smtp.test.local"
    db_session.add(cfg)
    db_session.commit()

    ok, message = notifier.send_test(db_session, "someone@test.local")
    assert ok is False
    assert "from" in message.lower()


def test_send_test_requires_a_recipient(db_session):
    _configured_cfg(db_session, default_to="")
    ok, message = notifier.send_test(db_session, "")
    assert ok is False
    assert "recipient" in message.lower()


def test_send_test_success_falls_back_to_default_to(db_session):
    _configured_cfg(db_session)
    ok, message = notifier.send_test(db_session, "")
    assert ok is True
    assert "default@test.local" in message
    assert len(FakeSMTP.sent) == 1
    assert FakeSMTP.sent[0]["To"] == "default@test.local"


def test_send_test_surfaces_relay_failure(db_session):
    _configured_cfg(db_session)
    FakeSMTP.connect_error = True
    ok, message = notifier.send_test(db_session, "someone@test.local")
    assert ok is False
    assert "Send failed" in message


def test_send_requires_valid_recipient(db_session):
    _configured_cfg(db_session)
    ok, message = notifier.send(db_session, "not-an-email", "Subject", "Body")
    assert ok is False
    assert "recipient" in message.lower()
    assert FakeSMTP.sent == []


def test_send_success(db_session):
    _configured_cfg(db_session)
    ok, message = notifier.send(db_session, "someone@test.local", "Hi", "Body text")
    assert ok is True
    assert len(FakeSMTP.sent) == 1
    sent = FakeSMTP.sent[0]
    assert sent["To"] == "someone@test.local"
    assert sent["Subject"] == "Hi"


def test_notify_phase_event_noop_when_disabled(db_session):
    _configured_cfg(db_session, enabled=False)

    class DummyLab:
        id, name = 1, "Lab"

    class DummyPhase:
        name, stage = "Design", "Development"

    notifier.notify_phase_event(db_session, DummyLab(), DummyPhase(), "submitted")
    assert FakeSMTP.sent == []


def test_notify_phase_event_noop_when_no_subscribers(db_session):
    _configured_cfg(db_session, enabled=True)

    class DummyLab:
        id, name = 1, "Lab"

    class DummyPhase:
        name, stage = "Design", "Development"

    notifier.notify_phase_event(db_session, DummyLab(), DummyPhase(), "submitted")
    assert FakeSMTP.sent == []


def test_notify_phase_event_sends_to_subscribed_list(db_session):
    _configured_cfg(db_session, enabled=True, app_base_url="https://holo.test")
    lst = NotificationList(name="vLabs Team")
    db_session.add(lst)
    db_session.flush()
    db_session.add(NotificationRecipient(list_id=lst.id, email="a@test.local"))
    db_session.add(NotificationRecipient(list_id=lst.id, email="b@test.local"))
    db_session.add(PhaseSubscription(list_id=lst.id, phase_name="Design", event="submitted"))
    db_session.commit()

    class DummyLab:
        id, name = 42, "Networking 101"

    class DummyPhase:
        name, stage = "Design", "Development"

    notifier.notify_phase_event(db_session, DummyLab(), DummyPhase(), "submitted")

    assert len(FakeSMTP.sent) == 1
    sent = FakeSMTP.sent[0]
    assert sent["To"] == "a@test.local, b@test.local"
    assert "Networking 101" in sent["Subject"]
    body = sent.get_content()
    assert "https://holo.test/labs/42" in body


def test_notify_phase_event_ignores_other_phase_or_event(db_session):
    _configured_cfg(db_session, enabled=True)
    lst = NotificationList(name="vLabs Team")
    db_session.add(lst)
    db_session.flush()
    db_session.add(NotificationRecipient(list_id=lst.id, email="a@test.local"))
    db_session.add(PhaseSubscription(list_id=lst.id, phase_name="Design", event="approved"))
    db_session.commit()

    class DummyLab:
        id, name = 1, "Lab"

    class DummyPhase:
        name, stage = "Design", "Development"

    # Subscribed to "approved", but this event is "submitted" — no match.
    notifier.notify_phase_event(db_session, DummyLab(), DummyPhase(), "submitted")
    assert FakeSMTP.sent == []


def test_notify_phase_event_swallows_send_failure(db_session):
    _configured_cfg(db_session, enabled=True)
    lst = NotificationList(name="vLabs Team")
    db_session.add(lst)
    db_session.flush()
    db_session.add(NotificationRecipient(list_id=lst.id, email="a@test.local"))
    db_session.add(PhaseSubscription(list_id=lst.id, phase_name="Design", event="submitted"))
    db_session.commit()
    FakeSMTP.connect_error = True

    class DummyLab:
        id, name = 1, "Lab"

    class DummyPhase:
        name, stage = "Design", "Development"

    # Must not raise — failures are logged and swallowed.
    notifier.notify_phase_event(db_session, DummyLab(), DummyPhase(), "submitted")
