"""mdplan.from_markdown and `build.py from-md`: Markdown plans of different shapes become plan docs that build with no
errors, with steps and files taken from the right places and every other line kept."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from _support import TempHome

import build
import mdplan

NUMBERED = """# Plan: Add rate limiting

Requests to `POST /orders` have no limit; a bot sent 40k in an hour.

## Context
The handler is in `app/server.py`.

## Implementation steps
1. Add a token bucket in `src/limits/bucket.ts` with per-IP keys stored in Redis so that limits survive restarts and every instance shares one counter.
2. Wire it into `app/server.py`
   - return 429 with `Retry-After`
3. Add tests

```ts
const limit = 100;
```

## Risks
| Risk | Mitigation |
|---|---|
| Shared NAT | allowlist |
"""

HEADINGS = """# Migrate settings to DataStore

## Overview
SharedPreferences blocks the main thread.

## Add the DataStore dependency
Edit `app/build.gradle.kts`.

## Write a migration
Use `SharedPreferencesMigration`.

## Verification
Run the app.
"""

QUESTIONS = """# Add dark mode

## Open questions
1. Default to system?
2. Persist the choice?

## Steps
1. Add color tokens
2. Switch on `prefers-color-scheme`
"""

NO_TITLE = """## Context
The reader asked for a greeting file.

## Summary
One file.

## Add the greeting file
1. Create `/tmp/greet/hello.txt`
2. Write `hi` into it
"""


class FromMarkdown(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.project = self.tmp.dir / "project"
        (self.project / "app").mkdir(parents=True)
        (self.project / "app" / "server.py").write_text("", encoding="utf-8")

    def doc(self, text: str) -> dict:
        d = mdplan.from_markdown(text, stem="p", project_dir=self.project, org="Acme")
        rep = build.validate(d, None)
        self.assertEqual(rep.errors, [], json.dumps(d, indent=1))
        return d

    @staticmethod
    def steps(d: dict) -> list[dict]:
        return next(b for s in d["sections"] for b in s["blocks"] if b["type"] == "steps")["items"]

    @staticmethod
    def files(d: dict) -> dict[str, dict]:
        return {f["path"]: f for s in d["sections"] for b in s["blocks"] if b["type"] == "files" for f in b["items"]}

    def test_numbered_list_under_a_steps_heading(self) -> None:
        d = self.doc(NUMBERED)
        self.assertEqual(d["title"], "Add rate limiting")
        self.assertTrue(d["tldr"].startswith("Requests to `POST /orders`"))
        steps = self.steps(d)
        self.assertEqual(len(steps), 3)
        self.assertLessEqual(len(steps[0]["title"]), mdplan.MAX_STEP_TITLE)
        self.assertIn("every instance shares one counter", steps[0]["md"], "the cut-off rest of a long item is kept")
        self.assertIn("429", steps[1]["md"], "nested list kept with its step")
        # the fence after the list is a block of the section, not part of step 3
        self.assertNotIn("md", steps[2])
        sec = next(s for s in d["sections"] if any(b["type"] == "steps" for b in s["blocks"]))
        self.assertEqual([b["type"] for b in sec["blocks"]], ["steps", "code"])
        self.assertIn("table", [b["type"] for s in d["sections"] for b in s["blocks"]])
        files = self.files(d)
        self.assertEqual(files["app/server.py"]["action"], "edit")
        self.assertEqual(files["src/limits/bucket.ts"]["action"], "add")
        self.assertEqual(files["src/limits/bucket.ts"]["step"], steps[0]["id"])
        self.assertNotIn("POST /orders", files, "an HTTP route isn't a file")

    def test_sections_become_steps_without_a_numbered_list(self) -> None:
        d = self.doc(HEADINGS)
        self.assertEqual([s["title"] for s in self.steps(d)], ["Add the DataStore dependency", "Write a migration"])
        self.assertEqual([s["id"] for s in d["sections"]], ["overview", "steps", "verification", "files"])

    def test_a_questions_list_is_not_the_steps(self) -> None:
        d = self.doc(QUESTIONS)
        self.assertEqual([s["title"] for s in self.steps(d)], ["Add color tokens", "Switch on `prefers-color-scheme`"])
        q = next(s for s in d["sections"] if s["title"] == "Open questions")
        self.assertIn("Persist the choice?", q["blocks"][0]["md"])

    def test_a_plan_without_steps_or_paths_still_meets_the_contract(self) -> None:
        d = self.doc("# Tiny fix\n\nRename a variable.\n")
        self.assertEqual(len(self.steps(d)), 1)
        self.assertEqual(len(self.files(d)), 1)

    def test_a_plan_without_a_title_is_named_from_its_file_or_doc_else_a_telling_heading(self) -> None:
        """omp's plans start at ##: the title isn't their first section (Context)."""
        title = lambda **kw: mdplan.from_markdown(NO_TITLE, project_dir=self.project, org="Acme", **kw)["title"]  # noqa: E731
        self.assertEqual(title(stem="p", plan_file="/plans/hello-txt-plan.md"), "Hello txt plan")
        # the gate's inline copy of an omp local:// plan says nothing; the doc it names after local://hello-txt-plan.md does
        self.assertEqual(title(stem="hello-txt-plan", plan_file="/h/omp/inline-0123456789ab.md"), "Hello txt plan")
        self.assertEqual(title(stem="plan-2", plan_file="/h/PLAN.md"), "Add the greeting file")
        self.assertEqual(title(stem="plan", plan_file=None), "Add the greeting file")
        self.assertEqual(mdplan.from_markdown("## Context\nx\n", stem="plan", project_dir=self.project, org="A")["title"],
                         "Plan")
        plan, out = self.tmp.dir / "hello-txt-plan.md", self.tmp.dir / "out" / "hello-txt-plan.bluedoc.json"
        plan.write_text(NO_TITLE, encoding="utf-8")
        r = self.tmp.run("build.py", "from-md", plan, out, "--project", self.project)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["title"], "Hello txt plan")

    def test_reimport_keeps_the_id_and_bumps_the_rev(self) -> None:
        plan, out = self.tmp.dir / "plan.md", self.tmp.dir / "out" / "my-plan.bluedoc.json"
        plan.write_text(NUMBERED, encoding="utf-8")
        r = self.tmp.run("build.py", "from-md", plan, out, "--project", self.project)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 error(s)", r.stderr)
        first = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual((first["id"], first["meta"]["rev"]), ("my-plan", "1"))
        plan.write_text(NUMBERED.replace("Add tests", "Add load tests"), encoding="utf-8")
        r = self.tmp.run("build.py", "from-md", plan, out, "--project", self.project, "--change", "Step 3 renamed.")
        self.assertEqual(r.returncode, 0, r.stderr)
        second = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual((second["id"], second["meta"]["rev"], second["changes"]), ("my-plan", "2", ["Step 3 renamed."]))
        history = json.loads(out.with_name("my-plan.bluedoc.history.json").read_text(encoding="utf-8"))
        self.assertEqual([e["rev"] for e in history["revs"]], ["1", "2"])


if __name__ == "__main__":
    unittest.main()
