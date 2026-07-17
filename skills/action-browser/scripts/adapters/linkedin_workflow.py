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
from scripts.adapters.public_read_runtime import FetchError, ReadResult, clean_text, emit_read, read_count
from scripts.owned_tab_lifecycle import add_workflow_args, attach_workflow
from scripts.workflow_runtime import evaluate, wait_until_stable


LINKEDIN = "https://www.linkedin.com"
READ_RESOURCES = (
    "company", "connections", "inbox", "job-detail", "jobs-preferences", "people-search", "post-analytics", "posts",
    "profile-analytics", "profile-experience", "profile-projects", "profile-read", "salesnav-inbox", "salesnav-search",
    "salesnav-thread", "search", "sent-invitations", "services-read", "thread-snapshot", "timeline", "whoami",
)


def safe_linkedin_url(value: str, label: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {"linkedin.com", "www.linkedin.com"} or parsed.username or parsed.password or parsed.port:
        raise FetchError("invalid_input", f"{label} must be an https linkedin.com URL", retryable=False)
    return value


def target_url(args: argparse.Namespace) -> str:
    resource = args.resource
    if resource == "company":
        raw_company = clean_text(args.company)
        if raw_company.startswith("http"):
            raw_company = safe_linkedin_url(raw_company, "company")
            match = re.search(r"/company/([^/?#]+)", urllib.parse.urlparse(raw_company).path)
            raw_company = match.group(1) if match else ""
        slug = raw_company.strip("/").split("/")[-1]
        if not re.fullmatch(r"[A-Za-z0-9%._-]+", slug):
            raise FetchError("invalid_input", "company must be a LinkedIn company slug or URL", retryable=False)
        return f"{LINKEDIN}/company/{urllib.parse.quote(slug)}/about/"
    if resource == "job-detail":
        return safe_linkedin_url(args.job_url, "job-url")
    if resource == "people-search":
        return f"{LINKEDIN}/search/results/people/?{urllib.parse.urlencode({'keywords': args.keywords})}"
    if resource == "salesnav-search":
        return f"{LINKEDIN}/sales/search/people/?{urllib.parse.urlencode({'query': args.keywords})}"
    if resource == "salesnav-thread":
        value = args.thread_or_recipient
        return safe_linkedin_url(value, "thread-or-recipient") if value.startswith("http") else f"{LINKEDIN}/sales/inbox/"
    if resource == "search":
        params = {"keywords": args.query}
        if args.location:
            params["location"] = args.location
        return f"{LINKEDIN}/jobs/search/?{urllib.parse.urlencode(params)}"
    if resource == "thread-snapshot":
        return safe_linkedin_url(args.thread_url, "thread-url")
    if resource == "services-read" and args.services_url:
        return safe_linkedin_url(args.services_url, "services-url")
    if resource in {"posts", "post-analytics", "profile-analytics", "profile-experience", "profile-projects", "profile-read", "services-read"} and args.profile_url:
        return safe_linkedin_url(args.profile_url, "profile-url")
    paths = {
        "connections": "/mynetwork/invite-connect/connections/",
        "inbox": "/messaging/",
        "jobs-preferences": "/jobs/preferences/",
        "salesnav-inbox": "/sales/inbox/",
        "sent-invitations": "/mynetwork/invitation-manager/sent/",
        "timeline": "/feed/",
        "whoami": "/feed/",
    }
    return LINKEDIN + paths.get(resource, "/feed/")


def extract_visible_page(book: ActionBookSession, limit: int) -> dict[str, Any]:
    # ponytail: one DOM snapshot keeps the 21 read entrypoints usable; promote each resource to its own API/field parser when smoke evidence shows semantic gaps.
    data = evaluate(
        book,
        f"""(() => {{
          const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
          const body = clean(document.body?.innerText || '');
          const authRequired = /linkedin\\.com\\/(login|checkpoint|authwall|uas)/i.test(location.href)
            || /sign in|log in|join linkedin|captcha|verification required|请登录|登录领英/i.test(body.slice(0, 4000));
          const articles = [...document.querySelectorAll('main article, article')].slice(0, {limit}).map((node, index) => {{
            const text = clean(node.innerText || node.textContent || '');
            const link = node.querySelector('a[href]')?.href || '';
            return {{id: link || `${{location.href}}#article-${{index + 1}}`, title: text.slice(0, 240), url: link, text: text.slice(0, 4000)}};
          }}).filter((item) => item.text);
          return {{authRequired, url: location.href, title: document.title || '', headings: [...document.querySelectorAll('h1,h2,h3')].map((node) => clean(node.innerText)).filter(Boolean).slice(0, 30), bodyText: body.slice(0, 8000), articles}};
        }})()""",
        "LinkedIn visible page",
        timeout=30,
    )
    if not isinstance(data, dict):
        raise FetchError("schema_mismatch", "LinkedIn returned an unexpected page payload", retryable=False)
    if data.get("authRequired"):
        raise FetchError("needs_login", "LinkedIn requires an authenticated browser session", retryable=False)
    articles = data.get("articles") if isinstance(data.get("articles"), list) else []
    if articles:
        return {"records": articles, "page": data}
    if not any(data.get(key) for key in ("url", "title", "headings", "bodyText")):
        raise FetchError("field_gap", "LinkedIn page exposed no readable fields", retryable=False)
    return {"records": [{"id": data.get("url"), "title": clean_text(data.get("title")), "url": data.get("url"), "headings": data.get("headings", []), "text": data.get("bodyText", "")}], "page": data}


def load_resource(args: argparse.Namespace) -> ReadResult:
    try:
        book = attach_workflow(args, LINKEDIN, ActionBookSession)
    except ValueError as exc:
        raise FetchError("needs_user_action", str(exc), retryable=False) from exc
    except ActionBookFailure as exc:
        if not has_failure_code(exc, {"CHROME_URL_BLOCKED", "OWNED_TAB_NOT_FOUND", "OWNED_TAB_MISMATCH"}):
            raise
        raise FetchError("needs_user_action", str(exc), retryable=False) from exc
    url = target_url(args)
    book.goto(url)
    wait_until_stable(book, timeout_secs=12)
    limit = read_count(1 if args.resource == "whoami" else getattr(args, "limit", 20), maximum=100)
    extracted = extract_visible_page(book, limit)
    return ReadResult(extracted["records"][:limit])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LinkedIn read-only workflows")
    sub = parser.add_subparsers(dest="resource", required=True)
    for resource in READ_RESOURCES:
        command = sub.add_parser(resource)
        add_workflow_args(command)
        command.add_argument("--output", default="")
        if resource == "company":
            command.add_argument("--company", required=True)
        elif resource == "job-detail":
            command.add_argument("--job-url", required=True)
        elif resource in {"people-search", "salesnav-search"}:
            command.add_argument("--keywords", required=True)
        elif resource == "search":
            command.add_argument("--query", required=True)
            command.add_argument("--location", default="")
        elif resource == "salesnav-thread":
            command.add_argument("--thread-or-recipient", required=True)
        elif resource == "thread-snapshot":
            command.add_argument("--thread-url", required=True)
            command.add_argument("--max-scrolls", type=int, default=30)
            command.add_argument("--json", action="store_true")
        elif resource == "services-read":
            command.add_argument("--profile-url", default="")
            command.add_argument("--services-url", default="")
        elif resource in {"posts", "post-analytics", "profile-analytics", "profile-experience", "profile-projects", "profile-read"}:
            command.add_argument("--profile-url", default="")
        if resource in {"connections", "inbox", "people-search", "posts", "post-analytics", "salesnav-inbox", "salesnav-search", "salesnav-thread", "timeline"}:
            command.add_argument("--limit", type=int, default=20)
        if resource in {"inbox", "salesnav-inbox"}:
            command.add_argument("--unread-only", action="store_true")
        if resource in {"salesnav-inbox", "salesnav-thread"}:
            command.add_argument("--max-pages", type=int, default=30)
        if resource == "search":
            command.add_argument("--details", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    install_interrupt_handlers()
    args = build_parser().parse_args(argv)
    requested_count = 1 if args.resource == "whoami" else int(getattr(args, "limit", 20) or 20)
    return emit_read(args, site="linkedin", resource=args.resource, loader=lambda: load_resource(args), access="browser", strategy="dom", requested_count=requested_count, limits={"max_items": requested_count, "max_scrolls": int(getattr(args, "max_scrolls", 0) or 0), "timeout_seconds": 60})


if __name__ == "__main__":
    raise SystemExit(main())
