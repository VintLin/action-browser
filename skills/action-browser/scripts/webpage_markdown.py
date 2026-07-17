#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extract a web page to Markdown with the same core approach used by Obsidian
Web Clipper: capture page HTML, extract readable content with Defuddle, then
convert the extracted HTML to Markdown.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from actionbook_interrupts import install_interrupt_handlers
from actionbook_session import ActionBookSession as ActionBook
from script_common import DEFAULT_TAB, add_session_tab_args, log, run_command


DEFAULT_SESSION = "markdown-task"
SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = SKILL_DIR / "assets" / "markdown"
DEFAULT_NODE_PREFIX = Path(
    os.environ.get(
        "ACTION_BROWSER_MARKDOWN_NODE_PREFIX",
        str(Path.home() / ".cache" / "action-browser" / "webpage-markdown-node"),
    )
)


CAPTURE_PAGE_JS = r"""
(() => {
  const serializeNode = node => {
    const div = document.createElement('div');
    div.appendChild(node);
    return div.innerHTML;
  };
  document.querySelectorAll('*').forEach(el => {
    try {
      if (el.shadowRoot && el.shadowRoot.innerHTML) {
        el.setAttribute('data-defuddle-shadow', el.shadowRoot.innerHTML);
      }
    } catch (error) {}
  });
  let selectedHtml = '';
  let selectedText = '';
  const selection = window.getSelection();
  if (selection && selection.rangeCount > 0 && !selection.isCollapsed) {
    const range = selection.getRangeAt(0);
    selectedText = String(selection.toString() || '').trim();
    selectedHtml = serializeNode(range.cloneContents());
  }
  return {
    url: location.href,
    baseUrl: document.baseURI,
    title: document.title || '',
    html: '<!doctype html>\n' + document.documentElement.outerHTML,
    selectedHtml,
    selectedText,
    capturedAt: new Date().toISOString()
  };
})()
"""


NODE_HELPER = r"""
import fs from 'node:fs';
import { parseHTML } from 'linkedom';
import { Defuddle as parseDefuddle } from 'defuddle/node';

function readStdin() {
  return fs.readFileSync(0, 'utf8');
}

function cleanText(value) {
  return String(value || '').replace(/\u00a0/g, ' ').trim();
}

function timeoutPromise(ms) {
  return new Promise((_, reject) => setTimeout(() => reject(new Error('parseAsync timeout')), ms));
}

function absolutize(value, baseUrl) {
  if (!value) return value;
  if (/^(?:https?:|data:|mailto:|tel:|#|\/\/)/i.test(value)) return value;
  try {
    return new URL(value, baseUrl).href;
  } catch {
    return value;
  }
}

function cleanFullHtml(html, baseUrl) {
  const parsed = parseHTML(html);
  const doc = parsed.document;
  doc.querySelectorAll('script, style').forEach(el => el.remove());
  doc.querySelectorAll('*').forEach(el => {
    el.removeAttribute('style');
    for (const attr of ['src', 'href']) {
      const value = el.getAttribute(attr);
      if (value) el.setAttribute(attr, absolutize(value, baseUrl));
    }
    const srcset = el.getAttribute('srcset');
    if (srcset) {
      const next = srcset.split(',').map(item => {
        const parts = item.trim().split(/\s+/);
        if (!parts[0]) return item.trim();
        parts[0] = absolutize(parts[0], baseUrl);
        return parts.join(' ');
      }).join(', ');
      el.setAttribute('srcset', next);
    }
  });
  return '<!doctype html>\n' + doc.documentElement.outerHTML;
}

function htmlToText(html) {
  if (!html) return '';
  const parsed = parseHTML(`<!doctype html><html><body>${html}</body></html>`);
  const text = parsed.document.body?.textContent || parsed.document.documentElement?.textContent || '';
  return cleanText(text);
}

async function parseWithDefuddle(html, url, timeoutMs) {
  return await Promise.race([
    parseDefuddle(html, url, { separateMarkdown: true }),
    timeoutPromise(timeoutMs),
  ]);
}

function getPackageVersion(name) {
  try {
    const pkgUrl = new URL(`./node_modules/${name}/package.json`, import.meta.url);
    return JSON.parse(fs.readFileSync(pkgUrl, 'utf8')).version || '';
  } catch {
    return '';
  }
}

const input = JSON.parse(readStdin());
const url = input.url || input.baseUrl || 'about:blank';
const sourceHtml = input.html || '<html><body></body></html>';
const defuddled = await parseWithDefuddle(sourceHtml, url, input.timeoutMs || 8000);
const selectedHtml = cleanText(input.selectedHtml);
let markdown = defuddled.contentMarkdown || '';
let selectedMarkdown = '';
if (selectedHtml) {
  const selected = await parseWithDefuddle(selectedHtml, url, input.timeoutMs || 8000);
  selectedMarkdown = selected.contentMarkdown || '';
  if (input.useSelection) markdown = selectedMarkdown;
}
const fullHtml = cleanFullHtml(sourceHtml, url);

const result = {
  engine: 'defuddle',
  engineVersion: getPackageVersion('defuddle'),
  markdown,
  selectedMarkdown,
  selectedHtml,
  textContent: htmlToText(defuddled.content || ''),
  contentHtml: defuddled.content || '',
  fullHtml,
  title: defuddled.title || input.title || '',
  author: defuddled.author || '',
  description: defuddled.description || '',
  favicon: defuddled.favicon || '',
  image: defuddled.image || '',
  language: defuddled.language || '',
  parseTime: defuddled.parseTime || 0,
  published: defuddled.published || '',
  schemaOrgData: defuddled.schemaOrgData || null,
  site: defuddled.site || '',
  wordCount: defuddled.wordCount || 0,
  metaTags: defuddled.metaTags || [],
  extractedContent: defuddled.variables || {},
};

process.stdout.write(JSON.stringify(result));
"""
def default_output_dir() -> Path:
    return ASSETS_DIR / "pages" / datetime.now().strftime("%Y%m%d-%H%M%S")


