# ADR 0021: Stage the clean break on an integration branch

## Status

Accepted

## Context

The programme replaces command, result, contract, and artifact schemas across the shared runtime and thirteen current sites. Shipping those changes site by site would expose a mixed runtime even though ADR 0017 requires a clean break with no compatibility aliases or dual writers. The migration also needs an unambiguous rollback boundary.

## Decision

Create a dedicated integration branch from the recorded clean Execution Baseline. Foundation, the ChatGPT Write Safety tracer, and all Wave 1 batches land on that branch as individually revertible atomic commits. The currently released branch keeps the old contract until the integration branch passes the complete deterministic suite, all required current-site smoke verification, generated-catalog validation, and independent integration review.

The final cutover is one merge from the integration branch. Legacy command aliases, legacy output writers, and legacy scheduler parsing are removed before that merge; no release contains both contracts.

Before cutover, rollback means reverting the failing atomic commit or abandoning the integration branch. After cutover, rollback means reverting the merge commit and restoring the previous release tag. Catalog status must be reverted with the corresponding code change.

## Consequences

- Parallel site work can be integrated and tested without publishing a half-migrated contract.
- Every batch remains independently diagnosable and revertible while the public cutover stays atomic.
- The integration branch may live longer than an ordinary feature branch and must be kept scoped to this programme.
- Execution cannot begin until the action-browser worktree is clean and its baseline commit is recorded.
