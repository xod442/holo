"""Home + admin console (user list, invite creation, pending invite links)."""
from datetime import datetime, timedelta

import os
import secrets
import tempfile
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import backup, config, notifier
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Invite, VALID_ROLES, ROLE_MEMBER, STAFF_ROLES
from ..security import generate_token, hash_password
from ..web import templates

router = APIRouter()


def _register_link(request: Request, token: str) -> str:
    return f"{str(request.base_url).rstrip('/')}/register?token={token}"


def _render_admin_home(request, db, user, new_invite_link=None, new_invite_id=None,
                       reset_info=None, msg="", ok=True):
    users = db.query(User).order_by(User.created_at).all()
    now = datetime.utcnow()
    pending = (
        db.query(Invite)
        .filter(Invite.used_at.is_(None), Invite.expires_at > now)
        .order_by(Invite.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "admin_home.html",
        {
            "request": request,
            "user": user,
            "users": users,
            "pending": pending,
            "register_base": f"{str(request.base_url).rstrip('/')}/register?token=",
            "new_invite_link": new_invite_link,
            "new_invite_id": new_invite_id,
            "reset_info": reset_info,
            "cfg": notifier.get_config(db),
            "backups": backup.list_backups(),
            "msg": msg,
            "ok": ok,
        },
    )


@router.get("/admin", response_class=HTMLResponse)
def admin_console(request: Request, ok: int = 1, msg: str = "",
                  db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if user.role not in STAFF_ROLES:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return _render_admin_home(request, db, user, msg=msg, ok=bool(ok))


@router.post("/admin/backup")
def backup_now(request: Request, db: Session = Depends(get_db),
               user=Depends(get_current_user)):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    try:
        path = backup.make_backup()
        import os
        return RedirectResponse(
            f"/admin?ok=1&msg={quote('Backup created: ' + os.path.basename(path))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:  # noqa: BLE001 — surface backup failure to the admin
        return RedirectResponse(
            f"/admin?ok=0&msg={quote('Backup failed: ' + str(exc))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.get("/admin/backup/download/{name}")
def download_backup(name: str, request: Request, db: Session = Depends(get_db),
                    user=Depends(get_current_user)):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    path = backup.safe_path(name)
    if path is None:
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
    return FileResponse(path, filename=name, media_type="application/octet-stream")


def _do_restore(source_path: str, label: str) -> RedirectResponse:
    """Validate, safety-backup the current DB, then restore. Returns a redirect."""
    ok, why = backup.is_valid_holo_db(source_path)
    if not ok:
        return RedirectResponse(
            f"/admin?ok=0&msg={quote('Restore rejected: ' + why)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    backup.make_backup()          # safety snapshot of current DB
    backup.restore_from(source_path)
    return RedirectResponse(
        f"/admin?ok=1&msg={quote('Database restored from ' + label + '. A safety backup was taken first — you may need to sign in again.')}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/restore")
async def restore_upload(request: Request, file: UploadFile = File(...),
                         db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    data = await file.read()
    db.close()  # release the pooled connection before we rewrite the DB file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    try:
        tmp.write(data)
        tmp.close()
        return _do_restore(tmp.name, file.filename or "uploaded file")
    finally:
        os.unlink(tmp.name)


@router.post("/admin/restore/{name}")
def restore_existing(name: str, request: Request, db: Session = Depends(get_db),
                     user=Depends(get_current_user)):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    path = backup.safe_path(name)
    if path is None:
        return RedirectResponse(
            f"/admin?ok=0&msg={quote('Backup not found.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    db.close()
    return _do_restore(path, name)


@router.post("/admin/users/{user_id}/reset-password")
def reset_password(user_id: int, request: Request, db: Session = Depends(get_db),
                   user=Depends(get_current_user)):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    target = db.get(User, user_id)
    if target is None:
        return _render_admin_home(request, db, user, msg="User not found.", ok=False)
    # Issue a temporary password and force a change at next login.
    temp = secrets.token_urlsafe(9)
    target.password_hash = hash_password(temp)
    target.must_change_password = True
    db.add(target)
    db.commit()
    return _render_admin_home(
        request, db, user,
        reset_info={"email": target.email, "temp": temp},
    )


@router.post("/admin/invite")
def create_invite(
    request: Request,
    email: str = Form(...),
    role: str = Form(ROLE_MEMBER),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    email = email.strip().lower()
    role = role if role in VALID_ROLES else ROLE_MEMBER
    token = generate_token()
    invite = Invite(
        email=email,
        role=role,
        token=token,
        expires_at=datetime.utcnow() + timedelta(days=config.INVITE_TTL_DAYS),
    )
    db.add(invite)
    db.commit()

    return _render_admin_home(
        request, db, user,
        new_invite_link=_register_link(request, token),
        new_invite_id=invite.id,
    )


def _invite_email_body(link: str) -> str:
    return (
        "You've been invited to HOLO — the Hands-On Lab Orchestrator.\n\n"
        "Set up your account using this single-use link (it will expire):\n\n"
        f"{link}\n"
    )


@router.post("/admin/invite/{invite_id}/email")
def email_invite(invite_id: int, request: Request, db: Session = Depends(get_db),
                 user=Depends(get_current_user)):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    invite = db.get(Invite, invite_id)
    if invite is None or invite.used_at is not None:
        return RedirectResponse(
            f"/admin?ok=0&msg={quote('Invitation not found or already used.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    link = _register_link(request, invite.token)
    ok, message = notifier.send(db, invite.email,
                                "Your HOLO invitation", _invite_email_body(link))
    return RedirectResponse(
        f"/admin?ok={1 if ok else 0}&msg={quote(message)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
