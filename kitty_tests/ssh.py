#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
from . import BaseTest

from kittens.ssh.main import get_connection_data
from kitty.utils import SSHConnectionData


class SSHTest(BaseTest):

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
