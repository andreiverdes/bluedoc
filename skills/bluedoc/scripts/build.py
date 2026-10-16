#!/usr/bin/env python3
"""Validate a bluedoc JSON document, record its revision, optionally write standalone HTML.

Usage:
  build.py doc.json                 validate, lint, record the revision (view it with serve.py)
  build.py doc.json -o out.html     same, plus a standalone HTML file for sharing offline (media and diffs inlined)
  build.py deck.json --deck out.html   same, plus a presentation as one HTML file that plays its slides offline
                                    (serve.py deck_html; any other doc type is refused)
  build.py deck.json --deck out.pdf    same, plus the deck as a PDF, one 16:9 page per slide, no notes (serve.py
                                    deck_pdf: needs Chrome or Chromium, BLUEDOC_CHROME); --format html|pdf
                                    overrides the extension
  build.py doc.json --check         validate and lint only; writes nothing (no history, no diff cache)
  build.py doc.json --strict        treat lint warnings as errors
  build.py doc.json --show-rev B    print revision B, rebuilt from the history, as JSON
  build.py new TYPE out.bluedoc.json [--title T] [--kind K] [--shape pr|area] [--target T,…] [--framework F]
                                    [--icons] [--url URL]
                                    write the fill-in skeleton of a docs|review|plan|design|presentation|website|
                                    other doc (--shape area: a review by area of a codebase, not by PR; design: one
                                    wireframe screen file per --target watch|mobile|tablet|desktop|web, --icons
                                    adds an app icon with stub layers; presentation: a deck of three stub slides;
                                    website: a home page, live from --url (a loopback dev server) or a stub file)
  build.py patch doc.json KEY [--set f=v ...] [--json OBJ] [--append OBJ] [--delete] [--html FILE|-]
                              [--change LINE ...] [--no-bump]
                                    change one object by its annotator key, bump meta.rev, validate, record

serve.py renders the JSON with assets/template.html on every request, so normal work needs no
HTML file at all: write the JSON, run build.py, open the serve.py URL.

Revisions: every build (and every patch) records the document under its `meta.rev` in
<doc>.history.json next to the JSON (doc.bluedoc.json -> doc.bluedoc.history.json). A new rev
appends; the same rev replaces that entry. A design doc's screen files and icon layers join the revision:
their text sits in the history's `html` pool by hash, and the entry lists the board's links. The page
embeds the history (screens as hashes only, links as they are), so readers can switch revisions and
compare two. --no-history skips reading and writing it.

Type contracts: each meta.type needs its data (review: a diff and sized findings; plan: steps and
files blocks; docs: a canvas or a hero; design: one board with an artboard; presentation: one board of
slide artboards only; website: one board of page artboards only). Missing data is an error on the doc
being built: a new meta.rev, or a recorded rev whose text changed (an edit in place). It is a warning only
while the doc is exactly the revision its history recorded, so old revisions keep rendering.

Screens (design, presentation and website docs): each artboard's HTML is a body fragment in <stem>.design/<id>.html. The build
fails on a missing file, a network URL, <base>, <iframe>, <object>, <embed>, <meta http-equiv>,
<form action> or a whole document; it warns above 24 KB and when no element has a data-bd name.
An element's data-nav ("[kind:]artboard" or "back") is a link; the build checks its target and name,
and the screens no board.entry reaches. An `icons` artboard has SVG layers in <stem>.design/<id>/
instead (fg.svg required), checked for a square viewBox, the safe circle and what a canvas can't draw.
A website page with `url` has no screen file: serve.py proxies that loopback dev server (any other host is
an error). Its `source` and its sections' `source` hints are checked against board.root when it is set.
A live page shows the site as it is now, so an earlier revision shows its snapshot instead: a static copy of the
page per revision and width in <name>.snapshots/rev-<rev>/<page>@<width>.html, which serve.py records when the
reader sends feedback (or a live page first loads at a rev without one) and `serve.py snapshot` on demand. A
patch that bumps the rev warns when the revision it replaces has none.

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
  (an element: data-bd names joined by '/', else a CSS path; --set 'text="<text>"' rewrites its one text
  run, HTML-escaped, --delete removes it from its screen file; the artboard stays. Live pages and icons
  artboards refuse both), frame:<device or WxH>@<x>,<y> (appends
  an artboard there and writes a stub screen file), link:<id>/<element> (the element's link: --set
  to=<artboard> kind=<push|modal|tab|replace|back> label=<text>, or --delete, rewrite its start tag in
  place; an element no name finds becomes a hidden gesture link), layout:<board> (--json
  '{"<artboard>": [x, y]}' sets positions). artboard:, el: and link: with no --set/--json/--html
  print the screen file and the element's selector (link: also its data-nav); with only --change
  they record a hand edit of the screen file as the next rev.
  Storelisting keys: field:<locale>/<platform>/<field> (a store text) and field:<locale>/strings/<key> (a
  caption string): --set <field>=<text> writes it, --delete drops it, no option prints it with its count and limit.
  brand:<listing id> is listing.brand: --json '{"font": …, "palette": …, "image": …}' merges it (null deletes one).
  On a storelisting shot, artboard: and el: with no option also print its recipe per target, each locale's capture
  with its time, and the `capture.py` command that re-shoots it (an uploaded shot: its PNG, which has none).
  <blockPath> is <section>/<index> or <checklist>/<item>/<index>. header, tldr and status address
  the doc's top level. --set and --json values parse as JSON when they can; null deletes the field.
  --append adds to the target's list (doc: sections, section and item: blocks, table: rows,
  canvas: nodes, diff: comments, board: artboards, other blocks: items). The rev bumps (A->B, 3->4,
  v1->v2) and meta.date becomes today unless --no-bump; on a bump `changes` becomes the --change lines
  (default: "Updated `KEY`.") and `resolves` the --resolves ids (none: removed), with --no-bump both are
  appended.

Exit codes: 0 ok, 1 validation errors (or warnings with --strict), 2 usage/IO error.
Python 3.9+ standard library only.
"""
from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import hashlib
import ipaddress
import json
import math
import os
import re
import shlex
import sys
from html import escape as escape_html
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import listing   # noqa: E402 — the storelisting rules and checks (scripts/listing.py)

TEMPLATE = HERE.parent / "assets" / "template.html"
SKELETONS = HERE.parent / "assets" / "skeletons"
HISTORY_VERSION = 1

BLOCK_TYPES = {"text", "callout", "table", "code", "terms", "cards", "checklist", "canvas", "diff", "steps", "files", "media", "compare",
               "board", "listing"}
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
RESOLVES_ID = re.compile(r"[A-Za-z0-9_-]{1,40}")   # a reader comment's id, as `resolves` lists it (the page writes c<base36>)
DOC_TYPES = {"docs", "review", "plan", "design", "presentation", "website", "storelisting", "other"}   # meta.type: the home page's grouping; unset = derived from meta.kind
# the types whose page is one board (a presentation: of slides only; a website: of pages only; a storelisting: of shots,
# assets and an icon, shown as platform pages by its listing block)
BOARD_TYPES = ("design", "presentation", "website", "storelisting")
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
           "slide": {"w": 1920, "h": 1080, "safe": [0, 0, 0, 0]}, "icons": {"w": 1280, "h": 860, "safe": [0, 0, 0, 0]},
           "page": {"w": 1440, "h": 900, "safe": [0, 0, 0, 0]},
           # a storelisting's shot and asset: their size on a board, which the platform pages don't use (they size each
           # shot by the set it fills, store px / scale: listing.frame_size); the iPhone 6.9" frame and the feature graphic
           "shot": {"w": 440, "h": 956, "safe": [0, 0, 0, 0]}, "asset": {"w": 1024, "h": 500, "safe": [0, 0, 0, 0]}}
# board.targets: what the board is for. `build.py new design --target` takes each but presentation and listing, which
# are `build.py new presentation` (the skeleton's stub deck, its slides in deck order) and `new storelisting`
TARGET_DEVICES = {"watch": "watch-round", "mobile": "phone", "tablet": "tablet", "desktop": "desktop", "web": "browser",
                  "presentation": "slide", "listing": "shot"}