def ensure_node_deps(node_prefix: Path = DEFAULT_NODE_PREFIX, install: bool = True) -> Path:
    helper_path = node_prefix / "webpage_markdown_helper.mjs"
    defuddle_dir = node_prefix / "node_modules" / "defuddle"
    linkedom_dir = node_prefix / "node_modules" / "linkedom"
    if (not defuddle_dir.exists() or not linkedom_dir.exists()) and not install:
        raise RuntimeError(
            "Missing Node dependencies: defuddle and linkedom. "
            f"Run with dependency install enabled or install them under {node_prefix}"
        )
    if not defuddle_dir.exists() or not linkedom_dir.exists():
        if shutil.which("npm") is None:
            raise RuntimeError("npm is required to install defuddle/linkedom for Markdown extraction")
        log(f"安装 Markdown 提取依赖到本机缓存: {node_prefix}")
        node_prefix.mkdir(parents=True, exist_ok=True)
        run_command(
            [
                "npm",
                "install",
                "--prefix",
                str(node_prefix),
                "--no-audit",
                "--no-fund",
                "--silent",
                "defuddle@^0.18.1",
                "linkedom@^0.18.0",
            ],
            timeout=180.0,
        )
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text(NODE_HELPER, encoding="utf-8")
    return helper_path


def run_defuddle(payload: dict[str, Any], node_prefix: Path = DEFAULT_NODE_PREFIX, install_deps: bool = True) -> dict[str, Any]:
    if shutil.which("node") is None:
        raise RuntimeError("node is required for defuddle Markdown extraction")
    helper_path = ensure_node_deps(node_prefix=node_prefix, install=install_deps)
    proc = subprocess.run(
        ["node", str(helper_path)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=120.0,
        cwd=str(node_prefix),
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "node defuddle helper failed").strip())
    return json.loads(proc.stdout)


def capture_current_page(session: str, tab: str) -> dict[str, Any]:
    if not tab:
        raise RuntimeError("--tab is required for current-page capture")
    book = ActionBook.owned(session, tab)
    value = book.eval(CAPTURE_PAGE_JS, timeout=20.0)
    if not isinstance(value, dict):
        raise RuntimeError(f"unexpected ActionBook eval result: {value!r}")
    return value


