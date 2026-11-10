"""hook.py, the plan-mode hook, against `serve.py run`. Claude Code: a plan is imported and opened and ExitPlanMode is
denied with instructions; the same plan stays one doc until the reader approves it, then ExitPlanMode is allowed; a
rewritten plan becomes the next rev; a plan that names a bluedoc doc opens that doc; the guards print nothing; the Bash
hook allows only the plan-mode hook's own commands. Codex (Stop), Copilot CLI (preToolUse, agentStop) and Antigravity CLI
(PreToolUse on write_to_file, PreInvocation) from recorded events, and `ext open` / `ext wait` for the omp and pi
extension.

PatchOnly: the patch-only check behind each agent's edit hook (`claude edit`, `codex edit`, `copilot edit`, `agy edit`,
`ext edit`), with each agent's event shape: an edit of a built doc that validates is denied with the get/patch
commands; a new doc, a scaffold not built yet, a doc that doesn't validate, another file and Copilot's `view` go
through, and so does everything with BLUEDOC_PATCH_ONLY=0 or patchOnly off in settings.json. A patch that names
several files is denied when any of them is a built doc."""
from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from _support import EXAMPLES, SCRIPTS, Server, TempHome

PLAN = """# Add rate limiting

Requests have no limit.

## Steps
1. Add a token bucket in `src/bucket.ts`
2. Return 429 from `src/server.ts`
"""
JSON_HDR = {"Content-Type": "application/json", "X-Bluedoc": "1"}


