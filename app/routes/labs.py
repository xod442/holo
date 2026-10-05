"""Lab portfolio dashboard, lab detail, and gated lifecycle actions."""
import calendar as _calendar
from datetime import date, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import lab_service as svc
from .. import audit, notifier
from ..db import get_db
from ..deps import get_current_user
from ..labs_template import PHASE_AXIS, TOTAL_ESTIMATED_HOURS
from ..models import (
    Lab, LabLink, Phase, Task, User,
    ROLE_MANAGER, STAFF_ROLES, PHASE_AWAITING,
)
from ..web import templates

router = APIRouter()

DASHBOARD_STATES = (
    ("approved", "Approved"),
    ("completed", "Completed"),
    ("awaiting_approval", "Awaiting"),
    ("in_progress", "In progress"),
    ("not_started", "Not started"),
    ("blocked", "Blocked"),
)

def _login() -> RedirectResponse:
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


def _back(lab_id: int) -> RedirectResponse:
    return RedirectResponse(f"/labs/{lab_id}", status_code=status.HTTP_303_SEE_OTHER)


def _matches_phase_status(lab: Lab, phase_state: str) -> bool:
    if phase_state == "unfinished":
        return svc.lab_status(lab) != "Complete"
    if phase_state == "all":
        return True
    effective = svc.current_phase(lab) or (lab.phases[-1] if lab.phases else None)
    return effective is not None and effective.state == phase_state


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, owner: str = "", phase_state: str = "all",
              db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    if phase_state not in {"all", "unfinished", *(state for state, _ in DASHBOARD_STATES)}:
        raise HTTPException(status_code=400, detail="Invalid dashboard status filter.")

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
        if owner == "unassigned" and lab.owner_id is not None:
            return False
        if owner not in ("", "all", "unassigned") and str(lab.owner_id) != owner:
            return False
        return _matches_phase_status(lab, phase_state)

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
            "phase_state_sel": phase_state,
            "phase_state_options": DASHBOARD_STATES,
            "filters_active": owner not in ("", "all") or phase_state != "all",
        },
    )


