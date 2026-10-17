"""tools/gen_commands.py and the /bluedoc-<name> commands it writes from commands/commands.json: the checked-in files
match the spec, and an edited spec or a stale file fails `--check`; every command has its Claude Code, Copilot and
Antigravity file; the action commands' shell lines run their script as written (Claude's `!` line, the command Antigravity's
skill names from its own folder); `build.py export` and `serve.py reply` without a target, which two actions use."""
from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from _support import REPO, TempHome

GEN = REPO / "tools" / "gen_commands.py"
SPEC = REPO / "commands" / "commands.json"
FOLDERS = ("commands", "com.github.copilot/commands", "antigravity/skills")
SUFFIXES = (".md", ".md", "/SKILL.md")


def gen(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GEN), *args], capture_output=True, text=True, timeout=30)


def spec() -> list[dict]:
    return json.loads(SPEC.read_text(encoding="utf-8"))


class Generated(unittest.TestCase):
    def test_check_passes_on_the_checked_in_files(self) -> None:
        r = gen("--check")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_an_edited_spec_or_a_stale_file_fails_check(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        for folder in FOLDERS:
            shutil.copytree(REPO / folder, tmp.dir / folder)
        self.assertEqual(gen("--check", "--root", str(tmp.dir)).returncode, 0)
        edited = spec()
        edited[0]["prompt"] = edited[0]["prompt"].replace("Write", "Draft", 1)
        (tmp.dir / "commands" / "commands.json").write_text(json.dumps(edited), encoding="utf-8")
        r = gen("--check", "--root", str(tmp.dir))
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"out of date: commands/bluedoc-{edited[0]['name']}.md", r.stderr)
        self.assertEqual(gen("--root", str(tmp.dir)).returncode, 0)
        self.assertIn("Draft", (tmp.dir / "commands" / f"bluedoc-{edited[0]['name']}.md").read_text(encoding="utf-8"))
        gone = tmp.dir / "antigravity" / "skills" / "bluedoc-gone"
        gone.mkdir()
        (gone / "SKILL.md").write_text("---\nname: bluedoc-gone\n---\n", encoding="utf-8")
        r = gen("--check", "--root", str(tmp.dir))
        self.assertEqual(r.returncode, 1)
        self.assertIn("stale: antigravity/skills/bluedoc-gone/SKILL.md", r.stderr)
        self.assertEqual(gen("--root", str(tmp.dir)).returncode, 0)
        self.assertFalse(gone.exists())

    def test_a_bad_spec_is_refused(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        (tmp.dir / "commands").mkdir()
        bad = [{"name": "bluedoc-x", "description": "", "args": "", "kind": "action",
                "run": {"script": "rm", "args": ["-f"]}},
               {"name": "y", "description": "Y", "args": "", "kind": "action",
                "run": {"script": "serve.py", "args": ["{{args}}", "open"]}}]
        (tmp.dir / "commands" / "commands.json").write_text(json.dumps(bad), encoding="utf-8")
        r = gen("--root", str(tmp.dir))
        self.assertEqual(r.returncode, 2)
        for field in ("[0].name", "[0].description", "[0].run.script", "[1].run.args"):
            self.assertIn(f"commands{field}", r.stderr)

    def test_every_command_has_each_agents_file(self) -> None:
        names = [c["name"] for c in spec()]
        self.assertEqual(len(names), 14)
        for name in names:
            for folder, suffix in zip(FOLDERS, SUFFIXES):
                self.assertTrue((REPO / folder / f"bluedoc-{name}{suffix}").is_file(), f"{folder}/bluedoc-{name}{suffix}")
        for c in spec():
            md = (REPO / "commands" / f"bluedoc-{c['name']}.md").read_text(encoding="utf-8")
            self.assertIn(f"description: {json.dumps(c['description'])}", md)
            takes = c["kind"] == "prompt" or c["run"]["args"][-1:] == ["{{args}}"]
            self.assertEqual("$ARGUMENTS" in md, takes, c["name"])
            if c["kind"] == "prompt":
                self.assertTrue(c["prompt"].endswith("Use the bluedoc skill; open the page and wait for my reply."))
                self.assertNotIn("!`", md)
        for c in spec():
            md = (REPO / "antigravity" / "skills" / f"bluedoc-{c['name']}" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(f"name: \"bluedoc-{c['name']}\"", md)
            self.assertIn(f"description: {json.dumps(c['description'])}", md)
            self.assertNotIn("{{args}}", md)
            if c["kind"] == "prompt":
                self.assertIn("the text I typed after the command", md)

    def test_antigravity_loads_the_skill_through_its_link(self) -> None:
        link = REPO / "antigravity" / "skills" / "bluedoc"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), (REPO / "skills" / "bluedoc").resolve())


