# OpenCLI 网站能力覆盖计划（Programme Spec）

## Problem Statement

action-browser 已经能在真实浏览器中操作 14 个网站，但各站点的命令语义、输出契约、错误分类、测试深度和真实站点证据不一致。OpenCLI 在冻结版本中提供了更广的网站能力参考，但它的命令名、TypeScript 运行时、Cookie 模型、输出形式和读写混合范围不是 action-browser 可以机械复制的目标。

本计划要建立可重复的能力盘点、迁移、验证和维护流程：先使 13 个重叠站点达到 OpenCLI 参考 read 能力的完整覆盖，同时保留并验证 action-browser 的 Native Capabilities；Feishu 作为第 14 个 Exclusive Website 使用同样的契约和证据标准，但不伪造 OpenCLI parity。随后才依据明确评分引入缺失站点。

工作将交给多个模型执行，因此 spec 必须使 capability 边界、schema、access gate、fallback、限制、TDD 入口、smoke 证据、文件所有权、依赖和 rollback 可以被确定地执行，不允许代理自行缩小范围、新建第二套 contract、以“代码完成”代替真实验证，或对网站执行未授权写入。

## Solution

建立一个串行 Foundation Wave，从冻结的 OpenCLI Reference Baseline 和干净的 action-browser Execution Baseline 生成单一 Capability Catalog Source。Catalog 以用户可见的 Website Outcome 及 remote/local effect 对齐 Canonical Capability，不以文件数、命令名或参数数量对齐。只有 JSON Catalog Source 可编辑，人读 Markdown View 必须由它生成。

在专用 integration branch 上完成一次 clean break。每个 Canonical Command 只在 stdout 输出一个版本化 Result Envelope，并生成一个版本化 Adapter Contract 和零个或多个站点特定 Site Artifacts。日志只进 stderr。旧输出 writer、scheduler parser 和命令 alias 在切换前移除，不发布双写或双语义状态。

能力按风险和策略运行：公开静态/API 读取在足够时不获取 tab；依赖页面或登录态的 Browser Capability 继续使用 owned-tab lifecycle。每个 capability 只有一个 primary strategy 和有限、有类型、保持 schema 的 fallback chain，实际策略及切换原因必须出现在 contract 中。

交付顺序为 Foundation、ChatGPT Write Safety tracer、Wave 1 四个最多 4 站的 batch、Wave 2 首批 3 个新站 tracer，最后才是 General Write Wave。站点之间可并行，共享 runtime、catalog integration、batch regression 和 cutover 只能串行。

## User Stories

