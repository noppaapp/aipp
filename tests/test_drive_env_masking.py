import base64
import json

import aipp_drive_runtime
import aipp_drive_task_bridge


def _assert_masked_env_value(capsys, env_path, name, expected_value):
    encoded = base64.b64encode(expected_value.encode("utf-8")).decode("ascii")
    assert f"{name}={encoded}\n" in env_path.read_text(encoding="utf-8")
    output = capsys.readouterr().out
    assert f"::add-mask::{encoded}" in output


def test_project_boot_payload_is_masked_before_github_env_publish(tmp_path, monkeypatch, capsys):
    env_path = tmp_path / "github_env"
    monkeypatch.setenv("GITHUB_ENV", str(env_path))
    value = "# PROJECT_BOOT\nprivate workspace context"

    aipp_drive_runtime.publish_boot_to_runtime_env(value)

    _assert_masked_env_value(capsys, env_path, "AIPP_PROJECT_BOOT_B64", value)


def test_authority_log_payload_is_masked_before_github_env_publish(tmp_path, monkeypatch, capsys):
    env_path = tmp_path / "github_env"
    monkeypatch.setenv("GITHUB_ENV", str(env_path))
    value = "# AUTHORITY_LOG\n| internal decision |"

    aipp_drive_runtime.publish_authority_to_runtime_env(value)

    _assert_masked_env_value(capsys, env_path, "AIPP_AUTHORITY_LOG_B64", value)


def test_discovered_task_payload_is_masked_before_github_env_publish(tmp_path, monkeypatch, capsys):
    env_path = tmp_path / "github_env"
    monkeypatch.setenv("GITHUB_ENV", str(env_path))
    candidates = [{"id": "drive-file-id", "task_ids": ["TASK-01"]}]
    monkeypatch.setattr(aipp_drive_task_bridge, "get_access_token", lambda: "access")
    monkeypatch.setenv("GDRIVE_FOLDER_ID", "folder-id")
    monkeypatch.setattr(aipp_drive_task_bridge, "discover_task_candidates", lambda *_: candidates)

    aipp_drive_task_bridge.main()

    # The shared publisher uses compact JSON for deterministic transport.
    compact = json.dumps(candidates, ensure_ascii=False, separators=(",", ":"))
    encoded = base64.b64encode(compact.encode("utf-8")).decode("ascii")
    assert f"AIPP_DISCOVERED_TASKS_B64={encoded}\n" in env_path.read_text(encoding="utf-8")
    assert f"::add-mask::{encoded}" in capsys.readouterr().out
