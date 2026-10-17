"""Store listings (`meta.type: "storelisting"`): the rules file and what build.py, serve.py and the page read from it.

assets/store-rules.json holds every set, asset, text field, video, variant limit, locale code, capture target and
screenshot style the two stores take, each naming its source; a rule with `unverified` only ever warns. load_rules()
reads and checks it once. validate_listing() checks a doc's `listing` block and its shot and asset artboards against
it (structure, ids, sets, styles, locales, strings, the Play video URL); page_data() is what the page gets beside the
doc: the rules, each shot's caption keys and the captures it can show.

A shot is an artboard with `device: "shot"` that names the sets it fills. Its screen file is a layout around a UI
slot (kits/shot.css); one file renders at every set's frame size (store px / scale). A shot whose `src` is a PNG under
<stem>.listing/ is a finished image instead (an upload). Captures sit in <stem>.listing/captures/<target>/<locale>/
<shot>.png with captures/captures.json; a capture whose recipe hash is the shot's recipe's is fresh.

Python 3.9+ standard library only; no import of build.py or serve.py (they import this)."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re
import struct
import zlib
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
RULES_PATH = HERE.parent / "assets" / "store-rules.json"
STALE_DAYS = 180   # the rules file's age past which the build warns
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
STRING_KEY = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$")   # a caption string's key, as data-l10n names it
LOCALE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,4})?$")
FONT_FAMILY = re.compile(r"^[^;{}<>\\\"'`]{1,64}$")
PALETTE_ROLES = ("bg", "surface", "accent", "text", "caption")
SHOT_DEVICES = ("shot", "asset", "icons")
IMAGE_TYPES = (".png",)
MAX_PREVIEWS = 3
DOC_SUFFIXES = (".bluedoc.json", ".blueprint.json")
UNVERIFIED_FOR = {"limit", "count", "required", "size", "bytes", "raw", "guide"}   # the checks a rule's `unverified` may name
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


class RulesError(ValueError):
    pass


_rules: tuple[float, dict] | None = None


def load_rules(path: Path = RULES_PATH) -> dict:
    """The rules file, checked (rules_problems), cached by its mtime. RulesError names every problem."""
    global _rules
    mtime = path.stat().st_mtime
    if _rules and _rules[0] == mtime and path == RULES_PATH:
        return _rules[1]
    rules = json.loads(path.read_text(encoding="utf-8"))
    problems = rules_problems(rules)
    if problems:
        raise RulesError(f"{path}: " + "; ".join(problems))
    if path == RULES_PATH:
        _rules = (mtime, rules)
    return rules


def _sizes_ok(v) -> bool:
    return isinstance(v, list) and all(isinstance(p, list) and len(p) == 2 and all(isinstance(n, int) and n > 0 for n in p) for p in v)


def rules_problems(rules: dict) -> list[str]:
    """What's wrong with a rules file: a rule naming no known source, a duplicate id, a set or asset whose authored
    size isn't one it accepts or isn't a whole multiple of its scale, a malformed date or count."""
    out: list[str] = []
    if not isinstance(rules, dict):
        return ["the rules file is no JSON object"]
    try:
        dt.date.fromisoformat(str(rules.get("accessed")))
    except ValueError:
        out.append("`accessed` is no YYYY-MM-DD date")
    sources = rules.get("sources") if isinstance(rules.get("sources"), dict) else {}
    for k, s in sources.items():
        if not isinstance(s, dict) or not isinstance(s.get("title"), str) or not isinstance(s.get("url"), str):
            out.append(f"source {k}: needs title and url")
    platforms = {p.get("id") for p in rules.get("platforms") or [] if isinstance(p, dict)}
    rows = {r.get("id") for r in rules.get("rows") or [] if isinstance(r, dict)}

    def rule(kind: str, r: dict, label: str) -> None:
        srcs = r.get("sources") if "sources" in r else [r.get("source")]
        for s in srcs or [None]:
            if s not in sources:
                out.append(f"{kind} {label}: source {s!r} is not in `sources`")
        if "unverified" in r and not (isinstance(r["unverified"], str) and r["unverified"]):
            out.append(f"{kind} {label}: `unverified` is a note saying what isn't confirmed")
        if "unverifiedFor" in r and not (isinstance(r["unverifiedFor"], list) and r["unverifiedFor"]
                                         and set(r["unverifiedFor"]) <= UNVERIFIED_FOR and "unverified" in r):
            out.append(f"{kind} {label}: `unverifiedFor` lists the checks its note concerns: {', '.join(sorted(UNVERIFIED_FOR))}")
        if "platform" in r and r["platform"] not in platforms:
            out.append(f"{kind} {label}: platform {r['platform']!r} unknown")

    for p in rules.get("platforms") or []:
        rule("platform", p, str(p.get("id")))
    seen: set[str] = set()
    for kind in ("sets", "assets", "text"):
        for r in rules.get(kind) or []:
            rid = str(r.get("id"))
            label = rid
            if rid in seen:
                out.append(f"{kind[:-1] if kind != 'text' else 'text'} {rid}: duplicate id")
            seen.add(rid)
            rule(kind.rstrip("s"), r, label)
            if kind == "text":
                if not (isinstance(r.get("limit"), int) and r["limit"] > 0) or r.get("unit") not in ("chars", "bytes"):
                    out.append(f"text {rid}: needs a positive limit and a unit, chars or bytes")
                if r.get("platform") and not rid.startswith(r["platform"] + "/"):
                    out.append(f"text {rid}: its id must start with its platform")
                continue
            if r.get("platform") and not rid.startswith(r["platform"] + "/"):
                out.append(f"{kind[:-1]} {rid}: its id must start with its platform")
            if kind == "sets" and r.get("row") not in rows:
                out.append(f"set {rid}: row {r.get('row')!r} unknown")
            for k in ("sizes",):
                if k in r and not _sizes_ok(r[k]):
                    out.append(f"{kind[:-1]} {rid}: {k} is a list of [w, h]")
            if "count" in r and not (isinstance(r["count"], list) and len(r["count"]) == 2 and 0 <= r["count"][0] <= r["count"][1]):
                out.append(f"{kind[:-1]} {rid}: count is [min, max]")
            if "from" in r and r.get("required") == "dated":
                try:
                    dt.date.fromisoformat(r["from"])
                except (TypeError, ValueError):
                    out.append(f"set {rid}: `from` is no YYYY-MM-DD date")
            author = r.get("author")
            if author is not None:
                if not _sizes_ok([author]):
                    out.append(f"{kind[:-1]} {rid}: author is [w, h]")
                    continue
                scale = r.get("scale")
                if not (isinstance(scale, int) and scale > 0) or author[0] % scale or author[1] % scale:
                    out.append(f"{kind[:-1]} {rid}: author {author} is not a whole multiple of scale {scale}")
                if size_problem(r, *author):
                    out.append(f"{kind[:-1]} {rid}: author {author} is not a size it accepts ({size_problem(r, *author)})")
            if "ui" in r and not _sizes_ok([r["ui"]]):
                out.append(f"set {rid}: ui is [w, h] in CSS px")
    for v in rules.get("video") or []:
        rule("video", v, str(v.get("platform")))
    for v in rules.get("variants") or []:
        rule("variant", v, str(v.get("kind")))
    for v in rules.get("ads") or []:
        rule("ads", v, str(v.get("id")))
    for v in rules.get("locales") or []:
        rule("locales", v, str(v.get("platform")))
    for v in rules.get("terms") or []:
        rule("terms", v, str(v.get("id")))
    for v in rules.get("targets") or []:
        rule("target", v, str(v.get("id")))
    styles = rules.get("styles") or []
    for v in styles:
        rule("style", v, str(v.get("id")))
        if v.get("axis") not in ("message", "layout") or v.get("grade") not in ("A", "B", "C", "D"):
            out.append(f"style {v.get('id')}: axis message|layout and a grade A-D")
    if sorted(s.get("id") for s in styles) != [f"{a}{n}" for a in ("l", "m") for n in range(1, 6)]:
        out.append("styles: exactly m1-m5 and l1-l5")
    out += brand_rules_problems(rules, sources)
    return out


def rules_age(rules: dict, today: dt.date | None = None) -> int:
    """Days since the rules file's `accessed` date."""
    return ((today or dt.date.today()) - dt.date.fromisoformat(rules["accessed"])).days


def by_id(rules: dict, kind: str) -> dict[str, dict]:
    return {r["id"]: r for r in rules.get(kind) or []}


def platform_of(rule_id: str) -> str:
    return rule_id.partition("/")[0]


def frame_size(rule: dict) -> tuple[int, int]:
    """A set's or asset's frame in CSS px: its authored store size divided by its scale."""
    w, h = rule["author"]
    return w // rule["scale"], h // rule["scale"]


def ui_size(rule: dict) -> tuple[int, int]:
    """The CSS viewport a set's UI slot renders the app's UI at: the set's `ui`, else its frame (a raw set's UI is the
    whole shot)."""
    return tuple(rule["ui"]) if "ui" in rule else frame_size(rule)


def size_problem(rule: dict, w: int, h: int) -> str | None:
    """Why a w × h image doesn't fit a set or asset, or None: an exact size of `sizes` (a portrait size turned too, with
    `landscape`), else `sides` (each side's range) with `maxAspect`, `ratio` or `ratios` and `min`/`max`."""
    if "sizes" in rule:
        ok = [tuple(s) for s in rule["sizes"]] + ([(b, a) for a, b in rule["sizes"]] if rule.get("landscape") else [])
        return None if (w, h) in ok else "one of " + ", ".join(f"{a}×{b}" for a, b in rule["sizes"])
    if "sides" in rule:
        lo, hi = rule["sides"]
        if not (lo <= w <= hi and lo <= h <= hi):
            return f"each side {lo}–{hi} px"
    if "maxAspect" in rule and max(w, h) > rule["maxAspect"] * min(w, h):
        return f"the long side at most {rule['maxAspect']}× the short side"
    ratios = rule.get("ratios") or ([rule["ratio"]] if "ratio" in rule else [])
    if ratios and not any(w * b == h * a for a, b in ratios):
        return "a ratio of " + " or ".join(f"{a}:{b}" for a, b in ratios)
    if "min" in rule and (w < rule["min"][0] or h < rule["min"][1]):
        return f"at least {rule['min'][0]}×{rule['min'][1]}"
    if "max" in rule and (w > rule["max"][0] or h > rule["max"][1]):
        return f"at most {rule['max'][0]}×{rule['max'][1]}"
    return None


def text_count(value: str, unit: str) -> int:
    """A text field's length as its store counts it: Unicode code points, or UTF-8 bytes (Apple keywords)."""
    return len(value.encode("utf-8")) if unit == "bytes" else len(value)


def png_info(data: bytes) -> dict | None:
    """{w, h, depth, colour, trns} from a PNG's IHDR (and whether a tRNS chunk follows), or None for no PNG."""
    if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    w, h = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    out = {"w": w, "h": h, "depth": data[24], "colour": data[25], "trns": False}
    i = 33
    while i + 8 <= len(data):
        n, kind = int.from_bytes(data[i:i + 4], "big"), data[i + 4:i + 8]
        if kind == b"tRNS":
            out["trns"] = True
        if kind in (b"IDAT", b"IEND"):
            break
        i += 12 + n
    return out


