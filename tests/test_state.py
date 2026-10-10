"""Reader state and replies in state.db: `serve.py run` on a free port with a temp BLUEDOC_HOME.

The state routes refuse a request without X-Bluedoc, from another Origin or Host (403) and a path outside the
registered folders (404). A PUT and GET round trip; state and queued replies survive a restart and `wait` takes a
reply once; an import adds only missing keys; the seed is embedded as inert JSON; an approval counts only for the
doc the page showed (its rev and docHash) and only while the doc is unchanged; reply files of earlier versions are
imported once and left in place, and no reply files are written."""
from __future__ import annotations

import json
import re
import shutil
import stat
import unittest
from urllib.parse import quote

from _support import Server, TempHome

JSON = {"Content-Type": "application/json", "X-Bluedoc": "1"}


class State(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.docs = self.tmp.copy_examples()
        self.doc = self.docs / "acme-orders.bluedoc.json"
        self.plan = self.docs / "acme-saved-carts-plan.bluedoc.json"
        self.assertEqual(self.tmp.run("serve.py", "add", self.docs).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.req = self.server.req
        self.url, self.plan_url = self.server.url_for(self.doc), self.server.url_for(self.plan)
        self.own = f"http://{self.server.host}"
        doc = json.loads(self.doc.read_text(encoding="utf-8"))
        cl = next(b for s in doc["sections"] for b in s.get("blocks") or [] if b.get("type") == "checklist")
        self.item = f"{cl['id']}:{cl['items'][0]['id']}"

    def tearDown(self) -> None:
        self.server.stop()
        self.tmp.cleanup()

    def put(self, ops, path: str | None = None, imported: bool = False, headers: dict | None = None) -> tuple[int, dict]:
        body = json.dumps({"path": path or self.url, "import": imported, "ops": ops}).encode()
        status, raw = self.req("PUT", "/__bluedoc/state", body, headers if headers is not None else {**JSON, "Origin": self.own})
        return status, json.loads(raw) if raw else {}

    def get(self, since: int | None = None) -> tuple[int, dict]:
        q = f"/__bluedoc/state?path={quote(self.url)}" + ("" if since is None else f"&since={since}")
        status, raw = self.req("GET", q, headers={"X-Bluedoc": "1"})
        return status, json.loads(raw) if raw else {}

    def wait(self, doc, timeout: int = 0) -> tuple[int, dict]:
        status, raw = self.req("GET", f"/__bluedoc/wait?doc={quote(str(doc))}&kind=any&timeout={timeout}", headers={"X-Bluedoc": "1"})
        return status, json.loads(raw) if raw else {}

    def test_guards(self) -> None:
        body = json.dumps({"path": self.url, "ops": [[self.item, "1"]]}).encode()
        for name, method, headers in (("PUT, no header", "PUT", {"Content-Type": "application/json"}),
                                      ("PUT, foreign origin", "PUT", {**JSON, "Origin": "http://evil.com"}),
                                      ("PUT, null origin", "PUT", {**JSON, "Origin": "null"}),
                                      ("PUT, foreign host", "PUT", {**JSON, "Host": f"evil.com:{self.server.port}"}),
                                      ("GET, no header", "GET", {}),
                                      ("GET, foreign host", "GET", {"X-Bluedoc": "1", "Host": f"evil.com:{self.server.port}"})):
            with self.subTest(name):
                path = "/__bluedoc/state" + ("" if method == "PUT" else f"?path={quote(self.url)}")
                self.assertEqual(self.req(method, path, body if method == "PUT" else None, headers)[0], 403)
        self.assertEqual(self.get()[1]["state"], {}, "a refused PUT wrote state")
        slug = self.url.split("/")[1]
        for path in (f"/{slug}/nope.bluedoc.json", f"/{slug}/../secret.bluedoc.json", f"/{slug}/media", "/elsewhere/acme-orders.bluedoc.json"):
            with self.subTest(path=path):
                self.assertEqual(self.put([[self.item, "1"]], path=path)[0], 404)
        for name, ops in (("bad key", [["Rollout:Canary", "1"]]), ("page-only key", [["__outbox", "[]"]]),
                          ("number value", [[self.item, 1]]), ("not a pair", [[self.item]]),
                          ("value over 64 KB", [[self.item, "x" * (64 * 1024 + 1)]]), ("too many ops", [[self.item, "1"]] * 2001)):
            with self.subTest(name):
                self.assertEqual(self.put(ops)[0], 400)
        # the length alone decides: the server answers before reading a body it won't take
        status = self.req("PUT", "/__bluedoc/state", b"{}", {**JSON, "Origin": self.own, "Content-Length": str(1024 * 1024 + 1)})[0]
        self.assertEqual(status, 413)
        self.assertEqual(self.put([[self.item, "1"]])[0], 200)

    def test_round_trip(self) -> None:
        self.assertEqual(self.get(), (200, {"version": 0, "state": {}}))
        note = '<!-- Acme --><img src=x onerror=alert(1)></script><script>alert(2)</script>'
        self.assertEqual(self.put([[self.item, "1"], [self.item + ":note", note], ["__seen", "A"]]), (200, {"ok": True, "version": 1}))
        self.assertEqual(self.put([[self.item, "1"]])[1]["version"], 1, "an unchanged value bumped the version")
        self.assertEqual(self.get(since=1)[0], 204)
        self.assertEqual(self.put([["__seen", None]])[1]["version"], 2)
        status, got = self.get(since=1)
        self.assertEqual((status, got), (200, {"version": 2, "state": {self.item: "1", self.item + ":note": note}}))
        # the page carries the same state, as inert JSON that parses as served: the note can't close its script element
        seed = self.seed(self.url)
        self.assertEqual({"version": seed["version"], "state": seed["state"]}, got)
        self.assertNotIn("</script><script>alert(2)", self.req("GET", self.url)[1].decode())
        # the home page's card progress: tick and pick values only
        index = json.loads(self.req("GET", "/__bluedoc/index.json")[1])
        cards = {d["path"]: d for r in index["roots"] for d in r["docs"]}
        self.assertEqual(cards[self.doc.name]["state"], {self.item: "1"})
        self.assertEqual(cards[self.plan.name]["state"], {})
        self.assertEqual(stat.S_IMODE((self.tmp.home / "state.db").stat().st_mode), 0o600)

    def test_import_adds_only_missing_keys(self) -> None:
        self.put([[self.item, "1"]])
        status, got = self.put([[self.item, "0"], ["__message", "Acme note"], ["nochecklist:noitem", "1"],
                                [self.item + ":note", "kept"], ["__seen", None]], imported=True)
        self.assertEqual((status, got["version"]), (200, 2))
        self.assertEqual(self.get()[1]["state"], {self.item: "1", "__message": "Acme note", self.item + ":note": "kept"})
        self.assertEqual(self.put([[self.item, "0"], ["__message", "other"]], imported=True)[1]["version"], 2,
                         "an import of keys the server has bumped the version")

    def test_state_and_replies_survive_a_restart(self) -> None:
        self.put([[self.item, "1"]])
        answers = {"path": self.plan_url, "rev": "A", "items": [], "markdown": "# Answers: Acme\n\nShip it.\n"}
        status, raw = self.req("POST", "/__bluedoc/reply", json.dumps(answers).encode(), JSON)
        self.assertEqual(status, 200, raw)
        rid = json.loads(raw)["id"]
        self.server.stop()
        self.server.start()
        self.assertEqual(self.get()[1], {"version": 1, "state": {self.item: "1"}})
        status, got = self.wait(self.plan)
        self.assertEqual(status, 200)
        self.assertEqual((got["message"]["id"], got["message"]["kind"], got["message"]["markdown"]), (rid, "answers", answers["markdown"]))
        self.assertEqual(self.wait(self.plan)[0], 204, "wait returned the reply twice")
        self.assertEqual([p.name for p in self.docs.iterdir() if re.search(r"\.(reply|changes|approval)\.", p.name)], [])
        r = self.tmp.run("serve.py", "reply", str(rid))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith(f"--- bluedoc answers (reply {rid}, rev A, "), r.stdout)
        self.assertIn("Ship it.", r.stdout)
        r = self.tmp.run("serve.py", "reply", self.plan, "--json")
        self.assertEqual(json.loads(r.stdout)["markdown"], answers["markdown"])

    def seed(self, url: str) -> dict:
        html = self.req("GET", url)[1].decode()
        return json.loads(re.search(r'<script type="application/json" id="bp-state">(.*?)</script>', html, re.S).group(1))

    def test_approval_counts_while_the_doc_is_unchanged(self) -> None:
        ping = lambda: json.loads(self.req("GET", f"/__bluedoc/ping?path={quote(self.plan_url)}", headers={"X-Bluedoc": "1"})[1])  # noqa: E731
        card = lambda: next(d for r in json.loads(self.req("GET", "/__bluedoc/index.json")[1])["roots"] for d in r["docs"] if d["path"] == self.plan.name)  # noqa: E731
        approve = lambda body: self.req("POST", "/__bluedoc/approve", json.dumps(body).encode(), JSON)  # noqa: E731
        edit = lambda text: self.plan.write_text(json.dumps({**json.loads(self.plan.read_text(encoding="utf-8")), "subtitle": text}), encoding="utf-8")  # noqa: E731
        rev = json.loads(self.plan.read_text(encoding="utf-8"))["meta"]["rev"]
        body = {"path": self.plan_url, "rev": rev, "docHash": self.seed(self.plan_url)["docHash"], "decision": "approved",
                "answers": [], "annotations": [], "at": "2026-01-01T00:00:00Z", "markdown": "# Plan approved: Acme\n"}
        # edited in place between the page load and the click: the reader approved a doc they didn't see
        edit("Edited.")
        status, raw = approve(body)
        self.assertEqual((status, json.loads(raw).get("reload")), (409, True))
        self.assertIsNone(ping()["approval"])
        body["docHash"] = self.seed(self.plan_url)["docHash"]
        for name, over in (("another rev", {"rev": rev + "0"}), ("no docHash", {"docHash": None})):
            with self.subTest(name):
                self.assertEqual(approve({**body, **over})[0], 409)
        self.assertIsNone(ping()["approval"])
        self.assertEqual(approve(body)[0], 200)
        self.assertEqual(ping()["approval"], {"rev": rev, "at": "2026-01-01T00:00:00Z"})
        self.assertEqual(card()["approval"]["rev"], rev)
        # an edit after the approval resets it
        edit("Edited again.")
        self.assertIsNone(ping()["approval"])
        self.assertNotIn("approval", card())


class ReplyFileImport(unittest.TestCase):
    """A first start with a new state.db takes in the reply files of earlier versions and inbox.json's marks."""

    def test_import_once_and_leave_the_files(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        docs = tmp.copy_examples()
        plan, orders = docs / "acme-saved-carts-plan.bluedoc.json", docs / "acme-orders.bluedoc.json"
        files = {}
        for doc, suffix, md in ((plan, "changes", "# Change requests: Acme\n"), (orders, "reply", "# Answers: Acme orders\n")):
            stem = doc.name[: -len(".bluedoc.json")]
            j, m = doc.with_name(f"{stem}.{suffix}.json"), doc.with_name(f"{stem}.{suffix}.md")
            j.write_text(json.dumps({"rev": "A", "kind": suffix, "markdown": md}), encoding="utf-8")
            m.write_text(md, encoding="utf-8")
            files[suffix] = (j, m)
        # inbox.json says `wait` delivered the orders reply, not the plan's change request
        j = files["reply"][0]
        (tmp.home / "inbox.json").write_text(json.dumps({str(j): j.stat().st_mtime}), encoding="utf-8")
        self.assertEqual(tmp.run("serve.py", "add", docs).returncode, 0)
        server = Server(tmp)
        server.start()
        self.addCleanup(server.stop)
        wait = lambda doc: server.req("GET", f"/__bluedoc/wait?doc={quote(str(doc))}&kind=any&timeout=0", headers={"X-Bluedoc": "1"})  # noqa: E731
        status, raw = wait(plan)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["message"]["markdown"], "# Change requests: Acme\n")
        self.assertEqual(wait(orders)[0], 204, "a delivered reply was queued again")
        index = json.loads(server.req("GET", "/__bluedoc/index.json")[1])
        cards = {d["path"]: d for r in index["roots"] for d in r["docs"]}
        self.assertEqual(cards[plan.name]["changes"]["rev"], "A")
        self.assertEqual(cards[orders.name]["answers"]["rev"], "A")
        # a restart doesn't import the files again
        server.stop()
        server.start()
        self.assertEqual(wait(plan)[0], 204)
        self.assertTrue(all(f.is_file() for pair in files.values() for f in pair), "the import moved a reply file")
        shutil.rmtree(tmp.home / "chrome", ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
