#!/usr/bin/env python3
"""Validate a bluedoc JSON document, record its revision, optionally write standalone HTML.

Usage:
  build.py doc.json                 validate, lint, record the revision (view it with serve.py)
  build.py doc.json -o out.html     same, plus a standalone HTML file for sharing offline (media and diffs inlined)
  build.py doc.json --check         validate and lint only; writes nothing (no history, no diff cache)
  build.py doc.json --strict        treat lint warnings as errors
  build.py doc.json --show-rev B    print revision B, rebuilt from the history, as JSON
  build.py new TYPE out.bluedoc.json [--title T] [--kind K]
                                    write the fill-in skeleton of a docs|review|plan|other doc
  build.py patch doc.json KEY [--set f=v ...] [--json OBJ] [--append OBJ] [--delete] [--change LINE ...] [--no-bump]
                                    change one object by its annotator key, bump meta.rev, validate, record

serve.py renders the JSON with assets/template.html on every request, so normal work needs no
HTML file at all: write the JSON, run build.py, open the serve.py URL.

Revisions: every build (and every patch) records the document under its `meta.rev` in
<doc>.history.json next to the JSON (doc.bluedoc.json -> doc.bluedoc.history.json). A new rev
appends; the same rev replaces that entry. The page embeds the history, so readers can switch
revisions and compare two. --no-history skips reading and writing it.

Type contracts: each meta.type needs its data (review: a diff and sized findings; plan: steps and
files blocks; docs: a canvas or a hero). Missing data is an error on the doc being built: a new
meta.rev, or a recorded rev whose text changed (an edit in place). It is a warning only while the
doc is exactly the revision its history recorded, so old revisions keep rendering.

Diff refs: a diff block with base and head and no files is expanded from git (cache file
<name>.diffcache.json, then `git diff`, then `gh pr diff`) by scripts/diffref.py when validating,
serving and writing -o. A build (not --check) drops the cache entries and source lines that no ref
in the doc or its history reads.

patch keys: doc, meta, header, tldr, status, section:<sec>, heading:<sec>, lead:<sec>,
  block:<blockPath>, item:<checklist>/<item>, row:<blockPath>/<r>, card:<blockPath>/<i>,
  step:<blockPath>/<step>, file:<blockPath>/<path>, node:<canvas>/<node>[/<child>…],
  comment:<diff>/<i>, para:<blockPath>/<i>, media:<blockPath>, compare:<blockPath>/<before|after>,
  line:<diff>/<path>:<n> (o<n> for an old-side line): the diff comment on <path> whose lines cover n;
  a diff ref's code comes from git, so with no such comment patch exits 2 (change the code, patch
  the finding with item:<checklist>/<item>, or add a comment). A key may keep the backticks the
  reply Markdown puts around it.
  <blockPath> is <section>/<index> or <checklist>/<item>/<index>. header, tldr and status address
  the doc's top level. --set and --json values parse as JSON when they can; null deletes the field.
  --append adds to the target's list (doc: sections, section and item: blocks, table: rows,
  canvas: nodes, diff: comments, other blocks: items). The rev bumps (A->B, 3->4, v1->v2) and
  meta.date becomes today unless --no-bump; on a bump `changes` becomes the --change lines
  (default: "Updated `KEY`."), with --no-bump they are appended.

Exit codes: 0 ok, 1 validation errors (or warnings with --strict), 2 usage/IO error.
Python 3.9+ standard library only.
"""
from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "assets" / "template.html"
SKELETONS = HERE.parent / "assets" / "skeletons"
HISTORY_VERSION = 1

BLOCK_TYPES = {"text", "callout", "table", "code", "terms", "cards", "checklist", "canvas", "diff", "steps", "files", "media", "compare"}
FILE_STATUSES = {"added", "modified", "deleted", "renamed", "context"}
ITEM_BLOCK_TYPES = {"text", "callout", "table", "code", "terms", "cards", "checklist", "files", "media", "compare"}
MAX_TITLE, MAX_SUB = 90, 120   # characters that fit the collapsed checklist row
MAX_CHOICES, MAX_CHOICE_LABEL = 6, 28
# a skeleton placeholder: <<words>>, with no space right inside the brackets and at least one letter or
# digit, so C shifts (`x << 4 >> 2`) and heredocs (`cat <<EOF >> log`) don't count
PLACEHOLDER = re.compile(r"<<(?=[^<>\n]*\w)[^<>\s](?:[^<>\n]{0,118}[^<>\s])?>>")
CODE_SPAN = re.compile(r"`([^`\n]*)`")
# what the page's safeUrl lets through: no scheme (relative paths, #fragments), http, https or mailto,
# after dropping U+0000-U+0020 as browsers do
URL_SCHEME = re.compile(r"^([a-z][a-z\d+.-]*):", re.I)
SAFE_SCHEMES = re.compile(r"^(https?|mailto)$", re.I)
# a markdown link as the page's inline() reads it; JavaScript's \s, not Python's (which also takes \x1c-\x1f)
MD_LINK = re.compile("\\[([^\\]]+)\\]\\(([^)\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+)\\)")
CALLOUT_KINDS = {"note", "caution", "warning", "risk", "decision"}
STATE_KINDS = {"ok", "warn", "risk", "info", "todo"}
DOC_TYPES = {"docs", "review", "plan", "other"}   # meta.type: the home page's grouping; unset = derived from meta.kind
# meta.kind words that make a doc type "docs" when meta.type is unset (after the plan and review rules)
DOCS_KINDS = {"architecture", "walkthrough", "runbook", "setup", "reference", "proposal", "change", "changes", "plan",
              "status", "guide", "design", "spec", "rfc", "adr", "overview", "tutorial", "onboarding", "explainer", "playbook"}
FINDING_SIZES = ("blocker", "major", "minor", "nit")   # a review finding's state
# hero: the home card's element for docs without a canvas and for other docs
HERO_ICONS = ["chart", "doc", "flag", "bolt", "clock", "users", "bug", "box", "check", "globe", "lock", "list"]
MAX_HERO_VALUE, MAX_HERO_LABEL = 8, 28
STEP_STATUSES = {"todo", "doing", "done", "blocked"}
STEP_EFFORTS = {"S", "M", "L"}
FILE_ACTIONS = {"add", "edit", "delete", "rename", "move"}
# media a page may show: extension -> MIME type (serve.py serves these; -o inlines them as data URIs)
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
               ".svg": "image/svg+xml", ".mp4": "video/mp4", ".webm": "video/webm"}
MAX_MEDIA_BYTES = 2 * 1024 * 1024
NODE_KINDS = {"service", "process", "function", "store", "db", "cache", "stream", "queue", "device", "hardware",
              "actor", "user", "person", "client", "app", "ui", "external", "cloud", "note", "port"}
