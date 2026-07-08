#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Weibo workflow helper for the action-browser skill.

The workflow uses ActionBook extension mode and the user's existing Chrome
session. It covers single post, profile, search, and home list extraction with
optional media download.
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
from scripts.adapter_runtime import prepare_task_book, wait_for_page_settle
from scripts.actionbook_session import ActionBookSession as ActionBook
from scripts.script_common import DEFAULT_TAB, add_session_tab_args, log, unwrap_eval


WEIBO_HOME_URL = "https://weibo.com"
WEIBO_SEARCH_URL = "https://s.weibo.com/weibo"
DEFAULT_SESSION = "weibo-task"
SKILL_DIR = Path(__file__).resolve().parents[2]
ASSETS_DIR = SKILL_DIR / "assets" / "weibo"


@dataclass
class WeiboPayload:
    weibo_id: str
    mid: str
    source_url: str
    source_page: str
    author_name: str
    author_id: str
    author_profile_url: str
    author_avatar_url: str
    text: str
    created_at_text: str
    source_device: str
    post_type: str
    reposted_weibo: dict[str, Any]
    media: list[dict[str, Any]]
    links: list[dict[str, str]]
    topics: list[str]
    mentions: list[str]
    metrics: dict[str, str]
    raw_text_lines: list[str]
    extraction_warnings: list[str]
def sanitize_name(value: str, fallback: str = "item", max_length: int = 64) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "", value or "").strip("._-")
    return (cleaned or fallback)[:max_length]
def default_action_output_dir(source: str, action: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    action_dir = "downloads" if action == "download" else "views"
    return ASSETS_DIR / action_dir / source / stamp


def normalize_weibo_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        return "https:" + raw
    if raw.startswith("/"):
        return urllib.parse.urljoin(WEIBO_HOME_URL, raw)
    if not re.match(r"^https?://", raw, re.I):
        return "https://" + raw
    return raw


def extract_mid(value: str) -> str:
    text = str(value or "")
    for pattern in (
        r"[?&]mid=(\d+)",
        r"/detail/(\d+)",
        r"/status(?:es)?/(\d+)",
        r"\bmid[:=](\d+)",
    ):
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1)
    return ""


def extract_weibo_id(value: str) -> str:
    text = str(value or "")
    for pattern in (
        r"weibo\.com/(?:u/)?\d+/([A-Za-z0-9]+)",
        r"weibo\.com/detail/(\d+)",
        r"m\.weibo\.cn/detail/(\d+)",
    ):
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1)
    return extract_mid(text)


def clean_html_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value or "")
    entities = {
        "&nbsp;": " ",
        "&lt;": "<",
        "&gt;": ">",
        "&amp;": "&",
        "&quot;": '"',
        "&#39;": "'",
    }
    for old, new in entities.items():
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip()


def read_count(value: Any, default: int = 30, max_value: int = 50) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = default
    return max(1, min(count, max_value))


def prepare_weibo_book(args: argparse.Namespace, url: str = WEIBO_HOME_URL) -> ActionBook:
    return prepare_task_book(args, url, ActionBook)


def api_eval(book: ActionBook, script: str, label: str, timeout: float = 45.0) -> Any:
    value = unwrap_eval(book.eval(script, timeout=timeout))
    if isinstance(value, dict) and value.get("error"):
        raise RuntimeError(f"{label}: {value.get('error')}")
    return value


def ensure_api_context(book: ActionBook) -> None:
    book.goto(WEIBO_HOME_URL)
    state = get_page_state(book)
    if page_has_login_or_risk(state):
        raise RuntimeError(f"Weibo requires login or verification: {state.get('href')} title={state.get('title')}")


def self_uid_js() -> str:
    return """
      const app = document.querySelector('#app')?.__vue_app__;
      const store = app?.config?.globalProperties?.$store;
      const storeUid = store?.state?.config?.config?.uid;
      if (storeUid) return String(storeUid);
      const cfgResp = await fetch('/ajax/config/get_config', { credentials: 'include' });
      if (cfgResp.ok) {
        const cfg = await cfgResp.json();
        if (cfg.data?.uid) return String(cfg.data.uid);
      }
      return '';
    """


def status_to_payload(item: dict[str, Any], source: str) -> WeiboPayload:
    user = item.get("user") if isinstance(item.get("user"), dict) else {}
    author_id = str(user.get("id") or user.get("idstr") or "")
    mblogid = str(item.get("mblogid") or "")
    mid = str(item.get("idstr") or item.get("id") or "")
    text = str(item.get("text_raw") or clean_html_text(str(item.get("text") or "")))
    media: list[dict[str, Any]] = []
    pic_infos = item.get("pic_infos") if isinstance(item.get("pic_infos"), dict) else {}
    for pic in pic_infos.values():
        if not isinstance(pic, dict):
            continue
        candidate = (
            pic.get("original")
            or pic.get("large")
            or pic.get("mw2000")
            or pic.get("mw690")
            or pic.get("thumbnail")
            or {}
        )
        if isinstance(candidate, dict) and candidate.get("url"):
            media.append({
                "kind": "image",
                "url": str(candidate.get("url") or ""),
                "alt_text": "",
                "width": candidate.get("width") or 0,
                "height": candidate.get("height") or 0,
            })
    page_info = item.get("page_info") if isinstance(item.get("page_info"), dict) else {}
    if page_info:
        media_info = page_info.get("media_info") if isinstance(page_info.get("media_info"), dict) else {}
        video_url = str(
            media_info.get("stream_url")
            or media_info.get("mp4_720p_mp4")
            or media_info.get("mp4_hd_url")
            or media_info.get("mp4_sd_url")
            or ""
        )
        poster = str(page_info.get("page_pic") or media_info.get("cover_image") or media_info.get("poster") or "")
        if video_url or poster:
            media.append({"kind": "video", "url": video_url, "poster_url": poster, "duration_text": ""})
    links = []
    for link in item.get("url_struct") or []:
        if isinstance(link, dict):
            url = str(link.get("long_url") or link.get("short_url") or link.get("url_title") or "")
            if url:
                links.append({"text": str(link.get("url_title") or ""), "url": normalize_weibo_url(url)})
    reposted = {}
    retweeted = item.get("retweeted_status") if isinstance(item.get("retweeted_status"), dict) else {}
    if retweeted:
        rt_user = retweeted.get("user") if isinstance(retweeted.get("user"), dict) else {}
        reposted = {
            "weibo_id": str(retweeted.get("mblogid") or retweeted.get("idstr") or retweeted.get("id") or ""),
            "mid": str(retweeted.get("idstr") or retweeted.get("id") or ""),
            "source_url": f"https://weibo.com/{rt_user.get('id') or ''}/{retweeted.get('mblogid') or ''}".rstrip("/"),
            "author_name": str(rt_user.get("screen_name") or ""),
            "author_id": str(rt_user.get("id") or ""),
            "text": str(retweeted.get("text_raw") or clean_html_text(str(retweeted.get("text") or ""))),
        }
    source_url = f"https://weibo.com/{author_id}/{mblogid}" if author_id and mblogid else ""
    return WeiboPayload(
        weibo_id=mblogid or mid,
        mid=mid,
        source_url=source_url,
        source_page=source,
        author_name=str(user.get("screen_name") or ""),
        author_id=author_id,
        author_profile_url=f"https://weibo.com/u/{author_id}" if author_id else "",
        author_avatar_url=str(user.get("avatar_hd") or user.get("avatar_large") or user.get("profile_image_url") or ""),
        text=text,
        created_at_text=str(item.get("created_at") or ""),
        source_device=clean_html_text(str(item.get("source") or "")),
        post_type="repost" if reposted else "post",
        reposted_weibo=reposted,
        media=media,
        links=links,
        topics=[match.strip() for match in re.findall(r"#([^#\n]{1,80})#", text)],
        mentions=[match.strip() for match in re.findall(r"@([\w\u4e00-\u9fff.-]{1,40})", text)],
        metrics={
            "reposts": str(item.get("reposts_count") or 0),
            "comments": str(item.get("comments_count") or 0),
            "likes": str(item.get("attitudes_count") or 0),
        },
        raw_text_lines=[line for line in text.splitlines() if line.strip()],
        extraction_warnings=[],
    )


