# JD and Taobao ActionBook Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add read-only JD.com and Taobao workflows to the action-browser skill using ActionBook extension mode.

**Architecture:** Add two independent site modules, `scripts/jd_workflow.py` and `scripts/taobao_workflow.py`, each using `ActionBookSession` for Chrome extension-mode browser control. Keep `SKILL.md` site-neutral and place site-specific command catalogs, output schemas, login notes, and risk boundaries in `references/jd.md` and `references/taobao.md`.

**Tech Stack:** Python 3.10+, stdlib `argparse` / `json` / `pathlib` / `unittest`, ActionBook CLI through `scripts/actionbook_session.py`, Chrome extension mode.

---

## File Structure

- Create: `tests/test_jd_taobao_workflows.py`
  - Contract tests for script existence, parser shape, helper behavior, output writing, and disabled write operations.
- Create: `scripts/jd_workflow.py`
  - JD read-only ActionBook workflow: `search view`, `item view`, `detail view`, `reviews view`, `cart view`, `whoami view`.
- Create: `scripts/taobao_workflow.py`
  - Taobao read-only ActionBook workflow: `search view`, `detail view`, `reviews view`, `cart view`, `whoami view`.
- Create: `references/jd.md`
  - JD support range, commands, output contract, login/risk handling, disabled capabilities, validation.
- Create: `references/taobao.md`
  - Taobao support range, commands, output contract, login/risk handling, disabled capabilities, validation.
- Modify: `SKILL.md`
  - Add JD and Taobao to the References table only.
- Modify: `README.md`
  - Add JD and Taobao to Included Workflows only.

Do not create a generic ecommerce abstraction in the first version. Small duplicated helpers inside the two scripts are acceptable.

### Task 1: Add Workflow Contract Tests

**Files:**
- Create: `tests/test_jd_taobao_workflows.py`
- Test: `tests/test_jd_taobao_workflows.py`

- [ ] **Step 1: Write the failing contract tests**

Create `tests/test_jd_taobao_workflows.py`:

```python
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load_script(name: str):
    sys.path.insert(0, str(SCRIPTS))
    try:
        path = SCRIPTS / f"{name}_workflow.py"
        spec = importlib.util.spec_from_file_location(f"{name}_workflow", path)
        if spec is None or spec.loader is None:
            raise AssertionError(f"failed to load spec for {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        try:
            sys.path.remove(str(SCRIPTS))
        except ValueError:
            pass


class JDWorkflowContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_script("jd")

    def test_read_count_clamps_values(self) -> None:
        self.assertEqual(self.module.read_count("5", default=10, max_value=30), 5)
        self.assertEqual(self.module.read_count("0", default=10, max_value=30), 1)
        self.assertEqual(self.module.read_count("999", default=10, max_value=30), 30)
        self.assertEqual(self.module.read_count("bad", default=10, max_value=30), 10)

    def test_page_has_login_or_risk_detects_jd_states(self) -> None:
        self.assertTrue(self.module.page_has_login_or_risk({"href": "https://passport.jd.com/login.aspx", "title": "", "text": ""}))
        self.assertTrue(self.module.page_has_login_or_risk({"href": "", "title": "安全验证", "text": ""}))
        self.assertFalse(self.module.page_has_login_or_risk({"href": "https://item.jd.com/100291143898.html", "title": "商品详情", "text": "京东 商品"}))

    def test_write_records_outputs_standard_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.module.write_records([{"title": "测试商品", "price": "¥1"}], out, "京东测试")
            self.assertEqual(json.loads((out / "summary.json").read_text(encoding="utf-8"))[0]["title"], "测试商品")
            self.assertIn("京东测试", (out / "summary.md").read_text(encoding="utf-8"))
            self.assertEqual(json.loads((out / "failures.json").read_text(encoding="utf-8")), [])

    def test_help_exposes_only_read_only_commands(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "jd_workflow.py"), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        help_text = result.stdout
        for command in ("search", "item", "detail", "reviews", "cart", "whoami"):
            self.assertIn(command, help_text)
        self.assertNotIn("add-cart", help_text)
        self.assertNotIn("checkout", help_text)


class TaobaoWorkflowContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_script("taobao")

    def test_read_count_clamps_values(self) -> None:
        self.assertEqual(self.module.read_count("5", default=10, max_value=40), 5)
        self.assertEqual(self.module.read_count("0", default=10, max_value=40), 1)
        self.assertEqual(self.module.read_count("999", default=10, max_value=40), 40)
        self.assertEqual(self.module.read_count("bad", default=10, max_value=40), 10)

    def test_page_has_login_or_risk_detects_taobao_states(self) -> None:
        self.assertTrue(self.module.page_has_login_or_risk({"href": "https://login.taobao.com/member/login.jhtml", "title": "", "text": ""}))
        self.assertTrue(self.module.page_has_login_or_risk({"href": "", "title": "", "text": "请登录后查看购物车"}))
        self.assertFalse(self.module.page_has_login_or_risk({"href": "https://item.taobao.com/item.htm?id=827563850178", "title": "商品详情", "text": "淘宝 商品"}))

    def test_write_records_outputs_standard_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.module.write_records([{"title": "测试商品", "price": "¥1"}], out, "淘宝测试")
            self.assertEqual(json.loads((out / "summary.json").read_text(encoding="utf-8"))[0]["title"], "测试商品")
            self.assertIn("淘宝测试", (out / "summary.md").read_text(encoding="utf-8"))
            self.assertEqual(json.loads((out / "failures.json").read_text(encoding="utf-8")), [])

    def test_help_exposes_only_read_only_commands(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "taobao_workflow.py"), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        help_text = result.stdout
        for command in ("search", "detail", "reviews", "cart", "whoami"):
            self.assertIn(command, help_text)
        self.assertNotIn("add-cart", help_text)
        self.assertNotIn("checkout", help_text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail because scripts do not exist**

Run:

```bash
python3 -m unittest tests.test_jd_taobao_workflows
```

Expected: fail with `FileNotFoundError` or import failure for `scripts/jd_workflow.py` and `scripts/taobao_workflow.py`.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_jd_taobao_workflows.py
git commit -m "test: add JD and Taobao workflow contracts"
```

