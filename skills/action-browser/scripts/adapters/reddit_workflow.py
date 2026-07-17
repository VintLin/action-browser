#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reddit read workflow based on opencli's same-origin JSON endpoints."""

from __future__ import annotations

import argparse
from html import unescape
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlencode

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[2]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from scripts.actionbook_interrupts import install_interrupt_handlers
from scripts.actionbook_session import ActionBookSession as ActionBook
from scripts.script_common import log
from scripts.owned_tab_lifecycle import add_workflow_args, attach_workflow
from scripts.workflow_runtime import evaluate, write_json


REDDIT_HOME_URL = "https://www.reddit.com"
# ponytail: read-only first; Reddit writes stay behind the shared write-safety gate.
SKILL_DIR = Path(__file__).resolve().parents[2]
ASSETS_DIR = SKILL_DIR / "assets" / "reddit"
POST_ID_RE = re.compile(r"^[a-z0-9]+$", re.I)
SUBREDDIT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,20}$")


def read_count(value: Any, default: int = 15, maximum: int = 100) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("count must be an integer") from exc
    if not 1 <= count <= maximum:
        raise ValueError(f"count must be between 1 and {maximum}")
    return count


def normalize_subreddit(value: str) -> str:
    name = str(value or "").strip()
    if name.startswith("/r/"):
        name = name[3:]
    elif name.startswith("r/"):
        name = name[2:]
    if not SUBREDDIT_RE.fullmatch(name):
        raise ValueError("subreddit must be 3-21 characters, start with a letter, and use only letters, digits, or _")
    return name


def normalize_username(value: str) -> str:
    name = str(value or "").strip()
    if name.startswith("u/"):
        name = name[2:]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
        raise ValueError("username must be a Reddit username, with an optional u/ prefix")
    return name


def normalize_post_id(value: str) -> str:
    raw = str(value or "").strip()
    fullname = re.fullmatch(r"t3_([a-z0-9]+)", raw, re.I)
    if fullname:
        return fullname.group(1).lower()
    match = re.search(r"/comments/([a-z0-9]+)(?:/|$)", raw, re.I)
    if match:
        return match.group(1).lower()
    if POST_ID_RE.fullmatch(raw):
        return raw.lower()
    raise ValueError("post must be a Reddit post id, t3_ fullname, or Reddit post URL")


def decode_reddit_html(value: Any) -> str:
    return unescape(str(value or ""))


def extract_media(data: dict[str, Any]) -> dict[str, Any]:
    gallery_urls: list[str] = []
    gallery_data = data.get("gallery_data") if isinstance(data.get("gallery_data"), dict) else {}
    items = gallery_data.get("items", [])
    metadata = data.get("media_metadata") if isinstance(data.get("media_metadata"), dict) else {}
    if isinstance(items, list) and isinstance(metadata, dict):
        for item in items:
            if not isinstance(item, dict):
                continue
            media = metadata.get(item.get("media_id"), {})
            source = media.get("s", {}) if isinstance(media, dict) else {}
            url = source.get("u") or source.get("gif") or source.get("mp4")
            if url:
                gallery_urls.append(decode_reddit_html(url))
    preview = data.get("preview") if isinstance(data.get("preview"), dict) else {}
    images = preview.get("images") if isinstance(preview.get("images"), list) else []
    source = images[0].get("source") if images and isinstance(images[0], dict) else {}
    source_url = source.get("url") if isinstance(source, dict) else ""
    return {
        "post_hint": str(data.get("post_hint") or ""),
        "url_overridden_by_dest": decode_reddit_html(data.get("url_overridden_by_dest")),
        "preview_image_url": decode_reddit_html(source_url),
        "gallery_urls": gallery_urls,
    }


def post_record(data: dict[str, Any], *, rank: int | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": str(data.get("id") or ""),
        "title": str(data.get("title") or ""),
        "subreddit": str(data.get("subreddit_name_prefixed") or ""),
        "author": str(data.get("author") or "[deleted]"),
        "score": data.get("score", 0),
        "comments": data.get("num_comments", 0),
        "url": f"{REDDIT_HOME_URL}{data.get('permalink')}" if data.get("permalink") else "",
        "created_utc": data.get("created_utc"),
        "selftext": str(data.get("selftext") or ""),
        **extract_media(data),
    }
    if rank is not None:
        record["rank"] = rank
    return record


