"""Where a design page's panels put things (1.0.0-beta14). The brief (TL;DR, the sections, status) is the right panel's
Brief tab, before Comments and Revisions, on a design, a deck, a website and a storelisting; the left panel has no Brief
and, on the first three, no tab bar. A storelisting's left panel is Text, Style, Colors and Checks: every store text
and caption is editable, Save makes each changed field a `listing` draft (op `field`) in the one undo history, Request
changes sends it with its `build.py patch … field:… --set` command, and the draft resolves once the doc has the value;
Colors is the old Brand (a stored `brand` tab opens it); the captions' Typography is a section of Text. serve.py keeps a field
draft only in its shape."""
from __future__ import annotations

import json
import shlex
import unittest

from _support import load_json
from test_page_state import CHROME, ChromePage, Tab

import listing
import serve

STEM = "acme-fit-listing"
LST = "BP.listing()"
LP_OPEN = "document.documentElement.classList.contains('bd-lp-open') || document.dispatchEvent(new KeyboardEvent('keydown', {key: '['}))"


def field_draft(**listing_op) -> str:
    a = {"id": "c1", "type": "listing", "status": "pending", "note": "", "target": {"key": "field:en-US/play/short", "label": "x"},
         "listing": {"op": "field", "locale": "en-US", "group": "play", "field": "short", "value": "New", "base": "Old", **listing_op}}
    return json.dumps(a)


