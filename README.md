# Action Browser

Action Browser is a portable agent skill for controlling a real browser through ActionBook. It gives an agent a repeatable workflow for opening pages, clicking, filling forms, reading page state, handling login-dependent sites, and exporting structured web data.

It is designed for tasks that need a real browser context instead of plain HTTP fetching, especially when the user's Chrome cookies, login state, extensions, or existing tabs matter.

## What This Does

Action Browser wraps ActionBook browser automation into a skill-oriented workflow. It provides:

- Browser session bootstrap and health checks
- Stable ref-based page operations through ActionBook snapshots
- Login-aware workflows for sites that need the user's Chrome session
- Long-running workflow tracking and interruption handling
- Site-specific extraction helpers for social, video, and content platforms
- Webpage-to-Markdown extraction using a browser-rendered page

The skill favors observable browser state over fixed sleeps. After each operation it checks URL, title, visible elements, list counts, or extracted payloads before continuing.

## Key Features

- Real Browser Control: operate local or Chrome extension browser sessions through ActionBook.
- Extension Mode First: reuse the user's Chrome login state when a task depends on cookies or authenticated pages.
- Session Recovery: reuse healthy sessions, open a new tab when possible, and rebuild only when the session is invalid.
- Stable Interaction Model: use snapshot refs such as `@e3` and `@e7` instead of fragile remembered selectors.
- Long-Running Runs: start crawls and exports through a tracked process wrapper so they can be stopped cleanly.
- Platform Workflows: includes helpers for Xiaohongshu, X, Weibo, Douban, Zhihu, YouTube, Douyin, and Bilibili.
- Markdown Capture: extract rendered webpages into Markdown with metadata.

## Installation

### For Agent Skill Users

Clone or copy this repository into your agent's skills directory:

```bash
git clone https://github.com/VintLin/action-browser.git <skills-dir>/action-browser
```

Then invoke the skill by asking your agent to use `浏览器操作` or `action-browser` for browser tasks.

### Manual Copy

If you already have a local copy:

```bash
mkdir -p <skills-dir>/action-browser
rsync -a ./ <skills-dir>/action-browser/
```

## Requirements

- An agent runtime with local skill support
- Python 3.10+
- Node.js 18+
- Google Chrome for extension-mode workflows
- ActionBook CLI:

```bash
npm install -g @actionbookdev/cli
```

For a first-time setup, run:

```bash
actionbook setup
```

If the task needs the user's logged-in Chrome session, configure extension mode and install the ActionBook Chrome extension:

```bash
actionbook setup --browser extension --non-interactive
```

The initialization guide is in `references/initialization.md`.

## Usage

### Open And Inspect A Page

Ask your agent to use the skill:

```text
使用浏览器操作打开 https://example.com，并读取页面主要内容。
```

The skill will bootstrap an ActionBook session, open or reuse a browser tab, take a snapshot, and operate on the latest page refs.

### Start A Reusable Browser Session

```bash
python3 scripts/actionbook_session.py ensure \
  --session task-browser \
  --url "https://example.com" \
  --json
```

The script returns a usable `session_id` and `tab_id`. It first tries to reuse a healthy session, then opens a new tab in that session, and only creates a new session as a fallback.

### Work With Multiple Tabs In One Session

Use one session when tasks need the same logged-in browser context, then give each subtask its own explicit tab id:

```bash
python3 scripts/actionbook_session.py ensure --session research --url "https://example.com" --json
python3 scripts/actionbook_session.py new-tab --session research --url "https://example.com/a" --json
python3 scripts/actionbook_session.py new-tab --session research --url "https://example.com/b" --json
python3 scripts/actionbook_session.py list-tabs --session research --json
```

Pass the returned `tab_id` into each workflow with `--tab`. Do not let parallel tasks share one implicit current tab.

### Run A Long Workflow

Use the run wrapper when a workflow may take time or needs a clean stop path:

```bash
python3 scripts/actionbook_run.py run \
  --id xhs-profile-download \
  --cwd "$PWD" \
  -- \
  python3 scripts/xiaohongshu_workflow.py profile download \
    --session xhs-profile-download \
    --profile-url "https://www.xiaohongshu.com/user/profile/..." \
    --count all \
    --output-dir "$PWD/output/xhs-profile"
```

Stop it later with:

```bash
python3 scripts/actionbook_run.py stop --id xhs-profile-download
```

## Scheduler (First Pass)

