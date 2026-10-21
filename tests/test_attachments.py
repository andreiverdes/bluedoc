"""Attachments: files the reader attaches to a comment, kept by the server and sent to the agent by their paths.

POST /__bluedoc/attach keeps the body as ~/.bluedoc/attachments/<doc id>/<8 hex>-<name>, the name stripped of folders
and characters that would break a path or a Markdown code span; it needs the key, a doc under a registered folder, a
name and at most 50 MB (route). DELETE removes only a file directly in that doc's folder (route). Reader state takes
`:files` and `__message-files` lists and thread messages of files alone, and refuses other shapes (state).

In Chrome: files attached to a decision's box are a draft: Save keeps them over a reload, Cancel deletes the copies it
added, a chip removed from a saved comment loses its copy on Save; Request changes moves them into the message, and the
reply Markdown lists each path under the comment (page/item). A pin's composer deletes its copies on Cancel (page/pin)."""
from __future__ import annotations

import json
import unittest
from urllib.parse import quote

from _support import Server, TempHome
from test_page_state import CHROME, ChromePage, Tab, until

PLAN = "acme-saved-carts-plan.bluedoc.json"


def attach_q(url: str, name: str) -> str:
    return f"/__bluedoc/attach?path={quote(url)}&name={quote(name)}"


