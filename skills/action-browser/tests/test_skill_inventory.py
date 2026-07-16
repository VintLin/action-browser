from pathlib import Path
import re


ROOT_DIR = Path(__file__).resolve().parents[1]


def _current_sites() -> set[str]:
    skill_text = (ROOT_DIR / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^Current sites:\s*(.+)$", skill_text, flags=re.MULTILINE)
    assert match, "SKILL.md must declare Current sites"
    return set(re.findall(r"`([^`]+)`", match.group(1)))


def _candidate_sites() -> set[str]:
    skill_text = (ROOT_DIR / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^Expansion candidates.*?:\s*(.+)$", skill_text, flags=re.MULTILINE)
    assert match, "SKILL.md must declare Expansion candidates"
    return set(re.findall(r"`([^`]+)`", match.group(1)))


def test_current_sites_match_adapter_files() -> None:
    reference_sites = {
        path.stem for path in (ROOT_DIR / "references" / "adapters").glob("*.md")
    }
    script_sites = {
        path.name.removesuffix("_workflow.py")
        for path in (ROOT_DIR / "scripts" / "adapters").glob("*_workflow.py")
    }

    candidates = _candidate_sites()
    assert _current_sites() == reference_sites - candidates == script_sites - candidates


def test_workflows_use_the_shared_runtime_without_legacy_bootstrap() -> None:
    for path in (ROOT_DIR / "scripts" / "adapters").glob("*_workflow.py"):
        source = path.read_text(encoding="utf-8")
        if "from scripts.adapters.public_read_runtime import" in source:
            continue
        assert "from scripts.workflow_runtime import" in source, path
        assert "scripts.adapter_runtime" not in source, path
        assert "prepare_task_book" not in source, path
        assert "add_session_tab_args" not in source, path


def test_skill_documents_atomic_runner_for_reaped_daemons() -> None:
    skill_text = (ROOT_DIR / "SKILL.md").read_text(encoding="utf-8")
    status_text = (ROOT_DIR / "references" / "status-check.md").read_text(encoding="utf-8")
    lifecycle_text = (ROOT_DIR / "references" / "task-lifecycle.md").read_text(encoding="utf-8")

    for text in (skill_text, status_text, lifecycle_text):
        assert "scripts/actionbook_task.py" in text
    for text in (skill_text, status_text):
        assert "SESSION_NOT_FOUND" in text
        assert "持久 PTY" in text
        assert "可能出现 User Gate" in text


def test_extracted_extension_directory_is_ignored() -> None:
    gitignore = (ROOT_DIR.parents[1] / ".gitignore").read_text(encoding="utf-8")
    assert "/skills/action-browser/actionbook-extension-v0.5.0/" in gitignore
