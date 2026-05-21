---
name: 浏览器操作
description: Use ActionBook to control a real browser for website operations, including opening pages, clicking, filling forms, searching, scrolling, handling popups, reading page state, and extracting structured data. Use when Codex needs Chrome extension mode, existing Chrome login state or cookies, ActionBook sessions/tabs/snapshots, site automation with stable refs, or browser task recovery and status checks.
---

# 浏览器操作

Use ActionBook to control real browser pages. Prefer this skill for opening websites, clicking, filling forms, searching, scrolling, handling popups, reading page state, and extracting structured data.

When the task needs the user's Chrome login state, cookies, or an existing browser environment, use `extension` mode first. Do not switch to another mode unless the user confirms it.

## References

Load these only when needed:

- `references/initialization.md`: use when ActionBook, Node.js, Chrome, CLI setup, config, or extension installation is missing or incomplete.
- `references/status-check.md`: use before a task when the environment, daemon, extension, session, or tab state is uncertain.
- `references/xiaohongshu.md`: use for Xiaohongshu-specific search workflows, profile browsing, note details, popup closing, summarizing, downloading, and the fixed detail-popup payload schema including post images vs comment images.
- `references/x.md`: use for X-specific home timeline, bookmarks, tweet, thread, search, profile, and me workflows, structured tweet payloads, local output locations, and X login/risk-control handling.
- `references/weibo.md`: use for Weibo-specific post, profile, search, structured post payloads, local output locations, and Weibo login/risk-control handling.
- `references/douban.md`: use for Douban-specific search, charts, subject details, movie photos, photo downloads, marks, reviews, local output locations, and Douban login/risk-control handling.
- `references/zhihu.md`: use for Zhihu-specific hot, recommend, search, question, answer-detail, collections, collection, article Markdown downloads, local output locations, and Zhihu login/risk-control handling.
- `references/youtube.md`: use for YouTube-specific search, video metadata, transcripts/subtitles, comments, channels, playlists, feed, history, watch-later, subscriptions, local output locations, and YouTube login/risk-control handling.
- `references/douyin.md`: use for Douyin-specific creator profile, videos, drafts, collections, activities, hashtags, locations, stats, public user videos, local output locations, and Douyin login/risk-control handling.
- `references/bilibili.md`: use for Bilibili-specific hot, ranking, search, video metadata, comments, dynamic/feed, history, profile, following, user videos, subtitles, summaries, local output locations, and Bilibili login/risk-control handling.
- `references/webpage-markdown.md`: use for site-agnostic webpage-to-Markdown extraction based on the Obsidian Web Clipper Defuddle pipeline.
- `scripts/actionbook_session.py`: use as the generic extension-session bootstrap for any site task that needs "reuse healthy session -> open new tab -> rebuild as last resort".
- `scripts/actionbook_run.py`: use as the generic run/stop wrapper for long-running site workflows, especially downloads, profile crawls, and batch exports.
- `scripts/actionbook_interrupts.py`: shared signal handling used by workflow scripts so `SIGINT` and `SIGTERM` exit as `KeyboardInterrupt` with code `130`.
- `scripts/xiaohongshu_workflow.py`: use for complete Xiaohongshu search/profile runs when the user asks for multiple posts, summaries, or downloads.
- `scripts/x_workflow.py`: use for viewing or downloading structured X posts from home, bookmarks, tweet, thread, search, profile, or me.
- `scripts/weibo_workflow.py`: use for viewing or downloading structured Weibo posts from post, profile, search, or home pages.
- `scripts/douban_workflow.py`: use for viewing Douban search, charts, subject details, movie photos, marks, reviews, or downloading movie photos.
- `scripts/zhihu_workflow.py`: use for viewing Zhihu hot, recommend, search, question answers, answer details, collections, collection items, or downloading articles as Markdown.
- `scripts/youtube_workflow.py`: use for viewing YouTube search, video metadata, transcripts/subtitles, comments, channels, playlists, feed, history, watch-later, subscriptions, or downloading transcripts.
- `scripts/douyin_workflow.py`: use for viewing Douyin creator profile, videos, drafts, collections, activities, hashtags, locations, stats, or public user videos.
- `scripts/bilibili_workflow.py`: use for viewing Bilibili hot, ranking, search, video metadata, comments, dynamic/feed, history, profile, following, user videos, subtitles, or official summaries.
- `scripts/webpage_markdown.py`: use for converting a live tab, URL, or local HTML file into Markdown and metadata.

