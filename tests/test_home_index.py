"""The home page's JSON from index.db: GET /__bluedoc/index.json?view=… and /__bluedoc/stats.

A request without ?view (a page of an earlier version) is 409 {error, code}; every answer carries X-Bluedoc-Code;
/__bluedoc/search-text is gone (404). index.json answers with an ETag and 304 to a matching If-None-Match over
HTTP/1.1 (Cache-Control: no-cache); the key (unlocked) and the query are part of it. Slices page by offset and limit
with `next`; rows and cards carry each doc's `card` (an open row draws it), ?view=menu carries the menu's fields only; ?p= one folder. What it says
follows every change within a sweep: a doc edited, added, renamed or deleted, a subfolder made or removed, a folder
added or removed through Settings, a registered folder gone (missing) and back. Rows survive a restart and answer the
first request; the indexer then reads nothing that didn't change. Stage 1 runs no git and opens no screen or capture
file. Validation runs in a worker process: a slow one never holds a request, and its badge lands after. Statistics
counts from index.db."""
from __future__ import annotations

import builtins
import io
import json
import os
import re
import shutil
import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock

from _support import Server, TempHome

import indexdb   # on sys.path through _support
import serve

JSON = {"Content-Type": "application/json", "X-Bluedoc": "1"}


def write_doc(p: Path, doc: dict) -> None:
    p.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