EXTRACT_VISIBLE_WEIBOS_JS = r"""
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
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const extractMid = value => {
    const raw = String(value || '');
    const match = raw.match(/[?&]mid=(\d+)/i)
      || raw.match(/\/detail\/(\d+)/i)
      || raw.match(/\/status(?:es)?\/(\d+)/i)
      || raw.match(/\bmid[:=](\d+)/i);
    return match ? match[1] : '';
  };
  const extractWeiboId = value => {
    const raw = String(value || '');
    const match = raw.match(/weibo\.com\/(?:u\/)?\d+\/([A-Za-z0-9]+)/i)
      || raw.match(/weibo\.com\/detail\/(\d+)/i)
      || raw.match(/m\.weibo\.cn\/detail\/(\d+)/i);
    return match ? match[1] : extractMid(raw);
  };
  const isMetricLine = line =>
    /^(转发|评论|赞|点赞|收藏|分享)$/.test(line)
    || /^[\d,.]+$/.test(line)
    || /^[\d,.]+万$/.test(line)
    || /^(?:转发|评论|赞|点赞|收藏|分享)\s*[\d,.万]*$/.test(line)
    || /^[\d,.万]+\s*(?:转发|评论|赞|点赞)$/.test(line);
  const isChromeLine = line =>
    !line
    || line === '关注'
    || line === '已关注'
    || line === '超话'
    || line === '展开'
    || line === '展开全文'
    || line === '收起全文'
    || line === '更多'
    || line === '举报'
    || line === 'û收藏'
    || line === 'û分享'
    || line === '赞'
    || line === '评论'
    || line === '转发'
    || line === '分享'
    || /^广告/.test(line)
    || /^推荐/.test(line)
    || /^微博正文$/.test(line)
    || /^视频$/.test(line)
    || /^图片$/.test(line)
    || /^网页链接$/.test(line)
    || isMetricLine(line);
  const cleanContentText = text => linesOf(text)
    .map(line => line.replace(/\s*(?:\.\.\.|…)\s*展开\s*$/g, '').trim())
    .filter(line => line && !['长图', '展开', '展开全文', '收起全文'].includes(line))
    .join('\n');
  const profileHrefRe = /\/(?:u\/)?(\d+)(?:[/?#]|$)|\/profile\/(\d+)/i;
  const parseAuthor = (root, sourceUrl = '') => {
    const links = [...root.querySelectorAll('a[href]')].map(anchor => ({
      href: absUrl(anchor.getAttribute('href')),
      text: normalize(anchor.innerText || anchor.getAttribute('title') || anchor.getAttribute('aria-label') || ''),
    }));
    const sourceUid = (String(sourceUrl || '').match(/weibo\.com\/(?:u\/)?(\d+)\//i) || [])[1] || '';
    const sourceProfile = sourceUid
      ? links.find(item => {
          const match = item.href.match(profileHrefRe);
          const id = match && (match[1] || match[2]);
          return id === sourceUid && item.text && !/^#.+#$/.test(item.text);
        })
      : null;
    const profile = sourceProfile
      || links.find(item => profileHrefRe.test(item.href) && item.text && !/^#.+#$/.test(item.text) && !/关注了$/.test(item.text))
      || links.find(item => profileHrefRe.test(item.href));
    const idMatch = profile?.href?.match(profileHrefRe);
    const avatar = [...root.querySelectorAll('img')]
      .map(img => img.currentSrc || img.src || '')
      .find(src => /avatar|sinaimg\.cn\/.*(?:50|180|large)|tvax|tva\d+\.sinaimg/i.test(src) && !/emotion|face|icon/i.test(src)) || '';
    return {
      name: profile?.text?.split('\n').find(Boolean) || '',
      id: (idMatch && (idMatch[1] || idMatch[2])) || '',
      profile_url: profile?.href || '',
      avatar_url: avatar,
    };
  };
  const parseLinks = root => uniq([...root.querySelectorAll('a[href]')].map(anchor => {
    const href = absUrl(anchor.getAttribute('href'));
    const text = normalize(anchor.innerText || anchor.getAttribute('title') || anchor.getAttribute('aria-label') || '');
    return { url: href, text };
  }).filter(item =>
    item.url
    && !profileHrefRe.test(item.url)
    && !/(?:weibo\.com|m\.weibo\.cn)\/(?:detail\/\d+|\d+\/[A-Za-z0-9]+)/i.test(item.url)
    && !item.url.includes('javascript:')
  ), item => item.url + '|' + item.text);
  const parseMedia = root => {
    const images = [...root.querySelectorAll('img')]
      .map(img => {
        const src = img.currentSrc || img.src || '';
        const rect = img.getBoundingClientRect();
        return {
          kind: 'image',
          url: src,
          alt_text: normalize(img.alt || img.getAttribute('title') || ''),
          width: img.naturalWidth || rect.width || 0,
          height: img.naturalHeight || rect.height || 0,
        };
      })
      .filter(item =>
        item.url
        && /sinaimg|sina\.cn|wx\d*\.sinaimg/i.test(item.url)
        && !/avatar|emotion|face|icon|badge|verified|default|loading/i.test(item.url)
        && Number(item.width || 0) >= 80
        && Number(item.height || 0) >= 80
      );
    const videos = [...root.querySelectorAll('video')]
      .map(video => ({
        kind: 'video',
        url: video.currentSrc || video.src || '',
        poster_url: video.poster || '',
        duration_text: '',
      }));
    const videoPosters = [...root.querySelectorAll('[class*="video"] img, [aria-label*="视频"] img')]
      .map(img => ({
        kind: 'video',
        url: '',
        poster_url: img.currentSrc || img.src || '',
        duration_text: '',
      }))
      .filter(item => item.poster_url && !/avatar|emotion|face|icon/i.test(item.poster_url));
    return uniq([...images, ...videos, ...videoPosters], item => item.kind + '|' + (item.url || item.poster_url));
  };
  const parseMetrics = root => {
    const metrics = {};
    const text = linesOf(root.innerText || '');
    const assign = (key, line) => {
      if (!metrics[key] && line) metrics[key] = line;
    };
    for (const line of text) {
      if (/转发/.test(line)) assign('reposts', line);
      if (/评论/.test(line)) assign('comments', line);
      if (/赞|点赞/.test(line)) assign('likes', line);
    }
    for (const node of root.querySelectorAll('a, button, [role="button"]')) {
      const label = normalize(node.innerText || node.getAttribute('aria-label') || node.getAttribute('title') || '');
      if (/转发/.test(label)) assign('reposts', label);
      if (/评论/.test(label)) assign('comments', label);
      if (/赞|点赞/.test(label)) assign('likes', label);
    }
    return metrics;
  };
  const extractText = root => {
    const preferred = [
      ...root.querySelectorAll('.wbpro-feed-content, [class*="wbtext"], [class*="ogText"], [node-type="feed_list_content_full"], [node-type="feed_list_content"], [class*="detail_wbtext"], .weibo-text, .weibo-og .weibo-text, .weibo-main .weibo-text'),
    ].map(node => normalize(node.innerText || node.textContent || '')).filter(Boolean);
    if (preferred.length) {
      return cleanContentText(preferred.sort((a, b) => b.length - a.length)[0]);
    }
    const lines = linesOf(root.innerText || '').filter(line => !isChromeLine(line));
    return cleanContentText(lines.slice(0, 12).join('\n'));
  };
  const parseCreatedAt = root => {
    const time = root.querySelector('time');
    if (time) return normalize(time.innerText || time.getAttribute('datetime') || time.getAttribute('title') || '');
    const links = [...root.querySelectorAll('a[href]')].map(anchor => normalize(anchor.innerText || anchor.getAttribute('title') || ''));
    return links.find(line => /(\d+分钟前|今天|昨天|\d+月\d+日|\d{4}-\d{1,2}-\d{1,2}|\d{4}年)/.test(line)) || '';
  };
  const parseSourceDevice = root => {
    const lines = linesOf(root.innerText || '');
    const index = lines.findIndex(line => /(\d+分钟前|今天|昨天|\d+月\d+日|\d{4}-\d{1,2}-\d{1,2}|\d{4}年)/.test(line));
    if (index >= 0) {
      const nearby = lines.slice(index + 1, index + 4).find(line => /^来自/.test(line) || /iPhone|Android|微博/.test(line));
      if (nearby) return nearby;
    }
    return '';
  };
  const parseRepost = root => {
    const repostRoot = root.querySelector('.weibo-rp, [class*="repost"], [node-type="feed_list_forwardContent"]');
    if (!repostRoot || repostRoot === root) return {};
    const author = parseAuthor(repostRoot);
    const text = extractText(repostRoot);
    const url = [...repostRoot.querySelectorAll('a[href]')]
      .map(anchor => absUrl(anchor.getAttribute('href')))
      .find(href => /(?:weibo\.com|m\.weibo\.cn)\/(?:detail\/\d+|\d+\/[A-Za-z0-9]+)/i.test(href)) || '';
    return {
      weibo_id: extractWeiboId(url),
      mid: extractMid(url),
      source_url: url,
      author_name: author.name,
      author_id: author.id,
      author_profile_url: author.profile_url,
      text,
      media: parseMedia(repostRoot),
    };
  };
  const roots = [
    ...document.querySelectorAll('article'),
    ...document.querySelectorAll('[action-type="feed_list_item"]'),
    ...document.querySelectorAll('[mid], [data-mid]'),
    ...document.querySelectorAll('.card-wrap, .m-panel.card, [data-card], .vue-recycle-scroller__item-view'),
  ].filter(visible);
  const uniqueRoots = [];
  const seenRoots = new Set();
  for (const root of roots) {
    if (seenRoots.has(root)) continue;
    if (uniqueRoots.some(parent => parent !== root && parent.contains(root))) continue;
    seenRoots.add(root);
    uniqueRoots.push(root);
  }
  return uniqueRoots.map(root => {
    const rawLines = linesOf(root.innerText || '');
    const mid = root.getAttribute('mid') || root.getAttribute('data-mid') || extractMid(root.outerHTML || '');
    const statusUrl = [...root.querySelectorAll('a[href]')]
      .map(anchor => absUrl(anchor.getAttribute('href')))
      .find(href => /(?:weibo\.com|m\.weibo\.cn)\/(?:detail\/\d+|\d+\/[A-Za-z0-9]+)/i.test(href)) || '';
    const sourceUrl = statusUrl || (mid ? `https://m.weibo.cn/detail/${mid}` : location.href);
    const author = parseAuthor(root, sourceUrl);
    const text = extractText(root);
    const media = parseMedia(root);
    const links = parseLinks(root);
    const reposted = parseRepost(root);
    const topics = uniq([...text.matchAll(/#([^#\n]{1,80})#/g)].map(match => match[1].trim()), item => item);
    const mentions = uniq([...text.matchAll(/@([\w\u4e00-\u9fff.-]{1,40})/g)].map(match => match[1].trim()), item => item);
    const warnings = [];
    if (!mid && !extractWeiboId(sourceUrl)) warnings.push('missing_weibo_id');
    if (!author.name && !author.id) warnings.push('missing_author');
    if (!text && media.length === 0 && !(reposted && reposted.text)) warnings.push('empty_content');
    return {
      weibo_id: extractWeiboId(sourceUrl),
      mid,
      source_url: sourceUrl,
      author_name: author.name,
      author_id: author.id,
      author_profile_url: author.profile_url,
      author_avatar_url: author.avatar_url,
      text,
      created_at_text: parseCreatedAt(root),
      source_device: parseSourceDevice(root),
      post_type: reposted && (reposted.text || reposted.source_url) ? 'repost' : 'post',
      reposted_weibo: reposted || {},
      media,
      links,
      topics,
      mentions,
      metrics: parseMetrics(root),
      raw_text_lines: rawLines,
      extraction_warnings: warnings,
    };
  }).filter(item => item.source_url || item.text || item.media.length || item.reposted_weibo?.text);
})()
"""