class PlanHookCase(unittest.TestCase):
    """A temp BLUEDOC_HOME, a running server and a project folder with a Markdown plan."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        for k in ("CI", "BLUEDOC_PLAN_HOOK", "SSH_CONNECTION", "SSH_TTY"):
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


class ClaudePlanHook(PlanHookCase):
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
        for name, env, over in (("off switch", {"BLUEDOC_PLAN_HOOK": "0"}, {}), ("CI", {"CI": "true"}, {}),
                                ("bypass mode", {}, {"permission_mode": "bypassPermissions"})):
            with self.subTest(name):
                self.assertIsNone(self.hook("plan", self.plan_event(**over), **env))
        self.assertFalse(self.plans.exists())

    def test_bash_hook_allows_only_the_plan_mode_commands(self) -> None:
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


class OtherAgents(PlanHookCase):
    """The same plan-mode hook behind each agent's own hook schema (recorded events, not live agents)."""

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

    def test_copilot_approval_holds_when_plan_md_was_updated_in_the_change_round(self) -> None:
        # live run (beta19): Copilot's plan mode updates plan.md while it patches the doc for a change request; the
        # reader then approved, and the next exit_plan_mode re-imported plan.md as a new rev and opened it again
        copilot = self.tmp.dir / "copilot-home"
        plan_md = copilot / "session-state" / "p2" / "plan.md"
        plan_md.parent.mkdir(parents=True)
        plan_md.write_text(PLAN, encoding="utf-8")
        event = {"sessionId": "p2", "timestamp": 1760000000000, "cwd": str(self.project), "toolName": "exit_plan_mode",
                 "toolArgs": {"summary": "- token bucket"}}
        self.assertEqual(self.out("copilot", "plan", event, COPILOT_HOME=str(copilot))["permissionDecision"], "deny")
        doc = self.plans / "plan.bluedoc.json"
        plan_md.write_text(PLAN.replace("Requests have no limit.", "Nothing limits requests today."), encoding="utf-8")
        self.approve(doc)
        out = self.out("copilot", "plan", event, COPILOT_HOME=str(copilot))
        self.assertEqual(out["permissionDecision"], "allow")
        self.assertIn("Approved in bluedoc, rev 1", out["modifiedArgs"]["summary"])
        self.assertEqual(json.loads(doc.read_text(encoding="utf-8"))["meta"]["rev"], "1")
        self.assertEqual(list(self.plans.glob("*.bluedoc.json")), [doc])

    def test_copilot_stop_after_the_approval_prompts_exit_plan_mode(self) -> None:
        # live runs (beta19, beta20): the agent read the approval from `serve.py wait` and ended its turn without
        # calling exit_plan_mode again, so the approved plan never ran until the user asked
        copilot = self.tmp.dir / "copilot-home"
        plan_md = copilot / "session-state" / "p3" / "plan.md"
        plan_md.parent.mkdir(parents=True)
        plan_md.write_text(PLAN, encoding="utf-8")
        plan = {"sessionId": "p3", "timestamp": 1760000000000, "cwd": str(self.project), "toolName": "exit_plan_mode",
                "toolArgs": {"summary": "- token bucket"}}
        stop = {"sessionId": "p3", "timestamp": 1760000000000, "cwd": str(self.project), "transcriptPath": "",
                "stopReason": "end_turn", "stop_hook_active": False}
        self.assertIsNone(self.out("copilot", "stop", stop), "no plan doc in this session")
        self.assertEqual(self.out("copilot", "plan", plan, COPILOT_HOME=str(copilot))["permissionDecision"], "deny")
        self.assertIsNone(self.out("copilot", "stop", stop), "the reader hasn't answered")
        doc = self.plans / "plan.bluedoc.json"
        self.approve(doc)
        out = self.out("copilot", "stop", stop)
        self.assertEqual(out["decision"], "block")
        self.assertIn("approved rev 1", out["reason"])
        self.assertIn("exit_plan_mode", out["reason"])
        self.assertIsNone(self.out("copilot", "stop", {**stop, "stop_hook_active": True}), "once per turn")
        self.assertEqual(self.out("copilot", "plan", plan, COPILOT_HOME=str(copilot))["permissionDecision"], "allow")
        self.assertIsNone(self.out("copilot", "stop", stop), "the approval went through: the record is gone")

    def agy_event(self, args: dict, name: str = "write_to_file") -> dict:
        """A PreToolUse event as `agy --mode plan` sent it (agy 1.4.0), trimmed to the fields the hook reads."""
        brain = self.tmp.dir / "agy-brain" / "a1"
        return {"conversationId": "a1", "workspacePaths": [str(self.project)], "modelName": "gemini-3.8-flash-high",
                "artifactDirectoryPath": str(brain), "transcriptPath": str(brain / ".system_generated" / "logs" /
                                                                         "transcript_full.jsonl"),
                "stepIdx": 4, "toolCall": {"name": name, "args": args}}

    def agy_plan_args(self, text: str = PLAN) -> dict:
        return {"ArtifactMetadata": {"RequestFeedback": True, "Summary": "Rate limiting plan", "UserFacing": True},
                "CodeContent": text, "Description": "Implementation plan", "Overwrite": True,
                "TargetFile": str(self.tmp.dir / "agy-brain" / "a1" / "implementation_plan.md"),
                "toolAction": "Writing plan artifact", "toolSummary": "Write plan artifact"}

    def agy_note_event(self) -> dict:
        return {"conversationId": "a1", "workspacePaths": [str(self.project)], "invocationNum": 3, "initialNumSteps": 4}

    def test_agy_denies_the_plan_artifact_then_allows_it_and_injects_the_note(self) -> None:
        out = self.out("agy", "plan", self.agy_event(self.agy_plan_args()))
        self.assertEqual(out["decision"], "deny")
        self.assertRegex(out["reason"], r"http://127\.0\.0\.1:\d+/")
        self.assertIn("write the implementation plan artifact again", out["reason"])
        doc = self.plans / "add-rate-limiting.bluedoc.json"
        self.assertTrue(doc.is_file())
        self.assertTrue((self.tmp.home / "hooks" / "agy" / "a1.json").is_file())
        self.assertIsNone(self.out("agy", "note", self.agy_note_event()))
        self.approve(doc)
        reworded = self.agy_plan_args(PLAN.replace("Requests have no limit.", "Nothing limits requests today."))
        out = self.out("agy", "plan", self.agy_event(reworded))
        self.assertEqual(out, {"decision": "allow", "overwrite": {"ArtifactMetadata": {
            "RequestFeedback": False, "Summary": "Rate limiting plan", "UserFacing": True}}})
        out = self.out("agy", "note", self.agy_note_event())
        note = out["injectSteps"][0]["systemMessage"]["systemMessage"]
        self.assertIn("Approved in bluedoc, rev 1", note)
        self.assertIn(str(doc), note)
        self.assertIsNone(self.out("agy", "note", self.agy_note_event()))   # once
        self.assertEqual(list(self.plans.glob("*.bluedoc.json")), [doc])

    def test_agy_leaves_other_calls_and_unreviewed_writes_alone(self) -> None:
        self.assertIsNone(self.out("agy", "plan", self.agy_event({"CommandLine": "ls"}, name="run_command")))
        walkthrough = {**self.agy_plan_args(), "ArtifactMetadata": {"RequestFeedback": False, "UserFacing": True}}
        self.assertIsNone(self.out("agy", "plan", self.agy_event(walkthrough)))
        self.assertIsNone(self.out("agy", "plan", self.agy_event({"CodeContent": "hi\n", "TargetFile": "/tmp/x.txt"})))
        self.assertIsNone(self.out("agy", "plan", self.agy_event(self.agy_plan_args()), BLUEDOC_PLAN_HOOK="0"))
        self.assertFalse(self.plans.exists())

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
        self.assertEqual(self.run_hook("ext", "open", req, BLUEDOC_PLAN_HOOK="0").stdout.strip(),
                         json.dumps({"state": "skip", "why": "BLUEDOC_PLAN_HOOK=0"}))

    def test_ext_open_imports_the_text_when_the_plan_path_is_an_omp_url(self) -> None:
        # omp's plan_review_requested reports `local://x-plan.md`; from-md can't read it, so the text is imported.
        req = {"text": PLAN, "planPath": "local://x-plan.md", "cwd": str(self.project), "sessionId": "o2", "agent": "omp"}
        r = self.run_hook("ext", "open", req)
        self.assertEqual(r.returncode, 0, r.stderr)
        g = json.loads(r.stdout)
        self.assertEqual(g["state"], "opened")
        self.assertEqual(Path(g["doc"]).name, "x-plan.bluedoc.json")
        self.assertIn("Add rate limiting", Path(g["doc"]).read_text(encoding="utf-8"))
        # The refined plan under the same URL: the text again, as the next rev of the same doc.
        r = self.run_hook("ext", "open", {**req, "text": PLAN.replace("429", "503")})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["doc"], g["doc"])
        doc = json.loads(Path(g["doc"]).read_text(encoding="utf-8"))
        self.assertEqual(str(doc["meta"]["rev"]), "2")
        self.assertIn("503", json.dumps(doc))

    def test_ext_open_reports_an_error_in_one_line(self) -> None:
        r = self.run_hook("ext", "open", "{not json")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1)
        self.assertEqual(r.stdout, "")


