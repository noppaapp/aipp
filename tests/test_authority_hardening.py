import base64

import pytest

import aipp_runner
from aipp_authority import binding_digest, is_approved, is_completion_approved, proposal_id
import aipp_sign_approval as signer


def gh_task(content="hello"):
    return {
        "id": "GH-001", "title": "Add file", "status": "FUTURE", "dependency_reason": "-",
        "description": "PR body", "external_action": "GITHUB_TARGET_TEXT_FILE",
        "target_path": "docs/a.txt", "target_content": content,
    }


def row(pid, task_id, decision="APPROVED"):
    return (
        "| Proposal ID | Task ID | Decision | Timestamp | Note |\n"
        "| :--- | :--- | :--- | :--- | :--- |\n"
        f"| {pid} | {task_id} | {decision} | 2026-10-06T00:00:00Z | human |\n"
    )


def state_with(task):
    state = aipp_runner.default_state()
    state["task_lifecycle"]["FUTURE"].append(task)
    return state


def keypair(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    priv = base64.b64encode(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())).decode()
    pub = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    monkeypatch.setenv("AIPP_APPROVER_PRIVATE_KEY", priv)
    return pub


def test_proposal_id_binds_execution_payload():
    base = proposal_id(gh_task())
    assert base != proposal_id(gh_task(content="changed"))
    other = gh_task()
    other["target_path"] = ".github/workflows/ci.yml"
    assert base != proposal_id(other)


def test_legacy_tasks_keep_legacy_id():
    legacy = {"id": "TASK-01", "title": "x", "status": "FUTURE", "dependency_reason": "-"}
    assert proposal_id(legacy) == proposal_id(dict(legacy, unrelated="ignored"))


def test_changed_payload_cannot_use_old_approval():
    original = gh_task()
    changed = gh_task(content="malicious")
    assert not is_approved(row(proposal_id(original), "GH-001"), changed)


def test_execute_halts_after_payload_mutation():
    task = gh_task()
    state = state_with(task)
    state = aipp_runner.request_approval(state, "GH-001")
    state = aipp_runner.approve_task(state, "GH-001", row(proposal_id(task), "GH-001"))
    state["task_lifecycle"]["NOW"]["target_content"] = "swapped"
    with pytest.raises(RuntimeError, match="binding digest mismatch"):
        aipp_runner.execute_task(state, ".")


def test_request_approval_never_renames_proposal():
    state = state_with({"id": "INTEL-AAAA", "title": "t", "status": "PROPOSED"})
    with pytest.raises(RuntimeError, match="FUTURE task not found: INTEL-BBBB"):
        aipp_runner.request_approval(state, "INTEL-BBBB")
    assert state["task_lifecycle"]["FUTURE"][0]["id"] == "INTEL-AAAA"


def test_signed_approval_is_verified(monkeypatch):
    pub = keypair(monkeypatch)
    monkeypatch.setenv("AIPP_AUTHORITY_PUBKEY", pub)
    task = gh_task()
    signed = signer.sign(proposal_id(task), "GH-001", "APPROVED", "alice")
    assert is_approved(signed + "\n", task)
    assert not is_approved(row(proposal_id(task), "GH-001"), task)


def test_forged_signature_is_rejected(monkeypatch):
    pub = keypair(monkeypatch)
    monkeypatch.setenv("AIPP_AUTHORITY_PUBKEY", pub)
    task = gh_task()
    keypair(monkeypatch)
    forged = signer.sign(proposal_id(task), "GH-001", "APPROVED", "mallory")
    assert not is_approved(forged + "\n", task)


def test_completion_gate_requires_completed_decision(monkeypatch):
    monkeypatch.setenv("AIPP_REQUIRE_COMPLETION_GATE", "1")
    task = {"id": "T-1", "title": "plain", "status": "FUTURE", "dependency_reason": "-"}
    state = state_with(task)
    state = aipp_runner.request_approval(state, "T-1")
    state = aipp_runner.approve_task(state, "T-1", row(proposal_id(task), "T-1"))
    # No external action: execution produces the local artifact.
    state = aipp_runner.execute_task(state, ".")
    state = aipp_runner.verify_task(state, ".")
    assert state["status"] == "AWAITING_COMPLETION_AUTHORITY"
    pid = state["task_lifecycle"]["NOW"]["proposal_id"]
    with pytest.raises(RuntimeError, match="completion approval not found"):
        aipp_runner.complete_task(state, "T-1", row(pid, "T-1", "APPROVED"))


def test_completion_approval_completes_verified_task(monkeypatch):
    monkeypatch.setenv("AIPP_REQUIRE_COMPLETION_GATE", "1")
    task = {"id": "T-2", "title": "complete", "status": "FUTURE", "dependency_reason": "-"}
    state = state_with(task)
    state = aipp_runner.request_approval(state, "T-2")
    state = aipp_runner.approve_task(state, "T-2", row(proposal_id(task), "T-2"))
    state = aipp_runner.execute_task(state, ".")
    state = aipp_runner.verify_task(state, ".")
    pid = state["task_lifecycle"]["NOW"]["proposal_id"]
    state = aipp_runner.complete_task(state, "T-2", row(pid, "T-2", "COMPLETED"))
    assert state["status"] == "COMPLETED"
    assert state["task_lifecycle"]["NOW"] is None
    assert state["task_lifecycle"]["COMPLETED"][-1]["id"] == "T-2"


def test_completion_approval_cannot_survive_payload_mutation(monkeypatch):
    monkeypatch.setenv("AIPP_REQUIRE_COMPLETION_GATE", "1")
    task = gh_task()
    state = state_with(task)
    state = aipp_runner.request_approval(state, "GH-001")
    state = aipp_runner.approve_task(state, "GH-001", row(proposal_id(task), "GH-001"))
    state = aipp_runner.execute_task(state, ".")
    state = aipp_runner.verify_task(state, ".")
    state["task_lifecycle"]["NOW"]["target_content"] = "changed after verification"
    pid = state["task_lifecycle"]["NOW"]["proposal_id"]
    with pytest.raises(RuntimeError, match="binding digest mismatch"):
        aipp_runner.complete_task(state, "GH-001", row(pid, "GH-001", "COMPLETED"))


def test_signed_completion_approval_is_verified(monkeypatch):
    pub = keypair(monkeypatch)
    monkeypatch.setenv("AIPP_AUTHORITY_PUBKEY", pub)
    task = gh_task()
    task["proposal_id"] = proposal_id(task)
    signed = signer.sign(task["proposal_id"], "GH-001", "COMPLETED", "alice")
    assert is_completion_approved(signed + "\\n", task)
    assert not is_completion_approved(row(task["proposal_id"], "GH-001", "COMPLETED"), task)


def test_forged_signed_completion_is_rejected(monkeypatch):
    pub = keypair(monkeypatch)
    monkeypatch.setenv("AIPP_AUTHORITY_PUBKEY", pub)
    task = gh_task()
    task["proposal_id"] = proposal_id(task)
    keypair(monkeypatch)
    forged = signer.sign(task["proposal_id"], "GH-001", "COMPLETED", "mallory")
    assert not is_completion_approved(forged + "\\n", task)
