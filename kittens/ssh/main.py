#!/usr/bin/env python3
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import atexit
import io
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
from contextlib import suppress
from typing import Dict, Iterator, List, NoReturn, Optional, Set, Tuple

from kitty.constants import cache_dir, shell_integration_dir, terminfo_dir
from kitty.short_uuid import uuid4
from kitty.utils import SSHConnectionData

from .completion import complete, ssh_options

DEFAULT_SHELL_INTEGRATION_DEST = '.local/share/kitty-ssh-kitten/shell-integration'


def make_tarfile(hostname: str = '', shell_integration_dest: str = DEFAULT_SHELL_INTEGRATION_DEST) -> bytes:

    def filter_files(tarinfo: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
        if tarinfo.name.endswith('ssh/bootstrap.sh') or tarinfo.name.endswith('ssh/bootstrap.py'):
            return None
        tarinfo.uname = tarinfo.gname = 'kitty'
        tarinfo.uid = tarinfo.gid = 0
        return tarinfo

    buf = io.BytesIO()
    with tarfile.open(mode='w:bz2', fileobj=buf, encoding='utf-8') as tf:
        tf.add(shell_integration_dir, arcname=shell_integration_dest, filter=filter_files)
        tf.add(terminfo_dir, arcname='.terminfo', filter=filter_files)
    return buf.getvalue()


def get_ssh_data(msg: str, shell_integration_dest: str = DEFAULT_SHELL_INTEGRATION_DEST) -> Iterator[bytes]:
    yield b"KITTY_SSH_DATA_START\n"
    try:
        hostname, pwfilename, pw = msg.split(':', 2)
    except Exception:
        yield b' invalid ssh data request message\n'
    try:
        with open(os.path.join(cache_dir(), pwfilename)) as f:
            os.unlink(f.name)
            if pw != f.read():
                raise ValueError('Incorrect password')
    except Exception:
        yield b' incorrect ssh data password\n'
    else:
        try:
            data = make_tarfile(hostname, shell_integration_dest)
        except Exception:
            yield b' error while gathering ssh data\n'
        else:
            from base64 import standard_b64encode
            encoded_data = memoryview(standard_b64encode(data))
            while encoded_data:
                yield encoded_data[:2048]
                yield b'\n'
                encoded_data = encoded_data[2048:]
    yield b"KITTY_SSH_DATA_END\n"


def safe_remove(x: str) -> None:
    with suppress(OSError):
        os.remove(x)


def prepare_script(ans: str, replacements: Dict[str, str]) -> str:
    pw = uuid4()
    with tempfile.NamedTemporaryFile(prefix='ssh-kitten-pw-', dir=cache_dir(), delete=False) as tf:
        tf.write(pw.encode('utf-8'))
    atexit.register(safe_remove, tf.name)
    replacements['DATA_PASSWORD'] = pw
    replacements['PASSWORD_FILENAME'] = os.path.basename(tf.name)
    for k in ('EXEC_CMD', 'OVERRIDE_LOGIN_SHELL'):
        replacements[k] = replacements.get(k, '')
    replacements['SHELL_INTEGRATION_DIR'] = replacements.get('SHELL_INTEGRATION_DIR', DEFAULT_SHELL_INTEGRATION_DEST)
    replacements['SHELL_INTEGRATION_VALUE'] = replacements.get('SHELL_INTEGRATION_VALUE', 'enabled')

    def sub(m: 're.Match[str]') -> str:
        return replacements[m.group()]

    return re.sub('|'.join(fr'\b{k}\b' for k in replacements), sub, ans)


def bootstrap_script(script_type: str = 'sh', **replacements: str) -> str:
    with open(os.path.join(shell_integration_dir, 'ssh', f'bootstrap.{script_type}')) as f:
        ans = f.read()
    return prepare_script(ans, replacements)


SHELL_SCRIPT = '''\
#!/bin/sh
# macOS ships with an ancient version of tic that cannot read from stdin, so we
# create a temp file for it
tmp=$(mktemp)
cat >$tmp << 'TERMEOF'
TERMINFO
TERMEOF

tname=.terminfo
if [ -e "/usr/share/misc/terminfo.cdb" ]; then
    # NetBSD requires this see https://github.com/kovidgoyal/kitty/issues/4622
    tname=".terminfo.cdb"
fi
tic_out=$(tic -x -o $HOME/$tname $tmp 2>&1)
rc=$?
rm $tmp
if [ "$rc" != "0" ]; then echo "$tic_out"; exit 1; fi
if [ -z "$USER" ]; then export USER=$(whoami); fi
export TERMINFO="$HOME/$tname"
login_shell=""
python=""

login_shell_is_ok() {
    if [ -z "$login_shell" ] || [ ! -x "$login_shell" ]; then return 1; fi
    case "$login_shell" in
        *sh) return 0;
    esac
    return 1;
}

detect_python() {
    python=$(command -v python3)
    if [ -z "$python" ]; then python=$(command -v python2); fi
    if [ -z "$python" ]; then python=python; fi
}

using_getent() {
    cmd=$(command -v getent)
    if [ -z "$cmd" ]; then return; fi
    output=$($cmd passwd $USER 2>/dev/null)
    if [ $? = 0 ]; then login_shell=$(echo $output | cut -d: -f7); fi
}

using_id() {
    cmd=$(command -v id)
    if [ -z "$cmd" ]; then return; fi
    output=$($cmd -P $USER 2>/dev/null)
    if [ $? = 0 ]; then login_shell=$(echo $output | cut -d: -f7); fi
}

using_passwd() {
    cmd=$(command -v grep)
    if [ -z "$cmd" ]; then return; fi
    output=$($cmd "^$USER:" /etc/passwd 2>/dev/null)
    if [ $? = 0 ]; then login_shell=$(echo $output | cut -d: -f7); fi
}

using_python() {
    detect_python
    if [ ! -x "$python" ]; then return; fi
    output=$($python -c "import pwd, os; print(pwd.getpwuid(os.geteuid()).pw_shell)")
    if [ $? = 0 ]; then login_shell=$output; fi
}

execute_with_python() {
    detect_python
    exec $python -c "import os; os.execl('$login_shell', '-' '$shell_name')"
}

die() { echo "$*" 1>&2 ; exit 1; }

using_getent
if ! login_shell_is_ok; then using_id; fi
if ! login_shell_is_ok; then using_python; fi
if ! login_shell_is_ok; then using_passwd; fi
if ! login_shell_is_ok; then die "Could not detect login shell"; fi


# If a command was passed to SSH execute it here
EXEC_CMD

# We need to pass the first argument to the executed program with a leading -
# to make sure the shell executes as a login shell. Note that not all shells
# support exec -a so we use the below to try to detect such shells
shell_name=$(basename $login_shell)
if [ -z "$PIPESTATUS" ]; then
    # the dash shell does not support exec -a and also does not define PIPESTATUS
    execute_with_python
fi
exec -a "-$shell_name" $login_shell
'''


PYTHON_SCRIPT = '''\
#!/usr/bin/env python
from __future__ import print_function
from tempfile import NamedTemporaryFile
import subprocess, os, sys, pwd, binascii, json

# macOS ships with an ancient version of tic that cannot read from stdin, so we
# create a temp file for it
with NamedTemporaryFile() as tmp:
    tname = '.terminfo'
    if os.path.exists('/usr/share/misc/terminfo.cdb'):
        tname += '.cdb'
    tmp.write(binascii.unhexlify('{terminfo}'))
    tmp.flush()
    p = subprocess.Popen(['tic', '-x', '-o', os.path.expanduser('~/' + tname), tmp.name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = p.communicate()
    if p.wait() != 0:
        getattr(sys.stderr, 'buffer', sys.stderr).write(stdout + stderr)
        raise SystemExit('Failed to compile terminfo using tic')
command_to_execute = json.loads(binascii.unhexlify('{command_to_execute}'))
try:
    shell_path = pwd.getpwuid(os.geteuid()).pw_shell or '/bin/sh'
except KeyError:
    shell_path = '/bin/sh'
shell_name = '-' + os.path.basename(shell_path)
if command_to_execute:
    os.execlp(shell_path, shell_path, '-c', command_to_execute)
os.execlp(shell_path, shell_name)
'''


def get_ssh_cli() -> Tuple[Set[str], Set[str]]:
    other_ssh_args: Set[str] = set()
    boolean_ssh_args: Set[str] = set()
    for k, v in ssh_options().items():
        k = f'-{k}'
        if v:
            other_ssh_args.add(k)
        else:
            boolean_ssh_args.add(k)
    return boolean_ssh_args, other_ssh_args


def get_connection_data(args: List[str], cwd: str = '') -> Optional[SSHConnectionData]:
    boolean_ssh_args, other_ssh_args = get_ssh_cli()
    port: Optional[int] = None
    expecting_port = expecting_identity = False
    expecting_option_val = False
    expecting_hostname = False
    host_name = identity_file = found_ssh = ''

    for i, arg in enumerate(args):
        if not found_ssh:
            if os.path.basename(arg).lower() in ('ssh', 'ssh.exe'):
                found_ssh = arg
            continue
        if expecting_hostname:
            host_name = arg
            continue
        if arg.startswith('-') and not expecting_option_val:
            if arg in boolean_ssh_args:
                continue
            if arg == '--':
                expecting_hostname = True
            if arg.startswith('-p'):
                if arg[2:].isdigit():
                    with suppress(Exception):
                        port = int(arg[2:])
                    continue
                elif arg == '-p':
                    expecting_port = True
            elif arg.startswith('-i'):
                if arg == '-i':
                    expecting_identity = True
                else:
                    identity_file = arg[2:]
                    continue
            expecting_option_val = True
            continue

        if expecting_option_val:
            if expecting_port:
                with suppress(Exception):
                    port = int(arg)
                expecting_port = False
            elif expecting_identity:
                identity_file = arg
            expecting_option_val = False
            continue

        if not host_name:
            host_name = arg
    if not host_name:
        return None
    if identity_file:
        if not os.path.isabs(identity_file):
            identity_file = os.path.expanduser(identity_file)
        if not os.path.isabs(identity_file):
            identity_file = os.path.normpath(os.path.join(cwd or os.getcwd(), identity_file))

    return SSHConnectionData(found_ssh, host_name, port, identity_file)


class InvalidSSHArgs(ValueError):

    def __init__(self, msg: str = ''):
        super().__init__(msg)
        self.err_msg = msg

    def system_exit(self) -> None:
        if self.err_msg:
            print(self.err_msg, file=sys.stderr)
        os.execlp('ssh', 'ssh')


def parse_ssh_args(args: List[str]) -> Tuple[List[str], List[str], bool]:
    boolean_ssh_args, other_ssh_args = get_ssh_cli()
    passthrough_args = {f'-{x}' for x in 'Nnf'}
    ssh_args = []
    server_args: List[str] = []
    expecting_option_val = False
    passthrough = False
    stop_option_processing = False
    for argument in args:
        if len(server_args) > 1 or stop_option_processing:
            server_args.append(argument)
            continue
        if argument.startswith('-') and not expecting_option_val:
            if argument == '--':
                stop_option_processing = True
                continue
            # could be a multi-character option
            all_args = argument[1:]
            for i, arg in enumerate(all_args):
                arg = f'-{arg}'
                if arg in passthrough_args:
                    passthrough = True
                if arg in boolean_ssh_args:
                    ssh_args.append(arg)
                    continue
                if arg in other_ssh_args:
                    ssh_args.append(arg)
                    rest = all_args[i+1:]
                    if rest:
                        ssh_args.append(rest)
                    else:
                        expecting_option_val = True
                    break
                raise InvalidSSHArgs(f'unknown option -- {arg[1:]}')
            continue
        if expecting_option_val:
            ssh_args.append(argument)
            expecting_option_val = False
            continue
        server_args.append(argument)
    if not server_args:
        raise InvalidSSHArgs()
    return ssh_args, server_args, passthrough


def get_posix_cmd(terminfo: str, remote_args: List[str]) -> List[str]:
    sh_script = SHELL_SCRIPT.replace('TERMINFO', terminfo, 1)
    command_to_execute = ''
    if remote_args:
        # ssh simply concatenates multiple commands using a space see
        # line 1129 of ssh.c and on the remote side sshd.c runs the
        # concatenated command as shell -c cmd
        args = [c.replace("'", """'"'"'""") for c in remote_args]
        command_to_execute = "exec $login_shell -c '{}'".format(' '.join(args))
    sh_script = sh_script.replace('EXEC_CMD', command_to_execute)
    return [f'sh -c {shlex.quote(sh_script)}']


def get_python_cmd(terminfo: str, command_to_execute: List[str]) -> List[str]:
    import json
    script = PYTHON_SCRIPT.format(
        terminfo=terminfo.encode('utf-8').hex(),
        command_to_execute=json.dumps(' '.join(command_to_execute)).encode('utf-8').hex()
    )
    return [f'python -c "{script}"']


def main(args: List[str]) -> NoReturn:
    args = args[1:]
    use_posix = True
    if args and args[0] == 'use-python':
        args = args[1:]
        use_posix = False
    try:
        ssh_args, server_args, passthrough = parse_ssh_args(args)
    except InvalidSSHArgs as e:
        e.system_exit()
    cmd = ['ssh'] + ssh_args
    if passthrough:
        cmd += server_args
    else:
        hostname, remote_args = server_args[0], server_args[1:]
        if not remote_args:
            cmd.append('-t')
        cmd.append('--')
        cmd.append(hostname)
        terminfo = subprocess.check_output(['infocmp', '-a']).decode('utf-8')
        f = get_posix_cmd if use_posix else get_python_cmd
        cmd += f(terminfo, remote_args)
    os.execvp('ssh', cmd)


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__completer__':
    setattr(sys, 'kitten_completer', complete)
