"""bluedoc's settings, in $BLUEDOC_HOME/settings.json (the home page's Settings writes it; a missing key is its default):

  planHook   true | false       the plan-mode hook opens agents' plans as bluedoc pages (hook.py); env BLUEDOC_PLAN_HOOK
                                (0, false, no or off turn it off)
  patchOnly  true | false       patch-only edits: agents' edit tools can't change a built doc (hook.py patch_only); env
                                BLUEDOC_PATCH_ONLY (0, false, no or off turn it off)
  chrome     "<path>" | null    Chrome or Chromium for PDFs, decks, snapshots and captures (serve.find_chrome); null: the
                                usual places; env BLUEDOC_CHROME
  fontDirs   ["<dir>"] | null   the font folders fonts.py scans instead of this system's; env BLUEDOC_FONT_DIRS
                                (os.pathsep-separated)
  shareAs    {"<folder>": "<login>"}   each project's GitHub account for Share, by its home-page folder's path
                                (share.py project_account); no environment variable, Settings' Sharing card writes it
  home       {"pinned": [...], "hidden": [...], "shown": [...], "names": {...}, "icons": {...}}   the home page's
                                project list, by registered folder path: pinned to the top, hidden by the reader,
                                temporary folders the reader shows, the reader's name for a folder (1 to 60 characters)
                                and its icon ({"icon": one of PROJECT_ICONS} or {"emoji": one emoji}) (serve.py
                                index); no environment variable, the home page's project menu writes it

An environment variable that is set (not empty) wins over the file, the file over the default. Python 3.9+ standard
library only."""
from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

ENV = {"planHook": "BLUEDOC_PLAN_HOOK", "patchOnly": "BLUEDOC_PATCH_ONLY", "chrome": "BLUEDOC_CHROME",
       "fontDirs": "BLUEDOC_FONT_DIRS"}
DEFAULTS: dict = {"planHook": True, "patchOnly": True, "chrome": None, "fontDirs": None}
SWITCHES = ("planHook", "patchOnly")   # true | false; the environment's 0, false, no or off is false
OFF = {"0", "false", "no", "off"}
HOME_LISTS = ("pinned", "hidden", "shown")   # the home key's lists of registered folder paths
HOME_MAPS = ("names", "icons")   # the home key's maps by registered folder path: a name, an icon
NAME_MAX = 60
# the icons a project can take (home.html PROJECT_ICONS draws them: HorizonUI's Icons, and Phone, Cart and Book of its own)
PROJECT_ICONS = ("Package", "Bookmark", "Folder", "FolderOpen", "Layers", "FileCode", "Terminal", "Database", "Server", "Cloud",
                 "Cpu", "Globe", "Compass", "Monitor", "Phone", "Layout", "Palette", "Image", "PenLine", "Chart",
                 "BarChart", "PieChart", "Calendar", "Mail", "Chat", "Users", "Home", "Cart", "Book", "Test", "Rocket",
                 "Zap", "Sparkles", "Star", "Lightbulb", "Brain", "Bot", "Wand", "Shield", "Lock", "Key", "Puzzle",
                 "Plug", "Tool", "Target", "Debug", "Flag", "GitBranch")
_KEYCAP = re.compile("[0-9#*]\ufe0f?\u20e3")


def _pictograph(c: str) -> bool:
    """An emoji's base character: a symbol (So, or an arrow's Sm), one of the four emoji punctuation marks, or a code
    point of the emoji blocks this Python doesn't know yet."""
    o = ord(c)
    if 0x1F1E6 <= o <= 0x1F1FF:   # a regional indicator alone isn't one
        return False
    return (unicodedata.category(c) == "So" or unicodedata.category(c) == "Sm" and 0x2190 <= o <= 0x21FF
            or o in (0x203C, 0x2049, 0x3030, 0x303D) or 0x1F000 <= o <= 0x1FAFF)


def one_emoji(s) -> bool:
    """Whether s is one emoji: a pictograph with its variation selector, skin tone and tag characters, several of them
    joined by ZWJ, a flag (two regional indicators) or a keycap."""
    if not isinstance(s, str) or not s or len(s) > 16:
        return False
    if len(s) == 2 and all(0x1F1E6 <= ord(c) <= 0x1F1FF for c in s) or _KEYCAP.fullmatch(s):
        return True
    for part in s.split("\u200d"):
        if not part or not _pictograph(part[0]):
            return False
        if not all(c in "\ufe0e\ufe0f" or 0x1F3FB <= ord(c) <= 0x1F3FF or 0xE0020 <= ord(c) <= 0xE007F for c in part[1:]):
            return False
    return True


def project_name(n) -> bool:
    """A reader's name for a project: 1 to NAME_MAX characters, no control characters, no space at either end."""
    return (isinstance(n, str) and 0 < len(n) <= NAME_MAX and n == n.strip()
            and not any(unicodedata.category(c) in ("Cc", "Cf") and c != "\u200d" for c in n))


def project_icon(v) -> bool:
    """{"icon": one of PROJECT_ICONS} or {"emoji": one emoji}."""
    return isinstance(v, dict) and len(v) == 1 and (v.get("icon") in PROJECT_ICONS or one_emoji(v.get("emoji")))


def valid_home(h) -> bool:
    if not isinstance(h, dict):
        return False
    for k, v in h.items():
        if k in HOME_LISTS:
            ok = isinstance(v, list) and all(isinstance(p, str) and p for p in v)
        elif k in HOME_MAPS:
            each = project_name if k == "names" else project_icon
            ok = isinstance(v, dict) and all(p and each(x) for p, x in v.items())
        else:
            ok = False
        if not ok:
            return False
    return True


def home() -> Path:
    return Path(os.environ.get("BLUEDOC_HOME") or "~/.bluedoc").expanduser()


def settings_file() -> Path:
    return home() / "settings.json"


def valid(name: str, value) -> bool:
    """Whether value has the shape settings.json keeps for name (null is never kept: it is the default)."""
    if name in SWITCHES:
        return isinstance(value, bool)
    if name == "chrome":
        return isinstance(value, str) and value != ""
    if name == "fontDirs":
        return isinstance(value, list) and all(isinstance(d, str) and d for d in value)
    if name == "shareAs":
        return isinstance(value, dict) and all(isinstance(k, str) and k and isinstance(v, str) and v for k, v in value.items())
    if name == "home":
        return valid_home(value)
    return False


def load() -> dict:
    """settings.json's known keys of the right shape; an unreadable file is empty."""
    try:
        data = json.loads(settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if valid(k, v)} if isinstance(data, dict) else {}


def save(changes: dict) -> dict:
    """Merge changes into settings.json (None removes a key) with an atomic replace; the file's new content."""
    data = load()
    for k, v in changes.items():
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    p = settings_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(p)
    return data


def env_value(name: str, raw: str):
    """The setting an environment variable's text gives."""
    if name in SWITCHES:
        return raw.strip().lower() not in OFF
    if name == "fontDirs":
        return [d for d in raw.split(os.pathsep) if d]
    return raw


def env_text(name: str) -> str | None:
    """`NAME=value` when the environment sets the setting's variable (not empty), else None."""
    raw = os.environ.get(ENV[name])
    return f"{ENV[name]}={raw}" if raw else None


def effective(name: str) -> tuple:
    """(value, source, env) of a setting: source env, file or default; env is env_text(name)."""
    env = env_text(name)
    if env:
        return env_value(name, os.environ[ENV[name]]), "env", env
    data = load()
    if name in data:
        return data[name], "file", None
    return DEFAULTS[name], "default", None
