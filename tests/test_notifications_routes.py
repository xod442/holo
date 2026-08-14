"""HTTP-level tests for /admin/notifications: staff guard, mail config,
notification lists/recipients/subscriptions CRUD."""
from app.models import AuditLog, MailConfig, NotificationList, PhaseSubscription

from conftest import login


def test_member_redirected_away_from_notification_routes(client, member_user):
    login(client, member_user)
    for method, path, kwargs in [
        ("get", "/admin/notifications", {}),
        ("post", "/admin/mail", {}),
        ("post", "/admin/mail/test", {}),
        ("post", "/admin/lists", {"data": {"name": "x"}}),
        ("post", "/admin/lists/1/delete", {}),
        ("post", "/admin/lists/1/recipients", {"data": {"email": "a@test.local"}}),
        ("post", "/admin/lists/1/recipients/1/delete", {}),
        ("post", "/admin/lists/1/subscriptions",
         {"data": {"phase_name": "Design", "event": "submitted"}}),
        ("post", "/admin/subscriptions/1/delete", {}),
    ]:
        resp = getattr(client, method)(path, follow_redirects=False, **kwargs)
        assert resp.status_code == 303, f"{method} {path}"
        assert resp.headers["location"] == "/", f"{method} {path}"


def test_staff_can_view_notifications_page(client, admin_user):
    login(client, admin_user)
    assert client.get("/admin/notifications", follow_redirects=False).status_code == 200


def test_save_mail_config_and_audits(client, db_session, admin_user):
    login(client, admin_user)
    resp = client.post(
        "/admin/mail",
        data={
            "host": "smtp.example.com",
            "port": "2525",
            "mail_from": "holo@example.com",
            "default_to": "team@example.com",
            "app_base_url": "https://holo.example.com",
            "enabled": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/admin?ok=1")

    cfg = db_session.get(MailConfig, 1)
    assert cfg.host == "smtp.example.com"
    assert cfg.port == 2525
    assert cfg.enabled is True

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "notifications.mail_config_save")
        .first()
    )
    assert entry is not None


def test_test_mail_reports_missing_config(client, admin_user):
    login(client, admin_user)
    resp = client.post("/admin/mail/test", data={"to_address": "x@test.local"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/admin?ok=0")


def test_test_mail_success(client, db_session, admin_user, fake_smtp):
    cfg = db_session.get(MailConfig, 1)
    cfg.host, cfg.mail_from = "smtp.example.com", "holo@example.com"
    db_session.add(cfg)
    db_session.commit()

    login(client, admin_user)
    resp = client.post("/admin/mail/test", data={"to_address": "x@test.local"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/admin?ok=1")
    assert len(fake_smtp.sent) == 1


def test_create_and_delete_notification_list(client, db_session, admin_user):
    login(client, admin_user)
    resp = client.post("/admin/lists", data={"name": "vLabs Team", "description": "d"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/admin/notifications")

    lst = db_session.query(NotificationList).filter_by(name="vLabs Team").first()
    assert lst is not None

    resp = client.post(f"/admin/lists/{lst.id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert db_session.get(NotificationList, lst.id) is None


def test_create_list_ignores_blank_name(client, db_session, admin_user):
    login(client, admin_user)
    client.post("/admin/lists", data={"name": "   "}, follow_redirects=False)
    assert db_session.query(NotificationList).count() == 0


def test_add_and_delete_recipient(client, db_session, admin_user):
    login(client, admin_user)
    lst = NotificationList(name="Team")
    db_session.add(lst)
    db_session.commit()

    client.post(f"/admin/lists/{lst.id}/recipients", data={"email": "Person@Test.LOCAL"},
               follow_redirects=False)
    db_session.refresh(lst)
    assert len(lst.recipients) == 1
    assert lst.recipients[0].email == "person@test.local"  # lower-cased

    rec_id = lst.recipients[0].id
    client.post(f"/admin/lists/{lst.id}/recipients/{rec_id}/delete", follow_redirects=False)
    db_session.refresh(lst)
    assert len(lst.recipients) == 0


def test_add_recipient_rejects_invalid_email(client, db_session, admin_user):
    login(client, admin_user)
    lst = NotificationList(name="Team")
    db_session.add(lst)
    db_session.commit()

    client.post(f"/admin/lists/{lst.id}/recipients", data={"email": "not-an-email"},
               follow_redirects=False)
    db_session.refresh(lst)
    assert len(lst.recipients) == 0


def test_add_subscription_and_prevent_duplicates(client, db_session, admin_user):
    login(client, admin_user)
    lst = NotificationList(name="Team")
    db_session.add(lst)
    db_session.commit()

    client.post(f"/admin/lists/{lst.id}/subscriptions",
               data={"phase_name": "Design", "event": "submitted"},
               follow_redirects=False)
    client.post(f"/admin/lists/{lst.id}/subscriptions",
               data={"phase_name": "Design", "event": "submitted"},
               follow_redirects=False)

    subs = db_session.query(PhaseSubscription).filter_by(list_id=lst.id).all()
    assert len(subs) == 1  # duplicate ignored


def test_add_subscription_rejects_unknown_phase_or_event(client, db_session, admin_user):
    login(client, admin_user)
    lst = NotificationList(name="Team")
    db_session.add(lst)
    db_session.commit()

    client.post(f"/admin/lists/{lst.id}/subscriptions",
               data={"phase_name": "Not A Phase", "event": "submitted"},
               follow_redirects=False)
    client.post(f"/admin/lists/{lst.id}/subscriptions",
               data={"phase_name": "Design", "event": "not-a-real-event"},
               follow_redirects=False)

    assert db_session.query(PhaseSubscription).filter_by(list_id=lst.id).count() == 0


def test_delete_subscription(client, db_session, admin_user):
    login(client, admin_user)
    lst = NotificationList(name="Team")
    db_session.add(lst)
    db_session.commit()
    sub = PhaseSubscription(list_id=lst.id, phase_name="Design", event="submitted")
    db_session.add(sub)
    db_session.commit()
    sub_id = sub.id

    client.post(f"/admin/subscriptions/{sub_id}/delete", follow_redirects=False)
    assert db_session.get(PhaseSubscription, sub_id) is None
