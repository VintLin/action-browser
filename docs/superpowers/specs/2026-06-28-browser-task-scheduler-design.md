# Browser Task Scheduler Design

## Summary

This skill should move to an agent-first browser task scheduler.

The scheduler exists to manage user-visible tasks, browser tab ownership, task persistence, and recovery. It must not become the site-automation brain. The agent remains the execution owner for each task and decides whether to use direct browser actions, an existing site workflow script, a mixed approach, or to stop for user intervention.

This design also includes:

- a targeted refactor of `scripts/` so scheduler concerns are separated from browser/session helpers and site adapters
- explicit documentation flow for how new adapters and references are added after the agent completes work on a previously unsupported site

The first pass must stay narrow. This is not a plan to rewrite all site workflows. It is a plan to add a reliable task control layer on top of the existing Action Browser foundations.

## Goals

- Let the agent manage multiple user tasks through independently owned browser tabs.
- Make `1 task = 1 exclusive tab` the default execution model.
- Persist task state so work can be observed and recovered across restarts.
- Close tabs automatically when no task is running on them.
- Keep scripts optional capabilities, not the control plane.
- Let unsupported sites be handled by the agent first, then adapted into reusable scripts and docs when worth keeping.
- Keep the first pass small enough to validate tab exclusivity, state consistency, recovery, and adapter contracts before broad site migration.

## Non-Goals

- No priority scheduler, preemption, or fair-sharing policy.
- No multi-agent contention on the same scheduler state.
- No automatic task migration to a different tab after a failure.
- No attempt to make every site work through one generic universal adapter.
- No full rewrite of all existing site workflows in the first pass.
- No large-scale file moves before the scheduler control plane proves stable.

## User Model

The scheduler should expose user-visible tasks, not low-level browser steps.

Example:

- `xiaohongshu search "儿童童书" top 20`
- `taobao search "儿童童书" top 20`
- `jd search "儿童童书" top 20`
- `douban search "儿童童书" top 20`

Each of those is a separate task with its own tab by default.

When the user explicitly asks to continue in the same tab, follow-up work becomes a serial task group that reuses one tab in sequence. The scheduler should not guess serial reuse from site or keyword similarity alone.

## Architecture

### 1. Scheduler

The scheduler manages:

- task lifecycle
- exclusive tab leases
- tab open/close behavior
- persisted task state
- tracked run metadata
- restart reconciliation

The scheduler does not decide how a site should be automated.

### 2. Agent Executor

The agent is the execution owner for a task. After the scheduler assigns a tab, the agent inspects:

- task intent
- current page state
- available site capabilities
- known failure history

Then the agent chooses one of:

- direct browser actions
- dedicated site workflow script
- mixed execution, such as browser actions plus a script
- waiting for user intervention
- blocking the task when completion is not currently feasible

### 3. Optional Capabilities

Existing site scripts become optional capabilities. They are useful tools, but they are not mandatory entrypoints.

Capability selection must remain a runtime decision made by the agent. Script existence alone is not enough to force script execution, because scripts may be stale, flaky, or narrower than the current task goal.

### 4. Task Workspace

Each task should have durable per-task state and artifacts so the agent can resume with context:

- progress file
- task state file
- result artifacts
- last known failure reason
- optional screenshots or snapshots when needed

## Core Objects

### Task

Represents a user-understandable work unit.

Suggested fields:

- `schema_version`
- `task_id`
- `site`
- `intent`
- `status`
- `stage`
- `attempts`
- `reason_code` optional
- `result_quality` optional
- `completed_items` optional
- `requested_items` optional
- `serial_group_id` optional
- `lease_id` optional
- `run_id` optional
- `result_path` optional
- `error` optional
- `followups` optional
- `updated_at`
- `last_heartbeat_at` optional
- `reconciled_at` optional

### TabLease

Represents exclusive ownership of one browser tab by one task.

Suggested fields:

- `schema_version`
- `lease_id`
- `session_id`
- `tab_id`
- `task_id`
- `opened_at`
- `last_active_at`
- `updated_at`

