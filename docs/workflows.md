# Agent workflow management

`cly` can keep an inventory of active agent sessions and collect their conversation
prose into one local library. Snapshots resume native conversations after a restart;
the library gives one selected model a catch-up view across agents.

These commands extend the existing MIT-licensed cly project. They need Python 3.9+
and use its standard library. The ordinary launcher still works without Python.
On macOS, cly also needs Bash 4.2+; the system Bash 3.2 is insufficient.

## Save and restore sessions

Launch agents through cly as usual, then save from another terminal:

```sh
cly claude
cly codex resume NATIVE_SESSION_ID

cly snapshot status
cly snapshot                    # same as snapshot save
cly snapshot list
cly snapshot restore latest --dry-run
cly snapshot restore 2026-10-07 --dry-run
cly snapshot restore 2026-10-07
```

Snapshots contain sessions whose tracked processes are still alive. Process start
identities guard against a recycled PID being mistaken for the original process.
Sessions opened outside cly are excluded unless explicitly adopted; visible
terminal tabs and Desktop conversations are not an automatic capture inventory.
Use `snapshot status` to review exactly what will be saved.
The date selector is a **UTC date** and picks the latest snapshot that day. Use the
full ID from `snapshot list` to select a specific saved inventory.

Restore checks every selected session's profile, executable, directory, native
history and terminal adapter before opening terminals. A failed preflight opens
nothing. `--dry-run`
prints the selected snapshot and launch plan without opening terminals.

This restores conversations through each agent's resume command. Terminal layout,
scrollback, shell state and running tools are outside the snapshot. Native history
must remain available in the agent's own store; the JSON snapshot is not a backup
of that history.

New snapshots save validated resume options from the actual agent command,
including standing flags, explicit bypass, model, search, sandbox/approval options
and writable directories. Restore replays those options without layering later
profile flags or `CLY_FLAGS` over them. Profile executable and environment are
still resolved on this computer; credentials and prompts are never saved.

Codex snapshots refresh permissions from the exact bound session's recorded
`turn_context`, including network and writable-root changes. A pre-launch context
does not override an explicitly requested launch policy. An idle `/permissions`
change has to reach native history before cly can observe it. Two clients bound to
one native ID share that history; cly cannot distinguish their unrecorded settings.
Codex restores locally: old remote connection addresses/auth environment names
are transport settings and are not replayed against a shared server whose existing
session might have different permissions.

Only known resume options and a small set of non-secret Codex config overrides
are saved. Unsupported flag names appear in `resume_options.omitted_flags`; their
values are excluded and restore refuses that record instead of silently dropping
the options. Add support for that option or adopt again with supported resume
settings. Legacy snapshots without `resume_options` remain readable and warn that
their restore uses the current profile. Lost original flags cannot be recovered
from legacy JSON alone.

### Reload from a snapshot

Reload stops **all currently tracked active agent process families**, then opens
the conversations in the selected snapshot. Preview it from a separate terminal:

```sh
cly snapshot reload latest --dry-run
cly snapshot reload 2026-10-08
cly snapshot reload SNAPSHOT_ID --terminal wt
```

The preview lists the processes to stop and conversations to reopen. It does not
save a snapshot, stop processes or open terminals. Reload validates the selected
profiles, executables, directories, native histories and terminal adapter before
asking you to type `reload` when active sessions will be stopped. It repeats
preflight after confirmation and refuses
if the active inventory or process families changed. PID start identities protect
against PID reuse. Running reload from an agent it would stop is refused; use a
separate terminal.

The warning includes currently running sessions. cly cannot determine whether
they are idle, generating a response or running tools, so save any work first.
`--yes` accepts the warning without a prompt and is required before stopping
sessions noninteractively. On Unix, reload sends SIGTERM and waits; `--force`
allows SIGKILL for processes that do not exit. Windows uses verified process
handles and immediate termination,
so the same warning applies even without `--force`.

Before stopping, cly saves a recovery snapshot of the current tracked inventory
and writes a receipt under the workflow state's `reloads` directory. Unbound
sessions remain in the recovery inventory but cannot be resumed until their
native IDs are resolved. Recovery inventories are normal snapshots and become
the new `latest`; use the printed selected snapshot ID to repeat the same reload.
A stop failure prevents all reopening. A terminal launch
failure records the completed launches and prints the selected snapshot's restore
command for recovery. Automatic rollback is omitted because retrying already
opened conversations could create duplicates. Inspect the receipt before retrying
a partial launch. Receipts record terminal adapter results; they do not verify
that the agent inside each terminal has finished starting or resumed successfully.

