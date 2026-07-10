#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zhihu workflow helper for the action-browser skill.

The workflow uses ActionBook extension mode and the user's existing Chrome
session. It covers read-only Zhihu hot, recommend, search, question answers,
single answer detail, favorite collections, collection items, and article
Markdown export.
"""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[2]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
from typing import Any

from scripts.actionbook_interrupts import install_interrupt_handlers
from scripts.workflow_runtime import add_workflow_args, attach_workflow, evaluate, wait_until_stable, write_json
from scripts.actionbook_session import ActionBookSession as ActionBook
from scripts.script_common import log


ZHIHU_HOME_URL = "https://www.zhihu.com"
ZHIHU_ZHUANLAN_URL = "https://zhuanlan.zhihu.com"
SKILL_DIR = Path(__file__).resolve().parents[2]
ASSETS_DIR = SKILL_DIR / "assets" / "zhihu"


def sanitize_name(value: str, fallback: str = "item", max_length: int = 80) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "", value or "").strip("._-")
    return (cleaned or fallback)[:max_length]


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def strip_html(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"<br\s*/?\s*>", "\n", text, flags=re.I)
    text = re.sub(r"</(?:p|div|h[1-6]|li|blockquote)>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def read_count(value: Any, default: int = 20, max_value: int = 1000) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = default
    return max(1, min(count, max_value))


def default_action_output_dir(source: str, action: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    action_dir = "downloads" if action == "download" else "views"
    return ASSETS_DIR / action_dir / source / stamp


def get_page_state(book: ActionBook) -> dict[str, str]:
    value = evaluate(book, """
    (() => ({
      href: location.href,
      title: document.title || '',
      text: (document.body?.innerText || '').slice(0, 1000)
    }))()
    """, "zhihu page state", timeout=10.0)
    return value if isinstance(value, dict) else {}


def page_has_login_or_risk(state: dict[str, str]) -> bool:
    href = str(state.get("href") or "")
    title = str(state.get("title") or "")
    text = str(state.get("text") or "")
    haystack = "\n".join([href, title, text])
    return bool(re.search(r"signin|login|安全验证|验证码|请验证|异常流量|unhuman|captcha", haystack, re.I))


def ensure_zhihu_ready(book: ActionBook) -> None:
    state = get_page_state(book)
    if page_has_login_or_risk(state):
        raise RuntimeError(f"Zhihu requires login or verification: {state.get('href')} title={state.get('title')}")



def write_records(records: list[dict[str, Any]], output_dir: Path, title: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", records)
    lines = [f"# {title}", "", f"- 条目数: {len(records)}", ""]
    for index, item in enumerate(records, start=1):
        heading = item.get("title") or item.get("question_title") or item.get("author") or item.get("id") or str(index)
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


def parse_question_id(value: str) -> str:
    raw = str(value or "").strip()
    match = re.search(r"(?:question:|/question/)(\d+)", raw)
    if match:
        return match.group(1)
    if re.fullmatch(r"\d+", raw):
        return raw
    raise ValueError("Question ID must be numeric, question:<id>, or a Zhihu question URL")


def parse_answer_target(value: str) -> dict[str, str]:
    raw = str(value or "").strip()
    if re.fullmatch(r"\d+", raw):
        return {"question_id": "", "answer_id": raw, "url": f"{ZHIHU_HOME_URL}/answer/{raw}"}
    match = re.fullmatch(r"answer:(\d+):(\d+)", raw)
    if match:
        qid, aid = match.groups()
        return {"question_id": qid, "answer_id": aid, "url": f"{ZHIHU_HOME_URL}/question/{qid}/answer/{aid}"}
    try:
        url = urllib.parse.urlparse(raw)
    except Exception:
        url = None
    if url and url.scheme == "https" and url.hostname in {"www.zhihu.com", "zhihu.com"}:
        match = re.fullmatch(r"/question/(\d+)/answer/(\d+)/?", url.path)
        if match:
            qid, aid = match.groups()
            return {"question_id": qid, "answer_id": aid, "url": f"{ZHIHU_HOME_URL}/question/{qid}/answer/{aid}"}
        match = re.fullmatch(r"/answer/(\d+)/?", url.path)
        if match:
            aid = match.group(1)
            return {"question_id": "", "answer_id": aid, "url": f"{ZHIHU_HOME_URL}/answer/{aid}"}
    raise ValueError("Answer target must be an answer ID, answer:<questionId>:<answerId>, or a Zhihu answer URL")


def parse_article_url(value: str) -> str:
    raw = str(value or "").strip()
    if re.fullmatch(r"article:\d+", raw):
        return f"{ZHIHU_ZHUANLAN_URL}/p/{raw.split(':', 1)[1]}"
    try:
        url = urllib.parse.urlparse(raw)
    except Exception:
        url = None
    if url and url.scheme == "https" and url.hostname == "zhuanlan.zhihu.com":
        match = re.fullmatch(r"/p/(\d+)/?", url.path)
        if match:
            return f"{ZHIHU_ZHUANLAN_URL}/p/{match.group(1)}"
    raise ValueError("Article URL must be https://zhuanlan.zhihu.com/p/<id> or article:<id>")


def canonical_zhihu_url(value: str) -> str:
    raw = str(value or "")
    if raw.startswith("//"):
        return "https:" + raw
    if raw.startswith("/"):
        return urllib.parse.urljoin(ZHIHU_HOME_URL, raw)
    return raw


def fetch_json_js(url: str) -> str:
    return f"""
    (async () => {{
      try {{
        const response = await fetch({json.dumps(url)}, {{ credentials: 'include' }});
        const text = await response.text();
        if (!response.ok) return {{ __httpError: response.status, __body: text.slice(0, 300) }};
        return JSON.parse(text.replace(/("id"\\s*:\\s*)(\\d{{16,}})/g, '$1"$2"'));
      }} catch (error) {{
        return {{ __fetchError: error?.message || String(error) }};
      }}
    }})()
    """


def require_api_payload(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{label}: malformed payload")
    if value.get("__httpError"):
        raise RuntimeError(f"{label}: HTTP {value.get('__httpError')}")
    if value.get("__fetchError"):
        raise RuntimeError(f"{label}: {value.get('__fetchError')}")
    return value


def item_url(obj: dict[str, Any]) -> str:
    item_type = str(obj.get("type") or "")
    item_id = str(obj.get("id") or "")
    if item_type == "answer":
        question = obj.get("question") if isinstance(obj.get("question"), dict) else {}
        qid = str(question.get("id") or "")
        return f"{ZHIHU_HOME_URL}/question/{qid}/answer/{item_id}" if qid and item_id else ""
    if item_type == "article":
        raw_url = str(obj.get("url") or "")
        if item_id and (not raw_url or "api.zhihu.com/articles/" in raw_url):
            return f"{ZHIHU_ZHUANLAN_URL}/p/{item_id}"
        return raw_url
    if item_type == "question":
        return f"{ZHIHU_HOME_URL}/question/{item_id}" if item_id else ""
    if item_type == "pin":
        return str(obj.get("url") or f"{ZHIHU_HOME_URL}/pin/{item_id}" if item_id else "")
    return ""


def normalize_feed_item(item: dict[str, Any], rank: int) -> dict[str, Any] | None:
    target = item.get("target") if isinstance(item.get("target"), dict) else {}
    item_type = str(target.get("type") or item.get("type") or "")
    title = ""
    if item_type == "answer":
        question = target.get("question") if isinstance(target.get("question"), dict) else {}
        title = normalize_text(question.get("title") or question.get("name") or "")
    else:
        title = normalize_text(target.get("title") or "")
    url = item_url(target)
    if not title and not url:
        return None
    author = target.get("author") if isinstance(target.get("author"), dict) else {}
    reaction = target.get("reaction") if isinstance(target.get("reaction"), dict) else {}
    stats = reaction.get("statistics") if isinstance(reaction.get("statistics"), dict) else {}
    return {
        "rank": rank,
        "type": item_type,
        "title": title,
        "author": str(author.get("name") or ""),
        "votes": target.get("voteup_count") or stats.get("like_count") or 0,
        "url": url,
    }


def run_hot(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=100)
    output_dir = Path(args.output) if args.output else default_action_output_dir("hot", "view")
    book = attach_workflow(args, ZHIHU_HOME_URL, ActionBook)
    book.goto(ZHIHU_HOME_URL)
    wait_until_stable(book)
    ensure_zhihu_ready(book)
    data = require_api_payload(evaluate(
        book,
        fetch_json_js(f"{ZHIHU_HOME_URL}/api/v3/feed/topstory/hot-lists/total?limit={max(count, 50)}"),
        "zhihu hot",
        timeout=30.0,
    ), "zhihu hot")
    rows = []
    for item in data.get("data") or []:
        target = item.get("target") if isinstance(item, dict) and isinstance(item.get("target"), dict) else {}
        question_id = str(target.get("id") or "")
        title = normalize_text(target.get("title"))
        if not question_id or not title:
            continue
        rows.append({
            "rank": len(rows) + 1,
            "id": question_id,
            "title": title,
            "heat": str(item.get("detail_text") or ""),
            "answer_count": target.get("answer_count") or 0,
            "follower_count": target.get("follower_count") or 0,
            "url": f"{ZHIHU_HOME_URL}/question/{question_id}",
        })
        if len(rows) >= count:
            break
    write_records(rows, output_dir, "知乎热榜")
    log(f"写入 {len(rows)} 条热榜结果: {output_dir}")
    return 0


def run_recommend(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=1000)
    output_dir = Path(args.output) if args.output else default_action_output_dir("recommend", "view")
    book = attach_workflow(args, ZHIHU_HOME_URL, ActionBook)
    book.goto(ZHIHU_HOME_URL)
    wait_until_stable(book)
    ensure_zhihu_ready(book)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    visited: set[str] = set()
    url = f"{ZHIHU_HOME_URL}/api/v3/feed/topstory/recommend?limit=10&desktop=true"
    while url and len(rows) < count and url not in visited:
        visited.add(url)
        data = require_api_payload(evaluate(book, fetch_json_js(url), "zhihu recommend", timeout=30.0), "zhihu recommend")
        for item in data.get("data") or []:
            if not isinstance(item, dict):
                continue
            target = item.get("target") if isinstance(item.get("target"), dict) else {}
            key = f"{target.get('type') or item.get('type') or ''}:{target.get('id') or item.get('id') or ''}"
            if key != ":" and key in seen:
                continue
            if key != ":":
                seen.add(key)
            row = normalize_feed_item(item, len(rows) + 1)
            if row:
                rows.append(row)
            if len(rows) >= count:
                break
        paging = data.get("paging") if isinstance(data.get("paging"), dict) else {}
        if paging.get("is_end"):
            break
        url = str(paging.get("next") or "")
    write_records(rows, output_dir, "知乎首页推荐")
    log(f"写入 {len(rows)} 条推荐结果: {output_dir}")
    return 0


def normalize_search_result(item: dict[str, Any], rank: int) -> dict[str, Any] | None:
    if item.get("type") != "search_result" or not isinstance(item.get("object"), dict):
        return None
    obj = item["object"]
    obj_type = str(obj.get("type") or "")
    if obj_type not in {"answer", "article", "question"}:
        return None
    question = obj.get("question") if isinstance(obj.get("question"), dict) else {}
    title = strip_html(str(obj.get("title") or question.get("name") or question.get("title") or ""))
    url = item_url(obj)
    if not title or not url:
        return None
    author = obj.get("author") if isinstance(obj.get("author"), dict) else {}
    return {
        "rank": rank,
        "type": obj_type,
        "title": title,
        "author": str(author.get("name") or ""),
        "votes": obj.get("voteup_count") or 0,
        "url": url,
    }


def normalize_search_next(value: str) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    try:
        parsed = urllib.parse.urlparse(raw)
    except Exception:
        return ""
    if parsed.hostname == "api.zhihu.com" and parsed.path == "/search_v3":
        return urllib.parse.urlunparse(("https", "www.zhihu.com", "/api/v4/search_v3", "", parsed.query, ""))
    if parsed.hostname == "www.zhihu.com" and parsed.path == "/api/v4/search_v3":
        return raw
    return ""


def run_search(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=10, max_value=1000)
    output_dir = Path(args.output) if args.output else default_action_output_dir("search", "view")
    book = attach_workflow(args, ZHIHU_HOME_URL, ActionBook)
    book.goto(ZHIHU_HOME_URL)
    wait_until_stable(book)
    ensure_zhihu_ready(book)
    query = normalize_text(args.query)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    visited: set[str] = set()
    url = f"{ZHIHU_HOME_URL}/api/v4/search_v3?q={urllib.parse.quote(query)}&t=general&offset=0&limit=20"
    while url and len(rows) < count and url not in visited:
        visited.add(url)
        data = require_api_payload(evaluate(book, fetch_json_js(url), "zhihu search", timeout=30.0), "zhihu search")
        for item in data.get("data") or []:
            if not isinstance(item, dict):
                continue
            obj = item.get("object") if isinstance(item.get("object"), dict) else {}
            if args.type != "all" and obj.get("type") != args.type:
                continue
            key = f"{obj.get('type') or ''}:{obj.get('id') or item_url(obj)}"
            if key in seen:
                continue
            row = normalize_search_result(item, len(rows) + 1)
            if not row:
                continue
            if args.type != "all" and row["type"] != args.type:
                continue
            seen.add(key)
            rows.append(row)
            if len(rows) >= count:
                break
        paging = data.get("paging") if isinstance(data.get("paging"), dict) else {}
        if paging.get("is_end"):
            break
        url = normalize_search_next(str(paging.get("next") or ""))
    write_records(rows, output_dir, f"知乎搜索: {query}")
    log(f"写入 {len(rows)} 条搜索结果: {output_dir}")
    return 0


def run_question(args: argparse.Namespace) -> int:
    question_id = parse_question_id(args.id)
    count = read_count(args.count, default=5, max_value=1000)
    max_content = max(0, int(args.max_content or 200))
    sort = "created" if args.sort == "created" else "default"
    output_dir = Path(args.output) if args.output else default_action_output_dir("question", "view")
    page_url = f"{ZHIHU_HOME_URL}/question/{question_id}/answers/updated" if sort == "created" else f"{ZHIHU_HOME_URL}/question/{question_id}"
    book = attach_workflow(args, page_url, ActionBook)
    book.goto(page_url)
    wait_until_stable(book)
    ensure_zhihu_ready(book)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    visited: set[str] = set()
    url = f"{ZHIHU_HOME_URL}/api/v4/questions/{question_id}/answers?limit=20&offset=0&sort_by={sort}&include=data%5B*%5D.content,voteup_count,comment_count,author,created_time,updated_time"
    question_title = normalize_text(evaluate(book, """
    (() => document.querySelector('h1.QuestionHeader-title, .QuestionHeader-title')?.textContent || document.title || '')()
    """, "zhihu question title", timeout=10.0))
    while url and len(rows) < count and url not in visited:
        visited.add(url)
        data = require_api_payload(evaluate(book, fetch_json_js(url), "zhihu question", timeout=30.0), "zhihu question")
        for item in data.get("data") or []:
            if not isinstance(item, dict):
                continue
            answer_id = str(item.get("id") or "")
            author = item.get("author") if isinstance(item.get("author"), dict) else {}
            key = answer_id or f"{author.get('name') or 'anonymous'}:{item.get('content') or ''}"
            if key in seen:
                continue
            seen.add(key)
            content = strip_html(str(item.get("content") or ""))
            if max_content > 0:
                content = content[:max_content]
            rows.append({
                "rank": len(rows) + 1,
                "id": answer_id,
                "question_id": question_id,
                "question_title": question_title,
                "author": str(author.get("name") or "anonymous"),
                "votes": item.get("voteup_count") or 0,
                "comments": item.get("comment_count") or 0,
                "created_at": unix_to_iso(item.get("created_time")),
                "updated_at": unix_to_iso(item.get("updated_time")),
                "url": f"{ZHIHU_HOME_URL}/question/{question_id}/answer/{answer_id}" if answer_id else page_url,
                "content": content,
            })
            if len(rows) >= count:
                break
        paging = data.get("paging") if isinstance(data.get("paging"), dict) else {}
        if paging.get("is_end"):
            break
        url = str(paging.get("next") or "")
    write_records(rows, output_dir, f"知乎问题回答: {question_title or question_id}")
    log(f"写入 {len(rows)} 条回答: {output_dir}")
    return 0


def unix_to_iso(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ""
    if number <= 0:
        return ""
    return datetime.fromtimestamp(number).isoformat()


def run_answer_detail(args: argparse.Namespace) -> int:
    target = parse_answer_target(args.id)
    max_content = max(0, int(args.max_content or 0))
    output_dir = Path(args.output) if args.output else default_action_output_dir("answer-detail", "view")
    book = attach_workflow(args, target["url"], ActionBook)
    book.goto(target["url"])
    wait_until_stable(book)
    ensure_zhihu_ready(book)
    current_url = str(book.browser("url", timeout=10.0) or "")
    current_qid = (re.search(r"/question/(\d+)/answer/", current_url) or [None, ""])[1]
    answer_id = target["answer_id"]
    api_url = f"{ZHIHU_HOME_URL}/api/v4/answers/{answer_id}?include=content,voteup_count,comment_count,author,created_time,updated_time,question"
    data = require_api_payload(evaluate(book, fetch_json_js(api_url), "zhihu answer-detail", timeout=30.0), "zhihu answer-detail")
    question = data.get("question") if isinstance(data.get("question"), dict) else {}
    qid = target["question_id"] or current_qid or str(question.get("id") or "")
    content = strip_html(str(data.get("content") or ""))
    if max_content > 0:
        content = content[:max_content]
    author = data.get("author") if isinstance(data.get("author"), dict) else {}
    row = {
        "id": answer_id,
        "author": str(author.get("name") or ""),
        "votes": data.get("voteup_count") or 0,
        "comments": data.get("comment_count") or 0,
        "question_id": qid,
        "question_title": normalize_text(question.get("title") or ""),
        "url": f"{ZHIHU_HOME_URL}/question/{qid}/answer/{answer_id}" if qid else f"{ZHIHU_HOME_URL}/answer/{answer_id}",
        "created_at": unix_to_iso(data.get("created_time")),
        "updated_at": unix_to_iso(data.get("updated_time")),
        "content": content,
    }
    write_records([row], output_dir, f"知乎回答详情: {row['question_title'] or answer_id}")
    log(f"写入回答详情: {output_dir}")
    return 0


def get_me_url_token(book: ActionBook) -> str:
    data = require_api_payload(evaluate(
        book,
        fetch_json_js(f"{ZHIHU_HOME_URL}/api/v4/me?include=url_token"),
        "zhihu me",
        timeout=20.0,
    ), "zhihu me")
    token = str(data.get("url_token") or "")
    if not token:
        raise RuntimeError("Could not resolve current Zhihu user url_token; login may be required")
    return token


def run_collections(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=200)
    output_dir = Path(args.output) if args.output else default_action_output_dir("collections", "view")
    book = attach_workflow(args, ZHIHU_HOME_URL, ActionBook)
    book.goto(ZHIHU_HOME_URL)
    wait_until_stable(book)
    ensure_zhihu_ready(book)
    url_token = get_me_url_token(book)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    offset = 0
    while len(rows) < count:
        page_limit = min(20, count - len(rows))
        url = f"{ZHIHU_HOME_URL}/api/v4/people/{urllib.parse.quote(url_token)}/collections?include=data%5B*%5D.updated_time&offset={offset}&limit={page_limit}"
        data = require_api_payload(evaluate(book, fetch_json_js(url), "zhihu collections", timeout=30.0), "zhihu collections")
        items = data.get("data") if isinstance(data.get("data"), list) else []
        if not items:
            break
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get("id") or item.get("url") or item.get("title") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            rows.append({
                "rank": len(rows) + 1,
                "title": str(item.get("title") or "未命名"),
                "item_count": item.get("item_count") or item.get("answer_count") or 0,
                "description": strip_html(str(item.get("description") or "")),
                "collection_id": str(item.get("id") or ""),
            })
            if len(rows) >= count:
                break
        paging = data.get("paging") if isinstance(data.get("paging"), dict) else {}
        if paging.get("is_end") or len(items) < page_limit:
            break
        next_url = str(paging.get("next") or "")
        parsed = urllib.parse.urlparse(next_url)
        next_offset = urllib.parse.parse_qs(parsed.query).get("offset", [""])[0]
        if next_offset.isdigit() and int(next_offset) > offset:
            offset = int(next_offset)
        else:
            offset += len(items)
    write_records(rows, output_dir, f"知乎收藏夹列表: {url_token}")
    log(f"写入 {len(rows)} 个收藏夹: {output_dir}")
    return 0


def normalize_collection_item(item: dict[str, Any], rank: int) -> dict[str, Any] | None:
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    item_type = str(content.get("type") or "")
    if item_type not in {"answer", "article", "pin"}:
        return None
    title = ""
    excerpt = ""
    url = ""
    author = content.get("author") if isinstance(content.get("author"), dict) else {}
    votes = 0
    if item_type == "answer":
        question = content.get("question") if isinstance(content.get("question"), dict) else {}
        title = normalize_text(question.get("title") or "")
        excerpt = strip_html(str(content.get("content") or ""))[:300]
        url = str(content.get("url") or item_url(content))
        votes = content.get("voteup_count") or 0
    elif item_type == "article":
        title = normalize_text(content.get("title"))
        excerpt = strip_html(str(content.get("content") or ""))[:300]
        url = str(content.get("url") or item_url(content))
        votes = content.get("voteup_count") or 0
    else:
        title = "想法"
        parts = content.get("content") if isinstance(content.get("content"), list) else []
        excerpt = strip_html(" ".join(str(part.get("content") or "") for part in parts if isinstance(part, dict)))[:300]
        url = str(content.get("url") or item_url(content))
        votes = content.get("reaction_count") or 0
    if not title or not url:
        return None
    return {
        "rank": rank,
        "type": item_type,
        "title": title[:120],
        "author": str(author.get("name") or "匿名用户"),
        "votes": votes,
        "excerpt": excerpt,
        "url": canonical_zhihu_url(url),
    }


def run_collection(args: argparse.Namespace) -> int:
    if not re.fullmatch(r"\d+", str(args.id or "")):
        raise ValueError("Collection ID must be numeric")
    count = read_count(args.count, default=20, max_value=200)
    offset = max(0, int(args.offset or 0))
    output_dir = Path(args.output) if args.output else default_action_output_dir("collection", "view")
    book = attach_workflow(args, ZHIHU_HOME_URL, ActionBook)
    book.goto(ZHIHU_HOME_URL)
    wait_until_stable(book)
    ensure_zhihu_ready(book)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    next_offset = offset
    while len(rows) < count:
        page_limit = min(20, count - len(rows))
        url = f"{ZHIHU_HOME_URL}/api/v4/collections/{args.id}/items?offset={next_offset}&limit={page_limit}"
        data = require_api_payload(evaluate(book, fetch_json_js(url), "zhihu collection", timeout=30.0), "zhihu collection")
        items = data.get("data") if isinstance(data.get("data"), list) else []
        if not items:
            break
        for item in items:
            if not isinstance(item, dict):
                continue
            content = item.get("content") if isinstance(item.get("content"), dict) else {}
            key = f"{content.get('type') or ''}:{content.get('id') or content.get('url') or ''}"
            if key in seen:
                continue
            row = normalize_collection_item(item, offset + len(rows) + 1)
            if not row:
                continue
            seen.add(key)
            rows.append(row)
            if len(rows) >= count:
                break
        paging = data.get("paging") if isinstance(data.get("paging"), dict) else {}
        if paging.get("is_end") or len(items) < page_limit:
            break
        next_url = str(paging.get("next") or "")
        parsed = urllib.parse.urlparse(next_url)
        parsed_offset = urllib.parse.parse_qs(parsed.query).get("offset", [""])[0]
        if parsed_offset.isdigit() and int(parsed_offset) > next_offset:
            next_offset = int(parsed_offset)
        else:
            next_offset += len(items)
    write_records(rows, output_dir, f"知乎收藏夹内容: {args.id}")
    log(f"写入 {len(rows)} 条收藏夹内容: {output_dir}")
    return 0


def markdown_from_article(data: dict[str, Any], image_map: dict[str, str] | None = None) -> str:
    image_map = image_map or {}
    title = normalize_text(data.get("title")) or "untitled"
    author = normalize_text(data.get("author"))
    publish_time = normalize_text(data.get("publishTime"))
    source_url = str(data.get("sourceUrl") or "")
    content = str(data.get("contentHtml") or "")
    content = re.sub(r"<h1[^>]*>(.*?)</h1>", r"\n# \1\n", content, flags=re.I | re.S)
    content = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1\n", content, flags=re.I | re.S)
    content = re.sub(r"<h3[^>]*>(.*?)</h3>", r"\n### \1\n", content, flags=re.I | re.S)
    content = re.sub(r"<blockquote[^>]*>(.*?)</blockquote>", lambda m: "\n> " + strip_html(m.group(1)).replace("\n", "\n> ") + "\n", content, flags=re.I | re.S)
    content = re.sub(r"<li[^>]*>(.*?)</li>", lambda m: "\n- " + strip_html(m.group(1)), content, flags=re.I | re.S)
    def image_repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        src = ""
        alt = ""
        src_match = re.search(r'(?:data-original|data-actualsrc|src)=["\']([^"\']+)["\']', tag, flags=re.I)
        alt_match = re.search(r'alt=["\']([^"\']*)["\']', tag, flags=re.I)
        if src_match:
            src = html.unescape(src_match.group(1))
        if alt_match:
            alt = html.unescape(alt_match.group(1))
        target = image_map.get(src) or src
        return f"\n![{alt}]({target})\n" if target else ""
    content = re.sub(r"<img\b[^>]*>", image_repl, content, flags=re.I)
    content = re.sub(r"</(?:p|div)>", "\n\n", content, flags=re.I)
    content = re.sub(r"<br\s*/?\s*>", "\n", content, flags=re.I)
    content = re.sub(r"<[^>]+>", "", content)
    content = html.unescape(content)
    content = re.sub(r"[ \t]+\n", "\n", content)
    content = re.sub(r"\n{3,}", "\n\n", content).strip()
    lines = [f"# {title}", ""]
    if author:
        lines.append(f"- 作者: {author}")
    if publish_time:
        lines.append(f"- 发布时间: {publish_time}")
    if source_url:
        lines.append(f"- 来源: {source_url}")
    lines.extend(["", content, ""])
    return "\n".join(lines).strip() + "\n"


def media_extension(url: str, content_type: str = "") -> str:
    try:
        suffix = Path(urllib.parse.urlparse(url).path).suffix
    except Exception:
        suffix = ""
    if suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp"}:
        return suffix
    guessed = mimetypes.guess_extension(content_type.split(";")[0].strip()) if content_type else ""
    return guessed or ".jpg"


def download_file(url: str, dest_base: Path, referer: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": referer})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read()
            ext = media_extension(url, response.headers.get("Content-Type", ""))
            dest = dest_base.with_suffix(ext)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            return {"status": "success", "path": str(dest), "size": len(content), "error": ""}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"status": "failed", "path": "", "size": 0, "error": str(exc)}


def run_download(args: argparse.Namespace) -> int:
    article_url = parse_article_url(args.url)
    output_dir = Path(args.output) if args.output else default_action_output_dir("download", "download")
    book = attach_workflow(args, article_url, ActionBook)
    book.goto(article_url)
    wait_until_stable(book)
    ensure_zhihu_ready(book)
    data = evaluate(book, """
    (() => {
      const normalize = value => String(value || '').replace(/\\s+/g, ' ').trim();
      const abs = value => {
        if (!value) return '';
        try { return new URL(value, location.origin).toString(); } catch { return String(value || ''); }
      };
      const contentEl = document.querySelector('.Post-RichTextContainer, .RichText, .ArticleContent, article');
      const imageUrls = [];
      if (contentEl) {
        for (const img of [...contentEl.querySelectorAll('img')]) {
          const src = abs(img.getAttribute('data-original') || img.getAttribute('data-actualsrc') || img.getAttribute('src') || '');
          if (src && !src.startsWith('data:') && !imageUrls.includes(src)) imageUrls.push(src);
        }
      }
      return {
        title: normalize(document.querySelector('.Post-Title, h1.ContentItem-title, .ArticleTitle, h1')?.textContent) || 'untitled',
        author: normalize(document.querySelector('.AuthorInfo-name, .UserLink-link, [class*="AuthorInfo"] a')?.textContent),
        publishTime: normalize(document.querySelector('.ContentItem-time, .Post-Time, time')?.textContent),
        sourceUrl: location.href,
        contentHtml: contentEl?.innerHTML || '',
        imageUrls
      };
    })()
    """, "zhihu download", timeout=30.0)
    if not isinstance(data, dict):
        raise RuntimeError("zhihu download: malformed article payload")
    output_dir.mkdir(parents=True, exist_ok=True)
    image_map: dict[str, str] = {}
    media_records: list[dict[str, Any]] = []
    if args.download_images:
        media_dir = output_dir / "media"
        for index, url in enumerate(data.get("imageUrls") or [], start=1):
            base = media_dir / f"{index:03d}_{sanitize_name(Path(urllib.parse.urlparse(str(url)).path).stem, 'image')}"
            result = download_file(str(url), base, article_url)
            row = {"index": index, "url": url, **result}
            media_records.append(row)
            if result.get("status") == "success" and result.get("path"):
                image_map[str(url)] = str(Path(result["path"]).relative_to(output_dir))
    markdown = markdown_from_article(data, image_map)
    article_slug = sanitize_name(str(data.get("title") or "article"), "article", max_length=80)
    (output_dir / f"{article_slug}.md").write_text(markdown, encoding="utf-8")
    (output_dir / "article.md").write_text(markdown, encoding="utf-8")
    record = {
        "title": data.get("title") or "",
        "author": data.get("author") or "",
        "publish_time": data.get("publishTime") or "",
        "source_url": article_url,
        "status": "success",
        "size": len(markdown.encode("utf-8")),
        "image_count": len(data.get("imageUrls") or []),
        "downloaded_image_count": sum(1 for item in media_records if item.get("status") == "success"),
    }
    write_records([record], output_dir, f"知乎文章导出: {record['title'] or article_url}")
    write_json(output_dir / "article.json", {**data, "media": media_records})
    log(f"导出知乎文章: {output_dir}")
    return 0


def add_common(parser: argparse.ArgumentParser, default_count: int = 20) -> None:
    parser.add_argument("--count", type=int, default=default_count, help="Number of records")
    parser.add_argument("--output", default="", help="Output directory")
    add_workflow_args(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Zhihu workflow helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    hot = subparsers.add_parser("hot", help="Zhihu hot list")
    hot_sub = hot.add_subparsers(dest="mode", required=True)
    hot_view = hot_sub.add_parser("view", help="View Zhihu hot list")
    add_common(hot_view, default_count=20)
    hot_view.set_defaults(func=run_hot)

    recommend = subparsers.add_parser("recommend", help="Zhihu home recommendations")
    recommend_sub = recommend.add_subparsers(dest="mode", required=True)
    recommend_view = recommend_sub.add_parser("view", help="View Zhihu home recommendations")
    add_common(recommend_view, default_count=20)
    recommend_view.set_defaults(func=run_recommend)

    search = subparsers.add_parser("search", help="Zhihu search")
    search_sub = search.add_subparsers(dest="mode", required=True)
    search_view = search_sub.add_parser("view", help="View Zhihu search results")
    search_view.add_argument("--query", required=True)
    search_view.add_argument("--type", choices=("all", "answer", "article", "question"), default="all")
    add_common(search_view, default_count=10)
    search_view.set_defaults(func=run_search)

    question = subparsers.add_parser("question", help="Zhihu question answers")
    question_sub = question.add_subparsers(dest="mode", required=True)
    question_view = question_sub.add_parser("view", help="View answers from one question")
    question_view.add_argument("--id", required=True, help="Question ID, question:<id>, or question URL")
    question_view.add_argument("--sort", choices=("default", "created"), default="default")
    question_view.add_argument("--max-content", type=int, default=200, help="Per-answer content cap; 0 means full content")
    add_common(question_view, default_count=5)
    question_view.set_defaults(func=run_question)

    answer_detail = subparsers.add_parser("answer-detail", help="Zhihu answer detail")
    answer_detail_sub = answer_detail.add_subparsers(dest="mode", required=True)
    answer_detail_view = answer_detail_sub.add_parser("view", help="View one full answer")
    answer_detail_view.add_argument("--id", required=True, help="Answer ID, answer:<qid>:<aid>, or answer URL")
    answer_detail_view.add_argument("--max-content", type=int, default=0, help="Content cap; 0 means full content")
    add_common(answer_detail_view, default_count=1)
    answer_detail_view.set_defaults(func=run_answer_detail)

    collections = subparsers.add_parser("collections", help="Current user's Zhihu collections")
    collections_sub = collections.add_subparsers(dest="mode", required=True)
    collections_view = collections_sub.add_parser("view", help="View current user's collections")
    add_common(collections_view, default_count=20)
    collections_view.set_defaults(func=run_collections)

    collection = subparsers.add_parser("collection", help="Zhihu collection items")
    collection_sub = collection.add_subparsers(dest="mode", required=True)
    collection_view = collection_sub.add_parser("view", help="View one collection")
    collection_view.add_argument("--id", required=True, help="Collection ID")
    collection_view.add_argument("--offset", type=int, default=0, help="Pagination offset")
    add_common(collection_view, default_count=20)
    collection_view.set_defaults(func=run_collection)

    download = subparsers.add_parser("download", help="Export a Zhihu article to Markdown")
    download.add_argument("--url", required=True, help="Article URL or article:<id>")
    download.add_argument("--download-images", action="store_true", help="Download images locally")
    download.add_argument("--output", default="", help="Output directory")
    add_workflow_args(download)
    download.set_defaults(func=run_download)

    return parser


def main() -> int:
    install_interrupt_handlers()
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
