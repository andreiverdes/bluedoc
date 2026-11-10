"""The home page's Settings (1.0.31): the gear at the sidebar's foot opens /settings with pushState (Back returns to the
docs), pressed there with no doc list current; at 390 px it sits in the drawer's foot. The page lists the folders, code
links, frameworks, the plan-mode hook's and patch-only edits' switches, Chrome and font folders, and the server, from GET
/__bluedoc/settings. A change saves at once (settings.json) and says so in the toast; a switch the environment sets is
locked and names its variable; a folder that isn't there shows the server's error under the field; the section list
marks the section scrolled to; a browser without the key sees the page read only with the unlock banner; Restart server
reloads the page once the server is back.

Browser tests: BLUEDOC_BROWSER_TESTS=1 with Chrome (BLUEDOC_CHROME names it when it isn't in a usual place)."""
from __future__ import annotations

import json
import shutil
import time
import unittest

from _support import EXAMPLES, Server, TempHome
from test_page_state import CHROME, ChromePage, Tab, until

GEAR = "document.querySelector('.bd-side [aria-label=Settings]')"
SWITCH = "document.querySelector('#agents button[role=switch]')"
PATCH_ONLY = "document.querySelector('#agents button[role=switch][aria-label=\"Patch-only edits\"]')"
NAV = "document.querySelector('.bd-st-nav [aria-current]')?.textContent"


