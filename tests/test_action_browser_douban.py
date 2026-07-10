from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.adapters.douban_public import PageStateError, parse_movie_chart
from scripts.action_browser import validate_artifact, validate_contract
from scripts.scheduler_lib.reconcile import reconcile_task_state


FIXTURE = (ROOT / "tests" / "fixtures" / "douban_movie_chart.html").read_text(encoding="utf-8")


def test_parser_returns_reference_semantic_fields_and_stable_identity() -> None:
    records, state = parse_movie_chart(FIXTURE, limit=1)

    assert state == "items"
    assert records == [{"id": "1292052", "url": "https://movie.douban.com/subject/1292052/", "title": "The Shawshank Redemption", "rank": 1, "rating": 9.7, "rating_count": 1234567, "summary": "1994 / 美国 / 剧情", "year": "1994"}]


def test_parser_accepts_only_explicit_empty_marker() -> None:
    assert parse_movie_chart('<div id="content"><div class="empty">暂无内容</div></div>', limit=5) == ([], "empty")
    with pytest.raises(PageStateError, match="page_not_ready"):
        parse_movie_chart('<div class="empty">unrelated</div><div id="content"></div>', limit=5)
    with pytest.raises(PageStateError, match="page_not_ready"):
        parse_movie_chart('<html><body>unexpected</body></html>', limit=5)


def test_parser_rejects_required_field_gap() -> None:
    with pytest.raises(PageStateError, match="field_gap"):
        parse_movie_chart('<div id="content"><div class="item"><div class="pl2"><a href="https://movie.douban.com/subject/1/">Missing score</a></div></div></div>', limit=1)


def test_parser_normalizes_relative_urls_and_requires_year() -> None:
    records, _ = parse_movie_chart('<div id="content"><tr class="item"><td class="pl2"><a href="/subject/1/">Relative</a><p>2026 / 中国大陆</p></td><span class="rating_nums">8.0</span><span class="pl">12人评价</span></tr></div>', limit=1)
    assert records[0]["url"] == "https://movie.douban.com/subject/1/"
    with pytest.raises(PageStateError, match="field_gap"):
        parse_movie_chart('<div id="content"><tr class="item"><td class="pl2"><a href="/subject/1/">No year</a><p>中国大陆</p></td><span class="rating_nums">8.0</span><span class="pl">12人评价</span></tr></div>', limit=1)


