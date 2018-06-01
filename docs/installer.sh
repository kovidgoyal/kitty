#!/bin/sh
#
# installer.sh
# Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
#
# Distributed under terms of the GPLv3 license.
#

python=$(command -v python3)
if [ -z "$python" ]; then
    python=$(command -v python2)
fi
if [ -z "$python" ]; then
    python=$(command -v python2.7)
fi
if [ -z "$python" ]; then
    python=$(command -v python)
fi
if [ -z "$python" ]; then
    python=python
fi

echo Using python executable: $python

$python -c "import sys; script_launch=lambda:sys.exit('Download of installer failed!'); exec(sys.stdin.read()); script_launch()" "$@" <<'INSTALLER_HEREDOC'
# {{{
# HEREDOC_START
# HEREDOC_END
# }}}
INSTALLER_HEREDOC
