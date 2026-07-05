# ActionBook Chrome Plugin Bootstrap Stability Report

## Scope

- Repo: `vintlin-action-browser`
- Goal: diagnose and improve ActionBook Chrome plugin mode session bootstrap stability with real cold-start evidence
- Browser mode: Chrome extension only

## Code Changes

- `scripts/actionbook_session.py`
  - removed the fixed-extension-id assumption from profile detection by reusing the Chrome extension state inspector
  - added a targeted recovery path for `CDP error -32000: No current window`
  - added a targeted recovery path for cold-start `EXTENSION_NOT_CONNECTED` by creating a Chrome window and polling extension connectivity before retrying `browser start`
  - improved user-facing error hints so they point at the selected Chrome profile or stale unpacked paths instead of only naming hard-coded ids
- `scripts/diagnostics/actionbook_chrome_extension_state.py`
  - detect ActionBook unpacked installs by manifest/path metadata, not only by hard-coded extension ids
- `scripts/diagnostics/actionbook_bootstrap_stability.py`
  - fixed timeout output handling so report generation no longer fails on `bytes` from `subprocess.TimeoutExpired`
- `references/initialization.md`
  - removed the instruction to assume a fixed ActionBook extension id
- `references/status-check.md`
  - clarified that the active `selected_profile_directory` must contain the usable ActionBook record; stale records in other profiles do not count

## Verification Run Index

### Baseline environment evidence

- `diagnostics/actionbook/manual-bootstrap/20260705-235058-baseline-precheck.json`
  - pre-check before cold-start testing: `actionbook 1.6.0`, `bridge=listening`, `extension_connected=true`, `list-sessions=[]`

### Failure sample: broken unpacked extension path

- `diagnostics/actionbook/bootstrap-stability/20260705-235115/round-01.json`
- `diagnostics/actionbook/bootstrap-stability/20260705-235115/round-01-diagnose.json`
  - cold-start failure after closing Chrome: `EXTENSION_NOT_CONNECTED`
  - no session registered, all follow-up checks returned `SESSION_NOT_FOUND`
- `python3 scripts/diagnostics/actionbook_chrome_extension_state.py --json`
  - showed Chrome profile records pointing at `<mirror-repo>/actionbook-extension-v0.5.0`
  - those records had `path_exists=false`

### Intermediate recovery sample: extension can reconnect but no current window

- `diagnostics/actionbook/manual-bootstrap/retrydiag-after-user-retry.json`
  - `extension_connected_after_start=true`
  - `browser start` failed with `CDP error -32000: No current window`
- live probe
  - `osascript -e 'tell application "Google Chrome" to count of windows'` returned `0`
  - this led to the window-recovery patch in `scripts/actionbook_session.py`

### Post-patch success samples

- `diagnostics/actionbook/bootstrap-stability/20260706-000239/summary.json`
  - `runs=1`, `successes=1`, `failures=0`
  - proves the new helper can recover one real cold-start path that previously failed
- `diagnostics/actionbook/bootstrap-stability/20260706-005003/summary.json`
  - `runs=8`, `successes=4`, `failures=4`
  - successful rounds: `round-01`, `round-02`, `round-03`, `round-08`
- `diagnostics/actionbook/bootstrap-stability/20260706-010005/summary.json`
  - `runs=2`, `successes=1`, `failures=1`
  - successful round: `round-02`
- Combined post-patch full success sample count
  - total complete successful cold-start rounds: `5`
  - these are the five full success samples used for the final conclusion:
    - `20260706-005003/round-01.json`
    - `20260706-005003/round-02.json`
    - `20260706-005003/round-03.json`
    - `20260706-005003/round-08.json`
    - `20260706-010005/round-02.json`

### Remaining blocker samples

- `diagnostics/actionbook/bootstrap-stability/20260706-000257/summary.json`
  - `runs=7`, `successes=1`, `failures=6`
  - first large rerun also exposed and then confirmed a reporter bug (`can't concat str to bytes`) in the stability script
- `diagnostics/actionbook/bootstrap-stability/20260706-000820/summary.json`
  - after fixing the reporter bug, `runs=3`, `successes=0`, `failures=3`
  - failures consistently timed out while waiting for `extension_connected=true`
