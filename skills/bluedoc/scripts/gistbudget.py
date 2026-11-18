#!/usr/bin/env python3
"""How many gist updates bluedoc sends per GitHub account, and when the next one may go (share.py, serve.py).

GitHub refuses an account's gist updates past about 100 an hour, and publishes no number for it. bluedoc sends at most
BUDGET (90) gist updates an hour per account, and at most one every SPACING (60) seconds per doc; deletes are logged but
never wait (the reader asked for them). An update that doesn't fit waits (serve.py's queue sends it when it is due).

A refusal (a 403 or 429 that names a rate limit, or carries `retry-after` or `x-ratelimit-remaining: 0`: rate_limited)
sets the account's retry time: `retry-after` seconds, else `x-ratelimit-reset`, else 1 min doubling with each refusal
in a row, up to 60 min. PAUSE_AFTER (4) refusals in a row pause the account: nothing goes out on it until the reader
resumes (the Share sheet's Resume updates, `serve.py share --resume`).

The log is $BLUEDOC_HOME/gist-budget.json (mode 0600, written atomically), keyed by the login in lower case:
  {"acme-dev": {"sent": [epoch, …], "retryAt": epoch | null, "refusals": 0, "paused": false, "docs": {path: epoch}}}
`sent` holds the account's writes in the last hour, `docs` each doc's last update. Times are wall-clock epoch seconds,
so the log survives restarts; one in the future (the clock went back) counts as now. Every function reads the file
afresh: the server and `build.py patch` see one count. `clock` is the time source; tests replace it.
Python 3.9+ standard library only."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

BUDGET = 90          # gist updates per account in the last hour
SPACING = 60         # seconds between two updates of one doc
HOUR = 3600
PAUSE_AFTER = 4      # refusals in a row that pause an account
BACKOFF_MAX = 3600   # the longest wait a refusal without GitHub's own time sets
GITHUB_LIMIT = 100   # what GitHub allows, as observed: the copy says "about 100"
clock = time.time
_LOCK = threading.Lock()


def budget_file() -> Path:
    return Path(os.environ.get("BLUEDOC_HOME") or "~/.bluedoc").expanduser() / "gist-budget.json"


def _load() -> dict:
    try:
        data = json.loads(budget_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    f = budget_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f"{f.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(json.dumps(data, indent=1, sort_keys=True) + "\n")
    tmp.replace(f)


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _entry(data: dict, login: str, now: float) -> dict:
    """The account's record, its hour pruned: sent times older than an hour dropped, future ones counted as now."""
    e = data.get(login.lower())
    e = e if isinstance(e, dict) else {}
    sent = sorted(min(t, now) for t in map(_num, e.get("sent") or []) if t is not None and t > now - HOUR)
    docs = {str(k): min(t, now) for k, t in ((k, _num(v)) for k, v in (e.get("docs") or {}).items())
            if t is not None and t > now - HOUR}
    retry = _num(e.get("retryAt"))
    refusals = e.get("refusals")
    return {"sent": sent, "retryAt": retry if retry is not None and retry > now else None,
            "refusals": refusals if isinstance(refusals, int) and refusals > 0 else 0, "paused": e.get("paused") is True,
            "docs": docs}


def _now(now: float | None) -> float:
    return clock() if now is None else now


def due(login: str, doc: str | None = None, now: float | None = None) -> tuple[float | None, str | None]:
    """(when the account may send the doc's next update, why it waits): (now, None) at once; else the latest of the hour
    freeing a place (why "hour"), the doc's last update + SPACING ("spacing") and GitHub's retry time ("retry").
    (None, "paused") while the account is paused."""
    now = _now(now)
    e = _entry(_load(), login, now)
    if e["paused"]:
        return None, "paused"
    at, why = now, None
    if len(e["sent"]) >= BUDGET:
        at, why = e["sent"][len(e["sent"]) - BUDGET] + HOUR, "hour"
    last = e["docs"].get(str(doc)) if doc is not None else None
    if last is not None and last + SPACING > at:
        at, why = last + SPACING, "spacing"
    if e["retryAt"] is not None and e["retryAt"] > at:
        at, why = e["retryAt"], "retry"
    return at, why


