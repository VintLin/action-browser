#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only Xianyu ActionBook workflow.

Reference behavior: OpenCLI Xianyu adapter (Apache-2.0), reimplemented for
action-browser's owned-tab lifecycle and file-based result contract. This
module intentionally does not implement chat/reply/publish writes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[2]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from scripts.actionbook_interrupts import install_interrupt_handlers
from scripts.actionbook_session import ActionBookSession as ActionBook
from scripts.owned_tab_lifecycle import add_workflow_args, attach_workflow
from scripts.script_common import log
from scripts.workflow_runtime import evaluate, wait_until_stable, write_json


Xianyu_HOME_URL = "https://www.goofish.com"
Xianyu_SEARCH_URL = f"{Xianyu_HOME_URL}/search"
Xianyu_IM_URL = f"{Xianyu_HOME_URL}/im"
MAX_SEARCH_COUNT = 60
MAX_INBOX_COUNT = 100
MAX_MESSAGE_COUNT = 200
SKILL_DIR = Path(__file__).resolve().parents[2]
ASSETS_DIR = SKILL_DIR / "assets" / "xianyu"


class LoginRequiredError(RuntimeError):
    """The attached browser session needs login or manual risk-control work."""


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def read_count(value: Any, default: int, maximum: int) -> int:
    raw = normalize_text(value)
    if not raw:
        return default
    if not re.fullmatch(r"\d+", raw):
        raise argparse.ArgumentTypeError(f"count must be an integer from 1 to {maximum}")
    number = int(raw)
    if number < 1 or number > maximum:
        raise argparse.ArgumentTypeError(f"count must be an integer from 1 to {maximum}")
    return number


def parse_price(value: Any, label: str) -> float | None:
    raw = normalize_text(value)
    if not raw:
        return None
    try:
        number = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label} must be a non-negative number") from exc
    if number < 0:
        raise argparse.ArgumentTypeError(f"{label} must be a non-negative number")
    return number


def normalize_numeric_id(value: Any, label: str = "item id") -> str:
    raw = normalize_text(value)
    match = re.search(r"[?&](?:id|itemId|item_id)=(\d+)", raw)
    if match:
        return match.group(1)
    if re.fullmatch(r"\d+", raw):
        return raw
    raise argparse.ArgumentTypeError(f"{label} must be numeric, for example 1040754408976")


def build_search_filter(min_price: float | None, max_price: float | None) -> str:
    if min_price is None and max_price is None:
        return ""
    low = 0 if min_price is None else min_price
    high = 99999999 if max_price is None else max_price
    format_price = lambda value: str(int(value)) if float(value).is_integer() else format(value, "g")
    return f"priceRange:{format_price(low)},{format_price(high)};"


