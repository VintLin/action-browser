#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generic Xiaohongshu workflow helper for the action-browser skill.

It uses ActionBook extension mode and the user's existing Chrome session.
The script intentionally contains only site-operation logic: search, profile
browsing, detail extraction, optional image download, and summary output.
Project-specific filtering, classification, and plan updates belong elsewhere.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import random
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[2]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
from typing import Any

from scripts.actionbook_interrupts import check_interrupt, install_interrupt_handlers, is_interrupted
from scripts.owned_tab_lifecycle import add_workflow_args, attach_workflow
from scripts.actionbook_session import ActionBookSession as ActionBook
from scripts.script_common import log


XHS_HOME = "https://www.xiaohongshu.com"
XHS_EXPLORE = "https://www.xiaohongshu.com/explore"
SKILL_DIR = Path(__file__).resolve().parents[2]
ASSETS_DIR = SKILL_DIR / "assets" / "xiaohongshu"
AI_SEARCH_SOURCE = "web_explore_feed"
SECURITY_TERMS = (
    "website-login/error",
    "error_code=300012",
    "IP存在风险",
    "安全限制",
    "Security Verification",
    "Requests too frequent",
    "Try again later",
)
UNAVAILABLE_TERMS = (
    "error_code=300031",
    "Sorry, This Page Isn't Available Right Now.",
    "你访问的页面不见了",
)


@dataclass
class NoteRef:
    note_id: str
    href: str
    profile_href: str
    title: str
    top: float
    left: float
    source: str


@dataclass
class NotePayload:
    note_id: str
    source_url: str
    candidate_href: str
    author: str
    author_avatar_url: str
    author_profile_url: str
    title: str
    content: str
    tags: list[str]
    date_text: str
    image_urls: list[str]
    comment_image_urls: list[str]
    video_url: str
    video_cover_url: str
    comment_count: int
    comments: list[dict[str, str]]
    is_video: bool


@dataclass
class WorkflowFailure:
    index: int
    source_page: str
    candidate_url: str
    reason: str
    message: str
    context: dict[str, Any]


@dataclass
class AiAnswerPayload:
    keyword: str
    source_url: str
    status: str
    source_count: int | None
    answer: str
    answer_length: int


@dataclass
class ProfileCard:
    note_id: str
    href: str
    profile_href: str
    title: str
    top: float
    left: float
    viewport_top: float
    key: str
def sleep_between(low: float = 0.8, high: float = 1.8) -> None:
    check_interrupt()
    time.sleep(random.uniform(low, high))
    check_interrupt()


def sanitize_name(value: str, fallback: str = "item", max_length: int = 64) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "", value or "").strip("._-")
    return (cleaned or fallback)[:max_length]


def format_download_folder(payload: NotePayload, index: int, template: str = "") -> Path:
    note_id = payload.note_id or extract_note_id(payload.source_url) or f"{index:03d}"
    if not template:
        safe_type = sanitize_name(note_type(payload), fallback="note", max_length=16)
        safe_flags = sanitize_name(note_media_flags(payload), fallback="text", max_length=48)
        safe_author = sanitize_name(payload.author, fallback="unknown", max_length=24)
        return Path(f"{index:03d}_{safe_type}_{safe_flags}_{safe_author}_{note_id}")

    values = {
        "index": index,
        "index3": f"{index:03d}",
        "author": sanitize_name(payload.author, fallback="unknown", max_length=96),
        "title": sanitize_name(payload.title or payload.note_id or "未命名帖子", fallback="未命名帖子", max_length=96),
        "note_id": sanitize_name(note_id, fallback=f"{index:03d}", max_length=64),
        "type": sanitize_name(note_type(payload), fallback="note", max_length=16),
        "media_flags": sanitize_name(note_media_flags(payload), fallback="text", max_length=48),
    }
    try:
        rendered = template.format(**values)
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(f"invalid --folder-template: {template}") from exc

    raw_parts = [part for part in re.split(r"[\\/]+", rendered.strip("/\\")) if part and part != "."]
    if not raw_parts or any(part == ".." for part in raw_parts):
        raise ValueError("--folder-template must produce a relative folder path")
    return Path(*[sanitize_name(part, fallback="item", max_length=96) for part in raw_parts])


def extract_note_id(value: str) -> str:
    match = re.search(r"/explore/([0-9a-z]{16,})", value or "", re.I)
    if match:
        return match.group(1)
    match = re.search(r"/user/profile/[^/]+/([0-9a-z]{16,})", value or "", re.I)
    return match.group(1) if match else ""


def can_direct_open_note_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value or "")
    if not parsed.netloc.endswith("xiaohongshu.com") or not re.search(r"/explore/[0-9a-z]{16,}", parsed.path, re.I):
        return True
    params = urllib.parse.parse_qs(parsed.query)
    return bool(params.get("xsec_token", [""])[0])


def search_result_url(keyword: str) -> str:
    encoded = urllib.parse.quote(keyword)
    return f"https://www.xiaohongshu.com/search_result/?keyword={encoded}&source=web_search_result_notes"


def ai_search_result_url(keyword: str) -> str:
    encoded = urllib.parse.quote(keyword)
    return f"https://www.xiaohongshu.com/search_result_ai?keyword={encoded}&source={AI_SEARCH_SOURCE}"


def extract_profile_id(value: str) -> str:
    match = re.search(r"/user/profile/([^/?#]+)", value or "", re.I)
    return match.group(1) if match else ""


def unique_notes(notes: list[NoteRef]) -> list[NoteRef]:
    seen: set[str] = set()
    result: list[NoteRef] = []
    for note in sorted(notes, key=lambda item: (item.top, item.left, item.note_id or item.title)):
        key = note.note_id or note.href or f"{note.title}|{note.top}|{note.left}"
        if key in seen:
            continue
        seen.add(key)
        result.append(note)
    return result

def get_page_state(book: ActionBook) -> dict[str, Any]:
    state = book.eval(
        """(() => {
            const body = document.body?.innerText || '';
            const href = location.href;
            const title = document.title;
            const detailOpen = !!document.querySelector('#noteContainer')
                || !!document.querySelector('.note-detail-mask')
                || href.includes('/explore/');
            const searchText = document.querySelector('#search-input, input.search-input')?.value || '';
            const filterText = !![...document.querySelectorAll('*')]
                .find(el => (el.innerText || '').trim() === '筛选');
            const searchTabs = [...document.querySelectorAll('*')]
                .filter(el => ['全部', '图文', '视频', '用户'].includes((el.innerText || '').trim())).length;
            const pcSearchLinks = [...document.querySelectorAll('a[href]')]
                .filter(a => (a.href || '').includes('pc_search')).length;
            return {
                href,
                title,
                bodyPreview: body.slice(0, 2000),
                noteItems: document.querySelectorAll('.note-item').length,
                searchText,
                filterText,
                searchTabs,
                pcSearchLinks,
                detailOpen,
            };
        })()"""
    )
    return state if isinstance(state, dict) else {}


def is_search_results_state(state: dict[str, Any]) -> bool:
    href = str(state.get("href") or "")
    title = str(state.get("title") or "")
    search_text = str(state.get("searchText") or "").strip()
    note_items = int(state.get("noteItems") or 0)
    if note_items <= 0:
        return False
    if "/search_result" in href:
        return True
    return title.endswith(" - 小红书搜索") and bool(search_text)


def is_security_or_unavailable(state: dict[str, Any]) -> bool:
    haystack = "\n".join(
        str(state.get(key) or "") for key in ("href", "title", "bodyPreview")
    )
    return any(term in haystack for term in SECURITY_TERMS + UNAVAILABLE_TERMS) or "/login" in haystack


def submit_search(book: ActionBook, keyword: str) -> None:
    log(f"提交搜索关键词: {keyword}")
    result = book.eval(
        f"""(() => {{
            const keyword = {json.dumps(keyword, ensure_ascii=False)};
            const candidates = [
                document.getElementById('search-input'),
                ...document.querySelectorAll('input.search-input, input[placeholder*="搜索"], input[type="search"]'),
            ].filter(Boolean);
            const input = candidates.find(el => {{
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return el.getAttribute('aria-hidden') !== 'true'
                    && String(el.getAttribute('tabindex') || '') !== '-1'
                    && style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && style.pointerEvents !== 'none'
                    && rect.width > 0
                    && rect.height > 0;
            }}) || candidates[0] || null;
            if (!input) return false;
            input.focus();
            input.value = keyword;
            input.dispatchEvent(new InputEvent('input', {{
                bubbles: true,
                data: keyword,
                inputType: 'insertText',
            }}));
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
            for (const type of ['keydown', 'keypress', 'keyup']) {{
                input.dispatchEvent(new KeyboardEvent(type, {{
                    key: 'Enter',
                    code: 'Enter',
                    keyCode: 13,
                    which: 13,
                    bubbles: true,
                }}));
            }}
            return true;
        }})()"""
    )
    if result is not True:
        raise RuntimeError("search input not found or not usable")
    sleep_between(2.0, 3.5)


def wait_for_search_results(book: ActionBook, keyword: str, timeout_secs: float = 25.0, retry_url: str = "") -> None:
    deadline = time.time() + timeout_secs
    attempts = 0
    last_submit_at = 0.0
    last_state: dict[str, Any] = {}
    while time.time() < deadline:
        last_state = get_page_state(book)
        if is_security_or_unavailable(last_state):
            raise RuntimeError(f"Xiaohongshu blocked or redirected the page: {last_state.get('href')}")
        if is_search_results_state(last_state):
            wait_for_result_stability(book)
            return
        if attempts < 2 and time.time() - last_submit_at >= 8.0:
            log(f"重新打开搜索结果页: {keyword}")
            book.goto(retry_url or search_result_url(keyword))
            last_submit_at = time.time()
            attempts += 1
            continue
        sleep_between(0.8, 1.5)
    raise RuntimeError(f"search results did not load: keyword={keyword!r}, state={last_state}")


def wait_for_result_stability(book: ActionBook, checks: int = 2) -> None:
    last_count = -1
    stable_hits = 0
    for _ in range(checks * 4):
        state = get_page_state(book)
        count = int(state.get("noteItems") or 0)
        if count == last_count and count > 0 and is_search_results_state(state):
            stable_hits += 1
            if stable_hits >= checks:
                return
        else:
            last_count = count
            stable_hits = 0
        sleep_between(1.0, 1.6)


def parse_ai_answer_state(keyword: str, state: dict[str, Any]) -> AiAnswerPayload:
    raw_text = str(state.get("rawText") or "").strip()
    raw_blocks = state.get("markdownBlocks")
    markdown_blocks = (
        [str(block).strip() for block in raw_blocks if str(block).strip()]
        if isinstance(raw_blocks, list)
        else []
    )
    source_match = re.search(r"ai总结(\d+)篇笔记生成", raw_text)
    message_class = str(state.get("messageClass") or "")
    if markdown_blocks:
        answer = "\n\n".join(markdown_blocks).strip()
    else:
        answer = re.sub(r"^ai总结\d+篇笔记生成\s*", "", raw_text).strip()

    if "finished" in message_class and answer:
        status = "finished"
    elif raw_text or markdown_blocks:
        status = "generating"
    else:
        status = "missing"

    return AiAnswerPayload(
        keyword=keyword,
        source_url=str(state.get("sourceUrl") or ""),
        status=status,
        source_count=int(source_match.group(1)) if source_match else None,
        answer=answer,
        answer_length=len(answer),
    )


