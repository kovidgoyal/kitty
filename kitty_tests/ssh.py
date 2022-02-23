#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
import shlex
import shutil
import tempfile

from kittens.ssh.main import bootstrap_script, get_connection_data
from kitty.utils import SSHConnectionData

from . import BaseTest
from .shell_integration import bash_ok, basic_shell_env


class SSHTest(BaseTest):

    def test_basic_pty_operations(self):
        pty = self.create_pty('echo hello')
        pty.process_input_from_child()
        self.ae(pty.screen_contents(), 'hello')
        pty = self.create_pty(self.cmd_to_run_python_code('''\
import array, fcntl, sys, termios
buf = array.array('H', [0, 0, 0, 0])
fcntl.ioctl(sys.stdout, termios.TIOCGWINSZ, buf)
print(' '.join(map(str, buf)))'''), lines=13, cols=77)
        pty.process_input_from_child()
        self.ae(pty.screen_contents(), '13 77 770 260')

    def test_ssh_connection_data(self):
        def t(cmdline, binary='ssh', host='main', port=None, identity_file=''):
            if identity_file:
                identity_file = os.path.abspath(identity_file)
            q = get_connection_data(cmdline.split())
            self.ae(q, SSHConnectionData(binary, host, port, identity_file))

        t('ssh main')
        t('ssh un@ip -i ident -p34', host='un@ip', port=34, identity_file='ident')
        t('ssh un@ip -iident -p34', host='un@ip', port=34, identity_file='ident')
        t('ssh -p 33 main', port=33)

    def test_ssh_bootstrap_script(self):
        for sh in ('dash', 'zsh', 'bash', 'posh', 'sh'):
            q = shutil.which(sh)
            if q:
                if sh == 'bash' and not bash_ok():
                    continue
                with self.subTest(sh=sh), tempfile.TemporaryDirectory() as tdir:
                    script = bootstrap_script(EXEC_CMD='echo UNTAR_DONE; exit 0')
                    env = basic_shell_env(tdir)
                    pty = self.create_pty(f'{sh} -c {shlex.quote(script)}', cwd=tdir, env=env)
                    self.check_bootstrap(tdir, pty)

    def check_bootstrap(self, home_dir, pty):
        pty.wait_till(lambda: 'UNTAR_DONE' in pty.screen_contents())
        self.assertTrue(os.path.exists(os.path.join(home_dir, '.terminfo/kitty.terminfo')))
