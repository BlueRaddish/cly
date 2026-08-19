#!/usr/bin/env bash
# test.sh — cly's test suite. No agent is launched: CLY_BIN points at a stub
# that prints its working directory and its arguments, which is the entire
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
stub="$work/agent-stub"
cat > "$stub" <<'EOF'
#!/usr/bin/env bash
printf 'PWD=%s\n' "$(pwd)"
for a in "$@"; do printf 'ARG=%s\n' "$a"; done
EOF
chmod +x "$stub"
export CLY_BIN="$stub"

# cly asks one more question when the tool being set up is not on PATH, so a
# suite that reads PATH is a suite whose piped answers land in different
# questions on different machines. Give it a PATH it owns.
mkdir -p "$work/bin"
for tool in codex claude; do
    printf '#!/usr/bin/env bash
printf "STUB=%%s\n" "$0"
' > "$work/bin/$tool"
    chmod +x "$work/bin/$tool"
done
PATH="$work/bin:$PATH"
export PATH

pass=0
fail=0
skip=0

ok()   { pass=$((pass + 1)); }
bad()  { fail=$((fail + 1)); printf 'FAIL %s\n' "$1"; [ $# -gt 1 ] && printf '     %s\n' "$2"; }
note() { skip=$((skip + 1)); printf 'SKIP %s\n' "$1"; }

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
config()      { cat "$CLY_CONFIG"; }

# Everything runs with stdin closed, so no prompt can fire and hang the suite.
# The prompts are exercised deliberately, by ask() below.
run() { "$cly" "$@" </dev/null 2>"$work/err"; }
err() { cat "$work/err"; }

# A run with answers fed in and a terminal claimed. CLY_ASSUME_TTY is the only
# way to reach the prompts without a pty; the script documents it as such.
ask() {  # ask ANSWERS ARG...
    local answers=$1; shift
    printf '%s' "$answers" | CLY_ASSUME_TTY=1 "$cly" "$@" 2>"$work/err"
}

here=$(pwd)
pinned="$work/pinned"; mkdir -p "$pinned"
other="$work/other";   mkdir -p "$other"

# --- tier 0: a bare cly -------------------------------------------------------

reset_config
out=$(run); rc=$?
eq   'bare cly exits 0' 0 "$rc"
has  'bare cly names the tool' 'cly — launch an agent CLI' "$out"
has  'bare cly shows the usage line' 'usage: cly [OPTION...] <PROFILE|.>' "$out"
has  'bare cly points at the default' 'cly .' "$out"
has  'bare cly points at the full help' "Run 'cly help' for more." "$out"
has  'bare cly says when nothing is configured' 'No profiles yet' "$out"
hasnt 'bare cly launches nothing' 'PWD=' "$out"
eq   'bare cly writes no config' '' "$(ls "$CLY_CONFIG" 2>/dev/null)"

write_config 'default=b' 'profile.a.bin=x' 'profile.b.bin=y'
out=$(run)
has  'bare cly lists the profiles' 'profiles: a, b (default)' "$out"

# --- help and version ---------------------------------------------------------

out=$(run help); rc=$?
eq   'help exits 0' 0 "$rc"
has  'help has a usage line' 'usage: cly [OPTION...]' "$out"
has  'help has examples' 'EXAMPLES' "$out"
has  'help has commands' 'COMMANDS' "$out"
has  'help documents the exit codes' 'EXIT STATUS' "$out"
has  'help links to the manual' 'https://github.com/BlueRaddish/cly' "$out"
eq   'help writes nothing to stderr' '' "$(err)"
eq   '--help is the same screen' "$out" "$(run --help)"
eq   '-h is the same screen' "$out" "$(run -h)"

long=$(printf '%s\n' "$out" | awk 'length > 95 { c++ } END { print c + 0 }')
eq   'help wraps under 95 columns' 0 "$long"

ver=$(run version)
has  'version prints a version' 'cly 3.' "$ver"
eq   '--version agrees' "$ver" "$(run --version)"
eq   '-V agrees' "$ver" "$(run -V)"

# Documented options and parsed options must be the same set — help that has
# drifted from behaviour is the bug this catches.
documented=$(printf '%s\n' "$out" \
    | awk '/^OPTIONS$/ { on = 1; next } /^[A-Z]+ ?[A-Z]*$/ { on = 0 } on' \
    | grep -o -- '--[a-z][a-z-]*' | sort -u)
parsed=$(grep -o -- '^            -[^)]*)' "$cly" | grep -o -- '--[a-z][a-z-]*' | sort -u)
eq   'documented options == parsed options' "$parsed" "$documented"

# The same for the commands: what COMMANDS lists is what may not be a profile
# name, and both come from the one list in the script.
documented_cmds=$(printf '%s\n' "$out" \
    | awk '/^COMMANDS$/ { on = 1; next } /^[A-Z]+ ?[A-Z]*$/ { on = 0 } on' \
    | grep -o '^  [a-z][a-z]*' | tr -d ' ' | sort -u)
reserved=$(grep -o "^CLY_RESERVED='[^']*'" "$cly" | sed "s/.*='//; s/'$//" \
    | tr ' ' '\n' | grep -v '^\.$' | sort -u)
eq   'documented commands == reserved names' "$reserved" "$documented_cmds"

# --- the grammar --------------------------------------------------------------

write_config 'default=one' \
    "profile.one.bin=$stub" 'profile.one.flags=--standing' "profile.one.dir=$pinned"

out=$(run .)
has  'cly . launches the default' "PWD=$pinned" "$out"
has  'cly . carries the profile flags' 'ARG=--standing' "$out"

out=$(run one)
has  'a profile name launches it' "PWD=$pinned" "$out"

out=$(run . --resume -p 'two words')
has  'agent flags pass through' 'ARG=--resume' "$out"
has  'quoted agent arguments survive' 'ARG=two words' "$out"
args=$(printf '%s\n' "$out" | grep '^ARG=' | tr '\n' ' ')
eq   'standing flags come first, in order' 'ARG=--standing ARG=--resume ARG=-p ARG=two words ' "$args"

# The whole point of the grammar: after the name, nothing is cly's.
out=$(run one --dir /nowhere)
has  'after the name --dir belongs to the agent' 'ARG=--dir' "$out"
has  'after the name --dir does not move cly' "PWD=$pinned" "$out"
out=$(run one --help)
has  'after the name --help belongs to the agent' 'ARG=--help' "$out"
out=$(run one .)
has  'after the name a dot belongs to the agent' 'ARG=.' "$out"

out=$(run --resume); rc=$?
eq   'an option before the name that cly does not know exits 2' 2 "$rc"
has  'it says whose options go where' "options come before the profile name" "$(err)"
has  'it suggests the fix' 'cly . --resume' "$(err)"

# --- options and the environment ----------------------------------------------

out=$(run --dir "$other" one)
has  '--dir wins over the profile' "PWD=$other" "$out"
out=$(run -d "$other" one)
has  '-d is the same option' "PWD=$other" "$out"
out=$(run --here one)
has  '--here launches here' "PWD=$here" "$out"
out=$(run --here --dir "$other" one)
has  '--here wins over --dir' "PWD=$here" "$out"
out=$(CLY_DIR="$other" run one)
has  'CLY_DIR wins over the profile' "PWD=$other" "$out"
out=$(CLY_DIR="$other" run --here one)
has  '--here wins over CLY_DIR' "PWD=$here" "$out"
out=$(CLY_FLAGS='--env' run one)
has  'CLY_FLAGS wins over the profile' 'ARG=--env' "$out"
hasnt 'CLY_FLAGS replaces the profile flags' 'ARG=--standing' "$out"
out=$(CLY_FLAGS='' run one)
hasnt 'an empty CLY_FLAGS means no flags at all' 'ARG=' "$out"

out=$(run --dir); rc=$?
eq   '--dir without a directory exits 2' 2 "$rc"
has  '--dir without a directory says usage' 'usage: cly' "$(err)"

# A profile with no flags of its own is given none: standing flags belong to
# the profile that asked for them, and another tool would choke on them.
write_config 'default=one' "profile.one.bin=$stub" 'profile.one.flags=--standing' \
    "profile.two.bin=$stub" 'profile.two.dir=none'
out=$(run two)
hasnt 'a profile without flags gets none' 'ARG=' "$out"
has  'a profile with dir=none launches here' "PWD=$here" "$out"
hasnt 'one profile does not borrow the flags of another' 'ARG=--standing' "$out"

# A profile with no bin of its own is named after the tool it runs.
write_config 'default=t' 'profile.t.flags=--x'
out=$( unset CLY_BIN; "$cly" config t </dev/null )
has  'a profile without bin is named after it' 'executable  t' "$out"

# --- the default profile ------------------------------------------------------

write_config "profile.only.bin=$stub" 'profile.only.dir=none'
out=$(run .)
has  'a lone profile is the default without being told' "PWD=$here" "$out"

write_config 'profile.a.bin=x' 'profile.b.bin=y'
out=$(run .); rc=$?
eq   'several profiles and no default exits 2' 2 "$rc"
has  'it says which profiles there are' 'profiles: a b' "$(err)"
has  'it says how to choose' "run 'cly init'" "$(err)"

reset_config
out=$(run .); rc=$?
eq   'no config and no terminal exits 2' 2 "$rc"
has  'no config and no terminal says why' 'no terminal to ask at' "$(err)"
eq   'no config and no terminal writes nothing' '' "$(ls "$CLY_CONFIG" 2>/dev/null)"

write_config 'default=one' "profile.one.bin=$stub" "profile.one.dir=$pinned"
out=$(run nope); rc=$?
eq   'an unconfigured name with no terminal exits 2' 2 "$rc"
has  'it names the profiles that do exist' 'profiles: one' "$(err)"
has  'it says how to make one' "run 'cly init nope'" "$(err)"

# --- init ---------------------------------------------------------------------

reset_config
out=$(ask '--search
'"$pinned"'
' init codex); rc=$?
eq   'init NAME exits 0' 0 "$rc"
has  'init NAME reports the profile' 'cly: profile codex  codex --search' "$out"
has  'init NAME reports the directory' "launches in    $pinned" "$out"
has  'init writes the executable' 'profile.codex.bin=codex' "$(config)"
has  'init writes the flags' 'profile.codex.flags=--search' "$(config)"
has  'init writes the directory' "profile.codex.dir=$pinned" "$(config)"
has  'the first profile becomes the default' 'default=codex' "$(config)"
has  'init says so' "'cly .' now launches codex" "$out"
has  'a fresh config explains itself' '# cly configuration' "$(config)"

out=$(ask 'none

' init claude)
has  'a second profile does not take the default' 'default=codex' "$(config)"
hasnt 'and does not claim to have' "now launches claude" "$out"
has  'none means no flags' 'profile.claude.flags=' "$(config)"
has  'an empty answer means launch here' 'profile.claude.dir=none' "$(config)"

out=$(run .)
has  'the default is still the first one' 'ARG=--search' "$out"

# The claude profile is offered Claude Code's flags; nothing else is.
out=$(ask '
none
' init claude)
has  'claude is offered the standing flags' '--remote-control --dangerously-skip-permissions' "$out"
out=$(ask '
none
' init codex)
hasnt 'codex is not' '--remote-control' "$out"

out=$(run init config); rc=$?
eq   'a reserved name exits 2' 2 "$rc"
has  'a reserved name says which words are taken' 'reserved: . init config help version' "$(err)"
hasnt 'a reserved name is never written as a profile' 'profile.config.' "$(config)"

out=$(run init nope); rc=$?
eq   'init with nothing to read exits 2' 2 "$rc"
has  'init with nothing to read says so' 'nothing here to read an answer from' "$(err)"

# init with no name is about the default, and changing it does not touch how
# the profile itself is set up.
write_config 'default=a' "profile.a.bin=$stub" 'profile.a.flags=--aa' 'profile.a.dir=none' \
    "profile.b.bin=$stub" 'profile.b.flags=--bb' 'profile.b.dir=none'
out=$(ask 'b
' init)
has  'init with no name sets the default' 'default=b' "$(config)"
has  'it says the profile was already there' 'which was already configured' "$out"
has  'the profile it points at is untouched' 'profile.b.flags=--bb' "$(config)"
out=$(run .)
has  'and the default now launches it' 'ARG=--bb' "$out"

# --- a profile that does not exist yet -----------------------------------------

write_config 'default=a' "profile.a.bin=$stub" 'profile.a.dir=none'
out=$(ask 'none

' codex --resume)
has  'an unconfigured name is offered for setup' 'no codex profile yet' "$out"
has  'the offer says why it is being made' 'codex is on your PATH' "$out"
has  'the profile is written' 'profile.codex.bin=codex' "$(config)"
hasnt 'and does not steal the default' 'default=codex' "$(config)"

out=$(ask '' nosuchtool); rc=$?
eq   'a name that is not a tool either exits 2' 2 "$rc"
has  'it says the profile is missing' "no profile named 'nosuchtool'" "$(err)"
has  'it says the tool is missing too' "and no 'nosuchtool' on your PATH" "$(err)"
has  'it offers the way to make one anyway' "run 'cly init nosuchtool'" "$(err)"

# --- a v2 config ---------------------------------------------------------------

# dir= and flags= at the top level are v2's whole config. They are read as the
# definition of a profile called claude, and nothing is rewritten behind anyone.
write_config "dir=$pinned"
out=$(run .)
has  'a v2 config still launches' "PWD=$pinned" "$out"
has  'a v2 config with no flags= gets the standing flags' 'ARG=--remote-control' "$out"
out=$(run claude)
has  'and answers to the name claude' "PWD=$pinned" "$out"
out=$(run config)
has  'config says it is reading a v2 file' 'reading the v2 dir=/flags= lines' "$out"
has  'the v2 file is the default' 'default:      claude' "$out"
eq   'reading a v2 config rewrites nothing' "dir=$pinned" "$(config)"

write_config "dir=$pinned" 'flags='
out=$(run .)
hasnt 'an empty v2 flags= means no flags' 'ARG=' "$out"

write_config "dir=$pinned" 'flags=--two' "profile.claude.bin=$stub" 'profile.claude.flags=--three'
out=$(run claude)
has  'a real claude profile supersedes the v2 lines' 'ARG=--three' "$out"
hasnt 'and its flags are not merged' 'ARG=--two' "$out"
out=$(run config)
has  'config says which one won' 'superseded by profile.claude' "$out"

# --- config -------------------------------------------------------------------

write_config 'default=one' "profile.one.bin=$stub" 'profile.one.flags=--standing' \
    "profile.one.dir=$pinned" "profile.two.bin=$stub" 'profile.two.dir=none'
out=$(run config); rc=$?
eq   'config exits 0' 0 "$rc"
has  'config names the file' "$CLY_CONFIG" "$out"
has  'config names the default' 'default:      one' "$out"
has  'config lists every profile' 'profile two:' "$out"
has  'config shows the flags' 'flags       --standing' "$out"
has  'config shows the directory' "launches in $pinned" "$out"
has  'config shows where nothing is pinned' 'launches in (wherever you are standing)' "$out"
hasnt 'config launches nothing' 'PWD=' "$out"

out=$(run config two)
has  'config NAME shows that one' 'profile two:' "$out"
hasnt 'config NAME shows only that one' 'profile one:' "$out"
out=$(run config .)
has  'config . shows the default' 'profile one:' "$out"

out=$(CLY_DIR="$other" run config one)
has  'config admits an override' 'from CLY_DIR, overriding the profile' "$out"

reset_config
out=$(run config)
has  'config with no config says so' 'none yet' "$out"
has  'config with no config has no profiles' '(none configured)' "$out"
eq   'config writes no config' '' "$(ls "$CLY_CONFIG" 2>/dev/null)"

# --- awkward cases ------------------------------------------------------------

write_config 'default=one' "profile.one.bin=$stub" "profile.one.dir=$work/deleted"
out=$(run .)
has  'a deleted directory warns' 'does not exist' "$(err)"
has  'a deleted directory still launches' "PWD=$here" "$out"
has  'and says how to fix it' "run 'cly init one'" "$(err)"

printf 'default=one\r\nprofile.one.bin=%s\r\nprofile.one.flags=--crlf\r\nprofile.one.dir=%s\r\n' \
    "$stub" "$pinned" > "$CLY_CONFIG"
out=$(run .)
has  'a CRLF config is read' "PWD=$pinned" "$out"
has  'a CRLF config loses the carriage return' 'ARG=--crlf' "$out"

if command -v cygpath >/dev/null 2>&1; then
    win=$(cygpath -w "$pinned")
    write_config 'default=one' "profile.one.bin=$stub" "profile.one.dir=$win"
    out=$(run .)
    has 'a Windows path in the config is understood' "PWD=$pinned" "$out"
    out=$(run --dir "$win" one)
    has 'a Windows path as an option is understood' "PWD=$pinned" "$out"
else
    note 'a Windows path in the config is understood (no cygpath)'
    note 'a Windows path as an option is understood (no cygpath)'
fi

write_config 'default=one' "profile.one.bin=$stub" 'profile.one.dir=~'
out=$(run .)
has  'a tilde in the config is expanded' "PWD=$HOME" "$out"
out=$(run --dir '~' one)
has  'a tilde in an option is expanded' "PWD=$HOME" "$out"

write_config 'default=one' "profile.one.bin=$stub" 'profile.one.dir=none' \
    '# profile.commented.bin=nope'
out=$(run config)
hasnt 'a commented profile is not a profile' 'profile commented' "$out"

# A profile whose name is also a real argument the agent takes: the name is
# claimed, the second one is not, because only the first word is ever cly's.
write_config 'default=one' "profile.one.bin=$stub" 'profile.one.dir=none' \
    "profile.two.bin=$stub" 'profile.two.dir=none'
out=$(run one two)
has  'only the first word is claimed' 'ARG=two' "$out"

# --- what the config file survives ------------------------------------------

# A lone profile is the default without a default= line. Setting up a second
# one must not quietly make `cly .` ambiguous.
write_config "profile.first.bin=$stub" 'profile.first.flags=--first' 'profile.first.dir=none'
out=$(ask 'none

' init codex)
has  'a second profile pins the first as the default' 'default=first' "$(config)"
has  'and says it did' "still launches first" "$out"
out=$(run .)
has  'so the default still launches' 'ARG=--first' "$out"

# The same when the second profile arrives through the offer, not through init.
write_config "profile.first.bin=$stub" 'profile.first.flags=--first' 'profile.first.dir=none'
out=$(ask 'none

' codex)
has  'the offer pins it too' 'default=first' "$(config)"

# A config that cannot be read must never be written over: cly would be
# destroying settings it never saw.
write_config 'default=one' "profile.one.bin=$stub" 'profile.one.dir=none'
chmod 000 "$CLY_CONFIG" 2>/dev/null
if [ -r "$CLY_CONFIG" ]; then
    chmod 644 "$CLY_CONFIG"
    note 'an unreadable config is not overwritten (chmod has no effect here)'
    note 'an unreadable config says why (chmod has no effect here)'
else
    out=$(ask 'none

' init two); rc=$?
    eq   'an unreadable config is not overwritten' 2 "$rc"
    has  'an unreadable config says why' 'cannot be read' "$(err)"
    chmod 644 "$CLY_CONFIG"
fi

# A tool that is not on PATH is asked about, rather than assumed to exist.
reset_config
out=$(ask 'my-agent --flag
--x

' init notonpath)
has  'an unknown tool is asked for an executable' 'Which executable' "$out"
has  'and the answer is what gets written' 'profile.notonpath.bin=my-agent --flag' "$(config)"
has  'and the questions do not shift' 'profile.notonpath.flags=--x' "$(config)"

# -- is not part of the grammar: a profile name cannot begin with a dash, so
# there is nothing for it to protect.
write_config 'default=one' "profile.one.bin=$stub" 'profile.one.dir=none'
out=$(run -- one); rc=$?
eq   '-- is not an option cly knows' 2 "$rc"
hasnt '-- launches nothing' 'PWD=' "$out"

# --- shell hygiene ------------------------------------------------------------

if command -v shellcheck >/dev/null 2>&1; then
    if shellcheck -s bash "$cly" "$self_dir/install.sh" >"$work/sc" 2>&1; then ok
    else bad 'shellcheck is clean' "$(head -20 "$work/sc")"; fi
else
    note 'shellcheck is clean (shellcheck not installed)'
fi

if bash -n "$cly" 2>"$work/syn"; then ok; else bad 'bin/cly parses' "$(cat "$work/syn")"; fi
if bash -n "$self_dir/install.sh" 2>"$work/syn"; then ok; else bad 'install.sh parses' "$(cat "$work/syn")"; fi

# The script may use shell builtins and mkdir and nothing else: the .cmd door
# can hand it a bash whose PATH carries none of the usual tools.
# cygpath is not in this list on purpose: it is reached through command -v and
# falls back to pure parameter expansion when it is missing.
for tool in cat sed awk grep tr cut basename dirname; do
    if grep -vE '^[[:space:]]*#' "$cly"         | grep -qE "(^|[^A-Za-z0-9_-])$tool([^A-Za-z0-9_-]|$)"; then
        bad "bin/cly does not depend on $tool" "found $tool outside a comment"
    else
        ok
    fi
done

# --- report -------------------------------------------------------------------

echo
printf '%s passed, %s failed, %s skipped\n' "$pass" "$fail" "$skip"
[ "$fail" = 0 ] || exit 1
