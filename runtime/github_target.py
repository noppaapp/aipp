"""Bounded adapter for applying AIPP artifacts to an external GitHub project.

The adapter never writes directly to the target default branch. It creates an
AIPP-prefixed feature branch, applies an explicitly supplied UTF-8 text file,
and opens a PR against the configured base branch.
"""
import os
import re
import subprocess


class TargetProjectHalt(RuntimeError):
    pass


_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH_RE = re.compile(r"^aipp/[A-Za-z0-9._/-]+$")


def _context():
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("AIPP_TARGET_REPOSITORY", "").strip()
    base = os.environ.get("AIPP_TARGET_BASE", "main").strip() or "main"
    if not token or not repo:
        raise TargetProjectHalt("HALT: target repository context missing")
    if not _REPO_RE.fullmatch(repo):
        raise TargetProjectHalt("HALT: invalid target repository")
    if base.startswith("aipp/") or not re.fullmatch(r"[A-Za-z0-9_.-]+", base):
        raise TargetProjectHalt("HALT: invalid target base branch")
    return token, repo, base


def _gh(args, token):
    result = subprocess.run(
        ["gh", *args], check=False, text=True, capture_output=True,
        env={**os.environ, "GH_TOKEN": token},
    )
    if result.returncode != 0:
        raise TargetProjectHalt(f"HALT: target GitHub action failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _safe_branch(task_id):
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in str(task_id)).strip("-")
    if not safe:
        raise TargetProjectHalt("HALT: task id cannot produce a target branch")
    branch = f"aipp/{safe}"
    if not _BRANCH_RE.fullmatch(branch):
        raise TargetProjectHalt("HALT: generated target branch is invalid")
    return branch


def apply_text_file(task_id, path, content, title=None, body=None):
    """Create an AIPP branch, commit one explicit file, and open a PR.

    This function is intentionally limited to one caller-supplied text file.
    It does not merge the PR and it never targets the base branch directly.
    """
    token, repo, base = _context()
    if not path or path.startswith("/") or ".." in path.split("/"):
        raise TargetProjectHalt("HALT: target file path must be repository-relative")
    branch = _safe_branch(task_id)

    base_sha = _gh(["api", f"repos/{repo}/git/ref/heads/{base}", "--jq", ".object.sha"], token)
    _gh(["api", f"repos/{repo}/git/refs", "--method", "POST",
         "-f", f"ref=refs/heads/{branch}", "-f", f"sha={base_sha}"], token)

    blob_sha = _gh(["api", f"repos/{repo}/git/blobs", "--method", "POST",
                    "-f", "content=" + content, "-f", "encoding=utf-8", "--jq", ".sha"], token)
    base_tree = _gh(["api", f"repos/{repo}/git/commits/{base_sha}", "--jq", ".tree.sha"], token)
    tree_sha = _gh(["api", f"repos/{repo}/git/trees", "--method", "POST",
                    "-f", f"base_tree={base_tree}",
                    "-f", f"tree[][path]={path}",
                    "-f", "tree[][mode]=100644",
                    "-f", "tree[][type]=blob",
                    "-f", f"tree[][sha]={blob_sha}", "--jq", ".sha"], token)
    commit_sha = _gh(["api", f"repos/{repo}/git/commits", "--method", "POST",
                      "-f", f"message={title or f'AIPP: {task_id}'}",
                      "-f", f"tree={tree_sha}",
                      "-f", f"parents[]={base_sha}", "--jq", ".sha"], token)
    _gh(["api", f"repos/{repo}/git/refs/heads/{branch}", "--method", "PATCH",
         "-f", f"sha={commit_sha}"], token)
    pr = _gh(["api", f"repos/{repo}/pulls", "--method", "POST",
              "-f", f"title={title or f'AIPP: {task_id}'}",
              "-f", f"body={body or 'Created by AIPP target project execution.'}",
              "-f", f"head={branch}", "-f", f"base={base}", "--jq", ".html_url"], token)
    return {"repository": repo, "base": base, "branch": branch, "commit": commit_sha, "pull_request": pr}
