"""Reader state and replies in BLUEDOC_HOME/state.db (SQLite), which serve.py owns.

docs     one row per doc file: its resolved path, its doc.id and a version that every changing write bumps
state    the page's bp:<doc.id>:<key> values, one row per key (the key without the 'bp:<doc.id>:' prefix)
replies  Send answers, Request changes and Approve plan, every one kept; delivered is NULL until `wait` returns it

A doc is found by its path; a path with no row takes over the row of the one other path with the same doc.id
whose file is gone (the doc moved). One connection behind a lock serves the threaded server; the file is mode 0600
and in WAL mode. Python 3.9+ standard library only.
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import threading
from pathlib import Path

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE docs (
  id      INTEGER PRIMARY KEY,
  path    TEXT NOT NULL UNIQUE,
  doc_id  TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE state (
  doc     INTEGER NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
  key     TEXT NOT NULL,
  value   TEXT NOT NULL,
  updated TEXT NOT NULL,
  PRIMARY KEY (doc, key)
) WITHOUT ROWID;
CREATE TABLE replies (
  id        INTEGER PRIMARY KEY,
  doc       INTEGER NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
  kind      TEXT NOT NULL CHECK (kind IN ('answers', 'changes', 'approval')),
  rev       TEXT NOT NULL,
  at        TEXT NOT NULL,
  doc_hash  TEXT,
  payload   TEXT NOT NULL,
  markdown  TEXT NOT NULL,
  delivered TEXT
);
CREATE INDEX replies_queue ON replies (doc, delivered, id);
"""
REPLY_KEYS = ("id", "doc", "kind", "rev", "at", "doc_hash", "payload", "markdown", "delivered")
REPLY_SELECT = ("SELECT r.id, d.path, r.kind, r.rev, r.at, r.doc_hash, r.payload, r.markdown, r.delivered "
                "FROM replies r JOIN docs d ON d.id = r.doc")


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


