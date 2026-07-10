# OpenCLI Capability Programme — Grilling Handoff

This document records the confirmed inputs for `/To Spec`. It is a decision handoff, not an implementation spec or ticket backlog. Domain terms are defined in [`CONTEXT.md`](../../CONTEXT.md); hard-to-reverse decisions live in [`docs/adr/`](../adr/).

## Objective

Use the latest OpenCLI website adapters as Reference Evidence to update existing action-browser websites and add missing high-value websites without copying OpenCLI's CLI or runtime architecture. Other models will execute the eventual tickets, so scope, ownership, safety, tests, and acceptance must be explicit.

## Reference facts to refresh at `/To Spec`

- OpenCLI's generated `cli-manifest.json` is the command inventory authority; source, tests, site docs, then README follow in evidence precedence.
- The observed planning snapshot was OpenCLI `1.8.6` at commit `6129bb39`, with 173 sites and 1275 commands, but this is not the future Reference Baseline.
- Action-browser currently declares 13 websites. Twelve map to OpenCLI (`x` to `twitter`, `zhipin` to `boss`); Feishu is action-browser-only.
- Before specification, fetch OpenCLI remote refs without changing its worktree, capture the latest remote-default-branch commit, and freeze it for the cycle.
- Before execution, record a clean action-browser Execution Baseline. Unknown or overlapping uncommitted changes block affected tickets.

## Scope and equivalence

- Build a complete Capability Catalog, then deliver it in waves; do not mechanically port every `clis/` directory.
- Include adapters with a Website Outcome even when their strategy is a public API. Exclude desktop apps, internal modules, and standalone developer/data APIs with no website user flow.
- Compare Canonical Capabilities by user outcome and remote/local effect, not by command name, file count, parameter count, or implementation.
- OpenCLI defines minimum semantic outcomes and fields; action-browser retains its owned-tab model, richer site schemas, lifecycle, safety, and Native Capabilities.
- `login` is Login Assistance, not coverage. `whoami` is a Read Capability. Pure local helpers are Utility Commands outside coverage.
- Reference removal triggers review, not automatic deletion. Material reference or native conflicts block specification until resolved.

## Delivery sequence

1. **Foundation Wave (serial):** Catalog Source and generator, canonical intent vocabulary, clean-break schemas, Adapter Contract, Result Envelope, typed Failure Reasons, execution/fallback metadata, inventory checks, test/smoke templates, privacy, write safety primitives, and canary matrix.
2. **ChatGPT Write Safety tracer:** migrate existing `ask` and `batch-ask` to default dry-run, Preview Hash approval, explicit execution, Idempotency Policy, and post-write verification before adding any other writes.
3. **Wave 1 (maximum four sites per Delivery Batch):** all 12 Overlap Websites reach full reference Read Coverage and all retained Native Capabilities are verified. Feishu is the thirteenth maintenance site and receives the common contract/tests/smoke without fabricated OpenCLI parity.
4. **Wave 2:** score Candidate Websites by user demand, browser-only value, reference maturity, smoke feasibility, complexity, and risk. Present the top three for approval as the first tracer batch; later batches contain at most five sites. A tracer proves the skeleton, but each admitted site must complete all reference reads before release.
5. **General Write Wave:** eligible only after Foundation, ChatGPT tracer, and Site Read Completion for all 13 current sites. A future site must complete its own reads before writes.
6. **Maintenance Cycles:** monthly plus OpenCLI releases, observed drift, or uncovered user requests. Automation creates read-only diffs and candidate tickets; it never modifies adapters or websites.

No calendar estimate is produced until model concurrency, Access Preflight results, and Assisted Smoke Windows are known.

## Capability and schema rules

- Aliases and ordinary count/sort/filter/format inputs are Parameter Variants, not separate capabilities.
- Different user outcomes, remote effects, or local download/export artifacts are separate capabilities.
- Listings emit stable Item Identity and canonical URL; related detail/comments/download/write commands accept that identity.
- Every Capability Record contains Semantic Field Map, Access Requirement, primary Execution Strategy, finite typed Fallback Chain, Operational Limits, evidence, status, and acceptance links.
- Public capabilities use static HTTP/API without a tab when sufficient. Browser Capabilities use the owned-tab lifecycle. Runtime strategy changes are never implicit.
- The checked-in JSON Catalog Source is the only editable catalog. Markdown Catalog Views are generated.
- One common versioned Adapter Contract wraps site-specific versioned artifacts. The current migration is a clean break: no dual writers, compatibility aliases, or legacy scheduler paths.
- Stdout contains one versioned JSON Result Envelope; logs go to stderr; Markdown artifacts provide human-readable views.
- Breaking schema changes bump `schema_version`; online adapters write only the current schema. Historical conversion is an offline tool.

## Capability lifecycle and completion

- Fixed states: `discovered -> specified -> implemented -> verified | verified_empty`; side states are `waiting_user`, `blocked`, `excluded`, and `deprecated`.
- `partial` is aggregate reporting only. A capability missing fields, tests, contract, or fresh smoke is not complete.
- `verified_empty` requires a proven site empty state plus correct URL, access state, and container; a bare empty array is failure evidence.
- Every capability requires command/docs/inventory agreement, a deterministic focused test, valid Adapter Contract, and redacted real-browser Smoke Evidence. Parameter combinations use documented equivalence classes.
- Existing action-browser-only reads meet the same verification standard as reference-derived reads.
- A Candidate Website enters `Current sites` only after Site Read Completion, independent verification, cross-site regression, and catalog integration.
- Read evidence is fresh for 90 days; write/high-risk UI evidence for 30 days. Observed drift invalidates affected evidence immediately.

