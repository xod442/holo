"""Outbound email via an unauthenticated SMTP forwarder, and phase-event dispatch.

Failures never break a lab transition — they're logged and swallowed at the
notify boundary so the workflow always proceeds.
"""
import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from .models import MailConfig, PhaseSubscription

logger = logging.getLogger("holo.notifier")

SMTP_TIMEOUT = 5  # seconds — bound the request if the relay is unreachable


def get_config(db: Session) -> MailConfig | None:
    return db.get(MailConfig, 1)


def _send(cfg: MailConfig, recipients: list[str], subject: str, body: str) -> None:
    """Send one message through the relay (no auth). Raises on failure."""
    msg = EmailMessage()
    msg["From"] = cfg.mail_from
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(cfg.host, cfg.port, timeout=SMTP_TIMEOUT) as server:
        server.send_message(msg)


def send_test(db: Session, to_address: str) -> tuple[bool, str]:
    """Send a test email. Returns (ok, message) for the admin UI."""
    cfg = get_config(db)
    if cfg is None or not cfg.host:
        return False, "No forwarder host configured."
    if not cfg.mail_from:
        return False, "No 'from' address configured."
    recipient = (to_address or cfg.default_to or "").strip()
    if not recipient:
        return False, "No recipient — set a default 'to' or enter a test address."
    try:
        _send(cfg, [recipient], "HOLO test email",
              "This is a test message from HOLO. If you received it, the "
              "mail forwarder is configured correctly.")
        return True, f"Test email sent to {recipient}."
    except Exception as exc:  # noqa: BLE001 — surface any relay error to the admin
        logger.warning("HOLO test email failed: %s", exc)
        return False, f"Send failed: {exc}"


def _body(cfg: MailConfig, lab, phase, event: str) -> str:
    lines = [
        f"Lab:    {lab.name}",
        f"Phase:  {phase.name} ({phase.stage})",
        f"Event:  {event}",
    ]
    if cfg.app_base_url:
        base = cfg.app_base_url.rstrip("/")
        lines.append(f"\nOpen in HOLO: {base}/labs/{lab.id}")
    return "\n".join(lines)


def notify_phase_event(db: Session, lab, phase, event: str) -> None:
    """Email every list subscribed to (phase name, event). Best-effort."""
    cfg = get_config(db)
    if cfg is None or not cfg.enabled or not cfg.host:
        return

    subs = (
        db.query(PhaseSubscription)
        .filter(PhaseSubscription.phase_name == phase.name,
                PhaseSubscription.event == event)
        .all()
    )
    recipients: set[str] = set()
    for sub in subs:
        for r in sub.list.recipients:
            recipients.add(r.email)
    if not recipients:
        return

    subject = f"[HOLO] {lab.name}: {phase.name} — {event}"
    try:
        _send(cfg, sorted(recipients), subject, _body(cfg, lab, phase, event))
        logger.info("Notified %d recipient(s) for %s/%s", len(recipients), phase.name, event)
    except Exception as exc:  # noqa: BLE001 — never break the transition
        logger.warning("HOLO notify failed (%s/%s): %s", phase.name, event, exc)
