---
name: action-browser
description: "Use when a task needs real browser interaction through ActionBook, Chrome extension login state, site adapters, browser session repair, batch browser workflows, downloads, or adapter maintenance after site UI drift."
---

# 浏览器操作

Use ActionBook for real browser pages. Prefer `extension` mode when the task needs the user's Chrome login state, cookies, or existing browser environment. Do not switch modes unless the user confirms it.

## Core Rules

- First-run setup is not optional for most adapters: no API key is needed, use `actionbook-extension-v0.5.0.zip`, and ask the user to install the unpacked extension in `chrome://extensions/`.
- Browser/account selection must preserve the user's current context. First use the system default browser. If Chrome extension mode is required, use the currently focused or most recently used Chrome window/profile/account. Do not open another Chrome profile/account with `--profile-directory` unless the user explicitly names it.
- Before extension-mode work, confirm the selected/default/current browser has Actionbook installed, enabled, connected, and version `0.5.0`. If it is missing, disconnected, or a different version, stop and tell the user exactly what to fix in that same browser/profile; do not silently open or switch to another browser/profile.
- If setup, extension, daemon, bridge, session, or tab state is unclear, read `references/initialization.md` or `references/status-check.md` before site work.
- If a supported site or capability is named, read `references/adapters/<site>.md` before running commands.
- If a supported site's UI drift breaks the documented workflow, or an unsupported site is likely to be reused, the agent may update this skill's adapter script and reference docs. Read `references/adapter-authoring.md` first and keep the patch scoped to observed site behavior.
- Treat `session` as the browser container and `tab` as the task page. Use one explicit tab id per subtask; do not share a mutable current tab pointer.
- Use `scripts/actionbook_session.py` for `ensure`, `list-tabs`, `new-tab`, `select-tab`, and `close-tab`. Keep raw `actionbook browser start/new-tab/list-tabs/close-tab` for diagnostics only.
- Continue only after a second CLI command proves the session and selected tab are still accessible.
- If `extension status` is `bridge: not_listening` or `extension_connected: false`, do not declare the browser unusable from one check. Run `actionbook browser start --mode extension ...`, poll again, or run `scripts/diagnostics/actionbook_diagnose.py`; only stop when the same browser/profile still cannot connect after that bootstrap.
- If `browser start` opens a page but the next command returns `SESSION_NOT_FOUND`, treat it as daemon/session persistence failure. Restart the ActionBook daemon, avoid stale fixed session names, and prefer a tracked workflow that creates and uses its tab in one process.
- For page operations, take a fresh `snapshot` after structure changes, use current refs, and verify URL/title/key elements after each click, fill, press, navigation, or list/detail transition.
- If login, CAPTCHA, MFA, or risk-control appears, keep the same Chrome window and ask the user to complete it there.
- Start long workflows through `scripts/actionbook_run.py` so later `中断` / `停止` can stop the process group.

## Default Loop

1. Route: read only the setup, status, site, or authoring reference needed for the task; done when the browser mode, site path, and required command are known.
2. Bootstrap: use `scripts/actionbook_session.py ensure` and a second session/tab command; done when the same session is reachable and the real tab id is known.
3. Operate: refresh `snapshot` after page structure changes and use current refs; done when URL, title, or key page elements prove each interaction landed.
4. Finish: stop for user gates, track long runs with `scripts/actionbook_run.py`, and preserve outputs; done when results, failures, or current browser state are durable enough to resume.

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