def typed(selector: str, text: str) -> str:
    """JS that types text into a React-controlled input, as a reader's keys do."""
    return (f"(el => {{ Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, {json.dumps(text)});"
            f" el.dispatchEvent(new Event('input', {{bubbles: true}})); }})(document.querySelector({json.dumps(selector)}))")


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class HomeSettings(ChromePage):
    def setUp(self) -> None:
        # two folders of Acme example docs and a code link, in a home of the test's own
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.shop, self.fit = self.tmp.dir / "w" / "acme-shop", self.tmp.dir / "w" / "acme-fit"
        for folder, stems in ((self.shop, ("acme-orders", "acme-saved-carts-plan")), (self.fit, ("acme-status",))):
            (folder / "docs").mkdir(parents=True)
            for stem in stems:
                shutil.copy(EXAMPLES / f"{stem}.bluedoc.json", folder / "docs")
            self.assertEqual(self.tmp.run("serve.py", "add", folder / "docs").returncode, 0)
        (self.tmp.home / "repos.json").write_text(json.dumps({"acme-shop": str(self.shop)}), encoding="utf-8")
        self.browser.errors.clear()

    def start(self, **env: str) -> None:
        self.tmp.env.update(env)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.base = f"http://{self.server.host}"

    def home(self, width: int = 1440, height: int = 900, mobile: bool = False) -> Tab:
        """A tab on the home page through a ?key= link, so it may save."""
        status, raw = self.server.req("POST", "/__bluedoc/unlock", b"{}", {"Content-Type": "application/json", "X-Bluedoc": "1"})
        self.assertEqual(status, 200, raw)
        t = Tab(self.browser)
        self.browser.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": mobile}, t.session)
        self.browser.call("Page.navigate", {"url": f"{self.base}/?key={json.loads(raw)['token']}"}, t.session)
        t.wait_for("document.readyState === 'complete' && !!document.querySelector('.bd-fc')")
        return t

    def settings(self, **kw) -> Tab:
        t = self.home(**kw)
        t.ev(f"{GEAR}.click()")
        t.wait_for("location.pathname === '/settings' && !!document.querySelector('#server .bd-st-row')")
        return t

    def saved(self) -> dict:
        p = self.tmp.home / "settings.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}

    def test_the_gear_opens_settings_and_back_returns(self) -> None:
        self.start()
        t = self.home()
        self.assertEqual(t.ev(f"{GEAR}.closest('.bd-side-foot').querySelectorAll('button').length"), 2, "the gear beside the theme key")
        self.assertNotEqual(t.ev(f"{GEAR}.getAttribute('aria-pressed')"), "true")
        t.ev(f"{GEAR}.click()")
        t.wait_for("location.pathname === '/settings' && !!document.querySelector('.bd-st h1')")
        self.assertEqual(t.ev("document.title"), "Settings · bluedoc")
        self.assertEqual(t.ev(f"{GEAR}.getAttribute('aria-pressed')"), "true")
        self.assertEqual(t.ev("document.querySelectorAll('.bd-side [aria-current]').length"), 0, "a doc list is current on Settings")
        self.assertIsNone(t.ev("document.querySelector('.bd-hero')"))
        t.ev("history.back()")
        t.wait_for("location.pathname === '/' && !!document.querySelector('.bd-hero')")
        self.assertEqual(t.ev("document.querySelector('.bd-side [aria-current=page]')?.textContent"), "All docs3")
        self.assertNotEqual(t.ev(f"{GEAR}.getAttribute('aria-pressed')"), "true")
        # a doc list from Settings goes back to the docs, filtered
        t.ev("history.forward()")
        t.wait_for("location.pathname === '/settings'")
        t.ev("[...document.querySelectorAll('.bd-side [data-item-id^=\"d:\"]')].pop().click()")   # acme-fit's folder
        t.wait_for("location.pathname === '/' && !!document.querySelector('.bd-hero')")
        self.assertTrue(t.wait_for("new URLSearchParams(location.search).get('p')"))
        self.assertEqual(t.ev("document.querySelectorAll('.bd-cw').length"), 1, "acme-fit's one doc")
        self.assertEqual(self.browser.errors, [])

    def test_the_gear_sits_in_the_phone_drawer(self) -> None:
        self.start()
        t = self.home(390, 800, True)
        t.ev("document.querySelector('.bd-hero-bar button').click()")
        t.wait_for("!!document.querySelector('.bd-drawer [aria-label=Settings]')")
        t.ev("document.querySelector('.bd-drawer [aria-label=Settings]').click()")
        t.wait_for("location.pathname === '/settings' && !document.querySelector('.bd-drawer') && !!document.querySelector('#server .bd-st-row')")
        self.assertEqual(t.ev("getComputedStyle(document.querySelector('.bd-st-nav')).display"), "none", "the section list at 390 px")
        self.assertEqual(t.wait_for("(w => w === 390 && w)(document.documentElement.scrollWidth)", 3), 390, "the page is wider than the phone")
        self.assertEqual(self.browser.errors, [])

    def test_the_sections_show_this_home(self) -> None:
        self.start()
        t = self.settings()
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-st-nav a')].map(a => a.textContent)"),
                         ["Folders", "Code links", "Frameworks", "Agents", "Tools", "Server"])
        rows = t.ev("[...document.querySelectorAll('#folders .bd-st-row:not(.add)')].map(r => [r.querySelector('b').textContent, r.querySelector('.bd-st-l span').textContent])")
        self.assertEqual([(p.split("/w/")[-1], n) for p, n in rows], [("acme-shop/docs", "2 docs"), ("acme-fit/docs", "1 doc")])
        self.assertEqual(t.ev("[...document.querySelectorAll('#repos .bd-st-row b')].map(b => b.textContent)"), ["acme-shop"])
        self.assertEqual(t.ev("document.querySelector('#frameworks .bd-st-row.note code').textContent"), "serve.py add-framework NAME [PATH|URL]")
        self.assertEqual(t.ev(f"{SWITCH}.getAttribute('aria-checked')"), "true")
        self.assertEqual(t.ev(f"{SWITCH}.disabled"), False)
        self.assertEqual(t.ev("[...document.querySelectorAll('#server .bd-st-row b')].map(b => b.textContent)"), ["Version", "Address", "Data folder", "Running since"])
        self.assertIn(f"http://127.0.0.1:{self.server.port}", t.ev("document.querySelector('#server').textContent"))
        self.assertNotRegex(t.ev("document.querySelector('.bd-st').textContent"), r"\bTheme\b|Doc width|\bPen\b", "browser preferences on the page")
        self.assertEqual(t.ev("[...document.querySelectorAll('#agents .bd-st-row b')].map(b => b.textContent)"),
                         ["Plan mode opens plans here", "Patch-only edits"])
        self.assertEqual(t.ev(f"{PATCH_ONLY}.closest('.bd-st-row').querySelector('.bd-st-l span').textContent"),
                         "Agents change a built doc with build.py patch; hand edits are refused.")
        self.assertEqual(t.ev(f"{PATCH_ONLY}.closest('.bd-st-row').querySelector('.bd-st-l code').textContent"), "build.py patch")
        self.assertEqual((t.ev(f"{PATCH_ONLY}.getAttribute('aria-checked')"), t.ev(f"{PATCH_ONLY}.disabled")), ("true", False))
        self.assertEqual(self.browser.errors, [])

    def test_the_plan_mode_switch_saves_at_once(self) -> None:
        self.start()
        t = self.settings()
        t.ev(f"{SWITCH}.click()")
        self.assertEqual(t.wait_for("document.querySelector('.bd-toast')?.textContent"), "Saved · Plan mode off")
        self.assertIs(until(lambda: self.saved().get("planHook") is False), True, self.saved())
        self.assertEqual(t.wait_for(f"{SWITCH}.getAttribute('aria-checked') === 'false' && 'off'"), "off")
        t.ev(f"{SWITCH}.click()")
        self.assertEqual(t.wait_for("(s => s === 'Saved · Plan mode on' && s)(document.querySelector('.bd-toast')?.textContent)"), "Saved · Plan mode on")
        self.assertIs(self.saved().get("planHook"), True)
        self.assertEqual(self.browser.errors, [])

    def test_the_patch_only_switch_saves_at_once(self) -> None:
        self.start()
        t = self.settings()
        t.ev(f"{PATCH_ONLY}.click()")
        self.assertEqual(t.wait_for("document.querySelector('.bd-toast')?.textContent"), "Saved · Patch-only edits off")
        self.assertIs(until(lambda: self.saved().get("patchOnly") is False), True, self.saved())
        self.assertEqual(t.wait_for(f"{PATCH_ONLY}.getAttribute('aria-checked') === 'false' && 'off'"), "off")
        self.assertEqual(t.ev(f"{SWITCH}.getAttribute('aria-checked')"), "true", "plan mode stays on")
        t.ev(f"{PATCH_ONLY}.click()")
        self.assertEqual(t.wait_for("(s => s === 'Saved · Patch-only edits on' && s)(document.querySelector('.bd-toast')?.textContent)"),
                         "Saved · Patch-only edits on")
        self.assertIs(self.saved().get("patchOnly"), True)
        self.assertEqual(self.browser.errors, [])

    def test_the_environment_locks_the_switch(self) -> None:
        self.start(BLUEDOC_PLAN_HOOK="0")
        t = self.settings()
        self.assertEqual(t.ev(f"{SWITCH}.getAttribute('aria-checked')"), "false")
        self.assertEqual(t.ev(f"{SWITCH}.disabled"), True)
        self.assertEqual(t.ev("document.querySelector('#agents .bd-st-env').textContent"), "BLUEDOC_PLAN_HOOK=0")
        self.assertEqual(t.ev("document.querySelector('#agents .bd-st-l span').textContent"),
                         "Off: set by BLUEDOC_PLAN_HOOK=0 in the environment, which wins over this page.")
        self.assertEqual(self.saved(), {})
        self.assertEqual(self.browser.errors, [])

    def test_the_environment_locks_the_patch_only_switch(self) -> None:
        self.start(BLUEDOC_PATCH_ONLY="0")
        t = self.settings()
        row = f"{PATCH_ONLY}.closest('.bd-st-row')"
        self.assertEqual((t.ev(f"{PATCH_ONLY}.getAttribute('aria-checked')"), t.ev(f"{PATCH_ONLY}.disabled")), ("false", True))
        self.assertEqual(t.ev(f"{row}.querySelector('.bd-st-env').textContent"), "BLUEDOC_PATCH_ONLY=0")
        self.assertEqual(t.ev(f"{row}.querySelector('.bd-st-l span').textContent"),
                         "Off: set by BLUEDOC_PATCH_ONLY=0 in the environment, which wins over this page.")
        self.assertEqual(t.ev(f"{SWITCH}.disabled"), False, "plan mode stays unlocked")
        self.assertEqual(self.saved(), {})
        self.assertEqual(self.browser.errors, [])

    def test_adding_a_missing_folder_shows_the_error(self) -> None:
        self.start()
        t = self.settings()
        missing = str(self.tmp.dir / "w" / "acme-blog")
        t.ev(typed("[aria-label='Folder to add']", missing))
        t.wait_for("!document.querySelector('#folders form button[type=submit]').disabled")
        t.ev("document.querySelector('#folders form button[type=submit]').click()")
        self.assertEqual(t.wait_for("document.querySelector('#folders .bd-st-err')?.textContent"), f"No folder at {missing}")
        self.assertEqual(t.ev("document.querySelector(\"[aria-label='Folder to add']\").getAttribute('aria-invalid')"), "true")
        self.assertEqual(t.ev("document.querySelectorAll('#folders .bd-st-row:not(.add)').length"), 2)
        # a folder that is there: added, listed, said in the toast, and the field clears
        site = self.tmp.dir / "w" / "acme-site"
        site.mkdir()
        t.ev(typed("[aria-label='Folder to add']", str(site)))
        t.wait_for("!document.querySelector('#folders .bd-st-err')")
        t.ev("document.querySelector('#folders form button[type=submit]').click()")
        self.assertEqual(t.wait_for("document.querySelector('.bd-toast')?.textContent"), "Folder added")
        self.assertEqual(t.wait_for("document.querySelectorAll('#folders .bd-st-row:not(.add)').length === 3 && document.querySelector(\"[aria-label='Folder to add']\").value === '' && 'ok'"), "ok")
        self.assertEqual(self.browser.errors, [])

    def test_the_section_list_marks_the_section_scrolled_to(self) -> None:
        self.start()
        t = self.settings(width=1280, height=640)
        self.assertEqual(t.ev(NAV), "Folders")
        t.ev("document.getElementById('frameworks').scrollIntoView()")
        self.assertEqual(t.wait_for(f"({NAV}) === 'Frameworks' && 'Frameworks'"), "Frameworks")
        t.ev("scrollTo(0, document.documentElement.scrollHeight)")
        self.assertEqual(t.wait_for(f"({NAV}) === 'Server' && 'Server'"), "Server", "the page's end marks the last section")
        # a pick scrolls to its section and stays marked
        t.ev("[...document.querySelectorAll('.bd-st-nav a')].find(a => a.textContent === 'Code links').click()")
        self.assertEqual(t.ev(NAV), "Code links")
        t.wait_for("Math.abs(document.getElementById('repos').getBoundingClientRect().top - 24) < 2")
        time.sleep(0.3)
        self.assertEqual(t.ev(NAV), "Code links")
        self.assertEqual(self.browser.errors, [])

    def test_a_browser_without_the_key_reads_only(self) -> None:
        self.start()
        t = Tab(self.browser)
        self.browser.call("Page.navigate", {"url": f"{self.base}/settings"}, t.session)
        t.wait_for("!!document.querySelector('#server .bd-st-row') && !!document.querySelector('.bd-lock')")
        self.assertEqual(t.ev(f"{SWITCH}.disabled"), True)
        self.assertEqual(t.ev("document.querySelector(\"[aria-label='Folder to add']\").disabled"), True)
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-st button')].filter(b => !b.disabled).map(b => b.textContent)"), [])
        self.assertEqual(self.browser.errors, [])

    def test_restart_reloads_the_page_when_the_server_is_back(self) -> None:
        self.start()
        t = self.settings()
        started = json.loads(self.server.req("GET", "/__bluedoc/ping")[1])["started"]
        t.ev("window.__before = true; [...document.querySelectorAll('#server button')].find(b => b.textContent === 'Restart server').click()")
        self.assertEqual(t.wait_for("document.querySelector('#server .bd-st-wait')?.textContent || (!window.__before && 'reloaded')"),
                         "Restarting… this page reloads when the server is back.")
        t.wait_for("!window.__before && location.pathname === '/settings' && !!document.querySelector('#server .bd-st-row')", 20)
        self.assertNotEqual(json.loads(self.server.req("GET", "/__bluedoc/ping")[1])["started"], started)
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
