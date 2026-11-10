"""Settings: $BLUEDOC_HOME/settings.json (scripts/settings.py) and the routes the home page's Settings uses.

For each setting (planHook, patchOnly, chrome, fontDirs) a set environment variable wins over the file and the file
over the default, and its consumer follows: hook.py skips plan mode when the file turns it off, the patch-only check
lets an edit of a built doc through when the file turns it off, fonts.font_dirs scans the file's folders,
serve.find_chrome takes the file's path. Against `serve.py run`: GET /settings is the home page, GET
/__bluedoc/settings reports each value and its source, POST /__bluedoc/settings writes the file (400 for a bad value,
409 when the environment sets the setting, 403 without the key); folders added and removed, a code link removed, a
framework removed, chrome-test with a stand-in Chrome, and a restart that comes back with a new `started`."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from _support import EXAMPLES, SCRIPTS, Server, TempHome

import fonts   # on sys.path through _support
import hook
import serve
import settings

ENV_NAMES = ("BLUEDOC_PLAN_HOOK", "BLUEDOC_PATCH_ONLY", "BLUEDOC_CHROME", "BLUEDOC_FONT_DIRS")
JSON_HDR = {"Content-Type": "application/json", "X-Bluedoc": "1"}


def fake_chrome(d: Path, version: str = "131.0.6778.86") -> Path:
    """A stand-in Chrome that answers --version."""
    p = d / "fake-chrome"
    p.write_text(f"#!/bin/sh\necho 'Google Chrome {version}'\n", encoding="utf-8")
    p.chmod(0o755)
    return p


def write_settings(home: Path, data: dict) -> None:
    (home / "settings.json").write_text(json.dumps(data), encoding="utf-8")


class Precedence(unittest.TestCase):
    """settings.effective in this process, with a temp BLUEDOC_HOME and none of the three variables set."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"BLUEDOC_HOME": str(self.tmp.home)})
        env.start()
        self.addCleanup(env.stop)
        for k in (*ENV_NAMES, "CI", "SSH_CONNECTION", "SSH_TTY"):
            os.environ.pop(k, None)

    def test_plan_hook_env_over_file_over_default(self) -> None:
        self.assertEqual(settings.effective("planHook"), (True, "default", None))
        write_settings(self.tmp.home, {"planHook": False})
        self.assertEqual(settings.effective("planHook"), (False, "file", None))
        os.environ["BLUEDOC_PLAN_HOOK"] = "1"
        self.assertEqual(settings.effective("planHook"), (True, "env", "BLUEDOC_PLAN_HOOK=1"))
        os.environ["BLUEDOC_PLAN_HOOK"] = "off"
        self.assertEqual(settings.effective("planHook"), (False, "env", "BLUEDOC_PLAN_HOOK=off"))
        os.environ["BLUEDOC_PLAN_HOOK"] = ""   # empty: not set
        self.assertEqual(settings.effective("planHook"), (False, "file", None))

    def test_the_hook_follows_plan_hook(self) -> None:
        self.assertIsNone(hook.no_reader({}))
        write_settings(self.tmp.home, {"planHook": False})
        self.assertEqual(hook.no_reader({}), "the plan-mode hook is off in Settings")
        os.environ["BLUEDOC_PLAN_HOOK"] = "1"
        self.assertIsNone(hook.no_reader({}))
        os.environ["BLUEDOC_PLAN_HOOK"] = "0"
        self.assertEqual(hook.no_reader({}), "BLUEDOC_PLAN_HOOK=0")

    def test_patch_only_env_over_file_over_default_and_the_check_follows(self) -> None:
        for name in ("acme-orders.bluedoc.json", "acme-orders.bluedoc.history.json"):
            shutil.copy(EXAMPLES / name, self.tmp.dir / name)
        built = [str(self.tmp.dir / "acme-orders.bluedoc.json")]
        self.assertEqual(settings.effective("patchOnly"), (True, "default", None))
        self.assertIn("is a built bluedoc doc", hook.patch_only(built, self.tmp.dir))
        write_settings(self.tmp.home, {"patchOnly": False})
        self.assertEqual(settings.effective("patchOnly"), (False, "file", None))
        self.assertIsNone(hook.patch_only(built, self.tmp.dir))
        os.environ["BLUEDOC_PATCH_ONLY"] = "1"
        self.assertEqual(settings.effective("patchOnly"), (True, "env", "BLUEDOC_PATCH_ONLY=1"))
        self.assertIsNotNone(hook.patch_only(built, self.tmp.dir))
        os.environ["BLUEDOC_PATCH_ONLY"] = "0"
        self.assertEqual(settings.effective("patchOnly"), (False, "env", "BLUEDOC_PATCH_ONLY=0"))
        self.assertIsNone(hook.patch_only(built, self.tmp.dir))

    def test_font_dirs_env_over_file_over_default(self) -> None:
        a, b = self.tmp.dir / "fonts-a", self.tmp.dir / "fonts-b"
        self.assertEqual(settings.effective("fontDirs"), (None, "default", None))
        self.assertEqual(fonts.font_dirs(), fonts.system_font_dirs())
        write_settings(self.tmp.home, {"fontDirs": [str(a)]})
        self.assertEqual(settings.effective("fontDirs"), ([str(a)], "file", None))
        self.assertEqual(fonts.font_dirs(), [a])
        os.environ["BLUEDOC_FONT_DIRS"] = os.pathsep.join([str(b), str(a)])
        self.assertEqual(settings.effective("fontDirs")[1:], ("env", f"BLUEDOC_FONT_DIRS={b}{os.pathsep}{a}"))
        self.assertEqual(fonts.font_dirs(), [b, a])

    def test_chrome_env_over_file_over_default(self) -> None:
        chrome = fake_chrome(self.tmp.dir)
        self.assertEqual(settings.effective("chrome"), (None, "default", None))
        write_settings(self.tmp.home, {"chrome": str(chrome)})
        self.assertEqual(settings.effective("chrome"), (str(chrome), "file", None))
        self.assertEqual(serve.find_chrome(), str(chrome))
        os.environ["BLUEDOC_CHROME"] = str(self.tmp.dir / "no-chrome")
        self.assertEqual(settings.effective("chrome")[1], "env")
        self.assertIsNone(serve.find_chrome(), "the variable wins, and it names nothing")

    def test_save_merges_and_null_removes(self) -> None:
        settings.save({"planHook": False, "fontDirs": ["/a"]})
        settings.save({"fontDirs": None, "chrome": "/c"})
        self.assertEqual(json.loads((self.tmp.home / "settings.json").read_text(encoding="utf-8")),
                         {"planHook": False, "chrome": "/c"})
        self.assertEqual(list(self.tmp.home.glob("*.tmp")), [])
        write_settings(self.tmp.home, {"planHook": "no", "chrome": 3, "fontDirs": "/a", "other": 1})
        self.assertEqual(settings.load(), {}, "values of the wrong shape are the default")


