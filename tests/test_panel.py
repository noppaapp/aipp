import base64
import json
import os
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import panel.server as panel_server

from aipp_authority import proposal_id

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


def test_panel_continue_uses_canonical_authority_and_core_loop(monkeypatch, tmp_path):
    monkeypatch.setattr(panel_server, "ROOT", tmp_path)
    monkeypatch.setattr(panel_server, "SESSION", panel_server.default_state())
    (tmp_path / "AIPP.md").write_text("# test\n", encoding="utf-8")
    (tmp_path / "PROJECT_BOOT.md").write_text(
        "# PROJECT_BOOT: AIPP\n\n"
        "**Workspace Status:** ACTIVE\n"
        "**Active State:** [READY]\n\n"
        "| Task ID | Task Description | Status | Dependency / Reason |\n"
        "| :--- | :--- | :--- | :--- |\n"
        "| **TASK-01** | `Panel continuation proof` | `FUTURE` | - |\n",
        encoding="utf-8",
    )
    task = {"id": "TASK-01", "title": "Panel continuation proof", "status": "FUTURE", "dependency_reason": "-"}
    approval = (
        "| Proposal ID | Task ID | Decision | Timestamp |\n"
        "| :--- | :--- | :--- | :--- |\n"
        f"| {proposal_id(task)} | TASK-01 | APPROVED | 2026-08-27T00:00:00Z |\n"
    )
    previous = os.environ.get("AIPP_AUTHORITY_LOG_B64")
    os.environ["AIPP_AUTHORITY_LOG_B64"] = base64.b64encode(approval.encode("utf-8")).decode("ascii")

    server = ThreadingHTTPServer(("127.0.0.1", 0), panel_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        state = post(server, {"command": "CONTINUE", "task": "TASK-01"})
        assert state["status"] == "COMPLETED"
        assert state["authority_gate"]["last_action"] == "VERIFIED"
        assert state["task_lifecycle"]["COMPLETED"][0]["id"] == "TASK-01"
        assert (tmp_path / "artifacts" / "TASK-01-execution.json").exists()
        assert not (tmp_path / "aipp_state.json").exists()
    finally:
        server.shutdown()
        server.server_close()
        if previous is None:
            os.environ.pop("AIPP_AUTHORITY_LOG_B64", None)
        else:
            os.environ["AIPP_AUTHORITY_LOG_B64"] = previous
