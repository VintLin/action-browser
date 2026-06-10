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
