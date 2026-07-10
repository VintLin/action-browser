# Workflow Toolkit

`scripts/workflow_runtime.py` is the shared module for every `scripts/adapters/*_workflow.py` browser command. A workflow owns site behavior; it does not create, adopt, or release its main tab.

## Lifecycle

```text
actionbook_session.py acquire-tab
  -> workflow receives task-id/session/tab
  -> attach_workflow verifies the owned tab
  -> site logic uses evaluate/wait/temporary_tab/write_json
  -> actionbook_session.py release-tab
```

Acquire and release stay outside the workflow so user gates can keep the exact tab alive and concurrent tasks cannot silently replace each other's tabs. Tab creation and close verification take a shared short mutation lock; the workflow work between them remains fully parallel.

## Shared Interface

| Helper | Responsibility |
| --- | --- |
| `add_workflow_args(parser)` | Add `--task-id`, `--session`, and `--tab` consistently |
| `attach_workflow(args, expected_url)` | Require and verify the owned tab; navigate only when its origin is wrong |
| `evaluate(book, script, label)` | Unwrap ActionBook results and retry transient context loss |
| `wait_until_stable(book)` | Return stable page state, or the last state at timeout; set `require_stable=True` only when stability is a hard precondition |
| `temporary_tab(book, url)` | Open a local detail tab and run verified close, including unique Chrome replacement cleanup, without hiding the primary workflow error |
| `write_json(path, data)` | Atomically replace durable JSON output |

Site-specific selectors, payload parsing, user-gate detection, output presentation, and domain naming remain in the matching workflow.

## New Workflow

1. Copy `scripts/adapters/workflow_template.py` to `<site>_workflow.py`.
2. Add browser args with `add_workflow_args`; never add a default session or auto-create a tab.
3. Call `attach_workflow` once per browser command.
4. Use `temporary_tab` for every detail tab; do not write manual `try/finally close-tab` loops.
5. Use `evaluate`, `wait_until_stable`, and `write_json` before adding site-local equivalents.
6. Add the site reference and focused tests, then update `Current sites` in `SKILL.md`.

## Invocation

```bash
python3 scripts/actionbook_session.py acquire-tab \
  --task example-view \
  --session shared \
  --url https://example.com \
  --adopt-running-session \
  --json

python3 scripts/adapters/example_workflow.py \
  --task-id example-view \
  --session <returned-session-id> \
  --tab <returned-tab-id> \
  --output output/example.json

python3 scripts/actionbook_session.py release-tab --task example-view --json
```

For a sequence of commands owned by one task, the same explicit context can be passed through `ACTIONBOOK_TASK_ID`, `ACTIONBOOK_SESSION_ID`, and `ACTIONBOOK_TAB_ID`. CLI flags override those variables. Do not share one mutable environment across concurrent tasks.

`attach_workflow` checks this context against the task registry before touching the browser. A workflow cannot attach to another task's tab merely by receiving its id.
