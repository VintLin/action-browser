#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Douban workflow helper for the action-browser skill.

The workflow uses ActionBook extension mode and the user's existing Chrome
session. It covers Douban search, movie/book charts, subject details, movie
photos, photo downloads, marks, and reviews.
"""

from __future__ import annotations

import argparse
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
from scripts.actionbook_session import ActionBookSession as ActionBook


DOUBAN_HOME_URL = "https://www.douban.com"
MOVIE_HOME_URL = "https://movie.douban.com"
BOOK_HOME_URL = "https://book.douban.com"
DEFAULT_SESSION = "douban-task"
DEFAULT_TAB = ""
SKILL_DIR = Path(__file__).resolve().parents[2]
ASSETS_DIR = SKILL_DIR / "assets" / "douban"


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def sanitize_name(value: str, fallback: str = "item", max_length: int = 64) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "", value or "").strip("._-")
    return (cleaned or fallback)[:max_length]


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def unwrap_eval(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def read_count(value: Any, default: int = 20, max_value: int = 500) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = default
    return max(1, min(count, max_value))


def normalize_subject_id(value: str) -> str:
    raw = str(value or "").strip()
    match = re.search(r"/subject/(\d+)", raw)
    if match:
        return match.group(1)
    if not re.fullmatch(r"\d+", raw):
        raise ValueError(f"Invalid Douban subject ID: {value}")
    return raw


def default_action_output_dir(source: str, action: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    action_dir = "downloads" if action == "download" else "views"
    return ASSETS_DIR / action_dir / source / stamp


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
      text: (document.body?.innerText || '').slice(0, 800)
    }))()
    """, "douban page state", timeout=10.0)
    return value if isinstance(value, dict) else {}


def ensure_douban_ready(book: ActionBook) -> None:
    state = get_page_state(book)
    href = str(state.get("href") or "")
    title = str(state.get("title") or "")
    text = str(state.get("text") or "")
    if "sec.douban.com" in href or "accounts.douban.com" in href or "登录跳转" in title or "异常请求" in text:
        raise RuntimeError(f"Douban requires login or verification: {href} title={title}")


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
        heading = item.get("title") or item.get("movieTitle") or item.get("subjectTitle") or item.get("photo_id") or item.get("id") or str(index)
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


def write_subject(subject: dict[str, Any], output_dir: Path) -> None:
    write_records([subject], output_dir, f"豆瓣条目: {subject.get('title') or subject.get('id')}")


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
    if not url:
        return {"status": "skipped", "path": "", "size": 0, "error": "missing url"}
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": referer or MOVIE_HOME_URL + "/",
        },
    )
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


def get_self_uid(book: ActionBook) -> str:
    book.goto(MOVIE_HOME_URL + "/mine")
    time.sleep(1.5)
    ensure_douban_ready(book)
    uid = api_eval(book, r"""
    (() => {
      if (window.__DATA__?.uid) return String(window.__DATA__.uid);
      const links = [...document.querySelectorAll('a[href*="/people/"]')];
      for (const link of links) {
        const href = link.getAttribute('href') || link.href || '';
        const match = href.match(/people\/([^/?#]+)/);
        if (match) return decodeURIComponent(match[1]);
      }
      return '';
    })()
    """, "douban self uid", timeout=15.0)
    if not uid:
        raise RuntimeError("Not logged in to Douban or current uid was not found")
    return str(uid)


def search_url(search_type: str, keyword: str) -> str:
    url = urllib.parse.urlparse(f"https://search.douban.com/{urllib.parse.quote(search_type)}/subject_search")
    query = {"search_text": keyword}
    if search_type == "book":
        query["cat"] = "1001"
    return urllib.parse.urlunparse(url._replace(query=urllib.parse.urlencode(query)))


