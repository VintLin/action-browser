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


API = "https://api.stackexchange.com/2.3"


def _query(path: str, **params: Any) -> dict[str, Any]:
    params = {"site": "stackoverflow", "pagesize": 20, **params}
    url = API + path + "?" + urllib.parse.urlencode(params)
    payload = fetch_json(url)
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise FetchError("schema_mismatch", "Stack Exchange returned an unexpected payload", retryable=False)
    return payload


def _item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("question_id") or item.get("user_id") or item.get("answer_id") or item.get("comment_id") or item.get("post_id"),
        "title": clean_text(item.get("title")),
        "name": clean_text(item.get("display_name")),
        "url": item.get("link") or item.get("website_url"),
        "excerpt": clean_text(item.get("excerpt")),
        "body": clean_text(item.get("body")),
        "score": item.get("score"),
        "answer_count": item.get("answer_count"),
        "tags": item.get("tags") or [],
        "creation_date": item.get("creation_date"),
        "is_answered": item.get("is_answered"),
    }


def _listing(path: str, count: int, **params: Any) -> ReadResult:
    payload = _query(path, pagesize=count, **params)
    records = [_item(item) for item in payload["items"] if isinstance(item, dict)]
    return ReadResult(records[:count], warnings=[f"backoff={payload['backoff']}"] if payload.get("backoff") else [])


def load_bounties(count: int) -> ReadResult:
    return _listing("/questions/featured", count)


def load_hot(count: int) -> ReadResult:
    return _listing("/questions", count, order="desc", sort="hot")


def load_search(query: str, count: int) -> ReadResult:
    return _listing("/search/advanced", count, order="desc", sort="relevance", q=query)


def load_tag(tag: str, count: int) -> ReadResult:
    return _listing("/questions", count, order="desc", sort="activity", tagged=tag)


def load_unanswered(count: int) -> ReadResult:
    return _listing("/questions/unanswered", count, order="desc", sort="votes")


def load_user(user: str, count: int = 20) -> ReadResult:
    return _listing("/users", count, inname=user, order="desc", sort="reputation")


def load_read(question_id: str) -> ReadResult:
    if not question_id.isdigit():
        raise FetchError("invalid_input", "question id must be numeric", retryable=False)
    question = _query(f"/questions/{question_id}", filter="withbody")["items"]
    answers = _query(f"/questions/{question_id}/answers", filter="withbody", pagesize=50, order="desc", sort="votes")["items"]
    if not question:
        raise FetchError("not_found", f"question {question_id} was not found", retryable=False)
    records = [_item(question[0])]
    records[0]["answers"] = [_item(answer) for answer in answers if isinstance(answer, dict)]
    return ReadResult(records)


def load_related(question_id: str, count: int) -> ReadResult:
    if not question_id.isdigit():
        raise FetchError("invalid_input", "question id must be numeric", retryable=False)
    return _listing(f"/questions/{question_id}/related", count, order="desc", sort="votes")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stack Overflow public read workflows")
    sub = parser.add_subparsers(dest="resource", required=True)

    for name in ("bounties", "hot", "unanswered"):
        command = sub.add_parser(name)
        command.add_argument("--count", type=int, default=10)
        command.add_argument("--output", default="")
    for name in ("search", "tag", "user"):
        command = sub.add_parser(name)
        option = "--query" if name == "search" else f"--{name}"
        command.add_argument(option, required=True)
        command.add_argument("--count", type=int, default=10)
        command.add_argument("--output", default="")
    for name in ("read", "related"):
        command = sub.add_parser(name)
        command.add_argument("--question-id", required=True)
        if name == "related":
            command.add_argument("--count", type=int, default=10)
        command.add_argument("--output", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    count = read_count(getattr(args, "count", 1 if args.resource == "read" else 10), maximum=50)
    if args.resource == "bounties":
        loader = lambda: load_bounties(count)
    elif args.resource == "hot":
        loader = lambda: load_hot(count)
    elif args.resource == "unanswered":
        loader = lambda: load_unanswered(count)
    elif args.resource == "search":
        loader = lambda: load_search(args.query, count)
    elif args.resource == "tag":
        loader = lambda: load_tag(args.tag, count)
    elif args.resource == "user":
        loader = lambda: load_user(args.user, count)
    elif args.resource == "read":
        loader = lambda: load_read(args.question_id)
    else:
        loader = lambda: load_related(args.question_id, count)
    return emit_read(args, site="stackoverflow", resource=args.resource, loader=loader, requested_count=count, limits={"max_items": 50, "timeout_seconds": 20})


if __name__ == "__main__":
    raise SystemExit(main())
