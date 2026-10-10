"""Key round trip (mnt/three-grammars): every key the annotator's keyOf can emit on the examples resolves in
`build.py patch`, and the docs list the same key forms.

keyOf (template.html) builds keys from the rendered page; `keys_of` below lists the same keys from the doc
JSON, one rule per keyOf case. KeyOfForms pins that case list to the template, so a new key form fails here
until keys_of, resolve_key and the docs learn it. Design keys: `artboard:`, `frame:` and `link:` come from keyOf on
the Acme Fit example; `el:<artboard>/<data-bd name or CSS path>` comes from the inspector inside a screen frame, and
patch names the screen file and the selector. LinkKeys runs every `link:` op and `layout:` through `build.py patch`:
each rewrites one start tag (or adds or drops one hidden element) and leaves every other byte."""
from __future__ import annotations

import copy
import json
import re
import unittest
from html.parser import HTMLParser

from _support import EXAMPLE_STEMS, SKILL, TempHome, load_json, template_text

import build
import diffref

DESIGN = "acme-fit-design"
STEMS = (*EXAMPLE_STEMS, DESIGN)   # the design example carries the artboard: and frame: forms


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


def keys_of(doc: dict, expanded: dict, doc_path=None) -> dict[str, list[str]]:
    """form -> the keys keyOf emits for doc. expanded is doc with its diff refs filled (the page shows those); doc_path
    lets a design's links be read from its screen files (Point on an arrow: link:<screen>/<element>)."""
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
        elif t == "board":
            for a in b.get("artboards") or []:
                add("artboard", f"artboard:{a['id']}")
            # Frame mode drops a requested frame anywhere on the board: one key per device, at a free spot
            add("frame", "frame:phone@0,2000")
            add("frame", "frame:390x844@-400,-120")
            for ln in build.board_links(doc, doc_path) if doc_path else []:
                add("link", f"link:{ln['from']}/{ln['el']}")
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
                                 "item", "block", "heading", "lead", "section", "artboard", "frame", "link"},
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
        for stem in STEMS:
            p = self.docs / f"{stem}.bluedoc.json"
            doc = load_json(p)
            expanded = copy.deepcopy(doc)
            problems = diffref.expand_doc(expanded, p, write_cache=False, allow_remote=False)
            self.assertEqual([x for x in problems if x.startswith("ERROR")], [], stem)
            self.raw[stem] = doc
            self.keys[stem] = keys_of(doc, expanded, p)
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
                if form == "link":   # a link takes --set: set its kind to the one it has
                    ln = next(l for l in build.board_links(self.raw[stem], self.docs / f"{stem}.bluedoc.json")
                              if key == f"link:{l['from']}/{l['el']}")
                    op = ["--set", f"kind={ln['kind']}"]
                else:
                    op = ["--json", value]
                r = self.tmp.run("build.py", "patch", self.docs / f"{stem}.bluedoc.json", key, *op, "--no-bump")
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_bare_line_key_cli_message(self) -> None:
        stem, key = next((s, k) for s, lines in self.lines.items() for k, cover in lines if not cover)
        r = self.tmp.run("build.py", "patch", self.docs / f"{stem}.bluedoc.json", key, "--set", "note=x")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertNotIn("unknown key", r.stderr)
        self.assertIn("line:", r.stderr)


