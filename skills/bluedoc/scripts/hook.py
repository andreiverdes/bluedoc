#!/usr/bin/env python3
"""Agent hooks for bluedoc. Each agent's hook file runs `hook.py <agent> <event>` with the hook JSON on stdin.

  hook.py claude plan    Claude Code PermissionRequest on ExitPlanMode: the plan gate
  hook.py claude bash    Claude Code PreToolUse on Bash: lets the gate's own serve.py / build.py commands run unprompted
  hook.py codex plan     Codex Stop: the plan gate for a turn that ends with a <proposed_plan> (codex/hooks.json)
  hook.py copilot plan   Copilot CLI preToolUse on exit_plan_mode: the plan gate (com.github.copilot/hooks/hooks.json)
  hook.py agy plan       Antigravity CLI PreToolUse on write_to_file: the plan gate (antigravity/hooks.json)
  hook.py agy note       Antigravity CLI PreInvocation: hands the approval note to the model (antigravity/hooks.json)
  hook.py ext open       for agent extensions (omp, pi): stdin {text, planPath, cwd, sessionId, agent}; prints open_gate's
                         result as JSON; exits non-zero with a one-line error on stderr when it fails
  hook.py ext wait DOC   blocks on `serve.py wait DOC --kind any`, then prints {kind: approval|changes, md, rev?}

The plan gate (open_gate, shared by every agent). When the agent finishes a plan, the gate shows it as a bluedoc plan
page and hands control back to the agent, which waits for the reader with `serve.py wait` as it does for any bluedoc doc:
  1. The plan Markdown names an existing *.bluedoc.json: that doc opens. Otherwise the plan is imported (mdplan.py)
     into $BLUEDOC_HOME/plans/<project>/<name>.bluedoc.json, or re-imported as the next rev when the agent rewrote it.
  2. The page opens in the browser (once per plan text), and the gate turns the agent back with instructions: wait in
     the background, patch the doc on a change request, finish the plan again (the agent's own exit hint) after the
     approval.
  3. When the agent finishes the same plan again and the doc's current rev is approved, the gate lets it through at once.
Both the instructions and the approval note end with `## Stale evidence` when checks' pinned evidence is stale
(codepin.py): a warning that names the checks to re-run, never a block.
The gate prints nothing, so the agent shows its own dialog, when BLUEDOC_PLAN_GATE=0, in CI, over SSH without a
display, in bypassPermissions mode, and on any error (logged to $BLUEDOC_HOME/hooks/hook.log).

Per agent and session, $BLUEDOC_HOME/hooks/<agent>/<session_id>.json records {doc, sha, url}: the doc, the sha256 of the
plan text it was imported or opened for, and its URL. An approval removes it, so the session's next plan starts a new doc.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import traceback
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True
STATE = Path(os.environ.get("BLUEDOC_HOME") or "~/.bluedoc").expanduser().resolve()
PLANS = STATE / "plans"
HOOKS = STATE / "hooks"
LOG = HOOKS / "hook.log"
# agent -> (the name the page shows replies go to, what the agent does to finish its plan again)
AGENTS = {
    "claude": ("Claude", "call ExitPlanMode again"),
    "codex": ("Codex", "write the final plan again"),
    "copilot": ("Copilot", "call exit_plan_mode again"),
    "agy": ("Antigravity", "write the implementation plan artifact again with write_to_file (RequestFeedback true)"),
    "omp": ("omp", "submit the plan again"),
    "pi": ("pi", "call bluedoc_submit_plan again"),
}
OFF = {"", "0", "false", "no", "off"}
SHELL_META = re.compile(r"[;&|<>`$(){}\n\\]")
DOC_PATH = re.compile(r"(?:^|[\s`'\"(])((?:~|\.{0,2})?/?[^\s`'\"()]*\.bluedoc\.json)")


def log(msg: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except OSError:
        pass


def emit(out: dict) -> int:
    print(json.dumps(out))
    return 0


def no_reader(event: dict) -> str | None:
    """Why nobody can answer a page in this run, or None."""
    if os.environ.get("BLUEDOC_PLAN_GATE", "1").strip().lower() in OFF - {""}:
        return "BLUEDOC_PLAN_GATE=0"
    if os.environ.get("CI", "").strip().lower() not in OFF:
        return "CI"
    if (os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY")) and sys.platform != "darwin" \
            and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return "SSH without a display"
    if event.get("permission_mode") == "bypassPermissions":
        return "bypassPermissions mode"
    return None


def session_file(agent: str, session_id: str) -> Path:
    return HOOKS / agent / (re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "none") + ".json")


def load_session(agent: str, session_id: str) -> dict:
    try:
        rec = json.loads(session_file(agent, session_id).read_text(encoding="utf-8"))
        return rec if isinstance(rec, dict) and Path(rec.get("doc", "")).is_file() else {}
    except (OSError, ValueError):
        return {}


def save_session(agent: str, session_id: str, rec: dict) -> None:
    p = session_file(agent, session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(rec), encoding="utf-8")
    tmp.replace(p)


def plan_text(tool_input: dict) -> str:
    """The plan file on disk (current) over the inline copy (stale in Claude Code before 2.1.285)."""
    path = tool_input.get("planFilePath")
    if isinstance(path, str) and path:
        try:
            return Path(path).expanduser().read_text(encoding="utf-8")
        except OSError:
            pass
    plan = tool_input.get("plan")
    return plan if isinstance(plan, str) else ""


def named_doc(text: str, cwd: Path) -> Path | None:
    """The first *.bluedoc.json the plan names that exists (relative paths from the project folder)."""
    for m in DOC_PATH.finditer(text):
        p = Path(m.group(1)).expanduser()
        p = p if p.is_absolute() else cwd / p
        if p.is_file():
            return p.resolve()
    return None


def new_doc_path(project: Path, plan_path: str | None, text: str) -> Path:
    """$BLUEDOC_HOME/plans/<project>/<name>.bluedoc.json, name from the agent's plan file, else the plan's title."""
    stem = Path(plan_path or "").stem
    if not stem:
        title = next((l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("# ")), "plan")
        stem = title
    stem = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:48].strip("-") or "plan"
    folder = PLANS / (re.sub(r"[^A-Za-z0-9._-]+", "-", project.name).strip("-") or "project")
    out, n = folder / f"{stem}.bluedoc.json", 2
    while out.exists():
        out, n = folder / f"{stem}-{n}.bluedoc.json", n + 1
    return out


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    r = subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True, text=True, timeout=50)
    if r.returncode != 0:
        raise RuntimeError(f"{script} {' '.join(args[:2])} exited {r.returncode}: {r.stderr.strip()[-500:]}")
    return r


def approved(doc: Path) -> str | None:
    """The approved rev that covers the doc's current rev, or None (asks the running server)."""
    import serve
    rev = str((json.loads(doc.read_text(encoding="utf-8")).get("meta") or {}).get("rev") or "")
    if not serve.alive():
        return None
    url = serve.call(f"/__bluedoc/url?doc={quote(str(doc))}")[1]["url"]
    a = serve.call(f"/__bluedoc/ping?path={quote(url)}")[1].get("approval")
    if a and (a.get("carried") or str(a.get("rev")) == rev):
        return str(a.get("rev"))
    return None