class Routes(unittest.TestCase):
    """`serve.py run` with a temp BLUEDOC_HOME whose settings.json names a stand-in Chrome."""

    def start(self, **env: str) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        for k in (*ENV_NAMES, "CI", "SSH_CONNECTION", "SSH_TTY"):
            self.tmp.env.pop(k, None)
        self.tmp.env.update(env)
        self.chrome = fake_chrome(self.tmp.dir)
        write_settings(self.tmp.home, {"chrome": str(self.chrome)})
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)

    def get(self, path: str) -> tuple[int, dict]:
        status, raw = self.server.req("GET", path)
        return status, json.loads(raw)

    def post(self, path: str, body: dict, **headers: str) -> tuple[int, dict]:
        status, raw = self.server.req("POST", path, json.dumps(body).encode(), {**JSON_HDR, **headers})
        return status, json.loads(raw)

    def file(self) -> dict:
        return json.loads((self.tmp.home / "settings.json").read_text(encoding="utf-8"))

    def test_the_settings_page_is_the_home_page(self) -> None:
        self.start()
        home, page = self.server.req("GET", "/"), self.server.req("GET", "/settings")
        self.assertEqual(page[0], 200)
        self.assertEqual(page[1], home[1])

    def test_get_reports_values_and_their_sources(self) -> None:
        self.start()
        status, v = self.get("/__bluedoc/settings")
        self.assertEqual(status, 200)
        self.assertEqual(set(v), {"folders", "repos", "frameworks", "presets", "agents", "tools", "server"})
        self.assertEqual(v["agents"], {"planHook": {"value": True, "source": "default", "env": None},
                                       "patchOnly": {"value": True, "source": "default", "env": None}})
        self.assertEqual(v["tools"]["chrome"], {"value": str(self.chrome), "source": "file", "env": None,
                                                "found": str(self.chrome), "version": "131.0.6778.86"})
        self.assertEqual(v["tools"]["fontDirs"]["source"], "default")
        self.assertEqual(v["tools"]["fontDirs"]["system"], [str(d) for d in fonts.system_font_dirs()])
        self.assertIn("daisyui", v["presets"])
        s = v["server"]
        self.assertEqual((s["port"], s["url"], s["portEnv"]), (self.server.port, f"http://127.0.0.1:{self.server.port}", None))
        self.assertEqual((s["home"], s["homeEnv"]), (str(self.tmp.home), f"BLUEDOC_HOME={self.tmp.home}"))
        _, ping = self.get("/__bluedoc/ping")
        self.assertEqual((s["started"], s["pid"]), (ping["started"], ping["pid"]))
        self.assertEqual(s["pid"], self.server.proc.pid)

    def test_post_writes_the_file_and_the_hook_follows(self) -> None:
        self.start()
        status, v = self.post("/__bluedoc/settings", {"planHook": False})
        self.assertEqual(status, 200, v)
        self.assertEqual(v["agents"]["planHook"], {"value": False, "source": "file", "env": None})
        self.assertFalse(self.file()["planHook"])
        req = {"text": "# Plan\n\nDo it.\n", "planPath": None, "cwd": str(self.tmp.dir), "sessionId": "s1", "agent": "pi"}
        r = subprocess.run([sys.executable, str(SCRIPTS / "hook.py"), "ext", "open"], input=json.dumps(req),
                           env=self.tmp.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(json.loads(r.stdout), {"state": "skip", "why": "the plan-mode hook is off in Settings"}, r.stderr)
        for name in ("acme-orders.bluedoc.json", "acme-orders.bluedoc.history.json"):
            shutil.copy(EXAMPLES / name, self.tmp.dir / name)
        edit = {"session_id": "s1", "cwd": str(self.tmp.dir), "hook_event_name": "PreToolUse", "tool_name": "Write",
                "tool_input": {"file_path": str(self.tmp.dir / "acme-orders.bluedoc.json"), "content": "{}"}}
        claude_edit = lambda: subprocess.run([sys.executable, str(SCRIPTS / "hook.py"), "claude", "edit"],  # noqa: E731
                                             input=json.dumps(edit), env=self.tmp.env, capture_output=True, text=True,
                                             timeout=60).stdout
        self.assertIn("permissionDecision", claude_edit())
        status, v = self.post("/__bluedoc/settings", {"patchOnly": False})
        self.assertEqual(status, 200, v)
        self.assertEqual(v["agents"]["patchOnly"], {"value": False, "source": "file", "env": None})
        self.assertEqual(claude_edit(), "", "the patch-only check is off in Settings")
        fdir = self.tmp.dir / "fonts"
        fdir.mkdir()
        status, v = self.post("/__bluedoc/settings", {"planHook": None, "patchOnly": None, "fontDirs": [str(fdir)]})
        self.assertEqual(status, 200, v)
        self.assertEqual(v["agents"]["planHook"]["source"], "default")
        self.assertEqual(v["tools"]["fontDirs"]["value"], [str(fdir.resolve())])
        self.assertEqual(self.file(), {"chrome": str(self.chrome), "fontDirs": [str(fdir.resolve())]})
        self.assertEqual(self.post("/__bluedoc/settings", {"fontDirs": []})[1]["tools"]["fontDirs"]["source"], "default")

    def test_bad_values_are_400_and_change_nothing(self) -> None:
        self.start()
        hosts = self.tmp.dir / "not-a-program"
        hosts.write_text("x", encoding="utf-8")
        for body, error in (({"planHook": "no"}, "planHook: true or false"),
                            ({"patchOnly": 0}, "patchOnly: true or false"),
                            ({"chrome": str(self.tmp.dir / "nope")}, f"No Chrome at {self.tmp.dir / 'nope'}"),
                            ({"chrome": str(hosts)}, f"{hosts} can't run (it isn't executable)"),
                            ({"fontDirs": [str(self.tmp.dir / "nope")]}, f"No folder at {self.tmp.dir / 'nope'}"),
                            ({"fontDirs": "/a"}, "fontDirs: a list of folders, or null"),
                            ({"planHook": False, "theme": "dark"}, "unknown setting: theme")):
            with self.subTest(body):
                self.assertEqual(self.post("/__bluedoc/settings", body), (400, {"error": error}))
        self.assertEqual(self.file(), {"chrome": str(self.chrome)})
        status, v = self.post("/__bluedoc/settings", {"planHook": False}, **{"X-Bluedoc-Key": "wrong"})
        self.assertEqual(status, 403)
        self.assertTrue(v["key"])

    def test_a_setting_the_environment_sets_is_409(self) -> None:
        fdir = TempHome()   # a folder that exists, for BLUEDOC_FONT_DIRS
        self.addCleanup(fdir.cleanup)
        self.start(BLUEDOC_PLAN_HOOK="0", BLUEDOC_PATCH_ONLY="off", BLUEDOC_FONT_DIRS=str(fdir.dir))
        self.assertEqual(self.post("/__bluedoc/settings", {"planHook": True}),
                         (409, {"error": "set by BLUEDOC_PLAN_HOOK in the environment"}))
        self.assertEqual(self.post("/__bluedoc/settings", {"patchOnly": True}),
                         (409, {"error": "set by BLUEDOC_PATCH_ONLY in the environment"}))
        self.assertEqual(self.post("/__bluedoc/settings", {"fontDirs": None}),
                         (409, {"error": "set by BLUEDOC_FONT_DIRS in the environment"}))
        _, v = self.get("/__bluedoc/settings")
        self.assertEqual(v["agents"]["planHook"], {"value": False, "source": "env", "env": "BLUEDOC_PLAN_HOOK=0"})
        self.assertEqual(v["agents"]["patchOnly"], {"value": False, "source": "env", "env": "BLUEDOC_PATCH_ONLY=off"})
        self.assertEqual(v["tools"]["fontDirs"]["env"], f"BLUEDOC_FONT_DIRS={fdir.dir}")
        self.assertEqual(self.file(), {"chrome": str(self.chrome)})

    def test_folders_add_and_remove(self) -> None:
        self.start()
        docs = self.tmp.copy_examples()
        count = sum(1 for _ in serve.walk_docs(docs))
        status, v = self.post("/__bluedoc/folders", {"add": str(docs)})
        self.assertEqual(status, 200, v)
        self.assertEqual(v["folders"], [{"path": str(docs), "display": serve.display_path(docs), "docs": count, "exists": True}])
        self.assertEqual(self.get("/__bluedoc/settings")[1]["folders"], v["folders"])
        missing = self.tmp.dir / "acme-blog"
        self.assertEqual(self.post("/__bluedoc/folders", {"add": str(missing)}), (400, {"error": f"No folder at {missing}"}))
        self.assertEqual(self.post("/__bluedoc/folders", {"add": str(docs)})[0], 400)
        inner = docs / "media"
        self.assertEqual(self.post("/__bluedoc/folders", {"add": str(inner)})[0], 400, "inside a listed folder")
        self.assertEqual(self.post("/__bluedoc/folders", {"remove": str(docs)}), (200, {"folders": []}))
        self.assertEqual(json.loads((self.tmp.home / "roots.json").read_text(encoding="utf-8")), [])
        self.assertEqual(self.post("/__bluedoc/folders", {"remove": str(docs)})[0], 400)

    def test_repos_remove(self) -> None:
        self.start()
        repo = self.tmp.dir / "acme-shop"
        repo.mkdir()
        (self.tmp.home / "repos.json").write_text(json.dumps({"acme-shop": str(repo), "acme-fit": str(self.tmp.dir / "gone")}),
                                                  encoding="utf-8")
        _, v = self.get("/__bluedoc/settings")
        self.assertEqual([(r["name"], r["exists"]) for r in v["repos"]], [("acme-fit", False), ("acme-shop", True)])
        status, v = self.post("/__bluedoc/repos", {"remove": "acme-fit"})
        self.assertEqual(status, 200, v)
        self.assertEqual(v["repos"], [{"name": "acme-shop", "path": str(repo), "display": serve.display_path(repo), "exists": True}])
        self.assertEqual(json.loads((self.tmp.home / "repos.json").read_text(encoding="utf-8")), {"acme-shop": str(repo)})
        self.assertEqual(self.post("/__bluedoc/repos", {"remove": "acme-fit"}), (400, {"error": "no code link named acme-fit"}))

    def test_frameworks_remove_and_unknown_preset(self) -> None:
        self.start()
        fw = self.tmp.home / "frameworks" / "acme-ui"
        fw.mkdir(parents=True)
        (fw / "acme.css").write_text("a{}", encoding="utf-8")
        (fw / "package.json").write_text('{"version": "2.1.0"}', encoding="utf-8")
        files = [{"path": "acme.css", "size": 3, "sha256": "x"}, {"path": "package.json", "size": 20, "sha256": "y"}]
        (fw / "manifest.json").write_text(json.dumps({"name": "acme-ui", "label": "Acme UI", "source": str(self.tmp.dir / "dist"),
                                                      "load": ["acme.css"], "files": files}), encoding="utf-8")
        _, v = self.get("/__bluedoc/settings")
        self.assertEqual(v["frameworks"], [{"name": "acme-ui", "label": "Acme UI", "version": "2.1.0", "files": 2, "bytes": 23,
                                            "source": serve.display_path(self.tmp.dir / "dist")}])
        self.assertEqual(self.post("/__bluedoc/frameworks", {"remove": "acme-ui"}), (200, {"frameworks": [], "presets": ["daisyui"]}))
        self.assertFalse(fw.exists())
        self.assertEqual(self.post("/__bluedoc/frameworks", {"remove": "acme-ui"}), (400, {"error": "no framework named acme-ui"}))
        self.assertEqual(self.post("/__bluedoc/frameworks", {"add": "acme-ui"}),
                         (400, {"error": "no preset named acme-ui (presets: daisyui)"}))

    def test_chrome_test(self) -> None:
        self.start()
        ok = {"ok": True, "path": str(self.chrome), "version": "131.0.6778.86"}
        self.assertEqual(self.post("/__bluedoc/chrome-test", {"path": None}), (200, ok))
        self.assertEqual(self.post("/__bluedoc/chrome-test", {"path": str(self.chrome)}), (200, ok))
        nope = self.tmp.dir / "nope"
        self.assertEqual(self.post("/__bluedoc/chrome-test", {"path": str(nope)}), (200, {"ok": False, "error": f"No Chrome at {nope}"}))

    def test_restart_comes_back_with_a_new_started(self) -> None:
        self.start()
        _, before = self.get("/__bluedoc/ping")
        self.assertTrue(before["started"])
        self.assertEqual(self.post("/__bluedoc/restart", {}), (200, {"ok": True}))
        deadline, after = time.monotonic() + 15, None
        while time.monotonic() < deadline:
            try:
                status, ping = self.get("/__bluedoc/ping")
                if status == 200 and ping["started"] != before["started"]:
                    after = ping
                    break
            except OSError:
                pass   # between the old server and the new one
            time.sleep(0.1)
        self.assertIsNotNone(after, "the server didn't come back")
        self.assertGreater(after["started"], before["started"])
        self.assertEqual(after["pid"], before["pid"])
        self.assertEqual(json.loads((self.tmp.home / "server.json").read_text(encoding="utf-8")),
                         {"pid": before["pid"], "port": self.server.port})
        self.assertEqual(self.post("/__bluedoc/settings", {"planHook": False})[0], 200, "the key still works")


if __name__ == "__main__":
    unittest.main()
