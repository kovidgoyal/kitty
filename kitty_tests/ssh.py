#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
import sys

from kittens.ssh.main import get_connection_data
from kitty.utils import SSHConnectionData

from . import BaseTest


class SSHTest(BaseTest):

    def test_basic_pty_operations(self):
        pty = self.create_pty('echo hello')
        self.assertTrue(pty.wait_for_input_from_child())
        pty.process_input_from_child()
        self.ae(pty.screen_contents(), 'hello')
        pty = self.create_pty([sys.executable, '-c', '''\
import array, fcntl, sys, termios
buf = array.array('H', [0, 0, 0, 0])
fcntl.ioctl(sys.stdout, termios.TIOCGWINSZ, buf)
print(' '.join(map(str, buf)))'''], lines=13, cols=17)
        self.assertTrue(pty.wait_for_input_from_child())
        pty.process_input_from_child()
        self.ae(pty.screen_contents(), '13 17 0 0')

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
