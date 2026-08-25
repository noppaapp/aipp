# AIPP Current Architecture Status

## Purpose

This document is a second-opinion briefing for architectural review of AIPP. It is not a protocol change and must not be treated as authority to modify the architecture.

## Identity

AIPP (AI Project Protocol) is not an AI. It is a deterministic project/workspace orchestration and execution protocol operating above AI sessions.

## Canonical architecture

- Google Drive is the Canonical Workspace and physical project reality.
- `PROJECT_BOOT.md` is the canonical project-state source currently consumed by the runtime workflow.
- Git is for AIPP protocol code, implementation, tests, and version history.
- Runtime state is ephemeral and must not be persisted to Git.
- AIPP must not autonomously move proposals to NOW. Authority Gate / human approval remains mandatory.
- Simulation and physical execution remain separate. A physical execution claim requires evidence from the target system.

## Migration already completed

1. Automatic Git commit/push of `aipp_state.json` was removed from the main pipeline.
2. The legacy `aipp_sync.yml` workflow that attempted to synchronize `aipp_state.json` was removed.
3. The main `AIPP Autonomous Pipeline` remains automatically triggered by relevant repository pushes and can still be manually dispatched when required.
4. A legacy `aipp-execution-proof.yml` workflow was removed because it still created and consumed a synthetic local `aipp_state.json`, contradicting the new runtime-state model.

## Recent failure and diagnosis

After `aipp_state.json` was removed from Git tracking, the legacy sync workflow failed with:

`FileNotFoundError: [Errno 2] No such file or directory: 'aipp_state.json'`

This was not evidence that the new architecture was broken. It proved that an obsolete workflow still depended on the removed state file. That workflow has now been removed.

## Main pipeline behavior

The main pipeline currently:

1. Checks out AIPP code.
2. Verifies the checked-out revision.
3. Sets up Python and test dependencies.
4. Pulls the canonical workspace from Google Drive.
5. Validates `AIPP.md` and `PROJECT_BOOT.md` in the execution workspace.
6. Runs AIPP tests.
7. Runs the session-continuation proof.
8. Runs `aipp_runner.py`.
9. Does not commit or push runtime state to Git.

## Current architectural question

The next work must verify that `aipp_runner.py` has no remaining dependency on local persistent `aipp_state.json` and that canonical project state comes from the Drive-provided workspace, especially `PROJECT_BOOT.md`.

Runtime counters, step information, discovery statistics, and runner metadata should exist only in process memory or transient workflow output.

## Concurrency requirement

Do not use Last Write Wins for canonical state. If AIPP later writes canonical project state, concurrent executions must detect that the source revision changed and HALT rather than silently overwrite another execution. The preferred direction is revision-aware / optimistic concurrency using the existing Drive integration, without introducing a new database.

## Important review constraints

- Do not reintroduce Git-persisted runtime state.
- Do not introduce a new database or external persistence layer.
- Do not weaken Authority Gate.
- Do not equate Git repository state with AIPP runtime/project state.
- Do not restore the removed legacy workflows merely to make tests green.
- Changes should be small, deterministic, reversible, and independently verifiable.

## Request for second opinion

Review this architecture as an independent systems architect. Identify remaining conceptual errors, hidden state persistence, race conditions, incorrect assumptions about Google Drive revisions/locking, and any contradiction between the protocol rules and the current GitHub Actions implementation.

Do not write code initially. First state whether the architecture is now coherent, what remains unsafe, and the smallest next migration step.
