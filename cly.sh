# cly — launch Claude Code from one fixed directory, whatever directory you are
# standing in.
#
# Claude Code keys its memory store off the working directory it was launched
# from: ~/.claude/projects/<working-dir-with-separators-mangled>/memory/. Keep
# your memories in one place and launching from anywhere else silently loads
# none of them — no error, they are just not there. cly pins the launch
# directory so that cannot happen by accident.
#
# Install:  . /path/to/cly.sh   in your ~/.bashrc  (or run install.sh)
#
# The launch directory is asked for once, on first use, and remembered in
# ~/.config/cly/config. `cly --cly-help` lists the flags that change it.
#
# Configure by exporting any of these before the call:
#   CLY_BIN     the claude executable    (default: claude, found on PATH)
#   CLY_FLAGS   flags passed every time  (default: --remote-control
#               --dangerously-skip-permissions; set to "" for none)
#   CLY_DIR     launch directory, overriding the config file for this shell
#   CLY_CONFIG  where the config lives   (default: ~/.config/cly/config)
#
# A function rather than an alias because an alias cannot change directory. The
# launch runs in a subshell, so your own shell is still where you left it.

_cly_config_path() { printf '%s' "${CLY_CONFIG:-$HOME/.config/cly/config}"; }

# The config file is shared with the PowerShell version, which naturally writes
# Windows paths — so accept one wherever a path is read. cygpath is the right
# tool when it exists; the fallback covers a plain Linux/macOS bash, where a
# drive-letter path is not going to work anyway but should at least not become
# a silently wrong relative path.
_cly_to_posix() {
    case $1 in
        [A-Za-z]:[/\\]*)
            if command -v cygpath >/dev/null 2>&1; then
                cygpath -u "$1"
            else
                local drive rest
                drive=$(printf '%s' "${1%%:*}" | tr 'A-Z' 'a-z')
                rest=$(printf '%s' "${1#*:}" | tr '\\' '/')
                printf '/%s%s' "$drive" "$rest"
            fi ;;
        *) printf '%s' "$1" ;;
    esac
}

# Prints the configured directory, or nothing when there is no config yet. The
# literal `none` is a real answer meaning "do not pin anything" — that is how
# declining at the prompt is remembered, so you are only ever asked once.
_cly_config_read() {
    local f
    f=$(_cly_config_path)
    [ -r "$f" ] || return 1
    sed -n 's/^dir=//p' "$f" | tail -n 1
}

_cly_config_write() {
    local f dir
    f=$(_cly_config_path)
    dir=$1
    mkdir -p "$(dirname "$f")" || return 1
    {
        printf '# cly configuration\n'
        printf '# Rewritten by `cly --cly-init`; safe to edit by hand.\n'
        printf '# dir=none means launch wherever you happen to be.\n'
        printf 'dir=%s\n' "$dir"
    } > "$f"
}

_cly_help() {
    cat <<'EOF'
cly — launch Claude Code from one fixed directory.

usage: cly [CLY-FLAGS] [CLAUDE ARGS ...]

Anything not listed below is passed straight through to Claude Code, so
`cly --resume`, `cly -p "..."` and the rest work as they always did.

  --cly-init [DIR]   set the launch directory and remember it. With no DIR you
                     are prompted. Creates the directory if it does not exist.
  --cly-dir DIR      launch from DIR just this once, ignoring the config
  --cly-no-dir       launch from the current directory just this once
  --cly-config       show the config file, what it says, and what would happen
  --cly-help         this help

The directory is asked for once, on first use, and stored in
~/.config/cly/config. Answer `none` there or at the prompt to turn pinning off
without being asked again. Re-run --cly-init whenever you want to change it.
EOF
}

# Whether there is a human on the other end to answer a prompt. A function of
# its own so it can be stubbed when testing the prompt without a pty.
_cly_stdin_is_tty() { [ -t 0 ]; }

