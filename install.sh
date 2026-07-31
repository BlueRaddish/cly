#!/usr/bin/env bash
# install.sh — wire cly.sh into your ~/.bashrc.
#
# Adds a single `source` line pointing at cly.sh where it already sits, so
# `git pull` in this directory updates the installed function too. Re-running
# is safe: the line is replaced, never duplicated.
#
# Usage: ./install.sh [--rc FILE] [--dir DIR] [--uninstall]

set -euo pipefail

SELF_DIR=$(cd "$(dirname "$0")" && pwd)
SRC="$SELF_DIR/cly.sh"
RC="$HOME/.bashrc"
CLY_DIR_VALUE=
UNINSTALL=0
MARKER="# >>> cly >>>"
END_MARKER="# <<< cly <<<"

while [ $# -gt 0 ]; do
  case $1 in
    --rc)        RC=${2:?--rc needs a file}; shift 2 ;;
    --dir)       CLY_DIR_VALUE=${2:?--dir needs a directory}; shift 2 ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help)
      sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "install: unknown option: $1" >&2; exit 1 ;;
  esac
done

[ -r "$SRC" ] || { echo "install: cannot find $SRC" >&2; exit 1; }

# Strip any previous block first — that is what makes re-running idempotent and
# gives --uninstall its behaviour for free.
if [ -f "$RC" ]; then
  tmp=$(mktemp)
  awk -v s="$MARKER" -v e="$END_MARKER" '
    $0 == s { skip = 1; next }
    $0 == e { skip = 0; next }
    !skip   { print }
  ' "$RC" > "$tmp"
  mv "$tmp" "$RC"
fi

if [ "$UNINSTALL" = 1 ]; then
  echo "cly: removed from $RC"
  exit 0
fi

{
  printf '%s\n' "$MARKER"
  [ -n "$CLY_DIR_VALUE" ] && printf 'export CLY_DIR=%s\n' "$CLY_DIR_VALUE"
  printf '. "%s"\n' "$SRC"
  printf '%s\n' "$END_MARKER"
} >> "$RC"

echo "cly: installed into $RC"
[ -n "$CLY_DIR_VALUE" ] && echo "cly: launch directory set to $CLY_DIR_VALUE"
echo "cly: open a new shell, or run: . $RC"
