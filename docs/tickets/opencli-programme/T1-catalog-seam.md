# T1 — Foundation tracer: 打通 Catalog seam
## Objective

从冻结 OpenCLI manifest 和 action-browser inventory 生成第一个可验证 Catalog Source、normalized diff 和 Markdown View，覆盖 13 个当前站，并使 conflict/field gap 以 typed record 阻塞。

## Blockers and ownership

- Blocked by: T0 / GitHub #2.
- Capability IDs: `programme.catalog.capture.read`, `programme.catalog.inventory.read`, `programme.catalog.diff.read`, `programme.catalog.render.read`, `programme.catalog.validate.read`.
- File Ownership: 新的 `scripts/catalog/`, `schemas/catalog/`, `catalog/`, `tests/catalog/` 及 generated catalog Markdown View。
- Prohibited: 站点 workflow、scheduler runtime、browser session runtime、site docs。
- 不新增 dependency；使用 Python standard library 和仓库已有工具。

## Reference Evidence

- OpenCLI `cli-manifest.json` at Reference Baseline 是 inventory authority。
- OpenCLI `clis/<site>/` 提供 semantics，`*.test.js` 提供 verified edges，`docs/adapters/browser/` 提供 intent。
- action-browser `SKILL.md`, adapter scripts, adapter references 和 skill inventory test 是 target inventory authority。

## Contract

- 实现 spec 定义的六个 `catalog` CLI interface。
- Catalog Source 必须严格验证 top-level/Capability Record schema，unknown fields 失败。
- `x` 以 `twitter` 为 alias，`zhipin` 以 `boss` 为 alias，不创建重复 site。
- Feishu 是 Native/Exclusive，reference fields 为空且必须有原因。
- Output 必须包含 spec 的 13-site gap 矩阵，并将 10 个缺失 focused-test 站点标记为未验证。

## TDD and verification

1. 用精简 manifest/target Synthetic Fixtures 写 failing tests：alias normalization、read/write/login/utility 分类、duplicate id、conflict、required field gap、deterministic render。
2. 实现最小 parser/normalizer/validator/renderer。
3. 在冻结 baseline 上运行 capture + inventory + diff + validate + render 两次，忽略 `generated_at` 后结果 byte-stable。
4. 运行 catalog focused tests 和完整 offline suite。

## Acceptance and handoff

- [ ] 13 current sites 均只有一个 canonical record。
- [ ] Reference/Execution Baseline hashes 出现在 source 和 generated view。
- [ ] 每个 capability 有 access/effect/strategy/limits/fields/status/evidence slots。
- [ ] conflict 和 field gap 使 `validate` 非零退出，不产生假 parity。
- [ ] generated Markdown 无人工事实来源。
- [ ] Capability Verifier 独立重跑 fixture 和 baseline generation。

Rollback 为 revert T1 atomic commit；不影响现有 site runtime。
