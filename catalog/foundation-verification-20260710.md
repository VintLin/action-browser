# Foundation Verification

- Integration branch: `codex/opencli-capability-integration`
- Foundation implementation commit: `31bb182016a01655d55be091daafc6dd9ecf3190`
- Reference baseline: `6129bb3953d5eebd8dd67f96802b320c723f50ca`
- Scope: T1 through T4 atomic commits; no released-branch cutover.

## Deterministic Pass

- `python3 -m pytest -q tests/catalog/test_catalog.py tests/test_write_safety.py tests/test_download_primitive.py tests/test_scheduler_reconcile.py tests/test_workflow_runtime.py tests/test_actionbook_session.py` -> `72 passed`.
- `python3 -m pytest -q` -> `145 passed`.

## Canary Matrix

See `catalog/foundation-canary.json`. Public HTTP, DOM, temporary-tab, and download canaries have current smoke evidence. Auth API, UI, User Gate, and write dry-run are `not_run`; this report does not treat them as passed.

## Evidence

- `catalog/evidence/t2/douban-movie-ranking-20260710T043116Z.json`
- `catalog/evidence/t3/x-timeline-smoke-20260710T0518Z.json`
- `catalog/evidence/t3/x-article-smoke-20260710T0514Z.json`
- `catalog/evidence/t4/douban-photo-download-smoke-20260710T0521Z.json`

## Independent Review

The independent verifier ran focused named-commit checks (`42 passed`) and reviewed T1--T4 without browser activity. Its shared-contract findings were resolved by T5a commit `d2bee33`.

`catalog validate` returning `field_gap` for still-discovered capabilities is expected T1 behavior, not a successful full-parity claim. The historical ownership conflict is recorded in `catalog/evidence/t5/foundation-native-conflict-20260710T0535Z.json`.

## Current Canary Rerun

- Douban public read reran successfully on 2026-07-10.
- Douban bounded photo download reran successfully on 2026-07-10.
- X timeline reran successfully on 2026-07-10.
- X article canary reran successfully after the collector was fixed to exclude offscreen virtualized nodes: the canonical timeline artifact included the long-form identity, its parent expansion control disappeared, full text and tail were saved, and the temporary tab closed.