def get_ai_answer_state(book: ActionBook) -> dict[str, Any]:
    state = book.eval(
        """(() => {
            const textOf = el => ((el && (el.innerText || el.textContent)) || '').trim();
            const classOf = el => (typeof el?.className === 'string' ? el.className : '');
            const section = document.querySelector('.ai-chat-section');
            const message = section?.querySelector('.ai-message.ai-message-finished')
                || section?.querySelector('.ai-message');
            const markdownBlocks = [...(section?.querySelectorAll('.markdown-block') || [])]
                .map(textOf)
                .filter(Boolean);
            return {
                sourceUrl: location.href,
                hasAiSection: !!section,
                messageClass: classOf(message),
                rawText: textOf(message),
                markdownBlocks,
            };
        })()"""
    )
    return state if isinstance(state, dict) else {}


def wait_for_ai_answer(book: ActionBook, keyword: str, timeout_secs: float = 35.0) -> AiAnswerPayload:
    deadline = time.time() + timeout_secs
    last_payload = parse_ai_answer_state(keyword, {})
    while time.time() < deadline:
        last_payload = parse_ai_answer_state(keyword, get_ai_answer_state(book))
        if last_payload.status == "finished":
            return last_payload
        sleep_between(1.0, 1.6)
    return last_payload


def collect_visible_notes(book: ActionBook, source: str) -> list[NoteRef]:
    data = book.eval(
        """(() => {
            const absoluteUrl = (value) => {
                if (!value) return '';
                try { return new URL(value, location.origin).toString(); }
                catch (e) { return ''; }
            };
            const extractNoteId = (value) => {
                const raw = String(value || '').trim();
                const match = raw.match(/\\/explore\\/([0-9a-z]{16,})/i)
                    || raw.match(/\\/user\\/profile\\/[^/]+\\/([0-9a-z]{16,})/i);
                return match ? match[1] : '';
            };
            const viewportW = window.innerWidth || document.documentElement.clientWidth || 0;
            const viewportH = window.innerHeight || document.documentElement.clientHeight || 0;
            const isVisible = node => {
                if (!node) return false;
                const rect = node.getBoundingClientRect();
                const style = getComputedStyle(node);
                return rect.width > 0
                    && rect.height > 0
                    && rect.right > 0
                    && rect.left < viewportW
                    && rect.bottom > 80
                    && rect.top < viewportH + 400
                    && style.display !== 'none'
                    && style.visibility !== 'hidden';
            };
            return [...document.querySelectorAll('.note-item')].filter(isVisible).map((item, index) => {
                const rect = item.getBoundingClientRect();
                const anchors = [...item.querySelectorAll('a[href]')].map(anchor => anchor.getAttribute('href') || '');
                const exploreHref = anchors.find(href => /\\/explore\\/[0-9a-z]{16,}/i.test(href)) || '';
                const profileHref = anchors.find(href => /\\/user\\/profile\\/[^/]+\\/[0-9a-z]{16,}/i.test(href)) || '';
                const title =
                    item.querySelector('.title')?.innerText?.trim()
                    || item.querySelector('.desc')?.innerText?.trim()
                    || '';
                const style = item.getAttribute('style') || '';
                const translateMatch = style.match(/translate\\(([-\\d.]+)px,\\s*([-\\d.]+)px\\)/);
                const left = translateMatch ? Number(translateMatch[1]) : rect.left;
                const top = translateMatch ? Number(translateMatch[2]) : (rect.top + window.scrollY);
                const noteId = extractNoteId(exploreHref || profileHref);
                return {
                    note_id: noteId,
                    href: absoluteUrl(profileHref || exploreHref || (noteId ? '/explore/' + noteId : '')),
                    profile_href: absoluteUrl(profileHref),
                    title,
                    top,
                    left,
                };
            }).filter(item => item.note_id || item.href || item.title);
        })()""",
        timeout=40.0,
    )
    if not isinstance(data, list):
        return []
    notes: list[NoteRef] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        notes.append(
            NoteRef(
                note_id=str(item.get("note_id") or ""),
                href=str(item.get("href") or ""),
                profile_href=str(item.get("profile_href") or ""),
                title=str(item.get("title") or ""),
                top=float(item.get("top") or 0),
                left=float(item.get("left") or 0),
                source=source,
            )
        )
    return unique_notes(notes)


def scroll_to_bottom(book: ActionBook) -> int:
    state = book.eval(
        """(() => {
            const step = Math.max(Math.floor((window.innerHeight || 0) * 0.85), 700);
            const containerCandidates = [
                document.querySelector('.tab-content-item'),
                ...document.querySelectorAll('.tab-content-item, .feeds-container, .feeds-page, .note-scroller'),
            ].filter(Boolean);
            const target =
                containerCandidates.find(node =>
                    node.scrollHeight > node.clientHeight + 40
                    && node.querySelector('.note-item')
                )
                || document.scrollingElement
                || document.documentElement
                || document.body;
            const isWindowScroller =
                target === document.scrollingElement
                || target === document.documentElement
                || target === document.body;
            const before = isWindowScroller
                ? (window.scrollY || window.pageYOffset || 0)
                : target.scrollTop;
            if (isWindowScroller) {
                window.scrollTo(0, before + step);
            } else {
                target.scrollTop = before + step;
                target.dispatchEvent(new Event('scroll', { bubbles: true }));
            }
            window.dispatchEvent(new Event('scroll'));
            return {
                before,
                after: isWindowScroller ? (window.scrollY || window.pageYOffset || 0) : target.scrollTop,
                height: isWindowScroller ? (document.documentElement.scrollHeight || 0) : target.scrollHeight,
                clientHeight: isWindowScroller ? (window.innerHeight || 0) : target.clientHeight,
                className: target.className || '',
            };
        })()"""
    )
    sleep_between(2.0, 3.2)
    if isinstance(state, dict):
        return int(state.get("after") or 0)
    return 0


def wait_for_notes_ready(book: ActionBook, source: str, timeout_secs: float = 25.0) -> None:
    deadline = time.time() + timeout_secs
    last_state: dict[str, Any] = {}
    while time.time() < deadline:
        last_state = get_page_state(book)
        if is_security_or_unavailable(last_state):
            raise RuntimeError(f"Xiaohongshu blocked or redirected the page: {last_state.get('href')}")
        if int(last_state.get("noteItems") or 0) > 0:
            return
        sleep_between(0.8, 1.4)
    raise RuntimeError(f"{source} notes did not load: state={last_state}")


def get_active_profile_tab_state(book: ActionBook) -> dict[str, Any]:
    state = book.eval(
        """(() => {
            const textOf = el => (el?.innerText || el?.textContent || '').trim();
            const viewportW = window.innerWidth || document.documentElement.clientWidth || 0;
            const viewportH = window.innerHeight || document.documentElement.clientHeight || 0;
            const visible = node => {
                if (!node) return false;
                const rect = node.getBoundingClientRect();
                const style = getComputedStyle(node);
                return rect.width > 0
                    && rect.height > 0
                    && rect.right > 0
                    && rect.left < viewportW
                    && rect.bottom > 80
                    && rect.top < viewportH + 400
                    && style.display !== 'none'
                    && style.visibility !== 'hidden';
            };
            const tabItems = [...document.querySelectorAll('.reds-tab-item.sub-tab-list, .reds-tabs-list .reds-tab-item, [role="tab"]')]
                .map(node => ({
                    text: textOf(node),
                    className: String(node.className || ''),
                    active: String(node.className || '').includes('active') || node.getAttribute('aria-selected') === 'true',
                }))
                .filter(item => item.text);
            const activeTab = tabItems.find(item => item.active)?.text || '';
            const visibleNotes = [...document.querySelectorAll('.note-item')].filter(visible);
            const bodyText = document.body?.innerText || '';
            return {
                href: location.href,
                activeTab,
                tabItems,
                visibleNoteItems: visibleNotes.length,
                visibleTitles: visibleNotes.slice(0, 10).map(item =>
                    textOf(item.querySelector('.title')) || textOf(item.querySelector('.desc')) || ''
                ),
                emptyFavorites: bodyText.includes('你还没有收藏任何内容哦'),
                emptyLikes: bodyText.includes('你还没有赞过任何内容哦'),
                bodyPreview: bodyText.slice(0, 800),
            };
        })()""",
        timeout=20.0,
    )
    return state if isinstance(state, dict) else {}


def collect_feed_notes(book: ActionBook, source: str, count: int, max_scrolls: int) -> list[NoteRef]:
    notes = collect_visible_notes(book, source)
    idle_rounds = 0
    last_len = len(notes)
    while len(notes) < count and max_scrolls > 0:
        scroll_to_bottom(book)
        notes = unique_notes(notes + collect_visible_notes(book, source))
        if len(notes) <= last_len:
            idle_rounds += 1
        else:
            idle_rounds = 0
            last_len = len(notes)
        if idle_rounds >= 4:
            break
        max_scrolls -= 1
    return notes[:count]


def collect_profile_tab_notes(book: ActionBook, source: str, count: int, max_scrolls: int) -> list[NoteRef]:
    notes = collect_active_profile_tab_notes(book, source)
    idle_rounds = 0
    last_len = len(notes)
    while len(notes) < count and max_scrolls > 0:
        scroll_to_bottom(book)
        notes = unique_notes(notes + collect_active_profile_tab_notes(book, source))
        if len(notes) <= last_len:
            idle_rounds += 1
        else:
            idle_rounds = 0
            last_len = len(notes)
        if idle_rounds >= 4:
            break
        max_scrolls -= 1
    return notes[:count]


def collect_active_profile_tab_notes(book: ActionBook, source: str) -> list[NoteRef]:
    data = book.eval(
        f"""(() => {{
            const source = {json.dumps(source)};
            const tabIndex = source === 'favorites' ? 1 : source === 'likes' ? 2 : 0;
            const absoluteUrl = (value) => {{
                if (!value) return '';
                try {{ return new URL(value, location.origin).toString(); }}
                catch (e) {{ return ''; }}
            }};
            const extractNoteId = (value) => {{
                const raw = String(value || '').trim();
                const match = raw.match(/\\/explore\\/([0-9a-z]{{16,}})/i)
                    || raw.match(/\\/user\\/profile\\/[^/]+\\/([0-9a-z]{{16,}})/i);
                return match ? match[1] : '';
            }};
            let primaryPanes = [...document.querySelectorAll('.user-page > .tab-content-item')];
            if (primaryPanes.length < 3) {{
                primaryPanes = [...document.querySelectorAll('.user-page .tab-content-item')];
            }}
            const pane = primaryPanes[tabIndex] || null;
            if (!pane) return [];
            return [...pane.querySelectorAll('.note-item')].map((item, index) => {{
                const rect = item.getBoundingClientRect();
                const anchors = [...item.querySelectorAll('a[href]')].map(anchor => anchor.getAttribute('href') || '');
                const exploreHref = anchors.find(href => /\\/explore\\/[0-9a-z]{{16,}}/i.test(href)) || '';
                const profileHref = anchors.find(href => /\\/user\\/profile\\/[^/]+\\/[0-9a-z]{{16,}}/i.test(href)) || '';
                const title =
                    item.querySelector('.title')?.innerText?.trim()
                    || item.querySelector('.desc')?.innerText?.trim()
                    || '';
                const noteId = extractNoteId(exploreHref || profileHref);
                return {{
                    note_id: noteId,
                    href: absoluteUrl(profileHref || exploreHref || (noteId ? '/explore/' + noteId : '')),
                    profile_href: absoluteUrl(profileHref),
                    title,
                    top: rect.top + window.scrollY,
                    left: rect.left,
                }};
            }}).filter(item => item.note_id || item.href || item.title);
        }})()""",
        timeout=40.0,
    )
    if not isinstance(data, list):
        return []
    notes: list[NoteRef] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        notes.append(
            NoteRef(
                note_id=str(item.get("note_id") or ""),
                href=str(item.get("href") or ""),
                profile_href=str(item.get("profile_href") or ""),
                title=str(item.get("title") or ""),
                top=float(item.get("top") or 0),
                left=float(item.get("left") or 0),
                source=source,
            )
        )
    return unique_notes(notes)


