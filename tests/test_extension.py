"""extensions/bluedoc.ts loaded under node with a stub pi API: on pi (no resolvePlanReview), session_start registers
/bluedoc-plan-mode and bluedoc_submit_plan, and the tool carries a promptSnippet, without which pi leaves it out of the
system prompt's tool list (a local model in the beta19 live test then took the tool for an MCP one and never called it).
The tool is also declared first: pi appends a late-registered tool behind pi-mcp-adapter's `mcp`, and the beta20 live
test's qwen then called it through `mcp` every time.

Patch-only edits: editTargets reads the files from pi's edit and write `path` and omp's write `path`, hashline
`[PATH#TAG]` sections with `MV`, apply_patch and sloppy headers, patch-mode renames and ast_edit `paths`; the tool_call
handler blocks an edit of a built doc with hook.py's reason and lets other calls, and every call with
BLUEDOC_PATCH_ONLY=0, through."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest

from _support import EXAMPLES, REPO, TempHome

NODE = shutil.which("node")
EXT = REPO / "extensions" / "bluedoc.ts"

LOAD = """
const tools = [], commands = [], handlers = {};
// pi's active tools before session_start: its built-ins and an extension tool registered at load.
let active = ["read", "bash", "edit", "write", "mcp"];
const pi = {
  on: (event, handler) => (handlers[event] ??= []).push(handler),
  registerCommand: (name) => commands.push(name),
  // Like pi after load: a new tool is registered and appended to the active tools.
  registerTool: (tool) => { tools.push(tool); active = [...active, tool.name]; },
  getActiveTools: () => [...active],
  setActiveTools: (names) => { active = [...names]; },
  sendUserMessage: () => {},
  appendEntry: () => {},
};
const { default: bluedoc } = await import(process.argv[1]);
bluedoc(pi);
const ctx = { cwd: process.cwd(), hasUI: true, ui: { notify: () => {} }, isIdle: () => true,
  sessionManager: { getSessionId: () => "s", getBranch: () => [] } };
for (const handler of handlers.session_start ?? []) handler({}, ctx);
console.log(JSON.stringify({ commands, active, tools: tools.map(({ execute, ...rest }) => rest) }));
"""


def load_on_pi() -> dict:
    r = subprocess.run([NODE, "--input-type=module", "-e", LOAD, EXT.as_uri()], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "node not installed")
class OnPi(unittest.TestCase):
    def test_the_submit_tool_is_listed_in_the_system_prompt(self) -> None:
        got = load_on_pi()
        self.assertIn("bluedoc-plan-mode", got["commands"])
        tool = next(t for t in got["tools"] if t["name"] == "bluedoc_submit_plan")
        self.assertTrue(tool.get("promptSnippet", "").strip(), "pi omits a custom tool without promptSnippet from <tools>")

    def test_the_submit_tool_is_declared_ahead_of_the_mcp_tool(self) -> None:
        active = load_on_pi()["active"]
        self.assertEqual(active[0], "bluedoc_submit_plan", active)
        self.assertEqual(sorted(active), sorted(["read", "bash", "edit", "write", "mcp", "bluedoc_submit_plan"]))


READ_TARGETS = """
const { editTargets } = await import(process.argv[1]);
console.log(JSON.stringify(JSON.parse(process.argv[2]).map(([tool, input]) => editTargets(tool, input))));
"""

# each [toolName, input] through the tool_call handlers, as pi and omp call them before the tool runs
TOOL_CALL = """
const handlers = {};
const pi = { on: (event, handler) => (handlers[event] ??= []).push(handler), registerCommand: () => {}, registerTool: () => {},
  getActiveTools: () => [], setActiveTools: () => {}, sendUserMessage: () => {}, appendEntry: () => {} };
const { default: bluedoc } = await import(process.argv[1]);
bluedoc(pi);
const ctx = { cwd: process.argv[3], hasUI: false, ui: { notify: () => {} }, isIdle: () => true,
  sessionManager: { getSessionId: () => "s", getBranch: () => [] } };
