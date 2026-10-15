#!/usr/bin/env python3
"""Take a storelisting's screenshots from its capture recipes: `capture.py <doc> [--shot ID] [--target T] [--locale L]`.

A shot (an artboard with device "shot") may carry a `recipe`: {route, appearance: light|dark, settle: seconds,
targets: [target ids], locales: [locale codes], size: [w, h] (web only, CSS px)}. listing.capture names the devices and
the apps: {devices: {<target>: <simulator name or UDID | AVD name>}, apps: {ios|watchos: {bundle, app?}, android|wearos:
{package, apk?}, web: {url | design}}}. A recipe runs on its targets (default: the targets of the sets the shot fills,
store-rules.json `targets`), in each of its locales (default: listing.locales):

  ios-phone, ios-phone-63, ios-tablet, watchos   xcrun simctl: boot, status bar 9:41 (iOS only: watchOS has none),
                                                 appearance, launch with -AppleLanguages/-AppleLocale, openurl, screenshot
                                                 --mask=black (opaque corners)
  android-phone, android-tablet, wearos          adb and emulator: boot the AVD headless, SystemUI demo mode, uimode
                                                 night, per-app locale (Android 13+), am start, raw screencap saved as RGB
  web                                            headless Chrome (serve.HeadlessChrome.capture_png): a loopback dev server
                                                 (apps.web.url + route) or a design doc's screen (apps.web.design, route:
                                                 its artboard id), at the size of the shot's first set's UI x its scale

It preflights every target, boots each device once (and shuts down what it booted), and per locale and shot sets
appearance and locale, opens the route, settles and shoots. Each PNG is read back: no alpha, and a raw set's capture
(Apple Watch, Wear OS) must be the set's size. It writes <stem>.listing/captures/<target>/<locale>/<shot>.png (the one
it replaces moves to captures/old/<sha256 16>.png, so compare can show it) and captures/captures.json rows {shot,
target, locale, file, w, h, sha256, recipe: listing.recipe_hash, device, tools, at}.

Lines: `ok|skip|fail  <shot>  <target>  <locale>  <file WxH | why>`. Exit 0 when every capture ran, 1 when one failed,
3 when none failed but a target was skipped (a missing tool or device), 2 on a bad doc or argument. --dry-run prints
the commands only. --device <target>=<name> names another simulator or AVD for this run.

Python 3.9+ standard library only."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import listing  # noqa: E402

STEP_TIMEOUT = 60      # seconds a device command may take
BOOT_TIMEOUT = 300     # seconds a simulator or emulator may take to boot
DEFAULT_SETTLE = 2.0   # seconds after opening the route
APP_KIND = {"ios-phone": "ios", "ios-phone-63": "ios", "ios-tablet": "ios", "watchos": "watchos",
            "android-phone": "android", "android-tablet": "android", "wearos": "wearos", "web": "web"}
APPEARANCES = ("light", "dark")


class Skip(Exception):
    """A target that can't run here: a missing tool or device."""


class Fail(Exception):
    """One capture that failed."""


def say(kind: str, shot: str, target: str, locale: str, what: str) -> None:
    print(f"{kind:<5} {shot:<12} {target:<14} {locale:<6} {what}", flush=True)


