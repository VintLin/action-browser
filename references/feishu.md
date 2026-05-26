# Feishu Drive And Docs Workflow

This reference is for Feishu/Lark Drive and Feishu Docs tasks that need the user's existing Chrome login state. Prefer ActionBook extension mode and keep all browser/API calls in the same logged-in session.

## Initialization

Use the generic session bootstrap first:

```bash
python3 /Users/Vint/.codex/skills/action-browser/scripts/actionbook_session.py \
  --session feishu-drive \
  --url "https://<tenant>.feishu.cn/drive/" \
  --json
```

Then confirm cookies are readable from the same session:

```bash
actionbook browser cookies list --session feishu-drive --json
```

Stop and ask the user to log in in the same Chrome window if the page shows login, permission approval, CAPTCHA, MFA, or organization risk-control prompts. Do not switch away from extension mode for login-dependent Feishu work.

## Folder Inventory

Use the unified workflow script:

```bash
python3 /Users/Vint/.codex/skills/action-browser/scripts/feishu_workflow.py \
  --session feishu-drive \
  inventory \
  --root "资料=https://<tenant>.feishu.cn/drive/folder/<folder_token>" \
  --output-dir records
```

For Drive folder URLs, prefer the Feishu folder children API over DOM scrolling:

```text
GET /space/api/explorer/v3/children/list/?token=<folder_token>&asc=0&rank=3&length=200
```

Use `last_label` from the previous response as the next page's `last_label`. Continue until `has_more=false`.

Expected response shape:

- `data.total`: total count reported by Feishu.
- `data.has_more`: whether another page exists.
- `data.last_label`: pagination cursor for the next request.
- `data.node_list`: ordered node ids.
- `data.entities.nodes`: node metadata keyed by node id.

For each node, preserve at least:

- name
- URL
- cloud path
- object type or document kind
- object token
- node token
- source, for example `api-v3-children-list`

Folder list pages are virtualized. If the API fails and UI fallback is necessary, scroll with medium steps, merge both visible rows and any available in-page store/state after every step, and deduplicate by URL or token. Do not assume the first visible DOM batch or the first store batch is complete.

## File Opening From Folder UI

In a folder file list, a single click often only selects the row. Double-click the file name or row to open the file. Feishu usually opens files in a new browser tab.

After opening a file, run `list-tabs` and choose the newly opened tab whose title or URL matches the target file:

```bash
actionbook browser list-tabs --session feishu-drive --json
```

Common content URL prefixes include:

- `/file/`
- `/sheets/`
- `/docx/`
- `/mindnotes/`
- `/base/`
- `/slides/`

Deduplicate tabs when repeated double-clicks open the same document more than once.

## Direct Attachment Download

Use the same script for direct downloads and supported cloud exports:

```bash
python3 /Users/Vint/.codex/skills/action-browser/scripts/feishu_workflow.py \
  --session feishu-drive \
  download \
  --manifest records/feishu_manifest.json \
  --output-dir downloads \
  --status-dir records
```

For ordinary `/file/<token>` attachments, download through the stream endpoint with cookies copied from the ActionBook Chrome session:

```text
GET https://<tenant>.feishu.cn/space/api/box/stream/download/all/<token>
```

Headers should include:

- `Cookie`: Feishu cookies from `actionbook browser cookies list`.
- `Referer`: the Feishu Drive or file URL.
- `User-Agent`: a normal browser user agent.

Stream to a temporary file such as `<target>.part`, then atomically rename after the response completes. Treat JSON responses, non-200 status codes, zero-byte output, and lingering temporary files as failures.

## Cloud Document Export API

For Feishu cloud documents, prefer the export API before page-menu automation.

Create an export job:

```text
POST https://<tenant>.feishu.cn/space/api/export/create/
```

Required request details:

- Include `X-CSRFToken`, using the `_csrf_token` cookie value.
- Include the Feishu cookies from the ActionBook Chrome session.
- Set `Origin` to the tenant origin.
- Set `Referer` to the source document URL.

Known request bodies:

```json
{"token":"<token>","type":"sheet","file_extension":"xlsx","event_source":"1"}
```

```json
{"token":"<token>","type":"docx","file_extension":"docx","event_source":"1"}
```

Poll the result endpoint:

```text
GET https://<tenant>.feishu.cn/space/api/export/result/<ticket>?token=<token>&type=<type>
```

