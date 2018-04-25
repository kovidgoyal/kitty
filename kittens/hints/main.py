#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import string
import sys
from functools import lru_cache, partial
from gettext import gettext as _

from kitty.cli import parse_args
from kitty.fast_data_types import set_clipboard_string
from kitty.key_encoding import ESCAPE, backspace_key, enter_key

from ..tui.handler import Handler
from ..tui.loop import Loop
from ..tui.operations import (
    clear_screen, faint, set_cursor_visible, set_window_title, styled
)

URL_PREFIXES = 'http https file ftp'.split()
HINT_ALPHABET = string.digits + string.ascii_lowercase


class Mark(object):

    __slots__ = ('index', 'start', 'end', 'text')

    def __init__(self, index, start, end, text):
        self.index, self.start, self.end = index, start, end
        self.text = text


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


class Hints(Handler):

    def __init__(self, lines, index_map, args):
        self.lines, self.index_map = tuple(lines), index_map
        self.current_input = ''
        self.current_text = None
        self.args = args
        self.window_title = _('Choose URL') if args.type == 'url' else _('Choose text')
        self.chosen = None

    def init_terminal_state(self):
        self.write(set_cursor_visible(False))
        self.write(set_window_title(self.window_title))

    def initialize(self):
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
                m.text for idx, m in self.index_map.items()
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
            self.chosen = self.index_map[idx].text
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


def regex_finditer(pat, minimum_match_length, line):
    for m in pat.finditer(line):
        s, e = m.span(pat.groups)
        if e - s >= minimum_match_length:
            yield s, e


closing_bracket_map = {'(': ')', '[': ']', '{': '}', '<': '>'}


def find_urls(pat, line):
    for m in pat.finditer(line):
        s, e = m.span()
        if s > 4 and line[s - 5:s] == 'link:':  # asciidoc URLs
            url = line[s:e]
            idx = url.rfind('[')
            if idx > -1:
                e -= len(url) - idx
        while line[e - 1] in '.,?!' and e > 1:  # remove trailing punctuation
            e -= 1
        # Detect a bracketed URL
        if s > 0 and e > s + 4 and line[s-1] in '({[<' and line[e-1] == closing_bracket_map[line[s-1]]:
            e -= 1
        yield s, e


def mark(finditer, line, all_marks):
    marks = []
    for s, e in finditer(line):
        idx = len(all_marks)
        text = line[s:e]
        marks.append(Mark(idx, s, e, text))
        all_marks.append(marks[-1])
    return line, marks


def run_loop(args, lines, index_map):
    loop = Loop()
    handler = Hints(lines, index_map, args)
    loop.loop(handler)
    if handler.chosen and loop.return_code == 0:
        return {'match': handler.chosen, 'program': args.program}
    raise SystemExit(loop.return_code)


def escape(chars):
    return chars.replace('\\', '\\\\').replace('-', r'\-').replace(']', r'\]')


def run(args, text):
    if args.type == 'url':
        from .url_regex import url_delimiters
        url_pat = '(?:{})://[^{}]{{3,}}'.format(
            '|'.join(args.url_prefixes.split(',')), url_delimiters
        )
        finditer = partial(find_urls, re.compile(url_pat))
    elif args.type == 'path':
        finditer = partial(regex_finditer, re.compile(r'(?:\S*/\S+)|(?:\S+[.][a-zA-Z0-9]{2,5})'), args.minimum_match_length)
    elif args.type == 'line':
        finditer = partial(regex_finditer, re.compile(r'(?m)^\s*(.+)\s*$'), args.minimum_match_length)
    elif args.type == 'word':
        chars = args.word_characters
        if chars is None:
            import json
            chars = json.loads(os.environ['KITTY_COMMON_OPTS'])['select_by_word_characters']
        pat = re.compile(r'(?u)[{}\w]{{{},}}'.format(escape(chars), args.minimum_match_length))
        finditer = partial(regex_finditer, pat, args.minimum_match_length)
    else:
        finditer = partial(regex_finditer, re.compile(args.regex), args.minimum_match_length)
    lines = []
    all_marks = []
    for line in text.splitlines():
        marked = mark(finditer, line, all_marks)
        lines.append(marked)
    if not all_marks:
        input(_('No {} found, press Enter to abort.').format(
            'URLs' if args.type == 'url' else 'matches'
            ))
        return

    largest_index = all_marks[-1].index
    for m in all_marks:
        m.index = largest_index - m.index
    index_map = {m.index: m for m in all_marks}

    return run_loop(args, lines, index_map)


OPTIONS = partial(r'''
--program
default=default
What program to use to open matched text. Defaults to the default open program
for the operating system.  Use a value of - to paste the match into the
terminal window instead. A value of @ will copy the match to the clipboard.


--type
default=url
choices=url,regex,path,line,word
The type of text to search for.


--regex
default=(?m)^\s*(.+)\s*$
The regular expression to use when --type=regex.  If you specify a group in the
regular expression only the group will be matched. This allow you to match text
ignoring a prefix/suffix, as needed. The default expression matches lines.


--url-prefixes
default={0}
Comma separated list of recognized URL prefixes.


--word-characters
Characters to consider as part of a word. In addition, all characters marked as
alpha-numeric in the unicode database will be considered as word characters.
Defaults to the select_by_word_characters setting from kitty.conf.


--minimum-match-length
default=3
type=int
The minimum number of characters to consider a match.
'''.format, ','.join(sorted(URL_PREFIXES)))


def main(args):
    msg = 'Select text from the screen using the keyboard. Defaults to searching for URLs.'
    text = ''
    if sys.stdin.isatty():
        if '--help' not in args and '-h' not in args:
            print('You must pass the text to be hinted on STDIN', file=sys.stderr)
            input(_('Press Enter to quit'))
            return
    else:
        text = sys.stdin.buffer.read().decode('utf-8')
        sys.stdin = open('/dev/tty')
    try:
        args, items = parse_args(args[1:], OPTIONS, '', msg, 'hints')
    except SystemExit as e:
        if e.code != 0:
            print(e.args[0], file=sys.stderr)
            input(_('Press Enter to quit'))
        return
    if items:
        print('Extra command line arguments present: {}'.format(' '.join(items)), file=sys.stderr)
        input(_('Press Enter to quit'))
        return
    return run(args, text)


def handle_result(args, data, target_window_id, boss):
    program = data['program']
    if program == '-':
        w = boss.window_id_map.get(target_window_id)
        if w is not None:
            w.paste(data['match'])
    elif program == '@':
        set_clipboard_string(data['match'])
    else:
        cwd = None
        w = boss.window_id_map.get(target_window_id)
        if w is not None:
            cwd = w.cwd_of_child
        boss.open_url(data['match'], None if program == 'default' else program, cwd=cwd)


if __name__ == '__main__':
    # Run with kitty +kitten hints
    ans = main(sys.argv)
    if ans:
        print(ans)