def png_rgb(w: int, h: int, rgb: bytes) -> bytes:
    """A PNG (colour type 2, 8 bits, filter 0 on every row) of w × h RGB pixels."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    stride = w * 3
    rows = b"".join(b"\0" + rgb[y * stride:(y + 1) * stride] for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


def raw_screencap_png(data: bytes) -> bytes:
    """`adb exec-out screencap` (no -p): a 12- or 16-byte header (w, h, format[, colour space]) then RGBA_8888 rows, as
    an RGB PNG. The -p PNG carries an alpha channel (colour type 6) the stores refuse; this one has none. Fail when a
    pixel isn't opaque or the format isn't RGBA_8888."""
    if len(data) < 12:
        raise Fail("screencap returned no image")
    w, h, fmt = struct.unpack("<III", data[:12])
    head = len(data) - w * h * 4
    if head not in (12, 16) or fmt != 1:
        raise Fail(f"screencap format {fmt} with {head} header bytes: want RGBA_8888")
    px = data[head:]
    if px[3::4].count(255) != w * h:
        raise Fail("the screen has transparent pixels")
    rgb = bytearray(w * h * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = px[0::4], px[1::4], px[2::4]
    return png_rgb(w, h, bytes(rgb))


class Runner:
    """Runs a device command, or prints it (--dry-run)."""

    def __init__(self, dry: bool) -> None:
        self.dry = dry

    def __call__(self, argv: list[str], *, timeout: float = STEP_TIMEOUT, check: bool = True, binary: bool = False):
        if self.dry:
            print("  $ " + " ".join(_q(a) for a in argv), flush=True)
            return b"" if binary else ""
        try:
            r = subprocess.run(argv, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise Fail(f"{Path(argv[0]).name} {' '.join(argv[1:3])}: no answer in {int(timeout)} s")
        except OSError as e:
            raise Fail(f"{argv[0]}: {e}")
        if check and r.returncode != 0:
            err = (r.stderr or r.stdout).decode("utf-8", "replace").strip().splitlines()
            raise Fail(f"{Path(argv[0]).name} {' '.join(argv[1:3])}: {err[-1] if err else 'exit ' + str(r.returncode)}")
        return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def _q(a: str) -> str:
    return a if re.fullmatch(r"[\w@%+=:,./-]+", a) else "'" + a.replace("'", "'\\''") + "'"


# ---------- targets ----------

class Simctl:
    """An iOS or watchOS simulator through `xcrun simctl`."""

    def __init__(self, run: Runner, target: str, device: str, app: dict, doc_dir: Path) -> None:
        self.run, self.target, self.device, self.app, self.doc_dir = run, target, device, app, doc_dir
        self.udid, self.booted, self.runtime, self.was_appearance = device, False, "", None
        self.watch = target == "watchos"

    def preflight(self) -> None:
        if not shutil.which("xcrun"):
            raise Skip("xcrun not found: install Xcode and its iOS and watchOS runtimes")
        if not isinstance(self.app.get("bundle"), str):
            raise Skip(f"no app: set listing.capture.apps.{APP_KIND[self.target]}.bundle")
        if self.run.dry:
            self.udid = self.device
            return
        try:
            listed = json.loads(self.run(["xcrun", "simctl", "list", "devices", "available", "-j"]))["devices"]
        except (Fail, ValueError, KeyError) as e:
            raise Skip(f"xcrun simctl list failed: {e}")
        found = [(rt, d) for rt, ds in listed.items() for d in ds if self.device in (d.get("name"), d.get("udid"))]
        if not found:
            raise Skip(f"no simulator '{self.device}': add it in Xcode (Window > Devices and Simulators) or name "
                       f"another with --device {self.target}=<name>")
        # a booted one first, else the newest runtime's
        rt, d = max(found, key=lambda x: (x[1].get("state") == "Booted", _version(x[0])))
        self.udid, self.runtime = d["udid"], _runtime_name(rt)
        self.booted = d.get("state") != "Booted"   # we boot it, so we shut it down

    def boot(self) -> None:
        if self.booted or self.run.dry:
            self.run(["xcrun", "simctl", "boot", self.udid], check=False)
        self.run(["xcrun", "simctl", "bootstatus", self.udid, "-b"], timeout=BOOT_TIMEOUT)
        if not self.watch:   # watchOS has no status bar overrides and no appearance setting
            self.run(["xcrun", "simctl", "status_bar", self.udid, "override", "--time", "9:41", "--batteryState", "charged",
                      "--batteryLevel", "100", "--cellularMode", "active", "--cellularBars", "4", "--wifiBars", "3",
                      "--dataNetwork", "wifi", "--operatorName", ""])
            was = self.run(["xcrun", "simctl", "ui", self.udid, "appearance"], check=False).strip()
            self.was_appearance = was if was in APPEARANCES else None
        if self.app.get("app"):
            self.run(["xcrun", "simctl", "install", self.udid, str(self.doc_dir / self.app["app"])], timeout=BOOT_TIMEOUT)
        if not self.run.dry:
            try:
                self.run(["xcrun", "simctl", "get_app_container", self.udid, self.app["bundle"]])
            except Fail:
                raise Fail(f"{self.app['bundle']} is not installed on {self.device}: set apps.{APP_KIND[self.target]}.app")

    def tools(self) -> str:
        if self.run.dry or not shutil.which("xcodebuild"):
            return self.runtime
        xcode = self.run(["xcodebuild", "-version"], check=False).splitlines()[:1]
        return ", ".join(x for x in [*(s.strip() for s in xcode), self.runtime] if x)

    def shoot(self, locale: str, recipe: dict, out: Path) -> bytes:
        bundle = self.app["bundle"]
        if not self.watch:
            self.run(["xcrun", "simctl", "ui", self.udid, "appearance", recipe.get("appearance") or "light"])
        self.run(["xcrun", "simctl", "launch", "--terminate-running-process", self.udid, bundle,
                  "-AppleLanguages", f"({locale})", "-AppleLocale", locale.replace("-", "_")])
        if recipe.get("route"):
            self.run(["xcrun", "simctl", "openurl", self.udid, recipe["route"]])
        settle(self.run, recipe)
        self.run(["xcrun", "simctl", "io", self.udid, "screenshot", "--type=png", "--mask=black", str(out)])
        return b"" if self.run.dry else out.read_bytes()

    def reset(self) -> None:
        if not self.watch:
            self.run(["xcrun", "simctl", "status_bar", self.udid, "clear"], check=False)
            if self.was_appearance:
                self.run(["xcrun", "simctl", "ui", self.udid, "appearance", self.was_appearance], check=False)
        if self.booted and not self.run.dry:
            self.run(["xcrun", "simctl", "shutdown", self.udid], check=False)


def _version(runtime_id: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", runtime_id.rsplit(".", 1)[-1]))


def _runtime_name(runtime_id: str) -> str:
    m = re.search(r"SimRuntime\.([A-Za-z]+)-([\d-]+)$", runtime_id)
    return f"{m[1]} {m[2].replace('-', '.')}" if m else runtime_id


def android_tool(name: str) -> str | None:
    """adb or emulator: on PATH, else under ANDROID_HOME, ANDROID_SDK_ROOT or the SDK's usual place."""
    found = shutil.which(name)
    if found:
        return found
    sub = "platform-tools" if name == "adb" else "emulator"
    for root in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
                 str(Path.home() / "Library" / "Android" / "sdk"), str(Path.home() / "Android" / "Sdk")):
        if root and (Path(root) / sub / name).is_file():
            return str(Path(root) / sub / name)
    return None


