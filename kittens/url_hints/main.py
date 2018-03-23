#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import re
import string
import subprocess
import sys
from collections import namedtuple
from functools import lru_cache, partial
from gettext import gettext as _

from kitty.cli import parse_args
from kitty.key_encoding import ESCAPE, backspace_key, enter_key
from kitty.utils import command_for_open

from ..tui.handler import Handler
from ..tui.loop import Loop
from ..tui.operations import (
    clear_screen, faint, set_cursor_visible, set_window_title, styled
)

Mark = namedtuple('Mark', 'index start end text')
URL_PREFIXES = 'http https file ftp'.split()
HINT_ALPHABET = string.digits + string.ascii_lowercase


@lru_cache(maxsize=2048)
def encode_hint(num):
    res = ''
    d = len(HINT_ALPHABET)
    while not res or num > 0:
        num, i = divmod(num, d)
        res = HINT_ALPHABET[i] + res
    return res


def decode_hint(x):
    return int(x, 36)


def render(lines, current_input):
    ans = []

    def mark(m):
        hint = encode_hint(m.index)
        text = m.text
        if current_input and not hint.startswith(current_input):
            return faint(text)
        hint = hint[len(current_input):] or ' '
        text = text[len(hint):]
        return styled(
            hint,
            fg='black',
            bg='green',
            bold=True
        ) + styled(
            text, fg='gray', fg_intense=True, bold=True
        )

    for line, marks in lines:
        if not marks:
            ans.append(faint(line))
            continue
        buf = []

        for i, m in enumerate(marks):
            if i == 0 and m.start:
                buf.append(faint(line[:m.start]))
            buf.append(mark(m))
            if m is not marks[-1]:
                buf.append(faint(line[m.end:marks[i + 1].start]))

        rest = line[marks[-1].end:]
        if rest:
            buf.append(faint(rest))

        ans.append(''.join(buf))
    return '\r\n'.join(ans)


class URLHints(Handler):

    def __init__(self, lines, index_map):
        self.lines, self.index_map = tuple(lines), index_map
        self.current_input = ''
        self.current_text = None
        self.chosen = None

    def init_terminal_state(self):
        self.write(set_cursor_visible(False))
        self.write(set_window_title(_('Choose URL')))

    def initialize(self, *args):
        Handler.initialize(self, *args)
        self.init_terminal_state()
        self.draw_screen()

    def on_text(self, text, in_bracketed_paste):
        changed = False
        for c in text:
            if c in HINT_ALPHABET:
                self.current_input += c
                changed = True
        if changed:
            matches = [
                t for idx, t in self.index_map.items()
                if encode_hint(idx).startswith(self.current_input)
            ]
            if len(matches) == 1:
                self.chosen = matches[0]
                self.quit_loop(0)
                return
            self.current_text = None
            self.draw_screen()

    def on_key(self, key_event):
        if key_event is backspace_key:
            self.current_input = self.current_input[:-1]
            self.current_text = None
            self.draw_screen()
        elif key_event is enter_key and self.current_input:
            idx = decode_hint(self.current_input)
            self.chosen = self.index_map[idx]
            self.quit_loop(0)
        elif key_event.key is ESCAPE:
            self.quit_loop(1)

    def on_interrupt(self):
        self.quit_loop(1)

    def on_eot(self):
        self.quit_loop(1)

    def on_resize(self, new_size):
        Handler.on_resize(self, new_size)
        self.draw_screen()

    def draw_screen(self):
        if self.current_text is None:
            self.current_text = render(self.lines, self.current_input)
        self.write(clear_screen())
        self.write(self.current_text)


def regex_finditer(pat, line):
    for m in pat.finditer(line):
        s, e = m.span()
        if e - s > 2:
            yield s, e


def find_urls(pat, line):
    for m in pat.finditer(line):
        s, e = m.span()
        if s > 4 and line[s - 5:s] == 'link:':  # asciidoc URLs
            url = line[s:e]
            idx = url.rfind('[')
            if idx > -1:
                e -= len(url) - idx
        yield s, e


def mark(finditer, line, index_map):
    marks = []
    for s, e in finditer(line):
        idx = len(index_map)
        text = line[s:e]
        marks.append(Mark(idx, s, e, text))
        index_map[idx] = text
    return line, marks


def run_loop(args, lines, index_map):
    loop = Loop()
    handler = URLHints(lines, index_map)
    loop.loop(handler)
    if handler.chosen and loop.return_code == 0:
        cmd = command_for_open(args.program)
        ret = subprocess.Popen(cmd + [handler.chosen]).wait()
        if ret != 0:
            print('URL handler "{}" failed with return code: {}'.format(' '.join(cmd), ret), file=sys.stderr)
            input('Press Enter to quit')
            loop.return_code = ret
    raise SystemExit(loop.return_code)


def run(args, source_file=None):
    if source_file is None:
        text = sys.stdin.buffer.read().decode('utf-8')
        sys.stdin = open('/dev/tty')
    else:
        with open(source_file, 'r') as f:
            text = f.read()
    if args.regex is None:
        from .url_regex import url_delimiters
        url_pat = '(?:{})://[^{}]{{3,}}'.format(
            '|'.join(args.url_prefixes.split(',')), url_delimiters
        )
        finditer = partial(find_urls, re.compile(url_pat))
    else:
        finditer = partial(regex_finditer, re.compile(args.regex))
    lines = []
    index_map = {}
    for line in text.splitlines():
        marked = mark(finditer, line, index_map)
        lines.append(marked)
    if not index_map:
        input(_('No URLs found, press Enter to abort.'))
        return

    try:
        run_loop(args, lines, index_map)
    except Exception:
        import traceback
        traceback.print_exc()
        input(_('Press Enter to quit'))


OPTIONS = partial('''\
--program
default=default
What program to use to open matched URLs. Defaults
to the default URL open program for the operating system.


--regex
Instead of searching for URLs search for the specified regular
expression instead.


--url-prefixes
default={0}
Comma separated list of recognized URL prefixes. Defaults to:
{0}
'''.format, ','.join(sorted(URL_PREFIXES)))


def main(args=sys.argv):
    msg = 'Highlight URLs inside the specified text'
    try:
        args, items = parse_args(args[1:], OPTIONS, '[path to file or omit to use stdin]', msg, 'url_hints')
    except SystemExit as e:
        print(e.args[0], file=sys.stderr)
        input('Press enter to quit...')
        return 1
    run(args, (items or [None])[0])
