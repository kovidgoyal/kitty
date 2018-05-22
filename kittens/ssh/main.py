#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import subprocess
import sys

SHELL_SCRIPT = '''\
#!/bin/sh

tmp=$(mktemp /tmp/terminfo.XXXXXX)
cat >$tmp << 'TERMEOF'
TERMINFO
TERMEOF

tic_out=$(tic -x -o ~/.terminfo $tmp 2>&1)
rc=$?
rm $tmp
if [ "$rc" != "0" ]; then echo "$tic_out"; exit 1; fi
if [ -z "$USER" ]; then USER=$(whoami); fi
search_for_python() {
    # We have to search for python as Ubuntu, in its infinite wisdom decided
    # to release 18.04 with no python symlink, making it impossible to run polyglot
    # python scripts.

    # We cannot use command -v as it is not implemented in the posh shell shipped with
    # Ubuntu/Debian. Similarly, there is no guarantee that which is installed.
    # Shell scripting is a horrible joke, thank heavens for python.
    local IFS=:
    if [ $ZSH_VERSION ]; then
        # zsh does not split by default
        setopt sh_word_split
    fi
    local candidate_path
    local candidate_python
    local pythons=python3:python2
    # disable pathname expansion (globbing)
    set -f
    for candidate_path in $PATH
    do
        if [ ! -z $candidate_path ]
        then
            for candidate_python in $pythons
            do
                if [ ! -z "$candidate_path" ]
                then
                    if [ -x "$candidate_path/$candidate_python" ]
                    then
                        printf "$candidate_path/$candidate_python"
                        return
                    fi
                fi
            done
        fi
    done
    set +f
    printf "python"
}
PYTHON=$(search_for_python)
exec $PYTHON -c "import os, pwd; shell = pwd.getpwuid(os.geteuid()).pw_shell or 'sh'; os.execlp(shell, '-' + os.path.basename(shell))"
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
