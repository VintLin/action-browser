#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Read-only JD workflow skeleton for the action-browser skill.

This file defines the parser and helper contract used by tests. Real
ActionBook browser extraction is intentionally left for a later task.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from actionbook_interrupts import install_interrupt_handlers
from actionbook_session import ActionBookSession as ActionBook


JD_HOME_URL = "https://www.jd.com"
JD_SEARCH_URL = "https://search.jd.com/Search"
DEFAULT_SESSION = "jd-task"
DEFAULT_TAB = ""
SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = SKILL_DIR / "assets" / "jd"


class LoginRequiredError(RuntimeError):
    """Raised when JD requires login or security verification."""


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def read_count(value: Any, default: int = 10, max_value: int = 30) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = default
    return max(1, min(count, max_value))


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_numeric_id(value: Any, label: str, example: str) -> str:
    raw = normalize_text(value)
    match = re.search(r"item\.jd\.com/(\d+)\.html", raw)
    if match:
        return match.group(1)
    match = re.search(r"(?:[?&](?:sku|id)=)(\d+)", raw)
    if match:
        return match.group(1)
    if re.fullmatch(r"\d+", raw):
        return raw
    raise argparse.ArgumentTypeError(f"{label} must include a numeric id, for example {example}")


def unwrap_eval(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def api_eval(book: ActionBook, script: str, label: str, timeout: float = 45.0) -> Any:
    data = unwrap_eval(book.eval(script, timeout=timeout))
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"{label}: {data.get('error')}")
    return data


def get_page_state(book: ActionBook) -> dict[str, str]:
    data = api_eval(
        book,
        """
        (() => ({
          href: location.href,
          title: document.title,
          text: (document.body?.innerText || '').slice(0, 1200),
        }))()
        """,
        "读取京东页面状态失败",
    )
    state = data if isinstance(data, dict) else {}
    return {
        "href": str(state.get("href") or ""),
        "title": normalize_text(state.get("title")),
        "text": normalize_text(state.get("text")),
    }


def page_has_login_or_risk(state: dict[str, str]) -> bool:
    href = str(state.get("href") or "").lower()
    title = normalize_text(state.get("title"))
    text = normalize_text(state.get("text"))
    haystack = f"{href} {title} {text}"
    risk_terms = (
        "passport.jd.com",
        "login.aspx",
        "plogin.m.jd.com",
        "安全验证",
        "身份验证",
        "风险",
        "请登录",
        "登录京东",
    )
    return any(term in haystack for term in risk_terms)


def ensure_ready(book: ActionBook) -> None:
    state = get_page_state(book)
    if page_has_login_or_risk(state):
        raise LoginRequiredError(
            "LOGIN_REQUIRED: 京东需要登录或安全验证；请在 ActionBook 连接的 Chrome 窗口完成后重试。"
        )