### Task 2: Add JD Workflow Skeleton

**Files:**
- Create: `scripts/jd_workflow.py`
- Test: `tests/test_jd_taobao_workflows.py`

- [ ] **Step 1: Implement the JD skeleton and shared helper contract**

Create `scripts/jd_workflow.py` with this structure:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JD.com read-only ActionBook workflow helper for the action-browser skill."""

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
    """Raised when JD asks for login, CAPTCHA, or security verification."""


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
    text = str(value or "").strip()
    match = re.search(r"(\d{5,})", text)
    if not match:
        raise argparse.ArgumentTypeError(f"{label} must include a numeric id, for example {example}")
    return match.group(1)


def unwrap_eval(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def page_has_login_or_risk(state: dict[str, str]) -> bool:
    href = str(state.get("href") or "")
    title = str(state.get("title") or "")
    text = str(state.get("text") or "")
    if re.search(r"passport\.jd\.com|/login|verify|captcha", href, re.I):
        return True
    haystack = "\n".join([title, text])
    return bool(re.search(r"请登录|登录后|扫码登录|验证码|安全验证|风险|访问频繁|passport|captcha|verify", haystack, re.I))


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
        heading = item.get("title") or item.get("name") or item.get("sku") or str(index)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JD.com read-only ActionBook workflow.")
    subparsers = parser.add_subparsers(dest="area", required=True)

    def add_common(p: argparse.ArgumentParser, default_count: int = 10) -> None:
        p.add_argument("--session", default=DEFAULT_SESSION, help="ActionBook session id")
        p.add_argument("--tab", default=DEFAULT_TAB, help="ActionBook tab id")
        p.add_argument("--output", default="", help="Output directory")
        p.add_argument("--count", default=default_count, help="Record count")

    search = subparsers.add_parser("search", help="JD product search")
    search_sub = search.add_subparsers(dest="mode", required=True)
    search_view = search_sub.add_parser("view", help="View JD search results")
    search_view.add_argument("--query", required=True, help="Search keyword")
    add_common(search_view, default_count=10)
    search_view.set_defaults(func=run_search)

    item = subparsers.add_parser("item", help="JD enhanced product detail")
    item_sub = item.add_subparsers(dest="mode", required=True)
    item_view = item_sub.add_parser("view", help="View enhanced product detail")
    item_view.add_argument("--sku", required=True, help="JD SKU id")
    item_view.add_argument("--images", default=200, help="Image count limit")
    add_common(item_view, default_count=1)
    item_view.set_defaults(func=run_item)

    detail = subparsers.add_parser("detail", help="JD compact product detail")
    detail_sub = detail.add_subparsers(dest="mode", required=True)
    detail_view = detail_sub.add_parser("view", help="View compact product detail")
    detail_view.add_argument("--sku", required=True, help="JD SKU id")
    add_common(detail_view, default_count=1)
    detail_view.set_defaults(func=run_detail)

    reviews = subparsers.add_parser("reviews", help="JD product reviews")
    reviews_sub = reviews.add_subparsers(dest="mode", required=True)
    reviews_view = reviews_sub.add_parser("view", help="View product reviews")
    reviews_view.add_argument("--sku", required=True, help="JD SKU id")
    add_common(reviews_view, default_count=10)
    reviews_view.set_defaults(func=run_reviews)

    cart = subparsers.add_parser("cart", help="JD cart")
    cart_sub = cart.add_subparsers(dest="mode", required=True)
    cart_view = cart_sub.add_parser("view", help="View current account cart")
    add_common(cart_view, default_count=20)
    cart_view.set_defaults(func=run_cart)

    whoami = subparsers.add_parser("whoami", help="JD current account")
    whoami_sub = whoami.add_subparsers(dest="mode", required=True)
    whoami_view = whoami_sub.add_parser("view", help="View current account identity")
    add_common(whoami_view, default_count=1)
    whoami_view.set_defaults(func=run_whoami)
    return parser


def finish(records: list[dict[str, Any]], args: argparse.Namespace, area: str, title: str) -> int:
    output_dir = Path(args.output).expanduser() if args.output else default_output_dir(area)
    write_records(records, output_dir, title)
    log(f"写入 {len(records)} 条记录: {output_dir}")
    return 0


def run_search(args: argparse.Namespace) -> int:
    return finish([], args, "search", f"京东搜索: {args.query}")


def run_item(args: argparse.Namespace) -> int:
    sku = normalize_numeric_id(args.sku, "sku", "100291143898")
    return finish([{"sku": sku, "source_url": f"https://item.jd.com/{sku}.html"}], args, "item", f"京东商品详情: {sku}")


def run_detail(args: argparse.Namespace) -> int:
    sku = normalize_numeric_id(args.sku, "sku", "100291143898")
    return finish([{"field": "SKU", "value": sku}], args, "detail", f"京东商品详情: {sku}")


def run_reviews(args: argparse.Namespace) -> int:
    sku = normalize_numeric_id(args.sku, "sku", "100291143898")
    return finish([], args, "reviews", f"京东商品评价: {sku}")


def run_cart(args: argparse.Namespace) -> int:
    return finish([], args, "cart", "京东购物车")


def run_whoami(args: argparse.Namespace) -> int:
    return finish([{"logged_in": False, "nickname": "", "user_id": "", "source_url": JD_HOME_URL}], args, "whoami", "京东当前账号")


def main() -> int:
    install_interrupt_handlers()
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args) or 0)
    except LoginRequiredError as exc:
        print(f"LOGIN_REQUIRED: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the contract tests**

Run:

```bash
python3 -m unittest tests.test_jd_taobao_workflows
```

Expected: JD tests pass; Taobao tests still fail because `scripts/taobao_workflow.py` does not exist.

- [ ] **Step 3: Commit JD skeleton**

```bash
git add scripts/jd_workflow.py
git commit -m "feat: add JD workflow skeleton"
```

### Task 3: Add Taobao Workflow Skeleton

**Files:**
- Create: `scripts/taobao_workflow.py`
- Test: `tests/test_jd_taobao_workflows.py`

- [ ] **Step 1: Implement the Taobao parser and shared helper contract**

Create `scripts/taobao_workflow.py` with these top-level constants:

```python
TAOBAO_HOME_URL = "https://www.taobao.com"
TAOBAO_SEARCH_URL = "https://s.taobao.com/search"
DEFAULT_SESSION = "taobao-task"
DEFAULT_TAB = ""
SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = SKILL_DIR / "assets" / "taobao"
```

Define these helper functions in the Taobao script: `log`, `read_count`, `normalize_text`, `normalize_numeric_id`, `unwrap_eval`, `page_has_login_or_risk`, `write_json`, `default_output_dir`, `write_records`, `finish`, `build_parser`, `main`. Use this login/risk detector:

```python
def page_has_login_or_risk(state: dict[str, str]) -> bool:
    href = str(state.get("href") or "")
    title = str(state.get("title") or "")
    text = str(state.get("text") or "")
    if re.search(r"login\.taobao\.com|login|passport|verify|captcha", href, re.I):
        return True
    haystack = "\n".join([title, text])
    return bool(re.search(r"请登录|登录后|扫码登录|验证码|安全验证|风险|访问频繁|captcha|verify|滑块", haystack, re.I))
```

Build parser commands:

```python
search view --query <keyword> --sort default|sale|price --count 10
detail view --id <item_id>
reviews view --id <item_id> --count 10
cart view --count 20
whoami view
```

Do not add `add-cart`, `checkout`, `buy`, `order`, `delete`, or quantity mutation commands.

- [ ] **Step 2: Run the contract tests**

Run:

```bash
python3 -m unittest tests.test_jd_taobao_workflows
```

Expected: all tests pass.

- [ ] **Step 3: Run static script checks**

Run:

```bash
python3 -m py_compile scripts/jd_workflow.py scripts/taobao_workflow.py
python3 scripts/jd_workflow.py --help
python3 scripts/taobao_workflow.py --help
```

Expected: all commands exit `0`; help output lists read-only commands only.

- [ ] **Step 4: Commit Taobao skeleton**

```bash
git add scripts/taobao_workflow.py
git commit -m "feat: add Taobao workflow skeleton"
```

### Task 4: Implement JD Read-Only Actions

**Files:**
- Modify: `scripts/jd_workflow.py`
- Test: `tests/test_jd_taobao_workflows.py`

- [ ] **Step 1: Replace parser-contract actions with ActionBook execution helpers**

Replace the minimal parser-contract actions with concrete helpers:

```python
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
      text: (document.body?.innerText || '').slice(0, 1200)
    }))()
    """, "jd page state", timeout=10.0)
    return value if isinstance(value, dict) else {}


