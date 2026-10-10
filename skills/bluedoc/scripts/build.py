#!/usr/bin/env python3
"""Validate a bluedoc JSON document, record its revision, optionally write standalone HTML.

Usage:
  build.py doc.json                 validate, lint, record the revision (view it with serve.py)
  build.py doc.json -o out.html     same, plus a standalone HTML file for sharing offline (media and diffs inlined)
  build.py doc.json --check         validate and lint only; writes nothing (no history, no diff cache)
  build.py doc.json --strict        treat lint warnings as errors
  build.py doc.json --show-rev B    print revision B, rebuilt from the history, as JSON
  build.py new TYPE out.bluedoc.json [--title T] [--kind K] [--shape pr|area] [--target T,…] [--framework F]
                                    write the fill-in skeleton of a docs|review|plan|design|other doc
                                    (--shape area: a review by area of a codebase, not by PR; design: one
                                    wireframe screen file per --target watch|mobile|tablet|desktop|web, three
                                    slides for presentation)
  build.py patch doc.json KEY [--set f=v ...] [--json OBJ] [--append OBJ] [--delete] [--html FILE|-]
                              [--change LINE ...] [--no-bump]
                                    change one object by its annotator key, bump meta.rev, validate, record

serve.py renders the JSON with assets/template.html on every request, so normal work needs no
HTML file at all: write the JSON, run build.py, open the serve.py URL.

Revisions: every build (and every patch) records the document under its `meta.rev` in
<doc>.history.json next to the JSON (doc.bluedoc.json -> doc.bluedoc.history.json). A new rev
appends; the same rev replaces that entry. A design doc's screen files join the revision: their text
sits in the history's `html` pool by hash. The page embeds the history (screens as hashes only), so
readers can switch revisions and compare two. --no-history skips reading and writing it.

Type contracts: each meta.type needs its data (review: a diff and sized findings; plan: steps and
files blocks; docs: a canvas or a hero; design: one board with an artboard). Missing data is an error on
the doc being built: a new meta.rev, or a recorded rev whose text changed (an edit in place). It is a
warning only while the doc is exactly the revision its history recorded, so old revisions keep rendering.

Screens (design docs): each artboard's HTML is a body fragment in <stem>.design/<id>.html. The build
fails on a missing file, a network URL, <base>, <iframe>, <object>, <embed>, <meta http-equiv>,
<form action> or a whole document; it warns above 24 KB and when no element has a data-bd name.

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
  Design keys: artboard:<id> (the artboard; --html FILE replaces its screen file), el:<id>/<path>
  (an element: data-bd names joined by '/', else a CSS path), frame:<device or WxH>@<x>,<y> (appends
  an artboard there and writes a stub screen file). artboard: and el: with no --set/--json/--html
  print the screen file and the element's selector; with only --change they record a hand edit of
  the screen file as the next rev.
  <blockPath> is <section>/<index> or <checklist>/<item>/<index>. header, tldr and status address
  the doc's top level. --set and --json values parse as JSON when they can; null deletes the field.
  --append adds to the target's list (doc: sections, section and item: blocks, table: rows,
  canvas: nodes, diff: comments, board: artboards, other blocks: items). The rev bumps (A->B, 3->4,
  v1->v2) and meta.date becomes today unless --no-bump; on a bump `changes` becomes the --change lines
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
import os
import re
import shlex
import sys
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "assets" / "template.html"
SKELETONS = HERE.parent / "assets" / "skeletons"
HISTORY_VERSION = 1

BLOCK_TYPES = {"text", "callout", "table", "code", "terms", "cards", "checklist", "canvas", "diff", "steps", "files", "media", "compare",
               "board"}
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
DOC_TYPES = {"docs", "review", "plan", "design", "other"}   # meta.type: the home page's grouping; unset = derived from meta.kind
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
# design docs: one board block of artboards; each artboard's HTML is a body fragment in <stem>.design/<id>.html
# device -> CSS px size and the safe area the kit exposes [top, right, bottom, left]; serve.py and the page read this
# table (watch-round: the kit derives --safe-inset, the inscribed square, from the diameter)
DEVICES = {"watch-round": {"w": 240, "h": 240, "safe": [0, 0, 0, 0]}, "watch-square": {"w": 198, "h": 242, "safe": [8, 8, 8, 8]},
           "phone": {"w": 390, "h": 844, "safe": [47, 0, 34, 0]}, "tablet": {"w": 820, "h": 1180, "safe": [24, 0, 20, 0]},
           "desktop": {"w": 1280, "h": 800, "safe": [32, 0, 0, 0]}, "browser": {"w": 1440, "h": 900, "safe": [72, 0, 0, 0]},
           "slide": {"w": 1920, "h": 1080, "safe": [0, 0, 0, 0]}}
TARGET_DEVICES = {"watch": "watch-round", "mobile": "phone", "tablet": "tablet", "desktop": "desktop", "web": "browser",
                  "presentation": "slide"}
# `build.py new design --target presentation`: the stub deck, one slide artboard each, in deck order
STUB_SLIDES = (("title", "Title slide: the deck's title and who presents it"), ("content", "Content slide: its one point"),
               ("closing", "Closing slide: the ask or next step"))
MAX_NOTES_BYTES = 2 * 1024        # an artboard's speaker notes, shown under the slide in Present
FIDELITIES = ("sketch", "wireframe", "hifi")
BUILTIN_FRAMEWORKS = ("plain", "horizon")
FRAMEWORK_EXTS = {".css", ".js", ".mjs"}
BOARD_GAP = 80                    # px between artboards placed without x/y
MAX_SCREEN_BYTES = 24 * 1024      # a screen file above this is a warning: edit fragments in place, don't regrow them
TOKEN_KEY = re.compile(r"^[a-z][a-z0-9-]*$")
TOKEN_VALUE = re.compile(r"^[^;{}<>\\]*$")
MOTION_KEYS = ("fast", "base", "slow", "ease")
SCREEN_SRC = re.compile(r"^(?:[\w.-]+/)*[\w.-]+\.design/[\w.-]+\.html$")

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
    if not isinstance(text, str):
        if text is not None:
            rep.err(where, f"{_shown(text)} is {_json_type(text)}: must be a string")
        return
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


# The JSON type of every field validate() reads as more than text (a key, a number, a list it walks).
# check_shape reports each mismatch at its path before anything reads it, so a wrong type is an ERROR
# line, not a traceback. NUMBER: an int or float, not true/false; SCOPE: a canvas level, recursively
# through node children; BLOCK: a block, checked against BLOCK_SHAPES[its type].
NUMBER, SCOPE, BLOCK = "number", "scope", "block"
SCOPE_SHAPE = {"nodes": [{"id": str, "label": str, "kind": str, "state": str, "x": NUMBER, "y": NUMBER,
                          "col": NUMBER, "row": NUMBER, "w": NUMBER, "h": NUMBER, "children": SCOPE}],
               "edges": [{"id": str, "from": str, "to": str, "kind": str, "label": str}],
               "flows": [{"steps": [{"edge": str, "edges": [str]}]}]}
ITEM_SHAPE = {"id": str, "text": str, "sub": str, "recommend": str, "choice": str, "refs": [str], "blocks": [BLOCK],
              "choices": [{"id": str, "label": str}]}
BLOCK_SHAPES = {
    "text": {"md": str}, "callout": {"md": str, "kind": str}, "code": {"code": str},
    "table": {"columns": list, "rows": [list]}, "terms": {"items": [dict]}, "cards": {"items": [dict]},
    "checklist": {"id": str, "items": [ITEM_SHAPE]}, "canvas": {"id": str, **SCOPE_SHAPE},
    "diff": {"id": str, "base": str, "head": str, "files": [{"path": str, "status": str}],
             "comments": [{"file": str, "item": str}]},
    "steps": {"id": str, "items": [{"id": str, "title": str, "status": str, "effort": str, "refs": [str]}]},
    "files": {"items": [{"path": str, "action": str, "step": str}]},
    "board": {"id": str, "targets": [str], "framework": str,
              "frameworks": [{"id": str, "label": str, "files": [str], "store": str}],
              "themes": [{"id": str, "label": str, "tokens": dict}], "motion": dict,
              "artboards": [{"id": str, "title": str, "device": str, "fidelity": str, "x": NUMBER, "y": NUMBER,
                             "w": NUMBER, "h": NUMBER, "variantOf": str, "framework": str, "src": str, "notes": str}]},
}
DOC_SHAPE = {"title": str, "meta": {"type": str}, "state": [{"kind": str}],
             "sections": [{"id": str, "title": str, "blocks": [BLOCK]}]}
JSON_TYPES = {dict: "an object", list: "a list", str: "a string", NUMBER: "a number"}


def _json_type(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true/false"
    return next((name for t, name in JSON_TYPES.items() if t != NUMBER and isinstance(v, t)), "a number")


def _shown(v) -> str:
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= 40 else s[:39] + "…"


def check_shape(rep: Report, where: str, value, spec) -> None:
    """Report every field of value whose JSON type isn't the one spec names (DOC_SHAPE's notation).
    A null field counts as absent, except a NUMBER: validate() reads positions when the key is there."""
    if spec == SCOPE:
        spec = SCOPE_SHAPE
    elif spec == BLOCK:
        t = value.get("type") if isinstance(value, dict) else None
        spec = {"type": str, **(BLOCK_SHAPES.get(t, {}) if isinstance(t, str) else {})}
    if isinstance(spec, dict):
        if not isinstance(value, dict):
            rep.err(where, f"{_shown(value)} is {_json_type(value)}: must be an object")
            return
        for k, sub in spec.items():
            if k in value and (value[k] is not None or sub == NUMBER):
                check_shape(rep, f"{where}.{k}", value[k], sub)
    elif isinstance(spec, list):
        if not isinstance(value, list):
            rep.err(where, f"{_shown(value)} is {_json_type(value)}: must be a list")
            return
        for i, v in enumerate(value):
            check_shape(rep, f"{where}[{i}]", v, spec[0])
    elif not (isinstance(value, (int, float)) and not isinstance(value, bool) if spec == NUMBER else isinstance(value, spec)):
        rep.err(where, f"{_shown(value)} is {_json_type(value)}: must be {JSON_TYPES[spec]}")


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
    """docs | review | plan | design | other: meta.type when set, else read from meta.kind (a design only by
    meta.type: a kind like 'Design' stays docs). template.html follows the same rule; serve.py puts the result
    in the home page's index."""
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


