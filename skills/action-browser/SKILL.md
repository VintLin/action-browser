---
name: action-browser
description: "Use when a task needs real browser interaction through ActionBook, Chrome extension login state, site adapters, browser session repair, batch browser workflows, downloads, or adapter maintenance after site UI drift."
---

# 浏览器操作

Use ActionBook for real browser pages. Prefer `extension` mode when the task needs the user's Chrome login state, cookies, or existing browser environment. Do not switch modes unless the user confirms it.

## Core Rules

- First-run setup is not optional for most adapters: no API key is needed, use `actionbook-extension-v0.5.0.zip`, and ask the user to install the unpacked extension in `chrome://extensions/`.
- If setup, extension, daemon, bridge, session, or tab state is unclear, read `references/initialization.md` or `references/status-check.md` before site work.
- Do not steal foreground focus by default. Reuse an existing Chrome process/window without repeatedly activating it. If a live browser task has no Chrome process or browser window, one cold-start launch/window creation is allowed; session repair must still prefer background-safe checks first.
- If a supported site or capability is named, read `references/adapters/<site>.md` before running commands.
- If a supported site's UI drift breaks the documented workflow, or an unsupported site is likely to be reused, the agent may update this skill's adapter script and reference docs. Read `references/adapter-authoring.md` first and keep the patch scoped to observed site behavior.
- Treat `session` as the browser container and `tab` as the task page. Give every independent task a stable task id and acquire one owned tab with `acquire-tab`; tasks may run concurrently in separate tabs of the same healthy session.
- Use `scripts/actionbook_session.py` for `acquire-tab`, `list-task-tabs`, and `release-tab`. Managed tab opens and closes share a short mutation lock, while page operations remain parallel. If ActionBook reattaches a closed page under a replacement id, the helper closes the unique Chrome tab matching its URL/title and verifies that the replacement disappeared. Ambiguous duplicate URLs remain a safe failure for manual `chrome:control-chrome` cleanup. Keep `ensure`, raw tab commands, and raw `actionbook browser start/new-tab/list-tabs/close-tab` for one-off work or diagnostics.
- If `acquire-tab` cannot create the named extension session but another running extension session is healthy, opt in with `--adopt-running-session` before falling back to diagnostics.
- Continue only after a second CLI command proves the session and selected tab are still accessible.
- If the host may reap child processes when one exec call returns, do not split acquire and workflow work across exec calls. A successful acquire followed by `SESSION_NOT_FOUND` only after the outer call exits is a process-lifetime failure, not proof that the extension is broken. Use `scripts/actionbook_task.py` for one atomic workflow that is expected to finish without user interaction; use a 持久 PTY when several commands must reuse the same session/tab or 可能出现 User Gate。
- `actionbook_task.py` requires a task id without an existing live lease. If that task already owns a tab, it exits without running or releasing it; finish or release the existing task, or choose a unique task id. Any automatic retry must happen inside the child workflow so it keeps the same tab.
- For page operations, take a fresh `snapshot` after structure changes, use current refs, and verify URL/title/key elements after each click, fill, press, navigation, or list/detail transition.
- If login, CAPTCHA, MFA, or risk-control appears, keep the same Chrome window and ask the user to complete it there.
- If the task is public-page reading, archival, or content extraction and does not need login state, extension cookies, live clicking, or dynamic postback behavior, prefer a non-interactive fetch/extract path first. Use ActionBook only when static HTTP fetch is blocked, incomplete, or loses required data.
- Start long workflows through `scripts/actionbook_run.py` so later `中断` / `停止` can stop the process group.

## Default Loop

1. Route: read only the setup, status, site, or authoring reference needed for the task; first decide whether this task truly needs a live browser or can be completed by static fetch/extraction without touching foreground Chrome.
2. Bootstrap: if a live browser is required, use `scripts/actionbook_session.py acquire-tab --task <task-id>` when the host preserves daemon children between commands. In an ephemeral exec host, use `scripts/actionbook_task.py` so acquire, workflow, and release share one parent process. Done means a second CLI command in that same lifetime reaches the returned session/tab.
3. Operate: refresh `snapshot` after page structure changes and use current refs; done when URL, title, or key page elements prove each interaction landed.
4. Finish: stop for user gates, track long runs with `scripts/actionbook_run.py`, and preserve outputs; then call `release-tab --task <task-id>` unless the user must continue in that exact tab. For archival tasks, save one durable local file per page plus a manifest/index so the run can resume without reopening pages.

