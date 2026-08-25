# AIPP Current Architecture Status

## Purpose

This document is a second-opinion briefing for architectural review of AIPP. It is not a protocol change and must not be treated as authority to modify the architecture.

## Identity

AIPP (AI Project Protocol) is not an AI. It is a deterministic project/workspace orchestration and execution protocol operating above AI sessions.

## Canonical architecture

- Google Drive is the Canonical Workspace and physical project reality.
- `PROJECT_BOOT.md` is the canonical project-state source consumed by the runtime workflow.
- Git is for AIPP protocol code, implementation, tests, and version history.
- Runtime state is ephemeral and must not be persisted to Git.
- AIPP must not autonomously move proposals to NOW. Authority Gate / human approval remains mandatory.
- Simulation and physical execution remain separate. A physical execution claim requires evidence from the target system.

## Migration completed

1. Automatic Git commit/push of `aipp_state.json` was removed from the main pipeline.
2. The legacy `aipp_sync.yml` workflow that synchronized `aipp_state.json` was removed.
3. The legacy `aipp-execution-proof.yml` workflow was removed because it recreated the obsolete local-state model.
4. `.gitignore` contains `aipp_state.json` as an ephemeral artifact guard.
5. `aipp_drive_runtime.py` no longer searches for, downloads, parses, or writes `aipp_state.json`. It now finds `PROJECT_BOOT.md` in Drive, materializes that canonical file into the ephemeral execution workspace, and performs workspace discovery.
6. `aipp_runner.py` initializes runtime state only in process memory and parses the Drive-provided `PROJECT_BOOT.md` through the existing bootstrap layer.
7. The runner no longer supports a `RUN` command that silently requests approval and immediately approves the task. That autonomous approval path now HALTs because it violates Authority Gate semantics.
8. Runner tests were migrated away from `aipp_state.json` and now assert that runtime state is not persisted.
9. The main pipeline now serializes executions with GitHub Actions `concurrency` and explicitly fails if `aipp_state.json` appears in the execution workspace.

## Important finding

The previous migration was incomplete even after removing Git commit/push. The Drive runtime still treated `aipp_state.json` as the canonical Drive state, then wrote a local copy before invoking the runner. That was a hidden persistence dependency. It has now been removed.

The current direction is therefore:

`Google Drive PROJECT_BOOT.md` -> ephemeral workflow workspace -> in-memory AIPP runtime state -> result/logs -> process ends

Git contains only implementation/protocol/test artifacts.

## Concurrency

The main GitHub Actions pipeline now serializes runs with a concurrency group. This prevents two AIPP pipeline executions from running concurrently through the same workflow. This is an execution-level safeguard, not a substitute for Drive revision-aware locking.

If AIPP later writes canonical project state back to Drive, do not use Last Write Wins. The next design must detect a changed Drive revision/source snapshot and HALT rather than overwrite another execution.

## Remaining architectural questions

1. How should a human Authority Gate approval be represented canonically in `PROJECT_BOOT.md` without requiring runtime state persistence?
2. Which exact Google Drive revision/metadata mechanism should be used for optimistic concurrency if AIPP ever writes canonical state?
3. Which outputs are true execution artifacts versus ephemeral runtime telemetry, and which of those need durable audit evidence?
4. How should a multi-session approval/execution flow resume when runtime memory is necessarily destroyed between GitHub Actions runs?

## Review constraints

- Do not reintroduce Git-persisted runtime state.
- Do not introduce a new database or external persistence layer.
- Do not weaken Authority Gate.
- Do not equate Git repository state with AIPP runtime/project state.
- Do not restore removed legacy workflows merely to make tests green.
- Keep changes small, deterministic, reversible, and independently verifiable.

## Request for second opinion

Review the current architecture as an independent systems architect. Focus especially on the four remaining questions above, hidden persistence, race conditions, Google Drive revision semantics, Authority Gate continuity across sessions, and contradictions between the protocol and the GitHub Actions implementation.

Do not write code initially. First state whether the architecture is coherent now, what remains unsafe, and the smallest next migration step.
