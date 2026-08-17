# HOLO — Hands-On Lab Orchestrator

HOLO tracks hands-on labs (workshops) through HPE Technical Enablement's 8-phase,
gated production pipeline — from first concept to a production-ready course. It's a
FastAPI + SQLite app, Dockerized, Opal-styled (dark theme, HPE branding).

- **Portfolio dashboard** with an 8-segment progress bar per lab + owner filter
- **Mallmanac** — a "You Are Here!" lifecycle map across all labs
- **Per-lab calendar** of phase target dates
- **Gated lifecycle** — approval gates vs. completion steps, per-step notes, target dates
- **Time Warp** — admin clicks any sub-process pill on the Mallmanac to fast-forward
  a lab that was already completed/near-complete before HOLO existed straight to
  that exact step, auto-approving/completing everything before it
- **Documents & resources** (SharePoint links) per lab
- **Notifications** — a configurable SMTP forwarder + phase-triggered team emails
- **Admin** — users/invites, daily backups + restore, self-hosted Swagger
- **System Log** — every state-changing action, by every user, in one filterable audit trail

---

## Roles & permissions

HOLO has three roles: **Admin**, **Manager**, and **Member**.

- **Admin** and **Manager** share all administrative tools.
- **Only the Manager approves phase submissions.** The Admin does everything *except* approve — that gate belongs to the Manager.
- **Member** is a regular lab contributor.

### Permission matrix

| Capability | Admin | Manager | Member |
|---|:---:|:---:|:---:|
| Sign in / change own password | ✅ | ✅ | ✅ |
| View dashboard, mallmanac, calendars, labs | ✅ | ✅ | ✅ |
| Create a lab (becomes owner) | ✅ | ✅ | ✅ |
| Edit pills: tasks, notes, hours, **target dates** | ✅ | ✅ | ✅ |
| Start a phase / **submit** a phase for approval | ✅ | ✅ | ✅ |
| Mark a completion phase **done** | ✅ | ✅ | ✅ |
| Block / unblock a phase | ✅ | ✅ | ✅ |
| Add / remove document (SharePoint) links | ✅ | ✅ | ✅ |
| Reassign a lab's **record owner** | ✅ | ✅ | own labs |
| **Approve a phase submission** | ❌ | ✅ | ❌ |
| See the "Awaiting your approval" queue | ❌ | ✅ | ❌ |
| Admin console (`/admin`) | ✅ | ✅ | ❌ |
| Invite users / choose their role | ✅ | ✅ | ❌ |
| Manage notification lists & SMTP forwarder | ✅ | ✅ | ❌ |
| Database backup / restore | ✅ | ✅ | ❌ |
| **Time Warp** a lab to any sub-process step | ✅ | ❌ | ❌ |
| API docs / Swagger (`/docs`) | ✅ | ✅ | ❌ |
| System log (`/admin/log`) | ✅ | ✅ | ❌ |

> **In short:** Members build labs and submit phases for sign-off. Admins run the
> system (users, backups, notifications, API) but **cannot approve**. The Manager
> holds the approval gate.

### Default accounts (first run)

All three are seeded automatically and **must change their password on first login**:

| Role | Username | Password |
|------|----------|----------|
| Admin | `admin` | `admin` |
| Admin | `admin-holo` | `admin-holo` |
| Manager | `manager` | `manager` |

`admin-holo` is a second admin account with **identical access** to `admin`
(access is role-based, not per-user) — useful as a backup/break-glass login or
for a second administrator. Unlike `admin` (only seeded on a brand-new,
user-less database), `admin-holo` is seeded by username on every startup, so
it's added automatically even to an existing database that doesn't have it yet.

