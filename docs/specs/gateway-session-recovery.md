# Gateway Session Recovery Spec

**Date:** 2026-04-22  
**Branch:** `codex/upgrade-hermes-v2026.4.16`

## Summary

Gateway session suspension is now reason-aware. We no longer treat every
unexpected restart like a full session reset.

Before this change:

- any `suspended = true` session auto-reset on the next message
- manual `/stop`, stuck-loop protection, and crash recovery all shared the same
  boolean flag
- an interrupted gateway restart could wipe useful context even when the user
  only wanted to continue the same conversation

After this change:

- manual stop and stuck-loop protection still start fresh on the next message
- interrupted restarts keep history and surface a one-shot resume notice
- legacy `suspended: true` sessions migrate to the least-destructive path:
  treat them as interrupted restarts

## Suspend Reasons

| Reason | Trigger | Next message behavior |
|---|---|---|
| `manual_stop` | `/stop` hard-stops a running or pending agent | Fresh session |
| `stuck_loop` | Session was active across repeated restarts and crossed the stuck-loop threshold | Fresh session |
| `interrupted_restart` | Previous gateway run ended without `.clean_shutdown` and the session was recently active | Keep history, resume with warning |

## User-Visible Behavior

### 1. Manual stop

- user runs `/stop`
- gateway interrupts the active agent and unlocks the session
- session is marked `manual_stop`
- next message creates a new session and shows the standard fresh-start reset notice

### 2. Unexpected restart

- previous gateway dies without writing `.clean_shutdown`
- startup marks recently-active sessions as `interrupted_restart`
- next message reuses the same session id and prior history
- gateway sends a one-shot warning telling the user the prior run was interrupted
- if the user wants a clean slate, they can explicitly use `/reset`

### 3. Stuck loop

- same session remains active across repeated failed restarts
- stuck-loop detection upgrades that session to `stuck_loop`
- next message starts fresh automatically to break the loop

## Persistence / Compatibility

Session metadata now stores:

- `suspended`
- `suspend_reason`
- `resume_notice_reason`

Legacy sessions that only contain:

- `suspended: true`

are migrated to:

- `suspend_reason = interrupted_restart`

This intentionally avoids destroying old history just because the previous
runtime only had a boolean flag.

## Non-Goals

This change does **not** fix the root cause of gateway silent death on Windows.
It only changes what happens **after** the next startup sees an interrupted
session.

The deeper reliability work still lives elsewhere:

- find why the gateway exits unexpectedly
- improve graceful drain / clean shutdown coverage
- log restart causes more explicitly in the desktop runtime