def get_current_user_profile_url(book: ActionBook) -> str:
    value = book.eval(
        """(() => {
            const abs = value => {
                if (!value) return '';
                try { return new URL(value, location.origin).toString(); }
                catch (e) { return ''; }
            };
            const userState = window.__INITIAL_STATE__?.user || {};
            const unwrap = value => value?._rawValue ?? value?._value ?? value;
            const currentUser = unwrap(userState.userInfo) || unwrap(userState.loggedInUserInfo) || {};
            const userId = currentUser.userId || currentUser.id || '';
            if (userId) return `${location.origin}/user/profile/${userId}`;
            const links = [...document.querySelectorAll('a[href*="/user/profile/"]')]
                .map(anchor => ({
                    href: abs(anchor.getAttribute('href')),
                    text: (anchor.innerText || anchor.getAttribute('aria-label') || '').trim()
                }))
                .filter(item => item.href);
            const selfLink = links.find(item => /我|个人|主页|profile/i.test(item.text)) || links[0];
            return selfLink?.href || '';
        })()""",
        timeout=20.0,
    )
    return str(value or "").strip()


def select_profile_tab(book: ActionBook, labels: tuple[str, ...], source: str) -> None:
    label_list = list(labels)
    clicked = book.eval(
        f"""(() => {{
            const labels = {json.dumps(label_list, ensure_ascii=False)};
            const isVisible = node => {{
                if (!node) return false;
                const rect = node.getBoundingClientRect();
                const style = getComputedStyle(node);
                return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            }};
            const exactText = node => (node?.innerText || node?.textContent || node?.getAttribute?.('aria-label') || '').trim();
            const candidates = [...document.querySelectorAll('.reds-tab-item.sub-tab-list, .reds-tabs-list .reds-tab-item, [role="tab"], button')]
                .filter(isVisible)
                .map(node => {{
                    const text = exactText(node);
                    return {{ node, text }};
                }})
                .filter(item => labels.some(label => item.text === label));
            const target = candidates[0]?.node || null;
            if (!target) return false;
            const clickable = target.closest('.reds-tab-item, button, [role="tab"], a') || target;
            clickable.scrollIntoView({{ behavior: 'instant', block: 'center' }});
            if (typeof clickable.click === 'function') {{
                clickable.click();
                return true;
            }}
            const rect = clickable.getBoundingClientRect();
            const x = rect.left + rect.width / 2;
            const y = rect.top + rect.height / 2;
            for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {{
                clickable.dispatchEvent(new MouseEvent(type, {{
                    bubbles: true,
                    cancelable: true,
                    view: window,
                    clientX: x,
                    clientY: y,
                }}));
            }}
            return true;
        }})()""",
        timeout=20.0,
    )
    if not clicked:
        raise RuntimeError(f"Xiaohongshu {source} tab was not found: labels={label_list}")
    deadline = time.time() + 15.0
    last_state: dict[str, Any] = {}
    while time.time() < deadline:
        last_state = get_active_profile_tab_state(book)
        active_tab = str(last_state.get("activeTab") or "")
        if any(label in active_tab for label in labels):
            return
        sleep_between(0.5, 0.9)
    raise RuntimeError(f"Xiaohongshu {source} tab did not become active: state={last_state}")


def profile_tab_url(profile_url: str, source: str) -> str:
    base = str(profile_url or "").split("?", 1)[0].rstrip("/")
    if source == "favorites":
        return f"{base}?tab=fav&subTab=note"
    if source == "likes":
        return f"{base}?tab=liked"
    return base


def collect_search_notes(book: ActionBook, count: int, max_scrolls: int) -> list[NoteRef]:
    notes = collect_visible_notes(book, "search")
    idle_rounds = 0
    last_len = len(notes)
    while len(notes) < count and max_scrolls > 0:
        scroll_to_bottom(book)
        notes = unique_notes(notes + collect_visible_notes(book, "search"))
        if len(notes) <= last_len:
            idle_rounds += 1
        else:
            idle_rounds = 0
            last_len = len(notes)
        if idle_rounds >= 3:
            break
        max_scrolls -= 1
    return notes[:count]


def get_profile_state(book: ActionBook) -> dict[str, Any]:
    state = book.eval(
        """(() => {
            const userState = window.__INITIAL_STATE__?.user || {};
            const pageData = userState.userPageData?._rawValue || userState.userPageData?._value || {};
            const basicInfo = pageData.basicInfo || {};
            const notes = (userState.notes?._rawValue || userState.notes?._value || []).flat?.() || [];
            return {
                href: location.href,
                title: document.title,
                profileId: basicInfo.userId || userState.userInfo?._rawValue?.userId || '',
                nickname: basicInfo.nickname || document.querySelector('.user-name')?.textContent || '',
                desc: basicInfo.desc || '',
                redId: basicInfo.redId || '',
                noteItems: document.querySelectorAll('.note-item').length,
                noteCount: notes.filter(Boolean).length,
                bodyPreview: document.body?.innerText?.slice(0, 600) || '',
            };
        })()"""
    )
    return state if isinstance(state, dict) else {}


def wait_for_profile(book: ActionBook, profile_url: str, timeout_secs: float = 25.0) -> dict[str, Any]:
    target_id = extract_profile_id(profile_url)
    deadline = time.time() + timeout_secs
    last_state: dict[str, Any] = {}
    while time.time() < deadline:
        last_state = get_profile_state(book)
        if is_security_or_unavailable(last_state):
            raise RuntimeError(f"Xiaohongshu blocked or redirected the profile: {last_state.get('href')}")
        current_id = extract_profile_id(str(last_state.get("href") or ""))
        if current_id == target_id and (last_state.get("nickname") or int(last_state.get("noteItems") or 0) > 0):
            return last_state
        sleep_between(1.0, 1.8)
    raise RuntimeError(f"profile did not become ready: {profile_url}, state={last_state}")


def click_note(book: ActionBook, note: NoteRef) -> bool:
    result = book.eval(
        f"""(() => {{
            const targetNoteId = {json.dumps(note.note_id)};
            const targetHref = {json.dumps((note.href or '').split('?', 1)[0].rstrip('/'))};
            const targetProfileHref = {json.dumps((note.profile_href or '').split('?', 1)[0].rstrip('/'))};
            const targetTitle = {json.dumps(note.title, ensure_ascii=False)};
            const targetTop = {json.dumps(note.top)};
            const targetLeft = {json.dumps(note.left)};
            const items = [...document.querySelectorAll('.note-item')];
            const candidates = items.map((item, index) => {{
                const rect = item.getBoundingClientRect();
                const title = (item.querySelector('.title')?.innerText || item.querySelector('.desc')?.innerText || '').trim();
                const hrefs = [...item.querySelectorAll('a[href]')].map(anchor => (anchor.getAttribute('href') || '').split('?')[0].replace(/\\/$/, ''));
                let score = 0;
                if (targetNoteId && hrefs.some(href => href.includes(targetNoteId))) score += 500;
                if (targetHref && hrefs.some(href => href === targetHref || href.endsWith(targetHref))) score += 400;
                if (targetProfileHref && hrefs.some(href => href === targetProfileHref || href.endsWith(targetProfileHref))) score += 400;
                if (targetTitle && title === targetTitle) score += 120;
                score -= Math.abs((rect.top + window.scrollY) - targetTop) * 0.02;
                score -= Math.abs(rect.left - targetLeft) * 0.1;
                return {{ item, score, rect, index }};
            }}).sort((a, b) => b.score - a.score || a.rect.top - b.rect.top || a.index - b.index);
            const best = candidates[0];
            if (!best || best.score < 80) {{
                const targetScroll = Math.max(targetTop - 300, 0);
                window.scrollTo(0, targetScroll);
                window.dispatchEvent(new Event('scroll'));
                return false;
            }}
            const item = best.item;
            const target =
                item.querySelector('a.cover.mask')
                || [...item.querySelectorAll('a[href]')].find(anchor => {{
                    const href = anchor.getAttribute('href') || '';
                    return (targetNoteId && href.includes(targetNoteId)) || /\\/explore\\/[0-9a-z]{{16,}}/i.test(href);
                }})
                || item.querySelector('.title')
                || item.querySelector('img')
                || item;
            item.scrollIntoView({{ behavior: 'instant', block: 'center' }});
            const rect = target.getBoundingClientRect();
            const x = rect.left + rect.width / 2;
            const y = rect.top + rect.height / 2;
            for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {{
                target.dispatchEvent(new MouseEvent(type, {{
                    bubbles: true,
                    cancelable: true,
                    view: window,
                    clientX: x,
                    clientY: y,
                }}));
            }}
            return true;
        }})()""",
        timeout=40.0,
    )
    sleep_between(1.0, 1.8)
    return bool(result)


def click_note_id_on_current_page(book: ActionBook, note_id: str, source: str = "current") -> bool:
    if not note_id:
        return False
    note = NoteRef(
        note_id=note_id,
        href=f"https://www.xiaohongshu.com/explore/{note_id}",
        profile_href="",
        title="",
        top=0,
        left=0,
        source=source,
    )
    return click_note(book, note)


def is_target_profile_page(book: ActionBook, profile_url: str) -> bool:
    state = get_profile_state(book)
    current_id = extract_profile_id(str(state.get("href") or ""))
    target_id = extract_profile_id(profile_url)
    return bool(current_id and target_id and current_id == target_id)


def ensure_profile_context(book: ActionBook, profile_url: str) -> None:
    if is_target_profile_page(book, profile_url):
        return
    book.goto(profile_url)
    sleep_between(1.2, 2.0)
    wait_for_profile(book, profile_url)


def collect_visible_profile_cards(book: ActionBook) -> list[ProfileCard]:
    data = book.eval(
        """(() => {
            const extractNoteId = (value) => {
                const raw = String(value || '').trim();
                const match = raw.match(/\\/explore\\/([0-9a-z]{16,})/i)
                    || raw.match(/\\/user\\/profile\\/[^/]+\\/([0-9a-z]{16,})/i);
                return match ? match[1] : '';
            };
            const absoluteUrl = (value) => {
                if (!value) return '';
                try { return new URL(value, location.origin).toString(); }
                catch (e) { return ''; }
            };
            const viewportH = window.innerHeight || document.documentElement.clientHeight || 0;
            return [...document.querySelectorAll('.note-item')]
                .map((item, index) => {
                    const rect = item.getBoundingClientRect();
                    const anchors = [...item.querySelectorAll('a[href]')].map(anchor => anchor.getAttribute('href') || '');
                    const exploreHref = anchors.find(href => /\\/explore\\/[0-9a-z]{16,}/i.test(href)) || '';
                    const profileHref = anchors.find(href => /\\/user\\/profile\\/[^/]+\\/[0-9a-z]{16,}/i.test(href)) || '';
                    const noteId = extractNoteId(exploreHref || profileHref);
                    const rawTitle =
                        item.querySelector('.title')?.innerText?.trim()
                        || item.querySelector('.desc')?.innerText?.trim()
                        || '';
                    const title = rawTitle || noteId || '';
                    const visible = rect.bottom > 120 && rect.top < viewportH - 80;
                    const key = noteId || `${title}||${profileHref || exploreHref || index}`;
                    return {
                        note_id: noteId,
                        href: absoluteUrl(exploreHref || (noteId ? `/explore/${noteId}` : '')),
                        profile_href: absoluteUrl(profileHref),
                        title,
                        top: rect.top + window.scrollY,
                        left: rect.left,
                        viewport_top: rect.top,
                        key,
                        visible,
                    };
                })
                .filter(item => item.visible && item.key)
                .map(({ visible, ...item }) => item)
                .sort((a, b) => a.top - b.top || a.left - b.left || a.title.localeCompare(b.title));
        })()""",
        timeout=40.0,
    )
    if not isinstance(data, list):
        return []
    cards: list[ProfileCard] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        card = ProfileCard(
            note_id=str(item.get("note_id") or ""),
            href=str(item.get("href") or ""),
            profile_href=str(item.get("profile_href") or ""),
            title=str(item.get("title") or ""),
            top=float(item.get("top") or 0),
            left=float(item.get("left") or 0),
            viewport_top=float(item.get("viewport_top") or 0),
            key=str(item.get("key") or ""),
        )
        if not card.key or card.key in seen:
            continue
        seen.add(card.key)
        cards.append(card)
    return cards


