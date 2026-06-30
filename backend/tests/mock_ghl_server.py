"""Tiny one-shot HTTP server that echoes the GHL push payload to a JSON
file. Used in regression tests to verify the outbound integration without
hitting Charity's real GHL workspace.

Run with: `python3 backend/tests/mock_ghl_server.py 9988 /tmp/ghl_last.json`
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class _Echo(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            data = json.loads(raw)
        except Exception:
            data = {"_raw": raw}
        with open(sys.argv[2], "w") as f:
            json.dump({"headers": dict(self.headers), "body": data}, f, indent=2)
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, *a, **k):  # silence default stderr logs
        return


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), _Echo).serve_forever()