def extract_visible_weibos(book: ActionBook, source: str) -> list[WeiboPayload]:
    value = unwrap_eval(book.eval(EXTRACT_VISIBLE_WEIBOS_JS, timeout=45.0))
    if not isinstance(value, list):
        return []
    payloads: list[WeiboPayload] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        source_url = normalize_weibo_url(str(item.get("source_url") or ""))
        payloads.append(
            WeiboPayload(
                weibo_id=str(item.get("weibo_id") or extract_weibo_id(source_url)),
                mid=str(item.get("mid") or extract_mid(source_url)),
                source_url=source_url,
                source_page=source,
                author_name=str(item.get("author_name") or ""),
                author_id=str(item.get("author_id") or ""),
                author_profile_url=normalize_weibo_url(str(item.get("author_profile_url") or "")),
                author_avatar_url=str(item.get("author_avatar_url") or ""),
                text=str(item.get("text") or ""),
                created_at_text=str(item.get("created_at_text") or ""),
                source_device=str(item.get("source_device") or ""),
                post_type=str(item.get("post_type") or "post"),
                reposted_weibo=item.get("reposted_weibo") if isinstance(item.get("reposted_weibo"), dict) else {},
                media=[media for media in item.get("media") or [] if isinstance(media, dict)],
                links=[link for link in item.get("links") or [] if isinstance(link, dict)],
                topics=[str(topic) for topic in item.get("topics") or []],
                mentions=[str(mention) for mention in item.get("mentions") or []],
                metrics=item.get("metrics") if isinstance(item.get("metrics"), dict) else {},
                raw_text_lines=[str(line) for line in item.get("raw_text_lines") or []],
                extraction_warnings=[str(line) for line in item.get("extraction_warnings") or []],
            )
        )
    return payloads