The successful result may be under `data.result` or directly under `data`. Read `file_token` from either shape, then download it with:

```text
GET https://<tenant>.feishu.cn/space/api/box/stream/download/all/<file_token>
```

Known stable export choices:

- `/sheets/`: export type `sheet`, extension `xlsx`.
- `/docx/`: export type `docx`, extension `docx`.
- `/docs/`: export type `doc`, extension `docx`.
- `/base/` and `/bitable/`: export type `bitable`, extension `xlsx`.
- `/slides/`: try export type `slides`, extension `pptx`, then `pdf`.

Do not assume all Feishu cloud document kinds accept the same export API body. The unified script records export failures per file instead of silently switching to UI automation.

## Page Menu Export Fallback

Use the content-page UI when the export API does not support a document kind or when the menu exposes a format unavailable through the API.

On Feishu content pages, the common path is:

1. Open the content page.
2. Locate the top-right `分享` button.
3. Click the second icon button to the right of `分享`; this is usually the top-right three-dot more menu.
4. Prefer `下载为`. If missing, look for direct `下载`.
5. Read the submenu items and choose the type-specific export format.
6. After clicking the final export format, inspect ActionBook network requests first. Prefer a captured `/space/api/box/stream/download/all/<file_token>` URL or a `file_token` returned by an export/result response, then download that URL directly into the target path with the Feishu cookies.
7. Only if no usable network URL or token is captured, wait for Chrome to finish the download, then move the downloaded file from the Chrome download directory into the target path.

ActionBook may not assign stable text to the top-right icon buttons. The position relative to `分享` is often more reliable than button text. Avoid using a similarly named menu from inside an editor canvas unless the top-right menu is unavailable.

Known fallback:

- `/mindnotes/`: `下载为` may expose only `FreeMind`; selecting it downloads a `.mm` file.

The unified script supports `mindnotes` page-menu export behind `download --ui-fallback`. It clears the tab network buffer before the final menu click, then polls captured requests for a final download URL or `file_token`. If the browser starts a Chrome-managed download without exposing a usable URL in ActionBook network records, it falls back to the Chrome download directory and records `network_capture: no_download_url_or_file_token`. API export candidates for mindnotes were tested and returned extension mismatch errors, so do not mark mindnotes as API-supported.

Known menu choices to prefer when visible:

- spreadsheet: `本地 Excel 表格(.xlsx)`
- document: Word or PDF, based on actual menu text and user requirement
- slides: PPTX or PDF, based on actual menu text and user requirement
- attachments/images: direct `下载` if present

## Batch Output And Recovery

For batch Feishu download tasks, keep durable progress files:

- `feishu_manifest.json`: full folder/file inventory.
- `feishu_manifest.md`: human-readable inventory summary.
- `download_status.jsonl`: one direct attachment record per line.
- `cloud_export_status.jsonl`: one cloud export record per line.
- `download_summary.json` and `cloud_export_summary.json`: counts and elapsed time.
- `failures.json` or failure rows in the JSONL files.

Make downloads resumable:

- Skip existing non-empty files unless the user passes an explicit force option.
- Keep `.part` files only while a request is active.
- Sanitize local path components for filesystem-invalid characters.
- Preserve the cloud folder structure under the output root.
- Record source URL, source path, local path, size, status, error, and timestamp where practical.

For long-running runs, wrap the script with `scripts/actionbook_run.py` so the task can be stopped later:

```bash
python3 /Users/Vint/.codex/skills/action-browser/scripts/actionbook_run.py run \
  --id feishu-drive-download \
  --cwd "$PWD" \
  -- \
  python3 your_feishu_download_script.py --session feishu-drive
```

## Verification

Verify local output with:

```bash
python3 /Users/Vint/.codex/skills/action-browser/scripts/feishu_workflow.py \
  verify \
  --manifest records/feishu_manifest.json \
  --output-dir downloads \
  --output records/download_verification.json
```

A Feishu batch download is not complete until inventory and local files reconcile.

Verify:

- manifest file count
- local non-empty file count
- local missing file count
- zero-byte file count
- output directory total size
- path collisions after filename sanitization
- counts by root folder and document kind

For high-value downloads, re-run folder inventory into a separate recheck directory and compare:

- added files
- removed files
- added folders
- removed folders
- folders with incomplete pagination
- folders where `has_more` remains true

Report concrete counts and paths in the final handoff.
