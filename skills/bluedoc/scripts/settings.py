"""bluedoc's settings, in $BLUEDOC_HOME/settings.json (the home page's Settings writes it; a missing key is its default):

  planHook   true | false       the plan-mode hook opens agents' plans as bluedoc pages (hook.py); env BLUEDOC_PLAN_HOOK
                                (0, false, no or off turn it off)
  patchOnly  true | false       patch-only edits: agents' edit tools can't change a built doc (hook.py patch_only); env
                                BLUEDOC_PATCH_ONLY (0, false, no or off turn it off)
  chrome     "<path>" | null    Chrome or Chromium for PDFs, decks, snapshots and captures (serve.find_chrome); null: the
                                usual places; env BLUEDOC_CHROME
  fontDirs   ["<dir>"] | null   the font folders fonts.py scans instead of this system's; env BLUEDOC_FONT_DIRS
                                (os.pathsep-separated)

An environment variable that is set (not empty) wins over the file, the file over the default. Python 3.9+ standard
library only."""
from __future__ import annotations

import json
import os
from pathlib import Path

ENV = {"planHook": "BLUEDOC_PLAN_HOOK", "patchOnly": "BLUEDOC_PATCH_ONLY", "chrome": "BLUEDOC_CHROME",
       "fontDirs": "BLUEDOC_FONT_DIRS"}
DEFAULTS: dict = {"planHook": True, "patchOnly": True, "chrome": None, "fontDirs": None}
SWITCHES = ("planHook", "patchOnly")   # true | false; the environment's 0, false, no or off is false
OFF = {"0", "false", "no", "off"}


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
