"""hook.py, the Claude Code plan gate, against `serve.py run`: a plan is imported and opened and ExitPlanMode is denied
with instructions; the same plan stays one doc until the reader approves it, then ExitPlanMode is allowed; a rewritten
plan becomes the next rev; a plan that names a bluedoc doc opens that doc; the guards print nothing; the Bash hook
allows only the gate's own commands."""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import unittest
from pathlib import Path

from _support import SCRIPTS, Server, TempHome

PLAN = """# Add rate limiting

Requests have no limit.

## Steps
1. Add a token bucket in `src/bucket.ts`
2. Return 429 from `src/server.ts`
"""
JSON_HDR = {"Content-Type": "application/json", "X-Bluedoc": "1"}


class PlanGate(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        for k in ("CI", "BLUEDOC_PLAN_GATE", "SSH_CONNECTION", "SSH_TTY"):
            self.tmp.env.pop(k, None)
        self.tmp.env["BROWSER"] = "true"   # webbrowser runs `true` instead of opening a tab
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.project = self.tmp.dir / "acme-shop"
        self.project.mkdir()
        self.plan_file = self.tmp.dir / "claude-plans" / "rate-limits.md"
        self.plan_file.parent.mkdir()
        self.plan_file.write_text(PLAN, encoding="utf-8")
        self.plans = self.tmp.home / "plans" / "acme-shop"

    def hook(self, event: str, payload: dict, **env: str) -> dict | None:
        r = subprocess.run([sys.executable, str(SCRIPTS / "hook.py"), "claude", event], input=json.dumps(payload),
                           env={**self.tmp.env, **env}, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        log = self.tmp.home / "hooks" / "hook.log"
        self.assertNotIn("failed", log.read_text(encoding="utf-8") if log.exists() else "")
        return json.loads(r.stdout) if r.stdout.strip() else None

    def plan_event(self, **over) -> dict:
        return {"session_id": "s1", "cwd": str(self.project), "permission_mode": "plan", "hook_event_name": "PermissionRequest",
                "tool_name": "ExitPlanMode", "tool_input": {"plan": PLAN, "planFilePath": str(self.plan_file)}, **over}

    def decision(self, out: dict | None) -> dict:
        self.assertIsNotNone(out)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PermissionRequest")
        return out["hookSpecificOutput"]["decision"]

    def approve(self, doc: Path) -> None:
        url = self.server.url_for(doc)
        html = self.server.req("GET", url)[1].decode()
        seed = json.loads(re.search(r'<script type="application/json" id="bp-state">(.*?)</script>', html, re.S).group(1))
        rev = json.loads(doc.read_text(encoding="utf-8"))["meta"]["rev"]
        body = {"path": url, "rev": rev, "docHash": seed["docHash"], "decision": "approved", "answers": [], "annotations": [],
                "at": "2026-01-01T00:00:00Z", "markdown": "# Plan approved\n"}
        status, raw = self.server.req("POST", "/__bluedoc/approve", json.dumps(body).encode(), JSON_HDR)
        self.assertEqual(status, 200, raw)

    def test_deny_until_approved_then_allow(self) -> None:
        d = self.decision(self.hook("plan", self.plan_event()))
        self.assertEqual(d["behavior"], "deny")
        doc = self.plans / "rate-limits.bluedoc.json"
        self.assertTrue(doc.is_file())
        self.assertIn(str(doc), d["message"])
        self.assertIn("serve.py", d["message"])
        self.assertIn("wait", d["message"])
        self.assertRegex(d["message"], r"http://127\.0\.0\.1:\d+/")
        # Claude calls again before the reader answered: same doc, same rev, denied again
        self.assertEqual(self.decision(self.hook("plan", self.plan_event()))["behavior"], "deny")
        self.assertEqual(json.loads(doc.read_text(encoding="utf-8"))["meta"]["rev"], "1")
        self.assertEqual(list(self.plans.glob("*.bluedoc.json")), [doc])
        self.approve(doc)
        d = self.decision(self.hook("plan", self.plan_event()))
        self.assertEqual(d["behavior"], "allow")
        self.assertEqual(d["updatedInput"]["planFilePath"], str(self.plan_file))
        self.assertTrue(d["updatedInput"]["plan"].startswith(PLAN))
        self.assertIn("Approved in bluedoc, rev 1", d["updatedInput"]["plan"])
        # the session's next plan starts a new doc
        self.assertFalse((self.tmp.home / "hooks" / "claude" / "s1.json").exists())

    def test_a_rewritten_plan_is_the_next_rev(self) -> None:
        self.hook("plan", self.plan_event())
        self.plan_file.write_text(PLAN + "3. Add tests in `test/bucket.test.ts`\n", encoding="utf-8")
        self.assertEqual(self.decision(self.hook("plan", self.plan_event()))["behavior"], "deny")
        doc = json.loads((self.plans / "rate-limits.bluedoc.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["meta"]["rev"], "2")
        self.assertEqual(len(next(b for s in doc["sections"] for b in s["blocks"] if b["type"] == "steps")["items"]), 3)

    def test_a_plan_that_names_a_bluedoc_opens_it(self) -> None:
        mine = self.project / "docs" / "plans" / "limits.bluedoc.json"
        r = self.tmp.run("build.py", "new", "plan", mine, "--title", "Limits")
        self.assertEqual(r.returncode, 0, r.stderr)
        payload = self.plan_event(tool_input={"plan": "See `docs/plans/limits.bluedoc.json`.", "planFilePath": ""})
        d = self.decision(self.hook("plan", payload))
        self.assertEqual(d["behavior"], "deny")
        self.assertIn(str(mine.resolve()), d["message"])
        self.assertFalse(self.plans.exists(), "nothing imported")

    def test_guards_print_nothing(self) -> None:
        for name, env, over in (("off switch", {"BLUEDOC_PLAN_GATE": "0"}, {}), ("CI", {"CI": "true"}, {}),
                                ("bypass mode", {}, {"permission_mode": "bypassPermissions"})):
            with self.subTest(name):
                self.assertIsNone(self.hook("plan", self.plan_event(**over), **env))
        self.assertFalse(self.plans.exists())

    def test_bash_hook_allows_only_the_gate_commands(self) -> None:
        self.hook("plan", self.plan_event())
        doc = self.plans / "rate-limits.bluedoc.json"
        serve, build = shlex.quote(str(SCRIPTS / "serve.py")), shlex.quote(str(SCRIPTS / "build.py"))
        ok = [f"python3 {serve} wait {shlex.quote(str(doc))} --kind any",
              f"python3 {build} patch {shlex.quote(str(doc))} step:steps/0/x --set status=done --change 'Done.'"]
        no = [f"python3 {serve} wait {shlex.quote(str(doc))} && rm -rf ~",
              f"python3 {serve} stop {shlex.quote(str(doc))}",
              f"python3 {build} patch {shlex.quote(str(self.tmp.dir / 'other.bluedoc.json'))} k --delete",
              f"python3 /tmp/serve.py wait {shlex.quote(str(doc))}"]
        for cmd in ok + no:
            with self.subTest(cmd):
                out = self.hook("bash", {"session_id": "s1", "cwd": str(self.project), "tool_name": "Bash",
                                         "tool_input": {"command": cmd}})
                if cmd in ok:
                    self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "allow")
                else:
                    self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
