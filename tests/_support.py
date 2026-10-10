"""Shared paths and helpers for the bluedoc tests (stdlib only)."""
from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

sys.dont_write_bytecode = True   # importing the scripts must not write __pycache__ into the skill folder

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skills" / "bluedoc"
SCRIPTS = SKILL / "scripts"
EXAMPLES = SKILL / "examples"
TEMPLATE = SKILL / "assets" / "template.html"
EXPORTS = REPO / "docs" / "examples"
EXAMPLE_STEMS = ("acme-orders", "acme-review-findings", "acme-saved-carts-plan")

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


class TempHome:
    """A temp dir with a copy of the examples and its own BLUEDOC_HOME, for one test."""

    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="bluedoc-test-")).resolve()
        self.home = self.dir / "home"
        self.home.mkdir()
        self.env = {**os.environ, "BLUEDOC_HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"}
        self.env.pop("BLUEDOC_PORT", None)

    def copy_examples(self, dest: str = "docs") -> Path:
        out = self.dir / dest
        shutil.copytree(EXAMPLES, out)
        return out

    def run(self, script: str, *args: str, timeout: float = 30) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], env=self.env, cwd=self.dir,
                              capture_output=True, text=True, timeout=timeout)

    def cleanup(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """`serve.py run` on a free port with tmp's BLUEDOC_HOME; start() again after stop() is a restart."""

    def __init__(self, tmp: TempHome) -> None:
        self.tmp, self.port = tmp, free_port()
        self.host = f"127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.log = open(self.tmp.dir / "server.log", "a")
        self.proc = subprocess.Popen([sys.executable, str(SCRIPTS / "serve.py"), "run", "--port", str(self.port)],
                                     env=self.tmp.env, cwd=self.tmp.dir, stdout=self.log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL)
        deadline = time.monotonic() + 10
        while True:
            try:
                if self.req("GET", "/__bluedoc/ping", headers={"X-Bluedoc": "1"})[0] == 200:
                    return
            except OSError:
                pass
            if self.proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(f"server did not start: {(self.tmp.dir / 'server.log').read_text()}")
            time.sleep(0.05)

    def stop(self) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.proc = None
        self.log.close()

    def req(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None) -> tuple[int, bytes]:
        """One request, path sent as is (no normalisation); Host defaults to the server's own."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            c.request(method, path, body=body, headers={"Host": self.host, **(headers or {})})
            r = c.getresponse()
            return r.status, r.read()
        finally:
            c.close()

    def url_for(self, doc: Path) -> str:
        return json.loads(self.req("GET", f"/__bluedoc/url?doc={quote(str(doc))}", headers={"X-Bluedoc": "1"})[1])["url"]


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def template_text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def template_slice(start_marker: str, end_marker: str) -> str:
    """The template source between two marker strings (start included, end excluded)."""
    t = template_text()
    i = t.index(start_marker)
    return t[i:t.index(end_marker, i)]
