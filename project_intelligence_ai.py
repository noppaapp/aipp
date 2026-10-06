"""AI-assisted project reconciliation with deterministic validation.

The model proposes. The deterministic layer validates structure and preserves
the Authority Gate. No AI output is ever auto-approved or executed.
"""
import json
import os

from ai.executor import execute, ExecutionResult
from ai.providers import configured_adapter, ProviderError
from ai.model_router import DEFAULT_MODELS

SYSTEM = """You are AIPP Project Intelligence.
Analyze ONLY the supplied project material.
Return JSON with exactly:
{"findings":[{"type":string,"claim":string,"evidence":[{"file_name":string,"quote":string}]}],
 "proposals":[{"action":"REVIEW|RECONCILE|ADD","target":string,"reason":string,"next_action":string,
 "evidence":[{"file_name":string,"quote":string}],"requires_authority":true}]}
Never invent files, quotes, tasks, dates, or project facts.
Do not approve, execute, or mutate anything.
Every proposal must have at least one exact evidence quote from supplied material.
"""

def _bounded_text(documents, limit=60000):
    chunks, used = [], 0
    for doc in documents:
        text = str(doc.get("text") or "")
        if not text:
            continue
        chunk = f'<document file_name="{doc.get("name","")}">\n{text}\n</document>\n'
        if used + len(chunk) > limit:
            remaining = max(0, limit - used)
            chunk = chunk[:remaining]
        if chunk:
            chunks.append(chunk)
            used += len(chunk)
        if used >= limit:
            break
    return "".join(chunks)


def _document_chunks(documents, limit=60000):
    """Split the full Drive corpus into bounded, lossless document chunks."""
    chunks, current, used = [], [], 0
    for doc in documents:
        text = str(doc.get("text") or "")
        if not text:
            continue
        block = f'<document file_name="{doc.get("name","")}">\n{text}\n</document>\n'
        if current and used + len(block) > limit:
            chunks.append("".join(current))
            current, used = [], 0
        if len(block) <= limit:
            current.append(block)
            used += len(block)
            continue
        start = 0
        while start < len(block):
            chunks.append(block[start:start + limit])
            start += limit
        current, used = [], 0
    if current:
        chunks.append("".join(current))
    return chunks


def _validate(result, documents):
    if not isinstance(result, dict):
        raise ValueError("AI result must be an object")
    source_text = {str(d.get("name")): str(d.get("text") or "") for d in documents}
    proposals = result.get("proposals", [])
    if not isinstance(proposals, list):
        raise ValueError("AI proposals must be a list")
    clean = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        evidence = proposal.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            continue
        valid_evidence = []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            name = str(item.get("file_name") or "")
            quote = str(item.get("quote") or "")
            if name in source_text and quote and quote in source_text[name]:
                valid_evidence.append({"file_name": name, "quote": quote})
        if not valid_evidence:
            continue
        action = str(proposal.get("action") or "").upper()
        if action not in {"REVIEW", "RECONCILE", "ADD"}:
            continue
        clean.append({
            "action": action,
            "target": str(proposal.get("target") or ""),
            "reason": str(proposal.get("reason") or ""),
            "next_action": str(proposal.get("next_action") or ""),
            "evidence": valid_evidence,
            "requires_authority": True,
            "status": "PROPOSED",
            "source": "ai-semantic-analysis",
        })
    findings = []
    for finding in result.get("findings", []):
        if not isinstance(finding, dict):
            continue
        evidence = finding.get("evidence")
        if not isinstance(evidence, list):
            continue
        valid_evidence = []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            name = str(item.get("file_name") or "")
            quote = str(item.get("quote") or "")
            if name in source_text and quote and quote in source_text[name]:
                valid_evidence.append({"file_name": name, "quote": quote})
        if valid_evidence:
            findings.append({
                "type": str(finding.get("type") or "finding"),
                "claim": str(finding.get("claim") or ""),
                "evidence": valid_evidence,
            })
    if not clean and findings:
        for index, finding in enumerate(findings, start=1):
            clean.append({
                "action": "REVIEW",
                "target": f"Finding {index}: {finding['type']}",
                "reason": finding["claim"],
                "next_action": "Kaynak belgeleri karşılaştırıp gerekli düzeltmeyi hazırlamak ve uygulama öncesinde doğrulamak.",
                "evidence": finding["evidence"],
                "requires_authority": True,
                "status": "PROPOSED",
                "source": "ai-semantic-analysis-finding",
            })
    return {"proposals": clean, "findings": findings}


def _telemetry(**fields):
    safe = " ".join(f"{key}={str(value).replace(chr(10), " ").replace(chr(13), " ")}" for key, value in fields.items())
    print(f"AIPP_AI_SEMANTIC {safe}", flush=True)


