#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bilibili workflow helper for the action-browser skill.

The workflow uses ActionBook extension mode and the user's existing Chrome
session. It covers low-risk read-only Bilibili hot, ranking, search, video
metadata, comments, dynamic/feed, history, profile, following, user videos,
subtitles, and official AI summaries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
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
from scripts.workflow_runtime import add_workflow_args, attach_workflow, evaluate, write_json
from scripts.actionbook_session import ActionBookSession as ActionBook
from scripts.script_common import log


BILIBILI_HOME_URL = "https://www.bilibili.com"
BILIBILI_API_URL = "https://api.bilibili.com"
SKILL_DIR = Path(__file__).resolve().parents[2]
ASSETS_DIR = SKILL_DIR / "assets" / "bilibili"

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]
def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def strip_html(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return normalize_text(text)
def read_count(value: Any, default: int = 20, max_value: int = 1000) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = default
    return max(1, min(count, max_value))


def default_action_output_dir(source: str, action: str = "view") -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    action_dir = "downloads" if action == "download" else "views"
    return ASSETS_DIR / action_dir / source / stamp


def write_records(records: list[dict[str, Any]], output_dir: Path, title: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", records)
    lines = [f"# {title}", "", f"- 条目数: {len(records)}", ""]
    for index, item in enumerate(records, start=1):
        heading = item.get("title") or item.get("name") or item.get("author") or item.get("field") or item.get("id") or str(index)
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


def start_book(args: argparse.Namespace, url: str = BILIBILI_HOME_URL) -> ActionBook:
    return attach_workflow(args, url, ActionBook)


def get_page_state(book: ActionBook) -> dict[str, str]:
    value = evaluate(book, """
    (() => ({
      href: location.href,
      title: document.title || '',
      text: (document.body?.innerText || '').slice(0, 1000)
    }))()
    """, "bilibili page state", timeout=10.0)
    return value if isinstance(value, dict) else {}


def ensure_bilibili_ready(book: ActionBook) -> None:
    state = get_page_state(book)
    haystack = "\n".join(str(state.get(key) or "") for key in ("href", "title", "text"))
    if re.search(r"captcha|验证码|安全验证|风控|访问异常|请求过于频繁|账号登录", haystack, re.I):
        raise RuntimeError(f"Bilibili requires login or verification: {state.get('href')} title={state.get('title')}")


def fetch_json_js(url: str) -> str:
    return f"""
    (async () => {{
      try {{
        const response = await fetch({json.dumps(url)}, {{ credentials: 'include' }});
        const text = await response.text();
        if (!response.ok) return {{ __httpError: response.status, __body: text.slice(0, 300) }};
        return JSON.parse(text);
      }} catch (error) {{
        return {{ __fetchError: error?.message || String(error) }};
      }}
    }})()
    """


def fetch_json_url(url: str, *, referer: str = BILIBILI_HOME_URL) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": referer,
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset, errors="replace"))