def capture_url(url: str, session: str, tab: str = "") -> dict[str, Any]:
    book = ActionBook.owned(session, tab)
    book.start(url)
    book.goto(url)
    time.sleep(1.0)
    value = book.eval(CAPTURE_PAGE_JS, timeout=20.0)
    if not isinstance(value, dict):
        raise RuntimeError(f"unexpected ActionBook eval result: {value!r}")
    value["sessionId"] = book.session
    value["tabId"] = book.tab
    return value


def read_html_file(path: Path, url: str) -> dict[str, Any]:
    html = path.read_text(encoding="utf-8")
    return {
        "url": url or path.resolve().as_uri(),
        "baseUrl": url or path.resolve().as_uri(),
        "title": path.stem,
        "html": html,
        "selectedHtml": "",
        "selectedText": "",
        "capturedAt": datetime.now(timezone.utc).isoformat(),
    }


def build_markdown(markdown: str, metadata: dict[str, Any], include_frontmatter: bool = False) -> str:
    markdown = markdown.strip() + "\n"
    if not include_frontmatter:
        return markdown
    fields = {
        "title": metadata.get("title") or "",
        "source": metadata.get("url") or "",
        "author": metadata.get("author") or "",
        "published": metadata.get("published") or "",
        "site": metadata.get("site") or "",
        "captured": metadata.get("capturedAt") or "",
    }
    lines = ["---"]
    for key, value in fields.items():
        if value:
            text = str(value).replace('"', '\\"')
            lines.append(f'{key}: "{text}"')
    lines.append("---")
    return "\n".join(lines) + "\n\n" + markdown


def write_output(
    result: dict[str, Any],
    capture: dict[str, Any],
    output_dir: Path,
    include_frontmatter: bool = False,
    save_html: bool = False,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "url": capture.get("url") or "",
        "baseUrl": capture.get("baseUrl") or "",
        "capturedAt": capture.get("capturedAt") or "",
        "sessionId": capture.get("sessionId") or "",
        "tabId": capture.get("tabId") or "",
        "title": result.get("title") or capture.get("title") or "",
        "author": result.get("author") or "",
        "description": result.get("description") or "",
        "favicon": result.get("favicon") or "",
        "image": result.get("image") or "",
        "language": result.get("language") or "",
        "published": result.get("published") or "",
        "site": result.get("site") or "",
        "wordCount": result.get("wordCount") or 0,
        "parseTime": result.get("parseTime") or 0,
        "engine": result.get("engine") or "defuddle",
        "engineVersion": result.get("engineVersion") or "",
        "selectedText": capture.get("selectedText") or "",
        "selectedHtmlLength": len(result.get("selectedHtml") or ""),
        "selectedMarkdownLength": len(result.get("selectedMarkdown") or ""),
        "textContentLength": len(result.get("textContent") or ""),
        "contentHtmlLength": len(result.get("contentHtml") or ""),
        "fullHtmlLength": len(result.get("fullHtml") or ""),
        "markdownLength": len(result.get("markdown") or ""),
        "schemaOrgData": result.get("schemaOrgData"),
        "metaTags": result.get("metaTags") or [],
        "extractedContent": result.get("extractedContent") or {},
    }
    markdown = build_markdown(str(result.get("markdown") or ""), metadata, include_frontmatter=include_frontmatter)
    md_path = output_dir / "content.md"
    meta_path = output_dir / "metadata.json"
    md_path.write_text(markdown, encoding="utf-8")
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    paths = {
        "output_dir": str(output_dir),
        "markdown": str(md_path),
        "metadata": str(meta_path),
    }
    if save_html:
        content_html_path = output_dir / "content.html"
        full_html_path = output_dir / "full.html"
        content_html_path.write_text(str(result.get("contentHtml") or ""), encoding="utf-8")
        full_html_path.write_text(str(result.get("fullHtml") or ""), encoding="utf-8")
        paths["content_html"] = str(content_html_path)
        paths["full_html"] = str(full_html_path)
    return paths


