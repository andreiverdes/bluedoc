"""The home page's index in BLUEDOC_HOME/index-<SCHEMA_VERSION>.db (SQLite): a cache of every listed doc's summary,
validation and reader overlay, which serve.py's indexer fills and its routes read. Deleting it loses nothing; the
server builds it again.

docs    one row per listed doc: stage 1 (the summary, read from the doc's JSON), stage 2 (validation, from the
        worker), the reader overlay (state.db's fields for the doc) and the status computed from all three (status_of)
edits   each doc's history `built` times and its mtime, for Statistics' activity and the hero's edits this week
search  FTS5 (trigram) over title, path, subtitle, sections, meta and body; a plain table when FTS5 is missing
meta    gen (moves on every commit: the ETag's index part) and the indexer's counts

Writes go through one connection behind a lock (the indexer thread, and a request's overlay refresh); reads use a
small pool of their own connections, so they never queue behind a write (WAL). The file is mode 0600. A file that
fails to open is deleted with its -wal and -shm and made again; files of other schemas whose lock is free are
deleted once this one is complete (drop_other_schemas). Python 3.9+ standard library only.

Run as a script (`python3 indexdb.py worker`), it is the validation worker: niced, it reads one JSON request a line
on stdin, {"path": …}, and answers {"errors", "firstError", "card"} a line on stdout (validate_doc).
"""
from __future__ import annotations

import json
import os
import queue
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE docs (
  id         INTEGER PRIMARY KEY,
  path       TEXT NOT NULL UNIQUE,
  root       TEXT NOT NULL,
  rel        TEXT NOT NULL,
  dir        TEXT NOT NULL,
  file_key   TEXT,
  screens    TEXT NOT NULL DEFAULT '[]',
  code       TEXT NOT NULL,
  type TEXT, kind TEXT, org TEXT, rev TEXT, doc_id TEXT, doc_title TEXT,
  mtime REAL NOT NULL, approvable INTEGER, steps_open INTEGER,
  summary    TEXT NOT NULL,
  valid_key  TEXT, valid_code TEXT,
  errors     INTEGER,
  first_error TEXT, validated_at REAL,
  card2      TEXT,
  reader_ver TEXT,
  overlay    TEXT NOT NULL DEFAULT '{}',
  title TEXT, emoji TEXT, archived REAL, sent REAL,
  st TEXT,
  st_col TEXT, needs INTEGER, awaiting INTEGER, approved INTEGER, waiting INTEGER,
  dec_total INTEGER, dec_open INTEGER, steps INTEGER, steps_done INTEGER
);
CREATE INDEX docs_by_root ON docs (root, dir, mtime DESC);
CREATE INDEX docs_by_mtime ON docs (mtime DESC);
CREATE TABLE edits (
  doc INTEGER NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
  at  INTEGER NOT NULL
);
CREATE INDEX edits_by_doc ON edits (doc);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""
FTS = "CREATE VIRTUAL TABLE search USING fts5 (title, path, subtitle, sections, meta, body, tokenize = 'trigram')"
NO_FTS = "CREATE TABLE search (rowid INTEGER PRIMARY KEY, title, path, subtitle, sections, meta, body)"
SEARCH_COLS = ("title", "path", "subtitle", "sections", "meta", "body")
WEIGHTS = (10, 6, 4, 3, 2, 1)   # home.html's match(): title, path, subtitle, sections, kind/org/type, body
TYPE_ONE = {"docs": "Docs", "review": "Review", "plan": "Plan", "design": "Design", "presentation": "Presentation",
            "website": "Website", "storelisting": "Store listing", "other": "Other"}
STATUSES = ("needs", "awaiting", "waiting", "approved", "errors", "archived")
GROUPS = ("today", "week", "month", "older")
DAY = 86400
MAX_LIMIT = 200
READERS = 4   # pooled read connections
# the row as a page draws it: summary fields the routes leave out of every answer (status_of reads them)
HIDDEN_FIELDS = ("items", "state", "built")


def plain(s) -> str:
    """home.html's plain(): markdown's ` and * dropped, [text](url) as text."""
    import re   # noqa: PLC0415
    s = re.sub(r"[`*]", "", str(s or ""))
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)


# ---------- status: home.html's progress() and statusOf(), the one implementation ----------

def progress(items: list, state: dict) -> dict:
    """Decisions and steps of the doc's checklists with the reader's ticks and picks (state: <checklist>:<item> ->
    value): {dec, decided, steps, done, open}, open = [{text, dec, n}] what is left, decisions first."""
    dec = decided = steps = done = 0
    opened: list[dict] = []
    for row in items or []:
        cl, iid, is_dec, author, choice_ids, text = (list(row) + [None] * 6)[:6]
        s = state.get(f"{cl}:{iid}") if state else None
        s = s if isinstance(s, str) else None
        if is_dec:
            dec += 1
            pick = author or ""
            if s is not None and s.startswith("="):
                bar = s.find("|")
                c, tail = (s[1:bar], s[bar + 1:]) if bar >= 0 else (s[1:-1], s)
                if tail == author and (not c or all(x in (choice_ids or []) for x in c.split(","))):
                    pick = c
            if pick:
                decided += 1
            else:
                opened.append({"text": text or iid, "dec": True, "n": len(choice_ids or [])})
        else:
            steps += 1
            on = author == "1"
            if s is not None and not s.startswith("=") and (s[1:2] == author if len(s) == 2 else not (s == "0" and author == "1")):
                on = s[:1] == "1"
            if on:
                done += 1
            else:
                opened.append({"text": text or iid, "dec": False})
    opened.sort(key=lambda x: not x["dec"])
    return {"dec": dec, "decided": decided, "steps": steps, "done": done, "open": opened}