1. 作为 action-browser 用户，我希望当前站点提供所有等价 OpenCLI read outcome，以免为某个缺失读取命令切换工具。
2. 作为现有用户，我希望 Native Capabilities 被明确保留并达到同一验证标准，而不是在 parity 工作中消失。
3. 作为 Feishu 用户，我希望 inventory 和 download 继续被维护，但 catalog 不声称它来自 OpenCLI。
4. 作为用户，我希望列表产出 stable Item Identity 和 canonical URL，详情、comments、download 可直接使用该 identity。
5. 作为用户，我希望 reference-required 语义字段都存在，同时保留 action-browser 更丰富的站点字段。
6. 作为用户，我希望 public read 不必要时不打开 tab，需要登录的能力则复用我的现有浏览器上下文。
7. 作为用户，我希望 login、CAPTCHA、MFA、permission 和 risk control 使相关 capability 安全暂停，而不阻塞同站 public work。
8. 作为用户，我希望只有页面显式空状态才返回 `verified_empty`，无法解释的空数组要按失败处理。
9. 作为下载用户，我希望文件原子落盘、可续传、有 content-type/size 检查，并在媒体失败时保留已获得的 metadata。
10. 作为用户，我希望 count、pagination、scroll、retry、runtime 和 bytes 都有明确上限，遇到 rate limit 或 account challenge 立即停止。
11. 作为机器调用者，我希望 stdout 只有一个 JSON Result Envelope，不需要从 log 中猜测最后结果。
12. 作为 scheduler，我希望所有站点共用 Adapter Contract、Capability Status 和 Failure Reason，不解析自由文本。
13. 作为 scheduler，我希望实际 strategy、fallback reason、progress 和 artifacts 可追溯，避免隐式降级。
14. 作为维护者，我希望只编辑一个 JSON Catalog Source，所有 Markdown View、diff 和 ticket input 由它生成。
15. 作为维护者，我希望每次 Maintenance Cycle 冻结一个最新 OpenCLI commit，使执行期间的 scope 不漂移。
16. 作为维护者，我希望 manifest、source、test、site docs 的冲突显式阻塞，而不是由代理随机选一个。
17. 作为维护者，我希望 `x/twitter` 和 `zhipin/boss` 只产生一个 action-browser 站点记录。
18. 作为维护者，我希望 reference removal 发起 review 而不是自动删除仍有价值的 Native Capability。
19. 作为维护者，我希望新站点依据可重算 Priority Score 选择，不使用“看起来有用”的主观排序。
20. 作为维护者，我希望新站 tracer 证明站点 skeleton 后仍必须完成该站所有 reference reads，才宣告 support。
21. 作为隐私敏感用户，我希望仓库只保存红化后的结构断言和计数，不保存 cookie、账号、私信、购物车或私密截图。
22. 作为 Site Owner，我希望 ticket 提供 capability ids、field map、contract、access、strategy、limits、tests、smoke 和 rollback，无需重新阅读本次对话。
23. 作为 Site Owner，我希望文件所有权和禁止修改范围明确，使并行代理不触碰 shared runtime 或其他站点。
24. 作为 Site Owner，我希望按 reconnaissance → fixture → failing test → minimum implementation → docs/contract → smoke 的 TDD 顺序执行。
25. 作为 Capability Verifier，我希望每个 capability 有一个真实 smoke，parameter variants 以显式 equivalence classes 覆盖。
26. 作为 Capability Verifier，我希望我是独立且只读的，写操作仅验证 dry-run，真实写入需另行授权。
27. 作为 Catalog Integrator，我希望站点和 shared change 各自形成 atomic commit，回归时可与 catalog status 一起回退。
28. 作为 programme owner，我希望 Foundation 是硬前置，Wave 1 每 batch 最多 4 站，Wave 2 首批 3 站，后续 batch 最多 5 站。
29. 作为 programme owner，我希望长期决策保留在 Programme Spec/ADR，只为 Foundation 和下一个通过 preflight 的 batch 生成 Executable Tickets。
30. 作为可逆写操作的批准者，我希望默认 dry-run，只有显式 `--execute` 才改变网站状态。
31. 作为消息、发布或删除的批准者，我希望授权绑定完整 Preview Hash，批准后任何参数变化都使授权失效。
32. 作为 batch write 批准者，我希望有 `--max-actions`、逐项 checkpoint 和不重放已成功项的 idempotency 政策。
33. 作为 ChatGPT 用户，我希望现有 `ask` 和 `batch-ask` 先成为 Write Safety tracer，之后才开放其他站写能力。
34. 作为执行代理，我希望 spec/ticket 使用中文解释和精确 English identifiers，并只将确定可执行的 issue 标记为 `ready-for-agent`。

## Implementation Decisions

### 1. Baselines 与证据优先级

- 本计划的 Reference Baseline 是 OpenCLI commit `c1ad69676f220b5ef382bbf4c387a2486daf8355`，package `1.8.6`，包含 173 sites 和 1277 commands。它在本 cycle 内不变。
- 后续 cycle 只允许 `fetch --prune` remote refs，不对 OpenCLI worktree 执行 pull、checkout 或修改；冻结 remote default branch commit。离线使用 local HEAD 需用户明确确认。
- OpenCLI 证据顺序是 generated manifest → source semantics → tests 已证明的 edge → site docs intent → README navigation。实质冲突记录为 `reference_conflict` 并阻塞相关 capability。
- Execution Baseline 必须是一个已记录 commit 且 worktree clean。当前工作树因规划文档处于 dirty 状态，因此 Execution Baseline 尚未冻结，任何 implementation ticket 不得开始。