def board_of(doc: dict) -> dict | None:
    """The design doc's board block (the first, if a doc wrongly has more), or None."""
    return next((b for b in all_blocks(doc) if b.get("type") == "board"), None) if isinstance(doc, dict) else None


def _screen_src_ok(src) -> bool:
    return isinstance(src, str) and bool(SCREEN_SRC.match(src)) and ".." not in src.split("/")


def screen_rel(doc_path: Path, a: dict) -> str:
    """An artboard's screen file relative to the doc's folder: its src, else <stem>.design/<id>.html. An invalid
    src (validate reports it) falls back to the default."""
    return a["src"] if _screen_src_ok(a.get("src")) else f"{doc_stem(Path(doc_path))}.design/{a['id']}.html"


def screen_paths(doc: dict, doc_path: Path) -> dict[str, Path]:
    """{artboard id: its screen file}; {} for a doc without a board."""
    b = board_of(doc)
    arts = b.get("artboards") if isinstance(b, dict) else None
    if not isinstance(arts, list):
        return {}
    folder = Path(doc_path).parent
    return {a["id"]: folder / screen_rel(doc_path, a)
            for a in arts if isinstance(a, dict) and isinstance(a.get("id"), str) and ID_RE.match(a["id"])}


def _read_text(f: Path) -> str | None:
    try:
        return f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def read_screens(doc: dict, doc_path: Path) -> dict[str, str | None]:
    """{artboard id: its screen file's text, None when unreadable}; {} for a doc without a board."""
    return {aid: _read_text(f) for aid, f in screen_paths(doc, doc_path).items()}


def screen_hashes(doc: dict, doc_path: Path) -> dict[str, str | None]:
    """{artboard id: _hash of its screen file's text, None when unreadable}: the keys of the history's html pool."""
    return {aid: None if text is None else _hash(text) for aid, text in read_screens(doc, doc_path).items()}


