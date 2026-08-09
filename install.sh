#!/usr/bin/env bash
# install.sh — put cly on your PATH.
#
# Writes a two-line stub into ~/bin that runs bin/cly where it already sits, so
# `git pull` in this clone is the whole of an upgrade. On Windows a cly.cmd
# stub goes beside it, because PowerShell and cmd will not run an extensionless
# file. Re-running is safe, and re-pointing after moving the clone is the same
# command again.
#
# usage: ./install.sh [--prefix DIR] [--uninstall] [--help]
#
#   --prefix DIR   where the stubs go (default: ~/bin)
#   --uninstall    remove the stubs instead of writing them
#   --help         show this help

set -eu

self_dir=$(cd "$(dirname "$0")" && pwd)
src="$self_dir/bin/cly"
src_cmd="$self_dir/bin/cly.cmd"
prefix="$HOME/bin"
uninstall=0

while [ $# -gt 0 ]; do
    case $1 in
        --prefix)    prefix=${2:?install: --prefix needs a directory}; shift 2 ;;
        --uninstall) uninstall=1; shift ;;
        -h|--help)
            sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *)
            echo "install: unknown option: $1" >&2
            echo "usage: ./install.sh [--prefix DIR] [--uninstall] [--help]" >&2
            exit 2 ;;
    esac
done

[ -r "$src" ] || { echo "install: cannot find $src" >&2; exit 1; }

# Windows is where the .cmd stub is worth having, and where the legacy install
# left lines in a PowerShell profile to clear out.
on_windows=0
case $(uname -s 2>/dev/null || echo unknown) in
    MSYS*|MINGW*|CYGWIN*|*NT*) on_windows=1 ;;
esac

to_windows_path() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$1"
    else
        # /c/Users/me -> C:\Users\me
        local p=$1 drive rest
        case $p in
            /?/*) drive=${p#/}; drive=${drive%%/*}
                  rest=${p#/?}
                  printf '%s:%s\n' "$drive" "${rest//\//\\}" ;;
            *) printf '%s\n' "${p//\//\\}" ;;
        esac
    fi
}

# --- uninstall ---------------------------------------------------------------

if [ "$uninstall" = 1 ]; then
    removed=0
    for f in "$prefix/cly" "$prefix/cly.cmd"; do
        if [ -e "$f" ]; then rm -f "$f"; echo "cly: removed $f"; removed=1; fi
    done
    [ "$removed" = 1 ] || echo "cly: nothing to remove in $prefix"
    echo "cly: the config in ~/.config/cly/ was left alone; delete it by hand"
    echo "cly: if you want the launch directory and flags forgotten too"
    exit 0
fi

# --- clear the v1 install ----------------------------------------------------

# v1 installed by appending a marker-delimited source line to ~/.bashrc and to
# both PowerShell profiles. Those lines point at cly.sh and cly.ps1, which no
# longer exist, so an upgrader would get an error in every new shell. Strip any
# that are still there. Silent when there are none, which is the normal case.
marker='# >>> cly >>>'
end_marker='# <<< cly <<<'
docs="$HOME/Documents"
[ -d "$docs" ] || docs="$HOME/OneDrive/Documents"
for rc in "$HOME/.bashrc" \
          "$docs/WindowsPowerShell/Microsoft.PowerShell_profile.ps1" \
          "$docs/PowerShell/Microsoft.PowerShell_profile.ps1"; do
    [ -f "$rc" ] || continue
    grep -qF "$marker" "$rc" 2>/dev/null || continue
    tmp=$(mktemp)
    skip=0
    while IFS= read -r line || [ -n "$line" ]; do
        stripped=${line%$'\r'}
        if [ "$stripped" = "$marker" ]; then skip=1; continue; fi
        if [ "$stripped" = "$end_marker" ]; then skip=0; continue; fi
        [ "$skip" = 1 ] || printf '%s\n' "$line"
    done < "$rc" > "$tmp"
    cat "$tmp" > "$rc"
    rm -f "$tmp"
    echo "cly: removed the old source line from $rc"
done

# --- install -----------------------------------------------------------------

mkdir -p "$prefix"

cat > "$prefix/cly" <<EOF
#!/usr/bin/env bash
# Written by cly's install.sh. It runs the clone in place, so a \`git pull\`
# there upgrades this command too. Re-run install.sh if you move the clone.
exec "$src" "\$@"
EOF
chmod +x "$prefix/cly"
echo "cly: installed $prefix/cly -> $src"

if [ "$on_windows" = 1 ] && [ -r "$src_cmd" ]; then
    win_cmd=$(to_windows_path "$src_cmd")
    # CRLF, because this one is read by cmd.exe.
    {
        printf '@echo off\r\n'
        printf 'rem Written by cly'"'"'s install.sh - runs the clone in place, so a\r\n'
        printf 'rem `git pull` there upgrades this command too.\r\n'
        printf '"%s" %%*\r\n' "$win_cmd"
        printf 'exit /b %%ERRORLEVEL%%\r\n'
    } > "$prefix/cly.cmd"
    echo "cly: installed $prefix/cly.cmd -> $win_cmd"
fi

# --- PATH --------------------------------------------------------------------

case ":$PATH:" in
    *":$prefix:"*) ;;
    *)
        echo
        echo "cly: $prefix is not on your PATH, so the command will not be found."
        if [ "$on_windows" = 1 ]; then
            echo "cly: add it to the Windows *User* PATH — a line in ~/.bashrc is"
            echo "cly: invisible to PowerShell, cmd and anything launched from the"
            echo "cly: Start menu. In PowerShell, once:"
            echo
            echo "     [Environment]::SetEnvironmentVariable('Path',"
            echo "       [Environment]::GetEnvironmentVariable('Path','User') +"
            echo "       ';$(to_windows_path "$prefix")', 'User')"
            echo
            echo "cly: then open a new shell — PATH is read once, at startup."
        else
            echo "cly: add   export PATH=\"$prefix:\$PATH\"   to your shell profile."
        fi ;;
esac

echo
echo "cly: run 'cly' — it asks for a launch directory and your standing flags,"
echo "cly: once, and then never again."
