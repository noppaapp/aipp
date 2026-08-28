"""Bounded GitHub external-action adapter used by AIPP execution."""
import os
import subprocess


class ExternalActionHalt(RuntimeError):
    pass


def _context():
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    sha = os.environ.get("GITHUB_SHA", "").strip()
    if not token or not repo or not sha:
        raise ExternalActionHalt("HALT: GitHub external-action credentials/context missing")
    return token, repo, sha


def create_proof_branch(branch_name: str) -> str:
    """Create one temporary proof branch at the current revision."""
    token, repo, sha = _context()
    if not branch_name.startswith("aipp-proof/"):
        raise ExternalActionHalt("HALT: proof branch must use aipp-proof/ prefix")
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/git/refs", "--method", "POST",
         "-f", f"ref=refs/heads/{branch_name}", "-f", f"sha={sha}"],
        check=False, text=True, capture_output=True,
        env={**os.environ, "GH_TOKEN": token},
    )
    if result.returncode != 0:
        raise ExternalActionHalt(f"HALT: GitHub external action failed: {result.stderr.strip()}")
    return f"refs/heads/{branch_name}"


def verify_proof_branch(branch_name: str) -> bool:
    """Verify that the temporary branch exists, without trusting local state."""
    token, repo, _ = _context()
    if not branch_name.startswith("aipp-proof/"):
        raise ExternalActionHalt("HALT: proof branch must use aipp-proof/ prefix")
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/git/ref/heads/{branch_name}"],
        check=False, text=True, capture_output=True,
        env={**os.environ, "GH_TOKEN": token},
    )
    return result.returncode == 0


def delete_proof_branch(branch_name: str) -> None:
    """Delete only the bounded proof branch created by this adapter."""
    token, repo, _ = _context()
    if not branch_name.startswith("aipp-proof/"):
        raise ExternalActionHalt("HALT: proof branch must use aipp-proof/ prefix")
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/git/refs/heads/{branch_name}", "--method", "DELETE"],
        check=False, text=True, capture_output=True,
        env={**os.environ, "GH_TOKEN": token},
    )
    if result.returncode != 0:
        raise ExternalActionHalt(f"HALT: GitHub cleanup failed: {result.stderr.strip()}")


def execute_bounded_github_proof(task_id: str) -> dict:
    """Perform create -> remote verify -> delete for an approved AIPP task."""
    safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(task_id))
    branch_name = f"aipp-proof/{safe_id}"
    create_proof_branch(branch_name)
    try:
        verified = verify_proof_branch(branch_name)
        if not verified:
            raise ExternalActionHalt("HALT: GitHub external action verification failed")
        return {"action": "GITHUB_PROOF_BRANCH", "branch": branch_name, "verified": True}
    finally:
        delete_proof_branch(branch_name)
