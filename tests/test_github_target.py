import os

import pytest

from runtime import github_target


def test_target_adapter_rejects_missing_context(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("AIPP_TARGET_REPOSITORY", raising=False)
    with pytest.raises(github_target.TargetProjectHalt, match="context missing"):
        github_target._context()


def test_target_adapter_rejects_non_aipp_base(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("AIPP_TARGET_REPOSITORY", "noppaapp/noppa")
    monkeypatch.setenv("AIPP_TARGET_BASE", "aipp/main")
    with pytest.raises(github_target.TargetProjectHalt, match="invalid target base"):
        github_target._context()


def test_target_adapter_generates_bounded_branch():
    assert github_target._safe_branch("TASK-42/demo") == "aipp/TASK-42-demo"
    with pytest.raises(github_target.TargetProjectHalt):
        github_target._safe_branch("///")


def test_target_adapter_applies_one_file_and_opens_pr(monkeypatch):
    calls = []
    responses = iter([
        "BASE_SHA",
        "BRANCH_REF",
        "BLOB_SHA",
        "BASE_TREE_SHA",
        "TREE_SHA",
        "COMMIT_SHA",
        "https://github.com/noppaapp/noppa/pull/1",
    ])

    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("AIPP_TARGET_REPOSITORY", "noppaapp/noppa")
    monkeypatch.setenv("AIPP_TARGET_BASE", "main")

    def fake_gh(args, token):
        calls.append(args)
        return next(responses)

    monkeypatch.setattr(github_target, "_gh", fake_gh)
    result = github_target.apply_text_file("TASK-42", "index.html", "<h1>NOPPA</h1>")

    assert result["repository"] == "noppaapp/noppa"
    assert result["branch"] == "aipp/TASK-42"
    assert result["commit"] == "COMMIT_SHA"
    assert result["pull_request"].endswith("/pull/1")
    assert any("refs/heads/aipp/TASK-42" in arg for call in calls for arg in call)