def instructions(doc: Path, url: str, exit_hint: str, wait_hint: str = "Run in the background (run_in_background: true)") -> str:
    """What the agent does after the gate opened its plan; exit_hint is how it finishes the plan again."""
    q = lambda p: shlex.quote(str(p))  # noqa: E731
    serve, build = q(HERE / "serve.py"), q(HERE / "build.py")
    return (
        f"bluedoc opened this plan for the reader at {url} (doc: {doc}). The reader answers on that page, not here. "
        f"Do not {exit_hint} until the reader approves.\n"
        f"1. {wait_hint}: python3 {serve} wait {q(doc)} --kind any\n"
        f"2. On a change request: revise the doc with python3 {build} patch {q(doc)} <key> --set field=value "
        "--change \"what changed and why\" (--resolves <comment id> for each comment you addressed; --no-bump on the "
        "second and later patches for one reply). Tell the reader in one line what changed, then wait again. Keys and "
        f"fields: the Replies section of {q(HERE.parent / 'SKILL.md')}. Don't edit the Markdown plan file.\n"
        f"3. On an approval: {exit_hint}. The reader's decisions and notes in the approval are binding."
    )


def approval(agent: str, session_id: str, rec: dict) -> dict | None:
    """{state: approved, doc, rev, note} when the session's gated doc is approved at its current rev (the record goes, so
    the session's next plan starts a new doc), else None."""
    rev = approved(Path(rec["doc"])) if rec else None
    if not rev:
        return None
    session_file(agent, session_id).unlink(missing_ok=True)
    note = (f"Approved in bluedoc, rev {rev}: {rec['doc']}. Implement that rev of the doc, with the "
            "reader's decisions and notes from the approval.")
    stale = stale_evidence(Path(rec["doc"]))
    if stale:   # a warning, not a block: the approval stands, and the checks run again
        note += "\n\n" + stale
    log(f"plan approved ({agent}): {rec['doc']} rev {rev}")
    return {"state": "approved", "doc": rec["doc"], "rev": rev, "note": note}


