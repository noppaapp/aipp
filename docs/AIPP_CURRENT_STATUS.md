# AIPP Current Status Report

**Date:** 2026-08-25
**Repository:** `noppaapp/aipp`
**Branch:** `main`
**Purpose:** Current factual checkpoint after the ephemeral-state migration and the latest regression.

## 1. Executive Status

**AIPP is NOT currently in a verified green/final state.**

The architectural migration away from Git-persisted runtime state is substantially implemented, but the latest runner change introduced regressions in the existing test contract. The repository must therefore be treated as **HALTED / REGRESSION INVESTIGATION**, not as finished.

The immediate priority is to restore the last known-good runner behavior without reintroducing `aipp_state.json` persistence.

## 2. Architecture Currently Intended

The canonical separation is:

`Google Drive PROJECT_BOOT.md` -> ephemeral execution transport -> in-memory AIPP runtime state -> execution/verification artifacts -> process ends

Responsibilities:

- **Google Drive:** Canonical Workspace and canonical project-state source.
- **PROJECT_BOOT.md:** Canonical project bootstrap/project-state input.
- **Git:** AIPP protocol code, implementation, tests and version history only.
- **GitHub Actions:** Execution environment and orchestration.
- **Python runner memory:** Ephemeral runtime state only.
- **Authority Gate:** Human approval remains mandatory. AIPP must not autonomously move a proposal to NOW.

This separation is documented in the existing architecture status report. fileciteturn315file0L2-L6

## 3. Completed Migration Work

The following architectural changes are already present in the repository:

1. Automatic `git commit` / `git push` of `aipp_state.json` was removed from the main pipeline.
2. Legacy state synchronization workflow was removed.
3. Legacy execution-proof workflow that recreated the obsolete local-state model was removed.
4. `aipp_state.json` is guarded by `.gitignore`.
5. `aipp_drive_runtime.py` no longer searches for, downloads, parses, or writes `aipp_state.json`.
6. Drive runtime discovers `PROJECT_BOOT.md` and publishes its content through an ephemeral GitHub Actions environment transport rather than materializing it into the repository workspace. fileciteturn316file0L2-L6
7. GitHub Actions concurrency serialization is enabled with `cancel-in-progress: false`. fileciteturn318file0L2-L5
8. The workflow explicitly fails if `aipp_state.json` or a materialized `PROJECT_BOOT.md` appears in the repository workspace. fileciteturn318file0L2-L5
9. The runner no longer has an autonomous `RUN` path that silently approves work.

## 4. Current Drive Runtime Status

The Drive runtime has progressed through these states:

- Earlier: `PROJECT_BOOT.md not found`.
- Then: Drive discovery successfully found the canonical file.
- Current known successful discovery signal:
  - `DRIVE_TREE_DISCOVERY folders=4 files=25`
  - `DRIVE_PROJECT_BOOT_FOUND ... mimeType=text/x-markdown`
- The next failure was that the file content could not initially be read.
- The current `aipp_drive_runtime.py` contains the canonical read path and ephemeral transport via `GITHUB_ENV`. fileciteturn316file0L2-L6

The Drive discovery layer also contains `reconcile_discovered_tasks`, which maps discovered task identifiers into FUTURE proposals without crossing the Authority Gate. fileciteturn316file0L2-L6

## 5. Current Runner Regression

The latest runner change is the current regression point.

The current `aipp_runner.py` initializes runtime state in memory and reads canonical boot content from the ephemeral `AIPP_PROJECT_BOOT_B64` transport. fileciteturn317file0L2-L6

However, the latest test run produced:

- **14 passed**
- **5 failed**

Failures:

1. `tests/e2e/test_session_continuation.py::test_session_restart_does_not_restore_ephemeral_authority_state`
2. `tests/e2e/test_session_continuation.py::test_session_restart_reloads_canonical_project_boot`
3. `tests/test_project_bootstrap.py::test_project_bootstrap_maps_canonical_workspace`
4. `tests/test_runner.py::test_bootstrap_is_ephemeral`
5. `tests/test_runner.py::test_authority_gate_does_not_persist_across_sessions`

Observed symptoms include:

- `active_project` returned as `None` where existing tests expect the canonical boot project.
- `REQUEST_APPROVAL` exits with code 1.
- Existing bootstrap/session behavior is therefore not currently preserved.

## 6. Critical Interpretation of the Regression

This regression must **not** be interpreted as evidence that the ephemeral architecture is wrong.

It indicates that the implementation change did not preserve the pre-existing runner/test contract.

The correct response is:

**Do not restore `aipp_state.json`. Do not weaken the new architecture. Restore compatibility with the existing bootstrap and Authority Gate behavior using the smallest possible code change.**

In particular, the runner should not be rewritten wholesale again. The next repair must first inspect the last known-good implementation and the failing tests, then make a minimal targeted change.

## 7. Authority Gate Status

The architectural direction remains:

- Runtime memory may contain a pending approval during one execution.
- Runtime memory must disappear when the process ends.
- Approval continuity across sessions must come from a canonical human-controlled source, not from `aipp_state.json`.
- AIPP must never infer approval merely because a previous process requested approval.
- A deterministic Proposal ID + Task ID model remains a candidate for the canonical Authority record, but its exact implementation is **not yet considered finalized**.

No implementation should be declared final until this governance model is tested end-to-end.

## 8. Concurrency Status

GitHub Actions workflow-level concurrency is already enabled. This serializes executions of the main AIPP pipeline. fileciteturn318file0L2-L5

This is sufficient as an execution-level safeguard for the current read-only Drive architecture.

If AIPP later writes canonical state back to Drive, concurrency must additionally become revision-aware. A changed Drive revision/source snapshot must cause HALT rather than Last-Write-Wins overwrite.

## 9. What Must NOT Be Done

- Do not reintroduce `aipp_state.json` as canonical state.
- Do not add Git commits for runtime state.
- Do not restore the removed legacy workflows just to make CI green.
- Do not make `RUN` autonomously approve a task.
- Do not rewrite the entire runner to solve five failing tests.
- Do not declare the current branch final while tests are red.
- Do not treat a passing workflow as proof of architectural correctness unless the relevant behavioral tests also pass.

## 10. Immediate Next Step

**HALT implementation.**

First compare the current `aipp_runner.py` with the last known-good version and inspect the five failing tests. Identify the exact behavioral contract that was accidentally removed or changed.

Then apply one minimal repair and rerun the full test suite.

Only after the suite is green should the next architectural layer be resumed.

## 11. Current Verdict

### Architecture
**Direction: APPROVED / coherent**

### Git/runtime separation
**Implemented**

### Drive canonical PROJECT_BOOT discovery
**Implemented, with runtime read/transport path present**

### Ephemeral runtime state
**Implemented in current design**

### Authority Gate
**Conceptually preserved, implementation continuity not yet fully verified**

### Concurrency
**Workflow-level serialization implemented**

### Automated test status
**FAILED: 14 passed / 5 failed**

### Release/final status
**NOT FINAL. HALTED pending regression repair.**

## 12. Golden Rule for the Next Change

> Preserve the architecture. Restore the behavior. Change the smallest possible surface.

This report is a factual checkpoint, not an authorization to redesign AIPP.
