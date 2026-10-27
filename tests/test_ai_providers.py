import json

import pytest

from ai import providers
from ai.model_router import DEFAULT_MODELS, route


def test_groq_adapter_uses_server_side_key_and_openai_compatible_api(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    captured = {}

    def fake_post(url, headers, payload):
        captured.update(url=url, headers=headers, payload=payload)
        return {"choices": [{"message": {"content": '{"findings":[],"proposals":[]}'}}]}

    monkeypatch.setattr(providers, "_post_json", fake_post)
    result = providers.GroqAdapter().execute(
        next(model for model in DEFAULT_MODELS if model.provider == "groq"),
        {"prompt": "analyze", "system": "stay evidence-based", "json_output": True},
    )

    assert result == {"findings": [], "proposals": []}
    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-groq-key"
    assert captured["payload"]["response_format"] == {"type": "json_object"}


def test_openrouter_adapter_uses_configured_key_and_endpoint(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    captured = {}

    def fake_post(url, headers, payload):
        captured.update(url=url, headers=headers, payload=payload)
        return {"choices": [{"message": {"content": "ready"}}]}

    monkeypatch.setattr(providers, "_post_json", fake_post)
    result = providers.OpenRouterAdapter().execute(
        next(model for model in DEFAULT_MODELS if model.provider == "openrouter"),
        {"prompt": "check", "json_output": False},
    )

    assert result == "ready"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-openrouter-key"
    assert captured["headers"]["X-Title"] == "AIPP"


@pytest.mark.parametrize(
    ("provider", "env_name", "adapter"),
    [
        ("groq", "GROQ_API_KEY", providers.GroqAdapter),
        ("openrouter", "OPENROUTER_API_KEY", providers.OpenRouterAdapter),
    ],
)
def test_fallback_provider_requires_its_own_api_key(monkeypatch, provider, env_name, adapter):
    monkeypatch.delenv(env_name, raising=False)
    with pytest.raises(providers.ProviderError, match=env_name):
        providers.configured_adapter(provider)


def test_router_order_keeps_gemini_primary_then_groq_openrouter_and_claude():
    ordered = [model.provider for model in sorted(DEFAULT_MODELS, key=lambda item: item.priority, reverse=True)]
    assert ordered == ["gemini", "gemini", "groq", "openrouter", "claude"]
    assert route({"text", "reasoning"}).provider == "gemini"



def test_transport_error_becomes_provider_error_for_fallback(monkeypatch):
    from urllib.error import URLError

    def fail_request(*args, **kwargs):
        raise URLError("connection timed out")

    monkeypatch.setattr(providers, "urlopen", fail_request)
    with pytest.raises(providers.ProviderError, match="request failed"):
        providers._post_json("https://provider.invalid/chat/completions", {}, {})



def test_semantic_analysis_falls_back_when_gemini_quota_is_exhausted(monkeypatch):
    import project_intelligence_ai as semantic

    monkeypatch.setenv("AIPP_SEMANTIC_ANALYSIS", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    calls = []

    class FakeAdapter:
        def __init__(self, provider):
            self.provider = provider

        def execute(self, model, task):
            calls.append((self.provider, model.model))
            if self.provider == "gemini":
                raise providers.ProviderError("quota exhausted")
            return {
                "findings": [{
                    "type": "observation",
                    "claim": "Kaynak metin doğrulandı.",
                    "evidence": [{
                        "file_name": "notes.md",
                        "quote": "Source line exact.",
                    }],
                }],
                "proposals": [],
            }

    monkeypatch.setattr(
        semantic,
        "configured_adapter",
        lambda provider: FakeAdapter(provider),
    )

    result = semantic.analyze_with_ai([
        {"name": "notes.md", "text": "Source line exact."},
    ])

    assert result["available"] is True
    assert result["provider"] == "groq"
    assert result["findings"][0]["evidence"][0]["quote"] == "Source line exact."
    assert calls[:3] == [
        ("gemini", "flash"),
        ("gemini", "pro"),
        ("groq", "openai/gpt-oss-120b"),
    ]
    assert all(provider in {"gemini", "groq"} for provider, _ in calls)
