import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
from pathlib import Path

from flask import Flask, jsonify, request

from aipp_drive_runtime import (
    get_access_token,
    find_project_boot,
    find_authority_log,
    read_file_text,
    discover_task_candidates,
)

app = Flask(__name__)
ROOT = Path(__file__).resolve().parent


def _token_fingerprint(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _require_runtime_token(body=None):
    expected = os.environ.get("AIPP_RUNTIME_TOKEN", "").strip()
    if not expected:
        return

    body = body or {}
    supplied_token = str(body.get("_runtime_token") or "").strip()
    if supplied_token:
        supplied = supplied_token
    else:
        supplied_header = request.headers.get("X-AIPP-Runtime-Token", "")
        if not supplied_header:
            supplied_header = request.headers.get("Authorization", "")
        supplied = supplied_header[7:] if supplied_header.startswith("Bearer ") else supplied_header

    expected_fp = _token_fingerprint(expected)
    supplied_fp = _token_fingerprint(supplied) if supplied else "NONE"
    print(
        f"AIPP_AUTH_CHECK expected={expected_fp} supplied={supplied_fp} "
        f"transport={'body' if supplied_token else 'header'}",
        flush=True,
    )

    if not hmac.compare_digest(supplied, expected):
        return jsonify(
            {
                "ok": False,
                "error": "Invalid runtime token",
                "token_fingerprint": expected_fp,
                "supplied_fingerprint": supplied_fp,
            }
        ), 401


def _drive_context():
    token = get_access_token()
    folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
    if not folder_id:
        raise RuntimeError("HALT: GDRIVE_FOLDER_ID is empty")

    boot_info = find_project_boot(token, folder_id)
    if not boot_info:
        raise RuntimeError("HALT: PROJECT_BOOT.md not found in configured Drive folder")
    boot_text = read_file_text(token, boot_info)
    if boot_text is None:
        raise RuntimeError("HALT: PROJECT_BOOT.md could not be read from Google Drive")

    authority_info = find_authority_log(token, folder_id)
    authority_text = ""
    if authority_info:
        authority_text = read_file_text(token, authority_info)
        if authority_text is None:
            raise RuntimeError("HALT: AUTHORITY_LOG.md could not be read from Google Drive")

    candidates = discover_task_candidates(token, folder_id)
    return boot_text, authority_text, candidates


def _run_aipp(command, task=None, max_attempts=3):
    boot_text, authority_text, candidates = _drive_context()

    env = os.environ.copy()
    env["AIPP_PROJECT_BOOT_B64"] = base64.b64encode(boot_text.encode()).decode()
    env["AIPP_AUTHORITY_LOG_B64"] = base64.b64encode(authority_text.encode()).decode()
    env["AIPP_DISCOVERED_TASKS_B64"] = base64.b64encode(
        json.dumps(candidates, ensure_ascii=False).encode()
    ).decode()

    cmd = [
        sys.executable,
        str(ROOT / "aipp_runner.py"),
        command,
        "--workspace",
        str(ROOT),
        "--max-attempts",
        str(max_attempts),
    ]
    if task:
        cmd.extend(["--task", task])

    result = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    payload = None
    if stdout:
        try:
            payload = json.loads(stdout.splitlines()[-1])
        except Exception:
            pass

    return result.returncode, payload, stdout, stderr


@app.get("/health")
def health():
    return jsonify(
        {
            "ok": True,
            "runner": "AIPP Standalone Cloud Runtime",
            "source": "Google Drive",
        }
    )


@app.get("/api/status")
def status():
    auth_error = _require_runtime_token()
    if auth_error:
        return auth_error
    try:
        boot, authority, candidates = _drive_context()
        return jsonify(
            {
                "ok": True,
                "source": "Google Drive",
                "project_boot": bool(boot),
                "authority_log": bool(authority),
                "task_candidates": candidates,
                "candidate_count": len(candidates),
            }
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/run")
def run():
    body = request.get_json(silent=True) or {}
    auth_error = _require_runtime_token(body)
    if auth_error:
        return auth_error
    try:
        command = str(body.get("command") or "BAŞLA").upper()
        task = str(body.get("task") or "").strip() or None
        max_attempts = int(body.get("max_attempts") or 3)

        body.pop("_runtime_token", None)
        code, payload, stdout, stderr = _run_aipp(command, task, max_attempts)
        return (
            jsonify(
                {
                    "ok": code == 0,
                    "command": command,
                    "task": task,
                    "result": payload,
                    "stdout": stdout,
                    "stderr": stderr,
                }
            ),
            200 if code == 0 else 422,
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
