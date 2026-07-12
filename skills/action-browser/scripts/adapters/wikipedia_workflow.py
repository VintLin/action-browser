#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import sys
import urllib.parse
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[2]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from scripts.adapters.public_read_runtime import FetchError, ReadResult, clean_text, emit_read, fetch_json, read_count


API = "https://en.wikipedia.org/w/api.php"
SUMMARY_API = "https://en.wikipedia.org/api/rest_v1/page/summary/"
TRENDING_API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access"


def _api(**params: Any) -> dict[str, Any]:
    url = API + "?" + urllib.parse.urlencode({"format": "json", "formatversion": 2, **params})
    payload = fetch_json(url)
    if not isinstance(payload, dict) or "query" not in payload:
        raise FetchError("schema_mismatch", "Wikipedia API returned an unexpected payload", retryable=False)
    return payload


def _page_record(page: dict[str, Any]) -> dict[str, Any]:
    title = clean_text(page.get("title"))
    return {
        "id": page.get("pageid"),
        "title": title,
        "url": page.get("fullurl") or f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
        "extract": clean_text(page.get("extract")),
        "timestamp": page.get("touched") or page.get("timestamp"),
    }


def _pages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    pages = payload.get("query", {}).get("pages", [])
    return [page for page in pages if isinstance(page, dict) and not page.get("missing")]


def load_search(query: str, count: int) -> ReadResult:
    payload = _api(action="query", list="search", srsearch=query, srlimit=count, srprop="snippet|timestamp|wordcount")
    records = [
        {
            "id": item.get("pageid"),
            "title": clean_text(item.get("title")),
            "url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(str(item.get('title', '')).replace(' ', '_'))}",
            "snippet": clean_text(item.get("snippet")),
            "timestamp": item.get("timestamp"),
            "wordcount": item.get("wordcount"),
        }
        for item in payload.get("query", {}).get("search", [])
        if isinstance(item, dict)
    ]
    return ReadResult(records[:count])


def load_page(title: str) -> ReadResult:
    payload = _api(action="query", prop="extracts|info", titles=title, redirects=1, explaintext=1, exintro=0, inprop="url")
    pages = _pages(payload)
    if not pages:
        raise FetchError("not_found", f"Wikipedia page {title!r} was not found", retryable=False)
    return ReadResult([_page_record(pages[0])])


def load_summary(title: str) -> ReadResult:
    encoded = urllib.parse.quote(title.replace(" ", "_"), safe="")
    payload = fetch_json(SUMMARY_API + encoded)
    if not isinstance(payload, dict) or payload.get("type") == "https://mediawiki.org/wiki/HyperSwitch/errors/not_found":
        raise FetchError("not_found", f"Wikipedia summary {title!r} was not found", retryable=False)
    return ReadResult(
        [
            {
                "id": payload.get("pageid"),
                "title": clean_text(payload.get("title")),
                "url": payload.get("content_urls", {}).get("desktop", {}).get("page") or payload.get("fullurl"),
                "description": clean_text(payload.get("description")),
                "extract": clean_text(payload.get("extract")),
                "thumbnail": payload.get("thumbnail", {}).get("source"),
            }
        ]
    )


def load_random(count: int) -> ReadResult:
    payload = _api(action="query", list="random", rnnamespace=0, rnlimit=count)
    records = [{"id": item.get("id"), "title": clean_text(item.get("title")), "url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(str(item.get('title', '')).replace(' ', '_'))}"} for item in payload.get("query", {}).get("random", []) if isinstance(item, dict)]
    return ReadResult(records[:count])


def load_trending(count: int) -> ReadResult:
    yesterday = dt.date.today() - dt.timedelta(days=1)
    url = f"{TRENDING_API}/{yesterday.year}/{yesterday.month:02d}/{yesterday.day:02d}"
    payload = fetch_json(url)
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list) or not payload["items"]:
        raise FetchError("schema_mismatch", "Wikipedia pageview trends returned an unexpected payload", retryable=False)
    articles = payload["items"][0].get("articles", [])
    records = [{"id": article.get("article"), "title": clean_text(article.get("article")), "views": article.get("views"), "rank": article.get("rank"), "url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(str(article.get('article', '')).replace(' ', '_'))}"} for article in articles if isinstance(article, dict) and article.get("article") not in {"Main_Page", "Special:Search"}]
    return ReadResult(records[:count])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Wikipedia public read workflows")
    sub = parser.add_subparsers(dest="resource", required=True)
    search = sub.add_parser("search")
    search.add_argument("--query", required=True)
    search.add_argument("--count", type=int, default=10)
    search.add_argument("--output", default="")
    for name in ("page", "summary"):
        command = sub.add_parser(name)
        command.add_argument("--title", required=True)
        command.add_argument("--output", default="")
    for name in ("random", "trending"):
        command = sub.add_parser(name)
        command.add_argument("--count", type=int, default=10)
        command.add_argument("--output", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    count = read_count(getattr(args, "count", 1), maximum=50)
    if args.resource == "search":
        loader = lambda: load_search(args.query, count)
    elif args.resource == "page":
        loader = lambda: load_page(args.title)
    elif args.resource == "summary":
        loader = lambda: load_summary(args.title)
    elif args.resource == "random":
        loader = lambda: load_random(count)
    else:
        loader = lambda: load_trending(count)
    return emit_read(args, site="wikipedia", resource=args.resource, loader=loader, requested_count=count, limits={"max_items": 50, "timeout_seconds": 20})


if __name__ == "__main__":
    raise SystemExit(main())