## Basic Rules

- Use one stable `session id` per task. Always pass `--session`. Pass `--tab` only after `list-tabs` or `browser start` confirms the real tab id. Do not assume `t1` exists.
- For long-running workflow scripts, use `scripts/actionbook_run.py run --id <run-id> -- ...` so the actual script can be stopped later even if the agent turn is interrupted.
- Confirm the ActionBook extension is connected before operating extension-mode tasks.
- Confirm the target session and tab are accessible before using the page. Treat `tabs_count: 0` or `list-tabs: []` as an invalid empty session and rebuild it immediately.
- Run `snapshot` after page structure changes and use the latest refs.
- Prefer refs from `snapshot` over remembered selectors.
- Treat `timeout` as the failure ceiling, not a wait strategy.
- After each operation, check URL, title, key elements, list count, or detail container state instead of sleeping.
- If login, CAPTCHA, MFA, or risk-control pages appear, keep the current session and tab, then ask the user to complete the step in the same Chrome window.
- If a site capability requires login and the current browser state is not logged in, stop that site's login-dependent workflow immediately. Tell the user which site and URL need login, wait for confirmation, then resume in the same Chrome session.

## Interrupts And Stops

Agent interruption does not always stop local processes that were launched by a skill. Treat user messages such as `中断`, `停止`, `停掉`, or `stop` as a request to stop both the current agent action and any tracked workflow script.

For long-running workflows, start the script through the run wrapper:

```bash
python3 /Users/Vint/.codex/skills/action-browser/scripts/actionbook_run.py run \
  --id xhs-profile-download \
  --cwd "$PWD" \
  -- \
  python3 /Users/Vint/.codex/skills/action-browser/scripts/xiaohongshu_workflow.py profile download \
    --session xhs-profile-download \
    --profile-url "https://www.xiaohongshu.com/user/profile/..." \
    --count all \
    --output-dir "$PWD/资源/.raw/profile-id"
```

The wrapper writes state files under `~/.codex/action-browser/runs/` with `pid`, `pgid`, command, cwd, status, and exit code. It starts the child command in its own process group.

All bundled workflow scripts (`*_workflow.py`) and `webpage_markdown.py` install the shared interrupt handler. A wrapped stop sends `SIGTERM` to the process group; scripts that receive it should return `130` rather than continuing to the next item. The wrapper records the final state even if the agent turn has already been interrupted.

When the user asks to stop:

1. If there is a live tool session, send `Ctrl-C` to it first.
2. Stop the tracked run:

```bash
python3 /Users/Vint/.codex/skills/action-browser/scripts/actionbook_run.py stop --id xhs-profile-download
```

3. If the run id is unknown, list active runs and stop the relevant one:

```bash
python3 /Users/Vint/.codex/skills/action-browser/scripts/actionbook_run.py list --active
python3 /Users/Vint/.codex/skills/action-browser/scripts/actionbook_run.py stop --id <run-id>
```

4. Verify no workflow script is still running:

```bash
ps aux | grep -E 'actionbook_run.py|_workflow.py' | grep -v grep
```

5. Report the stop result, output directory, and last durable evidence such as `summary.json`, `metadata.json`, folder count, or the last `已下载` log line.

Use `stop --all` only when the user clearly wants every ActionBook workflow stopped, or when all active runs are known to belong to the current task.

## Startup And Checks

For extension-mode tasks, prefer the generic bootstrap script first:

```bash
python3 /Users/Vint/.codex/skills/action-browser/scripts/actionbook_session.py \
  --session s1 \
  --url "https://example.com" \
  --json
```

