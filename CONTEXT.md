# Website Capability Coverage

This context defines the language used to compare and extend website operations across action-browser and reference projects.

## Language

**Website Capability**:
A user-visible operation on a website, identified independently from the command name or implementation used by any one project.
_Avoid_: Command parity, file parity

**Canonical Capability**:
A Website Capability normalized by user outcome and remote or local effect, collapsing command aliases and ordinary parameter variants while separating materially different artifacts or side effects.
_Avoid_: Opencli command, argparse subcommand

**Native Capability**:
An action-browser Website Capability with no equivalent in the Reference Baseline that must be preserved and verified without contributing to reference parity.
_Avoid_: Extra command, out-of-scope behavior

**Parameter Variant**:
A supported input class such as count, sort, filter, or format that changes how one Canonical Capability runs without changing its user outcome or effects.
_Avoid_: Separate capability

**Canonical Command**:
The single supported action-browser CLI path for a Canonical Capability under the current vocabulary.
_Avoid_: Compatibility alias, reference command name

**Utility Command**:
A deterministic local helper that neither reads nor changes website state and therefore remains documented and tested outside Read or Write Coverage and real-browser smoke requirements.
_Avoid_: Website Capability, coverage credit

**Read Capability**:
A Website Capability that observes or downloads website state without changing remote state.
_Avoid_: Safe command

**Write Capability**:
A Website Capability that changes remote website state, including posting, messaging, reacting, following, deleting, publishing, or modifying a cart.
_Avoid_: Interactive command, action command

**Write Safety Gate**:
The common contract that keeps a Write Capability non-mutating until the user explicitly approves the previewed remote change and verifies its outcome.
_Avoid_: Confirmation prompt

**Write Risk Tier**:
The safety class of a Write Capability: reversible state change, communication or publication, or destructive change, determining the required execution approval and impact limit.
_Avoid_: Read/write flag

**Preview Hash**:
The digest of the exact planned remote mutation that binds approval to reviewed inputs and becomes invalid when those inputs change.
_Avoid_: Yes flag, confirmation token

**Idempotency Policy**:
The Write Capability rule that determines whether an uncertain operation may be retried, must first be verified by reading remote state, or must stop for user direction.
_Avoid_: Retry count

**Adapter Contract**:
The site-independent run summary, progress state, and artifact index used by scheduling and acceptance tooling. It describes outcomes without replacing site-specific business data.
_Avoid_: Universal payload schema, legacy sidecar

**Result Envelope**:
The single versioned JSON object written to stdout with capability status, contract path, artifact references, and typed Failure Reason while all logs remain on stderr.
_Avoid_: Final log line, table output

**Site Artifact**:
A durable site-specific result such as posts, videos, products, jobs, files, or media, referenced by the Adapter Contract and retaining its own domain schema.
_Avoid_: Contract payload

**Schema Version**:
The explicit version on every structured Adapter Contract and Site Artifact that identifies one current, non-dual-written data shape.
_Avoid_: Compatibility mode, legacy field alias

**Download Manifest**:
The resumable item-level record of expected and completed local artifacts, including source identity, path, size, content type, verification state, and failure details.
_Avoid_: Progress log, file list

**Verified Capability**:
A Website Capability whose command surface, documentation, focused tests, Adapter Contract, and real-browser smoke evidence all satisfy the current Reference Baseline.
_Avoid_: Implemented command, code complete

**Verified Empty**:
A successful real-browser result in which the website explicitly proves there are no items while the URL, access state, and expected page container remain valid.
_Avoid_: Empty array, no nodes found

**Capability Status**:
The fixed lifecycle of a Capability Record: `discovered`, `specified`, `implemented`, `verified`, or `verified_empty`, with explicit `waiting_user`, `blocked`, `excluded`, and `deprecated` side states.
_Avoid_: Partial, mostly done, code complete

**Failure Reason**:
A stable typed `reason_code` in the Adapter Contract that determines user gates, retry eligibility, blocking, and failure reporting independently from prose or process exit numbers.
_Avoid_: Error message, exit code

**Smoke Evidence**:
A durable, redacted record proving that one canonical Website Capability completed against the real website in the expected browser and authentication state.
_Avoid_: Terminal log, manual claim

**Evidence Freshness**:
The independent validity window of Smoke Evidence: 90 days for reads and 30 days for writes or high-risk UI, invalidated immediately by observed website drift.
_Avoid_: Capability Status, permanent verification

**Canary Matrix**:
The small cross-site regression set representing public HTTP, authenticated API, DOM, UI, temporary-tab, download, and User Gate behavior after shared-runtime changes.
_Avoid_: Full capability smoke suite

