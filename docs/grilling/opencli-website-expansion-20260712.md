# OpenCLI Website Expansion — Grilling Handoff

状态：已完成 grilling，已进入实现；当前交付仍受 Batch 2 浏览器 User Gate 阻塞。

## 目标

为 action-browser 增加当前未支持的 OpenCLI 参考网站能力。已存在的 `youtube`、`reddit`、`x` 不重复实现。

## 已确认决策

1. 本次支持定义为：完成 OpenCLI Reference Baseline 对应的完整只读能力，并通过 focused tests、Adapter Contract、Result Envelope 和真实浏览器 smoke。
2. 本次不新增发帖、评论、点赞、私信等 Write Capability。
3. `google` 仅包含 Google Search、News、Suggest、Trends；`google-scholar`、`gemini`、`notebooklm` 不纳入本次范围。
4. `github` 纳入当前账号读取和公开 Trending 仓库读取；`github-trending` 归入同一个 `github` adapter，不扩展到仓库、Issue、PR 或代码搜索。
5. 新增范围为六个站点：`google`、`github`、`stackoverflow`、`hackernews`、`wikipedia`、`linkedin`。
6. 六个站点作为一个需求集合记录，但按最多四个站点一批交付；第一批为 `google`、`stackoverflow`、`hackernews`、`wikipedia`，第二批为 `github`、`linkedin`。
7. `linkedin` 纳入 OpenCLI 的私有只读能力，包括消息、个人分析、Sales Navigator 和个人资料详情；登录、MFA、验证码和风控继续使用现有 User Gate，不自动输入凭据或绕过门禁。
8. 只实现 OpenCLI Reference Baseline 中的只读能力；额外能力另行登记为 `Native Capability`。
9. 实施前只读刷新 OpenCLI 远端默认分支并冻结新的 Reference Baseline，不继续直接使用旧的 `1.8.6 / 6129bb39` 快照。
10. 若 `linkedin` 无法完成真实 smoke，保持对应 capability 为 `waiting_user` / `blocked`；不影响第一批公共站点，但第二批不能宣称完成。
11. 修正现有文档中“当前 13 个站点 / 12 个重叠站点”的过期数量，使其与实际 14 个 adapter 一致，并明确本次只新增六个站点。
12. 新站点 canonical website ID 为 `google`、`github`、`stackoverflow`、`hackernews`、`wikipedia`、`linkedin`；已有站点继续使用 `youtube`、`reddit`、`x`。
13. 新站点沿用当前 `<site> <resource> <intent>` 命令形态，按用户结果命名，不复制 OpenCLI 的命令、参数、表格输出或运行时。
14. 过期数量只修正当前有效的 spec、handoff、ticket README 和相关 ADR 引用；历史归档不改，本 handoff 作为本次扩展的事实源。
15. 若无法刷新 OpenCLI Reference Baseline，停止在待刷新状态，不使用旧快照实现；除非另行明确授权。
16. 验收按 capability 闭环，每个 capability 都需要 focused test、契约验证和独立真实 smoke；参数组合使用明确的 equivalence class。

## 当前事实

- 当前 adapter：`bilibili`、`chatgpt`、`douban`、`douyin`、`feishu`、`jd`、`reddit`、`taobao`、`weibo`、`x`、`xiaohongshu`、`youtube`、`zhihu`、`zhipin`。
- 当前站点索引位于 `skills/action-browser/SKILL.md`，站点文档和 workflow 分别位于 `references/adapters/<site>.md` 与 `scripts/adapters/<site>_workflow.py`。
- 项目现有 ADR 已规定只读优先、用户门禁、单一 Result Envelope、Capability Catalog、真实 smoke 和按站点并行边界。
- 本次决策沿用 ADR 0001、0002、0005、0008、0009、0010、0012、0018、0020、0021，不新增与其冲突的架构规则。
- OpenCLI 远端已刷新到 `c1ad69676f220b5ef382bbf4c387a2486daf8355`；Batch 1 已完成 26/26 smoke，GitHub `trending` 与 `whoami` 已完成，LinkedIn 21 个 read capability 仍为 `waiting_user`。

## 实现后的待办

- 恢复 ActionBook/Chrome 会话后，执行 GitHub `whoami` 与 LinkedIn 21 个 read capability 的 assisted smoke。
- 为六个候选站点补齐以参考字段为依据的 semantic catalog records，再将已满足闭环的站点从 `Expansion candidates` 提升为当前 Supported Website。
