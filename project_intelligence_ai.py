"""AI-assisted project reconciliation with deterministic validation.

The model proposes. The deterministic layer validates structure and preserves
the Authority Gate. No AI output is ever auto-approved or executed.
"""
import json
import os

from ai.executor import execute
from ai.providers import configured_adapter, ProviderError
from ai.model_router import DEFAULT_MODELS

SYSTEM = """You are AIPP Project Intelligence.
Analyze ONLY the supplied project material.
Return JSON with exactly:
{"findings":[{"type":string,"claim":string,"evidence":[{"file_name":string,"quote":string}]}],
 "proposals":[{"action":"REVIEW|RECONCILE|ADD","target":string,"reason":string,
 "evidence":[{"file_name":string,"quote":string}],"requires_authority":true}]}
Never invent files, quotes, tasks, dates, or project facts.
Do not approve, execute, or mutate anything.
Every proposal must have at least one exact evidence quote from supplied material.
"""

def _bounded_text(documents, limit=120000):
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
            "evidence": valid_evidence,
            "requires_authority": True,
            "status": "PROPOSED",
            "source": "ai-semantic-analysis",
        })
    return {"proposals": clean, "findings": result.get("findings", [])}


def analyze_with_ai(documents):
    """Return validated AI proposals, or an explicit unavailable result."""
    if os.environ.get("AIPP_SEMANTIC_ANALYSIS", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return {"enabled": False, "available": False, "reason": "semantic analysis disabled"}
    if not documents:
        return {"enabled": True, "available": False, "reason": "no readable documents"}

    prompt = (
        "Analyze this workspace for contradictions, obsolete decisions, missing "
        "follow-up work, redundant material, and meaningful changes between sources. "
        "Do not infer beyond evidence.\n\n"
        + _bounded_text(documents)
    )
    task = {
        "capabilities": ("text", "reasoning"),
        "prompt": prompt,
        "system": SYSTEM,
        "json_output": True,
        "max_output_tokens": 4096,
    }
    try:
        enabled = {
            "gemini": bool(os.environ.get("GEMINI_API_KEY")),
            "claude": bool(os.environ.get("ANTHROPIC_API_KEY")),
        }
        registry = tuple(model for model in DEFAULT_MODELS if enabled.get(model.provider, False))
        if not registry:
            return {"enabled": True, "available": False, "reason": "No configured AI provider key"}
        provider = max(registry, key=lambda model: model.priority).provider
        selected = execute(task, configured_adapter(provider), registry=registry)
        validated = _validate(selected.output, documents)
    except (ProviderError, ValueError, TypeError, KeyError, IndexError) as exc:
        return {
            "enabled": True,
            "available": False,
            "reason": f"semantic analysis unavailable: {exc}",
        }
    return {
        "enabled": True,
        "available": True,
        "provider": selected.provider,
        "model": selected.model,
        "findings": validated["findings"],
        "proposals": validated["proposals"],
    }
