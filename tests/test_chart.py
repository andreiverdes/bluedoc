"""The chart block: a doc's numbers drawn in the page in HorizonUI's look (kinds stat, line, bar, hbar, donut, progress).

The build checks a chart's kind, its one data list and how many entries it takes, x labels and values in step, finite
numbers (none below 0 for bars, ranked bars, donuts and progress rows), a progress row's max, spark lengths and the tone
palette, each with an error naming the field; every kind of the gallery below builds clean. Under node the template's
pure helpers give nice value axes, numbers with their units and the chart as a table of text. In Chrome
(BLUEDOC_BROWSER_TESTS=1) each kind draws, in a served page and in a `build.py -o` file, in the dark and the light
theme with theme colours; a legend pill hides its series and the value axis follows; a donut's legend row hides its
part and the total follows; hovering a point (or the arrow keys on the focused plot) shows the x label and each
series' value, and a bar's total; a compare view marks a changed chart Changed with its moved values; and the Markdown
export holds a chart's numbers as a table."""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import time
import unittest

from _support import TempHome, template_slice
import test_doc_export as export
from test_page_state import CHROME, ChromePage, Tab

import build

NODE = shutil.which("node")
P50 = [195, 197, 193, 199, 198, 196, 201, 205, 203, 202, 206, 203, 207, 209]
P95 = [398, 402, 395, 410, 406, 401, 414, 418, 411, 410, 422, 416, 420, 419]
DAYS = [f"Oct {i}" for i in range(1, 15)]
LINE = {"type": "chart", "kind": "line", "title": "Checkout latency, p50 and p95", "unit": "ms", "x": DAYS,
        "series": [{"id": "p50", "label": "p50", "values": P50, "area": True}, {"id": "p95", "label": "p95", "values": P95, "tone": "warning"}],
        "caption": "Daily. Shaded: p50."}
BAR = {"type": "chart", "kind": "bar", "title": "Orders by channel", "unit": "orders", "x": [f"Week {i}" for i in range(37, 43)],
       "series": [{"label": "Web", "values": [3840, 3970, 3900, 4120, 4310, 4180]}, {"label": "iOS", "values": [2620, 2710, 2700, 2880, 3020, 2960]},
                  {"label": "Android", "values": [1710, 1790, 1770, 1900, 2020, 1980]}]}
STAT = {"type": "chart", "kind": "stat", "title": "Checkout, last 14 days", "sub": "Oct 1–14", "x": DAYS,
        "stats": [{"label": "Orders", "value": 18420, "delta": "+4.1%", "spark": [1180, 1200, 1150, 1240, 1302, 1330, 1290, 1310, 1350, 1390, 1360, 1320, 1290, 1440]},
                  {"label": "p95 checkout", "value": 430, "unit": "ms", "delta": "+20 ms", "good": "down", "spark": P95},
                  {"label": "Refunds", "value": 1.2, "unit": "%", "delta": "0.0%"}]}
HBAR = {"type": "chart", "kind": "hbar", "title": "Edits by project", "unit": "edits",
        "items": [{"label": "acme-web", "value": 28}, {"label": "acme-shop", "value": 33}, {"label": "acme-docs", "value": 7}]}
DONUT = {"type": "chart", "kind": "donut", "title": "Docs by type", "unit": "docs",
         "items": [{"label": "Plans", "value": 92}, {"label": "Reviews", "value": 35}, {"label": "Docs", "value": 28}, {"label": "Other", "value": 61}]}
PROGRESS = {"type": "chart", "kind": "progress", "title": "Release 4.2 readiness", "sub": "Nov 14",
            "items": [{"label": "Tests", "value": 412, "max": 430}, {"label": "Docs", "value": 6, "max": 6},
                      {"label": "Crash-free sessions", "value": 99.2, "max": 99.5, "unit": "%", "tone": "warning", "note": "0.3 short"}]}
KINDS = {"stat": STAT, "line": LINE, "bar": BAR, "hbar": HBAR, "donut": DONUT, "progress": PROGRESS}


def gallery() -> dict:
    """A doc with one section per chart kind, the section's id the kind."""
    return {"id": "chart-gallery", "title": "Chart gallery", "meta": {"type": "other"},
            "sections": [{"id": k, "title": k.title(), "blocks": [copy.deepcopy(b)]} for k, b in KINDS.items()]}


def errors(block: dict) -> list[str]:
    doc = {"id": "c", "title": "C", "meta": {"type": "other"}, "sections": [{"id": "s", "title": "S", "blocks": [block]}]}
    return build.validate(doc, None, write_cache=False).errors


