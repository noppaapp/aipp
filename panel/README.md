# AIPP Control Panel v1

Minimal operator surface for AIPP v1.1.1.

## Scope

The panel is intentionally thin. It does not implement orchestration or execution. It exposes the existing AIPP runtime through a future control surface for:

- system status
- current task/state
- execution visibility
- logs/results
- start/stop/approval controls where permitted by AIPP authority rules

## Boundary

```text
Panel -> AIPP Core -> Execution -> GitHub / Drive / optional AI
```

The panel must never become a second orchestration engine and must never bypass Authority Gate or runner safety rules.

## v1 acceptance criteria

1. Display current AIPP state without duplicating state ownership.
2. Submit only valid AIPP commands.
3. Show execution status and result.
4. Preserve deterministic authority and verification rules.
5. Keep AI optional.