def open_gate(text: str, plan_path: str | None, cwd: Path, session_id: str, agent: str, mode: str = "") -> dict:
    """The plan gate for any agent. Returns {state: skip, why}, {state: approved, doc, rev, note} when this plan text's
    doc is approved (approval()), or {state: opened, doc, url, message} after importing or re-importing the plan and
    opening its page; `message` is what the agent does next. `mode` is the agent's permission mode, for the
    bypassPermissions guard."""
    why = no_reader({"permission_mode": mode})
    if why or not text.strip():
        why = why or "empty plan"
        log(f"plan gate skipped ({agent}): {why}")
        return {"state": "skip", "why": why}
    label, exit_hint = AGENTS.get(agent, (agent, "submit the plan again"))
    sha = hashlib.sha256(text.encode()).hexdigest()
    rec = load_session(agent, session_id)

    if rec and rec.get("sha") == sha:
        done = approval(agent, session_id, rec)
        if done:
            return done

    # The agent's plan file only when it is one on disk: omp reports `local://…` URLs, which from-md can't read.
    source = plan_path if plan_path and Path(plan_path).expanduser().is_file() else None
    doc = named_doc(text, cwd)
    fresh = False
    if doc is None:
        if rec and rec.get("sha") == sha:
            doc = Path(rec["doc"])   # the same plan, not yet approved: keep the doc
        elif rec and Path(rec["doc"]).is_relative_to(PLANS):
            doc = Path(rec["doc"])   # the agent rewrote the Markdown: the next rev of the same doc
            run("build.py", "from-md", source or _plan_file(agent, text), str(doc), "--project", str(cwd),
                "--change", f"{label} rewrote the Markdown plan; imported again.")
            fresh = True
        else:
            doc = new_doc_path(cwd, plan_path, text)
            run("build.py", "from-md", source or _plan_file(agent, text), str(doc), "--project", str(cwd))
            fresh = True
    opened = rec.get("doc") == str(doc) and rec.get("sha") == sha and not fresh
    root = doc.parent if doc.is_relative_to(PLANS) else None
    args = ["open", str(doc), "--to", label, *(["--root", str(root)] if root else []), *([] if opened else ["--browser"])]
    url = run("serve.py", *args).stdout.strip().splitlines()[-1]
    save_session(agent, session_id, {"doc": str(doc), "sha": sha, "url": url})
    log(f"plan gate ({agent}): {'reminded' if opened else 'opened'} {doc}")
    stale = stale_evidence(doc)
    wait_hint = "Run in the background (run_in_background: true)" if agent == "claude" else \
        "Run, in the background if you can (it blocks until the reader answers)"
    message = instructions(doc, url, exit_hint, wait_hint) + ("\n\n" + stale if stale else "")
    return {"state": "opened", "doc": str(doc), "url": url, "message": message}


def claude_plan(event: dict) -> int:
    tool_input = event.get("tool_input") or {}
    text = plan_text(tool_input)
    g = open_gate(text, tool_input.get("planFilePath") or None, Path(event.get("cwd") or os.getcwd()).resolve(),
                  str(event.get("session_id") or ""), "claude", str(event.get("permission_mode") or ""))
    if g["state"] == "approved":
        return emit({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {
            "behavior": "allow", "updatedInput": {**tool_input, "plan": text + "\n\n---\n" + g["note"]}}}})
    if g["state"] == "opened":
        return emit({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {
            "behavior": "deny", "message": g["message"]}}})
    return 0


def stale_evidence(doc: Path) -> str:
    """The doc's `## Stale evidence` (codepin.stale_md): checks whose pinned evidence the code has moved past, with the
    commands that re-record them; '' when there are none or the doc can't be read."""
    import codepin
    try:
        return codepin.stale_md(codepin.evaluate(json.loads(doc.read_text(encoding="utf-8")), doc), shlex.quote(str(doc))).rstrip()
    except (OSError, ValueError, codepin.GitMissing):
        return ""