def status_of(summary: dict, errors, overlay: dict) -> dict:
    """The doc's status from its summary, its validation (errors: None until validated, which counts as building) and
    the reader overlay, as home.html's statusOf had it: {col, needs, awaiting, approved, waiting, errors, archived,
    allDone, changesSent, staleRev, sent, dec, decided, steps, done, total, did, open}."""
    approvable, bad = bool(summary.get("approvable")), bool(errors and errors > 0)
    ap = overlay.get("approval") if approvable and not bad else None
    rev = str(summary.get("rev") or "")
    approved = bool(ap) and (ap.get("carried") is True or str(ap.get("rev") or "") == rev)
    stale = str(ap.get("rev") or "") if ap and not approved else None
    answers, changes = overlay.get("answers"), overlay.get("changes")
    sent = max(answers["at"] if answers else 0, changes["at"] if changes else 0)
    waiting = not approved and sent > (summary.get("mtime") or 0)
    p = progress(summary.get("items") or [], overlay.get("state") or {})
    if approved:   # approving settles every open pick: the agent uses its recommendation
        p = {**p, "decided": p["dec"], "open": [x for x in p["open"] if not x["dec"]]}
    awaiting = approvable and not bad and not waiting and not approved
    needs = not bad and not waiting and (awaiting or p["dec"] > p["decided"])
    total, did = p["dec"] + p["steps"], p["decided"] + p["done"]
    col = ("errors" if bad else "done" if approved else "waiting" if waiting else "needs" if needs
           else "progress" if 0 < did < total else "done")
    archived = overlay.get("archived") is not None
    all_done = (approved and not archived and bool(rev) and overlay.get("archiveLater") != rev
                and not (summary.get("stepsOpen") or 0) > 0 and p["steps"] == p["done"])
    return {"col": col, "needs": needs, "awaiting": awaiting, "approved": approved, "waiting": waiting, "errors": bad,
            "archived": archived, "allDone": all_done,
            "changesSent": bool(waiting and changes and (not answers or changes["at"] >= answers["at"])),
            "staleRev": stale, "sent": sent, **p, "total": total, "did": did}


# ---------- the database ----------