def get_page_state(book: ActionBook) -> dict[str, Any]:
    state = unwrap_eval(book.eval(
        """(() => ({
            href: location.href,
            title: document.title,
            body: (document.body?.innerText || '').slice(0, 1000),
            candidates: document.querySelectorAll('article, [mid], [data-mid], [action-type="feed_list_item"], .card-wrap, .m-panel.card, [data-card]').length,
            images: document.querySelectorAll('img').length,
        }))()""",
        timeout=10.0,
    ))
    return state if isinstance(state, dict) else {}


def page_has_login_or_risk(state: dict[str, Any]) -> bool:
    haystack = "\n".join(str(state.get(key) or "") for key in ("href", "title", "body"))
    return bool(re.search(r"验证码|安全验证|访问频繁|帐号异常|账号异常|请稍后再试|请先登录|登录后|立即登录|passport\.weibo|sso\.weibo", haystack, re.I))


def wait_page_ready(book: ActionBook, source: str, timeout_secs: float = 25.0) -> None:
    deadline = time.time() + timeout_secs
    last_state: dict[str, Any] = {}
    while time.time() < deadline:
        last_state = get_page_state(book)
        if page_has_login_or_risk(last_state):
            raise RuntimeError(f"Weibo requires login or verification: {last_state.get('href')} title={last_state.get('title')}")
        candidates = int(last_state.get("candidates") or 0)
        body = str(last_state.get("body") or "")
        if candidates > 0 and len(body) > 20:
            return
        time.sleep(0.4)
    raise RuntimeError(f"Weibo {source} page did not become ready: {last_state}")


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


def collect_weibos(book: ActionBook, source: str, count: int, max_scrolls: int) -> list[WeiboPayload]:
    seen: set[str] = set()
    payloads: list[WeiboPayload] = []
    idle_rounds = 0
    for round_no in range(1, max_scrolls + 1):
        visible = extract_visible_weibos(book, source)
        added = 0
        for payload in visible:
            key = payload.mid or payload.weibo_id or payload.source_url or f"{payload.author_name}|{payload.text[:160]}"
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
        before = scroll_page(book)
        wait_for_page_settle(book)
        after = scroll_page(book)
        if after <= before + 5 and added == 0:
            idle_rounds += 1
    return payloads[:count]


def media_download_url(media: dict[str, Any]) -> str:
    return str(media.get("url") or media.get("poster_url") or "")


def weibo_media_flags(payload: WeiboPayload) -> str:
    flags: list[str] = []
    media_kinds = {str(item.get("kind") or "") for item in payload.media if isinstance(item, dict)}
    if "image" in media_kinds:
        flags.append("image")
    if "video" in media_kinds:
        flags.append("video")
    if payload.links:
        flags.append("link")
    if payload.topics:
        flags.append("topic")
    if not flags:
        flags.append("text")
    return "_".join(flags)


def parse_metric_value(label: str) -> str:
    text = str(label or "").strip()
    if not text:
        return ""
    match = re.search(r"([\d,.]+)\s*(万)?", text)
    if not match:
        return text
    return "".join(part for part in match.groups() if part)


def render_metrics_lines(payload: WeiboPayload) -> list[str]:
    labels = {
        "reposts": "转发",
        "comments": "评论",
        "likes": "赞",
    }
    lines = []
    for key, label in labels.items():
        raw = str((payload.metrics or {}).get(key) or "").strip()
        if not raw:
            continue
        value = parse_metric_value(raw)
        lines.append(f"- {label}: {value} ({raw})")
    return lines or ["- 未读取到指标"]


