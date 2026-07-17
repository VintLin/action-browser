from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "adapters" / "xianyu_workflow.py"
SPEC = importlib.util.spec_from_file_location("xianyu_workflow", SCRIPT)
assert SPEC and SPEC.loader
xianyu = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(xianyu)


def test_opencli_search_filter_shape() -> None:
    assert xianyu.build_search_filter(None, None) == ""
    assert xianyu.build_search_filter(100, 800) == "priceRange:100,800;"
    assert xianyu.build_search_filter(100, None) == "priceRange:100,99999999;"
    assert json.loads(xianyu.build_extra_filter_value("广东", "深圳"))["divisionList"] == [{"province": "广东", "city": "深圳"}]


def test_normalizes_item_and_chat_urls() -> None:
    assert xianyu.normalize_numeric_id("https://www.goofish.com/item?id=1040754408976") == "1040754408976"
    assert xianyu.build_chat_url("10001", "90001") == "https://www.goofish.com/im?itemId=10001&peerUserId=90001"


def test_rejects_inverted_or_invalid_ranges() -> None:
    with pytest.raises(Exception):
        xianyu.parse_price("abc", "min-price")
    with pytest.raises(Exception):
        xianyu.read_count("0", 20, 60)


def test_script_does_not_expose_write_commands() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "def run_publish" not in source
    assert "def run_reply" not in source
    assert "--text" not in source