def _update(login: str, now: float, fn) -> dict:
    with _LOCK:
        data = _load()
        e = _entry(data, login, now)
        fn(e)
        data[login.lower()] = e
        for k in [k for k in data if k != login.lower()]:   # other accounts' hours pruned too, so the file stays small
            data[k] = _entry(data, k, now)
        _save(data)
        return e


def sent(login: str, doc: str | None = None, now: float | None = None) -> dict:
    """Log a gist write (a create or an update of doc; doc None: a delete) that GitHub took: it counts in the hour, and
    the refusals in a row start again."""
    now = _now(now)

    def fn(e: dict) -> None:
        e["sent"].append(now)
        if doc is not None:
            e["docs"][str(doc)] = now
        e["refusals"], e["retryAt"] = 0, None
    return _update(login, now, fn)


def deleted(login: str, now: float | None = None) -> dict:
    """Log a delete: it counts in the hour, and never waits."""
    return sent(login, None, now)


def _header(headers: dict, name: str) -> str | None:
    return next((str(v).strip() for k, v in (headers or {}).items() if k.lower() == name), None)


def rate_limited(status: int | None, headers: dict | None, text: str = "") -> bool:
    """Whether GitHub's answer is a rate-limit refusal: a 403 or 429 that names a rate limit, or carries retry-after or
    x-ratelimit-remaining: 0. Any other 403 is an error as before."""
    if status not in (403, 429):
        return False
    return (_header(headers or {}, "retry-after") is not None or _header(headers or {}, "x-ratelimit-remaining") == "0"
            or "rate limit" in (text or "").lower())


def wait_of(headers: dict | None, refusals: int, now: float) -> float:
    """Seconds GitHub asks to wait: retry-after, else until x-ratelimit-reset, else 1 min doubling with each refusal in
    a row (refusals: this one included), at most BACKOFF_MAX."""
    ra = _header(headers or {}, "retry-after")
    if ra is not None:
        try:
            return max(1.0, float(ra))
        except ValueError:
            pass
    reset = _header(headers or {}, "x-ratelimit-reset")
    if reset is not None:
        try:
            return max(1.0, float(reset) - now)
        except ValueError:
            pass
    return float(min(BACKOFF_MAX, 60 * 2 ** max(0, refusals - 1)))


def refused(login: str, headers: dict | None = None, now: float | None = None) -> dict:
    """Log a rate-limit refusal: the retry time from GitHub's headers (wait_of), and the account paused at the
    PAUSE_AFTER-th refusal in a row. The account's record."""
    now = _now(now)

    def fn(e: dict) -> None:
        e["refusals"] += 1
        e["retryAt"] = now + wait_of(headers, e["refusals"], now)
        if e["refusals"] >= PAUSE_AFTER:
            e["paused"] = True
    return _update(login, now, fn)


def resume(login: str, now: float | None = None) -> dict:
    """Lift the account's pause: its refusals and retry time cleared, its hour kept."""
    now = _now(now)

    def fn(e: dict) -> None:
        e["paused"], e["refusals"], e["retryAt"] = False, 0, None
    return _update(login, now, fn)


def status(login: str, now: float | None = None) -> dict:
    """{login, used: updates in the last hour, limit: BUDGET, next: when a place frees (epoch) while the hour is full,
    else null, retryAt, paused, refusals} for the account."""
    now = _now(now)
    e = _entry(_load(), login, now)
    full = len(e["sent"]) >= BUDGET
    return {"login": login, "used": len(e["sent"]), "limit": BUDGET,
            "next": e["sent"][len(e["sent"]) - BUDGET] + HOUR if full else None, "retryAt": e["retryAt"],
            "paused": e["paused"], "refusals": e["refusals"]}
