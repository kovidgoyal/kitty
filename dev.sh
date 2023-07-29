#!/bin/sh
#
# dev.sh
# Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
#
# Distributed under terms of the GPLv3 license.
#

exec go run bypy/devenv.go "$@"
