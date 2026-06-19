# ChatGPT Workflow

This reference covers `chatgpt_workflow.py`, a Chrome extension-mode workflow
for asking ChatGPT questions through the web UI and exporting ChatGPT
conversation replies to local Markdown.

## Goal

The workflow can:

1. Open `https://chatgpt.com/` with the user's Chrome login state.
2. Create one new chat or many new chats from local tasks.
3. Enable web search, intelligent mode, and Pro extension through the ChatGPT
   UI.
4. Send the question and wait for the assistant answer to finish.
5. Reopen or locate existing conversations from the sidebar.
6. Scroll to the conversation bottom.
7. Click ChatGPT's own `复制回复` / `Copy response` button.
8. Save the copied Markdown to local `.md` files.

Final answer extraction does not use DOM text fallback. The workflow writes a
sentinel to the macOS system clipboard, clicks ChatGPT's `复制回复` / `Copy
response` button, then requires the clipboard to change before writing
Markdown.

## Commands

Ask one question and export the latest assistant answer:

```bash
python3 scripts/chatgpt_workflow.py ask \
  --title "Q13：示例问题" \
  --question "这里是问题正文"
```

Ask many questions from JSONL or JSON:

```bash
python3 scripts/chatgpt_workflow.py batch-ask \
  --tasks-file /path/to/tasks.jsonl \
  --delay 60
```

`batch-ask` defaults to a 60 second delay between questions. Increase
`--delay` when ChatGPT shows rate limits or temporary access restrictions.
Stop real sending immediately if the page reports restricted access; continue
only after the account/browser session is healthy again.

Preview matching existing conversations:

```bash
python3 scripts/chatgpt_workflow.py list --limit 20
```

Export latest matching existing conversations:

```bash
python3 scripts/chatgpt_workflow.py export --limit 20
```

Tracked long run:

```bash
python3 scripts/actionbook_run.py run \
  --id chatgpt-qx-export \
  --cwd "$PWD" \
  -- \
  python3 scripts/chatgpt_workflow.py export --limit 20
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

`title` and `question` are required. `output_name` is optional and changes only
the Markdown filename.

## Output

Default ask output:

```text
assets/chatgpt/runs/yyyyMMdd-HHmmss/
  001-<title>.md
  summary.json
  failures.json
```

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
- Mode controls: visible menu/button items for `智能` and `Pro 扩展`. Current
  ChatGPT UI may not expose a separate `智能` menu item after web search is
  enabled; in that case the workflow records `mode_fallback: true` and
  continues after verifying search mode is active.
- Assistant messages: `data-message-author-role="assistant"` first, then
  broader article/markdown fallbacks for state detection only.
- Copy response controls: `data-testid="copy-turn-action-button"` or
  `aria-label` containing `复制回复`, `Copy response`, or `Copy reply`.

Do not match generic `复制` / `Copy` for final answer extraction because code
blocks and citations expose their own copy buttons.
