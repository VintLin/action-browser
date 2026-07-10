# JD and Taobao ActionBook Support Design

Date: 2026-06-10

## Goal

Add first-version JD.com and Taobao support to the action-browser skill as read-only ActionBook workflows.

The implementation must use ActionBook extension mode through the existing skill helpers. It must not call OpenCLI as the runtime backend and must not use direct Python-side cookie handling. OpenCLI is only a reference for command coverage and extraction behavior.

## Scope

First-version support is read-only.

JD support:

- `search view`: search products by keyword.
- `item view`: read enhanced product detail, including price, shop, specs, main images, and detail images.
- `detail view`: read compact product detail fields.
- `reviews view`: read product reviews.
- `cart view`: read current logged-in account cart items.
- `whoami view`: identify whether the current JD session is logged in and read visible account identity when available.

Taobao support:

- `search view`: search products by keyword.
- `detail view`: read product detail fields.
- `reviews view`: read product reviews.
- `cart view`: read current logged-in account cart items.
- `whoami view`: identify whether the current Taobao session is logged in and read visible account identity when available.

Out of scope:

- JD `add-cart`.
- Taobao `add-cart`.
- Purchasing, checkout, order submission, cart mutation, cart deletion, or quantity changes.
- Exporting cookies, saving login state, reading passwords, or handling credentials.
- Long-running price monitors or scheduled recurring crawls.

## File Boundaries

Add two independent site modules:

- `references/jd.md`
- `references/taobao.md`
- `scripts/jd_workflow.py`
- `scripts/taobao_workflow.py`

Update only the site indexes:

- `SKILL.md`: add JD and Taobao to the References table.
- `README.md`: add JD and Taobao to Included Workflows.

`SKILL.md` stays site-neutral. Site command catalogs, payload schemas, DOM details, output trees, login notes, and risk-control quirks belong in the matching reference file.

## Tooling

All browser interaction must go through ActionBook.

Required helpers:

- `scripts/actionbook_session.py`
  - Use `ActionBookSession`.
  - Reuse a healthy extension session when possible.
  - Open a fresh tab when needed.
  - Rebuild only as a fallback.
- `scripts/actionbook_run.py`
  - Use only if a future workflow becomes long-running.
  - First-version JD and Taobao commands are expected to be short `view` commands.

Runtime mode:

- Chrome extension mode is required so workflows can use the user's existing Chrome login state.
- Page reads may use ActionBook `eval` to run DOM extraction or same-origin browser-side `fetch(..., credentials: 'include')`.
- Python must not carry cookies or tokens.

## Command Interface

Both scripts use the existing `area mode` style and expose only `view` modes.

JD:

```bash
python3 scripts/jd_workflow.py search view --query "机械键盘" --count 10
python3 scripts/jd_workflow.py item view --sku 100291143898 --images 50
python3 scripts/jd_workflow.py detail view --sku 100291143898
python3 scripts/jd_workflow.py reviews view --sku 100291143898 --count 10
python3 scripts/jd_workflow.py cart view --count 20
python3 scripts/jd_workflow.py whoami view
```

Taobao:

```bash
python3 scripts/taobao_workflow.py search view --query "机械键盘" --sort default --count 10
python3 scripts/taobao_workflow.py detail view --id 827563850178
python3 scripts/taobao_workflow.py reviews view --id 827563850178 --count 10
python3 scripts/taobao_workflow.py cart view --count 20
python3 scripts/taobao_workflow.py whoami view
```

Common arguments:

- `--session`: ActionBook session id. Defaults: `jd-task` and `taobao-task`.
- `--tab`: optional known-good ActionBook tab id.
- `--output`: optional output directory.
- `--count`: list count limit, capped per command.

Command-specific arguments:

- JD `item view`: `--images`, capped to a practical limit.
- Taobao `search view`: `--sort default|sale|price`.

## Output

Default output directories:

```text
assets/jd/views/<area>/<timestamp>/
  summary.json
  summary.md
  failures.json

assets/taobao/views/<area>/<timestamp>/
  summary.json
  summary.md
  failures.json
```

`summary.json` is an array for normal record outputs.

Product list fields:

- `rank`
- `title`
- `price`
- `shop`
- `sku` or `item_id`
- `url`

Product detail fields:

- `title`
- `price`
- `shop`
- `specs`
- `main_images`
- `detail_images`
- `source_url`

Review fields:

- `rank`
- `user`
- `content`
- `date`
- `spec`

Cart fields:

- `index`
- `title`
- `price`
- `quantity` or `spec`
- `shop`
- `sku` or `item_id`

Current account fields:

- `nickname`
- `user_id`
- `logged_in`
- `source_url`

`summary.md` is a human-readable summary of the same records. `failures.json` is an array and is `[]` when no failures occurred.

## Data Flow

Each command follows this flow:

1. Create `ActionBookSession(args.session, args.tab)`.
2. Start or recover a Chrome extension session on the site home URL.
3. Navigate to the target page with `book.goto(...)` or browser-side `location.href = ...`.
4. Read page state with `book.eval(...)`: URL, title, and visible body text.
5. Detect login, CAPTCHA, security verification, or risk-control pages.
6. Extract data through DOM reads or page-context `fetch(..., credentials: 'include')`.
7. Normalize into records.
8. Write `summary.json`, `summary.md`, and `failures.json`.
9. Print the output directory and record count.

Empty results are allowed only when the page is loaded and no matching items are found. Login or risk-control pages must be treated as actionable failures.

## Error Handling

Known error classes:

- `LoginRequiredError`: login, QR login, CAPTCHA, security verification, access frequency, or risk-control state.
- `RuntimeError`: unexpected page structure, API error, malformed payload, or required field missing.

Handling rules:

- Keep the same Chrome window when login or risk-control appears.
- Ask the user to complete login or verification in that window, then rerun.
- Do not swallow base exceptions.
- Do not silently convert login failures into empty results.
- Record known command failures in `failures.json` with command, URL, error message, and timestamp when an output directory exists.

## Reference Documentation

Each new reference file should include:

- Supported scope.
- Common commands.
- Output location and files.
- Login and risk-control behavior.
- Data boundaries.
- Explicitly disabled capabilities.
- Verification commands.

The references must state that cart reads are personal logged-in account data and should only run when the user explicitly requests them.

## Validation

Static validation:

```bash
python3 -m py_compile scripts/jd_workflow.py scripts/taobao_workflow.py
python3 scripts/jd_workflow.py --help
python3 scripts/taobao_workflow.py --help
```

Browser validation:

```bash
python3 scripts/jd_workflow.py search view --query "机械键盘" --count 3
python3 scripts/jd_workflow.py item view --sku 100291143898 --images 5
python3 scripts/jd_workflow.py cart view --count 3

python3 scripts/taobao_workflow.py search view --query "机械键盘" --count 3
python3 scripts/taobao_workflow.py detail view --id 827563850178
python3 scripts/taobao_workflow.py cart view --count 3
```

Acceptance evidence:

- Command exit codes.
- Output directory paths.
- `summary.json` record counts.
- `summary.md` presence.
- `failures.json` status.
- Clear login or risk-control message when browser validation cannot proceed because the current Chrome session needs user action.

## Design Rationale

Two separate scripts are preferred over a shared ecommerce script because JD and Taobao have different pages, selectors, login flows, cart behavior, and review APIs. Small local duplication in each script is acceptable for first-version clarity.

Shared helpers should be introduced only when the same behavior is needed by a third ecommerce site or when duplication becomes a real maintenance burden.
