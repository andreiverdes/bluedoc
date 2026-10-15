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
    """{shot: {target: {locale: {file, w, h, fresh}}}} from <stem>.listing/captures/captures.json (written by
    capture.py): file relative to the doc's folder; fresh when the capture's recipe hash is the shot's recipe's. {}
    without the file or a readable list."""
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
            "file": c["file"], "w": c.get("w"), "h": c.get("h"), "fresh": c.get("recipe") == recipes[c["shot"]]}
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

    # style: the picker's default, and a shot's own
    styles = {s["id"]: s for s in rules["styles"]}

    def style_ok(where: str, st) -> None:
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
            if k not in ("message", "layout"):
                rep.err(f"{where}.{k}", "a style has message and layout only")
    style_ok(lw + ".style", lb.get("style"))

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

    for k in ("capture",):
        if k in lb and not isinstance(lb[k], dict):
            rep.err(f"{lw}.{k}", "an object")
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
    caps = captures(doc, doc_path) if doc_path is not None else {}
    if inline and doc_path is not None:
        for per in caps.values():
            for locs in per.values():
                for c in locs.values():
                    c["file"] = _data_uri(Path(doc_path).parent / c["file"], "image/png") or c["file"]
    return {"rules": rules, "keys": keys, "captures": caps, "images": images,
            "icon": icon_of(doc, doc_path) if doc_path is not None else None}