def ensure_ready(book: ActionBook) -> None:
    state = get_page_state(book)
    if page_has_login_or_risk(state):
        raise LoginRequiredError(f"JD requires login or verification: {state.get('href')} title={state.get('title')}")


def start_book(args: argparse.Namespace, url: str) -> ActionBook:
    book = ActionBook(args.session, args.tab)
    book.start(url)
    return book


def finish(records: list[dict[str, Any]], args: argparse.Namespace, area: str, title: str) -> int:
    output_dir = Path(args.output).expanduser() if args.output else default_output_dir(area)
    write_records(records, output_dir, title)
    log(f"写入 {len(records)} 条记录: {output_dir}")
    return 0
```

- [ ] **Step 2: Implement `run_search`**

Use ActionBook to navigate to `https://search.jd.com/Search?keyword=...&enc=utf-8`, scroll, and extract `div[data-sku]` records with fields `rank`, `title`, `price`, `shop`, `sku`, `url`.

- [ ] **Step 3: Implement `run_detail` and `run_item`**

`run_detail` returns compact fields: product name, price, shop, SKU, and link.

`run_item` returns one record with fields:

```python
{
    "title": title,
    "price": price,
    "shop": shop,
    "specs": specs,
    "main_images": main_images,
    "detail_images": detail_images,
    "source_url": url,
}
```

