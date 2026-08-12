"""Lab portfolio dashboard, lab detail, and gated lifecycle actions."""
import calendar as _calendar
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import lab_service as svc
from ..db import get_db
from ..deps import get_current_user
from ..labs_template import PHASE_TEMPLATE, STAGE_DEVELOPMENT, TOTAL_ESTIMATED_HOURS


def _phase_axis() -> list[dict]:
    """Left-axis labels: dev-1..dev-4, prod-1..prod-4 in pipeline order."""
    axis, dev, prod = [], 0, 0
    for tpl in PHASE_TEMPLATE:
        if tpl["stage"] == STAGE_DEVELOPMENT:
            dev += 1
            code = f"dev-{dev}"
        else:
            prod += 1
            code = f"prod-{prod}"
        axis.append({"code": code, "name": tpl["name"]})
    return axis
from ..models import (
    Lab, LabLink, Phase, User,
    ROLE_MANAGER, STAFF_ROLES, PHASE_AWAITING, PHASE_DONE_STATES,
)
from ..web import templates

router = APIRouter()

def _login() -> RedirectResponse:
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


def _back(lab_id: int) -> RedirectResponse:
    return RedirectResponse(f"/labs/{lab_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, owner: str = "",
              db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()

    all_labs = (
        db.query(Lab)
        .filter(Lab.archived_at.is_(None))
        .order_by(Lab.created_at.desc())
        .all()
    )

    # Build the owner filter options from every lab's owner.
    owner_options: dict[int, str] = {}
    has_unassigned = False
    for lab in all_labs:
        if lab.owner_id is None:
            has_unassigned = True
        elif lab.owner is not None:
            owner_options[lab.owner_id] = lab.owner.email
    owner_options = sorted(owner_options.items(), key=lambda kv: kv[1])

    def _keep(lab) -> bool:
        if owner in ("", "all"):
            return True
        if owner == "unassigned":
            return lab.owner_id is None
        return str(lab.owner_id) == owner

    labs = [lab for lab in all_labs if _keep(lab)]
    cards = [
        {
            "lab": lab,
            "progress": svc.progress(lab),
            "status": svc.lab_status(lab),
            "current": svc.current_phase(lab),
            "hours": svc.hours_summary(lab),
            "phases": lab.phases,
        }
        for lab in labs
    ]

    # The manager (the approver) gets a queue of everything waiting on sign-off.
    awaiting = []
    if user.role == ROLE_MANAGER:
        rows = (
            db.query(Phase)
            .join(Lab, Lab.id == Phase.lab_id)
            .filter(Phase.state == PHASE_AWAITING, Lab.archived_at.is_(None))
            .order_by(Lab.name)
            .all()
        )
        awaiting = [{"phase": p, "lab": p.lab} for p in rows]

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "cards": cards,
            "awaiting": awaiting,
            "total_estimated": TOTAL_ESTIMATED_HOURS,
            "owner_options": owner_options,
            "has_unassigned": has_unassigned,
            "owner_sel": owner,
            "total_labs": len(all_labs),
        },
    )


