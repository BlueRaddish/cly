#!/usr/bin/env bash
# test.sh — cly's test suite. No Claude Code is launched: CLY_BIN points at a
# stub that prints its working directory and its arguments, which is the entire
# observable behaviour of cly. CLY_CONFIG points into a scratch directory, so
# the real ~/.config/cly/config is unreachable from here.
#
# usage: ./test.sh

set -u

self_dir=$(cd "$(dirname "$0")" && pwd)
cly="$self_dir/bin/cly"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

export CLY_CONFIG="$work/config"
stub="$work/claude-stub"
cat > "$stub" <<'EOF'
#!/usr/bin/env bash
printf 'PWD=%s\n' "$(pwd)"
for a in "$@"; do printf 'ARG=%s\n' "$a"; done
EOF
chmod +x "$stub"
export CLY_BIN="$stub"

pass=0
fail=0
skip=0

ok()   { pass=$((pass + 1)); }
bad()  { fail=$((fail + 1)); printf 'FAIL %s\n' "$1"; [ $# -gt 1 ] && printf '     %s\n' "$2"; }
note() { skip=$((skip + 1)); printf 'SKIP %s\n' "$1"; }

# Assert that running cly with these arguments produces output containing
# (or, with want_absent, not containing) a line.
has() {  # has LABEL NEEDLE HAYSTACK
    case $3 in
        *"$2"*) ok ;;
        *) bad "$1" "expected to find: $2" ;;
    esac
}
hasnt() {
    case $3 in
        *"$2"*) bad "$1" "expected NOT to find: $2" ;;
        *) ok ;;
    esac
}
eq() {  # eq LABEL EXPECTED ACTUAL
    if [ "$2" = "$3" ]; then ok; else bad "$1" "expected [$2], got [$3]"; fi
}

reset_config() { rm -f "$CLY_CONFIG"; }
write_config() { printf '%s\n' "$@" > "$CLY_CONFIG"; }

# Everything runs with stdin closed, so the first-run prompt can never fire and
# hang the suite. The prompt itself is exercised by feeding a here-doc instead.
run() { "$cly" "$@" </dev/null 2>"$work/err"; }
err() { cat "$work/err"; }

# --- help ---------------------------------------------------------------------

out=$(run --cly-help); rc=$?
eq   'help exits 0' 0 "$rc"
has  'help names the tool' 'cly — launch Claude Code' "$out"
has  'help has a usage line' 'usage: cly' "$out"
has  'help has examples' 'EXAMPLES' "$out"
eq   'help writes nothing to stderr' '' "$(err)"

long=$(printf '%s\n' "$out" | awk 'length > 95 { c++ } END { print c + 0 }')
eq   'help wraps under 95 columns' 0 "$long"

# Documented flags and parsed flags must be the same set — help that has
# drifted from behaviour is the bug this catches.
documented=$(printf '%s\n' "$out" \
    | awk '/^OPTIONS$/ { on = 1; next } /^[A-Z]+$/ { on = 0 } on' \
    | grep -o -- '--cly-[a-z-]*' | sort -u)
parsed=$(grep -o -- '^            --cly-[a-z-]*' "$cly" | tr -d ' ' | sort -u)
eq   'documented flags == parsed flags' "$parsed" "$documented"

# --- no config ----------------------------------------------------------------

reset_config
here=$(pwd)
out=$(run)
has  'no config launches here' "PWD=$here" "$out"
has  'no config uses default flags' 'ARG=--remote-control' "$out"
has  'no config uses default flags (2)' 'ARG=--dangerously-skip-permissions' "$out"
[ -f "$CLY_CONFIG" ] && bad 'no config writes no config' 'config was created' || ok

# --- init ---------------------------------------------------------------------

reset_config
target="$work/pinned"
out=$(run --cly-init "$target"); rc=$?
eq   'init exits 0' 0 "$rc"
[ -d "$target" ] && ok || bad 'init creates the directory'
has  'init reports the directory' "launch directory  $target" "$out"
has  'init reports the flags' 'standing flags    --remote-control' "$out"
has  'config records the directory' "dir=$target" "$(cat "$CLY_CONFIG")"
has  'config records the flags' 'flags=--remote-control --dangerously-skip-permissions' "$(cat "$CLY_CONFIG")"

out=$(run)
has  'configured directory is used' "PWD=$target" "$out"

out=$(run --cly-init); rc=$?
eq   'init without a directory or a tty exits 2' 2 "$rc"
has  'init without a tty says why' 'needs a directory' "$(err)"

# The prompt, driven by a here-doc: directory, then flags.
reset_config
printf '%s\n%s\n' "$target" 'none' | "$cly" --cly-init >"$work/out" 2>&1
has  'prompt accepts a directory' "launch directory  $target" "$(cat "$work/out")"
has  'prompt accepts none for flags' 'standing flags    (none)' "$(cat "$work/out")"
has  'prompt writes empty flags' 'flags=' "$(cat "$CLY_CONFIG")"

