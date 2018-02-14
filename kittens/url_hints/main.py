#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import re
import string
import sys
from collections import namedtuple
from functools import lru_cache, partial
from gettext import gettext as _

from kitty.key_encoding import ESCAPE, backspace_key, enter_key
from kitty.utils import read_with_timeout

from ..tui.handler import Handler
from ..tui.loop import Loop
from ..tui.operations import clear_screen, colored, set_window_title, styled

Mark = namedtuple('Mark', 'index start end text')
URL_PREFIXES = 'http https file ftp'.split()
HINT_ALPHABET = string.digits + string.ascii_lowercase
FAINT = 242


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

    def faint(text):
        return colored(text, FAINT)

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
            fg_intense=True,
            bg='green',
            bg_intense=True,
            bold=True
        ) + styled(
            text, fg='gray', fg_intense=True, bold=True
        )

    for line, marks in lines:
        if not marks:
            ans.append(faint(line))
            continue
        buf = []
        if marks[0].start:
            buf.append(faint(line[:marks[0].start]))

        for i, m in enumerate(marks):
            if m is not marks[-1]:
                buf.append(faint(line[m.end:marks[i + 1].start]))
            buf.append(mark(m))

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


def read_from_stdin():
    buf = []

    def more_needed(data):
        idx = data.find(b'\x1c')
        if idx == -1:
            buf.append(data)
            return True
        buf.append(data[:idx])
        return False

    read_with_timeout(more_needed)
    return b''.join(buf).decode('utf-8')


def regex_finditer(pat, line):
    for m in pat.finditer(line):
        yield m.start(), m.end()


def find_urls(pat, line):
    for m in pat.finditer(line):
        s, e = m.start(), m.end()
        url = line[s:e]
        if s > 4 and line[s - 5:s] == 'link:':  # asciidoc URLs
            idx = url.rfind('[')
            if idx > -1:
                e = idx
        yield s, e


def mark(finditer, line, index_map):
    marks = []
    for s, e in finditer(line):
        idx = len(index_map)
        text = line[s:e]
        marks.append(Mark(idx, s, e, text))
        index_map[idx] = text
    return line, marks


def run(source_file=None, regex=None, opener=None):
    if source_file is None:
        text = read_from_stdin()
    else:
        with open(source_file, 'r') as f:
            text = f.read()
    if regex is None:
        finditer = partial(regex_finditer, re.compile(regex))
    else:
        from .url_regex import url_delimiters
        url_pat = '(?:{})://[^{}]{3,}'.format(
            '|'.join(URL_PREFIXES), url_delimiters
        )
        finditer = partial(find_urls, url_pat)
    lines = []
    index_map = {}
    for line in text.splitlines():
        marked = mark(finditer, line, index_map)
        lines.append(marked)

    loop = Loop()
    handler = URLHints(lines, index_map)
    loop.loop(handler)
    raise SystemExit(loop.return_code)


def main(args=sys.argv):
    pass


if __name__ == '__main__':
    main()
