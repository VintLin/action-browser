#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Taobao read-only ActionBook workflow helper for the action-browser skill."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[2]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
from typing import Any
from urllib.parse import quote

from scripts.actionbook_interrupts import install_interrupt_handlers
from scripts.workflow_runtime import add_workflow_args, attach_workflow, evaluate, write_json
from scripts.actionbook_session import ActionBookSession as ActionBook
from scripts.script_common import log


TAOBAO_HOME_URL = "https://www.taobao.com"
TAOBAO_SEARCH_URL = "https://s.taobao.com/search"
HOME_WARMUP_SECONDS = 2.0
SEARCH_SETTLE_SECONDS = 8.0
PAGE_SETTLE_SECONDS = 6.0
WHOAMI_SETTLE_SECONDS = 2.0
SKILL_DIR = Path(__file__).resolve().parents[2]
ASSETS_DIR = SKILL_DIR / "assets" / "taobao"
CONTRACT_DIRNAME = "contract"


class LoginRequiredError(RuntimeError):
    """Raised when Taobao requires login or security verification."""
def read_count(value: Any, default: int = 10, max_value: int = 40) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = default
    return max(1, min(count, max_value))


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_numeric_id(value: Any, label: str, example: str) -> str:
    raw = normalize_text(value)
    match = re.search(r"(?:item\.taobao\.com|detail\.tmall\.com)/item\.htm\?[^#\s]*\bid=(\d+)", raw)
    if match:
        return match.group(1)
    match = re.search(r"(?:[?&](?:id|itemId|item_id)=)(\d+)", raw)
    if match:
        return match.group(1)
    if re.fullmatch(r"\d+", raw):
        return raw
    raise argparse.ArgumentTypeError(f"{label} must include a numeric id, for example {example}")
