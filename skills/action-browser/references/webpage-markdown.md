# Webpage Markdown Extraction

This reference describes the reusable webpage-to-Markdown extractor in `action-browser`.

## Method

The extractor follows the current Obsidian Web Clipper content pipeline:

1. Capture the live page HTML, URL, title, and current selection from Chrome through ActionBook.
2. Stamp open shadow-root HTML into `data-defuddle-shadow` attributes when accessible.
3. Parse the HTML with `defuddle`.
4. Convert Defuddle's extracted content HTML through Defuddle's Markdown pipeline. In Node, the script uses `defuddle/node` with `separateMarkdown`, which calls the same Markdown conversion path.
5. Write Markdown and metadata to local files.

This script is intentionally site-agnostic, but it is only meant for long-form content such as X article bodies, blog posts, docs pages, and news articles. It is not the default extractor for all browser tasks. Short social posts, media cards, lists, metrics, comments, and site-specific structured fields should keep using their existing workflow logic.

## Script

```bash
python3 scripts/webpage_markdown.py --help
```

The first run may install Node packages `defuddle` and `linkedom` into:

```text
~/.cache/action-browser/webpage-markdown-node/
```

This avoids adding `node_modules/` to the skill directory.

## Capture URL

Open a URL with ActionBook extension mode, then extract it:

```bash
python3 scripts/webpage_markdown.py capture \
  --url "https://example.com/article" \
  --session markdown-task
```

## Capture Current Tab

Extract the current tab without navigating:

```bash
python3 scripts/webpage_markdown.py current \
  --session s1 \
  --tab t1
```

Use this when another site workflow has already opened the target detail page.

## Convert Local HTML

Convert saved HTML without browser access:

```bash
python3 scripts/webpage_markdown.py convert \
  --html-file page.html \
  --url "https://example.com/article"
```

## Output

Default output:

```text
assets/markdown/pages/yyyyMMdd-HHmmss/
  content.md
  metadata.json
```

Optional flags:

- `--frontmatter`: prefix `content.md` with simple YAML frontmatter.
- `--save-html`: also write `content.html` and cleaned `full.html`.
- `--use-selection`: convert selected HTML if the page has an active selection.
- `--min-text-chars`: minimum extracted plain-text length before writing output. Default is `800`.
- `--allow-short`: bypass the long-text threshold for debugging only.
- `--no-install-deps`: fail if local Node dependencies are missing.

## Metadata

`metadata.json` includes:

- source URL, captured time, session/tab id
- title, author, description, site, published time, language
- word count, parse time, engine name/version
- selected text length, content HTML length, Markdown length
- schema.org data, meta tags, Defuddle extracted variables

## Failure Handling

- If ActionBook or Chrome extension is not connected, follow `references/status-check.md`.
- If the page requires login, CAPTCHA, MFA, or risk-control handling, complete it in the same Chrome window first.
- If Defuddle misses content, rerun with `--save-html` and inspect `content.html` / `full.html`.
- If the extracted text is shorter than `--min-text-chars`, the script exits without writing output. This is expected for ordinary short posts.
- If the site blocks URL capture, open the page manually and use `current`.