def run_search(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=50)
    output_dir = Path(args.output) if args.output else default_action_output_dir("search", "view")
    book = start_book(args, search_url(args.type, args.keyword))
    book.goto(search_url(args.type, args.keyword))
    time.sleep(2.5)
    ensure_douban_ready(book)
    data = api_eval(book, f"""
    (async () => {{
      const type = {json.dumps(args.type)};
      const limit = {count};
      const normalize = value => String(value || '').replace(/\\s+/g, ' ').trim();
      const abs = value => {{
        if (!value) return '';
        try {{ return new URL(value, location.origin).toString(); }} catch {{ return String(value || ''); }}
      }};
      for (let i = 0; i < 20; i += 1) {{
        if (document.querySelector('.item-root .title-text, .item-root .title a, .result-list .result-item h3 a')) break;
        await new Promise(resolve => setTimeout(resolve, 300));
      }}
      const rawItems = Array.isArray(window.__DATA__?.items) ? window.__DATA__.items : [];
      const rawItemsById = new Map(rawItems.map(item => [String(item?.id || '').trim(), item]).filter(([id]) => id));
      const seen = new Set();
      const rows = [];
      for (const el of [...document.querySelectorAll('.item-root, .result-list .result-item')]) {{
        const titleEl = el.querySelector('.title-text, .title a, .title h3 a, h3 a, a[title]');
        const title = normalize(titleEl?.textContent) || normalize(titleEl?.getAttribute('title'));
        const href = abs(titleEl?.getAttribute('href') || el.querySelector('a[href*="/subject/"]')?.getAttribute('href') || '');
        if (!title || !href || !href.includes('/subject/') || seen.has(href)) continue;
        seen.add(href);
        const id = (href.match(/subject\\/(\\d+)/) || [])[1] || '';
        const raw = rawItemsById.get(id) || {{}};
        const labels = Array.isArray(raw.labels) ? raw.labels.map(label => String(label?.text || label || '').trim()).filter(Boolean) : [];
        const moreUrl = String(raw.more_url || raw.moreUrl || '');
        const isTv = /is_tv:\\s*['"]?1/.test(moreUrl) || labels.includes('剧集');
        const ratingText = normalize(el.querySelector('.rating_nums')?.textContent);
        const abstract = normalize(el.querySelector('.meta.abstract, .meta, .abstract, .subject-abstract, p')?.textContent);
        rows.push({{
          rank: rows.length + 1,
          id,
          type: type === 'movie' && isTv ? 'tvshow' : type,
          title,
          rating: ratingText.includes('.') ? Number.parseFloat(ratingText) || 0 : 0,
          abstract: abstract.slice(0, 180),
          url: href,
          cover: abs(el.querySelector('img')?.getAttribute('src') || '')
        }});
        if (rows.length >= limit) break;
      }}
      return rows;
    }})()
    """, "douban search", timeout=30.0)
    rows = data if isinstance(data, list) else []
    write_records(rows, output_dir, f"豆瓣搜索: {args.keyword}")
    log(f"写入 {len(rows)} 条搜索结果: {output_dir}")
    return 0


def run_top250(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=250, max_value=250)
    output_dir = Path(args.output) if args.output else default_action_output_dir("top250", "view")
    book = start_book(args, MOVIE_HOME_URL + "/top250")
    book.goto(MOVIE_HOME_URL + "/top250")
    time.sleep(1.5)
    ensure_douban_ready(book)
    rows = api_eval(book, f"""
    (async () => {{
      const limit = {count};
      const normalize = value => String(value || '').replace(/\\s+/g, ' ').trim();
      const abs = value => new URL(value, location.origin).toString();
      const rows = [];
      const parseDoc = doc => {{
        for (const el of [...doc.querySelectorAll('.item')]) {{
          if (rows.length >= limit) break;
          const link = el.querySelector('a[href*="/subject/"]');
          const href = link ? abs(link.getAttribute('href')) : '';
          const id = (href.match(/subject\\/(\\d+)/) || [])[1] || '';
          const title = normalize(el.querySelector('.title')?.textContent);
          if (!id || !title) continue;
          rows.push({{
            rank: Number.parseInt(normalize(el.querySelector('.pic em')?.textContent), 10) || rows.length + 1,
            id,
            title,
            rating: Number.parseFloat(normalize(el.querySelector('.rating_num')?.textContent)) || 0,
            quote: normalize(el.querySelector('.quote .inq')?.textContent),
            url: href,
            cover: abs(el.querySelector('img')?.getAttribute('src') || '')
          }});
        }}
      }};
      parseDoc(document);
      for (let start = 25; start < 250 && rows.length < limit; start += 25) {{
        const response = await fetch('/top250?start=' + start, {{ credentials: 'include' }});
        if (!response.ok) break;
        const html = await response.text();
        parseDoc(new DOMParser().parseFromString(html, 'text/html'));
        await new Promise(resolve => setTimeout(resolve, 120));
      }}
      return rows.slice(0, limit);
    }})()
    """, "douban top250", timeout=45.0)
    records = rows if isinstance(rows, list) else []
    write_records(records, output_dir, "豆瓣电影 Top250")
    log(f"写入 {len(records)} 条 Top250 结果: {output_dir}")
    return 0