@router.get("/mallmanac", response_class=HTMLResponse)
def mallmanac(request: Request, owner: str = "", ok: int = 1, msg: str = "",
             phase_state: str = "all",
             db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Lifecycle map: every lab as a 4-dev / 4-prod column grid of task pills,
    with independent task toggles and a pin on the furthest completed task."""
    if user is None:
        return _login()
    if phase_state not in {"all", "unfinished", *(state for state, _ in DASHBOARD_STATES)}:
        raise HTTPException(status_code=400, detail="Invalid Mallmanac status filter.")
    axis = PHASE_AXIS
    all_labs = db.query(Lab).filter(Lab.archived_at.is_(None)).order_by(Lab.created_at).all()

    owner_options: dict[int, str] = {}
    has_unassigned = False
    for lab in all_labs:
        if lab.owner_id is None:
            has_unassigned = True
        elif lab.owner is not None:
            owner_options[lab.owner_id] = lab.owner.email
    owner_options = sorted(owner_options.items(), key=lambda kv: kv[1])

    def _keep(lab) -> bool:
        if owner == "unassigned" and lab.owner_id is not None:
            return False
        if owner not in ("", "all", "unassigned") and str(lab.owner_id) != owner:
            return False
        return _matches_phase_status(lab, phase_state)

    labs = [lab for lab in all_labs if _keep(lab)]
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
        {
            "request": request,
            "user": user,
            "rows": rows,
            "msg": msg,
            "ok": bool(ok),
            "owner_options": owner_options,
            "owner_sel": owner,
            "has_unassigned": has_unassigned,
            "total_labs": len(all_labs),
            "phase_state_sel": phase_state,
            "phase_state_options": DASHBOARD_STATES,
            "filters_active": owner not in ("", "all") or phase_state != "all",
        },
    )


def _github_request_feedback(db: Session, lab: Lab, phase: Phase, user) -> tuple[bool, str] | None:
    if (phase.position != 2 or phase.stage != "Development"
            or lab.github_request_sent_at is not None
            or not any(t.title == "Git Repo Request" and t.done for t in phase.tasks)):
        return None
    ok, message = notifier.send_github_request(db, lab)
    audit.log(db, user, "lab.github_request_send" if ok else "lab.github_request_failed",
              target_type="lab", target_id=lab.id, target_label=lab.name, details=message)
    if not ok:
        message = ("Task saved, but the GitHub repository request was not sent. "
                   + message + " Fix the configuration and save Dev 3 again to retry.")
    return ok, message


@router.post("/labs/{lab_id}/tasks/{task_id}/complete")
def save_task(lab_id: int, task_id: int, done: str = Form(...), owner: str = Form(""),
              phase_state: str = Form("all"),
              db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    task = db.get(Task, task_id)
    if task is None or task.phase.lab_id != lab_id:
        raise HTTPException(status_code=404, detail="Task not found in this lab.")
    if done not in ("0", "1"):
        raise HTTPException(status_code=400, detail="Task completion must be 0 or 1.")
    before = task.done
    try:
        svc.set_task_done(db, task, done=done == "1", user_id=user.id)
    except ValueError as exc:
        return RedirectResponse(
            f"/mallmanac?owner={quote(owner, safe='')}&phase_state={quote(phase_state, safe='')}&ok=0&msg={quote(str(exc))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    lab = task.phase.lab
    if before != task.done:
        audit.log(db, user, "task.complete" if task.done else "task.reopen",
                  target_type="task", target_id=task.id,
                  target_label=f"{lab.name} / {task.title}")
    feedback = None
    if task.title == "Git Repo Request" and task.done:
        feedback = _github_request_feedback(db, lab, task.phase, user)
    suffix = ("Update checklists saved; Manager approval still gates release."
              if lab.parent_lab_id else "Phase gates unchanged.")
    ok, message = feedback or (True, f"{task.title}: {'completed' if task.done else 'reopened'}. {suffix}")
    return RedirectResponse(
        f"/mallmanac?owner={quote(owner, safe='')}&phase_state={quote(phase_state, safe='')}&ok={int(ok)}&msg={quote(message)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/metrics", response_class=HTMLResponse)
def metrics(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Manager command center — at-a-glance metrics across all active labs."""
    blocked_redirect = _staff_only(user)
    if blocked_redirect:
        return blocked_redirect

    labs = db.query(Lab).filter(Lab.archived_at.is_(None)).order_by(Lab.name).all()
    axis = PHASE_AXIS
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
    total_phases = sum(len(lab.phases) for lab in labs)
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
        audit.log(db, user, "lab.archive", target_type="lab", target_id=lab.id,
                  target_label=lab.name)
    return RedirectResponse("/admin/labs", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/labs/{lab_id}/unarchive")
def unarchive(lab_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    blocked = _staff_only(user)
    if blocked:
        return blocked
    lab = db.get(Lab, lab_id)
    if lab is not None:
        svc.unarchive_lab(db, lab)
        audit.log(db, user, "lab.unarchive", target_type="lab", target_id=lab.id,
                  target_label=lab.name)
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
    course_id: str = Form(""),
    abstract: str = Form(""),
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
        db, name=name, owner_id=user.id, course_id=course_id,
        abstract=abstract, target_release=target_release,
    )
    audit.log(db, user, "lab.create", target_type="lab", target_id=lab.id,
              target_label=lab.name)
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
            "links": [link for link in lab.links if link.task_id is None],
            "content_task": next((t for p in lab.phases for t in p.tasks
                                  if lab.parent_lab_id is not None
                                  and p.position == 5 and t.position == 0), None),
            "content_links": [link for link in lab.links if link.task_id is not None],
            "progress": svc.progress(lab),
            "status": svc.lab_status(lab),
            "hours": svc.hours_summary(lab),
            "can_approve": user.role == ROLE_MANAGER,
            "users": db.query(User).order_by(User.email).all(),
            "can_change_owner": user.role in STAFF_ROLES or lab.owner_id == user.id,
            "msg": request.query_params.get("msg", ""),
            "ok": request.query_params.get("ok", "1") == "1",
        },
    )


