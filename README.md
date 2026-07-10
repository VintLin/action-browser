# Action Browser

Action Browser is an agent skill for browser work that must happen in a real page: logged-in Chrome sessions, extension state, clicks, form fills, downloads, batch exports, and site adapters.

Start with [SKILL.md](SKILL.md). It is the runtime contract. This README is only the human entrypoint.

## Install

Copy or clone this folder into the agent skills directory:

```bash
git clone https://github.com/VintLin/action-browser.git <skills-dir>/action-browser
```

For an existing local copy:

```bash
mkdir -p <skills-dir>/action-browser
rsync -a ./ <skills-dir>/action-browser/
```

## First Run

Most adapters need the user's Chrome login state, so the default setup path is ActionBook extension mode:

```bash
npm install -g @actionbookdev/cli
actionbook --version
actionbook setup --browser extension --non-interactive
cd "<skills-dir>/action-browser"
unzip -o actionbook-extension-v0.5.0.zip
```

Then load the unpacked `actionbook-extension-v0.5.0` folder in `chrome://extensions/`. No API key is required for this setup path.

Full setup and repair details live in [references/initialization.md](references/initialization.md) and [references/status-check.md](references/status-check.md).

## Daily Commands

Connect the extension and give each task its own tracked tab:

```bash
python3 scripts/actionbook_session.py acquire-tab --task task-a --session task-browser --url "https://example.com" --adopt-running-session --json
python3 scripts/actionbook_session.py acquire-tab --task task-b --session task-browser --url "https://example.org" --adopt-running-session --json
python3 scripts/actionbook_session.py list-task-tabs --json
actionbook browser snapshot --session task-browser --tab <task-a-tab-id>
python3 scripts/actionbook_session.py release-tab --task task-a --json
python3 scripts/actionbook_session.py release-tab --task task-b --json
```

`acquire-tab` reuses a live tab already owned by the same task and opens a fresh tab for a different task. `--adopt-running-session` explicitly allows the task to use another healthy extension session when the requested name cannot be created. Managed tab mutations are briefly serialized; when ActionBook reattaches a closed page under a new id, `release-tab` closes the unique Chrome tab matching that replacement and verifies it disappeared. Ambiguous duplicate URLs fail safely. Page work across tabs remains parallel.

Run a long workflow so it can be stopped later:

```bash
python3 scripts/actionbook_run.py run \
  --id <run-id> \
  --cwd "$PWD" \
  -- \
  python3 scripts/adapters/<site>_workflow.py ...

python3 scripts/actionbook_run.py stop --id <run-id>
```

Capture a rendered webpage to Markdown:

```bash
python3 scripts/webpage_markdown.py capture \
  --session page-capture \
  --url "https://example.com/article" \
  --output-dir "$PWD/output/page"
```

## Reference Map

| Need | Read / Use |
| --- | --- |
| Runtime contract | [SKILL.md](SKILL.md) |
| First-run setup or missing extension/CLI | [references/initialization.md](references/initialization.md) |
| Session, daemon, bridge, or tab checks | [references/status-check.md](references/status-check.md) |
| Shared adapter browser boundaries | [references/adapter-operation-boundaries.md](references/adapter-operation-boundaries.md) |
| Adapter creation or UI drift fixes | [references/adapter-authoring.md](references/adapter-authoring.md) |
| Workflow runtime and copyable template | [references/workflow-toolkit.md](references/workflow-toolkit.md), `scripts/adapters/workflow_template.py` |
| Scheduler state and retries | [references/task-lifecycle.md](references/task-lifecycle.md) |
| Webpage-to-Markdown extraction | [references/webpage-markdown.md](references/webpage-markdown.md) |
| Site commands and output schemas | `references/adapters/<site>.md` |

Adapter scripts live in `scripts/adapters/<site>_workflow.py`. The supported site list is maintained in `SKILL.md` and checked by tests.

## Outputs

Workflow outputs stay under the requested `--output-dir` or the adapter default. Long-running process state lives outside the repo:

```text
~/.action-browser/runs/
```

Tracked task/tab ownership also lives outside the repo:

```text
~/.action-browser/task-tabs.json
```

Scheduler-managed adapter contracts use:

```text
<output>/
  summary.json
  failures.json
  contract/
    summary.json
    progress.json
    artifacts/
```

## Maintenance

When a reusable site flow changes, update the matching adapter script and `references/adapters/<site>.md`; keep `SKILL.md` site-neutral except for the site id list.

Run the focused check first, then the full local suite when the shared runtime or docs inventory changed:

```bash
python3 -m pytest -q
```
