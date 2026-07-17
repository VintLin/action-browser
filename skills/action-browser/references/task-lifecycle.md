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

Owned browser tabs use one separate source of truth:

```text
~/.action-browser/owned-tabs.json
```

The owned-tab lease store uses `schema_version: 2`. The former
`task-tabs.json` shape is intentionally unsupported after the clean break.
Scheduler task records may mirror `lease_id`, but do not persist a second lease
map or duplicate session/tab ownership.

Every scheduler-owned JSON file uses `schema_version: 2` after this clean break. The scheduler
must take `state.lock` before updating snapshot files, append the transition to
`events.jsonl`, and then atomically replace the latest snapshot.

## Progress Source Of Truth

There are two progress files with different roles:

- `~/.action-browser/scheduler/progress/<task_id>.json` is the scheduler-owned
  mirror used for list/status commands and restart reconciliation.
- `<output>/contract/progress.json` is the adapter-owned execution snapshot
  written by the running task when the site keeps legacy root outputs.

The adapter-owned `<output>/contract/progress.json` is the source of truth
while a task is active. The scheduler must copy or derive scheduler progress
from that file under `state.lock`; adapters must not write
`~/.action-browser/scheduler/progress/<task_id>.json` directly.

Conflict rule:

- if `<output>/contract/progress.json` is newer and valid, the scheduler mirror
  must be overwritten from it
- if the scheduler mirror is newer only because a reconcile or status change
  happened after the run stopped, keep the scheduler mirror and do not write
  back into `<output>/contract/progress.json`
- if timestamps disagree but the adapter file is malformed, keep the scheduler
  mirror, record a warning, and treat the adapter progress as unusable

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

## Tracked Run Stop Results

`actionbook_run.py stop` records the primary workflow outcome separately from
residual process-group cleanup. If the workflow handles SIGTERM and exits with
130/143, the run remains `stopped` with that exit code and
`stop_result: terminated`. If a daemon or other descendant still needs
SIGKILL, record that detail as `descendant_stop_result: killed`; do not replace
the workflow's graceful exit with `-9`.

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

- In extension mode first pass, the scheduler should prefer one stable browser session and multiple leased tabs inside it, but only after session persistence has been proven across commands.
- Scheduler and future executors should acquire and release session/tab state through the `scripts/owned_tab_lifecycle.py` module, exposed by `scripts/actionbook_session.py acquire-tab|release-tab`, not by open-coding raw `browser start/new-tab/list-tabs/close-tab` calls in control-plane code.
- Executors whose outer command runner reaps daemon children must launch one workflow through `scripts/actionbook_task.py`, which keeps acquire, workflow execution, and release in one parent-process lifetime. The atomic runner must refuse an existing live lease, and any same-tab retry must complete inside its child workflow before that process exits. Such executors must not persist a lease across separate ephemeral exec calls; use a persistent executor process when a task genuinely needs a long-lived tab.
- Scheduler-managed tasks must request a fresh tab and must not adopt an
  arbitrary existing tab.
- One `running` task owns exactly one `lease_id` and one `tab_id`.
- Multiple running tasks may share one browser `session_id` as long as each task has its own leased `tab_id`.
- The lease belongs to the task until the task reaches a terminal status or
  enters `waiting_user`.
- Releasing a lease should close only that task tab. If exact close cannot be
  verified, report the cleanup failure and retain the task-tab ownership record
  until exact cleanup succeeds or the resource is confirmed missing.
- A task in `waiting_user` keeps a paused lease by default when the required
  user action must happen in that exact tab, such as login, CAPTCHA, MFA, or a
  site challenge bound to current page state.
- A task in `waiting_user` must release its lease if the user action is not
  tab-bound, if the task can safely resume from a fresh tab later, or if a
  configured hold timeout expires.
- The default paused-lease hold timeout is 15 minutes. If the scheduler later
  exposes `waiting_user_hold_seconds`, use that key; otherwise fall back to 900
  seconds.

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
Do not silently migrate a recovered task to a different browser session in extension mode unless the old session is confirmed dead and the task is being restarted, not resumed.

## Heartbeats And Freshness

The scheduler or wrapper should refresh these fields every 5 to 10 seconds
while a task is active:

- `last_heartbeat_at`
- `last_progress_at`
- `last_stage`
- `last_observed_url`
- `last_observed_title`

Freshness defaults:

- use scheduler config `freshness_ttl_seconds` when present
- otherwise fall back to 30 seconds for heartbeat and progress freshness

If heartbeats expire and the run is stale, recovery should stop treating the
task as healthy even if the last snapshot said `running`.

## Status Mapping From Adapter Outputs

The scheduler is authoritative for task status, but it must map adapter outputs
consistently.

- `contract/summary.json.ok = true` and `needs_user_action = false` and
  `collected_count >= requested_count` => `status = completed`,
  `result_quality = full`
- `contract/summary.json.ok = true` and `needs_user_action = false` and
  `0 < collected_count < requested_count` => `status = completed`,
  `result_quality = partial`
- `contract/summary.json.ok = true` and `needs_user_action = false` and
  `requested_count > 0` and `collected_count = 0` => `status = completed`,
  `result_quality = partial`; expect a warning such as `no_results_found`
- `contract/summary.json.ok = true` and `needs_user_action = false` and
  `requested_count = 0` => `status = completed`, `result_quality = full`;
  do not emit a `no_results_found` warning, but a warning such as
  `nothing_requested` is allowed when the zero-request outcome is unusual
- `contract/summary.json.ok = true` and `needs_user_action = true` => `status =
  waiting_user`; preserve any partial counts but do not mark `completed`
- `contract/summary.json.ok = false` and `needs_user_action = true` => `status =
  waiting_user`
- `contract/summary.json.ok = false` and retry budget remains => `status = running`,
  `stage = retrying`
- `contract/summary.json.ok = false` and retry budget is exhausted => `status = failed`
  or `blocked`, based on `reason_code`

If both progress and summary exist and disagree, `contract/summary.json` wins
for final outcome after the run exits. `contract/progress.json` wins only for
in-flight status while the run is still active.

## Unrecoverable Conditions

Move the task to `blocked` or `failed` when one of these is confirmed:

- the live run depends on a tab that no longer exists
- the browser session was rebuilt and the original `tab_id` is gone
- login, CAPTCHA, MFA, or another challenge is still unresolved after a
  `waiting_user` pause
- output files exist but `contract/summary.json` is missing or malformed
- progress freshness exceeded the allowed TTL and the run is stale

## Event Expectations

`events.jsonl` is the audit trail for lifecycle changes. Each line should record
the scheduler decision before the latest snapshot write.

Example:

```json
{"schema_version":1,"task_id":"taobao-search-001","event":"task_waiting_user","status":"waiting_user","reason_code":"needs_login","at":"2026-06-28T12:01:00Z"}
{"schema_version":1,"task_id":"taobao-search-001","event":"task_retry_started","status":"running","attempts":2,"at":"2026-06-28T12:04:00Z"}
```
