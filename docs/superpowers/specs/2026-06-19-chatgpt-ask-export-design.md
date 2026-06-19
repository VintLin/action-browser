# ChatGPT Ask and Export Workflow Design

Date: 2026-06-19

## Goal

Extend the existing ChatGPT ActionBook workflow so it can run one or many
question-answer tasks through the ChatGPT web UI, then save the latest assistant
reply as Markdown.

The workflow must support:

- Single task execution from CLI arguments.
- Batch execution from a JSON or JSONL task file.
- Creating a new ChatGPT conversation.
- Enabling web search.
- Selecting the intelligent mode.
- Selecting Pro extension.
- Sending the question.
- Waiting for the answer to finish.
- Reopening or locating the resulting conversation.
- Moving to the conversation bottom.
- Clicking ChatGPT's own `Copy response` / `复制回复` control.
- Reading the system clipboard and writing a Markdown file locally.

The implementation must use ActionBook extension mode so it can reuse the
user's logged-in Chrome session. It must not call OpenAI APIs or read browser
cookies, local storage, session storage, tokens, or passwords.

## Scope

In scope:

- `ask`: submit one prompt and export its answer.
- `batch-ask`: submit multiple prompts from a local file and export each answer.
- Existing `list` and `export` commands continue to work.
- Reuse the current ChatGPT conversation listing and response export behavior.
- Store per-task Markdown files plus `summary.json` and `failures.json`.
- Treat login, CAPTCHA, MFA, Cloudflare, unusual activity, missing UI controls,
  and answer timeout as explicit failures.

Out of scope:

- Direct OpenAI API use.
- Model selection beyond the requested intelligent mode and Pro extension UI.
- Scheduling recurring runs.
- Retrying failed tasks in a separate future session.
- Editing or deleting ChatGPT conversations.
- Exporting entire conversation history; only the latest assistant reply is
  saved.
- Silent DOM-text fallback for final answer content.

## Chosen Approach

Use the existing `scripts/chatgpt_workflow.py` as the single CLI entry point and
add new commands to it.

Reason:

- The existing script already owns ChatGPT login checks, sidebar conversation
  discovery, bottom navigation, response copy, clipboard validation, and
  Markdown writing.
- A second script would duplicate those behaviors and risk selector drift.
- A shared-module split is cleaner long-term but wider than this change needs.

Design constraint:

- The file is already near the preferred size limit. The implementation should
  keep each new UI action as a small named function so a later split into
  `chatgpt_actions.py` is straightforward if more ChatGPT workflows are added.

## Data Model

Introduce one explicit task shape:

```json
{
  "title": "Q13：示例问题",
  "question": "这里是问题正文",
  "output_name": "optional-file-name"
}
```

Fields:

- `title`: required. Used for summary records, Markdown metadata, and default
  filename. It does not need to become the ChatGPT conversation title because
  ChatGPT derives sidebar titles from the prompt.
- `question`: required. Sent to ChatGPT exactly as provided.
- `output_name`: optional. Overrides the Markdown filename only. It is not sent
  to ChatGPT and does not change the conversation title.

The implementation should represent this as a typed Python data structure such
as `ChatGptTask`, not as untyped dictionaries passed through the workflow.

## Command Interface

Single task:

```bash
python3 scripts/chatgpt_workflow.py ask \
  --title "Q13：示例问题" \
  --question "这里是问题正文" \
  --output-dir /path/to/output
```

Batch task:

```bash
python3 scripts/chatgpt_workflow.py batch-ask \
  --tasks-file /path/to/tasks.jsonl \
  --output-dir /path/to/output
```

Common optional arguments:

- `--session`: ActionBook session id. Default remains `chatgpt-qx`.
- `--tab`: optional known-good tab id.
- `--output-dir`: output directory. Defaults to
  `assets/chatgpt/runs/<timestamp>/`.
- `--delay`: delay between batch tasks.
- `--answer-timeout`: maximum seconds to wait for an assistant response to
  finish.

Existing commands remain:

```bash
python3 scripts/chatgpt_workflow.py list --limit 20
python3 scripts/chatgpt_workflow.py export --limit 20
```

## Batch Input Format

Support JSONL:

```json
{"title":"Q13：示例问题","question":"这里是问题正文"}
{"title":"Q14：另一个问题","question":"另一个问题正文","output_name":"Q14-custom-name"}
```

Support JSON array:

```json
[
  {"title": "Q13：示例问题", "question": "这里是问题正文"},
  {"title": "Q14：另一个问题", "question": "另一个问题正文"}
]
```

Validation rules:

- Reject empty files.
- Reject malformed JSON.
- Reject records without non-empty `title` and `question`.
- Reject non-object records.
- Keep `output_name` optional and validate it only as a string when present.

## Output

Default output:

```text
assets/chatgpt/runs/yyyyMMdd-HHmmss/
  001-Q13-示例问题.md
  002-Q14-另一个问题.md
  summary.json
  failures.json
```

Markdown frontmatter:

- `title`
- `question`
- `source_url`
- `created_at`
- `copied_at`
- `method: system-clipboard`
- `web_search: true`
- `mode: intelligent`
- `extension: pro`

`summary.json` records one object per successful task:

- `index`
- `title`
- `question`
- `url`
- `file`
- `clicked_copy`
- `used_system_clipboard`
- `text_length`
- `started_at`
- `completed_at`

`failures.json` records one object per failed task:

- `index`
- `title`
- `question`
- `url` when known
- `error`
- `failed_at`