def current_profile_scroll_y(book: ActionBook) -> float:
    value = book.eval("window.scrollY || window.pageYOffset || 0")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def restore_profile_scroll_y(book: ActionBook, scroll_y: float) -> None:
    book.eval(
        f"""(() => {{
            window.scrollTo(0, Math.max({scroll_y!r}, 0));
            window.dispatchEvent(new Event('scroll'));
            return window.scrollY;
        }})()"""
    )
    sleep_between(0.6, 1.0)


def scroll_profile_by(book: ActionBook, step: int) -> float:
    value = book.eval(
        f"""(() => {{
            window.scrollTo(0, Math.max(window.scrollY + {step}, 0));
            window.dispatchEvent(new Event('scroll'));
            return window.scrollY;
        }})()"""
    )
    try:
        return float(value)
    except (TypeError, ValueError):
        return current_profile_scroll_y(book)


def profile_card_id(card: ProfileCard) -> str:
    return card.note_id or extract_note_id(card.href or card.profile_href)


def next_pending_profile_card(
    book: ActionBook,
    processed_keys: set[str],
    known_note_ids: set[str],
) -> tuple[list[ProfileCard], ProfileCard | None]:
    visible = collect_visible_profile_cards(book)
    pending = [
        card
        for card in visible
        if card.key not in processed_keys and profile_card_id(card) not in known_note_ids
    ]
    pending.sort(key=lambda card: (card.viewport_top, card.left, card.title))
    return visible, (pending[0] if pending else None)


def click_profile_card(book: ActionBook, card: ProfileCard) -> bool:
    result = book.eval(
        f"""(() => {{
            const targetTitle = {json.dumps(card.title, ensure_ascii=False)};
            const targetNoteId = {json.dumps(card.note_id)};
            const targetHref = {json.dumps((card.href or '').split('?', 1)[0].rstrip('/'))};
            const targetProfileHref = {json.dumps((card.profile_href or '').split('?', 1)[0].rstrip('/'))};
            const targetViewportTop = {json.dumps(card.viewport_top)};
            const targetLeft = {json.dumps(card.left)};
            const viewportH = window.innerHeight || document.documentElement.clientHeight || 0;
            const items = [...document.querySelectorAll('.note-item')];
            const candidates = items.map((item, index) => {{
                const rect = item.getBoundingClientRect();
                const title = (item.querySelector('.title')?.innerText || item.querySelector('.desc')?.innerText || '').trim();
                const hrefs = [...item.querySelectorAll('a[href]')]
                    .map(anchor => (anchor.getAttribute('href') || '').split('?')[0].replace(/\\/$/, ''));
                const exploreHref = hrefs.find(href => /\\/explore\\/[0-9a-z]{{16,}}/i.test(href)) || '';
                const profileHref = hrefs.find(href => /\\/user\\/profile\\/[^/]+\\/[0-9a-z]{{16,}}/i.test(href)) || '';
                let score = 0;
                if (targetProfileHref && profileHref === targetProfileHref) score += 1000;
                if (targetHref && exploreHref === targetHref) score += 1000;
                if (targetNoteId && hrefs.some(href => href.includes(targetNoteId))) score += 300;
                if (targetTitle && title === targetTitle) score += 120;
                score -= Math.abs(rect.top - targetViewportTop);
                score -= Math.abs(rect.left - targetLeft) * 0.2;
                return {{ item, score, rect, index }};
            }}).sort((a, b) => b.score - a.score || a.rect.top - b.rect.top || a.index - b.index);
            const best = candidates[0];
            if (!best || best.score < 80) return false;
            const item = best.item;
            if (!item) return false;
            if (best.rect.top < 90 || best.rect.bottom > viewportH - 50) {{
                const delta = best.rect.top < 90 ? best.rect.top - 110 : best.rect.bottom - (viewportH - 90);
                window.scrollTo(0, Math.max(window.scrollY + delta, 0));
                window.dispatchEvent(new Event('scroll'));
            }}
            const target =
                item.querySelector('a.cover.mask')
                || [...item.querySelectorAll('a[href]')].find(anchor => {{
                    const href = anchor.getAttribute('href') || '';
                    return (targetProfileHref && href === targetProfileHref)
                        || (targetHref && href === targetHref)
                        || (targetNoteId && href.includes(targetNoteId));
                }})
                || item.querySelector('.title')
                || item.querySelector('img')
                || item;
            const rect = target.getBoundingClientRect();
            const x = rect.left + rect.width / 2;
            const y = rect.top + rect.height / 2;
            for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {{
                target.dispatchEvent(new MouseEvent(type, {{
                    bubbles: true,
                    cancelable: true,
                    view: window,
                    clientX: x,
                    clientY: y,
                }}));
            }}
            return true;
        }})()""",
        timeout=40.0,
    )
    sleep_between(1.0, 1.8)
    return bool(result)


def locate_profile_anchor_and_advance(book: ActionBook, anchor: ProfileCard) -> bool:
    for _ in range(18):
        result = book.eval(
            f"""(() => {{
                const targetTitle = {json.dumps(anchor.title, ensure_ascii=False)};
                const targetNoteId = {json.dumps(anchor.note_id)};
                const targetHref = {json.dumps((anchor.href or '').split('?', 1)[0].rstrip('/'))};
                const targetProfileHref = {json.dumps((anchor.profile_href or '').split('?', 1)[0].rstrip('/'))};
                const targetViewportTop = {json.dumps(anchor.viewport_top)};
                const targetLeft = {json.dumps(anchor.left)};
                const items = [...document.querySelectorAll('.note-item')];
                const candidates = items.map((item, index) => {{
                    const rect = item.getBoundingClientRect();
                    const title = (item.querySelector('.title')?.innerText || item.querySelector('.desc')?.innerText || '').trim();
                    const hrefs = [...item.querySelectorAll('a[href]')]
                        .map(anchorEl => (anchorEl.getAttribute('href') || '').split('?')[0].replace(/\\/$/, ''));
                    const exploreHref = hrefs.find(href => /\\/explore\\/[0-9a-z]{{16,}}/i.test(href)) || '';
                    const profileHref = hrefs.find(href => /\\/user\\/profile\\/[^/]+\\/[0-9a-z]{{16,}}/i.test(href)) || '';
                    let score = 0;
                    if (targetProfileHref && profileHref === targetProfileHref) score += 1000;
                    if (targetHref && exploreHref === targetHref) score += 1000;
                    if (targetNoteId && hrefs.some(href => href.includes(targetNoteId))) score += 300;
                    if (targetTitle && title === targetTitle) score += 120;
                    score -= Math.abs(rect.top - targetViewportTop);
                    score -= Math.abs(rect.left - targetLeft) * 0.2;
                    return {{ item, score, rect, index }};
                }}).sort((a, b) => b.score - a.score || a.rect.top - b.rect.top || a.index - b.index);
                const best = candidates[0];
                if (!best || best.score < 80) return {{ found: false, scrollY: window.scrollY }};
                const rect = best.item.getBoundingClientRect();
                const absoluteTop = rect.top + window.scrollY;
                const targetTop = Math.max(absoluteTop - 120, 0);
                window.scrollTo(0, targetTop);
                window.dispatchEvent(new Event('scroll'));
                return {{ found: true, scrollY: window.scrollY }};
            }})()""",
            timeout=40.0,
        )
        if isinstance(result, dict) and result.get("found"):
            sleep_between(1.0, 1.6)
            book.eval(
                """(() => {
                    const step = Math.max(Math.floor((window.innerHeight || 0) * 0.72), 420);
                    window.scrollTo(0, window.scrollY + step);
                    window.dispatchEvent(new Event('scroll'));
                    return { scrollY: window.scrollY };
                })()"""
            )
            sleep_between(1.2, 1.8)
            return True
        before = current_profile_scroll_y(book)
        scroll_profile_by(book, 600)
        sleep_between(1.2, 1.8)
        if current_profile_scroll_y(book) <= before + 5:
            break
    return False


def advance_profile_batch(
    book: ActionBook,
    visible: list[ProfileCard],
    processed_keys: set[str],
    known_note_ids: set[str],
) -> bool:
    before_keys = {card.key for card in visible}
    if visible:
        anchor = visible[max(0, len(visible) - 1)]
        locate_profile_anchor_and_advance(book, anchor)
        sleep_between(1.2, 1.8)
    else:
        scroll_profile_by(book, 700)
        sleep_between(1.2, 1.8)

    for _ in range(10):
        current_visible = collect_visible_profile_cards(book)
        current_keys = {card.key for card in current_visible}
        has_pending = any(
            card.key not in processed_keys and profile_card_id(card) not in known_note_ids
            for card in current_visible
        )
        if current_keys != before_keys and (has_pending or current_keys):
            return True
        before = current_profile_scroll_y(book)
        scroll_profile_by(book, 360)
        sleep_between(1.0, 1.6)
        if current_profile_scroll_y(book) <= before + 5:
            break
    return False


def wait_for_detail(book: ActionBook, timeout_secs: float = 12.0) -> dict[str, Any]:
    deadline = time.time() + timeout_secs
    last_state: dict[str, Any] = {}
    while time.time() < deadline:
        last_state = get_page_state(book)
        if is_security_or_unavailable(last_state):
            return last_state
        detail_state = book.eval(
            """(() => ({
                noteContainer: !!document.querySelector('#noteContainer'),
                detailMask: !!document.querySelector('.note-detail-mask'),
                detailIframes: [...document.querySelectorAll('iframe')]
                    .filter(frame => (frame.src || '').includes('/explore/')).length,
                href: location.href,
            }))()"""
        )
        if isinstance(detail_state, dict) and (
            detail_state.get("noteContainer")
            or detail_state.get("detailMask")
            or int(detail_state.get("detailIframes") or 0) > 0
            or "/explore/" in str(detail_state.get("href") or "")
        ):
            return last_state
        sleep_between(0.5, 1.0)
    return last_state