def default_output_dir(source: str) -> Path:
    return ASSETS_DIR / "views" / source / datetime.now().strftime("%Y%m%d-%H%M%S")


def write_records(records: list[dict[str, Any]], output_dir: Path, title: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", records)
    lines = [f"# {title}", "", f"- 条目数: {len(records)}", ""]
    for index, item in enumerate(records, start=1):
        heading = item.get("title") or item.get("name") or item.get("field") or item.get("id") or str(index)
        lines.extend([f"## {index}. {heading}", ""])
        for key, value in item.items():
            if value in ("", None, [], {}):
                continue
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False)
            lines.append(f"- {key}: {value}")
        lines.append("")
    (output_dir / "summary.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    write_json(output_dir / "failures.json", [])


def fetch_json_js(path: str) -> str:
    return f"""
    (async () => {{
      try {{
        const response = await fetch({json.dumps(path)}, {{ credentials: 'include' }});
        const body = await response.text();
        let payload = null;
        try {{ payload = JSON.parse(body); }} catch (_) {{}}
        return {{ status: response.status, ok: response.ok, payload, body: body.slice(0, 300) }};
      }} catch (error) {{
        return {{ error: error?.message || String(error) }};
      }}
    }})()
    """


def reddit_json(book: ActionBook, path: str, label: str) -> Any:
    result = evaluate(book, fetch_json_js(path), label, timeout=30.0)
    if not isinstance(result, dict):
        raise RuntimeError(f"{label}: malformed browser response")
    if result.get("error"):
        raise RuntimeError(f"{label}: {result['error']}")
    if not result.get("ok"):
        status = result.get("status")
        if status in {401, 403}:
            raise RuntimeError(f"{label}: Reddit requires login or returned HTTP {status}")
        raise RuntimeError(f"{label}: Reddit returned HTTP {status}")
    payload = result.get("payload")
    if payload is None:
        raise RuntimeError(f"{label}: Reddit returned non-JSON content")
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(f"{label}: Reddit API error {payload.get('error')} ({payload.get('reason', 'unknown')})")
    return payload


def listing_children(payload: Any, label: str) -> list[dict[str, Any]]:
    children = payload.get("data", {}).get("children") if isinstance(payload, dict) else None
    if not isinstance(children, list):
        raise RuntimeError(f"{label}: Reddit response missing data.children")
    return [item for item in children if isinstance(item, dict) and isinstance(item.get("data"), dict)]


def identity_name(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    return str(data.get("name") or "") if isinstance(data, dict) else ""


def attach_reddit(args: argparse.Namespace) -> ActionBook:
    return attach_workflow(args, REDDIT_HOME_URL, ActionBook)


def run_listing(args: argparse.Namespace, path: str, title: str, *, require_login: bool = False, mode: str = "posts") -> int:
    count = read_count(args.count)
    book = attach_reddit(args)
    if require_login:
        me = reddit_json(book, "/api/me.json?raw_json=1", "reddit identity")
        if not identity_name(me):
            raise RuntimeError("reddit requires a logged-in account")
    payload = reddit_json(book, path, title)
    children = listing_children(payload, title)
    records: list[dict[str, Any]] = []
    for index, child in enumerate(children[:count], start=1):
        data = child["data"]
        if mode == "comments":
            body = str(data.get("body") or "")
            records.append({
                "subreddit": str(data.get("subreddit_name_prefixed") or ""),
                "score": data.get("score", 0),
                "body": body[:300] + ("..." if len(body) > 300 else ""),
                "url": f"{REDDIT_HOME_URL}{data.get('permalink')}" if data.get("permalink") else "",
            })
        else:
            record = post_record(data, rank=index)
            if mode in {"saved", "upvoted"} and not record["title"]:
                record["title"] = str(data.get("body") or "")[:100]
            records.append(record)
    output_dir = Path(args.output) if args.output else default_output_dir(args.command)
    write_records(records, output_dir, title)
    log(f"写入 {len(records)} 条 Reddit 结果: {output_dir}")
    return 0


def run_read(args: argparse.Namespace) -> int:
    post_id = normalize_post_id(args.post)
    limit = read_count(args.count, default=25, maximum=100)
    depth = read_count(args.depth, default=2, maximum=5)
    replies = read_count(args.replies, default=5, maximum=20)
    max_length = read_count(args.max_length, default=2000, maximum=10000)
    query = urlencode({"sort": args.sort, "limit": max(limit * 3, 100), "depth": depth + 1, "raw_json": 1})
    book = attach_reddit(args)
    payload = reddit_json(book, f"/comments/{post_id}.json?{query}", "reddit post")
    if not isinstance(payload, list) or len(payload) < 2:
        raise RuntimeError("reddit post: response must contain a post listing and a comment listing")
    posts = listing_children(payload[0], "reddit post")
    comments = listing_children(payload[1], "reddit comments")
    if not posts:
        raise RuntimeError(f"reddit post {post_id}: post was not found or is inaccessible")
    post = posts[0]["data"]
    records = [{"type": "post", **post_record(post)}]

    def walk(items: list[dict[str, Any]], level: int) -> None:
        shown = 0
        for item in items:
            max_items = limit if level == 1 else replies
            if shown >= max_items or item.get("kind") != "t1":
                continue
            data = item.get("data") or {}
            body = str(data.get("body") or "")
            records.append({
                "type": "comment",
                "depth": level,
                "author": str(data.get("author") or "[deleted]"),
                "score": data.get("score", 0),
                "text": body[:max_length] + ("..." if len(body) > max_length else ""),
                "url": f"{REDDIT_HOME_URL}{data.get('permalink')}" if data.get("permalink") else "",
            })
            shown += 1
            if level < depth:
                replies_data = data.get("replies") if isinstance(data.get("replies"), dict) else {}
                replies_listing = replies_data.get("data", {}).get("children", [])
                if isinstance(replies_listing, list):
                    walk([child for child in replies_listing if isinstance(child, dict)], level + 1)

    walk(comments, 1)
    output_dir = Path(args.output) if args.output else default_output_dir("read")
    write_records(records, output_dir, f"Reddit 帖子: {post.get('title') or post_id}")
    log(f"写入 Reddit 帖子及评论: {output_dir}")
    return 0


def field_records(values: list[tuple[str, Any]]) -> list[dict[str, str]]:
    return [{"field": key, "value": str(value if value not in (None, "") else "-")} for key, value in values]


def run_subreddit_info(args: argparse.Namespace) -> int:
    name = normalize_subreddit(args.name)
    book = attach_reddit(args)
    data = reddit_json(book, f"/r/{quote(name)}/about.json?raw_json=1", "reddit subreddit info").get("data", {})
    created = datetime.fromtimestamp(float(data["created_utc"])).date().isoformat() if data.get("created_utc") else "-"
    records = field_records([
        ("Name", data.get("display_name_prefixed") or f"r/{name}"),
        ("Title", data.get("title")),
        ("Subscribers", data.get("subscribers")),
        ("Active Now", data.get("active_user_count") or data.get("accounts_active")),
        ("NSFW", "Yes" if data.get("over18") else "No"),
        ("Type", data.get("subreddit_type")),
        ("Description", data.get("public_description")),
        ("Created", created),
        ("URL", f"{REDDIT_HOME_URL}{data.get('url')}" if data.get("url") else "-"),
    ])
    output_dir = Path(args.output) if args.output else default_output_dir("subreddit-info")
    write_records(records, output_dir, f"Reddit 版块: r/{name}")
    return 0


def run_user(args: argparse.Namespace) -> int:
    name = normalize_username(args.username)
    book = attach_reddit(args)
    data = reddit_json(book, f"/user/{quote(name)}/about.json?raw_json=1", "reddit user").get("data", {})
    link_karma = data.get("link_karma", 0) or 0
    comment_karma = data.get("comment_karma", 0) or 0
    created = datetime.fromtimestamp(float(data["created_utc"])).date().isoformat() if data.get("created_utc") else "-"
    records = field_records([
        ("Username", f"u/{data.get('name') or name}"),
        ("Post Karma", link_karma),
        ("Comment Karma", comment_karma),
        ("Total Karma", data.get("total_karma", link_karma + comment_karma)),
        ("Account Created", created),
        ("Gold", "Yes" if data.get("is_gold") else "No"),
        ("Verified", "Yes" if data.get("verified") else "No"),
    ])
    output_dir = Path(args.output) if args.output else default_output_dir("user")
    write_records(records, output_dir, f"Reddit 用户: u/{name}")
    return 0


def run_whoami(args: argparse.Namespace) -> int:
    book = attach_reddit(args)
    data = reddit_json(book, "/api/me.json?raw_json=1", "reddit identity")
    if not identity_name(data):
        raise RuntimeError("reddit is not logged in")
    data = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
    records = field_records([
        ("Username", f"u/{data.get('name')}"),
        ("ID", data.get("id")),
        ("Karma", data.get("total_karma")),
    ])
    output_dir = Path(args.output) if args.output else default_output_dir("whoami")
    write_records(records, output_dir, "Reddit 当前账号")
    return 0


def add_common(parser: argparse.ArgumentParser, default_count: int = 15) -> None:
    parser.add_argument("--count", type=int, default=default_count)
    parser.add_argument("--output", default="")
    add_workflow_args(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reddit workflow helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_listing(name: str, help_text: str, handler: Callable[[argparse.Namespace], int]) -> argparse.ArgumentParser:
        command = subparsers.add_parser(name, help=help_text)
        mode = command.add_subparsers(dest="mode", required=True)
        view = mode.add_parser("view", help=f"View Reddit {name}")
        add_common(view)
        view.set_defaults(func=handler)
        return view

    hot = add_listing("hot", "Hot posts", lambda args: run_listing(args, "/hot.json?limit=" + str(read_count(args.count)) + "&raw_json=1", "Reddit 热门帖子"))
    hot.add_argument("--subreddit", default="")
    hot.set_defaults(func=lambda args: run_listing(
        args,
        (f"/r/{quote(normalize_subreddit(args.subreddit))}/hot.json" if args.subreddit else "/hot.json")
        + f"?limit={read_count(args.count)}&raw_json=1",
        "Reddit 热门帖子",
    ))

    add_listing("frontpage", "Frontpage / r/all", lambda args: run_listing(args, f"/r/all.json?limit={read_count(args.count)}&raw_json=1", "Reddit Frontpage"))
    add_listing("popular", "Popular posts", lambda args: run_listing(args, f"/r/popular.json?limit={read_count(args.count)}&raw_json=1", "Reddit Popular"))
    add_listing("home", "Personalized Best feed", lambda args: run_listing(args, f"/best.json?limit={read_count(args.count)}&raw_json=1", "Reddit Home", require_login=True))

    search = subparsers.add_parser("search", help="Search posts")
    search_mode = search.add_subparsers(dest="mode", required=True)
    search_view = search_mode.add_parser("view")
    search_view.add_argument("--query", required=True)
    search_view.add_argument("--subreddit", default="")
    search_view.add_argument("--sort", choices=("relevance", "hot", "top", "new", "comments"), default="relevance")
    search_view.add_argument("--time", choices=("hour", "day", "week", "month", "year", "all"), default="all")
    add_common(search_view)
    search_view.set_defaults(func=lambda args: run_listing(
        args,
        ((f"/r/{quote(normalize_subreddit(args.subreddit))}/search.json" if args.subreddit else "/search.json") + "?" + urlencode({"q": args.query, "sort": args.sort, "t": args.time, "limit": read_count(args.count), "restrict_sr": "on" if args.subreddit else "off", "raw_json": 1})),
        f"Reddit 搜索: {args.query}",
    ))

    subreddit = subparsers.add_parser("subreddit", help="Subreddit posts")
    subreddit_mode = subreddit.add_subparsers(dest="mode", required=True)
    subreddit_view = subreddit_mode.add_parser("view")
    subreddit_view.add_argument("--name", required=True)
    subreddit_view.add_argument("--sort", choices=("hot", "new", "top", "rising", "controversial"), default="hot")
    subreddit_view.add_argument("--time", choices=("hour", "day", "week", "month", "year", "all"), default="all")
    add_common(subreddit_view)
    subreddit_view.set_defaults(func=lambda args: run_listing(
        args,
        f"/r/{quote(normalize_subreddit(args.name))}/{args.sort}.json?" + urlencode({"t": args.time, "limit": read_count(args.count), "raw_json": 1}),
        f"Reddit 版块: r/{args.name}",
    ))

    for name, mode, title in (("user-posts", "posts", "Reddit 用户帖子"), ("user-comments", "comments", "Reddit 用户评论")):
        command = subparsers.add_parser(name, help=title)
        command_mode = command.add_subparsers(dest="mode", required=True)
        view = command_mode.add_parser("view")
        view.add_argument("--username", required=True)
        add_common(view)
        endpoint = "submitted.json" if mode == "posts" else "comments.json"
        view.set_defaults(func=lambda args, endpoint=endpoint, mode=mode, title=title: run_listing(
            args, f"/user/{quote(normalize_username(args.username))}/{endpoint}?limit={read_count(args.count)}&raw_json=1", title, mode=mode,
        ))

    for name, endpoint, title in (("saved", "saved.json", "Reddit 已保存"), ("upvoted", "upvoted.json", "Reddit 已点赞")):
        command = subparsers.add_parser(name, help=title)
        command_mode = command.add_subparsers(dest="mode", required=True)
        view = command_mode.add_parser("view")
        add_common(view)
        view.set_defaults(func=lambda args, endpoint=endpoint, title=title, mode=name: run_saved_or_upvoted(args, endpoint, title, mode))

    subscribed = subparsers.add_parser("subscribed", help="Subscribed subreddits")
    subscribed_mode = subscribed.add_subparsers(dest="mode", required=True)
    subscribed_view = subscribed_mode.add_parser("view")
    add_common(subscribed_view, default_count=100)
    subscribed_view.set_defaults(func=lambda args: run_saved_or_upvoted(args, "subreddits/mine/subscriptions.json", "Reddit 已订阅版块", "subscriptions"))

    read = subparsers.add_parser("read", help="Read a post and comments")
    read_mode = read.add_subparsers(dest="mode", required=True)
    read_view = read_mode.add_parser("view")
    read_view.add_argument("--post", required=True)
    read_view.add_argument("--sort", choices=("best", "top", "new", "controversial", "old", "qa"), default="best")
    read_view.add_argument("--depth", type=int, default=2)
    read_view.add_argument("--replies", type=int, default=5)
    read_view.add_argument("--max-length", dest="max_length", type=int, default=2000)
    add_common(read_view, default_count=25)
    read_view.set_defaults(func=run_read)

    subreddit_info = subparsers.add_parser("subreddit-info", help="Subreddit metadata")
    subreddit_info_mode = subreddit_info.add_subparsers(dest="mode", required=True)
    subreddit_info_view = subreddit_info_mode.add_parser("view")
    subreddit_info_view.add_argument("--name", required=True)
    subreddit_info_view.add_argument("--output", default="")
    add_workflow_args(subreddit_info_view)
    subreddit_info_view.set_defaults(func=run_subreddit_info)

    user = subparsers.add_parser("user", help="User profile")
    user_mode = user.add_subparsers(dest="mode", required=True)
    user_view = user_mode.add_parser("view")
    user_view.add_argument("--username", required=True)
    user_view.add_argument("--output", default="")
    add_workflow_args(user_view)
    user_view.set_defaults(func=run_user)

    whoami = subparsers.add_parser("whoami", help="Current logged-in user")
    whoami_mode = whoami.add_subparsers(dest="mode", required=True)
    whoami_view = whoami_mode.add_parser("view")
    whoami_view.add_argument("--output", default="")
    add_workflow_args(whoami_view)
    whoami_view.set_defaults(func=run_whoami)
    return parser


def run_saved_or_upvoted(args: argparse.Namespace, endpoint: str, title: str, mode: str) -> int:
    me_book = attach_reddit(args)
    me = reddit_json(me_book, "/api/me.json?raw_json=1", "reddit identity")
    username = identity_name(me)
    if not username:
        raise RuntimeError("reddit requires a logged-in account")
    path = f"/user/{quote(username)}/{endpoint}?limit={read_count(args.count)}&raw_json=1" if mode != "subscriptions" else f"/{endpoint}?limit={read_count(args.count, maximum=1000)}&raw_json=1"
    payload = reddit_json(me_book, path, title)
    children = listing_children(payload, title)
    records = [post_record(child["data"], rank=index) for index, child in enumerate(children[:read_count(args.count)], start=1)] if mode != "subscriptions" else [
        {
            "id": str(child["data"].get("name") or child["data"].get("id") or ""),
            "subreddit": str(child["data"].get("display_name_prefixed") or ""),
            "title": str(child["data"].get("title") or ""),
            "subscribers": child["data"].get("subscribers"),
            "description": str(child["data"].get("public_description") or "")[:200],
            "url": f"{REDDIT_HOME_URL}{child['data'].get('url')}" if child["data"].get("url") else "",
        }
        for child in children[:read_count(args.count, maximum=1000)]
    ]
    output_dir = Path(args.output) if args.output else default_output_dir(mode)
    write_records(records, output_dir, title)
    return 0


def main() -> int:
    install_interrupt_handlers()
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
