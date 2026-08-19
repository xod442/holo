"""Read-only JSON API (/api/v1/...) for external integrations — namely VISTA,
the executive dashboard that aggregates HOLO and FOCUS.

Guarded by a static key in the `X-API-Key` header, entirely independent of the
session-cookie auth used everywhere else in the app. An empty `HOLO_API_KEY`
disables the API outright (every route 404s), mirroring the "empty secret =
feature disabled" convention used by the FOCUS SSO hand-off.
"""
import secrets
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import config
from .. import lab_service as svc
from ..db import get_db
from ..labs_template import PHASE_AXIS
from ..models import AuditLog, Invite, Lab, Phase, User, PHASE_AWAITING

router = APIRouter(prefix="/api/v1", tags=["api"])

ACTIVITY_DAY_CHOICES = (7, 30, 90)
ACTIVITY_DAYS_DEFAULT = 30


def require_api_key(x_api_key: str = Header(default="", alias="X-API-Key")) -> None:
    """Every route in this router depends on this — treat a disabled API the
    same as a route that doesn't exist, rather than leaking that it's just
    locked (matches how the rest of the app hides staff-only routes)."""
    if not config.API_KEY:
        raise HTTPException(status_code=404, detail="Not found")
    if not x_api_key or not secrets.compare_digest(x_api_key, config.API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@router.get("/summary", dependencies=[Depends(require_api_key)])
def summary(db: Session = Depends(get_db)):
    """Portfolio-wide metrics — the same figures shown on HOLO's own /metrics
    page, in JSON. Meant for a periodic pull, not per-request computation."""
    labs = db.query(Lab).filter(Lab.archived_at.is_(None)).order_by(Lab.name).all()
    today = date.today()
    total = len(labs)

    released = in_progress = blocked = awaiting = overdue = 0
    done_phases = est_hours = act_hours = 0.0
    dev_ct = prod_ct = 0
    funnel = [{"code": PHASE_AXIS[i]["code"], "name": PHASE_AXIS[i]["name"], "count": 0} for i in range(8)]
    owner_counts: dict[str, int] = {}

    for lab in labs:
        status = svc.lab_status(lab)
        prog = svc.progress(lab)
        cur = svc.current_phase(lab)
        hrs = svc.hours_summary(lab)
        done_phases += prog["done"]
        est_hours += hrs["estimated"]
        act_hours += hrs["actual"]

        if status == "Complete":
            released += 1
        elif status == "Blocked":
            blocked += 1
        else:
            in_progress += 1

        if cur is not None:
            funnel[cur.position]["count"] += 1
            if cur.position < 4:
                dev_ct += 1
            else:
                prod_ct += 1
            if cur.target_date:
                try:
                    if datetime.strptime(cur.target_date, "%Y-%m-%d").date() < today:
                        overdue += 1
                except ValueError:
                    pass

        awaiting += sum(1 for p in lab.phases if p.state == PHASE_AWAITING)
        owner = lab.owner.email if lab.owner else "Unassigned"
        owner_counts[owner] = owner_counts.get(owner, 0) + 1

    total_phases = total * 8
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total_labs": total,
        "released": released,
        "released_pct": round(100 * released / total) if total else 0,
        "in_progress": in_progress,
        "blocked": blocked,
        "awaiting_approval": awaiting,
        "overdue": overdue,
        "pipeline_pct": round(100 * done_phases / total_phases) if total_phases else 0,
        "estimated_hours": round(est_hours),
        "actual_hours": round(act_hours),
        "development_ct": dev_ct,
        "production_ct": prod_ct,
        "funnel": funnel,
        "owners": [{"email": e, "labs": c} for e, c in
                   sorted(owner_counts.items(), key=lambda kv: kv[1], reverse=True)],
        "archived_labs": db.query(Lab).filter(Lab.archived_at.isnot(None)).count(),
        "pending_invites": db.query(Invite).filter(Invite.used_at.is_(None)).count(),
        "total_users": db.query(User).count(),
    }


@router.get("/labs", dependencies=[Depends(require_api_key)])
def labs_list(db: Session = Depends(get_db)):
    """Every active lab with its current status/progress — the dashboard cards,
    in JSON."""
    labs = db.query(Lab).filter(Lab.archived_at.is_(None)).order_by(Lab.name).all()
    today = date.today()
    rows = []
    for lab in labs:
        prog = svc.progress(lab)
        cur = svc.current_phase(lab)
        hrs = svc.hours_summary(lab)
        overdue = False
        if cur is not None and cur.target_date:
            try:
                overdue = datetime.strptime(cur.target_date, "%Y-%m-%d").date() < today
            except ValueError:
                overdue = False
        rows.append({
            "id": lab.id,
            "name": lab.name,
            "course_id": lab.course_id,
            "owner_email": lab.owner.email if lab.owner else None,
            "status": svc.lab_status(lab),
            "percent": prog["percent"],
            "current_phase": cur.name if cur else None,
            "current_phase_target_date": cur.target_date if cur else "",
            "overdue": overdue,
            "estimated_hours": hrs["estimated"],
            "actual_hours": hrs["actual"],
            "created_at": lab.created_at.isoformat() + "Z",
        })
    return {"generated_at": datetime.utcnow().isoformat() + "Z", "labs": rows}


@router.get("/users", dependencies=[Depends(require_api_key)])
def users_list(db: Session = Depends(get_db)):
    """User roster — no password hashes, ever."""
    users = db.query(User).order_by(User.email).all()
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "role": u.role,
                "must_change_password": u.must_change_password,
                "created_at": u.created_at.isoformat() + "Z",
            }
            for u in users
        ],
    }


@router.get("/activity", dependencies=[Depends(require_api_key)])
def activity(days: int = Query(ACTIVITY_DAYS_DEFAULT), db: Session = Depends(get_db)):
    """Per-user audit-log activity over the trailing `days` — a proxy for who
    is actually using HOLO, plus each user's most recent login."""
    if days not in ACTIVITY_DAY_CHOICES:
        days = ACTIVITY_DAYS_DEFAULT
    cutoff = datetime.utcnow() - timedelta(days=days)

    counts = dict(
        db.query(AuditLog.user_email, func.count(AuditLog.id))
        .filter(AuditLog.created_at >= cutoff, AuditLog.user_email != "")
        .group_by(AuditLog.user_email)
        .all()
    )
    last_logins = dict(
        db.query(AuditLog.user_email, func.max(AuditLog.created_at))
        .filter(AuditLog.action == "auth.login", AuditLog.user_email != "")
        .group_by(AuditLog.user_email)
        .all()
    )

    users = db.query(User).order_by(User.email).all()
    rows = [
        {
            "id": u.id,
            "email": u.email,
            "role": u.role,
            "activity_count": counts.get(u.email, 0),
            "last_login": last_logins[u.email].isoformat() + "Z" if u.email in last_logins else None,
        }
        for u in users
    ]
    rows.sort(key=lambda r: r["activity_count"], reverse=True)
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "days": days,
        "users": rows,
    }
