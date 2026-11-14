"""The home page's JSON: GET /__bluedoc/index.json and /__bluedoc/search-text, kept between requests.

index.json lists every doc without its search text, search-text has that text by doc URL; both answer with an ETag
and 304 to a matching If-None-Match (Cache-Control: no-cache, so the browser keeps them and revalidates), ?root= one
folder's only. What they say follows every change: a doc edited, added, deleted or renamed, a subfolder made or
removed, a folder added or removed through Settings, a registered folder gone (listed as missing) and back, and the
reader's ticks, archive and approval, which live in state.db. In process, an unchanged home is answered without
summarizing a doc or listing a folder again, and a change reads only the folder or doc it touched."""
from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from _support import Server, TempHome

import serve   # on sys.path through _support

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
        self.etag = ""

    def tearDown(self) -> None:
        self.server.stop()
        self.tmp.cleanup()

    def fetch(self, path: str, etag: str = "") -> tuple[int, dict, bytes]:
        return self.server.exchange("GET", path, headers={"If-None-Match": etag} if etag else None)

    def version(self, path: str, etag: str = "") -> int:
        """The HTTP version of the answer's status line (11: HTTP/1.1)."""
        c = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        try:
            c.request("GET", path, headers={"Host": self.server.host, **({"If-None-Match": etag} if etag else {})})
            r = c.getresponse()
            r.read()
            return r.version
        finally:
            c.close()

    def index(self, query: str = "", moved: bool = True) -> dict:
        """index.json as {roots: {slug: {path: doc}}, missing: [path]}; moved: asserts the ETag moved since the last call."""
        status, head, body = self.fetch("/__bluedoc/index.json" + query)
        self.assertEqual(status, 200, body[:200])
        if moved:
            self.assertNotEqual(head["etag"], self.etag, "the body changed but the ETag didn't")
        self.etag = head["etag"]
        got = json.loads(body)
        return {"roots": {r["slug"]: {d["path"]: d for d in r["docs"]} for r in got["roots"]},
                "missing": [m["path"] for m in got["missing"]]}

    def texts(self) -> dict:
        status, _, body = self.fetch("/__bluedoc/search-text")
        self.assertEqual(status, 200)
        return json.loads(body)["docs"]

    def test_etag_and_304(self) -> None:
        status, head, body = self.fetch("/__bluedoc/index.json")
        self.assertEqual(status, 200)
        self.assertEqual((head["cache-control"], head["connection"]), ("no-cache", "close"))
        self.assertEqual(self.version("/__bluedoc/index.json"), 11, "Chromium revalidates an ETag of HTTP/1.1 only")
        etag = head["etag"]
        self.assertTrue(re.fullmatch(r'"[0-9a-f]{32}"', etag), etag)
        docs = [d for r in json.loads(body)["roots"] for d in r["docs"]]
        self.assertTrue(docs and all("text" not in d for d in docs), "index.json carries no search text")
        for sent in (etag, f"W/{etag}", f'"nope", {etag}', "*"):
            with self.subTest(sent=sent):
                status, head, again = self.fetch("/__bluedoc/index.json", sent)
                self.assertEqual((status, again, head["etag"], head["cache-control"]), (304, b"", etag, "no-cache"))
        self.assertEqual(self.version("/__bluedoc/index.json", etag), 11)
        self.assertEqual(self.fetch("/__bluedoc/index.json", '"nope"')[:3:2], (200, body))
        # the key is part of the body (unlocked): a request with it is another body, another ETag
        status, head, keyed = self.server.exchange("GET", "/__bluedoc/index.json", headers={"X-Bluedoc": "1", "If-None-Match": etag})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(keyed)["unlocked"])
        self.assertNotEqual(head["etag"], etag)
        # search-text: each doc's text by its URL, with its own ETag and 304
        status, head, raw = self.fetch("/__bluedoc/search-text")
        self.assertEqual((status, head["cache-control"]), (200, "no-cache"))
        texts = json.loads(raw)["docs"]
        self.assertLessEqual(set(texts), {d["url"] for d in docs})
        self.assertIn(self.url, texts)
        title = json.loads(self.doc.read_text(encoding="utf-8"))["title"]
        self.assertIn(title, texts[self.url])
        self.assertEqual(self.fetch("/__bluedoc/search-text", head["etag"])[0], 304)
        # ?root=: one folder's only, for both
        other = self.tmp.dir / "acme-fit"
        other.mkdir()
        shutil.copy(self.docs / "acme-fit-deck.bluedoc.json", other / "acme-fit-deck.bluedoc.json")
        self.assertEqual(self.tmp.run("serve.py", "add", other).returncode, 0)
        self.assertEqual(set(self.index("?root=acme-fit")["roots"]), {"acme-fit"})
        status, _, raw = self.fetch("/__bluedoc/search-text?root=acme-fit")
        self.assertEqual(list(json.loads(raw)["docs"]), ["/acme-fit/acme-fit-deck.bluedoc.json"])

    def test_doc_changes_show(self) -> None:
        listed = self.index()["roots"][self.slug]
        self.assertIn(self.doc.name, listed)
        # edited in place: its title and search text follow, twice in a row
        doc = json.loads(self.doc.read_text(encoding="utf-8"))
        for title in ("Acme orders, edited", "Acme orders, edited again"):
            doc["title"] = title
            write_doc(self.doc, doc)
            self.assertEqual(self.index()["roots"][self.slug][self.doc.name]["docTitle"], title)
            self.assertIn(title, self.texts()[self.url])
        # added, in a new subfolder too
        added = self.docs / "acme-orders-copy.bluedoc.json"
        shutil.copy(self.doc, added)
        (self.docs / "later").mkdir()
        shutil.copy(self.plan, self.docs / "later" / "acme-later-plan.bluedoc.json")
        listed = self.index()["roots"][self.slug]
        self.assertIn(added.name, listed)
        self.assertIn("later/acme-later-plan.bluedoc.json", listed)
        # renamed: the old path goes, the new one comes, its text under the new URL
        renamed = self.docs / "acme-orders-renamed.bluedoc.json"
        added.rename(renamed)
        listed = self.index()["roots"][self.slug]
        self.assertNotIn(added.name, listed)
        self.assertIn(renamed.name, listed)
        texts = self.texts()
        self.assertIn(f"/{self.slug}/{renamed.name}", texts)
        self.assertNotIn(f"/{self.slug}/{added.name}", texts)
        # deleted, and a subfolder removed with its doc
        renamed.unlink()
        shutil.rmtree(self.docs / "later")
        listed = self.index()["roots"][self.slug]
        self.assertNotIn(renamed.name, listed)
        self.assertNotIn("later/acme-later-plan.bluedoc.json", listed)
        self.assertIn(self.doc.name, listed)

    def test_folders_added_removed_and_missing(self) -> None:
        other = self.tmp.dir / "acme-fit"
        other.mkdir()
        shutil.copy(self.docs / "acme-fit-deck.bluedoc.json", other / "acme-fit-deck.bluedoc.json")
        self.assertEqual(self.index()["missing"], [])
        status, raw = self.server.req("POST", "/__bluedoc/folders", json.dumps({"add": str(other)}).encode(), JSON)
        self.assertEqual(status, 200, raw)
        got = self.index()
        self.assertEqual(list(got["roots"]["acme-fit"]), ["acme-fit-deck.bluedoc.json"])
        # gone: listed as missing, its docs no longer; back: listed again with its docs
        moved = self.tmp.dir / "acme-fit-away"
        other.rename(moved)
        got = self.index()
        self.assertNotIn("acme-fit", got["roots"])
        self.assertEqual(got["missing"], [str(other)])
        self.assertNotIn("/acme-fit/acme-fit-deck.bluedoc.json", self.texts())
        moved.rename(other)
        got = self.index()
        self.assertEqual((list(got["roots"]["acme-fit"]), got["missing"]), (["acme-fit-deck.bluedoc.json"], []))
        status, raw = self.server.req("POST", "/__bluedoc/folders", json.dumps({"remove": str(other)}).encode(), JSON)
        self.assertEqual(status, 200, raw)
        self.assertEqual(set(self.index()["roots"]), {self.slug})

    def test_reader_state_shows(self) -> None:
        """Ticks, archive and approval are in state.db, not the doc: index.json follows them all the same."""
        own = {**JSON, "Origin": f"http://{self.server.host}"}

        def put(url: str, ops: list) -> None:
            status, raw = self.server.req("PUT", "/__bluedoc/state", json.dumps({"path": url, "import": False, "ops": ops}).encode(), own)
            self.assertEqual(status, 200, raw)

        def entry(path: Path, moved: bool = True) -> dict:
            return self.index(moved=moved)["roots"][self.slug][path.name]

        self.assertEqual(entry(self.doc)["state"], {})
        doc = json.loads(self.doc.read_text(encoding="utf-8"))
        cl = next(b for s in doc["sections"] for b in s.get("blocks") or [] if b.get("type") == "checklist")
        item = f"{cl['id']}:{cl['items'][0]['id']}"
        put(self.url, [[item, "1"]])
        self.assertEqual(entry(self.doc)["state"], {item: "1"})
        rev = str(doc["meta"]["rev"])
        put(self.url, [["__archived", json.dumps({"at": "2026-11-01T10:00:00Z", "rev": rev})]])
        self.assertEqual(entry(self.doc)["archived"], "2026-11-01T10:00:00Z")
        put(self.url, [["__archived", None]])
        self.assertIsNone(entry(self.doc)["archived"])
        self.assertNotIn("approval", entry(self.plan, moved=False))
        html = self.server.req("GET", self.plan_url)[1].decode()
        seed = json.loads(re.search(r'<script type="application/json" id="bp-state">(.*?)</script>', html, re.S).group(1))
        plan_rev = str(json.loads(self.plan.read_text(encoding="utf-8"))["meta"]["rev"])
        body = {"path": self.plan_url, "rev": plan_rev, "docHash": seed["docHash"], "decision": "approved", "answers": [],
                "annotations": [], "at": "2026-01-01T00:00:00Z", "markdown": "# Plan approved: Acme\n"}
        status, raw = self.server.req("POST", "/__bluedoc/approve", json.dumps(body).encode(), JSON)
        self.assertEqual(status, 200, raw)
        self.assertEqual(entry(self.plan)["approval"]["rev"], plan_rev)


