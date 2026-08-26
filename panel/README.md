# AIPP Control Panel v1

Minimal operator surface for AIPP v1.1.1.

## Boundary

```text
Panel -> AIPP Core -> Execution -> GitHub / Drive / optional AI
```

The panel is not an orchestration engine and does not own runtime state. It must never bypass Authority Gate, deterministic execution, verification, or runner safety rules.

## v1

- system status
- current task/state
- execution visibility
- result/log visibility
- command surface for valid AIPP operations

AI remains optional. The panel exists so AIPP no longer depends on a ChatGPT/Gemini UI as its operator surface.