def run_movie_hot(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=50)
    output_dir = Path(args.output) if args.output else default_action_output_dir("movie-hot", "view")
    book = start_book(args, MOVIE_HOME_URL + "/chart")
    book.goto(MOVIE_HOME_URL + "/chart")
    time.sleep(2.0)
    ensure_douban_ready(book)
    rows = api_eval(book, f"""
    (() => {{
      const normalize = value => String(value || '').replace(/\\s+/g, ' ').trim();
      const abs = value => value ? new URL(value, location.origin).toString() : '';
      const rows = [];
      for (const el of [...document.querySelectorAll('.item')]) {{
        const titleEl = el.querySelector('.pl2 a');
        const title = normalize(titleEl?.textContent);
        const href = abs(titleEl?.getAttribute('href') || '');
        if (!title || !href) continue;
        const info = normalize(el.querySelector('.pl2 p')?.textContent);
        rows.push({{
          rank: rows.length + 1,
          id: (href.match(/subject\\/(\\d+)/) || [])[1] || '',
          title,
          rating: Number.parseFloat(normalize(el.querySelector('.rating_nums')?.textContent)) || 0,
          votes: Number.parseInt(normalize(el.querySelector('.star .pl')?.textContent).replace(/[^0-9]/g, ''), 10) || 0,
          year: (info.match(/\\b(?:19|20)\\d{{2}}\\b/) || [])[0] || '',
          url: href,
          cover: abs(el.querySelector('img')?.getAttribute('src') || '')
        }});
        if (rows.length >= {count}) break;
      }}
      return rows;
    }})()
    """, "douban movie-hot", timeout=30.0)
    records = rows if isinstance(rows, list) else []
    write_records(records, output_dir, "豆瓣电影热门榜单")
    log(f"写入 {len(records)} 条电影热门结果: {output_dir}")
    return 0


def run_book_hot(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=50)
    output_dir = Path(args.output) if args.output else default_action_output_dir("book-hot", "view")
    book = start_book(args, BOOK_HOME_URL + "/chart")
    book.goto(BOOK_HOME_URL + "/chart")
    time.sleep(2.0)
    ensure_douban_ready(book)
    rows = api_eval(book, f"""
    (() => {{
      const normalize = value => String(value || '').replace(/\\s+/g, ' ').trim();
      const abs = value => value ? new URL(value, location.origin).toString() : '';
      const rows = [];
      for (const el of [...document.querySelectorAll('.media.clearfix')]) {{
        const titleEl = el.querySelector('h2 a[href*="/subject/"]');
        const title = normalize(titleEl?.textContent);
        const href = abs(titleEl?.getAttribute('href') || '');
        if (!title || !href) continue;
        const info = normalize(el.querySelector('.subject-abstract, .pl, .pub')?.textContent);
        const parts = info.split('/').map(part => part.trim()).filter(Boolean);
        const quote = [...el.querySelectorAll('.subject-tags .tag')].map(node => normalize(node.textContent)).filter(Boolean).join(' / ');
        rows.push({{
          rank: Number.parseInt(normalize(el.querySelector('.green-num-box')?.textContent), 10) || rows.length + 1,
          id: (href.match(/subject\\/(\\d+)/) || [])[1] || '',
          title,
          rating: Number.parseFloat(normalize(el.querySelector('.subject-rating .font-small, .rating_nums, .rating')?.textContent)) || 0,
          quote,
          author: parts[0] || '',
          publisher: parts.find(part => /出版社|出版公司|Press/i.test(part)) || parts[2] || '',
          year: ((parts.find(part => /\\d{{4}}/.test(part)) || '').match(/\\d{{4}}/) || [])[0] || '',
          price: parts.find(part => /元|USD|\\$|￥/.test(part)) || '',
          url: href,
          cover: abs(el.querySelector('img')?.getAttribute('src') || '')
        }});
        if (rows.length >= {count}) break;
      }}
      return rows;
    }})()
    """, "douban book-hot", timeout=30.0)
    records = rows if isinstance(rows, list) else []
    write_records(records, output_dir, "豆瓣图书热门榜单")
    log(f"写入 {len(records)} 条图书热门结果: {output_dir}")
    return 0


