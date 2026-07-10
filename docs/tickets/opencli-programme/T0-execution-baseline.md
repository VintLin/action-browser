# T0 — 冻结 Execution Baseline 并建立 integration branch
## Objective

在不丢失任何用户更改的前提下，将当前 Programme docs 和 tracker setup 变更审核、落盘，获得一个 worktree clean 的 action-browser commit，并从它建立专用 clean-break integration branch。

## Non-goals

- 不实现 catalog、schema 或站点能力。
- 不改写、删除或 stash 未经识别的用户更改。
- 不 push/merge，除非用户另行明确授权。

## Baselines and blockers

- Reference Baseline: `6129bb3953d5eebd8dd67f96802b320c723f50ca`.
- Execution Baseline: 本票产出。
- 当前 blocker: `.gitignore`, `AGENTS.md`, `CONTEXT.md`, `docs/` 尚未被审核为已落盘 baseline。
- 需要用户授权 commit 后才能完成本票的 clean commit。

## File Ownership

- 允许：本计划已新增/修改的 tracker、glossary、ADR、grilling、spec、ticket 文档和 `.gitignore`/`AGENTS.md` setup 片段。
- 禁止：`scripts/`, `tests/`, `references/adapters/`, `assets/` 和所有无关 dirty/untracked files。

## Execution steps

1. 记录当前 HEAD、branch、remote 和 `git status --short`。
2. 逐文件审核 planning/setup diff，确认 `/docs` 完整允许跟踪，但 runtime outputs 仍不应被意外提交。
3. 获得用户 commit 授权后，只 stage 上述 File Ownership 内文件，创建一个 planning baseline commit。
4. 确认 worktree clean；将 commit hash 写入 Catalog/Programme 所需 Execution Baseline 记录。
5. 从该 commit 建立 `codex/opencli-capability-integration` integration branch。

## Verification

- `git diff --check` 零输出。
- `git status --short` 在 baseline 时零输出。
- `git rev-parse HEAD` 与记录的 Execution Baseline 一致。
- `git branch --show-current` 是专用 integration branch。
- 再次检查 OpenCLI worktree 未被修改。

## Acceptance and rollback

- [ ] 没有未授权文件被 stage/commit。
- [ ] worktree clean，Execution Baseline hash 可重现。
- [ ] integration branch 仅指向 baseline，尚无 implementation change。
- [ ] 产出给 T1 的 baseline handoff：commit、branch、status 输出。

Rollback 是删除尚未推送且无新 commit 的 integration branch；不 reset planning baseline commit。