class HomeIndex(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.docs = self.tmp.copy_examples()
        self.doc = self.docs / "acme-orders.bluedoc.json"
        self.plan = self.docs / "acme-saved-carts-plan.bluedoc.json"
        self.assertEqual(self.tmp.run("serve.py", "add", self.docs).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.url, self.plan_url = self.server.url_for(self.doc), self.server.url_for(self.plan)
        self.slug = self.url.split("/")[1]

    def tearDown(self) -> None:
        self.server.stop()
        self.tmp.cleanup()

    def fetch(self, path: str, etag: str = "", key: bool = False) -> tuple[int, dict, bytes]:
        headers = {"If-None-Match": etag} if etag else {}
        if key:
            headers["X-Bluedoc"] = "1"
        return self.server.exchange("GET", path, headers=headers)

    def listed(self, query: str = "") -> dict:
        """{path: row} of this folder after a sweep that started now."""
        self.server.indexed(fresh=True)
        return {d["path"]: d for d in self.server.index(f"p={self.slug}" + ("&" + query if query else ""), "rows")["docs"]}

    def test_old_pages_get_409_and_every_answer_names_the_code(self) -> None:
        code = json.loads(self.server.req("GET", "/__bluedoc/ping", headers={"X-Bluedoc": "1"})[1])["code"]
        status, head, body = self.fetch("/__bluedoc/index.json")
        self.assertEqual((status, json.loads(body)), (409, {"error": "bluedoc was updated: reload", "code": code}))
        self.assertEqual(head["x-bluedoc-code"], code)
        self.assertEqual(self.fetch("/__bluedoc/index.json?root=" + self.slug)[0], 409, "1.1.0's doc menu")
        for path in ("/__bluedoc/index.json?view=rows", "/__bluedoc/stats", self.url, "/", "/__bluedoc/nope"):
            with self.subTest(path=path):
                self.assertEqual(self.fetch(path)[1].get("x-bluedoc-code"), code)
        self.assertEqual(self.fetch("/__bluedoc/search-text")[0], 404)

    def test_etag_and_304(self) -> None:
        self.server.indexed()
        path = f"/__bluedoc/index.json?view=cards&p={self.slug}"
        status, head, body = self.fetch(path)
        self.assertEqual(status, 200)
        self.assertEqual((head["cache-control"], head["connection"]), ("no-cache", "close"))
        etag = head["etag"]
        self.assertTrue(re.fullmatch(r'"[0-9a-f]{32}"', etag), etag)
        for sent in (etag, f"W/{etag}", f'"nope", {etag}', "*"):
            with self.subTest(sent=sent):
                status, head, again = self.fetch(path, sent)
                self.assertEqual((status, again, head["etag"], head["cache-control"]), (304, b"", etag, "no-cache"))
        self.assertEqual(self.fetch(path, '"nope"')[::2], (200, body))
        # the key (unlocked) and the query are part of it
        status, head, keyed = self.fetch(path, etag, key=True)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(keyed)["unlocked"])
        self.assertNotEqual(self.fetch(path + "&t=plan", etag)[0], 304)
        # a reader's write moves it
        own = {**JSON, "Origin": f"http://{self.server.host}"}
        rev = str(json.loads(self.doc.read_text(encoding="utf-8"))["meta"]["rev"])
        body = json.dumps({"path": self.url, "ops": [["__archived", json.dumps({"at": "2026-01-01T00:00:00Z", "rev": rev})]]})
        self.assertEqual(self.server.req("PUT", "/__bluedoc/state", body.encode(), own)[0], 200)
        self.assertEqual(self.fetch(path, etag)[0], 200)

    def test_slices_views_and_folders(self) -> None:
        self.server.indexed()
        q = f"p={self.slug}"
        whole = self.server.index(q, "rows")
        self.assertEqual((whole["total"], whole["next"]), (8, None))
        # an open row draws the card's hero: rows carry the same card numbers as cards do
        cards = {d["url"]: d for d in self.server.index(q, "cards")["docs"]}
        self.assertEqual({d["url"]: d.get("card") for d in whole["docs"]}, {u: d["card"] for u, d in cards.items()})
        orders = next(d for d in whole["docs"] if d["path"].startswith("acme-orders"))
        self.assertTrue(orders["card"].get("nodes"), orders["card"])
        mtimes = [d["mtime"] for d in whole["docs"]]
        self.assertEqual(mtimes, sorted(mtimes, reverse=True), "newest first")
        got, offset = [], 0
        while offset is not None:
            s = json.loads(self.server.req("GET", f"/__bluedoc/index.json?view=rows&{q}&offset={offset}&limit=3",
                                           headers={"X-Bluedoc": "1"})[1])
            got += [d["url"] for d in s["docs"]]
            offset = s["next"]
        self.assertEqual(got, [d["url"] for d in whole["docs"]], "the slices add up to the list, no row twice")
        old = self.server.index(q + "&sort=old", "rows")["docs"]
        self.assertEqual([d["url"] for d in old], [d["url"] for d in whole["docs"]][::-1])
        cards = self.server.index(q, "cards")["docs"]
        self.assertTrue(all("card" in d and "st" in d for d in cards))
        menu = self.server.index(q, "menu")["docs"]
        self.assertEqual({k for d in menu for k in d} - {"planSteps"},
                         {"url", "root", "path", "title", "docTitle", "emoji", "type", "mtime", "archived", "st"})
        plan = next(d for d in menu if d["path"] == self.plan.name)
        steps = [it for s in json.loads(self.plan.read_text(encoding="utf-8"))["sections"] for b in s.get("blocks") or []
                 if b.get("type") == "steps" for it in b["items"]]
        self.assertEqual(plan["planSteps"], [sum(it.get("status") == "done" for it in steps), len(steps)])
        # ?doc= reaches that doc in the first slice
        last = whole["docs"][-1]
        s = self.server.index(f"{q}&doc={self.slug}/{last['path']}&limit=2", "rows")
        self.assertIn(last["url"], [d["url"] for d in s["docs"]])

    def test_counts_facets_hero_and_groups(self) -> None:
        self.server.indexed()
        now = time.time()
        # one doc a day ago, one 10 days ago, one 60 days ago: today, this week, this month, older at tz 0
        for name, age in (("acme-orders", 86400 * 2), ("acme-status", 86400 * 10), ("acme-site", 86400 * 60)):
            os.utime(self.docs / f"{name}.bluedoc.json", (now - age, now - age))
        self.server.indexed(fresh=True)
        got = self.server.index(f"p={self.slug}&tz=0", "rows")
        self.assertEqual(got["groups"], {"today": 5, "week": 1, "month": 1, "older": 1})
        self.assertEqual(got["facets"]["types"], {"design": 1, "docs": 1, "other": 1, "plan": 1, "presentation": 1, "review": 1,
                                                  "storelisting": 1, "website": 1})
        sts = [d["st"] for d in got["docs"]]
        self.assertEqual(got["facets"]["statuses"], {s: n for s in indexdb.STATUSES
                                                     if (n := sum(bool(st[s]) for st in sts))})
        self.assertEqual(got["hero"]["docs"], 8)
        self.assertEqual(got["hero"]["decisionsOpen"], sum(st["dec"] - st["decided"] for st in sts))
        self.assertEqual(got["hero"]["newest"], max(d["mtime"] for d in got["docs"]))
        root = next(r for r in got["roots"] if r["slug"] == self.slug)
        self.assertEqual((root["count"], root["last"]), (8, got["hero"]["newest"]))
        # a type, a status: the slice and the counts follow
        plans = self.server.index(f"p={self.slug}&t=plan", "rows")
        self.assertEqual([d["type"] for d in plans["docs"]], ["plan"])
        needs = self.server.index(f"p={self.slug}&s=needs", "rows")
        self.assertEqual(needs["total"], got["facets"]["statuses"]["needs"])
        self.assertTrue(all(d["st"]["needs"] for d in needs["docs"]))
        # folders: a doc in a subfolder shows in facets.dirs and ?d=
        (self.docs / "plans" / "q4").mkdir(parents=True)
        shutil.copy(self.plan, self.docs / "plans" / "q4" / "acme-q4-plan.bluedoc.json")
        self.server.indexed(fresh=True)
        got = self.server.index(f"p={self.slug}&d=plans", "rows")
        self.assertEqual(got["facets"]["dirs"], [{"dir": "plans/q4", "n": 1}])
        self.assertEqual([d["path"] for d in got["docs"]], ["plans/q4/acme-q4-plan.bluedoc.json"])

    def test_search_ranks_and_snips(self) -> None:
        self.server.indexed()
        got = self.server.index(f"p={self.slug}&q=saved+carts", "rows")
        self.assertTrue(got["docs"])
        self.assertEqual(got["docs"][0]["path"], self.plan.name, "the title match first")
        self.assertTrue(any(d.get("snip") for d in got["docs"]))
        self.assertEqual(self.server.index(f"p={self.slug}&q=zzqqxx", "rows")["total"], 0)
        # by the project's name and the doc's path
        self.assertEqual(self.server.index(f"p={self.slug}&q={self.slug}", "rows")["total"], 8)
        self.assertEqual([d["path"] for d in self.server.index(f"p={self.slug}&q=fit-deck", "rows")["docs"]],
                         ["acme-fit-deck.bluedoc.json"])

    def test_doc_changes_show(self) -> None:
        self.assertIn(self.doc.name, self.listed())
        doc = json.loads(self.doc.read_text(encoding="utf-8"))
        for title in ("Acme orders, edited", "Acme orders, edited again"):
            doc["title"] = title
            write_doc(self.doc, doc)
            self.assertEqual(self.listed()[self.doc.name]["docTitle"], title)
            self.assertEqual([d["path"] for d in self.server.index(f"p={self.slug}&q={title.replace(' ', '+')}", "rows")["docs"]][:1],
                             [self.doc.name], "search finds the new title")
        added = self.docs / "acme-orders-copy.bluedoc.json"
        shutil.copy(self.doc, added)
        (self.docs / "later").mkdir()
        shutil.copy(self.plan, self.docs / "later" / "acme-later-plan.bluedoc.json")
        listed = self.listed()
        self.assertIn(added.name, listed)
        self.assertIn("later/acme-later-plan.bluedoc.json", listed)
        renamed = self.docs / "acme-orders-renamed.bluedoc.json"
        added.rename(renamed)
        listed = self.listed()
        self.assertNotIn(added.name, listed)
        self.assertIn(renamed.name, listed)
        renamed.unlink()
        shutil.rmtree(self.docs / "later")
        listed = self.listed()
        self.assertNotIn(renamed.name, listed)
        self.assertNotIn("later/acme-later-plan.bluedoc.json", listed)
        self.assertIn(self.doc.name, listed)

    def test_folders_added_removed_and_missing(self) -> None:
        other = self.tmp.dir / "acme-fit"
        other.mkdir()
        shutil.copy(self.docs / "acme-fit-deck.bluedoc.json", other / "acme-fit-deck.bluedoc.json")
        status, raw = self.server.req("POST", "/__bluedoc/folders", json.dumps({"add": str(other)}).encode(), JSON)
        self.assertEqual(status, 200, raw)
        self.server.indexed(fresh=True)
        self.assertEqual([d["path"] for d in self.server.index("p=acme-fit", "rows")["docs"]], ["acme-fit-deck.bluedoc.json"])
        moved = self.tmp.dir / "acme-fit-away"
        other.rename(moved)
        self.server.indexed(fresh=True)
        got = self.server.index("", "rows")
        self.assertNotIn("acme-fit", [r["slug"] for r in got["roots"]])
        self.assertEqual([m["path"] for m in got["missing"]], [str(other)])
        self.assertEqual(self.server.index("q=acme-fit-deck&hidden=1", "rows")["total"]
                         + self.server.index("q=acme-fit-deck", "rows")["total"], 1, "the gone folder's deck is no row")
        moved.rename(other)
        self.server.indexed(fresh=True)
        self.assertEqual([d["path"] for d in self.server.index("p=acme-fit", "rows")["docs"]], ["acme-fit-deck.bluedoc.json"])
        status, raw = self.server.req("POST", "/__bluedoc/folders", json.dumps({"remove": str(other)}).encode(), JSON)
        self.assertEqual(status, 200, raw)
        self.server.indexed(fresh=True)
        self.assertEqual([r["slug"] for r in self.server.index("", "rows")["roots"]], [self.slug])

    def test_rows_survive_a_restart(self) -> None:
        """A restarted server answers its first request from index.db: every row, no `indexing`, at once."""
        self.server.indexed()
        before = self.server.index(f"p={self.slug}", "cards")
        self.server.stop()
        self.server.start()
        t = time.monotonic()
        status, raw = self.server.req("GET", f"/__bluedoc/index.json?view=cards&p={self.slug}&limit=48", headers={"X-Bluedoc": "1"})
        took = time.monotonic() - t
        after = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertLess(took, 0.2)
        self.assertNotIn("indexing", after)
        self.assertEqual([d["url"] for d in after["docs"]], [d["url"] for d in before["docs"]])
        self.assertEqual([d["card"] for d in after["docs"]], [d["card"] for d in before["docs"]])

    def test_statistics(self) -> None:
        self.server.indexed()
        status, raw = self.server.req("GET", f"/__bluedoc/stats?p={self.slug}&range=7&tz=0", headers={"X-Bluedoc": "1"})
        self.assertEqual(status, 200)
        st = json.loads(raw)
        self.assertEqual(st["docs"], 8)
        self.assertEqual(len(st["activity"]["counts"]), 14, "two weeks at least: this week against the last")
        self.assertEqual(st["activity"]["counts"][-1], 8, "every doc was saved today (the copy's mtimes)")
        self.assertEqual(st["types"]["review"], 1)
        rows = self.server.index(f"p={self.slug}", "rows")["docs"]
        self.assertEqual(st["decisions"]["dec"], sum(d["st"]["dec"] for d in rows))
        self.assertEqual(st["decisions"]["decided"], sum(d["st"]["decided"] for d in rows))
        self.assertEqual([x["url"] for x in st["decisions"]["open"]],
                         [d["url"] for d in sorted((d for d in rows if d["st"]["needs"]),
                                                   key=lambda d: (-(d["st"]["dec"] - d["st"]["decided"]), -d["mtime"]))][:3])
        review = json.loads((self.docs / "acme-review-findings.bluedoc.json").read_text(encoding="utf-8"))
        sizes = [it.get("state") for b in serve.build.all_blocks(review) if b.get("type") == "checklist" for it in b["items"]]
        self.assertEqual(st["findings"], {k: sizes.count(k) for k in ("blocker", "major", "minor", "nit")})
        self.assertEqual(st["byProject"], [{"slug": self.slug, "n": sum(st["activity"]["counts"][-7:])}])


class SlowValidation(unittest.TestCase):
    """Validation runs in the worker: a request never waits on it, and the badge lands when it is done."""

    def test_requests_never_wait_on_validation(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        tmp.env["BLUEDOC_TEST_VALIDATE_SLEEP"] = "3"
        docs = tmp.dir / "docs"
        docs.mkdir()
        bad = json.loads((serve.HERE.parent / "examples" / "acme-status.bluedoc.json").read_text(encoding="utf-8"))
        bad["sections"][0]["blocks"].append({"type": "no-such-block"})
        write_doc(docs / "acme-bad.bluedoc.json", bad)
        old = time.time() - 60
        os.utime(docs / "acme-bad.bluedoc.json", (old, old))
        self.assertEqual(tmp.run("serve.py", "add", docs).returncode, 0)
        server = Server(tmp)
        server.start()
        self.addCleanup(server.stop)
        slug = json.loads(server.req("GET", "/__bluedoc/index.json?view=menu", headers={"X-Bluedoc": "1"})[1])["roots"][0]["slug"]
        deadline, seen_null, slowest = time.monotonic() + 15, False, 0.0
        while time.monotonic() < deadline:
            t = time.monotonic()
            got = server.index(f"p={slug}", "rows")
            slowest = max(slowest, time.monotonic() - t)
            if got["docs"]:
                row = got["docs"][0]
                if row["errors"] is None:
                    seen_null = True
                    self.assertFalse(row["st"]["errors"], "a doc not validated yet counts as building")
                elif row["errors"] > 0:
                    break
            time.sleep(0.1)
        else:
            self.fail("the badge never landed")
        self.assertTrue(seen_null, "the row showed before its validation")
        self.assertLess(slowest, 0.2, "a request waited on validation")
        self.assertTrue(row["firstError"] and row["st"]["errors"] and row["st"]["col"] == "errors", row)


class Indexing(unittest.TestCase):
    """In process: what a sweep reads, and what stage 1 doesn't."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.docs = self.tmp.copy_examples()
        (self.docs / "sub").mkdir()
        shutil.copy(self.docs / "acme-orders.bluedoc.json", self.docs / "sub" / "acme-sub.bluedoc.json")
        old = time.time() - 3600   # past serve.RACY_NS: a fresh mtime is never stored as the file key
        for d, _, files in os.walk(self.docs):
            for f in files:
                os.utime(Path(d, f), (old, old))
            os.utime(d, (old, old))
        serve._dirs.clear()
        roots = [self.docs]
        self.patches = [mock.patch.object(serve, "DB", None), mock.patch.object(serve, "load_roots", lambda: list(roots)),
                        mock.patch.object(serve, "roots_listed", lambda: [str(r) for r in roots]),
                        mock.patch.object(serve, "home_lists", lambda: {})]
        for p in self.patches:
            p.start()
        self.idx = indexdb.IndexDB(self.tmp.home)

    def tearDown(self) -> None:
        self.idx.close()
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def stage1(self, ix: serve.Indexer) -> tuple[int, int]:
        """(summaries made, folders listed) by one sweep and its stage 1."""
        with mock.patch.object(serve, "summary_of", wraps=serve.summary_of) as made, \
                mock.patch.object(serve.os, "scandir", wraps=os.scandir) as listed:
            ix.sweep()
            while ix.queue:
                batch, ix.queue = ix.queue[:25], ix.queue[25:]
                ix.summarize(batch)
        return made.call_count, listed.call_count

    def test_only_what_changed_is_read_and_rows_survive(self) -> None:
        ix = serve.Indexer(self.idx)
        made, listed = self.stage1(ix)
        self.assertEqual(made, 9, "the first sweep reads every doc")
        self.assertGreaterEqual(listed, 2)
        self.assertEqual(self.stage1(ix), (0, 0), "an unchanged home summarizes and lists nothing")
        # a restart: a new indexer over the same file reads no doc again (the folders are listed once)
        serve._dirs.clear()
        again = indexdb.IndexDB(self.tmp.home)
        self.addCleanup(again.close)
        self.assertEqual(self.stage1(serve.Indexer(again))[0], 0)
        doc = self.docs / "acme-orders.bluedoc.json"
        data = json.loads(doc.read_text(encoding="utf-8"))
        data["title"] = "Acme orders, edited"
        write_doc(doc, data)
        old = time.time() - 3000
        os.utime(doc, (old, old))
        self.assertEqual(self.stage1(ix), (1, 0), "a doc edited: that doc only, no folder")
        self.assertEqual(self.idx.row(str(doc))["summary"]["docTitle"], "Acme orders, edited")
        shutil.copy(self.docs / "sub" / "acme-sub.bluedoc.json", self.docs / "sub" / "acme-sub2.bluedoc.json")
        for p in (self.docs / "sub" / "acme-sub2.bluedoc.json", self.docs / "sub"):
            os.utime(p, (old, old))
        self.assertEqual(self.stage1(ix), (1, 1), "a doc added: that folder and that doc")
        (self.docs / "sub" / "acme-sub2.bluedoc.json").unlink()
        os.utime(self.docs / "sub", (old - 100, old - 100))   # another stamp than the listing's
        self.stage1(ix)
        self.assertIsNone(self.idx.row(str(self.docs / "sub" / "acme-sub2.bluedoc.json")), "a deleted doc's row goes")
        # other code: every row is read again in the background
        with mock.patch.object(serve, "CODE_HASH", "other"):
            self.assertEqual(self.stage1(ix)[0], 9)

    def test_stage_1_runs_no_git_and_opens_no_screen_file(self) -> None:
        opened: list[str] = []
        real_open = io.open

        def spy(file, *a, **kw):
            opened.append(str(file))
            return real_open(file, *a, **kw)

        def no_process(*a, **kw):
            raise AssertionError(f"stage 1 ran a process: {a[:1]}")
        with mock.patch.object(builtins, "open", spy), mock.patch.object(io, "open", spy), \
                mock.patch.object(subprocess, "run", no_process), mock.patch.object(subprocess, "Popen", no_process), \
                mock.patch.object(serve.subprocess, "run", no_process):
            for p in sorted(self.docs.glob("*.bluedoc.json")):
                serve.summary_of(p)
        reads = [f for f in opened if not f.startswith(str(serve.HERE.parent))]
        self.assertTrue(reads)
        self.assertEqual([f for f in reads if not re.search(r"\.bluedoc(\.history)?\.json$|\.diffcache\.json$", f)], [],
                         "stage 1 read a screen, capture or layer file")


if __name__ == "__main__":
    unittest.main()
