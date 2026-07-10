# T7 — 当前 13 站 Access Preflight 与 Batch 1 admission

## Objective

以只读方式核对 13 个当前站的 extension、owned-tab、public reachability、login state、permission、empty-state 和 risk-control，产出 capability-level preflight matrix 及 Assisted Smoke Window 需求，为 Wave 1 Batch 1 是否可生成站点 tickets 提供 gate。

## Blockers and ownership

- Blocked by: T5 / GitHub #7.
- Foundation implementation commits: `fab0324`, `9716cac`.
- Foundation verification report commit: `0c432dcc118a8486a77eb141712b30dcbf211c7c`.
- File Ownership: preflight runner/config/tests，13-site redacted preflight records，programme preflight report，Catalog Source 中 access/status/evidence 的 integrator update。
- Prohibited: 站点实现修复、login 表单填写、登出用户、cookie/credential 导出、CAPTCHA/MFA 绕过、真实 write。
- 本票是 read-only；任何站点 drift 只记录 blocker，不顺手修复。

## Matrix and procedure

- 使用 Programme Spec 的 13-site public/login groups，每个 capability 记录 `public`, `optional_login`, `required_login`, `permission`, `user_gate` 之一。
- 每站先检查 public/low-gate representative，再在已有 session 上执行 `whoami` 或最小 auth representative；不切换 profile 来“自愈”。
- 验证 explicit empty marker 时同时记录 URL、access state 和 container；不以空数组为 pass。
- 遇到 `needs_login/captcha/mfa_required` 保留同 owned tab，每站最多一个 waiting tab；遇到 risk control/rate limit 立即停该站。
- 证据只含 hashes、capability、红化 URL、login classification、count/schema assertions、typed reason 和 timestamp。

## TDD and live verification

1. Failing fixture tests: extension missing, session missing, public pass, required login, CAPTCHA, permission denied, explicit empty, unexplained empty, risk control, one-waiting-tab limit。
2. 实现只读 preflight runner，不执行 capability 的实际批量抓取。
3. 运行 full offline suite。
4. 在 Assisted Smoke Window 按站点逐个运行，任何需用户的步骤暂停等待，不代替用户操作。

## Batch 1 admission rule

JD、Taobao、Douban、Weibo 只有在以下条件均满足后才能生成 site implementation tickets：

- 每站至少一个 public/low-gate read 可真实 smoke；
- 需要登录的 capability 已分类为可用或有明确 Assisted Smoke Window；
- 无未解决 risk-control 会使整站不可验证；
- Reference/Execution/Foundation hashes 已记录；
- Site ticket 能对每个 capability 标记 executable 或 `waiting_user`，不使用 unknown。

## Acceptance and next handoff

- [ ] 13 站无 `not_run` 遗留，除非附带了已排期 Assisted Smoke Window 和 owner。
- [ ] 没有 credential/private content 进入仓库。
- [ ] waiting/blocked 都使用 typed reasons，无自由文本假 pass。
- [ ] Batch 1 结论是 `admitted` 或列出精确 blocker。
- [ ] 只在 `admitted` 后调用 To Tickets 生成 JD/Taobao/Douban/Weibo 站点票。

Rollback 为 revert preflight Catalog status/evidence commit；不影响站点远程状态，因为本票无 writes。
