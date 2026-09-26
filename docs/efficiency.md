# Efficiency review — 2026-09-26

Measured on the installed Windows checkout through Git for Windows Bash.
These are local single-run timings, not guarantees for other disks or stores.
The picker measurement calls the real discovery, sorting, formatting and draw
functions, then supplies Escape; it excludes terminal-size negotiation and agent
startup. No agent was launched during these checks.

| Work | Before | After |
| --- | ---: | ---: |
| Codex discovery, 160 rollouts | 79.857 s | 0.371 s |
| Claude discovery, 42 sessions | 0.438 s | 0.385 s |
| All-agent picker through first frame | not separately measured | 0.970 s |
| Sort 2,000 deterministically shuffled rows | 26.852 s | 0.987 s |
| Complete session export through Windows launcher | not measured | 1.033 s |
| Windows launcher version / help | not measured | 0.087 / 0.083 s |

## Changes

- Codex discovery previously opened every rollout and processed its entire
  first line, about 18–22 KB in this store. History-backed rows now defer that
  work. Imported sessions read only enough metadata for their UTC timestamp
  and directory; no session is dropped to make discovery faster.
- Metadata reads stop in 512-character chunks once the required fields are
  available. Long paths continue across chunks; parsing stops at the first
  newline so later conversation events cannot supply a false directory.
- Discovery retains rollout paths, avoiding another directory-tree traversal
  for every directory lookup. Metadata, including missing directories, is
  cached only within an invocation. Scrolling and repeated searches reuse it.
- Visible rows resolve directories on draw. Directory searches also resolve
  unmatched off-screen rows, retaining the ability to find those sessions.
- Exact `--session KIND:ID` requests inspect only the requested agent's store
  and still respect any explicit profile-kind restriction.
- A merge sort replaces the quadratic insertion sort. Numeric descending
  timestamps and the previous reverse-discovery ordering for ties remain.

## Broader review and remaining limits

The Windows launcher already avoids a login shell when using Git Bash. Normal
launch, config loading, menu construction, installation and argument forwarding
do not enumerate session stores; they did not justify additional caching or
changes. Small profile/config rereads remain. Agent startup and remote-control
daemon startup are outside these picker measurements.

Claude still scans prompt history and checks transcript/title files. At about
0.4 seconds in this store it is now the largest measured discovery component,
but a persistent cache would introduce invalidation complexity without evidence
that it is needed. Both Claude and Codex histories are read whole, so very large
histories will still cost memory and processing time. Codex still enumerates
all rollout filenames to include imported sessions and exclude deleted ones.

Gemini and Kimi retain their existing newest-file limits (twice `CLY_ROWS`).
This is not an exhaustive older-session browser for those stores. Gemini's
newest-file selection is O(files × requested rows), and selecting the latest
session with `--continue` is linear. Neither had meaningful cost in this local
store. A future exhaustive browser should page those stores with their native
metadata rather than silently increasing the scan bounds.

Metadata without the expected fields can still require reading its whole
first line. This intentionally favors correct long/reordered metadata over a
fixed truncation limit. A structured reader would be the next step if malformed
or unusually ordered headers become a measured bottleneck.

## Verification

Run `bash test.sh` and `bash test-performance.sh`. The original suite passes
419 checks; two Windows permission checks and unavailable ShellCheck are skipped.
The performance checks use isolated synthetic stores and assert bounded reads,
cache reuse, off-screen directory search, long escaped paths, metadata-only
parsing, imported-session timestamps, and sorting including ties and empty lists.
They fail against the pre-change loader's eager transcript reads. They use no
wall-clock thresholds or additional test framework.

An independent Python JSON parse of the real store also confirmed that all 160
exported Codex IDs, timestamps and launch directories match the source history
and metadata. No real session files or configuration were modified.