class PatchOnly(unittest.TestCase):
    """A temp BLUEDOC_HOME (no server) and a project with a built example doc (acme-orders and its history)."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        for k in ("CI", "BLUEDOC_PATCH_ONLY"):
            self.tmp.env.pop(k, None)
        self.project = self.tmp.dir / "acme-shop"
        self.docs = self.project / "docs"
        self.docs.mkdir(parents=True)
        for name in ("acme-orders.bluedoc.json", "acme-orders.bluedoc.history.json"):
            shutil.copy(EXAMPLES / name, self.docs / name)
        self.built = self.docs / "acme-orders.bluedoc.json"

    def run_hook(self, agent: str, payload: dict, **env: str) -> str | None:
        """The denial's reason in the agent's own output shape, or None when the hook let the call through."""
        r = subprocess.run([sys.executable, str(SCRIPTS / "hook.py"), agent, "edit"], input=json.dumps(payload),
                           env={**self.tmp.env, **env}, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        log = self.tmp.home / "hooks" / "hook.log"
        self.assertNotIn("failed", log.read_text(encoding="utf-8") if log.exists() else "")
        out = json.loads(r.stdout) if r.stdout.strip() else None
        if agent == "ext":
            return out.get("reason")
        if out is None:
            return None
        if agent in ("claude", "codex"):
            self.assertEqual((out["hookSpecificOutput"]["hookEventName"], out["hookSpecificOutput"]["permissionDecision"]),
                             ("PreToolUse", "deny"))
            return out["hookSpecificOutput"]["permissionDecisionReason"]
        if agent == "copilot":
            self.assertEqual(out["permissionDecision"], "deny")
            return out["permissionDecisionReason"]
        self.assertEqual(out["decision"], "deny")   # agy
        return out["reason"]

    @staticmethod
    def patch(*files: str) -> str:
        """An apply_patch envelope that updates each file."""
        return "*** Begin Patch\n" + "".join(f"*** Update File: {f}\n@@\n-old\n+new\n" for f in files) + "*** End Patch\n"

    def events(self, path: Path) -> dict:
        """Each agent's edit event for one file, as the agent sends it."""
        rel = str(path.relative_to(self.project)) if path.is_relative_to(self.project) else str(path)
        return {
            "claude": {"session_id": "s1", "transcript_path": "", "cwd": str(self.project), "permission_mode": "default",
                       "hook_event_name": "PreToolUse", "tool_name": "Edit",
                       "tool_input": {"file_path": str(path), "old_string": "Orders", "new_string": "Acme orders"}},
            "codex": {"session_id": "c1", "turn_id": "t1", "transcript_path": "", "cwd": str(self.project),
                      "hook_event_name": "PreToolUse", "model": "gpt-5", "permission_mode": "default",
                      "tool_name": "apply_patch", "tool_use_id": "call_1", "tool_input": {"command": self.patch(rel)}},
            "copilot": {"sessionId": "p1", "timestamp": 1760000000000, "cwd": str(self.project), "toolName": "edit",
                        "toolArgs": {"path": str(path), "old_str": "Orders", "new_str": "Acme orders"}},
            "agy": {"conversationId": "a1", "workspacePaths": [str(self.project)], "modelName": "gemini-3.8-flash-high",
                    "stepIdx": 7, "toolCall": {"name": "replace_file_content", "args": {
                        "TargetFile": str(path), "TargetContent": "Orders", "ReplacementContent": "Acme orders"}}},
            "ext": {"paths": [rel], "cwd": str(self.project)},
        }

    def test_a_built_doc_is_denied_with_the_patch_commands(self) -> None:
        build = str(SCRIPTS / "build.py")
        for agent, payload in self.events(self.built).items():
            with self.subTest(agent):
                why = self.run_hook(agent, payload)
                self.assertIsNotNone(why)
                self.assertTrue(why.startswith("acme-orders.bluedoc.json is a built bluedoc doc"), why)
                for line in (f"python3 {build} get {self.built.resolve()}", f"python3 {build} get {self.built.resolve()} <key>",
                             f"python3 {build} patch {self.built.resolve()} <key> --set a/b=v --change \"why\"",
                             f"python3 {build} schema <block>"):
                    self.assertIn(line, why)
        self.assertEqual(self.run_hook("claude", {**self.events(self.built)["claude"], "tool_name": "Write",
                                                  "tool_input": {"file_path": str(self.built), "content": "{}"}})[:24],
                         "acme-orders.bluedoc.json")

    def test_new_docs_scaffolds_and_invalid_docs_go_through(self) -> None:
        scaffold = self.docs / "acme-returns.bluedoc.json"
        r = self.tmp.run("build.py", "new", "plan", scaffold, "--title", "Acme returns")
        self.assertEqual(r.returncode, 0, r.stderr)
        broken = self.docs / "acme-broken.bluedoc.json"
        doc = json.loads(self.built.read_text(encoding="utf-8"))
        doc["meta"]["type"] = "acme"   # ERROR doc.meta.type
        broken.write_text(json.dumps(doc), encoding="utf-8")
        shutil.copy(self.docs / "acme-orders.bluedoc.history.json", self.docs / "acme-broken.bluedoc.history.json")
        cases = {"a new doc": self.docs / "acme-new.bluedoc.json", "a scaffold not built yet": scaffold,
                 "a doc that doesn't validate": broken, "another file": self.project / "src" / "orders.ts"}
        for name, path in cases.items():
            for agent, payload in self.events(path).items():
                with self.subTest(name, agent=agent):
                    self.assertIsNone(self.run_hook(agent, payload))

    def test_the_off_switch_and_the_setting_let_every_edit_through(self) -> None:
        for agent, payload in self.events(self.built).items():
            with self.subTest("BLUEDOC_PATCH_ONLY=0", agent=agent):
                self.assertIsNone(self.run_hook(agent, payload, BLUEDOC_PATCH_ONLY="0"))
        (self.tmp.home / "settings.json").write_text(json.dumps({"patchOnly": False}), encoding="utf-8")
        for agent, payload in self.events(self.built).items():
            with self.subTest("settings.json", agent=agent):
                self.assertIsNone(self.run_hook(agent, payload))
        with self.subTest("the variable wins over the file"):
            self.assertIsNotNone(self.run_hook("claude", self.events(self.built)["claude"], BLUEDOC_PATCH_ONLY="1"))

    def test_a_patch_is_denied_when_any_file_is_a_built_doc(self) -> None:
        patch = self.patch("src/orders.ts", "docs/acme-orders.bluedoc.json")
        codex = {**self.events(self.built)["codex"], "tool_input": {"command": patch}}
        self.assertIn("acme-orders.bluedoc.json", self.run_hook("codex", codex))
        self.assertIsNone(self.run_hook("codex", {**codex, "tool_input": {"command": self.patch("src/orders.ts")}}))
        moved = "*** Begin Patch\n*** Update File: src/orders.ts\n*** Move to: docs/acme-orders.bluedoc.json\n*** End Patch\n"
        self.assertIsNotNone(self.run_hook("codex", {**codex, "tool_input": {"command": moved}}), "a move onto the doc")
        # Copilot's apply_patch: the patch as the arguments themselves, or as {input}
        copilot = {"sessionId": "p1", "timestamp": 1760000000000, "cwd": str(self.project), "toolName": "apply_patch"}
        self.assertIsNotNone(self.run_hook("copilot", {**copilot, "toolArgs": patch}))
        self.assertIsNotNone(self.run_hook("copilot", {**copilot, "toolArgs": {"input": patch}}))
        self.assertIsNone(self.run_hook("copilot", {**copilot, "toolArgs": self.patch("src/orders.ts")}))
        ext = {"paths": ["src/orders.ts", "docs/acme-orders.bluedoc.json"], "cwd": str(self.project)}
        self.assertIsNotNone(self.run_hook("ext", ext))

    def test_copilot_reads_through_str_replace_editor_view(self) -> None:
        event = {"sessionId": "p1", "timestamp": 1760000000000, "cwd": str(self.project), "toolName": "str_replace_editor"}
        self.assertIsNone(self.run_hook("copilot", {**event, "toolArgs": {"command": "view", "path": str(self.built)}}))
        self.assertIsNotNone(self.run_hook("copilot", {**event, "toolArgs": json.dumps(
            {"command": "str_replace", "path": str(self.built), "old_str": "Orders", "new_str": "Acme orders"})}))
        self.assertIsNotNone(self.run_hook("copilot", {**event, "toolName": "create",
                                                       "toolArgs": {"path": str(self.built), "file_text": "{}"}}))



if __name__ == "__main__":
    unittest.main()
