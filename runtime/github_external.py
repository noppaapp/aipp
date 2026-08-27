"""Small, bounded GitHub external-action adapter for the AIPP proof path."""
import os
import subprocess


class ExternalActionHalt(RuntimeError):
    pass


def create_proof_branch(branch_name: str) -> str:
    """Create a temporary proof branch at the current revision via GitHub's API.

    This is deliberately narrow: it performs one reversible, non-destructive
    repository operation and returns the created ref. It requires a GitHub
    Actions token with contents:write permission.
    """
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    sha = os.environ.get("GITHUB_SHA", "").strip()
    if not token or not repo or not sha:
        raise ExternalActionHalt("HALT: GitHub external-action credentials/context missing")
    if not branch_name.startswith("aipp-proof/"):
        raise ExternalActionHalt("HALT: proof branch must use aipp-proof/ prefix")

    result = subprocess.run(
        [
            "gh", "api", "repos/{repo}/git/refs".format(repo=repo),
            "--method", "POST",
            "-f", f"ref=refs/heads/{branch_name}",
            "-f", f"sha={sha}",
        ],
        check=False,
        text=True,
        capture_output=True,
        env={**os.environ, "GH_TOKEN": token},
    )
    if result.returncode != 0:
        raise ExternalActionHalt(f"HALT: GitHub external action failed: {result.stderr.strip()}")
    return f"refs/heads/{branch_name}"
