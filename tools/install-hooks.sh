#!/usr/bin/env bash
#
# install-hooks.sh — symlink tracked hooks in tools/hooks/ into
# .git/hooks/.  Run once after cloning, or any time a new hook is
# added to tools/hooks/.
#
# Existing hooks of the same name are backed up to <name>.bak.  To
# uninstall, delete the symlinks under .git/hooks/.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOKS_SRC="$REPO_ROOT/tools/hooks"
HOOKS_DST="$REPO_ROOT/.git/hooks"

if [[ ! -d "$HOOKS_DST" ]]; then
    echo "error: $HOOKS_DST does not exist — is this a git checkout?" >&2
    exit 1
fi

installed=0
for hook in "$HOOKS_SRC"/*; do
    [[ -f "$hook" ]] || continue
    name="$(basename "$hook")"
    target="$HOOKS_DST/$name"

    # If the destination already exists and isn't our symlink, back it up.
    if [[ -e "$target" && ! -L "$target" ]]; then
        mv "$target" "$target.bak"
        echo "backed up existing $name → $name.bak"
    elif [[ -L "$target" ]]; then
        rm "$target"
    fi

    ln -s "../../tools/hooks/$name" "$target"
    chmod +x "$hook"
    echo "installed $name"
    installed=$((installed + 1))
done

echo "$installed hook(s) installed.  Bypass for a one-off commit with --no-verify."
