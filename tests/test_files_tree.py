"""A plan's files block as a tree (1.0.39), on acme-saved-carts-plan: a nested path sits under its folders, a folder
holding only one folder sharing its row (`services/orders-api/`), and a folder's row folds its subtree (a jump to the
file opens it again); a row's step chip jumps to its step; clicking a row, not its chip, shows its whole why wrapped
under the name, which a phone shows only then; and a compare view (?diff=) marks a changed file and puts a removed
one's ghost in its folder, drawn again when it went with the file.

Browser tests: BLUEDOC_BROWSER_TESTS=1 with Chrome (BLUEDOC_CHROME names it when it isn't in a usual place)."""
from __future__ import annotations

import json
import time
import unittest

from test_page_state import CHROME, ChromePage

REPO_PATH = "services/orders-api/src/carts/savedCartRepo.ts"
REPO_WHY = "Reads and writes saved carts; enforces the 20-cart limit."


def row(path: str) -> str:
    return f"document.querySelector('.bp-ft .bp-frow[data-path=' + {json.dumps(json.dumps(path))} + ']')"


# a row's folders, outermost first: [data-dir, the folder row's text]
FOLDERS = ("(r => { const out = []; for (let d = r.parentElement.closest('.bp-fdir'); d; d = d.parentElement.closest('.bp-fdir'))"
           " out.unshift([d.dataset.dir, d.querySelector(':scope > .bp-fdir-b').textContent]); return out; })")
SRC = "document.querySelector('.bp-fdir[data-dir=\"services/orders-api/src\"] > .bp-fdir-b')"


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class FilesTree(ChromePage):
    def test_a_nested_path_sits_under_its_folded_folders(self) -> None:
        t = self.open(self.server.url_for(self.plan))
        r = row(REPO_PATH)
        self.assertEqual(t.ev(f"{FOLDERS}({r})"), [["services/orders-api", "services/orders-api/"], ["services/orders-api/src", "src/"],
                                                   ["services/orders-api/src/carts", "carts/"]])
        self.assertEqual(t.ev(f"getComputedStyle({r}).getPropertyValue('--d').trim()"), "3")
        self.assertEqual(t.ev("document.querySelectorAll('.bp-ft .bp-files, .bp-files .bp-frow').length"), 0, "the attachment chips' class")
        # a folder's row folds its subtree; a jump to the file (a step's file chip) opens it again
        t.ev(f"{SRC}.click()")
        self.assertEqual(t.ev(f"[{SRC}.getAttribute('aria-expanded'), {r}.checkVisibility()]"), ["false", False])
        t.ev(f"document.querySelector('.bp-fchip[data-path=\"{REPO_PATH}\"]').click()")
        self.assertEqual(t.ev(f"[{SRC}.getAttribute('aria-expanded'), {r}.checkVisibility()]"), ["true", True])
        self.assertEqual(self.browser.errors, [])

    def test_a_rows_step_chip_jumps_to_its_step(self) -> None:
        t = self.open(self.server.url_for(self.plan))
        chip, step = f"{row(REPO_PATH)}.querySelector('.bp-fstep')", "document.querySelector('.bp-step[data-step=\"repo\"]')"
        self.assertEqual(t.ev(f"{chip}.textContent"), "Step 2")
        self.assertFalse(t.ev(f"{step}.classList.contains('open')"))
        t.ev(f"{chip}.click()")
        t.wait_for(f"{step}.classList.contains('open') && (r => r.top >= 0 && r.bottom <= innerHeight)({step}.getBoundingClientRect())")
        self.assertFalse(t.ev(f"{row(REPO_PATH)}.classList.contains('open')"), "the chip doesn't open the row")
        self.assertEqual(self.browser.errors, [])

    def test_clicking_a_row_shows_its_whole_why(self) -> None:
        t = self.open(self.server.url_for(self.plan))
        r = row(REPO_PATH)
        hit, why, nm = f"{r}.querySelector('.bp-fhit')", f"{r}.querySelector('.bp-fwhy')", f"{r}.querySelector('.nm')"
        self.assertEqual(t.ev(f"{hit}.title"), REPO_WHY, "hovering shows the why whole")
        self.assertEqual(t.ev(f"[{why}.textContent, (w => w.top < {nm}.getBoundingClientRect().bottom)({why}.getBoundingClientRect())]"), [REPO_WHY, True], "on the name's line")
        t.ev(f"{hit}.click()")
        self.assertEqual(t.ev(f"[{r}.classList.contains('open'), {hit}.getAttribute('aria-expanded'), {why}.getBoundingClientRect().top > {nm}.getBoundingClientRect().bottom - 2]"),
                         [True, "true", True], "wrapped under the name")
        t.ev(f"{hit}.focus(); {hit}.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', bubbles: true }}))")
        self.assertEqual(t.ev(f"[{r}.classList.contains('open'), {hit}.getAttribute('aria-expanded')]"), [False, "false"], "Enter closes it")
        # a phone: no why on the row's line until it is open
        self.browser.call("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 800, "deviceScaleFactor": 2, "mobile": True}, t.session)
        time.sleep(0.5)
        self.assertFalse(t.ev(f"{why}.checkVisibility()"))
        t.ev(f"{hit}.click()")
        self.assertTrue(t.ev(f"{why}.checkVisibility() && {why}.getBoundingClientRect().top > {nm}.getBoundingClientRect().bottom - 2"))
        self.assertEqual(t.ev(f"(c => c.right <= innerWidth && c.right > innerWidth - 40)({r}.querySelector('.bp-fstep').getBoundingClientRect())"), True,
                         "the chip at the right edge")
        self.assertEqual(self.browser.errors, [])

    def test_a_compare_view_marks_a_changed_file_and_puts_a_removed_ones_ghost_in_its_folder(self) -> None:
        # rev 2: infra/cron's only file goes (so infra/flags/ would fold into one row) and server.ts's why changes
        for args in (("file:files/0/infra/cron/orders-api.yaml", "--delete", "--change", "The sweeper runs in the app."),
                     ("file:files/0/services/orders-api/src/server.ts", "--set", "why=Registers the new routes and the sweeper.", "--no-bump")):
            r = self.tmp.run("build.py", "patch", self.plan, *args)
            self.assertEqual(r.returncode, 0, r.stderr)
        url = self.server.url_for(self.plan)
        t = self.open(url)
        self.assertEqual(t.ev("document.querySelectorAll('.bp-fdir[data-dir=\"infra/flags\"] > .bp-fdir-b')[0].textContent"), "infra/flags/")
        t.go(f"{self.base}{url}?diff=1")
        t.wait_for("!!document.querySelector('.bp-ft .bd-ghost')")
        self.assertTrue(t.ev(f"{row('services/orders-api/src/server.ts')}.classList.contains('bd-chg-mod')"))
        ghost = "document.querySelector('.bp-ft .bd-ghost')"
        self.assertEqual(t.ev(f"[{ghost}.querySelector('.nm').textContent, {ghost}.hasAttribute('data-path'), !!{ghost}.querySelector('.bd-chg-tag.del'), !!{ghost}.querySelector('.bp-fstep')]"),
                         ["orders-api.yaml", False, True, False])
        self.assertEqual(t.ev(f"{FOLDERS}({ghost})"), [["infra", "infra/"], ["infra/cron", "cron/"]])
        self.assertEqual(t.ev("document.querySelector('.bp-fdir[data-dir=\"infra/flags\"] > .bp-fdir-b').textContent"), "flags/")
        self.assertEqual(t.ev(f"getComputedStyle({ghost}).getPropertyValue('--d').trim()"), "2")
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
