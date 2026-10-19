import pytest

import runtime_service


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/status", None),
        ("post", "/api/run", {"command": "BAŞLA"}),
    ],
)
def test_protected_routes_fail_closed_when_runtime_token_is_unset(
    monkeypatch, method, path, payload
):
    monkeypatch.delenv("AIPP_RUNTIME_TOKEN", raising=False)
    client = runtime_service.app.test_client()

    response = getattr(client, method)(
        path,
        json=payload if payload is not None else None,
    )

    assert response.status_code == 503
    assert response.get_json() == {
        "ok": False,
        "error": "Runtime authentication is not configured",
    }


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/status", None),
        ("post", "/api/run", {"command": "BAŞLA"}),
    ],
)
def test_protected_routes_reject_missing_request_token(
    monkeypatch, method, path, payload
):
    monkeypatch.setenv("AIPP_RUNTIME_TOKEN", "test-runtime-secret")
    client = runtime_service.app.test_client()

    response = getattr(client, method)(
        path,
        json=payload if payload is not None else None,
    )

    assert response.status_code == 401
    assert response.get_json()["ok"] is False
    assert response.get_json()["error"] == "Invalid runtime token"
