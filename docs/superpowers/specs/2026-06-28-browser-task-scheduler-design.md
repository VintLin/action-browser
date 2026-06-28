# Browser Task Scheduler Design

## Summary

This skill should move to an agent-first browser task scheduler.

The scheduler exists to manage user-visible tasks, browser tab ownership, task persistence, and recovery. It must not become the site-automation brain. The agent remains the execution owner for each task and decides whether to use direct browser actions, an existing site workflow script, a mixed approach, or to stop for user intervention.

This design also includes:

- a targeted refactor of `scripts/` so scheduler concerns are separated from browser/session helpers and site adapters
- explicit documentation flow for how new adapters and references are added after the agent completes work on a previously unsupported site

## Goals

- Let the agent manage multiple user tasks through independently owned browser tabs.
- Make `1 task = 1 exclusive tab` the default execution model.
- Persist task state so work can be observed and recovered across restarts.
- Close tabs automatically when no task is running on them.
- Keep scripts optional capabilities, not the control plane.
- Let unsupported sites be handled by the agent first, then adapted into reusable scripts and docs when worth keeping.

## Non-Goals

- No priority scheduler, preemption, or fair-sharing policy.
- No multi-agent contention on the same scheduler state.
- No automatic task migration to a different tab after a failure.
- No attempt to make every site work through one generic universal adapter.
- No full rewrite of all existing site workflows in the first pass.

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

- `task_id`
- `site`
- `intent`
- `status`
- `stage`
- `attempts`
- `serial_group_id` optional
- `lease_id` optional
- `run_id` optional
- `result_path` optional
- `error` optional

### TabLease

Represents exclusive ownership of one browser tab by one task.

Suggested fields:

- `lease_id`
- `session_id`
- `tab_id`
- `task_id`
- `opened_at`
- `last_active_at`

One lease serves one task at a time. Once the task leaves running state, the lease is released and the tab is closed.

### Run

Represents the currently tracked local execution backing a task. This should align with the existing `actionbook_run.py` tracked-process model rather than inventing a second process tracker.

### SchedulerState

Top-level persisted state containing:

- task index
- lease index
- serial-group index
- run index
- metadata for reconciliation

## Task States

Task status should stay small and user-readable:

- `queued`
- `running`
- `partial`
- `blocked`
- `completed`
- `completed_needs_adapter`

`completed_needs_adapter` means the user task is done, but the agent determined the site handling should be productized into a reusable adapter and reference document afterward.

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

## Failure Handling

The chosen failure policy is:

- retry in the same tab first
- keep retries limited
- if retries fail, mark the task `partial` or `blocked`
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
5. If yes, the task transitions to `completed_needs_adapter` until the new script and docs are added.
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

## scripts/ Refactor Scope

The current `scripts/` directory mixes browser infrastructure, site workflows, and process tracking. The refactor should separate concerns so the agent can reason about the skill more easily.

### Target Structure

Suggested grouping:

- scheduler layer
  - scheduler state management
  - scheduler run loop
  - scheduler reconciliation
- browser infrastructure layer
  - session bootstrap
  - tab management
  - tracked process helpers
  - interruption helpers
- site capability layer
  - per-site workflows and adapters
- migration/bootstrap helpers
  - one-off helpers kept minimal

The exact filenames can follow repo style, but the boundaries should be explicit.

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

### New: references/adapter-authoring.md

Add a focused document for:

- when a new adapter is worth creating
- minimal script contract
- expected outputs and artifacts
- failure and recovery expectations
- how to document a newly supported site

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
- `tasks/<task_id>.json`
- `progress/<task_id>.json`
- existing tracked run state under `~/.action-browser/runs/`

The scheduler should use atomic file replacement for writes.

No database is needed for the first version.

## Recovery Design

On restart:

1. load scheduler state
2. inspect non-terminal tasks
3. compare scheduler state with run state, tab accessibility, and progress freshness
4. repair task state conservatively

Conservative rules:

- live run + live tab -> resume as `running`
- dead run + valid results -> `partial` or `completed`
- dead run + no results -> `blocked`
- live run + lost tab -> stop the run, then treat as failure

Do not silently move a task to a new tab during reconciliation.

## Testing Strategy

The first pass should emphasize control-plane confidence over full browser end-to-end coverage.

Required coverage areas:

- task state transitions
- tab lease lifecycle
- restart reconciliation
- retry behavior in the same tab
- agent execution branching:
  - use script
  - use browser actions
  - fallback from script to browser
  - wait for user intervention
- adapter contract tests

Testing every site DOM flow is not the first-pass goal.

## Open Questions Resolved In This Design

- default task/tab mapping: `1 task = 1 exclusive tab`
- retries: limited same-tab retries only
- task visibility: task status plus current stage
- tab limits: no fixed concurrency cap in this design
- persistence: durable file-based state
- idle tabs: auto-close when no task is running
- unsupported sites: agent-first execution, adapter second

## Rollout Shape

Recommended order:

1. add scheduler state model and lifecycle docs
2. add scheduler entrypoints on top of existing browser infrastructure
3. wire agent-first execution decisions
4. update `SKILL.md` and `README.md`
5. add adapter-authoring and task-lifecycle references
6. incrementally normalize existing site scripts and references

This keeps the first rollout narrow while preserving room to tighten site capabilities later.