def start_book(args: argparse.Namespace, url: str) -> ActionBook:
    book = ActionBook(args.session, args.tab)
    book.start(url)
    return book


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def default_output_dir(area: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return ASSETS_DIR / "views" / area / stamp


def write_records(records: list[dict[str, Any]], output_dir: Path, title: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", records)
    lines = [f"# {title}", "", f"- 条目数: {len(records)}", ""]
    for index, item in enumerate(records, start=1):
        heading = item.get("title") or item.get("sku") or item.get("field") or item.get("source_url") or str(index)
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


def finish(records: list[dict[str, Any]], args: argparse.Namespace, area: str, title: str) -> int:
    output_dir = Path(args.output) if args.output else default_output_dir(area)
    write_records(records, output_dir, title)
    log(f"已写入: {output_dir}")
    return 0


def add_common_view_args(parser: argparse.ArgumentParser, count_default: int) -> None:
    parser.add_argument("--session", default=DEFAULT_SESSION)
    parser.add_argument("--tab", default=DEFAULT_TAB)
    parser.add_argument("--output", default="")
    parser.add_argument("--count", default=str(count_default))


def add_view_parser(
    area: argparse.ArgumentParser,
    *,
    help_text: str,
    handler: Any,
    count_default: int,
) -> argparse.ArgumentParser:
    modes = area.add_subparsers(dest="mode", metavar="{view}", required=True)
    view = modes.add_parser("view", help=help_text)
    add_common_view_args(view, count_default)
    view.set_defaults(func=handler)
    return view


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only JD workflow helper")
    areas = parser.add_subparsers(dest="area", required=True)

    search = areas.add_parser("search", help="JD search workflows")
    search_view = add_view_parser(search, help_text="View JD search results", handler=run_search, count_default=10)
    search_view.add_argument("--query", required=True)

    item = areas.add_parser("item", help="JD item workflows")
    item_view = add_view_parser(item, help_text="View JD item summary", handler=run_item, count_default=1)
    item_view.add_argument("--sku", required=True)
    item_view.add_argument("--images", type=int, default=200)

    detail = areas.add_parser("detail", help="JD detail workflows")
    detail_view = add_view_parser(detail, help_text="View JD item details", handler=run_detail, count_default=1)
    detail_view.add_argument("--sku", required=True)

    reviews = areas.add_parser("reviews", help="JD reviews workflows")
    reviews_view = add_view_parser(reviews, help_text="View JD item reviews", handler=run_reviews, count_default=10)
    reviews_view.add_argument("--sku", required=True)

    cart = areas.add_parser("cart", help="JD cart workflows")
    add_view_parser(cart, help_text="View JD cart", handler=run_cart, count_default=20)

    whoami = areas.add_parser("whoami", help="Current JD account workflows")
    add_view_parser(whoami, help_text="View current JD account", handler=run_whoami, count_default=1)

    return parser


SEARCH_SCRIPT = """
(async () => {
  const limit = LIMIT_PLACEHOLDER;
  const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  for (let i = 0; i < 20; i++) {
    if (document.querySelectorAll('div[data-sku]').length > 0) break;
    await sleep(500);
  }
  for (let i = 0; i < 2; i++) {
    window.scrollBy(0, Math.max(600, window.innerHeight * 0.9));
    await sleep(900);
  }
  const results = [];
  for (const el of document.querySelectorAll('div[data-sku]')) {
    const sku = el.getAttribute('data-sku') || '';
    if (!sku || results.some(item => item.sku === sku)) continue;
    const priceEl = el.querySelector('.p-price i, .p-price strong, [class*="price"] i');
    const titleEl = el.querySelector('.p-name em, .p-name a, [class*="name"] em, a[href*="item.jd.com"]');
    const shopEl = el.querySelector('.p-shop a, .p-shop span, [class*="shop"] a');
    const text = normalize(el.innerText || el.textContent);
    const priceMatch = text.match(/¥\\s*([\\d,.]+)/);
    const title = normalize(titleEl?.innerText || titleEl?.textContent || '').replace(/^京东价\\s*/, '');
    let shop = normalize(shopEl?.innerText || shopEl?.textContent || '');
    if (!shop) {
      const shopMatch = text.match(/(\\S{2,24}(?:旗舰店|专卖店|自营店|官方旗舰店|京东自营))/);
      shop = shopMatch ? shopMatch[1] : '';
    }
    const url = new URL(`/` + sku + `.html`, 'https://item.jd.com').href;
    if (!title || title.length < 2) continue;
    results.push({
      rank: results.length + 1,
      title: title.slice(0, 120),
      price: normalize(priceEl?.innerText || priceEl?.textContent) || (priceMatch ? '¥' + priceMatch[1] : ''),
      shop,
      sku,
      url,
    });
    if (results.length >= limit) break;
  }
  return results;
})()
"""


DETAIL_SCRIPT = """
(() => {
  const sku = SKU_PLACEHOLDER;
  const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
  const text = document.body?.innerText || '';
  const titleNode = document.querySelector('.sku-name, #name h1, h1, [class*="sku-name"]');
  const titleFromDoc = document.title.replace(/^【[^】]*】/, '').split('【')[0];
  const title = normalize(titleNode?.innerText || titleNode?.textContent || titleFromDoc);
  const priceNode = document.querySelector('.price, .p-price, .summary-price [class*="price"], [class*="price"]');
  const priceMatch = text.match(/¥\\s*([\\d,.]+)/);
  const shopNode = document.querySelector('#popbox .name a, .J-hove-wrap a, .seller-infor a, [class*="shop"] a');
  let shop = normalize(shopNode?.innerText || shopNode?.textContent || '');
  if (!shop) {
    const shopMatch = text.match(/(\\S{2,24}(?:京东自营旗舰店|官方旗舰店|旗舰店|专卖店|自营店|京东自营))/);
    shop = shopMatch ? shopMatch[1] : '';
  }
  const records = [
    { field: '商品名称', value: title },
    { field: '价格', value: normalize(priceNode?.innerText || priceNode?.textContent) || (priceMatch ? '¥' + priceMatch[1] : '') },
    { field: '店铺', value: shop },
    { field: 'SKU', value: sku },
    { field: '链接', value: location.href },
  ];
  return records.filter(item => item.value);
})()
"""


ITEM_SCRIPT = """
(async () => {
  const sku = SKU_PLACEHOLDER;
  const imageLimit = IMAGE_LIMIT_PLACEHOLDER;
  const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
  const normalizeUrl = value => {
    let url = String(value || '').trim();
    if (!url) return '';
    if (url.startsWith('//')) url = 'https:' + url;
    if (!/^https?:\\/\\//.test(url) || !url.includes('360buyimg.com')) return '';
    return url.replace(/\\?.*$/, '');
  };
  const pushUrl = (list, value) => {
    const url = normalizeUrl(value);
    if (url && !list.includes(url)) list.push(url);
  };
  const collectFrom = root => {
    const urls = [];
    for (const img of root.querySelectorAll?.('img[src*="360buyimg.com"], img[data-src*="360buyimg.com"], img[data-lazy-img*="360buyimg.com"], img[data-original*="360buyimg.com"]') || []) {
      pushUrl(urls, img.currentSrc || img.src);
      pushUrl(urls, img.getAttribute('data-src'));
      pushUrl(urls, img.getAttribute('data-lazy-img'));
      pushUrl(urls, img.getAttribute('data-original'));
    }
    for (const source of root.querySelectorAll?.('source[srcset*="360buyimg.com"], source[data-srcset*="360buyimg.com"]') || []) {
      pushUrl(urls, (source.getAttribute('srcset') || '').split(/\\s+/)[0]);
      pushUrl(urls, (source.getAttribute('data-srcset') || '').split(/\\s+/)[0]);
    }
    for (const el of root.querySelectorAll?.('[style*="360buyimg.com"]') || []) {
      for (const match of (el.getAttribute('style') || '').matchAll(/url\\(["']?([^"')]+360buyimg\\.com[^"')]+)["']?\\)/g)) {
        pushUrl(urls, match[1]);
      }
    }
    return urls;
  };
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  for (let i = 0; i < 2; i++) {
    window.scrollBy(0, Math.max(800, window.innerHeight));
    await sleep(800);
  }
  const text = document.body?.innerText || '';
  const titleNode = document.querySelector('.sku-name, #name h1, h1, [class*="sku-name"]');
  const title = normalize(titleNode?.innerText || titleNode?.textContent || document.title.split('【')[0]);
  const priceNode = document.querySelector('.price, .p-price, .summary-price [class*="price"], [class*="price"]');
  const priceMatch = text.match(/¥\\s*([\\d,.]+)/);
  const shopNode = document.querySelector('#popbox .name a, .J-hove-wrap a, .seller-infor a, [class*="shop"] a');
  const specs = {};
  for (const item of document.querySelectorAll('.p-parameter li, .parameter2 li, [class*="parameter"] li')) {
    const value = normalize(item.innerText || item.textContent);
    const parts = value.split(/[：:]/);
    if (parts.length >= 2 && Object.keys(specs).length < 30) specs[normalize(parts[0])] = normalize(parts.slice(1).join(':'));
  }
  const allImages = collectFrom(document);
  const mainImages = [];
  const detailImages = [];
  for (const url of allImages) {
    if (/\\/(n\\d+|pcpubliccms)\\/jfs\\//.test(url) && !/(detail|desc|sku|shaidan|comment|review)/i.test(url)) {
      pushUrl(mainImages, url);
    } else {
      pushUrl(detailImages, url);
    }
  }
  for (const url of allImages) {
    if (mainImages.length + detailImages.length >= imageLimit) break;
    if (!mainImages.includes(url) && !detailImages.includes(url)) pushUrl(detailImages, url);
  }
  return {
    title,
    price: normalize(priceNode?.innerText || priceNode?.textContent) || (priceMatch ? '¥' + priceMatch[1] : ''),
    shop: normalize(shopNode?.innerText || shopNode?.textContent || ''),
    specs,
    main_images: mainImages.slice(0, imageLimit),
    detail_images: detailImages.slice(0, Math.max(0, imageLimit - mainImages.slice(0, imageLimit).length)),
    source_url: location.href || `https://item.jd.com/${sku}.html`,
  };
})()
"""


REVIEWS_SCRIPT = """
(async () => {
  const limit = LIMIT_PLACEHOLDER;
  const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const reviewAnchor = document.querySelector('#comment, #comment-0, .comment, [clstag*="comment"]');
  if (reviewAnchor) reviewAnchor.scrollIntoView({ block: 'center' });
  else window.scrollBy(0, Math.max(1200, window.innerHeight * 2));
  await sleep(1200);
  const records = [];
  for (const item of document.querySelectorAll('.comment-item, .comment-con, [class*="comment-item"]')) {
    const user = normalize(item.querySelector('.user-info, .user-column, [class*="user"]')?.innerText || '');
    const content = normalize(item.querySelector('.comment-con, .comment-content, [class*="content"]')?.innerText || item.innerText || '');
    const dateMatch = content.match(/20\\d{2}[-./年]\\d{1,2}[-./月]\\d{1,2}/);
    const date = dateMatch ? dateMatch[0] : '';
    if (content.length < 5) continue;
    records.push({ rank: records.length + 1, user, content: content.slice(0, 200), date });
    if (records.length >= limit) return records;
  }
  const text = document.body?.innerText || '';
  const start = text.indexOf('买家评价');
  if (start < 0) return records;
  const section = text.slice(start, start + 4000);
  const lines = section.split('\\n').map(normalize).filter(Boolean);
  const userPattern = /^[a-zA-Z0-9*_\\u4e00-\\u9fa5-]{2,24}$/;
  for (let i = 0; i < lines.length && records.length < limit; i++) {
    if (!userPattern.test(lines[i]) || i + 1 >= lines.length) continue;
    const content = lines[i + 1];
    if (content.length < 5 || /^(全部评价|问大家|查看更多|商品问答)/.test(content)) continue;
    const dateMatch = content.match(/20\\d{2}[-./年]\\d{1,2}[-./月]\\d{1,2}/);
    records.push({ rank: records.length + 1, user: lines[i], content: content.slice(0, 200), date: dateMatch ? dateMatch[0] : '' });
  }
  return records;
})()
"""


CART_SCRIPT = """
(async () => {
  const limit = LIMIT_PLACEHOLDER;
  const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  for (let i = 0; i < 12; i++) {
    if ((document.body?.innerText || '').length > 400) break;
    await sleep(500);
  }
  const text = document.body?.innerText || '';
  if (/请登录|登录后|passport\\.jd\\.com|安全验证/.test(text) || location.href.includes('passport.jd.com')) {
    return { auth_required: true };
  }
  try {
    const resp = await fetch('https://api.m.jd.com/api?appid=JDC_mall_cart&functionId=pcCart_jc_getCurrentCart&body=%7B%22serInfo%22%3A%7B%7D%7D', {
      credentials: 'include',
      headers: { referer: 'https://cart.jd.com/' },
    });
    if (resp.ok) {
      const json = await resp.json();
      const vendors = json?.resultData?.cartInfo?.vendors || json?.cartInfo?.vendors || [];
      const items = [];
      for (const vendor of vendors) {
        for (const node of (vendor.sorted || vendor.items || [])) {
          const product = node.item || node;
          const sku = String(product.Id || product.skuId || product.sku || '');
          if (!sku) continue;
          items.push({
            index: items.length + 1,
            title: normalize(product.name || product.Name || product.title).slice(0, 120),
            price: product.price ? '¥' + product.price : '',
            quantity: String(product.num || product.Num || product.quantity || 1),
            sku,
          });
          if (items.length >= limit) return { items };
        }
      }
      if (items.length) return { items };
    }
  } catch (error) {}
  const lines = text.split('\\n').map(normalize).filter(Boolean);
  const items = [];
  for (let i = 0; i < lines.length && items.length < limit; i++) {
    const priceMatch = lines[i].match(/¥\\s*([\\d,.]+)/);
    if (!priceMatch || i === 0) continue;
    const title = lines.slice(Math.max(0, i - 3), i).reverse().find(line => line.length > 5 && !/^¥/.test(line)) || '';
    if (!title) continue;
    const skuMatch = lines.slice(Math.max(0, i - 8), i + 4).join(' ').match(/\\b(\\d{6,})\\b/);
    items.push({ index: items.length + 1, title: title.slice(0, 120), price: '¥' + priceMatch[1], quantity: '', sku: skuMatch ? skuMatch[1] : '' });
  }
  return { items };
})()
"""


WHOAMI_SCRIPT = """
(() => {
  const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
  const firstText = selectors => {
    for (const selector of selectors) {
      const text = normalize(document.querySelector(selector)?.innerText || document.querySelector(selector)?.textContent || '');
      if (text) return text;
    }
    return '';
  };
  const readState = () => {
    const result = { nickname: '', user_id: '' };
    const roots = [
      globalThis.__INITIAL_STATE__,
      globalThis.__INITIAL_DATA__,
      globalThis.__PAGE_DATA__,
      globalThis.pageData,
    ].filter(Boolean);
    const keyMap = {
      nickname: 'nickname',
      nickName: 'nickname',
      userName: 'nickname',
      displayName: 'nickname',
      userId: 'user_id',
      uid: 'user_id',
      accountId: 'user_id',
    };
    const walk = (value, depth, seen) => {
      if (!value || typeof value !== 'object' || depth > 3 || seen.has(value)) return;
      seen.add(value);
      for (const [key, item] of Object.entries(value)) {
        const target = keyMap[key];
        if (target && typeof item === 'string' && !result[target]) result[target] = normalize(item).slice(0, 80);
        if ((!result.nickname || !result.user_id) && item && typeof item === 'object') walk(item, depth + 1, seen);
      }
    };
    for (const root of roots) walk(root, 0, new Set());
    return result;
  };
  const text = document.body?.innerText || '';
  if (/请登录|登录京东|passport\\.jd\\.com|安全验证/.test(text) || location.href.includes('passport.jd.com')) {
    return { auth_required: true };
  }
  const state = readState();
  const nickname = firstText(['.user-info', '#aliveUserName', '.name', '.user-name', '[class*="nickname"]']) || state.nickname;
  const visibleId = firstText(['[data-user-id]', '[data-uid]', '[class*="user-id"]']);
  if (!nickname && !visibleId && !state.user_id) return { auth_required: true };
  return { logged_in: true, nickname, user_id: visibleId || state.user_id || '', source_url: location.href };
})()
"""


def run_search(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=10, max_value=30)
    url = f"{JD_SEARCH_URL}?keyword={quote(normalize_text(args.query))}&enc=utf-8"
    book = start_book(args, url)
    ensure_ready(book)
    records = api_eval(book, SEARCH_SCRIPT.replace("LIMIT_PLACEHOLDER", str(count)), "读取京东搜索结果失败")
    if not isinstance(records, list):
        records = []
    return finish(records[:count], args, "search", f"京东搜索: {args.query}")


def run_item(args: argparse.Namespace) -> int:
    sku = normalize_numeric_id(args.sku, "--sku", "100291143898")
    image_limit = read_count(args.images, default=200, max_value=200)
    url = f"https://item.jd.com/{sku}.html"
    book = start_book(args, url)
    ensure_ready(book)
    record = api_eval(
        book,
        ITEM_SCRIPT.replace("SKU_PLACEHOLDER", json.dumps(sku)).replace("IMAGE_LIMIT_PLACEHOLDER", str(image_limit)),
        "读取京东商品信息失败",
        timeout=60.0,
    )
    if not isinstance(record, dict):
        record = {"title": "", "price": "", "shop": "", "specs": {}, "main_images": [], "detail_images": [], "source_url": url}
    record["source_url"] = record.get("source_url") or url
    return finish([record], args, "item", f"京东商品: {sku}")


def run_detail(args: argparse.Namespace) -> int:
    sku = normalize_numeric_id(args.sku, "--sku", "100291143898")
    url = f"https://item.jd.com/{sku}.html"
    book = start_book(args, url)
    ensure_ready(book)
    records = api_eval(book, DETAIL_SCRIPT.replace("SKU_PLACEHOLDER", json.dumps(sku)), "读取京东商品详情失败")
    if not isinstance(records, list):
        records = [{"field": "SKU", "value": sku}, {"field": "链接", "value": url}]
    return finish(records, args, "detail", f"京东商品详情: {sku}")


def run_reviews(args: argparse.Namespace) -> int:
    sku = normalize_numeric_id(args.sku, "--sku", "100291143898")
    count = read_count(args.count, default=10, max_value=20)
    url = f"https://item.jd.com/{sku}.html"
    book = start_book(args, url)
    ensure_ready(book)
    records = api_eval(book, REVIEWS_SCRIPT.replace("LIMIT_PLACEHOLDER", str(count)), "读取京东商品评价失败")
    if not isinstance(records, list):
        records = []
    return finish(records[:count], args, "reviews", f"京东商品评价: {sku}")


def run_cart(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=50)
    book = start_book(args, "https://cart.jd.com/cart_index")
    ensure_ready(book)
    data = api_eval(book, CART_SCRIPT.replace("LIMIT_PLACEHOLDER", str(count)), "读取京东购物车失败", timeout=60.0)
    if isinstance(data, dict) and data.get("auth_required"):
        raise LoginRequiredError(
            "LOGIN_REQUIRED: 京东购物车需要已登录会话；请在 ActionBook 连接的 Chrome 窗口登录后重试。"
        )
    records = data.get("items") if isinstance(data, dict) else []
    if not isinstance(records, list):
        records = []
    return finish(records[:count], args, "cart", "京东购物车")


def run_whoami(args: argparse.Namespace) -> int:
    book = start_book(args, "https://home.jd.com/")
    ensure_ready(book)
    record = api_eval(book, WHOAMI_SCRIPT, "读取京东当前账号失败")
    if isinstance(record, dict) and record.get("auth_required"):
        raise LoginRequiredError(
            "LOGIN_REQUIRED: 未检测到京东登录态；请在 ActionBook 连接的 Chrome 窗口登录后重试。"
        )
    if not isinstance(record, dict):
        record = {"logged_in": False, "nickname": "", "user_id": "", "source_url": JD_HOME_URL}
    return finish([record], args, "whoami", "京东当前账号")


def main(argv: list[str] | None = None) -> int:
    install_interrupt_handlers()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except LoginRequiredError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