class Packaging(unittest.TestCase):
    def test_the_skill_description_fits_the_agent_skills_limit(self) -> None:
        """The Agent Skills spec caps `description` at 1024 characters; pi refuses a longer one."""
        skill = (REPO / "skills" / "bluedoc" / "SKILL.md").read_text(encoding="utf-8")
        description = re.search(r"^description: (.*)$", skill, re.M).group(1)
        self.assertLessEqual(len(description), 1024)
        for phrase in ('"plan mode"', '"make a plan"', '"review findings"', '"a bluedoc"', "slide decks", "UI mockups"):
            self.assertIn(phrase, description)

    def test_every_manifest_has_one_version(self) -> None:
        read = lambda p: json.loads((REPO / p).read_text(encoding="utf-8"))  # noqa: E731
        market = read(".claude-plugin/marketplace.json")
        versions = {read(p)["version"] for p in ("package.json", ".claude-plugin/plugin.json", ".codex-plugin/plugin.json",
                                                  ".plugin/plugin.json", "antigravity/plugin.json")}
        versions |= {market.get("metadata", {}).get("version")} | {p.get("version") for p in market["plugins"]}
        self.assertEqual(len(versions - {None}), 1, versions)


class Actions(unittest.TestCase):
    """The action commands' shell lines, run as the agent would, against the repo's scripts."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()

    def sh(self, line: str) -> subprocess.CompletedProcess:
        return subprocess.run(["sh", "-c", line], env=self.tmp.env, cwd=self.tmp.dir, capture_output=True, text=True,
                              timeout=60)

    def claude_line(self, name: str, args: str) -> str:
        """Claude Code's `!` line, with ${CLAUDE_PLUGIN_ROOT} and $ARGUMENTS substituted as Claude Code does."""
        md = (REPO / "commands" / f"bluedoc-{name}.md").read_text(encoding="utf-8")
        line = re.search(r"^!`(.*)`$", md, re.M).group(1)
        return line.replace("${CLAUDE_PLUGIN_ROOT}", str(REPO)).replace("$ARGUMENTS", args)

    def agy_line(self, name: str, args: str) -> str:
        """The command Antigravity's command skill asks for: <skill> is its own folder, <args> the user's text."""
        md = (REPO / "antigravity" / "skills" / f"bluedoc-{name}" / "SKILL.md").read_text(encoding="utf-8")
        line = re.search(r"^Run `(.*?)`", md, re.M).group(1)
        return line.replace("<skill>", shlex.quote(str(REPO / "antigravity" / "skills" / f"bluedoc-{name}"))) \
            .replace("<args>", args)

    def test_export_writes_the_docs_file_next_to_it(self) -> None:
        status, deck = self.docs / "acme-status.bluedoc.json", self.docs / "acme-fit-deck.bluedoc.json"
        for line in (self.claude_line("export", str(status)), self.agy_line("export", f"{deck} html")):
            r = self.sh(line)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(Path(r.stdout.strip().splitlines()[-1]), self.docs / "acme-fit-deck.html")
        self.assertTrue((self.docs / "acme-status.html").is_file())
        self.assertIn("<html", (self.docs / "acme-fit-deck.html").read_text(encoding="utf-8")[:500].lower())
        r = self.sh(self.claude_line("export", f"{status} zip"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("exports as html, not zip", r.stderr)

    def test_replies_prints_the_newest_reply(self) -> None:
        r = self.sh(self.claude_line("replies", ""))
        self.assertEqual(r.returncode, 1)
        self.assertIn("no replies stored yet", r.stderr)
        import statedb
        db = statedb.StateDB(self.tmp.home / "state.db")
        orders, status = self.docs / "acme-orders.bluedoc.json", self.docs / "acme-status.bluedoc.json"
        db.add_reply(str(orders), "orders", "answers", "1", "{}", "# Orders answers\n")
        db.add_reply(str(status), "status", "changes", "2", "{}", "# Status changes\n")
        db.close()
        for line in (self.claude_line("replies", ""), self.agy_line("replies", "")):
            r = self.sh(line)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("# Status changes", r.stdout)
            self.assertIn("--- bluedoc change request (reply 2, rev 2", r.stdout)
        r = self.sh(self.agy_line("replies", str(orders)))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("# Orders answers", r.stdout)

    def test_every_action_names_a_script_that_takes_its_args(self) -> None:
        for c in spec():
            if c["kind"] != "action":
                continue
            fixed = [a for a in c["run"]["args"] if a != "{{args}}"]
            r = self.sh(" ".join([shlex.quote(sys.executable), shlex.quote(str(REPO / "skills" / "bluedoc" / "scripts" /
                                                                              c["run"]["script"])),
                                  *map(shlex.quote, fixed[:1]), "--help"]))
            self.assertEqual(r.returncode, 0, f"{c['name']}: {r.stderr}")


if __name__ == "__main__":
    unittest.main()
