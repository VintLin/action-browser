---
name: action-browser
description: "Use when an agent needs ActionBook or Chrome extension mode for real browser tasks, also known as 浏览器操作: opening pages, clicking, filling forms, searching, scrolling, popup handling, page-state reading, structured extraction, downloads, authenticated Chrome sessions, site workflow recovery, or stopping tracked browser workflows."
---

# 浏览器操作

Use ActionBook for real browser pages. Prefer `extension` mode when the task needs the user's Chrome login state, cookies, or existing browser environment. Do not switch modes unless the user confirms it.

## Before Acting

1. If the task names a supported site or capability, read the matching reference below before running commands.
2. For extension-mode tasks, start with `scripts/actionbook_session.py`; with an explicit `--session`, it reuses only that same session, opens a fresh tab when needed, and rebuilds only as a last resort.
3. Treat `session` as the browser container and `tab` as the task-level page context. For parallel work in one browser session, allocate one stable `tab id` per subtask and pass `--tab` explicitly after `list-tabs`, `new-tab`, or the session bootstrap returns the real tab id.
4. Do not assume a started extension session is reusable until a second CLI command can still access it. If the session disappears between commands, stop and repair the ActionBook runtime before scheduling tasks onto tabs.
5. Use the helper as the default boundary: `ensure`, `list-tabs`, `new-tab`, `select-tab`, and `close-tab` should go through `scripts/actionbook_session.py`. Keep raw `actionbook browser start/new-tab/list-tabs/close-tab` for diagnostics only.
6. If login, CAPTCHA, MFA, or risk-control appears, keep the same Chrome window and ask the user to complete it there.
7. For long workflows, downloads, profile crawls, and batch exports, run through `scripts/actionbook_run.py` so later `中断` / `停止` can stop the process group.

## References

Load only what applies:

| Need | Read / Use |
| --- | --- |
| Setup, missing ActionBook, Chrome, extension, CLI | `references/initialization.md` |
| Unknown daemon, extension, session, tab state | `references/status-check.md` |
| Generic webpage to Markdown | `references/webpage-markdown.md`, `scripts/webpage_markdown.py` |
| Generic session bootstrap | `scripts/actionbook_session.py` |
| Long run tracking and stopping | `scripts/actionbook_run.py` |
| Xiaohongshu | `references/adapters/xiaohongshu.md`, `scripts/adapters/xiaohongshu_workflow.py` |
| X / Twitter | `references/adapters/x.md`, `scripts/adapters/x_workflow.py` |
| Weibo | `references/adapters/weibo.md`, `scripts/adapters/weibo_workflow.py` |
| Douban | `references/adapters/douban.md`, `scripts/adapters/douban_workflow.py` |
| Zhihu | `references/adapters/zhihu.md`, `scripts/adapters/zhihu_workflow.py` |
| YouTube | `references/adapters/youtube.md`, `scripts/adapters/youtube_workflow.py` |
| Douyin | `references/adapters/douyin.md`, `scripts/adapters/douyin_workflow.py` |
| Bilibili | `references/adapters/bilibili.md`, `scripts/adapters/bilibili_workflow.py` |
| JD | `references/adapters/jd.md`, `scripts/adapters/jd_workflow.py` |
| Taobao | `references/adapters/taobao.md`, `scripts/adapters/taobao_workflow.py` |
| BOSS Zhipin | `references/adapters/zhipin.md`, `scripts/adapters/zhipin_workflow.py` |
| Feishu / Lark Drive | `references/adapters/feishu.md`, `scripts/adapters/feishu_workflow.py` |
| ChatGPT | `references/adapters/chatgpt.md`, `scripts/adapters/chatgpt_workflow.py` |

Keep this file site-neutral. Put site command catalogs, payload schemas, DOM details, output trees, login notes, and risk-control quirks in the matching reference.

## Startup

```bash
python3 scripts/actionbook_session.py ensure \
  --session s1 \
  --url "https://example.com" \
  --json
```

For multi-tab work in one session:

```bash
python3 scripts/actionbook_session.py list-tabs --session s1 --json
python3 scripts/actionbook_session.py new-tab --session s1 --url "https://example.com/a" --json
python3 scripts/actionbook_session.py new-tab --session s1 --url "https://example.com/b" --json
```

For manual checks:

```bash
actionbook extension status --json
actionbook browser list-sessions --json
python3 scripts/actionbook_session.py list-tabs --session s1 --json
actionbook browser title --session s1 --tab <real-tab-id> --json
actionbook browser url --session s1 --tab <real-tab-id> --json
```

Continue only when the extension is connected, the session exists, `list-tabs` returns at least one tab, and `title` / `url` can access the chosen tab. Treat `tabs_count: 0`, `list-tabs: []`, or `TAB_NOT_FOUND` as an invalid empty session and rebuild before business logic.

## Page Operation Pattern

```bash
actionbook browser snapshot --session s1 --tab <real-tab-id>
actionbook browser click @e7 --session s1 --tab <real-tab-id> --timeout 8000
actionbook browser fill @e3 "keyword" --session s1 --tab <real-tab-id> --timeout 5000
actionbook browser press Enter --session s1 --tab <real-tab-id> --timeout 5000
actionbook browser url --session s1 --tab <real-tab-id> --json
```

Rules:

- Run `snapshot` after page structure changes and use the latest refs.
- Prefer refs from `snapshot` over remembered selectors.
- For concurrent subtasks, do not share one mutable tab pointer. Keep one explicit tab id per subtask and pass it through every command or workflow.
- Treat `timeout` as the failure ceiling, not a wait strategy.
- After each operation, verify URL, title, key elements, list count, or detail container state.
- Wait for explicit state with `wait navigation`, `wait element`, or `eval`; avoid fixed sleeps except brief animation waits under 1 second.
- On `TIMEOUT`: refresh snapshot, check stale refs, try one alternative reliable entry, retry once, then record current URL and error.

For lists and detail popups, confirm detail opened, close it, then confirm the list page is restored before clicking the next item. Prefer `Escape`, then close button, then browser back or `history.back()`.

## Long Runs And Stops

Start long workflows through the wrapper:

```bash
python3 scripts/actionbook_run.py run \
  --id <run-id> \
  --cwd "$PWD" \
  -- \
  python3 scripts/<site>_workflow.py ...
```

When the user asks to stop:

1. Send `Ctrl-C` to any live terminal session if present.
2. Stop the tracked run:

```bash
python3 scripts/actionbook_run.py stop --id <run-id>
```

3. If the id is unknown, list active runs and stop the relevant one:

```bash
python3 scripts/actionbook_run.py list --active
```

4. Verify no workflow script remains:

```bash
ps aux | grep -E 'actionbook_run.py|_workflow.py' | grep -v grep
```

5. Report stop result, output directory, and durable evidence such as `summary.json`, `metadata.json`, folder count, or the last completed log line.

Use `stop --all` only when the user clearly wants every ActionBook workflow stopped, or all active runs belong to the current task.

## Scheduler (First Pass)

- Use `scripts/scheduler.py` for `submit`, `list`, `status`, and `stop`.
- `reconcile` is reserved for recovery work but is not implemented in the first pass yet.
- First-pass extension scheduling assumes one shared browser session and one leased tab per running task.
- Scheduler-managed tasks open exclusive tabs with `--force-new-tab --no-adopt`.
- The first pass integrates one adapter contract through Taobao.
- Legacy workflow records stay at the output root; scheduler contract files live under `contract/`.
- Unsupported sites still default to direct agent browser work first.