def test_command_writes_one_result_envelope_and_versioned_artifacts(tmp_path: Path) -> None:
    fixture = tmp_path / "chart.html"
    fixture.write_text(FIXTURE, encoding="utf-8")
    output = tmp_path / "output"
    result = subprocess.run([sys.executable, "scripts/action_browser.py", "run", "--site", "douban", "--resource", "movie-ranking", "--intent", "trending", "--limit", "1", "--task-id", "t2-test", "--output-root", str(output), "--fixture", str(fixture)], cwd=ROOT, text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["capability_id"] == "douban.movie-ranking.trending.read"
    assert envelope["status"] == "completed"
    artifact = json.loads((output / "artifacts" / "movie-ranking.json").read_text(encoding="utf-8"))
    assert artifact["schema_version"] == 1
    assert list(artifact["items"][0]) == ["id", "url", "title", "rank", "rating", "rating_count", "summary", "year"]
    contract = json.loads((output / "contract" / "summary.json").read_text(encoding="utf-8"))
    assert contract["strategy_used"] == "public_http"
    assert contract["collected_count"] == 1
    assert json.loads((output / "contract" / "progress.json").read_text(encoding="utf-8"))["schema_version"] == 1


@pytest.mark.parametrize("limit", ["0", "-1", "21"])
def test_command_rejects_invalid_or_over_limit_values_with_envelope(tmp_path: Path, limit: str) -> None:
    result = subprocess.run([sys.executable, "scripts/action_browser.py", "run", "--site", "douban", "--resource", "movie-ranking", "--intent", "trending", "--limit", limit, "--task-id", "t2-test", "--output-root", str(tmp_path)], cwd=ROOT, text=True, capture_output=True, check=False)

    assert result.returncode == 1
    assert json.loads(result.stdout)["failure"]["reason_code"] == "invalid_input"


def test_command_io_failure_still_writes_exactly_one_envelope(tmp_path: Path) -> None:
    result = subprocess.run([sys.executable, "scripts/action_browser.py", "run", "--site", "douban", "--resource", "movie-ranking", "--intent", "trending", "--limit", "1", "--task-id", "t2-test", "--output-root", str(tmp_path), "--fixture", str(tmp_path / "missing.html")], cwd=ROOT, text=True, capture_output=True, check=False)

    assert result.returncode == 1
    assert json.loads(result.stdout)["failure"]["reason_code"] == "config_error"
    assert "Traceback" not in result.stderr


def test_command_unwritable_output_still_writes_an_envelope() -> None:
    result = subprocess.run([sys.executable, "scripts/action_browser.py", "run", "--site", "douban", "--resource", "movie-ranking", "--intent", "trending", "--limit", "1", "--task-id", "t2-test", "--output-root", "/dev/null/output", "--fixture", str(ROOT / "tests" / "fixtures" / "douban_movie_chart.html")], cwd=ROOT, text=True, capture_output=True, check=False)

    assert result.returncode == 1
    assert json.loads(result.stdout)["failure"]["reason_code"] == "storage_failed"
    assert "Traceback" not in result.stderr


def test_command_non_integer_limit_writes_an_envelope(tmp_path: Path) -> None:
    result = subprocess.run([sys.executable, "scripts/action_browser.py", "run", "--site", "douban", "--resource", "movie-ranking", "--intent", "trending", "--limit", "five", "--task-id", "t2-test", "--output-root", str(tmp_path)], cwd=ROOT, text=True, capture_output=True, check=False)

    assert result.returncode == 1
    assert json.loads(result.stdout)["failure"]["reason_code"] == "invalid_input"


def test_empty_contract_and_envelope_agree(tmp_path: Path) -> None:
    fixture = tmp_path / "empty.html"
    fixture.write_text('<div id="content"><div class="empty">暂无内容</div></div>', encoding="utf-8")
    output = tmp_path / "output"
    result = subprocess.run([sys.executable, "scripts/action_browser.py", "run", "--site", "douban", "--resource", "movie-ranking", "--intent", "trending", "--limit", "1", "--task-id", "t2-test", "--output-root", str(output), "--fixture", str(fixture)], cwd=ROOT, text=True, capture_output=True, check=False)

    assert json.loads(result.stdout)["status"] == "verified_empty"
    assert json.loads((output / "contract" / "summary.json").read_text(encoding="utf-8"))["status"] == "verified_empty"


def test_schema_validators_reject_invalid_nested_values(tmp_path: Path) -> None:
    artifact = {"schema_version": 1, "capability_id": "douban.movie-ranking.trending.read", "items": [{"id": None, "url": None, "title": None, "rank": None, "rating": None, "rating_count": None, "summary": None, "year": None}]}
    with pytest.raises(ValueError, match="invalid movie ranking item"):
        validate_artifact(artifact)

    fixture = tmp_path / "chart.html"
    fixture.write_text(FIXTURE, encoding="utf-8")
    output = tmp_path / "output"
    subprocess.run([sys.executable, "scripts/action_browser.py", "run", "--site", "douban", "--resource", "movie-ranking", "--intent", "trending", "--limit", "1", "--task-id", "t2-test", "--output-root", str(output), "--fixture", str(fixture)], cwd=ROOT, text=True, capture_output=True, check=False)
    contract = json.loads((output / "contract" / "summary.json").read_text(encoding="utf-8"))
    valid_progress = contract["progress"]
    contract["progress"] = {"schema_version": "1"}
    with pytest.raises(ValueError, match="invalid adapter contract"):
        validate_contract(contract)
    contract["progress"] = valid_progress
    for field, value in (("site", "other"), ("status", "unknown"), ("limits", {}), ("failure", {"reason_code": None}), ("progress", {"schema_version": 1, "task_id": "t2-test", "status": "unknown", "stage": "completed", "completed": 0, "requested": -1, "last_url": "", "last_title": ""})):
        invalid = dict(contract)
        invalid["progress"] = json.loads(json.dumps(contract["progress"]))
        invalid[field] = value
        with pytest.raises(ValueError, match="invalid adapter contract"):
            validate_contract(invalid)


def test_field_gap_contract_maps_to_a_blocked_scheduler_state(tmp_path: Path) -> None:
    fixture = tmp_path / "gap.html"
    fixture.write_text('<div id="content"><div class="item"><div class="pl2"><a href="https://movie.douban.com/subject/1/">Missing score</a></div></div></div>', encoding="utf-8")
    output = tmp_path / "output"
    subprocess.run([sys.executable, "scripts/action_browser.py", "run", "--site", "douban", "--resource", "movie-ranking", "--intent", "trending", "--limit", "1", "--task-id", "t2-test", "--output-root", str(output), "--fixture", str(fixture)], cwd=ROOT, text=True, capture_output=True, check=False)

    result = reconcile_task_state({"task_id": "t2-test", "status": "running"}, run_state=None, tab_alive=False, summary_path=output / "contract" / "summary.json")

    assert result["status"] == "blocked"
    assert result["reason_code"] == "field_gap"
