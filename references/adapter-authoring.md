# Adapter Authoring

This reference defines the minimum contract for a reusable site adapter under
the browser task scheduler. Adapters are optional execution capabilities. The
scheduler owns task state, tab leases, persistence, and recovery.

## When To Create An Adapter

Create a new adapter only when all of these are true:

- the agent already completed the site task manually or with mixed tooling
- the flow is likely to repeat
- the site has a stable enough path to justify maintenance
- direct browser actions alone would be slower or less reliable next time

If the site is still too brittle, leave the user task as completed and record a
`followups` entry such as `adapter_candidate` instead of forcing a premature
script.

## Required Inputs

Every scheduler-managed adapter must accept:

- `--task-id`
- `--session`
- `--tab`
- `--output`

The scheduler may also pass task-specific inputs such as `--query`,
`--limit`, or `--item-url`, but the four fields above are the minimum contract.

Input semantics:

- `--task-id` is the scheduler-issued stable identifier for one user-visible
  task attempt and must be copied into `contract/summary.json` and
  `contract/progress.json`
- `--session` is the existing ActionBook browser session identifier selected by
  the scheduler; adapters must attach to that session and must not create a new
  replacement session silently
- `--tab` is the scheduler-issued tab identifier inside `--session`; it is
  stable only for the lifetime of that browser session and lease, and becomes
  invalid if the session is rebuilt or the tab is closed
- `--output` is the adapter-owned output directory for durable artifacts and
  progress files for that task

## Ownership Boundaries

- The adapter works inside the tab assigned by the scheduler.
- Multiple tasks may share the same `--session`, but one adapter run owns only its assigned `--tab`.
- The scheduler should hand adapters a tab that was opened and validated through the session helper; adapters should not rely on raw session bootstrap semantics themselves.
- The adapter must not open a replacement tab on its own after failure.
- The adapter must not adopt a different current tab implicitly.
- Retry logic belongs to the scheduler. The adapter reports failures; it does
  not run unbounded self-retries.
- The adapter may stop and report `waiting_user` conditions, but it must not
  click through login, CAPTCHA, MFA, or risk-control prompts blindly.

## Required Outputs

The first pass stays file-based. Each adapter run writes to the task output
directory supplied by `--output`.

Minimum output shape:

```text
<output>/
  summary.json
  failures.json
  contract/
    summary.json
    progress.json
    artifacts/
```

`<output>/summary.json` and other root files may remain legacy site-workflow
outputs when the site already has an established file shape. For
scheduler-managed adapter metadata, use `<output>/contract/` as the stable
contract root in that compatibility mode.

If the adapter creates additional files, keep them under the same output root
so the scheduler can treat the directory as one durable task artifact set.

## File Contract

Every adapter-owned contract JSON file must include `schema_version`. Raw
artifact payloads under `contract/artifacts/` may keep their legacy shape when
they are direct data exports rather than contract metadata. Adapters do not own
scheduler snapshots, `state.lock`, or `events.jsonl`, but their output must
remain compatible with the scheduler's file-based persistence model.

Rules:

- the scheduler takes `state.lock` before it updates scheduler snapshots
- the scheduler appends lifecycle decisions to `events.jsonl`
- the adapter writes `contract/summary.json` and `contract/progress.json`
  atomically when using compatibility mode
- JSON stays readable after crashes or process kills

An adapter should never edit `~/.action-browser/scheduler/state.json`
directly.

Progress ownership:

- `<output>/contract/progress.json` is the adapter-owned scheduler contract
  source of truth while the run is active
- `~/.action-browser/scheduler/progress/<task_id>.json` is the scheduler-owned
  mirror
- adapters must never write the scheduler mirror directly
- after the run exits, `contract/summary.json` becomes the source of truth for
  final status and result quality if it conflicts with the last progress
  snapshot

## contract/summary.json

`contract/summary.json` is the final scheduler contract outcome as seen by the
scheduler and the user.

Example:

```json
{
  "schema_version": 1,
  "ok": true,
  "site": "taobao",
  "intent": "search",
  "requested_count": 20,
  "collected_count": 18,
  "artifacts": ["contract/artifacts/results.json"],
  "warnings": [],
  "needs_user_action": false,
  "followups": []
}
```

Required semantics:

- `ok = true` means the adapter finished the attempted flow
- `collected_count` may be less than `requested_count`
- `warnings` describes partial results or non-fatal issues
- `needs_user_action = true` means the scheduler should move the task to
  `waiting_user`
- `followups` records post-task work such as `adapter_candidate`,
  `selector_hardening`, or `schema_review`

Normative scheduler mapping:

- `ok = true` and `needs_user_action = false` and
  `collected_count >= requested_count` maps to `completed` with
  `result_quality = full`
- `ok = true` and `needs_user_action = false` and
  `0 < collected_count < requested_count` maps to `completed` with
  `result_quality = partial`
- `ok = true` and `needs_user_action = false` and `requested_count > 0` and
  `collected_count = 0` maps to `completed` with `result_quality = partial`;
  emit a warning such as `no_results_found`
- `ok = true` and `needs_user_action = false` and `requested_count = 0` maps
  to `completed` with `result_quality = full`; do not emit
  `no_results_found`, though `nothing_requested` is allowed when useful
- `needs_user_action = true` maps to `waiting_user`, even if partial artifacts
  already exist
- `ok = false` with no user-action requirement maps to retry, `failed`, or
  `blocked` based on scheduler retry budget and `reason_code`

## contract/progress.json

`contract/progress.json` is the mutable execution snapshot for recovery and
user-facing status.

Example:

```json
{
  "schema_version": 1,
  "task_id": "taobao-search-001",
  "status": "running",
  "stage": "collecting_results",
  "attempts": 1,
  "completed_items": 8,
  "requested_items": 20,
  "last_observed_url": "https://s.taobao.com/search?q=%E7%AB%A5%E4%B9%A6"
}
```

When the adapter encounters login, CAPTCHA, MFA, or a similar gate, write a
progress snapshot that makes the pause explicit so the scheduler can transition
to `waiting_user`.

Required fields when pausing for user action:

- `status = "waiting_user"`
- `reason_code` such as `needs_login`, `captcha`, or `mfa_required`
- `last_observed_url`
- `last_observed_title` when available

Lease expectation:

- assume `waiting_user` keeps the same paused lease only when the required user
  action is bound to the current tab state
- otherwise expect the scheduler to release the lease and later resume from a
  fresh tab

## Failure And Retry Semantics

Adapters should emit concrete failure reasons that let the scheduler decide
whether to retry, wait, or block.

Recommended reasons:

- `needs_login`
- `captcha`
- `mfa_required`
- `tab_lost`
- `run_stale`
- `selector_failed`
- `adapter_required`

Retry policy:

- automatic retries stay in the same leased tab only
- the scheduler-owned same-tab retry ceiling is 2 retries after the initial
  attempt
- after that ceiling, the adapter should return a clear failure and let the
  scheduler mark the task `failed` or `blocked`

Adapters must not hide repeated failures by recursively relaunching themselves.

## Documentation Expectations

When a site becomes supported:

1. add or update `references/<site>.md`
2. describe supported task types and current script coverage
3. call out known flaky areas and when the agent should prefer direct browser
   actions
4. document output artifacts and user-action boundaries

If the site is not ready for full support, keep the user task result and use
`followups` to capture the next engineering step instead of overstating support.
