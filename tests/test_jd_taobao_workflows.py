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

    def test_search_script_keeps_opencli_text_fallback(self) -> None:
        self.assertIn("beforePrice = text.slice(0, text.indexOf('¥'))", self.module.SEARCH_SCRIPT)
        self.assertIn("海外无货", self.module.SEARCH_SCRIPT)

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

    def test_cart_script_keeps_opencli_text_fallback(self) -> None:
        self.assertIn("text.split(/移入收藏/)", self.module.CART_SCRIPT)
        self.assertIn("rawPrice += lines[j]", self.module.CART_SCRIPT)

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


class ZhipinWorkflowContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_script("zhipin")

    def test_help_exposes_only_read_only_commands(self) -> None:
        help_text = run_help("zhipin")
        for command in ("filters", "recommend", "search", "detail", "chatlist", "chatmsg"):
            self.assertIn(command, help_text)
        for command in FORBIDDEN_WRITE_COMMANDS + (
            "greet",
            "batchgreet",
            "send",
            "exchange",
            "invite",
            "mark",
            "resume",
        ):
            self.assertNotIn(command, help_text)

    def test_script_avoids_sensitive_browser_reads(self) -> None:
        assert_script_avoids_sensitive_browser_reads("zhipin")

    def test_normalize_detail_payload_maps_opencli_fields(self) -> None:
        payload = {
            "zpData": {
                "jobInfo": {
                    "jobName": "AI Agent 工程师",
                    "salaryDesc": "30-50K",
                    "experienceName": "3-5年",
                    "degreeName": "本科",
                    "locationName": "上海",
                    "areaDistrict": "浦东新区",
                    "businessDistrict": "张江",
                    "postDescription": "负责智能体应用开发",
                    "showSkills": ["Python", "LLM"],
                    "address": "上海市浦东新区",
                    "encryptId": "job-enc",
                },
                "bossInfo": {"name": "王女士", "title": "HRBP", "activeTimeDesc": "刚刚活跃"},
                "brandComInfo": {
                    "brandName": "测试科技",
                    "industryName": "人工智能",
                    "scaleName": "100-499人",
                    "stageName": "B轮",
                    "labels": ["五险一金"],
                },
            }
        }

        detail = self.module.normalize_detail_payload(payload, security_id="sec-1")

        self.assertEqual(detail["title"], "AI Agent 工程师")
        self.assertEqual(detail["salary"], "30-50K")
        self.assertEqual(detail["district"], "浦东新区·张江")
        self.assertEqual(detail["description"], "负责智能体应用开发")
        self.assertEqual(detail["skills"], ["Python", "LLM"])
        self.assertEqual(detail["welfare"], ["五险一金"])
        self.assertEqual(detail["boss_name"], "王女士")
        self.assertEqual(detail["company"], "测试科技")
        self.assertEqual(detail["security_id"], "sec-1")
        self.assertEqual(detail["url"], "https://www.zhipin.com/job_detail/job-enc.html")

    def test_chatlist_mappers_cover_boss_and_geek_rows(self) -> None:
        boss_row = self.module.map_boss_chat_row({
            "name": "李候选人",
            "jobName": "后端工程师",
            "lastMessageInfo": {"text": "你好"},
            "lastTime": "10:00",
            "encryptUid": "uid-1",
            "securityId": "sec-1",
        })
        geek_row = self.module.map_geek_chat_row({
            "name": "张经理",
            "brandName": "测试科技",
            "jobName": "AI Agent 工程师",
            "bossTitle": "技术负责人",
            "lastMessageInfo": {"showText": "方便聊聊吗", "msgTime": 1716000000000},
            "encryptUid": "uid-2",
            "securityId": "sec-2",
        })

        self.assertEqual(boss_row["name"], "李候选人")
        self.assertEqual(boss_row["job"], "后端工程师")
        self.assertEqual(boss_row["last_msg"], "你好")
        self.assertEqual(boss_row["uid"], "uid-1")
        self.assertEqual(geek_row["company"], "测试科技")
        self.assertEqual(geek_row["title"], "技术负责人")
        self.assertEqual(geek_row["last_msg"], "方便聊聊吗")
        self.assertEqual(geek_row["security_id"], "sec-2")

    def test_chatmsg_mappers_preserve_direction_and_text(self) -> None:
        boss_messages = self.module.map_boss_chat_messages(
            [{"from": {"uid": 123, "name": "候选人"}, "type": 1, "text": "你好", "time": 1716000000000}],
            {"uid": 123, "name": "候选人"},
        )
        geek_messages = self.module.map_geek_chat_messages(
            [{"from": {"uid": 456}, "type": 3, "body": {"showText": "打招呼"}, "time": 1716000000000}],
            {"uid": 456},
        )

        self.assertEqual(boss_messages[0]["from"], "候选人")
        self.assertEqual(boss_messages[0]["type"], "文本")
        self.assertEqual(boss_messages[0]["text"], "你好")
        self.assertEqual(geek_messages[0]["from"], "对方")
        self.assertEqual(geek_messages[0]["type"], "招呼")
        self.assertEqual(geek_messages[0]["text"], "打招呼")


if __name__ == "__main__":
    unittest.main()
