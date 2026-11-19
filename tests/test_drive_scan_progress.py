import threading

import aipp_drive_runtime as drive


def test_drive_scan_reports_progress_and_isolates_one_file_failure(monkeypatch, capsys):
    files = [
        {"id": "one", "name": "one.md", "mimeType": "text/markdown"},
        {"id": "two", "name": "two.md", "mimeType": "text/markdown"},
        {"id": "three", "name": "three.md", "mimeType": "text/markdown"},
    ]
    second_started = threading.Event()

    monkeypatch.setattr(drive, "list_workspace_tree", lambda *_: files)

    def read(_token, item):
        if item["id"] == "one":
            assert second_started.wait(timeout=2)
            return "TASK-01 is an active proposal"
        if item["id"] == "two":
            second_started.set()
            raise RuntimeError("simulated parser failure")
        return "TASK-03 is another active proposal"

    monkeypatch.setattr(drive, "read_file_text", read)

    candidates, documents, summary = drive.discover_task_candidates(
        "fake-token", "root", include_documents=True
    )

    output = capsys.readouterr().out
    progress = [
        line for line in output.splitlines()
        if line.startswith("DRIVE_READ_PROGRESS ")
    ]

    assert len(progress) == 3
    assert sorted(int(line.split("completed=")[1].split()[0]) for line in progress) == [1, 2, 3]
    assert {line.split("name=")[1].split(" readable=")[0] for line in progress} == {
        "'one.md'", "'two.md'", "'three.md'"
    }
    assert "DRIVE_FILE_READ_ERROR name='two.md' type=RuntimeError" in output

    # Results remain in Drive listing order even when reads finish out of order.
    assert [item["id"] for item in candidates] == ["one", "three"]
    assert [item["name"] for item in documents] == ["one.md", "three.md"]
    assert [item["name"] for item in summary["files"]] == ["one.md", "two.md", "three.md"]
    assert summary["files_scanned"] == 3
    assert summary["documents_read"] == 2
    assert summary["documents_unreadable"] == 1
