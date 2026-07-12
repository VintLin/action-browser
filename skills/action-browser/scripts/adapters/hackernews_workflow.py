#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import urllib.parse
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[2]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from scripts.adapters.public_read_runtime import FetchError, ReadResult, clean_text, emit_read, fetch_json, read_count


API = "https://hacker-news.firebaseio.com/v0"
ALGOLIA = "https://hn.algolia.com/api/v1"
STORY_ENDPOINTS = {"ask": "askstories", "best": "beststories", "jobs": "jobstories", "new": "newstories", "show": "showstories", "top": "topstories"}


def _item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "title": clean_text(item.get("title")),
        "url": item.get("url") or (f"https://news.ycombinator.com/item?id={item.get('id')}" if item.get("id") else ""),
        "author": clean_text(item.get("by")),
        "score": item.get("score"),
        "text": clean_text(item.get("text")),
        "time": item.get("time"),
        "type": item.get("type"),
        "descendants": item.get("descendants"),
    }


def _fetch_item(item_id: int) -> dict[str, Any]:
    payload = fetch_json(f"{API}/item/{item_id}.json")
    if not isinstance(payload, dict):
        raise FetchError("schema_mismatch", f"Hacker News item {item_id} has an unexpected shape", retryable=False)
    return payload


def load_listing(resource: str, count: int) -> ReadResult:
    ids = fetch_json(f"{API}/{STORY_ENDPOINTS[resource]}.json")
    if not isinstance(ids, list):
        raise FetchError("schema_mismatch", "Hacker News story list has an unexpected shape", retryable=False)
    records = [_item(item) for item in (_fetch_item(int(item_id)) for item_id in ids[:count]) if item]
    return ReadResult(records)


def load_search(query: str, count: int) -> ReadResult:
    url = ALGOLIA + "/search?" + urllib.parse.urlencode({"query": query, "hitsPerPage": count})
    payload = fetch_json(url)
    if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
        raise FetchError("schema_mismatch", "Hacker News search has an unexpected shape", retryable=False)
    records = []
    for hit in payload["hits"][:count]:
        if not isinstance(hit, dict):
            continue
        records.append(
            {
                "id": hit.get("objectID"),
                "title": clean_text(hit.get("title") or hit.get("story_title")),
                "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                "author": clean_text(hit.get("author")),
                "points": hit.get("points"),
                "created_at": hit.get("created_at"),
            }
        )
    return ReadResult(records)


def load_read(item_id: str) -> ReadResult:
    if not item_id.isdigit():
        raise FetchError("invalid_input", "item id must be numeric", retryable=False)
    item = _fetch_item(int(item_id))
    comments = []
    for comment_id in (item.get("kids") or [])[:20]:
        comment = _fetch_item(int(comment_id))
        if comment.get("deleted") or comment.get("dead"):
            continue
        comments.append({"id": comment.get("id"), "author": clean_text(comment.get("by")), "text": clean_text(comment.get("text")), "time": comment.get("time")})
    record = _item(item)
    record["comments"] = comments
    return ReadResult([record])


def load_user(user: str) -> ReadResult:
    payload = fetch_json(f"{API}/user/{urllib.parse.quote(user)}.json")
    if not isinstance(payload, dict):
        raise FetchError("not_found", f"Hacker News user {user} was not found", retryable=False)
    return ReadResult([{"id": payload.get("id"), "about": clean_text(payload.get("about")), "created": payload.get("created"), "karma": payload.get("karma"), "submitted": payload.get("submitted", [])}])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hacker News public read workflows")
    sub = parser.add_subparsers(dest="resource", required=True)
    for name in STORY_ENDPOINTS:
        command = sub.add_parser(name)
        command.add_argument("--count", type=int, default=10)
        command.add_argument("--output", default="")
    search = sub.add_parser("search")
    search.add_argument("--query", required=True)
    search.add_argument("--count", type=int, default=10)
    search.add_argument("--output", default="")
    read = sub.add_parser("read")
    read.add_argument("--item-id", required=True)
    read.add_argument("--output", default="")
    user = sub.add_parser("user")
    user.add_argument("--user", required=True)
    user.add_argument("--output", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    count = read_count(getattr(args, "count", 1), maximum=20)
    if args.resource in STORY_ENDPOINTS:
        loader = lambda: load_listing(args.resource, count)
    elif args.resource == "search":
        loader = lambda: load_search(args.query, count)
    elif args.resource == "read":
        loader = lambda: load_read(args.item_id)
    else:
        loader = lambda: load_user(args.user)
    return emit_read(args, site="hackernews", resource=args.resource, loader=loader, requested_count=count, limits={"max_items": 20, "max_comments": 20, "max_requests": 41, "timeout_seconds": 60})


if __name__ == "__main__":
    raise SystemExit(main())
