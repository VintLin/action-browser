# Issue tracker: GitHub

Issues, specs, and executable tickets for this repository live in GitHub Issues under `VintLin/action-browser`. Use the `gh` CLI from this checkout so the remote is inferred correctly.

## Conventions

- Create and read issues with `gh issue create`, `gh issue view`, and `gh issue list`.
- Apply the canonical triage labels documented in `triage-labels.md`.
- Publish one spec as one parent issue and one executable ticket per child issue.
- Express ticket blocking edges with GitHub native issue dependencies when available; otherwise put `Blocked by: #...` at the top of the issue body.
- Do not close or rewrite a parent spec issue when publishing child tickets.

## Pull requests as a triage surface

External pull requests are not a request surface. Triage only GitHub Issues.

## Skill meanings

- "Publish to the issue tracker" means create a GitHub Issue.
- "Fetch the relevant ticket" means read the full issue body, labels, and comments with `gh issue view`.
- `ready-for-agent` marks an issue that an unattended agent can execute without extra context.