reset_config
printf '\n\n' | "$cly" --cly-init >"$work/out" 2>&1
has  'empty answer means launch here' 'launch directory  (wherever you are)' "$(cat "$work/out")"
has  'empty answer keeps the default flags' 'standing flags    --remote-control' "$(cat "$work/out")"

# --- precedence ---------------------------------------------------------------

write_config "dir=$target" 'flags=--verbose'
out=$(run)
has  'config flags are used' 'ARG=--verbose' "$out"
hasnt 'config flags replace the defaults' 'ARG=--remote-control' "$out"

out=$(run --cly-no-dir)
has  '--cly-no-dir launches here' "PWD=$here" "$out"

other="$work/other"; mkdir -p "$other"
out=$(run --cly-dir "$other")
has  '--cly-dir wins over the config' "PWD=$other" "$out"

out=$(CLY_DIR="$other" run)
has  'CLY_DIR wins over the config' "PWD=$other" "$out"

out=$(CLY_DIR="$other" run --cly-no-dir)
has  '--cly-no-dir wins over CLY_DIR' "PWD=$here" "$out"

out=$(CLY_FLAGS='' run)
hasnt 'empty CLY_FLAGS means no flags' 'ARG=' "$out"

out=$(CLY_FLAGS='--one --two' run)
has  'CLY_FLAGS wins over the config' 'ARG=--one' "$out"
hasnt 'CLY_FLAGS replaces the config flags' 'ARG=--verbose' "$out"

write_config "dir=$target" 'flags='
out=$(run)
hasnt 'empty flags= means no flags' 'ARG=' "$out"

# --- passthrough --------------------------------------------------------------

write_config "dir=$target" 'flags=--verbose'
out=$(run --resume -p 'two words')
has  'passthrough keeps a flag' 'ARG=--resume' "$out"
has  'passthrough keeps a quoted argument' 'ARG=two words' "$out"
has  'passthrough comes after the standing flags' 'ARG=--verbose' "$out"

out=$(run -- --cly-no-dir)
has  'after -- nothing is claimed by cly' 'ARG=--cly-no-dir' "$out"
has  'after -- the directory still applies' "PWD=$target" "$out"

out=$(run --cly-dir); rc=$?
eq   '--cly-dir without a directory exits 2' 2 "$rc"
has  '--cly-dir without a directory says usage' 'usage: cly' "$(err)"

# --- awkward cases ------------------------------------------------------------

write_config "dir=$work/deleted" 'flags='
out=$(run)
has  'a deleted directory warns' 'does not exist' "$(err)"
has  'a deleted directory still launches' "PWD=$here" "$out"

printf 'dir=%s\r\nflags=--crlf\r\n' "$target" > "$CLY_CONFIG"
out=$(run)
has  'a CRLF config is read' "PWD=$target" "$out"
has  'a CRLF config loses the carriage return' 'ARG=--crlf' "$out"

if command -v cygpath >/dev/null 2>&1; then
    win=$(cygpath -w "$target")
    write_config "dir=$win" 'flags='
    out=$(run)
    has 'a Windows path in the config is understood' "PWD=$target" "$out"
else
    note 'a Windows path in the config is understood (no cygpath)'
fi

write_config 'dir=~' 'flags='
out=$(run --cly-dir '~')
has  'a tilde is expanded' "PWD=$HOME" "$out"

# --- config report ------------------------------------------------------------

write_config "dir=$target" 'flags=--verbose'
out=$(run --cly-config); rc=$?
eq   '--cly-config exits 0' 0 "$rc"
has  '--cly-config names the file' "$CLY_CONFIG" "$out"
has  '--cly-config shows the directory' "launch dir:   $target" "$out"
has  '--cly-config shows the flags' 'flags:        --verbose' "$out"
has  '--cly-config shows the executable' "executable:   $stub" "$out"
hasnt '--cly-config launches nothing' 'PWD=' "$out"

reset_config
out=$(run --cly-config)
has  '--cly-config with no config says so' 'none yet' "$out"
[ -f "$CLY_CONFIG" ] && bad '--cly-config writes no config' 'config was created' || ok

# --- profiles -----------------------------------------------------------------

# A profile that has to answer without launching anything: --cly-config reports
# the executable, and only there can the profile's own bin be seen at all, since
# CLY_BIN is set for the whole suite and outranks it.
run_config() { ( unset CLY_BIN; "$cly" "$@" --cly-config </dev/null 2>"$work/err" ); }

profile_config() {  # profile_config [EXTRA-LINE...]
    write_config "dir=$target" 'flags=--verbose' \
        'profile.codex.bin=codex' \
        'profile.codex.flags=--full-auto' \
        'profile.codex.dir=none' \
        "$@"
}

profile_config
out=$(run codex)
has  'a bare profile name is claimed' 'ARG=--full-auto' "$out"
hasnt 'a profile replaces the standing flags' 'ARG=--verbose' "$out"
has  'a profile dir of none launches here' "PWD=$here" "$out"
hasnt 'a profile name is not passed on' 'ARG=codex' "$out"

