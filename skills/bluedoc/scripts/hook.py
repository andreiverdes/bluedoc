#!/usr/bin/env python3
"""Agent hooks for bluedoc. Each agent's hook file runs `hook.py <agent> <event>` with the hook JSON on stdin.

  hook.py claude plan   Claude Code PermissionRequest on ExitPlanMode: the plan gate
  hook.py claude bash   Claude Code PreToolUse on Bash: lets the gate's own serve.py / build.py commands run unprompted

The plan gate. When Claude finishes a plan, the gate shows it as a bluedoc plan page and hands control back to Claude,
which waits for the reader with `serve.py wait` as it does for any bluedoc doc:
  1. The plan Markdown names an existing *.bluedoc.json: that doc opens. Otherwise the plan is imported (mdplan.py)
     into $BLUEDOC_HOME/plans/<project>/<name>.bluedoc.json, or re-imported as the next rev when Claude rewrote it.
  2. The page opens in the browser (once per plan text), and the gate denies ExitPlanMode with instructions: wait in
     the background, patch the doc on a change request, call ExitPlanMode again after the approval.
  3. When Claude calls ExitPlanMode again and the doc's current rev is approved, the gate allows it at once.
The gate prints nothing, so Claude Code shows its own dialog, when BLUEDOC_PLAN_GATE=0, in CI, over SSH without a
display, in bypassPermissions mode, and on any error (logged to $BLUEDOC_HOME/hooks/hook.log).

Per session, $BLUEDOC_HOME/hooks/claude/<session_id>.json records {doc, sha, url}: the doc, the sha256 of the plan
text it was imported or opened for, and its URL. An allow removes it, so the session's next plan starts a new doc.
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
SESSIONS = STATE / "hooks" / "claude"
LOG = STATE / "hooks" / "hook.log"
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


def session_file(session_id: str) -> Path:
    return SESSIONS / (re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "none") + ".json")


def load_session(session_id: str) -> dict:
    try:
        rec = json.loads(session_file(session_id).read_text(encoding="utf-8"))
        return rec if isinstance(rec, dict) and Path(rec.get("doc", "")).is_file() else {}
    except (OSError, ValueError):
        return {}


def save_session(session_id: str, rec: dict) -> None:
    p = session_file(session_id)
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


def new_doc_path(project: Path, tool_input: dict, text: str) -> Path:
    """$BLUEDOC_HOME/plans/<project>/<name>.bluedoc.json, name from Claude's plan file, else the plan's title."""
    stem = Path(tool_input.get("planFilePath") or "").stem
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


def instructions(doc: Path, url: str) -> str:
    q = lambda p: shlex.quote(str(p))  # noqa: E731
    serve, build = q(HERE / "serve.py"), q(HERE / "build.py")
    return (
        f"bluedoc opened this plan for the reader at {url} (doc: {doc}). The reader answers on that page, not here. "
        "Do not call ExitPlanMode again until the reader approves.\n"
        f"1. Run in the background (run_in_background: true): python3 {serve} wait {q(doc)} --kind any\n"
        f"2. On a change request: revise the doc with python3 {build} patch {q(doc)} <key> --set field=value "
        "--change \"what changed and why\" (--resolves <comment id> for each comment you addressed; --no-bump on the "
        "second and later patches for one reply). Tell the reader in one line what changed, then wait again. Keys and "
        f"fields: the Replies section of {q(HERE.parent / 'SKILL.md')}. Don't edit the Markdown plan file.\n"
        "3. On an approval: call ExitPlanMode again. The reader's decisions and notes in the approval are binding."
    )


def claude_plan(event: dict) -> int:
    why = no_reader(event)
    if why:
        log(f"plan gate skipped: {why}")
        return 0
    tool_input = event.get("tool_input") or {}
    session_id = str(event.get("session_id") or "")
    cwd = Path(event.get("cwd") or os.getcwd()).resolve()
    text = plan_text(tool_input)
    if not text.strip():
        return 0
    sha = hashlib.sha256(text.encode()).hexdigest()
    rec = load_session(session_id)

    if rec and rec.get("sha") == sha:
        rev = approved(Path(rec["doc"]))
        if rev:
            session_file(session_id).unlink(missing_ok=True)
            note = (f"\n\n---\nApproved in bluedoc, rev {rev}: {rec['doc']}. Implement that rev of the doc, with the "
                    "reader's decisions and notes from the approval.")
            log(f"plan approved: {rec['doc']} rev {rev}")
            return emit({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {
                "behavior": "allow", "updatedInput": {**tool_input, "plan": text + note}}}})

    doc = named_doc(text, cwd)
    fresh = False
    if doc is None:
        if rec and rec.get("sha") == sha:
            doc = Path(rec["doc"])   # the same plan, not yet approved: keep the doc
        elif rec and Path(rec["doc"]).is_relative_to(PLANS):
            doc = Path(rec["doc"])   # Claude rewrote the Markdown: the next rev of the same doc
            run("build.py", "from-md", tool_input.get("planFilePath") or _plan_file(text), str(doc), "--project", str(cwd),
                "--change", "Claude rewrote the Markdown plan; imported again.")
            fresh = True
        else:
            doc = new_doc_path(cwd, tool_input, text)
            run("build.py", "from-md", tool_input.get("planFilePath") or _plan_file(text), str(doc), "--project", str(cwd))
            fresh = True
    opened = rec.get("doc") == str(doc) and rec.get("sha") == sha and not fresh
    root = doc.parent if doc.is_relative_to(PLANS) else None
    args = ["open", str(doc), "--to", "Claude", *(["--root", str(root)] if root else []), *([] if opened else ["--browser"])]
    url = run("serve.py", *args).stdout.strip().splitlines()[-1]
    save_session(session_id, {"doc": str(doc), "sha": sha, "url": url})
    log(f"plan gate: {'reminded' if opened else 'opened'} {doc}")
    return emit({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {
        "behavior": "deny", "message": instructions(doc, url)}}})


def _plan_file(text: str) -> str:
    """A plan that came only inline: written next to the session records so from-md can read it."""
    p = SESSIONS / f"inline-{hashlib.sha256(text.encode()).hexdigest()[:12]}.md"
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
    gated = load_session(str(event.get("session_id") or "")).get("doc")
    if not doc.name.endswith(".bluedoc.json") or not (doc.is_relative_to(PLANS) or str(doc) == gated):
        return 0
    return emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                        "permissionDecisionReason": "bluedoc plan gate command"}})


HANDLERS = {("claude", "plan"): claude_plan, ("claude", "bash"): claude_bash}


def main(argv: list[str]) -> int:
    handler = HANDLERS.get(tuple(argv[:2]))
    if handler is None:
        print(f"usage: hook.py {{{', '.join(' '.join(k) for k in HANDLERS)}}} < hook.json", file=sys.stderr)
        return 2
    try:
        event = json.load(sys.stdin)
        return handler(event if isinstance(event, dict) else {})
    except Exception:   # never break the agent: no output means its own flow goes on
        log(f"{' '.join(argv[:2])} failed:\n{traceback.format_exc()}")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