class _Names(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.names: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        name = dict(attrs).get("data-bd")
        if name:
            self.names.append(name)


def el_keys(doc_path) -> list[tuple[str, str, str]]:
    """(key, screen file name, data-bd name) for every data-bd name used once in its screen file: the key the inspector
    posts for a pick on that element (its shortest unique chain is the name itself)."""
    out = []
    for a in next(b for b in build.all_blocks(load_json(doc_path)) if b.get("type") == "board")["artboards"]:
        if a.get("device") == "icons":   # layers, no screen file
            continue
        f = doc_path.parent / f"{DESIGN}.design" / f"{a['id']}.html"
        p = _Names()
        p.feed(f.read_text(encoding="utf-8"))
        out += [(f"el:{a['id']}/{n}", f.name, n) for n in p.names if p.names.count(n) == 1]
    return out


class ElementKeys(unittest.TestCase):
    """el:<artboard>/<data-bd path> keys come from the inspector inside a screen frame, not from keyOf: each names a
    screen file and a selector, which `build.py patch` prints for the agent to edit."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.doc_path = self.docs / f"{DESIGN}.bluedoc.json"
        self.keys = el_keys(self.doc_path)

    def test_every_named_element_resolves(self) -> None:
        self.assertIn("el:login/submit", [k for k, *_ in self.keys])
        doc = load_json(self.doc_path)
        for key, *_ in self.keys:
            with self.subTest(key=key):
                try:
                    build.resolve_key(copy.deepcopy(doc), key)
                except build.PatchError as e:
                    self.fail(f"patch {key}: {e}")

    def test_patch_names_the_file_and_the_selector(self) -> None:
        for key, file, name in (("el:login/submit", "login.html", "submit"),
                                ('el:login/[data-bd="login"]>h1:nth-of-type(1)', "login.html", None)):
            with self.subTest(key=key):
                r = self.tmp.run("build.py", "patch", self.doc_path, key)
                out = r.stdout + r.stderr
                self.assertIn(file, out)
                self.assertIn(f'[data-bd="{name}"]' if name else 'h1:nth-of-type(1)', out)
                self.assertNotIn("unknown key", out)

    def test_an_unknown_artboard_is_refused(self) -> None:
        with self.assertRaises(build.PatchError):
            build.resolve_key(load_json(self.doc_path), "el:nowhere/submit")


class LinkKeys(unittest.TestCase):
    """link:<screen>/<element> and layout:<board> through `build.py patch` on a copy of Acme Fit."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.doc_path = self.docs / f"{DESIGN}.bluedoc.json"
        self.screens = self.docs / f"{DESIGN}.design"

    def patch(self, key: str, *args: str, code: int = 0):
        r = self.tmp.run("build.py", "patch", self.doc_path, key, *args)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r

    def changed(self, screen: str, before: str) -> tuple[list[str], list[str]]:
        """(lines only before has, lines only the file has now)."""
        a, b = before.splitlines(), (self.screens / screen).read_text(encoding="utf-8").splitlines()
        return [l for l in a if l not in b], [l for l in b if l not in a]

    def link(self, screen: str, el: str) -> dict | None:
        return next((l for l in build.board_links(load_json(self.doc_path), self.doc_path)
                     if l["from"] == screen and l["el"] == el), None)

    def add_to_root(self, screen: str, html: str) -> tuple[str, str]:
        """Put html at the end of the screen's root element; returns (the root's data-bd name, the new text)."""
        f = self.screens / screen
        text = f.read_text(encoding="utf-8")
        tree = build._ScreenTree(text)
        root = next(e for e in tree.els if e["parent"] is None and e["tag"] not in ("style", "script"))
        text = text[:root["close"]] + html + text[root["close"]:]
        f.write_text(text, encoding="utf-8")
        return root["attrs"]["data-bd"], text

    def test_no_op_names_the_file_the_selector_and_the_link(self) -> None:
        out = self.patch("link:today/tab-workouts").stdout
        self.assertIn("today.html", out)
        self.assertIn('[data-bd="tab-workouts"]', out)
        self.assertIn('data-nav="tab:workouts"', out)

    def test_retarget_kind_and_label_rewrite_one_start_tag(self) -> None:
        before = (self.screens / "today.html").read_text(encoding="utf-8")
        self.patch("link:today/tab-workouts", "--set", "to=activity", "--set", "kind=modal", "--set", "label=Tap Workouts",
                   "--change", "Workouts opens Activity.")
        gone, new = self.changed("today.html", before)
        self.assertEqual(len(gone), 1)
        self.assertEqual([gone[0].replace('data-nav="tab:workouts"',
                                          'data-nav="modal:activity" data-nav-label="Tap Workouts"')], new)
        ln = self.link("today", "tab-workouts")
        self.assertEqual((ln["to"], ln["kind"], ln["label"]), ("activity", "modal", "Tap Workouts"))
        h = build.load_history(build.history_path(self.doc_path))
        self.assertEqual(h["revs"][-1]["rev"], load_json(self.doc_path)["meta"]["rev"])
        self.assertIn(ln, h["revs"][-1]["links"], "the new rev records the changed link")
        self.assertNotIn(ln, h["revs"][-2]["links"], "the rev it replaces keeps the old one")

    def test_a_label_alone_and_its_removal(self) -> None:
        self.patch("link:today/tab-activity", "--set", "label=Tap Activity", "--no-bump")
        ln = self.link("today", "tab-activity")
        self.assertEqual((ln["to"], ln["kind"], ln.get("label")), ("activity", "tab", "Tap Activity"))
        self.patch("link:today/tab-activity", "--set", "label=", "--no-bump")
        self.assertNotIn("label", self.link("today", "tab-activity"))

    def test_delete_drops_the_attributes_and_a_gesture_element_whole(self) -> None:
        before = (self.screens / "profile.html").read_text(encoding="utf-8")
        self.patch("link:profile/open-settings", "--delete", "--no-bump")
        gone, new = self.changed("profile.html", before)
        self.assertEqual([g.replace(' data-nav="modal:settings" data-nav-label="Tap the gear"', "") for g in gone], new)
        self.assertIsNone(self.link("profile", "open-settings"))
        before = (self.screens / "workout.html").read_text(encoding="utf-8")
        self.patch("link:workout/edge-back", "--delete", "--no-bump")
        gone, new = self.changed("workout.html", before)
        self.assertEqual((len(gone), new), (1, []), "the hidden gesture element goes, line and all")
        self.assertIn('data-bd="edge-back"', gone[0])

    def test_a_new_gesture_link_goes_inside_the_root(self) -> None:
        before = (self.screens / "workout.html").read_text(encoding="utf-8")
        self.patch("link:workout/", "--set", "to=settings", "--set", "kind=modal", "--set", "label=Swipe up", "--no-bump")
        gone, new = self.changed("workout.html", before)
        self.assertEqual(gone, [])
        self.assertEqual([l.strip() for l in new],
                         ['<i hidden data-bd="swipe-up" data-nav="modal:settings" data-nav-label="Swipe up"></i>'])
        ln = self.link("workout", "swipe-up")
        self.assertEqual((ln["to"], ln["kind"], ln.get("edge")), ("settings", "modal", True))

    def test_an_unnamed_element_is_named_first(self) -> None:
        root, text = self.add_to_root("settings.html", "<button>See plans</button>")
        self.patch("artboard:settings", "--change", "A plans button.", "--no-bump")
        tree = build._ScreenTree(text)
        top = tree.named(root)[0]
        n = sum(1 for i in tree.children(top) if tree.els[i]["tag"] == "button")
        self.patch(f'link:settings/[data-bd="{root}"]>button:nth-of-type({n})', "--set", "to=today", "--set",
                   "label=Tap See plans", "--no-bump")
        self.assertEqual(self.link("settings", "tap-see-plans")["to"], "today")

    def test_a_bad_target_or_kind_writes_nothing(self) -> None:
        before = {p.name: p.read_text(encoding="utf-8") for p in self.screens.glob("*.html")}
        raw = self.doc_path.read_text(encoding="utf-8")
        self.patch("link:today/tab-workouts", "--set", "to=nowhere", code=2)
        self.patch("link:today/tab-workouts", "--set", "kind=jump", code=2)
        self.patch("link:today/tab-workouts", "--set", "colour=red", code=2)
        self.patch("link:today/tab-workouts", "--json", "{}", code=2)
        self.patch("link:today/nothing-here", "--delete", code=2)
        self.patch("link:app-icon/x", "--set", "to=today", code=2)
        self.assertEqual({p.name: p.read_text(encoding="utf-8") for p in self.screens.glob("*.html")}, before)
        self.assertEqual(self.doc_path.read_text(encoding="utf-8"), raw)

    def test_a_patch_the_lint_refuses_is_put_back(self) -> None:
        root, text = self.add_to_root("today.html", '<b data-bd="dup">1</b><b data-bd="dup">2</b>')
        r = self.patch(f'link:today/[data-bd="{root}"]>b:nth-of-type(1)', "--set", "to=activity", code=1)
        self.assertIn("not unique", r.stderr)
        self.assertEqual((self.screens / "today.html").read_text(encoding="utf-8"), text)

    def test_layout_sets_positions(self) -> None:
        self.patch("layout:main", "--json", '{"today": [600, 0], "login-b": [0, 960.5]}', "--resolves", "c1",
                   "--change", "Moved two screens.")
        arts = {a["id"]: a for a in build.board_of(load_json(self.doc_path))["artboards"]}
        self.assertEqual((arts["today"]["x"], arts["today"]["y"]), (600, 0))
        self.assertEqual((arts["login-b"]["x"], arts["login-b"]["y"]), (0, 960.5))
        self.assertEqual(load_json(self.doc_path)["resolves"], ["c1"])
        self.patch("layout:main", "--json", '{"today": null}', "--no-bump")
        today = next(a for a in build.board_of(load_json(self.doc_path))["artboards"] if a["id"] == "today")
        self.assertNotIn("x", today)
        for bad in ('{"nowhere": [0, 0]}', '{"today": [0]}', '{"today": ["a", 1]}', "[1, 2]", '{"today": [1e9, 0]}'):
            with self.subTest(json=bad):
                self.patch("layout:main", "--json", bad, "--no-bump", code=2)
        self.patch("layout:other", "--json", '{"today": [0, 0]}', code=2)


if __name__ == "__main__":
    unittest.main()