The page-side script should collect `img[src*="360buyimg.com"]`, normalize protocol-relative URLs to `https:`, split obvious main images and detail images, and cap both combined by `--images`.

- [ ] **Step 4: Implement `run_reviews`**

Navigate to `https://item.jd.com/<sku>.html`, scroll near the review section, and extract up to `--count` review records with fields `rank`, `user`, `content`, and `date`.

- [ ] **Step 5: Implement `run_cart`**

Navigate to `https://cart.jd.com/cart_index`, detect login/risk, then first try browser-side same-origin/cart API fetch with `credentials: 'include'`. If that returns no items, fall back to visible DOM text parsing. Output fields `index`, `title`, `price`, `quantity`, `sku`.

- [ ] **Step 6: Implement `run_whoami`**

Navigate to `https://home.jd.com/`, detect login/risk, and return one record:

```python
{
    "logged_in": True,
    "nickname": nickname,
    "user_id": user_id,
    "source_url": location.href,
}
```

If the page clearly shows login required, raise `LoginRequiredError` instead of returning `logged_in: False`.

- [ ] **Step 7: Run JD verification**

Run:

```bash
python3 -m unittest tests.test_jd_taobao_workflows
python3 -m py_compile scripts/jd_workflow.py
python3 scripts/jd_workflow.py --help
python3 scripts/jd_workflow.py search view --query "机械键盘" --count 3
python3 scripts/jd_workflow.py item view --sku 100291143898 --images 5
```

