# Browser Scheduler Contract Refactor Design

## Summary

The current browser-task scheduler direction is correct, but its single source
of truth is not. Session and tab policy already point toward one shared
extension session plus many leased task tabs, yet the executable contract is
still split between prose, helper behavior, and scattered dict literals.

This design narrows the next refactor to one goal: make the scheduler contract
and execution flow easier to understand, easier to verify, and harder to drift.

## Goals

- Make `scripts/scheduler_lib/contracts.py` the executable contract authority.
- Make the first-pass execution flow explicit: bootstrap shared session, lease
  fresh tab, run task in tab, persist contract, release tab.
- Keep `session` and `tab` semantics consistent across helper, scheduler, and
  docs.
- Reduce duplicated policy text across README, SKILL, and references.
- Keep the refactor small enough to land without rewriting every workflow.

## Non-Goals

- No full scheduler executor implementation for all sites.
- No priority queue, fairness model, or multi-session load balancing.
- No broad reorganization of unrelated workflow scripts.
- No database or service process; file-based persistence stays.

## Core Model

### Session

An ActionBook browser container. It owns browser mode, shared cookies, and the
tab set. In extension-mode first pass, the scheduler should prefer one stable
shared browser session.

### Tab

A single page context inside a session. It is the unit of task execution.
Browser actions, site adapters, and user-facing progress all bind to one leased
task tab.

### Tab Lease

The scheduler-owned binding between one task and one tab inside one session.

Required fields:

- `lease_id`
- `session_id`
- `tab_id`
- `task_id`
- `opened_at`
- `last_active_at`
- `updated_at`

### Task Record

The scheduler-owned durable task state.

Required first-pass fields:

- `task_id`
- `site`
- `intent`
- `payload`
- `status`
- `stage`
- `attempts`
- `followups`
- `updated_at`

Optional fields become populated during execution and recovery:

- `lease_id`
- `run_id`
- `reason_code`
- `result_quality`
- `completed_items`
- `requested_items`
- `last_heartbeat_at`

### Adapter Summary

The final task result emitted under `contract/summary.json`. The scheduler maps
this into task status and result quality.

## Single Source Of Truth

`scripts/scheduler_lib/contracts.py` becomes the authority for:

- `SCHEMA_VERSION`
- task statuses
- task stages
- result quality values
- default scheduler limits
- task record builders
- snapshot builders
- lease builders
- task-status transition helpers
- adapter-summary-to-task mapping helpers

Docs may explain these rules, but must not redefine them independently.

## Execution Flow

### Bootstrap

1. Verify Chrome / ActionBook environment.
2. Ensure one named session is healthy.
3. Do not silently adopt a different explicit session.

### Task Submission

1. Create scheduler task record.
2. Persist scheduler snapshot.
3. Emit task-created event.

### Task Execution

1. Acquire one fresh tab lease in the shared session.
2. Run one adapter or direct agent flow against the leased tab.
3. Persist progress and contract artifacts.
4. Update task state from contract outputs.

### Task Completion

1. Mark task terminal state.
2. Close only the leased task tab.
3. Release lease record.
4. Leave the shared session alive for later tasks.

## Module Boundaries

### `scripts/actionbook_session.py`

Owns bootstrap, same-session reuse, tab open/close/select, and a thin CLI
entrypoint. It should not become the scheduler.

### `scripts/scheduler.py`

Owns control-plane commands. It should call contract-aware helpers rather than
embedding state shapes directly.

### `scripts/scheduler_lib/contracts.py`

Owns scheduler and adapter contract shapes plus transition helpers.

### `scripts/scheduler_lib/state.py`

Owns file persistence, locking, snapshot reads/writes, and event appends. It
should build state through `contracts.py`, not ad-hoc dicts.

### `scripts/scheduler_lib/lease.py`

Owns tab-lease creation and lightweight lease updates. It should not hardcode
contract fields independently.

### `scripts/scheduler_lib/reconcile.py`

Owns conservative recovery decisions, but should rely on contract helpers for
status transitions and summary mapping.

## Documentation Structure

- `README.md`: high-level mental model and usage.
- `SKILL.md`: agent operating rules.
- `references/status-check.md`: operational debugging flow.
- `references/task-lifecycle.md`: lifecycle semantics and recovery rules.
- `references/adapter-authoring.md`: adapter author guide that references
  lifecycle semantics instead of duplicating them.

## Acceptance Criteria

- `contracts.py` is the only code module that defines scheduler contract
  constants and core record builders.
- `state.py`, `lease.py`, and `reconcile.py` consume contract helpers instead
  of re-declaring the same fields or literals.
- Docs consistently describe first-pass execution as one shared session plus
  leased task tabs.
- No helper or doc path implies that explicit task sessions should silently
  collapse into another named session.
