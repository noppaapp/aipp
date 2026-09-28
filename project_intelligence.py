"""Project-content intelligence for AIPP.

This module deliberately stays deterministic and evidence-backed. It builds a
workspace evidence index and turns only explicit, source-backed change
directives into passive proposals. It never approves, executes, or mutates
project content.
"""

import re
from collections import defaultdict

DIRECTIVE_RE = re.compile(
    r"^\s*\[AIPP-(ADD|MODIFY|REMOVE)\]\s+(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
HISTORY_WORDS = ("history", "histor", "archive", "changelog", "decision", "log", "record")
IDEA_WORDS = ("idea", "ideas", "note", "notes", "proposal", "brainstorm", "draft")
CANONICAL_NAMES = {"PROJECT_BOOT.md", "AIPP.md"}


def _kind(name):
    lower = name.lower()
    if name in CANONICAL_NAMES:
        return "canonical"
    if any(word in lower for word in HISTORY_WORDS):
        return "historical"
    if any(word in lower for word in IDEA_WORDS):
        return "idea"
    return "reference"


def analyze_documents(documents):
    evidence = []
    proposals = []
    counts = defaultdict(int)

    for doc in documents or []:
        name = str(doc.get("name") or "")
        text = doc.get("text")
        if text is None:
            continue
        kind = _kind(name)
        counts[kind] += 1
        evidence.append({
            "file_id": doc.get("id"),
            "file_name": name,
            "kind": kind,
            "modifiedTime": doc.get("modifiedTime"),
            "text_length": len(text),
        })
        for match in DIRECTIVE_RE.finditer(text):
            action = match.group(1).upper()
            target = match.group(2).strip()
            if not target:
                continue
            proposals.append({
                "action": action,
                "target": target,
                "reason": "Explicit AIPP change directive found in workspace material.",
                "evidence": [{"file_id": doc.get("id"), "file_name": name}],
                "requires_authority": True,
                "status": "PROPOSED",
            })

    return {
        "version": "1",
        "documents_scanned": len(evidence),
        "kind_counts": dict(counts),
        "evidence": evidence,
        "proposals": proposals,
    }
