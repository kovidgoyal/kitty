#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import json
import os
import shlex
import subprocess
import tempfile

from kitty.constants import kitten_exe as kitten

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


def is_delegate(num_to_remove: int = 0, command: str = ''):
    q = {}
    if num_to_remove:
        q['num_to_remove'] = num_to_remove
    if command:
        q['command'] = command

    def t(self, result):
        d = result['delegate']
        self.assertEqual(d, q, f'Command line: {self.current_cmd!r}')
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
        env['KITTY_CONFIG_DIRECTORY'] = os.path.join(tdir, 'sub')
        cp = subprocess.run(
            [kitten(), '__complete__', 'json'],
            check=True, stdout=subprocess.PIPE, cwd=tdir, input=json.dumps(all_argv).encode(), env=env
        )
        self.assertEqual(cp.returncode, 0, f'kitten __complete__ failed with exit code: {cp.returncode}')
        return json.loads(cp.stdout)

    add('kitty ', has_words('@', '+', '+open'))
    add('kitty @ l', has_words('ls', 'last-used-layout', 'launch'))

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
    add('kitty e', all_words('exe1', 'exe2'))
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
    add('kitty +ope', has_words('+open'))
    add('kitty +open -', has_words('-1', '-T'))

    add('kitty -', has_words('-c', '-1', '--'), does_not_have_words('--config', '--single-instance'))
    add('kitty -c', all_words('-c'))
    add('kitty --', has_words('--config', '--single-instance', '--'))
    add('kitty --s', has_words('--session', '--start-as'))
    add('kitty --start-as', all_words('--start-as'))
    add('kitty --start-as ', all_words('minimized', 'maximized', 'fullscreen', 'normal', 'hidden'))
    add('kitty -1 ', does_not_have_words('@ls', '@'))
    add('kitty --directory ', all_words('bin/', 'sub/'))
    add('kitty -1d ', all_words('exe1'))
    add('kitty -1d', all_words('-1d'))
    add('kitty -o a', has_words('allow_remote_control='))
    add('kitty --listen-on ', all_words('unix:', 'tcp:'))
    add('kitty --listen-on unix:b', all_words('unix:bin/'))
    add('kitty --directory=', all_words('--directory=bin/', '--directory=sub/'))
    add('kitty --start-as=m', all_words('--start-as=minimized', '--start-as=maximized'))
    add('kitty @launch --ty', has_words('--type'))
    add('kitty @launch --type ', has_words('window', 'background', 'overlay'))
    add('kitty @launch --cwd ', has_words('current', 'oldest', 'last_reported'))
    add('kitty @launch --logo ', all_words('exe-not3.png'))
    add('kitty @launch --logo ~', all_words('~/exe-not3.png'))
    add('kitten ', has_words('@'))
    add('kitten ', does_not_have_words('__complete__'))
    add('kitten @launch --ty', has_words('--type'))

    add('kitty + ', has_words('launch', 'kitten'))
    add('kitty + kitten ', has_words('icat', 'diff'))
    add('kitty +kitten icat ', has_words('sub/', 'exe-not2.jpeg'))
    add('kitty + kitten icat --pr', has_words('--print-window-size'))
    add('kitty + kitten diff ', has_words('exe-not2.jpeg'))
    add('kitty + kitten themes --', has_words('--cache-age'))
    add('kitty + kitten themes D', has_words('Default'))
    add('kitty + kitten hyperlinked_grep ', is_delegate(3, 'rg'))
    add('kitty +kitten hyperlinked_grep ', is_delegate(2, 'rg'))

    add('clone-in-kitty --ty', has_words('--type'))

    add('kitty bash ', is_delegate(1, 'bash'))
    add('kitty -1 bash ', is_delegate(2, 'bash'))
    add('kitty -1 bash --n', is_delegate(2, 'bash'))
    add('kitty @launch --type tab bash --n', is_delegate(4, 'bash'))
    add('kitty +kitten hyperlinked_grep --s', is_delegate(2, 'rg'))
    add('kitty @launch e', all_words('exe1', 'exe2'))

    for cmd, tests, result in zip(all_cmds, all_tests, run_tool()):
        self.current_cmd = cmd
        for test in tests:
            test(self, result)