MAX_NOTES_BYTES = 2 * 1024        # an artboard's speaker notes, shown under the slide in Present
FIDELITIES = ("sketch", "wireframe", "hifi")
# what ships with bluedoc (assets/kits, assets/vendor), by id: its label in the brief
BUILTIN_FRAMEWORKS = {"plain": "Plain kit", "horizon": "HorizonUI", "heroui": "Tailwind + HeroUI", "tailwind": "Tailwind CSS"}
# were `serve.py add-framework` presets until they shipped: a board may still declare them in frameworks[] (its files
# or store copy load instead), and a `store` of that name with no copy loads the shipped one
SHIPPED_PRESETS = ("heroui", "tailwind")
FRAMEWORK_EXTS = {".css", ".js", ".mjs"}
BOARD_GAP = 80                    # px between artboards placed without x/y
SLIDE_GAP = 280                   # px between slides in the slide column: clears their labels down to ~10% zoom
FLOW_GAP_X, FLOW_GAP_Y = 200, 120  # layout "flow": px between depth columns, and between screens in a column
BOARD_LAYOUTS = ("rows", "flow")
# links: an element's data-nav is "[kind:]artboard" (no kind: push) or "back"; data-nav-label names the action
NAV_KINDS = ("push", "modal", "tab", "replace", "back")
MAX_NAV_LABEL = 40                # characters a label pill on an arrow fits
# an `icons` artboard: SVG layers in <stem>.design/<id>/ instead of a screen file; fg.svg is required
ICON_LAYERS = ("fg.svg", "bg.svg", "mono.svg", "ios-dark.svg", "ios-tinted.svg", "play.svg")
ICON_SIZE, ICON_SAFE_R = 108, 33  # Android's adaptive layer (dp) and the safe circle every launcher mask shows
MAX_ICON_NAME = 30
HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
MAX_SCREEN_BYTES = 24 * 1024      # a screen file above this is a warning: edit fragments in place, don't regrow them
TOKEN_KEY = re.compile(r"^[a-z][a-z0-9-]*$")
TOKEN_VALUE = re.compile(r"^[^;{}<>\\]*$")
MOTION_KEYS = ("fast", "base", "slow", "ease")
SCREEN_SRC = re.compile(r"^(?:[\w.-]+/)*[\w.-]+\.design/[\w.-]+\.html$")
# website docs: every artboard a `page` (the browser bar sits above it, so its safe area is none) at a breakpoint the
# reader switches; a page with `url` shows a loopback dev server through serve.py's proxy instead of a screen file
BREAKPOINTS = (1440, 768, 390)    # board.breakpoints' default: desktop, tablet, mobile widths in CSS px
MIN_BREAKPOINT, MAX_BREAKPOINT, MAX_BREAKPOINTS = 240, 3840, 6
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")   # and every 127.x.y.z
MAX_SECTIONS, MAX_VARIANT_EDITS, MAX_EDIT_HTML = 40, 20, 8 * 1024
MAX_SOURCES, MAX_SOURCE = 3, 200
# a source hint: a path in the site's repo, then #symbol or :line (or :start-end); checked when board.root names the repo
SOURCE_HINT = re.compile(r"^(?P<path>[^\s#:][^\s#:]*?)(?:#(?P<sym>[\w$.-]+)|:(?P<line>\d+)(?:-(?P<end>\d+))?)?$")

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
        self.store: list[str] = []   # the errors from a storelisting's store rules (listing.store_checks), in errors too

    def err(self, where: str, msg: str) -> None:
        self.errors.append(f"ERROR {where}: {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"WARN  {where}: {msg}")

    def finding(self, f: dict) -> None:
        """A store-rule finding (listing._finding): an error fails the build, but the doc stays drawable, so serve.py
        shows the page with it in the Checks tab, and a patch may write while it is there (blocking)."""
        if f["level"] == "err":
            self.err(f["where"], f["msg"])
            self.store.append(self.errors[-1])
        else:
            self.warn(f["where"], f["msg"])

    @property
    def blocking(self) -> list[str]:
        """The errors that keep the page from drawing the doc: all but the store-rule ones."""
        return [e for e in self.errors if e not in self.store]


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
    "board": {"id": str, "targets": [str], "framework": str, "entry": [str], "layout": str, "viewport": dict,
              "frameworks": [{"id": str, "label": str, "files": [str], "store": str}],
              "themes": [{"id": str, "label": str, "tokens": dict}], "motion": dict,
              "artboards": [{"id": str, "title": str, "device": str, "fidelity": str, "x": NUMBER, "y": NUMBER,
                             "w": NUMBER, "h": NUMBER, "variantOf": str, "framework": str, "src": str, "notes": str,
                             "icon": {"bg": str, "name": str}, "sets": list, "locale": str, "asset": str,
                             "recipe": dict, "style": dict, "credits": str}]},
    # a storelisting's listing block: listing.validate_listing checks the rest against assets/store-rules.json
    "listing": {"id": str, "app": dict, "platforms": list, "rows": list, "locales": list, "defaultLocale": str,
                "text": dict, "strings": dict, "mt": dict, "style": dict, "brand": dict, "icon": str, "video": dict,
                "order": dict, "capture": dict, "variants": list, "translatedFrom": dict},
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
        if "bend" in e:
            rep.warn(w, "`bend` is ignored: edges route themselves")
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
    """docs | review | plan | design | presentation | website | other: meta.type when set, else read from meta.kind (a
    design, presentation or website only by meta.type: a kind like 'Design' stays docs). template.html follows the same
    rule; serve.py puts the result in the home page's index."""
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


def has_canvas(doc: dict, hist: dict | None = None) -> bool:
    """Whether the doc, or a revision of it the page carries (embed_history's blocks), has a canvas block."""
    older = list(((hist or {}).get("blocks") or {}).values())
    return any(b.get("type") == "canvas" for d in (doc, {"sections": [{"blocks": older}]}) for b in all_blocks(d))


def _screen_src_ok(src) -> bool:
    return isinstance(src, str) and bool(SCREEN_SRC.match(src)) and ".." not in src.split("/")


def screen_rel(doc_path: Path, a: dict) -> str:
    """An artboard's screen file relative to the doc's folder: its src, else <stem>.design/<id>.html. An invalid
    src (validate reports it) falls back to the default."""
    return a["src"] if _screen_src_ok(a.get("src")) else f"{doc_stem(Path(doc_path))}.design/{a['id']}.html"


def is_icons(a) -> bool:
    return isinstance(a, dict) and a.get("device") == "icons"


def is_live(a) -> bool:
    """A website page shown from a dev server (its `url`) instead of a screen file."""
    return isinstance(a, dict) and "url" in a


def live_url_problem(url) -> str | None:
    """Why url can't be a live page, or None: it must be http(s) on a loopback host (localhost, 127.x.y.z, ::1),
    without credentials. serve.py proxies only such URLs, so a doc can't make the reader's server fetch the network."""
    if not isinstance(url, str) or not url or len(url) > 2000:
        return "a URL as a string, e.g. http://localhost:4321/"
    try:
        u = urlsplit(url)
        u.port   # noqa: B018 — raises on a bad port
    except ValueError:
        return f"'{url}' is no URL"
    if u.scheme not in ("http", "https") or not u.hostname:
        return f"'{url}': an http:// or https:// URL of a local dev server"
    if u.username or u.password:
        return f"'{url}': no credentials in the URL"
    if not is_loopback(u.hostname):
        return f"'{u.hostname}' is not a loopback host: a live page is a dev server on this machine ({', '.join(LOOPBACK_HOSTS)} or 127.x.y.z)"
    return None


def is_loopback(host: str) -> bool:
    host = host.strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def sources_of(x) -> list[str]:
    """A page's or a section's `source` hints as a list (it may be one string)."""
    s = x.get("source") if isinstance(x, dict) else None
    return [s] if isinstance(s, str) else [v for v in s if isinstance(v, str)] if isinstance(s, list) else []


def site_root(board: dict, doc_path: Path | None) -> Path | None:
    """The site's repo folder a website board's `root` names (relative to the doc), or None."""
    r = board.get("root") if isinstance(board, dict) else None
    return (Path(doc_path).parent / r).resolve() if isinstance(r, str) and r and doc_path is not None else None


def icon_dir(doc_path: Path, a: dict) -> Path:
    """An icons artboard's layer folder: <stem>.design/<id>/ beside the doc."""
    return Path(doc_path).parent / f"{doc_stem(Path(doc_path))}.design" / a["id"]


def _artboards(doc: dict) -> list[dict]:
    """The board's artboards with a valid id; [] for a doc without a board."""
    b = board_of(doc)
    arts = b.get("artboards") if isinstance(b, dict) else None
    return [a for a in arts if isinstance(a, dict) and isinstance(a.get("id"), str) and ID_RE.match(a["id"])] \
        if isinstance(arts, list) else []


def icon_layers(doc: dict, doc_path: Path) -> dict[str, dict[str, Path]]:
    """{icons artboard id: {layer file name: its path}} in ICON_LAYERS order: the layers that exist, and fg.svg always
    (it is required; validate reports it missing)."""
    out = {}
    for a in _artboards(doc):
        if is_icons(a):
            folder = icon_dir(doc_path, a)
            out[a["id"]] = {n: folder / n for n in ICON_LAYERS if n == "fg.svg" or (folder / n).is_file()}
    return out


# the icon sheet's tiles (their data-bd names) -> the layers each is drawn from, in order of preference: the first
# that exists wins; "bg" is bg.svg and/or icon.bg. A panel (sheet, ios, android, home) shows every layer.
_FULL = (("fg.svg",), ("bg",))
ICON_TILES = {**{t: _FULL for t in ("ios-master", "ios-light", "ios-sizes", "home-ios-light", "android-layers",
                                    "android-circle", "android-squircle", "android-rounded", "android-teardrop",
                                    "home-android-light")},
              **{t: (("ios-dark.svg", "fg.svg"),) for t in ("ios-dark", "home-ios-dark")},
              "ios-tinted": (("ios-tinted.svg", "mono.svg", "fg.svg"),),
              **{t: (("mono.svg", "fg.svg"),) for t in ("android-themed", "home-android-dark")},
              "play": (("play.svg", "fg.svg"), ("bg",))}


def icon_tile_layers(tile: str, layers: dict[str, Path], a: dict) -> list[str]:
    """The layer files (and `icon.bg`) a sheet tile is drawn from; every layer for a panel or an unknown name.
    Android's themed tiles fall back to fg + the background when there is no mono.svg."""
    bg = [n for n in ("bg.svg",) if n in layers] + (["icon.bg"] if (a.get("icon") or {}).get("bg") else [])
    if tile not in ICON_TILES:
        return list(layers) + [n for n in bg if n not in layers]
    out: list[str] = []
    for options in ICON_TILES[tile]:
        pick = bg if options == ("bg",) else [next((n for n in options if n in layers), options[-1])]
        out += pick + (bg if options[0] == "mono.svg" and pick == ["fg.svg"] else [])
    return out


def screen_paths(doc: dict, doc_path: Path) -> dict[str, Path]:
    """{artboard id: its screen file}, and for an icons artboard {"<id>/<layer>": its layer file} instead: every file
    whose text belongs to the revision. A website's live page (`url`) has none. {} for a doc without a board."""
    folder, out = Path(doc_path).parent, {}
    layers = icon_layers(doc, doc_path)
    for a in _artboards(doc):
        if a["id"] in layers:
            out.update({f"{a['id']}/{n}": f for n, f in layers[a["id"]].items()})
        elif not is_live(a) and not listing.is_image_shot(a):   # a storelisting's uploaded shot is a PNG, no screen file
            out[a["id"]] = folder / screen_rel(doc_path, a)
    return out


def _read_text(f: Path) -> str | None:
    try:
        return f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def read_screens(doc: dict, doc_path: Path) -> dict[str, str | None]:
    """{artboard id or "<id>/<layer>": the file's text, None when unreadable}; {} for a doc without a board."""
    return {aid: _read_text(f) for aid, f in screen_paths(doc, doc_path).items()}


def screen_hashes(doc: dict, doc_path: Path) -> dict[str, str | None]:
    """{artboard id or "<id>/<layer>": _hash of the file's text, None when unreadable}: the keys of the history's
    html pool. A storelisting's captures add "<shot>/capture/<target>/<locale>": their PNG's hash (listing.file_hashes)."""
    out = {aid: None if text is None else _hash(text) for aid, text in read_screens(doc, doc_path).items()}
    return {**out, **listing.file_hashes(doc, doc_path)} if listing.listing_of(doc) else out


def approval_hash(doc, doc_path: Path | None = None, screens: dict[str, str | None] | None = None) -> str:
    """The docHash an approval carries: sha256 of the doc's canonical JSON (sorted keys, no spaces), and for a doc
    with a board also of its screen and icon layer hashes, so editing a screen or a layer asks for approval again.
    screens (a history revision's) stands in for reading the files under doc_path."""
    canon = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if screens is None:
        screens = screen_hashes(doc, doc_path) if doc_path is not None and isinstance(doc, dict) else {}
    if screens:
        canon += "\n" + json.dumps(screens, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


PROGRESS_FIELDS, PROGRESS_META = ("changes", "resolves", "state"), ("rev", "date")


def without_progress(doc: dict, picks: dict[str, str] | None = None, approved: dict[str, object] | None = None) -> dict:
    """A copy of doc without what may change after an approval and keep it: meta.rev and meta.date, `changes`,
    `resolves`, the `state` labels, steps' `status` and checklist items' `done`. With picks ({"<checklist>:<item>":
    the reader's approved pick}) a decision's `choice` set to its pick reads as the approved doc's (approved:
    {"<checklist>:<item>": that doc's item, for its `choice` or its absence})."""
    d = copy.deepcopy(doc)
    for k in PROGRESS_FIELDS:
        d.pop(k, None)
    if isinstance(d.get("meta"), dict):
        for k in PROGRESS_META:
            d["meta"].pop(k, None)
    for b in all_blocks(d):
        if b.get("type") not in ("steps", "checklist"):
            continue
        for it in b.get("items") or []:
            if not isinstance(it, dict):
                continue
            if b["type"] == "steps":
                it.pop("status", None)
                continue
            it.pop("done", None)
            k = f"{b.get('id')}:{it.get('id')}"
            if picks and it.get("choice") and it.get("choice") == picks.get(k):
                was = (approved or {}).get(k) or {}
                if "choice" in was:
                    it["choice"] = was["choice"]
                else:
                    del it["choice"]
    return d


def approval_carries(h: dict, rev: str, approved_hash: str, doc: dict, doc_path: Path, picks: dict[str, str]) -> bool:
    """Whether an approval of revision rev still holds for doc as it is now: the history's rev is the JSON and screens
    the reader approved (approved_hash), and every change since is progress (without_progress; picks: the decisions
    the approval carried). Any other change, a screen file or an icon layer included, asks for approval again."""
    entry = next((e for e in h.get("revs") or [] if e.get("rev") == rev), None)
    if entry is None:
        return False
    old, old_screens = restore(h, entry), entry.get("screens") or {}
    if approval_hash(old, screens=old_screens) != approved_hash or old_screens != screen_hashes(doc, doc_path):
        return False
    items = {f"{b.get('id')}:{it.get('id')}": it for b in all_blocks(old) if b.get("type") == "checklist"
             for it in b.get("items") or [] if isinstance(it, dict)}
    canon = lambda d: json.dumps(d, ensure_ascii=False, sort_keys=True)  # noqa: E731
    return canon(without_progress(old)) == canon(without_progress(doc, picks, items))


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


def _placed(a: dict) -> bool:
    return all(isinstance(a.get(k), (int, float)) and not isinstance(a.get(k), bool) for k in ("x", "y"))


def flow_places(board: dict, links: list[dict] | None) -> dict[str, tuple[float, float, float, float]]:
    """layout "flow": {artboard id: (x, y, w, h)} for the unplaced screens the entries reach; {} on other boards. Breadth-
    first from board.entry (in its order) over links of every kind but back, in link order; a screen reached first
    brings its unvisited variants (board order, recursively) along at its depth, so each sits right under its source.
    Slides take no part. The reached, unplaced screens go in columns by depth (empty depths dropped), FLOW_GAP_X
    apart from x 0, each column as wide as its widest; in a column they stack in visit order from y 0, FLOW_GAP_Y
    apart. template.html places them by the same rule."""
    if board.get("layout") != "flow":
        return {}
    arts: dict[str, dict] = {}
    for a in board.get("artboards") or []:
        if isinstance(a, dict) and isinstance(a.get("id"), str) and a["id"] not in arts and artboard_size(a):
            arts[a["id"]] = a
    ok = {aid for aid, a in arts.items() if a.get("device") != "slide"}
    variants: dict[str, list[str]] = {}
    for aid in arts:
        if aid in ok and isinstance(arts[aid].get("variantOf"), str):
            variants.setdefault(arts[aid]["variantOf"], []).append(aid)
    out_links: dict[str, list[str]] = {}
    for ln in links or []:
        if ln.get("kind") != "back" and ln.get("to") in ok:
            out_links.setdefault(ln.get("from"), []).append(ln["to"])
    depth: dict[str, int] = {}
    visit: list[str] = []
    queue: list[str] = []

    def reach(aid: str, d: int) -> None:
        depth[aid] = d
        visit.append(aid)
        queue.append(aid)
        for v in variants.get(aid, []):
            if v not in depth:
                reach(v, d)

    for e in board.get("entry") or []:
        if e in ok and e not in depth:
            reach(e, 0)
    i = 0
    while i < len(queue):
        u = queue[i]
        i += 1
        for t in out_links.get(u, []):
            if t not in depth:
                reach(t, depth[u] + 1)
    flow = [aid for aid in visit if not _placed(arts[aid])]
    out: dict[str, tuple[float, float, float, float]] = {}
    x = 0
    for d in sorted({depth[aid] for aid in flow}):
        col = [aid for aid in flow if depth[aid] == d]
        y = 0
        for aid in col:
            w, h = artboard_size(arts[aid])
            out[aid] = (x, y, w, h)
            y += h + FLOW_GAP_Y
        x += max(out[aid][2] for aid in col) + FLOW_GAP_X
    return out


def board_layout(board: dict, links: list[dict] | None = None) -> dict[str, tuple[float, float, float, float]]:
    """{artboard id: (x, y, w, h)} in board order. An artboard with x and y sits there. On a `layout: "flow"` board
    the unplaced screens the entries reach through links go where flow_places puts them. An unplaced `slide`
    artboard goes in the slide column, y 0 for the first and SLIDE_GAP below the previous one after that; the
    column's x is 0 on a board of only slides, else BOARD_GAP right of the rightmost artboard outside it. Any other
    unplaced artboard's row is its variantOf source's y (when placed before it), else row 0, and it goes BOARD_GAP
    right of the rightmost artboard already in that row (x 0 in an empty row). Row 0 is y 0, or FLOW_GAP_Y below
    the flow's lowest screen when flow placed any. links: board_links(); template.html places them by the same rule."""
    flow = flow_places(board, links)
    y0 = max((fy + fh for _, fy, _, fh in flow.values()), default=-FLOW_GAP_Y) + FLOW_GAP_Y
    at: dict[str, tuple[float, float, float, float]] = {}
    order: list[str] = []
    column: list[tuple[str, tuple[float, float]]] = []
    only_slides = True
    for a in board.get("artboards") or []:
        if not isinstance(a, dict) or not isinstance(a.get("id"), str) or a["id"] in order:
            continue
        size = artboard_size(a)
        if not size:
            continue
        order.append(a["id"])
        only_slides = only_slides and a.get("device") == "slide"
        x, y = a.get("x"), a.get("y")
        if a["id"] in flow:
            x, y = flow[a["id"]][:2]
        elif not _placed(a):
            if a.get("device") == "slide":
                column.append((a["id"], size))
                continue
            src = at.get(a.get("variantOf")) if isinstance(a.get("variantOf"), str) else None
            y = src[1] if src else y0
            row = [bx + bw for bx, by, bw, _ in at.values() if by == y]
            x = max(row) + BOARD_GAP if row else 0
        at[a["id"]] = (x, y, *size)
    cx = 0 if only_slides else max(bx + bw for bx, _, bw, _ in at.values()) + BOARD_GAP
    cy = 0
    for aid, (w, h) in column:
        at[aid] = (cx, cy, w, h)
        cy += h + SLIDE_GAP
    return {aid: at[aid] for aid in order}


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
    """A screen fragment's problems, one per construct, as (line, message); whether any data-bd is set; how often
    each data-bd name occurs; and every element with data-nav or data-nav-label (navs, in document order)."""
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.errors: list[tuple[int, str]] = []
        self.whole_doc = False
        self.has_bd = False
        self.bd_count: dict[str, int] = {}
        self.navs: list[dict] = []   # {line, bd, nav, label, hidden}; nav or label None when the attribute is absent
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
            bd = dict(attrs)["data-bd"] or ""
            self.bd_count[bd] = self.bd_count.get(bd, 0) + 1
        if "data-nav" in names or "data-nav-label" in names:
            at = dict(attrs)
            self.navs.append({"line": self.getpos()[0], "bd": at.get("data-bd"), "hidden": "hidden" in names,
                              "nav": (at["data-nav"] or "") if "data-nav" in at else None,
                              "label": (at["data-nav-label"] or "") if "data-nav-label" in at else None})
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


def parse_screen(text: str) -> _ScreenLint:
    p = _ScreenLint()
    p.feed(text)
    p.close()
    return p


def lint_screen(rep: Report, where: str, f: Path, shown: str) -> _ScreenLint | None:
    """A screen file: an ERROR when it is missing or holds a network URL, a banned tag or a whole document; a WARN
    above MAX_SCREEN_BYTES or without any data-bd (the annotator's element names). Returns the parsed file (its
    links go through lint_links), None when it is unreadable."""
    text = _read_text(f)
    if text is None:
        rep.err(where, f"screen file {shown} is missing or unreadable: write the artboard's HTML fragment there")
        return None
    size = len(text.encode("utf-8"))
    if size > MAX_SCREEN_BYTES:
        rep.warn(where, f"{shown} is {size // 1024} KB (> {MAX_SCREEN_BYTES // 1024} KB): use kit classes, split it into "
                 "artboards, and edit it in place rather than rewriting it")
    p = parse_screen(text)
    for line, msg in p.errors:
        rep.err(f"{where} {shown}:{line}", msg)
    if not p.has_bd:
        rep.warn(where, f"{shown} has no data-bd: name the elements a reader may point at (data-bd=\"submit\")")
    return p


BD_NAME = re.compile(r"^[A-Za-z0-9_-]+$")   # a data-bd name the inspector reports (its link key and Present's tap)


def parse_nav(value: str) -> tuple[str, str | None] | str:
    """A data-nav value as (kind, target artboard; None for back), else the reason it is malformed."""
    v = value.strip()
    if v == "back":
        return "back", None
    kind, colon, to = v.partition(":")
    if not colon:
        kind, to = "push", v
    if kind == "back":
        return "`back` takes no target: write data-nav=\"back\""
    if kind not in NAV_KINDS or not to.strip():
        return f"write [kind:]artboard or back; kinds {', '.join(k for k in NAV_KINDS if k != 'back')} (none: push)"
    return kind, to.strip()


def screen_links(p: _ScreenLint, aid: str, art_ids: set[str]) -> tuple[list[dict], list[tuple[str, int, str]]]:
    """One screen's links ({from, el, to, kind, label?, edge?} in document order; only valid ones) and its link
    problems as (ERROR|WARN, line, message), per *Navigation › Lint* in references/schema.md."""
    links, probs = [], []
    for n in p.navs:
        line, nav, label = n["line"], n["nav"], n["label"]
        if nav is None:
            probs.append(("ERROR", line, "data-nav-label without data-nav: a label names a link; add data-nav or drop it"))
            continue
        parsed = parse_nav(nav)
        if isinstance(parsed, str):
            probs.append(("ERROR", line, f"data-nav=\"{nav}\": {parsed}"))
            continue
        kind, to = parsed
        if to is not None and to not in art_ids:
            probs.append(("ERROR", line, f"data-nav=\"{nav}\": no artboard '{to}' on this board"))
            continue
        bd = n["bd"]
        if not bd or not BD_NAME.match(bd) or p.bd_count.get(bd, 0) != 1:
            why = "has no data-bd" if not bd else f"data-bd \"{bd}\" is {'not unique in this file' if BD_NAME.match(bd) else 'not letters, digits, - and _'}"
            probs.append(("ERROR", line, f"data-nav=\"{nav}\" {why}: name the element uniquely (data-bd=\"start\"); the "
                          "link's key and Present's tap use the name"))
            continue
        if to == aid:
            probs.append(("WARN", line, f"data-nav=\"{nav}\" leads to its own screen: a typo? (a tab bar's current tab has "
                          "no data-nav)"))
        if n["hidden"] and not label:
            probs.append(("WARN", line, f"hidden link \"{bd}\" has no data-nav-label: Present shows a gesture link by its "
                          "label (\"Swipe left\")"))
        if label and len(label) > MAX_NAV_LABEL:
            probs.append(("WARN", line, f"data-nav-label is {len(label)} characters (> {MAX_NAV_LABEL}): a label pill on "
                          "an arrow fits about 40"))
        ln = {"from": aid, "el": bd, "to": to, "kind": kind}
        if label:
            ln["label"] = label
        if n["hidden"]:
            ln["edge"] = True
        links.append(ln)
    return links, probs


def links_of(board: dict, texts: dict[str, str | None]) -> list[dict]:
    """The board's links from its screens' text ({artboard id: text}, read_screens' shape), in board order then
    document order: [{from, el, to, kind, label?, edge?}]. to is None for back; label is data-nav-label; edge marks a
    gesture link (a hidden element: its arrow starts at the screen's border)."""
    arts = [a for a in (board or {}).get("artboards") or [] if isinstance(a, dict) and isinstance(a.get("id"), str)]
    art_ids = {a["id"] for a in arts}
    out, seen = [], set()
    for a in arts:
        text = texts.get(a["id"]) if not is_icons(a) and a["id"] not in seen else None
        seen.add(a["id"])
        if text and "data-nav" in text:
            out += screen_links(parse_screen(text), a["id"], art_ids)[0]
    return out


def board_links(doc: dict, doc_path: Path) -> list[dict]:
    """The design doc's links as its screen files have them now (links_of); [] for a doc without a board."""
    b = board_of(doc)
    return links_of(b, read_screens(doc, doc_path)) if b else []


def lint_links(rep: Report, bw: str, b: dict, parsed: dict[str, tuple[str, str, _ScreenLint]]) -> None:
    """The board's links: each screen's link problems (screen_links), board.entry and board.layout, and the screens
    no entry reaches. parsed: {artboard id: (where, shown file, its parse)} for the readable screens."""
    arts = {a["id"]: a for a in b["artboards"] if isinstance(a, dict) and isinstance(a.get("id"), str)}
    links = []
    for aid, (where, shown, p) in parsed.items():
        found, probs = screen_links(p, aid, set(arts))
        links += found
        for level, line, msg in probs:
            (rep.err if level == "ERROR" else rep.warn)(f"{where} {shown}:{line}", msg)
    if b.get("layout") is not None and b["layout"] not in BOARD_LAYOUTS:
        rep.err(bw + ".layout", f"'{b['layout']}' not in {list(BOARD_LAYOUTS)}")
    entry = b.get("entry") or []
    for i, e in enumerate(entry):
        if e not in arts:
            rep.err(f"{bw}.entry[{i}]", f"'{e}' is no artboard in this board: reach is counted from the entries")
    if not links:
        return
    if not entry:
        rep.warn(bw, "the screens link to each other but the board has no entry: list the screens a flow starts from "
                 "(\"entry\": [\"login\"])")
        return
    nexts: dict[str, list[str]] = {}
    for ln in links:
        if ln["kind"] != "back":
            nexts.setdefault(ln["from"], []).append(ln["to"])
    reached, queue = set(), [e for e in entry if e in arts]
    while queue:
        u = queue.pop()
        if u not in reached:
            reached.add(u)
            queue += nexts.get(u, [])
    linked_devices = {arts[ln[k]].get("device") for ln in links for k in ("from", "to") if ln[k]}
    for aid, a in arts.items():
        if (aid in reached or a.get("variantOf") is not None or a.get("device") in ("slide", "icons")
                or a.get("device") not in linked_devices):
            continue
        rep.warn(f"{bw} artboard '{aid}'", f"no entry reaches it ({', '.join(entry)}): link to it with data-nav, add it to "
                 "entry, or drop it")


# icon layers: what an SVG drawn as an <img> or on a canvas can't use, and the drawing elements the safe-circle
# check reads (subtrees of SVG_UNDRAWN are definitions, not drawing)
SVG_UNDRAWN = {"defs", "clipPath", "mask", "symbol", "pattern", "marker", "linearGradient", "radialGradient", "filter",
               "metadata", "title", "desc", "style"}
SVG_NUMBER = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
SVG_TRANSFORM = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")
SVG_PATH_TOKEN = re.compile(r"[MmZzLlHhVvCcSsQqTtAa]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


def _svg_tree(text: str):
    """An SVG layer as nested (tag, attrs, line, children), tags and attributes without namespace processing (svg,
    xlink:href); or the reason it isn't usable XML. A DOCTYPE or an entity is refused: layers need neither."""
    import xml.parsers.expat
    root: list = []
    stack: list = []
    texts: list[str] = []
    p = xml.parsers.expat.ParserCreate()

    def start(tag, attrs):
        node = (tag, attrs, p.CurrentLineNumber, [])
        (stack[-1][3] if stack else root).append(node)
        stack.append(node)

    def doctype(*_):
        raise ValueError(f"line {p.CurrentLineNumber}: a DOCTYPE; drop it (a layer needs no DTD or entities)")

    p.StartElementHandler = start
    p.EndElementHandler = lambda tag: stack.pop()
    p.StartDoctypeDeclHandler = doctype
    p.EntityDeclHandler = doctype
    p.CharacterDataHandler = lambda d: texts.append(d) if stack and stack[-1][0].split(":")[-1] == "style" else None
    try:
        p.Parse(text, True)
    except xml.parsers.expat.ExpatError as e:
        return f"not XML: {e}"
    except ValueError as e:
        return str(e)
    return root[0], "".join(texts)


def _mul(m, n):
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2, a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def _transform(s: str | None):
    """An SVG transform attribute as a matrix (a, b, c, d, e, f)."""
    m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for name, args in SVG_TRANSFORM.findall(s or ""):
        v = [float(x) for x in SVG_NUMBER.findall(args)]
        if name == "matrix" and len(v) == 6:
            t = tuple(v)
        elif name == "translate" and v:
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == "scale" and v:
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "rotate" and v:
            r = math.radians(v[0])
            t = (math.cos(r), math.sin(r), -math.sin(r), math.cos(r), 0, 0)
            if len(v) == 3:
                t = _mul(_mul((1, 0, 0, 1, v[1], v[2]), t), (1, 0, 0, 1, -v[1], -v[2]))
        elif name in ("skewX", "skewY") and v:
            k = math.tan(math.radians(v[0]))
            t = (1, 0, k, 1, 0, 0) if name == "skewX" else (1, k, 0, 1, 0, 0)
        else:
            continue
        m = _mul(m, t)
    return m


def _num(attrs: dict, k: str) -> float:
    m = SVG_NUMBER.match((attrs.get(k) or "0").strip())
    return float(m.group(0)) if m else 0.0


def _path_points(d: str) -> list[tuple[float, float]]:
    """The points a path's outline passes through: every segment's end, and three points along each curve (an
    arc: its ends only). Stops at the first token it can't read."""
    toks = SVG_PATH_TOKEN.findall(d or "")
    pts, i, cmd = [], 0, None
    x = y = sx = sy = 0.0
    prev_ctrl = None
    arity = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}

    def bez(p0, ctrl, p3):
        for t in (0.25, 0.5, 0.75):
            ps = [p0, *ctrl, p3]
            while len(ps) > 1:
                ps = [((1 - t) * a[0] + t * b[0], (1 - t) * a[1] + t * b[1]) for a, b in zip(ps, ps[1:])]
            pts.append(ps[0])

    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]
            i += 1
            if cmd in "Zz":
                x, y = sx, sy
                pts.append((x, y))
                continue
        if cmd is None or cmd in "Zz":
            break
        n = arity[cmd.upper()]
        try:
            v = [float(t) for t in toks[i:i + n]]
        except ValueError:
            break
        if len(v) < n:
            break
        i += n
        rel = cmd.islower()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        C = cmd.upper()
        if C == "H":
            x = v[0] + (x if rel else 0)
        elif C == "V":
            y = v[0] + (y if rel else 0)
        elif C == "A":
            x, y = v[5] + ox, v[6] + oy
        else:
            xy = [(v[k] + ox, v[k + 1] + oy) for k in range(0, n, 2)]
            if C == "S":
                xy.insert(0, prev_ctrl or (x, y))
            elif C == "T":
                xy.insert(0, prev_ctrl or (x, y))
            if C in ("C", "S", "Q", "T"):
                bez((x, y), xy[:-1], xy[-1])
                c = xy[-2]
                prev_ctrl = (2 * xy[-1][0] - c[0], 2 * xy[-1][1] - c[1])
            x, y = xy[-1]
        if C not in ("C", "S", "Q", "T"):
            prev_ctrl = None
        if C == "M":
            sx, sy = x, y
            cmd = "l" if rel else "L"   # further pairs after a moveto are linetos
        pts.append((x, y))
    return pts


def _shape_points(tag: str, at: dict) -> list[tuple[float, float]]:
    """The points that bound one drawing element, in its own coordinates."""
    if tag in ("rect", "image", "use", "foreignObject"):
        x, y, w, h = _num(at, "x"), _num(at, "y"), _num(at, "width"), _num(at, "height")
        return [(x, y), (x + w, y), (x, y + h), (x + w, y + h)] if w > 0 and h > 0 else []
    if tag in ("circle", "ellipse"):
        cx, cy = _num(at, "cx"), _num(at, "cy")
        rx = _num(at, "r") if tag == "circle" else _num(at, "rx")
        ry = rx if tag == "circle" else _num(at, "ry")
        return [(cx + rx * math.cos(k * math.pi / 16), cy + ry * math.sin(k * math.pi / 16)) for k in range(32)]
    if tag == "line":
        return [(_num(at, "x1"), _num(at, "y1")), (_num(at, "x2"), _num(at, "y2"))]
    if tag in ("polyline", "polygon"):
        v = [float(t) for t in SVG_NUMBER.findall(at.get("points") or "")]
        return list(zip(v[0::2], v[1::2]))
    if tag == "path":
        return _path_points(at.get("d") or "")
    return []


def _view_box(at: dict) -> tuple[float, float, float] | str:
    """(min x, min y, size) of a square viewBox, else why it doesn't do."""
    v = [float(t) for t in SVG_NUMBER.findall(at.get("viewBox") or "")]
    if len(v) != 4:
        return "no viewBox: give it a square one, viewBox=\"0 0 108 108\""
    if v[2] <= 0 or v[2] != v[3]:
        return f"viewBox \"{at.get('viewBox')}\" is not square: every output is a square render (0 0 108 108)"
    return v[0], v[1], v[2]


def lint_icon(rep: Report, where: str, a: dict, doc_path: Path) -> None:
    """An icons artboard's layers (*App icons › Lint* in references/schema.md): fg.svg is required; every layer is
    XML with a square viewBox and nothing a canvas can't draw or that reaches the network; fg stays in the safe
    circle; mono.svg and a background are expected; text should be paths."""
    folder = icon_dir(doc_path, a)
    rel = f"{doc_stem(Path(doc_path))}.design/{a['id']}/"
    icon = a.get("icon") or {}
    for name in ICON_LAYERS:
        f = folder / name
        if not f.is_file():
            if name == "fg.svg":
                rep.err(where, f"{rel}fg.svg is missing: write the logo layer there (an SVG, viewBox 0 0 108 108)")
            continue
        shown = rel + name
        text = _read_text(f)
        tree = _svg_tree(text) if text is not None else "unreadable as UTF-8 text"
        if isinstance(tree, str):
            rep.err(f"{where} {shown}", tree)
            continue
        (tag, at, line, kids), style = tree
        if tag.split(":")[-1] != "svg":
            rep.err(f"{where} {shown}:{line}", f"the root is <{tag}>, not <svg>")
            continue
        vb = _view_box(at)
        if isinstance(vb, str):
            rep.err(f"{where} {shown}:{line}", vb)
        if NET_URL.search(style):
            rep.err(f"{where} {shown}", "<style>: a network URL; a layer loads nothing")
        text_line, far = None, None   # far: (distance from the centre in dp, line, tag)
        scale = ICON_SIZE / vb[2] if not isinstance(vb, str) else None
        root_m = (scale, 0.0, 0.0, scale, -vb[0] * scale, -vb[1] * scale) if scale else None

        def walk(node, m, drawn: bool) -> None:
            nonlocal text_line, far
            ntag, nat, nline, nkids = node
            local = ntag.split(":")[-1]
            if local in ("script", "foreignObject"):
                rep.err(f"{where} {shown}:{nline}", f"<{local}>: not allowed in a layer (an image runs no script and draws "
                        "no HTML)")
            bad = next((k for k in nat if k.lower().startswith("on")), None)
            if bad:
                rep.err(f"{where} {shown}:{nline}", f"<{local} {bad}>: no event handlers in a layer")
            net = next((k for k, v in nat.items() if NET_URL.search(v)), None)
            if net:
                rep.err(f"{where} {shown}:{nline}", f"<{local} {net}>: a network URL; a layer loads nothing (inline it)")
            if local == "text" and text_line is None:
                text_line = nline
            drawn = drawn and local not in SVG_UNDRAWN and nat.get("display") != "none"
            if m is not None and drawn:
                m = _mul(m, _transform(nat.get("transform")))
                for px, py in _shape_points(local, nat):
                    gx, gy = m[0] * px + m[2] * py + m[4], m[1] * px + m[3] * py + m[5]
                    dist = math.hypot(gx - ICON_SIZE / 2, gy - ICON_SIZE / 2)
                    if far is None or dist > far[0]:
                        far = (dist, nline, local)
            for k in nkids:
                walk(k, m, drawn)

        for k in kids:
            walk(k, root_m if name == "fg.svg" else None, True)
        if text_line is not None:
            rep.warn(f"{where} {shown}:{text_line}", "<text>: fonts don't load in an image or a canvas; convert the text "
                     "to paths")
        if far and far[0] > ICON_SAFE_R + 0.5:
            rep.warn(f"{where} {shown}:{far[1]}", f"<{far[2]}> reaches {far[0]:.1f} dp from the centre, outside the "
                     f"{2 * ICON_SAFE_R} dp safe circle (r {ICON_SAFE_R} of {ICON_SIZE}): launcher masks cut it; keep "
                     "the logo inside, with a margin")
    if not (folder / "mono.svg").is_file():
        rep.warn(where, f"no {rel}mono.svg: Android 13 themed icons fall back to the full-colour icon; draw the mark in "
                 "one colour there")
    if not icon.get("bg") and not (folder / "bg.svg").is_file():
        rep.warn(where, f"no background (icon.bg or {rel}bg.svg): the iOS light icon would have alpha, which App Store "
                 "Connect rejects")



def validate_site_board(rep: Report, bw: str, b: dict, doc_path: Path | None) -> Path | None:
    """A website board's breakpoints, viewport heights and root; returns the root folder when it exists (source hints
    are checked against it), else None."""
    bps = b.get("breakpoints")
    if bps is not None:
        ok = isinstance(bps, list) and 0 < len(bps) <= MAX_BREAKPOINTS and len(set(map(str, bps))) == len(bps) and all(
            isinstance(v, int) and not isinstance(v, bool) and MIN_BREAKPOINT <= v <= MAX_BREAKPOINT for v in bps)
        if not ok:
            rep.err(bw + ".breakpoints", f"1 to {MAX_BREAKPOINTS} distinct widths in CSS px, {MIN_BREAKPOINT} to "
                    f"{MAX_BREAKPOINT} (default {list(BREAKPOINTS)})")
    vps = b.get("viewport")
    if isinstance(vps, dict) and not all(re.fullmatch(r"[1-9]\d{2,3}", k) and MIN_BREAKPOINT <= int(k) <= MAX_BREAKPOINT
                                         and isinstance(v, int) and not isinstance(v, bool)
                                         and MIN_BREAKPOINT <= v <= MAX_BREAKPOINT for k, v in vps.items()):
        rep.err(bw + ".viewport", f"{{\"<width>\": <height>}} in CSS px, both {MIN_BREAKPOINT} to {MAX_BREAKPOINT} "
                f"(e.g. {{\"1440\": 900}}): each width's design viewport height")
    if "root" not in b:
        return None
    if not isinstance(b["root"], str) or not b["root"] or URL_SCHEME.match(b["root"]):
        rep.err(bw + ".root", "the site's repo folder, a path relative to the doc (e.g. \"..\")")
        return None
    root = site_root(b, doc_path)
    if root is not None and not root.is_dir():
        rep.warn(bw + ".root", f"'{b['root']}' is no folder (from {Path(doc_path).parent}): source hints go unchecked")
        return None
    return root


def validate_sources(rep: Report, where: str, x: dict, root: Path | None) -> None:
    """`source`: one hint or a list of up to MAX_SOURCES, each `path`, `path#symbol` or `path:line`. With root, a file
    that isn't there, a symbol the file doesn't name and a line past its end are warnings."""
    if "source" not in x:
        return
    s = x["source"]
    hints = [s] if isinstance(s, str) else s if isinstance(s, list) else None
    if not hints or len(hints) > MAX_SOURCES or not all(isinstance(h, str) for h in hints):
        rep.err(where, f"a source hint (\"src/content/site.ts#hero\") or a list of up to {MAX_SOURCES}")
        return
    for h in hints:
        if PLACEHOLDER.search(h):   # the placeholder check names it
            continue
        m = SOURCE_HINT.match(h) if len(h) <= MAX_SOURCE else None
        if not m or URL_SCHEME.match(h) or ".." in m["path"].split("/") or m["path"].startswith("/"):
            rep.err(where, f"'{h[:80]}': a path in the site's repo, then #symbol or :line (\"src/components/Hero.astro\", "
                    "\"src/content/site.ts#hero\", \"src/pages/index.astro:12\")")
            continue
        if root is None:
            continue
        f = root / m["path"]
        text = _read_text(f) if f.is_file() else None
        if text is None:
            rep.warn(where, f"'{m['path']}' not found under {root}")
        elif m["sym"] and not re.search(rf"(?<![\w$]){re.escape(m['sym'])}(?![\w$])", text):
            rep.warn(where, f"'{m['path']}' never names '{m['sym']}'")
        elif m["line"] and int(m["end"] or m["line"]) > text.count("\n") + 1:
            rep.warn(where, f"'{m['path']}' has {text.count(chr(10)) + 1} lines; '{h}' points past them")


def validate_page(rep: Report, aw: str, a: dict, root: Path | None, decisions: dict[str, dict]) -> None:
    """A website page: its live `url` (a loopback dev server; no screen file then), `source`, and `sections`, each a
    CSS selector with source hints and optionally the variants a brief decision picks between, shown in place."""
    if "url" in a:
        why = live_url_problem(a["url"])
        if why:
            rep.err(aw + ".url", why)
        if "src" in a:
            rep.err(aw + ".src", "a live page (url) has no screen file: drop src")
    validate_sources(rep, aw + ".source", a, root)
    secs = a.get("sections")
    if secs is None:
        return
    if not isinstance(secs, list) or len(secs) > MAX_SECTIONS:
        rep.err(aw + ".sections", f"a list of up to {MAX_SECTIONS} sections")
        return
    ids: set[str] = set()
    for j, s in enumerate(secs):
        sw = f"{aw}.sections[{j}]"
        if not isinstance(s, dict) or not need(rep, sw, s, "id", "title", "sel"):
            continue
        check_id(rep, sw, s["id"])
        if s["id"] in ids:
            rep.err(sw, f"duplicate section id '{s['id']}'")
        ids.add(s["id"])
        lint_text(rep, sw + ".title", s["title"])
        if not isinstance(s["sel"], str) or not s["sel"].strip() or len(s["sel"]) > 200 or (
                re.search(r"[<{};]", s["sel"]) and not PLACEHOLDER.search(s["sel"])):
            rep.err(sw + ".sel", "the section's CSS selector in the page, e.g. \"section.hero\" or \"#faq\" (at most 200 characters)")
        validate_sources(rep, sw + ".source", s, root)
        if "variants" in s and "decision" not in s:
            rep.err(sw + ".variants", "variants need a `decision`: the brief item whose choices they show")
        if "decision" not in s:
            continue
        it = decisions.get(s["decision"])
        if it is None:
            rep.err(sw + ".decision", f"'{s['decision']}' is no decision item of the checklist `brief`")
            continue
        choices = {c.get("id") for c in it["choices"] if isinstance(c, dict)}
        if len(choices) > 3:
            rep.warn(f"item brief/{s['decision']}", f"{len(choices)} versions of one section: offer 2 or 3")
        var = s.get("variants", {})
        if not isinstance(var, dict):
            rep.err(sw + ".variants", "{choice id: [edits]}: what each choice changes in the section")
            continue
        for cid, edits in var.items():
            vw = f"{sw}.variants.{cid}"
            if cid not in choices:
                rep.err(vw, f"'{cid}' is no choice of brief/{s['decision']} ({', '.join(sorted(map(str, choices)))})")
            if not isinstance(edits, list) or len(edits) > MAX_VARIANT_EDITS:
                rep.err(vw, f"a list of up to {MAX_VARIANT_EDITS} edits, each {{sel?, text | html}}")
                continue
            for k, e in enumerate(edits):
                ew = f"{vw}[{k}]"
                if not isinstance(e, dict) or set(e) - {"sel", "text", "html"} or ("text" in e) == ("html" in e):
                    rep.err(ew, "{sel?, text} or {sel?, html}: the element in the section (the section without sel) and "
                            "its new text or HTML")
                    continue
                if "sel" in e and (not isinstance(e["sel"], str) or not e["sel"] or len(e["sel"]) > 200):
                    rep.err(ew + ".sel", "a CSS selector inside the section, at most 200 characters")
                v = e.get("text", e.get("html"))
                if not isinstance(v, str):
                    rep.err(ew, "text and html are strings")
                elif "html" in e:
                    if len(v.encode("utf-8")) > MAX_EDIT_HTML:
                        rep.err(ew + ".html", f"over {MAX_EDIT_HTML // 1024} KB: edit a smaller element")
                    for _, msg in parse_screen(v).errors:
                        rep.err(ew + ".html", msg)
                else:
                    lint_text(rep, ew + ".text", v)


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
    fw_ids, declared = set(BUILTIN_FRAMEWORKS), set()
    for i, fw in enumerate(b.get("frameworks") or []):
        fwh = f"{bw}.frameworks[{i}]"
        if not need(rep, fwh, fw, "id", "label"):
            continue
        check_id(rep, fwh, fw["id"])
        if fw["id"] in declared or (fw["id"] in BUILTIN_FRAMEWORKS and fw["id"] not in SHIPPED_PRESETS):
            rep.err(fwh, f"framework id '{fw['id']}' is {'a duplicate' if fw['id'] in declared else 'built in'}")
        declared.add(fw["id"])
        fw_ids.add(fw["id"])
        if ("files" in fw) == ("store" in fw):
            rep.err(fwh, "give 'files' (paths from the doc's folder) or 'store' (a `serve.py add-framework` name), not both")
            continue
        if "store" in fw:
            check_id(rep, fwh + ".store", fw["store"])
            man = frameworks_dir() / fw["store"] / "manifest.json"
            if ID_RE.match(fw["store"]) and not man.is_file() and fw["store"] not in SHIPPED_PRESETS:
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
    site = doc_type(doc.get("meta") or {}) == "website"
    brief = next((c for c in all_blocks(doc) if c.get("type") == "checklist" and c.get("id") == "brief"), None)
    if site:
        root = validate_site_board(rep, bw, b, doc_path)
        decisions = {it.get("id"): it for it in (brief or {}).get("items") or []
                     if isinstance(it, dict) and isinstance(it.get("choices"), list)}
    else:
        for k in ("breakpoints", "viewport", "root"):
            if k in b:
                rep.err(f"{bw}.{k}", "only a website's board has it: set meta.type to 'website'")
    art_ids: set[str] = set()
    variants: list[tuple[str, str, str]] = []
    parsed: dict[str, tuple[str, str, _ScreenLint]] = {}
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
        image = listing.is_image_shot(a) and doc_type(doc.get("meta") or {}) == "storelisting"   # checked by validate_listing
        if "src" in a and not image and not _screen_src_ok(a["src"]):
            rep.err(aw + ".src", f"'{a['src']}': a relative path to an .html file in a <name>.design/ folder, no '..'")
        if is_icons(a):
            if "src" in a:
                rep.err(aw + ".src", "an icons artboard has no screen file: its layers sit in <stem>.design/<id>/")
            bg = (a.get("icon") or {}).get("bg")
            if bg is not None and not HEX_COLOR.match(bg):
                rep.err(aw + ".icon.bg", f"{_shown(bg)}: a hex colour, #rgb or #rrggbb")
            name = (a.get("icon") or {}).get("name")
            if isinstance(name, str) and len(name) > MAX_ICON_NAME:
                rep.warn(aw + ".icon.name", f"{len(name)} characters (> {MAX_ICON_NAME}): a home screen shows about 12")
        elif "icon" in a:
            rep.err(aw + ".icon", "only an artboard with device \"icons\" has an icon")
        if site:
            validate_page(rep, aw, a, root, decisions)
        else:
            for k in ("url", "source", "sections"):
                if k in a:
                    rep.err(f"{aw}.{k}", "only a website's page has it: set meta.type to 'website'")
        if doc_path is not None and ID_RE.match(a["id"]) and not is_live(a) and not image:
            if is_icons(a):
                lint_icon(rep, aw, a, doc_path)
            else:
                rel = screen_rel(doc_path, a)
                p = lint_screen(rep, aw, Path(doc_path).parent / rel, rel)
                if p is not None:
                    parsed.setdefault(a["id"], (aw, rel, p))
    for where, aid, src in variants:
        if src == aid or src not in art_ids:
            rep.err(where, f"'{src}' is {'the artboard itself' if src == aid else 'no artboard in this board'}")
    lint_links(rep, bw, b, parsed)
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
    elif t == "storelisting":
        out += listing.contract(doc)
    elif t in BOARD_TYPES:
        boards = [b for b in blocks if b.get("type") == "board"]
        if len(boards) != 1:
            out.append(f"a {t} needs exactly one board block (it has {len(boards)})")
        elif not boards[0].get("artboards"):
            out.append(f"a {t}'s board needs at least one artboard")
        elif t in ("presentation", "website") and isinstance(boards[0]["artboards"], list):
            want = "slide" if t == "presentation" else "page"
            other = [f"{a.get('id')}: {a.get('device') or 'no device'}" for a in boards[0]["artboards"]
                     if isinstance(a, dict) and a.get("device") != want]
            if other and t == "presentation":
                out.append(f"a presentation holds slides only; use a design doc for screens ({', '.join(other)})")
            elif other:
                out.append(f"a website holds pages only (device \"page\"); use a design doc for app screens ({', '.join(other)})")
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
    res = doc.get("resolves")
    if res is not None and not (isinstance(res, list) and all(isinstance(x, str) and RESOLVES_ID.fullmatch(x) for x in res)):
        rep.err("doc.resolves", "list of comment ids (as the reply Markdown shows them, e.g. c…): the comments this revision addresses")
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
            if doc_type(doc.get("meta") or {}) not in BOARD_TYPES:
                rep.err(bw, "a board block is for design, presentation, website and storelisting docs: set meta.type to one of them")
            boards.append((bw, b))
        elif t == "listing":
            if doc_type(doc.get("meta") or {}) != "storelisting":
                rep.err(bw, "a listing block is for storelisting docs: set meta.type to 'storelisting'")

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

    if doc_type(doc.get("meta") or {}) == "storelisting":
        try:
            listing.validate_listing(rep, doc, doc_path)
        except (listing.RulesError, OSError, ValueError) as e:
            rep.err("listing", f"cannot read the store rules: {e}")
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


# A website's live pages, recorded per revision (serve.py writes them: POST /__bluedoc/snapshot, `serve.py snapshot`):
# <name>.snapshots/rev-<rev>/<page id>@<width>.html beside the doc, each a whole document whose head carries
# <meta name="bluedoc-snapshot" content="external=<images still on the dev server>; at=<UTC time>">.
SNAP_REV = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
SNAP_FILE = re.compile(r"^([a-z0-9][a-z0-9-]*)@(\d{3,4})\.html$")
SNAP_META = re.compile(r'<meta name="bluedoc-snapshot" content="external=(\d+)[^"]*">')


def snapshots_dir(doc_path: Path) -> Path:
    """site.bluedoc.json -> site.bluedoc.snapshots/ beside it."""
    name = doc_path.name[:-5] if doc_path.name.endswith(".json") else doc_path.name
    return doc_path.with_name(name + ".snapshots")


def snapshot_path(doc_path: Path, rev: str, page: str, width: int) -> Path | None:
    """Where page's snapshot at width for revision rev goes; None for a rev, page id or width it can't be."""
    if not (isinstance(rev, str) and SNAP_REV.match(rev) and isinstance(page, str) and ID_RE.match(page)
            and isinstance(width, int) and not isinstance(width, bool) and 240 <= width <= 3840):
        return None
    return snapshots_dir(Path(doc_path)) / f"rev-{rev}" / f"{page}@{width}.html"


def snapshot_index(doc_path: Path) -> dict[str, dict[str, dict[str, int]]]:
    """{rev: {page id: {width: images it left on the dev server}}} of the snapshots beside the doc; {} without any."""
    out: dict[str, dict[str, dict[str, int]]] = {}
    base = snapshots_dir(Path(doc_path))
    try:
        revs = sorted(p for p in base.iterdir() if p.is_dir() and not p.is_symlink() and p.name.startswith("rev-"))
    except OSError:
        return out
    for d in revs:
        rev = d.name[4:]
        if not SNAP_REV.match(rev):
            continue
        for f in sorted(d.iterdir()):
            m = SNAP_FILE.match(f.name)
            if not m or not f.is_file() or f.is_symlink() or not 240 <= int(m[2]) <= 3840:
                continue
            try:
                with f.open("rb") as fh:
                    head = fh.read(4096).decode("utf-8", "replace")
            except OSError:
                continue
            ext = SNAP_META.search(head)
            out.setdefault(rev, {}).setdefault(m[1], {})[str(int(m[2]))] = int(ext[1]) if ext else 0
    return out


def live_pages(doc: dict) -> list[str]:
    """The ids of a website doc's live pages (`url`); [] on any other doc."""
    if doc_type((doc or {}).get("meta") or {}) != "website":
        return []
    return [a["id"] for a in _artboards(doc) if is_live(a)]


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
    design doc's screen files and icon layers join the revision: their text goes into the history's html pool, by
    _hash, and the entry maps artboard ids (a layer: "<id>/<file>") to those hashes (screens) and lists the board's
    links (links_of; no key when there are none). texts ({artboard id: text}) stands in for the files.
    keep_screens keeps the screens and links the history already holds for this rev: cmd_patch records the version a
    patch replaces, whose files the reader's change may already have rewritten."""
    meta = doc.get("meta") or {}
    rev = str(meta.get("rev") or "")
    snap = snapshot(doc, h["blocks"])
    entry = {"rev": rev, "date": meta.get("date") or "", "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **snap}
    revs = h["revs"]
    last = revs[-1] if revs and revs[-1]["rev"] == rev else None
    if keep_screens and last and "screens" in last:
        entry["screens"] = last["screens"]
        if last.get("links"):
            entry["links"] = last["links"]
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
            links = links_of(board_of(doc), texts)
            if links:
                entry["links"] = links
        if doc_path is not None and listing.listing_of(doc):   # a storelisting's captures: their PNG's hash, no text
            caps = listing.file_hashes(doc, doc_path)
            if caps:
                entry["screens"] = {**entry.get("screens", {}), **caps}
    if last:
        same = json.dumps(restore(h, last), sort_keys=True) == json.dumps(doc, sort_keys=True)
        moved = sorted(a for a in set(last.get("screens") or {}) | set(entry.get("screens") or {})
                       if (last.get("screens") or {}).get(a) != (entry.get("screens") or {}).get(a))
        if same and not moved:
            msg = f"rev {rev} unchanged"
            if last.get("links") != entry.get("links"):   # recorded before links were: add them, keep the rest
                last.pop("links", None)
                last.update({"links": entry["links"]} if "links" in entry else {})
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
        if doc.get("resolves") and revs[-2]["head"].get("resolves") == doc.get("resolves"):
            out += f"\nWARN  doc.resolves: same as rev {revs[-2]['rev']}; list only the comments this revision addresses"
    return out


def embed_history(h: dict | None, doc: dict, links: list[dict] | None = None) -> dict | None:
    """The history as the page needs it: blocks the current doc also has become '@section/block'
    references into the page's own document, so the page carries each block once. Each revision carries its
    `links`; links, when given, are the current revision's (read from the files now). A doc with one revision
    gets None, or with links only its current entry, {rev, links}, so the page reads every revision's links alike."""
    cur_rev = str((doc.get("meta") or {}).get("rev") or "")
    if not h or len(h["revs"]) < 2:
        if links is None and h and h["revs"] and h["revs"][-1]["rev"] == cur_rev:
            links = h["revs"][-1].get("links")
        return {"revs": [{"rev": cur_rev, "links": links}], "blocks": {}} if links else None
    here = {}
    for i, s in enumerate(doc.get("sections") or []):
        for j, b in enumerate(s.get("blocks") or []):
            here.setdefault(_hash(b), f"@{i}/{j}")
    revs, blocks = [], {}
    for idx, e in enumerate(h["revs"]):
        out = {"rev": e["rev"], "date": e.get("date", ""), "built": e.get("built", "")}
        if "screens" in e:   # a design's {artboard id: screen hash}; the HTML stays in the history file (?rev=)
            out["screens"] = e["screens"]
        if e.get("links"):
            out["links"] = e["links"]
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
        elif links is not None:
            out["links"] = links
        revs.append(out)
    if links is not None and not any("head" not in r for r in revs):   # no entry for this rev: links only
        revs.append({"rev": cur_rev, "links": links})
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


def with_screen_csp(page: str) -> str:
    """A whole screen document with STANDALONE_SCREEN_CSP as a <meta> first in its <head>."""
    meta = f'<meta http-equiv="Content-Security-Policy" content="{STANDALONE_SCREEN_CSP}">'
    return re.sub(r"(?i)<head[^>]*>", lambda m: m.group(0) + meta, page, count=1)


def _serve():
    """serve.py, which wraps screens (wrap_screen) and builds deck files (deck_html)."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import serve
    return serve


def standalone_screens(doc: dict, doc_path: Path) -> dict[str, str] | None:
    """{artboard id: its screen as a whole document with the kit inlined} for an -o file; None for a doc without
    a board. serve.py's wrap_screen fills the shell (an icons artboard: with serve.icon_fragment, the sheet with its
    layers inline); unreadable screens are left out (validate reported them)."""
    texts = read_screens(doc, doc_path)
    if not texts:
        return None
    serve = _serve()
    out = {}
    for a in _artboards(doc):
        aid = a["id"]
        text = serve.icon_fragment(doc, Path(doc_path), aid) if is_icons(a) else texts.get(aid)
        if text is not None and aid not in out:
            out[aid] = with_screen_csp(serve.wrap_screen(doc, Path(doc_path), aid, text, inline=True))
    return out


BOARD_GEO = HERE.parent / "assets" / "board-geo.js"   # the board's router and layouts, inlined into design pages
BOARD_GEO_SLOT = "/*__BOARD_GEO__*/"


def build(doc: dict, template: str, history: dict | None = None, media_base: Path | None = None,
          diff_path: Path | None = None, problems: list[str] | None = None, state: dict | None = None,
          screens: dict[str, str] | None = None, live: dict[str, int] | None = None,
          snaps: dict[str, dict[str, dict[str, int]]] | None = None) -> str:
    """The page. media_base (the doc's folder) makes it standalone: media files become data: URIs.
    diff_path (the doc's JSON file) fills its diff refs, in the doc and in earlier revisions, and gives the current
    revision its links from the screen files; their problems go into problems, or to stderr when it is None. state is
    the reader state serve.py seeds the page with ({version, state}); None (an -o file) leaves the page on
    localStorage. screens ({artboard id: a whole screen document}, from standalone_screens) makes a design page draw
    its frames from srcdoc; None (serve.py) loads them from the screen route. live ({dev server origin: proxy port},
    serve.py's) is where a website page frames its live pages; None shows them as a placeholder. snaps (serve.py's
    snapshot_index) lists the live pages' snapshots, which earlier revisions show; None: none. A page with a board
    or a canvas (in any revision it carries) gets assets/board-geo.js, the connector router, at the template's
    BOARD_GEO_SLOT; other pages get nothing there."""
    title = (doc.get("title") or "bluedoc").replace("&", "&amp;").replace("<", "&lt;")
    if "__BLUEDOC_DOC__" not in template:
        raise SystemExit("template is missing the __BLUEDOC_DOC__ placeholder")
    board = board_of(doc)
    links = board_links(doc, Path(diff_path)) if board is not None and diff_path is not None else None
    hist = embed_history(history, doc, links)   # before expanding and inlining: it matches blocks by their JSON
    geo = ""
    if (board is not None or has_canvas(doc, hist)) and BOARD_GEO_SLOT in template:
        geo = _read_text(BOARD_GEO)
        if geo is None:
            raise SystemExit(f"cannot read {BOARD_GEO}: pages with a board or a canvas need it")
        geo = re.sub(r"(?i)</(script)", r"<\\/\1", geo)
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
    # a storelisting's page: the store rules, each shot's caption keys, its captures and the icon (listing.page_data);
    # an -o file carries its PNGs inline
    lst = None
    if doc_type(doc.get("meta") or {}) == "storelisting":
        lst = listing.page_data(doc, Path(diff_path) if diff_path is not None else None, inline=media_base is not None)
    # one pass, so a placeholder's name inside a filled value (a doc's text, a reader's note) stays text
    fill = {"__BLUEDOC_TITLE__": title, "__BLUEDOC_HISTORY__": _script_json(hist) if hist else "null",
            "__BLUEDOC_STATE__": _script_json(state) if state is not None else "null", "__BLUEDOC_DOC__": _script_json(doc),
            "__BLUEDOC_SCREENS__": _script_json(screens) if screens is not None else "null",
            "__BLUEDOC_LIVE__": _script_json(live) if live is not None else "null",
            "__BLUEDOC_SNAPS__": _script_json(snaps) if snaps is not None else "null",
            "__BLUEDOC_LISTING__": _script_json(lst) if lst is not None else "null", BOARD_GEO_SLOT: geo}
    return re.sub("|".join(map(re.escape, fill)), lambda m: fill[m.group(0)], template)


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
    design_targets = [t for t in TARGET_DEVICES if t not in ("presentation", "listing")]
    ap.add_argument("--target", help=f"design only: comma list of {','.join(design_targets)}; one starter artboard "
                    "and wireframe screen file each (default mobile). A deck is `new presentation`")
    ap.add_argument("--framework", help="design only: plain | horizon | heroui | tailwind | <a `serve.py add-framework` "
                    "name> | auto (default: you fill the brief's framework pick from the project's files; see types/design.md)")
    ap.add_argument("--icons", action="store_true", help="design only: add an `app-icon` artboard (device icons) with stub "
                    "fg.svg and mono.svg layers")
    ap.add_argument("--url", help="website only: the home page's live URL on a local dev server (http://localhost:4321/); "
                    "without it the home page is a stub screen file")
    a = ap.parse_args(argv)
    if a.shape != "pr" and a.type != "review":
        ap.error("--shape is for review docs")
    if (a.target or a.framework or a.icons) and a.type != "design":
        ap.error("--target, --framework and --icons are for design docs")
    if a.url is not None and a.type != "website":
        ap.error("--url is for website docs")
    if a.url is not None and live_url_problem(a.url):
        ap.error(f"--url: {live_url_problem(a.url)}")
    targets = [t.strip() for t in (a.target or "mobile").split(",") if t.strip()]
    if "presentation" in targets:
        ap.error("--target presentation is gone: a deck is its own type, `build.py new presentation <path> --title …`")
    bad = [t for t in targets if t not in design_targets]
    if bad or not targets or len(set(targets)) != len(targets):
        ap.error(f"--target: a comma list of distinct {', '.join(design_targets)}")
    if a.framework and a.framework != "auto" and not ID_RE.match(a.framework):
        ap.error("--framework: plain, horizon, heroui, tailwind, auto or a store name (lowercase letters, digits, -)")
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
    stubs = (scaffold_design(doc, a.out, targets, a.framework or "auto", a.icons) if a.type == "design"
             else scaffold_deck(doc, a.out) if a.type == "presentation"
             else scaffold_site(doc, a.out, a.url) if a.type == "website"
             else scaffold_listing(doc, a.out) if a.type == "storelisting" else {})
    for f in stubs:
        if f.exists():
            print(f"{f} exists; not overwriting it", file=sys.stderr)
            return 2
    a.out.parent.mkdir(parents=True, exist_ok=True)
    write_doc(a.out, doc, raw)
    for f, text in stubs.items():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
        print(f"wrote {f} (a {'layer' if f.suffix == '.svg' else 'wireframe'} stub)")
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
    if dev == "shot":   # a store shot: caption, frame and the UI slot (references/kits.md `## Store shots`)
        return (f'<main class="shot" data-bd="{aid}">\n'
                f'  <h1 class="shot-cap" data-bd="cap" data-l10n="{aid}.title">Benefit in a few words</h1>\n'
                '  <div class="shot-frame" data-bd="frame">\n'
                '    <div class="shot-ui" data-bd="ui">\n'
                '      <main class="screen safe stack gap-4" data-bd="screen">\n'
                '        <div class="wf-line" data-bd="title"></div>\n'
                '        <div class="wf-img" data-bd="hero"></div>\n'
                '        <div class="wf-text" data-bd="body"></div>\n'
                '      </main>\n'
                '    </div>\n'
                '  </div>\n'
                '</main>\n')
    if dev == "asset":
        return (f'<main class="asset" data-bd="{aid}">\n'
                '  <div class="stack gap-2 p-6" data-bd="copy">\n'
                f'    <h1 class="asset-title" data-l10n="{aid}.title" data-bd="title">App name</h1>\n'
                '  </div>\n'
                '</main>\n')
    if dev == "slide":
        return stub_slide(aid, "content", None)
    if dev == "page":   # a web page: sections down the page, one column below 768 px
        return ('<style>\n  .pg { max-width: 1120px; margin: 0 auto; }\n'
                '  @media (max-width: 767px) { .pg .cols-3 { grid-template-columns: minmax(0, 1fr); } }\n</style>\n'
                f'<main class="screen stack" data-bd="{aid}">\n'
                '  <header class="row between p-4" data-bd="nav"><div class="wf-box" data-label="Logo"></div>'
                '<div class="wf-line"></div></header>\n'
                '  <section class="pg stack gap-4 p-6 center" data-bd="hero">\n'
                '    <h1 class="display" data-bd="headline">Headline</h1>\n'
                '    <div class="wf-text" style="--lines:2" data-bd="subline"></div>\n'
                '    <button class="btn primary" data-bd="cta">Primary action</button>\n'
                '  </section>\n'
                '  <section class="pg grid cols-3 gap-4 p-6" data-bd="features">\n'
                '    <div class="wf-box" data-label="Feature"></div>\n'
                '    <div class="wf-box" data-label="Feature"></div>\n'
                '    <div class="wf-box" data-label="Feature"></div>\n'
                '  </section>\n'
                '  <footer class="pg p-6" data-bd="footer"><div class="wf-line"></div></footer>\n'
                '</main>\n')
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


STUB_ICON_LAYER = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 108 108">\n'
                   '  <circle cx="54" cy="54" r="24" fill="{fill}"/>\n</svg>\n')   # inside the 66 dp safe circle


def scaffold_site(doc: dict, out: Path, url: str | None) -> dict[Path, str]:
    """Fill a website skeleton for `build.py new website`: the home page live from url, else a stub screen file
    (fidelity wireframe, sections on its data-bd names). board.root is the repo the doc sits in, when there is one.
    Returns {file: stub text} to write beside the doc."""
    board = board_of(doc)
    home = board["artboards"][0]
    repo = next((p for p in [out.resolve().parent, *out.resolve().parent.parents] if (p / ".git").exists()), None)
    if repo is not None:
        board["root"] = os.path.relpath(repo, out.resolve().parent)
    if url:
        home["url"] = url
        doc["state"] = [{"label": "live from the dev server", "kind": "ok"}]
        return {}
    doc["state"] = [{"label": "wireframes: hi-fi after your picks", "kind": "warn"}]
    home["fidelity"] = "wireframe"
    for s in home.get("sections") or []:
        s["sel"] = f'[data-bd="{s["id"]}"]'
    hero = next((s for s in home.get("sections") or [] if s["id"] == "hero"), None)
    for edits in ((hero or {}).get("variants") or {}).values():
        for e in edits:
            e["sel"] = '[data-bd="headline"]'
    return {out.parent / screen_rel(out, home): stub_screen(home)}


def scaffold_listing(doc: dict, out: Path) -> dict[Path, str]:
    """The stub files for `build.py new storelisting`: each shot's wireframe layout (caption, frame, UI slot) and the
    icon's fg and mono layers. Returns {file: stub text} to write beside the doc."""
    stubs = {}
    for a in board_of(doc)["artboards"]:
        if is_icons(a):
            folder = icon_dir(out, a)
            stubs[folder / "fg.svg"] = STUB_ICON_LAYER.format(fill="#ffffff")
            stubs[folder / "mono.svg"] = STUB_ICON_LAYER.format(fill="#000000")
        else:
            stubs[out.parent / screen_rel(out, a)] = stub_screen(a)
    return stubs


def scaffold_deck(doc: dict, out: Path) -> dict[Path, str]:
    """The stub slide files for `build.py new presentation`, one per slide of the skeleton's board in deck order: a
    title slide first, a closing one last, content slides between. Returns {file: stub text} to write beside the doc."""
    arts, stubs = board_of(doc)["artboards"], {}
    for n, a in enumerate(arts, 1):
        kind = "title" if n == 1 else "closing" if n == len(arts) else "content"
        stubs[out.parent / screen_rel(out, a)] = stub_slide(a["id"], kind, n)
    return stubs


def scaffold_design(doc: dict, out: Path, targets: list[str], framework: str, icons: bool = False) -> dict[Path, str]:
    """Fill a design skeleton for `build.py new design`: one wireframe artboard per target, the framework pick, and
    with icons an `app-icon` artboard with stub layers. A mobile target makes its screen the entry of a flow layout.
    Returns {file: stub text} to write beside the doc."""
    board = board_of(doc)
    board["targets"] = targets
    if "mobile" in targets:
        board["entry"], board["layout"] = ["mobile"], "flow"
    board["artboards"], stubs = [], {}
    for t in targets:
        a = {"id": t, "title": f"<<{t.capitalize()} screen: what it shows>>", "device": TARGET_DEVICES[t],
             "fidelity": "wireframe"}
        board["artboards"].append(a)
        stubs[out.parent / screen_rel(out, a)] = stub_screen(a)
    if icons:
        a = {"id": "app-icon", "title": "App icon", "device": "icons", "fidelity": "wireframe",
             "icon": {"name": "<<App name>>", "bg": "#2563eb"}}
        board["artboards"].append(a)
        folder = icon_dir(out, a)
        stubs[folder / "fg.svg"] = STUB_ICON_LAYER.format(fill="#ffffff")
        stubs[folder / "mono.svg"] = STUB_ICON_LAYER.format(fill="#000000")
    if framework != "auto":
        item = _item(doc, "brief", "framework").obj
        if framework not in BUILTIN_FRAMEWORKS:
            try:   # the label `serve.py add-framework` wrote (e.g. "Tailwind + daisyUI"), else the name
                label = str(json.loads((frameworks_dir() / framework / "manifest.json").read_text(encoding="utf-8"))
                            .get("label") or framework)[:MAX_CHOICE_LABEL]
            except (OSError, ValueError, AttributeError):
                label = framework
            board["frameworks"] = [{"id": framework, "label": label, "store": framework}]
            item["choices"].insert(0, {"id": framework, "label": label})
        elif not any(c["id"] == framework for c in item["choices"]):
            item["choices"].insert(0, {"id": framework, "label": BUILTIN_FRAMEWORKS[framework]})
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
    if kind == "link" and parts and parts[0]:
        aid, _, sel = path.partition("/")
        arts = _board_artboards(doc)
        a, i = _find(arts, lambda x: x.get("id") == aid, f"artboard '{aid}'")
        if is_icons(a):
            raise PatchError(f"'{aid}' is an icons artboard: it has no links")
        if is_live(a):
            raise PatchError(f"'{aid}' is a live page: its links are the site's own")
        return Target(a, arts, i, "link", sel)
    if kind == "field" and len(parts) == 3:
        return _field(doc, *parts)
    if kind == "section" and len(parts) == 2:   # a storelisting's device section: section:<platform>/<row>
        lb = listing.listing_of(doc)
        if lb is None:
            raise PatchError(f"bad key '{key}': section:<id> names a section; section:<platform>/<row> is a storelisting's")
        rules = listing.load_rules()
        if parts[0] not in (lb.get("platforms") or []) or parts[1] not in [*(r["id"] for r in rules["rows"]), "shared", "text"]:
            raise PatchError(f"no section '{path}': <platform>/<row>, platforms {', '.join(lb.get('platforms') or [])}, "
                             f"rows {', '.join(r['id'] for r in rules['rows'])}, shared or text")
        return Target(lb, None, None, "lsection", path)
    if kind == "variant" and len(parts) == 1:
        lb = listing.listing_of(doc)
        vs = (lb or {}).get("variants")
        if not isinstance(vs, list):
            raise PatchError("no listing.variants in this doc: variant: keys are a storelisting's")
        v, i = _find(vs, lambda x: x.get("id") == path, f"variant '{path}'")
        return Target(v, vs, i, "variant")
    if kind == "brand" and len(parts) == 1:
        lb = listing.listing_of(doc)
        if lb is None or (lb.get("id") or "main") != path:
            raise PatchError(f"no listing '{path}'" + (f" (this doc's listing is '{lb.get('id') or 'main'}')" if lb else ": brand: keys are a storelisting's"))
        if not isinstance(lb.get("brand"), dict):
            lb["brand"] = {}
        return Target(lb["brand"], lb, "brand", "brand")
    if kind == "layout" and len(parts) == 1:
        b = board_of(doc)
        if not b or b.get("id") != path:
            raise PatchError(f"no board '{path}'" + (f" (this doc's board is '{b.get('id')}')" if b else ""))
        return Target(b, None, None, "layout")
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
             **({"device": "page"} if doc_type(doc.get("meta") or {}) == "website"   # a website holds pages only
                else {"w": int(size.group(1)), "h": int(size.group(2))} if size else {"device": dev}),
             "fidelity": "wireframe", "x": x, "y": y}
        arts.append(a)
        return Target(a, arts, len(arts) - 1, "frame")
    raise PatchError(f"unknown key '{key}': see `build.py --help` for the key forms")


def _field(doc: dict, loc: str, group: str, field: str) -> Target:
    """field:<locale>/<platform>/<field> (a store text) or field:<locale>/strings/<key> (a caption string) on a
    storelisting: the field in listing.text[<locale>][<platform>] or listing.strings[<locale>]. Its parent is that
    object (made when missing), so --set <field>=… writes it and --delete drops it."""
    lb = listing.listing_of(doc)
    if lb is None:
        raise PatchError("no listing block in this doc: field: keys are a storelisting's")
    if loc not in (lb.get("locales") or []):
        raise PatchError(f"no locale '{loc}' in listing.locales ({', '.join(lb.get('locales') or [])})")
    if group == "strings":
        if not listing.STRING_KEY.match(field):
            raise PatchError(f"bad caption key '{field}': letters, digits, - and _ joined by dots")
        holder = lb.setdefault("strings", {}).setdefault(loc, {})
    else:
        if group not in (lb.get("platforms") or []):
            raise PatchError(f"no platform '{group}' in listing.platforms ({', '.join(lb.get('platforms') or [])}); "
                             "or strings for a caption")
        if field not in listing.text_rules(listing.load_rules(), group):
            raise PatchError(f"no {group} text field '{field}': {', '.join(listing.text_rules(listing.load_rules(), group))}")
        holder = lb.setdefault("text", {}).setdefault(loc, {}).setdefault(group, {})
    return Target(holder, holder, field, "field")


EL_NAMES = re.compile(r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*$")   # an el: path of data-bd names, else a CSS path
FRAME_KEY = re.compile(r"^([a-z0-9-]+|\d+x\d+)@(-?\d+),(-?\d+)$")


def _board_artboards(doc: dict) -> list:
    b = board_of(doc)
    if not b or not isinstance(b.get("artboards"), list):
        raise PatchError("no board block with artboards in this doc")
    return b["artboards"]


def source_lines(doc: dict, a: dict, sel: str, doc_path: Path) -> list[str]:
    """A website page's source hints for `patch` to print: the page's, then the section sel falls in (its key path
    starts with the section's selector, or names its data-bd; on a page with a screen file, the innermost section whose
    `[data-bd="…"]` or `#id` selector names an ancestor of the element), else every section's. [] on other docs."""
    if doc_type(doc.get("meta") or {}) != "website":
        return []
    root = site_root(board_of(doc), doc_path)
    out = [f"in {root}"] if root else []
    if sources_of(a):
        out.append(f"source: {', '.join(sources_of(a))}")
    secs = [s for s in a.get("sections") or [] if isinstance(s, dict) and isinstance(s.get("sel"), str)]
    names = sel.split("/") if EL_NAMES.match(sel) else []
    hit = [s for s in secs if sel and (sel == s["sel"] or sel.startswith((s["sel"] + ">", s["sel"] + " "))
                                       or any(s["sel"] == f'[data-bd="{n}"]' for n in names))]
    if sel and not hit and not is_live(a):
        tree = _ScreenTree(_read_text(Path(doc_path).parent / screen_rel(doc_path, a)) or "")
        i = tree.find(sel)
        while i is not None and not hit:
            at = tree.els[i]["attrs"]
            hit = [s for s in secs if (at.get("data-bd") and s["sel"] == f'[data-bd="{at["data-bd"]}"]')
                   or (at.get("id") and s["sel"] == f'#{at["id"]}')]
            i = tree.els[i]["parent"]
    for s in hit[-1:] or secs:
        if sources_of(s):
            out.append(f"section {s.get('id')} ({s['sel']}): {', '.join(sources_of(s))}")
    return out if len(out) > bool(root) else []


VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
CSS_STEP = re.compile(r"^([a-z][a-z0-9-]*):nth-of-type\((\d+)\)$")


class _ScreenTree(HTMLParser):
    """A screen fragment's elements with their source offsets, for rewriting one element in place. Each element:
    {tag, attrs, start, tag_end (offset after its start tag), close, close_end (its end tag's span; None without
    one), parent (index or None), text (its descendants' text), void (a void or self-closed tag)}."""
    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=True)
        self.src = text
        self.lines = [0] + [m.end() for m in re.finditer("\n", text)]
        self.els: list[dict] = []
        self._open: list[int] = []
        self.feed(text)
        self.close()

    def _off(self) -> int:
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def handle_starttag(self, tag: str, attrs, void: bool = False) -> None:
        start = self._off()
        raw = self.get_starttag_text() or ""
        void = void or tag in VOID_TAGS
        self.els.append({"tag": tag, "attrs": dict(attrs), "start": start, "tag_end": start + len(raw), "close": None,
                         "close_end": None, "parent": self._open[-1] if self._open else None, "text": "", "void": void})
        if not void:
            self._open.append(len(self.els) - 1)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs, void=True)

    def handle_endtag(self, tag: str) -> None:
        for k in range(len(self._open) - 1, -1, -1):
            if self.els[self._open[k]]["tag"] == tag:
                el = self.els[self._open[k]]
                el["close"] = self._off()
                el["close_end"] = self.src.find(">", el["close"]) + 1
                del self._open[k:]
                return

    def handle_data(self, data: str) -> None:
        for k in self._open:
            self.els[k]["text"] += data

    def children(self, parent: int | None) -> list[int]:
        return [i for i, e in enumerate(self.els) if e["parent"] == parent]

    def named(self, name: str) -> list[int]:
        return [i for i, e in enumerate(self.els) if e["attrs"].get("data-bd") == name]

    def find(self, sel: str) -> int | None:
        """The one element sel names: data-bd names joined by '/' (each inside the one before), or the inspector's
        CSS path from body or a named element ('[data-bd="x"]>li:nth-of-type(2)'). None when it names none or several."""
        if EL_NAMES.match(sel):
            names = sel.split("/")
            hits = []
            for i in self.named(names[-1]):
                want, p = names[:-1], self.els[i]["parent"]
                while want and p is not None:
                    if self.els[p]["attrs"].get("data-bd") == want[-1]:
                        want.pop()
                    p = self.els[p]["parent"]
                if not want:
                    hits.append(i)
            return hits[0] if len(hits) == 1 else None
        anchor, *steps = sel.split(">")
        m = re.fullmatch(r'\[data-bd="([A-Za-z0-9_-]+)"\]', anchor)
        if anchor == "body":
            cur = None
        elif m and len(self.named(m.group(1))) == 1:
            cur = self.named(m.group(1))[0]
        else:
            return None
        for step in steps:
            s = CSS_STEP.match(step)
            same = [i for i in self.children(cur) if s and self.els[i]["tag"] == s.group(1)]
            if not s or int(s.group(2)) > len(same) or int(s.group(2)) < 1:
                return None
            cur = same[int(s.group(2)) - 1]
        return cur


ATTR_SPAN = re.compile(r"""(\s+)([^\s"'>/=]+)(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?""")


def _set_attr(tag_text: str, name: str, value: str | None) -> str:
    """A start tag's text with one attribute set (value None: removed); the rest stays byte for byte."""
    head = re.match(r"<[^\s/>]+", tag_text).end()
    pos, spans = head, []
    while True:
        m = ATTR_SPAN.match(tag_text, pos)
        if not m:
            break
        spans.append((m.group(2).lower(), m.start(), m.end()))
        pos = m.end()
    new = "" if value is None else f' {name}="{escape_html(value, quote=True)}"'
    hit = next((s for s in spans if s[0] == name), None)
    if hit:
        return tag_text[:hit[1]] + new + tag_text[hit[2]:]
    end = len(tag_text) - (2 if tag_text.endswith("/>") else 1)
    body = tag_text[:end]
    return body.rstrip() + new + body[len(body.rstrip()):] + tag_text[end:]


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:32].strip("-")


