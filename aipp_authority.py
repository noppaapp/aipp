"""Deterministic proposal identity and canonical authority-log parsing."""

import hashlib
import json
import re
from pathlib import Path

AUTHORITY_LOG = "AUTHORITY_LOG.md"
AUTHORITY_ENV = "AIPP_AUTHORITY_LOG_B64"
PROPOSAL_PREFIX = "PROP"


def _canonical_payload(task):
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "status": task.get("status"),
        "dependency_reason": task.get("dependency_reason"),
    }


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


def parse_authority_log_text(text):
    """Parse approvals from canonical Authority Log content already in memory."""
    approvals = []
    for line in (text or "").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        proposal, task_id, decision, timestamp = cells[:4]
        if proposal.lower() in {"proposal id", ":---"}:
            continue
        if decision.upper() != "APPROVED":
            continue
        if not proposal.startswith(f"{PROPOSAL_PREFIX}-") or not task_id:
            continue
        approvals.append({"proposal_id": proposal, "task_id": task_id, "decision": "APPROVED", "timestamp": timestamp})
    return approvals


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
        row["proposal_id"] == pid and row["task_id"] == task.get("id")
        for row in parse_authority_log(source)
    )
