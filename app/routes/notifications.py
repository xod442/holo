"""Admin: SMTP forwarder config, notification lists, recipients, subscriptions."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import notifier
from ..db import get_db
from ..deps import get_current_user
from ..labs_template import PHASE_TEMPLATE
from ..models import (
    MailConfig,
    NotificationList,
    NotificationRecipient,
    PhaseSubscription,
    STAFF_ROLES,
    NOTIFY_EVENTS,
)
from ..web import templates

router = APIRouter()

PHASE_NAMES = [p["name"] for p in PHASE_TEMPLATE]


def _guard(user):
    if user is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if user.role not in STAFF_ROLES:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return None


def _redirect(msg: str = "", ok: bool = True):
    suffix = f"?ok={1 if ok else 0}&msg={quote(msg)}" if msg else ""
    return RedirectResponse(f"/admin/notifications{suffix}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/notifications", response_class=HTMLResponse)
def notifications_page(request: Request, ok: int = 1, msg: str = "",
                      db: Session = Depends(get_db), user=Depends(get_current_user)):
    blocked = _guard(user)
    if blocked:
        return blocked
    cfg = notifier.get_config(db)
    lists = db.query(NotificationList).order_by(NotificationList.name).all()
    return templates.TemplateResponse(
        request,
        "admin_notifications.html",
        {
            "request": request,
            "user": user,
            "cfg": cfg,
            "lists": lists,
            "phase_names": PHASE_NAMES,
            "events": NOTIFY_EVENTS,
            "msg": msg,
            "ok": bool(ok),
        },
    )


@router.post("/admin/mail")
def save_mail(request: Request, host: str = Form(""), port: int = Form(25),
              mail_from: str = Form(""), default_to: str = Form(""),
              app_base_url: str = Form(""), enabled: str = Form(""),
              db: Session = Depends(get_db), user=Depends(get_current_user)):
    blocked = _guard(user)
    if blocked:
        return blocked
    cfg = notifier.get_config(db)
    cfg.host = host.strip()
    cfg.port = port
    cfg.mail_from = mail_from.strip()
    cfg.default_to = default_to.strip()
    cfg.app_base_url = app_base_url.strip()
    cfg.enabled = enabled == "1"
    db.add(cfg)
    db.commit()
    return _redirect("Mail forwarder settings saved.")


@router.post("/admin/mail/test")
def test_mail(request: Request, to_address: str = Form(""),
              db: Session = Depends(get_db), user=Depends(get_current_user)):
    blocked = _guard(user)
    if blocked:
        return blocked
    ok, message = notifier.send_test(db, to_address)
    return _redirect(message, ok=ok)


@router.post("/admin/lists")
def create_list(request: Request, name: str = Form(...), description: str = Form(""),
                db: Session = Depends(get_db), user=Depends(get_current_user)):
    blocked = _guard(user)
    if blocked:
        return blocked
    if name.strip():
        db.add(NotificationList(name=name.strip(), description=description.strip()))
        db.commit()
    return _redirect("List created.")


@router.post("/admin/lists/{list_id}/delete")
def delete_list(list_id: int, request: Request,
                db: Session = Depends(get_db), user=Depends(get_current_user)):
    blocked = _guard(user)
    if blocked:
        return blocked
    lst = db.get(NotificationList, list_id)
    if lst is not None:
        db.delete(lst)
        db.commit()
    return _redirect("List deleted.")


@router.post("/admin/lists/{list_id}/recipients")
def add_recipient(list_id: int, request: Request, email: str = Form(...),
                  db: Session = Depends(get_db), user=Depends(get_current_user)):
    blocked = _guard(user)
    if blocked:
        return blocked
    email = email.strip().lower()
    lst = db.get(NotificationList, list_id)
    if lst is not None and "@" in email:
        db.add(NotificationRecipient(list_id=lst.id, email=email))
        db.commit()
    return _redirect("Recipient added.")


@router.post("/admin/lists/{list_id}/recipients/{rid}/delete")
def delete_recipient(list_id: int, rid: int, request: Request,
                     db: Session = Depends(get_db), user=Depends(get_current_user)):
    blocked = _guard(user)
    if blocked:
        return blocked
    rec = db.get(NotificationRecipient, rid)
    if rec is not None and rec.list_id == list_id:
        db.delete(rec)
        db.commit()
    return _redirect("Recipient removed.")


@router.post("/admin/lists/{list_id}/subscriptions")
def add_subscription(list_id: int, request: Request, phase_name: str = Form(...),
                     event: str = Form(...), db: Session = Depends(get_db),
                     user=Depends(get_current_user)):
    blocked = _guard(user)
    if blocked:
        return blocked
    lst = db.get(NotificationList, list_id)
    if lst is not None and phase_name in PHASE_NAMES and event in NOTIFY_EVENTS:
        exists = (
            db.query(PhaseSubscription)
            .filter_by(list_id=lst.id, phase_name=phase_name, event=event)
            .first()
        )
        if exists is None:
            db.add(PhaseSubscription(list_id=lst.id, phase_name=phase_name, event=event))
            db.commit()
    return _redirect("Subscription added.")


@router.post("/admin/subscriptions/{sub_id}/delete")
def delete_subscription(sub_id: int, request: Request,
                        db: Session = Depends(get_db), user=Depends(get_current_user)):
    blocked = _guard(user)
    if blocked:
        return blocked
    sub = db.get(PhaseSubscription, sub_id)
    if sub is not None:
        db.delete(sub)
        db.commit()
    return _redirect("Subscription removed.")
