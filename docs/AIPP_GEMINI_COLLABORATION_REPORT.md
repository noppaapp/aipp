# AIPP Gemini Collaboration Report

## Purpose

This document records the current architectural state and the work performed by the ChatGPT-side implementation agent for independent review by Gemini. It is a status/second-opinion briefing, not an authority to change the protocol by itself.

## Collaboration status

ChatGPT and Gemini are being used as two independent architectural reviewers. Gemini's earlier review identified the central architectural problem: Git repository state and AIPP runtime state must not be treated as the same thing. ChatGPT then implemented the agreed migration in the `noppaapp/aipp` repository in small, separately committed steps.

Gemini should review the resulting repository state independently and should not assume that a green CI result, by itself, proves architectural correctness.

## Architectural decision now in force

- AIPP is not an AI. It is a deterministic orchestration/execution protocol above AI sessions.
- Google Drive is the Canonical Workspace and physical project reality.
- `PROJECT_BOOT.md` is the canonical project-state source consumed by the runtime workflow.
- Git contains AIPP implementation, protocol code, tests, and version history only.
- Runtime execution state is ephemeral and must not be persisted to Git.
- Authority Gate remains mandatory. AIPP must not autonomously approve its own proposal or move a proposal to NOW.
- Simulation and physical execution remain separate. Physical execution requires evidence from the target system.

## Physical implementation performed

The following changes were committed to `main`:

1. `2f001639` — made runtime state ephemeral.
2. `9e722841` — stopped tracking `aipp_state.json` as runtime state.
3. `85a33b0` — removed the legacy state-sync workflow.
4. `b192183` — removed the legacy execution-proof workflow that recreated the obsolete local state model.
5. `6ef4a5b` — changed Drive runtime behavior so `PROJECT_BOOT.md` is the canonical state input rather than `aipp_state.json`.
6. `ec34519` — enforced ephemeral runtime behavior and blocked the autonomous approval path.
7. `5e6e9fa` — migrated runner tests to the new model.
8. `28099e4` — serialized GitHub Actions executions and added an explicit guard against runtime-state persistence.
9. `3a85f562` — updated this architecture briefing after the migration.

These are real repository commits, not simulated changes.

## Important discovery during migration

Removing the Git commit/push step was not sufficient. A legacy Drive runtime still searched for `aipp_state.json`, downloaded it, and materialized a local copy before invoking the runner. A failed Action exposed this hidden dependency with:

`FileNotFoundError: [Errno 2] No such file or directory: 'aipp_state.json'`

The legacy workflow was removed and the Drive runtime was changed to use `PROJECT_BOOT.md` instead. This is important evidence that architectural migrations must inspect the complete execution chain, not only the final persistence step.

## Current runtime direction

`Google Drive PROJECT_BOOT.md`

→ ephemeral GitHub Actions execution workspace

→ in-memory AIPP runtime state

→ discovery / bootstrap / execution result and transient logs

→ process ends

No runtime-state commit or push is performed.

## Concurrency status

The main GitHub Actions workflow now serializes executions with an Actions concurrency group. This prevents two instances of the same pipeline from executing concurrently through that workflow.

This is intentionally NOT considered a substitute for canonical-state optimistic locking.

If AIPP later gains a legitimate requirement to write canonical project state back to Drive, the design must not use Last Write Wins. It must capture the source revision/snapshot and HALT if the canonical source changed before the write.

## Authority Gate status

A previous runner path could request approval and immediately approve within the same execution. That behavior contradicted the protocol rule that AIPP cannot approve its own proposal.

The current runner behavior blocks that autonomous approval path and produces HALT instead.

This is a protocol-enforcement change, not merely a test change.

## What is NOT yet proven

The migration is not considered fully proven merely because the repository commits exist.

The next verification must establish:

1. The GitHub Actions workflow passes after the migration.
2. No execution path recreates or depends on `aipp_state.json`.
3. `PROJECT_BOOT.md` is actually the canonical project-state input used by the runtime path.
4. Runtime counters and metadata disappear with the process rather than becoming durable state.
5. Authority Gate behavior remains correct across separate sessions/runs.
6. The Drive revision mechanism required for future write-back is understood before any canonical-state write is implemented.

## Questions for Gemini

Please independently challenge the following assumptions:

1. Is `PROJECT_BOOT.md` alone sufficient as canonical project state, or does the protocol need a more explicit durable approval record inside the canonical Workspace?
2. Is GitHub Actions concurrency sufficient for the execution-level race model, or are there other triggers/paths that can bypass it?
3. What exact Google Drive revision/metadata primitive should be used if AIPP later writes canonical state?
4. Which outputs should become durable audit artifacts, if any, without turning ephemeral runtime state back into a database?
5. How should Authority Gate continuity work when GitHub Actions process memory disappears between sessions?
6. Is there any remaining conceptual contradiction between AIPP's deterministic state machine and the current implementation?

## Review rule

Do not recommend restoring `aipp_state.json` merely to make tests or workflows green. If a test fails, treat it as evidence of an obsolete dependency until proven otherwise.

Do not introduce a database or new external persistence layer unless the protocol requirements demonstrate that the current Google Drive + GitHub Actions architecture cannot satisfy them.

Do not write code in the first review. First provide an architectural verdict, identify remaining risks, and name the smallest next migration step.
