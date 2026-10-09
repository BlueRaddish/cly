# Session discovery, tracking and context handoffs

The session picker uses the shared Python readers when Python is available.
Codex subagent histories are excluded using their native source metadata, both
from rollout files and from JSON-encoded SQLite source values. Main terminal,
Desktop and imported histories remain available. A random-looking ID alone is
not evidence that a conversation is a subagent.

## Find a conversation

```sh
cly -r
cly --find "Project planning"
cly -r --find "Project planning" work
cly --session codex:NATIVE_SESSION_ID
```

Press `n` in the session picker to search its name/title column. `/` searches the
broader row. `--find` opens the same picker with a name search already applied;
it never resumes the first match automatically. A named profile narrows discovery
to that profile's store and resumes through that profile.

Codex names use a nonempty SQLite `name`, then the latest `session_index.jsonl`
`thread_name`, then SQLite `title`, with the native ID as a final fallback.
Recent activity uses native updated timestamps where available. Session IDs stay
stable when names change. Native histories are read without modifying their stores.
Fallback prompt titles are limited to 240 characters in the picker; explicit
native names remain fully searchable.
Claude names use the native custom-title file, then history prompt metadata;
history timestamps preserve recent activity in the picker.

`cly --list-sessions` preserves the five-column machine interface: epoch, agent,
native ID, directory and title, separated by ASCII 31. Terminal control characters
in modern-reader output are replaced with spaces. Duplicate IDs across different
stores are withheld when a profile cannot be selected safely; choose an explicit
profile. `CLY_SESSION_READER=bash` forces the compatibility reader, which has its
older provider coverage and scan limits.

## Discover configured stores

```sh
cly document sources
cly document status
cly document capture --agent codex --agent claude
```

`sources` returns JSON for configured profiles and uncovered native providers.
Each entry includes the profile, agent kind, store path, existence, capabilities
and discovery errors. Profile store overrides are honored without running the
configured executable or exposing API keys and other profile environment values.
Capture visits every configured store for the selected kinds and records
per-profile coverage. Unknown native formats remain visible as unsupported.

| Agent | Capture | Native resume validation | Lifecycle tracking |
|---|---|---|---|
| Claude | Native user/assistant JSONL | Supported | Scoped SessionStart hooks |
| Codex | Native public rollout prose | Supported | Hooks available; runtime setup required |
| Gemini | Native chat JSON | Supported | Explicit ID/manual binding |
| OpenCode | Native text parts | Supported | Explicit ID/manual binding |
| Kimi | Partial; context JSONL, wire-only requires import | Supported | Explicit ID/manual binding |
| Qwen | Partial; compatible JSONL | Supported | Explicit ID/manual binding |
| Muse | Native metadata; prose requires import | Supported | Explicit ID/manual binding |
| Antigravity/other formats | Normalized export/import | Unsupported native preflight | Manual |

Capabilities describe reader contracts. They do not certify every installed
provider version. Empty captures and malformed files are reported through status.

## Track exact session switches

```sh
cly snapshot status
cly snapshot hooks --kind codex --output codex-session-hooks.json
cly snapshot bind RUN_ID NATIVE_SESSION_ID
```

Managed Claude launches receive per-launch hook settings unless explicit
`--settings` were supplied. Supported main-session `SessionStart` events for
startup, resume, clear and compact update the run's native ID through a separate
lifecycle journal. The receiver excludes subagent events, validates transcript
identity/store containment when supplied, and stores no prompt text.

Codex hook configuration can be exported, but the native hook must be installed
and trusted through Codex's supported hook controls. The runtime executing the
hook must inherit `CLY_RUN_ID` and cly's state environment. A shared Desktop/app
server does not necessarily inherit the launching terminal's run identity, so
cly reports hooks as available and keeps manual binding for that boundary.
Explicit resume IDs and ordinary new Claude IDs remain supported independently.
The exact hook association is never inferred from the newest file or timing.

## Reload saved sessions

```sh
cly snapshot reload latest --dry-run
cly snapshot reload SNAPSHOT_ID
```

Reload previews all tracked active agent families to stop and the saved
conversations to reopen, then asks you to type `reload` before stopping active
sessions. cly cannot tell whether a running session is idle or doing work; the
warning covers interrupted responses and tools. Use a separate terminal, since
reload refuses to stop its own process
or ancestors. `--yes` accepts the warning explicitly for noninteractive use.
`--force` allows SIGKILL after the Unix stop timeout; Windows termination is
immediate even without that flag.

Native history and terminal preflight must pass before any stop. A recovery
snapshot and structured `reloads/*.json` receipt preserve the current tracked
inventory and reload outcome. Unbound conversations in the recovery snapshot
remain unresolved. Changes to the active inventory or process families abort the
operation, and stop failures prevent reopening. Inspect a failed receipt before
retrying a partial terminal launch. See the
[reload workflow](workflows.md#reload-from-a-snapshot) for the full command and
recovery boundaries.

## Transfer selected context

```sh
cly document capture --agent codex
cly handoff export handoff.json --session codex:NATIVE_SESSION_ID \
  --project my-project --project-root . --context README.md --target-agent claude
cly handoff import handoff.json
cly handoff show handoff.json --output handoff-context.md
cly handoff list
```

Repeat `--session` and `--context` to select multiple inputs. Conversations must
already be in the normalized library. Context files must be selected UTF-8 files
inside `--project-root`; `--project` gives them a stable project identity. Relative
project URIs identify the same context across devices, while origin references
record where it came from. Target agent is informational.

Packets carry stable entry identities, revisions, source references and checksums.
Exports are reread before a verified receipt is saved. Imports validate the whole
packet, stage its original contents, and report current, imported, stale or
conflicting entries. Divergent local conversation/context revisions are preserved
for review. Context is kept in the local library; importing does not overwrite
project files or create a native resumable conversation in another agent.
`show` renders a readable context packet with source revisions, ready to provide
to a target agent on this device or another device.

## Capture health, retries and startup

```sh
cly document start --interval 900
cly document status
cly document startup enable --interval 900 --agent codex --agent claude
cly document startup status
cly document startup disable
cly document publish --para-write ~/bin/para-write --vault-root ~/para
```

Startup is opt-in and runs at the user's login after reboot: Windows per-user Run,
macOS LaunchAgent or Linux user systemd. Windows uses `pythonw.exe` and hidden child
processes. Collector locks prevent simultaneous capture workers. Existing
startup registrations changed outside cly are preserved for review.

Re-run publication to retry pending exports. Intended staged bytes and revision
receipts survive interruptions. A retry verifies uncertain prior uploads before
writing again; changed remote notes are preserved. Successful publication requires
the writer's checksum verification, not merely a successful process exit.

`document status` is JSON with schema/type, overall health, warnings/errors,
per-profile sources, provider coverage, collector liveness, capture health,
startup registration and pending exports. These fields are suitable for ParaDesk
to display without scraping terminal prose. Pending review, filing and publication
are separate queues. Startup registration, hook delivery in real agent sessions,
and other-platform behavior need their own runtime validation; fixture checks do
not prove reboot or provider integration.

See [workflow storage and privacy](workflows.md#storage-and-privacy) for state and
library locations. The normalized library and handoff packets intentionally contain
selected conversation/project prose, which can itself contain private information.

Provider contracts: [Claude hooks](https://code.claude.com/docs/en/hooks),
[Claude CLI settings](https://code.claude.com/docs/en/cli-reference), and
[Codex hooks](https://learn.chatgpt.com/docs/hooks).