def _free_name(tree: _ScreenTree, base: str) -> str:
    name, n = base, 2
    while tree.named(name):
        name, n = f"{base}-{n}", n + 1
    return name


def nav_value(kind: str, to: str | None) -> str:
    return "back" if kind == "back" else to if kind == "push" else f"{kind}:{to}"


def link_patch(text: str, sel: str, sets: list[str], delete: bool, art_ids: set[str]) -> tuple[str, str]:
    """A screen's text with one link changed in place: the element sel names gets data-nav and data-nav-label as
    --set to=, kind=, label= say (label null or empty: removed), or loses both (delete; a hidden, empty gesture
    element goes whole). An element without data-bd is named first, from the label, else its text. A name no element
    has, or no name, adds a hidden gesture element inside the screen's root (named from the label). Returns (text,
    the element's data-bd name)."""
    fields: dict[str, str | None] = {}
    for s in sets:
        k, eq, v = s.partition("=")
        if not eq or k not in ("to", "kind", "label"):
            raise PatchError(f"--set '{s}': a link takes to=<artboard>, kind=<{'|'.join(NAV_KINDS)}> and label=<text>")
        p = _value(v.strip())   # a JSON string ('label="Tap Start"') reads as its text; any other value as written
        fields[k] = None if p in (None, "") else p.strip() if isinstance(p, str) else v.strip()
    tree = _ScreenTree(text)
    i = tree.find(sel) if sel else None
    if i is None and sel and not BD_NAME.match(sel):
        raise PatchError(f"no element '{sel}' in the screen (a data-bd name, names joined by '/', or a CSS path)")
    if i is None and sel and tree.named(sel.split("/")[-1]):
        raise PatchError(f"'{sel}' names no single element: use the inspector's CSS path")
    el = tree.els[i] if i is not None else None
    cur = parse_nav(el["attrs"].get("data-nav") or "") if el and "data-nav" in el["attrs"] else None
    cur = cur if isinstance(cur, tuple) else None
    if delete:
        if not el or "data-nav" not in el["attrs"]:
            raise PatchError(f"no link on '{sel}' to delete")
        if "hidden" in el["attrs"] and el["close"] is not None and not el["text"].strip() and \
                tree.children(i) == []:
            start, end = el["start"], el["close_end"]
            ls = text.rfind("\n", 0, start) + 1
            if not text[ls:start].strip() and text[end:].startswith("\n"):
                start, end = ls, end + 1
            return text[:start] + text[end:], el["attrs"].get("data-bd") or ""
        tag = _set_attr(_set_attr(text[el["start"]:el["tag_end"]], "data-nav", None), "data-nav-label", None)
        return text[:el["start"]] + tag + text[el["tag_end"]:], el["attrs"].get("data-bd") or ""
    if not fields:
        raise PatchError("give --set to=, kind= or label=, or --delete")
    kind = fields.get("kind") or (cur[0] if cur and not (cur[0] == "back" and fields.get("to")) else "push")
    if kind not in NAV_KINDS:
        raise PatchError(f"kind '{kind}' not in {', '.join(NAV_KINDS)}")
    to = None if kind == "back" else fields.get("to") or (cur[1] if cur else None)
    if kind != "back" and not to:
        raise PatchError("a new link needs its target: --set to=<artboard>")
    if to is not None and to not in art_ids:
        raise PatchError(f"no artboard '{to}' on this board")
    label = fields["label"] if "label" in fields else (el["attrs"].get("data-nav-label") if el else None)
    if el is None:   # a gesture link: a hidden named element inside the root
        name = _free_name(tree, sel or _slug(label or "") or "gesture")
        node = f'<i hidden data-bd="{name}" data-nav="{nav_value(kind, to)}"' + \
               (f' data-nav-label="{escape_html(label, quote=True)}"' if label else "") + "></i>"
        root = next((e for e in tree.els if e["parent"] is None and e["close"] is not None
                     and e["tag"] not in ("style", "script", "template")), None)
        if root is None:
            return text + ("" if text.endswith("\n") or not text else "\n") + node + "\n", name
        ls = text.rfind("\n", 0, root["close"]) + 1
        indent = re.match(r"[ \t]*", text[ls:]).group(0)
        if text[ls:root["close"]].strip():   # the end tag shares its line: put the element just before it
            return text[:root["close"]] + node + text[root["close"]:], name
        kids = tree.children(tree.els.index(root))
        inner = indent + "  "
        if kids:
            ks = text.rfind("\n", 0, tree.els[kids[0]]["start"]) + 1
            inner = re.match(r"[ \t]*", text[ks:]).group(0) or inner
        return text[:ls] + inner + node + "\n" + text[ls:], name
    tag = text[el["start"]:el["tag_end"]]
    name = el["attrs"].get("data-bd")
    if not name:
        name = _free_name(tree, _slug(label or "") or _slug(el["text"]) or el["tag"])
        tag = _set_attr(tag, "data-bd", name)
    tag = _set_attr(tag, "data-nav", nav_value(kind, to))
    if label != el["attrs"].get("data-nav-label"):
        tag = _set_attr(tag, "data-nav-label", label)
    return text[:el["start"]] + tag + text[el["tag_end"]:], name


