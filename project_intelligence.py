"""Deterministic project-content reconciliation for AIPP.

Evidence-first only. It never approves, executes, or mutates project content.
"""
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

TASK_RE = re.compile(r"\bTASK[-_ ]?\d+\b", re.IGNORECASE)
TABLE_TASK_RE = re.compile(
    r"\|\s*[`*]*(TASK[-_ ]?\d+)[`*]*\s*\|\s*([^|]+?)\s*\|\s*[`*]*([A-Z][A-Z _-]+?)[`*]*\s*\|",
    re.IGNORECASE,
)
SUPERSEDES_RE = re.compile(
    r"\b(?:supersedes|superseded by|replaces|replaced by|deprecated by|obsolete)\b",
    re.IGNORECASE,
)
ACTION_RE = re.compile(
    r"\b(?:must|should|need(?:s|ed)? to|todo|next step|implement|add|remove|replace|fix|resolve|investigate|decide|define)\b",
    re.IGNORECASE,
)
TOKEN_RE = re.compile(r"[a-z0-9_/-]{3,}", re.IGNORECASE)
KIND_WORDS = {
    "historical": ("history", "histor", "archive", "changelog", "decision", "decision-log", "record"),
    "idea": ("idea", "ideas", "note", "notes", "proposal", "brainstorm", "draft", "backlog"),
}
ARTIFACT_EXTENSIONS = {".zip", ".py", ".js", ".ts", ".toml", ".yaml", ".yml", ".json", ".xml", ".csv"}
CANONICAL = {"PROJECT_BOOT.md": "project_state", "AIPP.md": "protocol"}


def _kind(name, text):
    if name in CANONICAL:
        return CANONICAL[name]
    lower = name.lower()
    suffix = Path(name).suffix.lower()
    if suffix in ARTIFACT_EXTENSIONS:
        return "artifact"
    for kind, words in KIND_WORDS.items():
        if any(word in lower for word in words):
            return kind
    if SUPERSEDES_RE.search(text or ""):
        return "historical"
    if ACTION_RE.search(text or ""):
        return "proposal_candidate"
    return "reference"


def _tokens(text):
    return set(TOKEN_RE.findall((text or "").lower()))


