"""App configuration, driven by environment variables with dev-friendly defaults."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = os.getenv("HOLO_DB_PATH", str(BASE_DIR / "holo.db"))

# Session cookie. Per-app name + Secure by default so an edge session-handling
# change (theedge.ext.hpe.com) can't cross-break logins with sibling apps.
SECRET_KEY = os.getenv("HOLO_SECRET_KEY") or secrets.token_hex(32)
COOKIE_NAME = os.getenv("HOLO_COOKIE_NAME", "holo_session")
COOKIE_SECURE = os.getenv("HOLO_COOKIE_SECURE", "1") == "1"

# How long an invite link stays valid.
INVITE_TTL_DAYS = int(os.getenv("HOLO_INVITE_TTL_DAYS", "7"))

# Subpath the app is served under behind a reverse proxy / the HPE edge
# (e.g. "/holo"), so generated URLs and invite links are correct. Empty = root.
ROOT_PATH = os.getenv("HOLO_ROOT_PATH", "")

# Default admin, seeded on first startup when there are no users at all.
# Username has no domain by design; the password must be changed on first login.
DEFAULT_ADMIN_USERNAME = os.getenv("HOLO_ADMIN_USERNAME", "admin").strip().lower()
DEFAULT_ADMIN_PASSWORD = os.getenv("HOLO_ADMIN_PASSWORD", "admin")

# Predefined manager (approver). Seeded if no manager exists; must change
# password on first login. Same tools as admin, plus approval authority.
DEFAULT_MANAGER_USERNAME = os.getenv("HOLO_MANAGER_USERNAME", "manager").strip().lower()
DEFAULT_MANAGER_PASSWORD = os.getenv("HOLO_MANAGER_PASSWORD", "manager")

# Second predefined admin account (same access as the default admin — access
# is role-based, not per-user). Seeded if this username doesn't exist yet;
# must change password on first login.
DEFAULT_ADMIN2_USERNAME = os.getenv("HOLO_ADMIN2_USERNAME", "admin-holo").strip().lower()
DEFAULT_ADMIN2_PASSWORD = os.getenv("HOLO_ADMIN2_PASSWORD", "admin-holo")

USING_EPHEMERAL_SECRET = os.getenv("HOLO_SECRET_KEY") is None

# Backups: written to the volume (default alongside the DB) with retention.
BACKUP_DIR = os.getenv("HOLO_BACKUP_DIR", str(Path(DB_PATH).parent / "backups"))
BACKUP_KEEP = int(os.getenv("HOLO_BACKUP_KEEP", "30"))

# ── Single sign-on hand-off with FOCUS (same host, separate app/DB) ─────────
# Works both ways:
# - Incoming (from FOCUS): FOCUS generates a short-lived, signed token (the
#   user's own email, nothing else) and redirects here. We independently
#   verify the signature (shared secret, set identically in both apps' env —
#   NOT the same as either app's own SECRET_KEY) and log the person in if a
#   matching HOLO account exists.
# - Outgoing (to FOCUS): the "FOCUS" nav button does the same thing in
#   reverse, generating a token for the current HOLO user and redirecting to
#   FOCUS's own accepting route.
# Empty secret = both hand-off directions are disabled (buttons hidden,
# routes reject everything).
SSO_SHARED_SECRET = os.getenv("SSO_SHARED_SECRET", "").strip()
SSO_SALT = "focus-holo-sso"
SSO_TOKEN_MAX_AGE = 60  # seconds — must match the value FOCUS signs with
FOCUS_BASE_URL = os.getenv("FOCUS_BASE_URL", "http://localhost:9094").rstrip("/")