def element_patch(text: str, sel: str, sets: list[str], delete: bool) -> str:
    """A screen's text with one element rewritten in place, every other byte kept: --set text=<JSON string> replaces
    its one text run (the text between its tags beside children without text, such as icons; the run's surrounding
    whitespace stays), HTML-escaped; delete removes it from its start tag to its end tag, with its line when it is
    alone on it. A selector that finds no element or several, an element with no text run or several, or with text in
    a child element, is an error."""
    tree = _ScreenTree(text)
    i = tree.find(sel)
    if i is None:
        raise PatchError(f"no single element '{sel}' in the screen (a data-bd name, names joined by '/', or the "
                         "inspector's CSS path)")
    el = tree.els[i]
    if delete:
        if el["close"] is None and not el["void"]:
            raise PatchError(f"'{sel}' has no end tag: close it, then delete it")
        start, end = el["start"], el["close_end"] if el["close"] is not None else el["tag_end"]
        ls, le = text.rfind("\n", 0, start) + 1, text.find("\n", end)
        le = len(text) if le < 0 else le
        if not text[ls:start].strip() and not text[end:le].strip():
            start, end = ls, min(le + 1, len(text))
        return text[:start] + text[end:]
    value = None
    for s in sets:
        k, eq, v = s.partition("=")
        if not eq or k != "text":
            raise PatchError(f"--set '{s}': an el: key takes --set text=<JSON string>, or --delete")
        p = _value(v)   # a JSON string ('text="Start run"') reads as its text; any other value as written
        value = (p if isinstance(p, str) else v).strip()
    if not value:
        raise PatchError("the text is empty: --delete removes the element")
    if el["close"] is None:
        raise PatchError(f"'{sel}' ({el['tag']}) holds no text: comment on it instead")
    kids = tree.children(i)
    if any(tree.els[k]["text"].strip() for k in kids):
        raise PatchError(f"'{sel}' has text in a child element: set that element's text (its own el: key)")
    gaps, pos = [], el["tag_end"]
    for k in kids:
        c = tree.els[k]
        gaps.append((pos, c["start"]))
        pos = c["close_end"] if c["close"] is not None else c["tag_end"]
    gaps.append((pos, el["close"]))
    runs = [(a, b) for a, b in gaps if text[a:b].strip()]
    if len(runs) > 1 or any("<" in text[a:b] for a, b in runs):
        raise PatchError(f"'{sel}' has {len(runs)} text runs: set the text of one element inside it")
    new = escape_html(value, quote=False)
    if not runs:
        if kids:
            raise PatchError(f"'{sel}' has no text run beside its children: edit the screen file")
        return text[:el["tag_end"]] + new + text[el["close"]:]
    a, b = runs[0]
    seg = text[a:b]
    return text[:a + len(seg) - len(seg.lstrip())] + new + text[a + len(seg.rstrip()):]


