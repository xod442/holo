"""Durable create-only JADE registration; no network calls during HOL creation."""
import json
import logging
import socket
import threading
import uuid
from datetime import datetime, timedelta
from typing import TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sqlalchemy import or_, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from . import config
from .db import SessionLocal
from .models import JadeRegistration, Lab

logger = logging.getLogger(__name__)


class RegistrationResult(TypedDict):
    id: int
    record_path: str
    source: str
    external_id: str


def enabled() -> bool:
    return bool(config.JADE_API_URL or config.JADE_TOKEN)


def enqueue(db: Session, lab: Lab) -> None:
    if enabled():
        db.add(JadeRegistration(
            lab_id=lab.id,
            external_id=f"{config.JADE_SOURCE_ID or uuid.uuid4().hex}:{lab.id}",
        ))


def _validate_url(value: str, label: str) -> None:
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or any(char.isspace() for char in value)):
        raise ValueError(f"Configure a valid {label} base URL without credentials, query or fragment.")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError(f"Configure a valid port for {label}.")


def build_payload(lab: Lab, registration: JadeRegistration) -> dict[str, object]:
    from .lab_service import current_phase, lab_status

    for value, label in [
        (config.JADE_API_URL, "HOLO_JADE_API_URL"),
        (config.JADE_PUBLIC_URL, "HOLO_JADE_PUBLIC_URL"),
        (config.PUBLIC_URL, "HOLO_PUBLIC_URL"),
    ]:
        _validate_url(value, label)
    if len(config.JADE_TOKEN) < 32:
        raise ValueError("Configure HOLO_JADE_TOKEN with at least 32 characters matching JADE.")
    if (not config.JADE_SOURCE_ID or len(config.JADE_SOURCE_ID) > 128
            or any(char.isspace() for char in config.JADE_SOURCE_ID)):
        raise ValueError("Configure a stable, unique HOLO_JADE_SOURCE_ID without whitespace.")
    if not lab.owner or not lab.owner.email.strip():
        raise ValueError("Assign a lab owner whose email is registered in JADE.")
    if not lab.abstract.strip():
        raise ValueError("Add an abstract to this HOL, then retry JADE registration.")
    phase = current_phase(lab)
    lifecycle = ("Published" if lab_status(lab) == "Complete" else
                 "Ideation" if phase is not None and phase.position == 0 else "Development")
    if lab.archived_at is not None:
        lifecycle = "Retired"
    return {
        "source": "HOLO", "external_id": registration.external_id,
        "title": lab.name, "description": lab.abstract, "owner": lab.owner.email,
        "creating_team": config.JADE_TEAM, "technology": config.JADE_TECHNOLOGY,
        "audience": [config.JADE_AUDIENCE], "access_level": config.JADE_ACCESS,
        "asset_type": "Hands-On Lab", "lifecycle_status": lifecycle,
        "tags": ["HOLO"] + ([lab.course_id] if lab.course_id else []),
        "content_links": [
            {"type": "Web page", "label": "HOLO lab workflow",
             "url": f"{config.PUBLIC_URL}/labs/{lab.id}"},
            *[{"type": "Other", "label": link.label, "url": link.url} for link in lab.links],
        ],
    }


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_asset(payload: dict[str, object]) -> RegistrationResult:
    request = Request(
        f"{config.JADE_API_URL}/api/v1/assets",
        data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {config.JADE_TOKEN}", "Content-Type": "application/json"},
    )
    with build_opener(NoRedirect()).open(request, timeout=10) as response:
        if response.status not in (200, 201):
            raise ValueError("JADE returned an unexpected success status; check the API URL.")
        raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("JADE returned an oversized response.")
        result = json.loads(raw)
    asset_id = result.get("id") if isinstance(result, dict) else None
    if (type(asset_id) is not int or asset_id <= 0
            or result.get("record_path") != f"/assets/{asset_id}"
            or result.get("external_id") != payload["external_id"]
            or result.get("source") != "HOLO"):
        raise ValueError("JADE returned an invalid registration response; check the API URL.")
    return {
        "id": asset_id, "record_path": result["record_path"],
        "source": result["source"], "external_id": result["external_id"],
    }