class Adb:
    """An Android or Wear OS emulator through adb (an AVD already running is used as it is; else it boots headless)."""

    def __init__(self, run: Runner, target: str, device: str, app: dict, doc_dir: Path) -> None:
        self.run, self.target, self.device, self.app, self.doc_dir = run, target, device, app, doc_dir
        self.adb = self.emulator = ""
        self.serial, self.proc, self.sdk, self.was_night = "emulator-5580", None, 0, None

    def a(self, *args: str) -> list[str]:
        return [self.adb, "-s", self.serial, *args]

    def preflight(self) -> None:
        self.adb = android_tool("adb") or ""
        if not self.adb:
            raise Skip("adb not found: install platform-tools or set ANDROID_HOME")
        if not isinstance(self.app.get("package"), str):
            raise Skip(f"no app: set listing.capture.apps.{APP_KIND[self.target]}.package")
        if self.run.dry:
            self.emulator = android_tool("emulator") or "emulator"
            return
        for line in self.run([self.adb, "devices"]).splitlines()[1:]:
            serial = line.split("\t")[0]
            if line.endswith("\tdevice") and serial.startswith("emulator-"):
                name = self.run([self.adb, "-s", serial, "emu", "avd", "name"], check=False).splitlines()
                if name and name[0].strip() == self.device:
                    self.serial = serial
                    return
        self.emulator = android_tool("emulator") or ""
        if not self.emulator:
            raise Skip("emulator not found: install the Android Emulator or set ANDROID_HOME")
        if self.device not in self.run([self.emulator, "-list-avds"]).split():
            raise Skip(f"no AVD '{self.device}': create it in Android Studio's Device Manager, or name another with "
                       f"--device {self.target}=<avd>")
        used = set(re.findall(r"emulator-(\d+)", self.run([self.adb, "devices"])))
        port = next(p for p in range(5580, 5682, 2) if str(p) not in used and str(p + 1) not in used)
        self.serial = f"emulator-{port}"

    def boot(self) -> None:
        if self.emulator:   # not running yet: boot it headless, without saving a snapshot over the AVD's
            argv = [self.emulator, "-avd", self.device, "-no-window", "-no-audio", "-no-boot-anim", "-no-snapshot-save",
                    "-port", self.serial.split("-")[1]]
            if self.run.dry:
                self.run(argv)
            else:
                self.proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.run(self.a("wait-for-device"), timeout=BOOT_TIMEOUT)
        deadline = time.monotonic() + BOOT_TIMEOUT
        while not self.run.dry and self.run(self.a("shell", "getprop", "sys.boot_completed"), check=False).strip() != "1":
            if time.monotonic() > deadline or (self.proc and self.proc.poll() is not None):
                raise Fail(f"{self.device} did not boot in {BOOT_TIMEOUT} s")
            time.sleep(1)
        if self.run.dry:
            print(f"  $ {_q(self.adb)} -s {self.serial} shell getprop sys.boot_completed   # until 1", flush=True)
        self.sdk = int(self.run(self.a("shell", "getprop", "ro.build.version.sdk"), check=False).strip() or 0)
        self.run(self.a("shell", "settings", "put", "global", "sysui_demo_allowed", "1"))
        self.demo()
        was = self.run(self.a("shell", "cmd", "uimode", "night"), check=False).strip().rsplit(" ", 1)[-1]
        self.was_night = was if was in ("yes", "no") else None
        if self.app.get("apk"):
            self.run(self.a("install", "-r", str(self.doc_dir / self.app["apk"])), timeout=BOOT_TIMEOUT)
        if not self.run.dry and not self.run(self.a("shell", "pm", "path", self.app["package"]), check=False).strip():
            raise Fail(f"{self.app['package']} is not installed on {self.device}: set apps.{APP_KIND[self.target]}.apk")

    def demo(self) -> None:
        """SystemUI demo mode: 9:41, full battery and signal, no notifications. Sent again before each shot: a fresh
        SystemUI (just booted, or a night-mode change) drops it."""
        demo = ["shell", "am", "broadcast", "-a", "com.android.systemui.demo", "-e", "command"]
        for extra in (["enter"], ["clock", "-e", "hhmm", "0941"], ["battery", "-e", "level", "100", "-e", "plugged", "false"],
                      ["network", "-e", "wifi", "show", "-e", "level", "4"],
                      ["network", "-e", "mobile", "show", "-e", "datatype", "none", "-e", "level", "4"],
                      ["notifications", "-e", "visible", "false"]):
            self.run(self.a(*demo, *extra))

    def tools(self) -> str:
        if self.run.dry:
            return ""
        v = self.run([self.adb, "version"], check=False).splitlines()[:1]
        return ", ".join([*(s.strip() for s in v), f"Android API {self.sdk}"])

    def shoot(self, locale: str, recipe: dict, out: Path) -> bytes:
        pkg = self.app["package"]
        self.run(self.a("shell", "cmd", "uimode", "night", "yes" if recipe.get("appearance") == "dark" else "no"))
        if self.sdk and self.sdk < 33:
            raise Fail(f"per-app locales need Android 13 (API 33); {self.device} is API {self.sdk}")
        self.run(self.a("shell", "cmd", "locale", "set-app-locales", pkg, "--locales", locale))
        self.run(self.a("shell", "am", "force-stop", pkg))
        if recipe.get("route"):
            self.run(self.a("shell", "am", "start", "-W", "-a", "android.intent.action.VIEW", "-d", recipe["route"], pkg))
        else:
            found = self.run(self.a("shell", "cmd", "package", "resolve-activity", "--brief", "-a", "android.intent.action.MAIN",
                                    "-c", "android.intent.category.LAUNCHER", pkg)).strip().splitlines()
            comp = found[-1].strip() if found and "/" in found[-1] else f"{pkg}/<launcher activity>"
            self.run(self.a("shell", "am", "start", "-W", "-n", comp))
        settle(self.run, recipe)
        self.demo()
        if not self.run.dry:
            time.sleep(0.5)   # SystemUI redraws the status bar
        raw = self.run(self.a("exec-out", "screencap"), binary=True)
        return b"" if self.run.dry else raw_screencap_png(raw)

    def reset(self) -> None:
        self.run(self.a("shell", "am", "broadcast", "-a", "com.android.systemui.demo", "-e", "command", "exit"), check=False)
        if self.app.get("package"):
            self.run(self.a("shell", "cmd", "locale", "set-app-locales", self.app["package"], "--locales", ""), check=False)
        if self.was_night:
            self.run(self.a("shell", "cmd", "uimode", "night", self.was_night), check=False)
        if self.proc:
            self.run(self.a("emu", "kill"), check=False)
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class Web:
    """Headless Chrome on a loopback dev server or a design doc's screens (serve.py renders them as its screen route)."""

    def __init__(self, run: Runner, target: str, device: str, app: dict, doc_dir: Path) -> None:
        self.run, self.target, self.app, self.doc_dir = run, target, app, doc_dir
        self.chrome, self.ch, self.design, self.tmp = "", None, None, None

    def preflight(self) -> None:
        import serve   # Chrome and the screen renderer; serve.py imports build.py, which nothing else here needs
        self.serve = serve
        if not (self.app.get("url") or self.app.get("design")):
            raise Skip("no app: set listing.capture.apps.web.url (a loopback dev server) or .design (a design doc)")
        if self.app.get("url"):
            import build
            why = build.live_url_problem(self.app["url"])
            if why:
                raise Skip(f"apps.web.url: {why}")
        else:
            f = self.doc_dir / str(self.app["design"])
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise Skip(f"apps.web.design: cannot read {f.name}: {e}")
            self.design = (f, d)
        self.chrome = serve.find_chrome() or ""
        if not self.chrome:
            raise Skip("Chrome not found: set BLUEDOC_CHROME")

    def boot(self) -> None:
        if self.run.dry:
            print(f"  $ {_q(self.chrome)} --headless=new --remote-debugging-port=0 …", flush=True)
            return
        self.ch = self.serve.HeadlessChrome(self.chrome)
        self.tmp = Path(tempfile.mkdtemp(prefix="bluedoc-capture-"))

    def tools(self) -> str:
        return self.ch.call("Browser.getVersion").get("product", "") if self.ch else ""

    def url(self, route: str) -> str:
        if self.app.get("url"):
            return self.app["url"].rstrip("/") + "/" + route.lstrip("/") if route else self.app["url"]
        f, d = self.design
        if not listing.ID_RE.match(route or ""):
            raise Fail(f"route {route!r}: an artboard id of {f.name}")
        text = self.serve.current_screen_text(d, f, route, None)
        if text is None:
            raise Fail(f"{f.name} has no screen '{route}'")
        if self.run.dry:
            return f"{f.name}#{route}"
        page = self.tmp / f"{route}.html"
        page.write_text(self.serve.wrap_screen(d, f, route, text, inline=True), encoding="utf-8")
        return page.as_uri()

    def shoot(self, locale: str, recipe: dict, out: Path, size: tuple[int, int, int]) -> bytes:
        w, h, scale = size
        url = self.url(recipe.get("route") or "")
        if self.run.dry:
            print(f"  chrome: {url} at {w}×{h} CSS px × {scale}, {recipe.get('appearance') or 'light'}, {locale}", flush=True)
            return b""
        try:
            return self.ch.capture_png(url, w, h, scale, dark=recipe.get("appearance") == "dark", locale=locale,
                                       settle=_settle(recipe))
        except (RuntimeError, OSError, ValueError) as e:
            raise Fail(f"Chrome: {e}")

    def reset(self) -> None:
        if self.ch:
            self.ch.close()
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)