def parse_book_info(info_text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in str(info_text or "").replace("\r", "\n").splitlines():
        match = re.match(r"^([^:：]+)\s*[:：]\s*(.*)$", normalize_text(line))
        if match:
            result[normalize_text(match.group(1))] = normalize_text(match.group(2))
    return result


def split_people(value: str) -> list[str]:
    return [normalize_text(item) for item in re.split(r"\s*/\s*", value or "") if normalize_text(item)]


def normalize_book_subject(raw: dict[str, Any]) -> dict[str, Any]:
    info = parse_book_info(str(raw.get("infoText") or ""))
    isbn = re.sub(r"[^\dxX]", "", info.get("ISBN", ""))
    publish_date = info.get("出版年", "")
    return {
        "id": str(raw.get("id") or ""),
        "type": "book",
        "title": normalize_text(raw.get("title")),
        "subtitle": info.get("副标题", ""),
        "originalTitle": info.get("原作名", ""),
        "authors": split_people(info.get("作者", "")),
        "translators": split_people(info.get("译者", "")),
        "publisher": info.get("出版社", "") or info.get("出品方", ""),
        "publishDate": publish_date,
        "publishYear": (re.search(r"\b(?:19|20)\d{2}\b", publish_date) or [""])[0],
        "pageCount": int((re.search(r"\d+", info.get("页数", "")) or ["0"])[0] or "0"),
        "binding": info.get("装帧", ""),
        "price": info.get("定价", ""),
        "series": info.get("丛书", ""),
        "isbn10": isbn if len(isbn) == 10 else "",
        "isbn13": isbn if len(isbn) == 13 else "",
        "rating": float(raw.get("rating") or 0),
        "ratingCount": int(str(raw.get("ratingCount") or "0").replace(",", "") or "0"),
        "summary": normalize_text(raw.get("summary")),
        "cover": str(raw.get("cover") or ""),
        "url": str(raw.get("url") or ""),
    }


def run_subject(args: argparse.Namespace) -> int:
    subject_id = normalize_subject_id(args.id)
    subject_type = "book" if args.type == "book" else "movie"
    home = BOOK_HOME_URL if subject_type == "book" else MOVIE_HOME_URL
    output_dir = Path(args.output) if args.output else default_action_output_dir("subject", "view")
    book = start_book(args, f"{home}/subject/{subject_id}/")
    book.goto(f"{home}/subject/{subject_id}/")
    time.sleep(1.5)
    ensure_douban_ready(book)
    if subject_type == "book":
        raw = api_eval(book, f"""
        (() => {{
          const normalize = value => String(value || '').replace(/\\s+/g, ' ').trim();
          const nodes = [...document.querySelectorAll('#link-report .intro, .related_info .intro')];
          const summary = nodes.reverse().map(node => normalize(node.textContent)).find(Boolean) || '';
          return {{
            id: {json.dumps(subject_id)},
            title: normalize(document.querySelector('h1 span')?.textContent || document.querySelector('h1')?.textContent || ''),
            infoText: document.querySelector('#info')?.innerText || document.querySelector('#info')?.textContent || '',
            rating: normalize(document.querySelector('strong.rating_num, strong[property="v:average"]')?.textContent || '0'),
            ratingCount: normalize(document.querySelector('a.rating_people > span, span[property="v:votes"]')?.textContent || '0').replace(/[^0-9]/g, ''),
            summary,
            cover: document.querySelector('#mainpic img')?.getAttribute('src') || '',
            url: location.href
          }};
        }})()
        """, "douban book subject", timeout=30.0)
        subject = normalize_book_subject(raw if isinstance(raw, dict) else {})
    else:
        subject = api_eval(book, f"""
        (() => {{
          const normalize = value => String(value || '').replace(/\\s+/g, ' ').trim();
          const fullTitle = normalize(document.querySelector('span[property="v:itemreviewed"]')?.textContent || '');
          const year = normalize(document.querySelector('.year')?.textContent).replace(/[()（）]/g, '');
          const infoText = document.querySelector('#info')?.textContent || '';
          const country = (infoText.match(/制片国家\\/地区:\\s*([^\\n]+)/) || [])[1] || '';
          const runtime = normalize(document.querySelector('span[property="v:runtime"]')?.textContent || '');
          return {{
            id: {json.dumps(subject_id)},
            type: 'movie',
            title: fullTitle.replace(/\\s*\\([^)]*\\)\\s*$/, ''),
            originalTitle: '',
            year,
            rating: Number.parseFloat(normalize(document.querySelector('strong[property="v:average"]')?.textContent || '0')) || 0,
            ratingCount: Number.parseInt(normalize(document.querySelector('span[property="v:votes"]')?.textContent || '0'), 10) || 0,
            genres: [...document.querySelectorAll('span[property="v:genre"]')].map(node => normalize(node.textContent)).filter(Boolean).join(','),
            directors: [...document.querySelectorAll('a[rel="v:directedBy"]')].map(node => normalize(node.textContent)).filter(Boolean).join(','),
            casts: [...document.querySelectorAll('a[rel="v:starring"]')].slice(0, 8).map(node => normalize(node.textContent)).filter(Boolean),
            country: country.split(/\\s*\\/\\s*/).filter(Boolean),
            duration: Number.parseInt((runtime.match(/\\d+/) || [''])[0], 10) || null,
            summary: normalize(document.querySelector('span[property="v:summary"]')?.textContent || ''),
            cover: document.querySelector('#mainpic img')?.getAttribute('src') || '',
            url: location.href
          }};
        }})()
        """, "douban movie subject", timeout=30.0)
    write_subject(subject if isinstance(subject, dict) else {}, output_dir)
    log(f"写入条目详情: {output_dir}")
    return 0


def load_photos(book: ActionBook, subject_id: str, photo_type: str, count: int, photo_id: str = "") -> dict[str, Any]:
    url = f"{MOVIE_HOME_URL}/subject/{subject_id}/photos?type={urllib.parse.quote(photo_type)}"
    book.goto(url)
    time.sleep(1.5)
    ensure_douban_ready(book)
    safe_limit = 999999 if photo_id else count
    data = api_eval(book, f"""
    (async () => {{
      const subjectId = {json.dumps(subject_id)};
      const type = {json.dumps(photo_type)};
      const limit = {safe_limit};
      const targetPhotoId = {json.dumps(photo_id)};
      const pageSize = 30;
      const normalize = value => String(value || '').replace(/\\s+/g, ' ').trim();
      const abs = value => {{
        if (!value) return '';
        try {{ return new URL(value, location.origin).toString(); }} catch {{ return String(value || ''); }}
      }};
      const promote = value => abs(value).replace(/\\/view\\/photo\\/[^/]+\\/public\\//, '/view/photo/l/public/');
      const pageUrl = start => {{
        const next = new URL(location.href);
        next.searchParams.set('type', type);
        if (start > 0) next.searchParams.set('start', String(start));
        else next.searchParams.delete('start');
        return next.toString();
      }};
      const extract = (doc, page) => {{
        const rows = [];
        for (const node of [...doc.querySelectorAll('.poster-col3 li, .poster-col3l li, .article li')]) {{
          const link = node.querySelector('a[href*="/photos/photo/"]');
          const img = node.querySelector('img');
          if (!link || !img) continue;
          const detailUrl = abs(link.getAttribute('href') || '');
          const pid = (detailUrl.match(/\\/photo\\/(\\d+)/) || [])[1] || '';
          const thumbUrl = abs(img.getAttribute('data-origin') || img.getAttribute('data-src') || img.getAttribute('src') || '');
          const imageUrl = promote(thumbUrl);
          if (!detailUrl || !pid || !imageUrl || !/^https?:\\/\\//.test(imageUrl)) continue;
          rows.push({{
            photo_id: pid,
            title: normalize(link.getAttribute('title') || img.getAttribute('alt') || ('photo_' + pid)),
            image_url: imageUrl,
            thumb_url: thumbUrl,
            detail_url: detailUrl,
            page
          }});
        }}
        return rows;
      }};
      const subjectTitle = normalize(document.querySelector('#content h1')?.textContent || document.title).replace(/\\s*\\(豆瓣\\)\\s*$/, '');
      const seen = new Set();
      const photos = [];
      for (let pageIndex = 0; photos.length < limit; pageIndex += 1) {{
        let doc = document;
        if (pageIndex > 0) {{
          const response = await fetch(pageUrl(pageIndex * pageSize), {{ credentials: 'include' }});
          if (!response.ok) break;
          doc = new DOMParser().parseFromString(await response.text(), 'text/html');
        }}
        const pagePhotos = extract(doc, pageIndex + 1);
        if (!pagePhotos.length) break;
        let appended = 0;
        let found = false;
        for (const photo of pagePhotos) {{
          if (seen.has(photo.photo_id)) continue;
          seen.add(photo.photo_id);
          const row = {{ index: photos.length + 1, subject_id: subjectId, subject_title: subjectTitle, type, ...photo }};
          photos.push(row);
          appended += 1;
          if (targetPhotoId && photo.photo_id === targetPhotoId) {{ found = true; break; }}
          if (photos.length >= limit) break;
        }}
        if (found || appended === 0 || pagePhotos.length < pageSize) break;
      }}
      return {{ subjectId, subjectTitle, type, photos }};
    }})()
    """, "douban photos", timeout=60.0)
    if not isinstance(data, dict):
        return {"subjectId": subject_id, "subjectTitle": "", "type": photo_type, "photos": []}
    return data


def run_photos_view(args: argparse.Namespace) -> int:
    subject_id = normalize_subject_id(args.id)
    count = read_count(args.count, default=120, max_value=500)
    output_dir = Path(args.output) if args.output else default_action_output_dir("photos", "view")
    book = start_book(args, f"{MOVIE_HOME_URL}/subject/{subject_id}/photos")
    data = load_photos(book, subject_id, args.type, count)
    photos = data.get("photos") if isinstance(data.get("photos"), list) else []
    write_records(photos, output_dir, f"豆瓣图片列表: {data.get('subjectTitle') or subject_id}")
    log(f"写入 {len(photos)} 条图片记录: {output_dir}")
    return 0


def run_photos_download(args: argparse.Namespace) -> int:
    subject_id = normalize_subject_id(args.id)
    count = read_count(args.count, default=120, max_value=500)
    output_dir = Path(args.output) if args.output else default_action_output_dir("photos", "download")
    book = start_book(args, f"{MOVIE_HOME_URL}/subject/{subject_id}/photos")
    data = load_photos(book, subject_id, args.type, count, args.photo_id)
    photos = data.get("photos") if isinstance(data.get("photos"), list) else []
    if args.photo_id:
        photos = [photo for photo in photos if str(photo.get("photo_id") or "") == args.photo_id]
    records = []
    media_dir = output_dir / sanitize_name(subject_id, "subject") / "media"
    for photo in photos[:count]:
        base = media_dir / f"{int(photo.get('index') or len(records) + 1):03d}_{sanitize_name(str(photo.get('photo_id') or 'photo'), 'photo')}_{sanitize_name(str(photo.get('title') or 'image'), 'image')}"
        result = download_file(str(photo.get("image_url") or ""), base, str(photo.get("detail_url") or ""))
        row = {**photo, **result}
        records.append(row)
    write_records(records, output_dir, f"豆瓣图片下载: {data.get('subjectTitle') or subject_id}")
    write_json(output_dir / sanitize_name(subject_id, "subject") / "metadata.json", {"subject_id": subject_id, "type": args.type, "photos": records})
    log(f"下载 {sum(1 for row in records if row.get('status') == 'success')}/{len(records)} 张图片: {output_dir}")
    return 0


def run_marks(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=50, max_value=1000)
    output_dir = Path(args.output) if args.output else default_action_output_dir("marks", "view")
    book = start_book(args, MOVIE_HOME_URL + "/mine")
    uid = args.uid or get_self_uid(book)
    statuses = ["collect", "wish", "do"] if args.status == "all" else [args.status]
    rows: list[dict[str, Any]] = []
    for status in statuses:
        offset = 0
        while len(rows) < count:
            book.goto(f"{MOVIE_HOME_URL}/people/{urllib.parse.quote(uid)}/{status}?start={offset}&sort=time&rating=all&filter=all&mode=grid")
            time.sleep(1.2)
            ensure_douban_ready(book)
            page_rows = api_eval(book, f"""
            (() => {{
              const status = {json.dumps(status)};
              const normalize = value => String(value || '').replace(/\\s+/g, ' ').trim();
              const rows = [];
              for (const item of [...document.querySelectorAll('.item')]) {{
                const link = item.querySelector('.info a[href*="/subject/"]');
                if (!link) continue;
                const href = link.href || '';
                const id = (href.match(/subject\\/(\\d+)/) || [])[1] || '';
                const title = normalize(link.querySelector('em')?.textContent || link.textContent).split('/')[0].trim();
                if (!id || !title) continue;
                const cls = item.querySelector('span[class*="rating"]')?.className || '';
                const ratingMatch = cls.match(/rating(\\d)-t/);
                const intro = normalize(item.querySelector('.intro')?.textContent);
                rows.push({{
                  movieId: id,
                  title,
                  year: (intro.match(/\\b(?:19|20)\\d{{2}}\\b/) || [])[0] || '',
                  myRating: ratingMatch ? Number.parseInt(ratingMatch[1], 10) * 2 : null,
                  myStatus: status,
                  myDate: normalize(item.querySelector('.date')?.textContent),
                  myComment: normalize(item.querySelector('.comment')?.textContent),
                  url: href
                }});
              }}
              return rows;
            }})()
            """, "douban marks", timeout=30.0)
            batch = page_rows if isinstance(page_rows, list) else []
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < 15:
                break
            offset += 15
        if len(rows) >= count:
            break
    rows = rows[:count]
    write_records(rows, output_dir, f"豆瓣个人观影标记: {uid}")
    log(f"写入 {len(rows)} 条观影标记: {output_dir}")
    return 0


def run_reviews(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=500)
    output_dir = Path(args.output) if args.output else default_action_output_dir("reviews", "view")
    book = start_book(args, MOVIE_HOME_URL + "/mine")
    uid = args.uid or get_self_uid(book)
    rows: list[dict[str, Any]] = []
    start = 0
    while len(rows) < count:
        book.goto(f"{MOVIE_HOME_URL}/people/{urllib.parse.quote(uid)}/reviews?start={start}&sort=time")
        time.sleep(1.2)
        ensure_douban_ready(book)
        page_rows = api_eval(book, r"""
        (() => {
          const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
          const rows = [];
          for (const el of [...document.querySelectorAll('.tlst')]) {
            const movieLink = el.querySelector('.ilst a');
            const titleLink = el.querySelector('.nlst a[title]');
            const movieHref = movieLink?.href || '';
            const reviewHref = titleLink?.href || '';
            const cls = el.querySelector('.clst span[class*="allstar"]')?.className || '';
            const ratingMatch = cls.match(/allstar(\d)0/);
            const votes = normalize(el.querySelector('.review-short .pl span')?.textContent).match(/\d+/)?.[0] || '0';
            rows.push({
              reviewId: (reviewHref.match(/reviews\/(\d+)/) || [])[1] || '',
              movieId: (movieHref.match(/subject\/(\d+)/) || [])[1] || '',
              movieTitle: movieLink?.getAttribute('title') || normalize(movieLink?.textContent),
              title: normalize(titleLink?.textContent),
              content: normalize(el.querySelector('.review-short span')?.textContent),
              myRating: ratingMatch ? Number.parseInt(ratingMatch[1], 10) * 2 : 0,
              createdAt: '',
              votes: Number.parseInt(votes, 10) || 0,
              url: reviewHref
            });
          }
          return rows;
        })()
        """, "douban reviews", timeout=30.0)
        batch = page_rows if isinstance(page_rows, list) else []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 20:
            break
        start += 20
    rows = rows[:count]
    if args.full:
        for row in rows:
            if not row.get("url"):
                continue
            book.goto(str(row["url"]))
            time.sleep(1.0)
            row["content"] = str(api_eval(book, """
            (() => (document.querySelector('.review-content')?.textContent || '').replace(/\\s+/g, ' ').trim())()
            """, "douban full review", timeout=20.0) or "")
    write_records(rows, output_dir, f"豆瓣个人影评: {uid}")
    log(f"写入 {len(rows)} 条影评: {output_dir}")
    return 0


def add_common(parser: argparse.ArgumentParser, default_count: int = 20) -> None:
    parser.add_argument("--count", type=int, default=default_count, help="Number of records")
    parser.add_argument("--output", default="", help="Output directory")
    parser.add_argument("--session", default=DEFAULT_SESSION, help="ActionBook session id")
    parser.add_argument("--tab", default=DEFAULT_TAB, help="ActionBook tab id")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Douban workflow helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="Douban search workflows")
    search_sub = search.add_subparsers(dest="mode", required=True)
    search_view = search_sub.add_parser("view", help="View Douban search results")
    search_view.add_argument("--type", choices=("movie", "book", "music"), default="movie")
    search_view.add_argument("--keyword", required=True)
    add_common(search_view, default_count=20)
    search_view.set_defaults(func=run_search)

    top250 = subparsers.add_parser("top250", help="Douban movie Top250")
    top250_sub = top250.add_subparsers(dest="mode", required=True)
    top250_view = top250_sub.add_parser("view", help="View Douban movie Top250")
    add_common(top250_view, default_count=250)
    top250_view.set_defaults(func=run_top250)

    movie_hot = subparsers.add_parser("movie-hot", help="Douban movie hot chart")
    movie_hot_sub = movie_hot.add_subparsers(dest="mode", required=True)
    movie_hot_view = movie_hot_sub.add_parser("view", help="View Douban movie hot chart")
    add_common(movie_hot_view, default_count=20)
    movie_hot_view.set_defaults(func=run_movie_hot)

    book_hot = subparsers.add_parser("book-hot", help="Douban book hot chart")
    book_hot_sub = book_hot.add_subparsers(dest="mode", required=True)
    book_hot_view = book_hot_sub.add_parser("view", help="View Douban book hot chart")
    add_common(book_hot_view, default_count=20)
    book_hot_view.set_defaults(func=run_book_hot)

    subject = subparsers.add_parser("subject", help="Douban subject details")
    subject_sub = subject.add_subparsers(dest="mode", required=True)
    subject_view = subject_sub.add_parser("view", help="View one Douban subject")
    subject_view.add_argument("--id", required=True, help="Subject ID or subject URL")
    subject_view.add_argument("--type", choices=("movie", "book"), default="movie")
    add_common(subject_view, default_count=1)
    subject_view.set_defaults(func=run_subject)

    photos = subparsers.add_parser("photos", help="Douban movie photo workflows")
    photos_sub = photos.add_subparsers(dest="mode", required=True)
    photos_view = photos_sub.add_parser("view", help="View movie photos")
    photos_view.add_argument("--id", required=True, help="Movie subject ID or URL")
    photos_view.add_argument("--type", default="Rb", help="Douban photos type parameter, default Rb")
    add_common(photos_view, default_count=120)
    photos_view.set_defaults(func=run_photos_view)
    photos_download = photos_sub.add_parser("download", help="Download movie photos")
    photos_download.add_argument("--id", required=True, help="Movie subject ID or URL")
    photos_download.add_argument("--type", default="Rb", help="Douban photos type parameter, default Rb")
    photos_download.add_argument("--photo-id", default="", help="Only download one photo id")
    add_common(photos_download, default_count=120)
    photos_download.set_defaults(func=run_photos_download)

    download = subparsers.add_parser("download", help="Alias for photos download")
    download.add_argument("--id", required=True, help="Movie subject ID or URL")
    download.add_argument("--type", default="Rb", help="Douban photos type parameter, default Rb")
    download.add_argument("--photo-id", default="", help="Only download one photo id")
    add_common(download, default_count=120)
    download.set_defaults(func=run_photos_download)

    marks = subparsers.add_parser("marks", help="Douban movie marks")
    marks_sub = marks.add_subparsers(dest="mode", required=True)
    marks_view = marks_sub.add_parser("view", help="View movie marks")
    marks_view.add_argument("--status", choices=("collect", "wish", "do", "all"), default="collect")
    marks_view.add_argument("--uid", default="", help="Douban user id; default uses current login")
    add_common(marks_view, default_count=50)
    marks_view.set_defaults(func=run_marks)

    reviews = subparsers.add_parser("reviews", help="Douban movie reviews")
    reviews_sub = reviews.add_subparsers(dest="mode", required=True)
    reviews_view = reviews_sub.add_parser("view", help="View movie reviews")
    reviews_view.add_argument("--uid", default="", help="Douban user id; default uses current login")
    reviews_view.add_argument("--full", action="store_true", help="Fetch full review content")
    add_common(reviews_view, default_count=20)
    reviews_view.set_defaults(func=run_reviews)

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