### 2. Canonical Capability 与 Catalog Source

Canonical intent vocabulary 限定为：

- Read: `list`, `search`, `recommend`, `trending`, `detail`, `comments`, `profile`, `whoami`, `history`, `notifications`, `stats`, `download`, `export`.
- Write: `create`, `update`, `delete`, `react`, `follow`, `message`, `publish`.

Capability id 格式为 `<site>.<resource>.<intent>.<effect>`，例如同一 `detail` intent 由 resource 区分 post、video、product 或 job。Alias、sort、count、filter、format 是 Parameter Variant；用户 outcome、remote effect 或 local artifact effect 不同才是独立 capability。`login` 是 Login Assistance，`whoami` 是 read，纯本地 helper 是 Utility Command。

Catalog Source 顶层 schema 必须包含：

| Field | 约束 |
|---|---|
| `schema_version` | 整数，当前 clean-break 版本 |
| `reference_baseline` | `repo`, `commit`, `version`, `captured_at` |
| `execution_baseline` | `commit`, `worktree_status`, `captured_at` |
| `generated_at` | UTC timestamp |
| `sites` | canonical site id、reference aliases、support state |
| `capabilities` | Capability Records |
| `exclusions` | candidate id、category、reason、evidence |
| `conflicts` | conflict id、type、evidence、resolution state |
| `maintenance` | previous baseline、next due、trigger |

每个 Capability Record 必须包含：`id`, `site`, `reference_aliases`, `resource`, `intent`, `effect`, `local_effect`, `description`, `source_commands`, `native`, `access_requirement`, `primary_strategy`, `fallbacks`, `parameters`, `equivalence_classes`, `semantic_fields`, `identity`, `limits`, `risk_tier`, `idempotency`, `status`, `priority_score`, `evidence`, `tests`, `docs`, `exclusion_reason`, `conflict_reason`。

`semantic_fields` 每项包含 `semantic`, `reference_fields`, `target_field`, `required`；`fallbacks` 每项包含 `strategy` 和允许触发的 `reasons`。缺少 required semantic 是 `field_gap`，不能通过保留一个相同命令名来视为 parity。

Foundation 必须提供下列稳定 CLI interface：

- `catalog capture-reference --repo <repo> --commit <hash>`
- `catalog inventory-target --execution-baseline <hash>`
- `catalog diff --reference <snapshot> --target <inventory>`
- `catalog validate --source <catalog>`
- `catalog render --source <catalog> --format markdown`
- `catalog maintenance-check --previous <snapshot> --current <snapshot>`

`capture-reference` 和 `inventory-target` 只读；`render` 不接受人工编辑的 Markdown 作为输入；`validate` 必须拒绝 unknown field、duplicate capability id、dangling evidence、非法 lifecycle transition 和不完整 field map。

### 3. Result Envelope、Adapter Contract 与 artifacts

Result Envelope 是 stdout 的唯一 JSON 对象，必须包含：`schema_version`, `run_id`, `task_id`, `capability_id`, `site`, `command`, `status`, `result_quality`, `contract_ref`, `artifact_refs`, `strategy_used`, `fallback_reason`, `failure`, `started_at`, `finished_at`。`failure` 为 null 或包含 `reason_code`, `message`, `retryable`。

Adapter Contract 必须包含：`schema_version`, `run_id`, `task_id`, `reference_baseline`, `execution_baseline`, `capability_id`, `site`, `status`, `stage`, `result_quality`, `requested_count`, `collected_count`, `access`, `strategy_used`, `fallback_reason`, `limits`, `artifacts`, `warnings`, `failure`, `progress`, `started_at`, `updated_at`, `finished_at`。`progress` 至少包含 `completed`, `requested`, `last_url`, `last_title`。

Download Manifest 每 item 必须包含：`item_identity`, `source_url`, `destination`, `media_type`, `expected_bytes`, `actual_bytes`, `checksum`, `status`, `attempts`, `resumed_from`, `failure_reason`；顶层记录 output root、item/total byte limits 和 aggregate outcome。先写临时文件，校验通过后 atomic rename。

