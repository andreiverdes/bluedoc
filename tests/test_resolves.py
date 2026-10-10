"""A revision's `resolves`: the reader's comments it addresses, by id (res/*).

The build takes it only as a list of short id strings; `patch --resolves` rewrites it on a bump and appends with
--no-bump, and the history keeps each revision's list (res/build). In a real browser the reply Markdown names each
comment's id, and a reload after a patch that lists one resolves that open comment as the agent's; a pending one, an
unknown id, and a comment the reader reopened stay as they were until a newer revision lists it again (res/page)."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from _support import Server, TempHome, load_json
from test_page_state import CHROME, Browser, Tab, until


class ResolvesInTheBuild(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.plan = self.tmp.copy_examples() / "acme-saved-carts-plan.bluedoc.json"

    def check(self, resolves) -> tuple[int, str]:
        doc = load_json(self.plan)
        doc["resolves"] = resolves
        path = self.plan.with_name("acme-check.bluedoc.json")
        path.write_text(json.dumps(doc), encoding="utf-8")
        r = self.tmp.run("build.py", path, "--check")
        return r.returncode, r.stdout + r.stderr

    def test_resolves_must_be_a_list_of_short_ids(self) -> None:
        for bad in ("c1", ["c1", 2], ["has space"], ["x" * 41], [""]):
            with self.subTest(resolves=bad):
                code, out = self.check(bad)
                self.assertEqual(code, 1, out)
                self.assertIn("doc.resolves", out)
        code, out = self.check(["cmg2k3x1abcd", "c7f3"])
        self.assertEqual(code, 0, out)
        self.assertNotIn("doc.resolves", out)

    def test_patch_rewrites_on_a_bump_appends_without_and_the_history_keeps_each(self) -> None:
        def patch(*extra: str) -> None:
            r = self.tmp.run("build.py", "patch", self.plan, "tldr", "--set", "tldr=Acme saves carts per account.", *extra)
            self.assertEqual(r.returncode, 0, r.stderr)

        patch("--change", "Acme: say where carts live.", "--resolves", "(c1)", "--resolves", "`c2`")
        self.assertEqual(load_json(self.plan)["resolves"], ["c1", "c2"])
        patch("--no-bump", "--resolves", "c3", "--resolves", "c1")
        self.assertEqual(load_json(self.plan)["resolves"], ["c1", "c2", "c3"])
        patch("--change", "Acme: nothing a comment asked for.")
        self.assertNotIn("resolves", load_json(self.plan))
        patch("--change", "Acme: the second fix.", "--resolves", "c4")
        heads = {r["rev"]: r["head"] for r in load_json(self.plan.with_name("acme-saved-carts-plan.bluedoc.history.json"))["revs"]}
        self.assertEqual({rev: h.get("resolves") for rev, h in heads.items()}, {"1": None, "2": ["c1", "c2", "c3"], "3": None, "4": ["c4"]})


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class ResolvesOnThePage(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = Path(tempfile.mkdtemp(prefix="bluedoc-chrome-"))
        cls.browser = Browser(cls.profile)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        shutil.rmtree(cls.profile, ignore_errors=True)

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        docs = self.tmp.copy_examples("w/docs")
        self.plan = docs / "acme-saved-carts-plan.bluedoc.json"
        self.assertEqual(self.tmp.run("serve.py", "add", docs).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.url = self.server.url_for(self.plan)
        self.browser.errors.clear()

    def stored(self, cid: str) -> dict:
        status, raw = self.server.req("GET", f"/__bluedoc/state?path={quote(self.url)}", headers={"X-Bluedoc": "1"})
        return json.loads(json.loads(raw)["state"].get(f"__ann:{cid}") or "{}") if status == 200 else {}

    def patch(self, *resolves: str) -> str:
        r = self.tmp.run("build.py", "patch", self.plan, "tldr", "--set", "tldr=Acme saves carts per account.",
                         "--change", "Acme: say where carts live.", *[x for c in resolves for x in ("--resolves", c)])
        self.assertEqual(r.returncode, 0, r.stderr)
        return load_json(self.plan)["meta"]["rev"]

    def test_a_listed_open_comment_resolves_once_per_revision(self) -> None:
        status, raw = self.server.req("POST", "/__bluedoc/unlock", b"{}", {"Content-Type": "application/json", "X-Bluedoc": "1"})
        self.assertEqual(status, 200, raw)
        t = Tab(self.browser)
        t.go(f"http://{self.server.host}{self.url}?key={json.loads(raw)['token']}")
        pin = t.ev("BP.annotate({type: 'pin', key: 'tldr', note: 'Acme: say where saved carts live.'}).id")
        gen = t.ev("BP.annotate({type: 'general', note: 'Acme: shorter steps.'}).id")
        # Request changes → Send
        send = "[...document.querySelectorAll('.bd-chgs[open] .bp-btn.primary')].find(b => b.textContent.trim() === 'Send' && !b.hidden && !b.disabled)"
        t.ev("document.querySelector('.bd-key.go').click()")
        t.wait_for(f"!!{send}")
        t.ev(f"{send}.click()")
        t.wait_for("BP.annotations().filter(a => a.status === 'open').length === 2")
        r = self.tmp.run("serve.py", "reply", self.plan)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"`tldr` ({pin})", r.stdout)
        self.assertIn(f"- ({gen}) Acme: shorter steps.", r.stdout)

        late = t.ev("BP.annotate({type: 'pin', key: 'header', note: 'Acme: not sent yet.'}).id")
        rev = self.patch(pin, late, "cnosuchcomment")
        t.go(f"http://{self.server.host}{self.url}")
        status = lambda: {a["id"]: a for a in t.ev("BP.annotations()")}
        got = status()
        self.assertEqual((got[pin]["status"], got[pin].get("resolvedBy"), got[pin].get("resolvedRev")), ("resolved", "agent", rev))
        self.assertTrue(got[pin].get("resolvedAt"))
        self.assertEqual(got[gen]["status"], "open", "a comment the revision doesn't list was resolved")
        self.assertEqual(got[late]["status"], "pending", "a pending comment was resolved")
        self.assertEqual(until(lambda: self.stored(pin).get("status")), "resolved", "the agent's resolution wasn't saved")
        t.ev("document.querySelector('[role=radio][data-f=\"all\"]').click()")
        card = f"document.querySelector('li[data-id=\"{pin}\"]')"
        self.assertEqual(t.wait_for(f"{card}?.querySelector('.sago')?.textContent"), f"Resolved by the agent in rev {rev}")

        # the reader reopens it: the same revision doesn't resolve it again, a newer one that lists it does
        t.ev(f"{card}.querySelector('button[aria-label=\"Reopen\"]').click()")
        self.assertEqual(until(lambda: self.stored(pin).get("status") == "open" and "open"), "open")
        t.go(f"http://{self.server.host}{self.url}")
        self.assertEqual(status()[pin]["status"], "open", "a reopened comment was resolved again by the same revision")
        rev2 = self.patch(pin)
        t.go(f"http://{self.server.host}{self.url}")
        self.assertEqual((status()[pin]["status"], status()[pin].get("resolvedRev")), ("resolved", rev2))
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
