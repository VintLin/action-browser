# ChatGPT Workflow

> 所有 `*_workflow.py` 示例都假定当前 task 已通过 `acquire-tab` 领取 tab，并设置 `ACTIONBOOK_TASK_ID`、`ACTIONBOOK_SESSION_ID`、`ACTIONBOOK_TAB_ID`；也可在命令中显式传入同名参数。并行 task 不得共享同一组环境变量。

This reference covers `chatgpt_workflow.py`, a Chrome extension-mode workflow
for asking ChatGPT questions through the web UI and exporting ChatGPT
conversation replies to local Markdown.

Common entry rules live in `../../SKILL.md`; adapter runtime boundaries live in
`../adapter-operation-boundaries.md`.

## Goal

The workflow can:

1. Open `https://chatgpt.com/` with the user's Chrome login state.
2. Create one new chat or many new chats from local JSON / JSONL tasks.
3. Enable web search through the ChatGPT UI, log the verified search state, and try to select Pro extension.
4. Send each question and confirm the conversation started.
5. Write `submissions.json` and `failures.json` for submitted questions.
6. Reopen or locate existing conversations from the sidebar.
7. Export existing conversation replies to local Markdown through `export`.

Final answer extraction prefers the macOS system clipboard. The workflow writes
a sentinel, clicks ChatGPT's `复制回复` / `Copy response` button, and uses the
changed clipboard when available. If the copy control is missing or the
clipboard does not change but the latest assistant message DOM text is readable,
`export` records `method: dom-fallback` and writes that text instead.

## Commands

Ask one question and record the submitted conversation URL:

```bash
python3 scripts/adapters/chatgpt_workflow.py ask \
  --title "Q13：示例问题" \
  --question "这里是问题正文" \
  --require-web-search
```

Ask many questions from JSONL or JSON:

```bash
python3 scripts/adapters/chatgpt_workflow.py batch-ask \
  --tasks-file /path/to/tasks.jsonl \
  --require-web-search \
  --delay 60
```

`batch-ask` defaults to a 60 second delay between questions. Increase
`--delay` when ChatGPT shows rate limits or temporary access restrictions.
Stop real sending immediately if the page reports restricted access; continue
only after the account/browser session is healthy again.
When `--require-web-search` is set, the workflow aborts before sending if the
visible ChatGPT composer controls do not confirm that Web Search is enabled.

Preview matching existing conversations:

```bash
python3 scripts/adapters/chatgpt_workflow.py list --limit 20
```

Export latest matching existing conversations:

```bash
python3 scripts/adapters/chatgpt_workflow.py export --limit 20
```

Export the exact conversations that were just submitted:

```bash
python3 scripts/adapters/chatgpt_workflow.py export \
  --conversations-file assets/chatgpt/runs/yyyyMMdd-HHmmss/submissions.json \
  --output-dir assets/chatgpt/exports/qx/yyyyMMdd-HHmmss
```

Use `--conversations-file` when the sidebar contains unrelated chats, titles
have changed, or the task requires one submitted question to produce exactly
one Markdown file. The file must be a JSON array whose records include `title`
and `url`; the `submissions.json` written by `ask` / `batch-ask` already has
that shape.

Tracked long run:

```bash
python3 scripts/actionbook_run.py run \
  --id chatgpt-qx-export \
  --cwd "$PWD" \
  -- \
  python3 scripts/adapters/chatgpt_workflow.py export --limit 20
```

Use the same wrapper for `batch-ask` because it sends multiple real prompts:

```bash
python3 scripts/actionbook_run.py run \
  --id chatgpt-batch-ask \
  --cwd "$PWD" \
  -- \
  python3 scripts/adapters/chatgpt_workflow.py batch-ask \
    --tasks-file /path/to/tasks.jsonl \
    --delay 60
```

## Task Files

JSONL:

```json
{"title":"Q13：示例问题","question":"这里是问题正文"}
{"title":"Q14：另一个问题","question":"另一个问题正文","output_name":"Q14-custom-name"}
```

