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
- For page operations, take a fresh `snapshot` after structure changes, use current refs, and verify URL/title/key elements after each click, fill, press, navigation, or list/detail transition.
- If login, CAPTCHA, MFA, or risk-control appears, keep the same Chrome window and ask the user to complete it there.
- If the task is public-page reading, archival, or content extraction and does not need login state, extension cookies, live clicking, or dynamic postback behavior, prefer a non-interactive fetch/extract path first. Use ActionBook only when static HTTP fetch is blocked, incomplete, or loses required data.
- Start long workflows through `scripts/actionbook_run.py` so later `中断` / `停止` can stop the process group.

## Default Loop

1. Route: read only the setup, status, site, or authoring reference needed for the task; first decide whether this task truly needs a live browser or can be completed by static fetch/extraction without touching foreground Chrome.
2. Bootstrap: if a live browser is required, use `scripts/actionbook_session.py acquire-tab --task <task-id>`; done when the returned session/tab is reachable and recorded. Reuse that explicit tab for the whole task. Avoid foreground activation unless the user must interact.
3. Operate: refresh `snapshot` after page structure changes and use current refs; done when URL, title, or key page elements prove each interaction landed.
4. Finish: stop for user gates, track long runs with `scripts/actionbook_run.py`, and preserve outputs; then call `release-tab --task <task-id>` unless the user must continue in that exact tab. For archival tasks, save one durable local file per page plus a manifest/index so the run can resume without reopening pages.

## Reference Routing

| Need | Read / Use |
| --- | --- |
| Setup, missing extension/CLI, unknown session state | `references/initialization.md`, `references/status-check.md` |
| Generic webpage to Markdown | `references/webpage-markdown.md`, `scripts/webpage_markdown.py` |
| Public page archival without login/clicking | static HTTP fetch plus local extraction first; only escalate to ActionBook if the fetched content is incomplete or blocked |
| Connect plugin; acquire, list, or release task tabs | `scripts/actionbook_session.py`, `references/status-check.md` |
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
python3 scripts/actionbook_run.py run --id <run-id> --cwd "$PWD" -- python3 scripts/adapters/<site>_workflow.py ...
python3 scripts/actionbook_run.py stop --id <run-id>
```

For manual checks:

```bash
actionbook extension status --json
actionbook browser list-sessions --json
actionbook browser title --session s1 --tab <real-tab-id> --json
actionbook browser url --session s1 --tab <real-tab-id> --json
```