def build_extra_filter_value(province: str, city: str) -> str:
    if not province and not city:
        return "{}"
    return json.dumps(
        {
            "divisionList": [{"province": province, "city": city}],
            "excludeMultiPlacesSellers": "0",
            "extraDivision": "",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def build_item_url(item_id: str) -> str:
    return f"{Xianyu_HOME_URL}/item?id={quote(item_id)}"


def build_chat_url(item_id: str, peer_user_id: str) -> str:
    return f"{Xianyu_IM_URL}?itemId={quote(item_id)}&peerUserId={quote(peer_user_id)}"


def page_state(book: ActionBook) -> dict[str, str]:
    value = evaluate(
        book,
        """
        (() => ({
          href: location.href || '',
          title: document.title || '',
          text: (document.body?.innerText || '').slice(0, 1600)
        }))()
        """,
        "读取闲鱼页面状态失败",
    )
    if not isinstance(value, dict):
        return {}
    return {key: normalize_text(value.get(key)) for key in ("href", "title", "text")}


def page_has_login_or_risk(state: dict[str, str]) -> bool:
    haystack = " ".join(str(state.get(key) or "") for key in ("href", "title", "text"))
    return re.search(
        r"passport\.(?:taobao|goofish)\.com|/login|请先登录|登录后|扫码登录|验证码|安全验证|异常访问|访问频繁|风险控制",
        haystack,
        re.I,
    ) is not None


def ensure_ready(book: ActionBook) -> None:
    state = page_state(book)
    if page_has_login_or_risk(state):
        raise LoginRequiredError(
            "LOGIN_REQUIRED: 闲鱼需要登录或人工处理验证码/风控；请在当前 Chrome 窗口完成后重试。"
        )


def navigate(book: ActionBook, url: str, settle_seconds: float = 2.0) -> None:
    evaluate(book, f"location.href = {json.dumps(url)}; true", "打开闲鱼页面失败")
    wait_until_stable(book, timeout_secs=max(3.0, settle_seconds + 1.0))
    # OpenCLI's reference adapter gives Goofish's SPA a short post-navigation
    # window; the explicit state checks below remain the success criterion.
    time.sleep(settle_seconds)


def js_search(keyword: str, search_filter: str, extra_filter_value: str, limit: int) -> str:
    return f"""
    (async () => {{
      const clean = (value) => String(value ?? '').replace(/\\s+/g, ' ').trim();
      const cleanFirst = (...values) => values.map(clean).find(Boolean) || '';
      const cleanTags = (value) => (Array.isArray(value) ? value : [])
        .map((entry) => cleanFirst(entry?.text, entry?.title, entry?.name, entry?.label, entry?.content))
        .filter(Boolean).join(' | ');
      const retCode = (ret) => clean(Array.isArray(ret) ? ret[0] : '').split('::')[0] || '';
      const waitFor = async (predicate, timeoutMs = 6000) => {{
        const start = Date.now();
        while (Date.now() - start < timeoutMs) {{
          if (predicate()) return true;
          await new Promise((resolve) => setTimeout(resolve, 150));
        }}
        return false;
      }};
      const text = document.body?.innerText || '';
      if (/请先登录|扫码登录|登录后/.test(text)) return {{ status: 'auth_required' }};
      if (/验证码|安全验证|异常访问|访问频繁/.test(text)) return {{ status: 'blocked' }};
      await waitFor(() => window.lib?.mtop?.request);
      if (typeof window.lib?.mtop?.request !== 'function') return {{ status: 'mtop_not_ready' }};

      const filter = {json.dumps(search_filter, ensure_ascii=False)};
      const extraFilterValue = {json.dumps(extra_filter_value, ensure_ascii=False)};
      const result = [];
      const rowsPerPage = 30;
      const maxPages = Math.ceil({limit} / rowsPerPage);
      for (let page = 1; page <= maxPages && result.length < {limit}; page++) {{
        let response;
        try {{
          response = await window.lib.mtop.request({{
            api: 'mtop.taobao.idlemtopsearch.pc.search',
            data: {{
              pageNumber: page,
              keyword: {json.dumps(keyword, ensure_ascii=False)},
              fromFilter: Boolean(filter) || extraFilterValue !== '{{}}',
              rowsPerPage,
              sortValue: '', sortField: '', customDistance: '', gps: '',
              propValueStr: filter ? {{ searchFilter: filter }} : {{}},
              customGps: '', searchReqFromPage: 'pcSearch',
              extraFilterValue, userPositionJson: '{{}}'
            }},
            type: 'POST', v: '1.0', dataType: 'json',
            needLogin: false, needLoginPC: false, sessionOption: 'AutoLoginOnly', ecode: 0
          }});
        }} catch (error) {{
          const ret = error?.ret || [];
          return {{ status: 'request_error', code: retCode(ret), message: clean(ret.join(' | ') || error?.message || error) }};
        }}
        const code = retCode(response?.ret || []);
        if (code && code !== 'SUCCESS') return {{ status: 'response_error', code, message: clean((response?.ret || []).join(' | ')) }};
        if (!Array.isArray(response?.data?.resultList)) return {{ status: 'malformed' }};
        const list = response.data.resultList;
        if (!list.length) break;
        let valid = 0;
        for (const entry of list) {{
          const item = entry?.data?.item || {{}};
          const main = item.main || {{}};
          const args = main.clickParam?.args || {{}};
          const ex = main.exContent || item.exContent || {{}};
          const itemId = clean(args.item_id || args.id || '');
          const title = clean(ex.title || ex.detailParams?.title || '');
          if (!itemId || !title) continue;
          result.push({{
            item_id: itemId,
            title,
            price: clean(args.price || args.displayPrice || '') ? '¥' + clean(args.price || args.displayPrice) : '',
            condition: cleanFirst(ex.condition, ex.stuffStatus, ex.detailParams?.condition),
            brand: cleanFirst(ex.brand, ex.brandName, ex.detailParams?.brand),
            location: clean(args.p_city || ex.area || ''),
            badge: cleanFirst(ex.badge, ex.creditText, ex.creditLevel, cleanTags(ex.fishTags || ex.labels || ex.tags)),
            want: clean(args.wantNum || ex.want || ''),
            url: 'https://www.goofish.com/item?id=' + itemId
          }});
          valid++;
          if (result.length >= {limit}) break;
        }}
        if (!valid && list.length) return {{ status: 'malformed_rows' }};
        if (list.length < rowsPerPage) break;
      }}
      return {{ status: 'ok', items: result }};
    }})()
    """


def js_item(item_id: str) -> str:
    return f"""
    (async () => {{
      const clean = (value) => String(value ?? '').replace(/\\s+/g, ' ').trim();
      const retCode = (ret) => clean(Array.isArray(ret) ? ret[0] : '').split('::')[0] || '';
      const waitFor = async (predicate, timeoutMs = 5000) => {{
        const start = Date.now();
        while (Date.now() - start < timeoutMs) {{
          if (predicate()) return true;
          await new Promise((resolve) => setTimeout(resolve, 150));
        }}
        return false;
      }};
      const text = document.body?.innerText || '';
      if (/请先登录|登录后/.test(text)) return {{ status: 'auth_required' }};
      if (/验证码|安全验证|异常访问|访问频繁/.test(text)) return {{ status: 'blocked' }};
      await waitFor(() => window.lib?.mtop?.request);
      if (typeof window.lib?.mtop?.request !== 'function') return {{ status: 'mtop_not_ready' }};
      let response;
      try {{
        response = await window.lib.mtop.request({{
          api: 'mtop.taobao.idle.pc.detail',
          data: {{ itemId: {json.dumps(item_id)} }},
          type: 'POST', v: '1.0', dataType: 'json',
          needLogin: false, needLoginPC: false, sessionOption: 'AutoLoginOnly', ecode: 0
        }});
      }} catch (error) {{
        const ret = error?.ret || [];
        return {{ status: 'request_error', code: retCode(ret), message: clean(ret.join(' | ') || error?.message || error) }};
      }}
      const code = retCode(response?.ret || []);
      if (code && code !== 'SUCCESS') return {{ status: 'response_error', code, message: clean((response?.ret || []).join(' | ')) }};
      const data = response?.data || {{}};
      const item = data.itemDO || {{}};
      const seller = data.sellerDO || {{}};
      const labels = Array.isArray(item.itemLabelExtList) ? item.itemLabelExtList : [];
      const label = (name) => clean(labels.find((entry) => clean(entry.propertyText) === name)?.text || '');
      const images = Array.isArray(item.imageInfos) ? item.imageInfos.map((entry) => entry?.url).filter(Boolean) : [];
      return {{ status: 'ok', item: {{
        item_id: clean(item.itemId || {json.dumps(item_id)}),
        title: clean(item.title), description: clean(item.desc),
        price: clean(item.soldPrice || item.defaultPrice) ? '¥' + clean(item.soldPrice || item.defaultPrice) : '',
        original_price: clean(item.originalPrice), want_count: String(item.wantCnt ?? ''),
        collect_count: String(item.collectCnt ?? ''), browse_count: String(item.browseCnt ?? ''),
        status: clean(item.itemStatusStr), condition: label('成色'), brand: label('品牌'), category: label('分类'),
        location: clean(seller.publishCity || seller.city), seller_name: clean(seller.nick || seller.uniqueName),
        seller_id: String(seller.sellerId || ''), seller_score: clean(seller.xianyuSummary),
        reply_ratio_24h: clean(seller.replyRatio24h), reply_interval: clean(seller.replyInterval),
        item_url: {json.dumps(build_item_url(item_id))},
        seller_url: seller.sellerId ? 'https://www.goofish.com/personal?userId=' + seller.sellerId : '',
        image_count: images.length, image_urls: images
      }} }};
    }})()
    """


INBOX_SCRIPT = r"""
(() => {
  const clean = (value) => String(value ?? '').replace(/\s+/g, ' ').trim();
  const absolute = (value) => { try { return new URL(value, location.href).href; } catch { return ''; } };
  const readId = (url, key) => { try { return new URL(url, location.href).searchParams.get(key) || ''; } catch { return ''; } };
  const pick = (root, selectors) => {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      const text = clean(node?.getAttribute?.('title') || node?.textContent || '');
      if (text) return text;
    }
    return '';
  };
  const body = document.body?.innerText || '';
  const requiresAuth = /请先登录|登录后|扫码登录/.test(body);
  const blocked = /验证码|安全验证|异常访问|访问频繁/.test(body);
  const items = [];
  const seen = new Set();
  for (const link of Array.from(document.querySelectorAll('a[href*="itemId="][href*="peerUserId="]'))) {
    const href = link.href || link.getAttribute('href') || '';
    const itemId = readId(href, 'itemId');
    const peerUserId = readId(href, 'peerUserId');
    const key = itemId + ':' + peerUserId;
    if (!itemId || !peerUserId || seen.has(key)) continue;
    seen.add(key);
    const root = link.closest('[class*="conversation"], [class*="session"], [class*="contact"], li, [role="listitem"]') || link;
    const unreadText = pick(root, ['[class*="badge"]', '[class*="unread"]', '[class*="red"]']);
    const unreadCount = Number.parseInt(unreadText.replace(/\D/g, ''), 10) || (unreadText ? 1 : 0);
    items.push({
      row_index: items.length,
      peer_name: pick(root, ['[class*="name"]', '[class*="nick"]', '[class*="user"]', '[class*="text1"]']),
      peer_user_id: peerUserId, item_id: itemId,
      item_title: pick(root, ['[class*="title"]', '[class*="item"] [class*="desc"]', '[class*="desc"]']),
      price: pick(root, ['[class*="money"]', '[class*="price"]']),
      last_message: pick(root, ['[class*="message"]', '[class*="msg"]', '[class*="content"]', '[class*="summary"]']) || clean(root.textContent),
      unread: unreadCount > 0 || /unread|未读/.test(String(root.className || '')),
      unread_count: unreadCount, url: absolute(href)
    });
  }
  if (!items.length) {
    for (const row of Array.from(document.querySelectorAll('#conv-list-scrollable [class*="conversation-item"]'))) {
      const texts = Array.from(row.querySelectorAll('div, span'))
        .filter((node) => !Array.from(node.children || []).some((child) => ['DIV', 'SPAN'].includes(child.tagName)))
        .map((node) => clean(node.textContent)).filter(Boolean);
      const unreadTitle = clean(row.querySelector('sup')?.getAttribute('title') || '');
      const unreadCount = Number.parseInt(unreadTitle.replace(/\D/g, ''), 10) || (unreadTitle ? 1 : 0);
      const peerName = texts.find((text) => text !== unreadTitle) || '';
      const lastMessage = texts.find((text) => text !== peerName && text !== unreadTitle) || '';
      if (peerName || lastMessage) items.push({ row_index: items.length, peer_name: peerName, peer_user_id: '', item_id: '', item_title: '', price: '', last_message: lastMessage, unread: unreadCount > 0, unread_count: unreadCount, url: '' });
    }
  }
  return { status: 'ok', requiresAuth, blocked, items: items.slice(0, LIMIT_PLACEHOLDER) };
})()
""";


MESSAGES_SCRIPT = r"""
(() => {
  const clean = (value) => String(value ?? '').replace(/\s+/g, ' ').trim();
  const body = document.body?.innerText || '';
  const requiresAuth = /请先登录|登录后|扫码登录/.test(body);
  const root = document.querySelector('#message-list-scrollable') || document.querySelector('[class*="message-list"]') || document;
  let messages = Array.from(root.querySelectorAll('[class*="message-row"]'))
    .map((row) => clean(row.querySelector('[class*="message-text"]')?.textContent || row.textContent)).filter(Boolean);
  if (!messages.length) messages = Array.from(root.querySelectorAll('[class*="message"], [class*="msg"], [class*="bubble"]')).map((node) => clean(node.textContent)).filter(Boolean);
  messages = messages.filter((text) => !['发送', '闲鱼号', '立即购买'].includes(text)).filter((text) => !/^消息\d*\+?$/.test(text)).slice(-LIMIT_PLACEHOLDER);
  const params = new URL(location.href).searchParams;
  const topbar = document.querySelector('[class*="message-topbar"]');
  const item = document.querySelector('a[href*="/item?id="]');
  return { status: 'ok', requiresAuth, peer_name: clean(topbar?.querySelector('[class*="text1"]')?.textContent), peer_masked_id: clean(topbar?.querySelector('[class*="text2"]')?.textContent).replace(/^\(|\)$/g, ''), item_title: clean(item?.querySelector('[class*="title"]')?.textContent), item_url: item?.href || '', item_id: params.get('itemId') || '', peer_user_id: params.get('peerUserId') || '', messages: messages.map((text, index) => ({ index: index + 1, text })) };
})()
""";


def require_status(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{label}: malformed browser payload")
    status = str(value.get("status") or "")
    if status == "auth_required":
        raise LoginRequiredError("LOGIN_REQUIRED: 闲鱼登录态已失效，请在当前 Chrome 窗口登录后重试。")
    if status in {"blocked", "request_error", "response_error"}:
        code = value.get("code") or ""
        if re.search(r"SESSION_EXPIRED|TOKEN|AUTH|LOGIN", f"{code} {value.get('message', '')}", re.I):
            raise LoginRequiredError("LOGIN_REQUIRED: 闲鱼会话已失效，请在当前 Chrome 窗口重新登录后重试。")
        raise RuntimeError(f"{label}: {value.get('message') or status}")
    if status in {"mtop_not_ready", "malformed", "malformed_rows"}:
        raise RuntimeError(f"{label}: page returned {status}")
    return value


def default_output_dir(area: str) -> Path:
    return ASSETS_DIR / "views" / area / datetime.now().strftime("%Y%m%d-%H%M%S")


def write_records(records: list[dict[str, Any]], output_dir: Path, title: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", records)
    lines = [f"# {title}", "", f"- 条目数: {len(records)}", ""]
    for index, item in enumerate(records, start=1):
        heading = item.get("title") or item.get("peer_name") or item.get("text") or item.get("item_id") or str(index)
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


def finish(records: list[dict[str, Any]], args: argparse.Namespace, area: str, title: str, requested_count: int) -> int:
    output_dir = Path(args.output) if args.output else default_output_dir(area)
    write_records(records, output_dir, title)
    contract = output_dir / "contract"
    write_json(contract / "artifacts" / "results.json", records)
    write_json(contract / "summary.json", {"schema_version": 1, "task_id": str(args.task_id or ""), "ok": True, "site": "xianyu", "intent": area, "requested_count": requested_count, "collected_count": len(records), "artifacts": ["contract/artifacts/results.json"], "warnings": [], "needs_user_action": False, "followups": []})
    write_json(contract / "progress.json", {"schema_version": 1, "task_id": str(args.task_id or ""), "status": "completed", "stage": "writing_results", "completed_items": len(records), "requested_items": requested_count})
    log(f"已写入: {output_dir} 条目数={len(records)}")
    return 0


def base_view_parser(area: argparse.ArgumentParser, handler: Any, count: int) -> argparse.ArgumentParser:
    modes = area.add_subparsers(dest="mode", required=True)
    view = modes.add_parser("view")
    add_workflow_args(view)
    view.add_argument("--output", default="")
    view.add_argument("--count", default=str(count))
    view.set_defaults(func=handler)
    return view


def run_search(args: argparse.Namespace) -> int:
    query = normalize_text(args.query)
    if not query:
        raise argparse.ArgumentTypeError("query cannot be empty")
    count = read_count(args.count, 20, MAX_SEARCH_COUNT)
    min_price = parse_price(args.min_price, "min-price")
    max_price = parse_price(args.max_price, "max-price")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise argparse.ArgumentTypeError("min-price cannot be greater than max-price")
    book = attach_workflow(args, Xianyu_HOME_URL, ActionBook)
    navigate(book, f"{Xianyu_SEARCH_URL}?q={quote(query)}")
    ensure_ready(book)
    result = require_status(evaluate(book, js_search(query, build_search_filter(min_price, max_price), build_extra_filter_value(normalize_text(args.province), normalize_text(args.city)), count), "读取闲鱼搜索结果失败", timeout=60.0), "xianyu search")
    records = [{"rank": index, **item} for index, item in enumerate(result.get("items") or [], start=1)]
    return finish(records, args, "search", f"闲鱼搜索: {query}", count)


def run_item(args: argparse.Namespace) -> int:
    item_id = normalize_numeric_id(args.id)
    book = attach_workflow(args, Xianyu_HOME_URL, ActionBook)
    navigate(book, build_item_url(item_id))
    ensure_ready(book)
    result = require_status(evaluate(book, js_item(item_id), "读取闲鱼商品详情失败", timeout=60.0), "xianyu item")
    item = result.get("item")
    if not isinstance(item, dict) or not normalize_text(item.get("title")):
        raise RuntimeError("xianyu item: no item detail was returned")
    return finish([item], args, "item", f"闲鱼商品详情: {item_id}", 1)


def run_inbox(args: argparse.Namespace) -> int:
    count = read_count(args.count, 20, MAX_INBOX_COUNT)
    book = attach_workflow(args, Xianyu_IM_URL, ActionBook)
    navigate(book, Xianyu_IM_URL)
    ensure_ready(book)
    script = INBOX_SCRIPT.replace("LIMIT_PLACEHOLDER", str(count))
    result = require_status(evaluate(book, script, "读取闲鱼私信收件箱失败"), "xianyu inbox")
    if result.get("requiresAuth") or result.get("blocked"):
        raise LoginRequiredError("LOGIN_REQUIRED: 闲鱼私信页需要登录或人工处理风控。")
    records = result.get("items") if isinstance(result.get("items"), list) else []
    if args.unread_only:
        records = [item for item in records if item.get("unread")]
    records = [{"rank": index, **item} for index, item in enumerate(records[:count], start=1)]
    return finish(records, args, "inbox", "闲鱼私信收件箱", count)


def run_messages(args: argparse.Namespace) -> int:
    count = read_count(args.count, 50, MAX_MESSAGE_COUNT)
    if bool(args.item_id) != bool(args.user_id):
        raise argparse.ArgumentTypeError("item-id and user-id must be supplied together")
    if not args.item_id and not args.rank:
        raise argparse.ArgumentTypeError("provide item-id/user-id or --rank from inbox")
    book = attach_workflow(args, Xianyu_IM_URL, ActionBook)
    if args.rank:
        rank = read_count(args.rank, 1, MAX_INBOX_COUNT)
        navigate(book, Xianyu_IM_URL)
        ensure_ready(book)
        target = evaluate(book, f"""
        (() => {{
          const rows = Array.from(document.querySelectorAll('a[href*=\"itemId=\"][href*=\"peerUserId=\"], #conv-list-scrollable [class*=\"conversation-item\"]));
          const row = rows[{rank - 1}];
          if (!row) return {{ status: 'missing' }};
          row.click(); return {{ status: 'clicked' }};
        }})()
        """, "打开闲鱼指定会话失败")
        if not isinstance(target, dict) or target.get("status") != "clicked":
            raise RuntimeError("xianyu messages: inbox rank was not found")
        wait_until_stable(book, timeout_secs=5.0)
        current = evaluate(book, "location.href", "读取闲鱼会话地址失败")
        if not isinstance(current, str) or "itemId=" not in current or "peerUserId=" not in current:
            raise RuntimeError("xianyu messages: selected inbox row did not expose item/user ids")
    else:
        item_id = normalize_numeric_id(args.item_id, "item-id")
        user_id = normalize_numeric_id(args.user_id, "user-id")
        navigate(book, build_chat_url(item_id, user_id))
    ensure_ready(book)
    result = require_status(evaluate(book, MESSAGES_SCRIPT.replace("LIMIT_PLACEHOLDER", str(count)), "读取闲鱼私信消息失败"), "xianyu messages")
    if result.get("requiresAuth"):
        raise LoginRequiredError("LOGIN_REQUIRED: 闲鱼私信页需要登录。")
    messages = result.get("messages") if isinstance(result.get("messages"), list) else []
    records = [{"index": item.get("index"), "text": item.get("text"), "peer_name": result.get("peer_name"), "item_id": result.get("item_id"), "peer_user_id": result.get("peer_user_id"), "item_title": result.get("item_title"), "url": build_chat_url(result.get("item_id"), result.get("peer_user_id")) if result.get("item_id") and result.get("peer_user_id") else ""} for item in messages]
    return finish(records, args, "messages", "闲鱼私信消息", count)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Xianyu workflow helper")
    areas = parser.add_subparsers(dest="area", required=True)
    search = areas.add_parser("search", help="search Xianyu items")
    search_view = base_view_parser(search, run_search, 20)
    search_view.add_argument("--query", required=True)
    search_view.add_argument("--min-price", default="")
    search_view.add_argument("--max-price", default="")
    search_view.add_argument("--province", default="")
    search_view.add_argument("--city", default="")
    item = areas.add_parser("item", help="view one Xianyu item")
    item_view = base_view_parser(item, run_item, 1)
    item_view.add_argument("--id", required=True)
    inbox = areas.add_parser("inbox", help="view Xianyu message inbox")
    inbox_view = base_view_parser(inbox, run_inbox, 20)
    inbox_view.add_argument("--unread-only", action="store_true")
    messages = areas.add_parser("messages", help="view visible messages in one Xianyu conversation")
    messages_view = base_view_parser(messages, run_messages, 50)
    messages_view.add_argument("--item-id", default="")
    messages_view.add_argument("--user-id", default="")
    messages_view.add_argument("--rank", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    install_interrupt_handlers()
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except LoginRequiredError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
