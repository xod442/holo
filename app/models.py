"""ORM models: auth + invites (phase 1) and the gated lab lifecycle (phase 2)."""
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_MEMBER = "member"
VALID_ROLES = (ROLE_ADMIN, ROLE_MANAGER, ROLE_MEMBER)
# Admin-tool access (console, invites, backups, notifications, Swagger).
STAFF_ROLES = (ROLE_ADMIN, ROLE_MANAGER)
# Only the manager approves phase submissions (admin does everything else).

# Phase lifecycle states.
PHASE_NOT_STARTED = "not_started"
PHASE_IN_PROGRESS = "in_progress"
PHASE_AWAITING = "awaiting_approval"   # approval phases only
PHASE_APPROVED = "approved"            # approval phases, signed off by admin
PHASE_COMPLETED = "completed"          # non-approval phases, marked done by user
PHASE_BLOCKED = "blocked"

# Both count as "done" for gating and progress.
PHASE_DONE_STATES = (PHASE_APPROVED, PHASE_COMPLETED)

# Notification trigger events (which phase transition fired).
NOTIFY_SUBMITTED = "submitted"   # approval phase sent for sign-off
NOTIFY_APPROVED = "approved"     # approval phase approved
NOTIFY_COMPLETED = "completed"   # completion phase marked done
NOTIFY_EVENTS = (NOTIFY_SUBMITTED, NOTIFY_APPROVED, NOTIFY_COMPLETED)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default=ROLE_MEMBER)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String, default=ROLE_MEMBER)
    # Raw single-use token, stored so the admin can re-copy the link from the
    # home screen. Acceptable for internal, expiring, single-use invites.
    token: Mapped[str] = mapped_column(String, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Lab(Base):
    __tablename__ = "labs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    target_release: Mapped[str] = mapped_column(String, default="")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Archived labs are hidden from the dashboard/mallmanac (None = active).
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archived_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    owner: Mapped["User | None"] = relationship("User", foreign_keys=[owner_id])
    archived_by: Mapped["User | None"] = relationship("User", foreign_keys=[archived_by_id])
    phases: Mapped[list["Phase"]] = relationship(
        "Phase",
        back_populates="lab",
        cascade="all, delete-orphan",
        order_by="Phase.position",
    )
    links: Mapped[list["LabLink"]] = relationship(
        "LabLink",
        back_populates="lab",
        cascade="all, delete-orphan",
        order_by="LabLink.created_at",
    )


class Phase(Base):
    __tablename__ = "phases"

    id: Mapped[int] = mapped_column(primary_key=True)
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    estimated_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_hours: Mapped[float] = mapped_column(Float, default=0.0)
    state: Mapped[str] = mapped_column(String, default=PHASE_NOT_STARTED)
    # True = needs admin sign-off (Submit → Approve); False = user clicks Completed.
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    # Planned/target completion date for this phase (YYYY-MM-DD string, or "").
    target_date: Mapped[str] = mapped_column(String, default="")

    lab: Mapped["Lab"] = relationship("Lab", back_populates="phases")
    tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="phase",
        cascade="all, delete-orphan",
        order_by="Task.position",
    )
    approval: Mapped["Approval | None"] = relationship(
        "Approval",
        back_populates="phase",
        cascade="all, delete-orphan",
        uselist=False,
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    phase_id: Mapped[int] = mapped_column(ForeignKey("phases.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String)
    note: Mapped[str] = mapped_column(Text, default="")
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    done_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    phase: Mapped["Phase"] = relationship("Phase", back_populates="tasks")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    phase_id: Mapped[int] = mapped_column(ForeignKey("phases.id"), unique=True, index=True)
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    phase: Mapped["Phase"] = relationship("Phase", back_populates="approval")
    approver: Mapped["User | None"] = relationship("User")


class LabLink(Base):
    """A document/resource link for a workshop (e.g. a SharePoint document)."""
    __tablename__ = "lab_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id"), index=True)
    label: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(Text)
    added_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lab: Mapped["Lab"] = relationship("Lab", back_populates="links")
    added_by: Mapped["User | None"] = relationship("User")


class MailConfig(Base):
    """Single-row config for the outbound (unauthenticated) SMTP forwarder."""
    __tablename__ = "mail_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    host: Mapped[str] = mapped_column(String, default="")   # relay host / IP
    port: Mapped[int] = mapped_column(Integer, default=25)
    mail_from: Mapped[str] = mapped_column(String, default="")
    default_to: Mapped[str] = mapped_column(String, default="")  # fallback / test target
    app_base_url: Mapped[str] = mapped_column(String, default="")  # for links in emails


class NotificationList(Base):
    """A named team recipient list (e.g. 'vLabs Team')."""
    __tablename__ = "notification_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True)
    description: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    recipients: Mapped[list["NotificationRecipient"]] = relationship(
        "NotificationRecipient",
        back_populates="list",
        cascade="all, delete-orphan",
        order_by="NotificationRecipient.email",
    )
    subscriptions: Mapped[list["PhaseSubscription"]] = relationship(
        "PhaseSubscription",
        back_populates="list",
        cascade="all, delete-orphan",
    )


class NotificationRecipient(Base):
    __tablename__ = "notification_recipients"

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("notification_lists.id"), index=True)
    email: Mapped[str] = mapped_column(String)

    list: Mapped["NotificationList"] = relationship("NotificationList", back_populates="recipients")


class PhaseSubscription(Base):
    """Notify a list when a given phase (by name) hits a given event."""
    __tablename__ = "phase_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("notification_lists.id"), index=True)
    phase_name: Mapped[str] = mapped_column(String, index=True)
    event: Mapped[str] = mapped_column(String)

    list: Mapped["NotificationList"] = relationship("NotificationList", back_populates="subscriptions")