## Reference Routing

| Need | Read / Use |
| --- | --- |
| Setup, missing extension/CLI, unknown session state | `references/initialization.md`, `references/status-check.md` |
| Generic webpage to Markdown | `references/webpage-markdown.md`, `scripts/webpage_markdown.py` |
| Public page archival without login/clicking | static HTTP fetch plus local extraction first; only escalate to ActionBook if the fetched content is incomplete or blocked |
| Connect plugin; acquire, list, or release task tabs | `scripts/actionbook_session.py`, `references/status-check.md` |
| Exec host reaps daemon children; atomic browser workflow | `scripts/actionbook_task.py`, `references/status-check.md` |
| Page operations, waits, list/detail transitions | `references/adapter-operation-boundaries.md`, `references/status-check.md` |
| Long run tracking and stopping | `scripts/actionbook_run.py`, `references/task-lifecycle.md` |
| Adapter creation, UI drift, new reusable site support | `references/adapter-authoring.md`, `references/adapter-operation-boundaries.md` |
| Workflow runtime helpers and new workflow template | `references/workflow-toolkit.md`, `scripts/adapters/workflow_template.py` |
| Scheduler task lifecycle | `scripts/scheduler.py`, `references/task-lifecycle.md` |

Supported site adapters live in `references/adapters/<site>.md` and `scripts/adapters/<site>_workflow.py`.

Current sites: `xiaohongshu`, `x`, `weibo`, `douban`, `zhihu`, `youtube`, `douyin`, `bilibili`, `jd`, `taobao`, `zhipin`, `feishu`, `chatgpt`, `reddit`.

Expansion candidates (implemented but not yet `Supported Website`): `google`, `github`, `stackoverflow`, `hackernews`, `wikipedia`, `linkedin`.

Keep this file site-neutral. Put site command catalogs, payload schemas, DOM details, output trees, login notes, and risk-control quirks in the matching reference.

## Minimal Commands

```bash
python3 scripts/actionbook_session.py acquire-tab --task task-a --session shared --url "https://example.com" --adopt-running-session --json
python3 scripts/actionbook_session.py acquire-tab --task task-b --session shared --url "https://example.org" --adopt-running-session --json
python3 scripts/actionbook_session.py list-task-tabs --json
actionbook browser snapshot --session shared --tab <task-a-tab-id>
python3 scripts/actionbook_session.py release-tab --task task-a --json
python3 scripts/actionbook_session.py release-tab --task task-b --json
```

For long runs:

```bash
python3 scripts/actionbook_run.py run --id <run-id> --cwd "$PWD" -- \
  python3 scripts/actionbook_task.py \
    --task <task-id> --session <session-id> --url "https://example.com" --adopt-running-session --cwd "$PWD" -- \
    python3 scripts/adapters/<site>_workflow.py ...
python3 scripts/actionbook_run.py stop --id <run-id>
```

`actionbook_task.py` exports `ACTIONBOOK_TASK_ID`, `ACTIONBOOK_SESSION_ID`, and `ACTIONBOOK_TAB_ID` to the child workflow and releases its newly acquired tab on success, failure, SIGINT, or SIGTERM. It refuses to take over an existing task tab. Use it only when the child can finish without user interaction, including any same-tab retries. When several separate commands must share one tab or 可能出现 User Gate，start a 持久 PTY, run `acquire-tab` and the second CLI verification inside it, send later commands through that PTY, then release before exiting.

For manual checks:

```bash
actionbook extension status --json
actionbook browser list-sessions --json
actionbook browser title --session s1 --tab <real-tab-id> --json
actionbook browser url --session s1 --tab <real-tab-id> --json
```