def extract_payload(book: ActionBook, candidate_href: str) -> NotePayload | None:
    for _ in range(10):
        payload = book.eval(
            """(() => {
                const docs = [document];
                for (const frame of document.querySelectorAll('iframe')) {
                    try {
                        if (frame.contentDocument) docs.push(frame.contentDocument);
                    } catch (e) {}
                }
                const container = docs.map(doc => doc.querySelector('#noteContainer')).find(Boolean);
                if (!container) return null;
                const containerDoc = container.ownerDocument;
                const textOf = el => (el?.innerText || el?.textContent || '').trim();
                const attrOf = (el, name) => (el?.getAttribute?.(name) || '').trim();
                const normalizeTag = value => value.replace(/^#+/, '').trim();
                const normalizeLines = value => value.split('\\n').map(line => line.trim()).filter(Boolean);
                const normalizeUrl = value => String(value || '').replace(/^http:\\/\\//i, 'https://').trim();
                const normalizeCommentContent = value => normalizeLines(value)
                    .filter(line =>
                        line
                        && line !== '赞'
                        && line !== '回复'
                        && !/^展开\\s*\\d+\\s*条回复$/.test(line)
                        && !/^收起$/.test(line)
                    )
                    .join('\\n')
                    .trim();
                const sourceCandidates = [
                    containerDoc.location?.href || '',
                    ...docs.map(doc => doc.location?.href || ''),
                    ...[...document.querySelectorAll('iframe')].map(frame => frame.src || ''),
                    location.href,
                ].filter(Boolean);
                const sourceUrl = sourceCandidates.find(url => /\\/explore\\/[0-9a-z]{16,}/i.test(url))
                    || sourceCandidates[0]
                    || '';
                const stateNoteStore = window.__INITIAL_STATE__?.note || {};
                const unwrap = value => value?._rawValue ?? value?._value ?? value;
                const stateNoteMap = unwrap(stateNoteStore.noteDetailMap) || {};
                const sourceNoteId = (sourceUrl.match(/\\/explore\\/([0-9a-z]{16,})/i) || [])[1] || '';
                const stateNoteId =
                    stateNoteStore.currentNoteId
                    || sourceNoteId
                    || Object.keys(stateNoteMap).find(key => key && key !== 'undefined')
                    || '';
                const stateEntry = stateNoteMap[stateNoteId] || {};
                const stateNote = stateEntry.note || {};
                const stateComments = stateEntry.comments || {};
                const stateDesc = String(stateNote.desc || '')
                    .replace(/\\[话题\\]/g, '')
                    .replace(/\\s+/g, ' ')
                    .trim();
                const authorNode =
                    container.querySelector('.author-container')
                    || container.querySelector('[class*="author"]');
                const author =
                    String(stateNote.user?.nickname || stateNote.user?.name || '').trim()
                    || textOf(authorNode?.querySelector('.username'))
                    || textOf(container.querySelector('.username'))
                    || textOf(container.querySelector('[class*="author"] [class*="name"]'))
                    || '';
                const authorAvatarUrl =
                    normalizeUrl(stateNote.user?.avatar)
                    || normalizeUrl(stateNote.user?.images)
                    || normalizeUrl(authorNode?.querySelector('img')?.currentSrc)
                    || authorNode?.querySelector('img')?.src
                    || container.querySelector('img[class*="avatar"]')?.currentSrc
                    || container.querySelector('img[class*="avatar"]')?.src
                    || '';
                const authorProfileUrl =
                    (stateNote.user?.userId ? `${location.origin}/user/profile/${stateNote.user.userId}` : '')
                    || normalizeUrl(stateNote.user?.profileUrl)
                    || authorNode?.closest('a[href*="/user/profile/"]')?.href
                    || authorNode?.querySelector('a[href*="/user/profile/"]')?.href
                    || container.querySelector('a[href*="/user/profile/"]')?.href
                    || '';
                const noteContentNode =
                    container.querySelector('.note-content')
                    || container.querySelector('#detail-desc')
                    || container.querySelector('.note-scroller')
                    || container;
                const title =
                    String(stateNote.title || '').trim()
                    || textOf(container.querySelector('#detail-title'))
                    || textOf(container.querySelector('.note-content .title'))
                    || '';
                const noteText =
                    stateDesc
                    || textOf(noteContentNode?.querySelector('.desc'))
                    || textOf(container.querySelector('#detail-desc .note-text'))
                    || textOf(container.querySelector('#detail-desc'))
                    || textOf(container.querySelector('.note-content .desc'))
                    || '';
                const lines = normalizeLines(noteText);
                const ignored = new Set(['关注', '评论', '发送', '取消', '这是一片荒地点击评论']);
                const isDateLine = line =>
                    /^20\\d{2}[-/.年]\\d{1,2}[-/.月]\\d{1,2}(?:日)?(?:\\s+\\d{1,2}:\\d{2})?$/.test(line)
                    || /^\\d{2}-\\d{2}$/.test(line)
                    || /^\\d{4}年\\d{1,2}月\\d{1,2}日(?:\\s+\\d{1,2}:\\d{2})?$/.test(line)
                    || /^(?:刚刚|\\d+分钟前|\\d+小时前|\\d+天前)(?:\\s*.*)?$/.test(line)
                    || /^(?:昨天|今天|前天)(?:\\s+\\d{1,2}:\\d{2})?(?:\\s*.*)?$/.test(line)
                    || /^编辑于\\s*.+$/.test(line);
                const dateCandidates = [
                    textOf(noteContentNode?.querySelector('.bottom-container .date')),
                    textOf(noteContentNode?.querySelector('.date')),
                    ...textOf(noteContentNode).split('\\n').map(line => line.trim()),
                ].filter(Boolean);
                const dateText = dateCandidates.find(line => isDateLine(line)) || '';
                const bodyLines = lines.filter(line =>
                    line
                    && !ignored.has(line)
                    && line !== author
                    && line !== title
                    && !/^\\d+\\/\\d+$/.test(line)
                    && !isDateLine(line)
                    && !/^共\\s*\\d+\\s*条评论$/.test(line)
                );
                const tagCandidates = [
                    ...noteContentNode.querySelectorAll('a, .note-tag, [class*="tag"]'),
                ]
                    .map(el => textOf(el))
                    .map(normalizeTag)
                    .filter(Boolean)
                    .filter(value =>
                        value.length <= 40
                        && !ignored.has(value)
                        && value !== author
                        && value !== title
                        && !/^共\\s*\\d+\\s*条评论$/.test(value)
                    );
                const inlineTags = [...noteText.matchAll(/#([^#\\s][^#\\n]{0,30})/g)]
                    .map(match => normalizeTag(match[1] || ''))
                    .filter(Boolean);
                const stateTags = (stateNote.tagList || [])
                    .map(tag => normalizeTag(tag?.name || tag || ''))
                    .filter(Boolean);
                const tags = [...new Set([...stateTags, ...tagCandidates, ...inlineTags])];
                const stateImageUrls = [...new Set(
                    (stateNote.imageList || [])
                        .flatMap(image => [
                            image?.urlDefault,
                            image?.urlPre,
                            image?.url,
                            ...(image?.infoList || []).map(info => info?.url || ''),
                        ])
                        .map(normalizeUrl)
                        .filter(src =>
                            src
                            && src.startsWith('https://')
                            && src.includes('xhscdn.com')
                            && !src.includes('/comment/')
                            && !src.includes('avatar')
                            && !src.includes('user-avatar')
                            && !src.includes('fe-platform')
                        )
                )];
                const imageCandidates = [
                    ...container.querySelectorAll('.note-slider-img img'),
                    ...container.querySelectorAll('.swiper-slide img'),
                    ...container.querySelectorAll('.carousel-container img'),
                    ...container.querySelectorAll('.note-image-box img'),
                ];
                const domImageUrls = [...new Set(imageCandidates
                    .map(img => normalizeUrl(img.currentSrc || img.src || img.getAttribute('data-src') || ''))
                    .filter(src =>
                        src
                        && src.startsWith('https://')
                        && src.includes('xhscdn.com')
                        && !src.includes('/comment/')
                        && !src.includes('avatar')
                        && !src.includes('user-avatar')
                        && !src.includes('fe-platform')
                    ))];
                const imageUrls = stateImageUrls.length ? stateImageUrls : domImageUrls;
                const galleryHintMatch =
                    (container.innerText || '').match(/(?:^|\\n)\\s*(\\d+)\\s*\\/\\s*(\\d+)\\s*(?:\\n|$)/);
                const imageTotalHint = Number(galleryHintMatch?.[2] || 0);
                const videoNode =
                    container.querySelector('video')
                    || containerDoc.querySelector('video');
                const parseCssUrl = value => {
                    const match = String(value || '').match(/url\\((['"]?)(.*?)\\1\\)/i);
                    return match ? match[2] : '';
                };
                const stateVideo = stateNote.video || {};
                const stateVideoMedia = stateVideo.media || {};
                const posterNode =
                    container.querySelector('.xgplayer-poster')
                    || containerDoc.querySelector('.xgplayer-poster')
                    || container.querySelector('[class*="poster"]')
                    || containerDoc.querySelector('[class*="poster"]');
                const videoUrl =
                    normalizeUrl(stateVideoMedia.stream?.h264?.[0]?.masterUrl)
                    || normalizeUrl(stateVideo.consumer?.originVideoKey)
                    || normalizeUrl(videoNode?.currentSrc)
                    || videoNode?.src
                    || '';
                const videoCoverUrl =
                    normalizeUrl(stateVideo.image?.urlDefault)
                    || normalizeUrl(stateVideo.image?.urlPre)
                    || normalizeUrl(videoNode?.poster)
                    || parseCssUrl(posterNode ? getComputedStyle(posterNode).backgroundImage : '')
                    || parseCssUrl(posterNode?.getAttribute?.('style') || '')
                    || [...container.querySelectorAll('img')]
                        .map(img => normalizeUrl(img.currentSrc || img.src || img.getAttribute('data-src') || ''))
                        .find(src =>
                            src
                            && src.startsWith('https://')
                            && src.includes('xhscdn.com')
                            && !src.includes('avatar')
                            && !src.includes('fe-platform')
                            && !src.includes('/comment/')
                        )
                    || '';
                const commentNodes = [
                    ...container.querySelectorAll('.comment-item'),
                    ...container.querySelectorAll('.parent-comment'),
                    ...container.querySelectorAll('.root-comment'),
                    ...container.querySelectorAll('[class*="comment-item"]'),
                ];
                const commentImageUrls = [...new Set(
                    [...container.querySelectorAll('.comment-picture img')]
                        .map(img => normalizeUrl(img.currentSrc || img.src || img.getAttribute('data-src') || ''))
                        .filter(src =>
                            src
                            && src.startsWith('https://')
                            && src.includes('xhscdn.com')
                            && !src.includes('avatar')
                            && !src.includes('fe-platform')
                        )
                )];
                const comments = [];
                const seenComments = new Set();
                for (const node of commentNodes) {
                    const authorName =
                        textOf(node.querySelector('.name'))
                        || textOf(node.querySelector('.author'))
                        || textOf(node.querySelector('[class*="name"]'))
                        || '';
                    const commentContent = normalizeCommentContent(
                        textOf(node.querySelector('.content'))
                        || textOf(node.querySelector('.comment-content'))
                        || textOf(node.querySelector('[class*="content"]'))
                        || ''
                    );
                    const commentDate =
                        textOf(node.querySelector('.date'))
                        || textOf(node.querySelector('.time'))
                        || textOf(node.querySelector('[class*="date"]'))
                        || textOf(node.querySelector('[class*="time"]'))
                        || '';
                    const avatarUrl =
                        node.querySelector('img')?.currentSrc
                        || node.querySelector('img')?.src
                        || '';
                    const imageUrls = [...new Set(
                        [...node.querySelectorAll('.comment-picture img')]
                            .map(img => normalizeUrl(img.currentSrc || img.src || img.getAttribute('data-src') || ''))
                            .filter(src =>
                                src
                                && src.startsWith('https://')
                                && src.includes('xhscdn.com')
                                && !src.includes('avatar')
                                && !src.includes('fe-platform')
                            )
                    )];
                    const key = [authorName, commentContent, commentDate].join('|');
                    if (!authorName || !commentContent || seenComments.has(key)) continue;
                    seenComments.add(key);
                    comments.push({
                        author: authorName,
                        avatar_url: avatarUrl,
                        content: commentContent,
                        date_text: commentDate,
                        image_urls: imageUrls,
                    });
                    if (comments.length >= 20) break;
                }
                const commentCountText = [
                    String(stateNote.interactInfo?.commentCount || ''),
                    textOf(container.querySelector('.comment-count')),
                    ...normalizeLines(container.innerText).filter(line => /^共\\s*\\d+\\s*条评论$/.test(line)),
                ].find(Boolean) || '';
                const commentCount = Number((commentCountText.match(/(\\d+)/) || [])[1] || comments.length || 0);
                const isVideo = !!stateNote.video
                    || !!container.querySelector('video')
                    || !!container.querySelector('[class*="video"]')
                    || !!containerDoc.querySelector('video');
                const noteId = (sourceUrl.match(/\\/explore\\/([0-9a-z]{16,})/i) || [])[1] || '';
                return {
                    note_id: noteId || stateNoteId,
                    source_url: sourceUrl,
                    author,
                    author_avatar_url: authorAvatarUrl,
                    author_profile_url: authorProfileUrl,
                    title,
                    content: bodyLines.join('\\n') || stateDesc,
                    tags,
                    date_text: dateText,
                    image_urls: imageUrls,
                    image_total_hint: imageTotalHint,
                    comment_image_urls: commentImageUrls,
                    video_url: videoUrl,
                    video_cover_url: videoCoverUrl,
                    comment_count: commentCount,
                    comments,
                    is_video: isVideo,
                };
            })()""",
            timeout=45.0,
        )
        if isinstance(payload, dict):
            image_urls = [str(url) for url in payload.get("image_urls") or []]
            image_total_hint = int(payload.get("image_total_hint") or 0)
            date_text = str(payload.get("date_text") or "").strip()
            content = str(payload.get("content") or "").strip()
            title = str(payload.get("title") or "").strip()
            if image_total_hint > 1 and len(image_urls) < image_total_hint:
                sleep_between(0.8, 1.3)
                continue
            if title and not content and date_text in {"", "刚刚"}:
                sleep_between(0.8, 1.3)
                continue
            return NotePayload(
                note_id=str(payload.get("note_id") or extract_note_id(str(payload.get("source_url") or ""))),
                source_url=str(payload.get("source_url") or ""),
                candidate_href=candidate_href,
                author=str(payload.get("author") or ""),
                author_avatar_url=str(payload.get("author_avatar_url") or ""),
                author_profile_url=str(payload.get("author_profile_url") or ""),
                title=title,
                content=content,
                tags=[str(tag) for tag in payload.get("tags") or []],
                date_text=date_text,
                image_urls=image_urls,
                comment_image_urls=[str(url) for url in payload.get("comment_image_urls") or []],
                video_url=str(payload.get("video_url") or ""),
                video_cover_url=str(payload.get("video_cover_url") or ""),
                comment_count=int(payload.get("comment_count") or 0),
                comments=[
                    {
                        "author": str(comment.get("author") or ""),
                        "avatar_url": str(comment.get("avatar_url") or ""),
                        "content": str(comment.get("content") or ""),
                        "date_text": str(comment.get("date_text") or ""),
                        "image_urls": [str(url) for url in comment.get("image_urls") or []],
                    }
                    for comment in (payload.get("comments") or [])
                    if isinstance(comment, dict)
                ],
                is_video=bool(payload.get("is_video")),
            )
        sleep_between(0.6, 1.0)
    return None


