# OpenCLI Capability Programme — Ticket Map
Programme Spec: GitHub Issue #1.

## Dependency graph

1. T0 冻结 Execution Baseline 并建立 integration branch。
2. T1 依赖 T0：以冻结 reference/target inventory 打通 Catalog seam。
3. T2 依赖 T1：以 Douban public read 打通 Command seam。
4. T3 依赖 T2：以 X timeline + article 长文打通 owned-tab/temporary-tab/browser evidence。
5. T4 依赖 T3：以 Douban photos 打通 bounded/resumable download。
6. T5a 依赖 T4：完成 shared Foundation Contract Gate。
7. T5 依赖 T1–T4、T5a：完成 Foundation Pass 和 independent verification。
8. T6 依赖 T5：迁移 ChatGPT `ask`/`batch-ask` Write Safety tracer。
9. T7 依赖 T5：执行当前 13 站 Access Preflight，确定 Wave 1 Batch 1 是否可以生成站点 tickets。

T0–T5 是串行 Foundation。T6 和 T7 在 T5 后可并行，但 T6 只运行 dry-run，T7 只读。本轮不创建 Wave 1 site implementation tickets；只有 T7 产出通过的 preflight 后才能生成。

## Global execution rules

- 每张票一个 owner；Foundation 与 shared runtime 串行。
- Owner 先写 failing test，不 commit；Catalog Integrator 审查 diff/test/evidence 后做 atomic commit。
- 不触碰 ticket 未声明的文件，不引入 dependency，不做 drive-by refactor。
- 每张票继承 Reference Baseline `6129bb3953d5eebd8dd67f96802b320c723f50ca`；Execution Baseline 由 T0 填入后，其他票才能进入 `ready-for-agent`。
- 真实 smoke 只保存红化 evidence；diagnostics 保持 ignored。任何 CAPTCHA、MFA、rate limit 或 risk control 立即停止。