def _plan_file(agent: str, text: str) -> str:
    """A plan that came only inline: written next to the session records so from-md can read it."""
    p = HOOKS / agent / f"inline-{hashlib.sha256(text.encode()).hexdigest()[:12]}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return str(p)


def claude_bash(event: dict) -> int:
    """Allow, without a prompt, exactly the gate's commands: serve.py wait/reply and build.py patch on a doc under
    $BLUEDOC_HOME/plans or the session's gated doc, with no shell syntax around them. Anything else: no output."""
    cmd = str((event.get("tool_input") or {}).get("command") or "")
    if SHELL_META.search(cmd.replace("\\\n", " ")):
        return 0
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return 0
    if len(argv) < 4 or Path(argv[0]).name not in ("python3", "python"):
        return 0
    script = Path(argv[1]).expanduser()
    allowed = {("serve.py", "wait"), ("serve.py", "reply"), ("build.py", "patch")}
    if script.parent.resolve() != HERE or (script.name, argv[2]) not in allowed:
        return 0
    doc = Path(argv[3]).expanduser()
    doc = (doc if doc.is_absolute() else Path(event.get("cwd") or os.getcwd()) / doc).resolve()
    gated = load_session("claude", str(event.get("session_id") or "")).get("doc")
    if not doc.name.endswith(".bluedoc.json") or not (doc.is_relative_to(PLANS) or str(doc) == gated):
        return 0
    return emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                        "permissionDecisionReason": "bluedoc plan gate command"}})


PROPOSED_PLAN = re.compile(r"<proposed_plan>\s*\n?(.*?)\n?\s*</proposed_plan>", re.S)


def _codex_rollout(path: str) -> tuple[str, str]:
    """From a Codex rollout (JSONL): the collaboration mode of the newest turn and the newest assistant message text.
    The rollout is not a stable interface, so anything unexpected gives ''."""
    mode, last = "", ""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, TypeError):
        return mode, last
    for line in lines:
        try:
            o = json.loads(line)
        except ValueError:
            continue
        p = o.get("payload") if isinstance(o, dict) else None
        if not isinstance(p, dict):
            continue
        if o.get("type") == "turn_context" and isinstance(p.get("collaboration_mode"), dict):
            mode = str(p["collaboration_mode"].get("mode") or "")
        elif o.get("type") == "response_item" and p.get("type") == "message" and p.get("role") == "assistant":
            last = "".join(c.get("text", "") for c in p.get("content") or [] if isinstance(c, dict))
    return mode, last


def codex_plan(event: dict) -> int:
    """Codex Stop hook. In Plan mode Codex ends its turn with the plan inside <proposed_plan>…</proposed_plan>; the gate
    opens it and blocks the stop, so Codex goes on with the instructions as its next prompt (or, once the reader
    approved, with the approval note). Schema: https://learn.chatgpt.com/docs/hooks (Stop: stop_hook_active,
    last_assistant_message; `decision: "block"` + `reason` continues the turn with `reason` as the prompt) and
    https://developers.openai.com/plugins/build/plugins (extensions.com.openai.hooks, PLUGIN_ROOT).
    Codex (codex-rs core/src/hook_runtime.rs, stream_events_utils.rs) reports permission_mode from the approval
    policy only and strips the <proposed_plan> block from last_assistant_message in Plan mode, so Plan mode and the plan
    text come from the rollout at transcript_path (turn_context.collaboration_mode.mode, the raw assistant message).
    Codex writes its plan anew each time, so once the session's doc is approved any final plan counts as that doc's;
    and after the approval note went back, the turn's next stop ends the turn (Codex then offers to implement)."""
    mode, last = _codex_rollout(str(event.get("transcript_path") or ""))
    message = str(event.get("last_assistant_message") or "")
    plans = PROPOSED_PLAN.findall(message) or PROPOSED_PLAN.findall(last)
    if not plans or "plan" not in (event.get("permission_mode"), mode):
        return emit({})
    text = plans[-1].strip() + "\n"
    session_id = str(event.get("session_id") or "")
    done_mark = session_file("codex", session_id).with_suffix(".approved")
    if event.get("stop_hook_active") and done_mark.exists():
        return emit({})   # the approval note already went back this turn
    done_mark.unlink(missing_ok=True)
    rec = load_session("codex", session_id)
    sha = hashlib.sha256(text.encode()).hexdigest()
    g = approval("codex", session_id, rec) if rec and not no_reader(event) else None
    if g is None and event.get("stop_hook_active") and rec.get("sha") == sha:
        return emit({})   # the gate already sent this plan back this turn: let the turn end, the page stays open
    g = g or open_gate(text, None, Path(event.get("cwd") or os.getcwd()).resolve(), session_id, "codex",
                       str(event.get("permission_mode") or ""))
    if g["state"] == "skip":
        return emit({})
    if g["state"] == "approved":
        done_mark.parent.mkdir(parents=True, exist_ok=True)
        done_mark.write_text(g["doc"], encoding="utf-8")
        return emit({"decision": "block", "reason": g["note"]})
    return emit({"decision": "block", "reason": g["message"]})