Reload supports the same selector, `--map-dir`, `--terminal` and
`--skip-unresolved` options as restore. `--skip-unresolved` only limits what is
reopened: all tracked active agent families are still stopped. Untracked sessions,
terminal shells, terminal windows, window layouts and shared daemons outside those
process families remain outside its scope.

### Bind a new conversation

Claude provides a new-session ID flag, so cly assigns an exact ID when starting a
normal new Claude conversation. Explicit native resume/session arguments also
provide IDs. For other new conversations, cly records candidate IDs but does not
guess which conversation belongs to a process.

Get the exact ID from your agent, and bind it to the `run_id` shown by status:

```sh
cly snapshot status
cly snapshot bind RUN_ID NATIVE_SESSION_ID
cly snapshot
```

Binding verifies that the native history exists. Managed Claude launches now use
SessionStart hooks to track conversation switches. Codex can use the exported
lifecycle hook configuration after native trust review; remote daemons need the
same run identity. Other runtimes retain explicit binding. See
[session tracking](session-tracking.md) for setup and supported boundaries.

An unresolved run can be saved as inventory, but restore fails until a new snapshot
has a binding. `restore --skip-unresolved` explicitly restores only resolvable runs.
It does not repair the original snapshot.

Processes opened before installing this feature can be registered explicitly:

```sh
cly snapshot adopt 12345 --profile codex --kind codex \
  --session-id NATIVE_SESSION_ID --directory /home/you/project
cly snapshot adopt 12345 --profile codex --kind codex \
  --session-id NATIVE_SESSION_ID --directory /home/you/project --bypass \
  --resume-arg=--model --resume-arg=MODEL
```

Supply the PID and native ID of the same active agent. Adoption checks process
liveness and history, not their association. It does not discover arbitrary
terminal windows or migrate an older terminal-layout snapshot.
Codex adoption reads the exact session's latest recorded permissions when no
explicit policy is supplied. `--bypass` or `--resume-arg` permission settings take
precedence over earlier history. Other agents' adoption needs explicit resume
settings to preserve launch choices; unknown permissions are labeled `unknown`.

### Terminals and another computer

Automatic terminal selection uses Windows Terminal on Windows, Terminal.app on
macOS, or the first available Linux adapter. You can choose explicitly:

```sh
cly snapshot restore latest --terminal wt
cly snapshot restore latest --terminal terminal
cly snapshot restore latest --terminal tmux
cly snapshot restore latest --terminal gnome-terminal
```

`konsole` and `x-terminal-emulator` are also supported adapters. tmux restores a
detached workspace; attach it using the workspace name shown by `tmux ls`.

Windows managed agents inherit an attached console, including an invisible
console used for captured output; background commands do not open desktop
windows. Native `.cmd`/`.bat` launchers are resolved even without Bash's executable
bit and preserve literal arguments through the native batch parser. That parser
has a command-length limit; cly refuses batch arguments with line breaks or
commands over 8,000 characters. Use a native executable profile or stdin for
larger payloads.

Profiles and native histories must exist on the destination machine. Home-relative
directories map to the destination home when the hostname differs. Map other roots
explicitly; a mapping covers that root and its descendants:

```sh
cly snapshot restore SNAPSHOT_ID --map-dir '/old/projects=/new/projects' --dry-run
```

Copying a snapshot alone does not transfer agent histories, repositories or
credentials. The initial implementation has local Windows managed-launch validation
and fixture checks for terminal command construction. Actual terminal reopen and
native macOS/Linux agent sessions have not been exercised in that validation.

## Build a shared session-memory library

`document` reads supported local native stores, including histories opened outside
cly. It stores normalized user/assistant prose as JSON and Markdown, keyed by
`(agent, native session ID)`. Repeat captures update changed conversations without
creating another identity. Tool output, reasoning and injected system instructions
are excluded from supported native captures.

```sh
cly document                     # same as document capture
cly document capture --agent codex --agent claude
cly document status
cly document start               # background capture every 900 seconds
cly document start --interval 900 --agent codex --agent claude
cly document stop
```

`document watch` runs the collector in the foreground. `start` runs one background
collector with a process lock and a local log. Optional startup is configured with
`document startup enable|disable|status`; it is disabled by default. It does not
replace an existing PARA scheduler. Stop an existing collector before changing its interval
or selected providers.

Status reports capture errors, provider coverage, pending reviews, pending filing,
pending publications and collector liveness. A failed provider does not erase
already captured sessions. A capture with errors returns a failure status so a
scheduler can detect incomplete coverage. Restrict `--agent` when a store needs an
export; errors recorded for other providers remain visible until those providers
are captured successfully.

### Catch up with one model

```sh
cly document catch-up
cly document catch-up --agent claude --agent codex --profile codex
cly document catch-up --profile claude --model YOUR_MODEL
```

