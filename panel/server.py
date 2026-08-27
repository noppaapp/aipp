"""Minimal local AIPP operator panel.

The panel is a thin operator surface. Session state is held only in this
process and is never written to disk. Authority remains owned by AIPP Core.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import threading

ROOT = Path(__file__).resolve().parents[1]
PANEL = Path(__file__).resolve().parent

from aipp_runner import initialize_state, request_approval, approve_task, execute_task, verify_task, continue_execution, default_state

SESSION = default_state()
LOCK = threading.Lock()


def public_state():
    state = json.loads(json.dumps(SESSION, ensure_ascii=False))
    return state


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
            with LOCK:
                self._send(200, json.dumps(public_state(), ensure_ascii=False))
            return
        if self.path in ("/", "/index.html"):
            self._send(200, (PANEL / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path != "/api/command":
            self._send(404, json.dumps({"error": "not found"}))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
            command = str(data.get("command", "")).upper()
            task_id = data.get("task")
            global SESSION
            with LOCK:
                if command == "BAŞLA":
                    SESSION = initialize_state(SESSION, str(ROOT))
                elif command == "REQUEST_APPROVAL":
                    if not task_id:
                        raise ValueError("task is required")
                    SESSION = request_approval(SESSION, task_id)
                elif command == "APPROVE":
                    if not task_id:
                        raise ValueError("task is required")
                    SESSION = approve_task(SESSION, task_id)
                elif command == "EXECUTE":
                    SESSION = execute_task(SESSION, str(ROOT))
                elif command == "VERIFY":
                    SESSION = verify_task(SESSION, str(ROOT))
                elif command == "CONTINUE":
                    if not task_id:
                        raise ValueError("task is required")
                    SESSION = initialize_state(SESSION, str(ROOT))
                    SESSION = request_approval(SESSION, task_id)
                    SESSION = approve_task(SESSION, task_id)
                    SESSION = continue_execution(SESSION, str(ROOT))
                else:
                    raise ValueError("Unsupported panel command")
                self._send(200, json.dumps(public_state(), ensure_ascii=False))
        except Exception as exc:
            self._send(409, json.dumps({"error": str(exc)}, ensure_ascii=False))


if __name__ == "__main__":
    print("AIPP Control Panel: http://127.0.0.1:8787")
    ThreadingHTTPServer(("127.0.0.1", 8787), Handler).serve_forever()