def close_detail(book: ActionBook) -> str:
    def is_open() -> bool:
        state = book.eval(
            """(() => !!document.querySelector('#noteContainer')
                || !!document.querySelector('.note-detail-mask')
                || String(location.href || '').includes('/explore/'))()"""
        )
        return bool(state)

    def wait_closed(timeout_secs: float) -> bool:
        deadline = time.time() + timeout_secs
        while time.time() < deadline:
            if not is_open():
                return True
            sleep_between(0.25, 0.45)
        return not is_open()

    if not is_open():
        return "already_closed"

    clicked = book.eval(
        """(() => {
            const clickLikeUser = (node) => {
                if (!node) return false;
                const target = node.closest('button,[role="button"],a,div,span') || node;
                const rect = target.getBoundingClientRect();
                if (!(rect.width > 0 && rect.height > 0)) return false;
                const x = rect.left + rect.width / 2;
                const y = rect.top + rect.height / 2;
                for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                    target.dispatchEvent(new MouseEvent(type, {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX: x,
                        clientY: y,
                    }));
                }
                return true;
            };
            const closeNode =
                document.querySelector('button.close-icon')
                || document.querySelector('.close-icon')
                || document.querySelector('[class*="close-icon"]')
                || document.querySelector('[aria-label="关闭"]')
                || document.querySelector('[title="关闭"]');
            return clickLikeUser(closeNode);
        })()"""
    )
    if clicked:
        sleep_between(0.5, 0.9)
        if wait_closed(3.0):
            return "close_button"

    book.eval(
        """(() => {
            for (const type of ['keydown', 'keyup']) {
                document.dispatchEvent(new KeyboardEvent(type, {
                    key: 'Escape',
                    code: 'Escape',
                    keyCode: 27,
                    which: 27,
                    bubbles: true,
                    cancelable: true,
                }));
            }
            return true;
        })()"""
    )
    sleep_between(0.4, 0.8)
    if wait_closed(3.0):
        return "escape"

    book.eval("window.history.back(); true")
    sleep_between(0.8, 1.4)
    if wait_closed(4.0):
        return "history_back"
    return "still_open"


def download_image(url: str, output_dir: Path, index: int) -> str | None:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.xiaohongshu.com/",
    }
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log(f"图片下载失败: index={index} reason={exc}")
        return None
    ext = mimetypes.guess_extension(content_type) or Path(url.split("?", 1)[0]).suffix or ".jpg"
    if ext == ".jpe":
        ext = ".jpg"
    name = f"img-{index:02d}{ext}"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / name).write_bytes(data)
    return name


def note_media_flags(payload: NotePayload) -> str:
    flags: list[str] = []
    if payload.image_urls:
        flags.append("image")
    if payload.is_video or payload.video_url or payload.video_cover_url:
        flags.append("video")
    if payload.comment_image_urls:
        flags.append("comment_image")
    if not flags:
        flags.append("text")
    return "_".join(flags)


def note_type(payload: NotePayload) -> str:
    return "video" if payload.is_video or payload.video_url or payload.video_cover_url else "note"


def render_raw_text(payload: NotePayload) -> str:
    lines = [
        "# 小红书原始可见文本",
        "",
        f"- 类型: {note_type(payload)}",
        f"- 作者: {payload.author or 'unknown'}",
        f"- 日期: {payload.date_text or ''}",
        f"- 来源: {payload.source_url or payload.candidate_href}",
        f"- 标题: {payload.title or ''}",
        "",
        "## 指标说明",
        "",
        f"- 评论数: {payload.comment_count}",
        f"- 正文图片数: {len(payload.image_urls)}",
        f"- 评论图片数: {len(payload.comment_image_urls)}",
        f"- 视频: {'是' if payload.is_video else '否'}",
        "",
        "## 正文",
        "",
        payload.content.strip() or "(无正文)",
    ]
    if payload.comments:
        lines.extend(["", "## 评论", ""])
        for comment in payload.comments:
            lines.append(
                f"- {comment.get('author') or 'unknown'}"
                f" [{comment.get('date_text') or ''}]: {comment.get('content') or ''}"
            )
    return "\n".join(lines).strip() + "\n"


def render_note_markdown(payload: NotePayload, saved_images: list[str]) -> str:
    lines = [
        f"# {payload.title or payload.note_id or '小红书笔记'}",
        "",
        f"- 类型: {note_type(payload)}",
        f"- 作者: {payload.author or 'unknown'}",
        f"- 作者主页: {payload.author_profile_url or ''}",
        f"- 日期: {payload.date_text or ''}",
        f"- 来源: {payload.source_url or payload.candidate_href}",
        f"- 标签: {', '.join(payload.tags)}",
        f"- 评论数: {payload.comment_count}",
        f"- 正文图片数: {len(payload.image_urls)}",
        f"- 评论图片数: {len(payload.comment_image_urls)}",
        f"- 视频地址: {payload.video_url or ''}",
        f"- 视频封面: {payload.video_cover_url or ''}",
        "",
        "## 正文",
        "",
        payload.content.strip() or "(无正文)",
    ]
    if saved_images:
        lines.extend(["", "## 图片", ""])
        for image_name in saved_images:
            lines.extend([f"![{image_name}]({image_name})", ""])
    if payload.comments:
        lines.extend(["", "## 评论", ""])
        for comment in payload.comments:
            lines.append(
                f"- {comment.get('author') or 'unknown'}"
                f" [{comment.get('date_text') or ''}]: {comment.get('content') or ''}"
            )
    return "\n".join(lines).strip() + "\n"


