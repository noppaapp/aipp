"""Deterministic proposal identity and canonical authority-log parsing.

Hardening (v1.1.2 candidate):
* Proposal identity binds execution payload fields.
* Optional Ed25519 verification makes externally signed authority rows verifiable.
* COMPLETED can be a separate authority-gated decision.
"""

import base64
import hashlib
import json
import os
import re
from pathlib import Path


AUTHORITY_LOG = "AUTHORITY_LOG.md"
AUTHORITY_ENV = "AIPP_AUTHORITY_LOG_B64"
PUBKEY_ENV = "AIPP_AUTHORITY_PUBKEY"
PROPOSAL_PREFIX = "PROP"

DECISION_APPROVED = "APPROVED"
DECISION_COMPLETED = "COMPLETED"
_DECISIONS = {DECISION_APPROVED, DECISION_COMPLETED}
BINDING_FIELDS = ("external_action", "target_path", "target_content", "capability")

class AuthoritySignatureError(RuntimeError):
    pass



def _canonical_payload(task):
    payload = {
        "id": task.get("id"),
        "title": task.get("title"),
        "status": task.get("status"),
        "dependency_reason": task.get("dependency_reason"),
    }
    for key in BINDING_FIELDS:
        if task.get(key) is not None:
            payload[key] = task[key]
    if task.get("external_action") is not None and task.get("description") is not None:
        payload["description"] = task["description"]
    return payload


def binding_digest(task):
    """Status-independent digest of everything execution will act on."""
    payload = {"id": task.get("id"), "title": task.get("title")}
    for key in BINDING_FIELDS:
        payload[key] = task.get(key)
    if task.get("external_action") is not None:
        payload["description"] = task.get("description")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def signing_message(proposal, task_id, decision, timestamp, approver):
    return f"{proposal}|{task_id}|{decision}|{timestamp}|{approver}".encode("utf-8")


def _verify_signature(pubkey_b64, message, signature_b64):
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise AuthoritySignatureError("HALT: AIPP_AUTHORITY_PUBKEY is set but cryptography is not installed") from exc
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(pubkey_b64))
        key.verify(base64.b64decode(signature_b64), message)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def proposal_id(task):
    task_id = task.get("id")
    if not task_id:
        raise ValueError("Proposal requires a task id")
    encoded = json.dumps(
        _canonical_payload(task), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:12].upper()
    safe_task = re.sub(r"[^A-Z0-9]+", "-", str(task_id).upper()).strip("-")
    return f"{PROPOSAL_PREFIX}-{safe_task}-{digest}"


def parse_authority_log_text(text, pubkey=None):
    """Parse canonical Authority Log decisions; optionally require Ed25519 signatures."""
    pubkey = os.environ.get(PUBKEY_ENV, "").strip() if pubkey is None else pubkey
    rows = []
    for line in (text or "").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        proposal, task_id, decision, timestamp = cells[:4]
        approver = cells[4] if len(cells) > 4 else ""
        signature = cells[5] if len(cells) > 5 else ""
        if proposal.lower() in {"proposal id", ":---"}:
            continue
        decision = decision.upper()
        if decision not in _DECISIONS:
            continue
        if not proposal.startswith(f"{PROPOSAL_PREFIX}-") or not task_id:
            continue
        if pubkey:
            if not signature or not approver:
                continue
            if not _verify_signature(pubkey, signing_message(proposal, task_id, decision, timestamp, approver), signature):
                continue
        rows.append({"proposal_id": proposal, "task_id": task_id, "decision": decision,
                     "timestamp": timestamp, "approver": approver})
    return rows


def parse_authority_log(source):
    """Compatibility adapter for tests/tools; runner itself supplies Drive content as text."""
    if isinstance(source, Path):
        if not source.exists():
            return []
        return parse_authority_log_text(source.read_text(encoding="utf-8"))
    if isinstance(source, str):
        return parse_authority_log_text(source)
    return []


def is_approved(source, task):
    pid = proposal_id(task)
    return any(
        row["decision"] == DECISION_APPROVED and row["proposal_id"] == pid and row["task_id"] == task.get("id")
        for row in parse_authority_log(source)
    )


def is_completion_approved(source, task):
    pid = task.get("proposal_id")
    if not pid:
        return False
    return any(
        row["decision"] == DECISION_COMPLETED and row["proposal_id"] == pid and row["task_id"] == task.get("id")
        for row in parse_authority_log(source)
    )