JSON array:

```json
[
  {"title": "Q13：示例问题", "question": "这里是问题正文"},
  {"title": "Q14：另一个问题", "question": "另一个问题正文"}
]
```

`title` and `question` are required. `output_name` is optional and is ignored
by `ask` and `batch-ask`; those commands are submit-only and do not write
Markdown files.

## Output

Default ask / batch-ask output:

```text
assets/chatgpt/runs/yyyyMMdd-HHmmss/
  submissions.json
  failures.json
```

`ask` and `batch-ask` do not wait for complete answers and do not write
Markdown files. Use `export` later to copy finished answers from existing
conversations.

`submissions.json` lifecycle:

- Created by `ask` and `batch-ask` in the run output directory. The default is
  `assets/chatgpt/runs/yyyyMMdd-HHmmss/`; `--output-dir` overrides it.
- Written with `failures.json` whenever a submit run exits. `batch-ask` also
  rewrites both files after each task, so an interrupted run still has the last
  completed submission records.
- Each submitted record includes `index`, `title`, `question`, `url`, `status`,
  `mode`, `submitted_at`, and `attempts`. Treat the `url` as the durable handle
  for the ChatGPT conversation.
- Used later by `export --conversations-file <run-dir>/submissions.json` when
  the export must match the conversations created by that run instead of
  whatever the ChatGPT sidebar currently shows.
- Keep the run directory until export succeeds and the exported Markdown files,
  export `summary.json`, and export `failures.json` have been reviewed. Do not
  auto-delete it; it is audit/retry evidence and may contain the original
  questions. Archive by moving or copying the whole run directory with the final
  deliverable. Delete only when the user explicitly asks or local retention
  policy requires it.

Default export output:

```text
assets/chatgpt/exports/qx/yyyyMMdd-HHmmss/
  001-<title>.md
  002-<title>.md
  summary.json
  failures.json
```

Each Markdown file includes simple frontmatter with the conversation title,
source URL, timestamps, extraction method, and task metadata when available.
`summary.json` records `method`, `used_system_clipboard`, and
`used_dom_fallback` per conversation. Treat `failures.json` as the source of
truth for conversations that were skipped or could not be exported.

## Login And Risk Control

If ChatGPT shows login, CAPTCHA, MFA, Cloudflare, or unusual activity checks,
stop automation and complete the challenge in the same Chrome window. Then run
the command again with the same `--session`.

If ChatGPT shows request-frequency or restricted-access warnings, stop real
question sending. Do not use rapid retries. Resume with a larger `--delay`
after the restriction clears.

## DOM Notes

ChatGPT changes DOM labels and test ids frequently. The workflow deliberately
uses multiple selectors:

- Sidebar conversation links: anchors whose `href` contains `/c/`.
- Default title match: `^Q\d+[：:]`.
- New chat controls: visible `新聊天` / `New chat` controls.
- Composer controls: `data-testid="composer-plus-btn"` is used only to open the
  tool menu and choose `网页搜索`; it must not select upload-file items. The
  question is sent through the composer and the visible send button.
- Mode controls: the deprecated answer-capture helper can still look for `智能`
  and `Pro 扩展`. `ask` and `batch-ask` are submit-only; they enable Web Search,
  log the verified visible search control text, and make a best-effort Pro
  extension selection before sending, but they do not select `智能`.
  If Pro extension cannot be selected, the run continues and records
  `extension: not-selected` in `submissions.json`.
- Assistant messages: submission-start detection uses
  `data-message-author-role="assistant"`; broader article/markdown fallbacks are
  limited to the deprecated answer-capture helper.
- Copy response controls: `data-testid="copy-turn-action-button"` or
  `aria-label` containing `复制回复`, `Copy response`, or `Copy reply`.

Do not match generic `复制` / `Copy` for final answer extraction because code
blocks and citations expose their own copy buttons.
