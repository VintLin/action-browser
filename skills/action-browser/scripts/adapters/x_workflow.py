#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Single-file X workflow helper for the action-browser skill.

The workflow uses one ActionBook extension session/tab, extracts visible X
timeline/bookmark posts, scrolls until the requested count is reached, and
writes local per-post artifacts plus summary files.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
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

from scripts.actionbook_interrupts import install_interrupt_handlers
from scripts.workflow_runtime import add_workflow_args, attach_workflow, temporary_tab
from scripts.actionbook_session import ActionBookSession as ActionBook
from scripts.script_common import log, unwrap_eval


HOME_URL = "https://x.com/home"
BOOKMARKS_URL = "https://x.com/i/bookmarks"
SEARCH_URL = "https://x.com/search"
SKILL_DIR = Path(__file__).resolve().parents[2]
ASSETS_DIR = SKILL_DIR / "assets" / "x"


@dataclass
class TweetPayload:
    tweet_id: str
    source_url: str
    source_page: str
    author_name: str
    author_handle: str
    author_profile_url: str
    author_avatar_url: str
    text: str
    created_at_text: str
    created_at_iso: str
    tweet_type: str
    reply_to: dict[str, Any]
    quoted_tweet: dict[str, Any]
    media: list[dict[str, Any]]
    links: list[dict[str, str]]
    card: dict[str, Any]
    article: dict[str, Any]
    metrics: dict[str, str]
    social_context: dict[str, Any]
    is_bookmarked: bool
    raw_text_lines: list[str]
    extraction_warnings: list[str]
def sanitize_name(value: str, fallback: str = "item", max_length: int = 64) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "", value or "").strip("._-")
    return (cleaned or fallback)[:max_length]


def extract_status_id(url: str) -> str:
    match = re.search(r"/status/(\d+)", url or "")
    return match.group(1) if match else ""


def normalize_url(value: str) -> str:
    return str(value or "").split("?", 1)[0].rstrip("/")


