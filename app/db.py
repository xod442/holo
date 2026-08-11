"""Database engine, session factory, and schema init."""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config

engine = create_engine(
    f"sqlite:///{config.DB_PATH}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  (register mappers before create_all)
    Base.metadata.create_all(engine)
    _ensure_columns()
    seed_default_admin()
    seed_default_manager()
    seed_mail_config()


def _ensure_columns() -> None:
    """Add columns introduced after a table already exists (lightweight migration)."""
    with engine.begin() as conn:
        user_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        if "must_change_password" not in user_cols:
            conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN "
                    "must_change_password BOOLEAN NOT NULL DEFAULT 0"
                )
            )

        task_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(tasks)"))}
        if "note" not in task_cols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN note TEXT NOT NULL DEFAULT ''"))

        phase_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(phases)"))}
        if "notes" not in phase_cols:
            conn.execute(text("ALTER TABLE phases ADD COLUMN notes TEXT NOT NULL DEFAULT ''"))
        if "target_date" not in phase_cols:
            conn.execute(text("ALTER TABLE phases ADD COLUMN target_date TEXT NOT NULL DEFAULT ''"))
        if "requires_approval" not in phase_cols:
            conn.execute(
                text("ALTER TABLE phases ADD COLUMN requires_approval BOOLEAN NOT NULL DEFAULT 0")
            )
            # Backfill existing labs: only these four phases need sign-off.
            conn.execute(
                text(
                    "UPDATE phases SET requires_approval = 1 WHERE name IN "
                    "('Design', 'Develop', 'Testing & Feedback', 'Production')"
                )
            )


def seed_default_admin() -> None:
    """Create the default admin on a fresh database (no users yet)."""
    from .models import User, ROLE_ADMIN
    from .security import hash_password

    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            return
        db.add(
            User(
                email=config.DEFAULT_ADMIN_USERNAME,
                password_hash=hash_password(config.DEFAULT_ADMIN_PASSWORD),
                role=ROLE_ADMIN,
                must_change_password=True,
            )
        )
        db.commit()
    finally:
        db.close()


def seed_default_manager() -> None:
    """Ensure a predefined manager (approver) exists; must change pw on first login."""
    from .models import User, ROLE_MANAGER
    from .security import hash_password

    db = SessionLocal()
    try:
        if db.query(User).filter(User.role == ROLE_MANAGER).count() > 0:
            return
        db.add(
            User(
                email=config.DEFAULT_MANAGER_USERNAME,
                password_hash=hash_password(config.DEFAULT_MANAGER_PASSWORD),
                role=ROLE_MANAGER,
                must_change_password=True,
            )
        )
        db.commit()
    finally:
        db.close()


def seed_mail_config() -> None:
    """Ensure the single mail-config row exists."""
    from .models import MailConfig

    db = SessionLocal()
    try:
        if db.get(MailConfig, 1) is None:
            db.add(MailConfig(id=1))
            db.commit()
    finally:
        db.close()