TOOLS = {"simctl": Simctl, "adb": Adb, "chrome": Web}


def _settle(recipe: dict) -> float:
    s = recipe.get("settle", DEFAULT_SETTLE)
    return float(s) if isinstance(s, (int, float)) and not isinstance(s, bool) and 0 <= s <= 30 else DEFAULT_SETTLE


def settle(run: Runner, recipe: dict) -> None:
    if run.dry:
        print(f"  (settle {_settle(recipe):g} s)", flush=True)
    else:
        time.sleep(_settle(recipe))


# ---------- the run ----------

def jobs_of(doc: dict, lb: dict, rules: dict, shots: list[str], targets: list[str], locales: list[str]) -> list[tuple[dict, str, str]]:
    """(shot, target, locale) for every shot with a recipe, its targets and locales, as the filters narrow them."""
    out = []
    for a in listing.shots_of(doc):
        if a.get("device") != "shot" or not isinstance(a.get("recipe"), dict) or (shots and a["id"] not in shots):
            continue
        for t in listing.recipe_targets(a, rules):
            if targets and t not in targets:
                continue
            for loc in listing.recipe_locales(a, lb):
                if not locales or loc in locales:
                    out.append((a, t, loc))
    return out


def web_size(a: dict, rules: dict) -> tuple[int, int, int]:
    """A web capture's viewport: the recipe's size (CSS px), else the UI viewport of the shot's first set; its scale."""
    sets = listing.by_id(rules, "sets")
    r = next((sets[s] for s in a.get("sets") or [] if s in sets), None)
    w, h = (a["recipe"].get("size") if isinstance(a["recipe"].get("size"), list) else listing.ui_size(r) if r else (390, 844))
    return int(w), int(h), int(r["scale"]) if r else 3