The script returns a usable `session_id` and `tab_id`, and internally follows this order:

- Reuse the requested session if it already has an accessible tab.
- If the session exists but its tab is stale, open a new tab in that same session.
- If another healthy extension session already exists, reuse that session and open a new tab there.
- Create a new extension session only as the last resort.

Check extension installation and connection:

```bash
actionbook extension path
actionbook extension status --json
```

Usable extension state should include:

```json
{
  "bridge": "listening",
  "extension_connected": true
}
```

Start an extension session:

```bash
actionbook browser start \
  --mode extension \
  --set-session-id s1 \
  --open-url "https://example.com" \
  --timeout 30000
```

Use `--timeout 30000` only for `browser start` or first attach when Chrome extension wakeup and WebSocket handshake may be slow. Do not reuse 30 seconds for ordinary clicks, fills, or reads.

After startup, verify the real tab is accessible:

```bash
actionbook browser list-sessions --json
actionbook browser list-tabs --session s1 --json
actionbook browser title --session s1 --tab <real-tab-id> --json
actionbook browser url --session s1 --tab <real-tab-id> --json
```

Continue only when:

- `extension_connected` is `true`.
- `list-sessions` shows the target session.
- `list-tabs` returns at least one tab for the target session.
- `title` and `url` can access the chosen tab.
- If the session exists but `tabs_count` is `0`, `list-tabs` is empty, or the chosen tab returns `TAB_NOT_FOUND`, close that session and start a fresh one instead of retrying business logic.

## Page Operation Flow

Get a snapshot first:

```bash
actionbook browser snapshot --session s1 --tab t1
```

The snapshot returns refs such as `@e3` and `@e7`. Use these refs for interaction.

Common operations:

```bash
actionbook browser click @e7 --session s1 --tab t1 --timeout 8000
actionbook browser fill @e3 "keyword" --session s1 --tab t1 --timeout 5000
actionbook browser press Enter --session s1 --tab t1 --timeout 5000
```

Read state immediately after interactions:

```bash
actionbook browser url --session s1 --tab t1 --json
actionbook browser title --session s1 --tab t1 --json
```

If page state already matches the goal, continue. Add a short wait only for brief animation, page jitter, or dynamic lists still appearing; usually keep it under 1 second.

## Waiting Strategy

Wait for explicit state, not fixed time.

Useful commands:

```bash
actionbook browser wait navigation --session s1 --tab t1
actionbook browser wait element @e7 --session s1 --tab t1
actionbook browser eval "(() => ({ href: location.href, title: document.title, text: document.body.innerText.slice(0, 300) }))()" --session s1 --tab t1 --json
```

Recommended timeout ceilings:

- Startup or first attach: `10000ms`
- `goto` or obvious navigation: `5000-10000ms`
- Ordinary click, fill, or keypress: `2000-4000ms`
- URL, title, and state reads: default or `1000-3000ms`

For dynamic pages, different entries may have different interactability. On `TIMEOUT`, do this in order:

1. Run `snapshot` again and confirm the ref is not stale.
2. Try another reliable entry for the same target, such as title, button, or image.
3. Retry once only when the operation is clearly retryable.
4. If it still fails, record the error and current URL. Do not keep extending timeout blindly.

## Lists And Detail Popups

For feeds, search results, product lists, and similar list pages:

1. Run `snapshot` to get visible list items.
2. Choose a title, image, or button ref.
3. Click to open detail.
4. Confirm detail opened by URL, title, detail container, or body change.
5. Close detail.
6. Confirm the URL or key list element returned to the list page.

Close detail popups in this order:

```bash
actionbook browser press Escape --session s1 --tab t1 --timeout 5000
actionbook browser url --session s1 --tab t1 --json
```

If Escape fails, click the close button. If that fails, use `browser back` or page-side `history.back()`.

After closing, confirm the list page is restored before handling the next item. Do not continue clicking old list refs while still in a detail-page state.

## Site Workflow Scripts

For repeated site-specific browsing, prefer a workflow script over hand-running individual browser operations when the script already covers the requested flow.