out=$(run_config codex)
has  'a profile names its own executable' 'executable:   codex' "$out"
has  '--cly-config names the active profile' 'profile:      codex' "$out"
has  '--cly-config lists the profiles' 'profiles:     codex' "$out"

out=$(run codex --resume 'two words')
has  'a profile still passes arguments on' 'ARG=--resume' "$out"
has  'a profile still passes quoted arguments on' 'ARG=two words' "$out"

out=$(CLY_FLAGS='--env' run codex)
has  'CLY_FLAGS wins over a profile' 'ARG=--env' "$out"
hasnt 'CLY_FLAGS replaces the profile flags' 'ARG=--full-auto' "$out"
out=$(run codex --cly-dir "$other")
has  '--cly-dir wins over a profile' "PWD=$other" "$out"
out=$(run --cly-use codex)
has  '--cly-use selects the same profile' 'ARG=--full-auto' "$out"
out=$(run --cly-use codex hello)
has  '--cly-use leaves the first word alone' 'ARG=hello' "$out"

out=$(run --cly-use nope); rc=$?
eq   '--cly-use with an unknown name exits 2' 2 "$rc"
has  '--cly-use with an unknown name says so' "no profile named 'nope'" "$(err)"
has  '--cly-use with an unknown name lists the names' 'profiles configured: codex' "$(err)"

# Everything that is not a configured name is an argument, in the place it was
# typed. This is the whole safety of claiming a bare word.
out=$(run hello --resume)
args=$(printf '%s\n' "$out" | grep '^ARG=' | tr '\n' ' ')
eq   'an unknown first word keeps its place' 'ARG=--verbose ARG=hello ARG=--resume ' "$args"
has  'an unknown first word leaves the config alone' "PWD=$target" "$out"

out=$(run -- codex)
has  'after -- a profile name is only an argument' 'ARG=codex' "$out"
has  'after -- the configured directory still applies' "PWD=$target" "$out"

out=$(run 'codex is broken')
has  'a quoted argument is never a profile' 'ARG=codex is broken' "$out"

# claude is a profile nobody has to configure.
out=$(run claude)
has  'cly claude uses the configured directory' "PWD=$target" "$out"
has  'cly claude uses the standing flags' 'ARG=--verbose' "$out"
hasnt 'cly claude is not passed on' 'ARG=claude' "$out"

# A profile inherits what it does not mention.
write_config "dir=$target" 'flags=--verbose' 'profile.gem.flags=--sparse'
out=$(run gem)
has  'a profile without dir uses the configured one' "PWD=$target" "$out"
has  'a profile without dir keeps its own flags' 'ARG=--sparse' "$out"
out=$(run_config gem)
has  'a profile without bin is named after it' 'executable:   gem' "$out"

write_config "dir=$target" 'flags=--verbose' 'profile.gem.bin=gemini'
out=$(run gem)
hasnt 'a profile without flags gets none' 'ARG=' "$out"
out=$(run_config gem)
has  'a profile with bin uses it' 'executable:   gemini' "$out"
out=$(run --cly-config codex)
has  'CLY_BIN outranks a profile' "executable:   $stub" "$out"

# A commented-out example is not a profile.
write_config "dir=$target" 'flags=' '#   profile.example.bin=example'
out=$(run --cly-config)
has  'a commented profile is not read' 'profiles:     (none configured)' "$out"

# --cly-init rewrites two lines and must leave the rest of the file alone.
profile_config '# a comment of my own'
out=$(run --cly-init "$other")
cfg=$(cat "$CLY_CONFIG")
has  'init keeps profile lines' 'profile.codex.bin=codex' "$cfg"
has  'init keeps profile flags' 'profile.codex.flags=--full-auto' "$cfg"
has  'init keeps hand-written comments' '# a comment of my own' "$cfg"
has  'init still rewrites the directory' "dir=$other" "$cfg"
hasnt 'init leaves no second directory line' "dir=$target" "$cfg"

# none is what the prompt stores for "wherever you are", and it has to read
# back the same way in the file it was written to.
write_config 'dir=none' 'flags='
out=$(run)
has  'a directory of none launches here' "PWD=$here" "$out"

# --- shell hygiene ------------------------------------------------------------

if command -v shellcheck >/dev/null 2>&1; then
    if shellcheck -s bash "$cly" "$self_dir/install.sh" >"$work/sc" 2>&1; then ok
    else bad 'shellcheck is clean' "$(head -20 "$work/sc")"; fi
else
    note 'shellcheck is clean (shellcheck not installed)'
fi

if bash -n "$cly" 2>"$work/syn"; then ok; else bad 'bin/cly parses' "$(cat "$work/syn")"; fi
if bash -n "$self_dir/install.sh" 2>"$work/syn"; then ok; else bad 'install.sh parses' "$(cat "$work/syn")"; fi

# --- report -------------------------------------------------------------------

echo
printf '%s passed, %s failed, %s skipped\n' "$pass" "$fail" "$skip"
[ "$fail" = 0 ] || exit 1