Batch execution continues after a failed task. The command exits non-zero if
any failures occurred.

## Browser Flow: Ask

Each task follows this browser flow:

1. Start or recover an ActionBook extension session at `https://chatgpt.com/`.
2. Confirm ChatGPT is ready and not on login, CAPTCHA, MFA, Cloudflare, or
   unusual activity pages.
3. Open a new chat by clicking the visible `新聊天` / `New chat` control.
4. Click the composer `+` button.
5. Click `网页搜索` / web search.
6. Select `智能` mode.
7. Select `Pro 扩展`.
8. Fill the composer with `question`.
9. Send the prompt using the send button or `Enter`, whichever is verified to
   work in the page state.
10. Wait until an assistant answer starts.
11. Wait until generation finishes. A finished answer is defined by all of:
    - no visible stop-generating button,
    - composer is usable again,
    - a latest assistant message exists,
    - assistant message text is stable for repeated checks.
12. Move to the conversation bottom.
13. Click ChatGPT's `复制回复` / `Copy response` control for the latest assistant
    message.
14. Read macOS system clipboard with a sentinel check.
15. Write the Markdown file and update summary/failure records.

The workflow should prefer ActionBook real clicks for user-visible controls.
DOM evaluation may locate candidates, inspect state, and compute coordinates,
but final actions that affect clipboard or ChatGPT UI state should use
ActionBook interaction commands.

## Browser Flow: Export Existing Conversations

Existing export remains a separate command:

1. Find sidebar conversations by regex or prefix.
2. Open each matching conversation.
3. Move to the bottom.
4. Click the latest assistant message's `复制回复` / `Copy response` button.
5. Read system clipboard with a sentinel check.
6. Write Markdown and summary files.

This flow should share the same copy and Markdown writing helpers used by
`ask` and `batch-ask`.

## UI Selector Strategy

ChatGPT labels and DOM structure change often, so selectors must be layered and
verified.

Preferred controls:

- New chat: visible link/button with `新聊天`, `New chat`, or route/state change
  to a blank conversation.
- Composer plus: `data-testid="composer-plus-btn"` or `aria-label` containing
  add/attach text.
- Web search: visible composer menu item containing `网页搜索`, `Web search`, or
  `Search`; do not match the sidebar chat search control.
- Intelligent mode: visible menu item containing `智能` or `Intelligent`.
- Pro extension: visible composer pill or menu item containing `Pro 扩展`; only
  use bare `Pro` when the candidate is inside the composer tool/mode controls.
- Send: visible enabled send button, or `Enter` when the composer is focused.
- Copy response: `data-testid="copy-turn-action-button"`, or `aria-label`
  containing `复制回复`, `Copy response`, or `Copy reply`.

The workflow must not use generic `复制` / `Copy` as the final answer selector
because code blocks and citations expose their own copy buttons.

## Error Handling

Known failure cases:

- ChatGPT requires login, CAPTCHA, MFA, Cloudflare, or unusual activity
  verification.
- New chat control not found.
- Composer plus button not found.
- Web search option not found.
- Intelligent mode option not found.
- Pro extension option not found.
- Composer cannot be filled.
- Send button cannot be activated.
- Answer does not start before timeout.
- Answer does not finish before timeout.
- Copy response button not found.
- System clipboard does not change from the sentinel after clicking copy.

Rules:

- Keep the same Chrome window for login or verification and tell the user to
  complete it there.
- Do not silently save DOM text as the final answer.
- For `ask`, a failure exits non-zero and writes `failures.json` when an output
  directory is available.
- For `batch-ask`, record the failed task and continue to the next task.
- Include current URL, task title, and error message in failure records when
  available.

## Testing

Unit tests should cover pure logic:

- JSONL parsing.
- JSON array parsing.
- Rejection of malformed task files.
- Sanitized filename generation with `output_name`.
- CLI help exposes `ask` and `batch-ask`.
- Existing `list` and `export` help still works.
- Script source does not read sensitive browser storage terms:
  `document.cookie`, `localStorage`, `sessionStorage`, `token`, `password`.

Manual verification should cover real ChatGPT UI behavior:

1. Run one `ask` task with a short question.
2. Confirm ChatGPT creates a new conversation and sends the prompt.
3. Confirm web search, intelligent mode, and Pro extension are selected when
   visible in the UI.
4. Confirm answer completion waits until generation finishes.
5. Confirm `summary.json` has one success.
6. Confirm `failures.json` is empty.
7. Confirm Markdown content came from system clipboard and begins with the
   assistant answer, not the prompt.
8. Run `batch-ask` with two tasks and confirm two Markdown files are created.

## Documentation Updates

Update `references/chatgpt.md` to describe:

- `ask`
- `batch-ask`
- task file formats
- output structure
- selector caveats
- no DOM fallback for final answer content

`SKILL.md` already links ChatGPT to the reference and script, so no site index
change is expected unless command descriptions are expanded elsewhere.

## Completion Criteria

The implementation is complete when:

- `python3 scripts/chatgpt_workflow.py --help` lists `ask`, `batch-ask`, `list`,
  and `export`.
- Unit tests for task parsing and CLI exposure pass.
- A real single `ask` run creates one Markdown file and summary entry.
- A real `batch-ask` run creates one Markdown file per valid task and records
  failures without stopping the whole batch.
- Export of existing conversations still works through `复制回复` and system
  clipboard validation.
- `references/chatgpt.md` reflects the new commands and no longer says DOM
  fallback is acceptable for final answer extraction.