# Resolve and remember a launch directory. $1 is a directory, or empty to ask.
_cly_init() {
    local dir=$1 default reply
    default="$HOME/claude"

    if [ -z "$dir" ]; then
        if ! _cly_stdin_is_tty; then
            echo "cly: --cly-init needs a directory when stdin is not a terminal" >&2
            return 1
        fi
        echo "cly: which directory should Claude Code launch from?"
        echo "     It keeps a separate memory store per launch directory, so"
        echo "     pinning one means the same memories load every time."
        echo "     Enter a path, 'none' to launch wherever you are, or press"
        echo "     Enter for the default."
        printf '     [%s] > ' "$default"
        IFS= read -r reply || return 1
        dir=${reply:-$default}
    fi

    if [ "$dir" = none ]; then
        _cly_config_write none || return 1
        echo "cly: pinning turned off — cly will launch wherever you are."
        return 0
    fi

    # ~ only expands when the shell parses it, not when it arrives in a
    # variable, so a typed "~/claude" would otherwise become a literal
    # directory named "~".
    case $dir in "~") dir=$HOME ;; "~/"*) dir=$HOME/${dir#"~/"} ;; esac

    if [ ! -d "$dir" ]; then
        if mkdir -p "$dir" 2>/dev/null; then
            echo "cly: created $dir"
        else
            echo "cly: cannot create $dir" >&2
            return 1
        fi
    fi

    # Store it absolute: a relative path would mean something different from
    # every directory you later call cly in.
    dir=$(cd "$dir" && pwd) || return 1
    _cly_config_write "$dir" || return 1
    echo "cly: launch directory set to $dir"
    echo "cly: stored in $(_cly_config_path)"
}

cly() {
    local bin flags dir="" init_dir="" want_init=0 want_config=0 want_help=0
    local no_dir=0 rest_is_passthru=0 configured
    local -a passthru=()

    while [ $# -gt 0 ]; do
        if [ "$rest_is_passthru" = 1 ]; then passthru+=("$1"); shift; continue; fi
        case $1 in
            --) rest_is_passthru=1; passthru+=("$1"); shift ;;
            --cly-init)
                want_init=1; shift
                # An optional argument: take the next word only if it is not
                # itself a flag, so `--cly-init` alone still prompts.
                case ${1:-} in ''|-*) ;; *) init_dir=$1; shift ;; esac ;;
            --cly-dir)    dir=${2:?cly: --cly-dir needs a directory}; shift 2 ;;
            --cly-no-dir) no_dir=1; shift ;;
            --cly-config) want_config=1; shift ;;
            --cly-help)   want_help=1; shift ;;
            *) passthru+=("$1"); shift ;;
        esac
    done

    [ "$want_help" = 1 ] && { _cly_help; return 0; }
    [ "$want_init" = 1 ] && { _cly_init "$init_dir"; return $?; }

    bin=${CLY_BIN:-claude}
    # ${VAR+set} rather than :- so that CLY_FLAGS="" means "no flags at all"
    # and not "fall back to the defaults".
    if [ "${CLY_FLAGS+set}" = set ]; then
        flags=$CLY_FLAGS
    else
        flags="--remote-control --dangerously-skip-permissions"
    fi

    configured=$(_cly_config_read 2>/dev/null) || configured=

    if [ "$want_config" = 1 ]; then
        echo "config file: $(_cly_config_path)"
        if [ -n "$configured" ]; then
            echo "configured:  $configured"
        else
            echo "configured:  (nothing yet — you will be asked on first launch)"
        fi
        [ -n "${CLY_DIR:-}" ] && echo "CLY_DIR:     $CLY_DIR (overrides the config)"
        echo "executable:  $bin"
        echo "flags:       ${flags:-(none)}"
        return 0
    fi

    # Precedence, most specific first.
    if [ "$no_dir" = 1 ]; then
        dir=
    elif [ -n "$dir" ]; then
        :
    elif [ -n "${CLY_DIR:-}" ]; then
        dir=$CLY_DIR
    elif [ -n "$configured" ]; then
        [ "$configured" = none ] && dir= || dir=$(_cly_to_posix "$configured")
    elif _cly_stdin_is_tty; then
        # First use. Ask, remember, and carry on into the launch below.
        _cly_init "" || return 1
        configured=$(_cly_config_read 2>/dev/null) || configured=
        [ "$configured" = none ] && dir= || dir=$(_cly_to_posix "$configured")
    else
        # No config and nothing to ask with: behave like plain claude rather
        # than blocking a script on a prompt nobody can answer.
        dir=
    fi

    # Deliberately unquoted: $flags is a list of arguments, not one argument.
    # shellcheck disable=SC2086
    if [ -z "$dir" ]; then
        $bin $flags ${passthru[@]+"${passthru[@]}"}
    elif [ -d "$dir" ]; then
        ( cd "$dir" && exec $bin $flags ${passthru[@]+"${passthru[@]}"} )
    else
        # Configured but gone. Worth saying — the symptom otherwise is memories
        # quietly not loading.
        echo "cly: $dir does not exist — launching in $PWD instead" >&2
        echo "cly: run 'cly --cly-init' to point it somewhere else" >&2
        $bin $flags ${passthru[@]+"${passthru[@]}"}
    fi
}