def approval_hash(doc, doc_path: Path | None = None) -> str:
    """The docHash an approval carries: sha256 of the doc's canonical JSON (sorted keys, no spaces), and for a doc
    with a board also of its screen hashes, so editing a screen file asks for approval again."""
    canon = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    screens = screen_hashes(doc, doc_path) if doc_path is not None and isinstance(doc, dict) else {}
    if screens:
        canon += "\n" + json.dumps(screens, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def screen_source(doc_path: Path, artboard_id: str, rev: str | None = None) -> str | None:
    """A screen's HTML fragment: the file as it is now, or the text the history recorded for revision rev.
    None when the doc, the artboard, the revision or the text isn't there."""
    doc_path = Path(doc_path)
    if rev is None:
        try:
            doc = json.loads(doc_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        f = screen_paths(doc, doc_path).get(artboard_id)
        return _read_text(f) if f else None
    try:
        h = load_history(history_path(doc_path))
    except (OSError, ValueError):
        return None
    entry = next((e for e in h["revs"] if e.get("rev") == rev), None)
    k = ((entry or {}).get("screens") or {}).get(artboard_id)
    return (h.get("html") or {}).get(k) if k else None


def artboard_size(a: dict) -> tuple[float, float] | None:
    """(w, h) in CSS px: the device's, else the artboard's w and h; None when neither is valid."""
    dev = DEVICES.get(a.get("device")) if isinstance(a.get("device"), str) else None
    if dev:
        return dev["w"], dev["h"]
    w, h = a.get("w"), a.get("h")
    ok = all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in (w, h))
    return (w, h) if ok and "device" not in a else None


def board_layout(board: dict) -> dict[str, tuple[float, float, float, float]]:
    """{artboard id: (x, y, w, h)} in board order. An artboard with x and y sits there; else its row is its
    variantOf source's y (when placed before it), else 0, and it goes BOARD_GAP right of the rightmost
    artboard already in that row (x 0 in an empty row). template.html places them by the same rule."""
    out: dict[str, tuple[float, float, float, float]] = {}
    for a in board.get("artboards") or []:
        if not isinstance(a, dict) or not isinstance(a.get("id"), str) or a["id"] in out:
            continue
        size = artboard_size(a)
        if not size:
            continue
        x, y = a.get("x"), a.get("y")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (x, y)):
            src = out.get(a.get("variantOf")) if isinstance(a.get("variantOf"), str) else None
            y = src[1] if src else 0
            row = [bx + bw for bx, by, bw, _ in out.values() if by == y]
            x = max(row) + BOARD_GAP if row else 0
        out[a["id"]] = (x, y, *size)
    return out


def frameworks_dir() -> Path:
    """Where `serve.py add-framework` copies frameworks: $BLUEDOC_HOME/frameworks, ~/.bluedoc by default."""
    return Path(os.environ.get("BLUEDOC_HOME") or "~/.bluedoc").expanduser() / "frameworks"


# a network URL in a URL attribute, CSS or an event handler: a scheme that fetches, or a scheme-relative //host
NET_URL = re.compile(r"(?i)\b(?:https?|wss?|ftp):|(?:^|[\s'\"(=,])//[\w.-]")
# in a <script>: a fetching scheme, or a quoted //host (a bare // starts a comment)
SCRIPT_NET_URL = re.compile(r"(?i)\b(?:https?|wss?|ftp):|['\"`]//[\w.-]")
URL_ATTRS = {"href", "src", "srcset", "imagesrcset", "action", "formaction", "poster", "data", "background", "cite",
             "ping", "manifest", "xlink:href", "codebase", "longdesc", "lowsrc", "dynsrc", "icon", "archive", "profile"}
BANNED_TAGS = {"base": "it re-points every relative URL", "iframe": "screens can't nest frames",
               "frame": "screens can't nest frames", "object": "it loads external content", "embed": "it loads external content"}
DOC_TAGS = {"html", "head", "body"}


class _ScreenLint(HTMLParser):
    """A screen fragment's problems, one per construct, as (line, message); and whether any data-bd is set."""
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.errors: list[tuple[int, str]] = []
        self.whole_doc = False
        self.has_bd = False
        self._raw: str | None = None   # "style" or "script" while inside one

    def _doc(self) -> None:
        if not self.whole_doc:
            self.whole_doc = True
            self.errors.append((self.getpos()[0], "a whole document (<!doctype>, <html>, <head> or <body>): write only "
                                "the body's content; the server adds the shell"))

    def handle_decl(self, decl: str) -> None:
        if decl.lower().startswith("doctype"):
            self._doc()

    def handle_starttag(self, tag: str, attrs) -> None:
        names = {k for k, _ in attrs}
        if "data-bd" in names:
            self.has_bd = True
        if tag in ("style", "script"):
            self._raw = tag
        line = self.getpos()[0]
        if tag in DOC_TAGS:
            self._doc()
        elif tag in BANNED_TAGS:
            self.errors.append((line, f"<{tag}>: {BANNED_TAGS[tag]}"))
        elif tag == "meta" and "http-equiv" in names:
            self.errors.append((line, "<meta http-equiv>: it can refresh or redirect the frame, which the CSP can't stop"))
        elif tag == "form" and "action" in names:
            self.errors.append((line, "<form action>: a screen posts nowhere; drop 'action'"))
        else:
            bad = next((k for k, v in attrs if v and (k in URL_ATTRS or k == "style" or k.startswith("on"))
                        and NET_URL.search(v)), None)
            if bad:
                self.errors.append((line, f"<{tag} {bad}>: a network URL; screens load nothing from the network: "
                                    "put the file beside the screen or use a data: URI"))

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag: str) -> None:
        if tag == self._raw:
            self._raw = None

    def handle_data(self, data: str) -> None:
        pattern = {"style": NET_URL, "script": SCRIPT_NET_URL}.get(self._raw or "")
        if pattern and pattern.search(data):
            self.errors.append((self.getpos()[0], f"<{self._raw}>: a network URL; screens load nothing from the network"))


def lint_screen(rep: Report, where: str, f: Path, shown: str) -> None:
    """A screen file: an ERROR when it is missing or holds a network URL, a banned tag or a whole document; a WARN
    above MAX_SCREEN_BYTES or without any data-bd (the annotator's element names)."""
    text = _read_text(f)
    if text is None:
        rep.err(where, f"screen file {shown} is missing or unreadable: write the artboard's HTML fragment there")
        return
    size = len(text.encode("utf-8"))
    if size > MAX_SCREEN_BYTES:
        rep.warn(where, f"{shown} is {size // 1024} KB (> {MAX_SCREEN_BYTES // 1024} KB): use kit classes, split it into "
                 "artboards, and edit it in place rather than rewriting it")
    p = _ScreenLint()
    p.feed(text)
    p.close()
    for line, msg in p.errors:
        rep.err(f"{where} {shown}:{line}", msg)
    if not p.has_bd:
        rep.warn(where, f"{shown} has no data-bd: name the elements a reader may point at (data-bd=\"submit\")")