def changed(block: dict, **fields) -> dict:
    out = copy.deepcopy(block)
    for k, v in fields.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = v
    return out


class Validation(unittest.TestCase):
    def test_every_kind_builds_clean(self) -> None:
        for kind, block in KINDS.items():
            with self.subTest(kind=kind):
                self.assertEqual(errors(block), [])
        rep = build.validate(gallery(), None, write_cache=False)
        self.assertEqual((rep.errors, rep.warnings), ([], []))
        self.assertEqual(errors(changed(BAR, stacked=True)), [])
        self.assertEqual(errors({**LINE, "series": [{"label": "Δ", "values": [-3, 4]}], "x": ["a", "b"]}), [], "a line may go below 0")

    def test_a_bad_chart_is_an_error_naming_its_field(self) -> None:
        # (block, the field the error names, below the block, and what it says)
        cases = {
            "unknown kind": (changed(LINE, kind="pie"), ".kind", "no chart kind"),
            "no kind": (changed(LINE, kind=None), "", "missing required field 'kind'"),
            "no title": (changed(LINE, title=None), "", "missing required field 'title'"),
            "values off x": (changed(LINE, series=[{"label": "p50", "values": P50[:-1]}]), ".series[0].values", "13 values for 14 x labels"),
            "five series": (changed(BAR, series=[{"label": str(i), "values": [1] * 6} for i in range(5)]), ".series", "1 to 4 entries"),
            "one x label on a line": (changed(LINE, x=["Oct 1"], series=[{"label": "p", "values": [1]}]), ".x", "2 to 60 labels"),
            "61 points": (changed(LINE, x=[str(i) for i in range(61)], series=[{"label": "p", "values": [1] * 61}]), ".x", "2 to 60 labels"),
            "negative bar": (changed(BAR, series=[{"label": "Web", "values": [1, 2, -3, 4, 5, 6]}]), ".series[0].values", "starts at 0"),
            "a string value": (changed(LINE, series=[{"label": "p", "values": ["1"] * 14}]), ".series[0].values[0]", "must be a number"),
            "hex tone": (changed(LINE, series=[{"label": "p", "values": P50, "tone": "#ff0000"}]), ".series[0].tone", "never hex"),
            "items on a line": (changed(LINE, items=[{"label": "a", "value": 1}]), ".items", "reads 'series', not 'items'"),
            "x on a donut": (changed(DONUT, x=["a"]), ".x", "no x labels"),
            "stacked line": (changed(LINE, stacked=True), ".stacked", "bar chart only"),
            "area on a bar": (changed(BAR, series=[{"label": "Web", "values": [1] * 6, "area": True}]), ".series[0].area", "line chart's series only"),
            "two series one id": (changed(LINE, series=[{"label": "p 50", "values": P50}, {"label": "P-50", "values": P95}]), ".series[1]", "share the id 'p-50'"),
            "progress without max": (changed(PROGRESS, items=[{"label": "Tests", "value": 4}]), ".items[0]", "missing required field 'max'"),
            "progress max 0": (changed(PROGRESS, items=[{"label": "Tests", "value": 4, "max": 0}]), ".items[0].max", "above 0"),
            "max on a donut": (changed(DONUT, items=[{"label": "a", "value": 1, "max": 2}, {"label": "b", "value": 1}]), ".items[0].max", "progress rows"),
            "one part": (changed(DONUT, items=[{"label": "a", "value": 1}]), ".items", "2 to 8 entries in 'items'; it has 1"),
            "empty donut": (changed(DONUT, items=[{"label": "a", "value": 0}, {"label": "b", "value": 0}]), ".items", "add up to 0"),
            "five stats": (changed(STAT, stats=[{"label": str(i), "value": i} for i in range(5)]), ".stats", "1 to 4 entries"),
            "spark off x": (changed(STAT, stats=[{"label": "Orders", "value": 1, "spark": [1, 2, 3]}]), ".stats[0].spark", "3 numbers for 14 x labels"),
            "bad trend": (changed(STAT, x=None, stats=[{"label": "Orders", "value": 1, "trend": "sideways"}]), ".stats[0].trend", "up|down|flat"),
            "bad good": (changed(STAT, x=None, stats=[{"label": "Orders", "value": 1, "good": "left"}]), ".stats[0].good", "up or down"),
        }
        for name, (block, where, says) in cases.items():
            with self.subTest(case=name):
                errs = errors(block)
                self.assertTrue(any(e.startswith(f"ERROR sections[0].blocks[0]{where}: ") and says in e for e in errs), errs)

    def test_a_chart_may_sit_in_a_checklist_item(self) -> None:
        item = {"id": "load", "text": "Check the load", "blocks": [copy.deepcopy(BAR)]}
        self.assertEqual(errors({"type": "checklist", "id": "c", "title": "Checks", "items": [item]}), [])

    def test_schema_prints_the_card(self) -> None:
        r = TempHome()
        try:
            out = r.run("build.py", "schema", "chart")
        finally:
            r.cleanup()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith("chart: "))
        for s in ("stat|line|bar|hbar|donut|progress", "accent|success|warning|danger|violet|teal|rose|lime|cyan|muted", "e.g. {\"type\":\"chart\""):
            self.assertIn(s, out.stdout)


