"""Deterministic proposal identity and canonical authority-log parsing."""

import hashlib
import json
import re
from pathlib import Path

AUTHORITY_LOG = "AUTHORITY_LOG.md"
PROPOSAL_PREFIX = "PROP"


def _canonical_payload(task):
    """Return only proposal-defining fields in deterministic form."""
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "status": task.get("status"),
        "dependency_reason": task.get("dependency_reason"),
    }


def proposal_id(task):
    """Create a stable proposal ID from proposal-defining task content."""
    task_id = task.get("id")
    if not task_id:
        raise ValueError("Proposal requires a task id")
    encoded = json.dumps(
        _canonical_payload(task),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:12].upper()
    safe_task = re.sub(r"[^A-Z0-9]+", "-", str(task_id).upper()).strip("-")
    return f"{PROPOSAL_PREFIX}-{safe_task}-{digest}"


def parse_authority_log(path):
    """Parse strict approval rows from AUTHORITY_LOG.md.

    Expected table columns: Proposal ID, Task ID, Decision, Timestamp, Note.
    Unknown/malformed rows are ignored rather than granting authority.
    """
    path = Path(path)
    if not path.exists():
        return []
    approvals = []
    for line in path.read_text(encoding="utf-8").splitlines():
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


def is_approved(path, task):
    """Return True only when task and deterministic proposal ID both match."""
    pid = proposal_id(task)
    return any(row["proposal_id"] == pid and row["task_id"] == task.get("id") for row in parse_authority_log(path))