Capability lifecycle 是 `discovered -> specified -> implemented -> verified | verified_empty`，side states 是 `waiting_user`, `blocked`, `excluded`, `deprecated`。`partial` 只能是站点/batch 聚合结果，不是 capability complete state。

### 4. Failure Reason taxonomy 和状态映射

| Group | Codes |
|---|---|
| usage/config | `invalid_input`, `unsupported_capability`, `config_error` |
| catalog | `reference_conflict`, `native_conflict`, `field_gap`, `schema_mismatch` |
| access | `needs_login`, `captcha`, `mfa_required`, `permission_denied`, `risk_control` |
| browser | `extension_unavailable`, `session_unavailable`, `tab_lost`, `ownership_mismatch`, `navigation_failed`, `page_not_ready`, `selector_failed` |
| transport | `timeout`, `network_error`, `api_failed`, `rate_limited` |
| artifact | `download_failed`, `content_type_mismatch`, `size_limit_exceeded`, `storage_failed` |
| write | `preview_required`, `preview_hash_mismatch`, `execute_not_authorized`, `impact_limit_exceeded`, `uncertain_write_outcome` |
| lifecycle | `interrupted`, `internal_error` |

`needs_login`, `captcha`, `mfa_required` 映射 `waiting_user`；`permission_denied`, `risk_control`, catalog conflicts，以及 preflight 后仍无法使用的 extension/session 映射 `blocked`。`timeout`, `network_error`, `api_failed`, `navigation_failed`, `page_not_ready`, `selector_failed` 只能在幂等 read 上同 tab 最多自动重试 2 次；`rate_limited` 不自动重试。写操作按 Idempotency Policy 决定，`uncertain_write_outcome` 必须先 read-back 再等待用户。Numeric exit code 仅是上述 typed reason 的次级映射。

### 5. 当前 14 站能力差距

下表是 Reference Baseline 的 read 命令对当前 action-browser inventory 的规范化输入。命令不等同 capability；Site ticket 仍需从 source/tests 完成 Semantic Field Map。

| Site | Reference read inputs | 当前明确 gap/conflict | Native/utility 要求 | Focused test |
|---|---|---|---|---|
| `bilibili` | comments, download, dynamic, feed, feed-detail, following, history, hot, me, ranking, search, subtitle, summary, user-videos, video, whoami | download, feed-detail, whoami | 保留现有详情/动态结构 | 缺失 |
| `chatgpt` | deep-research-result, detail, history, new, project-list, read, status, whoami | deep-research-result, new, project-list, status, whoami；`list/export` 需规范化 | ask, batch-ask 为 write tracer | 已有，需 contract/safety 扩展 |
| `douban` | book-hot, download, marks, movie-hot, photos, reviews, search, subject, top250, whoami | whoami；photos view/download 需分离 | 保留 marks/reviews 富字段 | 缺失 |
| `douyin` | activities, collections, drafts, hashtag, location, profile, search, stats, user-videos, videos, whoami | search, whoami | 保留 creator-oriented 输出 | 缺失 |
| `feishu` | 无 reference | 无 parity，只做 common contract | inventory, download；verify 是 utility | 缺失 |
| `jd` | cart, detail, item, reviews, search, whoami | item/detail 语义需 clean-break 定义 | 保留产品/评论字段 | 缺失 |
| `taobao` | cart, detail, reviews, search, whoami | read inputs 齐全，但需新 schema | 保留已有 contract 作 prior art，不保留 legacy writer | 已有 |
| `weibo` | comments, favorites, feed, hot, me, post, search, user, user-posts, whoami | me/whoami 需规范化 | home/profile/download 按 outcome 保留 | 缺失 |
| `x` (`twitter`) | article, bookmark-folder(s), bookmarks, device-follow, download, followers, following, likes, list-tweets, lists, notifications, profile, search, thread, timeline, trending, tweets, whoami | article、bookmark folders、follow graph、likes、lists、notifications、trending | home/me 规范化；view/download 分离 | 已有，需扩展 |
| `xiaohongshu` | comments, creator-note-detail, creator-notes, creator-notes-summary, creator-profile, creator-stats, download, draft-open, drafts, feed, liked, note, notifications, saved, search, user, whoami | comments、creator suite、drafts、notifications | favorites/likes/profile/me 规范化 | 缺失 |
| `youtube` | channel, comments, feed, history, playlist, search, subscriptions, transcript, video, watch-later, whoami | whoami | 保留 transcript/download 分离 | 缺失 |
| `zhihu` | answer-comments, answer-detail, collection(s), download, followers, following, hot, pins, question, recommend, search, user, user-answers, user-articles, whoami | answer-comments、follow graph、pins、user suite、whoami | 保留问答/专栏 artifacts | 缺失 |
| `zhipin` (`boss`) | chatlist, chatmsg, detail, joblist, recommend, resume, search, stats, whoami | joblist, resume, stats, whoami | crawl 按 outcome 归并；filters 是 utility | 缺失 |