class StateDB:
    def __init__(self, path: Path, create: bool = True) -> None:
        """Open path; without it, create it (mode 0600, schema) when create is set, else raise FileNotFoundError.
        `created` tells whether this call made the file."""
        self.created = not path.exists()
        if self.created:
            if not create:
                raise FileNotFoundError(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False, timeout=10)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        if self.db.execute("PRAGMA user_version").fetchone()[0] == 0:
            self.db.executescript(f"BEGIN IMMEDIATE; {SCHEMA} PRAGMA user_version = {SCHEMA_VERSION}; COMMIT;")

    def close(self) -> None:
        with self.lock:
            self.db.close()

    def _write(self, fn):
        """fn(connection) in one IMMEDIATE transaction under the lock; its result."""
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                out = fn(self.db)
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            self.db.execute("COMMIT")
            return out

    def _read(self, sql: str, args=()) -> list[tuple]:
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    # ---------- docs ----------

    @staticmethod
    def _doc(c: sqlite3.Connection, path: str, doc_id: str | None, create: bool) -> int | None:
        """The docs row for path. A path with no row takes over the row of the one other path with this doc.id whose
        file is gone; otherwise a row is inserted when create is set."""
        row = c.execute("SELECT id, doc_id FROM docs WHERE path = ?", (path,)).fetchone()
        if row:
            if doc_id and row[1] != doc_id:
                c.execute("UPDATE docs SET doc_id = ? WHERE id = ?", (doc_id, row[0]))
            return row[0]
        if doc_id:
            gone = [r[0] for r in c.execute("SELECT id, path FROM docs WHERE doc_id = ? AND path != ?", (doc_id, path)).fetchall()
                    if not Path(r[1]).exists()]
            if len(gone) == 1:
                c.execute("UPDATE docs SET path = ? WHERE id = ?", (path, gone[0]))
                return gone[0]
        if not create:
            return None
        return c.execute("INSERT INTO docs (path, doc_id) VALUES (?, ?)", (path, doc_id or "")).lastrowid

    def _find(self, path: str, doc_id: str | None) -> int | None:
        """The docs row a read uses, or None (a takeover writes, so this runs as a transaction)."""
        return self._write(lambda c: self._doc(c, path, doc_id, create=False))

    # ---------- reader state ----------

    def state(self, path: str, doc_id: str | None) -> tuple[int, dict[str, str]]:
        """(version, {key: value}) for the doc; (0, {}) when it has no row."""
        doc = self._find(path, doc_id)
        if doc is None:
            return 0, {}
        with self.lock:
            version = self.db.execute("SELECT version FROM docs WHERE id = ?", (doc,)).fetchone()[0]
            return version, dict(self.db.execute("SELECT key, value FROM state WHERE doc = ? ORDER BY key", (doc,)).fetchall())

    def apply(self, path: str, doc_id: str | None, ops: list[tuple[str, str | None]], imported: bool) -> int:
        """Apply [(key, value, or None to delete)] in one transaction; the doc's version afterwards. An import only adds
        keys the doc lacks and skips deletes. The version goes up by one when at least one row changed."""
        def run(c: sqlite3.Connection) -> int:
            doc = self._doc(c, path, doc_id, create=True)
            stamp, changed = now(), 0
            for key, value in ops:
                if value is None:
                    if not imported:
                        changed += c.execute("DELETE FROM state WHERE doc = ? AND key = ?", (doc, key)).rowcount
                elif imported:
                    changed += c.execute("INSERT OR IGNORE INTO state (doc, key, value, updated) VALUES (?, ?, ?, ?)",
                                         (doc, key, value, stamp)).rowcount
                else:
                    changed += c.execute("INSERT INTO state (doc, key, value, updated) VALUES (?, ?, ?, ?) "
                                         "ON CONFLICT (doc, key) DO UPDATE SET value = excluded.value, updated = excluded.updated "
                                         "WHERE state.value != excluded.value", (doc, key, value, stamp)).rowcount
            if changed:
                c.execute("UPDATE docs SET version = version + 1 WHERE id = ?", (doc,))
            return c.execute("SELECT version FROM docs WHERE id = ?", (doc,)).fetchone()[0]
        return self._write(run)

    # ---------- replies ----------

    def add_reply(self, path: str, doc_id: str | None, kind: str, rev: str, payload: str, markdown: str,
                  doc_hash: str | None = None, at: str | None = None, delivered: str | None = None) -> int:
        """Store a reply; its id. It stays queued for `wait` (delivered NULL) unless delivered is given."""
        return self._write(lambda c: c.execute(
            "INSERT INTO replies (doc, kind, rev, at, doc_hash, payload, markdown, delivered) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (self._doc(c, path, doc_id, create=True), kind, rev, at or now(), doc_hash, payload, markdown, delivered)).lastrowid)

    def undelivered(self, path: str | None = None, kind: str = "any") -> list[dict]:
        """Queued replies, oldest first: one doc path's, or every doc's when path is None; kind 'any' takes all kinds."""
        sql, args = REPLY_SELECT + " WHERE r.delivered IS NULL", []
        if path is not None:
            sql, args = sql + " AND d.path = ?", [path]
        if kind != "any":
            sql, args = sql + " AND r.kind = ?", [*args, kind]
        return [dict(zip(REPLY_KEYS, r)) for r in self._read(sql + " ORDER BY r.id", args)]

    def mark_delivered(self, reply_id: int) -> None:
        self._write(lambda c: c.execute("UPDATE replies SET delivered = ? WHERE id = ? AND delivered IS NULL", (now(), reply_id)))

    def reply(self, reply_id: int) -> dict | None:
        rows = self._read(REPLY_SELECT + " WHERE r.id = ?", (reply_id,))
        return dict(zip(REPLY_KEYS, rows[0])) if rows else None

    def latest(self, path: str, doc_id: str | None) -> dict[str, dict]:
        """The doc's newest reply of each kind, by kind."""
        doc = self._find(path, doc_id)
        if doc is None:
            return {}
        rows = self._read(REPLY_SELECT + " WHERE r.id IN (SELECT MAX(id) FROM replies WHERE doc = ? GROUP BY kind)", (doc,))
        return {r[2]: dict(zip(REPLY_KEYS, r)) for r in rows}

    def approval(self, path: str, doc_id: str | None) -> dict | None:
        """The doc's newest approval, or None; the caller compares its doc_hash with the doc's own."""
        return self.latest(path, doc_id).get("approval")
