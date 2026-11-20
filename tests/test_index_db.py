"""index.db (indexdb.py) over the Acme examples, in process: pages and offsets, every facet against the counts the
home page made itself from the full list, search against a plain port of the home's match() over every doc (no FTS),
status_of against the home's statusOf cases, and a rebuild after garbage bytes and after a schema bump."""
from __future__ import annotations

import json
import os
import shutil
import time
import unittest
from unittest import mock

from _support import TempHome

import indexdb   # on sys.path through _support
import serve


class IndexDBTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = TempHome()
        cls.docs = cls.tmp.copy_examples()
        (cls.docs / "plans").mkdir()
        shutil.copy(cls.docs / "acme-saved-carts-plan.bluedoc.json", cls.docs / "plans" / "acme-q4-plan.bluedoc.json")
        now = time.time()
        for i, p in enumerate(sorted(cls.docs.rglob("*.bluedoc.json"))):   # distinct ages: one a few days old, one 40
            age = [3600, 86400 * 3, 86400 * 12, 86400 * 40][i % 4] + i
            os.utime(p, (now - age, now - age))
        roots = [cls.docs]
        cls.patches = [mock.patch.object(serve, "DB", None), mock.patch.object(serve, "load_roots", lambda: list(roots)),
                       mock.patch.object(serve, "roots_listed", lambda: [str(r) for r in roots]),
                       mock.patch.object(serve, "home_lists", lambda: {})]
        for p in cls.patches:
            p.start()
        serve._dirs.clear()
        cls.idx = indexdb.IndexDB(cls.tmp.home)
        ix = serve.Indexer(cls.idx)
        ix.sweep()
        ix.summarize(ix.queue)
        cls.roots = serve.roots_info({})
        # one doc archived for its rev
        plan = str(cls.docs / "acme-saved-carts-plan.bluedoc.json")
        row = cls.idx.row(plan)
        cls.idx.put_overlay(plan, {**row["overlay"], "archived": now}, "1:0")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.idx.close()
        for p in cls.patches:
            p.stop()
        cls.tmp.cleanup()

    def query(self, **kw) -> indexdb.Query:
        return indexdb.Query(self.roots, p=self.roots[0]["slug"], **kw)

    def every(self) -> list[dict]:
        """Every row, archived ones too, as the old full list had them."""
        q = self.query()
        return (self.idx.page(q, "rows", 0, 200)["docs"]
                + self.idx.page(self.query(s="archived"), "rows", 0, 200)["docs"])

    def test_pages_and_offsets(self) -> None:
        q = self.query()
        whole = self.idx.page(q, "rows", 0, 200)
        self.assertEqual(whole["total"], 8, "nine docs, one archived")
        mtimes = [d["mtime"] for d in whole["docs"]]
        self.assertEqual(mtimes, sorted(mtimes, reverse=True))
        seen, offset = [], 0
        while offset is not None:
            s = self.idx.page(q, "rows", offset, 3)
            seen += [d["url"] for d in s["docs"]]
            offset = s["next"]
        self.assertEqual(seen, [d["url"] for d in whole["docs"]])
        self.assertEqual(len(self.idx.page(q, "rows", 0, 10_000)["docs"]), 8, "limit is capped, not refused")
        self.assertEqual(len(self.idx.page(q, "rows", 0, 0)["docs"]), 1, "at least one row")

    def test_facets_match_the_home_s_own_counts(self) -> None:
        """types over the folder (archived apart), statuses over the typed set, archived matches for the hint,
        groups by the browser's day, roots' counts and the hero: as home.html counted them over the full list."""
        rows = self.every()
        live = [d for d in rows if not d["st"]["archived"]]
        for t in (None, "plan", "review"):
            for s in (None, "needs", "awaiting", "archived"):
                with self.subTest(t=t, s=s):
                    got = self.idx.page(self.query(t=t or "", s=s or "", tz=-120), "rows", 0, 200)
                    show_arch = s == "archived"
                    want_types = {}
                    for d in rows:
                        if d["st"]["archived"] == show_arch:
                            want_types[d["type"]] = want_types.get(d["type"], 0) + 1
                    self.assertEqual(got["facets"]["types"], want_types)
                    typed = [d for d in rows if not t or d["type"] == t]

                    def is_(d, k):
                        return d["st"]["archived"] if k == "archived" else not d["st"]["archived"] and bool(d["st"][k])
                    want_st = {k: n for k in indexdb.STATUSES if (n := sum(is_(d, k) for d in typed))}
                    self.assertEqual(got["facets"]["statuses"], want_st)
                    shown = [d for d in typed if (is_(d, s) if s else not d["st"]["archived"])]
                    self.assertEqual(sorted(d["url"] for d in got["docs"]), sorted(d["url"] for d in shown))
                    arch = 0 if show_arch else sum(d["st"]["archived"] and (not s or d["st"][s]) for d in typed)
                    self.assertEqual(got["facets"]["archived"], arch)
                    t0 = indexdb.Query([], tz=-120).today()
                    want_g = {g: sum(indexdb.group_of(d["mtime"], t0) == g for d in shown) for g in indexdb.GROUPS}
                    self.assertEqual(got["groups"], want_g)
        got = self.idx.page(self.query(), "rows", 0, 1)
        self.assertEqual(got["roots"][0]["count"], len(live))
        self.assertEqual(got["roots"][0]["last"], max(d["mtime"] for d in rows))
        self.assertEqual(got["facets"]["dirs"], [{"dir": "plans", "n": 1}])
        self.assertEqual((got["hero"]["docs"], got["hero"]["decisionsOpen"], got["hero"]["waiting"]),
                         (len(live), sum(d["st"]["dec"] - d["st"]["decided"] for d in live), 0))

    def test_search_finds_what_the_home_s_match_found(self) -> None:
        """Every term must match a field (substrings, any case); scores weigh title 10, path 6, subtitle 4, sections 3,
        kind/org/type 2, body 1; equal scores newest first. The reference scans every doc's fields without FTS."""
        name = self.roots[0]["name"]
        ref_rows = []
        for d in self.every():
            if d["st"]["archived"]:
                continue
            info = serve.summary_of(self.docs / d["path"])
            sr = info["search"]
            fields = [sr["title"], f"{name}/{d['path']}", sr["subtitle"], sr["sections"], sr["meta"], sr["body"]]
            ref_rows.append((d, [f.lower() for f in fields]))

        def reference(q: str) -> list[str]:
            terms = q.lower().split()
            hits = []
            for d, fields in ref_rows:
                score = 0
                for t in terms:
                    hit = sum(w for f, w in zip(fields, indexdb.WEIGHTS) if t in f)
                    if not hit:
                        break
                    score += hit
                else:
                    hits.append((-score, -d["mtime"], d["url"]))
            return [u for *_, u in sorted(hits)]
        for q in ("rate limit", "serve.py", "ok", "carts", "acme", "snake_case", "Kafka worker", "x", "tierFor", "zzqq"):
            with self.subTest(q=q):
                got = self.idx.page(self.query(q=q), "rows", 0, 200)
                self.assertEqual([d["url"] for d in got["docs"]], reference(q))
                self.assertEqual(got["total"], len(reference(q)))

    def test_status_of_ports_the_home_s_status(self) -> None:
        s = {"approvable": True, "rev": "2", "mtime": 100.0, "stepsOpen": 0,
             "items": [["c", "a", 1, "", ["x", "y"], "Pick one"], ["c", "b", 0, "0", None, "Tick it"]]}
        st = indexdb.status_of(s, None, {})
        self.assertEqual((st["col"], st["needs"], st["awaiting"], st["dec"], st["decided"], st["steps"], st["done"]),
                         ("needs", True, True, 1, 0, 1, 0))
        self.assertEqual([x["dec"] for x in st["open"]], [True, False], "decisions first")
        picked = indexdb.status_of(s, 0, {"state": {"c:a": "=x|", "c:b": "1"}})
        self.assertEqual((picked["decided"], picked["done"], picked["needs"], picked["awaiting"]), (1, 1, True, True))
        self.assertEqual(indexdb.status_of(s, 0, {"state": {"c:a": "=z|"}})["decided"], 0, "a pick of no option")
        self.assertEqual(indexdb.status_of(s, 0, {"state": {"c:b": "1x"}})["done"], 0, "a tick of another author value")
        self.assertEqual(indexdb.status_of(s, 3, {})["col"], "errors")
        sent = indexdb.status_of(s, 0, {"changes": {"at": 200.0, "rev": "2"}})
        self.assertEqual((sent["col"], sent["waiting"], sent["changesSent"], sent["needs"]), ("waiting", True, True, False))
        ap = indexdb.status_of(s, 0, {"approval": {"rev": "2", "carried": False}, "state": {"c:b": "1"}})
        self.assertEqual((ap["col"], ap["approved"], ap["decided"], ap["allDone"]), ("done", True, 1, True))
        old = indexdb.status_of(s, 0, {"approval": {"rev": "1", "carried": False}})
        self.assertEqual((old["approved"], old["staleRev"], old["awaiting"]), (False, "1", True))
        self.assertTrue(indexdb.status_of(s, 0, {"approval": {"rev": "1", "carried": True}})["approved"])
        self.assertFalse(indexdb.status_of(s, 0, {"approval": {"rev": "2"}, "archiveLater": "2", "state": {"c:b": "1"}})["allDone"])
        arch = indexdb.status_of(s, 0, {"archived": 5.0})
        self.assertTrue(arch["archived"])


