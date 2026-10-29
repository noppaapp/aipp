from ai.executor import ExecutionResult
import project_intelligence_ai as module


def test_ai_proposal_requires_exact_source_quote():
    documents = [{"name": "PROJECT_BOOT.md", "text": "TASK-01 is FUTURE."}]
    result = module._validate({
        "findings": [],
        "proposals": [{
            "action": "ADD",
            "target": "TASK-02",
            "reason": "invented",
            "evidence": [{"file_name": "PROJECT_BOOT.md", "quote": "TASK-02 is missing"}],
        }],
    }, documents)
    assert result["proposals"] == []


def test_ai_proposal_with_exact_quote_is_authority_gated():
    documents = [{"name": "ideas.md", "text": "Next step: implement verification panel."}]
    result = module._validate({
        "findings": [],
        "proposals": [{
            "action": "ADD",
            "target": "verification panel",
            "reason": "The idea is actionable.",
            "evidence": [{"file_name": "ideas.md", "quote": "Next step: implement verification panel."}],
        }],
    }, documents)
    assert result["proposals"][0]["requires_authority"] is True
    assert result["proposals"][0]["status"] == "PROPOSED"


def test_invalid_action_is_discarded():
    documents = [{"name": "notes.md", "text": "Review this."}]
    result = module._validate({
        "findings": [],
        "proposals": [{
            "action": "EXECUTE",
            "target": "x",
            "reason": "x",
            "evidence": [{"file_name": "notes.md", "quote": "Review this."}],
        }],
    }, documents)
    assert result["proposals"] == []


def test_malformed_ai_output_fails_closed(monkeypatch):
    monkeypatch.setenv("AIPP_SEMANTIC_ANALYSIS", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        module,
        "execute",
        lambda *args, **kwargs: ExecutionResult("gemini", "pro", "not-json"),
    )
    result = module.analyze_with_ai([{"name": "ideas.md", "text": "Next step: verify."}])
    assert result["enabled"] is True
    assert result["available"] is False
    assert result["reason"].startswith("semantic analysis unavailable:")


def test_provider_timeout_falls_back_without_aborting_scan(monkeypatch):
    monkeypatch.setenv("AIPP_SEMANTIC_ANALYSIS", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class Model:
        provider = "gemini"
        model = "test-model"
        priority = 1

    class Adapter:
        def execute(self, model_spec, task):
            raise TimeoutError("provider timed out")

    monkeypatch.setattr(module, "DEFAULT_MODELS", (Model(),))
    monkeypatch.setattr(module, "configured_adapter", lambda provider: Adapter())

    result = module.analyze_with_ai([{"name": "ideas.md", "text": "Next step: verify."}])

    assert result["enabled"] is True
    assert result["available"] is False
    assert "TimeoutError" in result["reason"]

def test_synthesis_failure_preserves_validated_batch_results(monkeypatch):
    monkeypatch.setenv("AIPP_SEMANTIC_ANALYSIS", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class Model:
        provider = "gemini"
        model = "flash"
        priority = 100

    class Adapter:
        calls = 0

        def execute(self, model_spec, task):
            self.calls += 1
            if self.calls == 1:
                return {
                    "findings": [{
                        "type": "verified_observation",
                        "claim": "Kaynak metin doğrulandı.",
                        "evidence": [{
                            "file_name": "ideas.md",
                            "quote": "Next step: verify this source.",
                        }],
                    }],
                    "proposals": [],
                }
            raise module.ProviderError("synthesis timed out")

    adapter = Adapter()
    monkeypatch.setattr(module, "DEFAULT_MODELS", (Model(),))
    monkeypatch.setattr(module, "configured_adapter", lambda provider: adapter)

    result = module.analyze_with_ai([{
        "name": "ideas.md",
        "text": "Next step: verify this source.",
    }])

    assert result["enabled"] is True
    assert result["available"] is True
    assert result["provider"] == "PARTIAL_BATCH_MERGE"
    assert result["findings"][0]["type"] == "verified_observation"
    assert result["findings"][0]["evidence"][0]["quote"] == "Next step: verify this source."
    assert result["proposals"][0]["requires_authority"] is True
    assert "synthesis timed out" in result["synthesis_warning"]



def test_later_batch_failure_preserves_prior_results_and_marks_analysis_incomplete(monkeypatch):
    monkeypatch.setenv("AIPP_SEMANTIC_ANALYSIS", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class Model:
        provider = "gemini"
        model = "flash"
        priority = 100

    class Adapter:
        calls = 0

        def execute(self, model_spec, task):
            self.calls += 1
            if self.calls == 1:
                return {
                    "findings": [{
                        "type": "verified_observation",
                        "claim": "İlk grup doğrulandı.",
                        "evidence": [{
                            "file_name": "ideas.md",
                            "quote": "Next step: verify this source.",
                        }],
                    }],
                    "proposals": [],
                }
            raise module.ProviderError("provider unavailable on second batch")

    adapter = Adapter()
    monkeypatch.setattr(module, "_document_chunks", lambda documents: ["batch one", "batch two"])
    monkeypatch.setattr(module, "DEFAULT_MODELS", (Model(),))
    monkeypatch.setattr(module, "configured_adapter", lambda provider: adapter)

    result = module.analyze_with_ai([{
        "name": "ideas.md",
        "text": "Next step: verify this source.",
    }])

    assert result["available"] is True
    assert result["status"] == "PARTIAL"
    assert result["complete"] is False
    assert result["batches"] == 1
    assert result["expected_batches"] == 2
    assert result["failed_batches"] == [2]
    assert result["findings"][0]["claim"] == "İlk grup doğrulandı."
    assert result["findings"][0]["evidence"][0]["quote"] == "Next step: verify this source."


def test_alternate_model_from_same_provider_is_tried_after_model_failure(monkeypatch):
    monkeypatch.setenv("AIPP_SEMANTIC_ANALYSIS", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class Model:
        def __init__(self, model, priority):
            self.provider = "gemini"
            self.model = model
            self.priority = priority

    class Adapter:
        calls = []

        def execute(self, model_spec, task):
            self.calls.append(model_spec.model)
            if model_spec.model == "flash":
                raise module.ProviderError("model temporarily unavailable")
            return {
                "findings": [{
                    "type": "verified_observation",
                    "claim": "Kaynak metin doğrulandı.",
                    "evidence": [{
                        "file_name": "ideas.md",
                        "quote": "Next step: verify this source.",
                    }],
                }],
                "proposals": [],
            }

    adapter = Adapter()
    monkeypatch.setattr(
        module, "DEFAULT_MODELS",
        (Model("flash", 100), Model("pro", 90)),
    )
    monkeypatch.setattr(module, "configured_adapter", lambda provider: adapter)

    result = module.analyze_with_ai([{
        "name": "ideas.md",
        "text": "Next step: verify this source.",
    }])

    assert result["status"] == "COMPLETE"
    assert result["complete"] is True
    assert result["findings"][0]["claim"] == "Kaynak metin doğrulandı."
    assert adapter.calls == ["flash", "pro", "pro"]