当前只有 ChatGPT、Taobao 和 X 具备站点行为 focused tests；其余 10 站必须在实现前先增加失败测试。Taobao 现有 summary/progress contract 只是 prior art，不是 clean-break schema 的保留要求。

所有 listing 的最小 semantic groups 是 identity、title/name、canonical URL、author/owner（如适用）、published/updated time（如适用）、summary/status 和 pagination cursor。Detail 必须添加 full content/body、engagement/price/job metadata 等 reference-required groups。具体 reference field → target field 对映由各站 ticket 从冻结 source/tests 记录，并由 catalog validation 检查 required 缺失。

### 6. Wave 1 精确批次与依赖

1. `Foundation` 串行：Catalog seam、Command seam、schemas、failure mapping、fixtures/smoke template、write-safety primitives、privacy rules、canary harness。
2. `ChatGPT Write Safety tracer` 串行且依赖 Foundation：`ask`/`batch-ask` 默认 dry-run、Preview Hash、`--execute`、`--max-actions`、idempotency 和 post-write verification contract。Verifier 不执行真实写入。
3. `Wave 1 / Batch 1`：JD、Taobao、Douban、Weibo。用较接近 parity 的商品/内容站证明 contract、identity、public/auth split。
4. `Wave 1 / Batch 2`：Bilibili、YouTube、Zhihu、Feishu。证明长内容、subtitle/transcript、comments、download 和 Exclusive Website 维护。
5. `Wave 1 / Batch 3`：Douyin、Zhipin、ChatGPT。证明 creator/job/auth-heavy reads，并完成 ChatGPT 全部 reference reads。
6. `Wave 1 / Batch 4`：X、Xiaohongshu。最后处理 gap 最大、UI 变动和风控更高的社交站。

每个 batch 依赖前一 batch 的 catalog integration、完整 deterministic suite、affected smoke 和独立 verification。不得同时开始下一 batch 来掩盖未解决 regression。

### 7. Wave 2 评分、排除与首批提案

Priority Score 按下式计算并 clamp 到 0–100：

`demand 0–30 + browser/auth value 0–20 + reference maturity 0–20 + smoke feasibility 0–15 + ecosystem fit 0–15 - complexity 0–10 - risk 0–10`。

Demand 在未有用户硬指定时使用仓库请求/用例证据并记录为 neutral assumption；reference maturity 使用 read 数、source/tests/docs 完整性；不允许手工直接改 final score 而不改分项和证据。

排除项包括：桌面 app adapters（例如 `chatgpt-app`, `discord-app`, `doubao-app`）；internal/shared modules（例如 `_shared`, `_atlassian`）；没有 Website Outcome 的独立 developer/data APIs（例如 `rest-countries`, `openfda`）。有网站 outcome 但 primary strategy 是 public API 的 adapter 不因 API 而被排除。

本 baseline 的首批提案如下（用户 demand 暂按 neutral 证据计分）：