For any workflow expected to run longer than a small sample, start it through `scripts/actionbook_run.py run` and choose a stable run id. Direct calls are acceptable for short `view`, `--help`, and small validation commands.

Keep this `SKILL.md` site-neutral. Do not add site command catalogs, payload schemas, DOM selectors, output trees, or login/risk-control quirks here. Put them in the matching reference document and load that document only for the requested site or capability.

Current site and capability references:

- Xiaohongshu: read `references/xiaohongshu.md`, then use `scripts/xiaohongshu_workflow.py`.
- X: read `references/x.md`, then use `scripts/x_workflow.py`.
- Weibo: read `references/weibo.md`, then use `scripts/weibo_workflow.py`.
- Douban: read `references/douban.md`, then use `scripts/douban_workflow.py`.
- Zhihu: read `references/zhihu.md`, then use `scripts/zhihu_workflow.py`.
- YouTube: read `references/youtube.md`, then use `scripts/youtube_workflow.py`.
- Douyin: read `references/douyin.md`, then use `scripts/douyin_workflow.py`.
- Bilibili: read `references/bilibili.md`, then use `scripts/bilibili_workflow.py`.
- Long-form webpage Markdown extraction: read `references/webpage-markdown.md`, then use `scripts/webpage_markdown.py`.

Rules for adding a new site:

1. Add `references/<site>.md` with the site's commands, channels, output paths, payload schema, login/risk-control handling, and known DOM issues.
2. Add one site workflow script when repeated operation is needed, preferably `scripts/<site>_workflow.py`.
3. Keep command examples inside `references/<site>.md`; in this file only add a one-line reference and script pointer.
4. Keep site scripts generic: navigation, extraction, summary, and download are appropriate. Project-specific filtering, classification, database writes, and plan updates are not.
5. Use `view` for structured summaries without per-item downloads, and `download` for summary plus local item folders, unless a site reference explicitly defines a narrower action.

## Forms And Search

Prefer submitting through real inputs. Do not build search URLs directly unless the site requires it.

Flow:

1. Open the target homepage.
2. Run `snapshot` and find the search box.
3. Use `fill` to enter the keyword.
4. Press `Enter` or click the search button.
5. Confirm the result page is stable by URL, title, result count, or filter bar.

If ordinary `fill` or `press Enter` is unstable, use `browser eval` to dispatch real input events:

```bash
actionbook browser eval "(() => {
  const input = document.querySelector('input[type=\"search\"], input[placeholder*=\"搜索\"], input');
  if (!input) return false;
  input.focus();
  input.value = '关键词';
  input.dispatchEvent(new InputEvent('input', { bubbles: true, data: '关键词', inputType: 'insertText' }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
  input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
  return true;
})()" --session s1 --tab t1 --json
```

## Data Reading

Read small amounts of state directly:

```bash
actionbook browser title --session s1 --tab t1 --json
actionbook browser url --session s1 --tab t1 --json
actionbook browser text --session s1 --tab t1
```

For structured extraction, return JSON from one `browser eval`:

```bash
actionbook browser eval "(() => {
  const text = el => (el?.innerText || el?.textContent || '').trim();
  const root = document.querySelector('main, article, #content') || document.body;
  return {
    title: text(root.querySelector('h1')),
    body: text(root),
    links: [...root.querySelectorAll('a[href]')].map(a => a.href),
    images: [...root.querySelectorAll('img')].map(img => img.currentSrc || img.src).filter(Boolean)
  };
})()" --session s1 --tab t1 --json
```

Limit the content scope during extraction. Avoid mixing navigation, comments, button labels, avatars, and icons into the target payload.

## Login And Risk Control

When login pages, account chooser, CAPTCHA, MFA, or security verification appear:

- Pause automation.
- Keep the current session and tab.
- Tell the user explicitly: the site name, the exact URL currently blocking, the action needed, and that they should reply after login or verification is complete.
- Do not keep testing other login-dependent features for that site until the user confirms login or verification is complete.
- Continue with the same session after the user confirms.
- Run `snapshot` again or reread page state after login.

