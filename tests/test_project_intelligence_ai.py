import json

from project_intelligence_ai import _validate


def test_ai_proposal_requires_exact_source_quote():
    documents = [{"name": "PROJECT_BOOT.md", "text": "TASK-01 is FUTURE."}]
    result = _validate({
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
    result = _validate({
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
    result = _validate({
        "findings": [],
        "proposals": [{
            "action": "EXECUTE",
            "target": "x",
            "reason": "x",
            "evidence": [{"file_name": "notes.md", "quote": "Review this."}],
        }],
    }, documents)
    assert result["proposals"] == []
