# T5 — Foundation integration gate 与 independent verification
## Objective

将 T1–T4 的 tracer 收敛为可供所有站点使用的 Foundation，通过明确 Foundation Pass，但不发布 clean-break runtime。

## Blockers and ownership

- Blocked by: T1 #3, T2 #4, T3 #5, T4 #6, T5a #10.
- Owner role: Catalog Integrator；Verifier 必须是未实现 T1–T4 的独立模型。
- File Ownership: Foundation integration tests，canary configuration/template，generated catalog view，programme verification report。
- Prohibited: 新 site capability、general writes、legacy cutover/removal、dependency 新增。

## Required pass

- Catalog CLI 六个 interface focused tests。
- Strict schemas and serialization for Catalog Source, Result Envelope, Adapter Contract, Site Artifact refs, Download Manifest。
- Failure Reason → scheduler state mapping，包含 retry/waiting/blocked/failed。
- Preview Hash/idempotency primitive deterministic tests（尚不做真实 write）。
- owned-tab lifecycle、temporary-tab cleanup、atomic files。
- Canary harness 可表达 public HTTP、auth API、DOM、UI、temporary tab、download、User Gate、write dry-run；未在 tracer 中真实运行的 canary 标记 `not_run`，不伪造 pass。
- Full Deterministic Pass 零 failure/skip。

## Verification workflow

1. Integrator 逐 atomic commit 检查 scope，确认 site-specific logic 没进 shared modules。
2. 从 clean integration branch 一次运行 full offline suite，保存命令和结果。
3. 重跑 Douban public read、X timeline/long-form、Douban download canaries，检查 evidence freshness/privacy。
4. Independent verifier 重跑精简 fixture 和一次真实 canary，审查 rollback。
5. 产出 Foundation verification report，列出 pass/not_run/blocker 和实际 hashes。

## Acceptance and rollback

- [ ] Foundation Pass 每一条都有命令输出或红化 evidence。
- [ ] 没有 legacy runtime 被提前删除，没有对 released branch 切换。
- [ ] Catalog Source 是唯一事实源，generated view 无 diff。
- [ ] independent verifier 签署 pass，未验证 canary 保持 `not_run`。
- [ ] T6/T7 获得 Foundation commit hash。

Rollback 优先 revert 失败 tracer atomic commit；如 contract 边界错误，放弃 integration branch 并回到 T0 baseline。
