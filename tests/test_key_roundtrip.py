"""Key round trip (mnt/three-grammars): every key the annotator's keyOf can emit on the examples resolves in
`build.py patch`, and the docs list the same key forms.

keyOf (template.html) builds keys from the rendered page; `keys_of` below lists the same keys from the doc
JSON, one rule per keyOf case. KeyOfForms pins that case list to the template, so a new key form fails here
until keys_of, resolve_key and the docs learn it."""
from __future__ import annotations

import copy
import json
import re
import unittest

from _support import EXAMPLE_STEMS, SKILL, TempHome, load_json, template_text

import build
import diffref


def keyof_source() -> str:
    t = template_text()
    i = t.index("function keyOf(")
    return t[i:t.index("\n  }\n", i)]


def keyof_forms() -> tuple[set[str], set[str]]:
    """(forms keyOf builds with a `case`, forms it returns bare). typeOf returns a SEL key or 'doc'; keyOf's
    default branch returns the type itself."""
    t = template_text()
    sel = re.search(r"const SEL = \{(.*?)\};", t, re.S)
    assert sel, "template has no `const SEL = {…};`: update this test"
    types = set(re.findall(r"(\w+):\s*'", sel.group(1))) | {"doc"}
    cased = set(re.findall(r"case '(\w+)':", keyof_source()))
    return cased, types - cased


def blocks_with_paths(doc: dict):
    """(blockPath, block) for every block, as keyOf's pathOf writes the path: <section>/<i> at the top level,
    <checklist>/<item>/<k> inside a checklist item (nested checklists too)."""
    def items(cl: dict):
        for it in cl.get("items") or []:
            for k, kb in enumerate(it.get("blocks") or []):
                yield f"{cl['id']}/{it['id']}/{k}", kb
                if kb.get("type") == "checklist":
                    yield from items(kb)
    for s in doc.get("sections") or []:
        for i, b in enumerate(s.get("blocks") or []):
            yield f"{s['id']}/{i}", b
            if b.get("type") == "checklist":
                yield from items(b)


def node_paths(scope: dict, prefix: tuple = ()):
    for n in scope.get("nodes") or []:
        p = prefix + (n["id"],)
        yield "/".join(p)
        if isinstance(n.get("children"), dict):
            yield from node_paths(n["children"], p)


def diff_line_keys(d: dict):
    """line:<diff>/<path>:<n>, or :o<n> for a removed line, for every line the diff shows (d.sel is the open file)."""
    for f in d.get("files") or []:
        for hk in f.get("hunks") or []:
            o, n = hk.get("old", 1), hk.get("new", 1)
            for line in hk.get("lines") or []:
                t = line[:1]
                yield f"line:{d['id']}/{f['path']}:" + (f"o{o}" if t == "-" else str(n)), f["path"], ("old" if t == "-" else "new"), (o if t == "-" else n)
                if t != "+":
                    o += 1
                if t != "-":
                    n += 1


def md_parts(src: str) -> int:
    """How many <p> and <li> the template's md() makes of src (keyOf's para index runs over them)."""
    n = 0
    for block in re.split(r"\n\s*\n", src.strip()):
        lines = [l for l in block.split("\n") if l.strip()]
        if lines and (all(re.match(r"\s*[-*] ", l) for l in lines) or all(re.match(r"\s*\d+[.)] ", l) for l in lines)):
            n += len(lines)
        else:
            n += 1
    return n


def keys_of(doc: dict, expanded: dict) -> dict[str, list[str]]:
    """form -> the keys keyOf emits for doc. expanded is doc with its diff refs filled (the page shows those)."""
    out: dict[str, list[str]] = {f: [] for f in ("doc", "header", "status")}
    add = lambda form, key: out.setdefault(form, []).append(key)
    add("doc", "doc"); add("header", "header"); add("status", "status")
    if doc.get("tldr"):
        add("tldr", "tldr")
    for s in doc.get("sections") or []:
        add("section", f"section:{s['id']}")
        add("heading", f"heading:{s['id']}")
        if s.get("lead"):
            add("lead", f"lead:{s['id']}")
    for path, b in blocks_with_paths(doc):
        add("block", f"block:{path}")
        t = b.get("type")
        if t == "text" and b.get("md"):
            for i in range(md_parts(b["md"])):
                add("para", f"para:{path}/{i}")
        elif t == "table":
            for r, _ in enumerate(b.get("rows") or []):
                add("row", f"row:{path}/{r}")
        elif t == "cards":
            for i, _ in enumerate(b.get("items") or []):
                add("card", f"card:{path}/{i}")
        elif t == "steps":
            for st in b.get("items") or []:
                add("step", f"step:{path}/{st['id']}")
        elif t == "files":
            for f in b.get("items") or []:
                add("file", f"file:{path}/{f['path']}")
        elif t == "media":
            add("media", f"media:{path}")
        elif t == "compare":
            for side in ("before", "after"):
                add("compare", f"compare:{path}/{side}")
        elif t == "checklist":
            for it in b.get("items") or []:
                add("item", f"item:{b['id']}/{it['id']}")
        elif t == "canvas":
            for np in node_paths(b):
                add("node", f"node:{b['id']}/{np}")
        elif t == "diff":
            for i, _ in enumerate(b.get("comments") or []):
                add("comment", f"comment:{b['id']}/{i}")
    for _, b in blocks_with_paths(expanded):
        if b.get("type") == "diff":
            for key, *_ in diff_line_keys(b):
                add("line", key)
    return out


def covering_comments(raw_diff: dict, path: str, side: str, n: int) -> list[int]:
    """Indexes of the diff's comments on path whose line range covers n on that side."""
    out = []
    for i, c in enumerate(raw_diff.get("comments") or []):
        c = diffref.parse_comment(c)
        if c.get("file") == path and c.get("line") and c.get("side", "new") == side and c["line"] <= n <= c.get("end", c["line"]):
            out.append(i)
    return out