const out = [];
for (const [toolName, input] of JSON.parse(process.argv[2])) {
  const results = await Promise.all((handlers.tool_call ?? []).map(h => h({ type: "tool_call", toolCallId: "t", toolName, input }, ctx)));
  out.push(results.find(r => r) ?? null);
}
console.log(JSON.stringify(out));
"""


def node(script: str, *args: str, env: dict | None = None) -> list:
    r = subprocess.run([NODE, "--no-warnings", "--input-type=module", "-e", script, EXT.as_uri(), *args],
                       capture_output=True, text=True, timeout=60, env=env)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "node not installed")
class PatchOnly(unittest.TestCase):
    def test_edit_targets_reads_each_tool_shape(self) -> None:
        hashline = ("*** Begin Patch\n[docs/acme-orders.bluedoc.json#1A2B]\nPUT 3.=3:\n+  \"title\": \"Acme orders\",\n"
                    "MV \"docs/acme orders.bluedoc.json\"\n[src/orders.ts#9F0C]\nREM\n*** End Patch")
        apply_patch = ("*** Begin Patch\n*** Update File: docs/acme-orders.bluedoc.json\n*** Move to: docs/acme-old.bluedoc.json\n"
                       "@@\n-a\n+b\n*** Add File: src/new.ts\n+x\n*** End Patch")
        cases = [
            (["edit", {"path": "@docs/acme-orders.bluedoc.json", "edits": [{"oldText": "a", "newText": "b"}]}],   # pi
             ["docs/acme-orders.bluedoc.json"]),
            (["write", {"path": "docs/acme-orders.bluedoc.json", "content": "{}"}], ["docs/acme-orders.bluedoc.json"]),
            (["write", {"path": "[docs/acme-orders.bluedoc.json#1A2B]", "content": "{}"}], ["docs/acme-orders.bluedoc.json"]),
            (["edit", {"input": hashline}], ["docs/acme-orders.bluedoc.json", "src/orders.ts", "docs/acme orders.bluedoc.json"]),
            (["edit", {"input": apply_patch}], ["docs/acme-orders.bluedoc.json", "src/new.ts", "docs/acme-old.bluedoc.json"]),
            (["edit", {"input": "*** Edit File: docs/acme-orders.bluedoc.json all\n*** Find\na\n*** Replace\nb"}],
             ["docs/acme-orders.bluedoc.json"]),
            (["edit", {"path": "src/orders.ts", "edits": [{"op": "update", "rename": "docs/acme-orders.bluedoc.json", "diff": "x"}]}],
             ["src/orders.ts", "docs/acme-orders.bluedoc.json"]),
            (["ast_edit", {"ops": [{"pat": "a", "out": "b"}], "paths": ["docs/acme-orders.bluedoc.json", "src"]}],
             ["docs/acme-orders.bluedoc.json", "src"]),
            (["read", {"path": "docs/acme-orders.bluedoc.json"}], []),
            (["write", {"path": "local://acme.bluedoc.json", "content": "{}"}], []),
        ]
        got = node(READ_TARGETS, json.dumps([call for call, _ in cases]))
        for (call, want), paths in zip(cases, got):
            with self.subTest(call[0], input=call[1]):
                self.assertEqual(sorted(paths), sorted(want))

    def test_tool_call_blocks_an_edit_of_a_built_doc(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        for k in ("CI", "BLUEDOC_PATCH_ONLY"):
            tmp.env.pop(k, None)
        project = tmp.dir / "acme-shop"
        (project / "docs").mkdir(parents=True)
        for name in ("acme-orders.bluedoc.json", "acme-orders.bluedoc.history.json"):
            shutil.copy(EXAMPLES / name, project / "docs" / name)
        calls = json.dumps([["edit", {"path": "docs/acme-orders.bluedoc.json", "edits": [{"oldText": "a", "newText": "b"}]}],
                            ["edit", {"input": "[docs/acme-orders.bluedoc.json#1A2B]\nPUT 1.=1:\n+{"}],
                            ["write", {"path": "docs/acme-new.bluedoc.json", "content": "{}"}],
                            ["read", {"path": "docs/acme-orders.bluedoc.json"}]])
        blocked, hashline, new, read = node(TOOL_CALL, calls, str(project), env=tmp.env)
        self.assertIs(blocked["block"], True)
        self.assertTrue(blocked["reason"].startswith("acme-orders.bluedoc.json is a built bluedoc doc"), blocked)
        self.assertIn("build.py patch", blocked["reason"])
        self.assertEqual(hashline, blocked)
        self.assertEqual((new, read), (None, None))
        self.assertEqual(node(TOOL_CALL, calls, str(project), env={**tmp.env, "BLUEDOC_PATCH_ONLY": "0"}), [None] * 4)


if __name__ == "__main__":
    unittest.main()