def require_api_payload(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{label}: malformed payload")
    if value.get("__httpError"):
        raise RuntimeError(f"{label}: HTTP {value.get('__httpError')}")
    if value.get("__fetchError"):
        raise RuntimeError(f"{label}: {value.get('__fetchError')}")
    if value.get("code") not in (None, 0):
        message = value.get("message") or value.get("msg") or "unknown error"
        raise RuntimeError(f"{label}: API {message} ({value.get('code')})")
    return value


def payload_data(payload: dict[str, Any]) -> Any:
    return payload.get("data") if isinstance(payload, dict) else payload


def dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def get_mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    return "".join(raw[i] if i < len(raw) else "" for i in MIXIN_KEY_ENC_TAB)[:32]


def get_wbi_keys(book: ActionBook) -> tuple[str, str]:
    payload = evaluate(book, fetch_json_js(f"{BILIBILI_API_URL}/x/web-interface/nav"), "bilibili nav", timeout=20.0)
    if not isinstance(payload, dict):
        raise RuntimeError("bilibili nav: malformed payload")
    if payload.get("__httpError"):
        raise RuntimeError(f"bilibili nav: HTTP {payload.get('__httpError')}")
    if payload.get("__fetchError"):
        raise RuntimeError(f"bilibili nav: {payload.get('__fetchError')}")
    wbi_img = payload.get("data", {}).get("wbi_img", {})
    img_key = str(wbi_img.get("img_url") or "").rsplit("/", 1)[-1].split(".", 1)[0]
    sub_key = str(wbi_img.get("sub_url") or "").rsplit("/", 1)[-1].split(".", 1)[0]
    if not img_key or not sub_key:
        require_api_payload(payload, "bilibili nav")
        raise RuntimeError("bilibili nav: WBI keys not found")
    return img_key, sub_key


def wbi_sign(book: ActionBook, params: dict[str, Any]) -> dict[str, str]:
    img_key, sub_key = get_wbi_keys(book)
    mixin_key = get_mixin_key(img_key, sub_key)
    all_params = {key: str(value) for key, value in params.items()}
    all_params["wts"] = str(int(time.time()))
    cleaned = {
        key: re.sub(r"[!'()*]", "", value)
        for key, value in sorted(all_params.items())
    }
    query = urllib.parse.urlencode(cleaned).replace("+", "%20")
    cleaned["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    return cleaned


def api_get(book: ActionBook, path: str, params: dict[str, Any] | None = None, *, signed: bool = False, label: str = "bilibili api") -> dict[str, Any]:
    query_params = params or {}
    if signed:
        query_params = wbi_sign(book, query_params)
    query = urllib.parse.urlencode({key: str(value) for key, value in query_params.items()}).replace("+", "%20")
    url = f"{BILIBILI_API_URL}{path}"
    if query:
        url += f"?{query}"
    return require_api_payload(evaluate(book, fetch_json_js(url), label, timeout=40.0), label)


def resolve_bvid(value: str) -> str:
    raw = str(value or "").strip()
    if re.fullmatch(r"BV[A-Za-z0-9]+", raw, re.I):
        return raw
    match = re.search(r"bilibili\.com/(?:video|bangumi/play)/(BV[A-Za-z0-9]+)", raw, re.I)
    if match:
        return match.group(1)
    if "b23.tv" in raw or re.fullmatch(r"[A-Za-z0-9_-]{4,16}", raw):
        url = raw if raw.startswith(("http://", "https://")) else f"https://b23.tv/{raw}"
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=8) as response:
            final_url = response.geturl()
        match = re.search(r"/video/(BV[A-Za-z0-9]+)", final_url, re.I)
        if match:
            return match.group(1)
    raise ValueError("Video target must be a BV ID, Bilibili video URL, or b23.tv short link/code")


def resolve_uid(book: ActionBook, value: str) -> str:
    raw = str(value or "").strip()
    if re.fullmatch(r"\d+", raw):
        return raw
    payload = api_get(
        book,
        "/x/web-interface/wbi/search/type",
        {"search_type": "bili_user", "keyword": raw, "page": 1},
        signed=True,
        label="bilibili user search",
    )
    results = payload.get("data", {}).get("result") or []
    if results:
        return str(results[0].get("mid") or "")
    raise RuntimeError(f"bilibili user search: no user found for {raw}")


def get_self_uid(book: ActionBook) -> str:
    payload = api_get(book, "/x/web-interface/nav", label="bilibili nav")
    mid = payload.get("data", {}).get("mid")
    if not mid:
        raise RuntimeError("Not logged in to bilibili.com or current uid was not found")
    return str(mid)


def format_time(seconds: Any) -> str:
    sec = max(0, int(float(seconds or 0)))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def iso_time(timestamp: Any, length: int = 16) -> str:
    try:
        return datetime.fromtimestamp(int(timestamp)).isoformat(sep=" ")[:length]
    except (TypeError, ValueError, OSError):
        return ""


def run_hot(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=100)
    output_dir = Path(args.output) if args.output else default_action_output_dir("hot")
    book = start_book(args)
    ensure_bilibili_ready(book)
    payload = api_get(book, "/x/web-interface/popular", {"ps": count, "pn": 1}, label="bilibili hot")
    items = payload.get("data", {}).get("list") or []
    rows = []
    for index, item in enumerate(items[:count], start=1):
        rows.append({
            "rank": index,
            "title": item.get("title") or "",
            "author": item.get("owner", {}).get("name") or "",
            "play": item.get("stat", {}).get("view") or 0,
            "danmaku": item.get("stat", {}).get("danmaku") or 0,
            "bvid": item.get("bvid") or "",
            "url": f"{BILIBILI_HOME_URL}/video/{item.get('bvid')}" if item.get("bvid") else "",
        })
    write_records(rows, output_dir, "Bilibili 热门视频")
    log(f"写入 {len(rows)} 条热门视频: {output_dir}")
    return 0


def run_ranking(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=100)
    output_dir = Path(args.output) if args.output else default_action_output_dir("ranking")
    book = start_book(args)
    ensure_bilibili_ready(book)
    payload = api_get(book, "/x/web-interface/ranking/v2", {"rid": args.rid, "type": args.type}, label="bilibili ranking")
    items = payload.get("data", {}).get("list") or []
    rows = []
    for index, item in enumerate(items[:count], start=1):
        rows.append({
            "rank": index,
            "title": item.get("title") or "",
            "author": item.get("owner", {}).get("name") or "",
            "score": item.get("stat", {}).get("view") or 0,
            "bvid": item.get("bvid") or "",
            "url": f"{BILIBILI_HOME_URL}/video/{item.get('bvid')}" if item.get("bvid") else "",
        })
    write_records(rows, output_dir, "Bilibili 排行榜")
    log(f"写入 {len(rows)} 条排行榜结果: {output_dir}")
    return 0


def run_search(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=50)
    output_dir = Path(args.output) if args.output else default_action_output_dir("search")
    book = start_book(args, f"{BILIBILI_HOME_URL}/")
    ensure_bilibili_ready(book)
    search_type = "bili_user" if args.type == "user" else "video"
    payload = api_get(
        book,
        "/x/web-interface/wbi/search/type",
        {"search_type": search_type, "keyword": args.query, "page": args.page},
        signed=True,
        label="bilibili search",
    )
    results = payload.get("data", {}).get("result") or []
    rows = []
    for index, item in enumerate(results[:count], start=1):
        if search_type == "bili_user":
            mid = item.get("mid") or ""
            rows.append({
                "rank": index,
                "type": "user",
                "title": strip_html(item.get("uname")),
                "author": normalize_text(item.get("usign"))[:120],
                "score": item.get("fans") or 0,
                "mid": mid,
                "url": f"https://space.bilibili.com/{mid}" if mid else "",
            })
        else:
            bvid = item.get("bvid") or ""
            rows.append({
                "rank": index,
                "type": "video",
                "title": strip_html(item.get("title")),
                "author": item.get("author") or "",
                "score": item.get("play") or 0,
                "bvid": bvid,
                "url": f"{BILIBILI_HOME_URL}/video/{bvid}" if bvid else "",
            })
    write_records(rows, output_dir, f"Bilibili 搜索: {args.query}")
    log(f"写入 {len(rows)} 条搜索结果: {output_dir}")
    return 0


def run_video(args: argparse.Namespace) -> int:
    bvid = resolve_bvid(args.url)
    output_dir = Path(args.output) if args.output else default_action_output_dir("video")
    book = start_book(args, f"{BILIBILI_HOME_URL}/video/{bvid}/")
    ensure_bilibili_ready(book)
    payload = api_get(book, "/x/web-interface/view", {"bvid": bvid}, label="bilibili video")
    data = payload.get("data") or {}
    stat = data.get("stat") or {}
    owner = data.get("owner") or {}
    rows = [
        {"field": "bvid", "value": data.get("bvid") or bvid},
        {"field": "aid", "value": str(data.get("aid") or "")},
        {"field": "title", "value": data.get("title") or ""},
        {"field": "author", "value": f"{owner.get('name')} (mid: {owner.get('mid')})" if owner.get("name") else ""},
        {"field": "category", "value": data.get("tname_v2") or data.get("tname") or ""},
        {"field": "publish_time", "value": iso_time(data.get("pubdate"))},
        {"field": "duration", "value": f"{format_time(data.get('duration'))} ({data.get('duration') or 0}s)"},
        {"field": "view", "value": str(stat.get("view") or "")},
        {"field": "danmaku", "value": str(stat.get("danmaku") or "")},
        {"field": "reply", "value": str(stat.get("reply") or "")},
        {"field": "like", "value": str(stat.get("like") or "")},
        {"field": "coin", "value": str(stat.get("coin") or "")},
        {"field": "favorite", "value": str(stat.get("favorite") or "")},
        {"field": "share", "value": str(stat.get("share") or "")},
        {"field": "parts", "value": str(data.get("videos") or 1)},
        {"field": "thumbnail", "value": data.get("pic") or ""},
        {"field": "description", "value": data.get("desc") or ""},
        {"field": "url", "value": f"{BILIBILI_HOME_URL}/video/{bvid}"},
    ]
    write_records(rows, output_dir, f"Bilibili 视频: {bvid}")
    log(f"写入视频信息: {output_dir}")
    return 0


def run_comments(args: argparse.Namespace) -> int:
    bvid = resolve_bvid(args.url)
    count = read_count(args.count, default=20, max_value=50)
    output_dir = Path(args.output) if args.output else default_action_output_dir("comments")
    book = start_book(args, f"{BILIBILI_HOME_URL}/video/{bvid}/")
    ensure_bilibili_ready(book)
    view = api_get(book, "/x/web-interface/view", {"bvid": bvid}, label="bilibili video")
    aid = view.get("data", {}).get("aid")
    if not aid:
        raise RuntimeError(f"Cannot resolve aid for bvid: {bvid}")
    payload = api_get(
        book,
        "/x/v2/reply/main",
        {"oid": aid, "type": 1, "mode": 3, "ps": count},
        signed=True,
        label="bilibili comments",
    )
    replies = payload.get("data", {}).get("replies") or []
    rows = []
    for index, item in enumerate(replies[:count], start=1):
        rows.append({
            "rank": index,
            "author": item.get("member", {}).get("uname") or "",
            "text": normalize_text(item.get("content", {}).get("message")),
            "likes": item.get("like") or 0,
            "replies": item.get("rcount") or 0,
            "time": iso_time(item.get("ctime")),
        })
    write_records(rows, output_dir, f"Bilibili 评论: {bvid}")
    log(f"写入 {len(rows)} 条评论: {output_dir}")
    return 0


TYPE_MAP = {
    "DYNAMIC_TYPE_AV": "video",
    "DYNAMIC_TYPE_DRAW": "draw",
    "DYNAMIC_TYPE_ARTICLE": "article",
    "DYNAMIC_TYPE_FORWARD": "forward",
    "DYNAMIC_TYPE_WORD": "text",
    "DYNAMIC_TYPE_LIVE_RCMD": "live",
    "DYNAMIC_TYPE_PGC": "bangumi",
}


def parse_dynamic_item(item: dict[str, Any], rank: int) -> dict[str, Any]:
    modules = dict_or_empty(item.get("modules"))
    author = dict_or_empty(modules.get("module_author"))
    dynamic = dict_or_empty(modules.get("module_dynamic"))
    major = dict_or_empty(dynamic.get("major"))
    stat = dict_or_empty(modules.get("module_stat"))
    item_type = TYPE_MAP.get(str(item.get("type") or ""), item.get("type") or "")
    title = ""
    url = f"https://t.bilibili.com/{item.get('id_str')}" if item.get("id_str") else ""
    archive = dict_or_empty(major.get("archive"))
    article = dict_or_empty(major.get("article"))
    desc = dict_or_empty(dynamic.get("desc"))
    draw = dict_or_empty(major.get("draw"))
    if archive:
        title = archive.get("title") or ""
        url = "https:" + archive.get("jump_url", "") if archive.get("jump_url") else url
    if not title and article:
        title = article.get("title") or ""
        url = "https:" + article.get("jump_url", "") if article.get("jump_url") else url
    if not title and desc.get("text"):
        title = strip_html(desc.get("text"))[:80]
    if not title and draw:
        title = f"[图片x{len(draw.get('items') or [])}]"
    if not title:
        title = f"[{item_type or '动态'}]"
    like = dict_or_empty(stat.get("like"))
    comment = dict_or_empty(stat.get("comment"))
    return {
        "rank": rank,
        "id": item.get("id_str") or "",
        "time": author.get("pub_time") or "",
        "author": author.get("name") or "",
        "title": title,
        "type": item_type,
        "likes": like.get("count") or 0,
        "comments": comment.get("count") or 0,
        "url": url,
    }


def run_feed(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=100)
    pages = read_count(args.pages, default=1, max_value=10)
    output_dir = Path(args.output) if args.output else default_action_output_dir("feed")
    book = start_book(args)
    ensure_bilibili_ready(book)
    rows: list[dict[str, Any]] = []
    offset = ""
    is_user_feed = bool(args.uid)
    uid = resolve_uid(book, args.uid) if args.uid else ""
    filter_type = "" if args.type == "all" else args.type
    for page_index in range(pages):
        if len(rows) >= count:
            break
        if is_user_feed:
            params: dict[str, Any] = {"host_mid": uid, "timezone_offset": -480}
            path = "/x/polymer/web-dynamic/v1/feed/space"
        else:
            params = {"timezone_offset": -480, "type": filter_type or "all", "page": page_index + 1}
            path = "/x/polymer/web-dynamic/v1/feed/all"
        if offset:
            params["offset"] = offset
        payload = api_get(book, path, params, label="bilibili feed")
        data = payload_data(payload) or {}
        items = data.get("items") or []
        if not items:
            break
        for item in items:
            parsed = parse_dynamic_item(item, len(rows) + 1)
            if filter_type and parsed.get("type") != filter_type:
                continue
            rows.append(parsed)
            if len(rows) >= count:
                break
        offset = data.get("offset") or items[-1].get("id_str") or ""
        if not offset or not data.get("has_more"):
            break
    write_records(rows, output_dir, "Bilibili 动态时间线")
    log(f"写入 {len(rows)} 条动态: {output_dir}")
    return 0


def run_dynamic(args: argparse.Namespace) -> int:
    if not args.output:
        args.output = str(default_action_output_dir("dynamic"))
    args.uid = ""
    args.type = "all"
    args.pages = 1
    return run_feed(args)


def run_history(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=30)
    output_dir = Path(args.output) if args.output else default_action_output_dir("history")
    book = start_book(args)
    ensure_bilibili_ready(book)
    payload = api_get(book, "/x/web-interface/history/cursor", {"ps": count, "type": "archive"}, label="bilibili history")
    items = payload.get("data", {}).get("list") or []
    rows = []
    for index, item in enumerate(items[:count], start=1):
        progress = int(item.get("progress") or 0)
        duration = int(item.get("duration") or 0)
        progress_text = "已看完" if progress < 0 or (duration and progress >= duration) else f"{format_time(progress)}/{format_time(duration)}"
        bvid = item.get("history", {}).get("bvid") or ""
        rows.append({
            "rank": index,
            "title": item.get("title") or "",
            "author": item.get("author_name") or "",
            "progress": progress_text,
            "bvid": bvid,
            "url": f"{BILIBILI_HOME_URL}/video/{bvid}" if bvid else "",
        })
    write_records(rows, output_dir, "Bilibili 观看历史")
    log(f"写入 {len(rows)} 条历史记录: {output_dir}")
    return 0


def run_me(args: argparse.Namespace) -> int:
    output_dir = Path(args.output) if args.output else default_action_output_dir("me")
    book = start_book(args)
    ensure_bilibili_ready(book)
    uid = get_self_uid(book)
    payload = api_get(book, "/x/space/wbi/acc/info", {"mid": uid}, signed=True, label="bilibili me")
    data = payload.get("data") or {}
    rows = [{
        "name": data.get("name") or "",
        "uid": data.get("mid") or uid,
        "level": data.get("level") or 0,
        "coins": data.get("coins") or 0,
        "followers": data.get("follower") or 0,
        "following": data.get("following") or 0,
        "url": f"https://space.bilibili.com/{uid}",
    }]
    write_records(rows, output_dir, "Bilibili 当前账号")
    log(f"写入当前账号信息: {output_dir}")
    return 0


def run_following(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=50, max_value=50)
    output_dir = Path(args.output) if args.output else default_action_output_dir("following")
    book = start_book(args)
    ensure_bilibili_ready(book)
    uid = resolve_uid(book, args.uid) if args.uid else get_self_uid(book)
    payload = api_get(
        book,
        "/x/relation/followings",
        {"vmid": uid, "pn": args.page, "ps": count, "order": "desc"},
        label="bilibili following",
    )
    items = payload.get("data", {}).get("list") or []
    rows = []
    for item in items[:count]:
        rows.append({
            "mid": item.get("mid") or "",
            "name": item.get("uname") or "",
            "sign": normalize_text(item.get("sign"))[:80],
            "following": "互相关注" if item.get("attribute") == 6 else "已关注",
            "fans": item.get("official_verify", {}).get("desc") or "",
            "url": f"https://space.bilibili.com/{item.get('mid')}" if item.get("mid") else "",
        })
    write_records(rows, output_dir, f"Bilibili 关注列表: {uid}")
    log(f"写入 {len(rows)} 条关注记录: {output_dir}")
    return 0


def run_user_videos(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=50)
    output_dir = Path(args.output) if args.output else default_action_output_dir("user-videos")
    book = start_book(args)
    ensure_bilibili_ready(book)
    uid = resolve_uid(book, args.uid)
    payload = api_get(
        book,
        "/x/space/wbi/arc/search",
        {"mid": uid, "pn": args.page, "ps": count, "order": args.order},
        signed=True,
        label="bilibili user videos",
    )
    items = payload.get("data", {}).get("list", {}).get("vlist") or []
    rows = []
    for index, item in enumerate(items[:count], start=1):
        bvid = item.get("bvid") or ""
        rows.append({
            "rank": index,
            "title": item.get("title") or "",
            "plays": item.get("play") or 0,
            "likes": item.get("like") or 0,
            "date": iso_time(item.get("created"), length=10),
            "bvid": bvid,
            "url": f"{BILIBILI_HOME_URL}/video/{bvid}" if bvid else "",
        })
    write_records(rows, output_dir, f"Bilibili 用户投稿: {uid}")
    log(f"写入 {len(rows)} 条投稿视频: {output_dir}")
    return 0


def run_subtitle(args: argparse.Namespace) -> int:
    bvid = resolve_bvid(args.url)
    output_dir = Path(args.output) if args.output else default_action_output_dir("subtitle")
    book = start_book(args, f"{BILIBILI_HOME_URL}/video/{bvid}/")
    ensure_bilibili_ready(book)
    view = api_get(book, "/x/web-interface/view", {"bvid": bvid}, label="bilibili video")
    cid = view.get("data", {}).get("cid")
    if not cid:
        raise RuntimeError(f"Cannot resolve cid for bvid: {bvid}")
    player = api_get(
        book,
        "/x/player/wbi/v2",
        {"bvid": bvid, "cid": cid},
        signed=True,
        label="bilibili subtitle list",
    )
    subtitles = player.get("data", {}).get("subtitle", {}).get("subtitles") or []
    if not subtitles:
        raise RuntimeError(f"bilibili subtitle: no subtitle track found for {bvid}")
    target = None
    if args.lang:
        target = next((item for item in subtitles if item.get("lan") == args.lang), None)
    target = target or subtitles[0]
    sub_url = target.get("subtitle_url") or ""
    if not sub_url:
        raise RuntimeError("bilibili subtitle: subtitle_url is empty, login or permission may be required")
    if sub_url.startswith("//"):
        sub_url = "https:" + sub_url
    try:
        sub_json = require_api_payload(evaluate(book, fetch_json_js(sub_url), "bilibili subtitle file", timeout=30.0), "bilibili subtitle file")
    except RuntimeError:
        sub_json = require_api_payload(fetch_json_url(sub_url, referer=f"{BILIBILI_HOME_URL}/video/{bvid}/"), "bilibili subtitle file")
    body = sub_json.get("body") if isinstance(sub_json, dict) else []
    rows = []
    for index, item in enumerate(body or [], start=1):
        rows.append({
            "index": index,
            "from": f"{float(item.get('from') or 0):.2f}s",
            "to": f"{float(item.get('to') or 0):.2f}s",
            "content": item.get("content") or "",
        })
    write_records(rows, output_dir, f"Bilibili 字幕: {bvid}")
    log(f"写入 {len(rows)} 条字幕: {output_dir}")
    return 0


def run_summary(args: argparse.Namespace) -> int:
    bvid = resolve_bvid(args.url)
    output_dir = Path(args.output) if args.output else default_action_output_dir("summary")
    book = start_book(args, f"{BILIBILI_HOME_URL}/video/{bvid}/")
    ensure_bilibili_ready(book)
    view = api_get(book, "/x/web-interface/view", {"bvid": bvid}, label="bilibili video")
    data = view.get("data") or {}
    cid = data.get("cid")
    up_mid = data.get("owner", {}).get("mid")
    if not cid or not up_mid:
        raise RuntimeError(f"Cannot resolve cid/up_mid for bvid: {bvid}")
    conclusion = api_get(
        book,
        "/x/web-interface/view/conclusion/get",
        {"bvid": bvid, "cid": cid, "up_mid": up_mid},
        signed=True,
        label="bilibili summary",
    )
    conclusion_data = conclusion.get("data") or {}
    if conclusion_data.get("code") not in (None, 0):
        raise RuntimeError(f"bilibili summary: no official AI summary for {bvid}")
    model_result = conclusion_data.get("model_result")
    if isinstance(model_result, str):
        model_result = json.loads(model_result)
    if not isinstance(model_result, dict) or not normalize_text(model_result.get("summary")):
        raise RuntimeError(f"bilibili summary: malformed or empty summary for {bvid}")
    rows = [{"time": "", "content": normalize_text(model_result.get("summary"))}]
    for section in model_result.get("outline") or []:
        title = normalize_text(section.get("title"))
        if title:
            rows.append({"time": format_time(section.get("timestamp")), "content": f"# {title}"})
        for point in section.get("part_outline") or []:
            content = normalize_text(point.get("content"))
            if content:
                rows.append({"time": format_time(point.get("timestamp")), "content": content})
    write_records(rows, output_dir, f"Bilibili AI 总结: {bvid}")
    log(f"写入 {len(rows)} 条总结片段: {output_dir}")
    return 0


def add_io(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", default="", help="Output directory")
    add_workflow_args(parser)


def add_common(parser: argparse.ArgumentParser, default_count: int = 20) -> None:
    parser.add_argument("--count", type=int, default=default_count, help="Number of items")
    add_io(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bilibili ActionBook read-only workflows")
    subparsers = parser.add_subparsers(dest="command", required=True)

    hot = subparsers.add_parser("hot", help="Bilibili hot videos")
    hot_sub = hot.add_subparsers(dest="mode", required=True)
    hot_view = hot_sub.add_parser("view", help="View Bilibili hot videos")
    add_common(hot_view)
    hot_view.set_defaults(func=run_hot)

    ranking = subparsers.add_parser("ranking", help="Bilibili ranking board")
    ranking_sub = ranking.add_subparsers(dest="mode", required=True)
    ranking_view = ranking_sub.add_parser("view", help="View Bilibili ranking board")
    ranking_view.add_argument("--rid", type=int, default=0, help="Ranking partition id, default 0")
    ranking_view.add_argument("--type", default="all", help="Ranking type, default all")
    add_common(ranking_view)
    ranking_view.set_defaults(func=run_ranking)

    search = subparsers.add_parser("search", help="Bilibili search")
    search_sub = search.add_subparsers(dest="mode", required=True)
    search_view = search_sub.add_parser("view", help="View Bilibili search results")
    search_view.add_argument("--query", required=True, help="Search keyword")
    search_view.add_argument("--type", choices=("video", "user"), default="video", help="Search type")
    search_view.add_argument("--page", type=int, default=1, help="Result page")
    add_common(search_view)
    search_view.set_defaults(func=run_search)

    video = subparsers.add_parser("video", help="Bilibili video metadata")
    video_sub = video.add_subparsers(dest="mode", required=True)
    video_view = video_sub.add_parser("view", help="View Bilibili video metadata")
    video_view.add_argument("--url", required=True, help="BV ID, video URL, or b23.tv short link/code")
    add_io(video_view)
    video_view.set_defaults(func=run_video)

    comments = subparsers.add_parser("comments", help="Bilibili video comments")
    comments_sub = comments.add_subparsers(dest="mode", required=True)
    comments_view = comments_sub.add_parser("view", help="View Bilibili video comments")
    comments_view.add_argument("--url", required=True, help="BV ID, video URL, or b23.tv short link/code")
    add_common(comments_view)
    comments_view.set_defaults(func=run_comments)

    dynamic = subparsers.add_parser("dynamic", help="Bilibili current dynamic feed")
    dynamic_sub = dynamic.add_subparsers(dest="mode", required=True)
    dynamic_view = dynamic_sub.add_parser("view", help="View current dynamic feed")
    add_common(dynamic_view, default_count=15)
    dynamic_view.set_defaults(func=run_dynamic)

    feed = subparsers.add_parser("feed", help="Bilibili dynamic feed")
    feed_sub = feed.add_subparsers(dest="mode", required=True)
    feed_view = feed_sub.add_parser("view", help="View current or user dynamic feed")
    feed_view.add_argument("--uid", default="", help="User UID or username; empty means current following feed")
    feed_view.add_argument("--type", choices=("all", "video", "article", "draw", "text"), default="all", help="Feed filter")
    feed_view.add_argument("--pages", type=int, default=1, help="Pages to fetch")
    add_common(feed_view)
    feed_view.set_defaults(func=run_feed)

    history = subparsers.add_parser("history", help="Bilibili watch history")
    history_sub = history.add_subparsers(dest="mode", required=True)
    history_view = history_sub.add_parser("view", help="View watch history")
    add_common(history_view)
    history_view.set_defaults(func=run_history)

    me = subparsers.add_parser("me", help="Bilibili current profile")
    me_sub = me.add_subparsers(dest="mode", required=True)
    me_view = me_sub.add_parser("view", help="View current profile")
    add_io(me_view)
    me_view.set_defaults(func=run_me)

    following = subparsers.add_parser("following", help="Bilibili following list")
    following_sub = following.add_subparsers(dest="mode", required=True)
    following_view = following_sub.add_parser("view", help="View following list")
    following_view.add_argument("--uid", default="", help="Target user UID or username; empty means current user")
    following_view.add_argument("--page", type=int, default=1, help="Page number")
    add_common(following_view, default_count=50)
    following_view.set_defaults(func=run_following)

    user_videos = subparsers.add_parser("user-videos", help="Bilibili user videos")
    user_videos_sub = user_videos.add_subparsers(dest="mode", required=True)
    user_videos_view = user_videos_sub.add_parser("view", help="View videos from one user")
    user_videos_view.add_argument("--uid", required=True, help="User UID or username")
    user_videos_view.add_argument("--order", default="pubdate", choices=("pubdate", "click", "stow"), help="Sort order")
    user_videos_view.add_argument("--page", type=int, default=1, help="Page number")
    add_common(user_videos_view)
    user_videos_view.set_defaults(func=run_user_videos)

    subtitle = subparsers.add_parser("subtitle", help="Bilibili video subtitles")
    subtitle_sub = subtitle.add_subparsers(dest="mode", required=True)
    subtitle_view = subtitle_sub.add_parser("view", help="View video subtitles")
    subtitle_view.add_argument("--url", required=True, help="BV ID, video URL, or b23.tv short link/code")
    subtitle_view.add_argument("--lang", default="", help="Subtitle language code, e.g. zh-CN")
    add_io(subtitle_view)
    subtitle_view.set_defaults(func=run_subtitle)

    summary = subparsers.add_parser("summary", help="Bilibili official AI summary")
    summary_sub = summary.add_subparsers(dest="mode", required=True)
    summary_view = summary_sub.add_parser("view", help="View official AI summary")
    summary_view.add_argument("--url", required=True, help="BV ID, video URL, or b23.tv short link/code")
    add_io(summary_view)
    summary_view.set_defaults(func=run_summary)

    return parser


def main() -> int:
    install_interrupt_handlers()
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