def analyze_with_ai(documents):
    """Return validated holistic AI proposals, or an explicit unavailable result."""
    if os.environ.get("AIPP_SEMANTIC_ANALYSIS", "").strip().lower() not in {"1", "true", "yes", "on"}:
        _telemetry(enabled=False, available=False, reason="semantic_analysis_disabled")
        return {"enabled": False, "available": False, "reason": "semantic analysis disabled"}
    if not documents:
        _telemetry(enabled=True, available=False, reason="no_readable_documents")
        return {"enabled": True, "available": False, "reason": "no readable documents"}

    chunks = _document_chunks(documents)
    partials = []
    try:
        enabled = {
            "gemini": bool(os.environ.get("GEMINI_API_KEY")),
            "claude": bool(os.environ.get("ANTHROPIC_API_KEY")),
        }
        registry = tuple(model for model in DEFAULT_MODELS if enabled.get(model.provider, False))
        if not registry:
            _telemetry(enabled=True, available=False, provider="NONE", reason="no_configured_provider_key")
            return {"enabled": True, "available": False, "reason": "No configured AI provider key"}

        ordered = sorted(registry, key=lambda model: model.priority, reverse=True)

        def run_model(prompt):
            errors = []
            for model_spec in ordered:
                provider = model_spec.provider
                try:
                    task = {
                        "capabilities": ("text", "reasoning"),
                        "prompt": prompt,
                        "system": SYSTEM,
                        "json_output": True,
                        "max_output_tokens": 4096,
                    }
                    result = ExecutionResult(
                        provider,
                        model_spec.model,
                        configured_adapter(provider).execute(model_spec, task),
                    )
                    return result
                except (ProviderError, ValueError, TypeError, KeyError, IndexError) as exc:
                    errors.append(f"{provider}:{type(exc).__name__}:{exc}")
            raise ProviderError("all configured AI providers failed: " + " | ".join(errors))

        # First pass: every readable Drive document is included in one or more
        # bounded batches. Nothing is silently dropped because the workspace
        # exceeds one model context window.
        for index, chunk in enumerate(chunks, start=1):
            prompt = (
                f"Analyze workspace batch {index}/{len(chunks)} as evidence for one coherent project. "
                "Do not treat this batch as the whole workspace. Identify concrete contradictions, "
                "overlaps, obsolete decisions, unresolved tensions, dependencies, and meaningful gaps. "
                "Use exact evidence quotes. Do not invent facts. Return only the required JSON.\n\n"
                + chunk
            )
            result = run_model(prompt)
            batch_validated = _validate(result.output, documents)
            partials.append({
                "batch": index,
                "provider": result.provider,
                "model": result.model,
                "findings": batch_validated["findings"],
                "proposals": batch_validated["proposals"],
            })

        # Second pass: synthesize the evidence from every batch into one
        # project-level result. The final model sees the complete batch set,
        # not just the first slice of the Drive.
        synthesis_material = json.dumps(partials, ensure_ascii=False)
        synthesis_prompt = (
            "Synthesize the ENTIRE supplied Google Drive workspace as one coherent project. "
            "The following are evidence-backed findings from EVERY workspace batch. "
            "Merge duplicates, identify cross-document relationships, distinguish current state "
            "from historical/obsolete material, and produce only the most important actionable "
            "project-level findings and proposals. Do not invent anything. Every final proposal "
            "must retain an exact quote from the original supplied documents. "
            "Explain reasons in plain language for a non-technical project owner. "
            "Return only the required JSON.\n\n"
            + synthesis_material
        )
        final_result = run_model(synthesis_prompt)
        final_validated = _validate(final_result.output, documents)
        _telemetry(
            enabled=True,
            available=True,
            provider=final_result.provider,
            model=final_result.model,
            batches=len(chunks),
            documents=len(documents),
            findings=len(final_validated["findings"]),
            proposals=len(final_validated["proposals"]),
        )
        return {
            "enabled": True,
            "available": True,
            "provider": final_result.provider,
            "model": final_result.model,
            "batches": len(chunks),
            "documents": len(documents),
            "findings": final_validated["findings"],
            "proposals": final_validated["proposals"],
        }
    except (ProviderError, ValueError, TypeError, KeyError, IndexError) as exc:
        _telemetry(
            enabled=True,
            available=False,
            provider="FALLBACK",
            error_type=type(exc).__name__,
            reason=str(exc),
            batches=len(partials),
            documents=len(documents),
        )
        return {
            "enabled": True,
            "available": False,
            "reason": f"semantic analysis unavailable: {exc}",
            "batches": len(partials),
            "documents": len(documents),
        }

