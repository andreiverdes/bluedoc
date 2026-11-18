"""gistbudget.py, the gist update budget, against a fake clock: at most 90 updates an hour per GitHub account (one log
for every doc shared as it), at most one a minute per doc, GitHub's retry time honoured, a pause after 4 refusals in a
row until resume. The log ($BLUEDOC_HOME/gist-budget.json, 0600) is read afresh on every call, so a reload keeps the
count; entries in the future count as now; deletes count but never wait."""
from __future__ import annotations

import json
import os
import stat
import unittest
from unittest import mock

from _support import TempHome

import gistbudget as gb

T0 = 1_800_000_000.0   # the fake clock's start


class Budget(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"BLUEDOC_HOME": str(self.tmp.home)})
        p.start()
        self.addCleanup(p.stop)
        self.now = T0
        c = mock.patch.object(gb, "clock", lambda: self.now)
        c.start()
        self.addCleanup(c.stop)

    def share(self, doc: str, login: str = "acme-dev") -> bool:
        """One Share press: sent when due now, else nothing (the queue would hold it)."""
        at, _ = gb.due(login, doc)
        if at is not None and at <= self.now:
            gb.sent(login, doc)
            return True
        return False

    def test_the_91st_update_in_an_hour_waits_for_the_oldest_to_leave_it(self) -> None:
        for i in range(90):
            self.now = T0 + i * 30   # 90 docs, one every 30 s
            self.assertTrue(self.share(f"doc{i}"))
        self.now = T0 + 2700
        at, why = gb.due("acme-dev", "another")
        self.assertEqual((at, why), (T0 + 3600, "hour"), "the oldest update leaves the hour at T0 + 60 min")
        self.assertEqual(gb.status("acme-dev")["used"], 90)
        self.assertEqual(gb.status("acme-dev")["next"], T0 + 3600)
        self.assertFalse(self.share("another"))
        self.now = T0 + 3600
        self.assertTrue(self.share("another"), "a place freed")
        self.assertEqual(gb.status("acme-dev")["used"], 90, "the first left the hour as the 91st came in")

    def test_five_shares_in_a_minute_send_one_and_the_doc_waits_a_minute(self) -> None:
        sent = []
        for i in range(5):
            self.now = T0 + i * 10
            sent.append(self.share("plan"))
        self.assertEqual(sent, [True, False, False, False, False])
        self.assertEqual(gb.due("acme-dev", "plan"), (T0 + 60, "spacing"))
        self.assertEqual(gb.due("acme-dev", "status"), (self.now, None), "another doc goes at once")
        self.now = T0 + 60
        self.assertTrue(self.share("plan"))

    def test_a_reload_keeps_the_count_and_the_file_is_private(self) -> None:
        for i in range(3):
            self.now = T0 + i
            gb.sent("acme-dev", f"d{i}")
        f = gb.budget_file()
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        data = json.loads(f.read_text(encoding="utf-8"))
        self.assertEqual(data["acme-dev"]["sent"], [T0, T0 + 1, T0 + 2])
        self.assertEqual(gb.status("acme-dev")["used"], 3, "read from the file, as a restarted server reads it")
        self.now = T0 + 3601
        gb.sent("acme-dev", "d9")
        self.assertEqual(json.loads(f.read_text(encoding="utf-8"))["acme-dev"]["sent"], [T0 + 2, T0 + 3601], "older than an hour: dropped")

    def test_two_docs_on_one_account_share_its_hour_and_accounts_are_apart(self) -> None:
        for i in range(45):
            self.now = T0 + i
            gb.sent("acme-dev", "plan" if i % 2 else "status")
            gb.sent("Acme-Dev", "design")   # GitHub ignores case
        self.assertEqual(gb.status("acme-dev")["used"], 90)
        self.assertEqual(gb.due("acme-dev", "fourth")[1], "hour")
        self.assertEqual(gb.due("acme-work", "fourth"), (self.now, None), "another account has its own hour")

    def test_a_future_entry_counts_as_now(self) -> None:
        gb.sent("acme-dev", "plan", now=T0 + 500)   # the clock jumped back since
        self.assertEqual(gb.due("acme-dev", "plan"), (T0 + 60, "spacing"))

    def test_refusals_back_off_then_pause_until_resume(self) -> None:
        e = gb.refused("acme-dev", {"Retry-After": "300"})
        self.assertEqual((e["retryAt"], e["refusals"], e["paused"]), (T0 + 300, 1, False))
        self.assertEqual(gb.due("acme-dev", "plan"), (T0 + 300, "retry"))
        e = gb.refused("acme-dev", {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(T0 + 900))})
        self.assertEqual(e["retryAt"], T0 + 900)
        gb.resume("acme-dev")
        self.assertEqual([gb.refused("acme-dev")["retryAt"] - T0 for _ in range(3)], [60, 120, 240], "no header: 1, 2, 4 min")
        e = gb.refused("acme-dev")
        self.assertTrue(e["paused"], "the 4th in a row pauses")
        self.assertEqual(gb.due("acme-dev", "plan"), (None, "paused"))
        self.now = T0 + 10_000
        self.assertEqual(gb.due("acme-dev", "plan"), (None, "paused"), "a pause outlasts the retry time")
        gb.resume("acme-dev")
        self.assertEqual(gb.due("acme-dev", "plan"), (self.now, None))
        self.assertEqual(gb.status("acme-dev")["refusals"], 0)
        gb.refused("acme-dev")
        gb.sent("acme-dev", "plan", now=self.now + 60)
        self.assertEqual(gb.status("acme-dev", now=self.now + 60)["refusals"], 0, "a write GitHub takes ends the run")

    def test_the_backoff_doubles_to_an_hour(self) -> None:
        self.assertEqual([gb.wait_of(None, n, T0) for n in (1, 2, 3, 4, 7, 9)], [60, 120, 240, 480, 3600, 3600])

    def test_which_refusals_are_rate_limits(self) -> None:
        self.assertTrue(gb.rate_limited(429, {"retry-after": "60"}))
        self.assertTrue(gb.rate_limited(403, {"X-RateLimit-Remaining": "0"}))
        self.assertTrue(gb.rate_limited(403, {}, '{"message": "You have exceeded a secondary rate limit"}'))
        self.assertFalse(gb.rate_limited(403, {"x-ratelimit-remaining": "4000"}, '{"message": "Resource not accessible by integration"}'))
        self.assertFalse(gb.rate_limited(404, {"retry-after": "60"}))

    def test_a_delete_counts_and_never_waits(self) -> None:
        for i in range(90):
            gb.sent("acme-dev", f"d{i}", now=T0 + i)
        self.now = T0 + 100
        gb.deleted("acme-dev")
        self.assertEqual(gb.status("acme-dev")["used"], 91, "logged: the hour is past the budget")
        self.assertEqual(gb.due("acme-dev", "x")[0], T0 + 3601, "the next update waits for two to leave")


if __name__ == "__main__":
    unittest.main()