class CachedWalk(unittest.TestCase):
    """In process: what an unchanged home and a change cost, counted in summaries made and folders listed."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.docs = self.tmp.copy_examples()
        (self.docs / "sub").mkdir()
        shutil.copy(self.docs / "acme-orders.bluedoc.json", self.docs / "sub" / "acme-sub.bluedoc.json")
        old = time.time() - 3600   # past serve.RACY_NS: a fresh mtime is never trusted
        for d, _, files in os.walk(self.docs):
            for f in files:
                os.utime(Path(d, f), (old, old))
            os.utime(d, (old, old))
        for cache in (serve._dirs, serve._entries, serve._bodies):
            cache.clear()
        roots = [self.docs]
        self.patches = [mock.patch.object(serve, "DB", None), mock.patch.object(serve, "load_roots", lambda: list(roots)),
                        mock.patch.object(serve, "roots_listed", lambda: [str(r) for r in roots]),
                        mock.patch.object(serve, "home_lists", lambda: {})]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def count(self) -> tuple[int, int, dict]:
        """(summaries made, folders listed, index.json) for one request."""
        with mock.patch.object(serve, "summarize", wraps=serve.summarize) as summarize, \
                mock.patch.object(serve.os, "scandir", wraps=os.scandir) as scandir:
            body, _ = serve.home_json("index")
        docs = {d["path"]: d for r in json.loads(body)["roots"] for d in r["docs"]}
        return summarize.call_count, scandir.call_count, docs

    def test_only_what_changed_is_read(self) -> None:
        made, listed, docs = self.count()
        self.assertEqual(made, len(docs), "the first request reads every doc")
        self.assertGreaterEqual(listed, 2, "and every folder")
        self.assertEqual(self.count()[:2], (0, 0), "an unchanged home summarizes and lists nothing")
        # a doc edited: that doc only, no folder
        doc = self.docs / "acme-orders.bluedoc.json"
        data = json.loads(doc.read_text(encoding="utf-8"))
        data["title"] = "Acme orders, edited"
        write_doc(doc, data)
        made, listed, docs = self.count()
        self.assertEqual((made, listed, docs[doc.name]["docTitle"]), (1, 0, "Acme orders, edited"))
        old = time.time() - 3000
        os.utime(doc, (old, old))
        self.assertEqual(self.count()[:2], (1, 0), "a doc whose mtime moved is read again")
        self.assertEqual(self.count()[:2], (0, 0))
        # a doc added to the subfolder: that folder only
        shutil.copy(self.docs / "sub" / "acme-sub.bluedoc.json", self.docs / "sub" / "acme-sub2.bluedoc.json")
        for p in (self.docs / "sub" / "acme-sub2.bluedoc.json", self.docs / "sub"):
            os.utime(p, (old, old))
        made, listed, docs = self.count()
        self.assertEqual((made, listed), (1, 1))
        self.assertIn("sub/acme-sub2.bluedoc.json", docs)
        self.assertEqual(self.count()[:2], (0, 0))


if __name__ == "__main__":
    unittest.main()
