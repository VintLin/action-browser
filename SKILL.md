---
name: action-browser
description: "Use when a task needs real browser interaction through ActionBook, Chrome extension login state, site adapters, browser session repair, batch browser workflows, downloads, or adapter maintenance after site UI drift."
---

# 浏览器操作

Use ActionBook for real browser pages. Prefer `extension` mode when the task needs the user's Chrome login state, cookies, or existing browser environment. Do not switch modes unless the user confirms it.

## Core Rules

- First-run setup is not optional for most adapters: no API key is needed, use `actionbook-extension-v0.5.0.zip`, and ask the user to install the unpacked extension in `chrome://extensions/`.
- If setup, extension, daemon, bridge, session, or tab state is unclear, read `references/initialization.md` or `references/status-check.md` before site work.
- If a supported site or capability is named, read `references/adapters/<site>.md` before running commands.
- If a supported site's UI drift breaks the documented workflow, or an unsupported site is likely to be reused, the agent may update this skill's adapter script and reference docs. Read `references/adapter-authoring.md` first and keep the patch scoped to observed site behavior.
- Treat `session` as the browser container and `tab` as the task page. Use one explicit tab id per subtask; do not share a mutable current tab pointer.
- Use `scripts/actionbook_session.py` for `ensure`, `list-tabs`, `new-tab`, `select-tab`, and `close-tab`. Keep raw `actionbook browser start/new-tab/list-tabs/close-tab` for diagnostics only.
- Continue only after a second CLI command proves the session and selected tab are still accessible.
- For page operations, take a fresh `snapshot` after structure changes, use current refs, and verify URL/title/key elements after each click, fill, press, navigation, or list/detail transition.
- If login, CAPTCHA, MFA, or risk-control appears, keep the same Chrome window and ask the user to complete it there.
- Start long workflows through `scripts/actionbook_run.py` so later `中断` / `停止` can stop the process group.

## Reference Routing

| Need | Read / Use |
| --- | --- |
| Setup, missing extension/CLI, unknown session state | `references/initialization.md`, `references/status-check.md` |
| Generic webpage to Markdown | `references/webpage-markdown.md`, `scripts/webpage_markdown.py` |
| Generic session/tab commands | `scripts/actionbook_session.py`, `references/status-check.md` |
| Page operations, waits, list/detail transitions | `references/adapter-operation-boundaries.md`, `references/status-check.md` |
| Long run tracking and stopping | `scripts/actionbook_run.py`, `references/task-lifecycle.md` |
| Adapter creation, UI drift, new reusable site support | `references/adapter-authoring.md`, `references/adapter-operation-boundaries.md` |
| Scheduler task lifecycle | `scripts/scheduler.py`, `references/task-lifecycle.md` |

Supported site adapters live in `references/adapters/<site>.md` and `scripts/adapters/<site>_workflow.py`.

Current sites: `xiaohongshu`, `x`, `weibo`, `douban`, `zhihu`, `youtube`, `douyin`, `bilibili`, `jd`, `taobao`, `zhipin`, `feishu`, `chatgpt`.

Keep this file site-neutral. Put site command catalogs, payload schemas, DOM details, output trees, login notes, and risk-control quirks in the matching reference.

## Minimal Commands

```bash
python3 scripts/actionbook_session.py ensure --session s1 --url "https://example.com" --json
python3 scripts/actionbook_session.py list-tabs --session s1 --json
actionbook browser snapshot --session s1 --tab <real-tab-id>
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