@router.post("/labs/{lab_id}/update")
def create_update(lab_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    source = db.get(Lab, lab_id)
    if source is None:
        raise HTTPException(status_code=404, detail="HOL not found.")
    try:
        update = svc.create_update(db, source)
    except ValueError as exc:
        return RedirectResponse(
            f"/labs/{source.id}?ok=0&msg={quote(str(exc))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    audit.log(db, user, "lab.update_create", target_type="lab", target_id=update.id,
              target_label=update.name, details=f"source_lab_id={source.id}")
    return _back(update.id)


@router.get("/labs/{lab_id}/calendar", response_class=HTMLResponse)
def lab_calendar(lab_id: int, request: Request, month: str = "",
                 db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    lab = db.get(Lab, lab_id)
    if lab is None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    axis = PHASE_AXIS

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
    new_owner_email = "Unassigned"
    if new_owner_id is not None:
        target_user = db.get(User, new_owner_id)
        new_owner_email = target_user.email if target_user else str(new_owner_id)
    svc.set_owner(db, lab, new_owner_id)
    audit.log(db, user, "lab.owner_change", target_type="lab", target_id=lab.id,
              target_label=lab.name, details=f"new owner={new_owner_email}")
    return _back(lab_id)


@router.post("/labs/{lab_id}/course-id")
def set_course_id(lab_id: int, course_id: str = Form(""),
                  db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    lab = db.get(Lab, lab_id)
    if lab is None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    # Only staff (admin/manager) or the current owner may set the course ID.
    if user.role not in STAFF_ROLES and lab.owner_id != user.id:
        return _back(lab_id)
    svc.set_course_id(db, lab, course_id)
    audit.log(db, user, "lab.course_id_set", target_type="lab", target_id=lab.id,
              target_label=lab.name, details=f"course_id={course_id.strip()}")
    return _back(lab_id)


@router.post("/labs/{lab_id}/abstract")
def set_abstract(lab_id: int, abstract: str = Form(""),
                 db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    lab = db.get(Lab, lab_id)
    if lab is None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    # Only staff (admin/manager) or the current owner may set the abstract.
    if user.role not in STAFF_ROLES and lab.owner_id != user.id:
        return _back(lab_id)
    svc.set_abstract(db, lab, abstract)
    audit.log(db, user, "lab.abstract_set", target_type="lab", target_id=lab.id,
              target_label=lab.name)
    return _back(lab_id)


@router.post("/labs/{lab_id}/revision")
def set_revision(lab_id: int, revision: str = Form(""),
                 db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    lab = db.get(Lab, lab_id)
    if lab is None:
        raise HTTPException(status_code=404, detail="HOL not found.")
    if lab.parent_lab_id is None:
        raise HTTPException(status_code=400, detail="Revisions are only available on HOL updates.")
    if user.role not in STAFF_ROLES and lab.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner or staff can edit the revision.")
    revision = revision.strip()
    if len(revision) > 80:
        return RedirectResponse(
            f"/labs/{lab_id}?ok=0&msg={quote('Revision must be 80 characters or fewer.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    lab.revision = revision
    db.commit()
    audit.log(db, user, "lab.revision_set", target_type="lab", target_id=lab.id,
              target_label=lab.name, details=f"revision={revision}")
    return _back(lab_id)


@router.post("/labs/{lab_id}/links")
def add_link(lab_id: int, url: str = Form(...), label: str = Form(""),
             db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    lab = db.get(Lab, lab_id)
    if lab is not None:
        if svc.add_link(db, lab, url=url, label=label, user_id=user.id):
            audit.log(db, user, "lab.link_add", target_type="lab", target_id=lab.id,
                      target_label=lab.name, details=f"url={url.strip()}")
    return _back(lab_id)


@router.post("/labs/{lab_id}/tasks/{task_id}/content")
def add_content(lab_id: int, task_id: int, url: str = Form(...), label: str = Form(""),
                db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    task = db.get(Task, task_id)
    if (task is None or task.phase.lab_id != lab_id or task.phase.lab.parent_lab_id is None
            or task.phase.position != 5 or task.position != 0):
        raise HTTPException(status_code=404, detail="New Content task not found.")
    url = url.strip()
    if not svc.is_safe_url(url) or not url.lower().startswith("https://"):
        return RedirectResponse(
            f"/labs/{lab_id}?ok=0&msg={quote('New Content requires a valid HTTPS document link.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    db.add(LabLink(lab_id=lab_id, task_id=task.id, url=url, label=label.strip() or url,
                   added_by_id=user.id))
    db.commit()
    audit.log(db, user, "lab.content_add", target_type="lab", target_id=lab_id,
              target_label=task.phase.lab.name, details=f"task_id={task.id}, url={url}")
    return _back(lab_id)


@router.post("/labs/{lab_id}/links/{link_id}/delete")
def delete_link(lab_id: int, link_id: int, db: Session = Depends(get_db),
                user=Depends(get_current_user)):
    if user is None:
        return _login()
    link = db.get(LabLink, link_id)
    if link is not None and link.lab_id == lab_id:
        url = link.url
        svc.delete_link(db, link)
        audit.log(db, user, "lab.link_delete", target_type="lab", target_id=lab_id,
                  details=f"url={url}")
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
    if phase is not None and svc.start_phase(db, phase, lab):
        audit.log(db, user, "phase.start", target_type="phase", target_id=phase.id,
                  target_label=f"{lab.name} / {phase.name}")
    return _back(lab_id)


@router.post("/labs/{lab_id}/phases/{phase_id}/submit")
def submit(lab_id: int, phase_id: int, db: Session = Depends(get_db),
           user=Depends(get_current_user)):
    if user is None:
        return _login()
    lab, phase = _fetch(db, lab_id, phase_id)
    if phase is not None and svc.submit_phase(db, phase, lab):
        audit.log(db, user, "phase.submit", target_type="phase", target_id=phase.id,
                  target_label=f"{lab.name} / {phase.name}")
    return _back(lab_id)


@router.post("/labs/{lab_id}/phases/{phase_id}/approve")
def approve(lab_id: int, phase_id: int, note: str = Form(""),
            db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    if user.role != ROLE_MANAGER:
        return _back(lab_id)  # only the manager holds the gate
    lab, phase = _fetch(db, lab_id, phase_id)
    if phase is not None and svc.approve_phase(db, phase, lab, approver_id=user.id, note=note):
        audit.log(db, user, "phase.approve", target_type="phase", target_id=phase.id,
                  target_label=f"{lab.name} / {phase.name}",
                  details=note.strip() if note.strip() else "")
    return _back(lab_id)


@router.post("/labs/{lab_id}/phases/{phase_id}/complete")
def complete(lab_id: int, phase_id: int, db: Session = Depends(get_db),
             user=Depends(get_current_user)):
    if user is None:
        return _login()
    lab, phase = _fetch(db, lab_id, phase_id)
    if phase is not None and svc.complete_phase(db, phase, lab):
        audit.log(db, user, "phase.complete", target_type="phase", target_id=phase.id,
                  target_label=f"{lab.name} / {phase.name}")
    return _back(lab_id)


@router.post("/labs/{lab_id}/phases/{phase_id}/save")
async def save_pill(lab_id: int, phase_id: int, request: Request,
                    db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Save the whole pill at once: hours, phase notes, and every step."""
    if user is None:
        return _login()
    lab, phase = _fetch(db, lab_id, phase_id)
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
        # Snapshot before/after so the log records what actually changed.
        before_done = {t.id: t.done for t in phase.tasks}
        before = (phase.actual_hours, phase.notes, phase.target_date)
        try:
            svc.save_phase(db, phase, actual_hours=hours,
                           notes=str(form.get("notes", "")),
                           target_date=str(form.get("target_date", "")),
                           task_updates=task_updates, user_id=user.id)
        except ValueError as exc:
            return RedirectResponse(
                f"/labs/{lab_id}?ok=0&msg={quote(str(exc))}",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        changes = []
        if before[0] != phase.actual_hours:
            changes.append(f"hours {before[0]}->{phase.actual_hours}")
        if before[1] != phase.notes:
            changes.append("notes updated")
        if before[2] != phase.target_date:
            changes.append(f"target_date->{phase.target_date or '(none)'}")
        toggled = [t.title for t in phase.tasks if before_done.get(t.id) != t.done]
        if toggled:
            changes.append(f"tasks toggled: {', '.join(toggled)}")
        if changes:
            audit.log(db, user, "phase.save", target_type="phase", target_id=phase.id,
                      target_label=f"{lab.name} / {phase.name}",
                      details="; ".join(changes))
        feedback = _github_request_feedback(db, lab, phase, user)
        if feedback is not None:
            ok, message = feedback
            return RedirectResponse(
                f"/labs/{lab_id}?ok={int(ok)}&msg={quote(message)}",
                status_code=status.HTTP_303_SEE_OTHER,
            )
    return _back(lab_id)


@router.post("/labs/{lab_id}/phases/{phase_id}/block")
def block(lab_id: int, phase_id: int, db: Session = Depends(get_db),
          user=Depends(get_current_user)):
    if user is None:
        return _login()
    lab, phase = _fetch(db, lab_id, phase_id)
    if phase is not None and svc.set_blocked(db, phase, True):
        audit.log(db, user, "phase.block", target_type="phase", target_id=phase.id,
                  target_label=f"{lab.name} / {phase.name}")
    return _back(lab_id)


@router.post("/labs/{lab_id}/phases/{phase_id}/unblock")
def unblock(lab_id: int, phase_id: int, db: Session = Depends(get_db),
            user=Depends(get_current_user)):
    if user is None:
        return _login()
    lab, phase = _fetch(db, lab_id, phase_id)
    if phase is not None and svc.set_blocked(db, phase, False):
        audit.log(db, user, "phase.unblock", target_type="phase", target_id=phase.id,
                  target_label=f"{lab.name} / {phase.name}")
    return _back(lab_id)