def write_note_download(
    payload: NotePayload,
    output_dir: Path,
    index: int,
    folder_template: str = "",
    media_layout: str = "media",
) -> Path:
    relative_folder = format_download_folder(payload, index, folder_template)
    folder = output_dir / relative_folder
    temp = folder.parent / f".{folder.name}.partial"
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True, exist_ok=False)
    saved_images: list[str] = []
    try:
        media_dir = temp / "media" if media_layout == "media" else temp
        for image_index, image_url in enumerate(payload.image_urls, start=1):
            image_name = download_image(image_url, media_dir, image_index)
            if image_name:
                saved_images.append(f"media/{image_name}" if media_layout == "media" else image_name)
                sleep_between(0.8, 1.5)
        markdown = render_note_markdown(payload, saved_images)
        (temp / "content.md").write_text(markdown, encoding="utf-8")
        (temp / "content.txt").write_text(markdown, encoding="utf-8")
        (temp / "raw.txt").write_text(render_raw_text(payload), encoding="utf-8")
        metadata = asdict(payload)
        metadata["saved_images"] = saved_images
        metadata["note_type"] = note_type(payload)
        metadata["media_flags"] = note_media_flags(payload)
        metadata["media_layout"] = media_layout
        (temp / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        final = folder
        suffix = 2
        while final.exists():
            final = folder.parent / f"{folder.name}-{suffix}"
            suffix += 1
        temp.replace(final)
        return final
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def write_summary(
    payloads: list[NotePayload],
    output_dir: Path,
    title: str,
    failures: list[WorkflowFailure] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = [asdict(payload) for payload in payloads]
    (output_dir / "summary.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [f"# {title}", "", f"- 帖子数: {len(payloads)}", ""]
    for index, payload in enumerate(payloads, start=1):
        lines.extend(
            [
                f"## {index}. {payload.title or payload.note_id or '未命名帖子'}",
                "",
                f"- 作者: {payload.author or 'unknown'}",
                f"- 日期: {payload.date_text or ''}",
                f"- 来源: {payload.source_url or payload.candidate_href}",
                f"- 标签: {', '.join(payload.tags) if payload.tags else ''}",
                f"- 图片数: {len(payload.image_urls)}",
                f"- 评论图片数: {len(payload.comment_image_urls)}",
                f"- 评论数: {payload.comment_count}",
                f"- 视频地址: {payload.video_url or ''}",
                f"- 视频封面: {payload.video_cover_url or ''}",
                f"- 视频: {'是' if payload.is_video else '否'}",
                "",
                payload.content[:800].strip() or "(无正文)",
                "",
            ]
        )
    (output_dir / "summary.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    failure_records = [asdict(item) for item in (failures or [])]
    (output_dir / "failures.json").write_text(
        json.dumps(failure_records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_ai_answer(payload: AiAnswerPayload, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    record = asdict(payload)
    (output_dir / "ai_answer.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    source_count = "" if payload.source_count is None else str(payload.source_count)
    lines = [
        f"# 点点 AI 回答: {payload.keyword}",
        "",
        f"- 状态: {payload.status}",
        f"- 来源: {payload.source_url}",
        f"- 总结笔记数: {source_count}",
        f"- 回答字数: {payload.answer_length}",
        "",
        payload.answer or "(无回答)",
        "",
    ]
    (output_dir / "ai_answer.md").write_text("\n".join(lines), encoding="utf-8")


def load_existing_profile_note_ids(output_dir: Path) -> set[str]:
    note_ids: set[str] = set()
    if not output_dir.exists():
        return note_ids
    for metadata_path in output_dir.rglob("metadata.json"):
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        note_id = str(payload.get("note_id") or extract_note_id(str(payload.get("source_url") or ""))).strip()
        if note_id:
            note_ids.add(note_id)
    return note_ids


def process_profile_notes(
    book: ActionBook,
    profile_url: str,
    action: str,
    output_dir: Path,
    title: str,
    count: int | None,
    max_batches: int,
    max_idle_batches: int,
    folder_template: str = "",
    media_layout: str = "media",
) -> list[NotePayload]:
    payloads: list[NotePayload] = []
    processed_keys: set[str] = set()
    known_note_ids = load_existing_profile_note_ids(output_dir)
    idle_batches = 0
    batch_no = 0

    output_dir.mkdir(parents=True, exist_ok=True)
    book.eval("window.scrollTo(0, 0); window.dispatchEvent(new Event('scroll')); true")
    sleep_between(1.2, 2.0)

    while batch_no < max_batches:
        check_interrupt()
        ensure_profile_context(book, profile_url)
        visible, card = next_pending_profile_card(book, processed_keys, known_note_ids)
        pending_count = sum(
            1
            for item in visible
            if item.key not in processed_keys and profile_card_id(item) not in known_note_ids
        )
        log(f"可视批次: batch={batch_no + 1}/{max_batches} visible={len(visible)} pending={pending_count}")

        if card is None:
            if not advance_profile_batch(book, visible, processed_keys, known_note_ids):
                idle_batches += 1
                if idle_batches > max_idle_batches:
                    break
            else:
                idle_batches = 0
            batch_no += 1
            continue

        idle_batches = 0
        last_visible = visible
        while card is not None:
            check_interrupt()
            if count is not None and len(payloads) >= count:
                write_summary(payloads, output_dir, title)
                return payloads

            last_visible = visible
            log(f"打开帖子: {len(payloads) + 1} title={card.title or card.note_id}")
            payload: NotePayload | None = None
            close_mode = ""
            scroll_before_click = current_profile_scroll_y(book)
            try:
                opened = click_profile_card(book, card)
                if not opened:
                    log(f"跳过帖子: reason=not_clickable note_id={card.note_id}")
                else:
                    wait_for_detail(book)
                    state = get_page_state(book)
                    if is_security_or_unavailable(state):
                        log(f"跳过帖子: reason=blocked_or_unavailable href={state.get('href')}")
                    else:
                        payload = extract_payload(book, card.href or card.profile_href)
                        if payload is None:
                            log("跳过帖子: reason=no_payload")
                        else:
                            if not payload.title and card.title:
                                payload.title = card.title
                            note_id = payload.note_id or extract_note_id(payload.source_url or payload.candidate_href)
                            if note_id and note_id in known_note_ids:
                                log(f"跳过帖子: reason=duplicate note_id={note_id}")
                                payload = None
                            elif note_id:
                                known_note_ids.add(note_id)
                if payload is not None:
                    payloads.append(payload)
                    log(
                        f"已抽取: title={payload.title or payload.note_id} "
                        f"images={len(payload.image_urls)} close={close_mode or 'pending'}"
                    )
                    if action == "download":
                        folder = write_note_download(payload, output_dir, len(payloads), folder_template, media_layout)
                        log(f"已下载: {folder}")
            finally:
                if not is_interrupted():
                    state = get_page_state(book)
                    href = str(state.get("href") or "")
                    has_detail = bool(
                        book.eval("(() => !!document.querySelector('#noteContainer') || !!document.querySelector('.note-detail-mask'))()", timeout=10.0)
                    )
                    if has_detail or "/explore/" in href:
                        close_mode = close_detail(book)
                        ensure_profile_context(book, profile_url)
                        if close_mode == "history_back":
                            restore_profile_scroll_y(book, scroll_before_click)
                processed_keys.add(card.key)
            visible, card = next_pending_profile_card(book, processed_keys, known_note_ids)

        batch_no += 1
        if count is not None and len(payloads) >= count:
            break
        if not advance_profile_batch(book, last_visible, processed_keys, known_note_ids):
            idle_batches += 1
            if idle_batches > max_idle_batches:
                break
        else:
            idle_batches = 0

    write_summary(payloads, output_dir, title)
    return payloads


def process_notes(
    book: ActionBook,
    notes: list[NoteRef],
    action: str,
    output_dir: Path,
    title: str,
    folder_template: str = "",
    media_layout: str = "media",
) -> list[NotePayload]:
    payloads: list[NotePayload] = []
    failures: list[WorkflowFailure] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, note in enumerate(notes, start=1):
        check_interrupt()
        log(f"打开帖子: {index}/{len(notes)} title={note.title or note.note_id}")
        opened = click_note(book, note)
        if not opened:
            opened = click_note(book, note)
        if not opened:
            note_url = note.href or note.profile_href
            if note_url and can_direct_open_note_url(note_url):
                log(f"卡片点击失败，改用 URL 打开: note_id={note.note_id}")
                try:
                    book.goto(note_url)
                    sleep_between(0.8, 1.4)
                    opened = True
                except Exception as exc:  # noqa: BLE001
                    failures.append(
                        WorkflowFailure(
                            index=index,
                            source_page=note.source,
                            candidate_url=note_url,
                            reason="not_clickable",
                            message=f"candidate note could not be opened by click or URL fallback: {exc}",
                            context=asdict(note),
                        )
                    )
                    log(f"跳过帖子: reason=not_clickable note_id={note.note_id}")
                    continue
            elif note_url:
                log(f"跳过 URL 兜底: reason=missing_xsec_token note_id={note.note_id}")
        if not opened:
            log(f"跳过帖子: reason=not_clickable note_id={note.note_id}")
            failures.append(
                WorkflowFailure(
                    index=index,
                    source_page=note.source,
                    candidate_url=note.href or note.profile_href,
                    reason="not_clickable",
                    message="candidate note could not be opened from current list page",
                    context=asdict(note),
                )
            )
            continue
        wait_for_detail(book)
        state = get_page_state(book)
        if is_security_or_unavailable(state):
            log(f"跳过帖子: reason=blocked_or_unavailable href={state.get('href')}")
            failures.append(
                WorkflowFailure(
                    index=index,
                    source_page=note.source,
                    candidate_url=note.href or note.profile_href,
                    reason="blocked_or_unavailable",
                    message=str(state.get("href") or ""),
                    context=state,
                )
            )
            close_detail(book)
            continue
        payload = extract_payload(book, note.href or note.profile_href)
        close_mode = close_detail(book)
        if payload is None:
            log(f"跳过帖子: reason=no_payload close_mode={close_mode}")
            failures.append(
                WorkflowFailure(
                    index=index,
                    source_page=note.source,
                    candidate_url=note.href or note.profile_href,
                    reason="no_payload",
                    message=f"detail opened but payload extraction returned empty; close_mode={close_mode}",
                    context=asdict(note),
                )
            )
            continue
        if not payload.title and note.title:
            payload.title = note.title
        payloads.append(payload)
        log(
            f"已抽取: title={payload.title or payload.note_id} images={len(payload.image_urls)} close={close_mode}"
        )
        if action == "download":
            folder = write_note_download(payload, output_dir, index, folder_template, media_layout)
            log(f"已下载: {folder}")
    write_summary(payloads, output_dir, title, failures)
    return payloads


def process_note_urls(
    book: ActionBook,
    notes: list[NoteRef],
    action: str,
    output_dir: Path,
    title: str,
    folder_template: str = "",
    media_layout: str = "media",
) -> list[NotePayload]:
    payloads: list[NotePayload] = []
    failures: list[WorkflowFailure] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, note in enumerate(notes, start=1):
        check_interrupt()
        note_url = note.href or note.profile_href
        log(f"打开帖子 URL: {index}/{len(notes)} title={note.title or note.note_id}")
        if not note_url:
            failures.append(
                WorkflowFailure(
                    index=index,
                    source_page=note.source,
                    candidate_url="",
                    reason="missing_url",
                    message="candidate note has no URL",
                    context=asdict(note),
                )
            )
            continue
        if not can_direct_open_note_url(note_url):
            failures.append(
                WorkflowFailure(
                    index=index,
                    source_page=note.source,
                    candidate_url=note_url,
                    reason="missing_xsec_token",
                    message="bare Xiaohongshu note URL cannot be opened directly; click the visible card or provide a full URL with xsec_token",
                    context=asdict(note),
                )
            )
            log(f"跳过 URL 打开: reason=missing_xsec_token note_id={note.note_id}")
            continue
        try:
            book.goto(note_url)
            wait_for_detail(book)
            state = get_page_state(book)
            if is_security_or_unavailable(state):
                failures.append(
                    WorkflowFailure(
                        index=index,
                        source_page=note.source,
                        candidate_url=note_url,
                        reason="blocked_or_unavailable",
                        message=str(state.get("href") or ""),
                        context=state,
                    )
                )
                continue
            payload = extract_payload(book, note_url)
            if payload is None:
                failures.append(
                    WorkflowFailure(
                        index=index,
                        source_page=note.source,
                        candidate_url=note_url,
                        reason="no_payload",
                        message="direct note URL opened but payload extraction returned empty",
                        context=asdict(note),
                    )
                )
                continue
            if not payload.title and note.title:
                payload.title = note.title
            payloads.append(payload)
            log(f"已抽取: title={payload.title or payload.note_id} images={len(payload.image_urls)}")
            if action == "download":
                folder = write_note_download(payload, output_dir, len(payloads), folder_template, media_layout)
                log(f"已下载: {folder}")
        except Exception as exc:  # noqa: BLE001
            failures.append(
                WorkflowFailure(
                    index=index,
                    source_page=note.source,
                    candidate_url=note_url,
                    reason="exception",
                    message=str(exc),
                    context=asdict(note),
                )
            )
            log(f"跳过帖子: reason=exception message={exc}")
    write_summary(payloads, output_dir, title, failures)
    return payloads


def parse_count(value: str, allow_all: bool = False) -> int | None:
    if allow_all and value.lower() == "all":
        return None
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--count must be an integer" + (" or all" if allow_all else "")) from exc
    if count <= 0:
        raise argparse.ArgumentTypeError("--count must be greater than 0")
    return count


def default_action_output_dir(source: str, action: str, name: str = "") -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    action_dir = "downloads" if action == "download" else "views"
    if name:
        return ASSETS_DIR / action_dir / source / f"{sanitize_name(name, max_length=40)}-{stamp}"
    return ASSETS_DIR / action_dir / source / stamp


def prepare_xhs_book(args: argparse.Namespace, url: str) -> ActionBook:
    return attach_workflow(args, url, ActionBook)


def run_note(args: argparse.Namespace) -> int:
    note_url = args.url
    note_id = extract_note_id(note_url) or "note"
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_action_output_dir("note", args.action, note_id)
    if can_direct_open_note_url(note_url):
        book = prepare_xhs_book(args, note_url)
        book.goto(note_url)
    else:
        book = prepare_xhs_book(args, XHS_EXPLORE)
        if args.tab:
            log(f"裸笔记 URL 不直接访问，尝试点击当前页可见卡片: note_id={note_id}")
        else:
            log(f"裸笔记 URL 不直接访问，先打开推荐页尝试查找可见卡片: note_id={note_id}")
        if not click_note_id_on_current_page(book, note_id, "note"):
            raise RuntimeError(
                "bare Xiaohongshu note URL cannot be opened directly and no matching visible card was found; "
                "open a search/feed/profile page containing the note, pass --tab for that page, or provide a full URL with xsec_token"
            )
    wait_for_detail(book)
    state = get_page_state(book)
    if is_security_or_unavailable(state):
        raise RuntimeError(f"note blocked or unavailable: {state.get('href')}")
    payload = extract_payload(book, note_url)
    if payload is None:
        raise RuntimeError(f"note payload not found: {note_url}")
    if args.action == "download":
        folder = write_note_download(payload, output_dir, 1, args.folder_template, args.media_layout)
        log(f"已下载: {folder}")
    write_summary([payload], output_dir, f"小红书笔记: {payload.title or payload.note_id or note_id}")
    result = {
        "source": "note",
        "url": note_url,
        "note_id": payload.note_id,
        "action": args.action,
        "count": 1,
        "output_dir": str(output_dir),
        "summary_json": str(output_dir / "summary.json"),
        "summary_md": str(output_dir / "summary.md"),
        "failures_json": str(output_dir / "failures.json"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    log(f"完成: output={output_dir}")
    return 0


def run_search(args: argparse.Namespace) -> int:
    count = parse_count(args.count, allow_all=False)
    assert count is not None
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_action_output_dir("search", args.action, args.keyword)
    if args.include_ai_answer and args.entry != "ai":
        raise RuntimeError("--include-ai-answer requires --entry ai")
    search_url = ai_search_result_url(args.keyword) if args.entry == "ai" else search_result_url(args.keyword)
    book = prepare_xhs_book(args, search_url)
    book.goto(search_url)
    wait_for_search_results(book, args.keyword, retry_url=search_url)
    ai_answer = wait_for_ai_answer(book, args.keyword) if args.include_ai_answer else None
    if ai_answer:
        write_ai_answer(ai_answer, output_dir)
        log(f"点点 AI 回答抽取完成: status={ai_answer.status} chars={ai_answer.answer_length}")
    notes = collect_search_notes(book, count, args.max_scrolls)
    log(f"搜索候选收集完成: requested={count} collected={len(notes)}")
    process_notes(
        book,
        notes,
        args.action,
        output_dir,
        f"小红书搜索结果: {args.keyword}",
        args.folder_template,
        args.media_layout,
    )
    log(f"完成: output={output_dir}")
    return 0


def run_feed(args: argparse.Namespace) -> int:
    count = parse_count(args.count, allow_all=False)
    assert count is not None
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_action_output_dir("feed", args.action)
    book = prepare_xhs_book(args, XHS_EXPLORE)
    book.goto(XHS_EXPLORE)
    wait_for_notes_ready(book, "feed")
    book.eval("window.scrollTo(0, 0); window.dispatchEvent(new Event('scroll')); true", timeout=10.0)
    sleep_between(1.0, 1.6)
    notes = collect_feed_notes(book, "feed", count, args.max_scrolls)
    log(f"推荐流候选收集完成: requested={count} collected={len(notes)}")
    process_notes(book, notes, args.action, output_dir, "小红书推荐流", args.folder_template, args.media_layout)
    log(f"完成: output={output_dir}")
    return 0


def run_profile_tab(args: argparse.Namespace, source: str, labels: tuple[str, ...], title_prefix: str) -> int:
    count = parse_count(args.count, allow_all=False)
    assert count is not None
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_action_output_dir(source, args.action)
    start_url = args.profile_url or XHS_HOME
    book = prepare_xhs_book(args, start_url)
    profile_url = args.profile_url.strip()
    if not profile_url:
        profile_url = get_current_user_profile_url(book)
    if not profile_url:
        raise RuntimeError(
            f"无法自动识别当前登录用户主页，不能读取 {source}。请传入 --profile-url。"
        )
    book.goto(profile_tab_url(profile_url, source))
    profile = wait_for_profile(book, profile_url)
    log(
        f"个人主页就绪: source={source} "
        f"nickname={profile.get('nickname') or ''} profile_id={profile.get('profileId') or extract_profile_id(profile_url)}"
    )
    select_profile_tab(book, labels, source)
    book.eval("window.scrollTo(0, 0); window.dispatchEvent(new Event('scroll')); true", timeout=10.0)
    sleep_between(1.0, 1.6)
    notes = collect_profile_tab_notes(book, source, count, args.max_scrolls)
    log(f"{title_prefix}候选收集完成: requested={count} collected={len(notes)}")
    process_notes(book, notes, args.action, output_dir, title_prefix, args.folder_template, args.media_layout)
    profile_path = output_dir / "profile.json"
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"完成: output={output_dir}")
    return 0


def run_favorites(args: argparse.Namespace) -> int:
    return run_profile_tab(args, "favorites", ("收藏",), "小红书收藏")


def run_likes(args: argparse.Namespace) -> int:
    return run_profile_tab(args, "likes", ("赞过", "点赞", "喜欢"), "小红书点赞")


def run_profile(args: argparse.Namespace) -> int:
    count = parse_count(args.count, allow_all=True)
    profile_url = args.profile_url
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_action_output_dir(
        "profile",
        args.action,
        extract_profile_id(profile_url) or "profile",
    )
    book = prepare_xhs_book(args, profile_url)
    profile = wait_for_profile(book, profile_url)
    log(
        "博主主页就绪: "
        f"nickname={profile.get('nickname') or ''} profile_id={profile.get('profileId') or extract_profile_id(profile_url)}"
    )
    requested = "all" if count is None else str(count)
    profile_title = f"小红书博主帖子: {profile.get('nickname') or extract_profile_id(profile_url)}"
    payloads = process_profile_notes(
        book,
        profile_url,
        args.action,
        output_dir,
        profile_title,
        count,
        args.max_scrolls,
        args.max_idle_scrolls,
        args.folder_template,
        args.media_layout,
    )
    log(f"博主帖子处理完成: requested={requested} collected={len(payloads)}")
    profile_path = output_dir / "profile.json"
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"完成: output={output_dir}")
    return 0


def run_me(args: argparse.Namespace) -> int:
    count = parse_count(args.count, allow_all=True)
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_action_output_dir("me", args.action)
    book = prepare_xhs_book(args, XHS_HOME)
    profile_url = get_current_user_profile_url(book)
    if not profile_url:
        raise RuntimeError("无法自动识别当前小红书登录账号主页")
    book.goto(profile_url)
    profile = wait_for_profile(book, profile_url)
    log(
        "当前账号主页就绪: "
        f"nickname={profile.get('nickname') or ''} profile_id={profile.get('profileId') or extract_profile_id(profile_url)}"
    )
    requested = "all" if count is None else str(count)
    profile_title = f"小红书当前账号帖子: {profile.get('nickname') or extract_profile_id(profile_url)}"
    payloads = process_profile_notes(
        book,
        profile_url,
        args.action,
        output_dir,
        profile_title,
        count,
        args.max_scrolls,
        args.max_idle_scrolls,
        args.folder_template,
        args.media_layout,
    )
    log(f"当前账号帖子处理完成: requested={requested} collected={len(payloads)}")
    profile_path = output_dir / "profile.json"
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"完成: output={output_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Xiaohongshu note/search/profile/feed/favorites/likes/me workflows through ActionBook."
    )
    subparsers = parser.add_subparsers(dest="area", required=True)

    def add_common(target: argparse.ArgumentParser) -> None:
        add_workflow_args(target)
        target.add_argument("--output-dir", help="Output directory")
        target.add_argument(
            "--folder-template",
            default="",
            help=(
                "Relative note folder template for downloads, for example "
                "'{author}/{index:03d}_{title}'. Available fields: index, index3, "
                "author, title, note_id, type, media_flags."
            ),
        )
        target.add_argument(
            "--media-layout",
            choices=("media", "flat"),
            default="media",
            help="Image save layout for downloads: 'media' saves images under media/, 'flat' saves images beside content files.",
        )

    def add_leaf(
        parent: argparse.ArgumentParser,
        name: str,
        help_text: str,
        func: Any,
        action: str,
    ) -> argparse.ArgumentParser:
        leaf = parent.add_parser(name, help=help_text)
        add_common(leaf)
        leaf.set_defaults(func=func, action=action)
        return leaf

    note = subparsers.add_parser("note", help="Xiaohongshu single note workflows")
    note_sub = note.add_subparsers(dest="mode", required=True)
    note_view = add_leaf(note_sub, "view", "Read one Xiaohongshu note URL", run_note, "summarize")
    note_view.add_argument("--url", required=True, help="Xiaohongshu note URL")
    note_download = add_leaf(note_sub, "download", "Download one Xiaohongshu note URL", run_note, "download")
    note_download.add_argument("--url", required=True, help="Xiaohongshu note URL")

    search = subparsers.add_parser("search", help="Xiaohongshu search workflows")
    search_sub = search.add_subparsers(dest="mode", required=True)
    for mode_name, action in (("view", "summarize"), ("download", "download")):
        target = add_leaf(search_sub, mode_name, f"{mode_name.title()} Xiaohongshu search results", run_search, action)
        target.add_argument("--keyword", required=True, help="Search keyword")
        target.add_argument("--count", default="10", help="Number of posts to process")
        target.add_argument("--max-scrolls", type=int, default=12, help="Maximum result-page scroll rounds")
        target.add_argument(
            "--entry",
            choices=("normal", "ai"),
            default="normal",
            help="Search entry: normal opens search_result; ai opens the Diandian AI search result page.",
        )
        target.add_argument(
            "--include-ai-answer",
            action="store_true",
            help="When used with --entry ai, save Diandian AI answer to ai_answer.json and ai_answer.md.",
        )

    feed = subparsers.add_parser("feed", help="Xiaohongshu explore feed workflows")
    feed_sub = feed.add_subparsers(dest="mode", required=True)
    for mode_name, action in (("view", "summarize"), ("download", "download")):
        target = add_leaf(feed_sub, mode_name, f"{mode_name.title()} Xiaohongshu explore feed", run_feed, action)
        target.add_argument("--count", default="30", help="Number of posts to process")
        target.add_argument("--max-scrolls", type=int, default=18, help="Maximum feed scroll rounds")

    profile = subparsers.add_parser("profile", help="Xiaohongshu profile workflows")
    profile_sub = profile.add_subparsers(dest="mode", required=True)
    for mode_name, action in (("view", "summarize"), ("download", "download")):
        target = add_leaf(profile_sub, mode_name, f"{mode_name.title()} a Xiaohongshu profile page", run_profile, action)
        target.add_argument("--profile-url", required=True, help="Xiaohongshu profile URL")
        target.add_argument("--count", default="all", help="Number of posts to process, or all")
        target.add_argument("--max-scrolls", type=int, default=120, help="Maximum profile scroll rounds")
        target.add_argument("--max-idle-scrolls", type=int, default=5, help="Stop after this many idle scroll rounds")

    me = subparsers.add_parser("me", help="Current Xiaohongshu account workflows")
    me_sub = me.add_subparsers(dest="mode", required=True)
    for mode_name, action in (("view", "summarize"), ("download", "download")):
        target = add_leaf(me_sub, mode_name, f"{mode_name.title()} the current Xiaohongshu account's posts", run_me, action)
        target.add_argument("--count", default="30", help="Number of posts to process, or all")
        target.add_argument("--max-scrolls", type=int, default=120, help="Maximum profile scroll rounds")
        target.add_argument("--max-idle-scrolls", type=int, default=5, help="Stop after this many idle scroll rounds")

    favorites = subparsers.add_parser("favorites", help="Current Xiaohongshu user's favorites workflows")
    favorites_sub = favorites.add_subparsers(dest="mode", required=True)
    for mode_name, action in (("view", "summarize"), ("download", "download")):
        target = add_leaf(favorites_sub, mode_name, f"{mode_name.title()} current user's Xiaohongshu favorites", run_favorites, action)
        target.add_argument("--profile-url", default="", help="Current user's profile URL; auto-detect when omitted")
        target.add_argument("--count", default="30", help="Number of posts to process")
        target.add_argument("--max-scrolls", type=int, default=18, help="Maximum favorites scroll rounds")

    likes = subparsers.add_parser("likes", help="Current Xiaohongshu user's liked posts workflows")
    likes_sub = likes.add_subparsers(dest="mode", required=True)
    for mode_name, action in (("view", "summarize"), ("download", "download")):
        target = add_leaf(likes_sub, mode_name, f"{mode_name.title()} current user's Xiaohongshu liked posts", run_likes, action)
        target.add_argument("--profile-url", default="", help="Current user's profile URL; auto-detect when omitted")
        target.add_argument("--count", default="30", help="Number of posts to process")
        target.add_argument("--max-scrolls", type=int, default=18, help="Maximum liked-post scroll rounds")
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
