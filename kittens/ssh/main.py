#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import shlex
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


def get_ssh_cli():
    other_ssh_args, boolean_ssh_args = [], []
    raw = subprocess.Popen(['ssh'], stderr=subprocess.PIPE).stderr.read().decode('utf-8')
    for m in re.finditer(r'\[(.+?)\]', raw):
        q = m.group(1)
        if len(q) < 2 or q[0] != '-':
            continue
        if ' ' in q:
            other_ssh_args.append(q[1])
        else:
            boolean_ssh_args.extend(q[1:])
    return set('-' + x for x in boolean_ssh_args), set('-' + x for x in other_ssh_args)


def parse_ssh_args(args):
    boolean_ssh_args, other_ssh_args = get_ssh_cli()
    passthrough_args = {'-' + x for x in 'Nnf'}
    ssh_args = []
    server_args = []
    expecting_option_val = False
    passthrough = False
    for arg in args:
        if len(server_args) > 1:
            server_args.append(arg)
            continue
        if arg.startswith('-') and not expecting_option_val:
            all_args = arg[1:]
            for i, arg in enumerate(all_args):
                arg = '-' + arg
                if arg in passthrough_args:
                    passthrough = True
                if arg in boolean_ssh_args:
                    ssh_args.append(arg)
                    continue
                if arg in other_ssh_args:
                    if i != len(all_args) - 1:
                        raise SystemExit('Option {} cannot occur in the middle'.format(arg))
                    ssh_args.append(arg)
                    expecting_option_val = True
                    continue
                raise SystemExit('Unknown option: {}'.format(arg))
            continue
        if expecting_option_val:
            ssh_args.append(arg)
            expecting_option_val = False
            continue
        server_args.append(arg)
    if not server_args:
        raise SystemExit('Must specify server to connect to')
    return ssh_args, server_args, passthrough


def quote(x):
    # we have to escape unbalanced quotes and other unparsable
    # args as they will break the shell script
    # But we do not want to quote things like * or 'echo hello'
    # See https://github.com/kovidgoyal/kitty/issues/1787
    try:
        shlex.split(x)
    except ValueError:
        x = shlex.quote(x)
    return x


def main(args):
    ssh_args, server_args, passthrough = parse_ssh_args(args[1:])
    if passthrough:
        cmd = ['ssh'] + ssh_args + server_args
    else:
        terminfo = subprocess.check_output(['infocmp']).decode('utf-8')
        sh_script = SHELL_SCRIPT.replace('TERMINFO', terminfo, 1)
        if len(server_args) > 1:
            command_to_execute = [quote(c) for c in server_args[1:]]
            command_to_execute = 'exec ' + ' '.join(command_to_execute)
        else:
            command_to_execute = ''
        sh_script = sh_script.replace('EXEC_CMD', command_to_execute)
        cmd = ['ssh'] + ssh_args + ['-t', server_args[0], sh_script] + server_args[1:]
    os.execvp('ssh', cmd)


if __name__ == '__main__':
    main(sys.argv)
