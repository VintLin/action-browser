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


def run_search(args: argparse.Namespace) -> int:
    return finish([], args, "search", f"京东搜索: {args.query}")


def run_item(args: argparse.Namespace) -> int:
    sku = normalize_numeric_id(args.sku, "--sku", "100291143898")
    return finish([{"sku": sku, "source_url": f"https://item.jd.com/{sku}.html"}], args, "item", f"京东商品: {sku}")


def run_detail(args: argparse.Namespace) -> int:
    sku = normalize_numeric_id(args.sku, "--sku", "100291143898")
    return finish([{"field": "SKU", "value": sku}], args, "detail", f"京东商品详情: {sku}")


def run_reviews(args: argparse.Namespace) -> int:
    sku = normalize_numeric_id(args.sku, "--sku", "100291143898")
    return finish([], args, "reviews", f"京东商品评价: {sku}")


def run_cart(args: argparse.Namespace) -> int:
    return finish([], args, "cart", "京东购物车")


def run_whoami(args: argparse.Namespace) -> int:
    records = [{"logged_in": False, "nickname": "", "user_id": "", "source_url": JD_HOME_URL}]
    return finish(records, args, "whoami", "京东当前账号")


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
