#!/bin/sh

# To be used via a script such as
: <<'COMMENT'
export RSYNC_PASSWORD=password
export BUILDBOT=rsync://useranme@server/path/to/this/directory
mkdir -p ~/kitty-src
cd ~/kitty-src || exit 1

script=rsync-and-build.sh
if [[ -e "$script" ]]; then
    . "./$script"
else
    rsync -a --include "$script" --exclude '*' "$BUILDBOT" . && source "$script"
fi
COMMENT

rsync --info=progress2 -a -zz --delete --force --exclude /bypy/b --exclude '*_generated.*' --exclude '*_generated_test.*' --exclude '/docs/_build' --include '/.github' --exclude '/.*' --exclude '/dependencies' --exclude '/tags' --exclude '__pycache__' --exclude '/kitty/launcher/kitt*' --exclude '/build' --exclude '/dist' --exclude '*.swp' --exclude '*.swo' --exclude '*.so' --exclude '*.dylib' --exclude '*.dSYM' "$BUILDBOT" . && exec ./dev.sh build "$@"
