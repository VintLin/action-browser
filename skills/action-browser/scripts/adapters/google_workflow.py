#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[2]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from scripts.adapters.public_read_runtime import FetchError, ReadResult, clean_text, emit_read, fetch_json, fetch_text, read_count
from scripts.actionbook_session import ActionBookSession
from scripts.workflow_runtime import add_workflow_args, attach_workflow, evaluate, wait_until_stable


GOOGLE_SEARCH = "https://www.google.com/search"
GOOGLE_HOME = "https://www.google.com/"
GOOGLE_NEWS = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
GOOGLE_SUGGEST = "https://suggestqueries.google.com/complete/search?client=firefox"
GOOGLE_TRENDS = "https://trends.google.com/trending/rss?geo=US"


class SearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._href = ""
        self._text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        self._href = dict(attrs).get("href") or ""
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._href:
            return
        text = clean_text(" ".join(self._text))
        href = self._href
        self._href = ""
        if text and href:
            self.links.append((text, href))


def _rss_items(xml_text: str, count: int) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FetchError("schema_mismatch", "Google RSS returned invalid XML", retryable=False) from exc
    records: list[dict[str, Any]] = []
    for item in root.findall(".//item")[:count]:
        records.append(
            {
                "id": clean_text(item.findtext("guid") or item.findtext("link") or item.findtext("title")),
                "title": clean_text(item.findtext("title")),
                "url": clean_text(item.findtext("link")),
                "published_at": clean_text(item.findtext("pubDate")),
                "description": clean_text(item.findtext("description")),
                "source": clean_text(item.findtext("source")),
            }
        )
    return records


def load_news(count: int) -> ReadResult:
    return ReadResult(_rss_items(fetch_text(GOOGLE_NEWS), count))


def load_search(query: str, count: int) -> ReadResult:
    url = GOOGLE_SEARCH + "?" + urllib.parse.urlencode({"q": query, "num": count, "hl": "en"})
    parser = SearchParser()
    html_text = fetch_text(url, headers={"Accept": "text/html"})
    if "httpservice/retry" in html_text or "emsg=SG_REL" in html_text:
        raise FetchError("risk_control", "Google Search returned a JavaScript/retry interstitial", retryable=False)
    parser.feed(html_text)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for title, raw_url in parser.links:
        if raw_url.startswith("/url?"):
            target = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query).get("q", [""])[0]
        else:
            target = raw_url
        if not target.startswith(("http://", "https://")) or "google." in urllib.parse.urlparse(target).netloc or target in seen:
            continue
        seen.add(target)
        records.append({"id": target, "title": title, "url": target})
        if len(records) >= count:
            break
    if not records:
        raise FetchError("field_gap", "Google Search returned no readable result links", retryable=False)
    return ReadResult(records)


def _browser_search_records(payload: Any, count: int) -> ReadResult:
    if not isinstance(payload, dict) or payload.get("riskControl"):
        raise FetchError("risk_control", "Google Search browser page requires user verification", retryable=False)
    raw_records = payload.get("results")
    if not isinstance(raw_records, list):
        raise FetchError("schema_mismatch", "Google Search browser payload has an unexpected shape", retryable=False)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_records:
        if not isinstance(item, dict):
            continue
        target = str(item.get("url") or "")
        title = clean_text(item.get("title"))
        if target.startswith(("http://", "https://")) and title and target not in seen:
            seen.add(target)
            records.append({"id": target, "title": title, "url": target})
        if len(records) >= count:
            break
    if not records:
        raise FetchError("field_gap", "Google Search browser page returned no readable results", retryable=False)
    return ReadResult(records, strategy_used="dom", last_url=str(payload.get("url") or ""), last_title=clean_text(payload.get("title")))


def load_search_browser(args: argparse.Namespace, count: int) -> ReadResult:
    try:
        book = attach_workflow(args, "https://www.google.com", ActionBookSession)
    except ValueError as exc:
        raise FetchError("needs_user_action", str(exc), retryable=False) from exc
    except RuntimeError as exc:
        if "chrome-extension://" not in str(exc):
            raise
        raise FetchError("needs_user_action", str(exc), retryable=False) from exc
    book.goto(GOOGLE_HOME)
    wait_until_stable(book, timeout_secs=12)
    # ponytail: Google currently exposes the search box as textarea/input[name=q]; keep only these two selectors.
    filled = False
    for selector in ("textarea[name='q']", "input[name='q']"):
        try:
            book.browser("fill", selector, args.query, timeout=20.0)
            filled = True
            break
        except RuntimeError:
            continue
    if not filled:
        raise FetchError("field_gap", "Google Search page has no usable search input", retryable=False)
    book.browser("press", "Enter", timeout=20.0)
    wait_until_stable(book, timeout_secs=12)
    payload = evaluate(
        book,
        f"""(() => {{
          const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
          const body = clean(document.body?.innerText || '');
          const riskControl = /unusual traffic|not a robot|captcha|sorry/i.test(body.slice(0, 4000));
          const results = [...document.querySelectorAll('a[href]')].map((node) => ({{
            title: clean(node.innerText || node.textContent || ''),
            url: node.href || ''
          }})).filter((item) => item.title && /^https?:\\/\\//.test(item.url) && !/google\\./i.test(new URL(item.url).hostname));
          return {{riskControl, url: location.href, title: document.title || '', results}};
        }})()""",
        "Google Search browser page",
        timeout=30,
    )
    return _browser_search_records(payload, count)


def load_search_or_browser(args: argparse.Namespace) -> ReadResult:
    count = read_count(args.count, maximum=50)
    try:
        return load_search(args.query, count)
    except FetchError as exc:
        if exc.reason_code not in {"risk_control", "field_gap"} or not all(str(getattr(args, key, "") or "").strip() for key in ("task_id", "session", "tab")):
            raise
        return load_search_browser(args, count)


def load_suggest(query: str, count: int) -> ReadResult:
    payload = fetch_json(GOOGLE_SUGGEST + "&" + urllib.parse.urlencode({"q": query}))
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        raise FetchError("schema_mismatch", "Google suggestions payload has an unexpected shape", retryable=False)
    records = [{"id": str(index), "query": clean_text(value)} for index, value in enumerate(payload[1][:count]) if clean_text(value)]
    return ReadResult(records)


def load_trends(count: int) -> ReadResult:
    records = _rss_items(fetch_text(GOOGLE_TRENDS), count)
    for record in records:
        record["traffic"] = record.pop("description", "")
    return ReadResult(records)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Google public read workflows")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("news", "trends"):
        command = sub.add_parser(name)
        command.add_argument("--count", type=int, default=10)
        command.add_argument("--output", default="")
        command.set_defaults(loader=lambda args, name=name: load_news(read_count(args.count, maximum=50)) if name == "news" else load_trends(read_count(args.count, maximum=50)), resource=name)
    for name in ("search", "suggest"):
        command = sub.add_parser(name)
        command.add_argument("--query", required=True)
        command.add_argument("--count", type=int, default=10)
        command.add_argument("--output", default="")
        if name == "search":
            add_workflow_args(command)
        command.set_defaults(loader=lambda args, name=name: load_search_or_browser(args) if name == "search" else load_suggest(args.query, read_count(args.count, maximum=50)), resource=name)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return emit_read(args, site="google", resource=args.resource, loader=lambda: args.loader(args), requested_count=args.count, limits={"max_items": 50, "timeout_seconds": 20})


if __name__ == "__main__":
    raise SystemExit(main())
