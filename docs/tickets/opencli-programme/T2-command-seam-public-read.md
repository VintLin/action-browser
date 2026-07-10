# T2 — Foundation tracer: Douban public read 打通 Command seam
## Objective

以 `douban.movie-ranking.trending.read` 为第一个端到端 Canonical Capability，从中央 command dispatcher 输入到单一 stdout Result Envelope、Adapter Contract、Site Artifact 和 scheduler state，证明 public HTTP 路径不获取 tab。

## Blockers and ownership

- Blocked by: T1 / GitHub #3.
- Reference/Execution Baselines: 使用 Catalog Source 内冻结 hashes。
- File Ownership: 新的 central command/contract/schema modules，Douban workflow 及 reference，scheduler contract/reconcile 相关测试，对应 focused fixtures/tests。
- Prohibited: 其他 site workflows、ActionBook session implementation、download implementation。

## Canonical Command and semantics

`python3 scripts/action_browser.py run --site douban --resource movie-ranking --intent trending --limit 5 --task-id <id> --output-root <root>`

- `limit` equivalence classes: 1，普通小值 5，非法 0/负数，超上限值。
- Item Identity 至少含 subject id 和 canonical URL。
- Required semantic fields: identity, title, canonical URL, rank, rating, rating count, summary/metadata available from reference outcome。
- Primary strategy: public HTTP/static payload。Fallback: 无；不允许为掩盖 parser drift 转浏览器。
- Limits: requested count 有上限，单页即停，timeout 和 retry 按 spec taxonomy。

## TDD and verification

1. 为 valid list、explicit empty marker、missing container、field gap、timeout 和 invalid input 写 Synthetic Fixtures/failing tests。
2. 实现 Result Envelope/Adapter Contract 序列化与 strict schema validation。
3. 将 typed Failure Reasons 映射到 scheduler states；不保留 mixed stdout parser。
4. 运行 focused tests、scheduler tests、full offline suite。
5. 对真实 Douban 运行 limit 5 smoke，记录 no-tab assertion、field assertions、counts 和红化 URL。

## Acceptance and rollback

- [ ] stdout 恰好一个 JSON object，logs 只在 stderr。
- [ ] Contract/artifact refs 都可解析，schema versions 一致。
- [ ] `verified_empty` 只在 explicit empty marker 时出现。
- [ ] real smoke 未创建/领养 tab，获得前 5 条且 Item Identity 可供详情使用。
- [ ] 独立 verifier 重跑同一 Command seam。

Rollback 为 revert T2 atomic commit；Catalog 中该 capability status 同步回退到 `specified`。
