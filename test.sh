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
for v in "${!CLY_T_@}"; do printf 'ENV %s=%s' "$v" "${!v}"; echo; done
EOF
chmod +x "$stub"
export CLY_BIN="$stub"

# The agents' session stores, faked under the scratch directory: the real
# ~/.claude, ~/.codex, ~/.gemini and ~/.kimi-code are unreachable from here.
stores="$work/stores"
export CLAUDE_CONFIG_DIR="$stores/claude" CODEX_HOME="$stores/codex"
export GEMINI_CLI_HOME="$stores/gemini" KIMI_CODE_HOME="$stores/kimi"

# cly asks one more question when the tool being set up is not on PATH, so a
# suite that reads PATH is a suite whose piped answers land in different
# questions on different machines. Give it a PATH it owns.
mkdir -p "$work/bin"
for tool in codex claude; do
    {
        echo '#!/usr/bin/env bash'
        echo 'printf "STUB=%s\\n" "$0"'
    } > "$work/bin/$tool"
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
has  'bare cly names the tool' 'cly — one command in front of every coding agent' "$out"
has  'bare cly shows the usage line' 'usage: cly [OPTION...] [PROFILE|.]' "$out"
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
has  'version prints a version' 'cly 4.' "$ver"
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

out=$(run --frobnicate); rc=$?
eq   'an option before the name that cly does not know exits 2' 2 "$rc"
has  'it says whose options go where' "options come before the profile name" "$(err)"
has  'it suggests the fix' 'cly . --frobnicate' "$(err)"

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

