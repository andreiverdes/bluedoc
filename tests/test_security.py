"""Security corpus, from the reviews' probes (sec/hunk-xss, sec/c0-href, bld/comment-escape, sec/textconv).

`build.validate` must reject the payloads; the template must not turn them into markup when a doc
skips validation (build.build doesn't validate). The page's JSON blocks parse as served when a doc quotes
`<!--` or `</script`. A diff ref never runs a command the repo's git config names (textconv), in a work tree or
in a bare repo inside the docs folder. The template's pure functions (safeUrl, inline, md and the diff
renderer's num) run under node when it is installed; the page-level checks need no node."""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _support import template_slice, template_text

import build
import diffref

HUNK_PAYLOAD = "<img src=x onerror=document.title+='|PWNED'>"
C0_HREF = "\u0001javascript:document.title+='|PWNED';undefined"

# a minimal valid doc with an embedded (not ref) diff and links
BASE_DOC = {
    "id": "acme-probe", "title": "Acme probe", "meta": {"type": "other", "rev": "A"}, "tldr": "Acme probe doc.",
    "links": [{"label": "Acme site", "href": "https://acme.test/x"}, {"label": "Acme orders", "href": "acme-orders.bluedoc.json"},
              {"label": "Acme ops", "href": "mailto:ops@acme.test"}, {"label": "Code", "href": "#code"}],
    "sections": [{"id": "code", "title": "Code", "blocks": [{
        "type": "diff", "id": "d1", "title": "Acme change",
        "files": [{"path": "src/cart.ts", "status": "modified", "hunks": [{"old": 1, "new": 1, "lines": [" a", "-b", "+c"]}]},
                  {"path": "src/new.ts", "status": "added", "hunks": [{"old": 0, "new": 1, "lines": ["+x"]}]}]}]}],
}


def probe(**changes) -> dict:
    d = copy.deepcopy(BASE_DOC)
    hunk = d["sections"][0]["blocks"][0]["files"][0]["hunks"][0]
    for k, v in changes.items():
        if k == "href":
            d["links"][0]["href"] = v
        else:
            hunk[k] = v
            hunk["lines"] = []   # as in the probe: no lines, so nothing does arithmetic on the bad number
    return d


class ValidateRejects(unittest.TestCase):
    def test_probe_base_is_valid(self) -> None:
        rep = build.validate(copy.deepcopy(BASE_DOC))
        self.assertEqual(rep.errors, [])

    def test_non_integer_hunk_numbers(self) -> None:
        for field in ("old", "new"):
            for bad in (HUNK_PAYLOAD, "3", 1.5, True):
                with self.subTest(field=field, value=bad):
                    rep = build.validate(probe(**{field: bad}))
                    self.assertTrue(any("hunks[0]" in e for e in rep.errors), f"no hunk error in {rep.errors}")

    def test_control_prefixed_javascript_href(self) -> None:
        for bad in (C0_HREF, "\u0000javascript:x", "\u001fjavascript:x", " javascript:x", "\tjavascript:x", "JavaScript:x"):
            with self.subTest(href=bad):
                rep = build.validate(probe(href=bad))
                self.assertTrue(any("links" in e for e in rep.errors), f"no links error in {rep.errors}")


