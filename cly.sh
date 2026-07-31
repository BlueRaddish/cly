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
# Configure by exporting any of these before the call:
#   CLY_DIR    directory to launch from  (default: $HOME/claude)
#   CLY_BIN    the claude executable     (default: claude, found on PATH)
#   CLY_FLAGS  flags passed every time   (default: --remote-control
#              --dangerously-skip-permissions; set to "" for none)
#
# A function rather than an alias because an alias cannot change directory. The
# body runs in a subshell, so your own shell is still where you left it on exit.
cly() {
    local dir=${CLY_DIR:-$HOME/claude}
    local bin=${CLY_BIN:-claude}
    local flags

    # ${VAR+set} rather than :- so that CLY_FLAGS="" means "no flags at all"
    # and not "fall back to the defaults".
    if [ "${CLY_FLAGS+set}" = set ]; then
        flags=$CLY_FLAGS
    else
        flags="--remote-control --dangerously-skip-permissions"
    fi

    # Deliberately unquoted: $flags is a list of arguments, not one argument.
    # shellcheck disable=SC2086
    if [ -d "$dir" ]; then
        ( cd "$dir" && exec $bin $flags "$@" )
    elif [ -n "${CLY_DIR:-}" ]; then
        # You asked for a specific directory and it is not there — worth saying,
        # because the symptom otherwise is memories quietly not loading.
        echo "cly: CLY_DIR=$CLY_DIR does not exist — starting in $PWD instead" >&2
        $bin $flags "$@"
    else
        # Nothing configured and no ~/claude to default to: behave like plain
        # claude. Nobody asked for the directory pinning, so do not complain.
        $bin $flags "$@"
    fi
}
