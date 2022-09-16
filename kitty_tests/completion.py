#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import json
import os
import shlex
import subprocess
import tempfile

from kitty.constants import kitty_tool_exe as kitty_tool

from . import BaseTest


class TestCompletion(BaseTest):

    def test_completion(self):
        with tempfile.TemporaryDirectory() as tdir:
            completion(self, tdir)


def get_all_words(result):
    all_words = set()
    for group in result.get('groups', ()):
        for m in group['matches']:
            all_words.add(m['word'])
    return all_words


def has_words(*words):
    def t(self, result):
        q = set(words)
        missing = q - get_all_words(result)
        self.assertFalse(missing, f'Words missing. Command line: {self.current_cmd!r}')
    return t


def does_not_have_words(*words):
    def t(self, result):
        q = set(words)
        all_words = get_all_words(result)
        self.assertFalse(q & all_words, f'Words unexpectedly present. Command line: {self.current_cmd!r}')
    return t


def all_words(*words):
    def t(self, result):
        expected = set(words)
        actual = get_all_words(result)
        self.assertEqual(expected, actual, f'Command line: {self.current_cmd!r}')
    return t


def completion(self: TestCompletion, tdir: str):
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
        env = os.environ.copy()
        env['PATH'] = os.path.join(tdir, 'bin')
        env['HOME'] = os.path.join(tdir, 'sub')
        cp = subprocess.run(
            [kitty_tool(), '__complete__', 'json'],
            check=True, stdout=subprocess.PIPE, cwd=tdir, input=json.dumps(all_argv).encode(), env=env
        )
        self.assertEqual(cp.returncode, 0, f'kitty-tool __complete__ failed with exit code: {cp.returncode}')
        return json.loads(cp.stdout)

    add('kitty ', has_words('@', '@ls'))
    add('kitty @ l', has_words('ls', 'last-used-layout', 'launch'))
    add('kitty @l', has_words('@ls', '@last-used-layout', '@launch'))

    def make_file(path, mode=None):
        with open(os.path.join(tdir, path), mode='x') as f:
            if mode is not None:
                os.chmod(f.fileno(), mode)

    os.mkdir(os.path.join(tdir, 'bin'))
    os.mkdir(os.path.join(tdir, 'sub'))
    make_file('bin/exe1', 0o700)
    make_file('bin/exe-not1')
    make_file('exe2', 0o700)
    make_file('exe-not2.jpeg')
    make_file('sub/exe3', 0o700)
    make_file('sub/exe-not3.png')

    add('kitty x', all_words())
    add('kitty e', all_words('exe1'))
    add('kitty ./', all_words('./bin/', './sub/', './exe2'))
    add('kitty ./e', all_words('./exe2'))
    add('kitty ./s', all_words('./sub/'))
    add('kitty ~', all_words('~/exe3'))
    add('kitty ~/', all_words('~/exe3'))
    add('kitty ~/e', all_words('~/exe3'))

    add('kitty @ goto-layout ', has_words('tall', 'fat'))
    add('kitty @ goto-layout spli', all_words('splits'))
    add('kitty @ goto-layout f f', all_words())
    add('kitty @ set-window-logo ', all_words('exe-not2.jpeg', 'sub/'))
    add('kitty @ set-window-logo e', all_words('exe-not2.jpeg'))
    add('kitty @ set-window-logo e e', all_words())

    add('kitty -', has_words('-c', '-1', '--'), does_not_have_words('--config', '--single-instance'))
    add('kitty -c', all_words('-c'))
    add('kitty --', has_words('--config', '--single-instance', '--'))
    add('kitty --s', has_words('--session', '--start-as'))
    add('kitty --start-as', all_words('--start-as'))
    add('kitty --start-as ', all_words('minimized', 'maximized', 'fullscreen', 'normal'))
    add('kitty -1 ', does_not_have_words('@ls', '@'))
    add('kitty --directory ', all_words('bin/', 'sub/'))
    add('kitty -1d ', all_words('bin/', 'sub/'))

    for cmd, tests, result in zip(all_cmds, all_tests, run_tool()):
        self.current_cmd = cmd
        for test in tests:
            test(self, result)
