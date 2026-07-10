# AGENTS.md

## Syncing Skill Changes

When syncing updates from another copy of this skill into this project:

1. Check both worktrees first: `git status --short` in the source skill and this project.
2. Compare source and target files before editing. Prefer file-level diffs for changed docs/scripts, and ignore runtime outputs such as `__pycache__/`, `.pytest_cache/`, `logs/`, `diagnostics/`, extracted extension folders, and backup files.
3. Merge only the changed skill content that still applies here. Do not mirror-delete target files just because the source copy lacks them; this project may have newer tests, docs, or helper modules.
4. Preserve existing local architecture and behavior unless the source change directly updates it.
5. Run the smallest relevant verification after merging, then report the exact commands and results.

## Agent skills

### Issue tracker

Use GitHub Issues in `VintLin/action-browser`; external pull requests are not a triage request surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five canonical labels `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository: read the root `CONTEXT.md` and relevant decisions under `docs/adr/`. See `docs/agents/domain.md`.
