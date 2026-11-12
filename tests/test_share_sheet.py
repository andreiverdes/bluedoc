"""The share sheet (template.html openShare; design share-account, sheet D) and the Share key, against a stub of
/__bluedoc/share, /__bluedoc/unshare and the settings POST that sets a project's account (STUB, put in the page before
its script runs), so no gh runs and nothing reaches GitHub.

The key sits before Export (its icon alone under 900 px) and marks a shared doc with a dot in the accent, a doc newer
than its share in the warning colour, also on load. The sheet is a ticket over the dimmed page with the notice
(share.NOTICE) as its red bottom strip. A first share with two usable accounts lists them as radios (an unusable one
off with its fix, and how to add another), the project's account picked, the focus on Share as <login>, which posts
`as`; ↓ picks the next. With one usable account there is no picker and nothing goes as `as`. Shared: the link with
Copy link, which shows a tick and Copied for 1.5 s; Share as is a key whose menu sets the project's account at once.
The doc newer: Link shows rev N and Update to rev M posts the same gist. The gist on another account than the
project's: Update waits for Move or Keep, then posts the pick. Stop sharing deletes the gist on the second press.
Sharing off: the key dims, its tooltip says why, a press opens the popover with the fix, and once sharing works the
next press opens the sheet. Esc and a press outside close the sheet; an error stays in it; a phone fits it."""
from __future__ import annotations

import json
import unittest

from test_page_state import CHROME, ChromePage, Tab

import share

STATUS = "acme-status"
KEY, SHEET = "document.querySelector('.bd-bar-r .bd-shk')", "document.querySelector('dialog.bd-share')"
LINK = "https://bluedoc.ai/g/Zl8DoBqtTsiT7pgCtn11Bw"
OFF = {"reason": "gh, the GitHub CLI, isn't signed in to GitHub", "fix": "gh auth login -s gist"}

# The routes as the server answers them, on a view the test sets: GET (brief: share, rev, off), the share POST (409
# with the mismatch until `move` or `keep`; `as` sets the project's account; a new gist, or the same one updated to the
# view's rev), unshare, and the settings POST {sharing}. Every call is in __share.calls; __share.fail makes them 502.
STUB = r"""
window.__share = (() => {
  const S = { view: null, calls: [], fail: null, delay: 0, n: 0 };
  const real = window.fetch.bind(window);
  const answer = (j, status = 200) => new Promise(r => setTimeout(() => r(new Response(JSON.stringify(j), { status, headers: { 'Content-Type': 'application/json' } })), S.delay));
  const gist = user => { const id = (++S.n).toString(16).padStart(32, 'b');
    return { id, user, link: 'https://bluedoc.ai/g/New' + S.n, url: `https://gist.github.com/${user}/${id}`, rev: S.view.rev, at: new Date().toISOString() }; };
  window.fetch = (input, init = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href), m = (init.method || 'GET').toUpperCase(), p = url.pathname;
    const body = init.body ? JSON.parse(init.body) : null;
    if (!(p === '/__bluedoc/share' || p === '/__bluedoc/unshare' || (p === '/__bluedoc/settings' && body && body.sharing))) return real(input, init);
    S.calls.push({ m, p, brief: url.searchParams.get('brief'), body });
    if (S.fail) return answer({ error: S.fail }, 502);
    const v = S.view;
    if (m === 'GET') return answer(url.searchParams.get('brief') ? { share: v.share, rev: v.rev, off: v.off } : v);
    if (p === '/__bluedoc/settings') {
      v.account = { login: body.sharing.account, why: 'project' };
      v.mismatch = v.share && v.share.user !== body.sharing.account ? { gist: v.share.user, project: body.sharing.account } : null;
      return answer({ ok: true });
    }
    if (p === '/__bluedoc/unshare') { const removed = v.share; v.share = null; v.mismatch = null; return answer({ ok: true, removed }); }
    if (v.mismatch && !body.move && !body.keep) return answer({ error: 'Pick Move or Keep', mismatch: v.mismatch }, 409);
    if (body.as) v.account = { login: body.as, why: 'project' };
    if (!v.share || body.move) v.share = gist(v.account.login);
    else v.share = { ...v.share, rev: v.rev, at: new Date().toISOString() };
    v.mismatch = null;
    return answer(v);
  };
  return S;
})();
"""