One lease serves one task at a time. Once the task leaves running state, the lease is released and the tab is closed.

### Run

Represents the currently tracked local execution backing a task. This should align with the existing `actionbook_run.py` tracked-process model rather than inventing a second process tracker.

### SchedulerState

Top-level persisted state containing:

- `schema_version`
- task index
- lease index
- serial-group index
- run index
- metadata for reconciliation
- `updated_at`

## Task States

Task status should stay small and user-readable:

- `queued`
- `running`
- `waiting_user`
- `blocked`
- `completed`
- `failed`
- `canceled`

The main task status should describe user-visible execution state. It should not mix in engineering follow-up work.

When a task completes partially, keep:

- `status = completed`
- `result_quality = partial`
- `completed_items`
- `requested_items`

When a completed task should later become a reusable adapter, keep that as a follow-up instead of a task status:

```json
{
  "status": "completed",
  "followups": [
    {
      "type": "adapter_candidate",
      "site": "taobao",
      "reason": "manual browser flow completed and likely reusable"
    }
  ]
}
```

## Task Stages

Stages are agent-facing progress hints, not a second state machine. Suggested stages:

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

The user-facing progress view should show task status plus stage, for example:

`taobao / running / collecting_results 8/20 / tab-7`

`reason_code` should explain non-happy paths such as:

- `needs_login`
- `captcha`
- `mfa_required`
- `tab_lost`
- `run_stale`
- `adapter_required`
- `script_failed`

## Default Execution Rules

- Default: `1 task = 1 exclusive tab`
- Default: tabs are not pooled or kept warm without a task
- Default: tasks do not share one mutable current-tab pointer
- Default: follow-up work reuses a tab only when the user explicitly asks for that behavior

### Serial Task Groups

When the user says to continue in the same tab, the scheduler creates a `serial_group_id`.

Rules:

- tasks in one serial group run in order
- only one task in the group can own the tab at a time
- if the next task is not immediately ready, the tab can still be closed
- serial reuse is an execution constraint, not a general workflow engine

## Concurrency Guardrails

The first pass should not run unbounded browser concurrency.

Recommended defaults:

- `max_running_tasks = 2` or `3`
- `max_tabs_per_session = 5`
- `max_running_tasks_per_site = 1`

This is a safety fuse, not a priority scheduler.

## Required Helper Changes For Tab Exclusivity

The scheduler model depends on real tab exclusivity. The existing session helper behavior is useful for manual recovery, but too permissive for scheduler-managed tasks.

First-pass helper support should include:

```text
scripts/actionbook_session.py ensure
  --session <session>
  --url <url>
  --force-new-tab
  --no-adopt
  --json

scripts/actionbook_session.py close-tab
  --session <session>
  --tab <tab_id>
  --json
```

Rules:

- scheduler-managed tasks default to `--force-new-tab --no-adopt`
- non-scheduler manual agent use may continue using the existing recovery behavior
- releasing a lease should close only that task tab, not the entire session
- if true single-tab close is unavailable, the temporary fallback is to navigate the tab to `about:blank` and mark the lease released, not to close the session

## Failure Handling

The chosen failure policy is:

- retry in the same tab first
- keep retries limited
- if retries fail, mark the task `completed` with `result_quality = partial`, `blocked`, or `failed` depending on the remaining usable output
- do not silently migrate the task to a fresh tab

Recommended first-pass limits:

- max `2` retries per task
- retry only in the original tab
- allow a light recovery step before retry, such as refreshing browser state or returning to the expected page

This keeps failure behavior understandable and avoids losing context tied to the current tab.

## Unsupported Site Policy

Unsupported sites should be handled by the agent first.

The flow is:

1. Scheduler creates the task and assigns an exclusive tab.
2. Agent inspects the task and the live page.
3. Agent directly completes the task through browser actions if feasible.
4. After completion, the agent decides whether the site handling should be turned into a reusable adapter.
5. If yes, the completed task records an adapter follow-up until the new script and docs are added.
6. If no, the task simply stays `completed`.

### When To Block Instead

`blocked` remains valid only when:

- the agent cannot complete the task directly
- the page requires user login, CAPTCHA, MFA, or other intervention that has not happened
- the site is complex enough that adapter work is required before this task can finish

## Adapter Creation Flow

When the agent successfully handles a previously unsupported site and decides it is worth keeping, the follow-up flow must be explicit:

1. finish the current user task first
2. add a new site adapter script or equivalent site capability
3. add a site reference document
4. update capability indexes in the main docs if needed

This order is important:

`deliver the task first -> then productize the site capability`

The design should not require adapter creation before the current user task is completed.

## Thin Adapter Contract

Scripts remain optional capabilities, but when the agent uses one, its outputs should follow a small shared contract so the scheduler, recovery logic, and UI can understand the result without reinterpreting each site separately.

### Inputs

- `task_id`
- `session_id`
- `tab_id`
- task intent
- `output_dir`
- task-specific business args such as `query`, `url`, or `limit`

### Outputs

- `summary.json`
- `progress.json`
- `artifacts/*`
- exit code

### summary.json Minimum Shape

```json
{
  "ok": true,
  "site": "taobao",
  "intent": "search",
  "requested_count": 20,
  "collected_count": 18,
  "artifacts": ["results.json", "screenshots/page-1.png"],
  "warnings": [],
  "needs_user_action": false
}
```

This is intentionally small. It is a thin contract, not a plugin framework.

## scripts/ Refactor Scope

The current `scripts/` directory mixes browser infrastructure, site workflows, and process tracking. The refactor should separate concerns so the agent can reason about the skill more easily.

### First-Pass Structure

Do not begin with a large-scale move of all existing files. Add the scheduler in a new narrow area first:

```text
scripts/
  scheduler.py
  scheduler_lib/
    state.py
    lease.py
    lifecycle.py
    reconcile.py
    executor.py
    contracts.py
```

After the scheduler proves stable, the repo can consider deeper structure cleanup later.

### Existing Script Mapping

First-pass expectations:

- `actionbook_session.py`, `actionbook_run.py`, and `actionbook_interrupts.py` stay in the browser infrastructure boundary
- `*_workflow.py` scripts move conceptually under the site capability boundary
- new scheduler entrypoints are added instead of forcing site scripts to become schedulers

This is a focused refactor, not a rewrite of each site implementation.

## Documentation Changes

The skill documentation should be restructured to match the new agent-first model.

### SKILL.md

Keep it as the operational entrypoint.

It should explain:

- the scheduler-first task/tab model
- that the agent chooses between direct browser work and site scripts
- that unsupported sites are completed first and adapted second
- how serial tab reuse works

It should remain site-neutral.

### README.md

Update it to describe:

- overall architecture
- task lifecycle
- scheduler role versus agent role
- directory structure after the refactor
- typical execution flows

### references/status-check.md

Keep it focused on environment and runtime health:

- daemon health
- extension status
- session/tab validity
- browser reachability

### New: references/task-lifecycle.md

Add a focused document for:

- task statuses
- task stages
- tab lease lifecycle
- retry and close rules
- restart recovery behavior
- heartbeat freshness
- unrecoverable conditions

### New: references/adapter-authoring.md

Add a focused document for:

- when a new adapter is worth creating
- minimal script contract
- expected outputs and artifacts
- failure and recovery expectations
- how to document a newly supported site
- failure codes and warning semantics

### references/<site>.md

Per-site references should clarify:

- supported task types
- current script coverage
- known flaky or failing areas
- when the agent should prefer direct browser actions instead

## Persistence Design

The first pass should stay file-based.

Suggested state layout under `~/.action-browser/scheduler/`:

- `state.json`
- `state.lock`
- `events.jsonl`
- `tasks/<task_id>.json`
- `progress/<task_id>.json`
- existing tracked run state under `~/.action-browser/runs/`

Minimum persistence rules:

- use atomic file replacement for snapshot writes
- take `state.lock` before scheduler snapshot updates
- append state transitions to `events.jsonl` before writing the latest snapshot
- include `schema_version` in every scheduler-owned JSON file
- sanitize `task_id`, `run_id`, and `lease_id` using the same safe-filename discipline already used by `actionbook_run.py`