def raw_rule(a: dict, target: str, rules: dict) -> dict | None:
    """The raw set (the capture is the shot itself) this target fills for the shot, if any."""
    sets = listing.by_id(rules, "sets")
    return next((sets[s] for s in a.get("sets") or [] if s in sets and sets[s].get("raw") and sets[s].get("target") == target), None)


def check_png(data: bytes, raw: dict | None, rules: dict) -> tuple[dict, str | None]:
    info = listing.png_info(data)
    if info is None:
        return {}, "not a PNG"
    if info["colour"] in (4, 6) or info["trns"]:
        return info, "the PNG has an alpha channel: the stores refuse transparency"
    if raw:
        why = listing.size_problem(raw, info["w"], info["h"])
        if why:
            dev = next((t.get("device") for t in rules["targets"] if t["id"] == raw.get("target")), None)
            return info, f"want {why}, got {info['w']}×{info['h']}" + (f": use {dev}" if dev else "")
    return info, None


def no_link_on_the_way(base: Path, f: Path) -> None:
    p = base
    for part in f.relative_to(base).parts:
        p = p / part
        if p.is_symlink():
            raise Fail(f"{p.relative_to(base)} is a link")


def write_capture(doc_path: Path, rel: str, data: bytes) -> str:
    """Write data at rel (under the doc's folder) atomically; the PNG it replaces, when different, moves to
    captures/old/<its sha256, 16 hex>.png. The new PNG's sha256."""
    base = doc_path.parent
    f = base / rel
    no_link_on_the_way(base, f)
    sha = hashlib.sha256(data).hexdigest()
    f.parent.mkdir(parents=True, exist_ok=True)
    if f.is_file():
        old = f.read_bytes()
        osha = hashlib.sha256(old).hexdigest()
        if osha != sha:
            keep = listing.listing_dir(doc_path) / "captures" / "old" / f"{osha[:16]}.png"
            no_link_on_the_way(base, keep)
            keep.parent.mkdir(parents=True, exist_ok=True)
            if not keep.exists():
                os.replace(f, keep)
    fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=".bd-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, f)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return sha