class Rebuild(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)

    def test_garbage_bytes_are_rebuilt(self) -> None:
        path = self.tmp.home / f"index-{indexdb.SCHEMA_VERSION}.db"
        path.write_bytes(os.urandom(8192))
        idx = indexdb.IndexDB(self.tmp.home)
        self.addCleanup(idx.close)
        self.assertEqual(idx.counts("x"), {"rows": 0, "summarized": 0, "validated": 0})
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")

    def test_a_schema_bump_builds_its_own_file_and_drops_the_old_one_once_free(self) -> None:
        old = indexdb.IndexDB(self.tmp.home)
        old.close()
        held = [True]
        with mock.patch.object(indexdb, "SCHEMA_VERSION", 2):
            new = indexdb.IndexDB(self.tmp.home)
            self.addCleanup(new.close)
            self.assertEqual(new.path.name, "index-2.db")
            new.drop_other_schemas(lambda lock: not held[0])
            self.assertTrue((self.tmp.home / "index-1.db").exists(), "a file another server holds stays")
            held[0] = False
            new.drop_other_schemas(lambda lock: not held[0])
            self.assertFalse((self.tmp.home / "index-1.db").exists())
            self.assertTrue(new.path.exists())

    def test_a_put_validation_for_an_older_key_is_dropped(self) -> None:
        idx = indexdb.IndexDB(self.tmp.home)
        self.addCleanup(idx.close)
        summary = {"docTitle": "A", "type": "other", "mtime": 1.0, "items": [], "card": {}}
        row = {"path": "/x/a.bluedoc.json", "root": "/x", "rel": "a.bluedoc.json", "dir": "", "file_key": "k1",
               "summary": summary, "search": {"title": "A"}, "edits": [1], "overlay": {}, "reader_ver": None}
        idx.put_summary([row], "c")
        idx.put_summary([{**row, "file_key": "k2"}], "c")
        self.assertFalse(idx.put_validation("/x/a.bluedoc.json", "k1", "c", 2, "bad", None))
        self.assertIsNone(idx.row("/x/a.bluedoc.json")["errors"])
        self.assertTrue(idx.put_validation("/x/a.bluedoc.json", "k2", "c", 2, "bad", None))
        self.assertEqual(idx.row("/x/a.bluedoc.json")["errors"], 2)
        idx.put_summary([{**row, "file_key": "k2"}], "c")
        self.assertEqual(idx.row("/x/a.bluedoc.json")["errors"], 2, "an unchanged file keeps its validation")
        idx.put_summary([{**row, "file_key": "k3"}], "c")
        self.assertIsNone(idx.row("/x/a.bluedoc.json")["errors"], "a changed file isn't validated yet")

    def test_a_save_during_stage_1_is_never_undone(self) -> None:
        """Stage 1 reads a doc's overlay, a save (an archive) lands and refreshes the row, then stage 1 writes its
        summary: the row keeps the save's newer overlay and the path comes back to be refreshed; an older overlay
        never replaces a newer one either (two saves answered out of order)."""
        idx = indexdb.IndexDB(self.tmp.home)
        self.addCleanup(idx.close)
        summary = {"docTitle": "A", "type": "other", "mtime": 1.0, "items": [], "card": {}}
        row = {"path": "/x/a.bluedoc.json", "root": "/x", "rel": "a.bluedoc.json", "dir": "", "file_key": "k1",
               "summary": summary, "search": {"title": "A"}, "edits": [1], "overlay": {"title": "A"}, "reader_ver": "0:0"}
        self.assertEqual(idx.put_summary([row], "c"), [])
        self.assertTrue(idx.put_overlay(row["path"], {"title": "A", "archived": 5.0}, "1:0"))
        self.assertEqual(idx.put_summary([{**row, "file_key": "k2"}], "c"), [row["path"]])
        self.assertEqual(idx.row(row["path"])["overlay"]["archived"], 5.0, "stage 1 undid the archive")
        self.assertTrue(idx.page(indexdb.Query([{"slug": "x", "path": "/x", "name": "x", "temp": False, "shown": True}], s="archived"),
                                 "rows", 0, 10)["docs"])
        self.assertFalse(idx.put_overlay(row["path"], {"title": "A"}, "0:0"), "an older overlay replaced a newer one")
        self.assertTrue(idx.put_overlay(row["path"], {"title": "A"}, "2:0"))
        self.assertIsNone(idx.row(row["path"])["overlay"].get("archived"))


if __name__ == "__main__":
    unittest.main()