@router.get("/mallmanac", response_class=HTMLResponse)
def mallmanac(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Lifecycle map: every lab as a 4-dev / 4-prod column grid of task pills,
    with a 'you are here' pin on the furthest completed task."""
    if user is None:
        return _login()
    axis = _phase_axis()
    labs = db.query(Lab).filter(Lab.archived_at.is_(None)).order_by(Lab.created_at).all()
    rows = []
    for lab in labs:
        # Furthest completed task = last done task in pipeline order.
        flat = [t for p in lab.phases for t in p.tasks]
        pin_id = None
        for t in flat:
            if t.done:
                pin_id = t.id
        if pin_id is None and flat:
            pin_id = flat[0].id  # nothing done yet → the very first task

        cols = [
            {
                "code": axis[p.position]["code"],
                "name": p.name,
                "state": p.state,
                "tasks": [{"id": t.id, "title": t.title, "done": t.done} for t in p.tasks],
            }
            for p in lab.phases
        ]
        rows.append({
            "lab": lab, "cols": cols, "pin": pin_id,
            "status": svc.lab_status(lab),
            "progress": svc.progress(lab),
        })
    return templates.TemplateResponse(
        request,
        "mallmanac.html",
        {"request": request, "user": user, "rows": rows},
    )


@router.get("/metrics", response_class=HTMLResponse)
def metrics(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Manager command center — at-a-glance metrics across all active labs."""
    blocked_redirect = _staff_only(user)
    if blocked_redirect:
        return blocked_redirect

    labs = db.query(Lab).filter(Lab.archived_at.is_(None)).order_by(Lab.name).all()
    axis = _phase_axis()
    today = date.today()
    total = len(labs)

    released = in_progress = blocked = awaiting = overdue = 0
    done_phases = est_hours = act_hours = 0.0
    dev_ct = prod_ct = 0
    funnel = [{"code": axis[i]["code"], "name": axis[i]["name"], "count": 0} for i in range(8)]
    owner_counts: dict[str, int] = {}
    rows = []

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

        rows.append({
            "lab": lab, "status": status, "percent": prog["percent"],
            "current": cur.name if cur else "—",
            "owner": owner, "act": hrs["actual"], "est": hrs["estimated"],
        })

    rows.sort(key=lambda r: r["percent"], reverse=True)
    total_phases = total * 8
    m = {
        "total": total,
        "released": released,
        "released_pct": round(100 * released / total) if total else 0,
        "in_progress": in_progress,
        "blocked": blocked,
        "awaiting": awaiting,
        "overdue": overdue,
        "pipeline_pct": round(100 * done_phases / total_phases) if total_phases else 0,
        "est_hours": round(est_hours),
        "act_hours": round(act_hours),
        "dev_ct": dev_ct,
        "prod_ct": prod_ct,
        "funnel": funnel,
        "funnel_max": max((f["count"] for f in funnel), default=0),
        "owners": sorted(owner_counts.items(), key=lambda kv: kv[1], reverse=True),
        "archived": db.query(Lab).filter(Lab.archived_at.isnot(None)).count(),
    }
    return templates.TemplateResponse(
        request, "metrics.html", {"request": request, "user": user, "m": m, "rows": rows},
    )


def _staff_only(user):
    if user is None:
        return _login()
    if user.role not in STAFF_ROLES:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return None


@router.get("/admin/labs", response_class=HTMLResponse)
def manage_labs(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Staff: pick an active lab to archive."""
    blocked = _staff_only(user)
    if blocked:
        return blocked
    labs = db.query(Lab).filter(Lab.archived_at.is_(None)).order_by(Lab.name).all()
    rows = [{"lab": l, "status": svc.lab_status(l), "progress": svc.progress(l)} for l in labs]
    archived_count = db.query(Lab).filter(Lab.archived_at.isnot(None)).count()
    return templates.TemplateResponse(
        request, "admin_labs.html",
        {"request": request, "user": user, "rows": rows, "archived_count": archived_count},
    )


@router.get("/archived", response_class=HTMLResponse)
def archived_labs(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Staff: view archived labs (hidden from the dashboard/mallmanac)."""
    blocked = _staff_only(user)
    if blocked:
        return blocked
    labs = db.query(Lab).filter(Lab.archived_at.isnot(None)).order_by(Lab.archived_at.desc()).all()
    rows = [{"lab": l, "status": svc.lab_status(l), "progress": svc.progress(l)} for l in labs]
    return templates.TemplateResponse(
        request, "archived.html", {"request": request, "user": user, "rows": rows},
    )


@router.post("/labs/{lab_id}/archive")
def archive(lab_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    blocked = _staff_only(user)
    if blocked:
        return blocked
    lab = db.get(Lab, lab_id)
    if lab is not None:
        svc.archive_lab(db, lab, user.id)
    return RedirectResponse("/admin/labs", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/labs/{lab_id}/unarchive")
def unarchive(lab_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    blocked = _staff_only(user)
    if blocked:
        return blocked
    lab = db.get(Lab, lab_id)
    if lab is not None:
        svc.unarchive_lab(db, lab)
    return RedirectResponse("/archived", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/labs/new", response_class=HTMLResponse)
def new_lab_form(request: Request, user=Depends(get_current_user)):
    if user is None:
        return _login()
    return templates.TemplateResponse(
        request, "lab_new.html", {"request": request, "user": user}
    )


@router.post("/labs")
def create_lab(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    target_release: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None:
        return _login()
    if not name.strip():
        return templates.TemplateResponse(
            request,
            "lab_new.html",
            {"request": request, "user": user, "error": "Lab name is required"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    lab = svc.create_lab(
        db, name=name, owner_id=user.id,
        description=description, target_release=target_release,
    )
    return _back(lab.id)


@router.get("/labs/{lab_id}", response_class=HTMLResponse)
def lab_detail(lab_id: int, request: Request, db: Session = Depends(get_db),
               user=Depends(get_current_user)):
    if user is None:
        return _login()
    lab = db.get(Lab, lab_id)
    if lab is None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    phase_rows = [
        {"phase": p, "can_start": svc.can_start(p, lab), "tasks": p.tasks}
        for p in lab.phases
    ]
    return templates.TemplateResponse(
        request,
        "lab_detail.html",
        {
            "request": request,
            "user": user,
            "lab": lab,
            "phase_rows": phase_rows,
            "links": lab.links,
            "progress": svc.progress(lab),
            "status": svc.lab_status(lab),
            "hours": svc.hours_summary(lab),
            "can_approve": user.role == ROLE_MANAGER,
            "users": db.query(User).order_by(User.email).all(),
            "can_change_owner": user.role in STAFF_ROLES or lab.owner_id == user.id,
        },
    )


@router.get("/labs/{lab_id}/calendar", response_class=HTMLResponse)
def lab_calendar(lab_id: int, request: Request, month: str = "",
                 db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    lab = db.get(Lab, lab_id)
    if lab is None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    axis = _phase_axis()

    def _view(p):
        return {"name": p.name, "state": p.state, "code": axis[p.position]["code"]}

    scheduled: dict[date, list] = {}
    unscheduled = []
    for p in lab.phases:
        if p.target_date:
            try:
                d = datetime.strptime(p.target_date, "%Y-%m-%d").date()
            except ValueError:
                unscheduled.append(_view(p))
                continue
            scheduled.setdefault(d, []).append(p)
        else:
            unscheduled.append(_view(p))

    today = date.today()
    year, mon = today.year, today.month
    if month:
        try:
            year, mon = int(month[:4]), int(month[5:7])
        except (ValueError, IndexError):
            pass
    elif scheduled:
        earliest = min(scheduled)
        year, mon = earliest.year, earliest.month

    weeks = []
    for week in _calendar.Calendar(firstweekday=6).monthdatescalendar(year, mon):
        weeks.append([
            {
                "day": d.day,
                "in_month": d.month == mon,
                "is_today": d == today,
                "phases": [_view(p) for p in scheduled.get(d, [])],
            }
            for d in week
        ])

    first = date(year, mon, 1)
    prev_str = (first - timedelta(days=1)).strftime("%Y-%m")
    nxt = date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)
    return templates.TemplateResponse(
        request,
        "lab_calendar.html",
        {
            "request": request,
            "user": user,
            "lab": lab,
            "weeks": weeks,
            "weekdays": ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
            "month_label": first.strftime("%B %Y"),
            "prev_month": prev_str,
            "next_month": nxt.strftime("%Y-%m"),
            "unscheduled": unscheduled,
            "scheduled_count": sum(len(v) for v in scheduled.values()),
        },
    )


@router.post("/labs/{lab_id}/owner")
def change_owner(lab_id: int, owner_id: str = Form(""),
                 db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    lab = db.get(Lab, lab_id)
    if lab is None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    # Only staff (admin/manager) or the current owner may reassign.
    if user.role not in STAFF_ROLES and lab.owner_id != user.id:
        return _back(lab_id)

    new_owner_id: int | None = None
    if owner_id.strip():
        try:
            candidate = int(owner_id)
        except ValueError:
            return _back(lab_id)
        if db.get(User, candidate) is not None:
            new_owner_id = candidate
    svc.set_owner(db, lab, new_owner_id)
    return _back(lab_id)


@router.post("/labs/{lab_id}/links")
def add_link(lab_id: int, url: str = Form(...), label: str = Form(""),
             db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    lab = db.get(Lab, lab_id)
    if lab is not None:
        svc.add_link(db, lab, url=url, label=label, user_id=user.id)
    return _back(lab_id)


@router.post("/labs/{lab_id}/links/{link_id}/delete")
def delete_link(lab_id: int, link_id: int, db: Session = Depends(get_db),
                user=Depends(get_current_user)):
    if user is None:
        return _login()
    link = db.get(LabLink, link_id)
    if link is not None and link.lab_id == lab_id:
        svc.delete_link(db, link)
    return _back(lab_id)


# --- Phase / task actions ---------------------------------------------------

def _fetch(db: Session, lab_id: int, phase_id: int) -> tuple[Lab | None, Phase | None]:
    lab = db.get(Lab, lab_id)
    phase = db.get(Phase, phase_id)
    if lab is None or phase is None or phase.lab_id != lab.id:
        return None, None
    return lab, phase


@router.post("/labs/{lab_id}/phases/{phase_id}/start")
def start(lab_id: int, phase_id: int, db: Session = Depends(get_db),
          user=Depends(get_current_user)):
    if user is None:
        return _login()
    lab, phase = _fetch(db, lab_id, phase_id)
    if phase is not None:
        svc.start_phase(db, phase, lab)
    return _back(lab_id)


@router.post("/labs/{lab_id}/phases/{phase_id}/submit")
def submit(lab_id: int, phase_id: int, db: Session = Depends(get_db),
           user=Depends(get_current_user)):
    if user is None:
        return _login()
    lab, phase = _fetch(db, lab_id, phase_id)
    if phase is not None:
        svc.submit_phase(db, phase, lab)
    return _back(lab_id)


@router.post("/labs/{lab_id}/phases/{phase_id}/approve")
def approve(lab_id: int, phase_id: int, note: str = Form(""),
            db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    if user.role != ROLE_MANAGER:
        return _back(lab_id)  # only the manager holds the gate
    lab, phase = _fetch(db, lab_id, phase_id)
    if phase is not None:
        svc.approve_phase(db, phase, lab, approver_id=user.id, note=note)
    return _back(lab_id)


@router.post("/labs/{lab_id}/phases/{phase_id}/complete")
def complete(lab_id: int, phase_id: int, db: Session = Depends(get_db),
             user=Depends(get_current_user)):
    if user is None:
        return _login()
    lab, phase = _fetch(db, lab_id, phase_id)
    if phase is not None:
        svc.complete_phase(db, phase, lab)
    return _back(lab_id)


@router.post("/labs/{lab_id}/phases/{phase_id}/save")
async def save_pill(lab_id: int, phase_id: int, request: Request,
                    db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Save the whole pill at once: hours, phase notes, and every step."""
    if user is None:
        return _login()
    _, phase = _fetch(db, lab_id, phase_id)
    if phase is not None:
        form = await request.form()
        raw_hours = form.get("actual_hours")
        try:
            hours = float(raw_hours) if raw_hours not in (None, "") else None
        except (TypeError, ValueError):
            hours = None
        task_updates = {
            t.id: {"note": str(form.get(f"note_{t.id}", "")),
                   "done": f"done_{t.id}" in form}
            for t in phase.tasks
        }
        svc.save_phase(db, phase, actual_hours=hours,
                       notes=str(form.get("notes", "")),
                       target_date=str(form.get("target_date", "")),
                       task_updates=task_updates, user_id=user.id)
    return _back(lab_id)


@router.post("/labs/{lab_id}/phases/{phase_id}/block")
def block(lab_id: int, phase_id: int, db: Session = Depends(get_db),
          user=Depends(get_current_user)):
    if user is None:
        return _login()
    _, phase = _fetch(db, lab_id, phase_id)
    if phase is not None:
        svc.set_blocked(db, phase, True)
    return _back(lab_id)


@router.post("/labs/{lab_id}/phases/{phase_id}/unblock")
def unblock(lab_id: int, phase_id: int, db: Session = Depends(get_db),
            user=Depends(get_current_user)):
    if user is None:
        return _login()
    _, phase = _fetch(db, lab_id, phase_id)
    if phase is not None:
        svc.set_blocked(db, phase, False)
    return _back(lab_id)