def _similarity(a, b):
    left, right = _tokens(a), _tokens(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _task_records(doc):
    records = []
    for match in TABLE_TASK_RE.finditer(doc.get("text") or ""):
        task_id = match.group(1).upper().replace("_", "-").replace(" ", "-")
        records.append({
            "id": task_id,
            "description": " ".join(match.group(2).split()),
            "status": match.group(3).strip().upper(),
        })
    return records


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


SOURCE_TYPE_BY_MIME = {
    "application/pdf": "PDF",
    "text/plain": "Text",
    "text/markdown": "Markdown",
    "text/x-markdown": "Markdown",
    "text/csv": "CSV",
    "application/json": "JSON",
    "application/xml": "XML",
    "application/x-yaml": "YAML",
    "text/yaml": "YAML",
    "application/zip": "ZIP",
    "application/vnd.google-apps.document": "Google Docs",
    "application/vnd.google-apps.spreadsheet": "Google Sheets",
    "application/vnd.google-apps.presentation": "Google Slides",
}


def _source_type(doc):
    mime = str(doc.get("mimeType") or "").strip()
    if mime in SOURCE_TYPE_BY_MIME:
        return SOURCE_TYPE_BY_MIME[mime]
    name = str(doc.get("name") or "")
    suffix = name.rsplit(".", 1)[-1].upper() if "." in name else ""
    return suffix or "Unknown"


def _excerpt(text, needle=None, max_chars=600):
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    if needle:
        match = re.search(re.escape(str(needle)), normalized, re.IGNORECASE)
        if match:
            start = max(0, match.start() - 180)
            end = min(len(normalized), match.end() + 420)
            return " ".join(normalized[start:end].split())[:max_chars]
    for line in normalized.splitlines():
        line = " ".join(line.split())
        if line:
            return line[:max_chars]
    return normalized[:max_chars]


def _evidence(doc, reason, signal=None, excerpt=None):
    text = doc.get("text") or ""
    item = {
        "file_id": doc.get("id"),
        "file_name": doc.get("name"),
        "file_type": _source_type(doc),
        "mime_type": doc.get("mimeType"),
        "source": "Google Drive",
        "reason": reason,
        "quote": str(excerpt or _excerpt(text, signal)),
    }
    if signal:
        item["signal"] = signal
    return item


def analyze_documents(documents):
    docs = []
    for raw in documents or []:
        text = raw.get("text")
        if text is None:
            continue
        doc = dict(raw)
        doc["name"] = str(doc.get("name") or "")
        doc["kind"] = _kind(doc["name"], text)
        doc["text_length"] = len(text)
        doc["task_records"] = _task_records(doc)
        docs.append(doc)

    task_index = defaultdict(list)
    for doc in docs:
        for record in doc["task_records"]:
            task_index[record["id"]].append((doc, record))

    findings, proposals = [], []

    for task_id, entries in sorted(task_index.items()):
        statuses = {record["status"] for _, record in entries}
        descriptions = {record["description"] for _, record in entries}
        if len(statuses) > 1:
            evidence = [_evidence(doc, f"{task_id} is {record['status']} here", record["status"]) for doc, record in entries]
            findings.append({"type": "status_conflict", "task_id": task_id, "statuses": sorted(statuses), "evidence": evidence})
            proposals.append({
                "action": "RECONCILE", "target": task_id,
                "reason": f"Conflicting status values found for {task_id}: {', '.join(sorted(statuses))}.",
                "finding_type": "status_conflict", "evidence": evidence,
                "requires_authority": True, "status": "PROPOSED",
            })
        if len(descriptions) > 1:
            evidence = [_evidence(doc, f"{task_id} description differs", record["description"]) for doc, record in entries]
            findings.append({"type": "task_definition_drift", "task_id": task_id, "evidence": evidence})
            proposals.append({
                "action": "RECONCILE", "target": task_id,
                "reason": f"Multiple descriptions exist for {task_id}; canonical definition requires review.",
                "finding_type": "task_definition_drift", "evidence": evidence,
                "requires_authority": True, "status": "PROPOSED",
            })

    canonical = next((d for d in docs if d["name"] == "PROJECT_BOOT.md"), None)
    if canonical:
        canonical_time = _parse_time(canonical.get("modifiedTime"))
        canonical_tasks = {r["id"] for r in canonical["task_records"]}
        for doc in docs:
            if doc is canonical or doc["kind"] == "protocol":
                continue
            doc_time = _parse_time(doc.get("modifiedTime"))
            newer = bool(canonical_time and doc_time and doc_time > canonical_time)
            relevant = [r for r in doc["task_records"] if r["id"] in canonical_tasks]
            if newer and relevant:
                evidence = [_evidence(doc, f"newer supporting source mentions {r['id']}", r["status"]) for r in relevant]
                findings.append({
                    "type": "newer_supporting_source", "file_name": doc["name"],
                    "tasks": [r["id"] for r in relevant], "evidence": evidence,
                })
                proposals.append({
                    "action": "REVIEW", "target": doc["name"],
                    "reason": "A newer workspace source overlaps canonical task state and may require re-sync.",
                    "finding_type": "newer_supporting_source", "evidence": evidence,
                    "requires_authority": True, "status": "PROPOSED",
                })

    for i, left in enumerate(docs):
        for right in docs[i + 1:]:
            if left["kind"] == "protocol" or right["kind"] == "protocol":
                continue
            similarity = _similarity(left.get("text"), right.get("text"))
            if similarity >= 0.92 and left["name"] != right["name"]:
                evidence = [
                    _evidence(left, f"content similarity={similarity:.3f}"),
                    _evidence(right, f"content similarity={similarity:.3f}"),
                ]
                findings.append({
                    "type": "near_duplicate", "files": [left["name"], right["name"]],
                    "similarity": round(similarity, 3), "evidence": evidence,
                })
                proposals.append({
                    "action": "REVIEW", "target": f"{left['name']} / {right['name']}",
                    "reason": "Two workspace sources are near-duplicates; review which one is authoritative.",
                    "finding_type": "near_duplicate", "evidence": evidence,
                    "requires_authority": True, "status": "PROPOSED",
                })

    for doc in docs:
        if doc["kind"] not in {"idea", "proposal_candidate", "historical"}:
            continue
        text = doc.get("text") or ""
        if not ACTION_RE.search(text):
            continue
        task_ids = sorted({m.upper().replace("_", "-").replace(" ", "-") for m in TASK_RE.findall(text)})
        if task_ids:
            continue
        reason = "Actionable language found in workspace material without an existing TASK id."
        action_match = ACTION_RE.search(text)
        evidence = [_evidence(
            doc,
            reason,
            signal=action_match.group(0) if action_match else None,
            excerpt=_excerpt(text, action_match.group(0) if action_match else None),
        )]
        findings.append({"type": "actionable_untracked_idea", "file_name": doc["name"], "evidence": evidence})
        proposals.append({
            "action": "REVIEW", "target": doc["name"], "reason": reason,
            "finding_type": "actionable_untracked_idea", "evidence": evidence,
            "requires_authority": True, "status": "PROPOSED",
        })

    proposals.sort(key=lambda p: (p["finding_type"], p["target"], p["action"]))
    kind_counts = defaultdict(int)
    for doc in docs:
        kind_counts[doc["kind"]] += 1

    return {
        "version": "2",
        "engine": "deterministic-evidence-reconciliation",
        "documents_scanned": len(docs),
        "kind_counts": dict(sorted(kind_counts.items())),
        "findings": findings,
        "proposals": proposals,
        "evidence": [
            {
                "file_id": d.get("id"), "file_name": d["name"], "kind": d["kind"],
                "modifiedTime": d.get("modifiedTime"), "text_length": d["text_length"],
            }
            for d in docs
        ],
    }
