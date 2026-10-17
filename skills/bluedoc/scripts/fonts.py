"""The fonts installed on this machine, for a storelisting's caption font (the Text tab's Typography, GET /__bluedoc/fonts).

scan() walks the font folders (macOS: /System/Library/Fonts, /Library/Fonts and ~/Library/Fonts; elsewhere
fontconfig's usual folders; BLUEDOC_FONT_DIRS, os.pathsep-separated, replaces them) and reads each TTF, OTF and TTC:
the `name` table's family and style (the typographic names 16 and 17 when present, else 1 and 2) and copyright (0),
and the `OS/2` table's weight class, italic bit and fsType (embedding rights: 0 installable, 2 restricted, 4 preview &
print, 8 editable; bit 9 bitmap only). A folder is read again only when its modification time changes, so a font
installed since (Font Book writes it into ~/Library/Fonts) shows on the next scan without a restart. Families whose
name starts with "." are the system's private ones and stay out.

Only the table directory and the two tables are read from each file, never the whole font. Python 3.9+ standard
library only."""
from __future__ import annotations

import os
import struct
import sys
import threading
from pathlib import Path

FONT_TYPES = (".ttf", ".otf", ".ttc")
MAX_FACES = 64   # faces read from one collection
MAX_FILES = 5000   # files read from one folder tree
MAC_ROMAN = "mac_roman"


def font_dirs() -> list[Path]:
    """The folders to scan: BLUEDOC_FONT_DIRS, else this system's font folders."""
    env = os.environ.get("BLUEDOC_FONT_DIRS")
    if env is not None:
        return [Path(p).expanduser() for p in env.split(os.pathsep) if p]
    home = Path.home()
    if sys.platform == "darwin":
        return [Path("/System/Library/Fonts"), Path("/Library/Fonts"), home / "Library" / "Fonts"]
    if sys.platform.startswith("win"):
        win = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        return [win, Path(os.environ.get("LOCALAPPDATA", str(home))) / "Microsoft" / "Windows" / "Fonts"]
    return [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), home / ".local" / "share" / "fonts", home / ".fonts"]


def _u16(b: bytes, i: int) -> int:
    return struct.unpack_from(">H", b, i)[0]