def convert_capture(
    capture: dict[str, Any],
    output_dir: Path,
    use_selection: bool = False,
    include_frontmatter: bool = False,
    save_html: bool = False,
    install_deps: bool = True,
    min_text_chars: int = 800,
    allow_short: bool = False,
) -> dict[str, Any]:
    payload = {
        "url": capture.get("url") or capture.get("baseUrl") or "about:blank",
        "baseUrl": capture.get("baseUrl") or capture.get("url") or "about:blank",
        "title": capture.get("title") or "",
        "html": capture.get("html") or "",
        "selectedHtml": capture.get("selectedHtml") or "",
        "useSelection": use_selection,
        "timeoutMs": 8000,
    }
    result = run_defuddle(payload, install_deps=install_deps)
    text_length = len(str(result.get("textContent") or "").strip())
    if min_text_chars > 0 and text_length < min_text_chars and not allow_short:
        raise RuntimeError(
            f"extracted text is too short for long-text Markdown extraction: "
            f"textContentLength={text_length}, minTextChars={min_text_chars}. "
            "Use --allow-short only for debugging or non-article pages."
        )
    paths = write_output(result, capture, output_dir, include_frontmatter=include_frontmatter, save_html=save_html)
    return {
        "url": capture.get("url") or "",
        "title": result.get("title") or capture.get("title") or "",
        "wordCount": result.get("wordCount") or 0,
        "markdownLength": len(result.get("markdown") or ""),
        "textContentLength": text_length,
        "minTextChars": min_text_chars,
        "engine": result.get("engine") or "defuddle",
        "engineVersion": result.get("engineVersion") or "",
        **paths,
    }


def add_common_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", default="", help="Output directory. Defaults to assets/markdown/pages/yyyyMMdd-HHmmss")
    parser.add_argument("--use-selection", action="store_true", help="Convert the current selection when selected HTML exists")
    parser.add_argument("--frontmatter", action="store_true", help="Prefix content.md with simple YAML frontmatter")
    parser.add_argument("--save-html", action="store_true", help="Also write content.html and cleaned full.html")
    parser.add_argument("--no-install-deps", action="store_true", help="Do not install missing Node dependencies")
    parser.add_argument("--min-text-chars", type=int, default=800, help="Minimum extracted plain-text length required before writing output")
    parser.add_argument("--allow-short", action="store_true", help="Write output even when extracted text is shorter than --min-text-chars")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract webpages to Markdown with Defuddle")
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture", help="Open a URL with ActionBook and extract it to Markdown")
    capture_parser.add_argument("--url", required=True)
    add_session_tab_args(capture_parser, default_session=DEFAULT_SESSION)
    add_common_output_args(capture_parser)

    current_parser = subparsers.add_parser("current", help="Extract the current ActionBook tab to Markdown")
    current_parser.add_argument("--session", required=True)
    current_parser.add_argument("--tab", required=True)
    add_common_output_args(current_parser)

    convert_parser = subparsers.add_parser("convert", help="Convert a local HTML file to Markdown")
    convert_parser.add_argument("--html-file", required=True)
    convert_parser.add_argument("--url", default="")
    add_common_output_args(convert_parser)

    return parser


def main(argv: list[str] | None = None) -> int:
    install_interrupt_handlers()
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_output_dir()
    install_deps = not args.no_install_deps

    if args.command == "capture":
        capture = capture_url(args.url, args.session, args.tab)
    elif args.command == "current":
        capture = capture_current_page(args.session, args.tab)
    elif args.command == "convert":
        capture = read_html_file(Path(args.html_file).expanduser(), args.url)
    else:
        raise RuntimeError(f"unsupported command: {args.command}")

    result = convert_capture(
        capture,
        output_dir=output_dir,
        use_selection=args.use_selection,
        include_frontmatter=args.frontmatter,
        save_html=args.save_html,
        install_deps=install_deps,
        min_text_chars=args.min_text_chars,
        allow_short=args.allow_short,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