NODE_STATES = {"live", "local", "proposed", "unverified", "removed", "replaced"}
EDGE_KINDS = {"data", "control", "async", "power", "dep", "replaced"}
PORTS = {"@left", "@right", "@top", "@bottom"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Mechanical CRISP checks. They catch common slips; they do not replace the CRISP pass.
FILLER = ["very", "really", "just", "simply", "basically", "actually", "quite", "extremely", "incredibly",
          "robust", "seamless", "seamlessly", "leverage", "utilize", "powerful", "comprehensive", "delve",
          "crucial", "cutting-edge", "game-changer", "in order to", "it's worth noting", "it is worth noting",
          "please note", "note that", "feel free", "let me know", "as mentioned", "needless to say",
          "at the end of the day", "in conclusion", "to summarize", "in summary"]
VAGUE = ["soon", "usually", "often", "sometimes", "appropriate", "appropriately", "various", "a number of",
         "as needed", "if necessary", "etc", "and so on", "some time", "a while", "fast enough", "properly"]
NON_IMPERATIVE_START = {"the", "a", "an", "this", "it", "you", "we", "there", "make sure", "ensure that", "should"}
MAX_WORDS = 32
# answer first: a tldr or lead states the conclusion, not what the text is about
ABOUT_OPENING = re.compile(r"^\s*(in )?this (section|doc|document|page)\b", re.I)
# no closing summary: the last section repeats nothing
CLOSING_TITLES = {"summary", "conclusion", "conclusions", "wrap-up", "wrap up", "recap", "closing thoughts"}
# the reader chooses through decision items, not by being asked to agree
ASK_AGREE = re.compile(r"\b(if you agree|do you agree|confirm whether|check if you agree)\b", re.I)


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, where: str, msg: str) -> None:
        self.errors.append(f"ERROR {where}: {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"WARN  {where}: {msg}")


def find_placeholders(text: str) -> list[str]:
    """The <<placeholders>> left in text. Inline code counts only when the whole span is one placeholder
    (skeletons write `<<path:line>>`), so a quoted shift or heredoc in backticks never does."""
    spans = [m.group(1) for m in CODE_SPAN.finditer(text) if PLACEHOLDER.fullmatch(m.group(1))]
    return spans + PLACEHOLDER.findall(CODE_SPAN.sub(" ", text))


def unsafe_scheme(url: str) -> str | None:
    """The scheme of a URL the page refuses to link (javascript:, data:, …), else None."""
    m = URL_SCHEME.match(re.sub(r"[\x00-\x20]", "", url))
    return m.group(1) if m and not SAFE_SCHEMES.match(m.group(1)) else None


def check_url(rep: Report, where: str, url) -> None:
    scheme = unsafe_scheme(url) if isinstance(url, str) else None
    if scheme:
        rep.err(where, f"URL {url!r} uses the scheme '{scheme}:': links take http, https, mailto, "
                       "a relative path or a #fragment")


def lint_text(rep: Report, where: str, text: str | None, *, imperative: bool = False) -> None:
    if not text:
        return
    plain = re.sub(r"`[^`]*`", "", text)
    plain = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", plain)
    low = " " + plain.lower() + " "
    for w in FILLER:
        if re.search(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", low):
            rep.warn(where, f"filler/ceremony word '{w}' (CRISP rule 3/9)")
    for w in VAGUE:
        if re.search(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", low):
            rep.warn(where, f"vague word '{w}': use a number, name, condition, or 'unknown' (CRISP rule 6)")
    for sentence in re.split(r"(?<=[.!?])\s+|\n", plain):
        n = len(sentence.split())
        if n > MAX_WORDS:
            rep.warn(where, f"sentence has {n} words (> {MAX_WORDS}): split it")
    if imperative:
        first = plain.strip().lower()
        for bad in NON_IMPERATIVE_START:
            if first.startswith(bad + " "):
                rep.warn(where, f"checklist item starts with '{bad}': start with a verb (\"Run …\", \"Open …\")")
                break
        if first.endswith("?"):
            rep.warn(where, "checklist item is a question: write one action")


def lint_opening(rep: Report, where: str, text: str | None) -> None:
    if isinstance(text, str) and ABOUT_OPENING.match(text):
        rep.warn(where, "opens by saying what the text is about: state the conclusion first")


def need(rep: Report, where: str, obj: dict, *keys: str) -> bool:
    ok = True
    for k in keys:
        if k not in obj or obj[k] in (None, "", []):
            rep.err(where, f"missing required field '{k}'")
            ok = False
    return ok


def check_id(rep: Report, where: str, value) -> None:
    if not isinstance(value, str) or not ID_RE.match(value):
        rep.err(where, f"id {value!r} must match {ID_RE.pattern} (stable ids keep checklist progress)")


def validate_scope(rep: Report, where: str, scope: dict, depth: int, node_keys: set[str], prefix: str,
                   is_child: bool) -> None:
    nodes = scope.get("nodes") or []
    edges = scope.get("edges") or []
    flows = scope.get("flows") or []
    if not nodes:
        rep.err(where, "scope has no nodes")
    if len(nodes) > 12:
        rep.warn(where, f"{len(nodes)} nodes in one level: group them into systems with children (aim for <= 9)")
    if depth > 4:
        rep.warn(where, "nesting deeper than 4 levels is hard to navigate")
    ids: set[str] = set()
    for i, n in enumerate(nodes):
        w = f"{where}.nodes[{i}]"
        if not need(rep, w, n, "id", "label"):
            continue
        check_id(rep, w, n["id"])
        if n["id"] in ids:
            rep.err(w, f"duplicate node id '{n['id']}' in this scope")
        ids.add(n["id"])
        key = f"{prefix}{n['id']}"
        node_keys.add(key)
        if n.get("kind") and n["kind"] not in NODE_KINDS:
            rep.err(w, f"kind '{n['kind']}' not in {sorted(NODE_KINDS)}")
        if n.get("state") and n["state"] not in NODE_STATES:
            rep.err(w, f"state '{n['state']}' not in {sorted(NODE_STATES)}")
        has_pos = ("x" in n and "y" in n) or ("col" in n or "row" in n)
        if not has_pos:
            rep.err(w, "node needs a position: x and y (centre), or col and row")
        if len(n.get("label", "")) > 40:
            rep.warn(w, "label longer than 40 characters: move detail to 'sub' or 'md'")
        lint_text(rep, w + ".md", n.get("md"))
        if n.get("children"):
            validate_scope(rep, w + ".children", n["children"], depth + 1, node_keys, key + "/", True)
    # overlap check (centre-based boxes)
    boxes = []
    for n in nodes:
        if "id" not in n:
            continue
        sys_ = bool(n.get("children", {}).get("nodes"))
        w_ = n.get("w") or (240 if sys_ else 180)
        h_ = n.get("h") or (140 if sys_ else 80)
        cx = n["x"] if "x" in n else n.get("col", 0) * 250
        cy = n["y"] if "y" in n else n.get("row", 0) * 160
        boxes.append((n["id"], cx - w_ / 2, cy - h_ / 2, cx + w_ / 2, cy + h_ / 2))
    for a in range(len(boxes)):
        for b in range(a + 1, len(boxes)):
            A, B = boxes[a], boxes[b]
            if A[1] < B[3] and B[1] < A[3] and A[2] < B[4] and B[2] < A[4]:
                rep.err(where, f"nodes '{A[0]}' and '{B[0]}' overlap: move one (col/row grid is 250 x 160)")
    edge_ids: set[str] = set()
    for i, e in enumerate(edges):
        w = f"{where}.edges[{i}]"
        if not need(rep, w, e, "from", "to"):
            continue
        for end in ("from", "to"):
            v = e[end]
            if v in PORTS:
                if not is_child:
                    rep.err(w, f"{end}='{v}': ports exist only inside a node's children")
            elif v not in ids:
                rep.err(w, f"{end}='{v}' is not a node id in this scope")
        eid = e.get("id") or f"{e['from']}->{e['to']}"
        if eid in edge_ids:
            rep.err(w, f"duplicate edge id '{eid}': give parallel edges explicit ids")
        edge_ids.add(eid)
        if e.get("kind") and e["kind"] not in EDGE_KINDS:
            rep.err(w, f"kind '{e['kind']}' not in {sorted(EDGE_KINDS)}")
        if e.get("label") and len(e["label"]) > 28:
            rep.warn(w, "edge label longer than 28 characters")
    for i, f in enumerate(flows):
        w = f"{where}.flows[{i}]"
        if not need(rep, w, f, "id", "label", "steps"):
            continue
        for j, st in enumerate(f.get("steps") or []):
            sw = f"{w}.steps[{j}]"
            refs = st.get("edges") or ([st["edge"]] if st.get("edge") else [])
            if not refs:
                rep.err(sw, "step needs 'edge' or 'edges'")
            for r in refs:
                if r not in edge_ids:
                    rep.err(sw, f"edge '{r}' not found in this scope (edge id defaults to 'from->to')")
            if not st.get("label"):
                rep.warn(sw, "step has no label: the caption bar will be empty")
            lint_text(rep, sw + ".label", st.get("label"))


def diff_lines(f: dict) -> tuple[set[int], set[int]]:
    """Line numbers a file's hunks display, per side (old, new)."""
    old: set[int] = set()
    new: set[int] = set()
    for h in f.get("hunks") or []:
        o, n = h.get("old", 1), h.get("new", 1)
        for l in h.get("lines") or []:
            if l[:1] != "+":
                old.add(o)
                o += 1
            if l[:1] != "-":
                new.add(n)
                n += 1
    return old, new


def is_count(v) -> bool:
    """A non-negative int; JSON true/false parse as bool, which Python counts as int."""
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def validate_diff(rep: Report, where: str, b: dict) -> dict[str, tuple[set[int], set[int]]]:
    """Every number the page draws into a diff must be an int: the template builds its rows as HTML."""
    files: dict[str, tuple[set[int], set[int]]] = {}
    for fi, f in enumerate(b.get("files") or []):
        fw = f"{where}.files[{fi}]"
        if not need(rep, fw, f, "path"):
            continue
        if f["path"] in files:
            rep.err(fw, f"duplicate file '{f['path']}'")
        if f.get("status", "modified") not in FILE_STATUSES:
            rep.err(fw, f"status '{f.get('status')}' not in {sorted(FILE_STATUSES)}")
        numbers_ok = True
        for k in ("add", "del"):
            if k in f and not is_count(f[k]):
                rep.err(f"{fw}.{k}", f"{f[k]!r}: a count of lines, an integer 0 or more")
        for hi, h in enumerate(f.get("hunks") or []):
            hw = f"{fw}.hunks[{hi}]"
            if not isinstance(h, dict):
                rep.err(hw, 'a hunk is an object {"old", "new", "lines"}')
                numbers_ok = False
                continue
            for k in ("old", "new"):
                if k in h and not is_count(h[k]):
                    rep.err(f"{hw}.{k}", f"{h[k]!r}: a line number, an integer 0 or more")
                    numbers_ok = False
            if not isinstance(h.get("lines"), list) or not all(isinstance(l, str) and l[:1] in ("+", "-", " ") for l in h["lines"]):
                rep.err(hw, "every line must be a string starting with '+', '-' or ' '")
                numbers_ok = False
        files[f["path"]] = diff_lines(f) if numbers_ok else (set(), set())
    return files


def check_media_src(rep: Report, where: str, src, base: Path | None) -> None:
    """A media src: a data: URI, or a path relative to the doc's folder with a known extension.
    base is the doc's folder; without it the file itself isn't checked."""
    if not isinstance(src, str) or not src.strip():
        rep.err(where, "src must be a non-empty string: a path relative to the doc's folder, or a data: URI")
        return
    if src.startswith("data:"):
        if not re.match(r"data:[\w.+-]+/[\w.+-]+[;,]", src):
            rep.err(where, "data: URI needs a MIME type, e.g. data:image/png;base64,…")
        return
    bare = re.sub(r"[\x00-\x20]", "", src)   # what a browser reads the scheme from
    if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", bare) or bare.startswith("//"):
        what = "http(s) sources" if re.match(r"(https?:)?//", bare, re.I) else "URLs with a scheme"
        rep.err(where, f"{what} aren't allowed (pages make no network calls): save the file next to the doc and use a relative path")
        return
    if bare.startswith("/"):
        rep.err(where, f"src '{src}' is absolute: use a path relative to the doc's folder, e.g. media/{Path(src).name}")
        return
    path = src.split("?", 1)[0].split("#", 1)[0]
    if Path(path).suffix.lower() not in MEDIA_TYPES:
        rep.err(where, f"'{src}': extension not in {' '.join(sorted(MEDIA_TYPES))}")
        return
    if base is None:
        return
    f = base / path
    if not f.is_file():
        rep.err(where, f"'{src}' not found (looked for {f})")
    elif f.stat().st_size > MAX_MEDIA_BYTES:
        rep.warn(where, f"'{src}' is {f.stat().st_size / 1048576:.1f} MB (> {MAX_MEDIA_BYTES // 1048576} MB): compress or crop it; -o embeds it in the page")


def doc_type(meta: dict) -> str:
    """docs | review | plan | other: meta.type when set, else read from meta.kind. template.html follows
    the same rule; serve.py puts the result in the home page's index."""
    if meta.get("type") in DOC_TYPES:
        return meta["type"]
    kind = str(meta.get("kind") or "").strip().lower()
    if kind.startswith("plan") or kind == "implementation plan":
        return "plan"
    if "review" in kind:
        return "review"
    return "docs" if set(re.findall(r"[a-z]+", kind)) & DOCS_KINDS else "other"


def all_blocks(doc: dict):
    """Every block, depth-first, including the blocks inside checklist items."""
    def walk(blocks):
        for b in blocks or []:
            if isinstance(b, dict):
                yield b
                if b.get("type") == "checklist":
                    for it in b.get("items") or []:
                        if isinstance(it, dict):
                            yield from walk(it.get("blocks"))
    for s in doc.get("sections") or []:
        if isinstance(s, dict):
            yield from walk(s.get("blocks"))


def check_contract(doc: dict) -> list[str]:
    """The data the doc's type requires and the doc lacks: its home card and page draw from it."""
    t = doc_type(doc.get("meta") or {})
    blocks = list(all_blocks(doc))
    types = {b.get("type") for b in blocks}
    out: list[str] = []
    if t == "review":
        if "diff" not in types:
            out.append("a review needs a diff block (gitdiff.py writes one)")
        for b in blocks:
            if b.get("type") != "checklist":
                continue
            for it in b.get("items") or []:
                if isinstance(it, dict) and it.get("choices") and it.get("state") not in FINDING_SIZES:
                    has = f"state {it['state']!r}" if it.get("state") else "no state"
                    out.append(f"finding '{b.get('id')}/{it.get('id')}' has {has}: give it one of {'|'.join(FINDING_SIZES)}")
    elif t == "plan":
        out += [f"a plan needs a {bt} block" for bt in ("steps", "files") if bt not in types]
    elif t == "docs" and "canvas" not in types and not doc.get("hero"):
        out.append("a docs page needs a canvas block or a top-level hero")
    return out


def contract_level(doc: dict, doc_path: Path | None) -> str:
    """'warn' only while the doc is exactly the revision its history recorded under meta.rev, so
    revisions written before a contract existed keep rendering; 'error' on the doc being built: a new
    meta.rev, or a recorded rev whose text changed in place. A doc without meta.rev keeps no history
    and counts as recorded; without doc_path every rev counts as new."""
    rev = str((doc.get("meta") or {}).get("rev") or "")
    if not rev:
        return "warn"
    if doc_path is None:
        return "error"
    try:
        h = load_history(history_path(Path(doc_path)))
        entry = next((r for r in h["revs"] if r.get("rev") == rev), None)
        same = entry is not None and json.dumps(restore(h, entry), sort_keys=True) == json.dumps(doc, sort_keys=True)
    except (OSError, ValueError, KeyError, TypeError):
        return "error"
    return "warn" if same else "error"


def _diffref():
    """scripts/diffref.py, imported on first use: docs without diff refs never load it."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import diffref
    return diffref


def _ref_candidates(doc: dict) -> list[dict]:
    """diff blocks without embedded files: the refs, plus malformed blocks validate reports."""
    return [b for b in all_blocks(doc) if b.get("type") == "diff" and "files" not in b]


def validate(doc: dict, doc_path: Path | None = None, *, allow_remote: bool = False, write_cache: bool = True) -> Report:
    """doc_path, when given, is the doc's JSON file: media srcs are checked against its folder, diff refs
    expand relative to it and the type contract is a warning only while the doc is the revision its history
    recorded. allow_remote lets a diff ref whose repo is missing fall back to `gh pr diff`; write_cache=False
    leaves <name>.diffcache.json as it is."""
    rep = Report()
    base = Path(doc_path).resolve().parent if doc_path else None
    need(rep, "doc", doc, "id", "title", "sections")
    if "id" in doc:
        check_id(rep, "doc", doc["id"])
    lint_text(rep, "doc.subtitle", doc.get("subtitle"))
    lint_text(rep, "doc.tldr", doc.get("tldr"))
    lint_opening(rep, "doc.tldr", doc.get("tldr"))
    hero = doc.get("hero")
    if hero is not None:
        if not isinstance(hero, dict):
            rep.err("doc.hero", 'an object {"icon", "value", "label"}')
        else:
            need(rep, "doc.hero", hero, "icon", "value", "label")
            if hero.get("icon") is not None and hero["icon"] not in HERO_ICONS:
                rep.err("doc.hero.icon", f"{hero['icon']!r} not in {HERO_ICONS}")
            for k, most in (("value", MAX_HERO_VALUE), ("label", MAX_HERO_LABEL)):
                v = hero.get(k)
                if v is not None and not isinstance(v, str):
                    rep.err(f"doc.hero.{k}", "a string")
                elif isinstance(v, str) and not find_placeholders(v) and len(v) > most:
                    rep.err(f"doc.hero.{k}", f"{len(v)} characters (at most {most}): the home card draws it large")
    # diff refs: check them against a filled-in copy, so the doc keeps only the reference
    ref_ids: set[int] = set()            # id() of the ref blocks
    expanded: dict[int, dict] = {}       # id() of a ref block -> its copy filled from git or the cache
    candidates = _ref_candidates(doc)
    dr = None
    if candidates:
        try:
            dr = _diffref()
        except ImportError:
            for b in candidates:
                rep.err(f"diff '{b.get('id')}'", "scripts/diffref.py is missing: it expands diff refs (base, head, no files)")
    if dr:
        refs = [b for b in candidates if dr.is_ref(b)]
        ref_ids = {id(b) for b in refs}
        # a ref still holding a <<placeholder>> is reported as one, not expanded
        live = [b for b in refs if not find_placeholders(json.dumps(b, ensure_ascii=False))]
        if live:
            probe = {"sections": [{"id": "refs", "blocks": copy.deepcopy(live)}]}
            for p in dr.expand_doc(probe, Path(doc_path) if doc_path else None, allow_remote=allow_remote,
                                   write_cache=write_cache):
                (rep.errors if p.startswith("ERROR") else rep.warnings).append(p)
            expanded = {id(b): e for b, e in zip(live, probe["sections"][0]["blocks"])}
    ch = doc.get("changes")
    if ch is not None:
        if not isinstance(ch, list) or not all(isinstance(x, str) and x.strip() for x in ch):
            rep.err("doc.changes", "list of non-empty inline-md strings: what changed in this revision")
        else:
            for i, x in enumerate(ch):
                lint_text(rep, f"doc.changes[{i}]", x)
    dtype = (doc.get("meta") or {}).get("type")
    if dtype is not None and dtype not in DOC_TYPES:
        rep.err("doc.meta.type", f"'{dtype}' not in {sorted(DOC_TYPES)}")
    for i, s in enumerate(doc.get("state") or []):
        if s.get("kind") and s["kind"] not in STATE_KINDS:
            rep.err(f"doc.state[{i}]", f"kind '{s['kind']}' not in {sorted(STATE_KINDS)}")
    sec_ids: set[str] = set()
    titles: set[str] = set()
    checklist_ids: set[str] = set()
    canvas_nodes: dict[str, set[str]] = {}
    refs_to_check: list[tuple[str, str]] = []
    checklist_items: dict[str, set[str]] = {}
    diffs: dict[str, dict[str, tuple[set[int], set[int]]]] = {}
    unexpanded: set[str] = set()               # diff refs with no files to check lines against
    ref_diffs: set[str] = set()                # diff ids that are refs
    comments_to_check: list[tuple[str, str, dict]] = []
    steps_blocks: set[str] = set()
    step_ids: set[str] = set()
    step_files: list[tuple[str, str]] = []     # (where, path) a step names in 'files'
    file_rows: set[str] = set()                # paths listed by files blocks
    file_steps: list[tuple[str, str]] = []     # (where, step id) a files row points to

    def check_block(bw: str, b: dict, depth: int) -> None:
        """depth 0 = section block, 1 = inside a checklist item, 2 = inside a nested checklist's item."""
        t = b.get("type")
        if t not in BLOCK_TYPES:
            rep.err(bw, f"type {t!r} not in {sorted(BLOCK_TYPES)}")
            return
        if depth and t not in ITEM_BLOCK_TYPES:
            rep.err(bw, f"type {t!r} can't sit inside a checklist item; use one of {sorted(ITEM_BLOCK_TYPES)}")
            return
        if depth >= 2 and t == "checklist":
            rep.err(bw, "checklists nest one level only: a nested checklist's items can't hold another checklist")
            return
        if t in ("text", "callout"):
            need(rep, bw, b, "md")
            lint_text(rep, bw, b.get("md"))
            if t == "text" and len(re.findall(r"^\s*\d+[.)]\s", b.get("md") or "", re.M)) >= 3:
                rep.warn(bw, "a procedure as a numbered list: make it a checklist, one action per item")
            if t == "callout" and b.get("kind", "note") not in CALLOUT_KINDS:
                rep.err(bw, f"callout kind '{b.get('kind')}' not in {sorted(CALLOUT_KINDS)}")
        elif t == "table":
            if need(rep, bw, b, "columns", "rows"):
                for ri, row in enumerate(b["rows"]):
                    if len(row) != len(b["columns"]):
                        rep.err(f"{bw}.rows[{ri}]", f"{len(row)} cells, {len(b['columns'])} columns")
        elif t == "code":
            need(rep, bw, b, "code")
        elif t == "terms":
            for ti, it in enumerate(b.get("items") or []):
                need(rep, f"{bw}.items[{ti}]", it, "term", "md")
                lint_text(rep, f"{bw}.items[{ti}]", it.get("md"))
        elif t == "cards":
            for ci, it in enumerate(b.get("items") or []):
                need(rep, f"{bw}.items[{ci}]", it, "title", "md")
                lint_text(rep, f"{bw}.items[{ci}]", it.get("md"))
        elif t == "checklist":
            if not need(rep, bw, b, "id", "title", "items"):
                return
            check_id(rep, bw, b["id"])
            if b["id"] in checklist_ids:
                rep.err(bw, f"duplicate checklist id '{b['id']}'")
            checklist_ids.add(b["id"])
            checklist_items[b["id"]] = {it.get("id") for it in b["items"]}
            item_ids: set[str] = set()
            for ii, it in enumerate(b["items"]):
                iw = f"{bw}.items[{ii}]"
                if not need(rep, iw, it, "id", "text"):
                    continue
                check_id(rep, iw, it["id"])
                if it["id"] in item_ids:
                    rep.err(iw, f"duplicate item id '{it['id']}'")
                item_ids.add(it["id"])
                choices = it.get("choices")
                # a decision item's title names the question or finding, so it need not be imperative
                lint_text(rep, iw + ".text", it.get("text"), imperative=not choices)
                if choices is not None:
                    if not isinstance(choices, list) or not 2 <= len(choices) <= MAX_CHOICES:
                        rep.err(iw + ".choices", f"give 2 to {MAX_CHOICES} options, each {{id, label}}")
                    else:
                        cids: set[str] = set()
                        for ci, c in enumerate(choices):
                            cw = f"{iw}.choices[{ci}]"
                            if not isinstance(c, dict) or not need(rep, cw, c, "id", "label"):
                                continue
                            check_id(rep, cw, c["id"])
                            if c["id"] in cids:
                                rep.err(cw, f"duplicate option id '{c['id']}'")
                            cids.add(c["id"])
                            if len(re.sub(r"`", "", c["label"])) > MAX_CHOICE_LABEL:
                                rep.warn(cw, f"option label over {MAX_CHOICE_LABEL} characters: options are pills; put the explanation in 'md'")
                            lint_text(rep, cw + ".md", c.get("md"))
                        for field in ("recommend", "choice"):
                            if it.get(field) is not None and it[field] not in cids:
                                rep.err(f"{iw}.{field}", f"'{it[field]}' is not one of the option ids {sorted(cids)}")
                    if it.get("done"):
                        rep.err(iw + ".done", "a decision item is answered by 'choice', not 'done'")
                elif it.get("recommend") or it.get("choice"):
                    rep.err(iw, "'recommend' and 'choice' need 'choices'")
                title = re.sub(r"`([^`]*)`", r"\1", it.get("text", ""))
                if len(title) > MAX_TITLE:
                    rep.warn(iw + ".text", f"{len(title)} characters: the collapsed row shows one line (about {MAX_TITLE}); "
                             "keep the action there and move the rest to 'sub', 'detail' or 'blocks'")
                if "\n" in (it.get("sub") or "") or len(it.get("sub") or "") > MAX_SUB:
                    rep.warn(iw + ".sub", f"the subtitle shows one line (about {MAX_SUB} characters); move the rest to 'detail'")
                lint_text(rep, iw + ".sub", it.get("sub"))
                lint_text(rep, iw + ".detail", it.get("detail"))
                for field in ("text", "sub"):
                    m = ASK_AGREE.search(it.get(field) or "")
                    if m:
                        rep.warn(f"{iw}.{field}", f"'{m.group(0)}': let the reader choose with 'choices' instead of asking for agreement")
                for r in it.get("refs") or []:
                    refs_to_check.append((iw, r))
                for ki, kb in enumerate(it.get("blocks") or []):
                    check_block(f"{iw}.blocks[{ki}]", kb, depth + 1)
        elif t == "canvas":
            if not need(rep, bw, b, "id", "title", "nodes"):
                return
            check_id(rep, bw, b["id"])
            if b["id"] in canvas_nodes:
                rep.err(bw, f"duplicate canvas id '{b['id']}'")
            keys: set[str] = set()
            validate_scope(rep, bw, b, 0, keys, "", False)
            canvas_nodes[b["id"]] = keys
            lint_text(rep, bw + ".caption", b.get("caption"))
        elif t == "diff":
            ref = id(b) in ref_ids
            if not need(rep, bw, b, "id", "title", *(("base", "head") if ref else ("files",))):
                return
            check_id(rep, bw, b["id"])
            if b["id"] in diffs:
                rep.err(bw, f"duplicate diff id '{b['id']}'")
            src = b
            if ref:
                if not (b.get("repo") or b.get("pr")):
                    rep.err(bw, "a diff ref needs 'repo' (the repo's path from the doc's folder) or 'pr' (owner/repo#N, for gh)")
                paths = b.get("paths")
                if paths is not None and not (isinstance(paths, list) and all(isinstance(p, str) and p for p in paths)):
                    rep.err(bw + ".paths", "a list of paths that limit the diff")
                src = expanded.get(id(b)) or b
                ref_diffs.add(b["id"])
                if not src.get("files"):
                    unexpanded.add(b["id"])
            diffs[b["id"]] = validate_diff(rep, bw, src)
            lint_text(rep, bw + ".note", b.get("note"))
            check_url(rep, bw + ".url", b.get("url"))
            for ci, c in enumerate(src.get("comments") or []):
                comments_to_check.append((f"{bw}.comments[{ci}]", b["id"], c))
        elif t == "steps":
            if not need(rep, bw, b, "id", "items"):
                return
            check_id(rep, bw, b["id"])
            if b["id"] in steps_blocks:
                rep.err(bw, f"duplicate steps id '{b['id']}'")
            steps_blocks.add(b["id"])
            lint_text(rep, bw + ".title", b.get("title"))
            for ii, it in enumerate(b["items"]):
                iw = f"{bw}.items[{ii}]"
                if not isinstance(it, dict) or not need(rep, iw, it, "id", "title"):
                    continue
                check_id(rep, iw, it["id"])
                if it["id"] in step_ids:
                    rep.err(iw, f"duplicate step id '{it['id']}' (step ids are unique in the doc: files rows point to them)")
                step_ids.add(it["id"])
                if it.get("status", "todo") not in STEP_STATUSES:
                    rep.err(iw + ".status", f"'{it.get('status')}' not in {sorted(STEP_STATUSES)}")
                if it.get("effort") is not None and it["effort"] not in STEP_EFFORTS:
                    rep.err(iw + ".effort", f"'{it['effort']}' not in {sorted(STEP_EFFORTS)}")
                title = re.sub(r"`([^`]*)`", r"\1", it["title"])
                if len(title) > MAX_TITLE:
                    rep.warn(iw + ".title", f"{len(title)} characters: the step row shows one line (about {MAX_TITLE}); move the rest to 'md'")
                lint_text(rep, iw + ".title", it["title"], imperative=True)
                lint_text(rep, iw + ".md", it.get("md"))
                files = it.get("files")
                if files is not None and not (isinstance(files, list) and all(isinstance(f, str) and f for f in files)):
                    rep.err(iw + ".files", "list of file paths")
                else:
                    step_files.extend((iw + ".files", f) for f in files or [])
                refs = it.get("refs")
                if refs is not None and not isinstance(refs, list):
                    rep.err(iw + ".refs", "list of '<canvas>/<node>' refs")
                else:
                    refs_to_check.extend((iw, r) for r in refs or [])
        elif t == "files":
            if not need(rep, bw, b, "items"):
                return
            lint_text(rep, bw + ".title", b.get("title"))
            seen: set[str] = set()
            for fi, f in enumerate(b["items"]):
                fw = f"{bw}.items[{fi}]"
                if not isinstance(f, dict):
                    rep.err(fw, "a row is an object {path, action, why}")
                    continue
                if isinstance(f.get("path"), str):
                    file_rows.add(f["path"])   # even an incomplete row is a target for step chips
                if not need(rep, fw, f, "path", "action", "why"):
                    continue
                if f["path"] in seen:
                    rep.warn(fw, f"'{f['path']}' is listed twice in this block")
                seen.add(f["path"])
                act = f["action"]
                if act not in FILE_ACTIONS:
                    rep.err(fw + ".action", f"'{act}' not in {sorted(FILE_ACTIONS)}")
                elif act in ("rename", "move") and not f.get("from"):
                    rep.warn(fw, f"a {act} names the old path in 'from'")
                elif act not in ("rename", "move") and f.get("from"):
                    rep.err(fw + ".from", f"'from' is for rename and move, not {act}")
                lint_text(rep, fw + ".why", f.get("why"))
                if f.get("step"):
                    file_steps.append((fw + ".step", f["step"]))
        elif t == "media":
            need(rep, bw, b, "src", "alt")
            if "src" in b:
                check_media_src(rep, bw + ".src", b["src"], base)
            if b.get("width") is not None and not (isinstance(b["width"], (int, float)) and not isinstance(b["width"], bool) and b["width"] > 0):
                rep.err(bw + ".width", "a positive number: the most pixels wide it shows")
            lint_text(rep, bw + ".alt", b.get("alt"))
            lint_text(rep, bw + ".caption", b.get("caption"))
        elif t == "compare":
            if not need(rep, bw, b, "before", "after"):
                return
            lint_text(rep, bw + ".title", b.get("title"))
            for side in ("before", "after"):
                sd, sw_ = b[side], f"{bw}.{side}"
                if not isinstance(sd, dict):
                    rep.err(sw_, "an object with 'md', 'code' or 'src'")
                    continue
                if not any(sd.get(k) for k in ("md", "code", "src")):
                    rep.err(sw_, "give one of 'md', 'code' or 'src'")
                if sd.get("src"):
                    check_media_src(rep, sw_ + ".src", sd["src"], base)
                    if not sd.get("alt"):
                        rep.warn(sw_, "an image side needs 'alt'")
                lint_text(rep, sw_ + ".md", sd.get("md"))
                lint_text(rep, sw_ + ".label", sd.get("label"))

    for si, sec in enumerate(doc.get("sections") or []):
        sw = f"sections[{si}]"
        if not need(rep, sw, sec, "id", "title"):
            continue
        check_id(rep, sw, sec["id"])
        if sec["id"] in sec_ids:
            rep.err(sw, f"duplicate section id '{sec['id']}'")
        sec_ids.add(sec["id"])
        if sec["title"].lower() in titles:
            rep.warn(sw, f"duplicate section title '{sec['title']}'")
        titles.add(sec["title"].lower())
        lint_text(rep, sw + ".lead", sec.get("lead"))
        lint_opening(rep, sw + ".lead", sec.get("lead"))
        blocks = sec.get("blocks") or []
        if not blocks:
            rep.warn(sw, "section has no blocks")
        for bi, b in enumerate(blocks):
            check_block(f"{sw}.blocks[{bi}]", b, 0)
    secs = [s for s in doc.get("sections") or [] if isinstance(s, dict)]
    if len(secs) > 1 and str(secs[-1].get("title", "")).strip().lower() in CLOSING_TITLES:
        rep.warn(f"sections[{len(secs) - 1}]", f"a closing '{secs[-1]['title']}' repeats the page: cut it, the tldr is the summary")

    for where, r in refs_to_check:
        cid, _, key = r.partition("/")
        if cid not in canvas_nodes:
            rep.err(where, f"ref '{r}': no canvas '{cid}'")
        elif key not in canvas_nodes[cid] and not any(k.split("/")[-1] == key for k in canvas_nodes[cid]):
            rep.err(where, f"ref '{r}': no node '{key}' in canvas '{cid}' (use 'canvas/parent/child' for inner nodes)")
    for where, path in step_files:
        if file_rows and path not in file_rows:
            rep.warn(where, f"'{path}' is in no files block: its chip has no row to jump to")
    for where, sid in file_steps:
        if sid not in step_ids:
            rep.warn(where, f"step '{sid}' is in no steps block")
    for where, did, c in comments_to_check:
        files = diffs[did]
        if c.get("item"):
            cid, _, iid = c["item"].partition("/")
            if iid not in checklist_items.get(cid, set()):
                rep.err(where, f"item '{c['item']}' is not a checklist item ('checklist-id/item-id')")
        elif not (c.get("md") or c.get("title")):
            rep.err(where, "comment needs 'item', or 'title'/'md'")
        lint_text(rep, where + ".md", c.get("md"))
        bad = [k for k in ("line", "end") if k in c and not (is_count(c[k]) and c[k] > 0)]
        for k in bad:
            rep.err(f"{where}.{k}", f"{c[k]!r}: a line number, an integer 1 or more")
        if bad or did in unexpanded:
            continue
        if not c.get("file"):
            if c.get("line"):
                rep.err(where, "a comment with 'line' needs 'file'")
            continue
        if c["file"] not in files:
            rep.err(where, f"file '{c['file']}' is not in diff '{did}'")
            continue
        if c.get("line"):
            side = c.get("side", "new")
            shown = files[c["file"]][0 if side == "old" else 1]
            end = c.get("end", c["line"])
            if end not in shown:
                fix = ("check its 'at': the file at head has no such line" if did in ref_diffs
                       else "add an excerpt hunk (gitdiff.py does)")
                rep.err(where, f"line {end} ({side} side) of '{c['file']}' is not shown in the diff: {fix}")
    for did, path, line in re.findall(r"#code:([\w-]+)(?:/([^\s)\"]+?))?(?::(\d+))?(?=[)\"\s])", json.dumps(doc)):
        if did not in diffs:
            rep.err("links", f"#code:{did} points to no diff block")
        elif path and did not in unexpanded and path not in diffs[did]:
            rep.err("links", f"#code:{did}/{path} points to no file in that diff")
    md_links = re.findall(r"#node:([\w-]+)/([\w/-]+)", json.dumps(doc))
    for cid, key in md_links:
        if cid not in canvas_nodes or (key not in canvas_nodes[cid] and not any(k.split('/')[-1] == key for k in canvas_nodes[cid])):
            rep.err("links", f"#node:{cid}/{key} points to no node")
    item_anchors = {f"item-{cid}-{iid}" for cid, iids in checklist_items.items() for iid in iids}
    for anchor in re.findall(r"\]\(#(item-[\w-]+)\)", json.dumps(doc)):
        if anchor not in item_anchors:
            rep.err("links", f"#{anchor} points to no checklist item (#item-<checklist>-<item>)")

    def texts(node, where: str) -> None:
        # skeletons (build.py new) and ghthreads.py stubs carry <<...>> where the author's text goes;
        # code (diff files, code blocks) is quoted source and may legitimately contain << >> or [x](y)
        if isinstance(node, dict):
            for k, v in node.items():
                if k not in ("files", "code"):
                    texts(v, f"{where}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                texts(v, f"{where}[{i}]")
        elif isinstance(node, str):
            for m in find_placeholders(node):
                rep.err(where, f"unfilled placeholder {m}: replace it with what it names")
            for _, url in MD_LINK.findall(CODE_SPAN.sub(" ", node)):
                check_url(rep, where, url)
    for k, v in doc.items():
        texts(v, k if k == "sections" else f"doc.{k}")
    for i, link in enumerate(doc.get("links") or []):
        if isinstance(link, dict):
            check_url(rep, f"doc.links[{i}].href", link.get("href"))

    gaps = check_contract(doc)
    if gaps:
        where = f"contract ({doc_type(doc.get('meta') or {})})"
        if contract_level(doc, doc_path) == "error":
            for m in gaps:
                rep.err(where, m)
        else:
            for m in gaps:
                rep.warn(where, m + " (an error as soon as the doc changes)")
    return rep


def history_path(doc_path: Path) -> Path:
    name = doc_path.name[:-5] if doc_path.name.endswith(".json") else doc_path.name
    return doc_path.with_name(name + ".history.json")


def _canon(x) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def _hash(x) -> str:
    return hashlib.sha1(json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def load_history(path: Path) -> dict:
    if not path.exists():
        return {"bluedoc_history": HISTORY_VERSION, "revs": [], "blocks": {}}
    h = json.loads(path.read_text(encoding="utf-8"))
    if h.get("bluedoc_history") != HISTORY_VERSION or not isinstance(h.get("revs"), list):
        raise ValueError(f"{path} is not a bluedoc history file")
    h.setdefault("blocks", {})
    return h


def snapshot(doc: dict, pool: dict) -> dict:
    """One revision: the document without section blocks, plus block hashes into the shared pool."""
    head = {k: v for k, v in doc.items() if k != "sections"}
    sections = []
    for s in doc.get("sections") or []:
        refs = []
        for b in s.get("blocks") or []:
            k = _hash(b)
            pool[k] = b
            refs.append(k)
        sections.append({**{k: v for k, v in s.items() if k != "blocks"}, "blocks": refs})
    return {"head": head, "sections": sections}


def restore(h: dict, entry: dict) -> dict:
    return {**entry["head"], "sections": [{**s, "blocks": [h["blocks"][r] for r in s["blocks"]]} for s in entry["sections"]]}


def record(h: dict, doc: dict) -> str:
    """Put doc into the history under its meta.rev. Returns what happened, for the build log."""
    meta = doc.get("meta") or {}
    rev = str(meta.get("rev") or "")
    snap = snapshot(doc, h["blocks"])
    entry = {"rev": rev, "date": meta.get("date") or "", "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **snap}
    revs = h["revs"]
    if revs and revs[-1]["rev"] == rev:
        same = json.dumps(restore(h, revs[-1]), sort_keys=True) == json.dumps(doc, sort_keys=True)
        if same:
            msg = f"rev {rev} unchanged"
        else:
            revs[-1] = entry
            msg = f"rev {rev} updated in place (bump meta.rev to keep the previous text as its own revision)"
    elif any(r["rev"] == rev for r in revs):
        return f"ERROR history: meta.rev {rev} is an earlier revision of this doc; bump it past {revs[-1]['rev']}"
    else:
        revs.append(entry)
        msg = f"recorded rev {rev}"
    # drop pool blocks no revision uses any more
    used = {r for e in revs for s in e["sections"] for r in s["blocks"]}
    h["blocks"] = {k: v for k, v in h["blocks"].items() if k in used}
    out = f"history: {msg}; {len(revs)} revision(s)"
    if len(revs) > 1:
        prev = revs[-2]["head"].get("changes")
        if not doc.get("changes"):
            out += f"\nWARN  doc.changes: say what changed since rev {revs[-2]['rev']} (shown in the revision list and the diff)"
        elif prev == doc.get("changes"):
            out += f"\nWARN  doc.changes: same as rev {revs[-2]['rev']}; describe this revision"
    return out


def embed_history(h: dict | None, doc: dict) -> dict | None:
    """The history as the page needs it: blocks the current doc also has become '@section/block'
    references into the page's own document, so the page carries each block once."""
    if not h or len(h["revs"]) < 2:
        return None
    here = {}
    for i, s in enumerate(doc.get("sections") or []):
        for j, b in enumerate(s.get("blocks") or []):
            here.setdefault(_hash(b), f"@{i}/{j}")
    cur_rev = str((doc.get("meta") or {}).get("rev") or "")
    revs, blocks = [], {}
    for idx, e in enumerate(h["revs"]):
        out = {"rev": e["rev"], "date": e.get("date", ""), "built": e.get("built", "")}
        if not (idx == len(h["revs"]) - 1 and e["rev"] == cur_rev):   # the current rev is the page's own doc
            secs = []
            for s in e["sections"]:
                refs = []
                for r in s["blocks"]:
                    if r in here:
                        refs.append(here[r])
                    else:
                        blocks[r] = h["blocks"][r]
                        refs.append(r)
                secs.append({**s, "blocks": refs})
            out.update(head=e["head"], sections=secs)
        revs.append(out)
    return {"revs": revs, "blocks": blocks}


def _script_json(x) -> str:
    return _canon(x).replace("</", "<\\/").replace("<!--", "<\\!--")


def inline_media(x, base: Path, missing: list[str], cache: dict[str, str] | None = None):
    """A copy of x (doc, or embedded history) with every relative media src (media blocks, compare sides)
    replaced by a data: URI read from base, the doc's folder. Srcs whose file is gone go into missing."""
    cache = {} if cache is None else cache

    def uri(src):
        if not isinstance(src, str) or src.startswith("data:") or re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:|/", src):
            return src
        path = src.split("?", 1)[0].split("#", 1)[0]
        if path not in cache:
            f, mime = base / path, MEDIA_TYPES.get(Path(path).suffix.lower())
            if not mime or not f.is_file():
                missing.append(src)
                cache[path] = src
            else:
                cache[path] = f"data:{mime};base64," + base64.b64encode(f.read_bytes()).decode("ascii")
        return cache[path]

    if isinstance(x, list):
        return [inline_media(v, base, missing, cache) for v in x]
    if not isinstance(x, dict):
        return x
    out = {k: inline_media(v, base, missing, cache) for k, v in x.items()}
    if out.get("type") == "media" and "src" in out:
        out["src"] = uri(out["src"])
    elif out.get("type") == "compare":
        for side in ("before", "after"):
            if isinstance(out.get(side), dict) and out[side].get("src"):
                out[side] = {**out[side], "src": uri(out[side]["src"])}
    return out


def expand_diff_refs(doc: dict, hist: dict | None, doc_path: Path, problems: list[str]) -> tuple[dict, dict | None]:
    """Copies of the page's doc and embedded history (embed_history's shape) with every diff ref filled
    from the cache, git or gh by diffref.py; the doc file keeps only the reference."""
    pool = (hist or {}).get("blocks") or {}
    old = [k for k, b in pool.items() if isinstance(b, dict) and b.get("type") == "diff" and "files" not in b]
    if not old and not _ref_candidates(doc):
        return doc, hist
    try:
        dr = _diffref()
    except ImportError:
        problems.append("ERROR diff refs: scripts/diffref.py is missing, so they show no files")
        return doc, hist
    doc, probs = dr.expanded_copy(doc, doc_path)
    problems += probs
    old = [k for k in old if dr.is_ref(pool[k])]
    if old:
        blocks = {**pool, **{k: copy.deepcopy(pool[k]) for k in old}}
        problems += dr.expand_doc({"sections": [{"id": "history", "blocks": [blocks[k] for k in old]}]}, doc_path)
        hist = {**hist, "blocks": blocks}
    return doc, hist


def prune_diff_cache(doc: dict, history: dict | None, doc_path: Path) -> list[str]:
    """Drop the <name>.diffcache.json entries and source lines that no diff ref in doc or its history
    (load_history's shape) reads; refs validate has expanded come from the cache, not git."""
    if not _ref_candidates(doc) and not (history or {}).get("blocks"):
        return []
    try:
        dr = _diffref()
    except ImportError:
        return []
    if not dr.cache_path(doc_path).exists():
        return []
    probe = copy.deepcopy({"doc": doc, "history": list(((history or {}).get("blocks") or {}).values())})
    return [p for p in dr.expand_doc(probe, doc_path, allow_remote=False, prune=True) if p.startswith("WARN  diffcache")]


def build(doc: dict, template: str, history: dict | None = None, media_base: Path | None = None,
          diff_path: Path | None = None, problems: list[str] | None = None) -> str:
    """The page. media_base (the doc's folder) makes it standalone: media files become data: URIs.
    diff_path (the doc's JSON file) fills its diff refs, in the doc and in earlier revisions; their
    problems go into problems, or to stderr when it is None."""
    title = (doc.get("title") or "bluedoc").replace("&", "&amp;").replace("<", "&lt;")
    if "__BLUEDOC_DOC__" not in template:
        raise SystemExit("template is missing the __BLUEDOC_DOC__ placeholder")
    hist = embed_history(history, doc)   # before expanding and inlining: it matches blocks by their JSON
    if diff_path is not None:
        found: list[str] = []
        doc, hist = expand_diff_refs(doc, hist, Path(diff_path), found)
        if problems is None:
            for p in found:
                print(p, file=sys.stderr)
        else:
            problems += found
    if media_base is not None:
        missing: list[str] = []
        cache: dict[str, str] = {}
        doc = inline_media(doc, media_base, missing, cache)
        hist = inline_media(hist, media_base, missing, cache)
        for src in sorted(set(missing)):
            print(f"WARN  media '{src}': file not found, left as a relative path (it won't show from file://)", file=sys.stderr)
    return (template.replace("__BLUEDOC_TITLE__", title)
            .replace("__BLUEDOC_HISTORY__", _script_json(hist) if hist else "null")
            .replace("__BLUEDOC_DOC__", _script_json(doc)))


class HistoryError(Exception):
    pass


def sync_history(doc_path: Path, doc: dict) -> tuple[dict | None, str]:
    """Record doc in its history file under meta.rev; returns (history or None, log line).
    Raises HistoryError when meta.rev names an earlier revision or the file is unreadable."""
    if not (doc.get("meta") or {}).get("rev"):
        return None, "history: off (set meta.rev to keep revisions)"
    hpath = history_path(doc_path)
    try:
        history = load_history(hpath)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        raise HistoryError(f"cannot read {hpath}: {e}") from e
    before = _canon(history)
    log = record(history, doc)
    if log.startswith("ERROR"):
        raise HistoryError(log)
    if _canon(history) != before:
        tmp = hpath.with_name(hpath.name + ".tmp")
        tmp.write_text(json.dumps(history, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(hpath)
    return history, log


DOC_SUFFIXES = (".bluedoc.json", ".blueprint.json")   # the files serve.py lists and renders


def doc_stem(path: Path) -> str:
    """The doc's name without its suffix: acme-orders.bluedoc.json -> acme-orders."""
    name = path.name
    return next((name[:-len(s)] for s in DOC_SUFFIXES if name.endswith(s)), path.stem)


def write_doc(path: Path, doc: dict, raw: str) -> None:
    """Write doc atomically with the indent (none, 1, 2 or 4 spaces) and final newline raw had."""
    indent = None if not raw.startswith("{\n") else next(
        (n for n in (1, 2, 4) if raw.startswith("{\n" + " " * n + '"') and not raw.startswith("{\n" + " " * (n + 1))), 2)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=indent) + ("\n" if raw.endswith("\n") else ""), encoding="utf-8")
    tmp.replace(path)


def cmd_new(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="build.py new", description="Write the fill-in skeleton of a doc type. "
                                 "Replace every <<…>>; the build fails while one is left.")
    ap.add_argument("type", choices=sorted(DOC_TYPES))
    ap.add_argument("out", type=Path, help="the new <name>.bluedoc.json; its name becomes the doc id")
    ap.add_argument("--title", help="the doc's title")
    ap.add_argument("--kind", help="meta.kind, the eyebrow word (e.g. Architecture, Runbook)")
    a = ap.parse_args(argv)
    if not a.out.name.endswith(DOC_SUFFIXES):
        ap.error(f"name it <name>{DOC_SUFFIXES[0]}: serve.py lists those files")
    if a.out.exists():
        print(f"{a.out} exists; not overwriting it (edit it, or change it with build.py patch)", file=sys.stderr)
        return 2
    skel = SKELETONS / f"{a.type}.json"
    try:
        raw = skel.read_text(encoding="utf-8")
        doc = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot read skeleton {skel}: {e}", file=sys.stderr)
        return 2
    doc["id"] = re.sub(r"[^a-z0-9-]+", "-", doc_stem(a.out).lower()).strip("-") or "doc"
    if a.title:
        doc["title"] = a.title
    meta = doc.setdefault("meta", {})
    meta.update(rev="1", date=dt.date.today().isoformat(), type=a.type)
    if a.kind:
        meta["kind"] = a.kind
    a.out.parent.mkdir(parents=True, exist_ok=True)
    write_doc(a.out, doc, raw)
    print(f"wrote {a.out} ({a.type}): replace every <<…>>; `build.py {a.out} --check` lists the ones left")
    print(f"then: python3 {HERE / 'build.py'} {a.out} && python3 {HERE / 'serve.py'} open {a.out}")
    return 0


class PatchError(Exception):
    pass


class Target:
    """What a patch key names: obj, the place it sits (parent[key]), and its kind."""
    def __init__(self, obj, parent, key, kind: str) -> None:
        self.obj, self.parent, self.key, self.kind = obj, parent, key, kind


def _find(items, pred, what: str) -> tuple[dict, int]:
    for i, x in enumerate(items or []):
        if isinstance(x, dict) and pred(x):
            return x, i
    raise PatchError(f"no {what}")


def _index(items, i: str, what: str) -> int:
    if not i.isdigit() or int(i) >= len(items or []):
        raise PatchError(f"no {what} {i} (there are {len(items or [])})")
    return int(i)


def _item(doc: dict, cid: str, iid: str) -> Target:
    cl, _ = _find(list(all_blocks(doc)), lambda b: b.get("type") == "checklist" and b.get("id") == cid, f"checklist '{cid}'")
    it, i = _find(cl.get("items"), lambda x: x.get("id") == iid, f"item '{iid}' in checklist '{cid}'")
    return Target(it, cl["items"], i, "item")


def _block(doc: dict, parts: list[str], rest: int | None) -> tuple[Target, list[str]]:
    """The block a block path names: <section>/<index> or <checklist>/<item>/<index>, followed by
    `rest` more parts (None: one or more, as a file path has). Returns it and the parts after it."""
    def fits(n: int) -> bool:
        return len(parts) - n == rest if rest is not None else len(parts) - n >= 1
    secs = {s.get("id"): s for s in doc.get("sections") or [] if isinstance(s, dict)}
    if fits(2) and parts[0] in secs and parts[1].isdigit():
        blocks = secs[parts[0]].setdefault("blocks", [])
        i = _index(blocks, parts[1], f"block in section '{parts[0]}':")
        return Target(blocks[i], blocks, i, "block"), parts[2:]
    if fits(3) and parts[2].isdigit():
        it = _item(doc, parts[0], parts[1]).obj
        blocks = it.setdefault("blocks", [])
        i = _index(blocks, parts[2], f"block in item '{parts[0]}/{parts[1]}':")
        return Target(blocks[i], blocks, i, "block"), parts[3:]
    raise PatchError(f"'{'/'.join(parts)}' doesn't start with a block path: <section>/<index> or <checklist>/<item>/<index>")


def _line(doc: dict, key: str, path: str) -> Target:
    """line:<diff>/<path>:<n> (o<n>: old side) names a code line, which comes from git or the embedded
    hunks; the JSON object behind it is the diff's comment on <path> whose lines cover n."""
    did, _, rest = path.partition("/")
    fpath, _, num = rest.rpartition(":")
    side = "old" if num.startswith("o") else "new"
    n = num[1:] if side == "old" else num
    if not did or not fpath or not n.isdigit():
        raise PatchError(f"bad key '{key}': line:<diff>/<path>:<n>, or :o<n> for an old-side line")
    d, _ = _find(list(all_blocks(doc)), lambda b: b.get("type") == "diff" and b.get("id") == did, f"diff '{did}'")
    cs = d.get("comments") or []
    parse = _diffref().parse_comment
    whole = None
    for i, raw in enumerate(cs):
        c = parse(raw) if isinstance(raw, dict) else {}
        if c.get("file") != fpath or c.get("side", "new") != side:
            continue
        line = c.get("line")
        if line is None:
            whole = i if whole is None else whole   # a comment on the whole file, if no range covers n
        elif isinstance(line, int) and isinstance(c.get("end", line), int) and line <= int(n) <= c.get("end", line):
            return Target(cs[i], cs, i, "comment")
    if whole is not None:
        return Target(cs[whole], cs, whole, "comment")
    at = f'"at": "{fpath}:{n}"' if side == "new" else f'"file": "{fpath}", "line": {n}, "side": "old"'
    raise PatchError(f"{key} names code from git, and no comment in diff '{did}' covers {fpath}:{num}: change the code, "
                     f"patch the finding it belongs to (item:<checklist>/<item>), or add a comment with "
                     f"block:<blockPath> --append '{{{at}, \"item\": \"<checklist>/<item>\"}}'")


def resolve_key(doc: dict, key: str) -> Target:
    """The object an annotator key names (see the patch keys in this module's docstring). The key may
    keep the backticks reply Markdown wraps it in."""
    key = key.strip().strip("`").strip()
    kind, _, path = key.partition(":")
    parts = path.split("/") if path else []
    if kind in ("doc", "header", "tldr", "status") and not path:
        return Target(doc, None, None, "doc")
    if kind == "meta" and not path:
        return Target(doc.setdefault("meta", {}), doc, "meta", "meta")
    if kind in ("section", "heading", "lead") and len(parts) == 1:
        secs = doc.get("sections") or []
        s, i = _find(secs, lambda x: x.get("id") == path, f"section '{path}'")
        return Target(s, secs, i, "section")
    if kind in ("block", "media") and parts:
        return _block(doc, parts, 0)[0]
    if kind == "para" and parts:
        return _block(doc, parts, 1)[0]
    if kind == "compare" and parts:
        b, (side,) = _block(doc, parts, 1)
        if side not in ("before", "after") or not isinstance(b.obj.get(side), dict):
            raise PatchError(f"no compare side '{side}' (before or after)")
        return Target(b.obj[side], b.obj, side, "side")
    if kind == "item" and len(parts) == 2:
        return _item(doc, *parts)
    if kind in ("row", "card", "step") and parts:
        b, (last,) = _block(doc, parts, 1)
        if kind == "row":
            rows = b.obj.get("rows")
            i = _index(rows, last, "row")
            return Target(rows[i], rows, i, "row")
        items = b.obj.get("items")
        if kind == "card":
            i = _index(items, last, "card")
            return Target(items[i], items, i, "card")
        it, i = _find(items, lambda x: x.get("id") == last, f"step '{last}' in that block")
        return Target(it, items, i, "step")
    if kind == "file" and parts:
        b, rest = _block(doc, parts, None)
        fpath = "/".join(rest)
        items = b.obj.get("items")
        it, i = _find(items, lambda x: x.get("path") == fpath, f"file row '{fpath}' in that block")
        return Target(it, items, i, "file")
    if kind == "node" and len(parts) >= 2:
        cv, _ = _find(list(all_blocks(doc)), lambda b: b.get("type") == "canvas" and b.get("id") == parts[0], f"canvas '{parts[0]}'")
        nodes, t = cv.get("nodes"), None
        for nid in parts[1:]:
            n, i = _find(nodes, lambda x: x.get("id") == nid, f"node '{'/'.join(parts[1:])}' in canvas '{parts[0]}'")
            t = Target(n, nodes, i, "node")
            nodes = (n.get("children") or {}).get("nodes")
        return t
    if kind == "comment" and len(parts) == 2:
        d, _ = _find(list(all_blocks(doc)), lambda b: b.get("type") == "diff" and b.get("id") == parts[0], f"diff '{parts[0]}'")
        cs = d.get("comments")
        i = _index(cs, parts[1], f"comment in diff '{parts[0]}':")
        return Target(cs[i], cs, i, "comment")
    if kind == "line":
        return _line(doc, key, path)
    raise PatchError(f"unknown key '{key}': see `build.py --help` for the key forms")


# the list --append adds to, per target kind (blocks: per block type)
APPEND_FIELD = {"doc": "sections", "section": "blocks", "item": "blocks"}
APPEND_BLOCK_FIELD = {"table": "rows", "canvas": "nodes", "diff": "comments", "checklist": "items", "steps": "items",
                      "files": "items", "cards": "items", "terms": "items"}


def _value(s: str):
    """A command-line value: JSON when it parses, else the string itself."""
    try:
        return json.loads(s)
    except ValueError:
        return s


def _merge(obj: dict, fields: dict) -> None:
    for k, v in fields.items():
        if v is None:
            obj.pop(k, None)
        else:
            obj[k] = v


def apply_patch(t: Target, sets: list[str], merge: str | None, append: str | None, delete: bool) -> None:
    if delete:
        if t.kind in ("doc", "meta"):
            raise PatchError(f"can't delete the {t.kind}")
        del t.parent[t.key]
        return
    for s in sets:
        field, eq, v = s.partition("=")
        if not eq or not field:
            raise PatchError(f"--set '{s}': write field=value")
        if isinstance(t.obj, list):   # a table row: field is the cell index
            t.obj[_index(t.obj, field, "cell")] = _value(v)
        else:
            _merge(t.obj, {field: _value(v)})
    if merge is not None:
        v = _value(merge)
        if isinstance(t.obj, list) and isinstance(v, list):
            t.obj[:] = v
        elif isinstance(t.obj, dict) and isinstance(v, dict):
            _merge(t.obj, v)
        else:
            raise PatchError("--json takes an object to merge (a list replaces a table row)")
    if append is not None:
        if isinstance(t.obj, list):
            t.obj.append(_value(append))
            return
        if t.kind == "block":
            field = APPEND_BLOCK_FIELD.get(t.obj.get("type"))
        elif t.kind == "node":
            t.obj.setdefault("children", {})
            t.obj["children"].setdefault("nodes", []).append(_value(append))
            return
        else:
            field = APPEND_FIELD.get(t.kind)
        if not field:
            raise PatchError(f"--append: a {t.obj.get('type') or t.kind} has no list to append to")
        t.obj.setdefault(field, []).append(_value(append))


def next_rev(rev: str) -> str:
    """A -> B, Z -> AA, 3 -> 4, v1 -> v2, 09 -> 10; no rev yet -> A."""
    if not rev:
        return "A"
    m = re.fullmatch(r"(.*?)(\d+)", rev)
    if m:
        return m.group(1) + str(int(m.group(2)) + 1).zfill(len(m.group(2)))
    if re.fullmatch(r"[A-Za-z]+", rev):
        chars = list(rev.upper())
        i = len(chars) - 1
        while i >= 0 and chars[i] == "Z":
            chars[i] = "A"
            i -= 1
        if i < 0:
            chars.insert(0, "A")
        else:
            chars[i] = chr(ord(chars[i]) + 1)
        out = "".join(chars)
        return out if rev[-1].isupper() else out.lower()
    raise PatchError(f"can't bump rev '{rev}': set meta.rev yourself and pass --no-bump")


def cmd_patch(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="build.py patch", description="Change one object by its annotator key, bump meta.rev, "
                                 "validate, write and record the revision. Key forms: see `build.py --help`.")
    ap.add_argument("doc", type=Path)
    ap.add_argument("key", help="e.g. item:t412/tier-boundary, step:steps/0/s3, row:risks/0/2, meta, tldr")
    ap.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE", help="set one field (JSON value, else a string; null deletes)")
    ap.add_argument("--json", metavar="OBJ", help="merge these fields (null deletes one)")
    ap.add_argument("--append", metavar="VALUE", help="append to the target's list (items, rows, nodes, blocks, comments)")
    ap.add_argument("--delete", action="store_true", help="remove the target")
    ap.add_argument("--change", action="append", default=[], metavar="LINE", help="a line for `changes` (repeat for more)")
    ap.add_argument("--no-bump", action="store_true", help="keep meta.rev: update the current revision in place")
    a = ap.parse_args(argv)
    if not (a.set or a.json is not None or a.append is not None or a.delete):
        ap.error("give --set, --json, --append or --delete")
    if a.delete and (a.set or a.json is not None or a.append is not None):
        ap.error("--delete goes alone")
    try:
        raw = a.doc.read_text(encoding="utf-8")
        doc = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot read {a.doc}: {e}", file=sys.stderr)
        return 2
    before = copy.deepcopy(doc)
    a.key = a.key.strip().strip("`").strip()
    try:
        apply_patch(resolve_key(doc, a.key), a.set, a.json, a.append, a.delete)
        meta = doc.setdefault("meta", {})
        rev0 = str(meta.get("rev") or "")
        rev1 = rev0 if a.no_bump else next_rev(rev0)
    except PatchError as e:
        print(f"patch: {e}", file=sys.stderr)
        return 2
    if a.no_bump:
        if a.change:
            doc["changes"] = list(doc.get("changes") or []) + a.change
    else:
        meta.update(rev=rev1, date=dt.date.today().isoformat())
        doc["changes"] = a.change or [f"Updated `{a.key}`."]
    rep = validate(doc, a.doc)
    if rep.errors:
        for line in rep.errors:
            print(line, file=sys.stderr)
        print(f"patch: {len(rep.errors)} error(s); {a.doc} not written", file=sys.stderr)
        return 1
    try:
        if rev0 and not a.no_bump:
            sync_history(a.doc, before)   # the text this patch replaces stays its own revision
        write_doc(a.doc, doc, raw)
        history, _ = sync_history(a.doc, doc)
    except HistoryError as e:
        print(e, file=sys.stderr)
        return 1
    for line in prune_diff_cache(doc, history, a.doc):
        print(line, file=sys.stderr)
    # only the warnings this patch introduced
    old = set(validate(before, a.doc, write_cache=False).warnings)
    for line in rep.warnings:
        if line not in old:
            print(line, file=sys.stderr)
    print(f"rev {rev0 or '-'} → {rev1}; {a.key} {'deleted' if a.delete else 'updated'}")
    if rev0 and rev0 != rev1:
        try:   # the link the reader needs, when the doc is under a registered folder
            import serve
            url = serve.url_for(Path(a.doc))
            if url:
                print(f"send the reader: {serve.base()}{url}?diff={rev0}")
        except Exception:
            pass
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["new"]:
        return cmd_new(argv[1:])
    if argv[:1] == ["patch"]:
        return cmd_patch(argv[1:])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("doc", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="also write a standalone HTML file (for sharing; serve.py renders the JSON directly)")
    ap.add_argument("--check", action="store_true", help="validate and lint only; write nothing (history, diff cache)")
    ap.add_argument("--strict", action="store_true", help="fail on lint warnings")
    ap.add_argument("--template", type=Path, default=TEMPLATE)
    ap.add_argument("--no-history", action="store_true", help="don't read or write <doc>.history.json")
    ap.add_argument("--show-rev", metavar="REV", help="print that revision from the history as JSON and exit")
    a = ap.parse_args(argv)
    hpath = history_path(a.doc)
    if a.show_rev is not None:
        try:
            h = load_history(hpath)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            print(f"cannot read {hpath}: {e}", file=sys.stderr)
            return 2
        entry = next((e for e in h["revs"] if e["rev"] == a.show_rev), None)
        if not entry:
            print(f"no rev {a.show_rev} in {hpath}; have: {', '.join(e['rev'] for e in h['revs']) or 'none'}", file=sys.stderr)
            return 2
        print(json.dumps(restore(h, entry), ensure_ascii=False, indent=2))
        return 0
    try:
        doc = json.loads(a.doc.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot read {a.doc}: {e}", file=sys.stderr)
        return 2
    rep = validate(doc, a.doc, write_cache=not a.check)
    for line in rep.errors + rep.warnings:
        print(line, file=sys.stderr)
    print(f"{len(rep.errors)} error(s), {len(rep.warnings)} warning(s)", file=sys.stderr)
    if rep.errors or (a.strict and rep.warnings):
        return 1
    if a.check:
        return 0
    history = None
    if not a.no_history:
        try:
            history, log = sync_history(a.doc, doc)
        except HistoryError as e:
            print(e, file=sys.stderr)
            return 1
        print(log, file=sys.stderr)
        for line in prune_diff_cache(doc, history, a.doc):
            print(line, file=sys.stderr)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(build(doc, a.template.read_text(encoding="utf-8"), history, a.doc.resolve().parent, a.doc), encoding="utf-8")
        print(f"wrote {a.out} ({a.out.stat().st_size // 1024} KB)", file=sys.stderr)
    else:
        print(f"view: python3 {HERE / 'serve.py'} open {a.doc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