class FieldDraftShape(unittest.TestCase):
    """serve.py value_ok, as the page's MARKUP valid: a field draft's locale, group, field, value and base."""

    def test_a_field_draft_is_kept_only_in_its_shape(self) -> None:
        self.assertTrue(serve.value_ok("__ann:c1", field_draft()))
        self.assertTrue(serve.value_ok("__ann:c1", field_draft(base=None)), "a field that wasn't set")
        self.assertTrue(serve.value_ok("__ann:c1", field_draft(value=["One", "Two"])), "a list of texts")
        for bad in ({"value": None}, {"value": 3}, {"value": "x" * (serve.FIELD_TEXT_MAX + 1)}, {"value": ["x"] * (serve.FIELD_ITEMS_MAX + 1)},
                    {"base": 1}, {"locale": ""}, {"group": None}, {"field": ""}):
            self.assertFalse(serve.value_ok("__ann:c1", field_draft(**bad)), bad)
        self.assertTrue(serve.value_ok("__ann:c1", json.dumps({**json.loads(field_draft()), "listing": {"op": "order"}})), "other ops stay as they were")


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class BriefInTheRightPanel(ChromePage):
    def brief_shows(self, name: str, ready: str) -> Tab:
        t = self.open(self.server.url_for(self.docs / f"{name}.bluedoc.json"))
        t.wait_for(ready)
        t.wait_for("!!document.querySelector('.bd-lp')")
        self.assertEqual(t.ev("document.querySelectorAll('#bd-lp-brief, .bd-lp [data-v=brief], .bd-lp .bd-tldr, .bd-lp main').length"), 0, f"{name}: Brief left the left panel")
        tabs = t.ev("[...document.querySelectorAll('.bd-sp-tabs [data-f]')].map(b => b.dataset.f)")
        self.assertEqual(tabs[:2], ["brief", "comments"], f"{name}: {tabs}")
        self.assertTrue(set(tabs) <= {"brief", "comments", "revisions"}, tabs)
        t.ev("BP.sidebar({section: 'brief'})")
        t.wait_for("BP.sidebar().section === 'brief' && BP.sidebar().open && !document.getElementById('bd-sp-brief').hidden")
        self.assertTrue(t.ev("(b => !!b.querySelector('.bd-tldr-card') && b.querySelectorAll('main section.bp-sec').length > 0 && b.getBoundingClientRect().width > 200)"
                             "(document.getElementById('bd-sp-brief'))"), name)
        # its parts are the doc's: a comment pins on the TL;DR
        a = t.ev("BP.annotate({type: 'pin', key: 'tldr', note: 'Shorter'})")
        self.assertEqual(a and a["target"]["key"], "tldr", name)
        # a reload keeps Brief picked
        t.ev("window.__before = 1; location.reload()")
        t.wait_for("!window.__before && document.readyState === 'complete' && !!window.BP")
        t.wait_for(ready)
        t.wait_for("BP.sidebar().section === 'brief'")
        self.assertEqual(self.browser.errors, [])
        return t

    def test_a_design_board(self) -> None:
        t = self.brief_shows("acme-fit-design", "!!BP.board()")
        self.assertEqual(t.ev("document.querySelectorAll('.bd-lp .bd-lp-tabs').length"), 0, "one content: no tab bar")
        self.assertTrue(t.ev("!document.getElementById('bd-lp-screens').hidden"))

    def test_a_deck(self) -> None:
        t = self.brief_shows("acme-fit-deck", "!!BP.board()")
        self.assertEqual(t.ev("document.querySelectorAll('.bd-lp .bd-lp-tabs').length"), 0)
        self.assertEqual(t.ev("document.querySelector('.bd-lp').getAttribute('aria-label')"), "Slides")

    def test_a_website(self) -> None:
        t = self.brief_shows("acme-site", "!!BP.board()")
        self.assertEqual(t.ev("document.querySelectorAll('.bd-lp .bd-lp-tabs').length"), 0)
        self.assertEqual(t.ev("document.querySelector('.bd-lp').getAttribute('aria-label')"), "Pages")

    def test_a_storelisting(self) -> None:
        t = self.brief_shows(STEM, "!!document.querySelector('.bd-lst-sec') && !!BP.listing()")
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-lp-tabs [data-v]')].map(b => b.dataset.v)"), ["text", "style", "colors", "checks"])


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class ListingLeftPanel(ChromePage):
    def setUp(self) -> None:
        super().setUp()
        self.doc_path = self.docs / f"{STEM}.bluedoc.json"
        self.url = self.server.url_for(self.doc_path)

    def page(self, frag: str = "#play", side: str = "text", t=None):
        t = t or self.open(self.url)
        t.ev(f"location.hash = {json.dumps(frag)}; window.__before = 1; location.reload()")
        t.wait_for("!window.__before && document.readyState === 'complete' && !!window.BP && !!document.querySelector('.bd-lst-sec') && !!BP.listing()")
        t.ev(LP_OPEN)
        t.ev(f"document.querySelector('.bd-lp-tabs [data-v=\"{side}\"]').click()")
        t.wait_for(f"!document.getElementById('bd-lp-{side}').hidden && document.documentElement.classList.contains('bd-lp-open')")
        return t

    def field(self, t, key: str) -> dict:
        return next(f for f in t.ev(LST)["fields"] if f["field"] == key)

    def test_a_text_edit_saves_as_a_draft_that_reloads_undoes_and_goes_with_its_patch_command(self) -> None:
        t = self.page()
        k, new = "en-US/play/short", "Your week of runs, rides and sleep at a glance."
        was = self.field(t, k)["value"]
        fields = t.ev(LST)["fields"]
        self.assertTrue(fields and all(f["editable"] for f in fields), [f["field"] for f in fields if not f["editable"]])
        self.assertEqual(t.ev(LST)["text"]["canSave"], False, "nothing changed: Save is off")
        self.assertTrue(t.ev("document.querySelector('#bd-lp-text [data-save]').disabled"))
        t.ev(f"BP.listing({{text: {{{json.dumps(k)}: {json.dumps(new)}}}}})")
        f = self.field(t, k)
        self.assertEqual((f["value"], f["dirty"], f["draft"], f["count"]), (new, True, False, f"{len(new)} / 80"))
        self.assertTrue(t.ev("document.querySelector('.bd-lp-tabs [data-v=text]').classList.contains('dirty')"), "the tab says unsaved")
        # leaving the tab keeps the edit; leaving the page asks first
        t.ev("document.querySelector('.bd-lp-tabs [data-v=style]').click(); document.querySelector('.bd-lp-tabs [data-v=text]').click()")
        self.assertEqual(t.ev(LST)["text"]["unsaved"], [k])
        self.assertTrue(t.ev("(e => (dispatchEvent(e), e.defaultPrevented))(new Event('beforeunload', {cancelable: true}))"))
        t.ev("document.querySelector('#bd-lp-text [data-save]').click()")
        t.wait_for(f"{LST}.text.drafts.length === 1 && {LST}.text.unsaved.length === 0")
        d = t.ev(LST)["text"]["drafts"][0]
        self.assertEqual((d["key"], d["value"], d["base"]), (f"field:{k}", new, was))
        self.assertFalse(t.ev("(e => (dispatchEvent(e), e.defaultPrevented))(new Event('beforeunload', {cancelable: true}))"))
        self.assertTrue(t.ev("document.querySelector('#bd-lp-text [data-save]').disabled"))
        # a reload keeps it: the field shows the draft, Draft-tagged; the history keeps the step
        t = self.page(t=t)
        f = self.field(t, k)
        self.assertEqual((f["value"], f["draft"], f["dirty"]), (new, True, False))
        self.assertEqual(t.ev(LST)["text"]["undo"], 1)
        self.assertEqual(t.ev(LST)["text"]["next"]["undo"], "Short description · en-US", "a one-field Save is named for its field")
        # undo puts the doc's text back; redo the draft
        t.ev("BP.listing({undo: true})")
        t.wait_for(f"{LST}.text.drafts.length === 0")
        self.assertEqual(self.field(t, k)["value"], was)
        t.ev("BP.listing({redo: true})")
        t.wait_for(f"{LST}.text.drafts.length === 1")
        self.assertEqual(self.field(t, k)["value"], new)
        # the card in Comments shows the change and Discard
        self.assertTrue(t.ev("[...document.querySelectorAll('#bd-sp-comments li')].some(li => li.querySelector('.eld b') && li.querySelector('.eld b').textContent.includes('Your week of runs'))"))
        self.send_changes(t, "1")
        self.assertEqual(t.ev(LST)["text"]["sealed"], 1, "sent: undo stops there")
        out = self.reply(self.doc_path)
        self.assertIn("## Text edits", out)
        cmd = next(l for l in out.splitlines() if l.startswith("build.py patch") and f"field:{k}" in l)
        args = shlex.split(cmd)
        self.assertEqual(args[3:5], [f"field:{k}", "--set"])
        r = self.tmp.run("build.py", "patch", self.doc_path, *args[3:])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(listing.listing_of(load_json(self.doc_path))["text"]["en-US"]["play"]["short"], new)
        t = self.page(t=t)
        f = self.field(t, k)
        self.assertEqual((f["value"], f["draft"]), (new, False), "the doc carries it: the draft is applied")
        self.assertEqual(t.ev(LST)["text"]["drafts"], [])
        self.assertEqual(self.browser.errors, [])

    def test_a_caption_and_an_mt_string_its_badge_clears_when_the_agent_records_it(self) -> None:
        t = self.page("#play/es-ES")
        mt, cap = "es-ES/play/short", "es-ES/strings/today.title"
        self.assertTrue(self.field(t, mt)["mt"])
        t.ev(f"BP.listing({{text: {{{json.dumps(mt)}: 'Tu semana de un vistazo.', {json.dumps(cap)}: 'Tu semana, de un vistazo'}}}})")
        self.assertEqual(sorted(t.ev(LST)["text"]["unsaved"]), sorted([mt, cap]))
        t.ev("BP.listing({save: true})")
        t.wait_for(f"{LST}.text.drafts.length === 2")
        self.assertTrue(self.field(t, mt)["mt"], "MT until the agent records the edit")
        self.assertEqual(t.ev(LST)["text"]["undo"], 1, "one Save is one step")
        self.send_changes(t, "2")
        out = self.reply(self.doc_path)
        cmds = [shlex.split(l) for l in out.splitlines() if l.startswith("build.py patch") and "field:es-ES/" in l]
        self.assertEqual(sorted(c[3] for c in cmds), sorted([f"field:{mt}", f"field:{cap}"]))
        for c in cmds:
            r = self.tmp.run("build.py", "patch", self.doc_path, *c[3:])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lb = listing.listing_of(load_json(self.doc_path))
        self.assertEqual(lb["strings"]["es-ES"]["today.title"], "Tu semana, de un vistazo")
        self.assertNotIn("play.short", lb["mt"].get("es-ES", []))
        t = self.page("#play/es-ES", t=t)
        self.assertFalse(self.field(t, mt)["mt"])
        self.assertEqual(t.ev(LST)["text"]["drafts"], [])

    def test_an_over_limit_edit_shows_red_and_still_saves(self) -> None:
        t = self.page()
        k = "en-US/play/short"
        t.ev(f"BP.listing({{text: {{{json.dumps(k)}: {json.dumps('x' * 81)}}}}})")
        f = self.field(t, k)
        self.assertEqual((f["over"], f["count"]), (True, "81 / 80"))
        self.assertTrue(t.ev(LST)["text"]["canSave"])
        t.ev("BP.listing({save: true})")
        t.wait_for(f"{LST}.text.drafts.length === 1")
        self.assertTrue(self.field(t, k)["over"])

    def test_colors_replaces_brand_and_an_old_brand_tab_opens_it(self) -> None:
        t = self.page(side="colors")
        self.assertTrue(t.ev("!!document.querySelector('#bd-lp-colors .bd-lst-imgdrop') && !!document.querySelector('#bd-lp-colors .bd-lst-roles') && !!document.querySelector('#bd-lp-colors .bd-lst-pairs')"))
        self.assertEqual(t.ev("document.querySelectorAll('#bd-lp-brand, .bd-lp-tabs [data-v=brand], #bd-lp-colors .bd-lst-fonts').length"), 0)
        t.ev("localStorage.setItem('bluedoc:listing-tab', 'brand'); window.__before = 1; location.reload()")
        t.wait_for("!window.__before && document.readyState === 'complete' && !!window.BP && !!BP.listing()")
        self.assertEqual(t.ev("[document.getElementById('bd-lp-colors').hidden, document.querySelector('.bd-lp-tabs [data-v=colors]').getAttribute('aria-checked'), localStorage.getItem('bluedoc:listing-tab')]"),
                         [False, "true", "colors"])
        t.ev("localStorage.setItem('bluedoc:listing-tab', 'brief'); window.__before = 1; location.reload()")
        t.wait_for("!window.__before && document.readyState === 'complete' && !!window.BP && !!BP.listing()")
        self.assertFalse(t.ev("document.getElementById('bd-lp-text').hidden"), "a stored Brief tab opens Text")

    def test_typography_is_a_section_of_text(self) -> None:
        t = self.page()
        sec = "document.querySelector('#bd-lp-text .bd-lst-fsec')"
        self.assertEqual(t.ev(f"{sec}.querySelector('h4').textContent"), "Typography")
        self.assertTrue(t.ev(f"!!{sec}.querySelector('.bd-ty-dd.fam[aria-haspopup=listbox]') && !!{sec}.querySelector('.bd-ty-dd.sty[aria-haspopup=listbox]')"
                             f" && !!{sec}.querySelector('.bd-ty-num[data-key=size]') && !!{sec}.querySelector('.bd-ty-num[data-key=lineHeight]')"
                             f" && !!{sec}.querySelector('.bd-ty-num[data-key=letterSpacing]') && {sec}.querySelectorAll('.seg button').length === 6"))
        # no always-open list, no preview card: the family list is a closed popover with ↻ Refresh fonts
        self.assertEqual(t.ev(f"{sec}.querySelectorAll('.bd-lst-fonts, .bd-lst-fcur, .bd-ty-pop:popover-open').length"), 0)
        self.assertIn("Refresh fonts", t.ev(f"{sec}.querySelector('.bd-ty-pop[data-menu=family] .rf').textContent"))
        # vendored Inter, or the same family installed on this machine: either way a licence note, in the ⓘ by the family
        self.assertRegex(t.ev(f"{sec}.querySelector('.bd-ty-info').title"), r"vendored, OFL|not a licence for marketing images", "the licence note")
        self.assertTrue(t.ev(f"(s => s.nextElementSibling === document.querySelector('#bd-lp-text .bd-lst-fields') && s.parentElement.id === 'bd-lp-text'"
                             f" && !s.previousElementSibling.matches('.bd-lfield, .bd-lst-fields'))({sec})"), "at the top of Text, over the fields")
        self.assertTrue(t.ev(f"(s => s.getBoundingClientRect().bottom <= document.querySelector('#bd-lp-text .bd-lfield').getBoundingClientRect().top)({sec})"),
                        "drawn above the first field")


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class ListingToolbar(ChromePage):
    """1.0.0-beta16: a storelisting's floating toolbar (the left panel's key, Undo, Redo, the drafts count, platform,
    locale, view, Jump to, Checks, Export to…), and every listing draft a step of the one undo history."""

    TB = ".bd-lst-btb"
    UNDO = ".bd-lst-btb [aria-keyshortcuts^='Meta+Z']"
    REDO = ".bd-lst-btb [aria-keyshortcuts^='Shift+Meta+Z']"
    page, field = ListingLeftPanel.page, ListingLeftPanel.field

    def setUp(self) -> None:
        super().setUp()
        self.doc_path = self.docs / f"{STEM}.bluedoc.json"
        self.url = self.server.url_for(self.doc_path)

    def keys(self, t) -> list:
        """[undo disabled, undo label, redo disabled, redo label]: the keys' state and the tooltips that name the step."""
        return t.ev(f"[...document.querySelectorAll(\"{self.UNDO}, {self.REDO}\")].flatMap(b => [b.disabled, b.getAttribute('aria-label')])")

    def test_the_toolbar_holds_the_listing_controls_and_the_app_bar_does_not(self) -> None:
        t = self.page()
        self.assertEqual(t.ev(LST)["toolbar"]["controls"], ["play", "appstore", "locale", "sections", "preview", "ads", "jump", "checks", "export"])
        self.assertTrue(t.ev(f"!!document.querySelector('.bd-lst .bd-btb{self.TB}[role=toolbar]')"), "floating in the listing, as a board's")
        self.assertEqual(t.ev("document.querySelectorAll('.bd-bar :is([data-p], [data-view], select, .bd-expb, .bd-lst-btb)').length"), 0, "the app bar keeps the breadcrumb, Rev and theme")
        self.assertTrue(t.ev("!!document.querySelector('.bd-bar .bd-crumb')"))
        # the switches still work, and the URL keeps the platform and locale
        t.ev(f"document.querySelector('{self.TB} [data-p=appstore]').click()")
        t.ev(f"document.querySelector('{self.TB} .bd-lst-loc .bd-selb').click()")
        t.ev(f"document.querySelector('{self.TB} .bd-lst-loc [role=option][data-v=es-ES]').click()")
        t.ev(f"document.querySelector('{self.TB} [data-view=preview]').click()")
        got = t.ev(LST)
        self.assertEqual((got["platform"], got["locale"], got["view"], got["hash"]), ("appstore", "es-ES", "preview", "#appstore/es-ES"))
        self.assertTrue(any("MT" in loc["label"] for loc in got["locales"]), "the locale menu keeps its MT counts")
        self.assertEqual(t.ev(f"[...document.querySelectorAll('{self.TB} .bd-lst-loc [role=option]')].map(o => [o.dataset.v, o.querySelector('.m') ? o.querySelector('.m').textContent : ''])"),
                         [[loc["id"], loc["label"][len(loc["id"]) + 3:]] for loc in got["locales"]], "each option's hint: its MT and missing counts")
        self.assertEqual(t.ev(f"document.querySelectorAll('{self.TB} select').length"), 0, "no native select in the toolbar")
        # Jump to: a menu of the sections, its key still "Jump to"; a pick scrolls to one
        jump = f"document.querySelector('{self.TB} .bd-lst-jump')"
        t.ev(f"document.querySelector('{self.TB} [data-view=sections]').click()")
        self.assertEqual(t.ev(f"[{jump}.btn.getAttribute('aria-haspopup'), {jump}.btn.getAttribute('aria-label'), {jump}.btn.textContent, {jump}.btn.disabled]"),
                         ["menu", "Jump to a section", "Jump to", False])
        rows = t.ev(f"[...{jump}.querySelectorAll('[role=menuitem]')].map(o => o.textContent)")
        self.assertEqual(rows, t.ev("[...document.querySelectorAll('.bd-lst-sec')].map(s => s.querySelector('h3') ? s.querySelector('h3').textContent : s.dataset.row)"))
        self.assertGreater(len(rows), 1)
        t.ev(f"{jump}.btn.click(); {jump}.querySelectorAll('[role=menuitem]')[{len(rows) - 1}].click()")
        t.wait_for("document.querySelector('.bd-lst-main').scrollTop > 0")
        self.assertEqual(t.ev(f"[{jump}.btn.textContent, {jump}.btn.getAttribute('aria-expanded')]"), ["Jump to", "false"])
        # the Checks count opens the Checks tab
        t.ev(f"document.querySelector('{self.TB} .bd-lst-ckb').click()")
        self.assertFalse(t.ev("document.getElementById('bd-lp-checks').hidden"))
        # one row at 1440 px with both panels open, and at 1100 px
        for w in (1440, 1100):
            self.browser.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": 900, "deviceScaleFactor": 1, "mobile": False}, t.session)
            t.wait_for(f"(b => b.scrollWidth <= b.clientWidth + 1 && b.getBoundingClientRect().right <= document.querySelector('.bd-lst').getBoundingClientRect().right"
                       f" && b.getBoundingClientRect().height < 48)(document.querySelector('{self.TB}'))")
        self.assertEqual(self.browser.errors, [])

    def test_the_bracket_and_the_toolbar_key_toggle_the_left_panel_and_a_reload_keeps_it(self) -> None:
        t = self.page()
        self.assertTrue(t.ev(LST)["toolbar"]["lp"])
        t.ev("document.dispatchEvent(new KeyboardEvent('keydown', {key: '['}))")
        self.assertEqual((t.ev(LST)["toolbar"]["lp"], t.ev("document.documentElement.classList.contains('bd-lp-open')")), (False, False))
        self.assertEqual(t.ev(f"document.querySelector('{self.TB} [aria-keyshortcuts=\"[\"]').getAttribute('aria-pressed')"), "false")
        t.ev("window.__before = 1; location.reload()")
        t.wait_for("!window.__before && document.readyState === 'complete' && !!window.BP && !!document.querySelector('.bd-lst-sec') && !!BP.listing()")
        self.assertFalse(t.ev(LST)["toolbar"]["lp"], "a reload keeps it hidden")
        t.ev(f"document.querySelector('{self.TB} [aria-keyshortcuts=\"[\"]').click()")
        self.assertTrue(t.ev(LST)["toolbar"]["lp"])
        t.ev("window.__before = 1; location.reload()")
        t.wait_for("!window.__before && document.readyState === 'complete' && !!window.BP && !!BP.listing()")
        self.assertTrue(t.ev(LST)["toolbar"]["lp"], "and open")

    def test_undo_and_redo_run_one_history_across_a_save_a_style_pick_and_a_colour_edit(self) -> None:
        t = self.page()
        self.assertEqual(self.keys(t), [True, "Nothing to undo", True, "Nothing to redo"])
        self.assertEqual(t.ev("document.querySelectorAll('#bd-lp-text .bd-lst-tsave :is(.bd-ibtn, [aria-label^=Undo], [aria-label^=Redo])').length"), 0,
                         "Text has Save, not its own Undo and Redo")
        self.assertTrue(t.ev("!!document.querySelector('#bd-lp-text .bd-lst-tsave [data-save]')"))
        k, new = "en-US/play/short", "Your week of runs, rides and sleep at a glance."
        was = self.field(t, k)["value"]
        was_style, was_bg = t.ev(LST)["style"], t.ev(LST)["brand"]["palette"]["bg"]
        # 1 a text Save, 2 a style pick, 3 a colour edit: three steps
        t.ev(f"BP.listing({{text: {{{json.dumps(k)}: {json.dumps(new)}}}, save: true}})")
        t.wait_for(f"{LST}.toolbar.undo === 'Short description · en-US'")
        t.ev("document.querySelector('.bd-lp-tabs [data-v=style]').click()")
        pick = "l4" if was_style["layout"] != "l4" else "l3"
        t.ev(f"document.querySelector('.bd-lst-stp [data-style=\"{pick}\"]').click()")
        t.wait_for(f"{LST}.style.layout === '{pick}' && {LST}.toolbar.undo.startsWith('Style · Google Play')")
        t.ev("document.querySelector('.bd-lp-tabs [data-v=colors]').click()")
        t.ev("(i => { i.value = '#7c3aed'; i.dispatchEvent(new Event('input')); })(document.querySelector('.bd-lst-role[data-role=\"bg\"] .hx'))")
        t.wait_for(f"{LST}.brand.draft && {LST}.text.undo === 3", 5)
        self.assertEqual(t.ev(LST)["toolbar"]["drafts"], 3)
        self.assertIn("Undo: ", self.keys(t)[1])
        self.assertEqual(self.keys(t)[2:], [True, "Nothing to redo"])
        # the history survives a reload
        t = self.page(t=t)
        self.assertEqual((t.ev(LST)["text"]["undo"], t.ev(LST)["toolbar"]["drafts"]), (3, 3))
        # undo each in reverse order: the colour, the pick, the text
        t.ev(f"document.querySelector(\"{self.UNDO}\").click()")
        t.wait_for(f"!{LST}.brand.draft && {LST}.brand.palette.bg === {json.dumps(was_bg)}")
        self.assertEqual(t.ev(LST)["style"]["layout"], pick)
        t.ev("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'z', metaKey: true}))")
        t.wait_for(f"{LST}.style.layout === {json.dumps(was_style['layout'])}")
        self.assertEqual(self.field(t, k)["value"], new)
        t.ev("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'z', ctrlKey: true}))")
        t.wait_for(f"{LST}.text.drafts.length === 0")
        self.assertEqual(self.field(t, k)["value"], was)
        self.assertEqual(t.ev(LST)["toolbar"]["drafts"], 0)
        undo_off, _, redo_off, redo_tip = self.keys(t)
        self.assertEqual((undo_off, redo_off, redo_tip), (True, False, "Redo: Short description · en-US"), "at the start: Undo off")
        # redo one: the text comes back; a reload keeps where the history is
        t.ev(f"document.querySelector(\"{self.REDO}\").click()")
        t.wait_for(f"{LST}.text.drafts.length === 1")
        self.assertEqual(self.field(t, k)["value"], new)
        t = self.page(t=t)
        self.assertEqual((t.ev(LST)["text"]["undo"], t.ev(LST)["text"]["redo"]), (1, 2))
        self.assertEqual(t.ev(LST)["toolbar"]["redo"].split(": ")[0], f"Style · Google Play")
        # redo to the end: Redo off
        t.ev("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'z', metaKey: true, shiftKey: true}))")
        t.ev("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'y', ctrlKey: true}))")
        t.wait_for(f"{LST}.brand.draft && {LST}.style.layout === '{pick}'")
        self.assertEqual(self.keys(t)[2:], [True, "Nothing to redo"])
        # in a text field the field's own undo runs, not the history's
        t.ev("document.querySelector('.bd-lp-tabs [data-v=text]').click()")
        t.ev("(ta => { ta.focus(); ta.dispatchEvent(new KeyboardEvent('keydown', {key: 'z', metaKey: true, bubbles: true})); })(document.querySelector('#bd-lp-text .bd-lfield textarea'))")
        self.assertEqual(t.ev(LST)["text"]["undo"], 3)
        self.assertEqual(self.browser.errors, [])

    def test_the_drafts_count_opens_comments_on_pending(self) -> None:
        t = self.page()
        self.assertTrue(t.ev(f"document.querySelector('{self.TB} .bd-dcount').hidden"))
        t.ev("BP.listing({text: {'en-US/play/short': 'Short and new'}, save: true})")
        t.wait_for(f"{LST}.toolbar.drafts === 1")
        self.assertEqual(t.ev(f"document.querySelector('{self.TB} .bd-dcount').textContent"), "1 draft")
        t.ev("BP.comments({filter: 'all', open: false})")
        t.ev(f"document.querySelector('{self.TB} .bd-dcount').click()")
        c = t.ev("BP.comments()")
        self.assertEqual((c["open"], c["filter"]), (True, "pending"))

    KEYS = {"Enter": ("Enter", 13, "\r"), "Escape": ("Escape", 27, None), "ArrowDown": ("ArrowDown", 40, None), "ArrowUp": ("ArrowUp", 38, None),
            "Home": ("Home", 36, None), "End": ("End", 35, None), "Tab": ("Tab", 9, None), "e": ("KeyE", 69, "e"), "[": ("BracketLeft", 219, "[")}

    def press(self, t, key: str) -> None:
        code, vk, text = self.KEYS[key]
        for typ in ("keyDown", "keyUp"):
            self.browser.call("Input.dispatchKeyEvent", {"type": typ, "key": key, "code": code, "windowsVirtualKeyCode": vk,
                                                         **({"text": text} if typ == "keyDown" and text else {})}, t.session)

    def test_the_locale_menu_opens_by_click_and_arrow_picks_by_keyboard_and_closes_back_to_its_key(self) -> None:
        """1.0.0-beta17: the toolbar's locale is a menu button, as Export to… is, not a native select: a listbox of the
        locales, the current one ticked; ↓ or a click opens it on the current locale, ↑ ↓ Home End and a typed letter
        move, Enter picks, Esc closes it back to its key, a press outside closes it, and the page's keys wait."""
        t = self.page()
        self.browser.call("Emulation.setFocusEmulationEnabled", {"enabled": True}, t.session)
        self.assertEqual(t.ev(f"document.querySelectorAll('{self.TB} select').length"), 0, "no native select in the toolbar")
        loc = f"document.querySelector('{self.TB} .bd-lst-loc')"
        btn, menu = f"{loc}.querySelector('.bd-selb')", f"{loc}.querySelector('[role=listbox]')"
        state = f"[{btn}.getAttribute('aria-expanded'), !{menu}.hidden, document.activeElement === {btn} ? 'button' : document.activeElement.dataset.v || null]"
        self.assertEqual(t.ev(f"[{btn}.getAttribute('aria-haspopup'), {btn}.getAttribute('aria-label'), {btn}.textContent, {loc}.value]"),
                         ["listbox", "Locale", "en-US", "en-US"])
        self.assertEqual(t.ev(f"[...{menu}.querySelectorAll('[role=option]')].map(o => [o.dataset.v, o.getAttribute('aria-selected')])"),
                         [["en-US", "true"], ["es-ES", "false"]])
        # a click opens it on the current locale; Esc closes it back to the key
        t.ev(f"{btn}.click()")
        self.assertEqual(t.ev(state), ["true", True, "en-US"])
        self.press(t, "Escape")
        self.assertEqual(t.ev(state), ["false", False, "button"])
        # ↓ opens it on the current locale; ↓ ↑ wrap, End and Home, a typed letter goes to the next locale it starts
        self.press(t, "ArrowDown")
        self.assertEqual(t.ev(state), ["true", True, "en-US"])
        for key, on in (("ArrowDown", "es-ES"), ("ArrowDown", "en-US"), ("ArrowUp", "es-ES"), ("Home", "en-US"), ("End", "es-ES"), ("e", "en-US"), ("Home", "en-US")):
            self.press(t, key)
            self.assertEqual(t.ev(state)[2], on, key)
        # the page's keys wait while it is open: [ leaves the left panel as it is
        lp = t.ev(LST)["toolbar"]["lp"]
        self.press(t, "[")
        self.assertEqual((t.ev(LST)["toolbar"]["lp"], t.ev(state)[:2]), (lp, ["true", True]))
        # ↓ Enter picks es-ES: the locale switches, the menu closes back to its key, which shows it, ticked
        self.press(t, "ArrowDown")
        self.press(t, "Enter")
        t.wait_for(f"{LST}.locale === 'es-ES'")
        self.assertEqual(t.ev(state), ["false", False, "button"])
        self.assertEqual(t.ev(f"[{btn}.textContent, {loc}.value, location.hash, [...{menu}.querySelectorAll('[aria-selected=true]')].map(o => o.dataset.v)]"),
                         ["es-ES", "es-ES", "#play/es-ES", ["es-ES"]])
        # a click opens it again on es-ES; a press outside closes it and leaves the locale; Tab closes it too
        t.ev(f"{btn}.click()")
        self.assertEqual(t.ev(state), ["true", True, "es-ES"])
        t.ev("document.querySelector('.bd-lst-main').dispatchEvent(new PointerEvent('pointerdown', {bubbles: true}))")
        self.assertEqual(t.ev(state)[:2], ["false", False])
        t.ev(f"{btn}.focus()")
        self.press(t, "ArrowUp")
        self.assertEqual(t.ev(state), ["true", True, "es-ES"])
        self.press(t, "Tab")
        self.assertEqual(t.ev(state)[:2], ["false", False])
        self.assertEqual(t.ev(LST)["locale"], "es-ES")
        # the platform switch keeps the menu showing the locale (the page sets .value, which picks nothing)
        t.ev(f"document.querySelector('{self.TB} [data-p=appstore]').click()")
        self.assertEqual(t.ev(f"[{btn}.textContent, {LST}.locale]"), ["es-ES", "es-ES"])
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