ACME = {"login": "jlee-acme", "usable": True, "active": False, "fix": None}
JLEE = {"login": "jlee", "usable": True, "active": True, "fix": None}
OSS = {"login": "jlee-oss", "usable": False, "active": False, "fix": "gh auth refresh -s gist -u jlee-oss"}


def view(**kw) -> dict:
    """A doc of the acme-shop project at rev 2, three accounts signed in (two usable), jlee-acme the remote's owner."""
    v = {"share": None, "rev": "2", "contents": {"media": 1, "screens": 0},
         "project": {"slug": "acme-shop", "name": "acme-shop", "remote": "acme-corp/shop"},
         "accounts": [ACME, JLEE, OSS], "account": {"login": "jlee-acme", "why": "remote"}, "ask": True, "mismatch": None, "off": None}
    v.update(kw)
    return v


def gist(user: str = "jlee-acme", rev: str = "2") -> dict:
    return {"id": "659f3c1a" + "0" * 24, "user": user, "link": LINK, "url": f"https://gist.github.com/{user}/659f3c1a", "rev": rev,
            "at": "2026-11-09T10:00:00Z"}


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class ShareSheet(ChromePage):
    def page(self, v: dict, width: int = 1440, height: int = 900) -> Tab:
        """The status doc with the stub answering as `v`, the clipboard kept in __copied."""
        status, raw = self.server.req("POST", "/__bluedoc/unlock", b"{}", {"Content-Type": "application/json", "X-Bluedoc": "1"})
        self.assertEqual(status, 200, raw)
        t = Tab(self.browser)
        if width != 1440:
            self.browser.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 2, "mobile": width < 600}, t.session)
        self.browser.call("Page.enable", session=t.session)
        self.browser.call("Page.addScriptToEvaluateOnNewDocument", {"source": STUB + f"__share.view = {json.dumps(v)};"}, t.session)
        t.go(f"{self.base}{self.server.url_for(self.docs / f'{STATUS}.bluedoc.json')}?key={json.loads(raw)['token']}")
        t.ev("window.__copied = []; navigator.clipboard.writeText = s => { __copied.push(s); return Promise.resolve(); }; true")
        t.wait_for("__share.calls.some(c => c.brief)")
        return t

    def sheet(self, t: Tab) -> None:
        t.ev(f"{KEY}.click()")
        t.wait_for(f"(d => d && d.open && !!d.querySelector('.acts .det'))({SHEET})")

    def q(self, t: Tab, sel: str, prop: str = "textContent"):
        return t.ev(f"(e => e && e.{prop})({SHEET}.querySelector({json.dumps(sel)}))")

    def posts(self, t: Tab) -> list:
        return t.ev("__share.calls.filter(c => c.m === 'POST').map(c => [c.p, c.body])")

    def key(self, t: Tab, key: str, code: str = "", vk: int = 0) -> None:
        for kind in ("rawKeyDown", "keyUp"):
            self.browser.call("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": code or key, "windowsVirtualKeyCode": vk}, t.session)

    def click_at(self, t: Tab, x: float, y: float) -> None:
        for kind in ("mousePressed", "mouseReleased"):
            self.browser.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1}, t.session)

    def test_the_key_sits_before_export_and_marks_a_share(self) -> None:
        t = self.page(view())
        self.assertEqual(t.ev("[...document.querySelector('.bd-bar-r').children].filter(e => e.matches('.bd-shk, .bd-docx, .bd-docm')).map(e => e.className.split(' ').find(c => /^bd-(shk|docx|docm)$/.test(c)))"),
                         ["bd-shk", "bd-docx", "bd-docm"], "Share · Export · ⋯")
        self.assertEqual(t.ev(f"[{KEY}.textContent, {KEY}.hasAttribute('aria-disabled'), {KEY}.getAttribute('aria-label'), {KEY}.dataset.share || null]"),
                         ["Share", False, "Share", None])
        t = self.page(view(share=gist(rev="2")), 390, 800)
        self.assertEqual(t.ev(f"[...{KEY}.children].map(e => getComputedStyle(e).display)"), ["block", "none", "block"], "narrow: the icon and the dot")
        self.assertEqual(t.wait_for(f"{KEY}.dataset.share"), "shared")
        self.assertIn("Shared as a secret gist at rev 2", t.ev(f"{KEY}.title"))
        t = self.page(view(share=gist(rev="1")))
        self.assertEqual(t.wait_for(f"{KEY}.dataset.share"), "newer")
        warn = t.ev("(e => { e.style.color = 'var(--warn)'; document.body.append(e); const c = getComputedStyle(e).color; e.remove(); return c; })(document.createElement('i'))")
        self.assertEqual(t.ev(f"getComputedStyle({KEY}.querySelector('.dot')).backgroundColor"), warn)
        self.assertIn("the doc is at rev 2 now", t.ev(f"{KEY}.title"))
        self.assertEqual(self.browser.errors, [])

    def test_a_first_share_with_two_accounts_preselects_the_project_s_and_shares_as_it(self) -> None:
        t = self.page(view())
        self.sheet(t)
        self.assertEqual(self.q(t, ".eyb"), "Share a read-only link")
        self.assertIsNone(self.q(t, ".eyb .bdg"), "no state badge on a first share")
        self.assertEqual(self.q(t, ".tt"), "Acme shop status, week 41acme-shop · acme-corp/shop")
        self.assertEqual(t.ev(f"[...{SHEET}.querySelectorAll('.meta2 .bdg')].map(b => b.textContent)"), ["1 media", "0 screens"])
        rows = t.ev(f"[...{SHEET}.querySelectorAll('.accs .acc')].map(r => [r.querySelector('b').textContent, r.querySelector('.why').textContent, r.querySelector('input').checked, r.querySelector('input').disabled])")
        self.assertEqual(rows, [["jlee-acme", "matches acme-corp/shop, this repo's owner", True, False], ["jlee", "gh's active account", False, False],
                                ["jlee-oss", "no gist scope: gh auth refresh -s gist -u jlee-oss", False, True]])
        self.assertEqual(self.q(t, ".oth"), "Another account: gh auth login -s gist")
        self.assertEqual(self.q(t, ".go"), "Share as jlee-acme")
        self.assertTrue(t.ev(f"document.activeElement === {SHEET}.querySelector('.go')"), "the focus on the action")
        strip = f"{SHEET}.querySelector('.strip')"
        self.assertEqual(t.ev(f"[{strip}.querySelector('b').textContent, {strip}.textContent]"), [share.NOTICE_LEAD, share.NOTICE])
        risk = t.ev("(e => { e.style.color = 'var(--risk-fg)'; document.body.append(e); const c = getComputedStyle(e).color; e.remove(); return c; })(document.createElement('i'))")
        self.assertEqual(t.ev(f"getComputedStyle({strip}).color"), risk, "the notice in the risk red")
        self.assertEqual(self.posts(t), [], "nothing goes before Share")
        # ↓ on the picked radio picks the next account; the action says so
        t.ev(f"{SHEET}.querySelector('.accs input:checked').focus()")
        self.key(t, "ArrowDown", vk=40)
        t.wait_for(f"{SHEET}.querySelector('.go').textContent === 'Share as jlee'")
        t.ev(f"{SHEET}.querySelector('.accs input[value=\"jlee-acme\"]').click()")
        t.wait_for(f"{SHEET}.querySelector('.go').textContent === 'Share as jlee-acme'")
        t.ev(f"{SHEET}.querySelector('.go').click()")
        t.wait_for(f"!!{SHEET}.querySelector('.lnk input')")
        self.assertEqual(self.posts(t), [["/__bluedoc/share", {"path": t.ev("location.pathname"), "as": "jlee-acme"}]])
        link = self.q(t, ".lnk input", "title")
        self.assertEqual(self.q(t, ".lnk input", "value"), link.removeprefix("https://"), "the field shows the link without its scheme")
        self.assertEqual(t.ev("__copied"), [link], "the link is copied on sharing")
        self.assertIn("link is copied", self.toast(t, "shared"))
        self.assertEqual(self.q(t, ".cp"), "Copied")
        self.assertEqual([self.q(t, ".eyb > span"), self.q(t, ".eyb .bdg")], ["Shared link", "Up to date"])
        self.assertEqual(self.q(t, ".stl"), "Shared at rev 2 · just now · as jlee-acme")
        self.assertEqual(self.q(t, ".acb .acl b"), "jlee-acme", "Share as: the project's account")
        self.assertEqual(t.wait_for(f"{KEY}.dataset.share"), "shared")
        self.assertEqual(self.browser.errors, [])

    def test_a_first_share_as_another_account(self) -> None:
        t = self.page(view())
        self.sheet(t)
        t.ev(f"{SHEET}.querySelector('.accs input[value=\"jlee\"]').click()")
        t.wait_for(f"{SHEET}.querySelector('.go').textContent === 'Share as jlee'")
        t.ev(f"{SHEET}.querySelector('.go').click()")
        t.wait_for(f"!!{SHEET}.querySelector('.lnk input')")
        self.assertEqual(self.posts(t)[0][1]["as"], "jlee")
        self.assertEqual(self.q(t, ".stl"), "Shared at rev 2 · just now · as jlee")

    def test_one_usable_account_has_no_picker(self) -> None:
        t = self.page(view(accounts=[ACME, OSS], account={"login": "jlee-acme", "why": "only"}, ask=False))
        self.sheet(t)
        self.assertEqual(t.ev(f"[!!{SHEET}.querySelector('.accs'), !!{SHEET}.querySelector('.acb'), !!{SHEET}.querySelector('.oth')]"), [False, False, False])
        self.assertEqual(self.q(t, ".go"), "Share")
        t.ev(f"{SHEET}.querySelector('.go').click()")
        t.wait_for(f"!!{SHEET}.querySelector('.lnk input')")
        self.assertEqual(self.posts(t), [["/__bluedoc/share", {"path": t.ev("location.pathname")}]], "no `as` with one account")
        self.assertFalse(t.ev(f"!!{SHEET}.querySelector('.acb')"), "shared: no Share as key either")
        t.ev(f"{SHEET}.querySelector('.det summary').click()")
        self.assertEqual(self.q(t, "[data-r=account] dd > div"), "jlee-acme · the only account with the gist scope")

    def test_a_shared_doc_copies_its_link_and_changes_the_project_s_account(self) -> None:
        t = self.page(view(share=gist(), account={"login": "jlee-acme", "why": "project"}))
        self.sheet(t)
        self.assertEqual([self.q(t, ".eyb .bdg"), self.q(t, ".lnk input", "value"), self.q(t, ".cp"), self.q(t, ".cp", "className")],
                         ["Up to date", LINK.removeprefix("https://"), "Copy link", "cp pri"])
        self.assertIsNone(self.q(t, ".go"), "up to date: nothing to update")
        self.assertTrue(t.ev(f"document.activeElement === {SHEET}.querySelector('.cp')"))
        t.ev(f"{SHEET}.querySelector('.cp').click()")
        self.assertEqual([self.q(t, ".cp"), self.q(t, ".cp", "className")], ["Copied", "cp ok"])
        self.assertEqual(t.ev("__copied"), [LINK])
        t.wait_for(f"{SHEET}.querySelector('.cp').textContent === 'Copy link'", 3)
        # Details: the account, the gist (Open on GitHub), what's left out, the readers, Stop sharing
        t.ev(f"{SHEET}.querySelector('.det summary').click()")
        self.assertEqual(t.ev(f"[...{SHEET}.querySelectorAll('.dr dt')].map(e => e.textContent)"), ["Account", "Gist", "Left out", "Readers", "Stop sharing"])
        self.assertEqual(self.q(t, "[data-r=gist] dd > div"), "Secret gist 659f3c1a… on jlee-acmeOpen on GitHub")
        self.assertEqual(self.q(t, "[data-r=gist] a", "href"), "https://gist.github.com/jlee-acme/659f3c1a")
        self.assertEqual(self.q(t, "[data-r=left-out] dd > div"), "Earlier revisions and compare")
        # Share as: a menu of the accounts; a pick sets the project's account, and the gist on the old one asks Move or Keep
        t.ev(f"{SHEET}.querySelector('.acb').click()")
        menu = f"{SHEET}.querySelector('.bd-acm')"
        t.wait_for(f"!{menu}.hidden")
        self.assertEqual(t.ev(f"[...{menu}.querySelectorAll('[role=menuitemradio]')].map(r => [r.querySelector('b').textContent, r.querySelector('small').textContent, r.getAttribute('aria-checked'), r.getAttribute('aria-disabled')])"),
                         [["jlee-acme", "acme-shop's account", "true", None], ["jlee", "gh's active account", "false", None],
                          ["jlee-oss", "no gist scope: gh auth refresh -s gist -u jlee-oss", "false", "true"]])
        self.assertIn("Another account: gh auth login -s gist", t.ev(f"{menu}.textContent"))
        self.assertTrue(t.ev(f"document.activeElement === {menu}.querySelector('[aria-checked=true]')"), "the menu opens on the project's account")
        self.key(t, "Escape", vk=27)
        t.wait_for(f"{menu}.hidden && document.activeElement === {SHEET}.querySelector('.acb')")
        self.assertTrue(t.ev(f"{SHEET}.open"), "Esc in the menu closes the menu, not the sheet")
        self.key(t, "ArrowDown", vk=40)
        t.wait_for(f"!{menu}.hidden")
        t.ev(f"{menu}.querySelectorAll('[role=menuitemradio]')[2].click()")
        self.assertFalse(t.ev(f"{menu}.hidden"), "an unusable account isn't a pick")
        t.ev(f"{menu}.querySelectorAll('[role=menuitemradio]')[1].click()")
        t.wait_for(f"!!{SHEET}.querySelector('.tiles')")
        self.assertEqual(self.posts(t), [["/__bluedoc/settings", {"sharing": {"slug": "acme-shop", "account": "jlee"}}]])
        self.assertEqual(self.q(t, ".acb .acl b"), "jlee")
        self.assertEqual(self.q(t, ".cap.mt"), "This gist is on jlee-acme; acme-shop shares as jlee")
        self.assertEqual(self.browser.errors, [])

    def test_a_newer_doc_updates_the_same_link(self) -> None:
        t = self.page(view(share=gist(rev="1"), account={"login": "jlee-acme", "why": "project"}))
        self.sheet(t)
        self.assertEqual(self.q(t, ".eyb .bdg"), "Link shows rev 1")
        self.assertEqual(self.q(t, ".up b"), "Readers see rev 1. The doc is at rev 2.")
        self.assertEqual(self.q(t, ".stl"), "Shared at rev 1 · " + t.ev(f"{SHEET}.querySelector('.stl').textContent.split(' · ')[1]") + " · as jlee-acme")
        self.assertEqual([self.q(t, ".go"), self.q(t, ".cp", "className")], ["Update to rev 2", "cp"])
        t.ev(f"{SHEET}.querySelector('.go').click()")
        t.wait_for(f"{SHEET}.querySelector('.eyb .bdg')?.textContent === 'Up to date'")
        self.assertEqual(self.posts(t), [["/__bluedoc/share", {"path": t.ev("location.pathname")}]])
        self.assertEqual(self.q(t, ".lnk input", "title"), LINK, "the link stays")
        self.assertIn("readers see rev 2", self.toast(t, "updated"))
        self.assertEqual(t.ev("__copied"), [], "the same link: nothing new to copy")
        self.assertEqual(t.wait_for(f"{KEY}.dataset.share === 'shared' && 'ok'"), "ok")

    def test_a_gist_on_another_account_waits_for_move_or_keep(self) -> None:
        mm = {"share": gist(user="jlee", rev="1"), "account": {"login": "jlee-acme", "why": "project"}, "mismatch": {"gist": "jlee", "project": "jlee-acme"}}
        for pick in ("keep", "move"):
            with self.subTest(pick=pick):
                t = self.page(view(**mm))
                self.sheet(t)
                self.assertEqual(self.q(t, ".cap.mt"), "This gist is on jlee; acme-shop shares as jlee-acme")
                self.assertEqual(t.ev(f"[...{SHEET}.querySelectorAll('.tile')].map(e => e.textContent)"),
                                 ["Move to jlee-acmeNew gist, jlee’s is deleted.Link changes", "Keep on jleeRev 2 goes into this gist.Link stays"])
                self.assertEqual([self.q(t, ".go"), self.q(t, ".go", "disabled")], ["Update to rev 2 · pick one first", True])
                t.ev(f"{SHEET}.querySelector('.go').click()")
                self.assertEqual(self.posts(t), [])
                t.ev(f"{SHEET}.querySelector('.tile[data-pick={pick}]').click()")
                t.wait_for(f"!{SHEET}.querySelector('.go').disabled")
                self.assertEqual(self.q(t, ".go"), "Update to rev 2")
                t.ev(f"{SHEET}.querySelector('.go').click()")
                t.wait_for(f"{SHEET}.querySelector('.eyb .bdg')?.textContent === 'Up to date'")
                self.assertEqual(self.posts(t), [["/__bluedoc/share", {"path": t.ev("location.pathname"), pick: True}]])
                self.assertIsNone(self.q(t, ".tiles"))
                if pick == "keep":
                    self.assertEqual([self.q(t, ".lnk input", "title"), self.q(t, ".stl").split(" · as ")[1]], [LINK, "jlee"])
                else:
                    self.assertNotEqual(self.q(t, ".lnk input", "title"), LINK, "a new gist: a new link")
                    self.assertEqual(self.q(t, ".stl").split(" · as ")[1], "jlee-acme")
                    self.assertIn("new link is copied", self.toast(t, "moved"))
        self.assertEqual(self.browser.errors, [])

    def test_stop_sharing_takes_a_second_press(self) -> None:
        t = self.page(view(share=gist()))
        self.sheet(t)
        t.ev(f"{SHEET}.querySelector('.stop').click()")
        self.assertEqual([self.q(t, ".stop"), self.q(t, ".stop", "className")], ["Delete the gist", "tb stop sure"])
        self.assertTrue(t.ev(f"document.activeElement === {SHEET}.querySelector('.stop')"))
        self.assertEqual(self.posts(t), [], "the first press deletes nothing")
        t.ev(f"{SHEET}.querySelector('.stop').click()")
        self.assertIn("gist is deleted", self.toast(t, "stopped sharing"))
        self.assertEqual(self.posts(t), [["/__bluedoc/unshare", {"path": t.ev("location.pathname")}]])
        self.assertFalse(t.ev(f"{SHEET}.open"))
        self.assertIsNone(t.ev(f"{KEY}.dataset.share || null"))

    def test_sharing_off_dims_the_key_and_its_popover_says_how_to_turn_it_on(self) -> None:
        t = self.page(view(off=OFF))
        t.wait_for(f"{KEY}.getAttribute('aria-disabled') === 'true'")
        self.assertLess(float(t.ev(f"getComputedStyle({KEY}).opacity")), 1)
        box = t.ev(f"(r => [r.left + r.width / 2, r.top + r.height / 2])({KEY}.getBoundingClientRect())")
        self.browser.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": box[0], "y": box[1]}, t.session)
        self.assertEqual(t.wait_for("(t => !t.hidden && t.textContent)(document.querySelector('.bd-tip'))"),
                         "Sharing is off: gh, the GitHub CLI, isn't signed in to GitHub. Click for how to turn it on.")
        self.click_at(t, *box)
        pop = "document.querySelector('.bd-shoff')"
        t.wait_for(f"!{pop}.hidden")
        self.assertFalse(t.ev(f"!!{SHEET}"), "no sheet while sharing is off")
        self.assertEqual(t.ev(f"{pop}.querySelector('h4').textContent"), "Sharing is off")
        self.assertEqual(t.ev(f"{pop}.querySelector('.cmd code').textContent"), "gh auth login -s gist")
        self.assertEqual(t.ev(f"{pop}.querySelector('.ft2').textContent"), "No gh? brew install gh or cli.github.com")
        self.assertTrue(t.ev(f"document.activeElement === {pop}.querySelector('.cmd button')"))
        t.ev(f"{pop}.querySelector('.cmd button').click()")
        self.assertEqual(t.ev("__copied"), ["gh auth login -s gist"])
        self.assertEqual(t.ev(f"{KEY}.getAttribute('aria-expanded')"), "true")
        self.key(t, "Escape", vk=27)
        t.wait_for(f"{pop}.hidden && document.activeElement === {KEY}")
        # gh signed in since: the next press asks again and opens the sheet
        t.ev("__share.view.off = null; true")
        t.ev(f"{KEY}.click()")
        t.wait_for(f"(d => d && d.open)({SHEET})")
        self.assertFalse(t.ev(f"{KEY}.hasAttribute('aria-disabled')"))
        self.assertEqual(self.browser.errors, [])

    def test_esc_and_a_press_outside_close_it_and_an_error_stays(self) -> None:
        t = self.page(view())
        self.sheet(t)
        self.key(t, "Escape", vk=27)
        t.wait_for(f"!{SHEET}.open")
        self.sheet(t)
        self.click_at(t, 20, 450)
        t.wait_for(f"!{SHEET}.open")
        self.sheet(t)
        self.click_at(t, *t.ev(f"(r => [r.left + 10, r.top + 10])({SHEET}.querySelector('.strip').getBoundingClientRect())"))
        self.assertTrue(t.ev(f"{SHEET}.open"), "a press in the ticket keeps it")
        t.ev("__share.fail = \"gh isn't signed in to GitHub: run `gh auth login -s gist`\"; true")
        t.ev(f"{SHEET}.querySelector('.go').click()")
        self.assertEqual(t.wait_for(f"{SHEET}.querySelector('.err')?.textContent"), "Couldn't share: gh isn't signed in to GitHub: run `gh auth login -s gist`")
        self.assertTrue(t.ev(f"{SHEET}.open"))

    def test_a_phone_fits_the_sheet(self) -> None:
        for v in (view(), view(share=gist(user="jlee", rev="1"), mismatch={"gist": "jlee", "project": "jlee-acme"})):
            t = self.page(v, 390, 800)
            self.sheet(t)
            t.ev(f"{SHEET}.querySelector('.det summary').click()")
            box = t.ev(f"(r => [r.left, r.right, r.bottom])({SHEET}.querySelector('.bd-tk').getBoundingClientRect())")
            self.assertGreaterEqual(box[0], 0)
            self.assertLessEqual(box[1], 390)
            self.assertEqual(t.ev(f"[...{SHEET}.querySelectorAll('.bd-tk *')].filter(e => e.getBoundingClientRect().right > {box[1]} + 0.5).length"), 0)
            self.assertGreaterEqual(t.ev(f"{SHEET}.getBoundingClientRect().bottom"), 799, "the sheet at the window's foot")


if __name__ == "__main__":
    unittest.main()
