# OpenCLI Website Expansion — Ticket Map

Source spec: [`docs/specs/opencli-website-expansion-20260712.md`](../../specs/opencli-website-expansion-20260712.md)

## Delivery batches

1. Batch 1: `google`, `stackoverflow`, `hackernews`, `wikipedia` — public read only.
2. Batch 2: `github`, `linkedin` — public/authenticated read only; user gates remain explicit.

Each site owner changes only its workflow, site reference, focused tests, and site-specific fixtures. Shared runtime, catalog integration, and current-site inventory updates are serial integration work.

## Shared seam

`skills/action-browser/scripts/adapters/public_read_runtime.py` is the single shared seam for the four public adapters. It owns HTTP fetches, explicit empty-state handling, the Result Envelope, the Adapter Contract, and the site artifact. Its focused contract tests are in `test_public_read_batch1.py`; no second generic adapter layer is introduced.

## Baseline

- Reference: OpenCLI `c1ad69676f220b5ef382bbf4c387a2486daf8355`.
- Execution: `d9f2c639a454b72121c4189c94601b05ddae2655`.
- Reference snapshot: `catalog/reference-opencli-c1ad6967.json`.

## Gate

No site is marked `verified` from code alone. Focused tests, catalog validation, and real smoke evidence are required; login/MFA/CAPTCHA/risk-control blocks only the affected capability.