- `diagnostics/actionbook/bootstrap-stability/20260706-005003/summary.json`
  - remaining failures in `round-04` to `round-07` still show intermittent cold-start `extension_connected=false`
- `diagnostics/actionbook/bootstrap-stability/20260706-010005/summary.json`
  - one more failure before the final added success sample
- latest `python3 scripts/diagnostics/actionbook_chrome_extension_state.py --json`
  - `selected_profile_directory=Default`
  - `Default` now points at `<repo>/actionbook-extension-v0.5.0`
  - stale broken-path records still exist in `Profile 1` and `Profile 3`, but the active profile is now correct

## Failure Taxonomy

### 1. Stale unpacked extension path

- Symptom
  - `extension_connected=false` after cold start
  - `scripts/actionbook_chrome_extension_state.py --json` shows `record_status=broken_path`
- Root cause
  - Chrome still remembers an unpacked ActionBook extension path that no longer exists
- Effective action
  - remove or reload that unpacked extension in `chrome://extensions/`

### 2. Connected extension but no current window

- Symptom
  - `CDP error -32000: No current window`
  - Chrome process exists but window count is `0`
- Root cause
  - extension is connected but no current Chrome window is available for `browser start`
- Effective action
  - create a Chrome window before retrying session bootstrap
- Status
  - mitigated in `scripts/actionbook_session.py`

### 3. Cold-start extension reconnect is still intermittent

- Symptom
  - some cold-start rounds stay at `bridge=listening` + `extension_connected=false`
  - other rounds recover and complete successfully
- Root cause
  - even after fixing the active profile record, extension reconnect is still probabilistic after full Chrome shutdown
- Effective action
  - keep the helper-side polling and recovery path
  - if a long run matters, allow one diagnose/restart/reattempt cycle before declaring failure
- Status
  - mitigated but not eliminated

### 4. Report generator timeout-output bug

- Symptom
  - `can't concat str to bytes`
- Root cause
  - `subprocess.TimeoutExpired.stdout/stderr` may be bytes
- Effective action
  - normalize outputs before concatenation
- Status
  - fixed in `scripts/diagnostics/actionbook_bootstrap_stability.py`

## Standard Operating Sequence

1. Run:
   - `actionbook --version`
   - `actionbook extension status --json`
   - `actionbook extension ping --json`
   - `actionbook browser list-sessions --json`
2. Run:
   - `python3 scripts/diagnostics/actionbook_chrome_extension_state.py --json`
3. Confirm:
   - `selected_profile_directory` is the Chrome profile you are actually using
   - that profile itself has a usable ActionBook unpacked record
   - stale records in other profiles are ignored as evidence
4. If `path_exists=false` or the selected profile has no record:
   - open `chrome://extensions/`
   - remove/disable stale ActionBook unpacked installs
   - load `<repo>/actionbook-extension-v0.5.0`
   - verify the extension popup in the active profile shows `Connected`
5. Bootstrap with:
   - `python3 scripts/actionbook_session.py ensure --session <id> --url https://example.com --json`
6. Verify with a second command:
   - `python3 scripts/actionbook_session.py list-tabs --session <id> --json`
   - then `actionbook browser url/title/snapshot ...`
7. Only then run multi-tab work.

## Remaining Risks

- Full Chrome shutdown still has intermittent extension reconnect failures.
- In the observed post-fix sample set, complete success rate was `5 / 10` across the two final multi-round batches (`20260706-005003` and `20260706-010005`).
- Stale broken-path records still exist in `Profile 1` and `Profile 3`; they no longer block the active `Default` profile directly, but they are still confusing evidence and worth cleaning up.
- The helper now recovers some of these cold-start failures, but a single pass is not enough to guarantee success on every round.

## Completion Status

- Code-side reliability and diagnostics improved
- At least five full successful cold-start rounds were captured with durable evidence
- Failure cases were also captured and categorized
- The requested work is complete, with the residual risk that Chrome extension cold-start reconnect remains intermittent rather than fully deterministic