| Rank | Site | Demand | Browser value | Maturity | Smoke | Fit | Complexity | Risk | Final | Tracer |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | Reddit | 24 | 20 | 20 | 11 | 15 | 8 | 7 | 75 | public `read` + authenticated `saved` |
| 2 | Weread | 22 | 18 | 20 | 12 | 14 | 7 | 5 | 74 | public `search` + authenticated `shelf` |
| 3 | 51job | 20 | 17 | 16 | 13 | 14 | 4 | 5 | 71 | `search` → stable job identity → `detail` |

Reddit 有 15 reads 和广泛 focused reference tests，能验证社交 feed/detail/comments 及 login split。Weread 有 10 reads、public/cookie 混合策略和完整 tests/docs，能验证书籍、书架、笔记及站内搜索。51job 只有 4 reads 但完整覆盖 company/job/search/hot，能以较小范围验证招聘域且与 Zhipin 形成可比较的第二实现。GitHub 在本 baseline 只有 `whoami` 一个 read，不适合首批 tracer；DeepSeek 与 ChatGPT 重叠较高，V2EX 价值可观但不如前三对新站 skeleton 的证明组合完整。

### 8. Access Preflight 和 Assisted Smoke Window

当前所有 preflight 都是 `not_run`，因为 Execution Baseline 尚未冻结。这不是默认通过。

| Site | Public/low-gate group | Login/permission group | Window |
|---|---|---|---|
| Bilibili | hot, ranking, search, video, comments, subtitle, summary | feed, dynamic, history, following, whoami, download | required |
| ChatGPT | status 可先检查 | history/detail/read/project/deep-research/whoami/new；write tracer | required |
| Douban | search, rankings, subject, photos, download | marks, reviews, whoami | required |
| Douyin | search, hashtag, location, public profile/video 尝试 | creator data, drafts, activities, collections, stats, whoami | required |
| Feishu | none assumed | inventory, download, permission scopes | required |
| JD | search, item/detail, reviews | cart, whoami | required |
| Taobao | search/detail/reviews 仍可能触发 gate | cart, whoami | required |
| Weibo | hot, post, user, search, comments | feed, favorites, me/whoami | required |
| X | public tweet/thread/profile/search/trending/article 尝试 | home, bookmarks/folders, likes, lists, notifications, follow graph, whoami | required |
| Xiaohongshu | note/user/search 可尝试 | feed, saved, liked, creator, drafts, notifications, whoami | required |
| YouTube | search, video, transcript, comments, channel, playlist | history, watch-later, subscriptions, whoami | required |
| Zhihu | hot, search, question, answer, user/comments | recommend, collections, follow graph, whoami | required |
| Zhipin | search/detail 可尝试 | recommend, chats, resume, stats, whoami | required |

Preflight 只读检查 extension availability、owned-tab 能力、login state、permission、empty-state 和 risk-control；不登出现有账号来制造 gate。User Gate canary 只在隔离的未登录测试 profile 中运行；未提供时保持 `not_run`，不以模拟证据替代真实 gate。每站最多保留一个 waiting owned tab。

Assisted Smoke Window 集中处理登录、MFA、permission 和经用户单次授权的写验证。无人时段先完成 fixture、focused tests 和 public smoke；等待窗口的 capability 为 `waiting_user`，不阻塞无关 public capabilities。

### 9. Canary Matrix 与证据

| Strategy/risk | Canary | 必须断言 |
|---|---|---|
| public HTTP | Douban `top250`/`search` | no tab acquired, fields, limit, stable identity |
| authenticated same-origin API | Bilibili `history` | owned session, auth classification, pagination stop |
| DOM extraction | X `timeline` | correct owned tab, visible container, stable identities |
| UI-driven read | ChatGPT `history` → `detail` | navigation, conversation identity, full visible content |
| temporary tab | X `article`/long-form expansion | temporary tab closes, expanded full text stored, parent tab preserved |
| download | YouTube transcript 或 Douban photos | manifest, type/size, atomic file, resume semantics |
| User Gate | isolated unauthenticated profile | `waiting_user`, same tab retained, no bypass |
| write safety | ChatGPT `ask` dry-run | no remote change, Preview Hash stable, execute absent |

