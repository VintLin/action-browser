# T6 — ChatGPT `ask`/`batch-ask` Write Safety tracer
## Objective

将现有 ChatGPT `ask` 和 `batch-ask` 迁移到默认 dry-run、Preview Hash、显式 execute、impact limit、checkpoint、Idempotency Policy 和 post-write read-back contract，作为所有未来 writes 的第一个 tracer。

## Blockers and ownership

- Blocked by: T5 / GitHub #7.
- Foundation implementation commits: `fab0324`, `9716cac`.
- Foundation verification report commit: `0c432dcc118a8486a77eb141712b30dcbf211c7c`.
- Capability IDs: `chatgpt.prompt.message.write`, `chatgpt.prompt-batch.message.write`.
- File Ownership: ChatGPT workflow/reference/fixtures/focused tests，shared write-safety primitive 在 Foundation 已定义的边界内的最小改动，ChatGPT dry-run evidence。
- Prohibited: 其他 site writes，真实 message submission smoke，新 dependency，为未来站点预建 framework。

## Contract

- 无 `--execute` 时只输出目标对话/模式/提示文本/搜索要求/批次顺序/限制的 redacted preview 和 Preview Hash，网站无变化。
- `--execute --preview-hash <hash>` 只在完整参数重算 hash 一致时允许。任何参数变化返回 `preview_hash_mismatch`。
- Batch 必须要求 `--max-actions`，逐项 checkpoint，重启后不重放 success item。
- 每次 send 是 non-idempotent；timeout 后先按 conversation identity read-back，无法确认返回 `uncertain_write_outcome`。

## TDD and verification

1. Failing tests: default dry-run no submit, stable hash, every material field invalidates hash, missing execute/hash, max-actions overflow, checkpoint resume, timeout/read-back found/not-found/uncertain。
2. 实现最小改动，复用 Foundation contract。
3. 运行 ChatGPT focused tests、shared write-safety tests、scheduler mapping 和 full offline suite。
4. 真实浏览器只运行 dry-run，前后核对 conversation list 未新增。

## Acceptance and rollback

- [ ] 所有默认路径零 remote effect。
- [ ] Preview Hash 绑定完整 effect，不包含 secret 明文。
- [ ] batch checkpoint 不重放已成功项。
- [ ] verifier 仅 dry-run，没有真实 ChatGPT 提交。
- [ ] General Write Wave 仍保持 blocked，直到 13-site read gate 通过。

Rollback 为 revert T6 atomic commit。因为 clean break 尚未发布，不保留 dual command alias。
