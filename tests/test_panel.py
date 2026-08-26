import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import panel.server as panel_server

ROOT = Path(__file__).resolve().parents[1]


def post(server, payload):
    url = f"http://127.0.0.1:{server.server_port}/api/command"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def test_panel_delegates_to_aipp_core_without_disk_state(monkeypatch, tmp_path):
    monkeypatch.setattr(panel_server, "ROOT", tmp_path)
    monkeypatch.setattr(panel_server, "SESSION", panel_server.default_state())
    (tmp_path / "AIPP.md").write_text("# test\n", encoding="utf-8")
    (tmp_path / "PROJECT_BOOT.md").write_text(
        "# PROJECT_BOOT: AIPP\n\n"
        "**Workspace Status:** ACTIVE\n"
        "**Active State:** [READY]\n\n"
        "| Task ID | Task Description | Status | Dependency / Reason |\n"
        "| :--- | :--- | :--- | :--- |\n"
        "| **TASK-01** | `Panel execution proof` | `FUTURE` | - |\n",
        encoding="utf-8",
    )

    server = ThreadingHTTPServer(("127.0.0.1", 0), panel_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        state = post(server, {"command": "BAŞLA"})
        assert state["active_project"] == "AIPP"
        assert state["status"] == "PROPOSAL_READY"
        assert state["task_lifecycle"]["FUTURE"][0]["id"] == "TASK-01"
        assert not (tmp_path / "aipp_state.json").exists()
    finally:
        server.shutdown()
        server.server_close()
