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
Write all user-facing narrative text in Turkish (Türkçe), including finding claims and proposal target descriptions, reasons, and next actions. Preserve exact filenames, task IDs, identifiers, and evidence quotes unchanged; do not translate quoted source evidence. Keep JSON keys and action enum values in English exactly as specified.
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
    safe = " ".join("{}={}".format(key, str(value).replace(chr(10), " ").replace(chr(13), " ")) for key, value in fields.items())
    print(f"AIPP_AI_SEMANTIC {safe}", flush=True)


def analyze_with_ai(documents):
    """Analyze all chunks while preserving an explicit completeness contract."""
    if os.environ.get("AIPP_SEMANTIC_ANALYSIS", "").strip().lower() not in {"1", "true", "yes", "on"}:
        _telemetry(enabled=False, available=False, status="DISABLED", reason="semantic_analysis_disabled")
        return {"enabled": False, "available": False, "status": "DISABLED", "complete": False,
                "reason": "semantic analysis disabled"}
    if not documents:
        _telemetry(enabled=True, available=False, status="UNAVAILABLE", reason="no_readable_documents")
        return {"enabled": True, "available": False, "status": "UNAVAILABLE", "complete": False,
                "reason": "no readable documents"}

    chunks = _document_chunks(documents)
    partials = []
    failed_batches = []
    batch_errors = []
    unavailable_providers = set()

    def merge_partials():
        merged = {"findings": [], "proposals": []}
        seen = {"findings": set(), "proposals": set()}
        for partial in partials:
            for key in ("findings", "proposals"):
                for item in partial.get(key, []):
                    fingerprint = json.dumps(item, sort_keys=True, ensure_ascii=False)
                    if fingerprint not in seen[key]:
                        seen[key].add(fingerprint)
                        merged[key].append(item)
        return merged

    try:
        enabled = {
            "gemini": bool(os.environ.get("GEMINI_API_KEY")),
            "groq": bool(os.environ.get("GROQ_API_KEY")),
            "openrouter": bool(os.environ.get("OPENROUTER_API_KEY")),
            "claude": bool(os.environ.get("ANTHROPIC_API_KEY")),
        }
        registry = tuple(model for model in DEFAULT_MODELS if enabled.get(model.provider, False))
        if not registry:
            _telemetry(enabled=True, available=False, status="UNAVAILABLE",
                       provider="NONE", reason="no_configured_provider_key")
            return {"enabled": True, "available": False, "status": "UNAVAILABLE", "complete": False,
                    "reason": "No configured AI provider key"}

        ordered = sorted(registry, key=lambda model: model.priority, reverse=True)

        def run_model(prompt):
            errors = []
            for model_spec in ordered:
                provider = model_spec.provider
                if provider in unavailable_providers:
                    continue
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
                except Exception as exc:
                    # A provider is quarantined for this scan after a transport,
                    # quota, response-shape, or JSON failure. Other providers
                    # remain eligible for fallback on the current and later batches.
                    detail = str(exc) or type(exc).__name__
                    errors.append(f"{provider}:{type(exc).__name__}:{detail[:240]}")
                    unavailable_providers.add(provider)
            raise ProviderError("all configured AI providers failed: " + " | ".join(errors))

        for index, chunk in enumerate(chunks, start=1):
            prompt = (
                f"Analyze workspace batch {index}/{len(chunks)} as evidence for one coherent project. "
                "Do not treat this batch as the whole workspace. Identify concrete contradictions, "
                "overlaps, obsolete decisions, unresolved tensions, dependencies, and meaningful gaps. "
                "Use exact evidence quotes. Do not invent facts. Return only the required JSON.\n\n"
                + chunk
            )
            try:
                result = run_model(prompt)
                batch_validated = _validate(result.output, documents)
                partials.append({
                    "batch": index,
                    "provider": result.provider,
                    "model": result.model,
                    "findings": batch_validated["findings"],
                    "proposals": batch_validated["proposals"],
                })
            except (ProviderError, ValueError, TypeError, KeyError, IndexError) as exc:
                failed_batches.append(index)
                batch_errors.append(f"batch={index}:{type(exc).__name__}:{str(exc)[:240]}")
                # If every configured provider is unavailable, later batches
                # cannot succeed in this scan. Mark them explicitly as unprocessed.
                if len(unavailable_providers) >= len(ordered):
                    break

        processed_batches = {item["batch"] for item in partials}
        failed_set = set(failed_batches)
        unprocessed_batches = [
            index for index in range(1, len(chunks) + 1)
            if index not in processed_batches and index not in failed_set
        ]

        # A failed batch makes the corpus analysis incomplete. Do not synthesize
        # a misleading "whole workspace" answer from a partial corpus.
        if failed_batches or unprocessed_batches:
            merged = merge_partials()
            if not partials:
                reason = "semantic analysis unavailable: " + " | ".join(batch_errors)
                _telemetry(enabled=True, available=False, status="UNAVAILABLE",
                           provider="FALLBACK", expected_batches=len(chunks),
                           failed_batches=failed_batches, unprocessed_batches=unprocessed_batches,
                           documents=len(documents), reason=reason[:500])
                return {
                    "enabled": True, "available": False, "status": "UNAVAILABLE", "complete": False,
                    "reason": reason[:1000], "batches": 0, "expected_batches": len(chunks),
                    "failed_batches": failed_batches, "unprocessed_batches": unprocessed_batches,
                    "documents": len(documents),
                }
            _telemetry(enabled=True, available=True, status="PARTIAL",
                       provider="PARTIAL_BATCH_MERGE", batches=len(partials),
                       expected_batches=len(chunks), failed_batches=failed_batches,
                       unprocessed_batches=unprocessed_batches, documents=len(documents),
                       findings=len(merged["findings"]), proposals=len(merged["proposals"]),
                       warning=" | ".join(batch_errors)[:500])
            return {
                "enabled": True, "available": True, "status": "PARTIAL", "complete": False,
                "provider": "PARTIAL_BATCH_MERGE", "model": "validated-batch-results",
                "batches": len(partials), "expected_batches": len(chunks),
                "failed_batches": failed_batches, "unprocessed_batches": unprocessed_batches,
                "documents": len(documents), "findings": merged["findings"],
                "proposals": merged["proposals"], "warnings": batch_errors[:20],
            }

        # Only a complete first pass is eligible for cross-batch synthesis.
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
        try:
            final_result = run_model(synthesis_prompt)
            final_validated = _validate(final_result.output, documents)
            _telemetry(enabled=True, available=True, status="COMPLETE",
                       provider=final_result.provider, model=final_result.model,
                       batches=len(chunks), expected_batches=len(chunks), documents=len(documents),
                       findings=len(final_validated["findings"]), proposals=len(final_validated["proposals"]))
            return {
                "enabled": True, "available": True, "status": "COMPLETE", "complete": True,
                "provider": final_result.provider, "model": final_result.model,
                "batches": len(chunks), "expected_batches": len(chunks),
                "documents": len(documents), "findings": final_validated["findings"],
                "proposals": final_validated["proposals"],
            }
        except (ProviderError, ValueError, TypeError, KeyError, IndexError) as synthesis_error:
            merged = merge_partials()
            _telemetry(enabled=True, available=True, status="PARTIAL",
                       provider="PARTIAL_BATCH_MERGE", model="validated-batch-results",
                       synthesis="unavailable", batches=len(partials), expected_batches=len(chunks),
                       documents=len(documents), findings=len(merged["findings"]),
                       proposals=len(merged["proposals"]), warning=str(synthesis_error)[:240])
            return {
                "enabled": True, "available": True, "status": "PARTIAL", "complete": False,
                "provider": "PARTIAL_BATCH_MERGE", "model": "validated-batch-results",
                "batches": len(partials), "expected_batches": len(chunks), "documents": len(documents),
                "findings": merged["findings"], "proposals": merged["proposals"],
                "synthesis_warning": str(synthesis_error)[:500],
            }
    except Exception as exc:
        # Fail closed at the outer boundary, while preserving diagnostics and
        # never claiming the semantic pass completed.
        merged = merge_partials()
        if partials:
            _telemetry(enabled=True, available=True, status="PARTIAL",
                       provider="PARTIAL_BATCH_MERGE", batches=len(partials),
                       expected_batches=len(chunks), documents=len(documents),
                       findings=len(merged["findings"]), proposals=len(merged["proposals"]),
                       warning=f"{type(exc).__name__}:{str(exc)[:240]}")
            return {
                "enabled": True, "available": True, "status": "PARTIAL", "complete": False,
                "provider": "PARTIAL_BATCH_MERGE", "model": "validated-batch-results",
                "batches": len(partials), "expected_batches": len(chunks), "documents": len(documents),
                "findings": merged["findings"], "proposals": merged["proposals"],
                "warning": f"{type(exc).__name__}:{str(exc)[:500]}",
            }
        _telemetry(enabled=True, available=False, status="UNAVAILABLE", provider="FALLBACK",
                   error_type=type(exc).__name__, reason=str(exc)[:500],
                   batches=0, expected_batches=len(chunks), documents=len(documents))
        return {
            "enabled": True, "available": False, "status": "UNAVAILABLE", "complete": False,
            "reason": f"semantic analysis unavailable: {type(exc).__name__}: {str(exc)[:500]}",
            "batches": 0, "expected_batches": len(chunks), "documents": len(documents),
        }