def process_one(db: Session) -> bool:
    now = datetime.utcnow()
    available = or_(
        (JadeRegistration.state == "pending") & (JadeRegistration.next_attempt_at <= now),
        (JadeRegistration.state == "processing") & (JadeRegistration.lease_until <= now),
    )
    job = db.query(JadeRegistration).filter(available).order_by(JadeRegistration.next_attempt_at).first()
    if job is None:
        return False
    lease = now + timedelta(minutes=2)
    claimed = db.query(JadeRegistration).filter(
        JadeRegistration.lab_id == job.lab_id, available,
    ).update({
        JadeRegistration.state: "processing", JadeRegistration.lease_until: lease,
        JadeRegistration.attempts: JadeRegistration.attempts + 1,
    }, synchronize_session=False)
    db.commit()
    if not claimed:
        return False
    db.refresh(job)
    values: dict[str, str | int | datetime | None]
    try:
        lab = db.get(Lab, job.lab_id)
        if lab is None:
            raise ValueError("The source HOL no longer exists.")
        result = post_asset(build_payload(lab, job))
    except HTTPError as exc:
        retry = exc.code == 429 or exc.code >= 500
        message = f"JADE HTTP {exc.code}. Check API configuration and the registered owner."
        if exc.code == 422:
            try:
                detail = json.loads(exc.read(65536)).get("detail")
                if isinstance(detail, str):
                    message = f"JADE validation: {detail}"
            except (ValueError, AttributeError):
                message = "JADE rejected the lab metadata. Check required fields and allowed values."
        values = _failed(job, retry, message)
        exc.close()
    except (URLError, socket.timeout, OSError):
        values = _failed(job, True, "JADE is unreachable or timed out. Automatic retry is scheduled.")
    except (ValueError, UnicodeError) as exc:
        values = _failed(job, False, str(exc))
    else:
        values = {
            "state": "registered", "jade_asset_id": result["id"],
            "record_url": f"{config.JADE_PUBLIC_URL}{result['record_path']}",
            "last_error": "", "lease_until": None,
        }
        logger.info("HOL %s registered in JADE as asset %s", job.lab_id, result["id"])
    db.execute(update(JadeRegistration).where(
        JadeRegistration.lab_id == job.lab_id, JadeRegistration.state == "processing",
        JadeRegistration.lease_until == lease,
    ).values(**values).execution_options(synchronize_session=False))
    db.commit()
    db.expire(job)
    return True


def _failed(job: JadeRegistration, retry: bool, message: str) -> dict[str, str | int | datetime | None]:
    state = "pending" if retry else "needs_attention"
    error = message.replace(config.JADE_TOKEN, "[redacted]")[:1000] if config.JADE_TOKEN else message[:1000]
    logger.warning("HOL %s JADE registration %s: %s", job.lab_id, state, error)
    return {
        "state": state, "last_error": error, "lease_until": None,
        "next_attempt_at": datetime.utcnow() + timedelta(seconds=min(3600, 30 * 2 ** min(job.attempts, 7))),
    }


def retry(db: Session, job: JadeRegistration) -> bool:
    now = datetime.utcnow()
    changed = db.query(JadeRegistration).filter(
        JadeRegistration.lab_id == job.lab_id,
        or_(JadeRegistration.state.in_(["pending", "needs_attention"]),
            (JadeRegistration.state == "processing") & (JadeRegistration.lease_until <= now)),
    ).update({
        JadeRegistration.state: "pending", JadeRegistration.next_attempt_at: now,
        JadeRegistration.lease_until: None, JadeRegistration.last_error: "",
    }, synchronize_session=False)
    db.commit()
    return bool(changed)


def run_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        if enabled():
            try:
                with SessionLocal() as db:
                    process_one(db)
            except SQLAlchemyError:
                logger.exception("JADE outbox database operation failed; retrying on the next pass.")
        stop.wait(5)