- Use `scripts/scheduler.py` for `submit`, `list`, `status`, `stop`, and `reconcile`.
- Scheduler-managed tasks open exclusive tabs with `--force-new-tab --no-adopt`.
- The first pass integrates one adapter contract through Taobao.
- Unsupported sites still default to direct agent browser work first.

### Extract A Rendered Webpage To Markdown

```bash
python3 scripts/webpage_markdown.py capture \
  --session page-capture \
  --url "https://example.com" \
  --output-dir "$PWD/output/page"
```

## Included Workflows

| Script | Purpose |
| --- | --- |
| `scripts/actionbook_session.py` | Ensure a usable ActionBook browser session and tab. |
| `scripts/actionbook_run.py` | Run, stop, inspect, and list tracked long-running workflows. |
| `scripts/webpage_markdown.py` | Capture a rendered webpage or local HTML as Markdown. |
| `scripts/xiaohongshu_workflow.py` | View and download Xiaohongshu notes, search results, profiles, feeds, favorites, and likes. |
| `scripts/x_workflow.py` | View and download X home, bookmarks, tweets, threads, searches, profiles, and current account posts. |
| `scripts/weibo_workflow.py` | View and download Weibo posts, profiles, searches, feeds, comments, favorites, and user data. |
| `scripts/douban_workflow.py` | View Douban search, charts, subjects, photos, marks, and reviews. |
| `scripts/zhihu_workflow.py` | View Zhihu hot lists, recommendations, searches, questions, answers, collections, and export articles. |
| `scripts/youtube_workflow.py` | View YouTube search, video metadata, transcripts, comments, channels, playlists, feeds, history, watch later, and subscriptions. |
| `scripts/douyin_workflow.py` | View Douyin creator pages, videos, collections, activities, hashtags, locations, stats, and public user videos. |
| `scripts/bilibili_workflow.py` | View Bilibili hot lists, rankings, search, videos, comments, dynamics, history, following, subtitles, and summaries. |
| `scripts/jd_workflow.py` | View JD product search, item details, reviews, cart, and current account state. |
| `scripts/taobao_workflow.py` | View Taobao product search, item details, reviews, cart, and current account state. |
| `scripts/zhipin_workflow.py` | View BOSS 直聘 filters, recommendation lists, keyword search/detail crawls, and chat metadata with DOM fallback for blocked APIs. |

## Output Structure

Typical workflow outputs are written to the directory passed with `--output-dir`. Depending on the workflow, outputs may include:

- `summary.json`
- `metadata.json`
- extracted Markdown files
- structured JSON payloads
- downloaded media assets
- per-item folders for batch exports

Long-running run state is stored outside the project at:

```text
~/.action-browser/runs/
```

## Architecture

This skill uses progressive disclosure:

| File | Purpose | Loaded When |
| --- | --- | --- |
| `SKILL.md` | Core rules, browser operation flow, waiting strategy, and stop handling. | Always when the skill is invoked. |
| `references/initialization.md` | ActionBook, Node.js, Chrome, CLI, and extension setup. | When the local ActionBook environment is missing or incomplete. |
| `references/status-check.md` | Minimal checks before starting browser work. | When daemon, extension, session, or tab state is uncertain. |
| `references/*.md` | Site-specific workflows and payload expectations. | Only for the matching site task. |
| `scripts/*.py` | Reusable workflow helpers and extraction scripts. | When the task needs automation beyond one-off browser operations. |
| `agents/openai.yaml` | Skill metadata for compatible agent interfaces. | When a tool reads skill display metadata. |

## Operating Principles

1. Use one stable session id per task or task group.
2. Confirm the real tab id before interacting with a page.
3. For parallel work in one session, allocate one stable tab id per subtask and pass `--tab` explicitly.
4. Take a fresh snapshot after page structure changes.
5. Use snapshot refs over remembered selectors.
6. Treat timeouts as failure ceilings, not as a waiting strategy.
7. Stop for login, CAPTCHA, MFA, and risk-control pages so the user can complete them in the same browser session.
8. Track long workflows so interruption can stop the underlying process group.

## Safety Boundaries

Action Browser does not read, save, or submit user passwords, cookies, tokens, API keys, or other secrets. Login and risk-control steps remain user-controlled in the browser.

Some target sites may change their DOM, API responses, login flow, or anti-automation behavior. The workflow references document the expected payloads and known recovery steps, but site-specific helpers should be treated as operational scripts that require maintenance.

## Credits

Built around ActionBook and packaged as a portable agent skill.