def default_output_dir(source: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return ASSETS_DIR / "downloads" / source / stamp


def default_action_output_dir(source: str, action: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    action_dir = "downloads" if action == "download" else "views"
    return ASSETS_DIR / action_dir / source / stamp
EXTRACT_VISIBLE_TWEETS_JS = r"""
(() => {
  const normalize = value => String(value || '')
    .replace(/\u00a0/g, ' ')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  const absUrl = value => {
    if (!value) return '';
    try { return new URL(value, location.origin).toString(); }
    catch (e) { return String(value || ''); }
  };
  const uniq = (items, keyFn) => {
    const seen = new Set();
    const out = [];
    for (const item of items) {
      const key = keyFn(item);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      out.push(item);
    }
    return out;
  };
  const visible = node => {
    if (!node) return false;
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < window.innerHeight && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const extractStatusId = value => {
    const match = String(value || '').match(/\/status\/(\d+)/);
    return match ? match[1] : '';
  };
  const textOf = node => normalize(node?.innerText || node?.textContent || '');
  const parseAuthor = article => {
    const userBlock = article.querySelector('[data-testid="User-Name"]') || article;
    const links = [...userBlock.querySelectorAll('a[href]')].map(anchor => ({
      href: absUrl(anchor.getAttribute('href')),
      text: normalize(anchor.innerText || anchor.textContent || ''),
    }));
    const handleLink = links.find(item => /^@\w+/.test(item.text))
      || links.find(item => /^https:\/\/x\.com\/[^/?#]+$/i.test(item.href) && !/\/(home|explore|i|search)$/.test(item.href));
    const handle = handleLink?.text?.match(/@\w+/)?.[0]
      || (handleLink?.href ? '@' + handleLink.href.split('/').pop() : '');
    const displayName = links.find(item => item.text && !item.text.startsWith('@') && !item.text.includes('\n'))?.text
      || normalize((userBlock.innerText || '').split('\n').find(line => line && !line.startsWith('@')) || '');
    const avatar = [...article.querySelectorAll('img')]
      .map(img => img.currentSrc || img.src || '')
      .find(src => /profile_images|pbs\.twimg\.com\/profile_images/.test(src)) || '';
    return {
      name: displayName || '',
      handle: handle || '',
      profile_url: handleLink?.href || '',
      avatar_url: avatar,
    };
  };
  const parseLinks = root => uniq([...root.querySelectorAll('a[href]')].map(anchor => {
    const href = absUrl(anchor.getAttribute('href'));
    const text = normalize(anchor.innerText || anchor.getAttribute('aria-label') || '');
    return { url: href, text };
  }).filter(item =>
    item.url
    && !item.url.includes('/status/')
    && !/^https:\/\/x\.com\/[^/?#]+$/i.test(item.url)
    && !item.url.startsWith('https://x.com/hashtag/')
  ), item => item.url + '|' + item.text);
  const parseMedia = article => {
    const images = [...article.querySelectorAll('[data-testid="tweetPhoto"] img, img[src*="pbs.twimg.com/media"]')]
      .map(img => ({
        kind: 'image',
        url: img.currentSrc || img.src || '',
        alt_text: img.getAttribute('alt') || '',
      }))
      .filter(item => item.url && !item.url.includes('profile_images'));
    const videos = [...article.querySelectorAll('video')]
      .map(video => ({
        kind: 'video',
        url: video.currentSrc || video.src || '',
        poster_url: video.poster || '',
        duration_text: '',
      }));
    const playerPosters = [...article.querySelectorAll('[data-testid="videoPlayer"] img, div[aria-label*="播放"] img, div[aria-label*="Play"] img')]
      .map(img => ({
        kind: 'video',
        url: '',
        poster_url: img.currentSrc || img.src || '',
        duration_text: '',
      }))
      .filter(item => item.poster_url);
    return uniq([...images, ...videos, ...playerPosters], item => item.kind + '|' + (item.url || item.poster_url));
  };
  const parseQuoted = article => {
    const nested = [...article.querySelectorAll('article')].find(node => node !== article);
    if (!nested) return {};
    const author = parseAuthor(nested);
    const statusLink = [...nested.querySelectorAll('a[href*="/status/"]')]
      .map(anchor => absUrl(anchor.getAttribute('href')))
      .find(Boolean) || '';
    return {
      tweet_id: extractStatusId(statusLink),
      source_url: statusLink,
      author_name: author.name,
      author_handle: author.handle,
      text: uniq([...nested.querySelectorAll('[data-testid="tweetText"]')]
        .map(node => textOf(node))
        .filter(Boolean), value => value).join('\n\n'),
      media: parseMedia(nested),
    };
  };
  const parseCard = article => {
    const cardRoot = article.querySelector('[data-testid="card.wrapper"], [data-testid="card.layoutLarge.media"], [data-testid="card.layoutSmall.media"]');
    if (!cardRoot) return {};
    const link = cardRoot.closest('a[href]') || cardRoot.querySelector('a[href]');
    const lines = normalize(cardRoot.innerText).split('\n').map(line => line.trim()).filter(Boolean);
    return {
      url: absUrl(link?.getAttribute('href') || ''),
      title: lines[0] || '',
      description: lines.slice(1, 4).join('\n'),
      image_url: cardRoot.querySelector('img')?.currentSrc || cardRoot.querySelector('img')?.src || '',
      raw_text: lines.join('\n'),
    };
  };
  const parseMetrics = article => {
    const metrics = {};
    for (const button of article.querySelectorAll('button[aria-label], a[aria-label]')) {
      const label = button.getAttribute('aria-label') || '';
      if (/回复|repl/i.test(label)) metrics.replies = label;
      else if (/转帖|repost|retweet/i.test(label)) metrics.reposts = label;
      else if (/喜欢|like/i.test(label)) metrics.likes = label;
      else if (/书签|bookmark/i.test(label)) metrics.bookmarks = label;
      else if (/查看|view/i.test(label)) metrics.views = label;
    }
    return metrics;
  };
  return [...document.querySelectorAll('article[data-testid="tweet"], article')]
    .filter(visible)
    .map(article => {
      const rawLines = normalize(article.innerText).split('\n').map(line => line.trim()).filter(Boolean);
      const statusUrl = [...article.querySelectorAll('a[href*="/status/"]')]
        .map(anchor => absUrl(anchor.getAttribute('href')))
        .find(href => /\/status\/\d+/.test(href) && !/\/(photo|video|analytics)\//.test(href)) || '';
      const time = article.querySelector('time');
      const author = parseAuthor(article);
      const domText = uniq([...article.querySelectorAll('[data-testid="tweetText"]')]
        .map(node => textOf(node))
        .filter(Boolean), value => value).join('\n\n');
      const media = parseMedia(article);
      let quoted = parseQuoted(article);
      const card = parseCard(article);
      const links = parseLinks(article);
      const replyLine = rawLines.find(line => /^(回复|Replying to)\s+@/i.test(line)) || '';
      const socialLine = rawLines.find(line => /转帖了|Reposted|Retweeted/i.test(line)) || '';
      const articleLink = [...article.querySelectorAll('a[href*="/i/articles/"], a[href*="/articles/"]')]
        .map(anchor => absUrl(anchor.getAttribute('href')))
        .find(Boolean) || '';
      const isMetricLine = line =>
        /^[\d,.]+$/.test(line)
        || /^[\d,.]+万$/.test(line)
        || /^[\d,.]+[KMB]$/i.test(line)
        || /^(?:\d+\s*)?(?:回复|喜欢|书签|转帖|次观看|views?|likes?|bookmarks?|reposts?)$/i.test(line);
      const contentLine = line =>
        line
        && line !== author.name
        && line !== author.handle
        && line !== '·'
        && line !== '文章'
        && line !== '引用'
        && line !== '显示更多'
        && line !== '图像'
        && !isMetricLine(line)
        && !/^(?:\d+小时|昨天|今天|前天|\d+月\d+日|\d{4}年|\d+分钟前)/.test(line);
      const articleMarkerIndex = rawLines.findIndex(line => line === '文章' || /^Article$/i.test(line));
      const quoteMarkerIndex = rawLines.findIndex(line => line === '引用' || /^Quote$/i.test(line));
      const articleLines = articleMarkerIndex >= 0
        ? rawLines.slice(articleMarkerIndex + 1).filter(contentLine)
        : [];
      const fallbackTextLines = rawLines
        .slice(0, quoteMarkerIndex >= 0 ? quoteMarkerIndex : rawLines.length)
        .filter(contentLine);
      const text = domText || (articleLines.length ? articleLines.join('\n') : fallbackTextLines.join('\n'));
      const articlePayload = (articleLink || articleLines.length)
        ? {
            url: articleLink || statusUrl,
            title: articleLines[0] || card.title || '',
            preview_text: articleLines.slice(1, 5).join('\n') || card.description || '',
          }
        : {};
      if (!(quoted && quoted.source_url) && quoteMarkerIndex >= 0) {
        const quoteLines = rawLines.slice(quoteMarkerIndex + 1).filter(contentLine);
        if (quoteLines.length) {
          quoted = {
            tweet_id: '',
            source_url: '',
            author_name: quoteLines[0] || '',
            author_handle: quoteLines.find(line => /^@\w+/.test(line)) || '',
            text: quoteLines.filter(line => !/^@\w+/.test(line)).slice(1).join('\n'),
            media: [],
          };
        }
      }
      let tweetType = 'tweet';
      if (socialLine) tweetType = 'repost';
      else if (replyLine) tweetType = 'reply';
      else if (quoted && (quoted.source_url || quoted.text)) tweetType = 'quote_tweet';
      else if (articlePayload && (articlePayload.url || articlePayload.title)) tweetType = 'article';
      const warnings = [];
      if (!statusUrl) warnings.push('missing_status_url');
      if (!author.handle) warnings.push('missing_author_handle');
      if (!text && media.length === 0 && !card.url && !(articlePayload && articlePayload.url) && !(quoted && (quoted.source_url || quoted.text))) {
        warnings.push('empty_content');
      }
      return {
        tweet_id: extractStatusId(statusUrl),
        source_url: statusUrl,
        author_name: author.name,
        author_handle: author.handle,
        author_profile_url: author.profile_url,
        author_avatar_url: author.avatar_url,
        text,
        created_at_text: time ? normalize(time.innerText || time.getAttribute('aria-label') || '') : '',
        created_at_iso: time ? (time.getAttribute('datetime') || '') : '',
        tweet_type: tweetType,
        reply_to: replyLine ? { raw_text: replyLine, handles: [...replyLine.matchAll(/@\w+/g)].map(m => m[0]) } : {},
        quoted_tweet: quoted || {},
        media,
        links,
        card,
        article: articlePayload,
        metrics: parseMetrics(article),
        social_context: socialLine ? { text: socialLine, is_repost: true } : {},
        is_bookmarked: !!article.querySelector('button[data-testid="removeBookmark"], button[aria-label*="已加入书签"], button[aria-label*="Remove Bookmark"]'),
        raw_text_lines: rawLines,
        extraction_warnings: warnings,
      };
    })
    .filter(item => item.source_url || item.text || item.media.length || item.card.url);
})()
"""


def extract_visible_tweets(book: ActionBook, source: str, tab_id: str | None = None) -> list[TweetPayload]:
    if tab_id:
        value = unwrap_eval(book.browser("eval", EXTRACT_VISIBLE_TWEETS_JS, timeout=45.0, tab=tab_id))
    else:
        value = unwrap_eval(book.eval(EXTRACT_VISIBLE_TWEETS_JS, timeout=45.0))
    if not isinstance(value, list):
        return []
    payloads: list[TweetPayload] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        source_url = str(item.get("source_url") or "")
        payloads.append(
            TweetPayload(
                tweet_id=str(item.get("tweet_id") or extract_status_id(source_url)),
                source_url=source_url,
                source_page=source,
                author_name=str(item.get("author_name") or ""),
                author_handle=str(item.get("author_handle") or ""),
                author_profile_url=str(item.get("author_profile_url") or ""),
                author_avatar_url=str(item.get("author_avatar_url") or ""),
                text=str(item.get("text") or ""),
                created_at_text=str(item.get("created_at_text") or ""),
                created_at_iso=str(item.get("created_at_iso") or ""),
                tweet_type=str(item.get("tweet_type") or "tweet"),
                reply_to=item.get("reply_to") if isinstance(item.get("reply_to"), dict) else {},
                quoted_tweet=item.get("quoted_tweet") if isinstance(item.get("quoted_tweet"), dict) else {},
                media=[media for media in item.get("media") or [] if isinstance(media, dict)],
                links=[link for link in item.get("links") or [] if isinstance(link, dict)],
                card=item.get("card") if isinstance(item.get("card"), dict) else {},
                article=item.get("article") if isinstance(item.get("article"), dict) else {},
                metrics=item.get("metrics") if isinstance(item.get("metrics"), dict) else {},
                social_context=item.get("social_context") if isinstance(item.get("social_context"), dict) else {},
                is_bookmarked=bool(item.get("is_bookmarked")),
                raw_text_lines=[str(line) for line in item.get("raw_text_lines") or []],
                extraction_warnings=[str(line) for line in item.get("extraction_warnings") or []],
            )
        )
    return payloads


def scroll_page(book: ActionBook) -> float:
    value = unwrap_eval(book.eval(
        """(() => {
            const before = window.scrollY || window.pageYOffset || 0;
            const step = Math.max(Math.floor((window.innerHeight || 800) * 0.82), 650);
            window.scrollTo(0, before + step);
            window.dispatchEvent(new Event('scroll'));
            return window.scrollY || window.pageYOffset || 0;
        })()""",
        timeout=10.0,
    ))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def read_scroll_y(book: ActionBook) -> float:
    value = unwrap_eval(book.eval("window.scrollY || window.pageYOffset || 0", timeout=10.0))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def wait_for_scroll_progress(book: ActionBook, before_y: float, timeout_secs: float = 3.0) -> float:
    deadline = time.time() + timeout_secs
    current = before_y
    while time.time() < deadline:
        current = read_scroll_y(book)
        if current > before_y + 5:
            return current
        time.sleep(0.4)
    return current


def is_x_user_gate_state(state: dict[str, Any]) -> bool:
    href = str(state.get("href") or "")
    body = str(state.get("body") or "")
    if re.search(r"/(login|i/flow/login|account/access|account/verify)", href, re.I):
        return True
    return bool(re.search(r"登录|Log in|Sign in|验证码|captcha|MFA|Verify your account|unusual activity", body, re.I))


def is_x_page_ready_state(state: dict[str, Any]) -> bool:
    if is_x_user_gate_state(state):
        return False
    return int(state.get("primary_articles") or 0) > 0


def wait_page_ready(book: ActionBook, source: str, timeout_secs: float = 20.0) -> None:
    deadline = time.time() + timeout_secs
    last_state: dict[str, Any] = {}
    while time.time() < deadline:
        state = unwrap_eval(book.eval(
            """(() => ({
                href: location.href,
                title: document.title,
                body: (document.body?.innerText || '').slice(0, 600),
                articles: document.querySelectorAll('article').length,
                primary_articles: (
                    document.querySelector('[data-testid="primaryColumn"], main, [role="main"]')
                    || document
                ).querySelectorAll('article').length,
            }))()""",
            timeout=10.0,
        ))
        last_state = state if isinstance(state, dict) else {}
        if is_x_user_gate_state(last_state):
            raise RuntimeError(f"X redirected to login page: {last_state.get('href')}")
        if is_x_page_ready_state(last_state):
            return
        time.sleep(0.4)
    raise RuntimeError(f"X {source} page did not become ready: {last_state}")


def wait_tab_articles(book: ActionBook, tab_id: str, timeout_secs: float = 15.0) -> None:
    deadline = time.time() + timeout_secs
    last_state: dict[str, Any] = {}
    while time.time() < deadline:
        state = unwrap_eval(book.browser(
            "eval",
            """(() => ({
                href: location.href,
                title: document.title,
                body: (document.body?.innerText || '').slice(0, 600),
                articles: document.querySelectorAll('article').length,
                primary_articles: (
                    document.querySelector('[data-testid="primaryColumn"], main, [role="main"]')
                    || document
                ).querySelectorAll('article').length,
            }))()""",
            timeout=10.0,
            tab=tab_id,
        ))
        last_state = state if isinstance(state, dict) else {}
        if is_x_user_gate_state(last_state):
            raise RuntimeError(f"X detail redirected to login page: {last_state.get('href')}")
        if is_x_page_ready_state(last_state):
            return
        time.sleep(0.8)
    raise RuntimeError(f"X detail page did not become ready: {last_state}")


def click_show_more_in_tab(book: ActionBook, tab_id: str) -> int:
    value = unwrap_eval(book.browser(
        "eval",
        r"""(() => {
            const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
            const candidates = [...document.querySelectorAll('button, a, div[role="button"], span')]
                .filter(node => /^(显示更多|Show more)$/i.test(normalize(node.innerText || node.textContent || node.getAttribute('aria-label') || '')));
            const clickLikeUser = node => {
                const target = node.closest('button, a, div[role="button"]') || node;
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
            for (const node of candidates) {
                if (clickLikeUser(node)) return 1;
            }
            return 0;
        })()""",
        timeout=10.0,
        tab=tab_id,
    ))
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def click_show_more_for_payload(book: ActionBook, payload: TweetPayload) -> int:
    if not payload.tweet_id:
        return 0
    value = unwrap_eval(book.browser(
        "eval",
        f"""(() => {{
            const statusId = {json.dumps(payload.tweet_id)};
            const normalize = value => String(value || '').replace(/\\s+/g, ' ').trim();
            const article = [...document.querySelectorAll('article[data-testid="tweet"], article')].find(node =>
                [...node.querySelectorAll('a[href*="/status/"]')].some(anchor =>
                    String(anchor.getAttribute('href') || '').includes(`/status/${{statusId}}`)
                )
            );
            if (!article) return false;
            return [...article.querySelectorAll('button, a, div[role="button"], span')].some(candidate =>
                /^(显示更多|Show more)$/i.test(normalize(candidate.innerText || candidate.textContent || candidate.getAttribute('aria-label') || ''))
            );
        }})()""",
        timeout=10.0,
    ))
    if not value:
        return 0
    # The extension's selector-click transport can acknowledge without X invoking
    # this React button. Activate the observed native button, then the caller
    # proves its visible state changed before treating the detail as expanded.
    clicked = unwrap_eval(book.browser(
        "eval",
        f"""(() => {{
            const statusId = {json.dumps(payload.tweet_id)};
            const article = [...document.querySelectorAll('article[data-testid="tweet"], article')].find(node =>
                [...node.querySelectorAll('a[href*="/status/"]')].some(anchor =>
                    String(anchor.getAttribute('href') || '').includes(`/status/${{statusId}}`)
                )
            );
            const button = article?.querySelector('button[data-testid="tweet-text-show-more-link"]');
            if (!button) return false;
            button.click();
            return true;
        }})()""",
        timeout=10.0,
    ))
    return 1 if clicked else 0


def wait_for_expanded_payload(
    book: ActionBook,
    original: TweetPayload,
    tab_id: str,
    timeout_secs: float = 3.0,
) -> TweetPayload | None:
    deadline = time.time() + timeout_secs
    fallback: TweetPayload | None = None
    while time.time() < deadline:
        candidates = extract_visible_tweets(book, original.source_page, tab_id=tab_id)
        expanded = next((item for item in candidates if item.tweet_id and item.tweet_id == original.tweet_id), None)
        if expanded is None and candidates:
            expanded = candidates[0]
        if expanded is None:
            time.sleep(0.4)
            continue
        fallback = expanded
        if expanded.text and len(expanded.text) > len(original.text or ""):
            return expanded
        if not needs_show_more_expansion(expanded):
            return expanded
        time.sleep(0.4)
    return fallback


def wait_for_parent_expansion(
    book: ActionBook,
    original: TweetPayload,
    timeout_secs: float = 3.0,
) -> TweetPayload | None:
    """Prove the native control changed the owned timeline before detail extraction."""
    deadline = time.time() + timeout_secs
    fallback: TweetPayload | None = None
    while time.time() < deadline:
        candidates = extract_visible_tweets(book, original.source_page)
        expanded = next((item for item in candidates if item.tweet_id and item.tweet_id == original.tweet_id), None)
        if expanded is None:
            time.sleep(0.4)
            continue
        fallback = expanded
        if expanded.text and not needs_show_more_expansion(expanded):
            return expanded
        time.sleep(0.4)
    return fallback


ARTICLE_DETAIL_JS = r"""
(() => {
  const normalize = value => String(value || '')
    .replace(/\u00a0/g, ' ')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  const linesOf = value => normalize(value).split('\n').map(line => line.trim()).filter(Boolean);
  const absUrl = value => {
    if (!value) return '';
    try { return new URL(value, location.origin).toString(); }
    catch (e) { return String(value || ''); }
  };
  const pageStatusId = (location.pathname.match(/\/status\/(\d+)/) || [])[1] || '';
  const articleNodes = [...document.querySelectorAll('article[data-testid="tweet"], article')];
  const targetRoot = articleNodes.find(node =>
    pageStatusId
    && [...node.querySelectorAll('a[href*="/status/"]')]
      .some(anchor => String(anchor.getAttribute('href') || '').includes(`/status/${pageStatusId}`))
  );
  const root = targetRoot || (
    pageStatusId ? null : articleNodes.find(node => node.querySelector('.longform-unstyled, .public-DraftStyleDefault-block'))
  );
  if (!root) {
    return {
      detail_url: location.href,
      page_title: document.title,
      title: document.title || '',
      body_text: '',
      body_lines: [],
      markdown_blocks: [],
      article_images: [],
      links: [],
      created_at_iso: '',
      raw_text_lines: [],
      scroll_y: scrollY,
      scroll_height: document.body?.scrollHeight || 0,
    };
  }
  const rawLines = linesOf(root.innerText || document.body?.innerText || '');
  const articleMarkerIndex = rawLines.findIndex(line => line === '文章' || /^Article$/i.test(line));
  const isMetricLine = line =>
    /^[\d,.]+$/.test(line)
    || /^[\d,.]+万$/.test(line)
    || /^[\d,.]+[KMB]$/i.test(line)
    || /^(?:\d+\s*)?(?:回复|喜欢|书签|转帖|次观看|views?|likes?|bookmarks?|reposts?)$/i.test(line);
  const contentLine = line =>
    line
    && line !== '·'
    && line !== '文章'
    && line !== '引用'
    && line !== '显示更多'
    && line !== '图像'
    && line !== '查看新帖子'
    && line !== '查看键盘快捷键'
    && line !== '要查看键盘快捷键，按下问号'
    && line !== '订阅'
    && line !== '查看'
    && line !== '相关'
    && line !== '查看引用'
    && line !== '想发布自己的文章？'
    && line !== '升级为 Premium'
    && !/^@\w+/.test(line)
    && !isMetricLine(line)
    && !/^(?:\d+小时|昨天|今天|前天|\d+月\d+日|\d{4}年|\d+分钟前)/.test(line);
  const tweetText = [...root.querySelectorAll('[data-testid="tweetText"]')]
    .map(node => normalize(node.innerText || node.textContent || ''))
    .filter(Boolean)
    .join('\n\n');
  const articleLines = articleMarkerIndex >= 0
    ? rawLines.slice(articleMarkerIndex + 1).filter(contentLine)
    : [];
  const title =
    document.querySelector('h1')?.innerText?.trim()
    || articleLines[0]
    || tweetText.split('\n').find(Boolean)
    || document.title
    || '';
  const bodyLines = articleLines.length
    ? articleLines
    : (tweetText ? linesOf(tweetText) : rawLines.filter(contentLine));
  const blocks = [];
  const seenText = new Set();
  const addTextBlock = (text, top) => {
    const cleaned = normalize(text);
    if (!cleaned || seenText.has(cleaned)) return;
    if (!contentLine(cleaned.split('\n')[0] || cleaned)) return;
    seenText.add(cleaned);
    blocks.push({ type: 'text', text: cleaned, top });
  };
  const longformBlocks = [...root.querySelectorAll('.longform-unstyled, .public-DraftStyleDefault-block')]
    .filter(node => {
      const text = normalize(node.innerText || node.textContent || '');
      const rect = node.getBoundingClientRect();
      return text && rect.width > 0 && rect.height > 0;
    });
  if (longformBlocks.length) {
    for (const node of longformBlocks) {
      const rect = node.getBoundingClientRect();
      addTextBlock(node.innerText || node.textContent || '', Math.round(rect.top + scrollY));
    }
  } else {
    for (const line of bodyLines) addTextBlock(line, blocks.length);
  }
  const articleImages = [...root.querySelectorAll('img')]
    .map(img => {
      const src = img.currentSrc || img.src || '';
      const rect = img.getBoundingClientRect();
      return {
        type: 'image',
        url: src,
        alt: normalize(img.alt || ''),
        top: Math.round(rect.top + scrollY),
        width: img.naturalWidth || rect.width || 0,
        height: img.naturalHeight || rect.height || 0,
        link_url: absUrl(img.closest('a[href]')?.getAttribute('href') || ''),
      };
    })
    .filter(item =>
      item.url
      && item.url.includes('pbs.twimg.com/media')
      && !item.url.includes('profile_images')
      && item.width >= 120
      && item.height >= 80
    );
  for (const image of articleImages) blocks.push(image);
  blocks.sort((a, b) => (a.top || 0) - (b.top || 0));
  const markdownBlocks = [];
  const seenBlockKeys = new Set();
  for (const block of blocks) {
    const key = block.type === 'image' ? `image|${block.url}` : `text|${block.text}`;
    if (seenBlockKeys.has(key)) continue;
    seenBlockKeys.add(key);
    markdownBlocks.push(block);
  }
  const markdownTextLines = markdownBlocks
    .filter(block => block.type === 'text')
    .map(block => block.text)
    .flatMap(text => linesOf(text));
  const finalBodyLines = markdownTextLines.length ? markdownTextLines : bodyLines;
  const links = [...root.querySelectorAll('a[href]')]
    .map(anchor => ({ url: absUrl(anchor.getAttribute('href')), text: normalize(anchor.innerText || '') }))
    .filter(item => item.url && !item.url.includes('/status/') && !/^https:\/\/x\.com\/[^/?#]+$/i.test(item.url));
  const time = root.querySelector('time');
  return {
    detail_url: location.href,
    page_title: document.title,
    title,
    body_text: finalBodyLines.join('\n'),
    body_lines: finalBodyLines,
    markdown_blocks: markdownBlocks,
    article_images: articleImages,
    links,
    created_at_iso: time?.getAttribute('datetime') || '',
    raw_text_lines: rawLines,
    scroll_y: scrollY,
    scroll_height: document.body?.scrollHeight || 0,
  };
})()
"""


def wait_article_detail(book: ActionBook, tab_id: str, timeout_secs: float = 18.0) -> dict[str, Any]:
    deadline = time.time() + timeout_secs
    last_detail: dict[str, Any] = {}
    seen_block_keys: set[str] = set()
    merged_blocks: list[dict[str, Any]] = []
    best_detail: dict[str, Any] = {}
    stable_rounds = 0
    previous_signature = ""
    while time.time() < deadline:
        detail = unwrap_eval(book.browser("eval", ARTICLE_DETAIL_JS, timeout=12.0, tab=tab_id))
        if isinstance(detail, dict):
            last_detail = detail
            body = str(detail.get("body_text") or "").strip()
            title = str(detail.get("title") or "").strip()
            raw_text = "\n".join(str(line) for line in detail.get("raw_text_lines") or [])
            if "/login" in str(detail.get("detail_url") or ""):
                raise RuntimeError(f"X article detail redirected to login: {detail.get('detail_url')}")
            for block in detail.get("markdown_blocks") or []:
                if not isinstance(block, dict):
                    continue
                key = f"{block.get('type')}|{block.get('url') or block.get('text')}"
                if not key or key in seen_block_keys:
                    continue
                seen_block_keys.add(key)
                merged_blocks.append(block)
            if len(body) > len(str(best_detail.get("body_text") or "")):
                best_detail = dict(detail)
            signature = f"{len(body)}|{len(merged_blocks)}|{detail.get('scroll_y')}|{detail.get('scroll_height')}"
            stable_rounds = stable_rounds + 1 if signature == previous_signature else 0
            previous_signature = signature
            if title and len(body) >= 120 and stable_rounds >= 2:
                break
            scroll_state = unwrap_eval(book.browser(
                "eval",
                """(() => {
                    const before = scrollY || 0;
                    const step = Math.max(Math.floor((innerHeight || 800) * 0.75), 600);
                    window.scrollTo(0, before + step);
                    window.dispatchEvent(new Event('scroll'));
                    return { before, after: scrollY || 0, height: document.body?.scrollHeight || 0 };
                })()""",
                timeout=10.0,
                tab=tab_id,
            ))
            if (
                isinstance(scroll_state, dict)
                and float(scroll_state.get("after") or 0) <= float(scroll_state.get("before") or 0) + 5
                and len(body) >= 120
            ):
                break
        time.sleep(0.8)
    final_detail = best_detail or last_detail
    if merged_blocks:
        merged_blocks.sort(key=lambda item: float(item.get("top") or 0))
        text_lines: list[str] = []
        article_images: list[dict[str, Any]] = []
        for block in merged_blocks:
            if block.get("type") == "text":
                text_lines.extend(str(block.get("text") or "").splitlines())
            elif block.get("type") == "image":
                article_images.append(block)
        cleaned_lines = [line.strip() for line in text_lines if line.strip()]
        if cleaned_lines and len("\n".join(cleaned_lines)) >= len(str(final_detail.get("body_text") or "")):
            final_detail["body_text"] = "\n".join(cleaned_lines)
            final_detail["body_lines"] = cleaned_lines
        final_detail["markdown_blocks"] = merged_blocks
        final_detail["article_images"] = article_images
    return final_detail


def enrich_article_payloads(book: ActionBook, payloads: list[TweetPayload]) -> None:
    for index, payload in enumerate(payloads, start=1):
        if payload.tweet_type != "article" and not payload.article:
            continue
        article_url = str(payload.article.get("url") or payload.source_url or "").strip()
        if not article_url:
            payload.extraction_warnings.append("article_missing_url")
            continue
        log(f"打开文章详情: {index}/{len(payloads)} {article_url}")
        try:
            with temporary_tab(book, article_url) as tab_id:
                detail = wait_article_detail(book, tab_id)
                if not detail:
                    payload.extraction_warnings.append("article_detail_empty")
                    continue
                article = dict(payload.article or {})
                article.update(
                    {
                        "url": article_url,
                        "detail_url": str(detail.get("detail_url") or article_url),
                        "title": str(detail.get("title") or article.get("title") or ""),
                        "body_text": str(detail.get("body_text") or ""),
                        "body_lines": [str(line) for line in detail.get("body_lines") or []],
                        "markdown_blocks": [
                            block for block in detail.get("markdown_blocks") or [] if isinstance(block, dict)
                        ],
                        "article_images": [
                            image for image in detail.get("article_images") or [] if isinstance(image, dict)
                        ],
                        "links": [link for link in detail.get("links") or [] if isinstance(link, dict)],
                        "created_at_iso": str(detail.get("created_at_iso") or payload.created_at_iso or ""),
                        "raw_text_lines": [str(line) for line in detail.get("raw_text_lines") or []],
                    }
                )
                payload.article = article
                if len(str(article.get("body_text") or "")) < 120:
                    payload.extraction_warnings.append("article_detail_too_short")
                if article.get("body_text") and len(str(article.get("body_text") or "")) >= 120 and (not payload.text or len(payload.text) < 80):
                    payload.text = str(article.get("body_text"))
                log(f"文章详情已补全: chars={len(str(article.get('body_text') or ''))}")
        except Exception as exc:  # noqa: BLE001
            payload.extraction_warnings.append(f"article_detail_failed: {exc}")
            log(f"文章详情抓取失败: {article_url} reason={exc}")


def needs_show_more_expansion(payload: TweetPayload) -> bool:
    lines = [str(line) for line in payload.raw_text_lines or []]
    return any(line.strip() in {"显示更多", "Show more"} for line in lines)


class ShowMoreExpansionError(RuntimeError):
    """Typed X long-form expansion failure for the canonical browser seam."""


def merge_expanded_payload(original: TweetPayload, expanded: TweetPayload) -> None:
    if expanded.text and len(expanded.text) > len(original.text or ""):
        original.text = expanded.text
    if expanded.raw_text_lines and len(expanded.raw_text_lines) > len(original.raw_text_lines or []):
        original.raw_text_lines = expanded.raw_text_lines
    elif expanded.raw_text_lines:
        original.raw_text_lines = expanded.raw_text_lines
    if expanded.media and len(expanded.media) >= len(original.media):
        original.media = expanded.media
    if expanded.links and len(expanded.links) >= len(original.links):
        original.links = expanded.links
    if expanded.card:
        original.card = expanded.card
    if expanded.metrics:
        original.metrics = expanded.metrics
    if expanded.reply_to:
        original.reply_to = expanded.reply_to
    if expanded.quoted_tweet:
        original.quoted_tweet = expanded.quoted_tweet
    if expanded.article:
        original.article = expanded.article
    original.extraction_warnings = [
        warning for warning in original.extraction_warnings if warning != "show_more_unexpanded"
    ]


def expand_show_more_payloads(book: ActionBook, payloads: list[TweetPayload], *, max_expansions: int = 2) -> None:
    expanded_count = 0
    for index, payload in enumerate(payloads, start=1):
        if not needs_show_more_expansion(payload):
            continue
        if expanded_count >= max_expansions:
            break
        if not payload.source_url:
            raise ShowMoreExpansionError("selector_failed: show more post has no source URL")
        log(f"展开显示更多: {index}/{len(payloads)} {payload.source_url}")
        try:
            clicked = click_show_more_for_payload(book, payload)
            if not clicked:
                raise ShowMoreExpansionError("selector_failed: show more control was not clicked")
            parent_expanded = wait_for_parent_expansion(book, payload)
            if parent_expanded is None or needs_show_more_expansion(parent_expanded):
                raise ShowMoreExpansionError("page_not_ready: parent show more control did not disappear")
            merge_expanded_payload(payload, parent_expanded)
            with temporary_tab(book, payload.source_url) as tab_id:
                wait_tab_articles(book, tab_id)
                expanded = wait_for_expanded_payload(book, payload, tab_id)
                if expanded is None:
                    candidates = extract_visible_tweets(book, payload.source_page, tab_id=tab_id)
                    expanded = next((item for item in candidates if item.tweet_id and item.tweet_id == payload.tweet_id), None)
                    if expanded is None and candidates:
                        expanded = candidates[0]
                if expanded is None:
                    raise ShowMoreExpansionError("page_not_ready: expanded post was not found")
                merge_expanded_payload(payload, expanded)
                if needs_show_more_expansion(payload) or len(payload.text) <= 0:
                    raise ShowMoreExpansionError("page_not_ready: expanded text is still unavailable")
                expanded_count += 1
                log(f"详情正文已补全: clicked_show_more={bool(clicked)} chars={len(payload.text)}")
        except ShowMoreExpansionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ShowMoreExpansionError(f"selector_failed: show more expansion failed: {exc}") from exc


def collect_tweets(book: ActionBook, source: str, count: int, max_scrolls: int) -> list[TweetPayload]:
    seen: set[str] = set()
    payloads: list[TweetPayload] = []
    idle_rounds = 0
    for round_no in range(1, max_scrolls + 1):
        visible = extract_visible_tweets(book, source)
        added = 0
        for payload in visible:
            key = payload.source_url or f"{payload.author_handle}|{payload.text[:160]}"
            if not key or key in seen:
                continue
            seen.add(key)
            payloads.append(payload)
            added += 1
            if len(payloads) >= count:
                log(f"收集完成: source={source} count={len(payloads)}")
                return payloads
        log(f"收集轮次: source={source} round={round_no} visible={len(visible)} added={added} total={len(payloads)}")
        idle_rounds = idle_rounds + 1 if added == 0 else 0
        if idle_rounds >= 4:
            break
        before = read_scroll_y(book)
        scroll_page(book)
        after = wait_for_scroll_progress(book, before)
        if after <= before + 5 and added == 0:
            idle_rounds += 1
    return payloads[:count]


def media_download_url(media: dict[str, Any]) -> str:
    return str(media.get("url") or media.get("poster_url") or "")


def tweet_media_flags(payload: TweetPayload) -> str:
    flags: list[str] = []
    if payload.article and payload.tweet_type != "article":
        flags.append("article")
    media_kinds = {str(item.get("kind") or "") for item in payload.media if isinstance(item, dict)}
    article_blocks = payload.article.get("markdown_blocks") if isinstance(payload.article, dict) else []
    has_article_images = any(
        isinstance(block, dict) and block.get("type") == "image"
        for block in (article_blocks or [])
    )
    if "image" in media_kinds:
        flags.append("image")
    elif has_article_images:
        flags.append("image")
    if "video" in media_kinds:
        flags.append("video")
    if payload.card:
        flags.append("card")
    if not flags:
        flags.append("text")
    return "_".join(flags)


def parse_metric_value(label: str) -> str:
    text = str(label or "").strip()
    if not text:
        return ""
    match = re.search(r"([\d,.]+)\s*(万|K|M|B)?", text, re.I)
    if not match:
        return text
    return "".join(part for part in match.groups() if part)


def render_metrics_lines(payload: TweetPayload) -> list[str]:
    labels = {
        "replies": "回复",
        "reposts": "转帖",
        "likes": "喜欢",
        "bookmarks": "书签",
        "views": "查看",
    }
    lines = []
    for key, label in labels.items():
        raw = str((payload.metrics or {}).get(key) or "").strip()
        if not raw:
            continue
        value = parse_metric_value(raw)
        lines.append(f"- {label}: {value} ({raw})")
    return lines or ["- 未读取到指标"]


def render_raw_text(payload: TweetPayload) -> str:
    lines = [
        "# X 原始可见文本",
        "",
        f"- 类型: {payload.tweet_type}",
        f"- 作者: {payload.author_name} {payload.author_handle}".strip(),
        f"- 时间: {payload.created_at_iso or payload.created_at_text}",
        f"- 来源: {payload.source_url}",
        "",
        "## 指标说明",
        "",
        *render_metrics_lines(payload),
        "",
        "## 原始行",
        "",
        *[str(line) for line in payload.raw_text_lines],
    ]
    if payload.article:
        article = payload.article
        article_lines = [str(line) for line in article.get("body_lines") or [] if str(line).strip()]
        article_blocks = [block for block in article.get("markdown_blocks") or [] if isinstance(block, dict)]
        article_images = [
            block for block in article_blocks
            if block.get("type") == "image" and (block.get("file") or block.get("url"))
        ]
        if article_lines or article_images:
            lines.extend(
                [
                    "",
                    "## 文章详情正文",
                    "",
                    f"- 文章链接: {article.get('detail_url') or article.get('url') or payload.source_url}",
                    f"- 正文字数: {len(str(article.get('body_text') or ''))}",
                    f"- 正文行数: {len(article_lines)}",
                    f"- 图片数: {len(article_images)}",
                    "",
                ]
            )
            if article_blocks:
                for block in article_blocks:
                    if block.get("type") == "text":
                        text = str(block.get("text") or "").strip()
                        if text:
                            lines.extend([text, ""])
                    elif block.get("type") == "image":
                        image_ref = str(block.get("file") or block.get("url") or "").strip()
                        alt = str(block.get("alt") or "图像").strip()
                        if image_ref:
                            lines.extend([f"[图片] {alt}: {image_ref}", ""])
            else:
                lines.extend(article_lines)
    return "\n".join(lines).strip() + "\n"


def render_article_markdown(article: dict[str, Any]) -> list[str]:
    title = str(article.get("title") or "").strip()
    detail_url = str(article.get("detail_url") or article.get("url") or "").strip()
    body = str(article.get("body_text") or "").strip()
    preview = str(article.get("preview_text") or "").strip()
    links = [link for link in article.get("links") or [] if isinstance(link, dict)]
    blocks = [block for block in article.get("markdown_blocks") or [] if isinstance(block, dict)]
    lines = ["", "## 文章正文", ""]
    if title:
        lines.extend([f"### {title}", ""])
    if detail_url:
        lines.extend([f"- 文章链接: {detail_url}", ""])
    if blocks:
        previous_text = ""
        for block in blocks:
            if block.get("type") == "text":
                text = str(block.get("text") or "").strip()
                if text and text != previous_text:
                    lines.extend([text, ""])
                    previous_text = text
            elif block.get("type") == "image":
                url = str(block.get("file") or block.get("url") or "").strip()
                alt = str(block.get("alt") or "article image").strip() or "article image"
                if url:
                    lines.extend([f"![{alt}]({url})", ""])
    elif body:
        lines.extend([body, ""])
    elif preview:
        lines.extend([preview, ""])
    else:
        lines.extend(["(未提取到文章正文)", ""])
    if links:
        lines.extend(["### 文章链接", ""])
        for link in links:
            text = str(link.get("text") or "").strip()
            url = str(link.get("url") or "").strip()
            if url:
                lines.append(f"- {text + ' ' if text else ''}{url}")
    return lines


def download_article_images(
    article: dict[str, Any],
    media_dir: Path,
    saved_media: list[dict[str, str]],
) -> None:
    if not article:
        return
    source_to_file = {
        str(item.get("source") or ""): str(item.get("file") or "")
        for item in saved_media
        if item.get("source") and item.get("file")
    }
    blocks = [block for block in article.get("markdown_blocks") or [] if isinstance(block, dict)]
    image_index = 1
    for block in blocks:
        if block.get("type") != "image":
            continue
        url = str(block.get("url") or "").strip()
        if not url:
            continue
        if url in source_to_file:
            block["file"] = source_to_file[url]
            continue
        saved = download_media(url, media_dir, f"article-image-{image_index:02d}")
        image_index += 1
        if saved:
            rel_path = f"media/{saved}"
            block["file"] = rel_path
            source_to_file[url] = rel_path
            saved_media.append({"source": url, "file": rel_path, "kind": "article_image"})
    article["markdown_blocks"] = blocks


def download_media(url: str, output_dir: Path, name: str) -> str | None:
    if not url or url.startswith("blob:"):
        return None
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://x.com/",
    }
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log(f"媒体下载失败: url={url} reason={exc}")
        return None
    ext = mimetypes.guess_extension(content_type) or Path(url.split("?", 1)[0]).suffix or ".bin"
    if ext == ".jpe":
        ext = ".jpg"
    output_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{name}{ext}"
    (output_dir / file_name).write_bytes(data)
    return file_name


def write_tweet(payload: TweetPayload, output_dir: Path, index: int) -> Path:
    safe_handle = sanitize_name(payload.author_handle.replace("@", ""), fallback="unknown", max_length=24)
    safe_type = sanitize_name(payload.tweet_type, fallback="tweet", max_length=24)
    safe_flags = sanitize_name(tweet_media_flags(payload), fallback="text", max_length=48)
    tweet_id = payload.tweet_id or f"{index:03d}"
    folder = output_dir / f"{index:03d}_{safe_type}_{safe_flags}_{safe_handle}_{tweet_id}"
    temp = output_dir / f".{folder.name}.partial"
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True, exist_ok=False)
    saved_media: list[dict[str, str]] = []
    try:
        media_dir = temp / "media"
        for media_index, media in enumerate(payload.media, start=1):
            kind = str(media.get("kind") or "media")
            prefix = "video-poster" if kind == "video" and not media.get("url") else kind
            saved = download_media(media_download_url(media), media_dir, f"{prefix}-{media_index:02d}")
            if saved:
                saved_media.append({"source": media_download_url(media), "file": f"media/{saved}", "kind": kind})
        if payload.article:
            download_article_images(payload.article, media_dir, saved_media)
        data = asdict(payload)
        data["saved_media"] = saved_media
        (temp / "metadata.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (temp / "raw.txt").write_text(render_raw_text(payload), encoding="utf-8")
        lines = [
            f"# {payload.author_name or payload.author_handle or 'X Post'}",
            "",
            f"- 类型: {payload.tweet_type}",
            f"- 作者: {payload.author_name} {payload.author_handle}".strip(),
            f"- 时间: {payload.created_at_iso or payload.created_at_text}",
            f"- 来源: {payload.source_url}",
            f"- 媒体数: {len(payload.media)}",
            f"- 外链数: {len(payload.links)}",
            f"- 已收藏: {'是' if payload.is_bookmarked else '否'}",
            "",
            "## 正文",
            "",
            payload.text or "(无正文)",
        ]
        if payload.reply_to:
            lines.extend(["", "## 回复对象", "", json.dumps(payload.reply_to, ensure_ascii=False)])
        if payload.quoted_tweet:
            lines.extend(["", "## 引用推文", "", json.dumps(payload.quoted_tweet, ensure_ascii=False, indent=2)])
        if payload.article:
            lines.extend(render_article_markdown(payload.article))
        if payload.card:
            lines.extend(["", "## 卡片", "", json.dumps(payload.card, ensure_ascii=False, indent=2)])
        if payload.links:
            lines.extend(["", "## 链接", "", *[f"- {link.get('text') or ''} {link.get('url') or ''}".strip() for link in payload.links]])
        if saved_media:
            lines.extend(["", "## 已保存媒体", "", *[f"- {item['kind']}: {item['file']}" for item in saved_media]])
        (temp / "content.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        final = folder
        suffix = 2
        while final.exists():
            final = output_dir / f"{folder.name}-{suffix}"
            suffix += 1
        temp.replace(final)
        return final
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def write_summary(payloads: list[TweetPayload], output_dir: Path, source: str, action: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = [asdict(payload) for payload in payloads]
    (output_dir / "summary.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failures = [
        {
            "index": index,
            "source_page": payload.source_page,
            "candidate_url": payload.source_url,
            "reason": "extraction_warnings",
            "warnings": payload.extraction_warnings,
            "raw_text_preview": "\n".join(payload.raw_text_lines[:12]),
        }
        for index, payload in enumerate(payloads, start=1)
        if payload.extraction_warnings
    ]
    (output_dir / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    type_counts: dict[str, int] = {}
    for payload in payloads:
        type_counts[payload.tweet_type] = type_counts.get(payload.tweet_type, 0) + 1
    action_label = "浏览结果" if action == "view" else "下载结果"
    lines = [
        f"# X {source} {action_label}",
        "",
        f"- 帖子数: {len(payloads)}",
        f"- 类型统计: {json.dumps(type_counts, ensure_ascii=False)}",
        "",
    ]
    for index, payload in enumerate(payloads, start=1):
        lines.extend(
            [
                f"## {index}. {payload.author_name or payload.author_handle or payload.tweet_id}",
                "",
                f"- 类型: {payload.tweet_type}",
                f"- 作者: {payload.author_name} {payload.author_handle}".strip(),
                f"- 时间: {payload.created_at_iso or payload.created_at_text}",
                f"- 来源: {payload.source_url}",
                f"- 媒体数: {len(payload.media)}",
                f"- 外链数: {len(payload.links)}",
                f"- 警告: {', '.join(payload.extraction_warnings) if payload.extraction_warnings else ''}",
                "",
                (payload.text or "\n".join(payload.raw_text_lines[:8]) or "(无正文)")[:800],
                "",
            ]
        )
    (output_dir / "summary.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def wait_for_visible_tweets(book: ActionBook, source: str, timeout_secs: float = 3.0) -> None:
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        if extract_visible_tweets(book, source):
            return
        time.sleep(0.4)


def run_download(args: argparse.Namespace, source: str, url: str) -> int:
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_action_output_dir(source, "download")
    book = attach_workflow(args, url, ActionBook)
    book.goto(url)
    wait_page_ready(book, source)
    book.eval("window.scrollTo(0, 0); window.dispatchEvent(new Event('scroll')); true", timeout=10.0)
    wait_for_visible_tweets(book, source)
    payloads = collect_tweets(book, source, args.count, args.max_scrolls)
    expand_show_more_payloads(book, payloads)
    enrich_article_payloads(book, payloads)
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, payload in enumerate(payloads, start=1):
        folder = write_tweet(payload, output_dir, index)
        log(f"已写入: {folder}")
    write_summary(payloads, output_dir, source, "download")
    result = {
        "source": source,
        "requested_count": args.count,
        "count": len(payloads),
        "output_dir": str(output_dir),
        "summary_json": str(output_dir / "summary.json"),
        "summary_md": str(output_dir / "summary.md"),
        "failures_json": str(output_dir / "failures.json"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_view(args: argparse.Namespace, source: str, url: str) -> int:
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_action_output_dir(source, "view")
    book = attach_workflow(args, url, ActionBook)
    book.goto(url)
    wait_page_ready(book, source)
    book.eval("window.scrollTo(0, 0); window.dispatchEvent(new Event('scroll')); true", timeout=10.0)
    wait_for_visible_tweets(book, source)
    payloads = collect_tweets(book, source, args.count, args.max_scrolls)
    expand_show_more_payloads(book, payloads)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_summary(payloads, output_dir, source, "view")
    result = {
        "source": source,
        "action": "view",
        "requested_count": args.count,
        "count": len(payloads),
        "output_dir": str(output_dir),
        "summary_json": str(output_dir / "summary.json"),
        "summary_md": str(output_dir / "summary.md"),
        "failures_json": str(output_dir / "failures.json"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_home_view(args: argparse.Namespace) -> int:
    return run_view(args, "home", HOME_URL)


def run_home_download(args: argparse.Namespace) -> int:
    return run_download(args, "home", HOME_URL)


def run_bookmarks_view(args: argparse.Namespace) -> int:
    return run_view(args, "bookmarks", BOOKMARKS_URL)


def run_bookmarks_download(args: argparse.Namespace) -> int:
    return run_download(args, "bookmarks", BOOKMARKS_URL)


def run_tweet_view(args: argparse.Namespace) -> int:
    return run_view(args, "tweet", args.url)


def run_tweet_download(args: argparse.Namespace) -> int:
    return run_download(args, "tweet", args.url)


def run_thread_view(args: argparse.Namespace) -> int:
    return run_view(args, "thread", args.url)


def run_thread_download(args: argparse.Namespace) -> int:
    return run_download(args, "thread", args.url)


def run_search_view(args: argparse.Namespace) -> int:
    query = urllib.parse.urlencode({"q": args.query, "src": "typed_query", "f": args.filter})
    return run_view(args, "search", f"{SEARCH_URL}?{query}")


def run_search_download(args: argparse.Namespace) -> int:
    query = urllib.parse.urlencode({"q": args.query, "src": "typed_query", "f": args.filter})
    return run_download(args, "search", f"{SEARCH_URL}?{query}")


def normalize_profile_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("@"):
        return f"https://x.com/{raw[1:]}"
    if re.match(r"^[A-Za-z0-9_]{1,20}$", raw):
        return f"https://x.com/{raw}"
    return raw


def get_current_x_profile_url(book: ActionBook) -> str:
    value = unwrap_eval(
        book.eval(
            """(() => {
                const abs = value => {
                    if (!value) return '';
                    try { return new URL(value, location.origin).toString(); }
                    catch (e) { return ''; }
                };
                const profileLink =
                    document.querySelector('[data-testid="AppTabBar_Profile_Link"][href]')
                    || [...document.querySelectorAll('a[href]')].find(anchor => {
                        const href = anchor.getAttribute('href') || '';
                        const text = (anchor.innerText || anchor.getAttribute('aria-label') || '').trim();
                        return /^\\/[^/?#]+$/i.test(href)
                            && !/^\\/(home|explore|notifications|messages|i|search|settings|compose)$/i.test(href)
                            && /Profile|个人资料|个人主页|我的/i.test(text);
                    });
                if (profileLink) return abs(profileLink.getAttribute('href'));
                const accountText = document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"]')?.innerText || '';
                const handle = (accountText.match(/@([A-Za-z0-9_]{1,20})/) || [])[1] || '';
                if (handle) return `https://x.com/${handle}`;
                return '';
            })()""",
            timeout=15.0,
        )
    )
    return normalize_profile_url(str(value or ""))


def run_profile_download(args: argparse.Namespace) -> int:
    profile_url = normalize_profile_url(args.profile_url or args.handle)
    if not profile_url:
        raise argparse.ArgumentTypeError("profile download requires --profile-url or --handle")
    return run_download(args, "profile", profile_url)


def run_profile_view(args: argparse.Namespace) -> int:
    profile_url = normalize_profile_url(args.profile_url or args.handle)
    if not profile_url:
        raise argparse.ArgumentTypeError("profile view requires --profile-url or --handle")
    return run_view(args, "profile", profile_url)


def resolve_current_x_profile_url(args: argparse.Namespace) -> str:
    book = attach_workflow(args, HOME_URL, ActionBook)
    book.goto(HOME_URL)
    wait_page_ready(book, "me")
    profile_url = get_current_x_profile_url(book)
    if not profile_url:
        raise RuntimeError("无法自动识别当前 X 登录账号主页")
    log(f"当前账号主页: {profile_url}")
    return profile_url


def run_me_view(args: argparse.Namespace) -> int:
    profile_url = resolve_current_x_profile_url(args)
    return run_view(args, "me", profile_url)


def run_me_download(args: argparse.Namespace) -> int:
    profile_url = resolve_current_x_profile_url(args)
    return run_download(args, "me", profile_url)



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run X workflows through ActionBook.")
    subparsers = parser.add_subparsers(dest="area", required=True)

    def add_common(target: argparse.ArgumentParser, default_count: int = 30, default_max_scrolls: int = 18) -> None:
        add_workflow_args(target)
        target.add_argument("--count", type=int, default=default_count, help="Number of posts to process")
        target.add_argument("--max-scrolls", type=int, default=default_max_scrolls, help="Maximum scroll rounds")
        target.add_argument("--output-dir", help="Output directory")

    home = subparsers.add_parser("home", help="X home timeline workflows")
    home_sub = home.add_subparsers(dest="mode", required=True)
    home_view = home_sub.add_parser("view", help="View visible X home posts")
    add_common(home_view)
    home_view.set_defaults(func=run_home_view)
    home_download = home_sub.add_parser("download", help="Download visible X home posts into local files")
    add_common(home_download)
    home_download.set_defaults(func=run_home_download)

    bookmarks = subparsers.add_parser("bookmarks", help="X bookmarks workflows")
    bookmarks_sub = bookmarks.add_subparsers(dest="mode", required=True)
    bookmarks_view = bookmarks_sub.add_parser("view", help="View X bookmark posts")
    add_common(bookmarks_view)
    bookmarks_view.set_defaults(func=run_bookmarks_view)
    bookmarks_download = bookmarks_sub.add_parser("download", help="Download X bookmark posts into local files")
    add_common(bookmarks_download)
    bookmarks_download.set_defaults(func=run_bookmarks_download)

    tweet = subparsers.add_parser("tweet", help="X single tweet workflows")
    tweet_sub = tweet.add_subparsers(dest="mode", required=True)
    tweet_view = tweet_sub.add_parser("view", help="View one X tweet URL")
    tweet_view.add_argument("--url", required=True, help="X tweet/status URL")
    add_common(tweet_view, default_count=1, default_max_scrolls=2)
    tweet_view.set_defaults(func=run_tweet_view)
    tweet_download = tweet_sub.add_parser("download", help="Download one X tweet URL into local files")
    tweet_download.add_argument("--url", required=True, help="X tweet/status URL")
    add_common(tweet_download, default_count=1, default_max_scrolls=2)
    tweet_download.set_defaults(func=run_tweet_download)

    thread = subparsers.add_parser("thread", help="X thread workflows")
    thread_sub = thread.add_subparsers(dest="mode", required=True)
    thread_view = thread_sub.add_parser("view", help="View a visible X thread from a tweet URL")
    thread_view.add_argument("--url", required=True, help="X tweet/status URL")
    add_common(thread_view, default_count=50, default_max_scrolls=24)
    thread_view.set_defaults(func=run_thread_view)
    thread_download = thread_sub.add_parser("download", help="Download a visible X thread from a tweet URL")
    thread_download.add_argument("--url", required=True, help="X tweet/status URL")
    add_common(thread_download, default_count=50, default_max_scrolls=24)
    thread_download.set_defaults(func=run_thread_download)

    search = subparsers.add_parser("search", help="X search workflows")
    search_sub = search.add_subparsers(dest="mode", required=True)
    search_view = search_sub.add_parser("view", help="View X search results")
    search_view.add_argument("--query", required=True, help="X search query")
    search_view.add_argument("--filter", choices=("live", "top", "user", "image", "video"), default="live")
    add_common(search_view, default_count=30, default_max_scrolls=18)
    search_view.set_defaults(func=run_search_view)
    search_download = search_sub.add_parser("download", help="Download X search results into local files")
    search_download.add_argument("--query", required=True, help="X search query")
    search_download.add_argument("--filter", choices=("live", "top", "user", "image", "video"), default="live")
    add_common(search_download, default_count=30, default_max_scrolls=18)
    search_download.set_defaults(func=run_search_download)

    profile = subparsers.add_parser("profile", help="X profile workflows")
    profile_sub = profile.add_subparsers(dest="mode", required=True)
    profile_view = profile_sub.add_parser("view", help="View posts from an X profile")
    profile_view.add_argument("--profile-url", default="", help="X profile URL")
    profile_view.add_argument("--handle", default="", help="X handle, with or without @")
    add_common(profile_view, default_count=30, default_max_scrolls=18)
    profile_view.set_defaults(func=run_profile_view)
    profile_download = profile_sub.add_parser("download", help="Download posts from an X profile")
    profile_download.add_argument("--profile-url", default="", help="X profile URL")
    profile_download.add_argument("--handle", default="", help="X handle, with or without @")
    add_common(profile_download, default_count=30, default_max_scrolls=18)
    profile_download.set_defaults(func=run_profile_download)

    me = subparsers.add_parser("me", help="Current X account profile workflows")
    me_sub = me.add_subparsers(dest="mode", required=True)
    me_view = me_sub.add_parser("view", help="View posts from the current X account")
    add_common(me_view, default_count=30, default_max_scrolls=18)
    me_view.set_defaults(func=run_me_view)
    me_download = me_sub.add_parser("download", help="Download posts from the current X account")
    add_common(me_download, default_count=30, default_max_scrolls=18)
    me_download.set_defaults(func=run_me_download)

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
