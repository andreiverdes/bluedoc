"""Server guards: `serve.py run` on a free port with a temp BLUEDOC_HOME; the probes the review ran with curl.

Path traversal is 404, a foreign or empty Host is 403, a POST without X-Bluedoc or from another origin is 403,
a preflight is 501, GET /__bluedoc/wait without X-Bluedoc is 403 and leaves the reply for the agent, and a
Content-Length or wait timeout that isn't a finite number 0 or more is 400 at once, with no traceback."""
from __future__ import annotations

import json
import shutil
import time
import unittest
from urllib.parse import quote

from _support import Server, TempHome


class ServerGuards(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.docs = self.tmp.copy_examples()
        self.doc = self.docs / "acme-saved-carts-plan.bluedoc.json"
        # a doc outside the registered folder: what a traversal would try to reach
        self.secret = self.tmp.dir / "secret.bluedoc.json"
        shutil.copy(self.docs / "acme-orders.bluedoc.json", self.secret)
        r = self.tmp.run("serve.py", "add", self.docs)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.server = Server(self.tmp)
        self.server.start()
        self.port, self.host, self.req = self.server.port, self.server.host, self.server.req
        self.url = self.server.url_for(self.doc)
        self.assertTrue(self.url and self.url.endswith("/acme-saved-carts-plan.bluedoc.json"), self.url)
        self.slug = self.url.split("/")[1]

    def tearDown(self) -> None:
        self.server.stop()
        self.tmp.cleanup()

    def test_doc_renders(self) -> None:
        self.assertEqual(self.req("GET", self.url)[0], 200)

    def test_path_traversal_is_404(self) -> None:
        s = self.slug
        paths = [f"/{s}/../secret.bluedoc.json", f"/{s}/%2e%2e/secret.bluedoc.json", f"/{s}/..%2fsecret.bluedoc.json",
                 f"/{s}/%2e%2e%2fsecret.bluedoc.json?raw=1", f"/{s}/../home/roots.json",
                 "/__bluedoc/vendor/../../scripts/serve.py", "/__bluedoc/vendor/%2e%2e/%2e%2e/scripts/serve.py",
                 "/__bluedoc/vendor/..%2f..%2fscripts%2fserve.py"]
        for p in paths:
            with self.subTest(path=p):
                status, body = self.req("GET", p)
                self.assertEqual(status, 404, body[:200])

    def test_host_header(self) -> None:
        for host, want in ((f"evil.com:{self.port}", 403), ("", 403), (f"localhost:{self.port}", 200)):
            with self.subTest(host=host):
                self.assertEqual(self.req("GET", "/", headers={"Host": host})[0], want)

    def changes(self) -> bytes:
        return json.dumps({"path": self.url, "rev": "1", "annotations": [], "message": "Acme test",
                           "markdown": "# Change requests: Acme test\n"}).encode()

    def test_cross_site_posts_are_refused(self) -> None:
        own = f"http://{self.host}"
        for name, headers, want in (("no header", {}, 403),
                                    ("foreign origin", {"X-Bluedoc": "1", "Origin": "http://evil.com"}, 403),
                                    ("null origin", {"X-Bluedoc": "1", "Origin": "null"}, 403)):
            with self.subTest(name):
                status, _ = self.req("POST", "/__bluedoc/changes", self.changes(), {"Content-Type": "application/json", **headers})
                self.assertEqual(status, want)
        self.assertEqual(self.req("OPTIONS", "/__bluedoc/changes", headers={"Origin": "http://evil.com",
                                  "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-bluedoc"})[0], 501)
        wait = f"/__bluedoc/wait?doc={quote(str(self.doc))}&kind=any&timeout=0"
        self.assertEqual(self.req("GET", wait, headers={"X-Bluedoc": "1"})[0], 204, "a refused POST stored a reply")
        status, _ = self.req("POST", "/__bluedoc/changes", self.changes(), {"Content-Type": "application/json", "X-Bluedoc": "1", "Origin": own})
        self.assertEqual(status, 200)

    def test_wait_needs_the_header_and_keeps_the_reply(self) -> None:
        status, _ = self.req("POST", "/__bluedoc/changes", self.changes(), {"Content-Type": "application/json", "X-Bluedoc": "1"})
        self.assertEqual(status, 200)
        wait = f"/__bluedoc/wait?doc={quote(str(self.doc))}&kind=any&timeout=1"
        self.assertEqual(self.req("GET", wait)[0], 403)
        status, body = self.req("GET", wait, headers={"X-Bluedoc": "1"})
        self.assertEqual(status, 200, "the refused wait consumed the reply")
        self.assertEqual(json.loads(body)["message"]["kind"], "changes")

    def test_bad_numbers_are_400(self) -> None:
        own = f"http://{self.host}"
        status, _ = self.req("PUT", "/__bluedoc/state", b"{}", {"Content-Type": "application/json", "X-Bluedoc": "1",
                                                                "Origin": own, "Content-Length": "abc"})
        self.assertEqual(status, 400, "Content-Length: abc")
        for timeout in ("abc", "nan", "inf", "-1"):
            with self.subTest(timeout=timeout):
                t0 = time.monotonic()
                status, _ = self.req("GET", f"/__bluedoc/wait?doc={quote(str(self.doc))}&kind=any&timeout={timeout}",
                                     headers={"X-Bluedoc": "1"})
                self.assertEqual(status, 400)
                self.assertLess(time.monotonic() - t0, 2, "a bad timeout held the connection")
        self.assertNotIn("Traceback", (self.tmp.dir / "server.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
