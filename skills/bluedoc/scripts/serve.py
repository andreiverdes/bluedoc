#!/usr/bin/env python3
"""Serve bluedoc pages on localhost so the reader can send answers back to the agent.

Usage:
  serve.py DOC.html|FOLDER [--port N] [--to NAME] [--once] [--open]

Prints the page URL, then waits. When the reader presses Send in the page, the reply is
printed to stdout as Markdown and saved next to the page:
  <doc>.reply.md    the same Markdown as Copy progress (picks, ticks, comments, message)
  <doc>.reply.json  {"doc", "title", "path", "at", "message", "items": [{checklist, item, text,
                     choice, recommend | done, note?}], "markdown"}
Each Send overwrites both files. --once exits after the first reply, so an agent can run
this in the background and treat the exit as "the reader answered".

Binds 127.0.0.1 only. POST needs the X-Bluedoc header (pages from other origins cannot send
it without a CORS preflight, which this server never grants). Python 3.9+ standard library only.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

MAX_BODY = 4 * 1024 * 1024


def reply_target(root: Path, page_path: str, doc_id: str) -> Path:
    """The page the reply came from, resolved inside root; falls back to <root>/<doc id>."""
    rel = unquote(urlsplit(page_path or '').path).lstrip('/')
    page = (root / rel).resolve() if rel else None
    if page and page.is_file() and page.suffix == '.html' and root in page.parents:
        return page.with_suffix('')
    safe = ''.join(ch if ch.isalnum() or ch in '-_.' else '-' for ch in doc_id) or 'bluedoc'
    return root / safe


def make_handler(root: Path, to: str, on_reply):
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):  # keep stdout for replies only
            pass

        def end_headers(self):
            self.send_header('Cache-Control', 'no-store')
            super().end_headers()

        def _json(self, code: int, obj) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if urlsplit(self.path).path == '/__bluedoc/ping':
                return self._json(200, {'bluedoc': True, 'to': to})
            return super().do_GET()

        def do_POST(self):
            if urlsplit(self.path).path != '/__bluedoc/reply':
                return self._json(404, {'error': 'not found'})
            if self.headers.get('X-Bluedoc') != '1':
                return self._json(403, {'error': 'missing X-Bluedoc header'})
            origin = self.headers.get('Origin')
            if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                return self._json(403, {'error': 'cross-origin'})
            n = int(self.headers.get('Content-Length') or 0)
            if not 0 < n <= MAX_BODY:
                return self._json(413, {'error': 'empty or too large'})
            try:
                data = json.loads(self.rfile.read(n))
                if not isinstance(data, dict) or not isinstance(data.get('items'), list):
                    raise ValueError('not a bluedoc reply')
            except ValueError as e:
                return self._json(400, {'error': str(e)})
            base = reply_target(root, str(data.get('path') or ''), str(data.get('doc') or ''))
            md_path, json_path = base.with_name(base.name + '.reply.md'), base.with_name(base.name + '.reply.json')
            md = str(data.get('markdown') or '').rstrip() + '\n'
            md_path.write_text(md, encoding='utf-8')
            json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            self._json(200, {'ok': True, 'saved': str(json_path)})
            on_reply(md, md_path, json_path)

    return Handler


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('target', help='a built bluedoc .html file, or a folder of them')
    ap.add_argument('--port', type=int, default=0, help='port on 127.0.0.1 (default: any free port)')
    ap.add_argument('--to', default='', help='who receives the reply, shown in the page (e.g. the agent name)')
    ap.add_argument('--once', action='store_true', help='exit after the first reply')
    ap.add_argument('--open', action='store_true', help='open the page in the default browser')
    a = ap.parse_args()

    target = Path(a.target).resolve()
    if not target.exists():
        print(f'error: {a.target} not found', file=sys.stderr)
        return 2
    root = target if target.is_dir() else target.parent
    page = '' if target.is_dir() else target.name

    srv: ThreadingHTTPServer

    def on_reply(md: str, md_path: Path, json_path: Path) -> None:
        print(f'--- bluedoc reply ({md_path.name}, {json_path.name}) ---', flush=True)
        print(md, end='', flush=True)
        print('--- end reply ---', flush=True)
        if a.once:
            threading.Thread(target=srv.shutdown, daemon=True).start()

    handler = partial(make_handler(root, a.to, on_reply), directory=str(root))
    srv = ThreadingHTTPServer(('127.0.0.1', a.port), handler)
    url = f'http://127.0.0.1:{srv.server_address[1]}/{page}'
    print(f'serving {url}', flush=True)
    if a.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
