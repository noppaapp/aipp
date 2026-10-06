"""Acceptance tests for runtime_service against an in-memory Drive."""
import base64
import shutil
from pathlib import Path

import pytest

import runtime_service
from tests.fakes.fake_drive import FakeDrive

ROOT = Path(runtime_service.__file__).resolve().parent
ARTIFACT = ROOT / "artifacts" / "TASK-10-execution.json"

BOOT = (
    "# PROJECT_BOOT: Demo\n\n"
    "**Workspace Status:** ACTIVE\n"
    "**Active State:** [READY]\n\n"
    "| Task ID | Task Description | Status | Dependency / Reason |\n"
    "| :--- | :--- | :--- | :--- |\n"
    "| **TASK-10** | Fix docs typo | **FUTURE** | - |\n"
)

@pytest.fixture
def service(tmp_path, monkeypatch):
    drive = FakeDrive().install(monkeypatch)
    drive.add("PROJECT_BOOT.md", BOOT)
    sub = drive.folder("proje-a")
    drive.add("notlar.md", "# Notlar\nBu bir referans notudur.\n", parent=sub)
    monkeypatch.delenv("AIPP_RUNTIME_TOKEN", raising=False)
    monkeypatch.delenv("AIPP_AUTHORITY_PUBKEY", raising=False)
    monkeypatch.setattr(runtime_service, "SESSION_STATE_PATH", tmp_path / "session.json")
    monkeypatch.setattr(runtime_service, "analyze_with_ai",
                        lambda docs: {"enabled": False, "available": False, "proposals": [], "findings": []})
    had_artifacts = (ROOT / "artifacts").exists()
    client = runtime_service.app.test_client()
    try:
        yield client, drive
    finally:
        ARTIFACT.unlink(missing_ok=True)
        if not had_artifacts:
            shutil.rmtree(ROOT / "artifacts", ignore_errors=True)

def call(client, command, task=None):
    body = {"command": command}
    if task:
        body["task"] = task
    response = client.post("/api/run", json=body)
    return response.status_code, response.get_json()

def test_full_cycle_against_fake_drive(service):
    client, drive = service
    code, data = call(client, "BAŞLA")
    assert code == 200, data
    state = data["result"]
    assert state["active_project"] == "Demo"
    assert "TASK-10" in [t["id"] for t in state["task_lifecycle"]["FUTURE"]]
    assert state["project_intelligence"]["documents_scanned"] >= 2
    code, data = call(client, "REQUEST_APPROVAL", "TASK-10")
    assert code == 200, data
    assert data["result"]["status"] == "AWAITING_AUTHORITY"
    code, data = call(client, "APPROVE", "TASK-10")
    assert code == 200, data
    assert data["result"]["status"] == "NOW"
    assert "| APPROVED |" in drive.text("AUTHORITY_LOG.md")
    code, data = call(client, "EXECUTE_APPROVED", "TASK-10")
    assert code == 200, data
    assert data["result"]["status"] == "EXECUTED"
    code, data = call(client, "VERIFY", "TASK-10")
    assert code == 200, data
    assert [t["id"] for t in data["result"]["task_lifecycle"]["COMPLETED"]] == ["TASK-10"]
    persisted = client.get("/api/status").get_json()
    assert persisted["ok"] and persisted["task_lifecycle"]["NOW"] is None
    assert drive.text("AIPP_SESSION_STATE.json")

def test_signed_approval_requires_external_human_row(service, monkeypatch):
    client, drive = service
    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv("AIPP_AUTHORITY_PUBKEY", base64.b64encode(
        key.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)).decode())
    monkeypatch.setenv("AIPP_APPROVER_PRIVATE_KEY", base64.b64encode(
        key.private_bytes(ser.Encoding.Raw, ser.PrivateFormat.Raw, ser.NoEncryption())).decode())
    assert call(client, "BAŞLA")[0] == 200
    code, data = call(client, "REQUEST_APPROVAL", "TASK-10")
    assert code == 200, data
    pid = data["result"]["authority_gate"]["pending_proposal_id"]
    code, data = call(client, "APPROVE", "TASK-10")
    assert code != 200
    assert drive.text("AUTHORITY_LOG.md") is None
    assert drive.writes_to("AUTHORITY_LOG.md") == []
    import aipp_sign_approval as signer
    drive.add("AUTHORITY_LOG.md", "# AUTHORITY_LOG\n\n" + signer.sign(pid, "TASK-10", "APPROVED", "alice") + "\n")
    code, data = call(client, "APPROVE", "TASK-10")
    assert code == 200, data
    assert data["result"]["status"] == "NOW"
