"""Evidence pinned to the code revision it checked (scripts/codepin.py), in a temp git repo.

`build.py patch` stamps the evidence it records with the repo, the full HEAD sha, whether the covered files were dirty
and a fingerprint of how, the paths it covers and the time; no git or no repo records `commit: null` with a reason and
never fails. Staleness compares a pin with the repo now: current, then stale after a commit touching its paths, moved
(still valid) after a commit elsewhere, stale after a reset past its commit, current again for the same uncommitted
changes and stale for others; a missing repo or git is unknown. `build.py --check-code` and the plan gate list stale
checks under `## Stale evidence` with the commands that re-record them, and `patch --pin` makes them current again.
In the browser, a stale item shows its warning, isn't counted as done, and Approve warns."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from _support import TempHome, load_json

import codepin
import hook
from test_page_state import CHROME, ChromePage

GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "Acme", "GIT_AUTHOR_EMAIL": "dev@acme.example",
           "GIT_COMMITTER_NAME": "Acme", "GIT_COMMITTER_EMAIL": "dev@acme.example"}
PLAN = "acme-saved-carts-plan.bluedoc.json"
EVIDENCE = {"evidence": [{"label": "Unit tests", "code": "pnpm --filter orders-api test", "md": "`12 passed`"}]}


def make_repo(root: Path, env: dict) -> None:
    """A git repo at root with Acme sources under src/, and everything already in root, committed."""
    (root / "src" / "carts").mkdir(parents=True, exist_ok=True)
    (root / "src" / "pricing").mkdir(parents=True, exist_ok=True)
    (root / "src" / "carts" / "savedCartRepo.ts").write_text("export const LIMIT = 20;\n", encoding="utf-8")
    (root / "src" / "pricing" / "tax.ts").write_text("export const VAT = 0.25;\n", encoding="utf-8")
    git(root, env, "init", "-q", "-b", "main")
    git(root, env, "add", "-A")
    git(root, env, "commit", "-qm", "Acme shop")


def git(root: Path, env: dict, *args: str) -> str:
    r = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args], env={**env, **GIT_ENV},
                       capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout.strip()


def evidence_of(doc: Path, block: str, item: str) -> list[dict]:
    """The evidence of item in the checklist or steps block with id block."""
    d = load_json(doc)
    b = next(b for s in d["sections"] for b in s["blocks"] if b.get("id") == block)
    return next(it for it in b["items"] if it["id"] == item).get("evidence") or []


class Pins(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.tmp.dir / "acme-shop"
        self.docs = self.tmp.copy_examples("acme-shop/docs")
        make_repo(self.repo, self.tmp.env)
        self.plan = self.docs / PLAN
        self.env = {**self.tmp.env, **GIT_ENV}

    def git(self, *args: str) -> str:
        return git(self.repo, self.tmp.env, *args)

    def commit(self, rel: str, text: str, msg: str) -> str:
        (self.repo / rel).write_text(text, encoding="utf-8")
        self.git("add", rel)
        self.git("commit", "-qm", msg)
        return self.git("rev-parse", "HEAD")

    def patch(self, *args: str, ok: bool = True) -> subprocess.CompletedProcess:
        r = subprocess.run([str(a) for a in ("python3", Path(codepin.__file__).with_name("build.py"), "patch", self.plan, *args)],
                           env=self.env, cwd=self.tmp.dir, capture_output=True, text=True, timeout=60)
        if ok:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def states(self, doc: Path | None = None) -> dict[str, list[str]]:
        doc = doc or self.plan
        res = codepin.evaluate(load_json(doc), doc) or {"owners": {}}
        return {k: [r and r["state"] for r in o["ev"]] for k, o in res["owners"].items()}

    def test_patch_stamps_commit_dirty_tree_and_paths(self) -> None:
        head = self.git("rev-parse", "HEAD")
        out = self.patch("item:checks/unit", "--set", "done=true", "--json", json.dumps(EVIDENCE), "--paths", "src/carts").stdout
        self.assertIn(f"pinned 1 evidence entry to the doc's repo at {head[:7]}", out)
        pin = evidence_of(self.plan, "checks", "unit")[0]["pin"]
        self.assertEqual(pin["repo"], "..")
        self.assertEqual(pin["commit"], head)
        self.assertIs(pin["dirty"], False)
        self.assertNotIn("tree", pin)
        self.assertEqual(pin["paths"], ["src/carts"])
        self.assertRegex(pin["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        # the patch rewrote the doc and its history: bluedoc's own files never count as changes
        self.assertEqual(self.states(), {"item:checks/unit": ["current"]})
        # an uncommitted change under the paths: dirty, with the fingerprint of how
        (self.repo / "src" / "carts" / "savedCartRepo.ts").write_text("export const LIMIT = 25;\n", encoding="utf-8")
        out = self.patch("step:steps/0/repo", "--set", "status=done", "--json", json.dumps(EVIDENCE), "--no-bump").stdout
        self.assertIn("+ uncommitted changes", out)
        pin = evidence_of(self.plan, "plan", "repo")[0]["pin"]
        self.assertIs(pin["dirty"], True)
        self.assertRegex(pin["tree"], r"^[0-9a-f]{64}$")
        self.assertNotIn("paths", pin)
        # the item's pin was clean: the same change makes it stale; the step's is as checked
        self.assertEqual(self.states(), {"item:checks/unit": ["stale"], "step:plan/repo": ["current"]})

    def test_staleness_follows_the_repo(self) -> None:
        pinned = codepin.stamp(self.plan, paths=["src/carts"])
        whole = codepin.stamp(self.plan)
        doc = load_json(self.plan)
        checks = next(b for s in doc["sections"] for b in s["blocks"] if b.get("id") == "checks")
        checks["items"][0]["evidence"] = [{"label": "Carts", "md": "ok", "pin": pinned}, {"label": "All", "md": "ok", "pin": whole}]
        self.plan = self.docs / "acme-pins.bluedoc.json"   # untracked: the resets below leave it alone
        self.plan.write_text(json.dumps(doc), encoding="utf-8")
        st = lambda: self.states()["item:checks/unit"]  # noqa: E731
        self.assertEqual(st(), ["current", "current"])
        # a commit elsewhere: the narrowed check is still valid, the whole-repo one isn't
        self.commit("src/pricing/tax.ts", "export const VAT = 0.21;\n", "VAT")
        self.assertEqual(st(), ["moved", "stale"])
        r = codepin.evaluate(load_json(self.plan), self.plan)["owners"]["item:checks/unit"]["ev"]
        self.assertEqual(r[0]["reason"], f"checked at {pinned['commit'][:7]}, code since doesn't touch it")
        self.assertEqual(r[1]["files"], ["src/pricing/tax.ts"])
        # a commit touching the paths
        self.commit("src/carts/savedCartRepo.ts", "export const LIMIT = 30;\n", "Limit")
        r = codepin.evaluate(load_json(self.plan), self.plan)["owners"]["item:checks/unit"]["ev"]
        self.assertEqual([x["state"] for x in r], ["stale", "stale"])
        self.assertEqual((r[0]["files"], r[0]["n"]), (["src/carts/savedCartRepo.ts"], 1))
        self.assertEqual(r[0]["reason"], f"code changed since {pinned['commit'][:7]}")
        # back to the pinned commit: current again
        self.git("reset", "-q", "--hard", pinned["commit"])
        self.assertEqual(st(), ["current", "current"])
        # a reset past it (and a rewritten history): HEAD no longer contains the commit
        self.git("checkout", "-q", "--orphan", "rewritten")
        self.git("commit", "-qm", "Acme shop, squashed")
        r = codepin.evaluate(load_json(self.plan), self.plan)["owners"]["item:checks/unit"]["ev"]
        self.assertEqual([x["state"] for x in r], ["stale", "stale"])
        self.assertIn("rebased or reset", r[0]["reason"])

    def test_dirty_pins_match_only_their_own_changes(self) -> None:
        f = self.repo / "src" / "carts" / "savedCartRepo.ts"
        f.write_text("export const LIMIT = 25;\n", encoding="utf-8")
        (self.repo / "src" / "carts" / "new.ts").write_text("export {};\n", encoding="utf-8")   # untracked counts too
        pin = codepin.stamp(self.plan, paths=["src/carts"])
        self.assertTrue(pin["dirty"])
        root = codepin.repo_root(self.repo)
        self.assertEqual(codepin.check(root, pin)["state"], "current")
        f.write_text("export const LIMIT = 26;\n", encoding="utf-8")
        res = codepin.check(root, pin)
        self.assertEqual((res["state"], res["files"]), ("stale", ["src/carts/new.ts", "src/carts/savedCartRepo.ts"]))
        f.write_text("export const LIMIT = 25;\n", encoding="utf-8")
        self.assertEqual(codepin.check(root, pin)["state"], "current")
        # committing exactly the checked changes: the code is what was checked, so the evidence stays valid
        self.commit("src/carts/savedCartRepo.ts", "export const LIMIT = 25;\n", "Limit 25")
        self.assertEqual(codepin.check(root, pin)["state"], "moved")
        self.commit("src/carts/new.ts", "export const NEW = 1;\n", "New")
        self.assertEqual(codepin.check(root, pin)["state"], "stale")

    def test_no_repo_or_no_git_is_unpinned_or_unknown(self) -> None:
        outside = self.tmp.dir / "loose"
        outside.mkdir()
        pin = codepin.stamp(outside / PLAN, repo=outside)
        self.assertEqual((pin["commit"], pin["reason"]), (None, "'loose' is not in a git repository"))
        saved = codepin.GIT
        codepin.GIT = ("acme-no-such-git",)
        try:
            self.assertEqual(codepin.stamp(self.plan)["reason"], "git is not installed")
            doc = load_json(self.plan)
            doc["sections"][-1]["blocks"][0]["items"][0]["evidence"] = [
                {"label": "Carts", "md": "ok", "pin": {"repo": "..", "commit": "a" * 40, "dirty": False, "at": "2026-10-17T09:30:00Z"}}]
            self.assertEqual(codepin.evaluate(doc, self.plan)["owners"]["item:checks/unit"]["ev"][0]["state"], "unknown")
        finally:
            codepin.GIT = saved
        # a named repo that isn't here
        doc["sections"][-1]["blocks"][0]["items"][0]["evidence"][0]["pin"]["repo"] = "acme-gone"
        r = codepin.evaluate(doc, self.plan)["owners"]["item:checks/unit"]["ev"][0]
        self.assertEqual((r["state"], r["reason"]), ("unknown", "repository 'acme-gone' isn't here"))
        # a patch outside any repo still writes, with the reason
        loose = outside / PLAN
        shutil.copytree(self.docs / "media", outside / "media")
        loose.write_text(self.plan.read_text(encoding="utf-8"), encoding="utf-8")
        r = subprocess.run(["python3", str(Path(codepin.__file__).with_name("build.py")), "patch", str(loose), "item:checks/unit",
                            "--json", json.dumps(EVIDENCE), "--repo", str(outside)], env=self.env, cwd=outside,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 evidence entry unpinned: 'loose' is not in a git repository", r.stdout)
        self.assertEqual(evidence_of(loose, "checks", "unit")[0]["pin"]["commit"], None)

    def test_check_code_lists_stale_checks_and_pin_re_records(self) -> None:
        self.patch("item:checks/unit", "--set", "done=true", "--json", json.dumps(EVIDENCE), "--paths", "src/carts")
        first = self.git("rev-parse", "HEAD")
        self.commit("src/carts/savedCartRepo.ts", "export const LIMIT = 30;\n", "Limit")
        r = subprocess.run(["python3", str(Path(codepin.__file__).with_name("build.py")), str(self.plan), "--check", "--check-code"],
                           env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"WARN  item:checks/unit 'Unit tests' stale: code changed since {first[:7]}: src/carts/savedCartRepo.ts", r.stderr)
        self.assertIn("1 check has stale evidence", r.stderr)
        md = codepin.stale_md(codepin.evaluate(load_json(self.plan), self.plan))
        self.assertTrue(md.startswith("## Stale evidence\n\n1 check has stale evidence: the code changed since it ran."), md)
        self.assertIn("- **Run the orders-api tests** `item:checks/unit`\n  - Unit tests: code changed since "
                      f"{first[:7]} (src/carts/savedCartRepo.ts)\n    Re-run: `pnpm --filter orders-api test`", md)
        self.assertIn(f"build.py patch {PLAN} item:checks/unit --pin --change 'Re-ran the checks after code changes'", md)
        # the plan gate says the same, with the doc's path
        self.assertIn("## Stale evidence", hook.stale_evidence(self.plan))
        self.assertIn(f"build.py patch {self.plan} item:checks/unit --pin", hook.stale_evidence(self.plan))
        # re-recording keeps each entry's paths and pins it to HEAD
        out = self.patch("item:checks/unit", "--pin").stdout
        self.assertIn("pinned 1 evidence entry", out)
        pin = evidence_of(self.plan, "checks", "unit")[0]["pin"]
        self.assertEqual((pin["commit"], pin["paths"]), (self.git("rev-parse", "HEAD"), ["src/carts"]))
        self.assertEqual(load_json(self.plan)["changes"], ["Re-recorded the evidence of `item:checks/unit`."])
        self.assertEqual(self.states(), {"item:checks/unit": ["current"]})
        self.assertEqual(hook.stale_evidence(self.plan), "")
        # --pin needs evidence to pin, and a step: or item: key
        self.assertIn("nothing to pin", self.patch("item:checks/cross-device", "--pin", ok=False).stderr)
        self.assertIn("--pin re-pins a step's or item's evidence", self.patch("tldr", "--pin", ok=False).stderr)


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class StaleOnThePage(ChromePage):
    def setUp(self) -> None:
        super().setUp()
        self.repo = self.docs.parent
        make_repo(self.repo, self.tmp.env)
        r = subprocess.run(["python3", str(Path(codepin.__file__).with_name("build.py")), "patch", str(self.plan), "item:checks/unit",
                            "--set", "done=true", "--json", json.dumps(EVIDENCE), "--paths", "src/carts"],
                           env={**self.tmp.env, **GIT_ENV}, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.first = git(self.repo, self.tmp.env, "rev-parse", "HEAD")

    def test_a_stale_check_warns_and_isnt_counted(self) -> None:
        url = self.server.url_for(self.plan)
        tab = self.open(url)
        item = "document.querySelector('#item-checks-unit')"
        self.assertEqual(tab.ev(f"{item}.querySelector('.bp-pin').dataset.state"), "current")
        self.assertEqual(tab.ev("BP.progress().find(c => c.id === 'checks').done"), 1)
        (self.repo / "src" / "carts" / "savedCartRepo.ts").write_text("export const LIMIT = 30;\n", encoding="utf-8")
        git(self.repo, self.tmp.env, "commit", "-qam", "Limit 30")
        tab.go(f"{self.base}{url}")
        self.assertTrue(tab.ev(f"{item}.classList.contains('stale') && {item}.querySelector('input').checked"))
        self.assertEqual(tab.ev(f"{item}.querySelector('.bp-recheck').textContent"), "Needs recheck")
        self.assertEqual(tab.ev(f"{item}.querySelector('.bp-pin').dataset.state"), "stale")
        self.assertEqual(tab.ev(f"{item}.querySelector('.bp-pin code').textContent"), self.first[:7])
        self.assertIn(self.first, tab.ev(f"{item}.querySelector('.bp-pin').title"))
        self.assertEqual(tab.ev(f"{item}.querySelector('.bp-pin-stale summary').textContent"),
                         f"Stale: code changed since {self.first[:7]} (1 file)")
        self.assertEqual(tab.ev(f"{item}.querySelector('.bp-pin-stale li').textContent"), "src/carts/savedCartRepo.ts")
        # not counted as done: the checklist, the sidebar and the top bar
        self.assertEqual(tab.ev("BP.progress().find(c => c.id === 'checks').done"), 0)
        self.assertEqual(tab.ev("document.querySelector('#cl-checks .bp-cl-count').textContent"), "0 of 6 · 1 to recheck")
        self.assertEqual(tab.ev("BP.evidence().stale"), ["item:checks/unit"])
        self.assertIn("- [ ] Run the orders-api tests `item:checks/unit` (needs recheck: its evidence is stale)", tab.ev("BP.progressMarkdown()"))
        # Approve warns without blocking, and the approval and the change request carry ## Stale evidence
        tab.ev("document.querySelector('.bd-key.approve').click()")
        tab.wait_for("!!document.querySelector('dialog.bd-approve[open]')")
        self.assertIn("1 check has stale evidence: the code changed since it ran",
                      tab.ev("document.querySelector('dialog.bd-approve[open] .bd-ap-sum').textContent"))
        self.assertFalse(tab.ev("document.querySelector('dialog.bd-approve[open] .ft .bp-btn.ok').disabled"))
        approval = tab.ev("BP.approvePayload('').markdown")
        self.assertIn("## Stale evidence\n\n1 check has stale evidence", approval)
        self.assertIn("build.py patch acme-saved-carts-plan.bluedoc.json item:checks/unit --pin", approval)
        self.assertIn("## Stale evidence", tab.ev("BP.changesPayload().markdown"))
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