Expected: unit tests and static checks pass. Browser commands either write output directories with non-error `summary.json`, or exit with a clear `LOGIN_REQUIRED` message if Chrome needs user action.

- [ ] **Step 8: Commit JD implementation**

```bash
git add scripts/jd_workflow.py tests/test_jd_taobao_workflows.py
git commit -m "feat: implement JD read-only workflow"
```

### Task 5: Implement Taobao Read-Only Actions

**Files:**
- Modify: `scripts/taobao_workflow.py`
- Test: `tests/test_jd_taobao_workflows.py`

- [ ] **Step 1: Add Taobao ActionBook execution helpers**

Add these functions to `scripts/taobao_workflow.py`: `api_eval`, `get_page_state`, `ensure_ready`, `start_book`, and `finish`. `api_eval` must unwrap ActionBook eval results and raise `RuntimeError` for page-side `{"error": "..."}` payloads. `get_page_state` must read `location.href`, `document.title`, and the first 1200 characters of `document.body.innerText`. `ensure_ready` must call `page_has_login_or_risk` and raise `LoginRequiredError` with a Taobao-specific message. `start_book` must create `ActionBook(args.session, args.tab)` and call `book.start(url)`. `finish` must write records to `Path(args.output)` when provided, otherwise to `default_output_dir(area)`, then print the output directory and record count.

- [ ] **Step 2: Implement `run_search`**

Navigate to `https://www.taobao.com`, then use page-side `location.href = "https://s.taobao.com/search?q=..."` with the `--sort` mapping:

```python
{"default": "", "sale": "&sort=sale-desc", "price": "&sort=price-asc"}
```

Extract product cards into `rank`, `title`, `price`, `sales`, `shop`, `location`, `item_id`, and `url`.

- [ ] **Step 3: Implement `run_detail`**

Navigate through Taobao home to `https://item.taobao.com/item.htm?id=<id>` and extract fields as records:

```python
[
    {"field": "商品名称", "value": title},
    {"field": "价格", "value": price},
    {"field": "销量", "value": sales},
    {"field": "评价数", "value": review_count},
    {"field": "店铺", "value": shop},
    {"field": "发货地", "value": location},
    {"field": "ID", "value": item_id},
    {"field": "链接", "value": source_url},
]
```

- [ ] **Step 4: Implement `run_reviews`**

On the Taobao item page, discover `sellerId` from page HTML or shop links, then read `https://rate.tmall.com/list_detail_rate.htm?...` via JSONP injection in page context. Output `rank`, `user`, `content`, `date`, and `spec`.

- [ ] **Step 5: Implement `run_cart`**

Navigate through Taobao home to `https://cart.taobao.com/cart.htm`, detect login/risk, scroll, and parse visible cart sections into `index`, `title`, `price`, `spec`, and `shop`. Do not click delete, quantity, checkout, select-all, or settlement buttons.

- [ ] **Step 6: Implement `run_whoami`**