class PageDoesNotInject(unittest.TestCase):
    """build.build skips validation, so these hold even for a doc that never went through build.py."""

    def test_hunk_payload_stays_inside_the_json_data_block(self) -> None:
        html = build.build(probe(old=HUNK_PAYLOAD, new=HUNK_PAYLOAD), template_text())
        m = re.search(r'<script type="application/json" id="bp-doc">(.*?)</script>', html, re.S)
        self.assertIsNotNone(m)
        self.assertEqual(json.loads(m.group(1))["sections"][0]["blocks"][0]["files"][0]["hunks"][0]["old"], HUNK_PAYLOAD)
        self.assertNotRegex(m.group(1), r"(?i)</script")
        outside = html[:m.start(1)] + html[m.end(1):]
        self.assertNotIn("onerror=", outside)

    def test_diff_renderer_coerces_hunk_numbers(self) -> None:
        # the renderer builds an HTML string from the hunk header: every read of hk.old / hk.new goes through num()
        t = template_text()
        reads = [m.start() for m in re.finditer(r"\bhk\.(old|new)\b", t)]
        self.assertTrue(reads, "the diff renderer no longer reads hk.old / hk.new: update this test")
        for i in reads:
            self.assertEqual(t[i - 4:i], "num(", f"uncoerced hunk number at template offset {i}: {t[i - 40:i + 20]!r}")

    def test_doc_urls_go_through_safeUrl(self) -> None:
        # every href built from doc data (links[].href, a diff's url) is filtered by safeUrl
        t = template_text()
        sinks = re.findall(r"\bhref:\s*([^,}]+)", t)
        data = [s.strip() for s in sinks if re.search(r"\.(href|url)\b", s) and "location" not in s]
        self.assertTrue(data, "no doc-data href sinks found: update this test")
        for s in data:
            self.assertTrue(s.startswith("safeUrl("), f"href sink {s!r} doesn't go through safeUrl")

    def test_json_blocks_parse_as_served_when_a_doc_quotes_a_comment_opener(self) -> None:
        # a doc that shows HTML: the comment opener and a script close must stay text, and the block valid JSON
        quoted = "<!-- Acme banner -->\n<h1>Acme</h1>\n</script><script>document.title+='|PWNED'</script>"
        doc = copy.deepcopy(BASE_DOC)
        doc["sections"].append({"id": "snippet", "title": "Snippet", "blocks": [{"type": "code", "lang": "html", "code": quoted}]})
        state = {"version": 1, "state": {"code:d1:note": quoted}}
        html = build.build(doc, template_text(), state=state)
        for block_id in ("bp-doc", "bp-state"):
            with self.subTest(block=block_id):
                m = re.search(rf'<script type="application/json" id="{block_id}">(.*?)</script>', html, re.S)
                self.assertIsNotNone(m)
                self.assertNotIn("<!--", m.group(1))
                self.assertNotRegex(m.group(1), r"(?i)</script")
                got = json.loads(m.group(1))   # as the page's JSON.parse reads it: no unescaping first
                text = got["state"]["code:d1:note"] if block_id == "bp-state" else got["sections"][-1]["blocks"][0]["code"]
                self.assertEqual(text, quoted)


GIT = shutil.which("git")