Do not switch tools, rebuild the session, or close the browser just because a login page appears.

## Error Handling

With `--json`, ActionBook returns an envelope:

- `ok: true`: read `data`.
- `ok: false`: read `error.code`, `error.message`, and `error.retryable`.

Common errors:

- `CDP_NODE_NOT_FOUND`: ref is stale. Run `snapshot` again.
- `CDP_NOT_INTERACTABLE`: element is not interactable. Scroll it into view, close overlays, or use another entry.
- `TIMEOUT`: inspect page state and refs before raising timeout.
- `CDP_NAV_TIMEOUT`: navigation timed out. Retry only after checking network and page state.
- `CDP_TARGET_CLOSED`: tab or session closed. Check for external interference.
- `SESSION_NOT_FOUND`: session missing or daemon restarted. Check sessions.
- `EXTENSION_NOT_CONNECTED`: Chrome extension not connected. Ask the user to confirm the extension shows Connected.

Retry only errors that are clearly retryable. Treat login, risk control, and page structure changes as causes to inspect first.

## Daemon Recovery

If `browser start` succeeds but the next command returns `SESSION_NOT_FOUND`, `bridge: not_listening`, or an empty session list, check:

```bash
actionbook extension status --json
actionbook browser list-sessions --json
ps -p "$(sed -n '1p' ~/.actionbook/daemon.pid)" -o pid,ppid,state,command
lsof -nP -iTCP:19222 -sTCP:LISTEN
tail -n 120 ~/.actionbook/daemon.log
```

Preferred recovery:

```bash
actionbook daemon restart
actionbook browser start --mode extension --set-session-id s1 --open-url "https://example.com" --timeout 30000
actionbook extension status --json
actionbook browser list-tabs --session s1 --json
```

If the restarted session still shows no tabs, or `title/url` fails on the returned tab, close that session and create a new one. Do not keep retrying the same empty session id.

If the desktop environment cannot keep the automatic daemon alive across commands, temporarily host it with tmux:

```bash
tmux new-session -d -s actionbook-daemon 'actionbook __daemon'
```

Stop the hosted daemon:

```bash
tmux kill-session -t actionbook-daemon
```

Use tmux only when the automatic daemon repeatedly fails to persist.

## Script Wrapping

For repeated workflows, wrap these functions:

- `ensure_session()`: start or reuse a session.
- `run_actionbook()`: execute commands, add `--json`, and parse the envelope.
- `get_page_state()`: read URL, title, key elements, and errors.
- `wait_until_ready()`: poll for explicit state.
- `open_item()`: open a list item.
- `close_item()`: close detail and confirm list restoration.
- `extract_payload()`: extract structured data.

Log at least target URL, current state, success count, skipped reason, and error code.

## Command Cheatsheet

```bash
# State
actionbook extension status --json
actionbook browser list-sessions --json
actionbook browser list-tabs --session s1 --json

# Session
actionbook browser start --mode extension --set-session-id s1 --open-url "https://example.com" --timeout 30000
actionbook browser close --session s1

# Navigation
actionbook browser goto "https://example.com" --session s1 --tab t1
actionbook browser back --session s1 --tab t1
actionbook browser reload --session s1 --tab t1

# Observation
actionbook browser snapshot --session s1 --tab t1
actionbook browser url --session s1 --tab t1 --json
actionbook browser title --session s1 --tab t1 --json
actionbook browser text --session s1 --tab t1
actionbook browser screenshot /tmp/page.png --session s1 --tab t1

# Interaction
actionbook browser click @e7 --session s1 --tab t1 --timeout 8000
actionbook browser fill @e3 "text" --session s1 --tab t1 --timeout 5000
actionbook browser press Enter --session s1 --tab t1 --timeout 5000
actionbook browser scroll down --session s1 --tab t1

# Wait and eval
actionbook browser wait navigation --session s1 --tab t1
actionbook browser wait element @e7 --session s1 --tab t1
actionbook browser eval "document.title" --session s1 --tab t1 --json
```
