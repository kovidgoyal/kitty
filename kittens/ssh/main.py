#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import subprocess
import sys

SHELL_SCRIPT = '''\
#!/bin/sh
# macOS ships with an ancient version of tic that cannot read from stdin, so we
# create a temp file for it
tmp=$(mktemp /tmp/terminfo.XXXXXX)
cat >$tmp << 'TERMEOF'
TERMINFO
TERMEOF

tic_out=$(tic -x -o ~/.terminfo $tmp 2>&1)
rc=$?
rm $tmp
if [ "$rc" != "0" ]; then echo "$tic_out"; exit 1; fi
if [ -z "$USER" ]; then export USER=$(whoami); fi


# We need to pass the first argument to the executed program with a leading -
# to make sure the shell executes as a login shell. Note that not all shells
# support exec -a
shell_name=$(basename $0)
exec -a "-$shell_name" "$0"
# exec does not support -a
exec "$0" --login
'''


def main(args):
    server = args[1]
    terminfo = subprocess.check_output(['infocmp']).decode('utf-8')
    sh_script = SHELL_SCRIPT.replace('TERMINFO', terminfo, 1)
    cmd = ['ssh', '-t', server, sh_script]
    p = subprocess.Popen(cmd)
    raise SystemExit(p.wait())


if __name__ == '__main__':
    main(sys.argv)
