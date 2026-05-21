#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Douyin workflow helper for the action-browser skill.

The workflow uses ActionBook extension mode and the user's existing Chrome
session. It only exposes low-risk read-only Douyin entries. OpenCLI write
entries such as publish, delete, draft, and update are intentionally not
enabled here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from actionbook_interrupts import install_interrupt_handlers
from actionbook_session import ActionBookSession as ActionBook


DOUYIN_CREATOR_URL = "https://creator.douyin.com"
DOUYIN_HOME_URL = "https://www.douyin.com"
DEFAULT_SESSION = "douyin-task"
DEFAULT_TAB = ""
SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = SKILL_DIR / "assets" / "douyin"


class LoginRequiredError(RuntimeError):
    """Raised when Douyin asks for login, CAPTCHA, or security verification."""


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def unwrap_eval(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def read_count(value: Any, default: int = 20, max_value: int = 100) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = default
    return max(1, min(count, max_value))


def default_action_output_dir(source: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return ASSETS_DIR / "views" / source / stamp


def api_eval(book: ActionBook, script: str, label: str, timeout: float = 45.0) -> Any:
    value = unwrap_eval(book.eval(script, timeout=timeout))
    if isinstance(value, dict) and value.get("error"):
        raise RuntimeError(f"{label}: {value.get('error')}")
    return value


def get_page_state(book: ActionBook) -> dict[str, str]:
    value = api_eval(book, """
    (() => ({
      href: location.href,
      title: document.title || '',
      text: (document.body?.innerText || '').slice(0, 1000)
    }))()
    """, "douyin page state", timeout=10.0)
    return value if isinstance(value, dict) else {}


def page_has_login_or_risk(state: dict[str, str]) -> bool:
    href = str(state.get("href") or "")
    title = str(state.get("title") or "")
    text = str(state.get("text") or "")
    if re.search(r"/login|passport|sso|verify|captcha", href, re.I):
        return True
    haystack = "\n".join([title, text])
    return bool(re.search(r"扫码登录|验证码|安全验证|verify|captcha|风险|访问频繁|请稍后|登录后|请先登录|登录\/注册|账号登录", haystack, re.I))


def ensure_douyin_ready(book: ActionBook) -> None:
    state = get_page_state(book)
    if page_has_login_or_risk(state):
        raise LoginRequiredError(f"Douyin requires login or verification: {state.get('href')} title={state.get('title')}")


def start_book(args: argparse.Namespace, url: str) -> ActionBook:
    book = ActionBook(args.session, args.tab)
    book.start(url)
    return book


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_records(records: list[dict[str, Any]], output_dir: Path, title: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", records)
    lines = [f"# {title}", "", f"- 条目数: {len(records)}", ""]
    for index, item in enumerate(records, start=1):
        heading = item.get("title") or item.get("name") or item.get("nickname") or item.get("aweme_id") or item.get("id") or str(index)
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


def probe_media_url(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": DOUYIN_HOME_URL + "/",
            "Range": "bytes=0-0",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        content_range = response.headers.get("Content-Range") or ""
        total = 0
        match = re.search(r"/(\d+)\s*$", content_range)
        if match:
            total = int(match.group(1))
        if not total:
            total = int(response.headers.get("Content-Length") or 0)
        return {
            "content_type": response.headers.get("Content-Type") or "",
            "content_length": total,
        }


def download_media_url(url: str, path: Path) -> int:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": DOUYIN_HOME_URL + "/",
        },
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with urllib.request.urlopen(request, timeout=120) as response, path.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            total += len(chunk)
    return total


def browser_fetch_js(method: str, url: str, body: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> str:
    body_line = f"body: JSON.stringify({json.dumps(body, ensure_ascii=False)})," if body is not None else ""
    return f"""
    (async () => {{
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 30000);
      try {{
        const response = await fetch({json.dumps(url)}, {{
          method: {json.dumps(method)},
          credentials: 'include',
          signal: controller.signal,
          headers: {{
            'Content-Type': 'application/json',
            ...{json.dumps(headers or {}, ensure_ascii=False)}
          }},
          {body_line}
        }});
        const text = await response.text();
        let payload;
        try {{
          payload = JSON.parse(text);
        }} catch (error) {{
          return {{ __error: `JSON parse failed: ${{text.slice(0, 300) || String(error?.message || error)}}`, __httpStatus: response.status }};
        }}
        if (!response.ok) {{
          return {{ __error: payload?.status_msg || payload?.message || `HTTP ${{response.status}}`, __httpStatus: response.status, payload }};
        }}
        return payload;
      }} catch (error) {{
        return {{ __error: String(error?.message || error) }};
      }} finally {{
        clearTimeout(timer);
      }}
    }})()
    """


def require_douyin_payload(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{label}: malformed payload")
    if value.get("__error"):
        message = str(value.get("__error") or "")
        if page_has_login_or_risk({"text": message}):
            raise LoginRequiredError(f"{label}: {message}")
        raise RuntimeError(f"{label}: {message}")
    if "status_code" in value and value.get("status_code") not in (0, "0", None):
        message = value.get("status_msg") or value.get("message") or "unknown error"
        if value.get("status_code") in (8, "8") or page_has_login_or_risk({"text": str(message)}):
            raise LoginRequiredError(f"{label}: Douyin API error {value.get('status_code')}: {message}")
        raise RuntimeError(f"{label}: Douyin API error {value.get('status_code')}: {message}")
    return value


def creator_fetch(book: ActionBook, method: str, url: str, label: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    ensure_douyin_ready(book)
    payload = api_eval(book, browser_fetch_js(method, url, body=body), label, timeout=40.0)
    return require_douyin_payload(payload, label)


def format_ts(value: Any) -> str:
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return str(value or "")
    if ts <= 0:
        return ""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def run_profile(args: argparse.Namespace) -> int:
    output_dir = Path(args.output) if args.output else default_action_output_dir("profile")
    book = start_book(args, DOUYIN_CREATOR_URL)
    data = creator_fetch(book, "GET", f"{DOUYIN_CREATOR_URL}/web/api/media/user/info/?aid=1128", "douyin profile")
    user = data.get("user_info") if isinstance(data.get("user_info"), dict) else data.get("user")
    if not isinstance(user, dict):
        raise LoginRequiredError("douyin profile: user info was not found; login may be required")
    rows = [{
        "uid": str(user.get("uid") or ""),
        "nickname": str(user.get("nickname") or ""),
        "follower_count": user.get("follower_count") or 0,
        "following_count": user.get("following_count") or 0,
        "aweme_count": user.get("aweme_count") or 0,
    }]
    write_records(rows, output_dir, "抖音账号信息")
    log(f"写入账号信息: {output_dir}")
    return 0


def normalize_video_status(status: Any, public_time: Any) -> str:
    now = int(time.time())
    if isinstance(status, dict):
        if status.get("is_delete"):
            return "deleted"
        if status.get("is_prohibited"):
            return "prohibited"
        if status.get("in_reviewing"):
            return "reviewing"
        if status.get("is_private"):
            return "private"
    try:
        public_ts = int(public_time or 0)
    except (TypeError, ValueError):
        public_ts = 0
    if public_ts > now:
        return "scheduled"
    return str(status) if isinstance(status, int) else "published"


def run_videos(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=100)
    output_dir = Path(args.output) if args.output else default_action_output_dir("videos")
    book = start_book(args, DOUYIN_CREATOR_URL)
    status_map = {"all": 0, "published": 1, "reviewing": 3, "scheduled": 0}
    page_size = min(count, 100)
    url = (
        f"{DOUYIN_CREATOR_URL}/janus/douyin/creator/pc/work_list?"
        f"page_size={page_size}&page_num={int(args.page)}&status={status_map.get(args.status, 0)}"
    )
    data = creator_fetch(book, "GET", url, "douyin videos")
    items = data.get("data", {}).get("work_list") if isinstance(data.get("data"), dict) else None
    if not isinstance(items, list):
        items = data.get("aweme_list") if isinstance(data.get("aweme_list"), list) else []
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        public_time = item.get("public_time")
        status = normalize_video_status(item.get("status"), public_time)
        if args.status == "scheduled" and status != "scheduled":
            continue
        stats = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
        rows.append({
            "aweme_id": str(item.get("aweme_id") or item.get("item_id") or ""),
            "title": normalize_text(item.get("desc") or item.get("title") or item.get("caption") or ""),
            "status": status,
            "play_count": stats.get("play_count") or 0,
            "digg_count": stats.get("digg_count") or stats.get("like_count") or 0,
            "create_time": format_ts(item.get("create_time") or public_time),
        })
        if len(rows) >= count:
            break
    write_records(rows, output_dir, f"抖音作品列表: {args.status}")
    log(f"写入 {len(rows)} 条作品记录: {output_dir}")
    return 0


def run_drafts(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=100)
    output_dir = Path(args.output) if args.output else default_action_output_dir("drafts")
    book = start_book(args, DOUYIN_CREATOR_URL)
    data = creator_fetch(
        book,
        "POST",
        f"{DOUYIN_CREATOR_URL}/web/api/media/aweme/draft",
        "douyin drafts",
        body={"item": {"common": {"draft": {"req_type": 3}}}},
    )
    rows = []
    if str(data.get("status_msg") or "").lower() == "not found":
        write_records(rows, output_dir, "抖音草稿列表")
        log(f"写入 {len(rows)} 条草稿记录: {output_dir}")
        return 0
    for item in (data.get("aweme_list") if isinstance(data.get("aweme_list"), list) else [])[:count]:
        if not isinstance(item, dict):
            continue
        rows.append({
            "aweme_id": str(item.get("aweme_id") or ""),
            "title": normalize_text(item.get("desc") or item.get("title") or ""),
            "create_time": format_ts(item.get("create_time")),
        })
    write_records(rows, output_dir, "抖音草稿列表")
    log(f"写入 {len(rows)} 条草稿记录: {output_dir}")
    return 0


def run_collections(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=100)
    output_dir = Path(args.output) if args.output else default_action_output_dir("collections")
    book = start_book(args, DOUYIN_CREATOR_URL)
    url = (
        f"{DOUYIN_CREATOR_URL}/web/api/mix/list/?status=0,1,2,3,6&count={count}"
        "&cursor=0&should_query_new_mix=1&device_platform=web&aid=1128"
    )
    data = creator_fetch(book, "GET", url, "douyin collections")
    rows = []
    for item in data.get("mix_list") if isinstance(data.get("mix_list"), list) else []:
        if not isinstance(item, dict):
            continue
        rows.append({
            "mix_id": str(item.get("mix_id") or ""),
            "name": normalize_text(item.get("mix_name") or item.get("name") or ""),
            "item_count": item.get("item_count") or 0,
        })
    write_records(rows[:count], output_dir, "抖音合集列表")
    log(f"写入 {len(rows[:count])} 个合集: {output_dir}")
    return 0


def run_activities(args: argparse.Namespace) -> int:
    output_dir = Path(args.output) if args.output else default_action_output_dir("activities")
    book = start_book(args, DOUYIN_CREATOR_URL)
    data = creator_fetch(book, "GET", f"{DOUYIN_CREATOR_URL}/web/api/media/activity/get/?aid=1128", "douyin activities")
    rows = []
    for item in data.get("activity_list") if isinstance(data.get("activity_list"), list) else []:
        if not isinstance(item, dict):
            continue
        rows.append({
            "activity_id": str(item.get("activity_id") or ""),
            "title": normalize_text(item.get("title") or item.get("activity_name") or ""),
            "end_time": format_ts(item.get("end_time")) or str(item.get("show_end_time") or ""),
        })
    write_records(rows, output_dir, "抖音官方活动列表")
    log(f"写入 {len(rows)} 个活动: {output_dir}")
    return 0


def run_hashtag(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=10, max_value=50)
    output_dir = Path(args.output) if args.output else default_action_output_dir("hashtag")
    book = start_book(args, DOUYIN_CREATOR_URL)
    if args.action == "search":
        if not args.keyword:
            raise ValueError("hashtag search requires --keyword")
        url = f"{DOUYIN_CREATOR_URL}/aweme/v1/challenge/search/?keyword={urllib.parse.quote(args.keyword)}&count={count}&aid=1128"
    elif args.action == "suggest":
        if not args.cover:
            raise ValueError("hashtag suggest requires --cover")
        url = f"{DOUYIN_CREATOR_URL}/web/api/media/hashtag/rec/?cover_uri={urllib.parse.quote(args.cover)}&aid=1128"
    else:
        keyword = f"keyword={urllib.parse.quote(args.keyword)}&" if args.keyword else ""
        url = f"{DOUYIN_CREATOR_URL}/aweme/v1/hotspot/recommend/?{keyword}aid=1128"
    data = creator_fetch(book, "GET", url, "douyin hashtag")
    rows = []
    if args.action == "search":
        source = data.get("challenge_list") if isinstance(data.get("challenge_list"), list) else []
        for item in source:
            info = item.get("challenge_info") if isinstance(item, dict) and isinstance(item.get("challenge_info"), dict) else {}
            rows.append({"name": str(info.get("cha_name") or ""), "id": str(info.get("cid") or ""), "view_count": info.get("view_count") or 0})
    elif args.action == "suggest":
        source = data.get("hashtag_list") if isinstance(data.get("hashtag_list"), list) else []
        for item in source:
            if isinstance(item, dict):
                rows.append({"name": str(item.get("name") or ""), "id": str(item.get("id") or ""), "view_count": item.get("view_count") or 0})
    else:
        source = data.get("hotspot_list")
        if not isinstance(source, list) and isinstance(data.get("all_sentences"), list):
            source = [{"sentence": item.get("word") or "", "hot_value": item.get("hot_value"), "sentence_id": item.get("sentence_id") or ""} for item in data["all_sentences"] if isinstance(item, dict)]
        for item in source if isinstance(source, list) else []:
            if isinstance(item, dict):
                rows.append({"name": str(item.get("sentence") or ""), "id": str(item.get("sentence_id") or ""), "view_count": item.get("hot_value") or item.get("view_count") or 0})
    rows = rows[:count]
    write_records(rows, output_dir, f"抖音话题: {args.action}")
    log(f"写入 {len(rows)} 条话题记录: {output_dir}")
    return 0


def run_location(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=50)
    output_dir = Path(args.output) if args.output else default_action_output_dir("location")
    book = start_book(args, DOUYIN_CREATOR_URL)
    url = f"{DOUYIN_CREATOR_URL}/aweme/v1/life/video_api/search/poi/?keyword={urllib.parse.quote(args.query)}&count={count}&aid=1128"
    data = creator_fetch(book, "GET", url, "douyin location")
    rows = []
    for item in data.get("poi_list") if isinstance(data.get("poi_list"), list) else []:
        if not isinstance(item, dict):
            continue
        rows.append({
            "poi_id": str(item.get("poi_id") or ""),
            "name": normalize_text(item.get("poi_name") or item.get("name") or ""),
            "address": normalize_text(item.get("address") or ""),
            "city": normalize_text(item.get("city_name") or ""),
        })
    write_records(rows[:count], output_dir, f"抖音 POI 搜索: {args.query}")
    log(f"写入 {len(rows[:count])} 条 POI 记录: {output_dir}")
    return 0


def run_stats(args: argparse.Namespace) -> int:
    output_dir = Path(args.output) if args.output else default_action_output_dir("stats")
    now = int(time.time())
    body = {
        "aweme_id": args.aweme_id,
        "start_time": now - 7 * 86400,
        "end_time": now,
        "metrics": ["play_count", "like_count", "comment_count", "share_count"],
    }
    book = start_book(args, DOUYIN_CREATOR_URL)
    data = creator_fetch(book, "POST", f"{DOUYIN_CREATOR_URL}/janus/douyin/creator/data/item_analysis/metrics_trend", "douyin stats", body=body)
    values = data.get("data") if isinstance(data.get("data"), dict) else {}
    rows = [{"metric": key, "value": value} for key, value in values.items()]
    write_records(rows, output_dir, f"抖音作品数据: {args.aweme_id}")
    log(f"写入 {len(rows)} 条作品数据: {output_dir}")
    return 0


def run_user_videos(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=20)
    comment_limit = read_count(args.comment_limit, default=10, max_value=10)
    output_dir = Path(args.output) if args.output else default_action_output_dir("user-videos")
    media_dir = output_dir / "media"
    max_media_bytes = max(0, int(float(args.max_media_mb) * 1024 * 1024))
    book = start_book(args, f"{DOUYIN_HOME_URL}/user/{args.sec_uid}")
    time.sleep(2.0)
    ensure_douyin_ready(book)
    params = urllib.parse.urlencode({"sec_user_id": args.sec_uid, "max_cursor": "0", "count": str(count), "aid": "6383"})
    data = creator_fetch(
        book,
        "GET",
        f"{DOUYIN_HOME_URL}/aweme/v1/web/aweme/post/?{params}",
        "douyin user-videos",
    )
    rows = []
    for index, item in enumerate(data.get("aweme_list") if isinstance(data.get("aweme_list"), list) else [], start=1):
        if not isinstance(item, dict):
            continue
        video = item.get("video") if isinstance(item.get("video"), dict) else {}
        stats = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
        play_addr = video.get("play_addr") if isinstance(video.get("play_addr"), dict) else {}
        comments: list[dict[str, Any]] = []
        if args.with_comments and item.get("aweme_id"):
            comment_params = urllib.parse.urlencode({"aweme_id": item.get("aweme_id"), "count": str(comment_limit), "cursor": "0", "aid": "6383"})
            comment_data = creator_fetch(book, "GET", f"{DOUYIN_HOME_URL}/aweme/v1/web/comment/list/?{comment_params}", "douyin comments")
            for comment in comment_data.get("comments") if isinstance(comment_data.get("comments"), list) else []:
                if not isinstance(comment, dict):
                    continue
                user = comment.get("user") if isinstance(comment.get("user"), dict) else {}
                comments.append({
                    "text": normalize_text(comment.get("text") or ""),
                    "digg_count": comment.get("digg_count") or 0,
                    "nickname": str(user.get("nickname") or ""),
                })
        play_url = (play_addr.get("url_list") or [""])[0] if isinstance(play_addr.get("url_list"), list) else ""
        media_download: dict[str, Any] = {}
        if args.download_media:
            if not play_url:
                media_download = {"status": "skipped", "reason": "empty play_url"}
            elif not video.get("duration"):
                media_download = {"status": "skipped", "reason": "not a video media item"}
            else:
                try:
                    probe = probe_media_url(play_url)
                    size = int(probe.get("content_length") or 0)
                    content_type = str(probe.get("content_type") or "")
                    if content_type and not content_type.startswith("video/"):
                        media_download = {"status": "skipped", "reason": f"content_type={content_type}", **probe}
                    elif max_media_bytes and size > max_media_bytes:
                        media_download = {"status": "skipped", "reason": f"media exceeds {args.max_media_mb} MB", **probe}
                    else:
                        media_path = media_dir / f"{index:03d}_{item.get('aweme_id') or 'unknown'}.mp4"
                        bytes_written = download_media_url(play_url, media_path)
                        media_download = {
                            "status": "downloaded",
                            "path": str(media_path),
                            "bytes": bytes_written,
                            **probe,
                        }
                except Exception as exc:  # noqa: BLE001
                    media_download = {"status": "failed", "reason": str(exc)}
        rows.append({
            "index": index,
            "aweme_id": str(item.get("aweme_id") or ""),
            "title": normalize_text(item.get("desc") or ""),
            "duration": round((video.get("duration") or 0) / 1000) if isinstance(video.get("duration"), (int, float)) else 0,
            "digg_count": stats.get("digg_count") or 0,
            "play_url": play_url,
            "media_download": media_download,
            "top_comments": comments,
        })
        if len(rows) >= count:
            break
    write_records(rows, output_dir, f"抖音用户视频: {args.sec_uid}")
    log(f"写入 {len(rows)} 条用户视频: {output_dir}")
    return 0


def add_common(parser: argparse.ArgumentParser, default_count: int = 20) -> None:
    parser.add_argument("--count", type=int, default=default_count, help="Number of records")
    parser.add_argument("--output", default="", help="Output directory")
    parser.add_argument("--session", default=DEFAULT_SESSION, help="ActionBook session id")
    parser.add_argument("--tab", default=DEFAULT_TAB, help="ActionBook tab id")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Douyin workflow helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    profile = subparsers.add_parser("profile", help="Douyin creator profile")
    profile_sub = profile.add_subparsers(dest="mode", required=True)
    profile_view = profile_sub.add_parser("view", help="View current creator profile")
    add_common(profile_view, default_count=1)
    profile_view.set_defaults(func=run_profile)

    videos = subparsers.add_parser("videos", help="Douyin creator videos")
    videos_sub = videos.add_subparsers(dest="mode", required=True)
    videos_view = videos_sub.add_parser("view", help="View creator video list")
    videos_view.add_argument("--page", type=int, default=1, help="Page number")
    videos_view.add_argument("--status", choices=("all", "published", "reviewing", "scheduled"), default="all")
    add_common(videos_view, default_count=20)
    videos_view.set_defaults(func=run_videos)

    drafts = subparsers.add_parser("drafts", help="Douyin creator drafts")
    drafts_sub = drafts.add_subparsers(dest="mode", required=True)
    drafts_view = drafts_sub.add_parser("view", help="View draft list")
    add_common(drafts_view, default_count=20)
    drafts_view.set_defaults(func=run_drafts)

    collections = subparsers.add_parser("collections", help="Douyin collections")
    collections_sub = collections.add_subparsers(dest="mode", required=True)
    collections_view = collections_sub.add_parser("view", help="View collection list")
    add_common(collections_view, default_count=20)
    collections_view.set_defaults(func=run_collections)

    activities = subparsers.add_parser("activities", help="Douyin official activities")
    activities_sub = activities.add_subparsers(dest="mode", required=True)
    activities_view = activities_sub.add_parser("view", help="View official activities")
    add_common(activities_view, default_count=50)
    activities_view.set_defaults(func=run_activities)

    hashtag = subparsers.add_parser("hashtag", help="Douyin hashtag workflows")
    hashtag_sub = hashtag.add_subparsers(dest="mode", required=True)
    hashtag_view = hashtag_sub.add_parser("view", help="View hashtags")
    hashtag_view.add_argument("--action", choices=("search", "suggest", "hot"), required=True)
    hashtag_view.add_argument("--keyword", default="", help="Keyword for search or hot")
    hashtag_view.add_argument("--cover", default="", help="Cover URI for suggest")
    add_common(hashtag_view, default_count=10)
    hashtag_view.set_defaults(func=run_hashtag)

    location = subparsers.add_parser("location", help="Douyin POI search")
    location_sub = location.add_subparsers(dest="mode", required=True)
    location_view = location_sub.add_parser("view", help="View POI search results")
    location_view.add_argument("--query", required=True, help="Location keyword")
    add_common(location_view, default_count=20)
    location_view.set_defaults(func=run_location)

    stats = subparsers.add_parser("stats", help="Douyin creator video stats")
    stats_sub = stats.add_subparsers(dest="mode", required=True)
    stats_view = stats_sub.add_parser("view", help="View one video metrics")
    stats_view.add_argument("--aweme-id", required=True, help="Douyin aweme_id")
    add_common(stats_view, default_count=10)
    stats_view.set_defaults(func=run_stats)

    user_videos = subparsers.add_parser("user-videos", help="Public Douyin user videos")
    user_videos_sub = user_videos.add_subparsers(dest="mode", required=True)
    user_videos_view = user_videos_sub.add_parser("view", help="View public user videos")
    user_videos_view.add_argument("--sec-uid", required=True, help="Douyin sec_uid from user URL")
    user_videos_view.add_argument("--with-comments", action="store_true", help="Also fetch top comments")
    user_videos_view.add_argument("--comment-limit", type=int, default=10, help="Top comments per video, max 10")
    user_videos_view.add_argument("--download-media", action="store_true", help="Download video media files when play_url points to video/mp4")
    user_videos_view.add_argument("--max-media-mb", type=float, default=50.0, help="Skip one media file if it exceeds this size; 0 disables the limit")
    add_common(user_videos_view, default_count=20)
    user_videos_view.set_defaults(func=run_user_videos)

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
    except LoginRequiredError as exc:
        print("需要你完成抖音登录或安全验证后才能继续。", file=sys.stderr)
        print(f"阻塞位置：{exc}", file=sys.stderr)
        print("请在当前 Chrome 窗口处理上面“阻塞位置”对应的页面，完成登录、验证码或安全验证。", file=sys.stderr)
        print("完成后回复“已登录”或“继续”，我会用同一个 Chrome 会话继续测试。", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