Without a profile, catch-up captures current prose and writes `catch-up.md` with
links to pending conversations. Use that packet and the local notes with a model
of your choice.

With a Claude or Codex profile, the same selected model reviews pending conversations
across the library in sequential batches. `--agent` selects stores to refresh, not a subset of previously
captured pending conversations. `--model` is passed to the chosen agent, so capture
and storage do not depend on a particular model. Claude review disables tools;
Codex review requests its read-only sandbox. cly removes its stored interactive
remote and bypass flags for the review job.

The requested output is a filing proposal that distinguishes confirmed constraints,
corrections and results from proposals, cites session IDs and treats transcripts
as untrusted data. Successful nonempty output creates a report and advances review
receipts for those revisions. A failed call leaves those revisions pending.
"Reviewed" records successful report generation; it does not verify the report's
judgments. Catch-up batches sessions, splits oversized sessions/messages into lossless
labeled parts, then reconciles the reports across agents. Successful batch and
fragment receipts let retries reuse completed work. Input is capped at 500,000
bytes per call; `--batch-bytes` can adjust that for the chosen model. This is a
byte bound, so the model can still report its own context-limit error. An oversized
final reconciliation fails with completed receipts retained; prose is never silently
truncated.

### Propose and file curated notes

Ask the chosen model for a filing plan instead of a prose review:

```sh
cly document catch-up --profile codex --filing-plan
cly document catch-up --profile claude --model YOUR_MODEL --filing-plan
```

The command prints the generated JSON plan's path. Review its proposed destinations,
full Markdown content and source identities before applying it:

```sh
cly document file /path/to/library/reviews/GENERATED_PLAN.json \
  --para-write /home/you/bin/para-write \
  --vault-root /home/you/para
```

A plan creates **new** Markdown notes within PARA. It cannot replace a README or an
existing note without receipts from this same plan. All destinations are checked
before publishing, and cited sources must still match their captured library
revisions. If a capture changed after generating the plan, generate a new plan.

Each publication requires the writer's remote checksum verification. Partial
failure retains verified destination receipts but leaves source filing revisions
pending. Rerunning the same plan rechecks its original staged files and attempts
destinations not previously attempted. An uncertain prior upload is preserved
when verification fails; inspect the remote note instead of blindly rewriting it.
Source revisions receive filing receipts only when the entire plan
has verified successfully. Sources omitted from the proposal remain pending.

A valid model result with no durable findings produces a successful plan with
`notes: []` and `outcome: "no-findings"`. Its batch evidence is cached without
marking sources filed or reviewed. There is no note to apply with `document file`.

This provides explicit model-assisted creation of curated notes. Semantic accuracy
still needs your review. Reconciliation into existing notes, project hubs and a
broader PARA reorganization remain separate work in the [roadmap](roadmap.md).

### Publish raw captures to PARA

PARA publication is an explicit bridge through an existing verified writer:

```sh
cly document publish \
  --para-write /home/you/bin/para-write \
  --vault-root /home/you/para
```

Use the extensionless Bash `para-write` script, including on Windows. Its interface
must accept `SOURCE VAULT_RELATIVE_PATH`, and `--check VAULT_RELATIVE_PATH SOURCE`
must return success only after verifying the remote file. cly stages notes locally,
calls the writer, then calls its verification mode. It never writes directly to the
mounted vault. Only verified revisions receive publication receipts; partial
failures remain pending.

Destinations are
`2-Areas/memory/sessions/AGENT/YYYY-MM/YYYY-MM-DD-HHMM-AGENT-NATIVE_ID.md`.
An existing matching note keeps its destination, frontmatter and established
project links. Its mounted bytes must first match the remote writer's exact
verification; a stale copy or failed check leaves it pending. Multiple matches or
malformed frontmatter fail for manual review.
The raw transcript body is replaced by the latest capture, so this command belongs
on capture notes rather than manually curated prose notes. A review report is not
published automatically by this command.

### Import another provider

Agents with unsupported store formats can export a normalized JSON object:

```json
{
  "agent": "my-agent",
  "session_id": "native-id-123",
  "started": "2026-10-07T10:30:00Z",
  "directory": "/home/you/project",
  "title": "Project session",
  "messages": [
    {"role": "user", "content": "Keep the public command simple."},
    {"role": "assistant", "content": "I prepared a proposed change."}
  ]
}
```

```sh
cly document import session-export.json
```

Only user/assistant string content is accepted; extra fields are dropped. The
exporter must remove reasoning, tool output and injected instructions before
import. Agent names must be lowercase portable slugs; case aliases and Windows
reserved folder names are rejected. An imported conversation joins the same
review/publication queue. Import
does not create a native resumable history or an active process binding.

## Provider coverage

