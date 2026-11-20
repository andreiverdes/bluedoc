"""Upgrading from bluedoc 1.1.0 (commit 20abba6, run from a `git archive` of it) and going back.

On a temp home with the Acme examples, 1.1.0 saves a reader's ticks and picks, an approval, an archive, an answer and
a title and emoji through its own routes. The new server on that home answers its first index.json at once, has rows
within 1 s and every row within 3 s, and each doc's reader fields (approval, answers, changes, archived, title,
emoji) equal what 1.1.0 listed; with Chrome (BLUEDOC_BROWSER_TESTS=1), each status pill 1.1.0's home showed equals
the new server's status and the new home's pill. 1.1.0 on the home the new server indexed lists every doc and saves a
tick, and never touches index-1.db. A 1.1.0 `open` still replaces a newer server (its rule), and the next newer `open`
replaces it back."""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import quote

from _support import REPO, SCRIPTS, Server, TempHome, free_port
from test_page_state import CHROME, Browser, Tab

OLD_COMMIT = "20abba6"   # 1.1.0; no tag exists for it
JSON = {"Content-Type": "application/json", "X-Bluedoc": "1"}
OLD: Path | None = None


def setUpModule() -> None:
    global OLD
    OLD = Path(tempfile.mkdtemp(prefix="bluedoc-1.1.0-"))
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null"}
    archive = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(REPO), "archive", OLD_COMMIT],
                             env=env, capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(OLD)], input=archive, check=True)


def tearDownModule() -> None:
    shutil.rmtree(OLD, ignore_errors=True)


def badge(st: dict) -> str:
    """The status pill home.html draws for a status (statusBadge)."""
    return ("Archived" if st["archived"] else "Doesn't build" if st["errors"] else "Approved" if st["approved"]
            else "Waiting on agent" if st["waiting"] else "Awaiting approval" if st["awaiting"] else "Needs you" if st["needs"] else "—")


def epoch(v) -> float | None:
    if v is None or isinstance(v, (int, float)):
        return v
    return dt.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()


@dataclasses.dataclass
class Saved:
    """What 1.1.0 listed after the reader's writes: {slug/path: doc} and the slug."""
    docs: dict
    slug: str


