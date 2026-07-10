# T3 — Foundation tracer: X owned-tab read 与长文全文
## Objective

以 `x.timeline.list.read` 和 `x.article.detail.read` 打通 Browser Capability：复用指定 owned tab，前 5 条 timeline 结果产生 stable identity，article 使用 temporary tab，显式点击长文展开并保存展开后的全文。

## Blockers and ownership

- Blocked by: T2 / GitHub #4.
- File Ownership: X workflow/reference，X fixtures/focused tests，Browser Command seam adapter glue，X smoke evidence。
- Prohibited: shared session internals（除非先拆出独立 shared blocker ticket）、其他 sites、catalog generator。
- Access Preflight: 要求用户已登录的 X tab；如不满足返回 `waiting_user/needs_login`，不绕过。

## Commands and field map

- Timeline: `python3 scripts/action_browser.py run --site x --resource timeline --intent list --limit 5 --task-id <id> --session <id> --tab <id> --output-root <root>`.
- Article detail: 使用 timeline 输出的 Item Identity 调用 `--resource article --intent detail --item-id <id>`。
- Timeline required fields: post identity, canonical URL, author identity/name, text preview, timestamp, engagement fields available in reference semantics, content type/long-form marker。
- Scope decision: OpenCLI exposes author `bio`; this DOM tracer does not open one profile page per timeline author, so `bio` is explicitly non-tracer and must remain unmapped rather than synthesized.
- Article required fields: identity, canonical URL, title, author, published time, full expanded text, referenced media/links。
- Primary strategy: DOM extraction in owned tab；article 使用 temporary tab。Fallback 只允许已在 catalog 登记的 typed strategy，本 tracer 不隐式加 API fallback。

## TDD and smoke

1. 保留现有 `show more` 控件识别 prior art，新增 failing tests：真控件、链接省略号误报、点击后全文、展开失败、temporary-tab cleanup、parent tab preservation。
2. 首页/timeline 取前 5 条，对其中最多 2 条 long-form 运行 article detail。
3. 长文必须实际点击展开；验收断言是展开控件消失或全文容器显式存在，且 artifact 文本长度/尾部与 fixture/visible page 一致。
4. 不允许仅清除“长文未展开” warning 却仍输出 preview。失败必须是 typed `selector_failed`/`page_not_ready`。
5. 运行 X focused tests、lifecycle tests、full offline suite 和真实 X smoke。

## Acceptance and rollback

- [ ] timeline 前 5 条的 identity 无重复且 URL canonical。
- [ ] 最多 2 条长文均保存展开后全文；`summary.json` 无虚假 success warning。
- [ ] temporary tab 总是验证关闭，parent owned tab 仍可用。
- [ ] User Gate 保留同 tab 且不自动登录。
- [ ] 独立 verifier 核对页面可见全文与 artifact，不只看 warning count。

Rollback 为 revert T3 atomic commit，并将两个 capability status 回退到 `specified`。