def _tables(f, at: int) -> dict[bytes, tuple[int, int]]:
    """{tag: (offset, length)} from the sfnt table directory at `at`."""
    f.seek(at)
    head = f.read(12)
    if len(head) < 12 or head[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        return {}
    n = _u16(head, 4)
    recs = f.read(16 * n)
    out = {}
    for i in range(min(n, len(recs) // 16)):
        tag, _, off, ln = struct.unpack_from(">4sIII", recs, 16 * i)
        out[tag] = (off, ln)
    return out


def _names(data: bytes) -> dict[int, str]:
    """{nameID: text} from a `name` table, English where it can: Windows US English (3/1/0x409), Unicode (0), then
    Mac Roman English (1/0/0)."""
    if len(data) < 6:
        return {}
    count, base = _u16(data, 2), _u16(data, 4)
    best: dict[int, tuple[int, str]] = {}
    for i in range(count):
        o = 6 + 12 * i
        if o + 12 > len(data):
            break
        pid, eid, lang, nid, ln, off = struct.unpack_from(">HHHHHH", data, o)
        if nid not in (0, 1, 2, 16, 17):
            continue
        raw = data[base + off:base + off + ln]
        if pid == 3 and eid in (1, 10):
            rank, enc = (0 if lang == 0x409 else 2), "utf-16-be"
        elif pid == 0:
            rank, enc = 1, "utf-16-be"
        elif pid == 1 and eid == 0 and lang == 0:
            rank, enc = 3, MAC_ROMAN
        else:
            continue
        try:
            text = raw.decode(enc).strip("\x00").strip()
        except UnicodeDecodeError:
            continue
        if text and (nid not in best or rank < best[nid][0]):
            best[nid] = (rank, text)
    return {k: v for k, (_, v) in best.items()}


def _face(f, at: int, size: int) -> dict | None:
    """One face at offset `at`: {family, style, weight, italic, fsType, copyright}, or None without a family."""
    tabs = _tables(f, at)
    if b"name" not in tabs:
        return None
    off, ln = tabs[b"name"]
    if off + ln > size or ln > 1 << 20:
        return None
    f.seek(off)
    names = _names(f.read(ln))
    family = names.get(16) or names.get(1)
    if not family:
        return None
    style = names.get(17) or names.get(2) or "Regular"
    weight, italic, fs_type = 400, "italic" in style.lower() or "oblique" in style.lower(), 0
    if b"OS/2" in tabs:
        off, ln = tabs[b"OS/2"]
        f.seek(off)
        os2 = f.read(min(ln, 64))
        if len(os2) >= 10:
            weight, fs_type = _u16(os2, 4), _u16(os2, 8)
        if len(os2) >= 64:
            italic = italic or bool(_u16(os2, 62) & 1)
    return {"family": family, "style": style, "weight": weight, "italic": italic, "fsType": fs_type,
            "copyright": names.get(0, "")[:200]}


def read_font(path: Path) -> list[dict]:
    """The faces of one font file (a TTC's each), as _face has them; [] when it isn't a font this reads."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            head = f.read(12)
            if head[:4] == b"ttcf" and len(head) >= 12:
                n = min(struct.unpack_from(">I", head, 8)[0], MAX_FACES)
                offs = struct.unpack(f">{n}I", f.read(4 * n))
                return [x for x in (_face(f, o, size) for o in offs if o < size) if x]
            x = _face(f, 0, size)
            return [x] if x else []
    except (OSError, struct.error, ValueError):
        return []


class FontCache:
    """The scan of each folder, kept until the modification time of the folder or one under it changes."""

    def __init__(self) -> None:
        self._dirs: dict[str, tuple[tuple, list[dict]]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _walk(root: Path) -> tuple[tuple, list[Path]]:
        stamp, files = [], []
        for d, subs, names in os.walk(root, followlinks=False):
            subs.sort()
            try:
                stamp.append((d, os.stat(d).st_mtime_ns))
            except OSError:
                continue
            files += [Path(d) / n for n in sorted(names) if n.lower().endswith(FONT_TYPES)]
            if len(files) >= MAX_FILES:
                break
        return tuple(stamp), files[:MAX_FILES]

    def faces(self, root: Path) -> list[dict]:
        if not root.is_dir():
            return []
        stamp, files = self._walk(root)
        with self._lock:
            got = self._dirs.get(str(root))
            if got and got[0] == stamp:
                return got[1]
        faces = [face for p in files for face in read_font(p)]
        with self._lock:
            self._dirs[str(root)] = (stamp, faces)
        return faces


CACHE = FontCache()


def families(dirs: list[Path] | None = None, cache: FontCache = CACHE) -> list[dict]:
    """The installed families, by name: {family, faces: [{style, weight, italic, fsType}], fsType, copyright}. A
    family's fsType is its upright regular face's (nearest weight 400), else its first face's."""
    by: dict[str, dict] = {}
    for d in font_dirs() if dirs is None else dirs:
        for face in cache.faces(Path(d)):
            fam = face["family"]
            if fam.startswith(".") or len(fam) > 64 or any(c in fam for c in ";{}<>\\\"'`"):
                continue
            x = by.setdefault(fam, {"family": fam, "faces": [], "copyright": ""})
            key = (face["style"], face["weight"], face["italic"])
            if key not in {(f["style"], f["weight"], f["italic"]) for f in x["faces"]}:
                x["faces"].append({"style": face["style"], "weight": face["weight"], "italic": face["italic"], "fsType": face["fsType"]})
            x["copyright"] = x["copyright"] or face["copyright"]
    out = []
    for fam in sorted(by, key=str.casefold):
        x = by[fam]
        x["faces"].sort(key=lambda f: (f["italic"], f["weight"], f["style"]))
        reg = min(x["faces"], key=lambda f: (f["italic"], abs(f["weight"] - 400)))
        out.append({**x, "fsType": reg["fsType"]})
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(families(), indent=1, ensure_ascii=False))
