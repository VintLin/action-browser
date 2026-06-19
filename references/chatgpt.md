# ChatGPT Workflow

This reference covers `chatgpt_workflow.py`, a Chrome extension-mode workflow
for exporting recent ChatGPT conversations whose sidebar title matches
`Q<number>:` or `Q<number>：`, such as `Q7：Codex approval request设计`.

## Goal

The workflow:

1. Opens `https://chatgpt.com/` with the user's Chrome login state.
2. Finds recent sidebar conversations whose visible title matches the
   configured regex or prefix.
3. Opens each conversation one by one.
4. Scrolls to the bottom.
5. Clicks the latest assistant message's Copy button when available.
6. Saves the copied Markdown to local `.md` files.

If browser clipboard read is blocked, the script falls back to extracting the
latest assistant response text from the DOM and records a warning in
`summary.json`.

## Commands

Preview matching conversations:

```bash
python3 scripts/chatgpt_workflow.py list --limit 20
```

Export latest matching conversations:

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

## Output

Default output:

```text
assets/chatgpt/exports/qx/yyyyMMdd-HHmmss/
  001-<title>.md
  002-<title>.md
  summary.json
  failures.json
```

Each Markdown file includes simple frontmatter with the conversation title,
source URL, export timestamp, extraction method, and warnings.

## Login And Risk Control

If ChatGPT shows login, CAPTCHA, MFA, Cloudflare, or unusual activity checks,
stop automation and complete the challenge in the same Chrome window. Then run
the command again with the same `--session`.

## DOM Notes

ChatGPT changes DOM labels and test ids frequently. The workflow deliberately
uses multiple selectors:

- Sidebar conversation links: anchors whose `href` contains `/c/`.
- Default title match: `^Q\d+[：:]`.
- Assistant messages: `data-message-author-role="assistant"` first, then
  broader article/markdown fallbacks.
- Copy controls: `data-testid*="copy"`, `aria-label` containing `copy` or
  `复制`, and buttons near the latest assistant message.

When the visible Copy button cannot be found, the DOM extraction fallback is
expected and should not be treated as data loss if the Markdown content is
present.
