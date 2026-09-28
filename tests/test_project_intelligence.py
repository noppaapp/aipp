from project_intelligence import analyze_documents


def test_analyzer_indexes_document_kinds():
    result = analyze_documents([
        {"id": "1", "name": "PROJECT_BOOT.md", "text": "# boot"},
        {"id": "2", "name": "decision_log.md", "text": "# history"},
        {"id": "3", "name": "idea_notes.md", "text": "# ideas"},
        {"id": "4", "name": "reference.md", "text": "# ref"},
    ])
    assert result["documents_scanned"] == 4
    assert result["kind_counts"] == {
        "canonical": 1,
        "historical": 1,
        "idea": 1,
        "reference": 1,
    }


def test_analyzer_creates_only_explicit_evidence_backed_proposals():
    result = analyze_documents([
        {
            "id": "idea-1",
            "name": "idea_notes.md",
            "text": "[AIPP-MODIFY] Noppa Protocol\n",
        },
        {
            "id": "ref-1",
            "name": "random.md",
            "text": "Users might like this.\n",
        },
    ])
    assert len(result["proposals"]) == 1
    proposal = result["proposals"][0]
    assert proposal["action"] == "MODIFY"
    assert proposal["target"] == "Noppa Protocol"
    assert proposal["requires_authority"] is True
    assert proposal["evidence"][0]["file_name"] == "idea_notes.md"


def test_analyzer_does_not_invent_changes_from_plain_text():
    result = analyze_documents([
        {"id": "1", "name": "history.md", "text": "old decision\n"},
        {"id": "2", "name": "ideas.md", "text": "maybe change the protocol\n"},
    ])
    assert result["proposals"] == []
