from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FORBIDDEN_WRITE_COMMANDS = (
    "add-cart",
    "checkout",
    "buy",
    "order",
    "delete",
    "submit",
    "结算",
    "提交订单",
    "加入购物车",
    "删除",
)
FORBIDDEN_SENSITIVE_BROWSER_READS = (
    "document.cookie",
    "localStorage",
    "sessionStorage",
    "token",
    "password",
)


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


def run_help(script_name: str, *args: str) -> str:
    result = subprocess.run(
        ["python3", str(SCRIPTS / f"{script_name}_workflow.py"), *args, "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def assert_area_has_only_view(script_name: str, area: str) -> None:
    help_text = run_help(script_name, area)
    if "{view}" not in help_text:
        raise AssertionError(f"{script_name} {area} help does not expose view mode")
    multiple_choices = re.search(r"\{[^}]*,[^}]*\}", help_text)
    if multiple_choices is not None:
        raise AssertionError(f"{script_name} {area} help exposes multiple mode choices: {multiple_choices.group(0)}")
    for command in FORBIDDEN_WRITE_COMMANDS:
        if command in help_text:
            raise AssertionError(f"{script_name} {area} help exposes write command: {command}")


def assert_script_avoids_sensitive_browser_reads(script_name: str) -> None:
    source = (SCRIPTS / f"{script_name}_workflow.py").read_text(encoding="utf-8")
    lowered_source = source.lower()
    for term in FORBIDDEN_SENSITIVE_BROWSER_READS:
        if term.lower() in lowered_source:
            raise AssertionError(f"{script_name}_workflow.py reads sensitive browser storage: {term}")


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

    def test_navigation_pacing_matches_opencli_baseline(self) -> None:
        self.assertGreaterEqual(self.module.SEARCH_SETTLE_SECONDS, 5.0)
        self.assertGreaterEqual(self.module.ITEM_SETTLE_SECONDS, 5.0)
        self.assertGreaterEqual(self.module.CART_SETTLE_SECONDS, 5.0)
        self.assertGreaterEqual(self.module.WHOAMI_SETTLE_SECONDS, 3.0)
        self.assertIn("await sleep(1500);", self.module.SEARCH_SCRIPT)
        self.assertIn("await sleep(1500);", self.module.REVIEWS_SCRIPT)

    def test_api_eval_unwraps_values_and_raises_labeled_errors(self) -> None:
        class Book:
            def __init__(self) -> None:
                self.next_value = {"value": {"ok": True}}

            def eval(self, script: str, timeout: float = 45.0):  # noqa: ARG002
                return self.next_value

        book = Book()
        self.assertEqual(self.module.api_eval(book, "1 + 1", "sample"), {"ok": True})

        book.next_value = {"error": "blocked"}
        with self.assertRaisesRegex(RuntimeError, "sample: blocked"):
            self.module.api_eval(book, "1 + 1", "sample")

    def test_get_page_state_returns_normalized_state(self) -> None:
        class Book:
            def eval(self, script: str, timeout: float = 45.0):  # noqa: ARG002
                return {"value": {"href": "https://item.jd.com/1.html", "title": " 商品 ", "text": " A\nB "}}

        self.assertEqual(
            self.module.get_page_state(Book()),
            {"href": "https://item.jd.com/1.html", "title": "商品", "text": "A B"},
        )

    def test_require_list_payload_rejects_malformed_payloads(self) -> None:
        records = [{"rank": 1}]
        self.assertIs(self.module.require_list_payload(records, "jd search"), records)

        with self.assertRaisesRegex(RuntimeError, "jd search: x"):
            self.module.require_list_payload({"error": "x"}, "jd search")

        for value in ({}, None, "bad"):
            with self.assertRaisesRegex(RuntimeError, "jd search: malformed payload"):
                self.module.require_list_payload(value, "jd search")

        with self.assertRaisesRegex(RuntimeError, "jd search: malformed element"):
            self.module.require_list_payload(["bad"], "jd search")

    def test_require_dict_payload_rejects_malformed_payloads(self) -> None:
        record = {"title": "测试商品"}
        self.assertIs(self.module.require_dict_payload(record, "jd item"), record)

        with self.assertRaisesRegex(RuntimeError, "jd item: x"):
            self.module.require_dict_payload({"error": "x"}, "jd item")

        for value in ([], None, "bad"):
            with self.assertRaisesRegex(RuntimeError, "jd item: malformed payload"):
                self.module.require_dict_payload(value, "jd item")

    def test_require_cart_payload_handles_explicit_empty_and_api_failures(self) -> None:
        self.assertEqual(self.module.require_cart_payload({"items": []}, "jd cart"), [])
        self.assertEqual(
            self.module.require_cart_payload(
                {"items": [{"sku": "1"}], "api_error": "api failed", "dom_fallback_used": True},
                "jd cart",
            ),
            [{"sku": "1"}],
        )

        for value in ({}, None, "bad", {"items": "bad"}):
            with self.assertRaisesRegex(RuntimeError, "jd cart: malformed payload"):
                self.module.require_cart_payload(value, "jd cart")

        with self.assertRaisesRegex(RuntimeError, "jd cart: malformed element"):
            self.module.require_cart_payload({"items": ["bad"]}, "jd cart")

        with self.assertRaisesRegex(RuntimeError, "jd cart: api failed"):
            self.module.require_cart_payload({"items": [], "api_error": "api failed", "dom_fallback_used": True}, "jd cart")

    def test_write_records_outputs_standard_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.module.write_records([{"title": "测试商品", "price": "¥1"}], out, "京东测试")
            self.assertEqual(json.loads((out / "summary.json").read_text(encoding="utf-8"))[0]["title"], "测试商品")
            self.assertIn("京东测试", (out / "summary.md").read_text(encoding="utf-8"))
            self.assertEqual(json.loads((out / "failures.json").read_text(encoding="utf-8")), [])

    def test_help_exposes_only_read_only_commands(self) -> None:
        help_text = run_help("jd")
        for command in ("search", "item", "detail", "reviews", "cart", "whoami"):
            self.assertIn(command, help_text)
        for command in FORBIDDEN_WRITE_COMMANDS:
            self.assertNotIn(command, help_text)

        for area in ("search", "item", "detail", "reviews", "cart", "whoami"):
            assert_area_has_only_view("jd", area)

    def test_script_avoids_sensitive_browser_reads(self) -> None:
        assert_script_avoids_sensitive_browser_reads("jd")


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

    def test_navigation_pacing_matches_opencli_baseline(self) -> None:
        self.assertGreaterEqual(self.module.HOME_WARMUP_SECONDS, 2.0)
        self.assertGreaterEqual(self.module.SEARCH_SETTLE_SECONDS, 8.0)
        self.assertGreaterEqual(self.module.PAGE_SETTLE_SECONDS, 6.0)
        self.assertGreaterEqual(self.module.WHOAMI_SETTLE_SECONDS, 2.0)
        self.assertIn("await sleep(2000);", self.module.SEARCH_SCRIPT)
        self.assertIn("await sleep(1500);", self.module.CART_SCRIPT)

    def test_api_eval_unwraps_values_and_raises_labeled_errors(self) -> None:
        class Book:
            def __init__(self) -> None:
                self.next_value = {"value": {"ok": True}}

            def eval(self, script: str, timeout: float = 45.0):  # noqa: ARG002
                return self.next_value

        book = Book()
        self.assertEqual(self.module.api_eval(book, "1 + 1", "sample"), {"ok": True})

        book.next_value = {"error": "blocked"}
        with self.assertRaisesRegex(RuntimeError, "sample: blocked"):
            self.module.api_eval(book, "1 + 1", "sample")

    def test_get_page_state_returns_normalized_state(self) -> None:
        class Book:
            def eval(self, script: str, timeout: float = 45.0):  # noqa: ARG002
                return {"value": {"href": "https://item.taobao.com/item.htm?id=1", "title": " 商品 ", "text": " A\nB "}}

        self.assertEqual(
            self.module.get_page_state(Book()),
            {"href": "https://item.taobao.com/item.htm?id=1", "title": "商品", "text": "A B"},
        )

    def test_require_list_payload_rejects_malformed_payloads(self) -> None:
        records = [{"rank": 1}]
        self.assertIs(self.module.require_list_payload(records, "taobao search"), records)

        with self.assertRaisesRegex(RuntimeError, "taobao search: x"):
            self.module.require_list_payload({"error": "x"}, "taobao search")

        for value in ({}, None, "bad"):
            with self.assertRaisesRegex(RuntimeError, "taobao search: malformed payload"):
                self.module.require_list_payload(value, "taobao search")

        with self.assertRaisesRegex(RuntimeError, "taobao search: malformed element"):
            self.module.require_list_payload(["bad"], "taobao search")

    def test_require_cart_payload_handles_explicit_empty_and_api_failures(self) -> None:
        self.assertEqual(self.module.require_cart_payload({"items": [], "loaded": True}, "taobao cart"), [])
        self.assertEqual(
            self.module.require_cart_payload({"items": [{"index": 1}], "loaded": True}, "taobao cart"),
            [{"index": 1}],
        )

        for value in ({}, None, "bad", {"items": "bad"}):
            with self.assertRaisesRegex(RuntimeError, "taobao cart: malformed payload"):
                self.module.require_cart_payload(value, "taobao cart")

        with self.assertRaisesRegex(RuntimeError, "taobao cart: malformed element"):
            self.module.require_cart_payload({"items": ["bad"], "loaded": True}, "taobao cart")

        with self.assertRaisesRegex(RuntimeError, "taobao cart: not fully loaded"):
            self.module.require_cart_payload({"items": [], "loaded": False}, "taobao cart")

    def test_write_records_outputs_standard_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.module.write_records([{"title": "测试商品", "price": "¥1"}], out, "淘宝测试")
            self.assertEqual(json.loads((out / "summary.json").read_text(encoding="utf-8"))[0]["title"], "测试商品")
            self.assertIn("淘宝测试", (out / "summary.md").read_text(encoding="utf-8"))
            self.assertEqual(json.loads((out / "failures.json").read_text(encoding="utf-8")), [])

    def test_help_exposes_only_read_only_commands(self) -> None:
        help_text = run_help("taobao")
        for command in ("search", "detail", "reviews", "cart", "whoami"):
            self.assertIn(command, help_text)
        for command in FORBIDDEN_WRITE_COMMANDS:
            self.assertNotIn(command, help_text)

        for area in ("search", "detail", "reviews", "cart", "whoami"):
            assert_area_has_only_view("taobao", area)

    def test_script_avoids_sensitive_browser_reads(self) -> None:
        assert_script_avoids_sensitive_browser_reads("taobao")


if __name__ == "__main__":
    unittest.main()
