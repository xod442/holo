"""Outbound email via an unauthenticated SMTP forwarder, and phase-event dispatch.

Failures never break a lab transition — they're logged and swallowed at the
notify boundary so the workflow always proceeds.
"""
import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage

from sqlalchemy.orm import Session

from .models import GitHubManager, Lab, MailConfig, NOTIFY_SUBMITTED, PhaseSubscription

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
        refused = server.send_message(msg)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)


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


def send(db: Session, to_address: str, subject: str, body: str) -> tuple[bool, str]:
    """Send a one-off email (e.g. an invitation) via the forwarder.

    Requires host + from to be set; independent of the phase-notification toggle."""
    cfg = get_config(db)
    if cfg is None or not cfg.host:
        return False, "No mail forwarder host configured (set it in the admin console)."
    if not cfg.mail_from:
        return False, "No 'from' address configured for the mail forwarder."
    to_address = (to_address or "").strip()
    if "@" not in to_address:
        return False, "No valid recipient address."
    try:
        _send(cfg, [to_address], subject, body)
        return True, f"Email sent to {to_address}."
    except Exception as exc:  # noqa: BLE001 — surface the relay error
        logger.warning("HOLO send failed: %s", exc)
        return False, f"Send failed: {exc}"


def send_github_request(db: Session, lab: Lab) -> tuple[bool, str]:
    """Send a repository request once per lab, independently of phase notifications."""
    if lab.github_request_sent_at is not None:
        return True, "GitHub repository request was already sent."
    cfg = get_config(db)
    recipients = [manager.email for manager in
                  db.query(GitHubManager).order_by(GitHubManager.email)]
    error = ""
    if not recipients:
        error = "No GitHub managers configured in the Admin console."
    elif cfg is None or not cfg.host or not cfg.mail_from:
        error = "Configure the mail forwarder host and from address in the Admin console."
    elif lab.owner is None:
        error = "Assign a lab owner so the repository request has a requestor."
    if error:
        logger.warning("GitHub repository request not sent for lab %s: %s", lab.id, error)
        return False, error
    assert cfg is not None and lab.owner is not None
    lines = [
        "Please prepare a GitHub repository for a new Hands On Lab.",
        "",
        f"Lab: {lab.name}",
        f"Requestor: {lab.owner.email}",
    ]
    if cfg.app_base_url:
        lines.extend(["", f"Open in HOLO: {cfg.app_base_url.rstrip('/')}/labs/{lab.id}"])
    try:
        _send(cfg, recipients, f"[HOLO] GitHub repository request: {lab.name}", "\n".join(lines))
    except (smtplib.SMTPException, OSError, ValueError) as exc:
        logger.warning("GitHub repository request failed for lab %s: %s", lab.id, exc)
        return False, f"Mail forwarder failed: {exc}"
    lab.github_request_sent_at = datetime.utcnow()
    db.add(lab)
    db.commit()
    logger.info("GitHub repository request sent for lab %s to %d manager(s)", lab.id, len(recipients))
    return True, "GitHub repository request emailed to the GitHub managers."


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
    """Email matching lists and the manager for approval requests. Best-effort."""
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
    if event == NOTIFY_SUBMITTED and "@" in cfg.manager_email:
        recipients.add(cfg.manager_email)
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
