"""Admin-only: Time Warp — fast-forward a lab that was already completed or
nearly complete before it was tracked in HOLO to any sub-process pill on the
Mallmanac, auto-approving/completing everything before that point."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import audit
from .. import lab_service as svc
from ..db import get_db
from ..deps import get_current_user
from ..models import Lab, ROLE_ADMIN, Task

router = APIRouter()


def _guard(user):
    """Admin-only — unlike other admin tools, Time Warp isn't available to
    Managers (it silently rewrites history rather than approving live work)."""
    if user is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if user.role != ROLE_ADMIN:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return None


@router.post("/admin/time-warp/{lab_id}/{task_id}")
def time_warp_to_task(lab_id: int, task_id: int, db: Session = Depends(get_db),
                      user=Depends(get_current_user)):
    blocked = _guard(user)
    if blocked:
        return blocked

    lab = db.get(Lab, lab_id)
    task = db.get(Task, task_id)
    if lab is None or task is None or task.phase.lab_id != lab.id:
        ok, message = False, "Lab or step not found."
    else:
        ok, message = svc.time_warp_to_task(db, lab, task_id, actor_id=user.id)
        if ok:
            audit.log(db, user, "lab.time_warp", target_type="lab", target_id=lab.id,
                      target_label=lab.name, details=message)

    return RedirectResponse(
        f"/mallmanac?ok={1 if ok else 0}&msg={quote(message)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