Navigate to `https://i.taobao.com/my_itaobao`, detect login/risk, and return one record:

```python
{
    "logged_in": True,
    "nickname": nickname,
    "user_id": user_id,
    "source_url": location.href,
}
```

If the page clearly shows login required, raise `LoginRequiredError`.

- [ ] **Step 7: Run Taobao verification**

Run:

```bash
python3 -m unittest tests.test_jd_taobao_workflows
python3 -m py_compile scripts/taobao_workflow.py
python3 scripts/taobao_workflow.py --help
python3 scripts/taobao_workflow.py search view --query "机械键盘" --count 3
python3 scripts/taobao_workflow.py detail view --id 827563850178
```

Expected: unit tests and static checks pass. Browser commands either write output directories with non-error `summary.json`, or exit with a clear `LOGIN_REQUIRED` message if Chrome needs user action.

- [ ] **Step 8: Commit Taobao implementation**

```bash
git add scripts/taobao_workflow.py tests/test_jd_taobao_workflows.py
git commit -m "feat: implement Taobao read-only workflow"
```

### Task 6: Add Site References and Index Entries

**Files:**
- Create: `references/jd.md`
- Create: `references/taobao.md`
- Modify: `SKILL.md`
- Modify: `README.md`

- [ ] **Step 1: Create `references/jd.md`**

Include these sections:

```markdown
# 京东 ActionBook 操作说明

本文记录京东网页在 ActionBook extension 模式下的站点专属经验。通用会话、等待、错误处理规则见 `../SKILL.md`。

## 支持范围

只启用低风险只读入口：`search`、`item`、`detail`、`reviews`、`cart`、`whoami`。

未启用：`add-cart`、购买、结算、提交订单、修改购物车数量、删除购物车商品。

## 常用命令

```bash
python3 scripts/jd_workflow.py search view --query "机械键盘" --count 10
python3 scripts/jd_workflow.py item view --sku 100291143898 --images 50
python3 scripts/jd_workflow.py detail view --sku 100291143898
python3 scripts/jd_workflow.py reviews view --sku 100291143898 --count 10
python3 scripts/jd_workflow.py cart view --count 20
python3 scripts/jd_workflow.py whoami view
```

## 输出位置

默认输出在 `assets/jd/views/<area>/<timestamp>/`，包含 `summary.json`、`summary.md`、`failures.json`。

## 登录和风控

脚本依赖 Chrome extension mode 和用户当前 Chrome 登录态。遇到登录、扫码、验证码、安全验证或访问频繁时，保持同一 Chrome 窗口，让用户手动处理后重试。

`cart` 和 `whoami` 读取当前登录账号数据，只在用户明确请求时运行。

## 数据边界

`search`、`detail`、`item`、`reviews` 读取商品公开页面。`cart` 读取当前账号购物车，只做展示，不点击结算、删除、数量或选择按钮。

## 修改后验证

```bash
python3 -m py_compile scripts/jd_workflow.py
python3 scripts/jd_workflow.py --help
python3 scripts/jd_workflow.py search view --query "机械键盘" --count 3
python3 scripts/jd_workflow.py item view --sku 100291143898 --images 5
```
```

- [ ] **Step 2: Create `references/taobao.md`**

Create `references/taobao.md` with this content:

