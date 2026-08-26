"""Minimal local AIPP operator panel.

Binds to loopback only and delegates commands to the existing runner.
It does not own AIPP state or bypass Authority Gate.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PANEL = Path(__file__).resolve().parent
ALLOWED = {"BAŞLA", "EXECUTE", "VERIFY"}

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload, content_type="application/json"):
        body = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/status":
            self._send(200, json.dumps({"service":"AIPP Control Panel","runner":"available","authority":"AIPP_CORE"}))
            return
        if self.path in ("/", "/index.html"):
            self._send(200, (PANEL / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        self._send(404, json.dumps({"error":"not found"}))

    def do_POST(self):
        if self.path != "/api/command":
            self._send(404, json.dumps({"error":"not found"}))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
            command = str(data.get("command", "")).upper()
            if command not in ALLOWED:
                raise ValueError("Command is not permitted by the control panel")
            proc = subprocess.run(
                [sys.executable, str(ROOT / "aipp_runner.py"), command, "--workspace", str(ROOT)],
                cwd=ROOT, capture_output=True, text=True, timeout=120,
            )
            self._send(200 if proc.returncode == 0 else 409, json.dumps({"command":command,"returncode":proc.returncode,"stdout":proc.stdout,"stderr":proc.stderr}))
        except Exception as exc:
            self._send(400, json.dumps({"error":str(exc)}))

if __name__ == "__main__":
    print("AIPP Control Panel: http://127.0.0.1:8787")
    ThreadingHTTPServer(("127.0.0.1", 8787), Handler).serve_forever()