def render_raw_text(payload: WeiboPayload) -> str:
    lines = [
        "# 微博原始可见文本",
        "",
        f"- 类型: {payload.post_type}",
        f"- 作者: {payload.author_name or payload.author_id}",
        f"- 时间: {payload.created_at_text}",
        f"- 来源设备: {payload.source_device}",
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
    return "\n".join(lines).strip() + "\n"


def download_media(url: str, output_dir: Path, name: str) -> str | None:
    if not url or url.startswith("blob:"):
        return None
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://weibo.com/",
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


def write_weibo(payload: WeiboPayload, output_dir: Path, index: int) -> Path:
    safe_author = sanitize_name(payload.author_name or payload.author_id, fallback="unknown", max_length=32)
    safe_type = sanitize_name(payload.post_type, fallback="post", max_length=24)
    safe_flags = sanitize_name(weibo_media_flags(payload), fallback="text", max_length=48)
    item_id = payload.mid or payload.weibo_id or f"{index:03d}"
    folder = output_dir / f"{index:03d}_{safe_type}_{safe_flags}_{safe_author}_{item_id}"
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
        data = asdict(payload)
        data["saved_media"] = saved_media
        (temp / "metadata.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (temp / "raw.txt").write_text(render_raw_text(payload), encoding="utf-8")
        lines = [
            f"# {payload.author_name or payload.author_id or 'Weibo Post'}",
            "",
            f"- 类型: {payload.post_type}",
            f"- 作者: {payload.author_name or payload.author_id}",
            f"- 时间: {payload.created_at_text}",
            f"- 来源设备: {payload.source_device}",
            f"- 来源: {payload.source_url}",
            f"- 媒体数: {len(payload.media)}",
            f"- 外链数: {len(payload.links)}",
            "",
            "## 正文",
            "",
            payload.text or "(无正文)",
        ]
        if payload.reposted_weibo:
            lines.extend(["", "## 转发原微博", "", json.dumps(payload.reposted_weibo, ensure_ascii=False, indent=2)])
        if payload.topics:
            lines.extend(["", "## 话题", "", *[f"- #{topic}#" for topic in payload.topics]])
        if payload.mentions:
            lines.extend(["", "## 提及", "", *[f"- @{mention}" for mention in payload.mentions]])
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


def write_summary(payloads: list[WeiboPayload], output_dir: Path, source: str, action: str) -> None:
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
        type_counts[payload.post_type] = type_counts.get(payload.post_type, 0) + 1
    action_label = "浏览结果" if action == "view" else "下载结果"
    lines = [
        f"# 微博 {source} {action_label}",
        "",
        f"- 微博数: {len(payloads)}",
        f"- 类型统计: {json.dumps(type_counts, ensure_ascii=False)}",
        "",
    ]
    for index, payload in enumerate(payloads, start=1):
        lines.extend(
            [
                f"## {index}. {payload.author_name or payload.author_id or payload.weibo_id or payload.mid}",
                "",
                f"- 类型: {payload.post_type}",
                f"- 作者: {payload.author_name or payload.author_id}",
                f"- 时间: {payload.created_at_text}",
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


def write_records(records: Any, output_dir: Path, title: str, result_key: str = "items") -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "failures.json").write_text("[]\n", encoding="utf-8")
    rows = records if isinstance(records, list) else [records]
    lines = [
        f"# {title}",
        "",
        f"- 数量: {len(rows)}",
        "",
    ]
    for index, item in enumerate(rows, start=1):
        lines.extend([f"## {index}", ""])
        if isinstance(item, dict):
            for key, value in item.items():
                if isinstance(value, (dict, list)):
                    continue
                lines.append(f"- {key}: {value}")
            text = str(item.get("text") or item.get("description") or item.get("word") or "").strip()
            if text:
                lines.extend(["", text[:1000]])
        else:
            lines.append(str(item))
        lines.append("")
    (output_dir / "summary.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def print_record_result(source: str, action: str, output_dir: Path, count: int) -> None:
    print(json.dumps({
        "source": source,
        "action": action,
        "count": count,
        "output_dir": str(output_dir),
        "summary_json": str(output_dir / "summary.json"),
        "summary_md": str(output_dir / "summary.md"),
        "failures_json": str(output_dir / "failures.json"),
    }, ensure_ascii=False, indent=2))


def run_hot_view(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_action_output_dir("hot", "view")
    count = read_count(args.count, default=30, max_value=50)
    book = prepare_weibo_book(args)
    ensure_api_context(book)
    rows = api_eval(book, f"""
        (async () => {{
          const resp = await fetch('/ajax/statuses/hot_band', {{ credentials: 'include' }});
          if (!resp.ok) return {{ error: 'HTTP ' + resp.status }};
          const data = await resp.json();
          if (!data.ok) return {{ error: 'API error: ' + (data.msg || 'unknown') }};
          const list = data.data?.band_list || [];
          return list.slice(0, {count}).map((item, index) => ({{
            rank: item.realpos || index + 1,
            word: item.word || '',
            hot_value: item.num || 0,
            category: item.category || '',
            label: item.label_name || '',
            url: 'https://s.weibo.com/weibo?q=' + encodeURIComponent('#' + (item.word || '') + '#'),
          }}));
        }})()
    """, "weibo hot")
    if not isinstance(rows, list):
        raise RuntimeError("weibo hot returned malformed payload")
    write_records(rows, output_dir, "微博 hot 浏览结果")
    print_record_result("hot", "view", output_dir, len(rows))
    return 0 if rows else 1


def run_feed_api(args: argparse.Namespace, action: str) -> int:
    feed_type = "following" if args.type == "following" else "for-you"
    source = f"feed-{feed_type}"
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_action_output_dir(source, action)
    count = read_count(args.count, default=15, max_value=50)
    endpoint = "friendstimeline" if feed_type == "following" else "unreadfriendstimeline"
    book = prepare_weibo_book(args)
    ensure_api_context(book)
    statuses = api_eval(book, f"""
        (async () => {{
          const readUid = async () => {{
            {self_uid_js()}
          }};
          const uid = await readUid();
          if (!uid) return {{ error: 'login required: missing uid' }};
          const listId = '10001' + uid;
          const url = '/ajax/feed/{endpoint}?list_id=' + listId + '&refresh=4&since_id=0&count={count}';
          const resp = await fetch(url, {{ credentials: 'include' }});
          if (!resp.ok) return {{ error: 'HTTP ' + resp.status }};
          const data = await resp.json();
          if (!data.ok) return {{ error: 'API error: ' + (data.msg || 'unknown') }};
          return (data.statuses || []).slice(0, {count});
        }})()
    """, "weibo feed")
    if not isinstance(statuses, list):
        raise RuntimeError("weibo feed returned malformed payload")
    payloads = [status_to_payload(item, source) for item in statuses if isinstance(item, dict)]
    if action == "download":
        output_dir.mkdir(parents=True, exist_ok=True)
        for index, payload in enumerate(payloads, start=1):
            folder = write_weibo(payload, output_dir, index)
            log(f"已写入: {folder}")
    write_summary(payloads, output_dir, source, action)
    print_record_result(source, action, output_dir, len(payloads))
    return 0 if payloads else 1


def resolve_profile_id_from_url(value: str) -> str:
    raw = str(value or "")
    match = re.search(r"/u/(\d+)", raw)
    if match:
        return match.group(1)
    match = re.search(r"weibo\.com/(\d+)(?:[/?#]|$)", raw)
    if match:
        return match.group(1)
    return raw.strip()


def run_user_view(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_action_output_dir("user", "view")
    user_id = resolve_profile_id_from_url(args.id or args.profile_url)
    book = prepare_weibo_book(args)
    ensure_api_context(book)
    data = api_eval(book, f"""
        (async () => {{
          const id = {json.dumps(user_id, ensure_ascii=False)};
          const isUid = /^\\d+$/.test(id);
          const query = isUid ? 'uid=' + encodeURIComponent(id) : 'screen_name=' + encodeURIComponent(id);
          const resp = await fetch('/ajax/profile/info?' + query, {{ credentials: 'include' }});
          if (!resp.ok) return {{ error: 'HTTP ' + resp.status }};
          const data = await resp.json();
          if (!data.ok || !data.data?.user) return {{ error: 'User not found' }};
          const u = data.data.user;
          let detail = {{}};
          try {{
            const detailResp = await fetch('/ajax/profile/detail?uid=' + u.id, {{ credentials: 'include' }});
            if (detailResp.ok) detail = (await detailResp.json()).data || {{}};
          }} catch {{}}
          return {{
            screen_name: u.screen_name || '',
            uid: String(u.id || ''),
            followers: u.followers_count || 0,
            following: u.friends_count || 0,
            statuses: u.statuses_count || 0,
            verified: !!u.verified,
            verified_reason: u.verified_reason || '',
            description: u.description || detail.description || '',
            location: u.location || '',
            gender: u.gender === 'm' ? 'male' : u.gender === 'f' ? 'female' : '',
            avatar: u.avatar_hd || u.avatar_large || '',
            url: 'https://weibo.com' + (u.profile_url || '/u/' + u.id),
            birthday: detail.birthday || '',
            created_at: detail.created_at || '',
            ip_location: detail.ip_location || '',
          }};
        }})()
    """, "weibo user")
    if not isinstance(data, dict):
        raise RuntimeError("weibo user returned malformed payload")
    write_records(data, output_dir, "微博 user 浏览结果")
    print_record_result("user", "view", output_dir, 1)
    return 0


def run_me_view(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_action_output_dir("me", "view")
    book = prepare_weibo_book(args)
    ensure_api_context(book)
    data = api_eval(book, """
        (async () => {
          const readUid = async () => {
            const app = document.querySelector('#app')?.__vue_app__;
            const store = app?.config?.globalProperties?.$store;
            const storeUid = store?.state?.config?.config?.uid;
            if (storeUid) return String(storeUid);
            const cfgResp = await fetch('/ajax/config/get_config', { credentials: 'include' });
            if (cfgResp.ok) {
              const cfg = await cfgResp.json();
              if (cfg.data?.uid) return String(cfg.data.uid);
            }
            return '';
          };
          const uid = await readUid();
          if (!uid) return { error: 'login required: missing uid' };
          const resp = await fetch('/ajax/profile/info?uid=' + uid, { credentials: 'include' });
          if (!resp.ok) return { error: 'HTTP ' + resp.status };
          const info = await resp.json();
          if (!info.ok || !info.data?.user) return { error: 'User data not found' };
          const u = info.data.user;
          return {
            screen_name: u.screen_name || '',
            uid: String(u.id || uid),
            followers: u.followers_count || 0,
            following: u.friends_count || 0,
            statuses: u.statuses_count || 0,
            verified: !!u.verified,
            location: u.location || '',
            description: u.description || '',
            avatar: u.avatar_hd || u.avatar_large || '',
            profile_url: 'https://weibo.com' + (u.profile_url || '/u/' + u.id),
          };
        })()
    """, "weibo me")
    if not isinstance(data, dict):
        raise RuntimeError("weibo me returned malformed payload")
    write_records(data, output_dir, "微博 me 浏览结果")
    print_record_result("me", "view", output_dir, 1)
    return 0


def run_post_api(args: argparse.Namespace, action: str) -> int:
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_action_output_dir("post", action)
    post_id = args.id or extract_weibo_id(args.url)
    if not post_id:
        raise argparse.ArgumentTypeError("post requires --id or --url")
    book = prepare_weibo_book(args)
    ensure_api_context(book)
    status = api_eval(book, f"""
        (async () => {{
          const strip = html => String(html || '').replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').trim();
          const id = {json.dumps(post_id, ensure_ascii=False)};
          const resp = await fetch('/ajax/statuses/show?id=' + encodeURIComponent(id), {{ credentials: 'include' }});
          if (!resp.ok) return {{ error: 'HTTP ' + resp.status }};
          const s = await resp.json();
          if (!s.ok && !s.idstr) return {{ error: 'Post not found' }};
          if (s.isLongText || s.is_long_text) {{
            try {{
              const ltResp = await fetch('/ajax/statuses/longtext?id=' + s.idstr, {{ credentials: 'include' }});
              if (ltResp.ok) {{
                const lt = await ltResp.json();
                if (lt.data?.longTextContent) {{
                  s.text_raw = strip(lt.data.longTextContent);
                  s.text = lt.data.longTextContent;
                }}
              }}
            }} catch {{}}
          }}
          return s;
        }})()
    """, "weibo post")
    if not isinstance(status, dict):
        raise RuntimeError("weibo post returned malformed payload")
    payload = status_to_payload(status, "post")
    if action == "download":
        output_dir.mkdir(parents=True, exist_ok=True)
        folder = write_weibo(payload, output_dir, 1)
        log(f"已写入: {folder}")
    write_summary([payload], output_dir, "post", action)
    print_record_result("post", action, output_dir, 1)
    return 0


def run_comments_view(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_action_output_dir("comments", "view")
    count = read_count(args.count, default=20, max_value=50)
    post_id = args.id or extract_mid(args.url) or extract_weibo_id(args.url)
    if not post_id:
        raise argparse.ArgumentTypeError("comments requires --id or --url")
    book = prepare_weibo_book(args)
    ensure_api_context(book)
    rows = api_eval(book, f"""
        (async () => {{
          const strip = html => String(html || '').replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').trim();
          const id = {json.dumps(post_id, ensure_ascii=False)};
          const url = '/ajax/statuses/buildComments?flow=0&is_reload=1&id=' + encodeURIComponent(id) + '&is_show_bulletin=2&is_mix=0&count={count}';
          const resp = await fetch(url, {{ credentials: 'include' }});
          if (!resp.ok) return {{ error: 'HTTP ' + resp.status }};
          const data = await resp.json();
          if (!data.ok) return {{ error: 'API error: ' + (data.msg || 'unknown') }};
          return (data.data || []).slice(0, {count}).map((c, index) => ({{
            rank: index + 1,
            author: c.user?.screen_name || '',
            text: strip(c.text || ''),
            likes: c.like_count || 0,
            replies: c.total_number || 0,
            time: c.created_at || '',
            reply_to: c.reply_comment ? ((c.reply_comment.user?.screen_name || '') + ': ' + strip(c.reply_comment.text || '').slice(0, 120)) : '',
          }}));
        }})()
    """, "weibo comments")
    if not isinstance(rows, list):
        raise RuntimeError("weibo comments returned malformed payload")
    write_records(rows, output_dir, "微博 comments 浏览结果")
    print_record_result("comments", "view", output_dir, len(rows))
    return 0 if rows else 1


def run_user_posts(args: argparse.Namespace, action: str) -> int:
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_action_output_dir("user-posts", action)
    count = read_count(args.count, default=30, max_value=50)
    user_id = resolve_profile_id_from_url(args.id or args.profile_url)
    if not user_id:
        raise argparse.ArgumentTypeError("user-posts requires --id or --profile-url")
    book = prepare_weibo_book(args)
    ensure_api_context(book)
    statuses = api_eval(book, f"""
        (async () => {{
          const rawId = {json.dumps(user_id, ensure_ascii=False)};
          const includeRetweets = {str(bool(args.include_retweets)).lower()};
          const starttime = {json.dumps(args.start or "")};
          const endtime = {json.dumps(args.end or "")};
          async function readJson(url) {{
            const resp = await fetch(url, {{ credentials: 'include' }});
            if (!resp.ok) return {{ error: 'HTTP ' + resp.status }};
            return await resp.json();
          }}
          let uid = rawId;
          if (!/^\\d+$/.test(rawId)) {{
            const profile = await readJson('/ajax/profile/info?screen_name=' + encodeURIComponent(rawId));
            if (profile.error) return profile;
            if (!profile.ok || !profile.data?.user?.id) return {{ error: 'User not found' }};
            uid = String(profile.data.user.id);
          }}
          const rows = [];
          const startTs = starttime ? Math.floor(new Date(starttime + 'T00:00:00+08:00').getTime() / 1000) : null;
          const endTs = endtime ? Math.floor(new Date(endtime + 'T23:59:59+08:00').getTime() / 1000) : null;
          for (let page = 1; page <= 20 && rows.length < {count}; page++) {{
            const qs = new URLSearchParams();
            qs.set('uid', uid);
            qs.set('page', String(page));
            qs.set('hasori', '1');
            qs.set('hasret', includeRetweets ? '1' : '0');
            if (startTs !== null) qs.set('starttime', String(startTs));
            if (endTs !== null) qs.set('endtime', String(endTs));
            const data = await readJson('/ajax/statuses/searchProfile?' + qs.toString());
            if (data.error) return data;
            if (data.ok === false) return {{ error: 'API error: ' + (data.msg || data.message || 'request failed') }};
            const list = data.data?.list || [];
            if (!Array.isArray(list) || list.length === 0) break;
            for (const post of list) {{
              if (rows.length >= {count}) break;
              rows.push(post);
            }}
            if (list.length < 10) break;
          }}
          return rows;
        }})()
    """, "weibo user-posts")
    if not isinstance(statuses, list):
        raise RuntimeError("weibo user-posts returned malformed payload")
    payloads = [status_to_payload(item, "user-posts") for item in statuses if isinstance(item, dict)]
    if action == "download":
        output_dir.mkdir(parents=True, exist_ok=True)
        for index, payload in enumerate(payloads, start=1):
            folder = write_weibo(payload, output_dir, index)
            log(f"已写入: {folder}")
    write_summary(payloads, output_dir, "user-posts", action)
    print_record_result("user-posts", action, output_dir, len(payloads))
    return 0 if payloads else 1


def run_action(args: argparse.Namespace, source: str, url: str, action: str) -> int:
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_action_output_dir(source, action)
    book = prepare_weibo_book(args, url)
    book.goto(url)
    wait_page_ready(book, source)
    book.eval("window.scrollTo(0, 0); window.dispatchEvent(new Event('scroll')); true", timeout=10.0)
    wait_for_page_settle(book)
    payloads = collect_weibos(book, source, args.count, args.max_scrolls)
    output_dir.mkdir(parents=True, exist_ok=True)
    if action == "download":
        for index, payload in enumerate(payloads, start=1):
            folder = write_weibo(payload, output_dir, index)
            log(f"已写入: {folder}")
    write_summary(payloads, output_dir, source, action)
    result = {
        "source": source,
        "action": action,
        "requested_count": args.count,
        "count": len(payloads),
        "output_dir": str(output_dir),
        "summary_json": str(output_dir / "summary.json"),
        "summary_md": str(output_dir / "summary.md"),
        "failures_json": str(output_dir / "failures.json"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if len(payloads) >= args.count else 1


def run_post_view(args: argparse.Namespace) -> int:
    return run_post_api(args, "view")


def run_post_download(args: argparse.Namespace) -> int:
    return run_post_api(args, "download")


def run_profile_view(args: argparse.Namespace) -> int:
    return run_action(args, "profile", args.profile_url, "view")


def run_profile_download(args: argparse.Namespace) -> int:
    return run_action(args, "profile", args.profile_url, "download")


def run_search_view(args: argparse.Namespace) -> int:
    query = urllib.parse.urlencode({"q": args.keyword})
    return run_action(args, "search", f"{WEIBO_SEARCH_URL}?{query}", "view")


def run_search_download(args: argparse.Namespace) -> int:
    query = urllib.parse.urlencode({"q": args.keyword})
    return run_action(args, "search", f"{WEIBO_SEARCH_URL}?{query}", "download")


def run_home_view(args: argparse.Namespace) -> int:
    return run_action(args, "home", WEIBO_HOME_URL, "view")


def run_home_download(args: argparse.Namespace) -> int:
    return run_action(args, "home", WEIBO_HOME_URL, "download")


def run_feed_view(args: argparse.Namespace) -> int:
    return run_feed_api(args, "view")


def run_feed_download(args: argparse.Namespace) -> int:
    return run_feed_api(args, "download")


def run_user_posts_view(args: argparse.Namespace) -> int:
    return run_user_posts(args, "view")


def run_user_posts_download(args: argparse.Namespace) -> int:
    return run_user_posts(args, "download")


def get_self_uid(book: ActionBook) -> str:
    uid = api_eval(book, f"""
        (async () => {{
          const readUid = async () => {{
            {self_uid_js()}
          }};
          return await readUid();
        }})()
    """, "weibo self uid")
    return str(uid or "")


def run_favorites(args: argparse.Namespace, action: str) -> int:
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_action_output_dir("favorites", action)
    book = prepare_weibo_book(args)
    ensure_api_context(book)
    uid = get_self_uid(book)
    if not uid:
        raise RuntimeError("weibo favorites: login required: missing uid")
    fav_url = f"https://weibo.com/u/page/fav/{uid}"
    book.goto(fav_url)
    wait_page_ready(book, "favorites", timeout_secs=30.0)
    book.eval("window.scrollTo(0, 0); window.dispatchEvent(new Event('scroll')); true", timeout=10.0)
    wait_for_page_settle(book)
    payloads = collect_weibos(book, "favorites", args.count, args.max_scrolls)
    output_dir.mkdir(parents=True, exist_ok=True)
    if action == "download":
        for index, payload in enumerate(payloads, start=1):
            folder = write_weibo(payload, output_dir, index)
            log(f"已写入: {folder}")
    write_summary(payloads, output_dir, "favorites", action)
    print_record_result("favorites", action, output_dir, len(payloads))
    return 0 if payloads else 1


def run_favorites_view(args: argparse.Namespace) -> int:
    return run_favorites(args, "view")


def run_favorites_download(args: argparse.Namespace) -> int:
    return run_favorites(args, "download")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Weibo workflows through ActionBook.")
    subparsers = parser.add_subparsers(dest="area", required=True)

    def add_common(target: argparse.ArgumentParser, default_count: int = 30, default_max_scrolls: int = 18) -> None:
        add_session_tab_args(target, default_session=DEFAULT_SESSION)
        target.add_argument("--count", type=int, default=default_count, help="Number of posts to process")
        target.add_argument("--max-scrolls", type=int, default=default_max_scrolls, help="Maximum scroll rounds")
        target.add_argument("--output-dir", help="Output directory")

    post = subparsers.add_parser("post", help="Weibo single post workflows")
    post_sub = post.add_subparsers(dest="mode", required=True)
    post_view = post_sub.add_parser("view", help="View one Weibo post URL")
    post_view.add_argument("--url", default="", help="Weibo post URL")
    post_view.add_argument("--id", default="", help="Weibo numeric idstr or mblogid")
    add_common(post_view, default_count=1, default_max_scrolls=2)
    post_view.set_defaults(func=run_post_view)
    post_download = post_sub.add_parser("download", help="Download one Weibo post URL into local files")
    post_download.add_argument("--url", default="", help="Weibo post URL")
    post_download.add_argument("--id", default="", help="Weibo numeric idstr or mblogid")
    add_common(post_download, default_count=1, default_max_scrolls=2)
    post_download.set_defaults(func=run_post_download)

    profile = subparsers.add_parser("profile", help="Weibo profile workflows")
    profile_sub = profile.add_subparsers(dest="mode", required=True)
    profile_view = profile_sub.add_parser("view", help="View posts from a Weibo profile")
    profile_view.add_argument("--profile-url", required=True, help="Weibo profile URL")
    add_common(profile_view, default_count=30, default_max_scrolls=18)
    profile_view.set_defaults(func=run_profile_view)
    profile_download = profile_sub.add_parser("download", help="Download posts from a Weibo profile")
    profile_download.add_argument("--profile-url", required=True, help="Weibo profile URL")
    add_common(profile_download, default_count=30, default_max_scrolls=18)
    profile_download.set_defaults(func=run_profile_download)

    search = subparsers.add_parser("search", help="Weibo search workflows")
    search_sub = search.add_subparsers(dest="mode", required=True)
    search_view = search_sub.add_parser("view", help="View Weibo search results")
    search_view.add_argument("--keyword", required=True, help="Weibo search keyword")
    add_common(search_view, default_count=30, default_max_scrolls=18)
    search_view.set_defaults(func=run_search_view)
    search_download = search_sub.add_parser("download", help="Download Weibo search results")
    search_download.add_argument("--keyword", required=True, help="Weibo search keyword")
    add_common(search_download, default_count=30, default_max_scrolls=18)
    search_download.set_defaults(func=run_search_download)

    home = subparsers.add_parser("home", help="Weibo home feed workflows")
    home_sub = home.add_subparsers(dest="mode", required=True)
    home_view = home_sub.add_parser("view", help="View visible Weibo home posts")
    add_common(home_view, default_count=30, default_max_scrolls=18)
    home_view.set_defaults(func=run_home_view)
    home_download = home_sub.add_parser("download", help="Download visible Weibo home posts")
    add_common(home_download, default_count=30, default_max_scrolls=18)
    home_download.set_defaults(func=run_home_download)

    hot = subparsers.add_parser("hot", help="Weibo hot search workflows")
    hot_sub = hot.add_subparsers(dest="mode", required=True)
    hot_view = hot_sub.add_parser("view", help="View Weibo hot search list")
    add_common(hot_view, default_count=30, default_max_scrolls=1)
    hot_view.set_defaults(func=run_hot_view)

    feed = subparsers.add_parser("feed", help="Weibo API feed workflows")
    feed_sub = feed.add_subparsers(dest="mode", required=True)
    feed_view = feed_sub.add_parser("view", help="View Weibo feed through API")
    feed_view.add_argument("--type", choices=("for-you", "following"), default="for-you")
    add_common(feed_view, default_count=15, default_max_scrolls=1)
    feed_view.set_defaults(func=run_feed_view)
    feed_download = feed_sub.add_parser("download", help="Download Weibo feed through API")
    feed_download.add_argument("--type", choices=("for-you", "following"), default="for-you")
    add_common(feed_download, default_count=15, default_max_scrolls=1)
    feed_download.set_defaults(func=run_feed_download)

    user = subparsers.add_parser("user", help="Weibo user profile workflows")
    user_sub = user.add_subparsers(dest="mode", required=True)
    user_view = user_sub.add_parser("view", help="View one Weibo user profile")
    user_view.add_argument("--id", default="", help="Weibo uid or screen name")
    user_view.add_argument("--profile-url", default="", help="Weibo profile URL")
    add_common(user_view, default_count=1, default_max_scrolls=1)
    user_view.set_defaults(func=run_user_view)

    user_posts = subparsers.add_parser("user-posts", help="Weibo user posts API workflows")
    user_posts_sub = user_posts.add_subparsers(dest="mode", required=True)
    user_posts_view = user_posts_sub.add_parser("view", help="View posts from one Weibo user through API")
    user_posts_view.add_argument("--id", default="", help="Weibo uid or screen name")
    user_posts_view.add_argument("--profile-url", default="", help="Weibo profile URL")
    user_posts_view.add_argument("--start", default="", help="Start date in Asia/Shanghai, YYYY-MM-DD")
    user_posts_view.add_argument("--end", default="", help="End date in Asia/Shanghai, YYYY-MM-DD")
    user_posts_view.add_argument("--include-retweets", dest="include_retweets", action="store_true", help="Include retweets")
    add_common(user_posts_view, default_count=30, default_max_scrolls=1)
    user_posts_view.set_defaults(func=run_user_posts_view)
    user_posts_download = user_posts_sub.add_parser("download", help="Download posts from one Weibo user through API")
    user_posts_download.add_argument("--id", default="", help="Weibo uid or screen name")
    user_posts_download.add_argument("--profile-url", default="", help="Weibo profile URL")
    user_posts_download.add_argument("--start", default="", help="Start date in Asia/Shanghai, YYYY-MM-DD")
    user_posts_download.add_argument("--end", default="", help="End date in Asia/Shanghai, YYYY-MM-DD")
    user_posts_download.add_argument("--include-retweets", dest="include_retweets", action="store_true", help="Include retweets")
    add_common(user_posts_download, default_count=30, default_max_scrolls=1)
    user_posts_download.set_defaults(func=run_user_posts_download)

    me = subparsers.add_parser("me", help="Current Weibo account profile workflows")
    me_sub = me.add_subparsers(dest="mode", required=True)
    me_view = me_sub.add_parser("view", help="View current Weibo account profile")
    add_common(me_view, default_count=1, default_max_scrolls=1)
    me_view.set_defaults(func=run_me_view)

    comments = subparsers.add_parser("comments", help="Weibo post comments workflows")
    comments_sub = comments.add_subparsers(dest="mode", required=True)
    comments_view = comments_sub.add_parser("view", help="View comments from one Weibo post")
    comments_view.add_argument("--id", default="", help="Weibo numeric idstr")
    comments_view.add_argument("--url", default="", help="Weibo post URL")
    add_common(comments_view, default_count=20, default_max_scrolls=1)
    comments_view.set_defaults(func=run_comments_view)

    favorites = subparsers.add_parser("favorites", help="Current Weibo account favorites workflows")
    favorites_sub = favorites.add_subparsers(dest="mode", required=True)
    favorites_view = favorites_sub.add_parser("view", help="View current user's Weibo favorites")
    add_common(favorites_view, default_count=20, default_max_scrolls=6)
    favorites_view.set_defaults(func=run_favorites_view)
    favorites_download = favorites_sub.add_parser("download", help="Download current user's Weibo favorites")
    add_common(favorites_download, default_count=20, default_max_scrolls=6)
    favorites_download.set_defaults(func=run_favorites_download)

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
