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
    """A shot that is a finished PNG (an upload: `src` under <stem>.listing/), not a layout with a screen file."""
    return isinstance(a, dict) and a.get("device") == "shot" and isinstance(a.get("src"), str) and a["src"].lower().endswith(IMAGE_TYPES)


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
            font = brand.get("font")
            if font is not None and not (isinstance(font, dict) and isinstance(font.get("family"), str)
                                         and FONT_FAMILY.match(font["family"])
                                         and (font.get("weight") is None or font["weight"] in range(100, 1000, 100))):
                rep.err(lw + ".brand.font", "{family, weight}: a family name without quotes or ; { } < > \\, a weight 100-900")
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
    if "variants" in lb and not isinstance(lb["variants"], list):
        rep.err(lw + ".variants", "a list of variants")

    sets = by_id(rules, "sets")
    assets = by_id(rules, "assets")
    in_set: dict[str, list[str]] = {}
    for i, a in enumerate(arts):
        aw = f"artboard '{a['id']}'"
        dev = a.get("device")
        if dev == "shot":
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
                else:
                    in_set.setdefault(s, []).append(a["id"])
                    if r["row"] not in rows:
                        rep.warn(aw + ".sets", f"'{s}' is in the {r['row']} section, which listing.rows leaves off: the "
                                 "pages don't show it")
            if "locale" in a and a["locale"] not in locs:
                rep.err(aw + ".locale", f"{a['locale']!r} is not in locales {locs}")
            style_ok(aw + ".style", a.get("style"))
            if "recipe" in a and not isinstance(a["recipe"], dict):
                rep.err(aw + ".recipe", "an object: route, appearance, settle, targets")
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
        elif dev == "asset":
            r = assets.get(a.get("asset"))
            if r is None:
                rep.err(aw + ".asset", f"{a.get('asset')!r} is no asset in the rules: {', '.join(assets)}")
            elif r["platform"] not in plats:
                rep.err(aw + ".asset", f"'{a['asset']}' is a {r['platform']} asset and the listing's platforms are {plats}")
            elif "author" not in r:
                rep.err(aw + ".asset", f"'{a['asset']}' isn't drawn as an artboard: {r.get('note') or 'see the rules'}")
        for k in ("sets", "locale", "recipe", "style"):
            if k in a and dev != "shot":
                rep.err(f"{aw}.{k}", "only a shot has it")
        if "asset" in a and dev != "asset":
            rep.err(aw + ".asset", "only an asset artboard has it")

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


def sections(lb: dict, artboards: list, rules: dict, platform: str, locale: str | None) -> list[dict]:
    """A platform page's device sections, as the page lays them out (board-geo.js listingSections, line for line):
    [{row, sets: [{set, shots: [artboard ids]}]}] for each row of listing.rows (default: the core rows) in the rules'
    order. A row lists the platform's sets in that row, in the rules' order, that are core, or have a shot, or are
    asked for (`if:watchFace` with listing.watchFace). A set's shots: the shots that name it, in board order, except
    an uploaded one of another locale; listing.order[set] puts the ids it names first, in its order. A row with no
    set is left out."""
    lb = lb if isinstance(lb, dict) else {}
    rows = lb.get("rows") if isinstance(lb.get("rows"), list) else [r["id"] for r in rules["rows"] if r.get("core")]
    order = lb.get("order") if isinstance(lb.get("order"), dict) else {}
    arts = [a for a in artboards or [] if isinstance(a, dict) and isinstance(a.get("id"), str) and a.get("device") == "shot"
            and isinstance(a.get("sets"), list)]
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
            want = [i for i in order.get(s["id"]) if i in shots] if isinstance(order.get(s["id"]), list) else []
            sets.append({"set": s["id"], "shots": want + [i for i in shots if i not in want]})
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
           "icon": icon_of(doc, doc_path) if doc_path is not None else None}
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


def uploads(doc: dict, doc_path: Path, rules: dict | None = None) -> list[dict]:
    """The drafts: uploaded PNGs no shot (in the doc or a revision) records, [{file, platform, locale, set, slot, w,
    h, colour, bytes, problem}] in set and slot order. file is relative to the doc's folder."""
    rules = rules or load_rules()
    lb = listing_of(doc) or {}
    recorded = recorded_srcs(doc, doc_path)
    base = listing_dir(doc_path)
    if base.is_symlink() or not base.is_dir():
        return []
    out = []
    for s in rules["sets"]:
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
                out.append({"file": rel, "platform": s["platform"], "locale": loc, "set": s["id"], "slot": int(m[1]),
                            "w": info.get("w"), "h": info.get("h"), "colour": info.get("colour"), "bytes": len(data),
                            "problem": upload_problem(s, data)})
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
    return out


def font_embedding(fs_type: int) -> str | None:
    """Why a font's OS/2 fsType keeps a PDF from embedding it (OT-FSTYPE), or None: bitmap only (bit 9), or
    restricted (2) without the preview & print (4) or editable (8) bits."""
    if fs_type & 0x200:
        return "bitmap only"
    if fs_type & 0xF and not fs_type & 0xC:
        return "restricted embedding"
    return None


def effective_style(lb: dict, platform: str, a: dict | None = None) -> dict[str, str]:
    """The message and layout a platform page shows: M1 and L1, the listing's, its platform's, then the shot's own."""
    out = {"message": "m1", "layout": "l1"}
    st = lb.get("style") if isinstance(lb.get("style"), dict) else {}
    for src in (st, st.get(platform), (a or {}).get("style")):
        if isinstance(src, dict):
            out.update({k: v for k, v in src.items() if k in ("message", "layout") and isinstance(v, str)})
    return out


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
