"""Unit tests for app.backup: SQLite online-backup, retention, and restore
safety checks. These talk to real files on disk (via the `backup_env` fixture,
config.DB_PATH/BACKUP_DIR patched to a tmp_path), independent of the
in-memory `db_session` used for everything else.
"""
import os
import sqlite3
from datetime import datetime, timedelta

from app import backup


class _FakeClock:
    """A stand-in for `datetime` that advances by a fixed step on each `.now()`
    call, so backup filenames (second-resolution timestamps) never collide
    without needing a real `time.sleep()` in the tests."""

    def __init__(self, start: datetime, step: timedelta):
        self._current = start
        self._step = step

    def now(self):
        value = self._current
        self._current += self._step
        return value

    def fromtimestamp(self, ts):
        return datetime.fromtimestamp(ts)


def _use_fake_clock(monkeypatch, step=timedelta(seconds=2)):
    monkeypatch.setattr(backup, "datetime", _FakeClock(datetime(2026, 1, 1), step))


def test_make_backup_writes_a_named_copy(backup_env, monkeypatch):
    _use_fake_clock(monkeypatch)
    path = backup.make_backup()
    assert os.path.isfile(path)
    assert os.path.dirname(path) == backup_env["backup_dir"]
    name = os.path.basename(path)
    assert name.startswith("holo-") and name.endswith(".db")

    # The copy is a real, independent SQLite file with the same schema.
    con = sqlite3.connect(path)
    try:
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()
    assert {"users", "labs", "phases"} <= tables


def test_list_backups_sorted_newest_first(backup_env, monkeypatch):
    _use_fake_clock(monkeypatch)
    first = backup.make_backup()
    second = backup.make_backup()

    entries = backup.list_backups()
    names = [e["name"] for e in entries]
    assert names == sorted(names, reverse=True)
    assert os.path.basename(second) == names[0]
    assert os.path.basename(first) in names
    assert all("size_kb" in e and "when" in e for e in entries)


def test_prune_keeps_only_backup_keep_newest(backup_env, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "BACKUP_KEEP", 2)
    _use_fake_clock(monkeypatch)

    for _ in range(4):
        backup.make_backup()

    entries = backup.list_backups()
    assert len(entries) == 2


def test_safe_path_rejects_path_traversal_and_bad_names(backup_env, monkeypatch):
    _use_fake_clock(monkeypatch)
    backup.make_backup()
    real_name = backup.list_backups()[0]["name"]

    assert backup.safe_path(real_name) is not None
    assert backup.safe_path("../../etc/passwd") is None
    assert backup.safe_path("not-a-backup-name.db") is None
    assert backup.safe_path("holo-20200101-000000.db") is None  # doesn't exist


def test_is_valid_holo_db_accepts_real_backup(backup_env, monkeypatch):
    _use_fake_clock(monkeypatch)
    path = backup.make_backup()
    ok, why = backup.is_valid_holo_db(path)
    assert ok is True
    assert why == "ok"


def test_is_valid_holo_db_rejects_garbage_file(backup_env, tmp_path):
    bogus = tmp_path / "not-a-db.db"
    bogus.write_bytes(b"this is not a sqlite database")
    ok, why = backup.is_valid_holo_db(str(bogus))
    assert ok is False
    assert "not a valid SQLite file" in why


def test_is_valid_holo_db_rejects_wrong_schema(backup_env, tmp_path):
    other = tmp_path / "other.db"
    con = sqlite3.connect(str(other))
    try:
        con.execute("CREATE TABLE not_holo (id INTEGER PRIMARY KEY)")
        con.commit()
    finally:
        con.close()
    ok, why = backup.is_valid_holo_db(str(other))
    assert ok is False
    assert "missing tables" in why


def test_restore_from_overwrites_live_db(backup_env, monkeypatch):
    _use_fake_clock(monkeypatch)
    live_path = backup_env["db_path"]

    # Mutate the live DB, then take a backup of that state.
    con = sqlite3.connect(live_path)
    try:
        con.execute("INSERT INTO users (id, email) VALUES (1, 'before@test.local')")
        con.commit()
    finally:
        con.close()
    snapshot = backup.make_backup()

    # Mutate the live DB again (this is the state we'll discard).
    con = sqlite3.connect(live_path)
    try:
        con.execute("INSERT INTO users (id, email) VALUES (2, 'after@test.local')")
        con.commit()
    finally:
        con.close()

    backup.restore_from(snapshot)

    con = sqlite3.connect(live_path)
    try:
        emails = {r[0] for r in con.execute("SELECT email FROM users")}
    finally:
        con.close()
    assert emails == {"before@test.local"}