def set_positions(board: dict, fields) -> list[str]:
    """Set x, y on the artboards {artboard id: [x, y] (null: unset, the board places it)} names; the ids changed."""
    if not isinstance(fields, dict) or not fields:
        raise PatchError("layout: --json takes {\"<artboard>\": [x, y], …}")
    arts = {a.get("id"): a for a in board.get("artboards") or [] if isinstance(a, dict)}
    for aid, v in fields.items():
        if aid not in arts:
            raise PatchError(f"no artboard '{aid}' on board '{board.get('id')}'")
        ok = isinstance(v, list) and len(v) == 2 and all(isinstance(n, (int, float)) and not isinstance(n, bool)
                                                         and math.isfinite(n) and abs(n) <= 100000 for n in v)
        if v is not None and not ok:
            raise PatchError(f"'{aid}': {_shown(v)} is no [x, y] of numbers within ±100000 (null unsets)")
    for aid, v in fields.items():
        if v is None:
            arts[aid].pop("x", None)
            arts[aid].pop("y", None)
        else:
            arts[aid]["x"], arts[aid]["y"] = (int(n) if float(n).is_integer() else n for n in v)
    return list(fields)


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
        if isinstance(t.parent, dict) and t.key not in t.parent:
            raise PatchError(f"nothing to delete: no '{t.key}' there")
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
    ap.add_argument("--resolves", action="append", default=[], metavar="ID",
                    help="a reader comment this revision addresses, by the id the reply shows (repeat for more)")
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
    on_screen = t.kind in ("artboard", "element", "link")
    if a.html is not None and t.kind not in ("artboard", "element"):
        ap.error("--html takes an artboard: or el: key")
    if t.kind == "link" and (a.json is not None or a.append is not None):
        ap.error("a link: key takes --set to=<artboard> / kind=<kind> / label=<text>, or --delete")
    if t.kind == "layout" and (a.set or a.append is not None or a.delete or a.json is None):
        ap.error("a layout: key takes --json '{\"<artboard>\": [x, y], …}'")
    if a.html is not None and is_icons(t.obj):
        ap.error("an icons artboard has no screen file: edit its layers in place, then patch it with --change")
    if a.html is not None and is_live(t.obj):
        ap.error("a live page has no screen file: edit the site's source (patch prints it), then patch it with --change")
    # an el: key changes the element in its screen file, never the artboard: only its text, or the element itself
    if t.kind == "element" and (a.json is not None or a.append is not None or any(s.partition("=")[0] != "text" for s in a.set)):
        ap.error("an el: key takes --set 'text=\"<text>\"' or --delete (--html replaces the whole screen file)")
    if t.kind == "element" and (a.set or a.delete) and (is_icons(t.obj) or is_live(t.obj) or listing.is_image_shot(t.obj)):
        for line in source_lines(doc, t.obj, a.key.partition(":")[2].partition("/")[2], a.doc):
            print(line, file=sys.stderr)
        ap.error("an icons artboard has no screen file: edit its layers in place, then patch it with --change" if is_icons(t.obj)
                 else "a live page has no screen file: edit the site's source, then patch it with --change" if is_live(t.obj)
                 else "an uploaded shot is a PNG: it has no element to change")
    if not ops and t.kind == "field":
        _, _, path = a.key.partition(":")
        loc, group, field = path.split("/", 2)
        v = t.obj.get(field)
        if group == "strings":
            print(f"{loc} caption {field}: {json.dumps(v, ensure_ascii=False) if v is not None else 'none (the shots show the default locale)'}")
        else:
            r = listing.text_rules(listing.load_rules(), group)[field]
            n = listing.text_count(v, r["unit"]) if isinstance(v, str) else 0
            print(f"{loc} {group} {r['label']}: {json.dumps(v, ensure_ascii=False) if v is not None else 'none'} "
                  f"({n} / {r['limit']} {r['unit']})")
        print(f"change it: build.py patch {a.doc} {shlex.quote(a.key)} --set {shlex.quote(field + '=<text>')}, or --delete")
        return 0
    if t.kind == "lsection":
        if ops:
            ap.error("a section: key prints the section: change its shots by their artboard: keys, its sets' order and "
                     "the sections shown by the listing's block: key")
        for line in listing.section_lines(doc, a.doc, t.selector):
            print(line)
        return 0
    if not ops and t.kind != "frame" and not (on_screen and a.change):
        if not on_screen:
            ap.error("give --set, --json, --append or --delete")
        # where to make the change: the screen file (an icon: its layers; a live page: its URL), the element in it, and
        # on a website the source hints
        if is_icons(t.obj):
            layers = icon_layers(doc, a.doc).get(t.obj["id"], {})
            tile = a.key.partition("/")[2].split("/")[-1] if t.kind == "element" else ""
            used = icon_tile_layers(tile, layers, t.obj)
            print(f"{icon_dir(a.doc, t.obj)}/  layers: {', '.join(used)}" + (f"  (what tile {tile} is built from)"
                                                                            if tile in ICON_TILES else ""))
        else:
            sel = " ".join(f'[data-bd="{n}"]' for n in t.selector.split("/")) if t.kind == "link" and \
                EL_NAMES.match(t.selector or "") else t.selector
            image = listing.is_image_shot(t.obj)   # a storelisting's uploaded shot: a PNG, no element to edit
            where = f"live page {t.obj['url']}" if is_live(t.obj) else f"{a.doc.parent / t.obj['src']}" \
                if image else f"{a.doc.parent / screen_rel(a.doc, t.obj)}"
            print(where + (f"  {sel}" if sel and not image else ""))
        for line in source_lines(doc, t.obj, a.key.partition(":")[2].partition("/")[2] if t.kind == "element" else "", a.doc):
            print(line)
        for line in listing.reshoot_lines(doc, t.obj, a.doc, str(a.doc)) if listing.listing_of(doc) else []:
            print(line)
        if listing.is_image_shot(t.obj):
            return 0
        if is_live(t.obj):
            print(f"edit the source, then: build.py patch {a.doc} {shlex.quote(a.key)} --change '<what changed>'")
            return 0
        if t.kind == "link":
            tree = _ScreenTree(_read_text(a.doc.parent / screen_rel(a.doc, t.obj)) or "")
            i = tree.find(t.selector) if t.selector else None
            at = tree.els[i]["attrs"] if i is not None else None
            print(" ".join(f'{k}="{at[k]}"' for k in ("data-nav", "data-nav-label") if k in at)
                  if at and "data-nav" in at else "no link there yet" if at is not None
                  else "no such element: --set adds a hidden gesture link")
            print(f"change it: build.py patch {a.doc} {shlex.quote(a.key)} --set to=<artboard> --set kind=<kind> "
                  "--set label=<text>, or --delete")
            return 0
        how = "; or set its text with --set 'text=\"<text>\"', or remove it with --delete" if t.kind == "element" else ""
        print(f"edit it in place, then: build.py patch {a.doc} {shlex.quote(a.key)} --change '<what changed>'{how}")
        return 0
    html = None
    if a.html is not None:
        try:
            html = sys.stdin.read() if a.html == "-" else Path(a.html).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"cannot read {a.html}: {e}", file=sys.stderr)
            return 2
    screen_text = None   # a link: or el: key's new screen text
    try:
        if t.kind in ("link", "element") and (a.set or a.delete):
            old_text = _read_text(a.doc.parent / screen_rel(a.doc, t.obj))
            if old_text is None:
                raise PatchError(f"cannot read {a.doc.parent / screen_rel(a.doc, t.obj)}")
            if t.kind == "element":
                screen_text = element_patch(old_text, a.key.partition(":")[2].partition("/")[2], a.set, a.delete)
            else:
                screen_text, name = link_patch(old_text, t.selector, a.set, a.delete,
                                               {x.get("id") for x in _board_artboards(doc) if isinstance(x, dict)})
                t.selector = f'[data-bd="{name}"]' if name else t.selector
        elif t.kind == "layout":
            set_positions(t.obj, _value(a.json))
        elif t.kind not in ("link", "element"):
            apply_patch(t, a.set, a.json, a.append, a.delete)
            if t.kind == "field":   # a reader's text replaces the string as human-written: no MT mark
                loc, group, field = a.key.partition(":")[2].split("/", 2)
                listing.mark_human(listing.listing_of(doc), loc, f"{group}.{field}")
        meta = doc.setdefault("meta", {})
        rev0 = str(meta.get("rev") or "")
        rev1 = rev0 if a.no_bump else next_rev(rev0)
    except PatchError as e:
        print(f"patch: {e}", file=sys.stderr)
        return 2
    resolves = [x.strip().strip("()`").strip() for x in a.resolves]
    if a.no_bump:
        if a.change:
            doc["changes"] = list(doc.get("changes") or []) + a.change
        if resolves:
            doc["resolves"] = list(dict.fromkeys(list(doc.get("resolves") or []) + resolves))
    else:
        meta.update(rev=rev1, date=dt.date.today().isoformat())
        doc["changes"] = a.change or [f"Updated `{a.key}`."]
        if resolves:
            doc["resolves"] = list(dict.fromkeys(resolves))
        else:
            doc.pop("resolves", None)
    # screen files change before validate, which lints them; undone when the patch fails
    written: list[tuple[Path, str | None]] = []
    screen = None
    if t.kind in ("artboard", "element", "frame", "link") and not (a.delete and t.kind == "artboard") and not is_icons(t.obj) \
            and not is_live(t.obj):
        screen = a.doc.parent / screen_rel(a.doc, t.obj)
    if screen and (html is not None or screen_text is not None or (t.kind == "frame" and not screen.exists())):
        written.append((screen, _read_text(screen) if screen.exists() else None))
        screen.parent.mkdir(parents=True, exist_ok=True)
        screen.write_text(html if html is not None else screen_text if screen_text is not None else stub_screen(t.obj),
                          encoding="utf-8")

    def undo() -> None:
        for f, old in written:
            if old is None:
                f.unlink(missing_ok=True)
            else:
                f.write_text(old, encoding="utf-8")
    rep = validate(doc, a.doc)
    # a storelisting's store-rule errors block a patch only when it brings them: one fix at a time stays possible
    had = set(validate(before, a.doc, write_cache=False).store) if rep.store else set()
    bad = [e for e in rep.errors if e not in rep.store or e not in had]
    if bad:
        undo()
        for line in bad:
            print(line, file=sys.stderr)
        print(f"patch: {len(bad)} error(s); {a.doc} not written", file=sys.stderr)
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
    for line in rep.warnings + rep.store:
        if line not in old:
            print(line, file=sys.stderr)
    if rep.store:
        print(f"{len(rep.store)} store-rule error(s) remain: build.py {shlex.quote(str(a.doc))} --check lists them", file=sys.stderr)
    # a live page shows the site as it is now: the revision this patch replaces keeps how it looked only in a snapshot
    if rev0 and rev0 != rev1:
        shot = snapshot_index(a.doc).get(rev0, {})
        missing = [p for p in live_pages(before) if p not in shot]
        if missing:
            print(f"WARN  rev {rev0} has no snapshot of live page{'s' if len(missing) > 1 else ''} {', '.join(missing)}: "
                  f"the doc shows a placeholder for it from now on. Before editing the site for the next change, record "
                  f"the current rev: serve.py snapshot {shlex.quote(str(a.doc))} (sending feedback from the page records "
                  f"the pages it shows)", file=sys.stderr)
    print(f"rev {rev0 or '-'} → {rev1}; {a.key} {'deleted' if a.delete else 'added' if t.kind == 'frame' else 'updated'}")
    if screen:
        print(f"screen: {screen}" + (f"  {t.selector}" if t.selector else "")
              + ("  (a stub: write the requested screen there)" if t.kind == "frame" and written else ""))
    elif a.delete and t.kind == "artboard" and not is_live(t.obj):
        left = f"{icon_dir(a.doc, t.obj)}/" if is_icons(t.obj) else a.doc.parent / screen_rel(a.doc, t.obj)
        print(f"left {left}: delete it if nothing uses it (the history keeps its text)")
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
    if argv[:1] == ["l10n"]:
        return cmd_l10n(argv[1:])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("doc", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="also write a standalone HTML file (for sharing; serve.py renders the JSON directly)")
    ap.add_argument("--deck", type=Path, metavar="OUT", help="presentation only: also write the deck as one HTML file that "
                    "plays its slides offline (Export to… HTML) or, as OUT.pdf, a PDF of one 16:9 page per slide (Export "
                    "to… PDF; needs Chrome or Chromium, BLUEDOC_CHROME)")
    ap.add_argument("--listing", type=Path, metavar="OUT", help="storelisting only: also write the listing as OUT.zip, the "
                    "fastlane layout of every shot and asset at its store size with manifest.json, OUT.pdf, the listing "
                    "for review, or OUT.html, one file with both platform pages (zip and pdf need Chrome, BLUEDOC_CHROME)")
    ap.add_argument("--format", choices=("html", "pdf", "zip"), help="--deck's or --listing's format (default: OUT's extension)")
    ap.add_argument("--platform", help="--listing's ZIP: one platform only (play, appstore)")
    ap.add_argument("--locale", help="--listing's ZIP: one locale only")
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
    kind = doc_type(doc.get("meta") if isinstance(doc, dict) and isinstance(doc.get("meta"), dict) else {})
    if a.format and not (a.deck or a.listing):
        ap.error("--format goes with --deck or --listing")
    if (a.platform or a.locale) and not a.listing:
        ap.error("--platform and --locale go with --listing")
    if a.deck and kind != "presentation":
        print(f"--deck: only a presentation exports as a deck, not a doc of type {kind} ({a.doc})", file=sys.stderr)
        return 2
    if a.listing and kind != "storelisting":
        print(f"--listing: only a storelisting exports as a listing, not a doc of type {kind} ({a.doc})", file=sys.stderr)
        return 2
    suffix = (a.deck or a.listing or Path()).suffix.lower()
    fmt = a.format or ("pdf" if suffix == ".pdf" else "html" if suffix in (".html", ".htm") or a.deck else "zip")
    if a.deck and fmt == "zip":
        ap.error("--deck writes html or pdf")
    if a.listing and fmt != "zip" and (a.platform or a.locale):
        ap.error("--platform and --locale narrow the ZIP only")
    chrome = _serve().find_chrome() if fmt in ("pdf", "zip") and (a.deck or a.listing) else None
    if (a.deck or a.listing) and fmt in ("pdf", "zip") and not chrome:
        print(f"--{'deck' if a.deck else 'listing'}: {_serve().DECK_PDF_NEEDS if a.deck else _serve().LISTING_NEEDS}", file=sys.stderr)
        return 1
    rep = validate(doc, a.doc, write_cache=not a.check)
    for line in rep.errors + rep.warnings:
        print(line, file=sys.stderr)
    print(f"{len(rep.errors)} error(s), {len(rep.warnings)} warning(s)", file=sys.stderr)
    # a storelisting's store-rule errors fail the build (exit 1) but leave it recordable and exportable for review
    if rep.blocking or (a.strict and rep.warnings) or (rep.errors and a.check):
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
    if a.deck:
        serve = _serve()
        try:
            deck = serve.deck_html(doc, a.doc)
        except serve.DeckError as e:
            print(f"--deck: {e}", file=sys.stderr)
            return 1
        if fmt == "pdf":
            try:
                deck = serve.deck_pdf(deck, chrome)
            except (OSError, RuntimeError) as e:
                print(f"--deck: Chrome couldn't print the deck: {e}", file=sys.stderr)
                return 1
        a.deck.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(deck, bytes):
            a.deck.write_bytes(deck)
        else:
            a.deck.write_text(deck, encoding="utf-8")
        print(f"wrote {a.deck} ({a.deck.stat().st_size // 1024} KB, {len(serve.deck_slides(doc))} slides)", file=sys.stderr)
    if a.listing:
        serve = _serve()
        a.listing.parent.mkdir(parents=True, exist_ok=True)
        try:
            if fmt == "zip":
                tmp = a.listing.with_name(a.listing.name + ".part")
                try:
                    m = serve.listing_zip(doc, a.doc, tmp, chrome, platform=a.platform, locale=a.locale)
                    os.replace(tmp, a.listing)
                finally:
                    tmp.unlink(missing_ok=True)
                pngs = [f for f in m["files"] if f["path"].endswith(".png")]
                what = f"{len(pngs)} PNGs, {len(m['files']) - len(pngs)} text files, manifest.json"
            else:
                html = serve.listing_html(doc, a.doc)
                if fmt == "pdf":
                    a.listing.write_bytes(serve.listing_pdf(html, chrome))
                else:
                    a.listing.write_text(html, encoding="utf-8")
                what = fmt.upper()
        except serve.ListingError as e:
            print(f"--listing: {e}", file=sys.stderr)
            return 1
        except (OSError, RuntimeError) as e:
            print(f"--listing: Chrome couldn't render the listing: {e}", file=sys.stderr)
            return 1
        for w in serve.listing_warnings(doc, fmt):
            print(f"WARN  --listing: {w}", file=sys.stderr)
        print(f"wrote {a.listing} ({a.listing.stat().st_size // 1024} KB: {what})", file=sys.stderr)
    if not a.out and not a.deck and not a.listing:
        print(f"view: python3 {HERE / 'serve.py'} open {a.doc}", file=sys.stderr)
    return 1 if rep.errors else 0


