from project_intelligence import analyze_documents


def test_detects_conflicting_task_state_and_keeps_authority_required():
    result = analyze_documents([
        {"id": "1", "name": "PROJECT_BOOT.md", "text": "| **TASK-01** | Build panel | `COMPLETED` | - |"},
        {"id": "2", "name": "decision-log.md", "text": "| TASK-01 | Build panel | BLOCKED | dependency |"},
    ])
    assert result["version"] == "2"
    proposal = next(p for p in result["proposals"] if p["finding_type"] == "status_conflict")
    assert proposal["target"] == "TASK-01"
    assert proposal["requires_authority"] is True


def test_detects_definition_drift():
    result = analyze_documents([
        {"id": "1", "name": "PROJECT_BOOT.md", "text": "| **TASK-01** | Build panel | `FUTURE` | - |"},
        {"id": "2", "name": "history.md", "text": "| TASK-01 | Build AI panel | FUTURE | - |"},
    ])
    assert any(f["type"] == "task_definition_drift" for f in result["findings"])


def test_detects_newer_supporting_source():
    result = analyze_documents([
        {"id": "1", "name": "PROJECT_BOOT.md", "modifiedTime": "2026-09-01T00:00:00Z",
         "text": "| **TASK-01** | Build panel | `FUTURE` | - |"},
        {"id": "2", "name": "decision-log.md", "modifiedTime": "2026-09-02T00:00:00Z",
         "text": "| TASK-01 | Build panel | COMPLETED | - |"},
    ])
    proposal = next(p for p in result["proposals"] if p["finding_type"] == "newer_supporting_source")
    assert proposal["action"] == "REVIEW"


def test_generic_note_does_not_become_a_task():
    result = analyze_documents([
        {"id": "1", "name": "notes.md", "text": "A useful observation with no requested action."},
    ])
    assert any(p["finding_type"] == "workspace_review_required" for p in result["proposals"])
    assert not any(p["finding_type"] == "actionable_untracked_idea" for p in result["proposals"])


def test_actionable_idea_without_task_id_becomes_passive_proposal():
    result = analyze_documents([
        {"id": "1", "name": "ideas.md", "text": "Next step: implement a verification panel."},
    ])
    proposal = next(p for p in result["proposals"] if p["finding_type"] == "actionable_untracked_idea")
    assert proposal["requires_authority"] is True
    assert proposal["status"] == "PROPOSED"


def test_near_duplicate_is_flagged():
    text = "AIPP verifies execution artifacts before completion and requires authority approval."
    result = analyze_documents([
        {"id": "1", "name": "notes-a.md", "text": text},
        {"id": "2", "name": "notes-b.md", "text": text},
    ])
    assert any(f["type"] == "near_duplicate" for f in result["findings"])


def test_classifies_canonical_protocol_and_reference():
    result = analyze_documents([
        {"id": "1", "name": "PROJECT_BOOT.md", "text": "state"},
        {"id": "2", "name": "AIPP.md", "text": "protocol"},
        {"id": "3", "name": "architecture.md", "text": "reference"},
    ])
    kinds = {item["file_name"]: item["kind"] for item in result["evidence"]}
    assert kinds == {
        "PROJECT_BOOT.md": "project_state",
        "AIPP.md": "protocol",
        "architecture.md": "reference",
    }

def test_actionable_proposal_preserves_source_type_and_exact_quote():
    source = "Next step: implement a verification panel."
    result = analyze_documents([
        {
            "id": "pdf-1",
            "name": "product-notes.pdf",
            "mimeType": "application/pdf",
            "text": source,
        },
    ])
    proposal = next(p for p in result["proposals"] if p["finding_type"] == "actionable_untracked_idea")
    evidence = proposal["evidence"][0]
    assert evidence["file_name"] == "product-notes.pdf"
    assert evidence["file_type"] == "PDF"
    assert evidence["mime_type"] == "application/pdf"
    assert evidence["source"] == "Google Drive"
    assert evidence["quote"] in source
    assert "Next step" in evidence["quote"]



def test_code_artifact_does_not_become_untracked_actionable_proposal():
    result = analyze_documents([
        {
            "id": "zip-1",
            "name": "AIPP_Runner_v1.0.zip",
            "mimeType": "application/zip",
            "text": "Next step: implement the runner and add the missing verification.",
        },
    ])
    assert any(p["finding_type"] == "workspace_review_required" for p in result["proposals"])
    assert not any(p["finding_type"] == "actionable_untracked_idea" for p in result["proposals"])
    assert result["evidence"][0]["kind"] == "artifact"

# CI trigger: no functional change.