class AttachRoute(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.docs = self.tmp.copy_examples()
        self.assertEqual(self.tmp.run("serve.py", "add", self.docs).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.server.stop)
        self.url = self.server.url_for(self.docs / PLAN)
        self.folder = self.tmp.home / "attachments" / "acme-saved-carts-plan"

    def post(self, name: str, body: bytes, headers: dict | None = None) -> tuple[int, dict]:
        status, raw = self.server.req("POST", attach_q(self.url, name), body, {"Content-Type": "application/octet-stream", "X-Bluedoc": "1", **(headers or {})})
        return status, json.loads(raw or b"{}")

    def delete(self, file: str, headers: dict | None = None) -> int:
        return self.server.req("DELETE", f"/__bluedoc/attach?path={quote(self.url)}&file={quote(file)}", None, {"X-Bluedoc": "1", **(headers or {})})[0]

    def test_a_file_is_kept_under_a_safe_name_and_deleted_only_from_its_folder(self) -> None:
        status, f = self.post("../../logs/crash`1`.log", b"boom")
        self.assertEqual(status, 200, f)
        kept = self.folder / f["path"].rsplit("/", 1)[-1]
        self.assertRegex(kept.name, r"^[0-9a-f]{8}-crash-1-\.log$")
        self.assertEqual([f["name"], f["size"], kept.read_bytes()], ["crash-1-.log", 4, b"boom"])
        # the same name twice: two copies
        self.assertNotEqual(self.post("../../logs/crash`1`.log", b"again")[1]["path"], f["path"])
        # a file outside the doc's folder stays, and so does one in it without the key
        outside = self.tmp.dir / "keep.txt"
        outside.write_text("x")
        self.assertEqual(self.delete(str(outside)), 404)
        self.assertEqual(self.delete(str(self.folder / ".." / ".." / ".." / "keep.txt")), 404)
        self.assertEqual(self.delete(f["path"], {"X-Bluedoc-Key": "nope"}), 403)
        self.assertTrue(outside.exists() and kept.exists())
        self.assertEqual(self.delete(f["path"]), 200)
        self.assertFalse(kept.exists())

    def test_refused_without_the_key_a_doc_a_name_or_room(self) -> None:
        self.assertEqual(self.post("a.txt", b"x", {"X-Bluedoc-Key": "nope"})[0], 403)
        status, raw = self.server.req("POST", attach_q("/nowhere/x.bluedoc.json", "a.txt"), b"x", {"X-Bluedoc": "1"})
        self.assertEqual(status, 404, raw)
        self.assertEqual(self.post("", b"x")[0], 400)
        status, raw = self.server.req("POST", attach_q(self.url, "big.bin"), None, {"X-Bluedoc": "1", "Content-Length": str(50 * 1024 * 1024 + 1)})
        self.assertEqual(status, 413, raw)
        self.assertFalse(self.folder.exists() and any(self.folder.iterdir()))

    def test_state_takes_files_of_the_right_shape(self) -> None:
        f = {"name": "a.png", "path": "/tmp/a.png", "size": 3}

        def put(key: str, value) -> int:
            body = json.dumps({"path": self.url, "import": False, "ops": [[key, json.dumps(value)]]}).encode()
            return self.server.req("PUT", "/__bluedoc/state", body, {"Content-Type": "application/json", "X-Bluedoc": "1"})[0]
        at = "2026-10-21T10:00:00Z"
        for key, value, want in (("decisions:retention:files", [f], 200), ("__message-files", [f], 200),
                                 ("decisions:retention:thread", [{"md": "", "rev": "1", "at": at, "files": [f]}], 200),
                                 ("decisions:retention:files", [{**f, "path": "relative/a.png"}], 400),
                                 ("decisions:retention:files", [f] * 11, 400),
                                 ("__message-files", [{**f, "size": "3"}], 400),
                                 ("decisions:retention:thread", [{"md": "", "rev": "1", "at": at}], 400),
                                 ("decisions:retention:thread", [{"md": "x", "rev": "1", "at": at, "files": []}], 400)):
            with self.subTest(key=key, value=value):
                self.assertEqual(put(key, value), want)


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class AttachPage(ChromePage):
    BOX = "document.querySelector('#item-decisions-retention > .bp-note')"

    def folder(self) -> list[str]:
        d = self.tmp.home / "attachments" / "acme-saved-carts-plan"
        return sorted(p.name.split("-", 1)[1] for p in d.iterdir()) if d.is_dir() else []

    def attach(self, tab: Tab, box: str, *names: str) -> None:
        """Picks files in box's Attach, as the file dialog would, and waits for their chips."""
        n = tab.ev(f"{box}.querySelectorAll('.bp-file').length")
        tab.ev(f"(b => {{ const dt = new DataTransfer(); for (const n of {json.dumps(names)}) dt.items.add(new File(['data of ' + n], n));"
               f" const i = b.querySelector('input[type=file]'); i.files = dt.files; i.dispatchEvent(new Event('change')); }})({box})")
        tab.wait_for(f"{box}.querySelectorAll('.bp-file').length === {n + len(names)} && !{box}.querySelector('.bp-files-up')")

    def chips(self, tab: Tab, box: str) -> list[str]:
        return tab.ev(f"[...{box}.querySelectorAll('.bp-file .t')].map(t => t.textContent)")

    def test_files_on_an_item_are_a_draft_until_saved_then_go_with_the_comment(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        box, save, cancel = self.BOX, f"{self.BOX}.querySelector('.acts .primary')", f"{self.BOX}.querySelector('.acts .ghost')"
        self.assertFalse(a.ev("!!document.querySelector('.bp-note .hint')"), "the old hint is gone")
        # Cancel deletes what it added
        self.attach(a, box, "draft.txt")
        self.assertEqual(self.folder(), ["draft.txt"])
        a.ev(f"{cancel}.click()")
        self.assertTrue(until(lambda: self.folder() == []), self.folder())
        self.assertEqual(self.chips(a, box), [])
        # files alone make a comment: Save keeps them over a reload
        self.attach(a, box, "reorders.csv", "cart.png")
        a.ev(f"{save}.click()")
        files = json.loads(until(lambda: (self.state(url) or {}).get("decisions:retention:files")))
        self.assertEqual([f["name"] for f in files], ["reorders.csv", "cart.png"])
        a.go(self.base + url)
        self.assertEqual(self.chips(a, box), ["reorders.csv", "cart.png"])
        # a saved chip removed: its copy stays until Save
        a.ev(f"{box}.querySelector('.bp-file .x').click()")
        self.assertEqual(self.folder(), ["cart.png", "reorders.csv"])
        a.ev(f"{save}.click()")
        self.assertTrue(until(lambda: self.folder() == ["cart.png"]), self.folder())
        # sent: the message carries the file, the box is empty, the reply lists its full path
        self.send_changes(a, "1 comment on items")
        msg = self.thread_files(a)
        self.assertEqual([f["name"] for f in msg], ["cart.png"])
        self.assertEqual(self.chips(a, box), [])
        self.assertEqual(a.ev("[...document.querySelectorAll('#item-decisions-retention .bp-msg .bp-file .t')].map(t => t.textContent)"), ["cart.png"])
        self.assertIn(f"  Files:\n  - `{msg[0]['path']}` (", self.reply(self.plan))
        self.assertTrue(msg[0]["path"].startswith(str(self.tmp.home / "attachments" / "acme-saved-carts-plan") + "/"))

    def thread_files(self, tab: Tab) -> list[dict]:
        return tab.ev("BP.thread('decisions/retention')[0].files")

    def test_a_pin_composer_deletes_its_copies_on_cancel(self) -> None:
        a = self.open(self.server.url_for(self.plan))
        a.ev("BP.setMode('point')")
        x, y = a.ev("(p => { p.scrollIntoView({block: 'center', behavior: 'instant'}); const r = p.getBoundingClientRect(); return [r.x + 30, r.y + 8]; })(document.querySelector('.bp-text p'))")
        for kind, buttons in (("mouseMoved", 0), ("mousePressed", 1), ("mouseReleased", 0)):
            self.browser.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "buttons": buttons, "clickCount": 1}, a.session)
        a.wait_for("!document.querySelector('.bd-cmp').hidden")
        self.attach(a, "document.querySelector('.bd-cmp')", "shot.png")
        self.assertEqual(self.folder(), ["shot.png"])
        a.ev("[...document.querySelectorAll('.bd-cmp .ft .bp-btn')].find(b => b.textContent === 'Cancel').click()")
        self.assertTrue(until(lambda: self.folder() == []), self.folder())


if __name__ == "__main__":
    unittest.main()