def copilot_plan(event: dict) -> int:
    """Copilot CLI preToolUse on exit_plan_mode. Copilot's exit_plan_mode takes {summary, showFleet?, recommendedAction?}
    and the plan itself is plan.md in the session folder ($COPILOT_HOME or ~/.copilot, session-state/<sessionId>/), so
    that file is the plan text, the summary the fallback. Schema: https://docs.github.com/en/copilot/reference/hooks-reference
    (preToolUse input sessionId/cwd/toolName/toolArgs, or snake_case for PreToolUse; output permissionDecision,
    permissionDecisionReason, modifiedArgs). Opened: deny with the instructions; approved: allow with the note
    appended to the summary; skip: no output. Copilot's plan mode has it update plan.md along with the doc on a change
    request, so the session doc's approval counts whatever plan.md says now (as for Codex), not only for the same text."""
    args = event.get("toolArgs") if "toolArgs" in event else event.get("tool_input")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    args = args if isinstance(args, dict) else {}
    session_id = str(event.get("sessionId") or event.get("session_id") or "")
    home = Path(os.environ.get("COPILOT_HOME") or "~/.copilot").expanduser()
    plan_md = home / "session-state" / re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "none") / "plan.md"
    text = plan_text({"planFilePath": str(plan_md) if plan_md.is_file() else "", "plan": args.get("summary")})
    rec = load_session("copilot", session_id)
    g = approval("copilot", session_id, rec) if rec and not no_reader({}) else None
    g = g or open_gate(text, str(plan_md) if plan_md.is_file() else None,
                       Path(event.get("cwd") or os.getcwd()).resolve(), session_id, "copilot")
    if g["state"] == "opened":
        return emit({"permissionDecision": "deny", "permissionDecisionReason": g["message"]})
    if g["state"] == "approved":
        summary = str(args.get("summary") or "")
        return emit({"permissionDecision": "allow", "modifiedArgs": {**args, "summary": summary + "\n\n---\n" + g["note"]}})
    return 0


def _agy_plan_call(event: dict) -> dict | None:
    """The tool call's args when it writes a plan for review: write_to_file with ArtifactMetadata.RequestFeedback, which
    Antigravity's planning mode sets on implementation_plan.md, the artifact the user approves before execution."""
    call = event.get("toolCall") or {}
    args = call.get("args") if isinstance(call, dict) else None
    if not isinstance(args, dict) or call.get("name") != "write_to_file":
        return None
    meta = args.get("ArtifactMetadata")
    if not isinstance(meta, dict) or meta.get("RequestFeedback") is not True or not isinstance(args.get("CodeContent"), str):
        return None
    return args


def agy_plan(event: dict) -> int:
    """Antigravity CLI (agy) PreToolUse on write_to_file. In plan mode agy writes implementation_plan.md into the
    conversation's artifact folder with write_to_file and ArtifactMetadata.RequestFeedback true, then waits for the
    user's review; that call is the gate. Sources: agy 1.4.0's bundled agy-customizations skill, docs/hooks.md
    (~/.gemini/antigravity-cli/builtin/skills/agy-customizations/docs/hooks.md: camelCase stdin with conversationId,
    workspacePaths, toolCall {name, args}; stdout decision allow|deny, reason, overwrite as a shallow args merge) and
    recorded `agy --mode plan` events. A denial reaches the model as the tool error ("tool call denied by pre-tool hook:
    <reason>"); an allow's reason does not reach it, so the approval note goes through agy_note.
    Opened: deny with the instructions. Approved: allow with RequestFeedback turned off (the reader's approval in bluedoc
    is the review) and the note left for agy_note. agy writes the plan anew each time, so once the conversation's doc is
    approved any plan written counts as that doc's. Skip or another call: no output."""
    args = _agy_plan_call(event)
    if args is None:
        return 0
    session_id = str(event.get("conversationId") or "")
    paths = event.get("workspacePaths") or []
    cwd = Path(paths[0] if paths and isinstance(paths[0], str) else Path.home()).resolve()
    rec = load_session("agy", session_id)
    g = approval("agy", session_id, rec) if rec and not no_reader({}) else None
    g = g or open_gate(args["CodeContent"], None, cwd, session_id, "agy")
    if g["state"] == "opened":
        return emit({"decision": "deny", "reason": g["message"]})
    if g["state"] == "approved":
        note = session_file("agy", session_id).with_suffix(".note")
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(g["note"], encoding="utf-8")
        return emit({"decision": "allow", "overwrite": {"ArtifactMetadata": {**args["ArtifactMetadata"], "RequestFeedback": False}}})
    return 0