@unittest.skipUnless(NODE, "node not installed")
class Helpers(unittest.TestCase):
    def run_js(self, expr: str):
        src = template_slice("const CH_KINDS = ", "// a tooltip in box")
        js = f"const chunk = require('fs').readFileSync(0, 'utf8'); eval(chunk + ';globalThis.__out = ' + {json.dumps(expr)}); console.log(JSON.stringify(globalThis.__out));"
        r = subprocess.run([NODE, "-e", js], input=src, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_value_axes_numbers_and_rows(self) -> None:
        self.assertEqual(self.run_js("[chScale(0, 430).ticks, chScale(0, 4310).ticks, chScale(0, 209).ticks, chScale(-3, 4).ticks]"),
                         [[0, 150, 300, 450], [0, 1500, 3000, 4500], [0, 80, 160, 240], [-5, -2.5, 0, 2.5, 5]])
        self.assertEqual(self.run_js("[chTick(4500), chTick(1500000), chTick(80), chFmt(18420), chFmt(99.98), chU('430', 'ms'), chU('1.2', '%'), chU('33', 'edits'), chPct(3, 400)]"),
                         ["4.5k", "1.5M", "80", "18,420", "99.98", "430 ms", "1.2%", "33", "<1%"])
        rows = self.run_js(f"[chartRows({json.dumps(LINE)}), chartRows({json.dumps(DONUT)}), chartRows({json.dumps(PROGRESS)})]")
        self.assertEqual(rows[0]["cols"], ["", "p50", "p95"])
        self.assertEqual(rows[0]["rows"][9], ["Oct 10", "202 ms", "410 ms"])
        self.assertEqual(rows[1]["rows"][0], ["Plans", "92", "43%"])
        self.assertEqual(rows[2]["rows"][2], ["Crash-free sessions", "99.2", "99.5 %"])


PLOT = "document.querySelector('#{} .bp-ch-plot')"
TIP = "(t => t && !t.hidden ? t.textContent : null)(document.querySelector('#{} .bp-ch-tip'))"


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class Drawn(ChromePage):
    def setUp(self) -> None:
        super().setUp()
        self.doc = self.docs / "chart-gallery.bluedoc.json"
        self.doc.write_text(json.dumps(gallery(), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    def mouse_at(self, t: Tab, expr: str) -> None:
        """Move the mouse to the centre of the element expr names, scrolled into view."""
        t.ev(f"{expr}.scrollIntoView({{ block: 'center', behavior: 'instant' }})")
        time.sleep(0.2)
        r = t.ev(f"(r => [r.left + r.width / 2, r.top + r.height / 2])({expr}.getBoundingClientRect())")
        self.browser.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": r[0], "y": r[1]}, t.session)
        time.sleep(0.2)

    def assert_drawn(self, t: Tab) -> None:
        t.wait_for("document.querySelectorAll('#line .bp-ch-plot svg path.ln').length === 2")
        got = t.ev("""({
          line: [document.querySelectorAll('#line path.ln').length, document.querySelectorAll('#line path.area').length,
                 [...document.querySelectorAll('#line .bp-ch-plot text')].map(x => x.textContent).filter(s => /^\\d/.test(s))],
          bar: [...document.querySelectorAll('#bar g[data-x]')].map(g => g.querySelectorAll('path').length),
          stat: [...document.querySelectorAll('#stat .bp-ch-st')].map(c => [c.querySelector('.bp-ch-sl').textContent, c.querySelector('.bp-ch-sv b').textContent,
                 (c.querySelector('.bp-ch-dp') || {}).className || '', !!c.querySelector('svg.bp-ch-sp')]),
          hbar: [...document.querySelectorAll('#hbar .bp-ch-eb')].map(r => r.textContent),
          donut: [document.querySelectorAll('#donut .bp-ch-ring circle').length, document.querySelector('#donut .bp-ch-ring .c b').textContent,
                  document.querySelector('#donut .bp-ch-h .u').textContent],
          progress: [...document.querySelectorAll('#progress .bp-ch-pb')].map(r => [r.querySelector('.v').textContent, r.querySelector('.tr i').style.getPropertyValue('--w')]),
          table: document.querySelector('#line table.bp-sr tbody tr').textContent })""")
        self.assertEqual(got["line"], [2, 1, ["0", "150", "300", "450"]])
        self.assertEqual(got["bar"], [3] * 6)
        self.assertEqual(got["stat"], [["Orders", "18,420", "bp-ch-dp ok", True], ["p95 checkout", "430", "bp-ch-dp bad", True],
                                       ["Refunds", "1.2", "bp-ch-dp flat", False]])
        self.assertEqual(got["hbar"], ["acme-shop33", "acme-web28", "acme-docs7"], "biggest first")
        self.assertEqual(got["donut"], [4, "216", "216 docs"])
        self.assertEqual(got["progress"], [["412 of 43096%", "95.8%"], ["6 of 6Done", "100%"], ["99.2 of 99.5 %0.3 short", "99.7%"]])
        self.assertEqual(got["table"], "Oct 1195 ms398 ms")

    def test_each_kind_draws_served_and_in_an_o_file_in_both_themes(self) -> None:
        t = self.open(self.server.url_for(self.doc))
        self.assert_drawn(t)
        # theme colours: a series' stroke and the plot's surface follow the theme
        look = "(() => { const l = getComputedStyle(document.querySelector('#line path.ln')).stroke, f = getComputedStyle(document.querySelector('#line .bp-chart')).backgroundColor; return [l, f]; })()"
        t.ev("document.documentElement.dataset.theme = 'dark'")
        dark = t.ev(look)
        t.ev("document.documentElement.dataset.theme = 'light'")
        light = t.ev(look)
        self.assertNotEqual(dark[0], light[0])
        self.assertNotEqual(dark[1], light[1])
        self.assertTrue(all(c.startswith(("rgb", "oklch", "color")) for c in dark + light), dark + light)
        # an -o file: no server, the same drawing
        out = self.tmp.dir / "gallery.html"
        r = self.tmp.run("build.py", self.doc, "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        t.go(out.as_uri())
        self.assert_drawn(t)
        # a phone: still the whole chart inside the window, grouped bars stacked
        self.browser.call("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 2, "mobile": True}, t.session)
        t.wait_for("document.querySelector('#bar .bp-ch-plot svg').getAttribute('width') < 360")
        self.assertEqual(t.ev("[...document.querySelectorAll('.bp-chart')].every(c => c.getBoundingClientRect().right <= innerWidth)"), True)
        self.assertEqual(t.ev("document.querySelectorAll('#bar g[data-x=\"0\"] path').length"), 3)
        self.assertEqual(t.ev("(p => new Set(p.map(x => x.getBBox().x)).size)([...document.querySelectorAll('#bar g[data-x=\"0\"] path')])"), 1, "stacked: one column")
        self.assertEqual(self.browser.errors, [])

    def test_the_legend_hides_a_series_and_the_axis_follows(self) -> None:
        t = self.open(self.server.url_for(self.doc))
        t.wait_for(f"{PLOT.format('line')}.querySelectorAll('path.ln').length === 2")
        chip = "document.querySelector('#line .bp-ch-li[data-series=\"p95\"]')"
        t.ev(f"{chip}.click()")
        self.assertEqual(t.ev(f"[{chip}.getAttribute('aria-pressed'), [...document.querySelectorAll('#line g[data-series]')].map(g => g.dataset.series),"
                              " [...document.querySelectorAll('#line .bp-ch-plot text')].map(x => x.textContent).filter(s => /^\\d/.test(s))]"),
                         ["false", ["p50"], ["0", "80", "160", "240"]])
        t.ev(f"{chip}.click()")
        self.assertEqual(t.ev("document.querySelectorAll('#line g[data-series]').length"), 2)
        # a donut's legend row hides its part; the total and the shares follow
        t.ev("document.querySelector('#donut .bp-ch-dli[data-part=\"0\"]').click()")
        self.assertEqual(t.ev("[document.querySelector('#donut .bp-ch-ring .c b').textContent, document.querySelectorAll('#donut .bp-ch-ring circle').length,"
                              " document.querySelector('#donut .bp-ch-dli[data-part=\"1\"] span').textContent]"), ["124", 3, "61 · 49%"])
        self.assertEqual(self.browser.errors, [])

    def test_hovering_a_point_shows_its_values(self) -> None:
        t = self.open(self.server.url_for(self.doc))
        t.wait_for(f"{PLOT.format('line')}.querySelectorAll('path.ln').length === 2")
        self.assertIsNone(t.ev(TIP.format("line")))
        self.mouse_at(t, "document.querySelector('#line g[data-series=\"p95\"] circle.dot')")
        self.assertEqual(t.ev(TIP.format("line")), "Oct 14p50209 msp95419 ms")
        self.assertEqual(t.ev("[document.querySelectorAll('#line circle.hdot').length, document.querySelector('#line text.on').textContent]"), [2, "Oct 14"])
        # bars: the hovered group lit, the others dimmed, the total in the tooltip
        self.mouse_at(t, "document.querySelector('#bar g[data-x=\"4\"]')")
        self.assertEqual(t.ev(TIP.format("bar")), "Week 41Web4,310iOS3,020Android2,020Total9,350")
        self.assertEqual(t.ev("document.querySelectorAll('#bar g[data-x].dim').length"), 5)
        # ranked bars and progress rows: the row's value and its share
        self.mouse_at(t, "document.querySelector('#hbar .bp-ch-eb[data-item=\"1\"]')")
        self.assertEqual(t.ev(TIP.format("hbar")), "acme-webCount28 editsShare41%")
        self.mouse_at(t, "document.querySelector('#donut .bp-ch-dli[data-part=\"1\"]')")
        self.assertEqual(t.ev(TIP.format("donut")), "OtherCount61 docsShare28%")
        self.mouse_at(t, "document.querySelector('#progress .bp-ch-pb[data-item=\"0\"]')")
        self.assertEqual(t.ev(TIP.format("progress")), "TestsReady412 of 430To go18Complete96%")
        # the keyboard: focus the plot, arrows step, Esc clears
        self.browser.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 2, "y": 2}, t.session)
        t.ev(f"{PLOT.format('line')}.focus()")
        for key in ("Home", "ArrowRight"):
            t.ev(f"{PLOT.format('line')}.dispatchEvent(new KeyboardEvent('keydown', {{ key: '{key}', bubbles: true }}))")
        self.assertEqual(t.ev(TIP.format("line")), "Oct 2p50197 msp95402 ms")
        t.ev(f"{PLOT.format('line')}.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Escape', bubbles: true }}))")
        self.assertIsNone(t.ev(TIP.format("line")))
        self.assertEqual(self.browser.errors, [])

    def test_a_compare_view_marks_a_changed_chart(self) -> None:
        status = self.docs / "acme-status.bluedoc.json"
        r = self.tmp.run("build.py", "patch", status, "block:numbers/1", "--set", "series/w41/values=[2510,2630,2702,2400,2790,2810,2390]",
                         "--change", "Thursday's orders corrected from the warehouse export.")
        self.assertEqual(r.returncode, 0, r.stderr)
        url = self.server.url_for(status)
        t = self.open(url)
        t.go(f"{self.base}{url}?diff=2")
        block = "document.querySelector('.bp-block[data-bk=\"numbers/1\"]')"
        t.wait_for(f"{block}.classList.contains('bd-chg-mod')")
        self.assertEqual(t.ev(f"[{block}.querySelector('.bd-chg-tag').textContent, {block}.querySelector('.bd-chgbox dt').textContent,"
                              f" {block}.querySelector('.bd-chgbox dd del').textContent, {block}.querySelector('.bd-chgbox dd ins').textContent,"
                              f" {block}.querySelector('.bd-chgbox dd').textContent.startsWith('Thu')]"),
                         ["Changed", "Week 41", "2,588", "2,400", True])
        self.assertFalse(t.ev("document.querySelector('.bp-block[data-bk=\"numbers/2\"]').classList.contains('bd-chg')"), "the stat chart didn't change")
        self.assertEqual(self.browser.errors, [])

    def test_the_markdown_export_holds_a_charts_numbers_as_a_table(self) -> None:
        t = self.open(self.server.url_for(self.docs / "acme-status.bluedoc.json"))
        self.assertTrue(t.ev(export.EXPORT_SPY) and t.ev(export.TEXT_SPY))
        t.ev(f"{export.ExportKey.BTN}.click()")
        t.ev(f"{export.ExportKey.MENU}.querySelector('[data-format=md]').click()")
        t.wait_for("__texts.length")
        lines = t.ev("__texts[0]").split("\n")
        at = lines.index("### Orders per day")
        self.assertEqual(lines[at + 2:at + 5], ["|  | Week 41 | Week 40 |", "|---|---|---|", "| Mon | 2,510 | 2,440 |"])
        self.assertIn("| Refunds | 1.2 % | 0.0 pt |", lines)
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
