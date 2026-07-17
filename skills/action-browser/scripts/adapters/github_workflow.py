#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[2]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from scripts.actionbook_interrupts import install_interrupt_handlers
from scripts.actionbook_session import ActionBookSession
from scripts.actionbook_errors import ActionBookFailure, has_failure_code
from scripts.adapters.public_read_runtime import FetchError, ReadResult, clean_text, emit_read, fetch_text, read_count
from scripts.owned_tab_lifecycle import add_workflow_args, attach_workflow
from scripts.workflow_runtime import evaluate, wait_until_stable


TRENDING = "https://github.com/trending"


def load_trending(language: str, since: str, count: int) -> ReadResult:
    suffix = f"/{urllib.parse.quote(language)}" if language else ""
    url = TRENDING + suffix + "?" + urllib.parse.urlencode({"since": since})
    html = fetch_text(url, headers={"Accept": "text/html"})
    blocks = re.findall(r"<article\b[^>]*class=[\"'][^\"']*Box-row[^\"']*[\"'][^>]*>(.*?)</article>", html, flags=re.I | re.S)
    records: list[dict[str, Any]] = []
    for rank, block in enumerate(blocks[:count], 1):
        match = re.search(r"href=[\"'](/[^\"']+/[^\"']+)[\"'][^>]*>\s*(.*?)\s*</a>", block, flags=re.I | re.S)
        if not match:
            continue
        path = match.group(1).split("?")[0].rstrip("/")
        title = clean_text(re.sub(r"<[^>]+>", " ", match.group(2))).replace(" / ", "/")
        stars = re.search(r"([\d,]+)\s+stars?", block, flags=re.I)
        forks = re.search(r"([\d,]+)\s+forks?", block, flags=re.I)
        records.append({"id": path.lstrip("/"), "rank": rank, "name": title, "url": "https://github.com" + path, "stars": stars.group(1) if stars else "", "forks": forks.group(1) if forks else ""})
    if not records and "Sign in" in html and "trending" not in html.lower():
        raise FetchError("needs_login", "GitHub Trending page requires access", retryable=False)
    return ReadResult(records)


def load_whoami(args: argparse.Namespace) -> ReadResult:
    try:
        book = attach_workflow(args, "https://github.com", ActionBookSession)
    except ValueError as exc:
        raise FetchError("needs_user_action", str(exc), retryable=False) from exc
    except ActionBookFailure as exc:
        if not has_failure_code(exc, {"CHROME_URL_BLOCKED", "OWNED_TAB_NOT_FOUND", "OWNED_TAB_MISMATCH"}):
            raise
        raise FetchError("needs_user_action", str(exc), retryable=False) from exc
    book.goto("https://github.com/")
    wait_until_stable(book, timeout_secs=8)
    data = evaluate(
        book,
        """(() => {
          const meta = document.querySelector('meta[name="user-login"]')?.content || '';
          const avatar = document.querySelector('img.avatar-user')?.alt || '';
          const profile = [...document.querySelectorAll('a[href^="/"]')]
            .map(node => node.getAttribute('href') || '')
            .find(href => /^\\/[^\\/]+$/.test(href) && !['/login', '/settings'].includes(href));
          const login = meta || avatar.replace(/^@/, '') || (profile ? profile.slice(1) : '');
          return login ? {login, profile_url: `https://github.com/${login}`} : {auth_required: true};
        })()""",
        "GitHub current account",
        timeout=20,
    )
    if not isinstance(data, dict) or data.get("auth_required") or not data.get("login"):
        raise FetchError("needs_login", "GitHub is not logged in", retryable=False)
    return ReadResult([{"id": data["login"], "login": data["login"], "profile_url": data["profile_url"]}])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GitHub read-only workflows")
    sub = parser.add_subparsers(dest="resource", required=True)
    trending = sub.add_parser("trending")
    trending.add_argument("--language", default="")
    trending.add_argument("--since", choices=("daily", "weekly", "monthly"), default="daily")
    trending.add_argument("--count", type=int, default=10)
    trending.add_argument("--output", default="")
    whoami = sub.add_parser("whoami")
    whoami.add_argument("--output", default="")
    add_workflow_args(whoami)
    return parser


def main(argv: list[str] | None = None) -> int:
    install_interrupt_handlers()
    args = build_parser().parse_args(argv)
    if args.resource == "trending":
        count = read_count(args.count, maximum=50)
        return emit_read(args, site="github", resource="trending", loader=lambda: load_trending(args.language, args.since, count), requested_count=count, limits={"max_items": 50, "timeout_seconds": 20})
    return emit_read(args, site="github", resource="whoami", loader=lambda: load_whoami(args), access="browser", strategy="dom", requested_count=1, limits={"max_items": 1, "timeout_seconds": 60})


if __name__ == "__main__":
    raise SystemExit(main())