**Synthetic Fixture**:
A minimal, readable, non-sensitive representation of the DOM or API shape needed for deterministic focused tests, derived without retaining real account data or full-page recordings.
_Avoid_: HAR recording, private response dump

**Diagnostic Artifact**:
Temporary local-only material containing additional detail needed to investigate a failed real-browser run, excluded from source control and subject to automatic expiry.
_Avoid_: Smoke Evidence, test fixture

**Reference Evidence**:
The opencli manifest entry, source behavior, documentation, tests, and observed website behavior used to define a Capability Record without making opencli's implementation the target architecture.
_Avoid_: Source template, code to port

**Reference Conflict**:
A material contradiction among the reference manifest, source, tests, or site documentation that blocks capability specification until explicitly resolved.
_Avoid_: Documentation typo, model judgment call

**Reference Removed**:
A Reference Baseline change that no longer exposes a previously cataloged capability and therefore triggers review rather than automatic deletion from action-browser.
_Avoid_: Deprecated Native Capability, removal instruction

**Native Conflict**:
A material contradiction among explicit user requirements, observed website behavior, action-browser tests, documentation, and current implementation that blocks preservation or removal of a Native Capability.
_Avoid_: Existing code wins, undocumented cleanup

**Capability Catalog**:
The complete inventory of Website Capabilities found in the reference scope, including their current action-browser coverage and implementation priority.
_Avoid_: Adapter list, site list

**Catalog Source**:
The checked-in machine-readable JSON that is the only editable source for Capability Records, baselines, evidence, statuses, scores, and exclusions.
_Avoid_: Markdown matrix, generated report

**Catalog View**:
A generated human-readable projection of the Catalog Source that must never be edited independently.
_Avoid_: Second source of truth

**Capability Record**:
One normalized entry in the Capability Catalog describing a Website Capability, its effects and access requirements, reference evidence, current coverage, and acceptance status.
_Avoid_: Manifest command, ticket

**Semantic Field Map**:
The Capability Record mapping from reference output semantics to action-browser Site Artifact fields, allowing different names or richer structures while making missing required meaning explicit.
_Avoid_: Column-name equality, sample payload

**Item Identity**:
The stable site id, canonical URL, or explicitly defined composite key emitted by a listing and accepted by related detail, comments, download, or write capabilities for the same remote object.
_Avoid_: Title match, list index, DOM ref

**Access Requirement**:
The capability-level browser state required for verification, such as public access, an authenticated account, a specific permission, or a user-completed verification gate.
_Avoid_: Site login status

**Access Preflight**:
The read-only check performed before a Delivery Batch to prove extension health, login state, required permissions, recognizable empty states, and absence of active risk-control for its capabilities.
_Avoid_: First smoke run, login automation

**Assisted Smoke Window**:
A scheduled verification period in which a user is available to complete User Gates or explicitly authorize live writes after unattended implementation and deterministic tests finish.
_Avoid_: Model waiting loop, implementation phase

**Execution Strategy**:
The declared primary mechanism for one Canonical Capability, such as public HTTP, an authenticated same-origin API, DOM extraction, UI interaction, or network interception.
_Avoid_: Site strategy, automatic best effort

**Fallback Chain**:
The finite ordered list of alternate Execution Strategies that may run only for declared typed failures while preserving the same capability schema and recording the transition.
_Avoid_: Best effort, retry everything

**Browser Capability**:
A Canonical Capability whose Access Requirement or Execution Strategy requires an owned browser tab.
_Avoid_: Every site adapter command

**User Gate**:
A login, CAPTCHA, MFA, risk-control, or permission step that automation must not bypass and that pauses only the affected capability in its owned tab.
_Avoid_: Adapter failure, site blocker

**Login Assistance**:
A lifecycle helper that opens the correct foreground page, records `waiting_user`, and verifies user-completed authentication without entering credentials or counting toward Website Capability coverage.
_Avoid_: Login capability, automated authentication

**Operational Limit**:
A declared bound on result count, pagination, scrolling, retries, runtime, or downloaded bytes that keeps real website work finite and within site safety expectations.
_Avoid_: Magic number, anti-bot bypass

**Reference Baseline**:
The latest opencli commit captured when a planning round begins and held unchanged until that round is complete.
_Avoid_: opencli latest, moving HEAD

**Execution Baseline**:
The recorded clean action-browser commit from which an approved set of tickets begins and against which all Site Owner diffs are scoped.
_Avoid_: Current working tree, assumed HEAD