def validate_board(rep: Report, bw: str, b: dict, doc: dict, doc_path: Path | None) -> None:
    """A board block: its frameworks, themes, motion and artboards, the brief's options against them, and the
    screen files (when doc_path is known)."""
    if not need(rep, bw, b, "id", "artboards"):
        return
    check_id(rep, bw, b["id"])
    base = Path(doc_path).resolve().parent if doc_path else None
    for i, t in enumerate(b.get("targets") or []):
        if t not in TARGET_DEVICES:
            rep.err(f"{bw}.targets[{i}]", f"'{t}' not in {sorted(TARGET_DEVICES)}")
    fw_ids = set(BUILTIN_FRAMEWORKS)
    for i, fw in enumerate(b.get("frameworks") or []):
        fwh = f"{bw}.frameworks[{i}]"
        if not need(rep, fwh, fw, "id", "label"):
            continue
        check_id(rep, fwh, fw["id"])
        if fw["id"] in fw_ids:
            rep.err(fwh, f"framework id '{fw['id']}' is {'built in' if fw['id'] in BUILTIN_FRAMEWORKS else 'a duplicate'}")
        fw_ids.add(fw["id"])
        if ("files" in fw) == ("store" in fw):
            rep.err(fwh, "give 'files' (paths from the doc's folder) or 'store' (a `serve.py add-framework` name), not both")
            continue
        if "store" in fw:
            check_id(rep, fwh + ".store", fw["store"])
            man = frameworks_dir() / fw["store"] / "manifest.json"
            if ID_RE.match(fw["store"]) and not man.is_file():
                rep.warn(fwh + ".store", f"{man.parent} not found: its screens show the plain kit until the reader runs "
                         f"`serve.py add-framework {fw['store']} <path|url>`")
            continue
        if not fw["files"]:
            rep.err(fwh + ".files", "list the framework's .css/.js/.mjs files")
        for j, path in enumerate(fw["files"]):
            fp = f"{fwh}.files[{j}]"
            if not path or URL_SCHEME.match(path) or path.startswith(("/", "\\")) or NET_URL.search(path):
                rep.err(fp, f"'{path}': a path relative to the doc's folder, no URL")
            elif Path(path).suffix.lower() not in FRAMEWORK_EXTS:
                rep.err(fp, f"'{path}': a framework file is one of {sorted(FRAMEWORK_EXTS)}")
            elif base is not None and not (base / path).is_file():
                rep.warn(fp, f"'{path}' not found (from {base}): screens using '{fw['id']}' show the plain kit")
    if b.get("framework") is not None and b["framework"] not in fw_ids:
        rep.err(bw + ".framework", f"'{b['framework']}' not in {sorted(fw_ids)}")
    theme_ids: set[str] = set()
    for i, th in enumerate(b.get("themes") or []):
        thw = f"{bw}.themes[{i}]"
        if not need(rep, thw, th, "id", "label", "tokens"):
            continue
        check_id(rep, thw, th["id"])
        if th["id"] in theme_ids:
            rep.err(thw, f"duplicate theme id '{th['id']}'")
        theme_ids.add(th["id"])
        for k, v in th["tokens"].items():
            if not TOKEN_KEY.match(k):
                rep.err(f"{thw}.tokens", f"token '{k}' must match {TOKEN_KEY.pattern} (it becomes the CSS variable --{k})")
            elif not isinstance(v, str) or not TOKEN_VALUE.match(v) or "url(" in v.lower():
                rep.err(f"{thw}.tokens.{k}", f"{_shown(v)}: a CSS value as a string, without ; {{ }} < > \\ or url()")
    for k, v in (b.get("motion") or {}).items():
        if k not in MOTION_KEYS:
            rep.err(f"{bw}.motion", f"'{k}' not in {list(MOTION_KEYS)}")
        elif not isinstance(v, str) or not TOKEN_VALUE.match(v) or "url(" in v.lower():
            rep.err(f"{bw}.motion.{k}", f"{_shown(v)}: a CSS time or easing as a string")
    if not b["artboards"]:
        rep.err(bw + ".artboards", "a board needs at least one artboard")
    art_ids: set[str] = set()
    variants: list[tuple[str, str, str]] = []
    for i, a in enumerate(b["artboards"]):
        aw = f"{bw}.artboards[{i}]"
        if not isinstance(a, dict) or not need(rep, aw, a, "id", "title", "fidelity"):
            continue
        check_id(rep, aw, a["id"])
        if a["id"] in art_ids:
            rep.err(aw, f"duplicate artboard id '{a['id']}'")
        art_ids.add(a["id"])
        lint_text(rep, aw + ".title", a["title"])
        if isinstance(a.get("notes"), str):
            size = len(a["notes"].encode("utf-8"))
            if size > MAX_NOTES_BYTES:
                rep.err(aw + ".notes", f"{size} bytes (at most {MAX_NOTES_BYTES}): speaker notes are a few talking "
                        "points; put the rest in the slide or the brief")
            lint_text(rep, aw + ".notes", a["notes"])
        if "device" in a:
            if a["device"] not in DEVICES:
                rep.err(aw + ".device", f"'{a['device']}' not in {sorted(DEVICES)}; or drop it and give w and h")
            elif "w" in a or "h" in a:
                rep.err(aw, "give 'device' or 'w' and 'h', not both")
        elif artboard_size(a) is None:
            rep.err(aw, f"give 'device' (one of {sorted(DEVICES)}) or 'w' and 'h', positive CSS px")
        if a["fidelity"] not in FIDELITIES:
            rep.err(aw + ".fidelity", f"'{a['fidelity']}' not in {list(FIDELITIES)}")
        if ("x" in a) != ("y" in a):
            rep.err(aw, "give both 'x' and 'y', or neither (the board places it)")
        if a.get("framework") is not None and a["framework"] not in fw_ids:
            rep.err(aw + ".framework", f"'{a['framework']}' not in {sorted(fw_ids)}")
        if a.get("variantOf") is not None:
            variants.append((aw + ".variantOf", a["id"], a["variantOf"]))
        if "src" in a and not _screen_src_ok(a["src"]):
            rep.err(aw + ".src", f"'{a['src']}': a relative path to an .html file in a <name>.design/ folder, no '..'")
        if doc_path is not None and ID_RE.match(a["id"]):
            rel = screen_rel(doc_path, a)
            lint_screen(rep, aw, Path(doc_path).parent / rel, rel)
    for where, aid, src in variants:
        if src == aid or src not in art_ids:
            rep.err(where, f"'{src}' is {'the artboard itself' if src == aid else 'no artboard in this board'}")
    brief = next((c for c in all_blocks(doc) if c.get("type") == "checklist" and c.get("id") == "brief"), None)
    for it in (brief or {}).get("items") or []:
        if not isinstance(it, dict) or not isinstance(it.get("choices"), list):
            continue
        ids = {c.get("id") for c in it["choices"] if isinstance(c, dict)}
        iw = f"item brief/{it.get('id')}"
        if it.get("id") == "framework":
            for c in sorted(ids - fw_ids, key=str):
                rep.err(iw, f"option '{c}' is no framework: add it to {bw}.frameworks or use one of {sorted(fw_ids)}")
        elif it.get("id") == "theme":
            for c in sorted(ids - theme_ids, key=str):
                rep.err(iw, f"option '{c}' has no theme in {bw}.themes: picking it couldn't re-skin the screens")
            for t in sorted(theme_ids - ids):
                rep.err(f"{bw}.themes", f"theme '{t}' is no option of {iw}: the reader couldn't pick it")


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
    elif t == "design":
        boards = [b for b in blocks if b.get("type") == "board"]
        if len(boards) != 1:
            out.append(f"a design needs exactly one board block (it has {len(boards)})")
        elif not boards[0].get("artboards"):
            out.append("a design's board needs at least one artboard")
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
        same = (entry is not None and json.dumps(restore(h, entry), sort_keys=True) == json.dumps(doc, sort_keys=True)
                and entry.get("screens") == (screen_hashes(doc, doc_path) or None))
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
    leaves <name>.diffcache.json as it is. Never raises: a wrong-typed field is an ERROR with its path."""
    rep = Report()
    if not isinstance(doc, dict):
        rep.err("doc", f"{_shown(doc)} is {_json_type(doc)}: a doc is an object")
        return rep
    for k, spec in DOC_SHAPE.items():
        if k in doc and doc[k] is not None:
            check_shape(rep, k if k == "sections" else f"doc.{k}", doc[k], spec)
    if rep.errors:
        return rep   # the checks below read these fields as the types DOC_SHAPE names
    try:
        _validate(rep, doc, doc_path, allow_remote=allow_remote, write_cache=write_cache)
    except Exception as e:   # a field DOC_SHAPE doesn't describe: still an ERROR line, not a crash
        rep.err("doc", f"stopped validating at a wrong-typed field ({type(e).__name__}: {e}); see references/schema.md")
    return rep


def _validate(rep: Report, doc: dict, doc_path: Path | None, *, allow_remote: bool, write_cache: bool) -> None:
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
    boards: list[tuple[str, dict]] = []        # (where, block): checked once the brief is known

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
        elif t == "board":
            if doc_type(doc.get("meta") or {}) != "design":
                rep.err(bw, "a board block is for design docs: set meta.type to 'design'")
            boards.append((bw, b))

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

    for bw, b in boards:
        validate_board(rep, bw, b, doc, doc_path)
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


def record(h: dict, doc: dict, doc_path: Path | None = None, *, keep_screens: bool = False,
           texts: dict[str, str | None] | None = None) -> str:
    """Put doc into the history under its meta.rev. Returns what happened, for the build log. With doc_path, a
    design doc's screen files join the revision: their text goes into the history's html pool, by _hash, and the
    entry maps artboard ids to those hashes (screens). texts ({artboard id: text}) stands in for the files.
    keep_screens keeps the screens the history already holds for this rev: cmd_patch records the version a
    patch replaces, whose files the reader's change may already have rewritten."""
    meta = doc.get("meta") or {}
    rev = str(meta.get("rev") or "")
    snap = snapshot(doc, h["blocks"])
    entry = {"rev": rev, "date": meta.get("date") or "", "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **snap}
    revs = h["revs"]
    last = revs[-1] if revs and revs[-1]["rev"] == rev else None
    if keep_screens and last and "screens" in last:
        entry["screens"] = last["screens"]
    else:
        if texts is None:
            texts = read_screens(doc, doc_path) if doc_path is not None else {}
        if texts:
            pool = h.setdefault("html", {})
            entry["screens"] = {}
            for aid, text in texts.items():
                entry["screens"][aid] = None if text is None else _hash(text)
                if text is not None:
                    pool[entry["screens"][aid]] = text
    if last:
        same = json.dumps(restore(h, last), sort_keys=True) == json.dumps(doc, sort_keys=True)
        moved = sorted(a for a in set(last.get("screens") or {}) | set(entry.get("screens") or {})
                       if (last.get("screens") or {}).get(a) != (entry.get("screens") or {}).get(a))
        if same and not moved:
            msg = f"rev {rev} unchanged"
        else:
            revs[-1] = entry
            what = f"screens {', '.join(moved)}" if same else "text"
            msg = f"rev {rev} updated in place ({what}; bump meta.rev to keep the previous version as its own revision)"
    elif any(r["rev"] == rev for r in revs):
        return f"ERROR history: meta.rev {rev} is an earlier revision of this doc; bump it past {revs[-1]['rev']}"
    else:
        revs.append(entry)
        msg = f"recorded rev {rev}"
    # drop pool blocks and screen HTML no revision uses any more
    used = {r for e in revs for s in e["sections"] for r in s["blocks"]}
    h["blocks"] = {k: v for k, v in h["blocks"].items() if k in used}
    if "html" in h:
        used = {k for e in revs for k in (e.get("screens") or {}).values() if k}
        h["html"] = {k: v for k, v in h["html"].items() if k in used}
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
        if "screens" in e:   # a design's {artboard id: screen hash}; the HTML stays in the history file (?rev=)
            out["screens"] = e["screens"]
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
    """x as JSON the page's <script type="application/json"> blocks hold: every '<' becomes \\u003c, which
    JSON.parse reads back, so no '</script' or '<!--' in a doc's text reaches the HTML parser."""
    return _canon(x).replace("<", "\\u003c")


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


# the screen route's CSP for a srcdoc frame in an -o file, as a <meta>: everything is inline there, so no 'self';
# frame-ancestors and sandbox can't sit in a <meta> (the frame's sandbox attribute carries the sandbox)
STANDALONE_SCREEN_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; "
                         "font-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'")
