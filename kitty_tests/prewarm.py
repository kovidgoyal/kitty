#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import json
import os
import tempfile

from kitty.constants import kitty_exe
from kitty.fast_data_types import get_options

from . import BaseTest


class Prewarm(BaseTest):

    maxDiff = None

    def test_prewarming(self):
        from kittens.prewarm.main import PrewarmProcess

        p = PrewarmProcess(create_file_to_read_from_worker=True)
        cwd = tempfile.gettempdir()
        env = {'TEST_ENV_PASS': 'xyz'}
        cols = 117
        stdin_data = 'from_stdin'
        pty = self.create_pty(cols=cols)
        ttyname = os.ttyname(pty.slave_fd)
        opts = get_options()
        opts.config_overrides = 'font_family prewarm',
        child = p(pty.slave_fd, [kitty_exe(), '+runpy', """\
import os, json; from kitty.utils import *; from kitty.fast_data_types import get_options; print(json.dumps({
        'cterm': os.ctermid(),
        'ttyname': os.ttyname(sys.stdout.fileno()),
        'cols': read_screen_size().cols,
        'cwd': os.getcwd(),
        'env': os.environ.get('TEST_ENV_PASS'),
        'pid': os.getpid(),
        'font_family': get_options().font_family,
        'stdin': sys.stdin.read(),

        'done': 'hello',
        }, indent=2))"""], cwd=cwd, env=env, stdin_data=stdin_data)
        self.assertFalse(pty.screen_contents().strip())
        p.mark_child_as_ready(child.child_id)
        pty.wait_till(lambda: 'hello' in pty.screen_contents())
        data = json.loads(pty.screen_contents())
        self.ae(data['cols'], cols)
        self.assertTrue(data['cterm'])
        self.ae(data['ttyname'], ttyname)
        self.ae(os.path.realpath(data['cwd']), os.path.realpath(cwd))
        self.ae(data['env'], env['TEST_ENV_PASS'])
        self.ae(data['font_family'], 'prewarm')
        self.ae(int(p.from_worker.readline()), data['pid'])