**Maintenance Cycle**:
A later planning round that compares a new Reference Baseline with the previous one and admits the resulting capability changes into new work.
_Avoid_: Continuous parity

**Maintenance Trigger**:
A monthly check or an event such as an opencli release, observed site drift, or a user request for uncovered behavior that starts a read-only baseline diff.
_Avoid_: Automatic adapter update

**Reference Website Adapter**:
An opencli adapter whose capabilities correspond to user-visible objects or operations on a website. Desktop applications, internal shared modules, and standalone developer or data APIs with no website user outcome are outside this term.
_Avoid_: Every directory under `opencli/clis`

**Website Outcome**:
The user-visible website object, state, or operation produced by a capability regardless of whether its Execution Strategy uses HTTP, an API, DOM, UI, or interception.
_Avoid_: API response, browser action

**Overlap Website**:
A website with both an action-browser adapter and a corresponding Reference Website Adapter, even when the two projects use different names such as `x`/`twitter` or `zhipin`/`boss`.
_Avoid_: Same-name site

**Canonical Website**:
The stable action-browser site identity chosen from the existing adapter id or, for a new website, its primary domain or official product name, with reference names stored only as aliases.
_Avoid_: Reference directory name, duplicate adapter

**Exclusive Website**:
A website supported by only one side of the comparison. It has no implied parity target until explicitly admitted to an Implementation Wave.
_Avoid_: Missing adapter

**Candidate Website**:
A reference-only Website Adapter that remains after excluding desktop applications, internal modules, and standalone developer or data APIs without a Website Outcome, and is eligible for prioritization into a future Implementation Wave.
_Avoid_: Every non-overlap directory, standalone data service

**Priority Score**:
The explainable ranking of a Candidate Website based on user demand, browser-only value, reference maturity, real-smoke feasibility, implementation complexity, and risk.
_Avoid_: Popularity, directory order

**Read Coverage**:
The set of Reference Website Adapter Read Capabilities that an Overlap Website must provide with equivalent user outcomes, while preserving action-browser-specific capabilities.
_Avoid_: Matching command count

**Site Read Completion**:
The state in which all admitted reference Read Capabilities and all retained Native Capabilities for one website are `verified` or `verified_empty`.
_Avoid_: Adapter exists, parity percentage

**Supported Website**:
A website that has reached Site Read Completion, passed independent verification and cross-site regression, and been integrated into the Capability Catalog before appearing in `Current sites`.
_Avoid_: Candidate with one working command

**Implementation Wave**:
An ordered delivery group from the Capability Catalog: shared existing websites first, high-value missing websites second, and the remaining accepted backlog afterward.
_Avoid_: Full parity in one pass

**Delivery Batch**:
A concurrency-limited subset of an Implementation Wave that must pass independent verification and cross-site regression before the next subset begins.
_Avoid_: All available tickets

**Programme Spec**:
The long-lived design that fixes the domain language, architecture, waves, safety boundaries, and completion rules without pre-generating implementation tickets for the full backlog.
_Avoid_: Mega ticket list, one delivery batch

**Executable Ticket**:
A work contract containing capability scope, both baselines, File Ownership, dependencies, Reference Evidence, command and schema design, strategy and limits, exact tests, smoke and privacy steps, Failure Reasons, acceptance, verifier handoff, and rollback boundaries.
_Avoid_: Task title, implementation suggestion

**Tracer Capability**:
The smallest representative Read Capability implemented first for a Candidate Website to prove its adapter skeleton, Execution Strategy, Adapter Contract, and real access before the Site Owner completes full Read Coverage.
_Avoid_: Minimum viable site, completed adapter

**Foundation Wave**:
The mandatory first Implementation Wave that establishes the Capability Catalog, canonical intent mapping, adapter contract, inventory checks, test template, and real-smoke evidence format before site work is parallelized.
_Avoid_: Setup tasks, optional tooling

**Site Owner**:
The sole model permitted to change one website's adapter, documentation, Synthetic Fixtures, and focused tests during an active site work unit.
_Avoid_: Contributor, parallel site agents

**File Ownership**:
The explicit ticket-level list of files a Site Owner may change in the shared workspace; shared runtime, catalog, and cross-site documents are excluded from site ownership.
_Avoid_: Git branch ownership, directory convention

**Catalog Integrator**:
The single serial role that applies verified catalog status changes, regenerates Catalog Views, and runs cross-site regression after Site Owner work.
_Avoid_: Every Site Owner

**Capability Verifier**:
An independent model that does not edit the site implementation and decides whether its focused tests, contract, documentation, and real-browser evidence meet verification requirements.
_Avoid_: Implementer self-check