class KeyOfForms(unittest.TestCase):
    def test_keyof_forms_are_the_known_ones(self) -> None:
        cased, bare = keyof_forms()
        self.assertEqual(cased, {"line", "comment", "row", "node", "step", "file", "media", "compare", "card", "para",
                                 "item", "block", "heading", "lead", "section"},
                         "keyOf's cases changed: teach keys_of (this file), build.resolve_key and the docs the new form")
        self.assertEqual(bare, {"header", "tldr", "status", "doc"})

    def test_docs_list_every_form(self) -> None:
        cased, bare = keyof_forms()
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        line = next(l for l in skill.splitlines() if "**Change requests**" in l)
        listed = set(re.findall(r"`(\w+):?`", line))
        self.assertEqual((cased | bare) - listed, set(), "SKILL.md's Change requests line misses key forms")
        schema = (SKILL / "references" / "schema.md").read_text(encoding="utf-8")
        table = set(re.findall(r"^\| `(\w+)", schema, re.M)) | set(re.findall(r", `(\w+)[:`]", schema))
        self.assertEqual((cased | bare) - table, set(), "schema.md's key table misses key forms")


class KeyRoundTrip(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.docs = self.tmp.copy_examples()
        self.keys: dict[str, dict[str, list[str]]] = {}
        self.raw: dict[str, dict] = {}
        self.lines: dict[str, list[tuple[str, list[int]]]] = {}   # (line key, indexes of the comments covering it)
        for stem in EXAMPLE_STEMS:
            p = self.docs / f"{stem}.bluedoc.json"
            doc = load_json(p)
            expanded = copy.deepcopy(doc)
            problems = diffref.expand_doc(expanded, p, write_cache=False, allow_remote=False)
            self.assertEqual([x for x in problems if x.startswith("ERROR")], [], stem)
            self.raw[stem] = doc
            self.keys[stem] = keys_of(doc, expanded)
            raw_diffs = {b["id"]: b for _, b in blocks_with_paths(doc) if b.get("type") == "diff"}
            self.lines[stem] = [(key, covering_comments(raw_diffs[b["id"]], path, side, n))
                                for _, b in blocks_with_paths(expanded) if b.get("type") == "diff"
                                for key, path, side, n in diff_line_keys(b)]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_examples_cover_every_keyof_form(self) -> None:
        cased, bare = keyof_forms()
        seen = {form for ks in self.keys.values() for form, keys in ks.items() if keys}
        self.assertEqual((cased | bare) - seen, set(), "no example emits these key forms: add them to an example")

    def test_every_key_resolves(self) -> None:
        for stem, forms in self.keys.items():
            doc = self.raw[stem]
            for form, keys in forms.items():
                if form == "line":
                    continue
                for key in keys:
                    with self.subTest(doc=stem, key=key):
                        try:
                            build.resolve_key(copy.deepcopy(doc), key)
                        except build.PatchError as e:
                            self.fail(f"patch {key}: {e}")

    def test_line_keys_resolve_to_their_comment_or_say_why_not(self) -> None:
        """A line a comment covers resolves to that comment; any other line gets its own message, not 'unknown key'."""
        bad: list[str] = []
        n_cov = n_bare = 0
        for stem, lines in self.lines.items():
            for key, cover in lines:
                try:
                    t = build.resolve_key(copy.deepcopy(self.raw[stem]), key)
                except build.PatchError as e:
                    n_bare += 1
                    if cover:
                        bad.append(f"{key}: comments {cover} cover it, but: {e}")
                    elif "unknown key" in str(e):
                        bad.append(f"{key}: generic message, not the line: one: {e}")
                else:
                    n_cov += 1
                    if t.kind != "comment" or t.key not in cover:
                        bad.append(f"{key}: resolved to {t.kind} {t.key!r}, covering comments are {cover}")
        self.assertEqual(bad[:5], [], f"{len(bad)} of {n_cov + n_bare} line keys are wrong (first 5 shown)")
        self.assertGreater(n_cov, 0, "no line key is covered by a comment: the examples lost their line comments")
        self.assertGreater(n_bare, 0, "every line has a comment: the examples no longer exercise the bare-line message")

    def test_one_key_per_form_through_the_cli(self) -> None:
        """`build.py patch` end to end: a no-op merge on one key of each form, on the temp copies. For `line:` the key
        is one a comment covers, so `patch` resolves it to that comment."""
        for form in sorted({f for ks in self.keys.values() for f in ks}):
            if form == "line":
                stem, key = next((s, k) for s, lines in self.lines.items() for k, cover in lines if cover)
            else:
                stem, key = next((s, ks[form][0]) for s, ks in self.keys.items() if ks.get(form))
            with self.subTest(form=form, key=key):
                try:
                    target = build.resolve_key(copy.deepcopy(self.raw[stem]), key)
                except build.PatchError as e:
                    self.fail(f"patch {key}: {e}")
                value = json.dumps(target.obj) if isinstance(target.obj, list) else "{}"
                r = self.tmp.run("build.py", "patch", self.docs / f"{stem}.bluedoc.json", key, "--json", value, "--no-bump")
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_bare_line_key_cli_message(self) -> None:
        stem, key = next((s, k) for s, lines in self.lines.items() for k, cover in lines if not cover)
        r = self.tmp.run("build.py", "patch", self.docs / f"{stem}.bluedoc.json", key, "--set", "note=x")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertNotIn("unknown key", r.stderr)
        self.assertIn("line:", r.stderr)


if __name__ == "__main__":
    unittest.main()
