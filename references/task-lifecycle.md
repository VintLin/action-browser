# Task Lifecycle

This reference defines the scheduler-facing lifecycle for browser tasks. It is
the control-plane contract for task status, tab leases, retries, persistence,
and restart recovery.

## Scope

The first pass stays file-based. Scheduler state lives under
`~/.action-browser/scheduler/` and must remain readable without a database or a
live browser session.

Minimum scheduler files:

```text
~/.action-browser/scheduler/
  state.json
  state.lock
  events.jsonl
  tasks/<task_id>.json
  progress/<task_id>.json
```

Every scheduler-owned JSON file must include `schema_version`. The scheduler
must take `state.lock` before updating snapshot files, append the transition to
`events.jsonl`, and then atomically replace the latest snapshot.

## Statuses

- `queued`: accepted by the scheduler and waiting for a run slot.
- `running`: currently owns a tab lease and may be using a script, direct
  browser actions, or both.
- `waiting_user`: paused because login, CAPTCHA, MFA, or another user action is
  required in the same tab.
- `blocked`: cannot continue automatically and needs a later retry, code fix,
  or manual intervention beyond the current run.
- `completed`: finished with a readable result set.
- `failed`: exhausted the allowed retry path for the current execution.
- `canceled`: stopped intentionally by the user or operator.

Completed tasks may still be partial:

```json
{
  "status": "completed",
  "result_quality": "partial",
  "completed_items": 8,
  "requested_items": 20
}
```

## Stages

Stages are progress hints, not a second status system:

- `triaging`
- `opening_site`
- `using_script`
- `using_browser`
- `searching`
- `collecting_results`
- `writing_results`
- `waiting_user_action`
- `retrying`
- `stalled`

The scheduler should persist the latest observed stage in the task snapshot and
in the matching event entry so recovery can explain what the task was doing.

## Task Record

Each task file should persist the user-visible state plus enough recovery
context to reconcile after a restart.

Recommended fields:

```json
{
  "schema_version": 1,
  "task_id": "taobao-search-001",
  "site": "taobao",
  "intent": "search",
  "status": "running",
  "stage": "collecting_results",
  "attempts": 1,
  "lease_id": "lease-001",
  "run_id": "run-001",
  "result_quality": null,
  "reason_code": null,
  "followups": [],
  "updated_at": "2026-06-28T12:00:00Z",
  "last_heartbeat_at": "2026-06-28T12:00:05Z"
}
```

Use `followups` for engineering work that should happen after the user task is
done. Do not create a fake task status for adapter work.

Example:

```json
{
  "status": "completed",
  "followups": [
    {
      "type": "adapter_candidate",
      "site": "taobao",
      "reason": "manual browser flow completed and is likely reusable"
    }
  ]
}
```

## Lease Rules

- Scheduler-managed tasks must request a fresh tab and must not adopt an
  arbitrary existing tab.
- One `running` task owns exactly one `lease_id` and one `tab_id`.
- The lease belongs to the task until the task reaches a terminal status or
  moves to `waiting_user`.
- Releasing a lease should close only that task tab. If close fails, record a
  warning and release the lease anyway.
- A task in `waiting_user` keeps its tab only when the user must complete the
  next action in that same tab.

## Retry Rules

Retries are intentionally narrow. The first pass allows same-tab retries only.

- Retry in the original leased tab only.
- Never auto-migrate a failed task to a new tab.
- Cap automatic retries at 2 additional attempts after the first failure.
- If the same-tab retry ceiling is hit, set `status = failed` or `blocked`
  with a concrete `reason_code`.
- If the failure is a login or risk-control gate, use `waiting_user` instead of
  spending retry budget on blind clicks.

## Recovery Rules

On restart or explicit reconcile:

1. Load `state.json`.
2. Inspect every non-terminal task file.
3. Compare task state with tracked run state, tab accessibility, and progress
   freshness.
4. Repair state conservatively and append the decision to `events.jsonl`.

Conservative outcomes:

- live run + live tab => `running`
- dead run + valid results => `completed`
- dead run + no valid results => `blocked`
- live run + lost tab => stop run, then `failed`

Do not silently move a recovered task to a different tab.

## Heartbeats And Freshness

The scheduler or wrapper should refresh these fields every 5 to 10 seconds
while a task is active:

- `last_heartbeat_at`
- `last_progress_at`
- `last_stage`
- `last_observed_url`
- `last_observed_title`

If heartbeats expire and the run is stale, recovery should stop treating the
task as healthy even if the last snapshot said `running`.

## Unrecoverable Conditions

Move the task to `blocked` or `failed` when one of these is confirmed:

- the live run depends on a tab that no longer exists
- the browser session was rebuilt and the original `tab_id` is gone
- login, CAPTCHA, MFA, or another challenge is still unresolved after a
  `waiting_user` pause
- output files exist but `summary.json` is missing or malformed
- progress freshness exceeded the allowed TTL and the run is stale

## Event Expectations

`events.jsonl` is the audit trail for lifecycle changes. Each line should record
the scheduler decision before the latest snapshot write.

Example:

```json
{"schema_version":1,"task_id":"taobao-search-001","event":"task_waiting_user","status":"waiting_user","reason_code":"needs_login","at":"2026-06-28T12:01:00Z"}
{"schema_version":1,"task_id":"taobao-search-001","event":"task_retry_started","status":"running","attempts":2,"at":"2026-06-28T12:04:00Z"}
```