def cmd_l10n(argv: list[str]) -> int:
    """`build.py l10n`: a storelisting's translations (listing.l10n_*). --export prints, as JSON, the strings a
    locale lacks or whose default-locale text changed since its translation, each with its limit and the shots that
    show it. --import merges a JSON file of {MT key: text}, refusing it whole when a string is over its limit (with
    its count); --mt marks them machine-translated. --accept clears the MT marks of the keys the reader accepted. An
    import or accept bumps the rev and records it, as `patch` does."""
    ap = argparse.ArgumentParser(prog="build.py l10n", description=cmd_l10n.__doc__)
    ap.add_argument("doc", type=Path)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--export", metavar="LOCALE", help="print the strings LOCALE lacks or whose source changed, as JSON")
    g.add_argument("--import", dest="imp", nargs=2, metavar=("LOCALE", "FILE"), help="merge FILE's {key: text} into LOCALE")
    g.add_argument("--accept", nargs="+", metavar="LOCALE KEY", help="clear the MT marks of these keys in LOCALE")
    ap.add_argument("--mt", action="store_true", help="--import: the strings are machine-translated (MT badges until accepted)")
    ap.add_argument("--change", action="append", default=[], metavar="LINE", help="a line for `changes` (repeat for more)")
    ap.add_argument("--resolves", action="append", default=[], metavar="ID", help="a reader comment or draft this addresses")
    ap.add_argument("--no-bump", action="store_true", help="keep meta.rev: update the current revision in place")
    a = ap.parse_args(argv)
    if a.mt and not a.imp:
        ap.error("--mt goes with --import")
    try:
        raw = a.doc.read_text(encoding="utf-8")
        doc = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot read {a.doc}: {e}", file=sys.stderr)
        return 2
    lb = listing.listing_of(doc)
    if lb is None:
        print("l10n: no listing block: l10n is a storelisting's", file=sys.stderr)
        return 2
    rules = listing.load_rules()
    if a.export:
        try:
            out = listing.l10n_export(doc, a.doc, a.export, rules)
        except ValueError as e:
            print(f"l10n: {e}", file=sys.stderr)
            return 2
        print(json.dumps({"doc": str(a.doc), **out}, ensure_ascii=False, indent=1))
        print(f"{len(out['strings'])} string(s) to translate into {a.export}; then: build.py l10n {shlex.quote(str(a.doc))} "
              f"--import {a.export} <file.json> --mt", file=sys.stderr)
        return 0
    before = copy.deepcopy(doc)
    before_screens = read_screens(before, a.doc)
    if a.imp:
        loc, path = a.imp
        try:
            entries = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"cannot read {path}: {e}", file=sys.stderr)
            return 2
        problems = listing.l10n_import(listing.listing_of(doc), loc, entries, rules, mt=a.mt)
        change = f"Imported {len(entries) if isinstance(entries, dict) else 0} {loc} strings" + (" (machine-translated)" if a.mt else "")
    else:
        loc, keys = a.accept[0], a.accept[1:]
        problems = listing.l10n_accept(listing.listing_of(doc), loc, keys)
        change = f"Accepted {len(keys)} machine-translated {loc} string{'' if len(keys) == 1 else 's'}"
    if problems:
        for p in problems:
            print(f"l10n: {p}", file=sys.stderr)
        print(f"l10n: {len(problems)} problem(s); {a.doc} not written", file=sys.stderr)
        return 1
    meta = doc.setdefault("meta", {})
    rev0 = str(meta.get("rev") or "")
    rev1 = rev0 if a.no_bump else next_rev(rev0)
    resolves = [x.strip().strip("()`").strip() for x in a.resolves]
    if a.no_bump:
        doc["changes"] = list(doc.get("changes") or []) + (a.change or [change])
        if resolves:
            doc["resolves"] = list(dict.fromkeys(list(doc.get("resolves") or []) + resolves))
    else:
        meta.update(rev=rev1, date=dt.date.today().isoformat())
        doc["changes"] = a.change or [change]
        if resolves:
            doc["resolves"] = list(dict.fromkeys(resolves))
        else:
            doc.pop("resolves", None)
    rep = validate(doc, a.doc)
    had = set(validate(before, a.doc, write_cache=False).store) if rep.store else set()
    bad = [e for e in rep.errors if e not in rep.store or e not in had]
    if bad:
        for line in bad:
            print(line, file=sys.stderr)
        print(f"l10n: {len(bad)} error(s); {a.doc} not written", file=sys.stderr)
        return 1
    try:
        if rev0 and not a.no_bump:
            sync_history(a.doc, before, keep_screens=True, texts=before_screens)
        write_doc(a.doc, doc, raw)
        sync_history(a.doc, doc)
    except HistoryError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"rev {rev0 or '-'} → {rev1}; {change.lower()[0] + change[1:]}")
    if rep.store:
        print(f"{len(rep.store)} store-rule error(s) remain: build.py {shlex.quote(str(a.doc))} --check lists them", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
