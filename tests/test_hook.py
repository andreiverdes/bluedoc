"""hook.py, the plan gate, against `serve.py run`. Claude Code: a plan is imported and opened and ExitPlanMode is
denied with instructions; the same plan stays one doc until the reader approves it, then ExitPlanMode is allowed; a
rewritten plan becomes the next rev; a plan that names a bluedoc doc opens that doc; the guards print nothing; the Bash
hook allows only the gate's own commands. Codex (Stop), Copilot CLI (preToolUse) and Gemini CLI (BeforeTool/AfterTool)
from recorded events, and `ext open` / `ext wait` for the omp and pi extension."""
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


class GateCase(unittest.TestCase):
    """A temp BLUEDOC_HOME, a running server and a project folder with a Markdown plan."""

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


class PlanGate(GateCase):
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


class OtherAgents(GateCase):
    """The same gate behind each agent's own hook schema (recorded events, not live agents)."""

    def run_hook(self, agent: str, event: str, payload: dict | str, *extra: str, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPTS / "hook.py"), agent, event, *extra],
                              input=payload if isinstance(payload, str) else json.dumps(payload),
                              env={**self.tmp.env, **env}, capture_output=True, text=True, timeout=60)

    def out(self, agent: str, event: str, payload: dict, **env: str) -> dict | None:
        r = self.run_hook(agent, event, payload, **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        log = self.tmp.home / "hooks" / "hook.log"
        self.assertNotIn("failed", log.read_text(encoding="utf-8") if log.exists() else "")
        return json.loads(r.stdout) if r.stdout.strip() else None

    def codex_event(self, message: str, mode: str = "plan", **over) -> dict:
        rollout = self.tmp.dir / "rollout.jsonl"
        rollout.write_text("\n".join(json.dumps(o) for o in (
            {"type": "turn_context", "payload": {"cwd": str(self.project), "collaboration_mode": {"mode": mode}}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                                  "content": [{"type": "output_text", "text": message}]}})) + "\n")
        # Codex strips the <proposed_plan> block from last_assistant_message in Plan mode; the rollout keeps it
        return {"session_id": "c1", "turn_id": "t1", "transcript_path": str(rollout), "cwd": str(self.project),
                "hook_event_name": "Stop", "model": "gpt-5", "permission_mode": "default", "stop_hook_active": False,
                "last_assistant_message": "Here is the plan.", **over}

    def test_codex_plan_mode_blocks_with_the_page_then_the_approval(self) -> None:
        message = f"Here is the plan.\n\n<proposed_plan>\n{PLAN}</proposed_plan>\n"
        out = self.out("codex", "plan", self.codex_event(message))
        self.assertEqual(out["decision"], "block")
        self.assertRegex(out["reason"], r"http://127\.0\.0\.1:\d+/")
        self.assertIn("write the final plan again", out["reason"])
        doc = self.plans / "add-rate-limiting.bluedoc.json"
        self.assertTrue(doc.is_file())
        # the turn ends again before the reader answered: Codex may stop, the page stays open
        self.assertEqual(self.out("codex", "plan", self.codex_event(message, stop_hook_active=True)), {})
        self.approve(doc)
        reworded = message.replace("Requests have no limit.", "Nothing limits requests today.")
        out = self.out("codex", "plan", self.codex_event(reworded, stop_hook_active=True))
        self.assertEqual(out["decision"], "block")
        self.assertIn("Approved in bluedoc, rev 1", out["reason"])
        # the approval went back: the turn's next stop ends it, with no new doc
        self.assertEqual(self.out("codex", "plan", self.codex_event(reworded, stop_hook_active=True)), {})
        self.assertEqual(list(self.plans.glob("*.bluedoc.json")), [doc])

    def test_codex_outside_plan_mode_is_left_alone(self) -> None:
        message = f"<proposed_plan>\n{PLAN}</proposed_plan>"
        self.assertEqual(self.out("codex", "plan", self.codex_event(message, mode="default")), {})
        self.assertEqual(self.out("codex", "plan", self.codex_event("Done: tests pass.")), {})
        self.assertFalse(self.plans.exists())

    def test_copilot_denies_with_the_instructions_then_allows(self) -> None:
        copilot = self.tmp.dir / "copilot-home"
        (copilot / "session-state" / "p1").mkdir(parents=True)
        (copilot / "session-state" / "p1" / "plan.md").write_text(PLAN, encoding="utf-8")
        event = {"sessionId": "p1", "timestamp": 1760000000000, "cwd": str(self.project), "toolName": "exit_plan_mode",
                 "toolArgs": {"summary": "- token bucket\n- 429s"}}
        out = self.out("copilot", "plan", event, COPILOT_HOME=str(copilot))
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("call exit_plan_mode again", out["permissionDecisionReason"])
        self.assertRegex(out["permissionDecisionReason"], r"http://127\.0\.0\.1:\d+/")
        doc = self.plans / "plan.bluedoc.json"
        self.assertTrue(doc.is_file())
        self.approve(doc)
        out = self.out("copilot", "plan", event, COPILOT_HOME=str(copilot))
        self.assertEqual(out["permissionDecision"], "allow")
        self.assertTrue(out["modifiedArgs"]["summary"].startswith("- token bucket"))
        self.assertIn("Approved in bluedoc, rev 1", out["modifiedArgs"]["summary"])

    def test_gemini_denies_then_notes_the_approval_after_the_tool(self) -> None:
        temp = self.tmp.dir / "gemini-tmp" / "acme-shop"
        (temp / "g1" / "plans").mkdir(parents=True)
        (temp / "g1" / "plans" / "rate-limits.md").write_text(PLAN, encoding="utf-8")
        (temp / "chats").mkdir()
        base = {"session_id": "g1", "transcript_path": str(temp / "chats" / "session-g1.json"), "cwd": str(self.project),
                "timestamp": "2026-01-01T00:00:00Z", "tool_name": "exit_plan_mode", "tool_input": {"plan_filename": "rate-limits.md"}}
        out = self.out("gemini", "plan", {**base, "hook_event_name": "BeforeTool"})
        self.assertEqual(out["decision"], "deny")
        self.assertIn("call exit_plan_mode again", out["reason"])
        doc = self.plans / "rate-limits.bluedoc.json"
        self.assertTrue(doc.is_file())
        self.assertIsNone(self.out("gemini", "note", {**base, "hook_event_name": "AfterTool"}))
        self.approve(doc)
        out = self.out("gemini", "plan", {**base, "hook_event_name": "BeforeTool"})
        self.assertNotIn("decision", out)
        out = self.out("gemini", "note", {**base, "hook_event_name": "AfterTool"})
        self.assertIn("Approved in bluedoc, rev 1", out["hookSpecificOutput"]["additionalContext"])
        self.assertIsNone(self.out("gemini", "note", {**base, "hook_event_name": "AfterTool"}))

    def test_ext_open_then_wait_for_the_approval(self) -> None:
        req = {"text": PLAN, "planPath": None, "cwd": str(self.project), "sessionId": "o1", "agent": "omp"}
        r = self.run_hook("ext", "open", req)
        self.assertEqual(r.returncode, 0, r.stderr)
        g = json.loads(r.stdout)
        self.assertEqual(g["state"], "opened")
        self.assertRegex(g["url"], r"http://127\.0\.0\.1:\d+/")
        self.assertIn("submit the plan again", g["message"])
        doc = Path(g["doc"])
        waiter = subprocess.Popen([sys.executable, str(SCRIPTS / "hook.py"), "ext", "wait", str(doc)], env=self.tmp.env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: waiter.poll() is None and waiter.kill())
        self.approve(doc)
        stdout, stderr = waiter.communicate(timeout=30)
        self.assertEqual(waiter.returncode, 0, stderr)
        self.assertEqual(json.loads(stdout), {"kind": "approval", "md": "# Plan approved\n", "rev": "1"})
        r = self.run_hook("ext", "open", req)
        self.assertEqual(json.loads(r.stdout)["state"], "approved")
        self.assertEqual(self.run_hook("ext", "open", req, BLUEDOC_PLAN_GATE="0").stdout.strip(),
                         json.dumps({"state": "skip", "why": "BLUEDOC_PLAN_GATE=0"}))

    def test_ext_open_reports_an_error_in_one_line(self) -> None:
        r = self.run_hook("ext", "open", "{not json")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1)
        self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    unittest.main()