# A v2 config's implicit default is pinned in the file when a second profile
# arrives, as a lone v3 profile's is.
write_config 'dir=none' 'flags=--v2'
out=$(ask '
none

' init codex)
has  'a second profile beside v2 lines pins the v2 default' 'default=claude' "$(config)"

# The claude profile is offered Claude Code's flags; nothing else is.
reset_config
out=$(ask '
none
' init claude)
has  'claude is offered the standing flags' '[--remote-control] >' "$out"
hasnt 'but not the bypass, which is -x now' 'dangerously' "$out"
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
    out=$(ask 'agent
none

' init two); rc=$?
    eq   'an unreadable config is not overwritten' 1 "$rc"
    has  'an unreadable config says why' 'refusing to overwrite it' "$(err)"
    chmod 644 "$CLY_CONFIG"
fi

# A tool that is not on PATH is asked about, rather than assumed to exist.
reset_config
out=$(ask 'my-agent
--x

' init notonpath)
has  'an unknown tool is asked for an executable' 'Which executable' "$out"
has  'and the answer is what gets written' 'profile.notonpath.bin=my-agent' "$(config)"
has  'and the questions do not shift' 'profile.notonpath.flags=--x' "$(config)"
hasnt 'the two questions do not run onto one line' '>   Which flags' "$out"

# A command with arguments would be accepted here and then fail at every
# launch, because exec takes a program.
reset_config
out=$(ask '/usr/bin/env FOO=1

' init notonpath); rc=$?
eq   'a command with arguments is refused' 2 "$rc"
has  'and says why' 'not a program' "$(err)"
eq   'and writes nothing' '' "$(ls "$CLY_CONFIG" 2>/dev/null)"

# A path with a space in it is not the same thing: it resolves, so it stands.
spaced="$work/a dir"; mkdir -p "$spaced"; cp "$stub" "$spaced/agent"
reset_config
out=$(ask "$spaced/agent
none

" init spacey)
has  'a path with a space is accepted' "profile.spacey.bin=$spaced/agent" "$(config)"

# -- is not part of the grammar: a profile name cannot begin with a dash, so
# there is nothing for it to protect.
write_config 'default=one' "profile.one.bin=$stub" 'profile.one.dir=none'
out=$(run -- one); rc=$?
eq   '-- is not an option cly knows' 2 "$rc"
hasnt '-- launches nothing' 'PWD=' "$out"

# --- changing a profile that already exists ----------------------------------

# Finding 1: `cly init NAME` offers what is configured now, so Enter keeps it.
# Losing this emptied the profile the command was aimed at.
write_config 'default=codex' "profile.codex.bin=$stub"     'profile.codex.flags=--search --model o3' "profile.codex.dir=$pinned"
# Three questions here, not two: this profile's executable is not its name,
# so the bin question is asked as well, and each one offers what is set now.
out=$(ask '


' init codex); rc=$?
eq   'init NAME exits 0 when every answer is kept' 0 "$rc"
has  'init reports that it wrote the profile' 'cly: profile codex' "$out"
has  'init offers the configured executable' "[$stub]" "$out"
has  'init offers the configured flags' '[--search --model o3]' "$out"
has  'init offers the configured directory' "[$pinned]" "$out"
has  'Enter keeps the flags' 'profile.codex.flags=--search --model o3' "$(config)"
has  'Enter keeps the directory' "profile.codex.dir=$pinned" "$(config)"
has  'and the executable survives' "profile.codex.bin=$stub" "$(config)"

out=$(ask '

here
' init codex)
has  'here unpins a configured directory' 'profile.codex.dir=none' "$(config)"

# The same on the path the README tells a v2 user to take.
write_config "dir=$pinned" 'flags=--two'
out=$(ask '

' init claude)
has  'converting a v2 config keeps its directory' "profile.claude.dir=$pinned" "$(config)"
has  'converting a v2 config keeps its flags' 'profile.claude.flags=--two' "$(config)"

# Finding 2: a name with a dot could be written and never read back, and the
# default= line pointing at it took the whole config down with it.
reset_config
out=$(ask 'none

' init 'gpt-4.1'); rc=$?
eq   'a dotted name is refused' 2 "$rc"
has  'and says why' 'cannot be a profile name' "$(err)"
eq   'and writes nothing' '' "$(ls "$CLY_CONFIG" 2>/dev/null)"
out=$(ask 'none

' init 'a=b'); rc=$?
eq   'an = in a name is refused too' 2 "$rc"

# Finding 6: a directory typed just now is a typo, not a stale config.
write_config 'default=one' "profile.one.bin=$stub" "profile.one.dir=$pinned"
out=$(run --dir "$work/nope" one); rc=$?
eq   'a --dir that does not exist exits 2' 2 "$rc"
hasnt 'and launches nothing' 'PWD=' "$out"
has  'and says which directory' "$work/nope does not exist" "$(err)"
out=$(CLY_DIR="$work/nope" run one); rc=$?
eq   'the same for CLY_DIR' 2 "$rc"
write_config 'default=one' "profile.one.bin=$stub" "profile.one.dir=$work/gone"
out=$(run one)
has  'but a configured directory that vanished still launches here' "PWD=$here" "$out"
has  'and warns' 'does not exist' "$(err)"

# --- kinds, -x and env= ---------------------------------------------------------

# The stub stands in for every agent, so the kind comes from the config.
write_config 'default=one' "profile.one.bin=$stub" 'profile.one.flags=--standing' 'profile.one.kind=claude'
out=$(run -x .)
has  "-x adds the kind's flag" 'ARG=--dangerously-skip-permissions' "$out"
args=$(printf '%s\n' "$out" | grep '^ARG=' | tr '\n' ' ')
eq   'after the standing flags' 'ARG=--standing ARG=--dangerously-skip-permissions ' "$args"
out=$(run -x . --model x)
args=$(printf '%s\n' "$out" | grep '^ARG=' | tr '\n' ' ')
eq   "and before the agent's" 'ARG=--standing ARG=--dangerously-skip-permissions ARG=--model ARG=x ' "$args"
out=$(run --bypass .)
has  '--bypass is -x' 'ARG=--dangerously-skip-permissions' "$out"
out=$(run .)
hasnt 'without -x the flag is not there' 'dangerously' "$out"

for k in claude:--dangerously-skip-permissions codex:--dangerously-bypass-approvals-and-sandbox \
         gemini:--yolo kimi:--yolo qwen:--yolo opencode:--auto; do
    write_config 'default=k' "profile.k.bin=$stub" "profile.k.kind=${k%%:*}"
    out=$(run -x .)
    has  "-x on kind ${k%%:*} adds ${k#*:}" "ARG=${k#*:}" "$out"
done

# The kind defaults to the executable's name, so a profile that names codex
# needs no kind= line.
write_config 'default=c' 'profile.c.bin=codex'
out=$(run -x .)
has  'the kind follows the executable' 'ARG=--dangerously-bypass-approvals-and-sandbox' "$out"
write_config 'default=c' 'profile.c.bin=C:\tools\claude.exe'
out=$(run -x .)
has  'even through a Windows path' 'ARG=--dangerously-skip-permissions' "$out"

write_config 'default=z' "profile.z.bin=$stub"
out=$(run -x .); rc=$?
eq   'a kind cly does not know refuses -x' 2 "$rc"
hasnt 'and launches nothing' 'PWD=' "$out"
has  'and names the config key' 'profile.z.kind=' "$(err)"

write_config 'default=one' "profile.one.bin=$stub" 'profile.one.flags=--dangerously-skip-permissions' 'profile.one.kind=claude'
out=$(run -x .)
eq   'a flag already in flags= is not added twice' 1 "$(printf '%s\n' "$out" | grep -c dangerously)"

# env= is exported before the launch; $NAME is read from the caller's environment.
write_config 'default=one' "profile.one.bin=$stub" 'profile.one.env=CLY_T_A=1 CLY_T_B=$CLY_T_SRC'
out=$(CLY_T_SRC=secret run .)
has  'env= sets a variable' 'ENV CLY_T_A=1' "$out"
has  'and reads $NAME from the environment' 'ENV CLY_T_B=secret' "$out"
out=$(run .)
has  'an unset $NAME is empty' 'ENV CLY_T_B=' "$out"

# kind= and env= survive the setup questions, which never ask about them.
write_config 'default=one' "profile.one.bin=$stub" 'profile.one.kind=claude' 'profile.one.env=CLY_T_A=1' '# a note'
out=$(ask '
none

' init one)
has  'cly init keeps kind=' 'profile.one.kind=claude' "$(config)"
has  'cly init keeps env=' 'profile.one.env=CLY_T_A=1' "$(config)"
has  'and the comment after them' '# a note' "$(config)"
eq   'and writes the kind once' 1 "$(config | grep -c 'profile.one.kind=')"

write_config 'default=one' "profile.one.bin=$stub" 'profile.one.kind=claude'
out=$(ask "$work/bin/codex
none

" init one)
hasnt 'a changed executable takes the old kind with it' 'profile.one.kind=' "$(config)"
write_config 'default=one' "profile.one.bin=$stub"
out=$(run init 'bad.name'); rc=$?
eq   'an invalid name at init is refused' 2 "$rc"
out=$(run init -x); rc=$?
eq   'so is one that starts with a dash: it would be one of the options' 2 "$rc"
has  'and the error says so' 'a leading' "$(err)"
eq   'before anything is written' "$(printf '%s\n' 'default=one' "profile.one.bin=$stub")" "$(config)"
write_config 'default=one' "profile.one.bin=$stub" 'profile.one.kind=claude' 'profile.one.env=CLY_T_A=1'
out=$(run config)
has  'config shows the kind' 'kind        claude — -x adds --dangerously-skip-permissions' "$out"
has  'config shows the environment' 'environment CLY_T_A=1' "$out"
write_config 'default=z' "profile.z.bin=$stub"
out=$(run config)
has  'config says when -x cannot serve a kind' 'not one cly knows' "$out"

# --- the menu ---------------------------------------------------------------------

write_config 'default=a' "profile.a.bin=$stub" 'profile.a.flags=--aa' 'profile.a.kind=claude' \
             "profile.b.bin=$stub" 'profile.b.flags=--bb' 'profile.b.kind=codex'
out=$(run)
has  'without a terminal a bare cly is still the brief' "Run 'cly help' for more" "$out"
hasnt 'and launches nothing' 'PWD=' "$out"

out=$(ask '
')
has  'with one, it is the menu' 'which agent?' "$out"
has  'the profiles come first' '1  a         Claude Code' "$out"
has  'the default is marked' '(default)' "$out"
has  'the catalog follows' 'gemini    Gemini CLI   not installed: npm install -g @google/gemini-cli' "$out"
has  'installed tools without a profile say so' 'claude    Claude Code  installed, no profile yet' "$out"
has  'Enter launches the default' 'ARG=--aa' "$out"
out=$(ask '2
')
has  'a number launches that row' 'ARG=--bb' "$out"
out=$(ask 'b
')
has  'a name launches that profile' 'ARG=--bb' "$out"
out=$(ask $'\e'); rc=$?
eq   'Esc picks nothing' 2 "$rc"
hasnt 'and launches nothing' 'PWD=' "$out"
out=$(ask '99
'); rc=$?
eq   'a number past the end lands on the last row, meta, which needs ollama' 2 "$rc"
has  'and says so' 'ollama' "$(err)"
out=$(ask ''); rc=$?
eq   'no answer at all exits 2' 2 "$rc"

# Picking an installed tool that has no profile sets it up on the spot.
out=$(ask 'claude
none

')
has  'picking an unconfigured tool asks the setup questions' 'Which flags should claude' "$out"
has  'then launches it' 'PWD=' "$out"
has  'and the profile is now there' 'profile.claude.bin=claude' "$(config)"
has  'the default did not move' 'default=a' "$(config)"

# Picking one that is not installed prints how to get it. qwen, gemini and
# kimi start with letters a picker might have kept for itself; none is.
out=$(ask 'qwen
'); rc=$?
eq   'a name starting with q can be typed' 2 "$rc"
has  'and is the one picked' 'qwen-code' "$(err)"
out=$(ask 'kimi
'); rc=$?
has  'so can one starting with k' 'kimi-code' "$(err)"
out=$(ask 'gemini
'); rc=$?
eq   'a tool that is not installed exits 2' 2 "$rc"
has  'and says what to install' 'npm install -g @google/gemini-cli' "$(err)"
has  'and how to sign in' 'Login with Google' "$(err)"
out=$(ask 'deepseek
'); rc=$?
eq   'a route whose host is missing exits 2' 2 "$rc"
has  'and names the host' 'ollama' "$(err)"

# With ollama on the PATH, the DeepSeek route sets itself up with Claude Code's
# kind, so -x and -r treat it as Claude Code.
{ echo '#!/usr/bin/env bash'; echo 'true'; } > "$work/bin/ollama"
chmod +x "$work/bin/ollama"
out=$(ask 'deepseek



')
has  'the route offers ollama' '[ollama] >' "$out"
has  'and its launch words' '[launch claude --model deepseek-v4-pro --] >' "$out"
has  'and launches through them' 'ARG=launch' "$out"
has  'and records the kind' 'profile.deepseek.kind=claude' "$(config)"
out=$(run -x deepseek)
args=$(printf '%s\n' "$out" | grep '^ARG=' | tr '\n' ' ')
eq   '-x lands after the --, where Claude Code reads it' 'ARG=launch ARG=claude ARG=--model ARG=deepseek-v4-pro ARG=-- ARG=--dangerously-skip-permissions ' "$args"
rm -f "$work/bin/ollama"

# --- sessions -----------------------------------------------------------------

# Four fake stores, one per kind, shaped as the agents write them. Timestamps
# are relative to now so the age column can be checked.
now=$(date +%s)
iso() { date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -r "$1" +%Y-%m-%dT%H:%M:%SZ; }
proja="$work/proj-a"; projb="$work/proj-b"
mkdir -p "$proja" "$projb"

c1=c1c1c1c1-0000-0000-0000-000000000001
c2=c2c2c2c2-0000-0000-0000-000000000002
c3=c3c3c3c3-0000-0000-0000-000000000003
mkdir -p "$stores/claude/projects/${proja//[^A-Za-z0-9]/-}" "$stores/claude/projects/C--Users-me-proj"
printf '%s\n' \
  '{"display":"/effort","pastedContents":{},"timestamp":'$(( (now - 3600) * 1000 ))',"project":"'"$proja"'","sessionId":"'$c1'"}' \
  '{"display":"Claude first \"real\" prompt\nline two","pastedContents":{},"timestamp":'$(( (now - 120) * 1000 ))',"project":"'"$proja"'","sessionId":"'$c1'"}' \
  '{"display":"purged","pastedContents":{},"timestamp":'$(( (now - 60) * 1000 ))',"project":"'"$proja"'","sessionId":"'$c2'"}' \
  '{"display":"On Windows","pastedContents":{},"timestamp":'$(( (now - 5 * 86400) * 1000 ))',"project":"C:\\Users\\me\\proj","sessionId":"'$c3'"}' \
  > "$stores/claude/history.jsonl"
echo '{}' > "$stores/claude/projects/${proja//[^A-Za-z0-9]/-}/$c1.jsonl"
echo '{}' > "$stores/claude/projects/C--Users-me-proj/$c3.jsonl"

x1=01a0aaaa-0000-7000-8000-000000000001
x2=01a0bbbb-0000-7000-8000-000000000002
mkdir -p "$stores/codex/sessions/2026/09/01"
printf '%s\n' \
  '{"session_id":"'$x1'","ts":'$(( now - 86400 ))',"text":"codex first prompt"}' \
  '{"session_id":"'$x1'","ts":'$(( now - 80000 ))',"text":"codex later prompt"}' \
  '{"session_id":"'$x2'","ts":'$(( now - 10 ))',"text":"no rollout any more"}' \
  > "$stores/codex/history.jsonl"
printf '%s\n' \
  '{"id":"'$x1'","thread_name":"first name","updated_at":"x"}' \
  '{"id":"'$x1'","thread_name":"named thread","updated_at":"x"}' \
  > "$stores/codex/session_index.jsonl"
printf '%s\n' '{"timestamp":"2026-09-01T00:00:00.000Z","type":"session_meta","payload":{"id":"'$x1'","timestamp":"2026-09-01T00:00:00.000Z","cwd":"'"$projb"'"}}' \
  > "$stores/codex/sessions/2026/09/01/rollout-2026-09-01T00-00-00-$x1.jsonl"

g1=g1g1g1g1-1111-2222-3333-444444444444
g2=g2g2g2g2-1111-2222-3333-444444444444
mkdir -p "$stores/gemini/tmp/proj-a/chats" "$stores/gemini/tmp/other/chats"
printf '%s\n' \
  '{"sessionId":"'$g1'","projectHash":"abc","startTime":"'$(iso $((now - 7200)))'","lastUpdated":"'$(iso $((now - 7000)))'","kind":"main"}' \
  '{"id":"m1","timestamp":"x","type":"user","content":[{"text":"Gemini asks a \"quoted\" question"}]}' \
  > "$stores/gemini/tmp/proj-a/chats/session-2026-09-01T10-00-${g1:0:8}.jsonl"
printf '%s\n' "$proja" > "$stores/gemini/tmp/proj-a/.project_root"
printf '%s\n' '{"sessionId":"sub","kind":"subagent","lastUpdated":"'$(iso "$now")'"}' \
  > "$stores/gemini/tmp/proj-a/chats/session-2026-09-01T11-00-subagent.jsonl"
printf '%s\n' '{' '  "sessionId": "'$g2'",' '  "startTime": "2026-08-20T09:00:00.000Z",' \
  '  "lastUpdated": "2026-08-20T09:45:00.000Z",' '  "messages": [' '    {' '      "type": "user",' \
  '      "content": "Legacy gemini session"' '    }' '  ]' '}' \
  > "$stores/gemini/tmp/other/chats/session-2026-08-20T09-00-${g2:0:8}.json"
printf '%s\n' '{' '  "projects": {' '    "'"$projb"'": "other"' '  }' '}' > "$stores/gemini/projects.json"

k1=11111111-aaaa-bbbb-cccc-000000000001
k2=22222222-aaaa-bbbb-cccc-000000000002
k3=33333333-aaaa-bbbb-cccc-000000000003
for k in $k1 $k2 $k3; do mkdir -p "$stores/kimi/sessions/wd_proj_abc/$k"; done
printf '%s\n' \
  '{"sessionId":"'$k1'","sessionDir":"'"$stores/kimi/sessions/wd_proj_abc/$k1"'","workDir":"x"}' \
  '{"sessionId":"'$k2'","sessionDir":"'"$stores/kimi/sessions/wd_proj_abc/$k2"'","workDir":"x"}' \
  '{"sessionId":"'$k3'","sessionDir":"'"$stores/kimi/sessions/wd_proj_abc/$k3"'","workDir":"x"}' \
  '{"sessionId":"'$k3'","deleted":true}' \
  > "$stores/kimi/session_index.jsonl"
printf '%s\n' '{' '  "title": "Kimi fixes the build",' '  "lastPrompt": "run the tests again",' \
  '  "updatedAt": "'$(iso $((now - 3 * 86400)))'",' '  "archived": false,' '  "custom": {' \
  '    "cwd": "'"$proja"'"' '  }' '}' > "$stores/kimi/sessions/wd_proj_abc/$k1/state.json"
printf '%s\n' '{"lastPrompt":"archived","updatedAt":'$(( now * 1000 ))',"archived":true,"cwd":"'"$proja"'"}' \
  > "$stores/kimi/sessions/wd_proj_abc/$k2/state.json"
printf '%s\n' '{"lastPrompt":"deleted","updatedAt":'$(( now * 1000 ))',"archived":false,"cwd":"'"$proja"'"}' \
  > "$stores/kimi/sessions/wd_proj_abc/$k3/state.json"

write_config 'default=one' "profile.one.bin=$stub" 'profile.one.flags=--standing' 'profile.one.kind=claude' \
             "profile.two.bin=$stub" 'profile.two.flags=--codexy' 'profile.two.kind=codex'
out=$(COLUMNS=120 run -r); rc=$?
eq   'without a terminal -r lists and exits 2' 2 "$rc"
has  'and says so' 'no terminal to pick at' "$(err)"
has  'the table has a header' '#  agent     last      where' "$out"
rows=$(printf '%s\n' "$out" | grep -E '^ +[0-9]+  ')
eq   'six sessions are listed' 6 "$(printf '%s\n' "$rows" | grep -c .)"
has  'the newest is first' '1  claude    2m ago' "$out"
has  'then the gemini session' '2  gemini    1h ago' "$out"
has  'then codex' '3  codex     22h ago' "$out"
has  'then kimi' '4  kimi      3d ago' "$out"
has  'a title is the first prompt that was not a slash command' 'Claude first "real" prompt line two' "$out"
hasnt 'a slash command is not a title' '/effort' "$out"
hasnt 'a session whose transcript is gone is not offered' 'purged' "$out"
hasnt 'a codex session without its rollout is not offered' 'no rollout' "$out"
has  'a codex thread is shown by its latest name' 'named thread' "$out"
hasnt 'not an older one' 'first name' "$out"
has  'gemini reads the first user message, escaped quotes and all' 'Gemini asks a "quoted" question' "$out"
has  'and the legacy one-object file' 'Legacy gemini session' "$out"
hasnt 'a subagent transcript is not a session' 'subagent' "$out"
has  'kimi shows the title' 'Kimi fixes the build' "$out"
hasnt 'an archived kimi session is not offered' 'archived' "$out"
hasnt 'nor a deleted one' 'deleted' "$out"
has  'a Windows launch directory reads as a posix one' '/c/Users/me/proj' "$out"
has  'a session older than a week shows its date' 'Aug 20' "$out"

out=$(run -r two)
eq   '-r NAME narrows to that kind' 1 "$(printf '%s\n' "$out" | grep -c 'named thread')"
hasnt 'and shows nothing else' 'claude' "$(printf '%s\n' "$out" | grep -E '^ +[0-9]+  ')"
out=$(run -r codex)
has  'a bare kind narrows too' 'named thread' "$out"
out=$(run -r nosuch); rc=$?
eq   '-r with an unknown name exits 2' 2 "$rc"
has  'and says so' "no profile named 'nosuch'" "$(err)"
write_config 'default=oc' "profile.oc.bin=$stub" 'profile.oc.kind=opencode'
out=$(run -r oc); rc=$?
eq   '-r on a kind whose sessions cly cannot read exits 2' 2 "$rc"
has  'and says which kinds it can' 'claude codex gemini kimi' "$(err)"
out=$(CLY_ROWS=abc run -r); rc=$?
eq   'a CLY_ROWS that is not a number is ignored' 2 "$rc"
has  'and the list is whole' 'Kimi fixes the build' "$out"
out=$(CLY_ROWS=2 run -r)
has  'CLY_ROWS caps the list' '2 of ' "$out"
hasnt 'at that many rows' '   3  ' "$out"

write_config 'default=one' "profile.one.bin=$stub" 'profile.one.flags=--standing' 'profile.one.kind=claude' \
             "profile.two.bin=$stub" 'profile.two.flags=--codexy' 'profile.two.kind=codex'
out=$(ask '
' -r)
has  'Enter resumes the newest' "ARG=$c1" "$out"
has  'in its own directory' "PWD=$proja" "$out"
args=$(printf '%s\n' "$out" | grep '^ARG=' | tr '\n' ' ')
eq   'with the standing flags, then the resume words' "ARG=--standing ARG=--resume ARG=$c1 " "$args"
has  'and says what it is doing' "resuming claude session ${c1:0:8} in $proja" "$(err)"
out=$(ask '3
' -r)
has  'a number resumes that row' "ARG=$x1" "$out"
out=$(ask 'kimi3
' -r)
has  'a number typed after letters starts over from the full list' "ARG=$x1" "$out"
has  'by the profile of its kind' 'ARG=--codexy' "$out"
has  'with its own resume words' 'ARG=resume' "$out"
has  'in the directory its rollout names' "PWD=$projb" "$out"
out=$(ask '2
' -r)
args=$(printf '%s\n' "$out" | grep '^ARG=' | tr '\n' ' ')
eq   'a kind with no profile resumes by the bare agent, no standing flags' "ARG=--resume ARG=$g1 " "$args"
out=$(CLY_BIN='' ask '2
' -r); rc=$?
eq   'unless the agent is not on the PATH' 2 "$rc"
has  'which it says' 'no gemini on your PATH' "$(err)"
out=$(ask '4
' -r)
has  'kimi resumes with --session' 'ARG=--session' "$out"
has  'in its working directory' "PWD=$proja" "$out"
out=$(ask '5
' -r)
has  'a session whose directory is gone resumes here' "PWD=$here" "$out"
has  'and warns' 'is gone' "$(err)"
out=$(ask '6
' -r)
has  'the legacy gemini session finds its directory in projects.json' "PWD=$projb" "$out"
out=$(ask '9
' -r)
has  'a number past the end lands on the last row' "ARG=$g2" "$out"
out=$(ask $'\e' -r); rc=$?
eq   'Esc resumes nothing' 2 "$rc"
hasnt 'and launches nothing' 'PWD=' "$out"

out=$(run -c)
has  '-c resumes the newest without asking' "ARG=$c1" "$out"
hasnt 'and shows no table' 'which session' "$out"
write_config 'default=one' "profile.one.bin=$stub" 'profile.one.kind=claude' \
             'profile.codex.bin=ollama' 'profile.codex.kind=claude' 'profile.codex.env=CLY_T_A=leak' "profile.codex.dir=$projb"
out=$(ask '3
' -r)
has  'the bare agent resumes a kind no profile has' 'ARG=resume' "$out"
hasnt 'without the env of a profile that merely shares its name' 'ENV CLY_T_A=leak' "$out"
has  'and in the session'"'"'s own directory' "PWD=$projb" "$out"
write_config 'default=one' "profile.one.bin=$stub" 'profile.one.flags=--standing' 'profile.one.kind=claude' \
             "profile.two.bin=$stub" 'profile.two.flags=--codexy' 'profile.two.kind=codex'

out=$(run -x -c)
args=$(printf '%s\n' "$out" | grep '^ARG=' | tr '\n' ' ')
eq   '-x goes between the standing flags and the resume words' "ARG=--standing ARG=--dangerously-skip-permissions ARG=--resume ARG=$c1 " "$args"
out=$(run -x -c two)
args=$(printf '%s\n' "$out" | grep '^ARG=' | tr '\n' ' ')
eq   'for codex too' "ARG=--codexy ARG=--dangerously-bypass-approvals-and-sandbox ARG=resume ARG=$x1 " "$args"
out=$(run -c . --model x)
args=$(printf '%s\n' "$out" | grep '^ARG=' | tr '\n' ' ')
eq   'agent arguments follow the id' "ARG=--standing ARG=--resume ARG=$c1 ARG=--model ARG=x " "$args"
out=$(run --here -c)
has  '--here resumes where you stand' "PWD=$here" "$out"
out=$(run -d "$projb" -c)
has  '-d resumes there' "PWD=$projb" "$out"
out=$(run --continue)
has  '--continue is -c' "ARG=$c1" "$out"
rm -rf "$stores"
out=$(run -c); rc=$?
eq   'no sessions at all exits 2' 2 "$rc"
has  'and says so' 'no sessions found' "$(err)"

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
