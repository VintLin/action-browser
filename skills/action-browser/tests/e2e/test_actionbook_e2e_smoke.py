from pathlib import Path
import sys

# `pytest tests/e2e/test_actionbook_e2e_smoke.py -v` does not place the repo root on sys.path here.
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tests.e2e import actionbook_e2e_smoke


def test_parse_json_maybe_extracts_trailing_json_block() -> None:
    text = '[00:00:00] log line\n{\n  "session_id": "s1",\n  "tab_id": "t2"\n}'

    assert actionbook_e2e_smoke.parse_json_maybe(text) == {"session_id": "s1", "tab_id": "t2"}