每个 Smoke Evidence record 使用 `<cycle>/<site>/<capability>/<timestamp>` 逻辑 key，只保存 baseline hashes、capability id、红化 URL、requested/collected counts、schema assertions、strategy、status、failure reason 和 timestamp。Read evidence 90 天过期，write/high-risk UI 30 天过期；观察到 UI/API drift 立即失效。富诊断产物必须本地 ignore 且有到期删除规则。

### 10. Write Safety

- 所有 writes 进 catalog，但 General Write Wave 只在 Foundation、ChatGPT tracer 和当前 14 站 Site Read Completion 全部通过后开始。
- Reversible write 默认 dry-run，真实执行需 `--execute`。Communication/publication/destructive write 还需批准包含所有影响参数的 Preview Hash。
- Batch write 必须指定 `--max-actions`，逐项记录成功/失败/checkpoint。已成功项不重放。
- 每个 write 声明 Idempotency Policy。非幂等 send/post 在 timeout 后不盲目 retry；先 read-back，无法确认则返回 `uncertain_write_outcome`。

### 11. Cutover、并行与 rollback

1. 从干净 Execution Baseline 创建专用 integration branch；当前 released branch 继续使用旧 contract。
2. Foundation 作为一个可独立 revert 的 shared commit 落在 integration branch，不单独发布。
3. ChatGPT tracer 和 Wave 1 站点以 atomic site/ticket commits 依次集成。Site Owners 不 commit；Catalog Integrator 审核 scoped diff 后 commit。
4. 最后 cutover ticket 移除 legacy output writers、aliases 和 scheduler parsing path，生成 Catalog Views，通过 Foundation Pass、Wave 1 Read Pass、Full Deterministic Pass、Full Current-site Smoke Pass 和 independent review。
5. 只有上述全部通过后，才以一次 merge 切换。切换前 rollback 是 revert 失败 atomic commit 或放弃 integration branch；切换后 rollback 是 revert merge commit 并恢复上一 release tag。Catalog status 必须同步回退。

Parallelism 只在同 batch 的不同站点之间开放。每站一个 Site Owner，ticket 声明精确 File Ownership 并禁止 shared runtime/catalog/cross-site docs。依赖增加由独立 shared ticket 处理；只有三个已验证的 site-neutral repetition 才允许提取 shared abstraction。

### 12. Deterministic pass definitions

- `Foundation Pass`：Catalog CLI 六个 interface 的 focused tests，schema validation，Result Envelope/Adapter Contract serialization，Failure Reason/state mapping，Preview Hash/idempotency，download atomic/resume，owned-tab lifecycle 和 Canary harness 的所有 deterministic tests 通过。
- `Site Read Pass`：该站 catalog 内每个 reference read 和 retained Native read 处于 `verified`/`verified_empty`，focused tests、field map、contract、docs、有效 smoke 全部存在，无 unresolved conflict。
- `Wave 1 Read Pass`：14 个当前站全部达到 Site Read Pass，Feishu 以 Native read 规则计算。
- `Full Deterministic Pass`：仓库全部 offline tests 一次运行零 failure/skip；与浏览器环境无关的测试不得 xfail。
- `Affected Smoke Pass`：变更的每个 capability 都有当前 baseline 上的有效真实 smoke，shared change 还要通过 Canary Matrix。
- `Full Current-site Smoke Pass`：14 站每个 Canonical Read Capability 都有未过期 evidence，或是有记录 Assisted Smoke Window 的 `waiting_user`；cutover 时不允许 `waiting_user`，必须最终验证或显式从本 release 排除并重新审批 scope。
- `Major Runtime Pass`：Full Deterministic Pass + 全 Canary Matrix + 所有受共享 runtime 路径影响站点的 affected smoke。

## Testing Decisions

两个稳定测试 seam 是 Catalog seam 和 Command seam。Catalog seam 接收冻结 OpenCLI manifest snapshot 和 action-browser inventory，输出 Catalog Source、normalized diff 和 generated View。Command seam 接收 Canonical Command invocation，输出 Result Envelope、Adapter Contract 和 Site Artifacts。Synthetic Fixture 和 real HTTP/ActionBook smoke 必须走同一 seam，不建立 test-only entrypoint。

