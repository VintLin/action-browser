# T5a — Shared Foundation Contract Gate

## Objective

Before T5, add the site-neutral contract primitives required by the Foundation Pass: versioned schemas, atomic JSON persistence, and deterministic scheduler handling of retryable failures.

## Ownership

- Blocked by: T4 / GitHub #6.
- Blocks: T5 / GitHub #7.
- Files: `schemas/`, shared contract/serializer modules, `scripts/scheduler_lib/`, focused tests, and this Ticket Map.
- Prohibited: site capability work, real writes, dependencies, legacy cutover.

## Acceptance

- Result Envelope, Adapter Contract, Site Artifact reference, and Download Manifest validate deterministically.
- JSON writes are same-filesystem atomic replacements.
- Scheduler distinguishes retryable failure, user gate, blocked, and terminal failure.
- Existing T1--T4 suites remain green.