@unittest.skipUnless(GIT, "git not installed")
class DiffRefRunsNoRepoCommand(unittest.TestCase):
    """A repo's config can name a textconv driver: a doc's diff ref must not run it (sec/textconv)."""

    def git(self, *args: str) -> str:
        return subprocess.run([GIT, "-c", "user.name=Acme", "-c", "user.email=dev@acme.test", *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    def test_textconv_driver_does_not_run(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="bluedoc-test-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        work, docs = tmp / "acme-src", tmp / "docs"
        docs.mkdir()
        self.git("init", "-q", str(work))
        (work / ".gitattributes").write_text("*.txt diff=acme\n", encoding="utf-8")
        for text in ("one\n", "two\n"):
            (work / "a.txt").write_text(text, encoding="utf-8")
            self.git("-C", str(work), "add", "-A")
            self.git("-C", str(work), "commit", "-qm", text.strip())
        base, head = self.git("-C", str(work), "rev-parse", "HEAD~1"), self.git("-C", str(work), "rev-parse", "HEAD")
        # the review's probe: a bare repo shipped as plain files inside the docs folder, and a work tree
        bare = docs / "vendored.git"
        self.git("clone", "-q", "--bare", str(work), str(bare))
        (bare / "info").mkdir(exist_ok=True)
        (bare / "info" / "attributes").write_text("*.txt diff=acme\n", encoding="utf-8")
        markers = {"work": tmp / "ran-work", "bare": tmp / "ran-bare"}
        for name, config in (("work", work / ".git" / "config"), ("bare", bare / "config")):
            self.git("config", "--file", str(config), "diff.acme.textconv", f"touch '{markers[name]}'; cat")
        ref = {"type": "diff", "base": base, "head": head}
        doc = {"id": "acme-textconv", "title": "Acme textconv probe", "meta": {"type": "review", "rev": "1"}, "tldr": "Probe.",
               "sections": [{"id": "code", "title": "Code", "blocks": [
                   {**ref, "id": "d-work", "title": "Work tree", "repo": str(work)},
                   {**ref, "id": "d-bare", "title": "Bare repo", "repo": "vendored.git"}]}]}
        doc_path = docs / "acme-textconv.bluedoc.json"
        doc_path.write_text(json.dumps(doc), encoding="utf-8")
        out, _ = diffref.expanded_copy(doc, doc_path, use_cache=False, write_cache=False, allow_remote=False)
        self.assertEqual([n for n, m in markers.items() if m.exists()], [], "git ran the repo's textconv command")
        lines = [ln for f in out["sections"][0]["blocks"][0]["files"] for hk in f["hunks"] for ln in hk["lines"]]
        self.assertEqual(lines, ["-one", "+two"], "the work tree's diff is no longer the plain one")


NODE = shutil.which("node")


def run_node(cases: list) -> list:
    """Evaluate the template's markdown-lite helpers and the diff renderer's num() over cases ([fn, arg])."""
    helpers = template_slice("/* ---------- markdown-lite ---------- */", "/* ---------- storage ---------- */")
    num = re.search(r"const num = x => [^\n]*;", template_text())
    assert num, "the diff renderer's `const num = x => …;` is gone: update this test"
    js = ("const src = require('fs').readFileSync(0, 'utf8'); const {code, cases} = JSON.parse(src);"
          "const fns = new Function(code + '\\nreturn { esc, safeUrl, inline, md, num };')();"
          "process.stdout.write(JSON.stringify(cases.map(([f, a]) => fns[f](a))));")
    r = subprocess.run([NODE, "-e", js], input=json.dumps({"code": helpers + "\n" + num.group(0), "cases": cases}),
                       capture_output=True, text=True, timeout=20)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "node not installed")
class TemplateFunctions(unittest.TestCase):
    BAD = [C0_HREF, "\u0000javascript:x", "\u001fjavascript:alert(1)", " javascript:x", "\tjavascript:x", "java\tscript:x",
           "java\nscript:x", "JAVASCRIPT:x", "data:text/html,x", "vbscript:x", "file:///etc/passwd"]
    GOOD = ["https://acme.test/a?b=1", "http://acme.test", "mailto:ops@acme.test", "#item-t412-tier-boundary",
            "#node:acme-orders/api", "acme-orders.bluedoc.json", "../runbooks/acme.md", "/acme/x"]

    def test_safeUrl_allow_list(self) -> None:
        out = run_node([["safeUrl", u] for u in self.BAD + self.GOOD])
        for u, got in zip(self.BAD, out):
            self.assertEqual(got, "#", f"safeUrl({u!r})")
        for u, got in zip(self.GOOD, out[len(self.BAD):]):
            self.assertEqual(got, u, f"safeUrl({u!r})")

    def test_markdown_links_with_bad_schemes_become_hash(self) -> None:
        srcs = [f"[go]({u})" for u in self.BAD if not any(c.isspace() for c in u)]   # a markdown url has no whitespace
        out = run_node([["inline", s] for s in srcs] + [["md", "Read [the runbook](" + C0_HREF + ") first."]])
        for s, got in zip(srcs, out):
            self.assertEqual(got, '<a href="#">go</a>', f"inline({s!r})")
        self.assertIn('<a href="#">the runbook</a>', out[-1])
        self.assertNotIn("javascript", out[-1])

    def test_inline_escapes_markup(self) -> None:
        out = run_node([["inline", HUNK_PAYLOAD], ["inline", '[x](https://acme.test/"onmouseover="alert(1))']])
        self.assertNotIn("<img", out[0])
        self.assertNotRegex(out[1], r'href="[^"]*"onmouseover')

    def test_num_makes_hunk_numbers_integers(self) -> None:
        vals = [HUNK_PAYLOAD, "12", 3.7, None, {}, "1e3", -2]
        out = run_node([["num", v] for v in vals])
        for v, got in zip(vals, out):
            self.assertIsInstance(got, int, f"num({v!r}) = {got!r}")
        self.assertEqual(out[:2], [0, 12])


if __name__ == "__main__":
    unittest.main()
