import runtime_service


def test_basta_runs_as_background_job_and_returns_result(monkeypatch):
    monkeypatch.setenv("AIPP_RUNTIME_TOKEN", "test-runtime-token")

    class ImmediateThread:
        def __init__(self, target, args, daemon):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(runtime_service.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(
        runtime_service,
        "_execute_run",
        lambda body: (
            runtime_service.jsonify({"ok": True, "command": body["command"], "result": "scan-result"}),
            200,
        ),
    )
    runtime_service.RUNTIME_JOBS.clear()
    client = runtime_service.app.test_client()

    started = client.post(
        "/api/run",
        json={"command": "BAŞLA", "_runtime_token": "test-runtime-token"},
    )

    assert started.status_code == 202
    job_id = started.get_json()["job_id"]
    status = client.get(
        f"/api/jobs/{job_id}",
        headers={"X-AIPP-Runtime-Token": "test-runtime-token"},
    )

    assert status.status_code == 200
    assert status.get_json()["status"] == "COMPLETED"
    assert status.get_json()["data"]["result"] == "scan-result"


def test_basta_reuses_existing_running_runtime_job(monkeypatch):
    monkeypatch.setenv("AIPP_RUNTIME_TOKEN", "test-runtime-token")
    runtime_service.RUNTIME_JOBS.clear()
    runtime_service.RUNTIME_JOBS["existing-job"] = {"status": "RUNNING"}
    client = runtime_service.app.test_client()

    response = client.post(
        "/api/run",
        json={"command": "BAŞLA", "_runtime_token": "test-runtime-token"},
    )

    assert response.status_code == 202
    assert response.get_json()["job_id"] == "existing-job"
    assert response.get_json()["reused_job"] is True


def test_runtime_job_status_requires_runtime_token(monkeypatch):
    monkeypatch.setenv("AIPP_RUNTIME_TOKEN", "test-runtime-token")
    runtime_service.RUNTIME_JOBS.clear()
    runtime_service.RUNTIME_JOBS["known-job"] = {"status": "RUNNING"}
    response = runtime_service.app.test_client().get("/api/jobs/known-job")

    assert response.status_code == 401
    assert response.get_json()["error"] == "Invalid runtime token"