```markdown
# 淘宝 ActionBook 操作说明

本文记录淘宝网页在 ActionBook extension 模式下的站点专属经验。通用会话、等待、错误处理规则见 `../SKILL.md`。

## 支持范围

只启用低风险只读入口：`search`、`detail`、`reviews`、`cart`、`whoami`。

未启用：`add-cart`、购买、结算、提交订单、修改购物车数量、删除购物车商品。

## 常用命令

```bash
python3 scripts/taobao_workflow.py search view --query "机械键盘" --sort default --count 10
python3 scripts/taobao_workflow.py detail view --id 827563850178
python3 scripts/taobao_workflow.py reviews view --id 827563850178 --count 10
python3 scripts/taobao_workflow.py cart view --count 20
python3 scripts/taobao_workflow.py whoami view
```

## 输出位置

默认输出在 `assets/taobao/views/<area>/<timestamp>/`，包含 `summary.json`、`summary.md`、`failures.json`。

## 登录和风控

脚本依赖 Chrome extension mode 和用户当前 Chrome 登录态。遇到登录、扫码、验证码、安全验证、滑块或访问频繁时，保持同一 Chrome 窗口，让用户手动处理后重试。

`cart` 和 `whoami` 读取当前登录账号数据，只在用户明确请求时运行。

## 数据边界

`search`、`detail`、`reviews` 读取商品页面和评价数据。`cart` 读取当前账号购物车，只做展示，不点击结算、删除、数量或选择按钮。

## 修改后验证

```bash
python3 -m py_compile scripts/taobao_workflow.py
python3 scripts/taobao_workflow.py --help
python3 scripts/taobao_workflow.py search view --query "机械键盘" --count 3
python3 scripts/taobao_workflow.py detail view --id 827563850178
```
```

- [ ] **Step 3: Update `SKILL.md` References table**

Add rows:

```markdown
| JD.com / 京东 | `references/jd.md`, `scripts/jd_workflow.py` |
| Taobao / 淘宝 | `references/taobao.md`, `scripts/taobao_workflow.py` |
```

- [ ] **Step 4: Update `README.md` Included Workflows table**

Add rows:

```markdown
| `scripts/jd_workflow.py` | View JD search, product details, reviews, cart, and current account identity. |
| `scripts/taobao_workflow.py` | View Taobao search, product details, reviews, cart, and current account identity. |
```

- [ ] **Step 5: Run documentation checks**

Run:

```bash
rg -n "jd_workflow|taobao_workflow|references/jd|references/taobao|add-cart|checkout" SKILL.md README.md references/jd.md references/taobao.md
```

Expected: JD/Taobao references are present; `add-cart` and `checkout` appear only as disabled/out-of-scope capabilities.

- [ ] **Step 6: Commit docs and indexes**

```bash
git add SKILL.md README.md references/jd.md references/taobao.md
git commit -m "docs: add JD and Taobao ActionBook references"
```

### Task 7: Final Verification

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run static checks**

```bash
python3 -m unittest tests.test_jd_taobao_workflows
python3 -m py_compile scripts/jd_workflow.py scripts/taobao_workflow.py
python3 scripts/jd_workflow.py --help
python3 scripts/taobao_workflow.py --help
```

Expected: all commands exit `0`.

- [ ] **Step 2: Run browser smoke checks**

```bash
python3 scripts/jd_workflow.py search view --query "机械键盘" --count 3
python3 scripts/jd_workflow.py item view --sku 100291143898 --images 5
python3 scripts/taobao_workflow.py search view --query "机械键盘" --count 3
python3 scripts/taobao_workflow.py detail view --id 827563850178
```

Expected: each command either writes an output directory with `summary.json`, `summary.md`, and `failures.json`, or exits with a clear `LOGIN_REQUIRED` message requiring user action in Chrome.

- [ ] **Step 3: Run cart checks only when user explicitly approves**

```bash
python3 scripts/jd_workflow.py cart view --count 3
python3 scripts/taobao_workflow.py cart view --count 3
```

Expected: run only after explicit approval because cart reads personal logged-in account data. Commands either write cart summaries or clearly stop at login/risk control.

- [ ] **Step 4: Confirm no write operations exist**

```bash
rg -n "add-cart|checkout|submit|结算|提交订单|加入购物车|delete|删除" scripts/jd_workflow.py scripts/taobao_workflow.py references/jd.md references/taobao.md SKILL.md README.md
```

Expected: matches in references only describe disabled capabilities; scripts do not expose write commands or click write-operation buttons.

- [ ] **Step 5: Check Git status**

```bash
git status --short --branch
```

Expected: clean working tree after final commit.

- [ ] **Step 6: Commit final fixes if any**

If final verification required small fixes:

```bash
git add scripts/jd_workflow.py scripts/taobao_workflow.py tests/test_jd_taobao_workflows.py SKILL.md README.md references/jd.md references/taobao.md
git commit -m "chore: finalize JD and Taobao ActionBook support"
```

If no fixes were needed, do not create an empty commit.