def save_rows(doc_path: Path, rows: list[dict]) -> None:
    """Merge rows into captures.json: a row replaces the one of the same shot, target and locale."""
    f = listing.listing_dir(doc_path) / "captures" / "captures.json"
    try:
        old = json.loads(f.read_text(encoding="utf-8")).get("captures") or []
    except (OSError, ValueError, AttributeError):
        old = []
    key = lambda r: (r.get("shot"), r.get("target"), r.get("locale"))  # noqa: E731
    new = {key(r) for r in rows}
    merged = [r for r in old if isinstance(r, dict) and key(r) not in new] + rows
    merged.sort(key=lambda r: tuple(str(x) for x in key(r)))
    no_link_on_the_way(doc_path.parent, f)
    f.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=".bd-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump({"captures": merged}, out, indent=1, ensure_ascii=False)
            out.write("\n")
        os.replace(tmp, f)
    finally:
        Path(tmp).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="capture.py", description="Take a storelisting's screenshots from its recipes "
                                 "on simulators, emulators and headless Chrome.")
    ap.add_argument("doc", type=Path)
    ap.add_argument("--shot", action="append", default=[], metavar="ID", help="only this shot (repeat for more)")
    ap.add_argument("--target", action="append", default=[], metavar="T", help="only this target (repeat for more)")
    ap.add_argument("--locale", action="append", default=[], metavar="L", help="only this locale (repeat for more)")
    ap.add_argument("--device", action="append", default=[], metavar="T=NAME", help="this run's simulator or AVD for a target")
    ap.add_argument("--dry-run", action="store_true", help="print the commands only")
    a = ap.parse_args(argv)
    try:
        doc = json.loads(a.doc.read_text(encoding="utf-8"))
        rules = listing.load_rules()
    except (OSError, ValueError) as e:
        print(f"cannot read {a.doc}: {e}", file=sys.stderr)
        return 2
    lb = listing.listing_of(doc)
    if lb is None:
        print(f"{a.doc}: no listing block: capture.py takes a storelisting doc", file=sys.stderr)
        return 2
    known = {t["id"]: t for t in rules["targets"]}
    over: dict[str, str] = {}
    for d in a.device:
        t, eq, name = d.partition("=")
        if not eq or t not in known or not name:
            ap.error(f"--device {d!r}: <target>=<simulator or AVD name>, target one of {', '.join(known)}")
        over[t] = name
    for t in a.target:
        if t not in known:
            ap.error(f"--target {t!r}: one of {', '.join(known)}")
    jobs = jobs_of(doc, lb, rules, a.shot, a.target, a.locale)
    if not jobs:
        print("no capture to take: no shot with a recipe" + (" matches the filters" if a.shot or a.target or a.locale else ""),
              file=sys.stderr)
        return 2
    cap = lb.get("capture") if isinstance(lb.get("capture"), dict) else {}
    devices = cap.get("devices") if isinstance(cap.get("devices"), dict) else {}
    apps = cap.get("apps") if isinstance(cap.get("apps"), dict) else {}
    doc_path = a.doc.resolve()
    run = Runner(a.dry_run)
    by_target: dict[str, list[tuple[dict, str]]] = {}
    for shot, t, loc in jobs:
        by_target.setdefault(t, []).append((shot, loc))
    failed = skipped = 0
    rows: list[dict] = []
    stem_dir = listing.listing_dir(doc_path).name
    for t, todo in by_target.items():
        rule = known[t]
        device = over.get(t) or devices.get(t) or ("" if rule["tool"] == "adb" else rule["device"])
        app = apps.get(APP_KIND[t]) if isinstance(apps.get(APP_KIND[t]), dict) else {}
        dev = TOOLS[rule["tool"]](run, t, str(device), app, doc_path.parent)
        try:
            if rule["tool"] == "adb" and not device:
                raise Skip(f"no AVD named: set listing.capture.devices.{t}, or --device {t}=<avd>")
            if a.dry_run:
                print(f"# {t} on {device or 'headless Chrome'}", flush=True)
            dev.preflight()
        except Skip as e:
            for shot, loc in todo:
                say("skip", shot["id"], t, loc, str(e))
            skipped += 1
            continue
        try:
            try:
                dev.boot()
                tools = dev.tools()
            except Fail as e:
                for shot, loc in todo:
                    say("fail", shot["id"], t, loc, str(e))
                failed += len(todo)
                continue
            for loc in dict.fromkeys(loc for _, loc in todo):
                for shot in [s for s, x in todo if x == loc]:
                    rel = f"{stem_dir}/captures/{t}/{loc}/{shot['id']}.png"
                    try:
                        if a.dry_run:
                            print(f"# {shot['id']} {loc} -> {rel}", flush=True)
                        with tempfile.TemporaryDirectory(prefix="bluedoc-shot-") as td:
                            out = Path(rel) if a.dry_run else Path(td) / "shot.png"
                            data = (dev.shoot(loc, shot["recipe"], out, web_size(shot, rules)) if isinstance(dev, Web)
                                    else dev.shoot(loc, shot["recipe"], out))
                        if a.dry_run:
                            continue
                        info, why = check_png(data, raw_rule(shot, t, rules), rules)
                        if why:
                            raise Fail(why)
                        sha = write_capture(doc_path, rel, data)
                    except Fail as e:
                        say("fail", shot["id"], t, loc, str(e))
                        failed += 1
                        continue
                    rows.append({"shot": shot["id"], "target": t, "locale": loc, "file": rel, "w": info["w"], "h": info["h"],
                                 "sha256": sha, "recipe": listing.recipe_hash(shot["recipe"]), "device": device or "headless Chrome",
                                 "tools": tools, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
                    say("ok", shot["id"], t, loc, f"{rel.split('/', 1)[1]}  {info['w']}×{info['h']}")
        finally:
            dev.reset()
    if rows:
        save_rows(doc_path, rows)
    return 1 if failed else 3 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