MAX_STANDALONE_BYTES = 10 * 1024 * 1024


def standalone_screens(doc: dict, doc_path: Path) -> dict[str, str] | None:
    """{artboard id: its screen as a whole document with the kit inlined} for an -o file; None for a doc without
    a board. serve.py's wrap_screen fills the shell; unreadable screens are left out (validate reported them)."""
    texts = read_screens(doc, doc_path)
    if not texts:
        return None
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import serve
    meta = f'<meta http-equiv="Content-Security-Policy" content="{STANDALONE_SCREEN_CSP}">'
    out = {}
    for aid, text in texts.items():
        if text is not None:
            page = serve.wrap_screen(doc, Path(doc_path), aid, text, inline=True)
            out[aid] = re.sub(r"(?i)<head[^>]*>", lambda m: m.group(0) + meta, page, count=1)
    return out


def build(doc: dict, template: str, history: dict | None = None, media_base: Path | None = None,
          diff_path: Path | None = None, problems: list[str] | None = None, state: dict | None = None,
          screens: dict[str, str] | None = None) -> str:
    """The page. media_base (the doc's folder) makes it standalone: media files become data: URIs.
    diff_path (the doc's JSON file) fills its diff refs, in the doc and in earlier revisions; their
    problems go into problems, or to stderr when it is None. state is the reader state serve.py seeds the
    page with ({version, state}); None (an -o file) leaves the page on localStorage. screens ({artboard id:
    a whole screen document}, from standalone_screens) makes a design page draw its frames from srcdoc;
    None (serve.py) loads them from the screen route."""
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
    # one pass, so a placeholder's name inside a filled value (a doc's text, a reader's note) stays text
    fill = {"__BLUEDOC_TITLE__": title, "__BLUEDOC_HISTORY__": _script_json(hist) if hist else "null",
            "__BLUEDOC_STATE__": _script_json(state) if state is not None else "null", "__BLUEDOC_DOC__": _script_json(doc),
            "__BLUEDOC_SCREENS__": _script_json(screens) if screens is not None else "null"}
    return re.sub("|".join(fill), lambda m: fill[m.group(0)], template)


