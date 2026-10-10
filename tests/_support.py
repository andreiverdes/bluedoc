"""Shared paths and helpers for the bluedoc tests (stdlib only)."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

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


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def template_text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def template_slice(start_marker: str, end_marker: str) -> str:
    """The template source between two marker strings (start included, end excluded)."""
    t = template_text()
    i = t.index(start_marker)
    return t[i:t.index(end_marker, i)]