class Query:
    """What a page asks for. roots: [{slug, path, name, temp, shown}] every registered folder (shown: on the home
    page by default); p, d, t, s, hidden, q: the home's URL filters; tz: the browser's getTimezoneOffset() minutes."""

    def __init__(self, roots: list[dict], p: str = "", d: str = "", t: str = "", s: str = "", hidden: bool = False,
                 q: str = "", sort: str = "new", tz: int = 0, now: float | None = None) -> None:
        self.roots, self.p, self.d, self.t, self.s, self.hidden = roots, p, d, t, s, hidden
        self.terms = [x for x in q.lower().split() if x]
        self.sort, self.tz = sort, tz
        self.now = time.time() if now is None else now
        self.by_path = {r["path"]: r for r in roots}
        self.by_slug = {r["slug"]: r for r in roots}

    def today(self) -> float:
        """The epoch second of today's local midnight in the browser's zone."""
        off = -self.tz * 60
        return (int(self.now + off) // DAY) * DAY - off

    def pool(self) -> list[str]:
        """The folders a view starts from: hidden ones (hidden), the picked one, else the shown ones."""
        if self.hidden:
            return [r["path"] for r in self.roots if not r["shown"]]
        if self.p:
            r = self.by_slug.get(self.p)
            return [r["path"]] if r else []
        return [r["path"] for r in self.roots if r["shown"]]

    def scope(self) -> tuple[str, list]:
        roots = self.pool()
        sql, args = f"root IN ({','.join('?' * len(roots))})" if roots else "0", list(roots)
        if self.p and self.d and not self.hidden:
            sql, args = sql + " AND (dir = ? OR substr(dir, 1, ?) = ?)", args + [self.d, len(self.d) + 1, self.d + "/"]
        return sql, args


def _status_sql(s: str) -> str:
    return "errors > 0" if s == "errors" else f"{s} = 1"


class IndexDB:
    def __init__(self, home: Path) -> None:
        self.home = Path(home)
        self.path = self.home / f"index-{SCHEMA_VERSION}.db"
        self.wlock = threading.Lock()
        self.readers: queue.LifoQueue = queue.LifoQueue()
        self.fts = True
        self.home.mkdir(parents=True, exist_ok=True)
        try:
            self._open()
        except sqlite3.DatabaseError:
            self.w.close() if getattr(self, "w", None) else None
            self.remove_files()
            self._open()

    # ---------- open, rebuild ----------

    def remove_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(str(self.path) + suffix)
            except OSError:
                pass

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.path), isolation_level=None, check_same_thread=False, timeout=5)
        c.execute("PRAGMA busy_timeout = 5000")
        c.execute("PRAGMA foreign_keys = ON")
        return c

    def _open(self) -> None:
        if not self.path.exists():
            os.close(os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600))
        self.w = self._connect()
        self.w.execute("PRAGMA journal_mode = WAL")
        self.w.execute("PRAGMA synchronous = NORMAL")
        if self.w.execute("PRAGMA user_version").fetchone()[0] == 0:
            try:
                self.w.execute("CREATE VIRTUAL TABLE temp.fts_probe USING fts5 (x, tokenize = 'trigram')")
                self.w.execute("DROP TABLE temp.fts_probe")
                search = FTS
            except sqlite3.OperationalError:   # no FTS5 or no trigram tokenizer: search scans with instr()
                search = NO_FTS
            try:   # executescript commits first: the whole schema in its own transaction
                self.w.executescript(f"BEGIN IMMEDIATE; {SCHEMA} {search}; INSERT INTO meta VALUES ('gen', '0'); "
                                     f"PRAGMA user_version = {SCHEMA_VERSION}; COMMIT;")
            except sqlite3.OperationalError:
                if self.w.in_transaction:
                    self.w.execute("ROLLBACK")
                if self.w.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:   # not another server's make
                    raise
        sql = self.w.execute("SELECT sql FROM sqlite_master WHERE name = 'search'").fetchone()
        if not sql:
            raise sqlite3.DatabaseError("no search table")
        self.fts = "fts5" in sql[0].lower()
        self.w.execute("SELECT count(*) FROM docs").fetchone()   # a damaged file fails here, not on the first request

    def drop_other_schemas(self, lock_free) -> None:
        """Delete index files of other schemas whose lock lock_free(path) says no server holds."""
        for f in self.home.glob("index-*.db"):
            if f != self.path and lock_free(Path(str(f) + ".lock")):
                for suffix in ("", "-wal", "-shm", ".lock"):
                    try:
                        os.unlink(str(f) + suffix)
                    except OSError:
                        pass

    def close(self) -> None:
        with self.wlock:
            self.w.close()
        while not self.readers.empty():
            self.readers.get_nowait().close()

    @contextmanager
    def reader(self):
        try:
            c = self.readers.get_nowait()
        except queue.Empty:
            c = self._connect()
            c.execute("PRAGMA query_only = ON")
        try:
            yield c
        finally:
            if c.in_transaction:
                c.execute("ROLLBACK")
            if self.readers.qsize() < READERS:
                self.readers.put(c)
            else:
                c.close()

    def _write(self, fn):
        """fn(connection) in one IMMEDIATE transaction that moves gen; its result."""
        with self.wlock:
            self.w.execute("BEGIN IMMEDIATE")
            try:
                out = fn(self.w)
                self.w.execute("UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'gen'")
            except BaseException:
                self.w.execute("ROLLBACK")
                raise
            self.w.execute("COMMIT")
            return out

    # ---------- writes ----------

    @staticmethod
    def _status_cols(summary: dict, errors, overlay: dict) -> tuple:
        st = status_of(summary, errors, overlay)
        return (json.dumps(st, ensure_ascii=False), st["col"], int(st["needs"]), int(st["awaiting"]), int(st["approved"]),
                int(st["waiting"]), st["dec"], st["dec"] - st["decided"], st["steps"], st["done"])

    def put_summary(self, rows: list[dict], code: str) -> list[str]:
        """Stage 1 for each row: {path, root, rel, dir, file_key (None: read again next sweep), screens, summary,
        search: {title, path, subtitle, sections, meta, body}, edits: [epoch seconds], overlay, reader_ver}, in one
        transaction. A row whose file_key changed loses its validation (errors NULL) unless stage 1 already knows it
        doesn't build (summary errors). An overlay older than the row's (a save landed while stage 1 read the doc:
        newer_ver) keeps the row's; the paths where that happened, which the caller refreshes."""
        kept: list[str] = []

        def run(c: sqlite3.Connection) -> None:
            for r in rows:
                s, ov, ver = r["summary"], r["overlay"], r.get("reader_ver")
                old = c.execute("SELECT id, file_key, valid_key, errors, first_error, reader_ver, overlay FROM docs WHERE path = ?",
                                (r["path"],)).fetchone()
                if old and newer_ver(old[5], ver):
                    ov, ver = json.loads(old[6]), old[5]
                    kept.append(r["path"])
                if s.get("errors"):
                    errors, first = s["errors"], s.get("firstError") or ""
                elif old and old[1] is not None and old[1] == r["file_key"] and old[2] == r["file_key"]:
                    errors, first = old[3], old[4]
                else:
                    errors, first = None, None
                stored = {k: v for k, v in s.items() if k not in ("errors", "firstError")}
                vals = (r["root"], r["rel"], r["dir"], r["file_key"], json.dumps(r.get("screens") or []), code,
                        s.get("type"), s.get("kind"), s.get("org"), s.get("rev"), s.get("id"), s.get("docTitle"),
                        s.get("mtime") or 0, int(bool(s.get("approvable"))), s.get("stepsOpen") or 0,
                        json.dumps(stored, ensure_ascii=False), errors, first, ver,
                        json.dumps(ov, ensure_ascii=False), ov.get("title"), ov.get("emoji"), ov.get("archived"),
                        _sent(ov), *self._status_cols(s, errors, ov))
                cols = ("root, rel, dir, file_key, screens, code, type, kind, org, rev, doc_id, doc_title, mtime, approvable, "
                        "steps_open, summary, errors, first_error, reader_ver, overlay, title, emoji, archived, "
                        "sent, st, st_col, needs, awaiting, approved, waiting, dec_total, dec_open, steps, steps_done")
                if old:
                    doc = old[0]
                    keep_valid = old[1] is not None and old[1] == r["file_key"]
                    c.execute(f"UPDATE docs SET {', '.join(x.strip() + ' = ?' for x in cols.split(','))}"
                              + ("" if keep_valid else ", valid_key = NULL, valid_code = NULL, card2 = NULL") + " WHERE id = ?",
                              (*vals, doc))
                    c.execute("DELETE FROM search WHERE rowid = ?", (doc,))
                    c.execute("DELETE FROM edits WHERE doc = ?", (doc,))
                else:
                    doc = c.execute(f"INSERT INTO docs (path, {cols}) VALUES (?, {', '.join('?' * len(vals))})",
                                    (r["path"], *vals)).lastrowid
                sr = r["search"]
                c.execute("INSERT INTO search (rowid, title, path, subtitle, sections, meta, body) VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (doc, *(sr.get(k, "") for k in SEARCH_COLS)))
                c.executemany("INSERT INTO edits (doc, at) VALUES (?, ?)", [(doc, int(t)) for t in set(map(int, r.get("edits") or []))])
        self._write(run)
        return kept

    def put_validation(self, path: str, file_key: str, code: str, errors: int, first_error: str, card2: dict | None) -> bool:
        """Stage 2's result for the doc as it was at file_key: written only while the row still has that key
        (compare-and-set); False when the doc changed since, so it is validated again."""
        def run(c: sqlite3.Connection) -> bool:
            row = c.execute("SELECT summary, overlay FROM docs WHERE path = ? AND file_key = ?", (path, file_key)).fetchone()
            if not row:
                return False
            s, ov = json.loads(row[0]), json.loads(row[1])
            c.execute("UPDATE docs SET errors = ?, first_error = ?, valid_key = ?, valid_code = ?, validated_at = ?, card2 = ?, "
                      "st = ?, st_col = ?, needs = ?, awaiting = ?, approved = ?, waiting = ?, dec_total = ?, dec_open = ?, "
                      "steps = ?, steps_done = ? WHERE path = ?",
                      (errors, first_error, file_key, code, time.time(), json.dumps(card2) if card2 else None,
                       *self._status_cols(s, errors, ov), path))
            return True
        return self._write(run)

    def put_overlay(self, path: str, overlay: dict, reader_ver: str | None) -> bool:
        """The reader overlay of a row and the status it makes; False when the doc has no row yet, or the row already
        has a newer one (another save's, read later than this one)."""
        def run(c: sqlite3.Connection) -> bool:
            row = c.execute("SELECT id, summary, errors, reader_ver FROM docs WHERE path = ?", (path,)).fetchone()
            if not row or newer_ver(row[3], reader_ver):
                return False
            s = json.loads(row[1])
            c.execute("UPDATE docs SET overlay = ?, reader_ver = ?, title = ?, emoji = ?, archived = ?, sent = ?, st = ?, st_col = ?, "
                      "needs = ?, awaiting = ?, approved = ?, waiting = ?, dec_total = ?, dec_open = ?, steps = ?, steps_done = ? "
                      "WHERE id = ?", (json.dumps(overlay, ensure_ascii=False), reader_ver, overlay.get("title"), overlay.get("emoji"),
                                       overlay.get("archived"), _sent(overlay), *self._status_cols(s, row[2], overlay), row[0]))
            c.execute("UPDATE search SET title = ? WHERE rowid = ?", (plain(overlay.get("title") or s.get("docTitle") or ""), row[0]))
            return True
        return self._write(run)

    def drop(self, paths) -> int:
        paths = list(paths)

        def run(c: sqlite3.Connection) -> int:
            n = 0
            for p in paths:
                row = c.execute("SELECT id FROM docs WHERE path = ?", (p,)).fetchone()
                if row:
                    c.execute("DELETE FROM search WHERE rowid = ?", row)
                    n += c.execute("DELETE FROM docs WHERE id = ?", row).rowcount
            return n
        return self._write(run) if paths else 0

    def set_meta(self, **kw) -> None:
        self._write(lambda c: c.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", [(k, json.dumps(v)) for k, v in kw.items()]))

    # ---------- reads for the indexer ----------

    def keys(self) -> dict[str, tuple]:
        """{path: (file_key, screens, code, valid_key, valid_code, mtime, reader_ver, errors, root)} of every row."""
        with self.reader() as c:
            return {r[0]: r[1:] for r in c.execute(
                "SELECT path, file_key, screens, code, valid_key, valid_code, mtime, reader_ver, errors, root FROM docs")}

    def row(self, path: str) -> dict | None:
        """A row's summary (with mtime) and its overlay, or None."""
        with self.reader() as c:
            r = c.execute("SELECT summary, overlay, errors FROM docs WHERE path = ?", (path,)).fetchone()
        return None if not r else {"summary": json.loads(r[0]), "overlay": json.loads(r[1]), "errors": r[2]}

    def generation(self) -> str:
        with self.reader() as c:
            r = c.execute("SELECT value FROM meta WHERE key = 'gen'").fetchone()
        return r[0] if r else "0"

    def meta(self, key: str):
        with self.reader() as c:
            r = c.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return json.loads(r[0]) if r else None

    def counts(self, code: str, paths: set[str] | None = None) -> dict:
        """{rows, summarized, validated}: rows of the listed paths (every row without paths), those stage 1 wrote with
        this code, those validated for their file key with this code."""
        with self.reader() as c:
            rows = c.execute("SELECT path, code, file_key, valid_key, valid_code, errors FROM docs").fetchall()
        rows = [r for r in rows if paths is None or r[0] in paths]
        return {"rows": len(rows), "summarized": sum(r[1] == code for r in rows),
                "validated": sum(r[2] is not None and r[3] == r[2] and r[4] == code and r[5] is not None for r in rows)}

    # ---------- reads for the routes ----------

    def _search_ids(self, c: sqlite3.Connection, q: Query, where: str, args: list) -> dict[int, tuple[int, str]] | None:
        """{doc id: (score, snip)} of the docs in where that match every term (home.html's match(): substrings, title
        10, path 6 (the project's name and the doc's path), subtitle 4, sections 3, kind/org/type 2, body 1), or None
        without terms."""
        if not q.terms:
            return None
        sql, sargs = where, list(args)
        names = {r["path"]: r.get("label") or r["name"] for r in q.roots}
        for t in q.terms:
            hit_roots = [p for p, n in names.items() if t in str(n).lower()]
            if self.fts and len(t) >= 3:
                part, pargs = "id IN (SELECT rowid FROM search WHERE search MATCH ?)", ['"' + t.replace('"', '""') + '"']
            else:
                part, pargs = ("id IN (SELECT rowid FROM search WHERE instr(lower(title || char(1) || path || char(1) || subtitle "
                               "|| char(1) || sections || char(1) || meta || char(1) || body), ?))"), [t]
            if hit_roots:
                part = f"({part} OR root IN ({','.join('?' * len(hit_roots))}))"
                pargs += hit_roots
            sql, sargs = f"{sql} AND {part}", sargs + pargs
        rows = c.execute("SELECT d.id, d.root, s.title, s.path, s.subtitle, s.sections, s.meta, s.body FROM docs d "
                         f"JOIN search s ON s.rowid = d.id WHERE {sql}", sargs).fetchall()
        out = {}
        for did, root, title, path, sub, secs, meta, body in rows:
            fields = (title, f"{names.get(root, '')}/{path}", sub, secs, meta, body)
            low = [str(f or "").lower() for f in fields]
            score = 0
            for t in q.terms:
                hit = sum(w for f, w in zip(low, WEIGHTS) if f and t in f)
                if not hit:
                    break
                score += hit
            else:
                out[did] = (score, snip(body or "", title or "", q.terms))
        return out

    def page(self, q: Query, view: str = "rows", offset: int = 0, limit: int = 25, doc: tuple[str, str] | None = None) -> dict:
        """One slice of the view with what the page counts: {docs, total, next, groups, facets, roots, hero}.
        doc: (root path, rel) of a doc the first slice must reach."""
        limit = max(1, min(MAX_LIMIT, limit))
        offset = max(0, offset)
        scope, sargs = q.scope()
        show_arch = q.s == "archived"
        arch = "archived IS NOT NULL" if show_arch else "archived IS NULL"
        with self.reader() as c:
            c.execute("BEGIN")   # one snapshot for the slice and its counts
            types = dict(c.execute(f"SELECT type, COUNT(*) FROM docs WHERE {scope} AND {arch} GROUP BY type", sargs).fetchall())
            typed, targs = (f"{scope} AND type = ?", sargs + [q.t]) if q.t else (scope, sargs)
            st_counts = c.execute(
                "SELECT " + ", ".join(f"SUM(archived IS NULL AND {_status_sql(s)})" for s in STATUSES[:-1])
                + f", SUM(archived IS NOT NULL) FROM docs WHERE {typed}", targs).fetchone()
            statuses = {s: n or 0 for s, n in zip(STATUSES, st_counts) if n}
            if q.s and q.s != "archived" and q.s in STATUSES:
                filt, fargs = f"{typed} AND archived IS NULL AND {_status_sql(q.s)}", targs
            elif show_arch:
                filt, fargs = f"{typed} AND archived IS NOT NULL", targs
            else:
                filt, fargs = f"{typed} AND archived IS NULL", targs
            found = self._search_ids(c, q, filt, fargs)
            order = "mtime ASC, id" if q.sort == "old" and found is None else "mtime DESC, id"
            ordered = [r for r in c.execute(f"SELECT id, mtime, root, rel FROM docs WHERE {filt} ORDER BY {order}", fargs)]
            if found is not None:
                ordered = sorted((r for r in ordered if r[0] in found), key=lambda r: -found[r[0]][0])   # stable: newest first among equals
            total = len(ordered)
            t0 = q.today()
            groups = {g: 0 for g in GROUPS}
            for r in ordered:
                groups[group_of(r[1], t0)] += 1
            if doc and offset == 0:
                at = next((i for i, r in enumerate(ordered) if (r[2], r[3]) == doc), None)
                if at is not None and at >= limit:
                    limit = at + 1
            ids = [r[0] for r in ordered[offset:offset + limit]]
            rows = self._rows(c, ids, view, q, found)
            archived_n = 0
            if not show_arch:
                af, aargs = f"{typed} AND archived IS NOT NULL" + (f" AND {_status_sql(q.s)}" if q.s in STATUSES[:-1] else ""), targs
                archived_n = (len(self._search_ids(c, q, af, aargs)) if q.terms
                              else c.execute(f"SELECT COUNT(*) FROM docs WHERE {af}", aargs).fetchone()[0])
            dirs = []
            if q.p and q.p in q.by_slug:
                dirs = [{"dir": d, "n": n} for d, n in c.execute(
                    "SELECT dir, COUNT(*) FROM docs WHERE root = ? AND archived IS NULL AND dir != '' GROUP BY dir ORDER BY dir",
                    (q.by_slug[q.p]["path"],))]
            roots = self._roots(c, q)
            hero = self._hero(c, q, scope, sargs, t0)
        end = offset + len(ids)
        return {"docs": rows, "total": total, "next": end if end < total else None, "groups": groups,
                "facets": {"types": types, "statuses": statuses, "dirs": dirs, "archived": archived_n},
                "roots": roots, "hero": hero}

    def _rows(self, c: sqlite3.Connection, ids: list[int], view: str, q: Query, found) -> list[dict]:
        if not ids:
            return []
        got = {r[0]: r for r in c.execute(
            "SELECT id, root, rel, dir, summary, overlay, errors, first_error, st, card2 FROM docs WHERE id IN "
            f"({','.join('?' * len(ids))})", ids)}
        out = []
        for i in ids:
            _, root, rel, dr, summary, overlay, errors, first, st, card2 = got[i]
            r = q.by_path.get(root) or {"slug": "", "name": ""}
            url = f"/{_quote(r['slug'])}/{_quote(rel)}"
            s, ov, st = json.loads(summary), json.loads(overlay), json.loads(st)
            if view == "menu":
                out.append({"url": url, "root": r["slug"], "path": rel, "title": ov.get("title") or s.get("docTitle"),
                            "docTitle": s.get("docTitle"), "emoji": ov.get("emoji") or s.get("emoji"), "type": s.get("type"),
                            "mtime": s.get("mtime"), "archived": ov.get("archived"), "st": st,
                            **({"planSteps": [s.get("stepsTotal", 0) - (s.get("stepsOpen") or 0), s.get("stepsTotal", 0)]}
                               if s.get("type") == "plan" else {})})
                continue
            d = {k: v for k, v in s.items() if k not in HIDDEN_FIELDS and k != "card"}
            for k in ("answers", "changes", "approval", "archived", "unarchivedBy", "archiveLater"):
                if ov.get(k) is not None:
                    d[k] = ov[k]
            d.setdefault("archived", None)
            d.update({"url": url, "root": r["slug"], "path": rel, "dir": dr, "title": ov.get("title") or s.get("docTitle"),
                      "emoji": ov.get("emoji") or s.get("emoji"), "errors": errors, "firstError": first or "", "st": st})
            if view in ("cards", "rows"):   # an open row draws the card's hero too
                card = dict(s.get("card") or {})
                if card2:
                    card.update(json.loads(card2))
                d["card"] = card
            if found is not None:
                d["snip"] = found[i][1]
            out.append(d)
        return out

    def _roots(self, c: sqlite3.Connection, q: Query) -> list[dict]:
        got = {r[0]: r[1:] for r in c.execute(
            "SELECT root, SUM(archived IS NULL), MAX(mtime) FROM docs GROUP BY root")}
        return [{"slug": r["slug"], "name": r["name"], "path": r["path"], "temp": r["temp"],
                 "count": (got.get(r["path"]) or (0, 0))[0] or 0, "last": (got.get(r["path"]) or (0, 0))[1] or 0}
                for r in q.roots]

    def _edit_days(self, c: sqlite3.Connection, where: str, args: list, start: float, tz: int) -> list[tuple]:
        """[(day index from start, doc count)] of the docs in where edited (built or saved) since start."""
        off = -tz * 60
        return c.execute(
            f"SELECT CAST((e.at + ? - ?) / {DAY} AS INTEGER) AS day, COUNT(DISTINCT e.doc) FROM edits e JOIN docs ON docs.id = e.doc "
            f"WHERE {where} AND e.at >= ? GROUP BY day", [off, start + off, *args, start]).fetchall()

    def _hero(self, c: sqlite3.Connection, q: Query, scope: str, sargs: list, t0: float) -> dict:
        live = f"{scope} AND archived IS NULL"
        n, newest, dec_open, waiting = c.execute(
            f"SELECT COUNT(*), MAX(mtime), SUM(dec_open), SUM(waiting) FROM docs WHERE {live}", sargs).fetchone()
        week = self._edit_days(c, live, sargs, t0 - 6 * DAY, q.tz)
        return {"docs": n, "projects": len(q.pool()), "newest": newest or 0, "editsWeek": sum(x[1] for x in week),
                "decisionsOpen": dec_open or 0, "waiting": waiting or 0}

    def stats(self, q: Query, days: int) -> dict:
        """Statistics' widgets over the non-archived docs of the shown folders (or q.p's): activity over max(days, 14)
        days, oldest first; edits by project in the range (top 8); docs by type and review findings; decisions with
        the three docs with most to decide; waiting on the agent (the newest 4); the 6 oldest docs with open picks."""
        roots = q.pool()
        live, args = (f"root IN ({','.join('?' * len(roots))}) AND archived IS NULL" if roots else "0"), list(roots)
        t0, span = q.today(), max(days, 14)
        start = t0 - (span - 1) * DAY
        with self.reader() as c:
            c.execute("BEGIN")
            counts = [0] * span
            for day, n in self._edit_days(c, live, args, start, q.tz):
                if 0 <= day < span:
                    counts[day] = n
            range_start = t0 - (days - 1) * DAY
            by_root: dict[str, int] = {}
            off = -q.tz * 60
            for root, n in c.execute(
                    f"SELECT root, COUNT(*) FROM (SELECT DISTINCT docs.root AS root, e.doc, CAST((e.at + ?) / {DAY} AS INTEGER) "
                    f"FROM edits e JOIN docs ON docs.id = e.doc WHERE {live} AND e.at >= ?) GROUP BY root", [off, *args, range_start]):
                by_root[root] = n
            names = {r["path"]: r["slug"] for r in q.roots}
            by_project = sorted(({"slug": names.get(k, ""), "n": n} for k, n in by_root.items() if n), key=lambda x: -x["n"])[:8]
            n, dec, dec_open, steps, done, waiting = c.execute(
                f"SELECT COUNT(*), SUM(dec_total), SUM(dec_open), SUM(steps), SUM(steps_done), SUM(waiting) FROM docs WHERE {live}",
                args).fetchone()
            types = dict(c.execute(f"SELECT type, COUNT(*) FROM docs WHERE {live} GROUP BY type", args).fetchall())
            findings = {k: 0 for k in ("blocker", "major", "minor", "nit")}
            for (card,) in c.execute(f"SELECT json_extract(summary, '$.card.findings') FROM docs WHERE {live} AND type = 'review'", args):
                for k, v in (json.loads(card) if card else {}).items():
                    if k in findings:
                        findings[k] += int(v or 0)
            cols = "root, rel, dir, summary, overlay, st"

            def brief(r, q=q) -> dict:
                root, rel, dr, s, ov, st = r
                s, ov, st = json.loads(s), json.loads(ov), json.loads(st)
                rr = q.by_path.get(root) or {"slug": "", "name": ""}
                return {"url": f"/{_quote(rr['slug'])}/{_quote(rel)}", "title": ov.get("title") or s.get("docTitle"),
                        "docTitle": s.get("docTitle"), "emoji": ov.get("emoji") or s.get("emoji"),
                        "root": rr.get("label") or rr["name"], "slug": rr["slug"],
                        "dir": dr, "mtime": s.get("mtime"), "st": st}
            top = [brief(r) for r in c.execute(f"SELECT {cols} FROM docs WHERE {live} AND needs = 1 "
                                               "ORDER BY dec_open DESC, mtime DESC LIMIT 3", args)]
            wait = [brief(r) for r in c.execute(f"SELECT {cols} FROM docs WHERE {live} AND waiting = 1 ORDER BY sent DESC LIMIT 4", args)]
            oldest = [brief(r) for r in c.execute(f"SELECT {cols} FROM docs WHERE {live} AND needs = 1 AND dec_open > 0 "
                                                  "ORDER BY mtime LIMIT 6", args)]
        return {"docs": n, "projects": len(roots), "days": days,
                "activity": {"counts": counts, "start": start},
                "byProject": by_project, "types": types, "findings": findings,
                "decisions": {"dec": dec or 0, "decided": (dec or 0) - (dec_open or 0), "steps": steps or 0, "done": done or 0,
                              "open": [{**x, "n": x["st"]["dec"] - x["st"]["decided"], "awaiting": x["st"]["awaiting"]} for x in top]},
                "waiting": {"n": waiting or 0, "docs": [{**x, "sent": x["st"]["sent"], "changesSent": x["st"]["changesSent"]} for x in wait]},
                "oldest": oldest}


def newer_ver(a: str | None, b: str | None) -> bool:
    """Whether reader version a ('<state.db docs.version>:<newest reply id>') is newer than b: one number higher,
    neither lower. None or a malformed one is the oldest."""
    def parse(v):
        try:
            x, y = str(v).split(":")
            return int(x), int(y)
        except ValueError:
            return -1, -1
    (a1, a2), (b1, b2) = parse(a), parse(b)
    return a1 >= b1 and a2 >= b2 and (a1, a2) != (b1, b2)


def _sent(ov: dict) -> float:
    return max((ov.get("answers") or {}).get("at") or 0, (ov.get("changes") or {}).get("at") or 0)


def _quote(s: str) -> str:
    from urllib.parse import quote   # noqa: PLC0415
    return quote(s)


def group_of(t: float, t0: float) -> str:
    """home.html's date groups: today, this week (the 6 days before), this month (the 23 before), older."""
    return "today" if t >= t0 else "week" if t >= t0 - 6 * DAY else "month" if t >= t0 - 29 * DAY else "older"


def snip(body: str, title: str, terms: list[str]) -> str:
    """Body text around the first term the title doesn't show (home.html's match())."""
    low = body.lower()
    t = next((x for x in terms if x not in title.lower()), terms[0])
    i = low.find(t)
    if i < 0:
        return ""
    a = max(0, body.rfind(" ", 0, max(0, i - 36)) + 1)
    b = min(len(body), i + len(t) + 160)
    return ("…" if a > 0 else "") + body[a:b] + ("…" if b < len(body) else "")


# ---------- the validation worker ----------

def validate_doc(path: str) -> dict:
    """Stage 2 for one doc: build.validate's blocking problems, and the card numbers stage 1 leaves out: a review's
    add and del over its diff refs (the diff cache and local git, never gh; the cache is not written) and a store
    listing's check levels and store-rule errors (listing.store_checks)."""
    import build   # noqa: PLC0415
    p = Path(path)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        rep = build.validate(doc, p, write_cache=False)
    except (OSError, ValueError, TypeError, AttributeError) as e:
        return {"errors": 1, "firstError": f"cannot read: {e}", "card": None}
    card = None
    try:
        dtype = build.doc_type(doc.get("meta") or {})
        if dtype == "review":
            import diffref   # noqa: PLC0415
            if any(diffref.is_ref(b) for b in build.all_blocks(doc) if b.get("type") == "diff"):
                expanded, _ = diffref.expanded_copy(doc, p, allow_remote=False, write_cache=False)
                card = diff_counts([b for b in build.all_blocks(expanded) if b.get("type") == "diff"])
        elif dtype == "storelisting":
            import listing   # noqa: PLC0415
            lb = listing.listing_of(doc)
            if lb:
                rules = listing.load_rules()
                loc = lb.get("defaultLocale") or next(iter(lb.get("locales") or []), None)
                known = {x["id"] for x in rules["platforms"]}
                found = listing.store_checks(doc, p, rules)

                def level(pl: str, section: str) -> str:
                    ls = {f["level"] for f in found if f["section"] == section and (not f["platforms"] or pl in f["platforms"])}
                    return "err" if "err" in ls else "warn" if ls else "ok"
                levels = {}
                for pl in [x for x in lb.get("platforms") or [] if x in known]:
                    shots = [level(pl, s["row"]) for s in listing.sections(lb, listing.shots_of(doc), rules, pl, loc)]
                    levels[pl] = {"text": level(pl, "text"), "shared": level(pl, "shared"),
                                  "shots": "err" if "err" in shots else "warn" if "warn" in shots else "ok"}
                card = {"levels": levels, "storeErrors": sum(f["level"] == "err" for f in found)}
    except Exception:   # noqa: BLE001 (the card's extras are optional; the validation stands)
        card = None
    return {"errors": len(rep.blocking), "firstError": rep.blocking[0] if rep.blocking else "", "card": card}


def diff_counts(diffs: list[dict]) -> dict:
    """{add, del} over expanded diff blocks' files (context files left out), as card() counted them."""
    add = dele = 0
    for f in (f for b in diffs for f in b.get("files") or [] if isinstance(f, dict) and f.get("status") != "context"):
        n_add, n_del = f.get("add"), f.get("del")
        if n_add is None or n_del is None:
            lines = [ln for hk in f.get("hunks") or [] if not hk.get("context") for ln in hk.get("lines") or []]
            n_add, n_del = sum(ln.startswith("+") for ln in lines), sum(ln.startswith("-") for ln in lines)
        add, dele = add + int(n_add), dele + int(n_del)
    return {"add": add, "del": dele}


def worker() -> int:
    """The validation worker's loop: a request a line, an answer a line; ends at EOF."""
    import sys   # noqa: PLC0415
    try:
        os.nice(10)
    except OSError:
        pass
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    stub = os.environ.get("BLUEDOC_TEST_VALIDATE_SLEEP")   # tests: a validator that takes this many seconds
    for line in sys.stdin:
        try:
            req = json.loads(line)
            if stub:
                time.sleep(float(stub))
            out = validate_doc(req["path"])
        except Exception as e:   # noqa: BLE001
            out = {"errors": 1, "firstError": f"cannot validate: {e}", "card": None}
        sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(worker() if sys.argv[1:] == ["worker"] else 2)