class _Keys(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.keys: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        for k, v in attrs:
            if k == "data-l10n" and v and v not in self.keys:
                self.keys.append(v)

    handle_startendtag = handle_starttag


def l10n_keys(html: str) -> list[str]:
    """The caption string keys a shot's HTML names with data-l10n, in document order, once each."""
    p = _Keys()
    p.feed(html)
    p.close()
    return p.keys


def doc_stem(path: Path) -> str:
    name = Path(path).name
    return next((name[:-len(s)] for s in DOC_SUFFIXES if name.endswith(s)), Path(path).stem)


def listing_dir(doc_path: Path) -> Path:
    """<stem>.listing/ beside the doc: uploads, captures and the brand image."""
    return Path(doc_path).parent / f"{doc_stem(Path(doc_path))}.listing"


def _blocks(doc: dict):
    for s in doc.get("sections") or []:
        if isinstance(s, dict):
            for b in s.get("blocks") or []:
                if isinstance(b, dict):
                    yield b


def listing_of(doc: dict) -> dict | None:
    """The doc's listing block (the first), or None."""
    return next((b for b in _blocks(doc) if b.get("type") == "listing"), None) if isinstance(doc, dict) else None


def shots_of(doc: dict) -> list[dict]:
    b = next((b for b in _blocks(doc) if b.get("type") == "board"), None) if isinstance(doc, dict) else None
    arts = b.get("artboards") if isinstance(b, dict) else None
    return [a for a in arts if isinstance(a, dict) and isinstance(a.get("id"), str)] if isinstance(arts, list) else []


def is_image_shot(a) -> bool:
    """A shot or asset that is a finished PNG (an upload: `src` under <stem>.listing/), not a layout with a screen file."""
    return isinstance(a, dict) and a.get("device") in ("shot", "asset") and isinstance(a.get("src"), str) \
        and a["src"].lower().endswith(IMAGE_TYPES)


def image_src_problem(src: str, doc_path: Path | None) -> str | None:
    """Why an image shot's src can't be, or None: a relative path inside <stem>.listing/, no '..', a .png."""
    parts = src.split("/")
    if not src or src.startswith("/") or "\\" in src or ".." in parts or re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", src):
        return "a path relative to the doc, inside <stem>.listing/, no '..'"
    if doc_path is not None and parts[0] != listing_dir(doc_path).name:
        return f"inside {listing_dir(doc_path).name}/"
    return None


def recipe_hash(recipe) -> str:
    """The hash a capture records of the recipe it ran: sha256 of its canonical JSON, 16 hex digits."""
    canon = json.dumps(recipe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


def captures(doc: dict, doc_path: Path) -> dict:
    """{shot: {target: {locale: {file, w, h, fresh, at, sha, device}}}} from <stem>.listing/captures/captures.json
    (written by capture.py): file relative to the doc's folder; fresh when the capture's recipe hash is the shot's
    recipe's; at the time it was taken; sha its PNG's sha256 (16 hex digits), as the revision records it. {} without
    the file or a readable list."""
    f = listing_dir(doc_path) / "captures" / "captures.json"
    try:
        rows = json.loads(f.read_text(encoding="utf-8")).get("captures")
    except (OSError, ValueError, AttributeError):
        return {}
    recipes = {a["id"]: recipe_hash(a.get("recipe")) for a in shots_of(doc) if a.get("device") == "shot"}
    base = f"{listing_dir(doc_path).name}/captures/"
    out: dict = {}
    for c in rows if isinstance(rows, list) else []:
        if not isinstance(c, dict) or not all(isinstance(c.get(k), str) for k in ("shot", "target", "locale", "file")):
            continue
        if c["shot"] not in recipes or ".." in c["file"].split("/") or not c["file"].startswith(base):
            continue
        out.setdefault(c["shot"], {}).setdefault(c["target"], {})[c["locale"]] = {
            "file": c["file"], "w": c.get("w"), "h": c.get("h"), "fresh": c.get("recipe") == recipes[c["shot"]],
            "at": str(c.get("at") or "")[:25], "sha": str(c.get("sha256") or "")[:16], "device": str(c.get("device") or "")[:80]}
    return out


def youtube_problem(url) -> str | None:
    """Why a Play preview video URL isn't one video on YouTube, or None: no playlist, timecode or channel."""
    if not isinstance(url, str) or not url:
        return "a YouTube video URL"
    try:
        u = urlsplit(url)
    except ValueError:
        return f"'{url}' is no URL"
    if u.scheme not in ("http", "https") or (u.hostname or "") not in YOUTUBE_HOSTS:
        return f"'{url}': a YouTube URL (youtube.com/watch?v=… or youtu.be/…)"
    q = parse_qs(u.query)
    bad = [k for k in ("list", "t", "start", "index") if k in q]
    if bad or "#t=" in url:
        return f"'{url}': no playlist or timecode ({', '.join(bad) or 't'})"
    if u.hostname == "youtu.be":
        return None if re.fullmatch(r"/[\w-]{6,}", u.path) else f"'{url}': youtu.be/<video id>"
    if re.match(r"/(channel|c|user|@)", u.path) or u.path.startswith("/@"):
        return f"'{url}': a video, not a channel"
    if u.path == "/watch" and q.get("v"):
        return None
    if re.fullmatch(r"/(shorts|embed)/[\w-]{6,}", u.path):
        return None
    return f"'{url}': a video URL, youtube.com/watch?v=<id>"


def locales_for(rules: dict, platform: str) -> set[str]:
    return set(next((x["codes"] for x in rules.get("locales") or [] if x.get("platform") == platform), []))


def text_rules(rules: dict, platform: str | None = None) -> dict[str, dict]:
    """{field: its text rule} for a platform (every field of both when None, keyed by rule id)."""
    if platform is None:
        return by_id(rules, "text")
    return {r["field"]: r for r in rules.get("text") or [] if r.get("platform") == platform}


def validate_listing(rep, doc: dict, doc_path: Path | None, rules: dict | None = None) -> None:
    """The listing block and the shots and assets of the board against the rules file; rep has err(where, msg) and
    warn(where, msg), as build.Report. Structure, ids, platforms, rows, locales, text fields, caption strings and their
    MT marks, style ids, brand tokens, the icon, the videos, order drafts, and each artboard's sets, asset and src."""
    rules = rules or load_rules()
    found = [(i, b) for i, b in enumerate(_blocks(doc)) if b.get("type") == "listing"]
    if not found:
        return
    lw = _where(doc)
    lb = found[0][1]
    if not isinstance(lb.get("id"), str) or not ID_RE.match(lb["id"]):
        rep.err(lw, f"id {lb.get('id')!r} must match {ID_RE.pattern}")
    if rules_age(rules) > STALE_DAYS:
        rep.warn(lw, f"the store rules were read on {rules['accessed']}, over {STALE_DAYS} days ago: check them against "
                 "the stores' pages (assets/store-rules.json)")
    app = lb.get("app")
    if not isinstance(app, dict) or not isinstance(app.get("name"), str) or not app["name"].strip():
        rep.err(lw + ".app", "{name, company}: the app's name (and its maker's), which keyword checks read")
    known_p = [p["id"] for p in rules["platforms"]]
    plats = lb.get("platforms")
    if not isinstance(plats, list) or not plats or not all(p in known_p for p in plats) or len(set(plats)) != len(plats):
        rep.err(lw + ".platforms", f"a list of distinct platforms of {known_p}")
        plats = [p for p in plats if p in known_p] if isinstance(plats, list) else []
    known_r = [r["id"] for r in rules["rows"]]
    rows = lb.get("rows", [r["id"] for r in rules["rows"] if r.get("core")])
    if not isinstance(rows, list) or not all(r in known_r for r in rows) or len(set(rows)) != len(rows):
        rep.err(lw + ".rows", f"a list of distinct device sections of {known_r}")
        rows = [r for r in rows if r in known_r] if isinstance(rows, list) else []
    for r in rows:
        if not next(x for x in rules["rows"] if x["id"] == r).get("core"):
            rep.warn(lw + ".rows", f"'{r}' is an optional section: its sets are in the rules, but capture targets and "
                     "export come in a later version")
    locs = lb.get("locales")
    if not isinstance(locs, list) or not locs or not all(isinstance(x, str) and LOCALE.match(x) for x in locs) \
            or len(set(locs)) != len(locs):
        rep.err(lw + ".locales", "a list of distinct locale codes, e.g. [\"en-US\", \"es-ES\"]")
        locs = [x for x in locs if isinstance(x, str)] if isinstance(locs, list) else []
    for x in locs:
        for p in plats:
            if x not in locales_for(rules, p):
                rep.warn(lw + ".locales", f"'{x}' is not a {p} locale in the rules file (store-rules.json locales, "
                         "unverified lists): check the store's code")
    default = lb.get("defaultLocale", locs[0] if locs else None)
    if locs and default not in locs:
        rep.err(lw + ".defaultLocale", f"{default!r} is not in locales {locs}")
    for k in ("ipad", "watchFace"):
        if k in lb and not isinstance(lb[k], bool):
            rep.err(f"{lw}.{k}", "true or false")

    # text: {locale: {platform: {field: text}}}
    text = lb.get("text") or {}
    if not isinstance(text, dict):
        rep.err(lw + ".text", "{locale: {platform: {field: text}}}")
        text = {}
    for loc, per in text.items():
        tw = f"{lw}.text.{loc}"
        if loc not in locs:
            rep.err(tw, f"'{loc}' is not in locales {locs}")
        if not isinstance(per, dict):
            rep.err(tw, "{platform: {field: text}}")
            continue
        for p, fields in per.items():
            pw = f"{tw}.{p}"
            if p not in plats:
                rep.err(pw, f"'{p}' is not in platforms {plats}")
                continue
            known = text_rules(rules, p)
            if not isinstance(fields, dict):
                rep.err(pw, "{field: text}")
                continue
            for f, v in fields.items():
                if f not in known:
                    rep.err(f"{pw}.{f}", f"no {p} text field '{f}': {', '.join(known)}")
                elif "items" in known[f]:
                    if not isinstance(v, list) or not all(isinstance(s, str) for s in v):
                        rep.err(f"{pw}.{f}", "a list of strings")
                elif not isinstance(v, str):
                    rep.err(f"{pw}.{f}", "a string")
    for p in plats:
        for f, r in text_rules(rules, p).items():
            if r.get("required") is True and r.get("group") == "listing" and default in locs \
                    and not ((text.get(default) or {}).get(p) or {}).get(f):
                rep.warn(f"{lw}.text.{default}.{p}", f"no {r['label'].lower()} ({f}) in the default locale: {p} requires it")

    # caption strings: {locale: {key: text}}
    strings = lb.get("strings") or {}
    if not isinstance(strings, dict):
        rep.err(lw + ".strings", "{locale: {key: text}}")
        strings = {}
    for loc, per in strings.items():
        sw = f"{lw}.strings.{loc}"
        if loc not in locs:
            rep.err(sw, f"'{loc}' is not in locales {locs}")
        if not isinstance(per, dict) or not all(isinstance(k, str) and STRING_KEY.match(k) and isinstance(v, str) for k, v in per.items()):
            rep.err(sw, "{key: text}, keys of letters, digits, - and _ joined by dots (today.title)")

    # MT marks: {locale: ["<platform>.<field>" | "strings.<key>"]}
    mt = lb.get("mt") or {}
    if not isinstance(mt, dict):
        rep.err(lw + ".mt", "{locale: [\"appstore.subtitle\", \"strings.today.title\"]}")
        mt = {}
    for loc, keys in mt.items():
        mw = f"{lw}.mt.{loc}"
        if loc not in locs:
            rep.err(mw, f"'{loc}' is not in locales {locs}")
        if not isinstance(keys, list):
            rep.err(mw, "a list of keys")
            continue
        for k in keys:
            head, _, rest = str(k).partition(".")
            if head == "strings":
                ok = rest in ((strings.get(loc) or {}) if isinstance(strings.get(loc), dict) else {})
            else:
                ok = head in plats and rest in (((text.get(loc) or {}).get(head) or {}) if isinstance(text.get(loc), dict) else {})
            if not ok:
                rep.err(mw, f"'{k}' names no string in {loc}: <platform>.<field> or strings.<key>")
    tf = lb.get("translatedFrom")
    if tf is not None and not (isinstance(tf, dict) and all(loc in locs and isinstance(m, dict) and all(
            isinstance(v, str) and re.fullmatch(r"[0-9a-f]{16}", v) for v in m.values()) for loc, m in tf.items())):
        rep.err(lw + ".translatedFrom", "{locale: {key: hash}}: what `build.py l10n --import` records; leave it to it")

    # style: the picker's default (listing.style, and listing.style.<platform>: a platform page's pick), and a shot's own
    styles = {s["id"]: s for s in rules["styles"]}

    def style_ok(where: str, st, platforms: bool = False) -> None:
        if st is None:
            return
        if not isinstance(st, dict):
            rep.err(where, "{message, layout}: style ids m1-m5 and l1-l5")
            return
        for axis, pre in (("message", "m"), ("layout", "l")):
            v = st.get(axis)
            if v is not None and not (v in styles and styles[v]["axis"] == axis):
                rep.err(f"{where}.{axis}", f"{v!r} is no {axis} style: {', '.join(s for s in styles if s.startswith(pre))}")
        for k in st:
            if platforms and k in (lb.get("platforms") or []):
                style_ok(f"{where}.{k}", st[k])
            elif k not in ("message", "layout"):
                rep.err(f"{where}.{k}", "a style has message and layout" + (", and a platform's own: play, appstore" if platforms else " only"))
    style_ok(lw + ".style", lb.get("style"), platforms=True)

    brand = lb.get("brand")
    if brand is not None:
        if not isinstance(brand, dict):
            rep.err(lw + ".brand", "{font, palette, image}")
        else:
            for k, msg in caption_font_problems(brand.get("font"), rules):
                rep.err(lw + ".brand.font" + (f".{k}" if k else ""), msg)
            pal = brand.get("palette")
            if pal is not None:
                if not isinstance(pal, dict):
                    rep.err(lw + ".brand.palette", f"{{role: #hex}} for {', '.join(PALETTE_ROLES)}")
                else:
                    for k, v in pal.items():
                        if k not in PALETTE_ROLES:
                            rep.err(f"{lw}.brand.palette.{k}", f"no role '{k}': {', '.join(PALETTE_ROLES)}")
                        elif not (isinstance(v, str) and HEX.match(v)):
                            rep.err(f"{lw}.brand.palette.{k}", f"{v!r}: a hex colour, #rgb or #rrggbb")
            img = brand.get("image")
            if img is not None and (not isinstance(img, str) or image_src_problem(img.replace(".jpg", ".png").replace(".jpeg", ".png").replace(".webp", ".png"), doc_path)):
                rep.err(lw + ".brand.image", "a path inside <stem>.listing/brand/")

    arts = shots_of(doc)
    ids = {a["id"]: a for a in arts}
    icon = lb.get("icon")
    if icon is not None:
        if not isinstance(icon, str) or not icon:
            rep.err(lw + ".icon", "an icons artboard's id, or <design doc path>#<artboard id>")
        elif "#" in icon:
            path, _, aid = icon.partition("#")
            if not path.endswith(DOC_SUFFIXES) or ".." in Path(path).name or not ID_RE.match(aid or ""):
                rep.err(lw + ".icon", "<design doc path>.bluedoc.json#<icons artboard id>")
            elif doc_path is not None:
                other = Path(doc_path).parent / path
                try:
                    od = json.loads(other.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    rep.warn(lw + ".icon", f"cannot read {other}: the pages show no icon")
                else:
                    if not any(a.get("id") == aid and a.get("device") == "icons" for a in shots_of(od)):
                        rep.err(lw + ".icon", f"{path} has no icons artboard '{aid}'")
        elif not (icon in ids and ids[icon].get("device") == "icons"):
            rep.err(lw + ".icon", f"'{icon}' is no icons artboard on this board")

    video = lb.get("video")
    if video is not None:
        if not isinstance(video, dict):
            rep.err(lw + ".video", "{play: <YouTube URL>, appstore: [{src, row, poster}]}")
        else:
            if "play" in video:
                why = youtube_problem(video["play"])
                if why:
                    rep.err(lw + ".video.play", why)
            prev = video.get("appstore", [])
            per_row: dict[str, int] = {}
            for i, v in enumerate(prev if isinstance(prev, list) else [None]):
                vw = f"{lw}.video.appstore[{i}]"
                if not isinstance(v, dict) or not isinstance(v.get("src"), str) or not v["src"].lower().endswith(".mp4") \
                        or v.get("row", "phone") not in ("phone", "tablet") \
                        or not (v.get("poster") is None or (isinstance(v["poster"], (int, float)) and 0 <= v["poster"] <= 30)):
                    rep.err(vw, "{src: <file>.mp4 beside the doc, row: phone|tablet, poster: seconds (default 5)}")
                    continue
                per_row[v.get("row", "phone")] = per_row.get(v.get("row", "phone"), 0) + 1
                if doc_path is not None and not (Path(doc_path).parent / v["src"]).is_file():
                    rep.err(vw + ".src", f"'{v['src']}' not found")
            for row, n in per_row.items():
                if n > MAX_PREVIEWS:
                    rep.err(lw + ".video.appstore", f"{n} {row} previews: at most {MAX_PREVIEWS} per size and locale (A-PV)")

    validate_capture(rep, lw, lb, doc, doc_path, rules)
    validate_brand_style(rep, lw, lb, doc, doc_path, rules)
    sets = by_id(rules, "sets")
    assets = by_id(rules, "assets")
    in_set: dict[str, list[str]] = {}
    for i, a in enumerate(arts):
        aw = f"artboard '{a['id']}'"
        dev = a.get("device")
        if dev == "shot":
            own = isinstance(a.get("variantOf"), str)   # a variant's shot: only a swap shows it, in its source's place
            ss = a.get("sets")
            if not isinstance(ss, list) or not ss or not all(isinstance(s, str) for s in ss) or len(set(ss)) != len(ss):
                rep.err(aw + ".sets", "the distinct sets this shot fills, e.g. [\"play/phone\", \"appstore/iphone-69\"]")
                ss = []
            for s in ss:
                r = sets.get(s)
                if r is None:
                    rep.err(aw + ".sets", f"no set '{s}' in the rules: {', '.join(k for k, v in sets.items() if v.get('core'))}")
                elif r["platform"] not in plats:
                    rep.err(aw + ".sets", f"'{s}' is a {r['platform']} set and the listing's platforms are {plats}")
                elif not own:
                    in_set.setdefault(s, []).append(a["id"])
                    if r["row"] not in rows:
                        rep.warn(aw + ".sets", f"'{s}' is in the {r['row']} section, which listing.rows leaves off: the "
                                 "pages don't show it")
            style_ok(aw + ".style", a.get("style"))
            if "recipe" in a and not isinstance(a["recipe"], dict):
                rep.err(aw + ".recipe", "an object: route, appearance, settle, targets")
        elif dev == "asset":
            r = assets.get(a.get("asset"))
            if r is None:
                rep.err(aw + ".asset", f"{a.get('asset')!r} is no asset in the rules: {', '.join(assets)}")
            elif r["platform"] not in plats:
                rep.err(aw + ".asset", f"'{a['asset']}' is a {r['platform']} asset and the listing's platforms are {plats}")
            elif "author" not in r:
                rep.err(aw + ".asset", f"'{a['asset']}' isn't drawn as an artboard: {r.get('note') or 'see the rules'}")
        if dev in ("shot", "asset") and "locale" in a and a["locale"] not in locs:
            rep.err(aw + ".locale", f"{a['locale']!r} is not in locales {locs}")
        if is_image_shot(a):
            why = image_src_problem(a["src"], doc_path)
            if why:
                rep.err(aw + ".src", f"'{a['src']}': {why}")
            elif doc_path is not None:
                f = Path(doc_path).parent / a["src"]
                try:
                    info = png_info(f.read_bytes()[:4096])
                except OSError:
                    rep.err(aw + ".src", f"'{a['src']}' not found")
                else:
                    if info is None:
                        rep.err(aw + ".src", f"'{a['src']}' is no PNG")
        for k in ("sets", "recipe", "style"):
            if k in a and dev != "shot":
                rep.err(f"{aw}.{k}", "only a shot has it")
        if "locale" in a and dev not in ("shot", "asset"):
            rep.err(aw + ".locale", "only a shot or an asset has it")
        if "asset" in a and dev != "asset":
            rep.err(aw + ".asset", "only an asset artboard has it")
    validate_variants(rep, lw, lb, arts, rules, plats, locs, style_ok)

    order = lb.get("order")
    if order is not None:
        if not isinstance(order, dict):
            rep.err(lw + ".order", "{set: [shot ids]}")
        else:
            for s, seq in order.items():
                ow = f"{lw}.order.{s}"
                if s not in sets:
                    rep.err(ow, f"no set '{s}'")
                elif not isinstance(seq, list) or len(set(map(str, seq))) != len(seq) or set(seq) - set(in_set.get(s, [])):
                    rep.err(ow, f"a list of the shots that fill {s}, each once: {', '.join(in_set.get(s, []))}")

    # caption keys the shots use, with no string in the default locale
    if doc_path is not None and default:
        have = strings.get(default) if isinstance(strings.get(default), dict) else {}
        for a in arts:
            if a.get("device") not in ("shot", "asset") or is_image_shot(a):
                continue
            f = Path(doc_path).parent / str(a.get("src") or f"{doc_stem(Path(doc_path))}.design/{a['id']}.html")
            try:
                keys = l10n_keys(f.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue   # build reports the screen file
            for k in keys:
                if not STRING_KEY.match(k):
                    rep.err(f"artboard '{a['id']}'", f"data-l10n=\"{k}\": a key of letters, digits, - and _ joined by dots")
                elif k not in have:
                    rep.warn(f"artboard '{a['id']}'", f"data-l10n=\"{k}\" has no string in {default}: the shot shows its "
                             "HTML text; add it to listing.strings")
    validate_store(rep, lb, doc, doc_path, rules)


def _where(doc: dict) -> str:
    for si, s in enumerate(doc.get("sections") or []):
        for bi, b in enumerate((s or {}).get("blocks") or []):
            if isinstance(b, dict) and b.get("type") == "listing":
                return f"sections[{si}].blocks[{bi}]"
    return "listing"


def contract(doc: dict) -> list[str]:
    """A storelisting's contract gaps: exactly one listing block and one board of at least one artboard, every one a
    shot, an asset or an icons artboard."""
    out = []
    listings = [b for b in _blocks(doc) if b.get("type") == "listing"]
    if len(listings) != 1:
        out.append(f"a storelisting needs exactly one listing block (it has {len(listings)})")
    boards = [b for b in _blocks(doc) if b.get("type") == "board"]
    if len(boards) != 1:
        out.append(f"a storelisting needs exactly one board block (it has {len(boards)})")
    elif not boards[0].get("artboards"):
        out.append("a storelisting's board needs at least one shot")
    elif isinstance(boards[0]["artboards"], list):
        other = [f"{a.get('id')}: {a.get('device') or 'no device'}" for a in boards[0]["artboards"]
                 if isinstance(a, dict) and a.get("device") not in SHOT_DEVICES]
        if other:
            out.append(f"a storelisting's board holds shots, assets and an icon only (device shot, asset or icons): {', '.join(other)}")
    return out


def sections(lb: dict, artboards: list, rules: dict, platform: str, locale: str | None, variant: dict | None = None) -> list[dict]:
    """A platform page's device sections, as the page lays them out (board-geo.js listingSections, line for line):
    [{row, sets: [{set, shots: [artboard ids]}]}] for each row of listing.rows (default: the core rows) in the rules'
    order. A row lists the platform's sets in that row, in the rules' order, that are core, or have a shot, or are
    asked for (`if:watchFace` with listing.watchFace). A set's shots: the shots that name it, in board order, except
    an uploaded one of another locale and a variant's own shot (`variantOf`); listing.order[set] puts the ids it names
    first, in its order. With a variant (an entry of listing.variants): its `swap` ({default shot: its shot}) puts a
    shot in another's place (a shot once, at its first place), then its `order[set]` puts the ids it names first. A
    row with no set is left out."""
    lb = lb if isinstance(lb, dict) else {}
    rows = lb.get("rows") if isinstance(lb.get("rows"), list) else [r["id"] for r in rules["rows"] if r.get("core")]
    order = lb.get("order") if isinstance(lb.get("order"), dict) else {}
    shot_ids = {a["id"] for a in artboards or [] if isinstance(a, dict) and isinstance(a.get("id"), str) and a.get("device") == "shot"}
    arts = [a for a in artboards or [] if isinstance(a, dict) and isinstance(a.get("id"), str) and a.get("device") == "shot"
            and isinstance(a.get("sets"), list) and not isinstance(a.get("variantOf"), str)]
    v = variant if isinstance(variant, dict) else {}
    swap = {k: s for k, s in v["swap"].items() if isinstance(s, str) and s in shot_ids} if isinstance(v.get("swap"), dict) else {}
    v_order = v.get("order") if isinstance(v.get("order"), dict) else {}

    def first(ids: list[str], want) -> list[str]:
        want = [i for i in want if i in ids] if isinstance(want, list) else []
        return want + [i for i in ids if i not in want]
    out = []
    for r in rules["rows"]:
        if r["id"] not in rows:
            continue
        sets = []
        for s in rules["sets"]:
            if s["platform"] != platform or s["row"] != r["id"]:
                continue
            shots = [a["id"] for a in arts if s["id"] in a["sets"] and (not isinstance(a.get("locale"), str) or a["locale"] == locale)]
            if not (s.get("core") or shots or (s.get("required") == "if:watchFace" and lb.get("watchFace") is True)):
                continue
            shots = list(dict.fromkeys(swap.get(i, i) for i in first(shots, order.get(s["id"]))))
            sets.append({"set": s["id"], "shots": first(shots, v_order.get(s["id"]))})
        if sets:
            out.append({"row": r["id"], "sets": sets})
    return out


def _data_uri(f: Path, mime: str) -> str | None:
    try:
        data = f.read_bytes()
    except OSError:
        return None
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


ICON_TILE_LAYERS = ("fg.svg", "bg.svg", "play.svg")   # what the Shared section's icon tiles draw (an icon sheet's layers)
MAX_LAYER_BYTES = 2 * 1024 * 1024


def icon_of(doc: dict, doc_path: Path) -> dict | None:
    """The listing's icon for the Shared section: {from, layers: {fg, bg?, play?} as SVG data: URIs, bg: colour or
    None}, read from the icons artboard listing.icon names (on this board, or `<design doc>#<id>` beside it). None when
    there is none or its fg.svg is unreadable."""
    lb = listing_of(doc) or {}
    ref = lb.get("icon")
    if not isinstance(ref, str) or not ref:
        return None
    src_doc, src_path, aid = doc, Path(doc_path), ref
    if "#" in ref:
        path, _, aid = ref.partition("#")
        if not path.endswith(DOC_SUFFIXES):
            return None
        src_path = (Path(doc_path).parent / path).resolve()
        try:
            src_doc = json.loads(src_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    a = next((x for x in shots_of(src_doc) if x.get("id") == aid and x.get("device") == "icons"), None)
    if a is None or not ID_RE.match(aid):
        return None
    folder = src_path.parent / f"{doc_stem(src_path)}.design" / aid
    layers = {}
    for name in ICON_TILE_LAYERS:
        f = folder / name
        try:
            if f.is_file() and f.stat().st_size <= MAX_LAYER_BYTES:
                layers[name[:-4]] = _data_uri(f, "image/svg+xml")
        except OSError:
            pass
    if not layers.get("fg"):
        return None
    icon = a.get("icon") if isinstance(a.get("icon"), dict) else {}
    bg = icon.get("bg") if isinstance(icon.get("bg"), str) and HEX.match(icon["bg"]) else None
    return {"from": ref, "layers": layers, "bg": bg, "name": str(icon.get("name") or "")[:30]}


def page_data(doc: dict, doc_path: Path | None, texts: dict[str, str | None] | None = None, inline: bool = False) -> dict:
    """What the page needs beside the doc: the rules file, each shot's caption keys (from texts, {artboard id: screen
    text}, else the screen files), the captures it may show, the uploaded shots' PNGs ({id: {src, w, h, colour,
    trns}}) and the icon (icon_of). Paths are relative to the doc's folder; inline (an -o file) makes the PNGs data:
    URIs. JSON-safe."""
    rules = load_rules()
    keys: dict[str, list[str]] = {}
    images: dict[str, dict] = {}
    hooks: dict[str, list[str]] = {}
    for a in shots_of(doc):
        if is_image_shot(a):
            if doc_path is None or image_src_problem(a["src"], doc_path):
                continue
            f = Path(doc_path).parent / a["src"]
            try:
                info = png_info(f.read_bytes()[:65536]) or {}
            except OSError:
                continue
            images[a["id"]] = {"src": (_data_uri(f, "image/png") if inline else a["src"]), **info}
            continue
        if a.get("device") not in ("shot", "asset"):
            continue
        t = (texts or {}).get(a["id"])
        if t is None and doc_path is not None and texts is None:
            f = Path(doc_path).parent / str(a.get("src") or f"{doc_stem(Path(doc_path))}.design/{a['id']}.html")
            try:
                t = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                t = None
        keys[a["id"]] = l10n_keys(t) if t else []
        hooks[a["id"]] = style_hooks(t) if t else []
    caps = captures(doc, doc_path) if doc_path is not None else {}
    if inline and doc_path is not None:
        for per in caps.values():
            for locs in per.values():
                for c in locs.values():
                    c["file"] = _data_uri(Path(doc_path).parent / c["file"], "image/png") or c["file"]
    out = {"rules": rules, "keys": keys, "captures": caps, "images": images,
           "icon": icon_of(doc, doc_path) if doc_path is not None else None,
           "checks": checks_page_data(doc, doc_path)}   # the build's report: the Checks tab, per platform
    if doc_path is not None and not inline:
        out.update(capture_page_data(doc, doc_path))
    out.update(style_page_data(hooks))
    return out


# ---------- uploads, captures, re-shoot (M2) ----------
# An upload is a PNG the page posts into a set's slot (serve.py POST /__bluedoc/listing/upload): it is written at once
# under <stem>.listing/<platform>/<locale>/<set name>/NN.png and stays a draft until the agent records it as a shot's
# `src` (`build.py patch … --append`, the command the page's Request changes gives). A recipe is a shot's capture
# instructions; capture.py runs it and writes captures.json. A capture's PNG joins the revision by its hash, under
# "<shot>/capture/<target>/<locale>" in the history entry's screens (file_hashes).

UPLOAD_MAX_BYTES = 8 * 1024 * 1024   # a set's upload limit unless its rule has maxBytes
UPLOAD_NAME = re.compile(r"^(\d{2})\.png$")
APP_KINDS = {"ios": "bundle", "watchos": "bundle", "android": "package", "wearos": "package"}
RECIPE_KEYS = ("route", "appearance", "settle", "targets", "locales", "size")
BUNDLE = re.compile(r"^[A-Za-z0-9-]+(?:\.[A-Za-z0-9_-]+)+$")


def recipe_targets(a: dict, rules: dict) -> list[str]:
    """The targets a shot's recipe runs on: its own `targets`, else the targets of the sets it fills, once each."""
    r = a.get("recipe") if isinstance(a.get("recipe"), dict) else {}
    if isinstance(r.get("targets"), list) and r["targets"]:
        return [t for t in r["targets"] if isinstance(t, str)]
    sets = by_id(rules, "sets")
    return list(dict.fromkeys(sets[s]["target"] for s in a.get("sets") or [] if s in sets and sets[s].get("target")))


def recipe_locales(a: dict, lb: dict) -> list[str]:
    r = a.get("recipe") if isinstance(a.get("recipe"), dict) else {}
    locs = r.get("locales") if isinstance(r.get("locales"), list) and r["locales"] else lb.get("locales") or []
    return [x for x in locs if isinstance(x, str)]


def target_device(lb: dict, rules: dict, target: str) -> str:
    """The simulator or AVD a target runs on: listing.capture.devices, else the rules' device."""
    cap = lb.get("capture") if isinstance(lb.get("capture"), dict) else {}
    dev = (cap.get("devices") or {}).get(target) if isinstance(cap.get("devices"), dict) else None
    return dev if isinstance(dev, str) and dev else next((t["device"] for t in rules["targets"] if t["id"] == target), "")


def _rel_ok(v) -> bool:
    return isinstance(v, str) and bool(v) and not v.startswith("/") and "\\" not in v and ".." not in v.split("/")


def validate_capture(rep, lw: str, lb: dict, doc: dict, doc_path: Path | None, rules: dict) -> None:
    """listing.capture ({devices, apps}), each shot's recipe, and on disk: captures a changed recipe made stale, and
    uploads no shot records yet (warnings)."""
    targets = {t["id"] for t in rules["targets"]}
    cap = lb.get("capture")
    cw = lw + ".capture"
    if cap is not None and not isinstance(cap, dict):
        rep.err(cw, "{devices: {<target>: <simulator or AVD>}, apps: {ios|watchos: {bundle, app?}, android|wearos: "
                "{package, apk?}, web: {url | design}}}")
        cap = {}
    for k, v in (cap or {}).items():
        if k == "devices":
            if not isinstance(v, dict) or not all(t in targets and isinstance(n, str) and 0 < len(n) <= 80 for t, n in v.items()):
                rep.err(cw + ".devices", f"{{<target>: <simulator name or UDID, or AVD name>}}, targets {', '.join(sorted(targets))}")
        elif k == "apps":
            if not isinstance(v, dict):
                rep.err(cw + ".apps", "{ios|watchos: {bundle, app?}, android|wearos: {package, apk?}, web: {url | design}}")
                continue
            for kind, app in v.items():
                aw = f"{cw}.apps.{kind}"
                if kind in APP_KINDS:
                    idk, build_k = APP_KINDS[kind], "app" if APP_KINDS[kind] == "bundle" else "apk"
                    if not isinstance(app, dict) or not BUNDLE.match(str(app.get(idk) or "")) \
                            or (build_k in app and not _rel_ok(app[build_k])) or set(app) - {idk, build_k}:
                        rep.err(aw, f"{{{idk}: <reverse-DNS id>, {build_k}?: <a build beside the doc>}}")
                elif kind == "web":
                    url, design = (app or {}).get("url"), (app or {}).get("design") if isinstance(app, dict) else None
                    ok_url = isinstance(url, str) and re.match(r"^https?://(localhost|127(?:\.\d{1,3}){3}|\[::1\])(?::\d+)?(?:/|$)", url)
                    ok_design = _rel_ok(design) and str(design).endswith(DOC_SUFFIXES)
                    if not isinstance(app, dict) or not (ok_url or ok_design) or (url and design) or set(app) - {"url", "design"}:
                        rep.err(aw, "{url: a loopback dev server (http://localhost:<port>/)} or {design: <a design doc beside>}")
                    elif design and doc_path is not None and not (Path(doc_path).parent / design).is_file():
                        rep.err(aw + ".design", f"'{design}' not found")
                else:
                    rep.err(aw, f"no app kind '{kind}': ios, watchos, android, wearos, web")
        else:
            rep.err(f"{cw}.{k}", "capture has devices and apps")
    locs = [x for x in lb.get("locales") or [] if isinstance(x, str)]
    shots = [a for a in shots_of(doc) if a.get("device") == "shot"]
    for a in shots:
        r = a.get("recipe")
        if not isinstance(r, dict):
            continue
        rw = f"artboard '{a['id']}'.recipe"
        for k in r:
            if k not in RECIPE_KEYS:
                rep.err(f"{rw}.{k}", f"a recipe has {', '.join(RECIPE_KEYS)}")
        if "route" in r and not (isinstance(r["route"], str) and 0 < len(r["route"]) <= 2000 and not re.search(r"\s", r["route"])):
            rep.err(rw + ".route", "a deep link (acmefit://workout), a path on the web app, or a design screen's id")
        if r.get("appearance", "light") not in ("light", "dark"):
            rep.err(rw + ".appearance", "light or dark")
        s = r.get("settle", 2)
        if isinstance(s, bool) or not isinstance(s, (int, float)) or not 0 <= s <= 30:
            rep.err(rw + ".settle", "seconds to wait after opening the route, 0-30")
        if "targets" in r and not (isinstance(r["targets"], list) and r["targets"] and all(t in targets for t in r["targets"])):
            rep.err(rw + ".targets", f"a list of {', '.join(sorted(targets))}")
        if "locales" in r and not (isinstance(r["locales"], list) and r["locales"] and all(x in locs for x in r["locales"])):
            rep.err(rw + ".locales", f"a list of the listing's locales {locs}")
        if "size" in r and not (isinstance(r["size"], list) and len(r["size"]) == 2
                                and all(isinstance(n, int) and not isinstance(n, bool) and 120 <= n <= 3840 for n in r["size"])):
            rep.err(rw + ".size", "[w, h]: the web capture's viewport in CSS px, 120-3840")
    if doc_path is None:
        return
    stem = Path(doc_path).name
    for sid, per in captures(doc, doc_path).items():
        for t, by_loc in per.items():
            for loc, c in by_loc.items():
                if not (Path(doc_path).parent / c["file"]).is_file():
                    rep.warn(f"artboard '{sid}'", f"capture {c['file']} is missing: re-shoot it: capture.py {stem} --shot {sid} "
                             f"--target {t} --locale {loc}")
                elif not c["fresh"]:
                    rep.warn(f"artboard '{sid}'", f"the {t} {loc} capture is stale (its recipe changed since): capture.py {stem} "
                             f"--shot {sid} --target {t} --locale {loc}")
    for u in uploads(doc, doc_path, rules):
        rep.warn(lw, f"{u['file']}: an uploaded shot no artboard records yet (Request changes on the page gives the "
                 "`build.py patch … --append` command)" + (f"; it doesn't fit {u['set']}: {u['problem']}" if u.get("problem") else ""))


def _history_file(doc_path: Path) -> Path:
    name = Path(doc_path).name
    return Path(doc_path).with_name((name[:-5] if name.endswith(".json") else name) + ".history.json")


def recorded_srcs(doc: dict, doc_path: Path) -> set[str]:
    """Every image shot src the doc or a revision in its history records: files that are never overwritten."""
    out = {a["src"] for a in shots_of(doc) if is_image_shot(a)}
    try:
        h = json.loads(_history_file(doc_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    for b in (h.get("blocks") or {}).values() if isinstance(h, dict) else []:
        if isinstance(b, dict) and b.get("type") == "board":
            out |= {a["src"] for a in b.get("artboards") or [] if is_image_shot(a)}
    return out


def upload_folder(doc_path: Path, set_id: str, locale: str) -> Path:
    """<stem>.listing/<platform>/<locale>/<set name>/: where a set's uploads for a locale go."""
    platform, _, name = set_id.partition("/")
    return listing_dir(doc_path) / platform / locale / name


def upload_problem(rule: dict, data: bytes) -> str | None:
    """Why a PNG can't be an upload to a set, or None: a PNG of an accepted size, RGB or indexed colour without
    transparency, at most the set's byte limit."""
    limit = rule.get("maxBytes", UPLOAD_MAX_BYTES)
    if len(data) > limit:
        return f"{len(data) / 1048576:.1f} MB: at most {limit // 1048576} MB"
    info = png_info(data)
    if info is None:
        return "not a PNG"
    why = size_problem(rule, info["w"], info["h"])
    if why:
        return f"{info['w']}×{info['h']}: want {why}"
    if info["colour"] not in (2, 3) or info["trns"]:
        return "it has transparency: want RGB or indexed colour without alpha"
    return None


def next_upload_name(folder: Path, slot: int, recorded: set[str], rel_of) -> str | None:
    """The file a slot's upload is written to: NN.png for the slot, unless a revision records that name (the file
    there, or gone since); then the next number after every NN.png in the folder or recorded in it. None past 99."""
    name = f"{slot:02d}.png"
    if rel_of(name) not in recorded:
        return name
    nums = [int(m[1]) for f in (folder.iterdir() if folder.is_dir() else []) for m in [UPLOAD_NAME.match(f.name)] if m]
    nums += [n for n in range(1, 100) if rel_of(f"{n:02d}.png") in recorded]
    n = max(nums, default=slot) + 1
    return f"{n:02d}.png" if n <= 99 else None


def upload_rules(rules: dict) -> dict[str, dict]:
    """What takes an upload, by id: every set, and the ads' assets (Google Ads images, the search results asset, Apple
    Ads creative assets), which are authored as asset artboards or uploaded."""
    return {**by_id(rules, "sets"), **{r["id"]: r for r in rules["assets"] if r.get("group") == "ads" and "author" in r}}


def uploads(doc: dict, doc_path: Path, rules: dict | None = None) -> list[dict]:
    """The drafts: uploaded PNGs no shot or asset (in the doc or a revision) records, [{file, platform, locale, set,
    asset, slot, w, h, colour, bytes, problem}] in set and slot order; `set` is the set's or asset's id, `asset` true for
    an asset. file is relative to the doc's folder."""
    rules = rules or load_rules()
    lb = listing_of(doc) or {}
    recorded = recorded_srcs(doc, doc_path)
    base = listing_dir(doc_path)
    if base.is_symlink() or not base.is_dir():
        return []
    out = []
    for s in upload_rules(rules).values():
        if s["platform"] not in (lb.get("platforms") or []):
            continue
        for loc in lb.get("locales") or []:
            if not isinstance(loc, str) or not LOCALE.match(loc):
                continue
            folder = upload_folder(doc_path, s["id"], loc)
            if not folder.is_dir() or any(p.is_symlink() for p in (folder.parent.parent, folder.parent, folder)):
                continue
            for f in sorted(folder.iterdir()):
                m = UPLOAD_NAME.match(f.name)
                rel = f"{base.name}/{s['platform']}/{loc}/{s['id'].partition('/')[2]}/{f.name}"
                if not m or f.is_symlink() or not f.is_file() or rel in recorded:
                    continue
                try:
                    data = f.read_bytes()
                except OSError:
                    continue
                info = png_info(data[:65536]) or {}
                out.append({"file": rel, "platform": s["platform"], "locale": loc, "set": s["id"], "asset": "row" not in s,
                            "slot": int(m[1]), "w": info.get("w"), "h": info.get("h"), "colour": info.get("colour"),
                            "bytes": len(data), "problem": upload_problem(s, data)})
    return out


def file_hashes(doc: dict, doc_path: Path) -> dict[str, str]:
    """{"<shot>/capture/<target>/<locale>": the capture's sha256, 16 hex digits}: what a revision records of the
    captures (beside its screen files' text hashes), so a re-shoot changes the revision and compare shows it."""
    out = {}
    for sid, per in captures(doc, doc_path).items():
        for t, by_loc in per.items():
            for loc, c in by_loc.items():
                f = Path(doc_path).parent / c["file"]
                if not f.is_file():
                    continue
                sha = c.get("sha")
                if not sha:
                    try:
                        sha = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
                    except OSError:
                        continue
                out[f"{sid}/capture/{t}/{loc}"] = sha
    return out


def capture_page_data(doc: dict, doc_path: Path) -> dict:
    """page_data's part for uploads and re-shoots: the draft uploads (uploads()), the captures a re-shoot replaced
    ({sha 16: file} in captures/old/, for compare) and each target's device."""
    rules = load_rules()
    old = listing_dir(doc_path) / "captures" / "old"
    olds = {}
    if old.is_dir() and not old.is_symlink():
        for f in old.iterdir():
            if re.fullmatch(r"[0-9a-f]{16}\.png", f.name) and f.is_file() and not f.is_symlink():
                olds[f.name[:16]] = f"{listing_dir(doc_path).name}/captures/old/{f.name}"
    lb = listing_of(doc) or {}
    return {"uploads": uploads(doc, doc_path, rules), "oldCaptures": olds,
            "devices": {t["id"]: target_device(lb, rules, t["id"]) for t in rules["targets"]}}


def reshoot_lines(doc: dict, a: dict, doc_path: Path, doc_arg: str) -> list[str]:
    """What `build.py patch <doc> el:<shot>/…` prints after the screen file: the shot's recipe per target, each
    locale's capture with its time, and the capture.py command that re-shoots it; for an upload, that it has none."""
    if a.get("device") != "shot":
        return []
    rules, lb = load_rules(), listing_of(doc) or {}
    r = a.get("recipe")
    if not isinstance(r, dict):
        return [f"upload {a['src']}: no recipe to re-shoot: ask for a new PNG, or add a recipe so the shot becomes a capture"
                if is_image_shot(a) else "no recipe: the shot shows mock-up UI; add a recipe to capture the app"]
    caps = captures(doc, doc_path).get(a["id"], {})
    out = []
    for t in recipe_targets(a, rules):
        out.append(f"recipe {t}: {target_device(lb, rules, t) or '?'} · {r.get('route') or '(the app as it opens)'} · "
                   f"{r.get('appearance') or 'light'}")
        for loc in recipe_locales(a, lb):
            c = (caps.get(t) or {}).get(loc)
            have = (f"{c['file']}, taken {c['at'][:10] or 'at an unknown time'}" + ("" if c["fresh"] else ", stale: the recipe changed since")
                    if c else "no capture yet")
            out.append(f"  {loc}: {have}; re-shoot: capture.py {doc_arg} --shot {a['id']} --target {t} --locale {loc}")
    return out


# ---------- style and brand (M3) ----------
# The Style pane's hooks and thumbnails, the brand (store-rules.json `brand`: defaults, the contrast pairs the shot kit
# draws text in, the font's embedding bits, the brand image's types) and the build's warnings on picks and palettes.

THUMBS_PATH = HERE.parent / "assets" / "kits" / "style-thumbs.svg"


class _Hooks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: set[str] = set()

    def handle_starttag(self, tag, attrs) -> None:
        d = dict(attrs)
        if "data-callout" in d:
            self.found.add("callout")
        if tag == "img" and "shot-photo" in (d.get("class") or "").split():
            self.found.add("photo")

    handle_startendtag = handle_starttag


def style_hooks(html: str) -> list[str]:
    """What a shot's HTML offers the styles that need the agent: `callout` (an element marked data-callout, M3) and
    `photo` (an img.shot-photo, L5's lifestyle photo)."""
    p = _Hooks()
    p.feed(html)
    p.close()
    return sorted(p.found)


def _hex6(c: str) -> str:
    c = c.lower()
    return "#" + "".join(ch * 2 for ch in c[1:]) if len(c) == 4 else c


def relative_luminance(c: str) -> float:
    """WCAG 2.2 relative luminance of a #rgb or #rrggbb colour."""
    c = _hex6(c)
    ch = [int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in ch)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    """WCAG 2.2 contrast ratio of two colours, 1 to 21."""
    hi, lo = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def brand_palette(lb: dict, rules: dict) -> dict[str, str]:
    """The colours every shot gets: the rules' brand defaults (kits/shot.css's), then listing.brand.palette."""
    pal = {k: _hex6(v) for k, v in rules["brand"]["defaults"].items()}
    own = (lb.get("brand") or {}).get("palette") if isinstance(lb.get("brand"), dict) else None
    for k, v in (own if isinstance(own, dict) else {}).items():
        if k in pal and isinstance(v, str) and HEX.match(v):
            pal[k] = _hex6(v)
    return pal


def contrast_report(palette: dict[str, str], rules: dict) -> list[dict]:
    """Each pair the shot kit draws text in (the rules' brand.contrast.pairs): {fg, bg, label, styles, ratio, ok}."""
    c = rules["brand"]["contrast"]
    out = []
    for p in c["pairs"]:
        r = contrast_ratio(palette[p["fg"]], palette[p["bg"]])
        out.append({**p, "ratio": round(r, 2), "ok": r >= c["min"]})
    return out


def brand_rules_problems(rules: dict, sources: dict) -> list[str]:
    """What's wrong with the rules file's `brand`: a default or pair naming no role, a minimum that isn't a ratio."""
    b = rules.get("brand")
    if not isinstance(b, dict):
        return ["brand: {defaults, roles, contrast, font, image}"]
    out = [f"brand: source {s!r} is not in `sources`" for s in (b.get("source"), (b.get("font") or {}).get("source")) if s not in sources]
    d = b.get("defaults") or {}
    if sorted(d) != sorted(PALETTE_ROLES) or not all(isinstance(v, str) and HEX.match(v) for v in d.values()):
        out.append(f"brand.defaults: a hex colour for each role, {', '.join(PALETTE_ROLES)}")
    c = b.get("contrast") or {}
    if not (isinstance(c.get("min"), (int, float)) and 1 < c["min"] <= 21):
        out.append("brand.contrast.min: a ratio between 1 and 21")
    for i, p in enumerate(c.get("pairs") or [None]):
        if not (isinstance(p, dict) and p.get("fg") in PALETTE_ROLES and p.get("bg") in PALETTE_ROLES and p["fg"] != p["bg"]
                and isinstance(p.get("label"), str) and isinstance(p.get("styles"), str)):
            out.append(f"brand.contrast.pairs[{i}]: {{fg, bg: two roles, label, styles}}")
    f = b.get("font") or {}
    for k in ("size", "lineHeight", "letterSpacing"):
        if not (isinstance(f.get(k), list) and len(f[k]) == 2 and all(_number(x) for x in f[k]) and f[k][0] < f[k][1]):
            out.append(f"brand.font.{k}: [min, max]")
    for k, names in (("align", ["left", "center", "right"]), ("valign", ["top", "middle", "bottom"])):
        if f.get(k) != names:
            out.append(f"brand.font.{k}: {names}")
    for s in rules.get("styles") or []:
        if isinstance(s, dict) and s.get("axis") == "layout" and not (isinstance(s.get("valign"), list) and "top" in s["valign"]
                                                                     and set(s["valign"]) <= set(f.get("valign") or [])):
            out.append(f"styles {s.get('id')}: valign, where the layout can put the caption block: top and others of brand.font.valign")
    return out


# listing.brand.font: the caption's family and its typography (the page's Typography section; kits/shot.css reads them
# as the --bd-*-caption tokens). The rules' brand.font bounds the numbers and names the alignments
FONT_KEYS = ("family", "weight", "italic", "source", "fsType", "size", "lineHeight", "letterSpacing", "align", "valign")


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def caption_font_problems(font, rules: dict) -> list[tuple[str, str]]:
    """(key, message) for what's wrong with listing.brand.font (key '' : the whole of it); [] for None. family: a name
    without quotes or ; { } < > \\; weight 100-900 by 100; italic a boolean; size a scale of each style's caption size
    (1: the kit's); lineHeight a multiple of the size (absent: the style's own); letterSpacing % of the size; align and
    valign (where the caption block sits) the rules' names."""
    if font is None:
        return []
    if not (isinstance(font, dict) and isinstance(font.get("family"), str) and FONT_FAMILY.match(font["family"])):
        return [("", "{family, …}: a family name without quotes or ; { } < > \\")]
    r, out = rules["brand"]["font"], []
    out += [(k, f"no font key '{k}': {', '.join(FONT_KEYS)}") for k in font if k not in FONT_KEYS]
    if font.get("weight") is not None and font["weight"] not in range(100, 1000, 100):
        out.append(("weight", "a weight 100-900, by 100"))
    if font.get("italic") is not None and not isinstance(font["italic"], bool):
        out.append(("italic", "true or false"))
    for k, what in (("size", "a scale of the style's caption size (1: as the kit draws it)"),
                    ("lineHeight", "a multiple of the size (absent: the style's own)"), ("letterSpacing", "% of the size")):
        lo, hi = r[k]
        if font.get(k) is not None and not (_number(font[k]) and lo <= font[k] <= hi):
            out.append((k, f"{what}, {lo} to {hi}"))
    for k in ("align", "valign"):
        if font.get(k) is not None and font[k] not in r[k]:
            out.append((k, f"{font[k]!r}: one of {', '.join(r[k])}"))
    return out


def caption_tokens(font, rules: dict) -> dict[str, str]:
    """The caption tokens a valid listing.brand.font sets on a shot's :root (kits/shot.js `brand` sets the same from
    the page): --bd-font-caption (the family, then Inter), --bd-weight-caption, --bd-style-caption (italic),
    --bd-size-caption (unitless scale), --bd-leading-caption (unitless), --bd-tracking-caption (em: letterSpacing / 100),
    --bd-align-caption (left|center|right) and --bd-valign-caption (top|middle|bottom). A key it leaves out keeps the
    kit's default (kits/shot.css); an invalid font sets none."""
    if not isinstance(font, dict) or caption_font_problems(font, rules):
        return {}
    out = {"--bd-font-caption": f'"{font["family"]}", Inter, system-ui, sans-serif'}
    if font.get("weight") is not None:
        out["--bd-weight-caption"] = str(font["weight"])
    if font.get("italic"):
        out["--bd-style-caption"] = "italic"
    if font.get("size") is not None:
        out["--bd-size-caption"] = f"{font['size']:g}"
    if font.get("lineHeight") is not None:
        out["--bd-leading-caption"] = f"{font['lineHeight']:g}"
    if font.get("letterSpacing") is not None:
        out["--bd-tracking-caption"] = f"{font['letterSpacing'] / 100:g}em"
    for k in ("align", "valign"):
        if font.get(k) is not None:
            out[f"--bd-{k}-caption"] = font[k]
    return out


def font_embedding(fs_type: int) -> str | None:
    """Why a font's OS/2 fsType keeps a PDF from embedding it (OT-FSTYPE), or None: bitmap only (bit 9), or
    restricted (2) without the preview & print (4) or editable (8) bits."""
    if fs_type & 0x200:
        return "bitmap only"
    if fs_type & 0xF and not fs_type & 0xC:
        return "restricted embedding"
    return None


def effective_style(lb: dict, platform: str, a: dict | None = None, variant: dict | None = None) -> dict[str, str]:
    """The message and layout a platform page shows: M1 and L1, the listing's, its platform's, the variant's
    (variant_style), then the shot's own."""
    out = {"message": "m1", "layout": "l1"}
    st = lb.get("style") if isinstance(lb.get("style"), dict) else {}
    for src in (st, st.get(platform), variant, (a or {}).get("style")):
        if isinstance(src, dict):
            out.update({k: v for k, v in src.items() if k in ("message", "layout") and isinstance(v, str)})
    return out


# ---------- variants (M5): custom pages and A/B tests ----------
# listing.variants[]: {id, platform, kind: cpp|ppo|csl|sle, title, swap: {default shot: its shot}, order: {set: [ids]},
# style: {message, layout}, text: {locale: {field: text}}, locale (an SLE's language: a localized experiment),
# adGroup (a CPP's Apple Ads ad group)}. A variant changes only what its kind's rule `varies`; the rest is the default
# page's. A shot with `variantOf` is a variant's own shot: it shows only where a swap puts it.

AB_LAYOUT = "l5"   # an A/B treatment's layout unless it names one (the plan's style-ab pick: L5 lifestyle)


def variants_of(lb: dict, platform: str | None = None) -> list[dict]:
    """The listing's variants with an id (of a platform)."""
    vs = lb.get("variants") if isinstance(lb, dict) and isinstance(lb.get("variants"), list) else []
    return [v for v in vs if isinstance(v, dict) and isinstance(v.get("id"), str) and (platform is None or v.get("platform") == platform)]


def variant_rule(rules: dict, v: dict) -> dict | None:
    return next((r for r in rules.get("variants") or [] if r["kind"] == v.get("kind") and r["platform"] == v.get("platform")), None)


def variant_style(rules: dict, v: dict | None) -> dict[str, str]:
    """What a variant puts over the platform's style: L5 for an A/B treatment (AB_LAYOUT), then its own style."""
    if not isinstance(v, dict):
        return {}
    out = {"layout": AB_LAYOUT} if (variant_rule(rules, v) or {}).get("ab") else {}
    st = v.get("style") if isinstance(v.get("style"), dict) else {}
    out.update({k: s for k, s in st.items() if k in ("message", "layout") and isinstance(s, str)})
    return out


def variant_text_fields(rules: dict, v: dict) -> set[str]:
    """The store text fields a variant's kind may change: its rule's `varies` that are text fields of its platform."""
    r = variant_rule(rules, v) or {}
    return set(r.get("varies") or []) & set(text_rules(rules, v.get("platform")))


def variant_changes(lb: dict, arts: list, rules: dict, v: dict, locale: str | None) -> list[str]:
    """What a variant changes against the default page in a locale: its swaps that show, the sets whose order differs
    beyond them, the style and the text fields it sets. The page's "N changes" (template.html variantChanges)."""
    p = v.get("platform")
    out = []
    base = {x["set"]: x["shots"] for r in sections(lb, arts, rules, p, locale) for x in r["sets"]}
    mine = {x["set"]: x["shots"] for r in sections(lb, arts, rules, p, locale, v) for x in r["sets"]}
    shown = {i for ids in mine.values() for i in ids}
    shots = {a.get("id") for a in arts if isinstance(a, dict) and a.get("device") == "shot"}
    swap = {k: s for k, s in v["swap"].items() if isinstance(s, str) and s in shots} if isinstance(v.get("swap"), dict) else {}
    out += [f"{a} → {b}" for a, b in swap.items() if b in shown]
    for s, ids in mine.items():
        if list(dict.fromkeys(swap.get(i, i) for i in base.get(s, []))) != ids:
            out.append(f"{s} order")
    a, b = effective_style(lb, p), effective_style(lb, p, variant=variant_style(rules, v))
    out += [f"{k} {b[k]}" for k in ("message", "layout") if a[k] != b[k]]
    text = v.get("text") if isinstance(v.get("text"), dict) else {}
    mine_t = text.get(locale) if isinstance(text.get(locale), dict) else {}
    out += [f"{f} text" for f in mine_t if f in text_rules(rules, p)]
    return out


def validate_variants(rep, lw: str, lb: dict, arts: list, rules: dict, plats: list, locs: list, style_ok) -> None:
    """listing.variants' shape: ids, a kind of its platform, swaps from a shot of the default page to a shot, orders
    of the platform's sets, a style, text fields of its platform per locale, an SLE's locale, a CPP's adGroup. What a
    kind may change and how many there may be are store rules: store_checks."""
    if "variants" not in lb:
        return
    vs = lb["variants"]
    if not isinstance(vs, list):
        rep.err(lw + ".variants", "a list of variants: {id, platform, kind, title, swap, order, style, text}")
        return
    shots = {a["id"]: a for a in arts if a.get("device") == "shot"}
    sets = by_id(rules, "sets")
    seen: set[str] = set()
    for i, v in enumerate(vs):
        vw = f"{lw}.variants[{i}]"
        if not isinstance(v, dict) or not isinstance(v.get("id"), str) or not ID_RE.match(v["id"]) or v["id"] in seen:
            rep.err(vw, "an id of a-z, 0-9 and -, once each")
            continue
        seen.add(v["id"])
        r = variant_rule(rules, v)
        if r is None or v.get("platform") not in plats:
            rep.err(vw, "a platform of the listing and a kind of it: " + ", ".join(f"{x['kind']} ({x['platform']})" for x in rules["variants"]))
            continue
        p = r["platform"]
        for k in v:
            if k not in ("id", "platform", "kind", "title", "swap", "order", "style", "text", "locale", "adGroup"):
                rep.err(f"{vw}.{k}", "a variant has id, platform, kind, title, swap, order, style, text, locale and adGroup")
        if "title" in v and not (isinstance(v["title"], str) and 0 < len(v["title"]) <= 60):
            rep.err(vw + ".title", "1-60 characters: the tab's name")
        swap = v.get("swap", {})
        if not isinstance(swap, dict):
            rep.err(vw + ".swap", "{default shot id: the shot that takes its place}")
            swap = {}
        for a, b in swap.items():
            src = shots.get(a)
            if src is None or isinstance(src.get("variantOf"), str) or not any((sets.get(s) or {}).get("platform") == p for s in src.get("sets") or []):
                rep.err(f"{vw}.swap.{a}", f"'{a}' is no shot of the default {p} page")
            elif not (isinstance(b, str) and b in shots):
                rep.err(f"{vw}.swap.{a}", f"{b!r} is no shot on this board")
            else:
                need = [s for s in src.get("sets") or [] if (sets.get(s) or {}).get("platform") == p]
                gone = [s for s in need if s not in (shots[b].get("sets") or [])]
                if gone:
                    rep.err(f"{vw}.swap.{a}", f"'{b}' takes {a}'s place in {', '.join(need)}: add {', '.join(gone)} to its sets")
        order = v.get("order", {})
        if not isinstance(order, dict):
            rep.err(vw + ".order", "{set: [shot ids]}")
            order = {}
        for s, ids in order.items():
            if (sets.get(s) or {}).get("platform") != p or not isinstance(ids, list) or not all(isinstance(x, str) and x in shots for x in ids) \
                    or len(set(ids)) != len(ids):
                rep.err(f"{vw}.order.{s}", f"a {p} set and its shots' ids, each once")
        style_ok(vw + ".style", v.get("style"))
        text = v.get("text", {})
        fields = text_rules(rules, p)
        if not isinstance(text, dict) or not all(loc in locs and isinstance(per, dict) for loc, per in text.items()):
            rep.err(vw + ".text", f"{{locale: {{field: text}}}} for locales of {locs}")
        else:
            for loc, per in text.items():
                for f, s in per.items():
                    if f not in fields or fields[f].get("group") != "listing" or not isinstance(s, str):
                        rep.err(f"{vw}.text.{loc}.{f}", f"a {p} store text field and its text: "
                                + ", ".join(k for k, x in fields.items() if x.get("group") == "listing"))
        if "locale" in v and (r.get("textIn") != "locale" or v["locale"] not in locs):
            rep.err(vw + ".locale", f"an SLE's language (a localized experiment), one of {locs}" if r.get("textIn") == "locale"
                    else f"a {r['label'].lower()} covers every locale: leave locale out")
        if "adGroup" in v and not (r.get("adGroup") and isinstance(v["adGroup"], str) and 0 < len(v["adGroup"]) <= 100):
            rep.err(vw + ".adGroup", "a custom product page's Apple Ads ad group, 1-100 characters" if r.get("adGroup")
                    else "only a custom product page has an Apple Ads ad group")
    swapped = {b for v in vs if isinstance(v, dict) and isinstance(v.get("swap"), dict) for b in v["swap"].values() if isinstance(b, str)}
    for a in shots.values():
        if isinstance(a.get("variantOf"), str) and a["id"] not in swapped:
            rep.warn(f"artboard '{a['id']}'", "a variant's shot no variant swaps in: it shows on no page (listing.variants[].swap)")


def _shot_html(a: dict, doc_path: Path | None) -> str:
    if doc_path is None or is_image_shot(a):
        return ""
    f = Path(doc_path).parent / str(a.get("src") or f"{doc_stem(Path(doc_path))}.design/{a['id']}.html")
    try:
        return f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def validate_brand_style(rep, lw: str, lb: dict, doc: dict, doc_path: Path | None, rules: dict) -> None:
    """Warnings on the brand and the picks: a contrast pair under the rules' minimum (WCAG 2.2 1.4.3; the shot kit's
    text pairs, named by what they draw), a caption font a PDF can't embed, and per platform page what its style needs
    from the agent: a data-callout (M3), shot 1's proof string (M4, App Store), a video (M5), a lifestyle photo and its
    rights in the shot's `credits` (L5); M4 on Play is use-case first, as Play bans awards and testimonials in shots."""
    brand = lb.get("brand") if isinstance(lb.get("brand"), dict) else {}
    pal = brand.get("palette")
    if pal is None or isinstance(pal, dict) and all(isinstance(v, str) and HEX.match(v) for v in pal.values()):
        mn = rules["brand"]["contrast"]["min"]
        for p in contrast_report(brand_palette(lb, rules), rules):
            if not p["ok"]:
                rep.warn(lw + ".brand.palette", f"{p['label']} ({p['styles']}): {p['fg']} on {p['bg']} is {p['ratio']:.2f}:1, "
                                                f"under {mn}:1 (WCAG22 1.4.3): a darker or lighter {p['fg']} or {p['bg']}")
    font = brand.get("font") if isinstance(brand.get("font"), dict) else {}
    if "fsType" in font:
        if not (isinstance(font["fsType"], int) and 0 <= font["fsType"] <= 0xFFFF):
            rep.err(lw + ".brand.font.fsType", "the font's OS/2 fsType, an integer (fonts.py reads it)")
        elif font_embedding(font["fsType"]):
            rep.warn(lw + ".brand.font", f"{font.get('family')}: {font_embedding(font['fsType'])} (fsType {font['fsType']}, "
                                         "OT-FSTYPE): the PNGs render it, a PDF export can't embed it")
    if "source" in font and font["source"] not in ("system", "vendored"):
        rep.err(lw + ".brand.font.source", "system (installed on this Mac) or vendored (Inter)")
    arts = shots_of(doc)
    by = {a["id"]: a for a in arts}
    strings = lb.get("strings") if isinstance(lb.get("strings"), dict) else {}
    base = strings.get(lb.get("defaultLocale")) if isinstance(strings.get(lb.get("defaultLocale")), dict) else {}
    sets = by_id(rules, "sets")
    video = lb.get("video") if isinstance(lb.get("video"), dict) else {}
    hooks: dict[str, list[str]] = {}
    for p in lb.get("platforms") or []:
        if p not in ("play", "appstore"):
            continue
        groups = [s for r in sections(lb, arts, rules, p, lb.get("defaultLocale")) for s in r["sets"]
                  if not (sets.get(s["set"]) or {}).get("raw") and s["shots"]]
        ids = list(dict.fromkeys(i for s in groups for i in s["shots"] if i in by))
        if not ids:
            continue
        for i in ids:
            if i not in hooks:
                hooks[i] = style_hooks(_shot_html(by[i], doc_path))
        where = f"{lw}.style.{p}"
        used = {(k, effective_style(lb, p, by[i])[k]) for i in ids for k in ("message", "layout")}
        if ("message", "m3") in used and not any("callout" in hooks[i] for i in ids if effective_style(lb, p, by[i])["message"] == "m3"):
            rep.warn(where, "M3 zoomed callout needs the agent: mark the element to enlarge with data-callout in a shot's UI")
        if ("message", "m4") in used:
            if p == "play":
                rep.warn(where, "M4 on Google Play is use-case first: shot 1's caption names the job; Play bans awards, "
                                "testimonials and ranking in shots (G-PA)")
            elif not any(f"{s['shots'][0]}.proof" in base for s in groups):
                rep.warn(where, "M4 social proof needs the agent: the string <shot>.proof (a rating, award or quote) for shot 1")
        if ("message", "m5") in used and not (video.get("play") if p == "play" else video.get("appstore")):
            rep.warn(where, "M5 video-first needs the agent: " + ("listing.video.play, a YouTube video" if p == "play" else "an app preview in listing.video.appstore"))
        if ("layout", "l5") in used:
            l5 = [i for i in ids if effective_style(lb, p, by[i])["layout"] == "l5"]
            if not any("photo" in hooks[i] for i in l5):
                rep.warn(where, "L5 lifestyle needs the agent: a photo (img.shot-photo) in the shots; a drawn figure stands in")
            for i in l5:
                if "photo" in hooks[i] and not (isinstance(by[i].get("credits"), str) and by[i]["credits"].strip()):
                    rep.warn(f"artboard {i}.credits", "a lifestyle photo needs a rights note in the shot's credits (A-ARG 2.3.9)")
        valign = font.get("valign")
        if valign in rules["brand"]["font"]["valign"] and valign != "top":
            styles = by_id(rules, "styles")
            off = sorted({effective_style(lb, p, by[i])["layout"] for i in ids} - {s for s in styles if valign in styles[s].get("valign", [])})
            if off:
                rep.warn(lw + ".brand.font.valign", f"{', '.join(x.upper() for x in off)} on {p} puts the caption at the top, "
                                                    f"not {valign} (store-rules.json styles[].valign)")


def brand_image_type(data: bytes) -> str | None:
    """png, jpeg or webp from an image's first bytes, or None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def style_page_data(hooks: dict[str, list[str]]) -> dict:
    """What the Style pane reads beside the rules: each shot's hooks and the thumbnails' SVG."""
    try:
        thumbs = THUMBS_PATH.read_text(encoding="utf-8")
    except OSError:
        thumbs = ""
    return {"hooks": hooks, "thumbs": thumbs}


# ---------- store checks, translation and export (M4) ----------
# store_checks() is the build's report on a listing against the store rules, beyond the doc's shape: text limits and
# words, keywords, set counts and required sets, PNG sizes and alpha, Wear's UI-only rule, the Apple Watch's one size,
# locales that fall back, MT strings, mock-up UI, the caption font and the variants. Each finding names its platforms,
# set, locales and source key; one from a rule marked `unverified` only warns. build.Report.finding keeps them apart
# from the doc's own errors, so serve.py still draws a listing whose only errors are these, and its Checks tab lists
# them. l10n_*: `build.py l10n`. export_plan and png_rgb24: the fastlane ZIP of `build.py --listing` and
# GET /__bluedoc/listing (serve.py renders the PNGs).

EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF]")
CAPS = re.compile(r"\b[A-Z]{4,}\b")   # a shouted word; acronyms of up to 3 letters pass
REPEAT_PUNCT = re.compile(r"[!?]{2,}")
HTML_TAG = re.compile(r"<[A-Za-z/!][^>]*>")
PRICE = re.compile(r"[$€£¥]\s?\d|\d\s?[$€£¥]|\b(?:free|gratis)\b", re.I)
RAW_FRAME = re.compile(r"(?:^|-)(?:bezel|device)(?:-|$)")   # a class naming a device frame
MASK = re.compile(r"clip-path\s*:|(?<![\w-])mask(?:-image)?\s*:", re.I)
BACKGROUND = re.compile(r"background(?:-color)?\s*:\s*([^;\"'}]+)", re.I)


def _obj(v) -> dict:
    return v if isinstance(v, dict) else {}


def _finding(level: str, msg: str, *, source: str | None = None, platforms=(), set_id: str | None = None, locales=(),
             section: str | None = None, key: str | None = None, rule: dict | None = None, check: str | None = None) -> dict:
    """One check's result: {level: err|warn, where, msg, source, platforms, set, locales, section, key}. An error from
    a rule marked `unverified` is a warning with the note, unless the rule's `unverifiedFor` names other checks (count,
    required, size, bytes, raw, guide) than this one."""
    if rule and rule.get("unverified") and level == "err" and (not rule.get("unverifiedFor") or check in rule["unverifiedFor"]):
        level, msg = "warn", f"{msg} [unverified: {rule['unverified']}]"
    where = " · ".join([*([set_id] if set_id else platforms), *([", ".join(locales)] if locales else [])]) or "listing"
    return {"level": level, "where": where, "msg": f"{msg} ({source})" if source else msg, "source": source,
            "platforms": list(platforms), "set": set_id, "locales": list(locales), "section": section, "key": key}


def _hits(text: str, words) -> list[str]:
    t = text.lower()
    return [w for w in words if re.search(r"(?<!\w)" + re.escape(w.lower()) + r"(?!\w)", t)]


def _see_through(value: str) -> bool:
    """Whether a CSS background value lets what's under it show: transparent, or a colour with alpha under 1."""
    v = value.lower()
    if "transparent" in v:
        return True
    for m in re.finditer(r"(?:rgba?|hsla?)\(([^)]*)\)", v):
        parts = [x for x in re.split(r"[\s,/]+", m[1].strip()) if x]
        if len(parts) == 4:
            a = parts[3]
            try:
                if (float(a[:-1]) / 100 if a.endswith("%") else float(a)) < 1:
                    return True
            except ValueError:
                pass
    return any(len(h) in (4, 8) and h[-(len(h) // 4):] not in ("f", "ff") for h in re.findall(r"#([0-9a-f]{3,8})\b", v))


class _RawLint(HTMLParser):
    """What a Wear shot's HTML draws beside the UI: a caption, a device frame, a mask, a see-through background."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[str] = []
        self.css: list[str] = []
        self._style = False

    def handle_starttag(self, tag, attrs) -> None:
        d = {k: v or "" for k, v in attrs}
        cls = d.get("class", "").split()
        if {"shot-cap", "shot-sub"} & set(cls) and "a caption" not in self.found:
            self.found.append("a caption")
        if any(RAW_FRAME.search(c) for c in cls) and "a device frame" not in self.found:
            self.found.append("a device frame")
        self.css.append(d.get("style", ""))
        self._style = tag == "style"

    def handle_data(self, data) -> None:
        if self._style:
            self.css.append(data)

    def handle_endtag(self, tag) -> None:
        self._style = False

    def problems(self) -> list[str]:
        css = "\n".join(self.css)
        out = list(self.found)
        if MASK.search(css):
            out.append("a mask")
        if any(_see_through(v) for v in BACKGROUND.findall(css)):
            out.append("a see-through background")
        return out


def _required(rule: dict, counts: dict[str, int], lb: dict) -> tuple[bool, str]:
    """Whether a set needs shots in this listing, and why."""
    r = str(rule.get("required") or "never")
    if r in ("always", "row"):
        return True, "the store requires it"
    if r.startswith("either:"):
        ids = r[7:].split("|")
        return not any(counts.get(i) for i in ids), f"one of {' or '.join(ids)} needs shots"
    if r == "if:ipad":
        return lb.get("ipad") is True, "the app runs on iPad (listing.ipad)"
    if r == "if:watchFace":
        return lb.get("watchFace") is True, "the app is a watch face (listing.watchFace)"
    return False, "optional"


def _png_head(f: Path) -> tuple[dict | None, int]:
    try:
        with open(f, "rb") as fh:
            head = fh.read(65536)
        return png_info(head), f.stat().st_size
    except OSError:
        return None, 0


def _shown_size(a: dict, rule: dict, doc_path: Path | None) -> tuple[int, int]:
    """A shot's store size in a set: an upload's PNG size, else the set's authored size (a layout renders at it)."""
    if doc_path is not None and is_image_shot(a):
        info = _png_head(Path(doc_path).parent / a["src"])[0]
        if info:
            return info["w"], info["h"]
    return tuple(rule["author"])


def capture_fits(c: dict, rule: dict) -> bool:
    """Whether a web capture fills a set: its aspect is within 5% of the set's UI viewport's, so a phone capture
    stays out of a tablet's slot (that set shows the mock-up). A capture without its size (an earlier rev's) fits."""
    w, h = c.get("w"), c.get("h")
    if not (isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0):
        return True
    uw, uh = ui_size(rule)
    return abs((w / h) / (uw / uh) - 1) <= 0.05


def capture_for(caps: dict, a: dict, rule: dict, locale: str, default: str | None) -> dict | None:
    """The capture a shot shows in a set for a locale, as the page's captureFor picks it: the set's target, then a web
    capture that fits the set (capture_fits); the locale's, else the default locale's. {file, w, h, fresh, …, target,
    locale} or None."""
    per = caps.get(a["id"]) or {}
    targets = list(dict.fromkeys(t for t in (rule.get("target"), "web") if t))
    for loc in dict.fromkeys(x for x in (locale, default) if x):
        for t in targets:
            c = (per.get(t) or {}).get(loc)
            if c and (t == rule.get("target") or capture_fits(c, rule)):
                return {**c, "target": t, "locale": loc}
    return None


def store_checks(doc: dict, doc_path: Path | None, rules: dict | None = None, today: dt.date | None = None) -> list[dict]:
    """The listing against the store rules (the table in references/schema.md `### Checks`): a list of _finding()s,
    errors first. Files (uploads, captures, screen HTML, the icon) are read only with doc_path."""
    rules = rules or load_rules()
    today = today or dt.date.today()
    lb = listing_of(doc)
    if not isinstance(lb, dict):
        return []
    out: list[dict] = []
    add = lambda level, msg, **kw: out.append(_finding(level, msg, **kw))  # noqa: E731
    known_p = {p["id"]: p for p in rules["platforms"]}
    plats = [p for p in lb.get("platforms") or [] if p in known_p]
    locs = [x for x in lb.get("locales") or [] if isinstance(x, str)]
    default = lb.get("defaultLocale") if lb.get("defaultLocale") in locs else (locs[0] if locs else None)
    text, strings, mt = _obj(lb.get("text")), _obj(lb.get("strings")), _obj(lb.get("mt"))
    app = _obj(lb.get("app"))
    names = [n.lower() for n in (app.get("name"), app.get("company")) if isinstance(n, str) and n.strip()]
    terms = {t["id"]: t for t in rules.get("terms") or []}
    sets, assets = by_id(rules, "sets"), by_id(rules, "assets")
    arts = shots_of(doc)
    by = {a["id"]: a for a in arts}
    rows_on = lb.get("rows") if isinstance(lb.get("rows"), list) else [r["id"] for r in rules["rows"] if r.get("core")]
    caps = captures(doc, doc_path) if doc_path is not None else {}

    # store text: limits in every locale, MT or not; words each field's rule lists
    for loc in locs:
        for p in plats:
            fields = _obj(_obj(text.get(loc)).get(p))
            rs = text_rules(rules, p)
            for f, v in fields.items():
                r = rs.get(f)
                if r is None:
                    continue
                kw = {"platforms": [p], "locales": [loc], "section": "text", "key": f"field:{loc}/{p}/{f}"}
                is_mt = f"{p}.{f}" in (mt.get(loc) or [])
                for s in (v if isinstance(v, list) else [v]):
                    if not isinstance(s, str):
                        continue
                    n = text_count(s, r["unit"])
                    if n > r["limit"]:
                        add("warn" if r.get("level") == "warn" else "err", f"{r['label']}: {n} / {r['limit']} {r['unit']}"
                            + (" after machine translation" if is_mt else ""), source=r["source"], rule=r, check="limit", **kw)
                    elif r.get("min") and n < r["min"]:
                        add("err", f"{r['label']}: {n} {r['unit']}, at least {r['min']}", source=r["source"], rule=r, check="limit", **kw)
                if "items" in r and isinstance(v, list) and len(v) > r["items"][1]:
                    add("err", f"{r['label']}: {len(v)} items, at most {r['items'][1]}", source=r["source"], rule=r, check="count", **kw)
                for s in (v if isinstance(v, list) else [v]):
                    if not isinstance(s, str):
                        continue
                    checks = r.get("checks") or []
                    if "keyword-min" in checks or "no-app-name" in checks or "no-repeats" in checks:
                        kws = [k.strip() for k in s.split(",")]
                        short = [k for k in kws if 0 < len(k) <= 2]
                        if short and "keyword-min" in checks:
                            add("err", f"keywords of 2 characters or fewer: {', '.join(short)}", source=r["source"], **kw)
                        named = [k for k in kws if k and any(_hits(k, [nm]) for nm in names)]
                        if named and "no-app-name" in checks:
                            add("err", f"keywords repeat the app's or company's name: {', '.join(named)}", source=r["source"], **kw)
                        seen: set[str] = set()
                        dup = [k for k in kws if k and (k.lower() in seen or seen.add(k.lower()))]
                        if dup and "no-repeats" in checks:
                            add("err", f"repeated keywords: {', '.join(dict.fromkeys(dup))}", source=r["source"], **kw)
                    for c in ("play-terms", "no-cta"):
                        hit = _hits(s, terms.get(c, {}).get("words") or []) if c in checks else []
                        if hit:
                            what = "a call to action" if c == "no-cta" else "words Play bans in store text"
                            add("warn", f"{r['label']}: {what}: {', '.join(hit)}", source=terms[c]["source"], **kw)
                    if "no-emoji" in checks and EMOJI.search(s):
                        add("warn", f"{r['label']}: emoji", source="G-PA", **kw)
                    if "no-caps" in checks and CAPS.search(s):
                        add("warn", f"{r['label']}: words in capitals: {', '.join(dict.fromkeys(CAPS.findall(s)))}", source="G-PA", **kw)
                    if "no-repeat-punct" in checks and REPEAT_PUNCT.search(s):
                        add("warn", f"{r['label']}: repeated punctuation", source="G-PA", **kw)
                    if "no-price" in checks and PRICE.search(s):
                        add("warn", f"{r['label']}: a price: {PRICE.search(s)[0]}", source="A-ARG 2.3.7", **kw)
                    if "no-other-platforms" in checks:
                        hit = _hits(s, terms.get("other-platforms", {}).get("words") or [])
                        if hit:
                            add("warn", f"{r['label']}: another platform: {', '.join(hit)}", source="A-ARG 2.3.10", **kw)
                    if "no-html" in checks and HTML_TAG.search(s):
                        add("warn", f"{r['label']}: HTML tags: the store shows plain text", source=r["source"], **kw)

    # sets: counts and required sets in each locale (an upload may be one locale's), the same finding once across them
    seen_f: dict[tuple, list[str]] = {}

    def per_locale(loc: str, level: str, msg: str, **kw) -> None:
        key = (level, msg, kw.get("set_id"), kw.get("source"), tuple(kw.get("platforms") or ()), kw.get("section"))
        if key not in seen_f:
            seen_f[key] = []
            out.append({"_key": key, "_kw": kw})
        seen_f[key].append(loc)
    by_p_loc: dict[tuple[str, str], dict[str, list[str]]] = {}
    for p in plats:
        for loc in locs or [None]:
            secs = sections(lb, arts, rules, p, loc)
            shots = {x["set"]: x["shots"] for s in secs for x in s["sets"]}
            by_p_loc[(p, loc)] = shots
            counts = {k: len(v) for k, v in shots.items()}
            for r in rules["sets"]:
                if r["platform"] != p or r["row"] not in rows_on or r.get("required") == "dated":
                    continue
                n = counts.get(r["id"], 0)
                req = str(r.get("required") or "")
                if r["id"] not in shots and req not in ("row", "always") and not req.startswith("either:"):
                    continue
                lo, hi = r.get("count") or [0, 10]
                need, why = _required(r, counts, lb)
                kw = {"platforms": [p], "set_id": r["id"], "section": r["row"], "source": r["source"], "rule": r,
                      "key": f"section:{p}/{r['row']}"}
                if n > hi:
                    per_locale(loc, "err", f"{r['label']}: {n} shots, at most {hi}", check="count", **kw)
                elif need and n < max(lo, 1) and (not req.startswith("either:") or req[7:].split("|")[0] == r["id"]):
                    per_locale(loc, "err", f"{r['label']}: {n} shot{'' if n == 1 else 's'}; {why}", check="required", **kw)
                elif 0 < n < lo:
                    per_locale(loc, "err", f"{r['label']}: {n} shot{'' if n == 1 else 's'}, at least {lo}", check="count", **kw)
                elif r.get("recommend") and 0 < n < r["recommend"]["count"]:
                    per_locale(loc, "warn", f"{r['label']}: {n} shot{'' if n == 1 else 's'}; {r['recommend']['note']}",
                               **{**kw, "rule": None})
                elif (r.get("recommend") or {}).get("minSide") and n:
                    big = sum(1 for sid in shots.get(r["id"], []) if min(_shown_size(by.get(sid) or {}, r, doc_path)) >= r["recommend"]["minSide"])
                    if big < r["recommend"]["count"]:
                        per_locale(loc, "warn", f"{r['label']}: {big} shot{'' if big == 1 else 's'} at {r['recommend']['minSide']} px or more; "
                                                f"{r['recommend']['note']}", **{**kw, "rule": None})
            mn = known_p[p].get("minShots")
            total = sum(counts.values())
            if mn and total < mn:
                per_locale(loc, "err", f"{total} shot{'' if total == 1 else 's'} across device types: {known_p[p]['label']} needs {mn}",
                           platforms=[p], source=known_p[p]["source"])
    for i, x in enumerate(out):
        if "_key" in x:
            level, msg = x["_key"][0], x["_key"][1]
            ls = seen_f[x["_key"]]
            out[i] = _finding(level, msg, locales=[y for y in ls if y], **x["_kw"])
    # dated sets: a warning until their date, then an error
    for r in rules["sets"]:
        if r["platform"] in plats and r.get("required") == "dated" and r["row"] in rows_on \
                and not any(r["id"] in (a.get("sets") or []) for a in arts if a.get("device") == "shot"):
            due = dt.date.fromisoformat(r["from"]) <= today
            add("err" if due else "warn", f"{r['label']}: no shots; required from {r['from']}" + (f" ({r['note']})" if r.get("note") else ""),
                source=r["source"], platforms=[r["platform"]], set_id=r["id"], section=r["row"])
    # required assets and the icon
    for r in rules["assets"]:
        if r["platform"] not in plats:
            continue
        req = str(r.get("required") or "never")
        if r.get("from") == "icons":
            if req == "always" and not lb.get("icon"):
                add("err", f"no icon: listing.icon names none ({r['label']})", source=r["source"], platforms=[r["platform"]], section="shared")
            elif req == "always" and doc_path is not None and icon_of(doc, doc_path) is None:
                add("err", f"the icon {lb['icon']} has no readable fg.svg layer ({r['label']})", source=r["source"],
                    platforms=[r["platform"]], section="shared")
            continue
        if "author" in r and (req == "always" or (req.startswith("row:") and req[4:] in rows_on)) \
                and not any(a.get("device") == "asset" and a.get("asset") == r["id"] for a in arts):
            add("err", f"no {r['label'].lower()} ({r['id']}): add an asset artboard", source=r["source"], rule=r, check="required",
                platforms=[r["platform"]], section="shared")

    if doc_path is not None:
        # uploads: their size for each set they fill, no alpha, the byte limit
        for a in arts:
            if not is_image_shot(a) or image_src_problem(a["src"], doc_path):
                continue
            info, size = _png_head(Path(doc_path).parent / a["src"])
            if info is None:
                continue
            for s in a.get("sets") or []:
                r = sets.get(s)
                if r is None:
                    continue
                kw = {"platforms": [r["platform"]], "set_id": s, "locales": [a["locale"]] if isinstance(a.get("locale"), str) else [],
                      "section": r["row"], "key": f"artboard:{a['id']}"}
                why = size_problem(r, info["w"], info["h"])
                if why:
                    add("err", f"upload {a['src']} is {info['w']}×{info['h']}: want {why}", source=r["source"], rule=r, check="size", **kw)
                if info["colour"] in (4, 6) or info["trns"]:
                    add("err", f"upload {a['src']} has an alpha channel: the stores refuse transparency", source=r["source"], **kw)
                plat = known_p[r["platform"]]
                limit = r.get("maxBytes") or plat.get("maxBytes")
                if limit and size > limit:
                    add("err", f"upload {a['src']}: {size / 1048576:.1f} MB, at most {limit // 1048576} MB", source=plat["source"],
                        rule=r if r.get("maxBytes") else plat, check="bytes", **kw)
        # captures: no alpha; a raw set's capture is the shot itself, so its size is the set's
        for sid, per in caps.items():
            a = by.get(sid)
            if a is None:
                continue
            for t, by_loc in per.items():
                raw = [sets[s] for s in a.get("sets") or [] if s in sets and sets[s].get("raw") and sets[s].get("target") == t]
                for loc, c in by_loc.items():
                    info, _ = _png_head(Path(doc_path).parent / c["file"])
                    if info is None:
                        continue
                    kw = {"locales": [loc], "key": f"artboard:{sid}"}
                    if info["colour"] in (4, 6) or info["trns"]:
                        add("err", f"capture {c['file']} has an alpha channel: re-shoot it", source="A-SS", **kw)
                    for r in raw:
                        why = size_problem(r, info["w"], info["h"])
                        if why:
                            add("err", f"the {t} capture of {sid} is {info['w']}×{info['h']}: want {why}; re-shoot it on "
                                       f"{target_device(lb, rules, t)}", source=r["source"], rule=r, check="size", platforms=[r["platform"]],
                                set_id=r["id"], section=r["row"], **kw)
        # Wear OS shots are the UI alone
        for a in arts:
            wear = [s for s in a.get("sets") or [] if s in sets and sets[s].get("raw") and sets[s]["platform"] == "play"]
            if not wear or is_image_shot(a):
                continue
            lint = _RawLint()
            lint.feed(_shot_html(a, doc_path))
            lint.close()
            for what in lint.problems():
                add("err", f"{a['id']} draws {what}: Wear OS shots show the UI only", source="G-PA", platforms=["play"], locales=locs,
                    set_id=wear[0], section="watch", key=f"artboard:{a['id']}")

    # one size in every locale (Apple Watch)
    for r in rules["sets"]:
        if not r.get("oneSize") or r["platform"] not in plats:
            continue
        per_loc: dict[str, set[tuple[int, int]]] = {}
        for loc in locs:
            got: set[tuple[int, int]] = set()
            for sid in by_p_loc.get((r["platform"], loc), {}).get(r["id"], []):
                a = by.get(sid) or {}
                img = _png_head(Path(doc_path).parent / a["src"])[0] if doc_path is not None and is_image_shot(a) else None
                cap = capture_for(caps, a, r, loc, default) if not img else None
                got.add((img["w"], img["h"]) if img else (cap["w"], cap["h"]) if cap and cap.get("w") else tuple(r["author"]))
            per_loc[loc] = got
        if len(set().union(*per_loc.values()) if per_loc else set()) > 1:
            add("err", f"{r['label']}: one size in every locale; " + "; ".join(f"{loc} " + ", ".join(f"{w}×{h}" for w, h in sorted(v))
                                                                          for loc, v in per_loc.items()),
                source=r["source"], platforms=[r["platform"]], set_id=r["id"], section=r["row"])

    # locales: text, captions and captures that fall back to the default locale
    used = {}   # caption key -> the shots that show it
    for a in arts:
        if a.get("device") in ("shot", "asset") and not is_image_shot(a):
            for k in l10n_keys(_shot_html(a, doc_path)) if doc_path is not None else []:
                used.setdefault(k, []).append(a["id"])
    for loc in locs:
        if loc == default:
            continue
        for p in plats:
            base, mine = _obj(_obj(text.get(default)).get(p)), _obj(_obj(text.get(loc)).get(p))
            rs = text_rules(rules, p)
            gone = [rs[f]["label"].lower() for f in base if f not in mine and f in rs and rs[f].get("group") == "listing"]
            if gone:
                add("warn", f"{loc} has no {', '.join(gone)}: the store shows {default}'s", source="G-TR" if p == "play" else "A-LOC",
                    platforms=[p], locales=[loc], section="text")
        miss = [k for k in used if k in _obj(strings.get(default)) and k not in _obj(strings.get(loc))
                and any(not isinstance(by[i].get("locale"), str) or by[i]["locale"] == loc for i in used[k])]
        if miss:
            add("warn", f"{len(miss)} caption string{' falls' if len(miss) == 1 else 's fall'} back to {default}: {', '.join(miss)}",
                locales=[loc], section="text", key=f"field:{loc}/strings/{miss[0]}")
        fb = [sid for sid, per in caps.items() if sid in by and any(default in v and loc not in v for v in per.values())]
        if fb:
            add("warn", f"{', '.join(fb)} show{'s' if len(fb) == 1 else ''} the {default} capture: no {loc} capture yet",
                locales=[loc], key=f"artboard:{fb[0]}")
        n = len(mt.get(loc) or [])
        if n:
            add("warn", f"{n} machine-translated string{'' if n == 1 else 's'} not accepted yet: "
                        f"{', '.join(mt[loc][:6])}{', …' if n > 6 else ''}", locales=[loc], section="text")
    if default and mt.get(default):
        add("warn", f"{len(mt[default])} machine-translated string(s) not accepted yet", locales=[default], section="text")

    # mock-up UI (A-ARG 2.3.3): shots with no capture or upload, and sets no capture fits (another aspect: a phone
    # capture in a tablet set), where captured shots show their mock-up; social proof in Play's shots (G-PA)
    for p in plats:
        on = by_p_loc.get((p, default), {})
        ids = list(dict.fromkeys(i for i in (x for shots in on.values() for x in shots)))
        bare = [i for i in ids if i in by and not is_image_shot(by[i]) and not caps.get(i)]
        unfit = {s: [i for i in shots if i in by and caps.get(i) and not is_image_shot(by[i])
                     and capture_for(caps, by[i], sets[s], default, default) is None] for s, shots in on.items() if s in sets}
        unfit = {s: v for s, v in unfit.items() if v}
        if bare or unfit:
            msg = [f"{len(bare)} shot{'s show' if len(bare) != 1 else ' shows'} mock-up UI, no capture or upload: {', '.join(bare)}"] if bare else []
            if unfit:
                msg.append(f"no capture fits {', '.join(sets[s]['label'] for s in unfit)} (another aspect), so "
                           f"{', '.join(dict.fromkeys(i for v in unfit.values() for i in v))} show their mock-up there")
            add("warn", "; ".join(msg) + "; the stores want the app in use", source="A-ARG 2.3.3", platforms=[p],
                key=f"artboard:{(bare or next(iter(unfit.values())))[0]}")
        if p != "play":
            continue
        shown = ids + [a["id"] for a in arts if a.get("device") == "asset" and a.get("asset") == "play/feature"]
        words = terms.get("social-proof", {}).get("words") or []
        for sid in shown:
            keys = [k for k, v in used.items() if sid in v] + [f"{sid}.proof"]
            hit = sorted({w for loc in locs for k in keys for w in _hits(str(_obj(strings.get(loc)).get(k) or ""), words)})
            if hit:
                add("warn", f"{sid}: social proof in a Play graphic: {', '.join(hit)}", source="G-PA", platforms=["play"],
                    key=f"artboard:{sid}")

    # the caption font: installed here (a vendored Inter needs nothing)
    font = _obj(_obj(lb.get("brand")).get("font"))
    fam = font.get("family")
    if isinstance(fam, str) and fam != rules["brand"]["font"]["default"] and font.get("source") != "vendored":
        try:
            import fonts   # noqa: PLC0415 — the font folders are read only for a listing with an installed caption font
            have = {f["family"] for f in fonts.families()}
        except (ImportError, OSError):
            have = {fam}
        if fam not in have:
            add("warn", f"the caption font {fam} isn't installed here: shots and exports fall back to Inter", section="shared")

    # variants: what each kind may change and how many there may be (custom pages and A/B tests); validate_variants
    # reports a malformed one
    per_kind: dict[tuple[str, str], int] = {}
    groups: dict[str, list[str]] = {}
    for v in variants_of(lb):
        r = variant_rule(rules, v)
        if r is None or r["platform"] not in plats:
            continue
        kw = {"source": r["source"], "platforms": [r["platform"]], "key": f"variant:{v['id']}", "section": "variants"}
        what = r["label"].lower()
        per_kind[(r["platform"], r["kind"])] = per_kind.get((r["platform"], r["kind"]), 0) + 1
        text = {loc: per for loc, per in _obj(v.get("text")).items() if isinstance(per, dict) and per}
        ok = variant_text_fields(rules, v)
        bad = sorted({f for per in text.values() for f in per if f not in ok})
        if bad:
            rs = text_rules(rules, r["platform"])
            add("err", f"variant {v['id']}: a {what} can't change {', '.join(rs[f]['label'].lower() if f in rs else f for f in bad)}"
                + ("" if ok else ": text isn't tested"), locales=sorted(text), **kw)
        elif text and r.get("textIn") == "locale" and not (isinstance(v.get("locale"), str) and set(text) == {v["locale"]}):
            add("err", f"variant {v['id']}: only a localized {what} changes text, in its own language: set its locale"
                + (f" ({v['locale']}) and keep its text there" if isinstance(v.get("locale"), str) else ""), locales=sorted(text), **kw)
        swap = _obj(v.get("swap"))
        off = sorted({sid for pair in swap.items() for sid in pair if isinstance(sid, str) and sid in by
                      and any((sets.get(s) or {}).get("row") in (r.get("not") or []) for s in by[sid].get("sets") or [])}
                     | {s for s in _obj(v.get("order")) if (sets.get(s) or {}).get("row") in (r.get("not") or [])})
        if off:
            add("err", f"variant {v['id']}: a {what} can't change {', '.join(r['not'])} shots: {', '.join(off)}", **kw)
        if isinstance(v.get("adGroup"), str):
            groups.setdefault(v["adGroup"], []).append(v["id"])
        if not variant_changes(lb, arts, rules, v, v.get("locale") if isinstance(v.get("locale"), str) else default):
            add("warn", f"variant {v['id']}: no change from the default page yet", **{**kw, "source": None})
    for (p, k), n in per_kind.items():
        r = next(x for x in rules["variants"] if (x["platform"], x["kind"]) == (p, k))
        if n > r["max"]:
            add("err", f"{n} {r['label'].lower()}s, at most {r['max']}", source=r["source"], platforms=[p], section="variants")
    ads = {x["platform"]: x for x in rules.get("ads") or []}
    for g, ids in groups.items():
        if len(ids) > (ads.get("appstore") or {}).get("adGroup", 1):
            add("err", f"ad group {g}: one custom product page each, not {', '.join(ids)}", source=(ads.get("appstore") or {}).get("source"),
                platforms=["appstore"], key=f"variant:{ids[1]}", section="ads")

    # ads and other assets: how many of each per locale; an uploaded one's size, alpha and bytes
    for r in rules["assets"]:
        if r["platform"] not in plats or "count" not in r:
            continue
        for loc in locs:
            n = sum(1 for a in arts if a.get("device") == "asset" and a.get("asset") == r["id"]
                    and (not isinstance(a.get("locale"), str) or a["locale"] == loc))
            if n > r["count"][1]:
                add("err", f"{r['label']}: {n}, at most {r['count'][1]}", source=r["source"], rule=r, check="count",
                    platforms=[r["platform"]], locales=[loc], section=r.get("group") or "shared")
    for a in arts:
        r = assets.get(a.get("asset")) if a.get("device") == "asset" else None
        if r is None or r["platform"] not in plats:
            continue
        kw = {"platforms": [r["platform"]], "locales": [a["locale"]] if isinstance(a.get("locale"), str) else [],
              "section": r.get("group") or "shared", "key": f"artboard:{a['id']}"}
        if r.get("kind") == "ad" and r.get("unverified"):
            add("warn", f"{a['id']}: {r['label']}: {r['unverified']}", source=r["source"], **kw)
        if doc_path is None or not is_image_shot(a) or image_src_problem(a["src"], doc_path):
            continue
        info, size = _png_head(Path(doc_path).parent / a["src"])
        if info is None:
            continue
        why = size_problem(r, info["w"], info["h"])
        if why:
            add("err", f"upload {a['src']} is {info['w']}×{info['h']}: want {why}", source=r["source"], rule=r, check="size", **kw)
        if not r.get("alpha") and (info["colour"] in (4, 6) or info["trns"]):
            add("err", f"upload {a['src']} has an alpha channel: the stores refuse transparency", source=r["source"], **kw)
        if size > r.get("maxBytes", UPLOAD_MAX_BYTES):
            add("err", f"upload {a['src']}: {size / 1048576:.1f} MB, at most {r.get('maxBytes', UPLOAD_MAX_BYTES) // 1048576} MB",
                source=r["source"], rule=r, check="bytes", **kw)
    out.sort(key=lambda f: f["level"] != "err")
    return out


def validate_store(rep, lb: dict, doc: dict, doc_path: Path | None, rules: dict) -> None:
    """store_checks into the build's report: rep.finding when it has one (build.Report), else err and warn."""
    for f in store_checks(doc, doc_path, rules):
        if hasattr(rep, "finding"):
            rep.finding(f)
        else:
            (rep.err if f["level"] == "err" else rep.warn)(f["where"], f["msg"])


class Findings:
    """A report (err, warn, finding) that keeps every line of validate_listing as a finding: what the page's Checks
    tab lists. A doc-shape line names no platform unless its place does (`….style.play`, `text.es-ES.appstore`)."""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def _add(self, level: str, where: str, msg: str) -> None:
        p = re.search(r"\.(play|appstore)(?:\.|$)", where)
        self.items.append({"level": level, "where": where, "msg": msg, "source": None, "platforms": [p[1]] if p else [],
                           "set": None, "locales": [], "section": None, "key": None})

    def err(self, where: str, msg: str) -> None:
        self._add("err", where, msg)

    def warn(self, where: str, msg: str) -> None:
        self._add("warn", where, msg)

    def finding(self, f: dict) -> None:
        self.items.append(f)


def checks_page_data(doc: dict, doc_path: Path | None) -> list[dict]:
    """Every finding of validate_listing, errors first: the page's Checks tab and the HTML export's."""
    rep = Findings()
    try:
        validate_listing(rep, doc, doc_path)
    except (RulesError, OSError, ValueError) as e:
        rep.err("listing", f"cannot read the store rules: {e}")
    return sorted(rep.items, key=lambda f: f["level"] != "err")


def section_lines(doc: dict, doc_path: Path | None, path: str) -> list[str]:
    """What `build.py patch <doc> section:<platform>/<row>` prints: the section's sets and shots (text: its fields per
    locale; shared: the icon and assets) in the default locale, its findings, and the keys that change it."""
    rules, lb = load_rules(), listing_of(doc) or {}
    p, _, row = path.partition("/")
    locs = [x for x in lb.get("locales") or [] if isinstance(x, str)]
    default = lb.get("defaultLocale") if lb.get("defaultLocale") in locs else (locs[0] if locs else None)
    label = {x["id"]: x["label"] for x in rules["platforms"]}.get(p, p)
    rows = {r["id"]: r["label"] for r in rules["rows"]}
    out = [f"{label} · {rows.get(row, row.capitalize())}"]
    sets = by_id(rules, "sets")
    if row == "text":
        for loc in locs:
            fields = _obj(_obj(_obj(lb.get("text")).get(loc)).get(p))
            out += [f"  {loc} {r['label']}: {text_count(fields[f], r['unit']) if isinstance(fields.get(f), str) else '-'} / {r['limit']} {r['unit']}"
                    + (" (MT)" if f"{p}.{f}" in (_obj(lb.get("mt")).get(loc) or []) else "")
                    for f, r in text_rules(rules, p).items() if f in fields]
    elif row == "shared":
        out.append(f"  icon: {lb.get('icon') or 'none'}")
        out += [f"  {a['id']}: {a.get('asset')}" for a in shots_of(doc) if a.get("device") == "asset"
                and platform_of(str(a.get("asset"))) == p]
    else:
        for s in sections(lb, shots_of(doc), rules, p, default):
            if s["row"] == row:
                out += [f"  {x['set']}: {len(x['shots'])} / {(sets[x['set']].get('count') or [0, 10])[1]} at "
                        f"{'×'.join(map(str, sets[x['set']]['author']))}: {', '.join(x['shots']) or 'no shots'}" for x in s["sets"]]
    for f in store_checks(doc, doc_path, rules):
        if f["section"] == row and (not f["platforms"] or p in f["platforms"]):
            out.append(f"  {'ERROR' if f['level'] == 'err' else 'WARN '} {f['where']}: {f['msg']}")
    block = next((f"block:{s.get('id')}/{i}" for s in doc.get("sections") or [] if isinstance(s, dict)
                  for i, b in enumerate(s.get("blocks") or []) if b is lb), "block:<listing>")
    out.append("change it: a text by its field: key, a shot by its artboard: key, the sets' order and the sections "
               f"shown by {block} --json '{{\"order\": …, \"rows\": …}}'")
    return out


# ---------- translation: build.py l10n ----------
# A string's MT key: "<platform>.<field>" (store text) or "strings.<key>" (a caption). listing.mt[locale] lists the
# machine-translated ones until the reader accepts them; listing.translatedFrom[locale][key] is the hash of the
# default locale's text a translation was made from, so `--export` lists the strings whose source changed since.


def source_hash(v) -> str:
    return hashlib.sha256(json.dumps(v, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def l10n_sources(lb: dict, rules: dict) -> dict[str, dict]:
    """{MT key: {value, label, limit, unit}} of the default locale: what a translation starts from (limit None for a
    caption, which no store limits)."""
    locs = [x for x in lb.get("locales") or [] if isinstance(x, str)]
    default = lb.get("defaultLocale") if lb.get("defaultLocale") in locs else (locs[0] if locs else None)
    labels = {p["id"]: p["label"] for p in rules["platforms"]}
    out: dict[str, dict] = {}
    for p, fields in _obj(_obj(lb.get("text")).get(default)).items():
        rs = text_rules(rules, p)
        for f, v in _obj(fields).items():
            if f in rs:
                out[f"{p}.{f}"] = {"value": v, "label": f"{labels.get(p, p)} {rs[f]['label'].lower()}", "limit": rs[f]["limit"], "unit": rs[f]["unit"]}
    for k, v in _obj(_obj(lb.get("strings")).get(default)).items():
        out[f"strings.{k}"] = {"value": v, "label": "Caption", "limit": None, "unit": None}
    return out


def l10n_value(lb: dict, locale: str, key: str):
    head, _, rest = key.partition(".")
    holder = _obj(_obj(lb.get("strings")).get(locale)) if head == "strings" else _obj(_obj(_obj(lb.get("text")).get(locale)).get(head))
    return holder.get(rest)


def l10n_export(doc: dict, doc_path: Path | None, locale: str, rules: dict | None = None) -> dict:
    """The strings `locale` lacks, or whose default-locale text changed since its translation: {from, to, strings:
    [{key, label, source, why: missing|changed, limit?, unit?, current?, shots?}]}. ValueError: not a listing's
    locale, or the default one."""
    rules = rules or load_rules()
    lb = listing_of(doc)
    if lb is None:
        raise ValueError("no listing block: l10n is a storelisting's")
    locs = [x for x in lb.get("locales") or [] if isinstance(x, str)]
    default = lb.get("defaultLocale") if lb.get("defaultLocale") in locs else (locs[0] if locs else None)
    if locale not in locs or locale == default:
        raise ValueError(f"'{locale}': one of the listing's other locales ({', '.join(x for x in locs if x != default)})")
    done = _obj(_obj(lb.get("translatedFrom")).get(locale))
    shots: dict[str, list[str]] = {}
    for a in shots_of(doc):
        if a.get("device") in ("shot", "asset") and not is_image_shot(a):
            for k in [*l10n_keys(_shot_html(a, doc_path)), f"{a['id']}.proof"]:
                shots.setdefault(f"strings.{k}", []).append(a["id"])
    items = []
    for key, s in l10n_sources(lb, rules).items():
        have = l10n_value(lb, locale, key)
        why = "missing" if have is None else "changed" if key in done and done[key] != source_hash(s["value"]) else None
        if not why:
            continue
        item = {"key": key, "label": s["label"], "source": s["value"], "why": why}
        if s["limit"]:
            item.update(limit=s["limit"], unit=s["unit"])
        if have is not None:
            item["current"] = have
        if shots.get(key):
            item["shots"] = list(dict.fromkeys(shots[key]))
        items.append(item)
    return {"from": default, "to": locale, "strings": items}


def l10n_import(lb: dict, locale: str, entries, rules: dict, *, mt: bool) -> list[str]:
    """Merge {MT key: text} into `locale`: each key one the default locale has, each text within its store limit
    (code points, or UTF-8 bytes for Apple keywords). On any problem nothing changes and the problems come back (an
    over-limit string with its count). Else the strings are set, translatedFrom records their sources, and listing.mt
    gains them (mt) or loses them (a human translation)."""
    if not isinstance(entries, dict) or not entries:
        return ["the file holds a JSON object of {\"<platform>.<field>\" or \"strings.<key>\": text}"]
    locs = [x for x in lb.get("locales") or [] if isinstance(x, str)]
    default = lb.get("defaultLocale") if lb.get("defaultLocale") in locs else (locs[0] if locs else None)
    if locale not in locs or locale == default:
        return [f"'{locale}': one of the listing's other locales ({', '.join(x for x in locs if x != default)})"]
    src = l10n_sources(lb, rules)
    problems = []
    for key, v in entries.items():
        s = src.get(key)
        if s is None:
            problems.append(f"{key}: {default} has no such string to translate")
            continue
        items = v if isinstance(v, list) else [v]
        if isinstance(v, list) != isinstance(s["value"], list) or not all(isinstance(x, str) and x.strip() for x in items):
            problems.append(f"{key}: " + ("a list of strings, as in " + default if isinstance(s["value"], list) else "a non-empty string"))
            continue
        for x in items:
            n = text_count(x, s["unit"]) if s["limit"] else 0
            if s["limit"] and n > s["limit"]:
                problems.append(f"{key}: {n} / {s['limit']} {s['unit']}: shorten it")
    if problems:
        return problems
    for key, v in entries.items():
        head, _, rest = key.partition(".")
        holder = (lb.setdefault("strings", {}).setdefault(locale, {}) if head == "strings"
                  else lb.setdefault("text", {}).setdefault(locale, {}).setdefault(head, {}))
        holder[rest] = v
        lb.setdefault("translatedFrom", {}).setdefault(locale, {})[key] = source_hash(src[key]["value"])
    marks = [k for k in (lb.get("mt") or {}).get(locale) or [] if mt or k not in entries]
    if mt:
        marks += [k for k in entries if k not in marks]
    if marks:
        lb.setdefault("mt", {})[locale] = marks
    elif isinstance(lb.get("mt"), dict):
        lb["mt"].pop(locale, None)
        if not lb["mt"]:
            del lb["mt"]
    return []


def l10n_accept(lb: dict, locale: str, keys: list[str]) -> list[str]:
    """Clear the MT marks of `keys` in `locale` (the reader accepted them as they are). Problems: a key that isn't
    marked; nothing changes then."""
    marks = list(_obj(lb.get("mt")).get(locale) or [])
    bad = [k for k in keys if k not in marks]
    if bad or not keys:
        return [f"{k}: not a machine-translated {locale} string" for k in bad] or ["name the keys to accept"]
    left = [k for k in marks if k not in keys]
    if left:
        lb["mt"][locale] = left
    else:
        lb["mt"].pop(locale)
        if not lb["mt"]:
            del lb["mt"]
    return []


def mark_human(lb: dict | None, locale: str, key: str) -> None:
    """A string a person wrote or edited (`patch field:`): no MT mark, and in another locale than the default, made
    from the default's text as it is now."""
    if not isinstance(lb, dict):
        return
    if key in (_obj(lb.get("mt")).get(locale) or []):
        l10n_accept(lb, locale, [key])
    src = l10n_sources(lb, load_rules()).get(key)
    locs = [x for x in lb.get("locales") or [] if isinstance(x, str)]
    default = lb.get("defaultLocale") if lb.get("defaultLocale") in locs else (locs[0] if locs else None)
    if src is not None and locale != default and l10n_value(lb, locale, key) is not None:
        lb.setdefault("translatedFrom", {}).setdefault(locale, {})[key] = source_hash(src["value"])
    elif isinstance(_obj(lb.get("translatedFrom")).get(locale), dict):   # deleted: nothing was translated
        lb["translatedFrom"][locale].pop(key, None)
        if not lb["translatedFrom"][locale]:
            del lb["translatedFrom"][locale]
        if not lb["translatedFrom"]:
            del lb["translatedFrom"]


# ---------- export: the fastlane layout ----------
# fastlane's folder names, read in its source (store-rules.json source FL): supply reads
# fastlane/metadata/android/<locale>/{title,short_description,full_description,video}.txt, changelogs/<code>.txt
# (default.txt for any), images/{icon,featureGraphic,tvBanner}.png and images/<type>/*.png for phoneScreenshots,
# sevenInchScreenshots, tenInchScreenshots, tvScreenshots and wearScreenshots, in name order. deliver reads
# fastlane/metadata/<locale>/<field>.txt and fastlane/screenshots/<locale>/*.png, telling each PNG's display type by its
# size and ordering a type's PNGs by name. Variants and ads go beside it in folders fastlane doesn't read.

PLAY_META = "fastlane/metadata/android"
APPSTORE_META = "fastlane/metadata"
APPSTORE_SHOTS = "fastlane/screenshots"
PLAY_IMAGE_TYPES = ("phoneScreenshots", "sevenInchScreenshots", "tenInchScreenshots", "tvScreenshots", "wearScreenshots")
PLAY_IMAGES = ("icon", "featureGraphic", "tvBanner")


def _text_file(p: str, loc: str, name: str) -> str:
    if p == "play":
        return f"{PLAY_META}/{loc}/" + ("changelogs/default.txt" if name == "changelogs" else name)
    return f"{APPSTORE_META}/{loc}/{name}"


def export_plan(doc: dict, doc_path: Path | None, rules: dict | None = None, platform: str | None = None,
                locale: str | None = None, caps: dict | None = None) -> list[dict]:
    """The fastlane ZIP's files in order, before rendering: text {path, kind: text, text, platform, locale, field, mt}
    and images {path, kind: shot|upload|asset|icon, platform, locale, set or asset, shot, i, n, w, h (store px), fw,
    fh (CSS px), scale, src (an upload's PNG), capture (the PNG the UI slot shows), fallback (a capture of the
    default locale), variant, message and layout (a variant's style)}. A field the locale lacks is left out: the store
    falls back to its default. Ads text and images go under ads/google/<locale>/ and ads/apple/<locale>/, a set or
    asset fastlane has no folder for under extra/<platform>/<locale>/. A variant's files go under
    variants/<platform>-<kind>-<id>/ at their default paths: only what it changes (its text, each set whose shots or
    style differ), the rest is the default page's. platform and locale narrow it; caps (captures_at, an earlier
    revision's) stands in for captures.json. ValueError: a platform or locale the listing hasn't."""
    rules = rules or load_rules()
    lb = listing_of(doc) or {}
    locs = [x for x in lb.get("locales") or [] if isinstance(x, str)]
    default = lb.get("defaultLocale") if lb.get("defaultLocale") in locs else (locs[0] if locs else None)
    plats = [p["id"] for p in rules["platforms"] if p["id"] in (lb.get("platforms") or [])]
    if platform is not None and platform not in plats:
        raise ValueError(f"platform: one of {', '.join(plats)}")
    if locale is not None and locale not in locs:
        raise ValueError(f"locale: one of {', '.join(locs)}")
    arts = shots_of(doc)
    by = {a["id"]: a for a in arts}
    sets, assets = by_id(rules, "sets"), by_id(rules, "assets")
    caps = caps if caps is not None else captures(doc, doc_path) if doc_path is not None else {}
    mt = _obj(lb.get("mt"))
    out: list[dict] = []

    def text_entry(p: str, loc: str, f: str, r: dict, v, prefix: str = "") -> None:
        name = r.get("fastlane") or {"adHeadlines": "headlines.txt", "adDescriptions": "descriptions.txt"}.get(f)
        if not name or not v or not (isinstance(v, str) or (isinstance(v, list) and all(isinstance(x, str) for x in v))):
            return
        out.append({"path": prefix + (f"ads/google/{loc}/{name}" if r.get("group") == "ads" else _text_file(p, loc, name)),
                    "kind": "text", "text": "\n".join(v) if isinstance(v, list) else v, "platform": p,
                    "locale": loc, "field": f, "mt": [f"{p}.{f}"] if not prefix and f"{p}.{f}" in (mt.get(loc) or []) else []})

    def shot_entries(p: str, loc: str, secs: list[dict], extra: dict | None = None, style: dict | None = None,
                     prefix: str = "") -> None:
        for sec in secs:
            for x in sec["sets"]:
                r = sets[x["set"]]
                name = r["id"].partition("/")[2]
                for i, sid in enumerate(x["shots"]):
                    a = by[sid]
                    if p == "play" and r.get("fastlane") in PLAY_IMAGE_TYPES:
                        path = f"{PLAY_META}/{loc}/images/{r['fastlane']}/{i + 1:02d}-{sid}.png"
                    elif p == "appstore" and r.get("fastlane"):
                        path = f"{APPSTORE_SHOTS}/{loc}/{i + 1:02d}-{name}-{sid}.png"
                    else:
                        path = f"extra/{p}/{loc}/{name}/{i + 1:02d}-{sid}.png"
                    fw, fh = frame_size(r)
                    e = {"path": prefix + path, "kind": "upload" if is_image_shot(a) else "shot", "platform": p, "locale": loc,
                         "set": r["id"], "shot": sid, "i": i, "n": len(x["shots"]), "w": r["author"][0], "h": r["author"][1],
                         "fw": fw, "fh": fh, "scale": r["scale"], **(extra or {})}
                    if style is not None and not r.get("raw"):
                        e.update(effective_style(lb, p, a, style))
                    if is_image_shot(a):
                        e["src"] = a["src"]
                    else:
                        c = capture_for(caps, a, r, loc, default)
                        if c:
                            e["capture"] = c["file"]
                            e["fallback"] = c["locale"] != loc
                    out.append(e)

    for p in plats if platform is None else [platform]:
        for loc in locs if locale is None else [locale]:
            for f, r in text_rules(rules, p).items():
                text_entry(p, loc, f, r, _obj(_obj(_obj(lb.get("text")).get(loc)).get(p)).get(f))
            if p == "play" and isinstance(_obj(lb.get("video")).get("play"), str):
                out.append({"path": f"{PLAY_META}/{loc}/video.txt", "kind": "text", "text": lb["video"]["play"], "platform": p,
                            "locale": loc, "field": "video", "mt": []})
            if p == "play" and lb.get("icon"):
                out.append({"path": f"{PLAY_META}/{loc}/images/icon.png", "kind": "icon", "platform": p, "locale": loc,
                            "asset": "play/icon", "w": 512, "h": 512, "fw": 512, "fh": 512, "scale": 1})
            ads = 0
            for a in arts:
                r = assets.get(a.get("asset")) if a.get("device") == "asset" else None
                if not r or r["platform"] != p or "author" not in r or (isinstance(a.get("locale"), str) and a["locale"] != loc):
                    continue
                fw, fh = frame_size(r)
                if r.get("group") == "ads" and p == "play":
                    ads += 1
                    path = f"ads/google/{loc}/{r['author'][0]}x{r['author'][1]}-{ads}.png"
                elif r.get("group") == "ads":
                    path = f"ads/apple/{loc}/{r['id'].partition('/')[2]}-{a['id']}.png"
                elif p == "play" and r.get("fastlane") in PLAY_IMAGES:
                    path = f"{PLAY_META}/{loc}/images/{r['fastlane']}.png"
                else:
                    path = f"extra/{p}/{loc}/assets/{a['id']}.png"
                e = {"path": path, "kind": "upload" if is_image_shot(a) else "asset", "platform": p, "locale": loc, "asset": r["id"],
                     "shot": a["id"], "w": r["author"][0], "h": r["author"][1], "fw": fw, "fh": fh, "scale": r["scale"]}
                if is_image_shot(a):
                    e["src"] = a["src"]
                out.append(e)
            base = sections(lb, arts, rules, p, loc)
            shot_entries(p, loc, base)
            # the variants: what each changes, under variants/<platform>-<kind>-<id>/
            for v in variants_of(lb, p):
                vr = variant_rule(rules, v)
                if vr is None or (isinstance(v.get("locale"), str) and v["locale"] != loc):
                    continue
                prefix, vst = f"variants/{p}-{vr['kind']}-{v['id']}/", variant_style(rules, v)
                for f, r in text_rules(rules, p).items():
                    if r.get("group") == "listing":
                        text_entry(p, loc, f, r, _obj(_obj(v.get("text")).get(loc)).get(f), prefix)
                was = {x["set"]: x["shots"] for s in base for x in s["sets"]}
                mine = [{"row": s["row"], "sets": [x for x in s["sets"] if x["shots"] != was.get(x["set"]) or (not sets[x["set"]].get("raw") and any(
                    effective_style(lb, p, by[i]) != effective_style(lb, p, by[i], vst) for i in x["shots"]))]}
                        for s in sections(lb, arts, rules, p, loc, v)]
                shot_entries(p, loc, mine, {"variant": v["id"]}, vst, prefix)
    return out


def captures_at(doc: dict, doc_path: Path, screens: dict) -> dict:
    """An earlier revision's captures, as captures() gives them, from the hashes its history entry records
    ("<shot>/capture/<target>/<locale>": sha256, 16 hex digits): today's PNG when its hash is still that, else the
    one a re-shoot kept in captures/old/. A capture neither has is left out (the shot shows its mock-up)."""
    now = captures(doc, doc_path)
    base = listing_dir(doc_path)
    out: dict = {}
    for k, sha in (screens or {}).items():
        parts = k.split("/")
        if len(parts) != 4 or parts[1] != "capture" or not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{16}", sha):
            continue
        sid, _, t, loc = parts
        c = ((now.get(sid) or {}).get(t) or {}).get(loc)
        if c and c.get("sha") == sha:
            out.setdefault(sid, {}).setdefault(t, {})[loc] = c
        elif (base / "captures" / "old" / f"{sha}.png").is_file():
            out.setdefault(sid, {}).setdefault(t, {})[loc] = {"file": f"{base.name}/captures/old/{sha}.png", "fresh": True, "sha": sha}
    return out


def export_fonts(lb: dict, rules: dict) -> list[dict]:
    """The fonts an export draws with, for manifest.json: the caption font (installed here, with its fsType and what
    it allows) and Inter, the vendored default (OFL)."""
    f = _obj(_obj(lb.get("brand")).get("font"))
    default = rules["brand"]["font"]["default"]
    out = []
    if isinstance(f.get("family"), str) and f["family"] != default:
        fs = f.get("fsType") if isinstance(f.get("fsType"), int) else None
        out.append({"family": f["family"], "weight": f.get("weight"), "use": "captions", "source": f.get("source") or "system",
                    "fsType": fs, "embedding": (font_embedding(fs) or "allowed") if fs is not None else "unknown"})
    out.append({"family": default, "weight": f.get("weight") if f.get("family") == default else None,
                "use": "captions" if not out else "fallback", "source": "vendored", "licence": "OFL", "embedding": "allowed"})
    return out


PNG_KEEP = (b"IHDR", b"IDAT", b"IEND", b"sRGB", b"gAMA", b"cHRM", b"iCCP", b"pHYs")


def png_rgb(w: int, h: int, rgb: bytes) -> bytes:
    """A PNG (colour type 2, 8 bits, filter 0 on every row) of w × h RGB pixels."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    stride = w * 3
    rows = b"".join(b"\0" + rgb[y * stride:(y + 1) * stride] for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


def _chunks(data: bytes):
    i = 8
    while i + 8 <= len(data):
        n, kind = int.from_bytes(data[i:i + 4], "big"), data[i + 4:i + 8]
        yield kind, data[i + 8:i + 8 + n], data[i:i + 12 + n]
        i += 12 + n
        if kind == b"IEND":
            return


def _unfilter(raw: bytes, h: int, stride: int, bpp: int) -> bytearray:
    out, prev, i = bytearray(h * stride), bytearray(stride), 0
    for y in range(h):
        ft, line = raw[i], bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        if ft == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 255
        elif ft == 2:
            line = bytearray((a + b) & 255 for a, b in zip(line, prev))
        elif ft == 3:
            for x in range(stride):
                line[x] = (line[x] + (((line[x - bpp] if x >= bpp else 0) + prev[x]) >> 1)) & 255
        elif ft == 4:
            for x in range(stride):
                a, b, c = (line[x - bpp] if x >= bpp else 0), prev[x], (prev[x - bpp] if x >= bpp else 0)
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        elif ft != 0:
            raise ValueError(f"PNG row filter {ft}")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


def png_rgb24(data: bytes) -> bytes:
    """data as a 24-bit RGB PNG, what both stores take: an 8-bit RGB one without tRNS keeps its pixels as they are
    (only IHDR, IDAT, IEND and the colour chunks stay; text and time chunks go); grey, indexed, 16-bit and RGBA ones
    are decoded and written again, any alpha dropped. ValueError: not a PNG, or an interlaced one."""
    info = png_info(data)
    if info is None:
        raise ValueError("not a PNG")
    chunks = list(_chunks(data))
    ihdr = chunks[0][1]
    w, h, depth, colour, interlace = info["w"], info["h"], info["depth"], info["colour"], ihdr[12]
    if colour == 2 and depth == 8 and not info["trns"]:
        return b"\x89PNG\r\n\x1a\n" + b"".join(c for k, _, c in chunks if k in PNG_KEEP)
    if interlace:
        raise ValueError("an interlaced PNG: save it without interlacing")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour]
    bits = channels * depth
    stride, bpp = (w * bits + 7) // 8, max(1, bits // 8)
    px = _unfilter(zlib.decompress(b"".join(b for k, b, _ in chunks if k == b"IDAT")), h, stride, bpp)
    if depth == 16:
        px, depth = px[0::2], 8
        stride = w * channels
    if depth < 8:   # indexed or grey at 1, 2 or 4 bits: one byte per pixel
        per = 8 // depth
        mask = (1 << depth) - 1
        unpacked = bytearray(w * h)
        for y in range(h):
            row = px[y * stride:(y + 1) * stride]
            for x in range(w):
                unpacked[y * w + x] = (row[x // per] >> (8 - depth * (x % per + 1))) & mask
        px = unpacked
        if colour == 0:
            px = bytearray(v * 255 // mask for v in px)
    rgb = bytearray(w * h * 3)
    if colour == 2:
        rgb[:] = px
    elif colour == 6:
        rgb[0::3], rgb[1::3], rgb[2::3] = px[0::4], px[1::4], px[2::4]
    elif colour in (0, 4):
        g = px[0::channels]
        rgb[0::3], rgb[1::3], rgb[2::3] = g, g, g
    else:
        pal = next(b for k, b, _ in chunks if k == b"PLTE")
        rgb = bytearray(b"".join(pal[3 * v:3 * v + 3] for v in px))
    return png_rgb(w, h, bytes(rgb))
