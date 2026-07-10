# T4 — Foundation tracer: Douban photos bounded/resumable download
## Objective

以 `douban.photo.download.read` 打通 metadata 与 local media 分离、Download Manifest、atomic file、content validation、byte limits 和 resumability。

## Blockers and ownership

- Blocked by: T3 / GitHub #5.
- File Ownership: shared download primitive 及 tests，Douban photos workflow/reference/fixtures/tests，download smoke evidence。
- Prohibited: 其他站点 download migration、新 dependency、无界媒体 crawl。
- Capability command 必须使用明确 `--output-root`, `--limit`, `--max-item-bytes`, `--max-total-bytes`。

## Semantics

- Listing/detail metadata 先写 Site Artifact；每个 media item 写 Download Manifest item。
- Primary strategy 根据 catalog 的 public/browser evidence 选定；下载失败不删除已验证 metadata。
- 临时文件必须与目标文件同 filesystem，通过 type/size/checksum 后 atomic rename。
- Resume 只重试未成功 item；已成功 checksum 匹配时 skip，不重写。

## TDD and smoke

1. Failing tests: success, wrong content type, per-item/total size overflow, interrupted partial, resume, checksum mismatch, storage failure, metadata-success/media-failure aggregate。
2. 实现最小 shared primitive，不将 Douban selector/URL logic 放入 shared code。
3. 在可控 fixture HTTP source 上证明 atomic/resume。
4. 真实 smoke 只下载最多 2 个小图片，严格 byte limits，然后在相同 output root 重跑验证 skip/resume。

## Acceptance and rollback

- [ ] 不会将 HTML/error page 标为 image success。
- [ ] 中断后没有未记录的最终文件，resume 不重下成功项。
- [ ] metadata 成功/media 失败产生 aggregate partial，但 capability 不标记 `verified`。
- [ ] manifest 和 Result Envelope/Adapter Contract refs 一致。
- [ ] verifier 检查实际文件 type、size、checksum 和二次运行。

Rollback 为 revert T4 atomic commit；删除仅用于 smoke 的临时 output，不删用户输出。