class Upgrade(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples("w/docs")
        now = time.time()
        for p in self.docs.rglob("*"):   # all edited today: 1.1.0's home shows them in an open date group
            os.utime(p, (now - 60, now - 60))
        self.assertEqual(self.tmp.run("serve.py", "add", self.docs).returncode, 0)
        self.port = free_port()
        self.old = Server(self.tmp, OLD / "skills" / "bluedoc" / "scripts", self.port)
        self.new = Server(self.tmp, SCRIPTS, self.port)

    def tearDown(self) -> None:
        self.old.stop()
        self.new.stop()

    def seed(self, server: Server, url: str) -> dict:
        html = server.req("GET", url)[1].decode()
        return json.loads(re.search(r'<script type="application/json" id="bp-state">(.*?)</script>', html, re.S).group(1))

    def put(self, server: Server, url: str, ops: list) -> None:
        body = json.dumps({"path": url, "import": False, "ops": ops}).encode()
        status, raw = server.req("PUT", "/__bluedoc/state", body, {**JSON, "Origin": f"http://{server.host}"})
        self.assertEqual(status, 200, raw)

    def write_through_1_1_0(self) -> Saved:
        """Ticks, a pick, an approval, an archive, an answer, a title and an emoji, through 1.1.0's routes; its index."""
        s = self.old
        s.start()
        url = {p.name.split(".")[0]: s.url_for(p) for p in self.docs.glob("*.bluedoc.json")}
        orders = json.loads((self.docs / "acme-orders.bluedoc.json").read_text(encoding="utf-8"))
        cl = next(b for sec in orders["sections"] for b in sec.get("blocks") or [] if b.get("type") == "checklist")
        self.put(s, url["acme-orders"], [[f"{cl['id']}:{cl['items'][0]['id']}", "1"], [f"{cl['id']}:{cl['items'][1]['id']}", "1"]])
        plan = json.loads((self.docs / "acme-saved-carts-plan.bluedoc.json").read_text(encoding="utf-8"))
        dec = next((b, it) for sec in plan["sections"] for b in sec.get("blocks") or [] if b.get("type") == "checklist"
                   for it in b["items"] if it.get("choices"))
        self.put(s, url["acme-saved-carts-plan"], [[f"{dec[0]['id']}:{dec[1]['id']}", f"={dec[1]['choices'][0]['id']}|{dec[1].get('choice') or ''}"]])
        design = json.loads((self.docs / "acme-fit-design.bluedoc.json").read_text(encoding="utf-8"))
        body = {"path": url["acme-fit-design"], "rev": str(design["meta"]["rev"]), "docHash": self.seed(s, url["acme-fit-design"])["docHash"],
                "decision": "approved", "answers": [], "annotations": [], "at": "2026-01-01T00:00:00Z", "markdown": "# Design approved\n"}
        self.assertEqual(s.req("POST", "/__bluedoc/approve", json.dumps(body).encode(), JSON)[0], 200)
        status = json.loads((self.docs / "acme-status.bluedoc.json").read_text(encoding="utf-8"))
        self.put(s, url["acme-status"], [["__archived", json.dumps({"at": "2026-11-01T10:00:00Z", "rev": str(status["meta"]["rev"])})]])
        answers = {"path": url["acme-review-findings"], "rev": "1", "items": [], "markdown": "# Answers\n\nShip it.\n"}
        self.assertEqual(s.req("POST", "/__bluedoc/reply", json.dumps(answers).encode(), JSON)[0], 200)
        self.put(s, url["acme-fit-deck"], [["__title", "Acme Fit launch deck"], ["__emoji", "🚀"]])
        index = json.loads(s.req("GET", "/__bluedoc/index.json", headers={"X-Bluedoc": "1"})[1])
        root = next(r for r in index["roots"] if r["docs"])
        return Saved({f"{root['slug']}/{d['path']}": d for d in root["docs"]}, root["slug"])

    def pills(self, server: Server, slug: str, old: bool) -> dict:
        """{slug/path: pill text} from the home in Chrome, Rows view, the archived docs too."""
        browser = Browser(Path(tempfile.mkdtemp(prefix="bluedoc-chrome-")))
        self.addCleanup(browser.close)
        status, raw = server.req("POST", "/__bluedoc/unlock", b"{}", JSON)
        self.assertEqual(status, 200, raw)
        t = Tab(browser)
        base = f"http://{server.host}"
        browser.call("Page.navigate", {"url": f"{base}/?key={json.loads(raw)['token']}"}, t.session)
        t.wait_for("document.readyState === 'complete'")
        t.ev("localStorage.setItem('bluedoc:home', JSON.stringify({...JSON.parse(localStorage.getItem('bluedoc:home') || '{}'), view: 'rows'}))")
        out = {}
        for query in (f"p={quote(slug)}", f"p={quote(slug)}&s=archived"):
            browser.call("Page.navigate", {"url": f"{base}/?{query}"}, t.session)
            t.wait_for("document.querySelectorAll('.bd-r[data-key]').length > 0", timeout=15)
            time.sleep(0.3)
            out.update(t.ev("Object.fromEntries([...document.querySelectorAll('.bd-r[data-key]')].map(r => "
                            "[r.dataset.key, (r.querySelector('.bd-sp') || r.querySelector('.bd-no') || {}).textContent || '—']))"))
        return out

    def test_upgrade_keeps_every_reader_field_and_status(self) -> None:
        saved = self.write_through_1_1_0()
        old_pills = self.pills(self.old, saved.slug, True) if CHROME else None
        self.old.stop()
        self.assertFalse(list(self.tmp.home.glob("index-*.db")), "1.1.0 made an index file")
        self.new.start()
        t = time.monotonic()
        status, raw = self.new.req("GET", f"/__bluedoc/index.json?view=rows&p={saved.slug}&limit=25", headers={"X-Bluedoc": "1"})
        took = time.monotonic() - t
        self.assertEqual(status, 200)
        self.assertLess(took, 0.2, "the first index.json waited")
        first = json.loads(raw)
        if "indexing" in first:
            self.assertLessEqual(first["indexing"]["done"], first["indexing"]["total"])
        deadline = time.monotonic() + 1
        while not self.new.index(f"p={saved.slug}", "rows")["docs"]:
            self.assertLess(time.monotonic(), deadline, "no rows within 1 s")
            time.sleep(0.02)
        deadline = time.monotonic() + 3
        while True:
            got = self.new.index(f"p={saved.slug}", "rows")
            if "indexing" not in got:
                break
            self.assertLess(time.monotonic(), deadline, f"not every row within 3 s: {got['indexing']}")
            time.sleep(0.05)
        self.new.indexed()
        rows = {f"{saved.slug}/{d['path']}": d for d in self.new.docs("rows", wait=False)}
        self.assertEqual(set(rows), set(saved.docs))
        for key, before in saved.docs.items():
            after = rows[key]
            with self.subTest(doc=key):
                for k in ("answers", "changes"):
                    self.assertEqual(after.get(k), before.get(k), k)
                self.assertEqual(after.get("approval") and {x: after["approval"][x] for x in ("rev", "carried")},
                                 before.get("approval") and {x: before["approval"][x] for x in ("rev", "carried")})
                self.assertEqual((after["title"], after["emoji"]), (before["title"], before["emoji"]))
                self.assertEqual(after["archived"], epoch(before["archived"]))
                if old_pills is not None:
                    self.assertEqual(badge(after["st"]), old_pills[key], "the status pill changed")
        self.assertTrue(rows[f"{saved.slug}/acme-fit-design.bluedoc.json"]["st"]["approved"])
        self.assertTrue(rows[f"{saved.slug}/acme-status.bluedoc.json"]["st"]["archived"])
        self.assertTrue(rows[f"{saved.slug}/acme-review-findings.bluedoc.json"]["st"]["waiting"])
        self.assertEqual(rows[f"{saved.slug}/acme-orders.bluedoc.json"]["st"]["done"], 2)
        if old_pills is not None:
            self.assertEqual(self.pills(self.new, saved.slug, False), old_pills, "the new home's pills")

    def test_downgrade_lists_every_doc_and_saves(self) -> None:
        saved = self.write_through_1_1_0()
        self.old.stop()
        self.new.start()
        self.new.indexed()
        self.new.stop()
        index_file = self.tmp.home / "index-1.db"
        self.assertTrue(index_file.is_file())
        digest = hashlib.sha256(index_file.read_bytes()).hexdigest()
        self.old.start()
        index = json.loads(self.old.req("GET", "/__bluedoc/index.json", headers={"X-Bluedoc": "1"})[1])
        self.assertEqual({f"{r['slug']}/{d['path']}" for r in index["roots"] for d in r["docs"]}, set(saved.docs))
        url = self.old.url_for(self.docs / "acme-saved-carts-plan.bluedoc.json")
        plan = json.loads((self.docs / "acme-saved-carts-plan.bluedoc.json").read_text(encoding="utf-8"))
        step = next((b, it) for sec in plan["sections"] for b in sec.get("blocks") or [] if b.get("type") == "checklist"
                    for it in b["items"] if not it.get("choices"))
        self.put(self.old, url, [[f"{step[0]['id']}:{step[1]['id']}", "1"]])
        self.old.stop()
        self.assertEqual(hashlib.sha256(index_file.read_bytes()).hexdigest(), digest, "1.1.0 touched index-1.db")

    def test_a_1_1_0_open_still_replaces_a_newer_server(self) -> None:
        env = {**self.tmp.env, "BLUEDOC_PORT": str(self.port)}
        doc = self.docs / "acme-status.bluedoc.json"

        def open_with(scripts: Path) -> dict:
            r = subprocess.run([sys.executable, str(scripts / "serve.py"), "open", str(doc), "--to", "none"], env=env,
                               cwd=self.tmp.dir, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(self.new.req("GET", "/__bluedoc/ping", headers={"X-Bluedoc": "1"})[1])
        self.addCleanup(lambda: subprocess.run([sys.executable, str(SCRIPTS / "serve.py"), "stop"], env=env, capture_output=True, timeout=30))
        newer = open_with(SCRIPTS)
        self.assertIn("index", newer)
        older = open_with(OLD / "skills" / "bluedoc" / "scripts")
        self.assertNotEqual(older["pid"], newer["pid"], "1.1.0's rule replaces any other code")
        self.assertNotIn("index", older)
        again = open_with(SCRIPTS)
        self.assertNotEqual(again["pid"], older["pid"], "the next newer open replaces 1.1.0")
        self.assertIn("index", again)


if __name__ == "__main__":
    unittest.main()
