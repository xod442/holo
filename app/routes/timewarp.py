"""Admin-only: Time Warp — fast-forward a lab that was already completed
or nearly complete before it was tracked in HOLO to whichever phase it's
really at, auto-approving/completing everything before that point."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import audit
from .. import lab_service as svc
from ..db import get_db
from ..deps import get_current_user
from ..labs_template import PHASE_AXIS
from ..models import Lab, ROLE_ADMIN
from ..web import templates

router = APIRouter()


def _guard(user):
    """Admin-only — unlike other admin tools, Time Warp isn't available to
    Managers (it silently rewrites history rather than approving live work)."""
    if user is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if user.role != ROLE_ADMIN:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return None


@router.get("/admin/time-warp", response_class=HTMLResponse)
def time_warp_page(request: Request, ok: int = 1, msg: str = "",
                   db: Session = Depends(get_db), user=Depends(get_current_user)):
    blocked = _guard(user)
    if blocked:
        return blocked

    labs = db.query(Lab).filter(Lab.archived_at.is_(None)).order_by(Lab.name).all()
    rows = []
    for lab in labs:
        current = svc.current_phase(lab)
        # Only phases strictly ahead of the current one are valid targets.
        # A fully complete lab (current is None) has nothing left to warp to.
        options = [p for p in PHASE_AXIS if p["position"] > current.position] if current else []
        rows.append({
            "lab": lab,
            "current": current,
            "status": svc.lab_status(lab),
            "progress": svc.progress(lab),
            "options": options,
        })

    return templates.TemplateResponse(
        request,
        "admin_time_warp.html",
        {
            "request": request,
            "user": user,
            "rows": rows,
            "msg": msg,
            "ok": bool(ok),
        },
    )


@router.post("/admin/time-warp/{lab_id}")
def time_warp_lab(lab_id: int, target_position: int = Form(...),
                  db: Session = Depends(get_db), user=Depends(get_current_user)):
    blocked = _guard(user)
    if blocked:
        return blocked

    lab = db.get(Lab, lab_id)
    if lab is None:
        return RedirectResponse(
            f"/admin/time-warp?ok=0&msg={quote('Lab not found.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    ok, message = svc.time_warp(db, lab, target_position, actor_id=user.id)
    if ok:
        audit.log(db, user, "lab.time_warp", target_type="lab", target_id=lab.id,
                  target_label=lab.name, details=message)
    return RedirectResponse(
        f"/admin/time-warp?ok={1 if ok else 0}&msg={quote(message)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