def agy_note(event: dict) -> int:
    """Antigravity CLI PreInvocation: the approval note agy_plan left, injected once as a system message before the
    model's next call (docs/hooks.md: injectSteps [{systemMessage: {systemMessage}}])."""
    note = session_file("agy", str(event.get("conversationId") or "")).with_suffix(".note")
    try:
        text = note.read_text(encoding="utf-8")
    except OSError:
        return 0
    note.unlink(missing_ok=True)
    return emit({"injectSteps": [{"systemMessage": {"systemMessage": text}}]})


def ext_open(args: list[str]) -> int:
    """hook.py ext open: stdin {text, planPath, cwd, sessionId, agent}; prints open_gate's result. An empty text reads
    planPath."""
    req = json.load(sys.stdin)
    agent = re.sub(r"[^a-z0-9_-]", "", str(req.get("agent") or "").lower())
    if not agent:
        raise ValueError("agent is required")
    plan_path = req.get("planPath") or None
    text = req.get("text") if isinstance(req.get("text"), str) and req["text"].strip() else plan_text({"planFilePath": plan_path or ""})
    print(json.dumps(open_gate(text, plan_path, Path(req.get("cwd") or os.getcwd()).resolve(), str(req.get("sessionId") or ""), agent)))
    return 0


def ext_wait(args: list[str]) -> int:
    """hook.py ext wait DOC: blocks on `serve.py wait DOC --kind any`; prints {kind: approval, md, rev} when the doc's
    current rev is approved, else {kind: changes, md}. md is the reply's Markdown, without wait's header and footer."""
    if len(args) != 1:
        raise ValueError("usage: hook.py ext wait DOC")
    doc = Path(args[0]).expanduser().resolve()
    r = subprocess.run([sys.executable, str(HERE / "serve.py"), "wait", str(doc), "--kind", "any"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"serve.py wait exited {r.returncode}: {r.stderr.strip()}")
    lines = r.stdout.splitlines()
    if lines and lines[0].startswith("--- bluedoc "):
        lines = lines[1:]
    if lines and lines[-1] == "--- end ---":
        lines = lines[:-1]
    md = "\n".join(lines).strip() + "\n"
    rev = approved(doc)
    print(json.dumps({"kind": "approval", "md": md, "rev": rev} if rev else {"kind": "changes", "md": md}))
    return 0


HANDLERS = {("claude", "plan"): claude_plan, ("claude", "bash"): claude_bash, ("codex", "plan"): codex_plan,
            ("copilot", "plan"): copilot_plan, ("agy", "plan"): agy_plan, ("agy", "note"): agy_note,
            ("ext", "open"): ext_open, ("ext", "wait"): ext_wait}


def main(argv: list[str]) -> int:
    handler = HANDLERS.get(tuple(argv[:2]))
    if handler is None:
        print(f"usage: hook.py {{{', '.join(' '.join(k) for k in HANDLERS)}}} < hook.json", file=sys.stderr)
        return 2
    if argv[0] == "ext":   # an extension asked: it reports the error itself and leaves the agent's own flow alone
        try:
            return handler(argv[2:])
        except Exception as e:
            log(f"{' '.join(argv[:2])} failed:\n{traceback.format_exc()}")
            print(f"hook.py {' '.join(argv[:2])}: {' '.join(str(e).split()) or type(e).__name__}", file=sys.stderr)
            return 1
    try:
        event = json.load(sys.stdin)
        return handler(event if isinstance(event, dict) else {})
    except Exception:   # never break the agent: no output means its own flow goes on
        log(f"{' '.join(argv[:2])} failed:\n{traceback.format_exc()}")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