现有稳定 prior-art modules/interfaces 如下，Foundation 先为它们定义 clean-break replacement 而不是新建平行 runtime：

- `ActionBookSession`, `require_owned_task_tab`, `tab_mutation_lock`, `temporary_tab`, `write_json_atomic` 约束 tab ownership、mutation serialization、cleanup 和 atomic files。
- `SchedulerStore`, lifecycle/reconcile/contracts interfaces 约束 queued/running/waiting-user/blocked/completed/failed/canceled 状态与持久化。
- Taobao contract tests 证明 summary/progress artifact 入口，但其 legacy records/writer 必须在 cutover 移除。
- X focused tests 证明 owned tab、User Gate、page-ready 和长文 `show more` 语义；长文验收必须点击展开，保存展开后的全文，并以展开控件消失/全文容器存在作为 smoke assertion，不能只清除 warning。
- ChatGPT focused tests 证明对话提交和 web-search state，Write Safety tracer 需在同一 Command seam 增加 dry-run/approval/idempotency 断言。
- E2E smoke helper 和 scheduler CLI tests 作为完整入口先例；新 harness 不得继续依赖“从混合 stdout 提取最后 JSON block”。

每个 capability 按固定 TDD 顺序执行：只读 reconnaissance；最小、可读、无敏感信息 Synthetic Fixture；先观察到 failing focused test；最小 passing implementation；更新 docs/schema/contract；通过 Command seam 运行真实 smoke；交给独立 Capability Verifier。Parameter combinations 必须在 ticket 中列出 equivalence classes，不用全组合穷举。

Focused tests 完全离线，不保存 private response dump 或 full HAR。`verified_empty` 测试必须同时断言正确 URL、access state、expected container 和显式 empty marker。每 batch 运行 Full Deterministic Pass；site change 运行 affected capability smoke；shared-runtime change 运行 Major Runtime Pass。每月 maintenance 至少每 Supported Website 一个 canary。

## Out of Scope

- 与 OpenCLI command names、arguments、stdout format、exit numbers、TypeScript runtime 做一对一兼容。
- 不经 Canonical Capability 规范化就机械迁移所有 OpenCLI directories/commands。
- 桌面 app adapters、internal modules 和没有 Website Outcome 的 standalone developer/data APIs。
- 自动建号、导入凭据/cookies、填写登录表单、解 CAPTCHA/MFA 或绕过 risk control。
- 无界 crawl、stealth、自动规避 rate limit 或默认领养其他 session/tab。
- 没有每次用户明确授权的真实 write smoke。
- 在 Foundation、ChatGPT tracer 和当前站 reads 完成前实现 General Write Wave。
- 将所有业务 payload 压成一个 universal schema。
- Runtime compatibility layer、dual writer、legacy command alias 或 online historical artifact migration。
- 由某个 Site Owner 引入站点专用 dependency 或未满三次重复就抽象 shared framework。
- 为所有 Candidate Websites 和未来 Maintenance Cycles 预先生成巨大 ticket backlog。
- 在并发资源、Access Preflight 和 Assisted Smoke Windows 未知时承诺日历时间。
- 因 OpenCLI 后续删除某能力而自动删除 action-browser 行为。
- 提交 cookie、credential、账号身份、私信、购物车、私密页截图或未红化 diagnostics。

## Further Notes

- 本 spec 的 normative inputs 是项目 glossary、ADR 0001–0021 和 grilling handoff；实现时如发现 repo truth 与 spec 冲突，不得自行选择，必须记录 `native_conflict` 并返回 programme owner。
- Capability Catalog 第一次生成会产出每个站点的完整 Semantic Field Map。本 spec 给出必需 schema 和差距范围，不以手工复制 1277 条 manifest 取代 generator。
- 旧的中国站点 partial-gap plan 已删除，不再是 programme guidance。
- 下一阶段只为 Foundation、ChatGPT tracer 和通过 Access Preflight 的 Wave 1 Batch 1 生成 tickets。因当前 Execution Baseline 未冻结，site implementation tickets 必须带 blocker，不能被标为可立即执行。