Override the seeded values with the `HOLO_ADMIN_*` / `HOLO_ADMIN2_*` / `HOLO_MANAGER_*`
env vars (see [Configuration](#configuration)). Additional users are added by
**invitation** from the admin console (single-use, expiring links you copy and send).

---

## The pipeline

Every lab is created from an 8-phase template, grouped into **Development** and
**Production**. Two kinds of phase:

- **Approval phase** — `Start → Submit → Manager approves` (the gate).
- **Completion phase** — the owner clicks **Mark completed** (no approval needed).

A phase is **locked** until every earlier phase is done; finishing one auto-activates
the next.

| Code | Phase | Stage | Type | Est. hrs |
|------|-------|-------|------|:---:|
| dev-1 | Concept | Development | Completion | 8 |
| dev-2 | Design | Development | **Approval** | 16 |
| dev-3 | Develop | Development | **Approval** | 40 |
| dev-4 | Video Demo | Development | Completion | — |
| prod-1 | Testing & Feedback | Production | **Approval** | 80 |
| prod-2 | Publish | Production | Completion | 32 |
| prod-3 | Production | Production | **Approval** | 80 |
| prod-4 | Post-Production Acceptance | Production | Completion | — |

Each pill has its sub-process **tasks** (checkable), a **per-step note** on each task,
**phase notes**, an **actual-hours** field vs. the estimate, and a **target date**
(flatpickr) — all saved with one **Save** button.

---

## Views

- **Dashboard** (`/`) — one card per lab: 8-segment progress bar, status, % done,
  current phase, hours. Filter by **owner**. Managers also see an **approval queue**.
- **Mallmanac** (`/mallmanac`) — the "You Are Here!" map: each lab's 8 phase columns
  (4 dev / 4 prod) with task pills; a 📍 pin marks the furthest completed task.
  Admins can toggle **Time Warp mode** here and click any pill to fast-forward
  that lab straight to that exact sub-process step.
- **Lab detail** (`/labs/{id}`) — the workspace: pills, tasks, notes, hours, target
  dates, document links, record owner, and the phase actions.
- **Lab calendar** (`/labs/{id}/calendar`) — a month grid plotting phases on their
  target dates, with an "unscheduled" list.
- **Time Warp** (on the Mallmanac, admin-only) — pick the exact sub-process a lab
  is really at, down to a single task pill (not just a whole phase). Every phase
  strictly before it is marked done (approvals auto-approved, tasks checked off);
  its own phase is activated and every task up through the one you picked is
  checked off too, but the phase itself stays open so you can still gate it
  normally. Forward-only, and it never sends notification emails (it's a
  historical correction, not a live event).
- **System Log** (`/admin/log`, staff-only) — every state-changing action across the
  app, newest first, filterable by user and action, paginated.

---

## Run it with Docker (recommended)

```bash
cd ~/holo
cp .env.example .env
python3 -c "import secrets; print('HOLO_SECRET_KEY=' + secrets.token_hex(32))" >> .env
# local plain-HTTP testing only:
echo 'HOLO_COOKIE_SECURE=0' >> .env

docker compose up -d --build
```

Open the app (locally mapped to **http://127.0.0.1:8010** via `HOLO_PORT`), sign in as
`admin` / `admin` (or `admin-holo` / `admin-holo`, or `manager` / `manager`), and set a
new password when prompted. Data persists in the `holo-data` volume.

### Run it locally (no Docker)

```bash
cd ~/holo
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

---

## Testing & CI

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

ruff check .                                # lint
pytest                                      # tests
pytest --cov --cov-report=term-missing      # tests + coverage
```

Tests spin up an isolated in-memory SQLite database per test (no `holo.db` on
disk is touched) and exercise the app through FastAPI's `TestClient` — real
HTTP requests, real session cookies, real password hashing. Coverage focuses
on the highest-risk areas: login/logout/invite registration, the forced
password-change flow, and the phase-gating/RBAC rules (only a Manager may
approve a submitted phase; staff-only routes reject Members).

A GitHub Actions workflow (`.github/workflows/ci.yml`) runs `ruff` + `pytest`
on every push and pull request to `main`.

---

## Configuration

| Var | Default | Purpose |
|-----|---------|---------|
| `HOLO_SECRET_KEY` | random (ephemeral) | Session signing key. **Set a fixed value in prod** or sessions drop on restart. |
| `HOLO_COOKIE_NAME` | `holo_session` | Per-app cookie name (avoids edge cross-app collisions). |
| `HOLO_COOKIE_SECURE` | `1` | Cookie over HTTPS only. Set `0` for local HTTP. |
| `HOLO_DB_PATH` | `/data/holo.db` (Docker) | SQLite file path. |
| `HOLO_ROOT_PATH` | `` (root) | Subpath when served behind the edge, e.g. `/holo`. |
| `HOLO_INVITE_TTL_DAYS` | `7` | Invite link lifetime. |
| `HOLO_ADMIN_USERNAME` / `HOLO_ADMIN_PASSWORD` | `admin` / `admin` | Seeded admin (fresh DB); must change on first login. |
| `HOLO_ADMIN2_USERNAME` / `HOLO_ADMIN2_PASSWORD` | `admin-holo` / `admin-holo` | Seeded second admin (same access as admin); seeded by username on every startup; must change on first login. |
| `HOLO_MANAGER_USERNAME` / `HOLO_MANAGER_PASSWORD` | `manager` / `manager` | Seeded manager (approver); must change on first login. |
| `HOLO_BACKUP_DIR` | `<db dir>/backups` | Where backups are written (on the volume). |
| `HOLO_BACKUP_KEEP` | `30` | Number of backups retained. |
| `HOLO_PORT` | `8000` | Host port mapping (Docker). |
| `SSO_SHARED_SECRET` | *(empty — disabled)* | Enables the `/sso/focus` single sign-on hand-off from FOCUS; must match FOCUS's own `SSO_SHARED_SECRET` exactly. |

---

## Single sign-on from FOCUS

FOCUS (same host, port 9094 by default) can hand off an already-authenticated
user straight into HOLO: it generates a short-lived (60s), signed token
containing just that user's email and redirects to `GET /sso/focus?token=...`.
HOLO independently verifies the signature and, if a HOLO account with that
same email exists, logs them in with no separate login step — no account is
ever auto-created. An invalid/expired/mismatched-secret token, or no matching
email, redirects to `/login` with a clear error message instead.

Requires `SSO_SHARED_SECRET` to be set to the exact same value in both apps'
`.env` files — a secret shared between the two apps, **not** either app's own
`HOLO_SECRET_KEY`/`FOCUS_SECRET_KEY` (which sign session cookies, not this
hand-off). Leave it empty to disable the route entirely.

---

## Backups & restore

- **Automatic daily backup** — an in-process scheduler writes one backup per calendar
  day to `HOLO_BACKUP_DIR` (SQLite online-backup API; keeps the newest `HOLO_BACKUP_KEEP`).
- **Admin console** → *Database backup*: **Back up now**, download any backup, and
  **restore** — either by uploading a downloaded `.db` or restoring an existing one.
- Restore **validates** the file (integrity check + HOLO schema) and takes a
  **safety backup** of the current DB first. You may need to sign in again afterward.

> DR note: backups live on the **same volume** as the DB. For off-box safety, download
> copies or mount `HOLO_BACKUP_DIR` elsewhere.

---

## Notifications

Admin console → **Notifications** (`/admin/notifications`):

1. Configure the **mail forwarder** — an *unauthenticated* SMTP relay (host/IP, port,
   from, default-to). Toggle **Enabled** and use **Send test email** to verify.
2. Create **notification lists** (teams) and add recipient emails.
3. Add **triggers** per list: a phase + an event (`submitted` / `approved` /
   `completed`). When that phase hits that event, the list is emailed.

Sending is best-effort (short timeout) — a mail failure never blocks a phase from
advancing.

---

## Deploying to production

**Config & secrets**
- Set a fixed **`HOLO_SECRET_KEY`** (long random hex) in the prod env / secret store — never in git. If unset it's random per boot and sessions drop on every restart.
- Set **`HOLO_ROOT_PATH`** to the subpath the edge serves (e.g. `/holo`) so links and invite/asset URLs resolve.
- Keep **`HOLO_COOKIE_SECURE=1`** (needs HTTPS) and a unique **`HOLO_COOKIE_NAME`**.
- Pre-seed prod logins via `HOLO_ADMIN_*` / `HOLO_MANAGER_*`, or change `admin`/`manager` at first login (both force a change).
- If enabling the FOCUS SSO hand-off, set **`SSO_SHARED_SECRET`** to the same long random value in both apps' prod env.

**Edge / serving**
- Serve behind the HPE edge with TLS; ensure the proxy passes `X-Forwarded-Proto/Host` (run uvicorn with `--proxy-headers` if needed).
- Assets are vendored (HPE logo, Swagger, flatpickr) — don't swap any to a CDN (the edge blocks them).
- If login bounces with no error and you didn't deploy, suspect the **edge session policy**, not the app.

**Data & backups**
- Put the `holo-data` volume on persistent storage. Backups land on the **same volume** — set up an off-box copy (mount `HOLO_BACKUP_DIR` externally or download regularly) and **test a restore**.

**Clean start**
- Start prod with an **empty volume** so only the seeded `admin` + `admin-holo` + `manager` exist (no demo labs/users).

**Mail**
- In Admin → Mail forwarder, set the real SMTP relay + `App base URL`, enable it, and send a test.

**Runtime**
- Container runs as a **non-root user** and deps are **pinned** (see `requirements.txt`).
- Keep a **single uvicorn worker** (the daily-backup scheduler runs per-process and SQLite is single-writer).
- Capture/rotate logs.

**Before go-live**
- Rotate `admin`/`admin-holo`/`manager` and any passwords typed during setup.
- Consider login rate-limiting at the edge (the app doesn't throttle). Note: forms have no CSRF token (session cookie is `SameSite=Lax`).
- Smoke test: login (admin + manager), create lab → Submit → Approve, invite + email a user, reset a password, back up + restore.

## Notes & conventions

- **Assets are vendored** (HPE logo, Swagger UI, flatpickr) and served from `/static` —
  the HPE VPN blocks external CDNs, so nothing is hotlinked.
- The **HPE logo** is the official asset; do not recolor it.
- Behind the HPE edge (`theedge.ext.hpe.com`), set `HOLO_ROOT_PATH` and a per-app
  `HOLO_COOKIE_NAME`; if logins break with no deploy, suspect the edge session policy.

## Status

**Implemented**

- **Auth & roles** — invite-only registration (copy link or email it via the
  forwarder); admin / manager / member; seeded admin + second admin (`admin-holo`)
  + manager with forced first-login password change; self-service password
  change; **staff password reset** (temporary password + forced change).
- **Gated lifecycle** — 8-phase template (approval vs. completion), per-step
  task notes, phase notes, actual-vs-estimate hours, target dates (flatpickr);
  manager-only approvals; block/unblock.
- **Time Warp** — admin-only, click-any-pill fast-forward on the Mallmanac for
  labs that predate HOLO, down to a single sub-process step (not just a whole
  phase), auto-approving/completing everything before it (silent, forward-only,
  fully audited).
- **Views** — portfolio dashboard (+owner filter), Mallmanac ("You Are Here!"),
  per-lab month calendar, lab detail workspace.
- **Content** — document/SharePoint links per lab; changeable record owner.
- **Notifications** — configurable unauthenticated SMTP forwarder (on the admin
  console) + phase-triggered notification lists; email test.
- **Admin** — users/invites, database backups (daily + on-demand) & restore,
  self-hosted Swagger.
- **System Log** — every login/logout, password change, invite, backup/restore,
  notification-config edit, and lab/phase transition recorded with actor, target,
  and details; staff-only, filterable and paginated.
- **Production readiness** — Dockerized, non-root container, pinned dependencies,
  vendored assets (no CDN), edge/`ROOT_PATH` aware, deploy checklist above.
- **Testing & CI** — pytest suite (isolated per-test SQLite DB, `TestClient`)
  covering auth, forced password change, phase-gating/RBAC, Time Warp, backups,
  and notifications; `ruff` lint; GitHub Actions runs both on every push/PR to `main`.

**Not yet built**

- Lab edit / delete UI.
- Automated off-box backup copy (currently manual download or external mount).
- Offboarding tools: bulk-reassign a departing owner's labs; deactivate a user.
- Login rate-limiting / CSRF tokens (see production notes).