class HistoryError(Exception):
    pass


def sync_history(doc_path: Path, doc: dict, *, keep_screens: bool = False,
                 texts: dict[str, str | None] | None = None) -> tuple[dict | None, str]:
    """Record doc in its history file under meta.rev (keep_screens, texts: see record); returns (history or
    None, log line). Raises HistoryError when meta.rev names an earlier revision or the file is unreadable."""
    if not (doc.get("meta") or {}).get("rev"):
        return None, "history: off (set meta.rev to keep revisions)"
    hpath = history_path(doc_path)
    try:
        history = load_history(hpath)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        raise HistoryError(f"cannot read {hpath}: {e}") from e
    before = _canon(history)
    log = record(history, doc, doc_path, keep_screens=keep_screens, texts=texts)
    if log.startswith("ERROR"):
        raise HistoryError(log)
    if _canon(history) != before:
        tmp = hpath.with_name(hpath.name + ".tmp")
        tmp.write_text(json.dumps(history, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(hpath)
    return history, log


# a doc file's suffixes, the one list: serve.py lists and renders these, diffref.py and migrate.py import it
DOC_SUFFIXES = (".bluedoc.json", ".blueprint.json")


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
    ap.add_argument("--shape", choices=("pr", "area"), default="pr",
                    help="review only: one section per PR (pr), or per area of a codebase review (area)")
    ap.add_argument("--target", help=f"design only: comma list of {','.join(TARGET_DEVICES)}; one starter artboard "
                    "and wireframe screen file each, three slides for presentation (default mobile)")
    ap.add_argument("--framework", help="design only: plain | horizon | <a `serve.py add-framework` name> | auto "
                    "(default: you fill the brief's framework pick from the project's files; see types/design.md)")
    a = ap.parse_args(argv)
    if a.shape != "pr" and a.type != "review":
        ap.error("--shape is for review docs")
    if (a.target or a.framework) and a.type != "design":
        ap.error("--target and --framework are for design docs")
    targets = [t.strip() for t in (a.target or "mobile").split(",") if t.strip()]
    bad = [t for t in targets if t not in TARGET_DEVICES]
    if bad or not targets or len(set(targets)) != len(targets):
        ap.error(f"--target: a comma list of distinct {', '.join(TARGET_DEVICES)}")
    if a.framework and a.framework != "auto" and not ID_RE.match(a.framework):
        ap.error("--framework: plain, horizon, auto or a store name (lowercase letters, digits, -)")
    if not a.out.name.endswith(DOC_SUFFIXES):
        ap.error(f"name it <name>{DOC_SUFFIXES[0]}: serve.py lists those files")
    if a.out.exists():
        print(f"{a.out} exists; not overwriting it (edit it, or change it with build.py patch)", file=sys.stderr)
        return 2
    skel = SKELETONS / (f"{a.type}.json" if a.shape == "pr" else f"{a.type}-{a.shape}.json")
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
    stubs = scaffold_design(doc, a.out, targets, a.framework or "auto") if a.type == "design" else {}
    for f in stubs:
        if f.exists():
            print(f"{f} exists; not overwriting it", file=sys.stderr)
            return 2
    a.out.parent.mkdir(parents=True, exist_ok=True)
    write_doc(a.out, doc, raw)
    for f, text in stubs.items():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
        print(f"wrote {f} (a wireframe stub)")
    print(f"wrote {a.out} ({a.type}): replace every <<…>>; `build.py {a.out} --check` lists the ones left")
    print(f"then: python3 {HERE / 'build.py'} {a.out} && python3 {HERE / 'serve.py'} open {a.out}")
    return 0


def stub_slide(aid: str, kind: str, n: int | None) -> str:
    """A wireframe starter slide (`title`, `content` or `closing`) in the kit's slide classes; n: its page number."""
    num = f' data-n="{n}"' if n else ""
    foot = f'  <footer class="slide-foot"{num} data-bd="foot">Deck title</footer>\n'
    if kind == "title":
        return (f'<section class="slide center" data-bd="{aid}">\n'
                '  <p class="slide-kicker" data-bd="kicker">Team · date</p>\n'
                '  <h1 class="slide-title" data-bd="headline">Deck title</h1>\n'
                '  <div class="wf-text" style="--lines:1" data-bd="presenter"></div>\n'
                '</section>\n')
    if kind == "closing":
        return (f'<section class="slide center" data-bd="{aid}">\n'
                '  <h2 class="slide-title" data-bd="ask">The ask</h2>\n'
                '  <div class="wf-text" style="--lines:2" data-bd="next"></div>\n'
                + foot + '</section>\n')
    return (f'<section class="slide" data-bd="{aid}">\n'
            '  <p class="slide-kicker" data-bd="kicker">Section</p>\n'
            '  <h2 class="slide-title" data-bd="headline">One point per slide</h2>\n'
            '  <div class="slide-cols grow" data-bd="body">\n'
            '    <div class="wf-text" style="--lines:5" data-bd="points"></div>\n'
            '    <div class="wf-img" data-bd="visual"></div>\n'
            '  </div>\n'
            + foot + '</section>\n')


def stub_screen(a: dict) -> str:
    """A wireframe starter for an artboard, in plain-kit classes (references/kits.md): the agent's rev A."""
    aid, dev = a["id"], a.get("device")
    if dev == "slide":
        return stub_slide(aid, "content", None)
    if dev in ("watch-round", "watch-square"):
        return (f'<main class="screen {"round " if dev == "watch-round" else ""}safe stack gap-2 center" data-bd="{aid}">\n'
                '  <div class="wf-circle" data-bd="glance"></div>\n'
                '  <div class="wf-line" data-bd="title"></div>\n'
                '  <div class="wf-box" data-label="Action" data-bd="action"></div>\n'
                '</main>\n')
    if dev in ("desktop", "browser"):
        return (f'<main class="screen safe row gap-4" data-bd="{aid}">\n'
                '  <nav class="sidebar" data-bd="nav">\n'
                '    <div class="wf-line"></div>\n    <div class="wf-line"></div>\n    <div class="wf-line"></div>\n'
                '  </nav>\n'
                '  <section class="stack gap-4 grow" data-bd="content">\n'
                '    <div class="wf-line" data-bd="title"></div>\n'
                '    <div class="grid cols-3 gap-4" data-bd="cards">\n'
                '      <div class="wf-box" data-label="Card"></div>\n'
                '      <div class="wf-box" data-label="Card"></div>\n'
                '      <div class="wf-box" data-label="Card"></div>\n'
                '    </div>\n'
                '    <div class="wf-img" data-bd="main"></div>\n'
                '  </section>\n'
                '</main>\n')
    return (f'<main class="screen safe stack gap-4" data-bd="{aid}">\n'
            '  <div class="wf-line" data-bd="title"></div>\n'
            '  <div class="wf-img" data-bd="hero"></div>\n'
            '  <div class="wf-text" data-bd="body"></div>\n'
            '  <div class="wf-box" data-label="Primary action" data-bd="action"></div>\n'
            '</main>\n')


def scaffold_design(doc: dict, out: Path, targets: list[str], framework: str) -> dict[Path, str]:
    """Fill a design skeleton for `build.py new design`: one wireframe artboard per target (presentation: the stub
    deck's slides) and the framework pick. Returns {screen file: stub text} to write beside the doc."""
    board = board_of(doc)
    board["targets"] = targets
    board["artboards"], stubs = [], {}
    for t in targets:
        if t == "presentation":
            for n, (kind, title) in enumerate(STUB_SLIDES, 1):
                a = {"id": kind, "title": f"<<{title}>>", "device": "slide", "fidelity": "wireframe",
                     "notes": "<<What you say on this slide, or drop notes>>"}
                board["artboards"].append(a)
                stubs[out.parent / screen_rel(out, a)] = stub_slide(kind, kind, n)
        else:
            a = {"id": t, "title": f"<<{t.capitalize()} screen: what it shows>>", "device": TARGET_DEVICES[t],
                 "fidelity": "wireframe"}
            board["artboards"].append(a)
            stubs[out.parent / screen_rel(out, a)] = stub_screen(a)
    if framework != "auto":
        item = _item(doc, "brief", "framework").obj
        if framework not in BUILTIN_FRAMEWORKS:
            try:   # the label `serve.py add-framework` wrote (e.g. "Tailwind + HeroUI"), else the name
                label = str(json.loads((frameworks_dir() / framework / "manifest.json").read_text(encoding="utf-8"))
                            .get("label") or framework)[:MAX_CHOICE_LABEL]
            except (OSError, ValueError, AttributeError):
                label = framework
            board["frameworks"] = [{"id": framework, "label": label, "store": framework}]
            item["choices"].insert(0, {"id": framework, "label": label})
        board["framework"] = framework
        item["recommend"] = framework
        label = next(c["label"] for c in item["choices"] if c["id"] == framework)
        item["sub"] = f"Recommend {label}: <<why it fits these screens>>."
    return stubs


class PatchError(Exception):
    pass


class Target:
    """What a patch key names: obj, the place it sits (parent[key]), and its kind. selector: the CSS selector of
    an el: key's element in its screen file."""
    def __init__(self, obj, parent, key, kind: str, selector: str = "") -> None:
        self.obj, self.parent, self.key, self.kind, self.selector = obj, parent, key, kind, selector


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
    if kind in ("artboard", "el") and parts:
        aid, _, sel = path.partition("/")
        if kind == "el" and not sel:
            raise PatchError(f"bad key '{key}': el:<artboard>/<data-bd names joined by '/', or a CSS path>")
        arts = _board_artboards(doc)
        a, i = _find(arts, lambda x: x.get("id") == aid, f"artboard '{aid}'")
        if kind == "artboard":
            return Target(a, arts, i, "artboard")
        names = sel.split("/") if EL_NAMES.match(sel) else None
        return Target(a, arts, i, "element", " ".join(f'[data-bd="{n}"]' for n in names) if names else sel)
    if kind == "frame":
        m = FRAME_KEY.match(path)
        if not m:
            raise PatchError(f"bad key '{key}': frame:<device or WxH>@<x>,<y>, e.g. frame:phone@1200,0")
        dev, x, y = m.group(1), int(m.group(2)), int(m.group(3))
        size = re.fullmatch(r"(\d+)x(\d+)", dev)
        if not size and dev not in DEVICES:
            raise PatchError(f"bad key '{key}': '{dev}' is no device ({', '.join(sorted(DEVICES))}) and no <w>x<h>")
        arts = _board_artboards(doc)
        taken = {o.get("id") for o in arts if isinstance(o, dict)}
        aid = next(f"frame-{n}" for n in range(1, len(arts) + 2) if f"frame-{n}" not in taken)
        a = {"id": aid, "title": "Requested frame",
             **({"w": int(size.group(1)), "h": int(size.group(2))} if size else {"device": dev}),
             "fidelity": "wireframe", "x": x, "y": y}
        arts.append(a)
        return Target(a, arts, len(arts) - 1, "frame")
    raise PatchError(f"unknown key '{key}': see `build.py --help` for the key forms")


EL_NAMES = re.compile(r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*$")   # an el: path of data-bd names, else a CSS path
FRAME_KEY = re.compile(r"^([a-z0-9-]+|\d+x\d+)@(-?\d+),(-?\d+)$")


def _board_artboards(doc: dict) -> list:
    b = board_of(doc)
    if not b or not isinstance(b.get("artboards"), list):
        raise PatchError("no board block with artboards in this doc")
    return b["artboards"]


# the list --append adds to, per target kind (blocks: per block type)
APPEND_FIELD = {"doc": "sections", "section": "blocks", "item": "blocks"}
APPEND_BLOCK_FIELD = {"table": "rows", "canvas": "nodes", "diff": "comments", "checklist": "items", "steps": "items",
                      "files": "items", "cards": "items", "terms": "items", "board": "artboards"}


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
    ap.add_argument("key", help="e.g. item:t412/tier-boundary, step:steps/0/s3, row:risks/0/2, meta, tldr, artboard:login")
    ap.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE", help="set one field (JSON value, else a string; null deletes)")
    ap.add_argument("--json", metavar="OBJ", help="merge these fields (null deletes one)")
    ap.add_argument("--append", metavar="VALUE", help="append to the target's list (items, rows, nodes, blocks, comments, artboards)")
    ap.add_argument("--delete", action="store_true", help="remove the target")
    ap.add_argument("--html", metavar="FILE", help="artboard: and el: keys: replace the screen file with FILE's text (- reads stdin)")
    ap.add_argument("--change", action="append", default=[], metavar="LINE", help="a line for `changes` (repeat for more)")
    ap.add_argument("--no-bump", action="store_true", help="keep meta.rev: update the current revision in place")
    a = ap.parse_args(argv)
    ops = bool(a.set or a.json is not None or a.append is not None or a.delete or a.html is not None)
    if a.delete and (a.set or a.json is not None or a.append is not None or a.html is not None):
        ap.error("--delete goes alone")
    try:
        raw = a.doc.read_text(encoding="utf-8")
        doc = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot read {a.doc}: {e}", file=sys.stderr)
        return 2
    before = copy.deepcopy(doc)
    before_screens = read_screens(before, a.doc)   # the screen text this patch may replace, read before it does
    a.key = a.key.strip().strip("`").strip()
    try:
        t = resolve_key(doc, a.key)
    except PatchError as e:
        print(f"patch: {e}", file=sys.stderr)
        return 2
    on_screen = t.kind in ("artboard", "element")
    if a.html is not None and not on_screen:
        ap.error("--html takes an artboard: or el: key")
    if not ops and t.kind != "frame" and not (on_screen and a.change):
        if not on_screen:
            ap.error("give --set, --json, --append or --delete")
        # where to make the change: the screen file, and the element in it
        print(f"{a.doc.parent / screen_rel(a.doc, t.obj)}" + (f"  {t.selector}" if t.selector else ""))
        print(f"edit it in place, then: build.py patch {a.doc} {shlex.quote(a.key)} --change '<what changed>'")
        return 0
    html = None
    if a.html is not None:
        try:
            html = sys.stdin.read() if a.html == "-" else Path(a.html).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"cannot read {a.html}: {e}", file=sys.stderr)
            return 2
    try:
        apply_patch(t, a.set, a.json, a.append, a.delete)
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
    # screen files change before validate, which lints them; undone when the patch fails
    written: list[tuple[Path, str | None]] = []
    screen = a.doc.parent / screen_rel(a.doc, t.obj) if t.kind in ("artboard", "element", "frame") and not a.delete else None
    if screen and (html is not None or (t.kind == "frame" and not screen.exists())):
        written.append((screen, _read_text(screen) if screen.exists() else None))
        screen.parent.mkdir(parents=True, exist_ok=True)
        screen.write_text(html if html is not None else stub_screen(t.obj), encoding="utf-8")

    def undo() -> None:
        for f, old in written:
            if old is None:
                f.unlink(missing_ok=True)
            else:
                f.write_text(old, encoding="utf-8")
    rep = validate(doc, a.doc)
    if rep.errors:
        undo()
        for line in rep.errors:
            print(line, file=sys.stderr)
        print(f"patch: {len(rep.errors)} error(s); {a.doc} not written", file=sys.stderr)
        return 1
    try:
        if rev0 and not a.no_bump:   # the version this patch replaces stays its own revision
            sync_history(a.doc, before, keep_screens=True, texts=before_screens)
    except HistoryError as e:
        undo()
        print(e, file=sys.stderr)
        return 1
    write_doc(a.doc, doc, raw)
    try:
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
    print(f"rev {rev0 or '-'} → {rev1}; {a.key} {'deleted' if a.delete else 'added' if t.kind == 'frame' else 'updated'}")
    if screen:
        print(f"screen: {screen}" + (f"  {t.selector}" if t.selector else "")
              + ("  (a stub: write the requested screen there)" if t.kind == "frame" and written else ""))
    elif a.delete and t.kind in ("artboard", "element"):
        print(f"left {a.doc.parent / screen_rel(a.doc, t.obj)}: delete it if nothing uses it (the history keeps its text)")
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
        page = build(doc, a.template.read_text(encoding="utf-8"), history, a.doc.resolve().parent, a.doc,
                     screens=standalone_screens(doc, a.doc))
        a.out.write_text(page, encoding="utf-8")
        size = a.out.stat().st_size
        print(f"wrote {a.out} ({size // 1024} KB)", file=sys.stderr)
        if size > MAX_STANDALONE_BYTES:
            print(f"WARN  {a.out}: {size / 1048576:.1f} MB (> {MAX_STANDALONE_BYTES // 1048576} MB): each screen carries its "
                  "kit inline; share the JSON and serve.py instead, or use fewer or plain-kit screens", file=sys.stderr)
    else:
        print(f"view: python3 {HERE / 'serve.py'} open {a.doc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
