# OpenCLI Website Expansion — 2026-07-12

## Scope

Add six currently missing canonical website adapters to action-browser:

- Batch 1 public read: `google`, `stackoverflow`, `hackernews`, `wikipedia`.
- Batch 2 authenticated/read mix: `github`, `linkedin`.

Existing `youtube`, `reddit`, and `x` adapters are inventory-checked only and are not changed by this expansion.

The Reference Baseline is OpenCLI `c1ad69676f220b5ef382bbf4c387a2486daf8355`, package `1.8.6`, captured in `catalog/reference-opencli-c1ad6967.json`.

## Read capability inventory

| Website | OpenCLI read commands in baseline | In scope |
|---|---:|---|
| `google` | 4 | `news`, `search`, `suggest`, `trends` |
| `github` + `github-trending` | 2 | `whoami`, `trending` (reference resource: `repos`) |
| `stackoverflow` | 8 | `bounties`, `hot`, `read`, `related`, `search`, `tag`, `unanswered`, `user` |
| `hackernews` | 9 | `ask`, `best`, `jobs`, `new`, `read`, `search`, `show`, `top`, `user` |
| `wikipedia` | 5 | `page`, `random`, `search`, `summary`, `trending` |
| `linkedin` | 21 | `company`, `connections`, `inbox`, `job-detail`, `jobs-preferences`, `people-search`, `post-analytics`, `posts`, `profile-analytics`, `profile-experience`, `profile-projects`, `profile-read`, `salesnav-inbox`, `salesnav-search`, `salesnav-thread`, `search`, `sent-invitations`, `services-read`, `thread-snapshot`, `timeline`, `whoami` |

Total: 49 read capabilities. OpenCLI write commands, login-assistance writes, and LinkedIn message/connect writes are excluded.

## Command and runtime contract

- Canonical CLI shape follows the repository's site/resource/intent pattern, with read intent `view`.
- Public sites use the lightest stable public HTTP/API path; no browser tab is acquired when it is unnecessary.
- Authenticated capabilities use the existing owned-tab lifecycle and stop at login, MFA, CAPTCHA, permission, or risk-control gates.
- Every capability writes the current shared Result Envelope, Adapter Contract, and site artifact shape; logs remain on stderr.
- No OpenCLI runtime, command alias, table output, or cookie handling is copied.
- LinkedIn's first implementation exposes the complete read command surface and a safe visible-page artifact, but remains `waiting_user` until each resource's semantic fields and assisted smoke are independently verified.

## Current delivery state

- Batch 1 has 26/26 smoke runs recorded per capability in `catalog/evidence/opencli-website-expansion-batch1-20260712.json`; Google Search has also passed a real simulated UI flow: fill the search box, press Enter, and read the result page after the public HTTP `SG_REL` retry interstitial.
- GitHub Trending and `whoami` have completed smoke; LinkedIn `whoami` now passes after login, while the other LinkedIn capabilities remain `waiting_user` pending assisted semantic smoke. LinkedIn semantic parity is intentionally not promoted from its visible-page artifact until that smoke is available.
- The six adapters are listed as `Expansion candidates` in `skills/action-browser/SKILL.md`; the current-site catalog remains the verified 14-site catalog until the candidate capabilities have their semantic fields, focused fixtures, and independent smoke evidence.

## Acceptance

- Every in-scope capability has a focused offline fixture test and a generated catalog record.
- Public capabilities have at least one real read smoke; a blocked or drifted page is recorded as `blocked`, never as success.
- Authenticated capabilities require a user-assisted smoke window; unavailable access remains `waiting_user` or `blocked`.
- All six adapters have reference docs, focused tests, and are listed in `skills/action-browser/SKILL.md` only after their implementation entrypoints exist.
- No write-capability code or unrequested native capability is introduced.
