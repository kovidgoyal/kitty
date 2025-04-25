#!/bin/sh
#
# rsync-and-build.sh
# Copyright (C) 2025 Kovid Goyal <kovid at kovidgoyal.net>
#
# Distributed under terms of the MIT license.

rsync --info=progress2 -a -zz --delete --force --exclude /bypy/b --exclude '*_generated.*' --exclude '*_generated_test.*' --exclude '/docs/_build' --include '/.github' --exclude '/.*' --exclude '/dependencies' --exclude '/tags' --exclude '__pycache__' --exclude '/kitty/launcher/kitt*' --exclude '/build' --exclude '/dist' --exclude '*.swp' --exclude '*.swo' --exclude '*.so' --exclude '*.dylib' --exclude '*.dSYM' "$BUILDBOT" . && exec ./dev.sh build "$@"