def require_list_payload(value: Any, label: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        for index, item in enumerate(value, start=1):
            if not isinstance(item, dict):
                raise RuntimeError(f"{label}: malformed element at index {index}")
        return value
    if isinstance(value, dict) and value.get("error"):
        raise RuntimeError(f"{label}: {value.get('error')}")
    raise RuntimeError(f"{label}: malformed payload")


def require_dict_payload(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("error"):
        raise RuntimeError(f"{label}: {value.get('error')}")
    if not isinstance(value, dict):
        raise RuntimeError(f"{label}: malformed payload")
    return value


def require_cart_payload(value: Any, label: str) -> list[dict[str, Any]]:
    if isinstance(value, dict) and value.get("error"):
        raise RuntimeError(f"{label}: {value.get('error')}")
    if not isinstance(value, dict) or "items" not in value or not isinstance(value.get("items"), list):
        raise RuntimeError(f"{label}: malformed payload")
    records = value["items"]
    for index, item in enumerate(records, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"{label}: malformed element at index {index}")
    if not records and not bool(value.get("loaded")):
        raise RuntimeError(f"{label}: not fully loaded")
    return records


def get_page_state(book: ActionBook) -> dict[str, str]:
    data = evaluate(
        book,
        """
        (() => ({
          href: location.href,
          title: document.title,
          text: (document.body?.innerText || '').slice(0, 1200),
        }))()
        """,
        "读取淘宝页面状态失败",
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
        "login.taobao.com",
        "/login",
        "passport",
        "verify",
        "captcha",
        "请登录后",
        "登录后",
        "扫码登录",
        "验证码",
        "安全验证",
        "风险",
        "访问频繁",
        "滑块",
    )
    risk_pattern = "|".join(re.escape(term) for term in risk_terms)
    return re.search(risk_pattern, haystack, re.I) is not None


def ensure_ready(book: ActionBook) -> None:
    state = get_page_state(book)
    if page_has_login_or_risk(state):
        raise LoginRequiredError(
            "LOGIN_REQUIRED: 淘宝需要登录或安全验证；请在 ActionBook 连接的 Chrome 窗口完成后重试。"
        )



def default_output_dir(area: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return ASSETS_DIR / "views" / area / stamp


def write_records(records: list[dict[str, Any]], output_dir: Path, title: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", records)
    lines = [f"# {title}", "", f"- 条目数: {len(records)}", ""]
    for index, item in enumerate(records, start=1):
        heading = item.get("title") or item.get("id") or item.get("field") or item.get("source_url") or str(index)
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


def write_contract_outputs(
    *,
    records: list[dict[str, Any]],
    output_dir: Path,
    task_id: str,
    site: str,
    intent: str,
    requested_count: int,
    warnings: list[str],
    needs_user_action: bool,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    contract_dir = output_dir / CONTRACT_DIRNAME
    artifacts_dir = contract_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    write_json(artifacts_dir / "results.json", records)
    write_json(
        contract_dir / "summary.json",
        {
            "schema_version": 1,
            "task_id": task_id,
            "ok": True,
            "site": site,
            "intent": intent,
            "requested_count": requested_count,
            "collected_count": len(records),
            "artifacts": [f"{CONTRACT_DIRNAME}/artifacts/results.json"],
            "warnings": warnings,
            "needs_user_action": needs_user_action,
        },
    )
    write_json(
        contract_dir / "progress.json",
        {
            "schema_version": 1,
            "task_id": task_id,
            "stage": "writing_results",
            "completed_items": len(records),
            "requested_items": requested_count,
        },
    )


def requested_count_for_intent(args: argparse.Namespace, area: str) -> int:
    if area in {"detail", "whoami"}:
        return 1
    count_value = getattr(args, "count", None)
    if area == "cart":
        return read_count(count_value, default=20, max_value=50)
    if area == "reviews":
        return read_count(count_value, default=10, max_value=20)
    return read_count(count_value, default=10, max_value=40)


def finish(records: list[dict[str, Any]], args: argparse.Namespace, area: str, title: str) -> int:
    output_dir = Path(args.output) if args.output else default_output_dir(area)
    write_records(records, output_dir, title)
    write_contract_outputs(
        records=records,
        output_dir=output_dir,
        task_id=str(getattr(args, "task_id", "") or ""),
        site="taobao",
        intent=area,
        requested_count=requested_count_for_intent(args, area),
        warnings=[],
        needs_user_action=False,
    )
    log(f"已写入: {output_dir} 条目数={len(records)}")
    return 0


def add_common_view_args(parser: argparse.ArgumentParser, count_default: int) -> None:
    add_workflow_args(parser)
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
    parser = argparse.ArgumentParser(description="Read-only Taobao workflow helper")
    areas = parser.add_subparsers(dest="area", required=True)

    search = areas.add_parser("search", help="Taobao search workflows")
    search_view = add_view_parser(search, help_text="View Taobao search results", handler=run_search, count_default=10)
    search_view.add_argument("--query", required=True)
    search_view.add_argument("--sort", choices=("default", "sale", "price"), default="default")

    detail = areas.add_parser("detail", help="Taobao detail workflows")
    detail_view = add_view_parser(detail, help_text="View Taobao item details", handler=run_detail, count_default=1)
    detail_view.add_argument("--id", required=True)

    reviews = areas.add_parser("reviews", help="Taobao reviews workflows")
    reviews_view = add_view_parser(reviews, help_text="View Taobao item reviews", handler=run_reviews, count_default=10)
    reviews_view.add_argument("--id", required=True)

    cart = areas.add_parser("cart", help="Taobao cart workflows")
    add_view_parser(cart, help_text="View Taobao cart", handler=run_cart, count_default=20)

    whoami = areas.add_parser("whoami", help="Current Taobao account workflows")
    add_view_parser(whoami, help_text="View current Taobao account", handler=run_whoami, count_default=1)

    return parser


SEARCH_SCRIPT = """
(async () => {
  const limit = LIMIT_PLACEHOLDER;
  const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  for (let i = 0; i < 30; i++) {
    const text = document.body?.innerText || '';
    if (/login\\.taobao\\.com|安全验证|验证码|扫码登录|请登录后/.test(location.href + ' ' + text)) {
      return { error: 'auth-required' };
    }
    if (document.querySelectorAll('[class*="doubleCard--"], a[href*="item.taobao.com/item.htm"], a[href*="detail.tmall.com/item.htm"]').length > 4) break;
    await sleep(500);
  }
  for (let i = 0; i < 3; i++) {
    window.scrollBy(0, Math.max(700, window.innerHeight * 0.9));
    await sleep(2000);
  }
  const text = document.body?.innerText || '';
  if (/login\\.taobao\\.com|安全验证|验证码|扫码登录|请登录后/.test(location.href + ' ' + text)) {
    return { error: 'auth-required' };
  }
  const cardSet = new Set();
  for (const card of document.querySelectorAll('[class*="doubleCard--"]')) cardSet.add(card);
  for (const link of document.querySelectorAll('a[href*="item.taobao.com/item.htm"], a[href*="detail.tmall.com/item.htm"]')) {
    let node = link;
    for (let i = 0; i < 5 && node; i++) {
      const body = normalize(node.innerText || node.textContent);
      if (body.length > 30 && /[￥¥]\\s*\\d/.test(body)) {
        cardSet.add(node);
        break;
      }
      node = node.parentElement;
    }
  }
  const results = [];
  const seenIds = new Set();
  const seenTitles = new Set();
  for (const card of cardSet) {
    const body = normalize(card.innerText || card.textContent);
    if (body.length < 10) continue;
    const titleEl = card.querySelector('[class*="title--"], [class*="Title--"], a[href*="item.taobao.com/item.htm"], a[href*="detail.tmall.com/item.htm"]');
    let title = normalize(titleEl?.innerText || titleEl?.textContent || '');
    if (!title) {
      title = body.split(/[\\n￥¥]/).map(normalize).find(line => line.length >= 4 && line.length <= 120) || '';
    }
    title = title.replace(/^广告\\s*/, '').slice(0, 120);
    if (!title || title.length < 3 || seenTitles.has(title)) continue;
    const link = card.querySelector('a[href*="item.taobao.com/item.htm"], a[href*="detail.tmall.com/item.htm"]');
    const href = link?.href || link?.getAttribute('href') || '';
    const idMatch = href.match(/[?&]id=(\\d+)/) || body.match(/\\bid[=:](\\d{8,})\\b/);
    let itemId = idMatch ? idMatch[1] : '';
    if (!itemId) {
      let wrapper = card;
      for (let i = 0; i < 4 && wrapper; i++) {
        const spmId = wrapper.getAttribute('data-spm-act-id') || wrapper.getAttribute('data-item-id') || '';
        if (/^\\d{8,}$/.test(spmId)) {
          itemId = spmId;
          break;
        }
        wrapper = wrapper.parentElement;
      }
    }
    if (itemId && seenIds.has(itemId)) continue;
    const intEl = card.querySelector('[class*="priceInt--"], [class*="price-int"]');
    const floatEl = card.querySelector('[class*="priceFloat--"], [class*="price-float"]');
    const priceMatch = body.match(/[￥¥]\\s*([\\d,.]+(?:\\.\\d{1,2})?)/);
    const price = intEl
      ? '¥' + normalize(intEl.textContent) + normalize(floatEl?.textContent || '')
      : (priceMatch ? '¥' + priceMatch[1] : '');
    const salesEl = card.querySelector('[class*="realSales--"], [class*="sales--"]');
    const salesMatch = body.match(/(?:月销|付款|已售)\\s*([\\d.]+万?\\+?)/);
    const sales = normalize(salesEl?.textContent || '') || (salesMatch ? salesMatch[0] : '');
    const shopEl = card.querySelector('[class*="shopName--"], [class*="ShopName--"], [class*="shop--"] a, a[href*="shop"]');
    let shop = normalize(shopEl?.innerText || shopEl?.textContent || '');
    shop = normalize(shop.replace(/^\\d+年老店/, '').replace(/^回头客[\\d万]+/, ''));
    const locEls = card.querySelectorAll('[class*="procity--"], [class*="location--"]');
    let itemLocation = Array.from(locEls).map(el => normalize(el.textContent)).join('');
    if (!itemLocation) {
      const locMatch = body.match(/(?:上海|北京|天津|重庆|广东|浙江|江苏|福建|山东|河南|河北|湖南|湖北|四川|陕西|安徽|江西|辽宁|吉林|黑龙江|广西|云南|贵州|海南|山西|甘肃|青海|内蒙古|宁夏|新疆|西藏)[\\u4e00-\\u9fa5]{0,4}/);
      itemLocation = locMatch ? locMatch[0] : '';
    }
    seenTitles.add(title);
    if (itemId) seenIds.add(itemId);
    results.push({
      rank: results.length + 1,
      title,
      price,
      sales,
      shop,
      location: itemLocation,
      item_id: itemId,
      url: itemId ? 'https://item.taobao.com/item.htm?id=' + itemId : (href ? new URL(href, location.href).href : ''),
    });
    if (results.length >= limit) break;
  }
  if (!results.length && !/没有找到|暂无相关|无结果/.test(text)) {
    return { error: 'no search cards found' };
  }
  return results;
})()
"""


DETAIL_SCRIPT = """
(() => {
  const itemId = ITEM_ID_PLACEHOLDER;
  const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
  const text = document.body?.innerText || '';
  if (/login\\.taobao\\.com|安全验证|验证码|扫码登录|请登录后/.test(location.href + ' ' + text)) {
    return { error: 'auth-required' };
  }
  if (/error\\.item\\.taobao\\.com|\\/error\\/noitem|宝贝不存在|商品不存在|已下架|已删除/.test(location.href + ' ' + text)) {
    return { error: 'item unavailable or removed' };
  }
  const titleEl = document.querySelector('[class*="mainTitle--"], [class*="ItemTitle--"], h1');
  const titleFromDoc = normalize(document.title.replace(/^【[^】]+】/, '').split(/[-_]/)[0]);
  let title = normalize(titleEl?.innerText || titleEl?.textContent || '');
  if (!title || /用户评价|累计评价|商品详情|店铺/.test(title)) title = titleFromDoc;
  if (!title || title.length < 2 || text.length < 100) {
    return { error: 'detail payload missing title' };
  }
  const priceEl = document.querySelector('[class*="priceText--"], [class*="Price--"], [class*="price--"]');
  const prices = [];
  for (const match of text.matchAll(/[￥¥]\\s*(\\d+(?:\\.\\d{1,2})?)/g)) {
    const price = Number(match[1]);
    if (price > 0.1 && price < 100000) prices.push(price);
    if (prices.length >= 5) break;
  }
  let price = normalize(priceEl?.innerText || priceEl?.textContent || '');
  if (!price || price.length > 30) price = prices.length ? '¥' + Math.min(...prices) : price.slice(0, 60);
  const salesMatch = text.match(/(\\d+(?:\\.\\d+)?万?\\+?)\\s*人付款/) || text.match(/月销\\s*(\\d+(?:\\.\\d+)?万?\\+?)/);
  const reviewMatch = text.match(/累计评价\\s*(\\d+(?:\\.\\d+)?万?\\+?)/) || text.match(/评价[（(]?\\s*(\\d+(?:\\.\\d+)?万?\\+?)/);
  const shopEl = document.querySelector('[class*="shopName--"], [class*="ShopName--"], a[href*="shop"], [class*="seller"] a');
  let shop = normalize(shopEl?.innerText || shopEl?.textContent || '');
  if (!shop) {
    const shopMatch = text.match(/([\\u4e00-\\u9fa5A-Za-z0-9]{2,30}(?:旗舰店|专卖店|企业店|专营店|淘宝店|官方店))/);
    shop = shopMatch ? shopMatch[1] : '';
  }
  if (/免费开店|卖家中心|千牛/.test(shop)) shop = '';
  const locMatch = text.match(/发货地[：:]*\\s*([\\u4e00-\\u9fa5]{2,10})/) || text.match(/([\\u4e00-\\u9fa5]{2,4}(?:省|市))\\s*发货/);
  const sourceUrl = location.href.split('#')[0].split('&spm=')[0];
  return [
    { field: '商品名称', value: title.slice(0, 120) },
    { field: '价格', value: price },
    { field: '销量', value: salesMatch ? salesMatch[0] : '' },
    { field: '评价数', value: reviewMatch ? reviewMatch[1] : '' },
    { field: '店铺', value: shop },
    { field: '发货地', value: locMatch ? locMatch[1] : '' },
    { field: 'ID', value: itemId },
    { field: '链接', value: sourceUrl || ('https://item.taobao.com/item.htm?id=' + itemId) },
  ];
})()
"""


REVIEWS_SCRIPT = """
(async () => {
  const itemId = ITEM_ID_PLACEHOLDER;
  const limit = LIMIT_PLACEHOLDER;
  const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
  const text = document.body?.innerText || '';
  if (/login\\.taobao\\.com|安全验证|验证码|扫码登录|请登录后/.test(location.href + ' ' + text)) {
    return { error: 'auth-required' };
  }
  const html = document.documentElement?.innerHTML || '';
  let sellerId = '';
  const sellerMatch = html.match(/sellerId['"\\s:=]+['"]?(\\d+)/)
    || html.match(/userId['"\\s:=]+['"]?(\\d+)/)
    || html.match(/shopId['"\\s:=]+['"]?(\\d+)/);
  if (sellerMatch) sellerId = sellerMatch[1];
  if (!sellerId) {
    const shopLink = document.querySelector('a[href*="shopId="], a[href*="seller_id="], a[href*="userId="]');
    const href = shopLink?.getAttribute('href') || '';
    const match = href.match(/(?:shopId|seller_id|userId)=(\\d+)/);
    if (match) sellerId = match[1];
  }
  const endpoint = 'https://rate.tmall.com/list_detail_rate.htm?itemId=' + itemId
    + (sellerId ? '&sellerId=' + sellerId : '')
    + '&order=3&currentPage=1&append=0&content=1&tagId=&posi=&picture=&groupValue=&needFold=0&_ksTS=' + Date.now();
  return await new Promise(resolve => {
    const cbName = '__ab_rate_' + Date.now() + '_' + Math.floor(Math.random() * 100000);
    const script = document.createElement('script');
    let settled = false;
    const cleanup = value => {
      if (settled) return;
      settled = true;
      try { delete window[cbName]; } catch {}
      script.remove();
      resolve(value);
    };
    window[cbName] = payload => {
      const list = payload?.rateDetail?.rateList;
      if (!Array.isArray(list)) {
        cleanup({ error: 'reviews payload missing rate list' });
        return;
      }
      cleanup(list.slice(0, limit).map((item, index) => ({
        rank: index + 1,
        user: normalize(item.displayUserNick || item.userNick || '').slice(0, 40),
        content: normalize(item.rateContent || '').slice(0, 300),
        date: String(item.rateDate || '').slice(0, 19),
        spec: normalize(item.auctionSku || '').slice(0, 120),
      })).filter(item => item.content));
    };
    script.onerror = () => cleanup({ error: 'reviews request failed' });
    script.src = endpoint + '&callback=' + cbName;
    document.head.appendChild(script);
    setTimeout(() => cleanup({ error: 'reviews request timed out' }), 12000);
  });
})()
"""


CART_SCRIPT = """
(async () => {
  const limit = LIMIT_PLACEHOLDER;
  const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  for (let i = 0; i < 14; i++) {
    const text = document.body?.innerText || '';
    if (/login\\.taobao\\.com|安全验证|验证码|扫码登录|请登录后/.test(location.href + ' ' + text)) {
      return { auth_required: true };
    }
    if (text.length > 500 || /购物车空空|还没有添加|全部商品|结算/.test(text)) break;
    await sleep(500);
  }
  for (let i = 0; i < 3; i++) {
    window.scrollBy(0, Math.max(700, window.innerHeight * 0.85));
    await sleep(1500);
  }
  const text = document.body?.innerText || '';
  if (/login\\.taobao\\.com|安全验证|验证码|扫码登录|请登录后/.test(location.href + ' ' + text)) {
    return { auth_required: true };
  }
  const emptyCart = /购物车空空|还没有添加|空空如也/.test(text);
  const roots = new Set();
  for (const node of document.querySelectorAll('[class*="item"], [class*="cart"], [data-id], [data-itemid]')) {
    const body = normalize(node.innerText || node.textContent);
    if (body.length > 30 && /[￥¥]\\s*\\d/.test(body)) roots.add(node);
  }
  const items = [];
  const seen = new Set();
  const blockedTitle = /^(删除|全选|全部商品|合计|结算|找相似|移入收藏|优惠|券|店铺|宝贝|数量|单价|小计|已选)/;
  for (const root of roots) {
    const lines = (root.innerText || root.textContent || '').split('\\n').map(normalize).filter(Boolean);
    if (lines.length < 2) continue;
    const priceLine = lines.find(line => /[￥¥]\\s*\\d/.test(line)) || '';
    if (!priceLine) continue;
    let title = '';
    for (const line of lines) {
      if (line.length > title.length && line.length >= 8 && line.length < 180 && !/[￥¥]\\s*\\d/.test(line) && !blockedTitle.test(line)) {
        title = line;
      }
    }
    if (!title || seen.has(title)) continue;
    const spec = lines.find(line => /^(颜色分类|尺码|规格|套餐|型号|版本|配置)[：:]/.test(line)) || '';
    let shop = '';
    const shopLine = lines.find(line => line.length >= 2 && line.length <= 40 && /店|旗舰|官方|专营|专卖/.test(line) && !blockedTitle.test(line));
    if (shopLine && shopLine !== title) shop = shopLine;
    const priceMatch = priceLine.match(/[￥¥]\\s*([\\d,.]+(?:\\.\\d{1,2})?)/);
    seen.add(title);
    items.push({
      index: items.length + 1,
      title: title.slice(0, 120),
      price: priceMatch ? '¥' + priceMatch[1] : priceLine.slice(0, 40),
      spec: spec.slice(0, 120),
      shop: shop.slice(0, 80),
    });
    if (items.length >= limit) break;
  }
  if (items.length > 0) return { items, loaded: true };
  const sections = text.split(/移入收藏/);
  for (const section of sections) {
    const lines = section.split('\\n').map(normalize).filter(Boolean);
    if (lines.length < 3) continue;
    let title = '';
    let titleIndex = -1;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.length > title.length && line.length >= 8 && line.length < 180 && !/[￥¥]/.test(line) && !blockedTitle.test(line)) {
        title = line;
        titleIndex = i;
      }
    }
    if (!title || seen.has(title)) continue;
    let price = '';
    for (let i = 0; i < lines.length; i++) {
      if (lines[i] !== '￥' && lines[i] !== '¥') continue;
      let rawPrice = '';
      for (let j = i + 1; j < Math.min(i + 5, lines.length); j++) {
        if (/^[\\d,.]+$/.test(lines[j])) rawPrice += lines[j];
        else if (lines[j] === '.') rawPrice += '.';
        else break;
      }
      if (rawPrice) {
        price = '¥' + rawPrice;
        break;
      }
    }
    if (!price) continue;
    let shop = '';
    if (titleIndex > 0) {
      const previous = lines[titleIndex - 1];
      if (previous && previous.length >= 2 && previous.length <= 40 && !blockedTitle.test(previous) && !/[￥¥]/.test(previous)) {
        shop = previous;
      }
    }
    const spec = lines.find(line => /^(颜色分类|尺码|规格|套餐|型号|版本|配置|适用)[：:]/.test(line)) || '';
    seen.add(title);
    items.push({
      index: items.length + 1,
      title: title.slice(0, 120),
      price,
      spec: spec.slice(0, 120),
      shop: shop.slice(0, 80),
    });
    if (items.length >= limit) break;
  }
  if (items.length > 0) return { items, loaded: true };
  return { items: [], loaded: emptyCart };
})()
"""


WHOAMI_SCRIPT = """
(() => {
  const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
  const text = document.body?.innerText || '';
  if (/login\\.taobao\\.com|安全验证|验证码|扫码登录|请登录后/.test(location.href + ' ' + text)) {
    return { auth_required: true };
  }
  const firstText = selectors => {
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      const value = normalize(node?.innerText || node?.textContent || node?.getAttribute('content') || '');
      if (value) return value;
    }
    return '';
  };
  const html = document.body?.innerHTML || '';
  const idMatch = html.match(/userId['"\\s:=]+['"]?(\\d+)/i)
    || html.match(/user_id['"\\s:=]+['"]?(\\d+)/i)
    || html.match(/uid['"\\s:=]+['"]?(\\d+)/i);
  const nickname = firstText(['.user-nick', '.site-nav-user', '.user-name', '[class*="nick"]', '[class*="Nick"]']);
  const userId = idMatch ? idMatch[1] : '';
  if (!nickname && !userId) return { auth_required: true };
  return {
    logged_in: true,
    nickname,
    user_id: userId,
    source_url: location.href,
  };
})()
"""


def navigate_from_home(args: argparse.Namespace, target_url: str, settle_seconds: float) -> ActionBook:
    book = attach_workflow(args, TAOBAO_HOME_URL, ActionBook)
    time.sleep(HOME_WARMUP_SECONDS)
    evaluate(book, f"location.href = {json.dumps(target_url)}; true", "打开淘宝页面失败")
    time.sleep(settle_seconds)
    return book


def run_search(args: argparse.Namespace) -> int:
    query = normalize_text(args.query)
    if not query:
        raise RuntimeError("taobao search: query is required")
    count = read_count(args.count, default=10, max_value=40)
    sort_map = {"default": "", "sale": "&sort=sale-desc", "price": "&sort=price-asc"}
    sort_param = sort_map.get(str(args.sort or "default"), "")
    url = f"{TAOBAO_SEARCH_URL}?q={quote(query)}{sort_param}"
    book = navigate_from_home(args, url, SEARCH_SETTLE_SECONDS)
    ensure_ready(book)
    records = require_list_payload(
        evaluate(book, SEARCH_SCRIPT.replace("LIMIT_PLACEHOLDER", str(count)), "读取淘宝搜索结果失败", timeout=60.0),
        "taobao search",
    )
    return finish(records[:count], args, "search", f"淘宝搜索: {query}")


def run_detail(args: argparse.Namespace) -> int:
    item_id = normalize_numeric_id(args.id, "--id", "827563850178")
    url = f"https://item.taobao.com/item.htm?id={item_id}"
    book = navigate_from_home(args, url, PAGE_SETTLE_SECONDS)
    ensure_ready(book)
    records = require_list_payload(
        evaluate(book, DETAIL_SCRIPT.replace("ITEM_ID_PLACEHOLDER", json.dumps(item_id)), "读取淘宝商品详情失败"),
        "taobao detail",
    )
    return finish(records, args, "detail", f"淘宝商品详情: {item_id}")


def run_reviews(args: argparse.Namespace) -> int:
    item_id = normalize_numeric_id(args.id, "--id", "827563850178")
    count = read_count(args.count, default=10, max_value=20)
    url = f"https://item.taobao.com/item.htm?id={item_id}"
    book = navigate_from_home(args, url, PAGE_SETTLE_SECONDS)
    ensure_ready(book)
    records = require_list_payload(
        evaluate(
            book,
            REVIEWS_SCRIPT.replace("ITEM_ID_PLACEHOLDER", json.dumps(item_id)).replace("LIMIT_PLACEHOLDER", str(count)),
            "读取淘宝商品评价失败",
            timeout=60.0,
        ),
        "taobao reviews",
    )
    return finish(records[:count], args, "reviews", f"淘宝商品评价: {item_id}")


def run_cart(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=50)
    book = navigate_from_home(args, "https://cart.taobao.com/cart.htm", PAGE_SETTLE_SECONDS)
    ensure_ready(book)
    data = evaluate(book, CART_SCRIPT.replace("LIMIT_PLACEHOLDER", str(count)), "读取淘宝购物车失败", timeout=60.0)
    if isinstance(data, dict) and data.get("auth_required"):
        raise LoginRequiredError(
            "LOGIN_REQUIRED: 淘宝购物车需要已登录会话；请在 ActionBook 连接的 Chrome 窗口登录后重试。"
        )
    records = require_cart_payload(data, "taobao cart")
    return finish(records[:count], args, "cart", "淘宝购物车")


def run_whoami(args: argparse.Namespace) -> int:
    book = navigate_from_home(args, "https://i.taobao.com/my_itaobao", WHOAMI_SETTLE_SECONDS)
    ensure_ready(book)
    record = require_dict_payload(evaluate(book, WHOAMI_SCRIPT, "读取淘宝当前账号失败"), "taobao whoami")
    if record.get("auth_required"):
        raise LoginRequiredError(
            "LOGIN_REQUIRED: 未检测到淘宝登录态；请在 ActionBook 连接的 Chrome 窗口登录后重试。"
        )
    record["logged_in"] = True
    record["source_url"] = record.get("source_url") or "https://i.taobao.com/my_itaobao"
    return finish([record], args, "whoami", "淘宝当前账号")


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
