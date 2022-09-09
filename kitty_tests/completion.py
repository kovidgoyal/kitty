#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import json
import shlex
import subprocess
import tempfile

from kitty.constants import kitty_tool_exe as kitty_tool

from . import BaseTest


class TestCompletion(BaseTest):

    def test_completion(self):
        completion(self)


def has_words(*words):
    def t(self, result):
        q = set(words)
        for group in result['groups']:
            for m in group['matches']:
                if m['word'] in words:
                    q.discard(m['word'])
        self.assertFalse(q, f'Command line: {self.current_cmd!r}')
    return t


def completion(self: TestCompletion):
    all_cmds = []
    all_argv = []
    all_tests = []

    def add(cmdline: str, *tests):
        all_cmds.append(cmdline)
        new_word = cmdline.endswith(' ')
        if new_word:
            cmdline = cmdline[:-1]
        all_argv.append(shlex.split(cmdline))
        if new_word:
            all_argv[-1].append('')
        all_tests.append(tests)

    def run_tool():
        with tempfile.TemporaryDirectory() as tdir:
            return json.loads(subprocess.run(
                [kitty_tool(), '__complete__', 'json'],
                check=True, stdout=subprocess.PIPE, cwd=tdir, input=json.dumps(all_argv).encode()
            ).stdout)

    add('kitty ', has_words('@', '@ls'))
    add('kitty @ l', has_words('ls', 'last-used-layout', 'launch'))
    add('kitty @l', has_words('@ls', '@last-used-layout', '@launch'))

    for cmd, tests, result in zip(all_cmds, all_tests, run_tool()):
        self.current_cmd = cmd
        for test in tests:
            test(self, result)
