from pathlib import Path
import re


ROOT_DIR = Path(__file__).resolve().parents[1]


def _current_sites() -> set[str]:
    skill_text = (ROOT_DIR / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^Current sites:\s*(.+)$", skill_text, flags=re.MULTILINE)
    assert match, "SKILL.md must declare Current sites"
    return set(re.findall(r"`([^`]+)`", match.group(1)))


def test_current_sites_match_adapter_files() -> None:
    reference_sites = {
        path.stem for path in (ROOT_DIR / "references" / "adapters").glob("*.md")
    }
    script_sites = {
        path.name.removesuffix("_workflow.py")
        for path in (ROOT_DIR / "scripts" / "adapters").glob("*_workflow.py")
    }

    assert _current_sites() == reference_sites == script_sites


def test_workflows_use_the_shared_runtime_without_legacy_bootstrap() -> None:
    for path in (ROOT_DIR / "scripts" / "adapters").glob("*_workflow.py"):
        source = path.read_text(encoding="utf-8")
        assert "from scripts.workflow_runtime import" in source, path
        assert "scripts.adapter_runtime" not in source, path
        assert "prepare_task_book" not in source, path
        assert "add_session_tab_args" not in source, path