## Test and smoke workflow

1. Read-only reconnaissance of Reference Evidence and the real website.
2. Create a minimal, readable, non-sensitive Synthetic Fixture.
3. Add the failing focused test.
4. Implement the minimum passing behavior.
5. Update site docs, schemas, and contract output.
6. Run the canonical capability against the real site and save redacted evidence.
7. Hand off to an independent Capability Verifier.

Focused tests are offline and never use private recordings or full HAR files. Every Delivery Batch runs the full deterministic suite. Site changes smoke affected capabilities; shared-runtime changes run lifecycle tests and the cross-strategy Canary Matrix. Monthly maintenance runs at least one canary per Supported Website; major runtime changes trigger full smoke.

## Access, privacy, and operational safety

- Access Preflight runs before tickets are assigned: extension, login, permission, empty-state, and risk-control conditions are checked read-only.
- Authentication is capability-level. Public work proceeds while gated work becomes `waiting_user`; one waiting owned tab per site is allowed.
- User Gates are never bypassed. Models do not create accounts, import credentials, solve CAPTCHA/MFA, or switch session/tab to self-heal.
- Unattended implementation and deterministic tests precede a scheduled Assisted Smoke Window for login, permissions, or authorized writes.
- Smoke Evidence stores only capability/baseline/time, redacted URL, counts, schema assertions, status, and error class. Sensitive Diagnostic Artifacts stay ignored locally and expire.
- Real smoke uses minimum counts. Every list has count, pagination/scroll limits, and stable stop conditions. Rate limit, CAPTCHA, unusual activity, or verification stops immediately; no stealth bypass.
- Download/export uses an explicit output root, atomic files, per-item Download Manifest, content checks, byte limits, resumability, and separate remote-metadata/local-media outcomes.

## Write safety

- All writes are cataloged but reads ship first.
- Reversible writes require explicit `--execute` after dry-run.
- Communication/publication and destructive writes additionally require approval of the exact Preview Hash; batch writes declare `--max-actions` and report each item.
- Every write declares an Idempotency Policy. Non-idempotent sends/posts never retry blindly; uncertain outcomes are read back before user direction. Successful batch checkpoints never replay.
- Capability Verifiers run dry-runs only. Any real write smoke requires separate user authorization.

## Multi-model execution

- Foundation and shared-runtime tickets execute serially. Site implementation parallelizes only across sites.
- One Site Owner per website; tickets declare exact File Ownership and exclude shared runtime, catalog, and cross-site docs.
- Default to the shared workspace. Use worktrees only when the execution platform already isolates them or file ownership overlaps.
- Parallel Site Owners do not commit. They deliver scoped diffs, exact test results, and smoke evidence.
- Capability Verifiers are read-only and independent from implementers.
- One Catalog Integrator serially validates scope, updates Catalog Source/views, runs cross-site regression, and creates atomic ticket/site commits.
- Regressions revert the atomic site/shared commit and catalog status. The Foundation schema cutover is its own rollback boundary.
- Site tickets cannot add dependencies or speculative shared abstractions. Dependencies require separate shared review; shared extraction waits for three verified site-neutral repetitions.

## Executable Ticket contract

Every ticket is written in Chinese with English technical identifiers and contains:

- Capability IDs, objective, and explicit non-goals;
- Reference and Execution Baseline hashes;
- exact File Ownership and prohibited files;
- prerequisites, Access Preflight, and blocking conditions;
- precise Reference Evidence paths;
- Canonical Command, args, Parameter Variants, Semantic Field Map, schemas, and Item Identity;
- Access Requirement, Execution Strategy, Fallback Chain, Operational Limits, and typed Failure Reasons;
- test-first steps and exact commands;
- smoke steps, redaction, freshness, and `requires_user_session`;
- acceptance checklist, Capability Verifier handoff, and rollback boundary.

A ticket missing any required section is not executable. `/To Tickets` generates tickets only for Foundation and the next Access-Preflight-approved Delivery Batch, not the full long-term backlog.

## Inputs `/To Spec` must derive rather than guess

- The latest frozen Reference Baseline and normalized manifest inventory.
- The clean Execution Baseline or an explicit blocker if the worktree remains dirty.
- Exact JSON Catalog Source schema, canonical intents, Failure Reason taxonomy, contract/result schemas, and generator commands.
- Current 13-site capability matrix, native/reference conflicts, field maps, and focused-test gaps.
- Wave 1 batch grouping and dependency ordering within the agreed maximum of four sites.
- Wave 2 Priority Score formula, candidate exclusions, top-three proposal, and tracer selection.
- Access Preflight matrix, Assisted Smoke Window needs, canary selection, and smoke artifact paths.
- Foundation cutover and rollback sequence, including removal of legacy output/alias paths.

## Removed guidance

The stale `docs/plans/opencli-site-support-gap-analysis.md` was deleted. It described an obsolete 10-site, China-only, partial-gap plan and must not be used as programme guidance.
