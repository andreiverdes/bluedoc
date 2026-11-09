"""A review's finding comments, the Comments panel's finding threads, and the diff block's branch names.

On a review page a saved comment on a finding goes with Request changes: it counts on that key, sits in its payload's
`answers` and its Markdown, and the send key (Reply and fix here) carries the picks alone (route). The Comments panel
lists the findings' threads with the page's comments, in its Pending · Open · Resolved · All tabs, grouped: the agent
replied (waiting for the reader), not sent yet, you answered, resolved (the doc carries a `choice`), then the page's own
(panel). On load a review opens the panel when something waits for the reader, else leaves it as it was (open); a click
on a finding's card opens the finding, scrolls to it and rings it (jump). `gitdiff.py --pr` stores the PR's `headRef` and
`baseRef` from `gh pr view` (a stub here: no network), and the build checks them (refs)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _support import EXAMPLES, SCRIPTS, load_json
from test_page_state import CHROME, GO, ChromePage, Tab

import build

REVIEW = "acme-review-findings.bluedoc.json"   # meta.review threads: the send key is Reply and fix
SEND = "document.querySelector('.bd-anntb .bd-key.send')"


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class FindingComments(ChromePage):
    def setUp(self) -> None:
        super().setUp()
        self.doc = self.docs / REVIEW
        self.url = self.server.url_for(self.doc)

    def keys(self, tab: Tab) -> list:
        """[Request changes' number, the send key's number ('' when hidden)]"""
        return tab.ev(f"[{GO}.querySelector('.n').textContent, (n => n.hidden ? '' : n.textContent)({SEND}.querySelector('.n'))]")

    def patch(self, *args: str) -> None:
        r = self.tmp.run("build.py", "patch", self.doc, *args)
        self.assertEqual(r.returncode, 0, r.stderr)

    def panel(self, tab: Tab, f: str) -> dict:
        return tab.ev(f"BP.comments({{filter: {json.dumps(f)}}})")

    def card(self, key: str) -> str:
        return f"document.querySelector('.bd-cs-fc[data-item=\"{key}\"]')"

    def test_a_finding_comment_goes_with_request_changes_and_the_pick_with_the_send_key(self) -> None:
        a = self.open(self.url)
        a.wait_for(f"!!{SEND}")
        self.assertEqual(self.keys(a), ["0", ""])
        a.ev("BP.setNote('t412/float-cents', 'Round per line, then sum.')")
        self.assertEqual(self.keys(a), ["1", ""], "the comment counts on Request changes, not on the send key")
        a.ev("BP.choose('t412/float-cents', 'fix')")
        self.assertEqual(self.keys(a), ["1", "1"], "the pick counts on the send key")
        p = a.ev("BP.changesPayload()")
        self.assertEqual([(x["item"], x.get("note")) for x in p["answers"]], [("float-cents", "Round per line, then sum.")])
        self.assertIn("`item:t412/float-cents`", p["markdown"])
        self.assertIn("  > Round per line, then sum.", p["markdown"])
        s = a.ev("BP.replyPayload()")
        self.assertEqual([x for x in s["items"] if "note" in x or "files" in x or "more" in x], [])
        self.assertEqual(next(x for x in s["items"] if x["item"] == "float-cents")["choice"], "fix")
        self.assertNotIn("Round per line", s["markdown"])
        # Request changes sends the comment into the thread; the pick waits for the send key
        a.ev(f"{GO}.click()")
        a.wait_for("!!document.querySelector('.bd-chgs[open]')")
        self.assertIn("picks go with Reply and fix", a.ev("document.querySelector('.bd-chgs[open] .sum').textContent"))
        a.ev("document.querySelector('.bd-chgs[open] .bd-ibtn').click()")
        self.send_changes(a, "1 comment on findings")
        self.assertIn("> Round per line, then sum.", self.reply(self.doc))
        self.assertEqual(self.keys(a), ["0", "1"])
        self.assertEqual([(m["who"], m["md"]) for m in a.ev("BP.thread('t412/float-cents')")], [("you", "Round per line, then sum.")])
        # a comment saved after it waits for the next Request changes: the send dialog says so and leaves it out
        a.ev("BP.setNote('t412/float-cents', 'And a test at 10 units.')")
        a.ev(f"{SEND}.click()")
        a.wait_for("!!document.querySelector('.bd-send[open]:not(.bd-chgs)')")
        self.assertIn("1 comment on findings goes with Request changes", a.ev("document.querySelector('.bd-send[open] .sum').textContent"))
        a.wait_for("!document.querySelector('.bd-send[open] .ft .primary').hidden")
        a.ev("document.querySelector('.bd-send[open] .ft .bp-btn.primary').click()")
        self.toast(a, "sent to")
        answers = json.loads(self.tmp.run("serve.py", "reply", self.doc, "--kind", "answers", "--json").stdout)
        x = next(x for x in answers["items"] if x["item"] == "float-cents")
        self.assertEqual({k: v for k, v in x.items() if k != "text"}, {"checklist": "t412", "item": "float-cents", "choice": "fix", "recommend": "fix"})
        self.assertEqual(self.keys(a), ["1", ""], "the send key took the pick and left the comment")
        self.assertEqual(a.ev("BP.thread('t412/float-cents').length"), 1)
        self.assertEqual(self.browser.errors, [])

    def test_the_panel_lists_finding_threads_by_tab_and_group(self) -> None:
        a = self.open(self.url)
        a.ev("BP.setNote('t415/double-auth', 'Fix it in this PR: reuse the first idempotency key.')")
        a.ev("BP.setNote('t415/retry-4xx', 'Retry 5xx and timeouts only.')")
        self.send_changes(a, "2 comments on findings")
        self.patch("item:t415/retry-4xx", "--reply", "A 402 is final, so the retry stops on any 4xx and keeps 5xx and timeouts. Does that cover the decline you saw?")
        self.patch("item:t412/docs-stale", "--set", "choice=ticket", "--no-bump")
        a = self.open(self.url)
        a.ev("BP.moreDetails('t412/boundary-tests'); BP.setNote('t412/boundary-tests', 'Which thresholds, and is 50 inclusive?')")
        a.ev("BP.setNote('t415/latency', 'Cap the whole retry at 10 s, not each attempt.')")
        # tabs count the findings with the page's comments
        a.ev("BP.annotate({type: 'pin', key: 'tldr', note: 'Acme: name the two PRs here.'})")
        self.assertEqual(a.ev("[...document.querySelectorAll('.bd-cs-f [data-f]')].map(b => b.textContent)"), ["Pending3", "Open2", "Resolved1", "All6"])
        p = self.panel(a, "open")
        self.assertEqual(p["groups"], ["wait", "answered"])
        self.assertEqual([(x["item"], x["group"]) for x in p["findings"]], [("t415/retry-4xx", "wait"), ("t415/double-auth", "answered")])
        self.assertEqual(a.ev(f"[{self.card('t415/retry-4xx')}.querySelector('.pr').textContent, {self.card('t415/retry-4xx')}.querySelector('.s').textContent]"),
                         ["#415", "Waiting for yourev 5"])
        self.assertTrue(a.ev(f"{self.card('t415/retry-4xx')}.querySelector('.m').textContent.endsWith('Does that cover the decline you saw?')"))
        self.assertEqual(a.ev(f"(c => [c.classList.contains('done'), c.querySelector('.m').textContent, c.querySelector('.s').textContent])({self.card('t415/double-auth')})"),
                         [True, "You: Fix it in this PR: reuse the first idempotency key.", "Answeredsent in rev 4"])
        self.assertTrue(a.ev("document.querySelector('.bd-cs-h[data-g=wait]').textContent.endsWith(' replied1')"))
        p = self.panel(a, "pending")
        self.assertEqual(p["groups"], ["unsent", "page"])
        self.assertEqual([x["item"] for x in p["findings"]], ["t412/boundary-tests", "t415/latency"])
        self.assertEqual(len(p["cards"]), 1)
        self.assertEqual(a.ev(f"(c => [c.querySelector('.m').textContent, c.querySelector('.st').textContent])({self.card('t412/boundary-tests')})"),
                         ["You: Need more details: Which thresholds, and is 50 inclusive?", "Goes with Request changes"])
        p = self.panel(a, "resolved")
        self.assertEqual([(x["item"], x["group"]) for x in p["findings"]], [("t412/docs-stale", "resolved")])
        self.assertEqual(a.ev(f"{self.card('t412/docs-stale')}.querySelector('.s').textContent"), "Resolved→ Ticket")
        self.assertEqual(self.panel(a, "all")["groups"], ["wait", "unsent", "answered", "resolved", "page"])
        # Request changes takes the two comments and the pin: the pending findings move to You answered
        self.send_changes(a, "1 pending comment, 1 comment on findings, 1 request for more details")
        p = self.panel(a, "open")
        self.assertEqual([(x["item"], x["group"]) for x in p["findings"]],
                         [("t415/retry-4xx", "wait"), ("t412/boundary-tests", "answered"), ("t415/double-auth", "answered"), ("t415/latency", "answered")])
        self.assertEqual(self.browser.errors, [])

    def test_the_panel_opens_on_load_when_something_waits_for_the_reader(self) -> None:
        # the example's docs-stale finding has the agent's reply and nothing from the reader: it waits
        a = self.open(self.url)
        a.ev("document.querySelector('.bd-cs-f [data-f=resolved]').click(); BP.sidebar({open: false})")
        a = self.open(self.url)
        self.assertEqual([a.ev("BP.comments().open"), a.ev("BP.comments().filter")], [True, "open"])
        self.assertEqual(self.panel(a, "open")["findings"], [{"item": "t412/docs-stale", "group": "wait", "status": "open"}])
        # a comment not sent yet: it opens on Pending
        a.ev("BP.setNote('t412/docs-stale', 'Fine as a ticket.'); BP.sidebar({open: false})")
        a = self.open(self.url)
        self.assertEqual([a.ev("BP.comments().open"), a.ev("BP.comments().filter")], [True, "pending"])
        # sent, nothing waits: it stays as the reader left it, closed
        self.send_changes(a, "1 comment on findings")
        a.ev("BP.sidebar({open: false})")
        a = self.open(self.url)
        self.assertFalse(a.ev("BP.comments().open"))
        self.assertEqual(self.browser.errors, [])

    def test_a_card_click_opens_the_finding_scrolls_to_it_and_rings_it(self) -> None:
        a = self.open(self.url)
        a.ev("scrollTo(0, 0)")
        a.wait_for(f"!!{self.card('t412/docs-stale')}")
        a.ev(f"{self.card('t412/docs-stale')}.click()")
        ring = "document.querySelector('.bd-ring')"
        a.wait_for(f"!!{ring}")
        self.assertTrue(a.ev(f"{ring}.matches('.bd-mrow[data-item=\"t412/docs-stale\"], #item-t412-docs-stale')"))
        a.wait_for(f"(r => r.top >= 0 && r.bottom <= innerHeight)({ring}.getBoundingClientRect())")
        a.wait_for(f"!{ring}", timeout=4)
        self.assertEqual(self.browser.errors, [])


GH_STUB = """#!/bin/sh
printf '%s\\n' "$@" > "$GH_ARGS"
[ -n "$GH_FAIL" ] && { echo "gh: no network" >&2; exit 1; }
printf '%s\\n' '{"baseRefName":"main","headRefName":"fix/payco-retry-reuses-the-idempotency-key"}'
"""


class GitdiffBranchNames(unittest.TestCase):
    """`gitdiff.py --pr` asks `gh pr view <n> --repo <owner/repo> --json headRefName,baseRefName` (recorded output from a
    stub on PATH) and stores headRef and baseRef; gh failing leaves them out with a warning."""

    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="bluedoc-gitdiff-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.repo = self.dir / "acme-shop"
        self.repo.mkdir()
        git = ["git", "-C", str(self.repo), "-c", "user.name=Acme", "-c", "user.email=dev@acme.test", "-c", "core.hooksPath=/dev/null"]
        subprocess.run([*git, "init", "-q"], check=True)
        for n, text in enumerate(("export const RETRIES = 3;\n", "export const RETRIES = 3;\nexport const KEY = 'reuse';\n")):
            (self.repo / "retry.ts").write_text(text, encoding="utf-8")
            subprocess.run([*git, "add", "-A"], check=True)
            subprocess.run([*git, "commit", "-q", "-m", f"c{n}"], check=True)
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text(GH_STUB, encoding="utf-8")
        (bin_dir / "gh").chmod(0o755)
        self.args = self.dir / "gh-args"
        self.env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GH_ARGS": str(self.args), "PYTHONDONTWRITEBYTECODE": "1"}

    def gitdiff(self, *extra: str, fail: bool = False) -> subprocess.CompletedProcess:
        env = {**self.env, **({"GH_FAIL": "1"} if fail else {})}
        return subprocess.run([sys.executable, str(SCRIPTS / "gitdiff.py"), "--repo", str(self.repo), "--base", "HEAD~1", "--head", "HEAD",
                               "--id", "diff-415", "--title", "acme-shop #415", *extra], env=env, capture_output=True, text=True)

    def test_pr_stores_the_branch_names_gh_reports(self) -> None:
        r = self.gitdiff("--pr", "acme/acme-shop#415")
        self.assertEqual(r.returncode, 0, r.stderr)
        block = json.loads(r.stdout)
        self.assertEqual((block["headRef"], block["baseRef"]), ("fix/payco-retry-reuses-the-idempotency-key", "main"))
        self.assertEqual(self.args.read_text().split("\n")[:-1], ["pr", "view", "415", "--repo", "acme/acme-shop", "--json", "headRefName,baseRefName"])
        r = self.gitdiff("--pr", "https://github.com/acme/acme-shop/pull/415", "--embed")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["headRef"], "fix/payco-retry-reuses-the-idempotency-key")

    def test_without_pr_gh_is_not_asked_and_a_failing_gh_only_warns(self) -> None:
        r = self.gitdiff()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("headRef", json.loads(r.stdout))
        self.assertFalse(self.args.exists())
        r = self.gitdiff("--pr", "acme/acme-shop#415", fail=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse({"headRef", "baseRef"} & set(json.loads(r.stdout)))
        self.assertIn("WARNING: gh pr view acme/acme-shop#415 gave no branch names", r.stderr)


class BuildBranchNames(unittest.TestCase):
    """The example's diff blocks name their branches; the build takes a branch name and refuses anything else."""

    def test_the_example_names_both_prs_branches(self) -> None:
        doc = load_json(EXAMPLES / REVIEW)
        diffs = {b["id"]: (b.get("headRef"), b.get("baseRef")) for s in doc["sections"] for b in s.get("blocks", []) if b["type"] == "diff"}
        self.assertEqual(diffs, {"diff-412": ("bulk-discount-tiers", "main"), "diff-415": ("fix/payco-retry-reuses-the-idempotency-key", "main")})
        rep = build.validate(doc, EXAMPLES / REVIEW, write_cache=False)
        self.assertEqual(rep.errors, [])

    def test_a_bad_branch_name_is_an_error(self) -> None:
        doc = load_json(EXAMPLES / REVIEW)
        sec = next(s for s in doc["sections"] if s["id"] == "pr-412")
        for value in ("", "has space", "x" * 256, 412):
            with self.subTest(value=value):
                sec["blocks"][1]["headRef"] = value
                errors = build.validate(doc, EXAMPLES / REVIEW, write_cache=False).errors
                self.assertTrue([e for e in errors if "headRef" in e], errors)


if __name__ == "__main__":
    unittest.main()