Native formats evolve. These are the reader contracts for this version, not a
promise that every installed agent version has been tested.

| Agent | Snapshot history check | Native prose capture |
|---|---|---|
| Claude | Project JSONL; automatic ID for ordinary new sessions | User/assistant JSONL |
| Codex | Thread SQLite metadata or rollout JSONL | Rollout response and completed-item prose, paired to avoid duplicate representations |
| Gemini | Project chat JSON | User and Gemini messages |
| Qwen | Compatible session JSONL | Claude-style message records; other formats require export |
| OpenCode | `opencode.db` SQLite | User/assistant text parts; excludes synthetic, ignored and tool parts |
| Kimi | Session `state.json` metadata | `context.jsonl` when present; newer wire-only stores require export/import |
| Muse | Native session metadata | Current Muse event prose is not supported; use export/import |
| Antigravity and other profiles | Inventory can be tracked; native restore preflight is unsupported | Export/import |

Resume IDs come from explicit native arguments, supported lifecycle hooks or
manual bindings. Unsupported hook integrations require manual binding.
Missing or unreadable history blocks restore.
Empty or unrecognized supported-store prose is not evidence of complete capture;
check the provider counts and errors in `document status`.

## Storage and privacy

By default, workflow state is under `${XDG_STATE_HOME:-~/.local/state}/cly` and the
library under `${XDG_DATA_HOME:-~/.local/share}/cly/library`. On Windows, `~` means
the user profile. Nothing is written to the repository.

| Variable | Purpose |
|---|---|
| `CLY_STATE_HOME` | Override the entire workflow-state directory |
| `CLY_LIBRARY_HOME` | Override the entire session-library directory |
| `CLY_PYTHON` | Select a Python 3.9+ executable |
| `CLY_SHELL` | Select Bash for workflow child commands; normally supplied by cly |
| `CLY_TRACK=0` | Disable launch tracking |
| `CLY_TRACK=1` | Require tracking and Python; opt in when `CLY_BIN` overrides the executable |
| `CLY_MUSE_HOME` | cly's override for the Muse data-store root |
| `CLY_OPENCODE_HOME` | cly's override for the OpenCode data-store root |

Readers also honor `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `GEMINI_CLI_HOME`,
`KIMI_CODE_HOME` and `QWEN_HOME`. Snapshot restore queries the selected profile's
exported environment for its native root. Document capture and the modern picker
discover configured profiles and their store overrides, deduplicating shared
roots. `document sources` reports coverage and unsupported formats. See
[session tracking](session-tracking.md) for handoffs, startup and structured health.

Snapshots persist native IDs, process identities, profile names, directory/store
paths and timestamps. They omit command arguments, prompts, credentials and
environment values. The document library deliberately contains conversation prose,
which can itself contain private information. Keep it and model reports private;
an explicit model catch-up sends the pending prose to the configured provider.
Local files use restrictive permissions where the operating system supports them.

## Run the isolated pipeline checks

```sh
python test-workflows.py
python test-snapshot-reload.py
python test-snapshot-options.py
python test-windows-batch.py
python test-snapshot-console.py
python test-document-pipeline.py
```

The workflow check exercises native format boundaries, model failures and receipt
logic with fixtures. The reload check covers confirmation, preflight, process
identity safety, stop failures and recovery with fixtures and disposable hidden
processes. It does not stop real agent sessions or open terminals.
Windows batch and console checks execute literal argument fixtures and managed
native probes inside an invisible ConPTY. They preserve captured output and
console attachment without opening desktop windows or starting real agents.
Actual provider UI and keyboard behavior require their own runtime check.
The document pipeline check invokes the actual document commands against
temporary stores and a local writer that copies and verifies bytes. It covers
Unicode paths, revisions, malformed/torn sources, stale indexes, partial writes,
changed remote notes and retries. These checks do not call live models or Drive.

To include an installed PARA validator without publishing, pass
`--validator-root PATH_TO_DIRECTORY_CONTAINING_PARALIB` to the second command.
`--results REPORT.json` saves an isolated command/check report locally.

cly probes `WRITER --capabilities` for `prepare-v1`. Supporting writers accept
`WRITER --prepare SOURCE VAULT_PATH OUTPUT`, producing destination-correct bytes
locally without uploading or changing SOURCE. cly stages those exact bytes before
hashing, uploading and checking them. Preparation failure prevents upload; retries
reuse the first staged artifact. The installed PARA writer supports this from
version 1.2.0. Older writers remain supported, but must upload the staged bytes
unchanged to pass exact verification. Writer-side conditional creation/version
checks remain needed to close the initial existence-check/write race.

See the [roadmap](roadmap.md) for optional GUI work and remaining portability and
filing improvements.
