#!/usr/bin/env bash
# Deterministic checks for bounded reads and ordering; no timing thresholds,
# real session stores, or agent launches. Optional argument: script to test.
set -eu
self_dir=$(cd "$(dirname "$0")" && pwd)
source <(sed '/^cly_main "\$@"/,$d' "${1:-$self_dir/bin/cly}")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
export CODEX_HOME="$work/codex"
mkdir -p "$CODEX_HOME/sessions/2026/09/01"
check() { if ! "$@"; then printf 'FAIL: %s\n' "$*" >&2; exit 1; fi; }

# Large instruction tails must not be read just to find an early cwd.
printf -v tail '%22000s' ''
for ((i=1;i<=4;i++)); do
    printf -v sid '00000000-0000-0000-0000-%012d' "$i"
    printf '{"session_id":"%s","ts":%s,"text":"test"}\n' "$sid" "$i" >> "$CODEX_HOME/history.jsonl"
    printf '{"timestamp":"2026-09-01T00:00:01Z","payload":{"timestamp":"2026-09-01T00:00:00Z","cwd": "/project-%s","instructions":"%s"}}\n' "$i" "$tail" \
        > "$CODEX_HOME/sessions/2026/09/01/rollout-2026-09-01T00-00-0$i-$sid.jsonl"
done
read_calls=0
read() { read_calls=$((read_calls + 1)); builtin read "$@"; }
(
    cly_pick_session codex 1
    check test "$read_calls" = 1
    check test "$row_cwd" = /project-4
)
cly_sessions_codex
check test "${#ses_rows[@]}" = 4
check test "$read_calls" = 0
cly_sort_rows
cly_session_lines
check test "$read_calls" = 0
cly_screen_filter ''
cly_screen_rowtext 0 0
check test "$read_calls" = 1
check test "${#codex_cwds[@]}" = 1
check test "$row_cwd" = /project-4
cly_screen_rowtext 0 0
check test "$read_calls" = 1
cly_screen_rowtext 3 3
check test "$read_calls" = 2
check test "$row_cwd" = /project-1
# Searching directories must still find a row that has never been drawn.
cly_screen_filter project-2
check test "${#scr_match[@]}" = 1
cly_row_fields "${ses_rows[scr_match[0]]}"
check test "$row_cwd" = /project-2

# A missing cwd stays within the metadata line, never a later event.
f="$work/header.jsonl"
codex_rollouts[missing]=$f
printf '{"payload":{}}\n{"cwd":"/wrong-event"}\n' > "$f"
cly_session_cwd codex missing
check test "$jv" = ''
before=$read_calls
cly_session_cwd codex missing
check test "$read_calls" = "$before"

# Paths can cross chunk boundaries, contain escaped quotes/backslashes,
# and end at EOF without a newline. No fixed prefix limit may truncate them.
printf -v padding '%1100s' ''
printf '%s' '{"cwd":"C:\\Users\\'"$padding"'\\a\"b"}' > "$f"
codex_rollouts[long]=$f
cly_session_cwd codex long
check test "$jv" = 'C:\Users\'"$padding"'\a"b'

# Clearing/reloading discovery invalidates cached metadata within a process.
ses_rows=()
cly_sessions_codex
check test "${#codex_cwds[@]}" = 0
# Imported sessions use their actual UTC metadata time, not local filenames.
rm "$CODEX_HOME/history.jsonl"
read_calls=0
ses_rows=()
cly_sessions_codex
check test "$read_calls" = 4
cly_iso_epoch 2026-09-01T00:00:00Z
expected_epoch=$epoch
for row in "${ses_rows[@]}"; do
    cly_row_fields "$row"
    check test "$row_epoch" = "$expected_epoch"
done

# Compare every sorted row, including ties, to an independent reference.
ses_rows=()
for ((i=0;i<1001;i++)); do
    cly_add_row "$(( (i * 7919) % 97 ))" codex "$i" '' "title $i"
done
for ((i=${#ses_rows[@]}-1;i>=0;i--)); do printf '%s\n' "${ses_rows[i]}"; done \
    | LC_ALL=C sort -s -t "$CLY_US" -k1,1nr > "$work/expected"
cly_sort_rows
printf '%s\n' "${ses_rows[@]}" > "$work/actual"
check cmp "$work/expected" "$work/actual"
ses_rows=(); cly_sort_rows
check test "${#ses_rows[@]}" = 0
cly_add_row 0 codex only '' title
cly_sort_rows
check test "${#ses_rows[@]}" = 1
printf 'Performance regression checks passed\n'
