"""extensions/bluedoc.ts loaded under node with a stub pi API: on pi (no resolvePlanReview), session_start registers
/bluedoc-plan-mode and bluedoc_submit_plan, and the tool carries a promptSnippet, without which pi leaves it out of the
system prompt's tool list (a local model in the beta19 live test then took the tool for an MCP one and never called it)."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest

from _support import REPO

NODE = shutil.which("node")
EXT = REPO / "extensions" / "bluedoc.ts"

LOAD = """
const tools = [], commands = [], handlers = {};
const pi = {
  on: (event, handler) => (handlers[event] ??= []).push(handler),
  registerCommand: (name) => commands.push(name),
  registerTool: (tool) => tools.push(tool),
  sendUserMessage: () => {},
  appendEntry: () => {},
};
const { default: bluedoc } = await import(process.argv[1]);
bluedoc(pi);
const ctx = { cwd: process.cwd(), hasUI: true, ui: { notify: () => {} }, isIdle: () => true,
  sessionManager: { getSessionId: () => "s", getBranch: () => [] } };
for (const handler of handlers.session_start ?? []) handler({}, ctx);
console.log(JSON.stringify({ commands, tools: tools.map(({ execute, ...rest }) => rest) }));
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


if __name__ == "__main__":
    unittest.main()
