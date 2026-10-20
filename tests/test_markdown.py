"""Markdown in md and inline md fields: one renderer, the page's md() / inline() (template.html), mirrored by serve.py
md_html() / md_inline() for the deck file's speaker notes. tests/fixtures/markdown-cases.json is the shared table of cases
(Markdown in, HTML out) both must produce: paragraphs, hard breaks, nested, numbered and task lists, headings, fenced
code, quotes, rules, GFM tables (alignment, no outer pipes, `\\|`, a pipe in code, ragged rows, right after a paragraph),
code spans, strong, em, strike, `_` in snake_case, links, autolinks, bare URLs, escapes, and XSS attempts. Python runs
them always, node when it is installed, and headless Chrome (BLUEDOC_BROWSER_TESTS=1), where a 50 KB adversarial string
of each kind renders in under 200 ms and the reply of a checklist item draws its table. The linter reads a table's
cells and skips fenced code."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
import unittest

from _support import REPO, TempHome, template_slice
from test_page_state import CHROME, ChromePage, Tab

import build
import serve

CASES = json.loads((REPO / "tests" / "fixtures" / "markdown-cases.json").read_text(encoding="utf-8"))["cases"]
NODE = shutil.which("node")
RENDERER = template_slice("/* ---------- markdown ---------- */", "/* ---------- storage ---------- */")
# evaluated in a blank tab or under node: the template's renderer as `globalThis.MD`
LOAD_JS = "globalThis.MD = new Function(%s + '\\nreturn { md, inline };')(); true"
BUDGET_MS = 200
SIZE = 50_000


def fill(unit: str) -> str:
    return (unit * (SIZE // len(unit) + 1))[:SIZE]


# 50 KB each of the shapes that make a backtracking renderer go quadratic or worse
ADVERSARIAL = {
    "unclosed strong": fill("**a "), "brackets": fill("["), "link openers": fill("[a]("), "underscores": fill("_a"),
    "stars": fill("*a"), "tildes": fill("~~a "), "space run": "a" + " " * (SIZE - 2) + "b", "angles": "<" + fill("a"),
    "backtick runs": "".join("`" * k + " " for k in range(1, 400))[:SIZE], "url parens": "https://" + fill("a(")[:SIZE - 8],
    "table rows": "| a | b |\n|---|---|\n" + fill("| `x` \\| y | z |\n"), "quote markers": fill("> "), "list markers": fill("- "),
    "hard breaks": fill("a  \n"), "fences": fill("```\n"), "hashes": "# " + fill("#"), "mixed": fill("**_~~`[<https://a_b>](x) "),
}

SHOT = next(c["md"] for c in CASES if c["name"] == "the reply in the screenshot")


def rendered(fn: str, src: str) -> str:
    return serve.md_html(src) if fn == "md" else serve.md_inline(src)


class SharedCases(unittest.TestCase):
    def test_the_fixture_covers_every_construct(self) -> None:
        self.assertGreaterEqual(len(CASES), 40)
        html = "".join(c["html"] for c in CASES)
        for tag in ("<table", "<thead>", "<tbody>", 'style="text-align:center"', "<ul>", "<ol start=", "bd-task", "<h4",
                    "<h5", "<h6", "<blockquote>", "<hr>", "<pre><code>", "<code>", "<strong>", "<em>", "<del>", "<br>",
                    'data-node="', 'target="_blank"', 'href="#"'):
            self.assertIn(tag, html)

    def test_serve_py_renders_every_case_as_the_page(self) -> None:
        for c in CASES:
            with self.subTest(c["name"]):
                self.assertEqual(rendered(c["fn"], c["md"]), c["html"])

    @unittest.skipUnless(NODE, "node not installed")
    def test_the_template_renders_every_case_under_node(self) -> None:
        js = ("const {code, cases} = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
              "const r = new Function(code + '\\nreturn { md, inline };')();"
              "process.stdout.write(JSON.stringify(cases.map(c => r[c.fn](c.md))));")
        out = subprocess.run([NODE, "-e", js], input=json.dumps({"code": RENDERER, "cases": CASES}), capture_output=True,
                             text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        for c, got in zip(CASES, json.loads(out.stdout)):
            with self.subTest(c["name"]):
                self.assertEqual(got, c["html"])

    def test_no_raw_html_and_no_script_urls(self) -> None:
        for c in CASES:
            if c["name"].startswith("XSS"):
                with self.subTest(c["name"]):
                    self.assertNotRegex(c["html"], r"<(script|img|i |b>)|<[^>]* on[a-z]+=|href=\"[^\"]*javascript")

    def test_serve_py_stays_linear(self) -> None:
        for name, src in ADVERSARIAL.items():
            with self.subTest(name):
                t = time.perf_counter()
                serve.md_html(src)
                serve.md_inline(src)
                self.assertLess(time.perf_counter() - t, 2.0, f"{name}: Python took over 2 s on 50 KB")


class LintReadsMarkdown(unittest.TestCase):
    """Tables and code fences in md don't trip the CRISP lint: a long row isn't one sentence, numbered lines and
    filler words in code aren't prose."""

    def lint(self, text: str) -> list[str]:
        rep = build.Report()
        build.lint_text(rep, "x", text)
        return rep.warnings

    def test_a_table_row_is_cells_not_a_sentence(self) -> None:
        cells = " | ".join(f"`col{i}` holds a short value" for i in range(8))
        self.assertEqual(self.lint(f"| {cells} |\n|{'---|' * 8}\n| {cells} |"), [])

    def test_fenced_code_is_not_prose(self) -> None:
        code = "```sh\n" + "echo " + "word " * 40 + "\n1. a\n2. b\n3. c\n```"
        self.assertEqual(self.lint(code), [])
        doc = {"id": "acme-md-lint", "title": "Acme lint", "meta": {"type": "other", "rev": "1"}, "tldr": "Fences hold code.",
               "sections": [{"id": "s", "title": "Setup", "blocks": [{"type": "text", "md": code}]}]}
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        path = tmp.dir / "acme-md-lint.bluedoc.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        r = tmp.run("build.py", path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("numbered list", r.stderr)
        self.assertNotIn("words (>", r.stderr)

    def test_a_link_in_fenced_code_is_no_link(self) -> None:
        doc = {"id": "acme-md-fence", "title": "Acme fence", "meta": {"type": "other", "rev": "1"}, "tldr": "Code shows a link.",
               "sections": [{"id": "s", "title": "Setup", "blocks": [{"type": "text", "md": "```md\n[x](javascript:alert(1))\n```"}]}]}
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        path = tmp.dir / "acme-md-fence.bluedoc.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        r = tmp.run("build.py", path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("javascript", r.stderr)


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class MarkdownInChrome(ChromePage):
    def blank(self) -> Tab:
        t = Tab(self.browser)
        t.ev(LOAD_JS % json.dumps(RENDERER))
        return t

    def test_the_page_renders_every_case(self) -> None:
        t = self.blank()
        got = t.ev(f"{json.dumps(CASES)}.map(c => MD[c.fn](c.md))")
        for c, html in zip(CASES, got):
            with self.subTest(c["name"]):
                self.assertEqual(html, c["html"])

    def test_50_kb_of_adversarial_text_renders_in_under_200_ms(self) -> None:
        t = self.blank()
        t.ev(f"MD.md({json.dumps(fill('warm *up* `x` | y'))})")
        for name, src in ADVERSARIAL.items():
            with self.subTest(name):
                ms = t.ev(f"(s => {{ const t = performance.now(); MD.md(s); MD.inline(s); return performance.now() - t; }})({json.dumps(src)})")
                self.assertLess(ms, BUDGET_MS, f"{name}: {ms:.0f} ms")

    def test_a_reply_with_a_table_draws_the_table_in_its_checklist_item(self) -> None:
        doc = {"id": "acme-md-reply", "title": "Acme advisor review", "meta": {"type": "other", "rev": "2"},
               "tldr": "Four code findings need a fix lane.",
               "sections": [{"id": "lane", "title": "Fix lane", "blocks": [{"type": "checklist", "id": "lane", "title": "Decisions", "items": [
                   {"id": "start", "text": "Start a fix lane for the code findings in the advisor review?",
                    "sub": "Ban/suspend control, report abuse limits, fail-closed safety startup, bypass guard: code, not plan text.",
                    "choices": [{"id": "now", "label": "Start now", "md": "The fix lane starts today, before your picks below."},
                                {"id": "after", "label": "After your picks below", "md": "The fix lane waits for your picks below, then starts."}],
                    "recommend": "after", "detail": SHOT}]}]}]}
        path = self.docs / "acme-md-reply.bluedoc.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        tab = self.open(self.server.url_for(path))
        tab.ev("document.querySelector('#item-lane-start .bp-cl-head').click()")
        got = tab.wait_for("(d => d && d.querySelector('table') && {"
                           "cols: d.querySelectorAll('thead th').length, rows: d.querySelectorAll('tbody tr').length,"
                           "codes: [...d.querySelectorAll('tbody tr')].map(r => r.cells[0].querySelector('code')?.textContent),"
                           "wide: getComputedStyle(d.querySelector('table').parentElement).overflowX,"
                           "paras: d.querySelectorAll(':scope > p').length, raw: d.textContent.includes('|---|')})"
                           "(document.querySelector('#item-lane-start .bp-cl-detail'))")
        self.assertEqual(got, {"cols": 2, "rows": 4, "codes": ["mod-fail-open", "ban-control", "reports-abuse", "bypass-guard"],
                               "wide": "auto", "paras": 2, "raw": False})
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
