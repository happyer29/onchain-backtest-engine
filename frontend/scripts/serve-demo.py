"""Serve only the built static demo under its GitHub project path on loopback."""

import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "demo-dist"
PREFIX = "/onchain-backtest-engine/"


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(302)
            self.send_header("Location", PREFIX)
            self.end_headers()
            return
        if not self.path.startswith(PREFIX):
            self.send_error(404)
            return
        self.path = "/" + self.path[len(PREFIX) :]
        super().do_GET()

    def do_POST(self):
        self.send_error(405, "Static demo is read only")

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    if not (ROOT / "distribution.json").is_file():
        raise SystemExit("Build the verified demo before serving it.")
    port = int(os.environ.get("BACKTEST_DEMO_PORT", "18744"))
    print(f"Static demo: http://127.0.0.1:{port}{PREFIX}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(ROOT))).serve_forever()
