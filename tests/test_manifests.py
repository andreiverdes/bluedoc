"""The plugin manifests Codex and Copilot CLI read (their versions: test_commands): each one wires its components to
paths inside the repo. The layout is pinned because each agent picks its manifest by where it is and what it
declares: a root plugin.json with an Agent Plugins `$schema` makes Codex (0.163, codex-rs/core-plugins loader.rs)
load that file and no plugin hooks at all, skipping .codex-plugin/plugin.json and the plan-mode hook's Stop hook; Copilot
CLI reads .plugin/plugin.json first among legacy manifests, so it gets its commands and hooks from there."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from _support import REPO

AGENT_PLUGINS_SCHEMA = "https://agent-plugins.org/schemas/"


def manifest(rel: str) -> dict:
    return json.loads((REPO / rel).read_text(encoding="utf-8"))


class ManifestLayout(unittest.TestCase):
    def test_no_root_agent_plugins_manifest(self):
        """Codex reads a root plugin.json with an Agent Plugins $schema in place of .codex-plugin/ and loads no hooks."""
        root = REPO / "plugin.json"
        if root.exists():
            self.assertFalse(str(manifest("plugin.json").get("$schema", "")).startswith(AGENT_PLUGINS_SCHEMA))

    def test_codex_manifest_wires_skills_and_hooks(self):
        m = manifest(".codex-plugin/plugin.json")
        self.assertTrue((REPO / m["skills"] / "bluedoc" / "SKILL.md").is_file())
        hooks = manifest(m["hooks"])["hooks"]
        self.assertIn("codex plan", hooks["Stop"][0]["hooks"][0]["command"])
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "apply_patch")   # patch-only edits
        self.assertIn("codex edit", hooks["PreToolUse"][0]["hooks"][0]["command"])

    def test_copilot_manifest_wires_skills_commands_and_hooks(self):
        m = manifest(".plugin/plugin.json")
        self.assertTrue((REPO / m["skills"] / "bluedoc" / "SKILL.md").is_file())
        self.assertTrue(sorted((REPO / m["commands"]).glob("bluedoc-*.md")))
        hooks = manifest(m["hooks"])["hooks"]
        self.assertEqual(hooks["preToolUse"][0]["matcher"], "exit_plan_mode")
        self.assertIn("copilot plan", hooks["preToolUse"][0]["bash"])
        # after an approval Copilot ends its turn without exit_plan_mode unless agentStop prompts it (beta19, beta20)
        self.assertIn("copilot stop", hooks["agentStop"][0]["bash"])
        self.assertEqual(hooks["preToolUse"][1]["matcher"], "edit|create|str_replace|str_replace_editor|apply_patch")
        self.assertIn("copilot edit", hooks["preToolUse"][1]["bash"])

    def test_component_paths_stay_in_the_repo(self):
        for rel in (".codex-plugin/plugin.json", ".plugin/plugin.json"):
            m = manifest(rel)
            for key in ("skills", "commands", "hooks"):
                if key in m:
                    with self.subTest(rel=rel, key=key):
                        path = (REPO / m[key]).resolve()
                        self.assertTrue(path.is_relative_to(REPO.resolve()) and path.exists(), path)


if __name__ == "__main__":
    unittest.main()
