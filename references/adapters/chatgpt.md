# ChatGPT Workflow

This reference covers `chatgpt_workflow.py`, a Chrome extension-mode workflow
for asking ChatGPT questions through the web UI and exporting ChatGPT
conversation replies to local Markdown.

Common entry rules live in `../../SKILL.md`; adapter runtime boundaries live in
`../adapter-operation-boundaries.md`.

## Goal

The workflow can:

1. Open `https://chatgpt.com/` with the user's Chrome login state.
2. Create one new chat or many new chats from local JSON / JSONL tasks.
3. Apply the default submit route, then send each question.
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
  --question "这里是问题正文"
```

Ask many questions from JSONL or JSON:

```bash
python3 scripts/adapters/chatgpt_workflow.py batch-ask \
  --tasks-file /path/to/tasks.jsonl \
  --delay 60
```

`batch-ask` defaults to a 60 second delay between questions. Increase
`--delay` when ChatGPT shows rate limits or temporary access restrictions.
Stop real sending immediately if the page reports restricted access; continue
only after the account/browser session is healthy again.

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

## Default Submit Route

Observed on the zh-CN ChatGPT web UI on 2026-07-02. Treat labels as routing
hints, not stable API names; always take a fresh snapshot after opening a menu.

`ask` and `batch-ask` default to:

1. Select `网页搜索`.
2. Select `超高`.
3. Best-effort select the newest visible `GPT-*` concrete model, such as
   `GPT-5.5` over `GPT-5.4` / `GPT-5.3`.
4. If no concrete `GPT-*` option is visible, keep `超高` and continue.

Default route failures:

- Missing `网页搜索`, the model picker, or `超高` is a nonfatal submit failure for
  that item.
- Missing newest `GPT-*` is not a failure; `超高` is the fallback.

## Composer Controls

| Control | Observed label / role | Route use | Notes |
| --- | --- | --- | --- |
| Add menu | `添加文件等`, `data-testid="composer-plus-btn"` | Opens the tool and connector menu. | Use this for Web Search, Deep Research, image creation, uploads, and connectors. |
| Composer | `与 ChatGPT 聊天`, role `textbox` | Main prompt input. | Use `actionbook browser type`, not DOM `innerText`, so ChatGPT receives input events. |
| Model picker | Current label such as `高级` | Opens model menu. | The button text changes to the selected mode/model. |
| Dictation | `开始听写` | Voice input. | Do not use in automation. |
| Voice | `启动语音功能` | Voice conversation. | Do not use in automation. |

Shortcut chips below the composer are intent helpers, not separate models:
`生成图片`, `撰写或编辑`, and `查找资料`. Prefer explicit menu routes when the
task needs deterministic behavior.

`+` menu entries:

| Entry | Visible subtitle / evidence | Route use | Automation boundary |
| --- | --- | --- | --- |
| `添加照片和文件` | upload input `data-testid="upload-photos-input"` | Attach local images/files. | Do not click unless a file path is explicitly provided; it can open a file chooser. |
| `创建图片` | `可视化呈现任何内容` | Image generation mode. | Select only when the user asks to generate or edit images through ChatGPT. |
| `网页搜索` | `查找实时新闻和信息` | Default Web Search mode. | Select before sending by default. Verify a `网页搜索` chip/control is visible in the composer. |
| `深度研究` | `获取详细报告` | Deep Research mode. | Select only for user-approved long research tasks; expect slower completion. |
| `OpenAI Platform` | `Create an OpenAI API key after connecting Platform.` | Connector route for OpenAI Platform account data. | Requires connector authorization; stop if a connect/login flow appears. |
| `GitHub` | `访问代码仓库、问题和拉取请求。这是 Codex 等功能的必备要素` | Connector route for GitHub repositories/issues/PRs. | Requires connected GitHub state; do not authorize silently. |
| `Gmail` | `查找并引用你收件箱中的电子邮件` | Connector route for mailbox-backed answers. | Requires connected Gmail state; do not authorize silently. |

## Model Routing

| Entry | Observed role | Route use |
| --- | --- | --- |
| `极速` | `menuitemradio` | Fastest response mode. Use for low-stakes short answers. |
| `均衡` | `menuitemradio` | Balanced default. Use when no special latency/depth requirement exists. |
| `高级` | `menuitemradio` | Higher quality general mode. Current default in this profile. |
| `超高` | `menuitemradio` | Default highest general quality mode. |
| `Pro 扩展` | `menuitemradio` | Extended Pro mode. Use only when explicitly needed or requested. |
| `GPT-5.5` | `menuitem`; expands submenu | Opens a concrete model submenu. Default route selects the newest visible `GPT-*` option. |

Concrete model submenu entries observed after opening `GPT-5.5`: `GPT-5.5`,
`GPT-5.4`, `GPT-5.3`, and `o3`.

Model switching procedure:

1. Open a fresh snapshot and identify the current model button by labels such
   as `极速`, `均衡`, `高级`, `超高`, `Pro 扩展`, or `GPT-5.5`.
2. Click that button and take another snapshot.
3. For top-level modes, click the matching `menuitemradio`.
4. For concrete models under `GPT-5.5`, first click `GPT-5.5`, then click the
   submenu `menuitemradio`.
5. Take a final snapshot and verify the composer model button text changed to
   the requested route before filling or sending the prompt.

Routing cautions:

- Do not infer active mode from stale snapshots. ChatGPT can leave old chips or
  draft text in idle tabs.
- Do not use direct DOM assignment for prompts. In testing, `innerText` changed
  the visible composer but did not reliably enable sending; `browser type`
  fired the required input events.
- If selecting a mode creates a chip such as `网页搜索`, verify it is visible
  before sending. Duplicate chips indicate a reused dirty tab; switch to a clean
  tab or clear the composer before continuing.
- Connector entries may open authorization flows. Stop and ask the user when
  login, connection, permission, CAPTCHA, or risk-control appears.

## Selector Notes

- Sidebar conversation links: anchors whose `href` contains `/c/`.
- Default title match: `^Q\d+[：:]`.
- New chat controls: visible `新聊天` / `New chat` controls.
- Assistant messages: `data-message-author-role="assistant"`.
- Copy response controls: `data-testid="copy-turn-action-button"` or
  `aria-label` containing `复制回复`, `Copy response`, or `Copy reply`.
- Do not match generic `复制` / `Copy` for final answer extraction because code
  blocks and citations expose their own copy buttons.