No database is needed for the first version.

## Recovery Design

On restart:

1. load scheduler state
2. inspect non-terminal tasks
3. compare scheduler state with run state, tab accessibility, and progress freshness
4. repair task state conservatively

Conservative rules:

- live run + live tab -> resume as `running`
- dead run + valid results -> `completed` with `result_quality = partial` or full `completed`
- dead run + no results -> `blocked`
- live run + lost tab -> stop the run, then treat as failure

Do not silently move a task to a new tab during reconciliation.

The scheduler or wrapper should update heartbeat-style fields every 5 to 10 seconds:

- `last_heartbeat_at`
- `last_progress_at`
- `last_stage`
- `last_observed_url`
- `last_observed_title`

Unrecoverable conditions should be documented explicitly:

- tab lost while the live run still depends on that tab
- session rebuilt and original `tab_id` no longer exists
- login, CAPTCHA, or MFA required but not completed
- output directory exists but `summary.json` is missing or malformed
- progress exceeded TTL and the run is stale

## Testing Strategy

The first pass should emphasize control-plane confidence over full browser end-to-end coverage.

Required coverage areas:

- task state transitions
- tab lease lifecycle
- restart reconciliation
- retry behavior in the same tab
- lock and atomic write behavior
- agent execution branching:
  - use script
  - use browser actions
  - fallback from script to browser
  - wait for user intervention
- adapter contract tests

The first pass should also use fake ActionBook test doubles so scheduler semantics can be verified without requiring full live browser runs for every case.

Testing every site DOM flow is not the first-pass goal.

## Open Questions Resolved In This Design

- default task/tab mapping: `1 task = 1 exclusive tab`
- retries: limited same-tab retries only
- task visibility: task status plus current stage
- tab limits: conservative concurrency caps are required
- persistence: durable file-based state
- idle tabs: auto-close when no task is running
- unsupported sites: agent-first execution, adapter second

## Rollout Shape

Recommended order:

### P0

- add `references/task-lifecycle.md`
- add `references/adapter-authoring.md`
- define scheduler state schema and JSON examples
- define task, lease, and run transition rules
- add fake ActionBook test doubles

### P1

Build the minimum scheduler CLI:

```bash
python3 scripts/scheduler.py submit --site taobao --intent search --query "儿童童书" --limit 20
python3 scripts/scheduler.py list
python3 scripts/scheduler.py status --task <task_id>
python3 scripts/scheduler.py stop --task <task_id>
python3 scripts/scheduler.py reconcile
```

This phase only needs to prove:

- create task
- open exclusive tab
- write progress
- release lease
- close tab or warn if tab close fails
- recover or mark blocked after interruption

### P2

- align scheduler run handling with the existing `actionbook_run.py` tracked-process model
- do not build a second process tracker

### P3

- integrate exactly one site workflow, such as Taobao or Douban
- prove scheduler-assigned tab usage
- prove contract outputs: `summary.json`, `progress.json`, `artifacts/*`
- prove same-tab retry up to 2 times

### P4

- revisit broader directory cleanup only after the above is stable

## Acceptance Criteria

1. Submitting 4 tasks at once never exceeds the configured running-task cap; extra tasks remain `queued`.
2. Every `running` task has a unique `lease_id` and `tab_id`; no scheduler-managed task shares an implicit current tab.
3. On completion, failure, or cancellation, the lease is always released; if tab close fails, the task records a warning.
4. After a killed process and `reconcile`, each task lands in one of: `running`, `completed`, `blocked`, `failed`, or `canceled`.
5. A site script failure retries only in the original tab, at most 2 times, and never auto-migrates to a new tab.
6. Login, CAPTCHA, MFA, and risk-control pages move the task to `waiting_user` or `blocked`; automation does not continue clicking through them.
7. Result artifacts and progress files remain readable independent of the live browser state.
8. All persisted writes use lock plus atomic replace plus `schema_version`.
