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
    write_authority_approval,
    write_completion_approval,
    read_session_state,
    write_session_state,
    discover_task_candidates,
    list_workspace_tree,
    get_credentials,
)
from project_intelligence import analyze_documents, build_boot_version_update_proposal
from project_intelligence_ai import analyze_with_ai

app = Flask(__name__)
ROOT = Path(__file__).resolve().parent
SESSION_STATE_PATH = Path("/tmp/aipp_session_state.json")

def _load_session_state():
    try:
        if SESSION_STATE_PATH.exists():
            return json.loads(SESSION_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass

    # Render instances can restart or lose their ephemeral /tmp state.
    # Restore the canonical session snapshot from Drive before falling back
    # to a full workspace scan during an approved execution.
    try:
        folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
        if not folder_id:
            return None
        token = get_access_token()
        persisted = read_session_state(token, folder_id)
        if isinstance(persisted, dict):
            restored = persisted if isinstance(persisted.get("result"), dict) else {"result": persisted}
            SESSION_STATE_PATH.write_text(json.dumps(restored, ensure_ascii=False), encoding="utf-8")
            print("AIPP_SESSION_STATE_RESTORED source=Google Drive", flush=True)
            return restored
    except Exception as exc:
        print(f"AIPP_SESSION_STATE_RESTORE_ERROR type={type(exc).__name__}", flush=True)
    return None

def _save_session_state(payload):
    try:
        SESSION_STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        print(f"AIPP_SESSION_STATE_SAVE_ERROR type={type(exc).__name__}", flush=True)


def _token_fingerprint(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12] if value else "NONE"


def _require_runtime_token(body=None):
    expected = os.environ.get("AIPP_RUNTIME_TOKEN", "").strip()
    if not expected:
        # Fail closed: a missing server-side secret must never disable auth.
        return jsonify(
            {
                "ok": False,
                "error": "Runtime authentication is not configured",
            }
        ), 503

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


def _oauth_client_fingerprint():
    try:
        client_id, _ = get_credentials()
        return _token_fingerprint(client_id)
    except Exception:
        return "INVALID_OR_MISSING"


def _drive_context(include_ai=True, recovery_mode=False):
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

    if recovery_mode:
        # A stale-approval recovery only needs the canonical boot and protocol
        # documents. Scanning every PDF in both AIPP and Noppa during this
        # request caused avoidable memory pressure and worker termination.
        files = list_workspace_tree(token, folder_id)
        protocol_info = next((item for item in files if item.get("name") == "AIPP.md"), None)
        protocol_text = read_file_text(token, protocol_info) if protocol_info else ""
        if protocol_text is None:
            protocol_text = ""
        intelligence = {
            "version": "1.1.1",
            "findings": [],
            "proposals": [],
            "drive_scan": {
                "files_scanned": 2 if protocol_info else 1,
                "documents_read": 2 if protocol_info else 1,
                "documents_unreadable": 0,
                "folders_scanned": 0,
                "task_candidates": 0,
            },
            "project_scopes": {
                "AIPP": {
                    "configured": True,
                    "documents_scanned": 2 if protocol_info else 1,
                    "status": "TARGETED_RECOVERY_SCAN",
                },
                "NOPPA": {
                    "configured": False,
                    "status": "NOT_SCANNED_FOR_RECOVERY",
                    "message": "Recovery intentionally skips unrelated workspace documents.",
                },
            },
            "semantic": {
                "enabled": False,
                "available": False,
                "reason": "targeted recovery does not call semantic AI",
            },
        }
        boot_proposal = build_boot_version_update_proposal(
            boot_text, boot_info.get("id"), protocol_text
        )
        if boot_proposal:
            intelligence["findings"].append({
                "type": "boot_version_mismatch",
                "file_name": "PROJECT_BOOT.md",
                "evidence": boot_proposal["evidence"],
            })
            intelligence["proposals"].append(boot_proposal)
        return boot_text, authority_text, [], intelligence

    candidates, documents, drive_scan = discover_task_candidates(token, folder_id, include_documents=True)
    intelligence = analyze_documents(documents)
    intelligence["drive_scan"] = drive_scan
    intelligence["project_scopes"] = {
        "AIPP": {"configured": True, "documents_scanned": len(documents), "status": "SCANNED"}
    }

    # Analyze Noppa separately: its project state must not be confused with
    # AIPP's canonical boot, authority log, or task lifecycle.
    noppa_folder_id = os.environ.get("NOPPA_GDRIVE_FOLDER_ID", "").strip()
    if noppa_folder_id:
        try:
            _, noppa_documents, noppa_scan = discover_task_candidates(
                token, noppa_folder_id, include_documents=True
            )
            noppa_intelligence = analyze_documents(noppa_documents)
            for finding in noppa_intelligence.get("findings", []):
                finding["project"] = "NOPPA"
                for evidence in finding.get("evidence", []):
                    evidence["project"] = "NOPPA"
            for proposal in noppa_intelligence.get("proposals", []):
                proposal["project"] = "NOPPA"
                proposal["target"] = f"[NOPPA] {proposal.get('target', 'Proje incelemesi')}"
                for evidence in proposal.get("evidence", []):
                    evidence["project"] = "NOPPA"
            intelligence["findings"].extend(noppa_intelligence.get("findings", []))
            intelligence["proposals"].extend(noppa_intelligence.get("proposals", []))
            intelligence["project_scopes"]["NOPPA"] = {
                "configured": True, "documents_scanned": len(noppa_documents),
                "status": "SCANNED", "drive_scan": noppa_scan,
                "findings": len(noppa_intelligence.get("findings", [])),
                "proposals": len(noppa_intelligence.get("proposals", [])),
            }
            if include_ai:
                noppa_semantic = analyze_with_ai(noppa_documents)
                intelligence.setdefault("project_semantic", {})["NOPPA"] = noppa_semantic
                if noppa_semantic.get("available"):
                    for finding in noppa_semantic.get("findings", []):
                        finding["project"] = "NOPPA"
                        for evidence in finding.get("evidence", []):
                            evidence["project"] = "NOPPA"
                    for proposal in noppa_semantic.get("proposals", []):
                        proposal["project"] = "NOPPA"
                        proposal["target"] = f"[NOPPA] {proposal.get('target', 'Proje incelemesi')}"
                        for evidence in proposal.get("evidence", []):
                            evidence["project"] = "NOPPA"
                    intelligence["findings"].extend(noppa_semantic.get("findings", []))
                    intelligence["proposals"].extend(noppa_semantic.get("proposals", []))
                    intelligence["project_scopes"]["NOPPA"]["ai_status"] = "AVAILABLE"
                else:
                    intelligence["project_scopes"]["NOPPA"]["ai_status"] = "FALLBACK"
            else:
                intelligence.setdefault("project_semantic", {})["NOPPA"] = {
                    "enabled": False, "available": False, "reason": "status endpoint does not run AI"
                }
            print(
                "NOPPA_DRIVE_DISCOVERY "
                f"files={noppa_scan.get('files_scanned', 0)} "
                f"readable={noppa_scan.get('documents_read', len(noppa_documents))} "
                f"unreadable={noppa_scan.get('documents_unreadable', 0)} "
                f"findings={len(noppa_intelligence.get('findings', []))} "
                f"proposals={len(noppa_intelligence.get('proposals', []))} "
                f"ai={intelligence['project_scopes']['NOPPA'].get('ai_status', 'NOT_RUN')}",
                flush=True,
            )
        except Exception as exc:
            print(f"NOPPA_DRIVE_DISCOVERY_ERROR type={type(exc).__name__} message={str(exc)[:240]}", flush=True)
            intelligence["project_scopes"]["NOPPA"] = {
                "configured": True, "status": "ACCESS_ERROR", "error": str(exc)[:240]
            }
    else:
        intelligence["project_scopes"]["NOPPA"] = {
            "configured": False, "status": "NOT_CONFIGURED",
            "message": "Set NOPPA_GDRIVE_FOLDER_ID to the Noppa Google Drive folder ID."
        }

    if include_ai:
        semantic = analyze_with_ai(documents)
        intelligence["semantic"] = semantic
        if semantic.get("available"):
            intelligence["proposals"].extend(semantic.get("proposals", []))
            intelligence["findings"].extend(semantic.get("findings", []))
        intelligence["proposals"].sort(key=lambda p: (str(p.get("finding_type", "")), str(p.get("target", "")), str(p.get("action", ""))))
    else:
        intelligence["semantic"] = {"enabled": False, "available": False, "reason": "status endpoint does not run AI"}

    # Create a passive proposal only when the canonical protocol confirms v1.1.1
    # and PROJECT_BOOT has exactly one v1.0 marker.
    protocol_text = next((doc.get("text", "") for doc in documents if doc.get("name") == "AIPP.md"), "")
    boot_proposal = build_boot_version_update_proposal(boot_text, boot_info.get("id"), protocol_text)
    if boot_proposal:
        intelligence["findings"].append({
            "type": "boot_version_mismatch",
            "file_name": "PROJECT_BOOT.md",
            "evidence": boot_proposal["evidence"],
        })
        intelligence["proposals"].append(boot_proposal)
    return boot_text, authority_text, candidates, intelligence


def _run_aipp(command, task=None, max_attempts=3, include_ai=True, reuse_persisted_state=False, authority_text_override=None, reset_session_state=False, recovery_mode=False):
    session_state = None if reset_session_state else _load_session_state()
    if isinstance(session_state, dict) and isinstance(session_state.get("result"), dict):
        session_state = session_state["result"]
    else:
        session_state = None
    if reuse_persisted_state and session_state:
        boot_text, authority_text, candidates, intelligence = "", "", [], {"version":"0","findings":[],"proposals":[]}
    else:
        boot_text, authority_text, candidates, intelligence = _drive_context(
            include_ai=include_ai, recovery_mode=recovery_mode
        )

    env = os.environ.copy()
    if reset_session_state:
        env.pop("AIPP_SESSION_STATE_B64", None)
    env["AIPP_PROJECT_BOOT_B64"] = base64.b64encode(boot_text.encode()).decode()
    if authority_text_override is not None:
        authority_text = authority_text_override
    env["AIPP_AUTHORITY_LOG_B64"] = base64.b64encode(authority_text.encode()).decode()
    env["AIPP_DISCOVERED_TASKS_B64"] = base64.b64encode(
        json.dumps(candidates, ensure_ascii=False).encode()
    ).decode()
    env["AIPP_PROJECT_INTELLIGENCE_B64"] = base64.b64encode(
        json.dumps(intelligence, ensure_ascii=False).encode()
    ).decode()
    # Carry the persisted runtime state into the runner so every command
    # continues the same session instead of rebuilding from an empty state.
    if session_state:
        env["AIPP_SESSION_STATE_B64"] = base64.b64encode(
            json.dumps(session_state, ensure_ascii=False).encode()
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
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            for line in reversed(stdout.splitlines()):
                candidate = line.strip()
                if not candidate:
                    continue
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict):
                        payload = parsed
                        break
                except json.JSONDecodeError:
                    continue

    return result.returncode, payload, stdout, stderr


@app.get("/health")
def health():
    return jsonify(
        {
            "ok": True,
            "runner": "AIPP Standalone Cloud Runtime",
            "source": "Google Drive",
            "oauth_client_fingerprint": _oauth_client_fingerprint(),
        }
    )


@app.get("/api/status")
def status():
    auth_error = _require_runtime_token()
    if auth_error:
        return auth_error
    try:
        # Status remains strictly read-only: it never runs the runner or AI.
        # It restores the durable session snapshot from Drive so refresh cannot
        # erase an active queue or decision.
        token = get_access_token()
        folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
        persisted = read_session_state(token, folder_id) if folder_id else None
        if isinstance(persisted, dict) and isinstance(persisted.get("result"), dict):
            persisted = persisted["result"]
        if isinstance(persisted, dict) and persisted.get("task_lifecycle"):
            persisted = dict(persisted)
            persisted["ok"] = True
            persisted["source"] = "Google Drive"
            persisted["runtime"] = "AIPP Standalone Cloud Runtime"
            persisted["oauth_client_fingerprint"] = _oauth_client_fingerprint()
            return jsonify(persisted)
        return jsonify(
            {
                "ok": True,
                "source": "Google Drive",
                "runtime": "AIPP Standalone Cloud Runtime",
                "status": "READY",
                "project_boot": False,
                "authority_log": False,
                "task_candidates": [],
                "candidate_count": 0,
                "oauth_client_fingerprint": _oauth_client_fingerprint(),
            }
        )
    except Exception as exc:
        return jsonify(
            {
                "ok": False,
                "source": "Google Drive",
                "runtime": "AIPP Standalone Cloud Runtime",
                "oauth_client_fingerprint": _oauth_client_fingerprint(),
                "error": str(exc),
            }
        ), 500


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
        if max_attempts < 1 or max_attempts > 5:
            raise RuntimeError("HALT: max_attempts must be between 1 and 5")

        body.pop("_runtime_token", None)
        authority_override = None
        persisted = _load_session_state()
        if isinstance(persisted, dict) and isinstance(persisted.get("result"), dict):
            persisted = persisted["result"]
        if command == "BAŞLA" and isinstance(persisted, dict) and persisted.get("task_lifecycle"):
            # Reuse only a genuinely active session. A persisted snapshot with
            # an empty FUTURE queue can contain stale intelligence from a
            # previous scan; returning it unchanged makes the panel fall back
            # to HAZIR forever even though the workspace has fresh proposals.
            lifecycle = persisted.get("task_lifecycle", {})
            future = lifecycle.get("FUTURE", [])
            now = lifecycle.get("NOW")
            gate = persisted.get("authority_gate", {})
            status = str(persisted.get("status") or "").upper()
            protected_session = bool(
                now
                or gate.get("pending_approval")
                or status in {
                    "RUNNING",
                    "EXECUTING",
                    "IN_PROGRESS",
                    "AWAITING_AUTHORITY",
                    "APPROVED",
                }
            )
            active_session = bool(future or protected_session)
            # An explicit panel start can refresh a proposal-only snapshot,
            # but must never discard a task already in NOW or awaiting approval.
            force_refresh = bool(body.get("force_refresh"))
            if active_session and not (force_refresh and not protected_session):
                return jsonify({"ok": True, "command": command, "result": persisted,
                                "stdout": json.dumps(persisted, ensure_ascii=False),
                                "stderr": "", "reused_session": True,
                                "oauth_client_fingerprint": _oauth_client_fingerprint()}), 200
        if command == "REQUEST_APPROVAL" and task:
            # Never launch a workspace scan as a side effect of an approval click.
            # A stale proposal must stop here; the operator can explicitly start
            # a new scan and then review the newly generated proposal.
            current_future = (persisted or {}).get("task_lifecycle", {}).get("FUTURE", []) if isinstance(persisted, dict) else []
            if not any(isinstance(item, dict) and item.get("id") == task for item in current_future):
                raise RuntimeError(
                    f"HALT: proposal {task} is stale or no longer active. "
                    "No scan or action was started. Use BAŞLAT explicitly to refresh the workspace, then review the current proposal."
                )
        if command == "RECOVER_STALE_APPROVAL":
            if not task:
                raise RuntimeError("HALT: --task is required to recover a stale approval.")
            token = get_access_token()
            folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
            if not folder_id:
                raise RuntimeError("HALT: GDRIVE_FOLDER_ID is empty")
            drive_current = read_session_state(token, folder_id)
            if isinstance(drive_current, dict) and isinstance(drive_current.get("result"), dict):
                drive_current = drive_current["result"]
            current = drive_current if isinstance(drive_current, dict) else persisted
            lifecycle = (current or {}).get("task_lifecycle", {})
            active = lifecycle.get("NOW")
            if not isinstance(active, dict) or active.get("id") != task or str(active.get("status", "")).upper() != "APPROVED":
                raise RuntimeError("HALT: only the exact currently approved task can be recovered")
            supported = {"GITHUB_PROOF_BRANCH", "GITHUB_TARGET_TEXT_FILE", "GDRIVE_PROJECT_BOOT_TEXT"}
            if active.get("external_action") in supported:
                raise RuntimeError("HALT: this task already has a supported action; recovery is not allowed")
            # Revoke and persist the stale approval BEFORE any full Drive scan.
            # Previously, the old APPROVED snapshot remained canonical until the
            # entire scan finished; a timeout therefore made the panel resurrect it.
            stale = dict(active)
            old_id = str(active.get("id"))
            suffix = hashlib.sha256(old_id.encode("utf-8")).hexdigest()[:8].upper()
            stale["superseded_task_id"] = old_id
            stale["id"] = f"STALE-APPROVAL-{suffix}"
            stale["status"] = "STALE_APPROVAL_REVOKED"
            recovery_state = json.loads(json.dumps(current))
            recovery_lifecycle = recovery_state.setdefault("task_lifecycle", {})
            recovery_lifecycle["NOW"] = None
            # The revoked task must not remain visible in FUTURE while recovery
            # is running. Otherwise the panel can render it as a fresh proposal
            # before the recovery operation has finished.
            recovery_lifecycle["FUTURE"] = [
                item for item in recovery_lifecycle.get("FUTURE", [])
                if not isinstance(item, dict) or str(item.get("id") or "") != old_id
            ]
            recovery_lifecycle.setdefault("REFERENCE", []).append(stale)
            recovery_state["status"] = "RECOVERY_IN_PROGRESS"
            recovery_state["recovery_job"] = {
                "status": "IN_PROGRESS",
                "superseded_task_id": old_id,
                "started_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                "stage": "WORKSPACE_SCAN",
            }
            recovery_gate = recovery_state.setdefault("authority_gate", {})
            recovery_gate["pending_approval"] = None
            recovery_gate["pending_proposal_id"] = None
            recovery_gate["last_action"] = "STALE_APPROVAL_REVOKED_RECOVERY_IN_PROGRESS"
            recovery_snapshot = {
                "result": recovery_state,
                "saved_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            }
            _save_session_state(recovery_snapshot)
            # This Drive write is the commit point: do not begin scanning unless
            # the canonical snapshot no longer contains the old active approval.
            write_session_state(token, folder_id, recovery_state)

            # Recovery is deterministic and does not call the slow semantic AI provider.
            code, refreshed, stdout, stderr = _run_aipp(
                "BAŞLA", None, max_attempts, include_ai=False,
                reuse_persisted_state=False, reset_session_state=True,
                recovery_mode=True,
            )
            if code != 0 or not isinstance(refreshed, dict):
                recovery_state["status"] = "RECOVERY_FAILED"
                recovery_state["recovery_job"]["status"] = "FAILED"
                recovery_state["recovery_job"]["stage"] = "WORKSPACE_SCAN"
                recovery_state["recovery_job"]["error"] = (stderr or "Workspace scan failed")[:500]
                recovery_snapshot = {
                    "result": recovery_state,
                    "saved_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                }
                _save_session_state(recovery_snapshot)
                write_session_state(token, folder_id, recovery_state)
                raise RuntimeError(stderr or "HALT: fresh workspace analysis failed; stale approval remains revoked")
            new_lifecycle = refreshed.setdefault("task_lifecycle", {})
            new_lifecycle["NOW"] = None
            new_lifecycle.setdefault("REFERENCE", []).append(stale)
            refreshed["recovery_job"] = {
                "status": "COMPLETED",
                "superseded_task_id": old_id,
                "completed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            }
            new_future = new_lifecycle.setdefault("FUTURE", [])
            if new_future:
                fresh = new_future[0]
                fresh_id = str(fresh.get("id") or "INTEL-RECOVERED")
                fresh["id"] = f"{fresh_id}-REAUTH-{suffix}"
                fresh["title"] = str(fresh.get("title") or "Yeni öneri") + " (yeniden onay gerekli)"
                refreshed["intelligence_queue"] = [
                    fresh["id"] if item == fresh_id else item
                    for item in refreshed.get("intelligence_queue", [])
                ]
                for entry in (refreshed.get("project_intelligence") or {}).get("queue", []):
                    if entry.get("id") == fresh_id:
                        entry["id"] = fresh["id"]
                        entry["title"] = fresh["title"]
                refreshed["status"] = "PROPOSAL_READY"
                refreshed.setdefault("authority_gate", {})["pending_approval"] = None
                refreshed["authority_gate"]["pending_proposal_id"] = None
                refreshed["authority_gate"]["last_action"] = "STALE_APPROVAL_REVOKED_REQUIRES_NEW_APPROVAL"
            else:
                refreshed["status"] = "COMPLETED"
                refreshed.setdefault("authority_gate", {})["pending_approval"] = None
                refreshed["authority_gate"]["pending_proposal_id"] = None
                refreshed["authority_gate"]["last_action"] = "STALE_APPROVAL_REVOKED_NO_ACTIONABLE_PROPOSAL"
            snapshot = {"result": refreshed, "saved_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}
            _save_session_state(snapshot)
            write_session_state(token, folder_id, refreshed)
            return jsonify({
                "ok": True, "command": command, "task": task, "result": refreshed,
                "stdout": json.dumps(refreshed, ensure_ascii=False), "stderr": "",
                "stale_approval_revoked": True,
                "oauth_client_fingerprint": _oauth_client_fingerprint(),
            }), 200

        if command == "APPROVE":
            if not task:
                raise RuntimeError("HALT: --task is required.")
            token = get_access_token()
            folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
            if not folder_id:
                raise RuntimeError("HALT: GDRIVE_FOLDER_ID is empty")
            # The panel's status endpoint reads the canonical Drive snapshot,
            # while this process also keeps a local /tmp cache. Always prefer
            # Drive here so an approval cannot be checked against stale local state.
            drive_current = read_session_state(token, folder_id)
            if isinstance(drive_current, dict) and isinstance(drive_current.get("result"), dict):
                drive_current = drive_current["result"]
            current = drive_current if isinstance(drive_current, dict) and drive_current.get("task_lifecycle") else (
                persisted if isinstance(persisted, dict) else None
            )
            if current:
                _save_session_state({"result": current, "saved_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()})
            if not current or not current.get("task_lifecycle"):
                code0, current, _, err0 = _run_aipp("REQUEST_APPROVAL", task, max_attempts, include_ai=False)
                if code0 != 0 or not current:
                    raise RuntimeError(err0 or "HALT: approval request could not be validated")
            # Make duplicate approval submissions safe: if the same task has
            # already moved from FUTURE to NOW, preserve that approved state and
            # let the operator continue with EXECUTE_APPROVED instead of failing.
            now_task = current.get("task_lifecycle", {}).get("NOW")
            if isinstance(now_task, dict) and now_task.get("id") == task and str(now_task.get("status", "")).upper() in {"APPROVED", "NOW"}:
                return jsonify({
                    "ok": True,
                    "command": command,
                    "task": task,
                    "result": current,
                    "stdout": json.dumps(current, ensure_ascii=False),
                    "stderr": "",
                    "already_approved": True,
                    "oauth_client_fingerprint": _oauth_client_fingerprint(),
                }), 200
            future = current.get("task_lifecycle", {}).get("FUTURE", [])
            approved_task = next((item for item in future if item.get("id") == task), None)
            if not approved_task:
                # An approval click must never silently trigger BAŞLA. A stale
                # proposal is rejected without scanning or changing the queue;
                # the operator must explicitly start a fresh workspace scan.
                raise RuntimeError(
                    f"HALT: proposal {task} is stale or no longer active. "
                    "No scan or action was started. Use BAŞLAT explicitly to refresh the workspace, then review the current proposal."
                )
            from datetime import datetime, timezone
            if os.environ.get("AIPP_AUTHORITY_PUBKEY", "").strip():
                # Signed-approval mode: the runtime must NOT write approvals.
                # A human appends a row signed offline; the runner verifies it.
                pass
            else:
                write_authority_approval(token, folder_id, approved_task, datetime.now(timezone.utc).isoformat())
            authority_info = find_authority_log(token, folder_id)
            if authority_info:
                authority_override = read_file_text(token, authority_info)
                if authority_override is None:
                    raise RuntimeError("HALT: AUTHORITY_LOG.md could not be read from Google Drive")
        if command == "EXECUTE_APPROVED":
            # APPROVE has already been completed by the preceding operator action.
            # Re-running APPROVE here would search FUTURE again after the proposal
            # has already moved to NOW, causing a false "task not found" halt.
            # Continue directly from the persisted APPROVED/NOW session state.
            code, payload, stdout, stderr = _run_aipp(
                "EXECUTE",
                task,
                max_attempts,
                include_ai=False,
                reuse_persisted_state=True,
            )
        else:
            reuse = command in {"REQUEST_APPROVAL", "APPROVE", "EXECUTE", "VERIFY", "CONTINUE", "COMPLETE"}
            include_ai = command == "BAŞLA"
            if command == "COMPLETE":
                if os.environ.get("AIPP_AUTHORITY_PUBKEY", "").strip():
                    raise RuntimeError(
                        "HALT: signed-authority mode is enabled. Add a signed COMPLETED decision to AUTHORITY_LOG.md before finalizing."
                    )
                token = get_access_token()
                folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
                if not folder_id:
                    raise RuntimeError("HALT: GDRIVE_FOLDER_ID is empty")
                drive_current = read_session_state(token, folder_id)
                if isinstance(drive_current, dict) and isinstance(drive_current.get("result"), dict):
                    drive_current = drive_current["result"]
                current_task = (drive_current or {}).get("task_lifecycle", {}).get("NOW")
                if not isinstance(current_task, dict) or current_task.get("id") != task:
                    raise RuntimeError("HALT: completion target is not the current active task")
                if str(current_task.get("status", "")).upper() != "VERIFIED":
                    raise RuntimeError("HALT: only a VERIFIED task can receive completion approval")
                from datetime import datetime, timezone
                authority_override = write_completion_approval(
                    token, folder_id, current_task, datetime.now(timezone.utc).isoformat()
                )
            code, payload, stdout, stderr = _run_aipp(
                command, task, max_attempts, include_ai=include_ai,
                reuse_persisted_state=reuse, authority_text_override=authority_override
            )
        response_result = {
            "ok": code == 0,
            "command": command,
            "task": task,
            "result": payload,
            "stdout": stdout,
            "stderr": stderr,
            "oauth_client_fingerprint": _oauth_client_fingerprint(),
        }
        if code == 0 and payload:
            _save_session_state({"result": payload, "saved_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()})
            token = get_access_token()
            folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
            if folder_id:
                write_session_state(token, folder_id, payload)
        return (
            jsonify(response_result),
            200 if code == 0 else 422,
        )
    except Exception as exc:
        return jsonify(
            {
                "ok": False,
                "source": "Google Drive",
                "runtime": "AIPP Standalone Cloud Runtime",
                "oauth_client_fingerprint": _oauth_client_fingerprint(),
                "error": str(exc),
            }
        ), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
