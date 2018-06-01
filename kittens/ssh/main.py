#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
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
EXEC_CMD
shell_name=$(basename $0)

# We need to pass the first argument to the executed program with a leading -
# to make sure the shell executes as a login shell. Note that not all shells
# support exec -a so we use the below to try to detect such shells

case "dash" in
    *$shell_name*)
        python=$(command -v python3)
        if [ -z "$python" ]; then python=$(command -v python2); fi
        if [ -z "$python" ]; then python=python; fi
        exec $python -c "import os; os.execlp('$0', '-' '$shell_name')"
    ;;
esac

exec -a "-$shell_name" "$0"
'''


def parse_ssh_args(args):
    boolean_ssh_args = {'-' + x for x in '46AaCfGgKkMNnqsTtVvXxYy'}
    other_ssh_args = {'-' + x for x in 'bBcDeEFIJlLmOopQRSWw'}
    passthrough_args = {'-' + x for x in 'Nnf'}
    ssh_args = []
    server_args = []
    expecting_option_val = False
    passthrough = False
    for arg in args:
        if server_args:
            server_args.append(arg)
            continue
        if arg.startswith('-'):
            if arg in passthrough_args:
                passthrough = True
            if arg in boolean_ssh_args:
                ssh_args.append(arg)
                continue
            if arg in other_ssh_args:
                ssh_args.append(arg)
                expecting_option_val = True
                continue
            raise SystemExit('Unknown option: {}'.format(args))
        if expecting_option_val:
            ssh_args.append(arg)
            expecting_option_val = False
            continue
        server_args.append(arg)
    if not server_args:
        raise SystemExit('Must specify server to connect to')
    return ssh_args, server_args, passthrough


def main(args):
    ssh_args, server_args, passthrough = parse_ssh_args(args[1:])
    if passthrough:
        cmd = ['ssh'] + ssh_args + server_args
    else:
        terminfo = subprocess.check_output(['infocmp']).decode('utf-8')
        sh_script = SHELL_SCRIPT.replace('TERMINFO', terminfo, 1)
        if len(server_args) > 1:
            command_to_execute = ["'{}'".format(c.replace("'", """'"'"'""")) for c in server_args[1:]]
            command_to_execute = 'cmd=({}); exec "$cmd"'.format(' '.join(command_to_execute))
        else:
            command_to_execute = ''
        sh_script = sh_script.replace('EXEC_CMD', command_to_execute)
        cmd = ['ssh'] + ssh_args + ['-t', server_args[0], sh_script] + server_args[1:]
    os.execvp('ssh', cmd)


if __name__ == '__main__':
    main(sys.argv)
