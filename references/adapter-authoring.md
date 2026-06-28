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

## Ownership Boundaries

- The adapter works inside the tab assigned by the scheduler.
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
  progress.json
  artifacts/
```

If the adapter creates additional files, keep them under the same output root
so the scheduler can treat the directory as one durable task artifact set.

## File Contract

Every adapter-owned JSON file must include `schema_version`. Adapters do not
own scheduler snapshots, `state.lock`, or `events.jsonl`, but their output must
remain compatible with the scheduler's file-based persistence model.

Rules:

- the scheduler takes `state.lock` before it updates scheduler snapshots
- the scheduler appends lifecycle decisions to `events.jsonl`
- the adapter writes `summary.json` and `progress.json` atomically
- JSON stays readable after crashes or process kills

An adapter should never edit `~/.action-browser/scheduler/state.json`
directly.

## summary.json

`summary.json` is the final task outcome as seen by the scheduler and the user.

Example:

```json
{
  "schema_version": 1,
  "ok": true,
  "site": "taobao",
  "intent": "search",
  "requested_count": 20,
  "collected_count": 18,
  "artifacts": ["results.json"],
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

## progress.json

`progress.json` is the mutable execution snapshot for recovery and user-facing
status.

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
