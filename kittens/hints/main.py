#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import string
import sys
from functools import lru_cache
from gettext import gettext as _
from itertools import repeat

from kitty.cli import parse_args
from kitty.fast_data_types import set_clipboard_string
from kitty.key_encoding import ESCAPE, backspace_key, enter_key
from kitty.utils import screen_size_function

from ..tui.handler import Handler
from ..tui.loop import Loop
from ..tui.operations import faint, styled

URL_PREFIXES = 'http https file ftp'.split()
DEFAULT_HINT_ALPHABET = string.digits + string.ascii_lowercase
screen_size = screen_size_function()


class Mark:

    __slots__ = ('index', 'start', 'end', 'text')

    def __init__(self, index, start, end, text):
        self.index, self.start, self.end = index, start, end
        self.text = text


@lru_cache(maxsize=2048)
def encode_hint(num, alphabet):
    res = ''
    d = len(alphabet)
    while not res or num > 0:
        num, i = divmod(num, d)
        res = alphabet[i] + res
    return res


def decode_hint(x, alphabet=DEFAULT_HINT_ALPHABET):
    base = len(alphabet)
    index_map = {c: i for i, c in enumerate(alphabet)}
    i = 0
    for char in x:
        i = i * base + index_map[char]
    return i


def highlight_mark(m, text, current_input, alphabet):
    hint = encode_hint(m.index, alphabet)
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


def render(text, current_input, all_marks, ignore_mark_indices, alphabet):
    for mark in reversed(all_marks):
        if mark.index in ignore_mark_indices:
            continue
        mtext = highlight_mark(mark, text[mark.start:mark.end], current_input, alphabet)
        text = text[:mark.start] + mtext + text[mark.end:]

    text = text.replace('\0', '')

    return text.replace('\n', '\r\n').rstrip()


class Hints(Handler):

    def __init__(self, text, all_marks, index_map, args):
        self.text, self.index_map = text, index_map
        self.alphabet = args.alphabet or DEFAULT_HINT_ALPHABET
        self.all_marks = all_marks
        self.ignore_mark_indices = set()
        self.args = args
        self.window_title = _('Choose URL') if args.type == 'url' else _('Choose text')
        self.multiple = args.multiple
        self.match_suffix = self.get_match_suffix(args)
        self.chosen = []
        self.reset()

    def get_match_suffix(self, args):
        if args.add_trailing_space == 'always':
            return ' '
        if args.add_trailing_space == 'never':
            return ''
        return ' ' if args.multiple else ''

    def reset(self):
        self.current_input = ''
        self.current_text = None

    def init_terminal_state(self):
        self.cmd.set_cursor_visible(False)
        self.cmd.set_window_title(self.window_title)
        self.cmd.set_line_wrapping(False)

    def initialize(self):
        self.init_terminal_state()
        self.draw_screen()

    def on_text(self, text, in_bracketed_paste):
        changed = False
        for c in text:
            if c in self.alphabet:
                self.current_input += c
                changed = True
        if changed:
            matches = [
                m for idx, m in self.index_map.items()
                if encode_hint(idx, self.alphabet).startswith(self.current_input)
            ]
            if len(matches) == 1:
                self.chosen.append(matches[0].text + self.match_suffix)
                if self.multiple:
                    self.ignore_mark_indices.add(matches[0].index)
                    self.reset()
                else:
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
            try:
                idx = decode_hint(self.current_input, self.alphabet)
                self.chosen.append(self.index_map[idx].text + self.match_suffix)
                self.ignore_mark_indices.add(idx)
            except Exception:
                self.current_input = ''
                self.current_text = None
                self.draw_screen()
            else:
                if self.multiple:
                    self.reset()
                    self.draw_screen()
                else:
                    self.quit_loop(0)
        elif key_event.key is ESCAPE:
            self.quit_loop(0 if self.multiple else 1)

    def on_interrupt(self):
        self.quit_loop(1)

    def on_eot(self):
        self.quit_loop(1)

    def on_resize(self, new_size):
        self.draw_screen()

    def draw_screen(self):
        if self.current_text is None:
            self.current_text = render(self.text, self.current_input, self.all_marks, self.ignore_mark_indices, self.alphabet)
        self.cmd.clear_screen()
        self.write(self.current_text)


def regex_finditer(pat, minimum_match_length, text):
    for m in pat.finditer(text):
        s, e = m.span(pat.groups)
        while e > s + 1 and text[e-1] == '\0':
            e -= 1
        if e - s >= minimum_match_length:
            yield s, e


closing_bracket_map = {'(': ')', '[': ']', '{': '}', '<': '>', '*': '*', '"': '"', "'": "'"}
opening_brackets = ''.join(closing_bracket_map)
postprocessor_map = {}


def postprocessor(func):
    postprocessor_map[func.__name__] = func
    return func


@postprocessor
def url(text, s, e):
    if s > 4 and text[s - 5:s] == 'link:':  # asciidoc URLs
        url = text[s:e]
        idx = url.rfind('[')
        if idx > -1:
            e -= len(url) - idx
    while text[e - 1] in '.,?!' and e > 1:  # remove trailing punctuation
        e -= 1
    # truncate url at closing bracket/quote
    if s > 0 and e <= len(text) and text[s-1] in opening_brackets:
        q = closing_bracket_map[text[s-1]]
        idx = text.find(q, s)
        if idx > s:
            e = idx
    # Restructured Text URLs
    if e > 3 and text[e-2:e] == '`_':
        e -= 2

    return s, e


@postprocessor
def brackets(text, s, e):
    # Remove matching brackets
    if s < e <= len(text):
        before = text[s]
        if before in '({[<' and text[e-1] == closing_bracket_map[before]:
            s += 1
            e -= 1
    return s, e


@postprocessor
def quotes(text, s, e):
    # Remove matching quotes
    if s < e <= len(text):
        before = text[s]
        if before in '\'"' and text[e-1] == before:
            s += 1
            e -= 1
    return s, e


def mark(pattern, post_processors, text, args):
    pat = re.compile(pattern)
    for idx, (s, e) in enumerate(regex_finditer(pat, args.minimum_match_length, text)):
        for func in post_processors:
            s, e = func(text, s, e)
        mark_text = text[s:e].replace('\n', '').replace('\0', '')
        yield Mark(idx, s, e, mark_text)


def run_loop(args, text, all_marks, index_map):
    loop = Loop()
    handler = Hints(text, all_marks, index_map, args)
    loop.loop(handler)
    if handler.chosen and loop.return_code == 0:
        return {'match': handler.chosen, 'programs': args.program,
                'multiple_joiner': args.multiple_joiner,
                'type': args.type}
    raise SystemExit(loop.return_code)


def escape(chars):
    return chars.replace('\\', '\\\\').replace('-', r'\-').replace(']', r'\]')


def functions_for(args):
    post_processors = []
    if args.type == 'url':
        from .url_regex import url_delimiters
        pattern = '(?:{})://[^{}]{{3,}}'.format(
            '|'.join(args.url_prefixes.split(',')), url_delimiters
        )
        post_processors.append(url)
    elif args.type == 'path':
        pattern = r'(?:\S*/\S+)|(?:\S+[.][a-zA-Z0-9]{2,7})'
        post_processors.extend((brackets, quotes))
    elif args.type == 'line':
        pattern = '(?m)^\\s*(.+)[\\s\0]*$'
    elif args.type == 'hash':
        pattern = '[0-9a-f]{7,128}'
    elif args.type == 'word':
        chars = args.word_characters
        if chars is None:
            import json
            chars = json.loads(os.environ['KITTY_COMMON_OPTS'])['select_by_word_characters']
        pattern = r'(?u)[{}\w]{{{},}}'.format(escape(chars), args.minimum_match_length)
        post_processors.extend((brackets, quotes))
    else:
        pattern = args.regex
    return pattern, post_processors


def convert_text(text, cols):
    lines = []
    empty_line = '\0' * cols
    for full_line in text.split('\n'):
        if full_line:
            if not full_line.rstrip('\r'):  # empty lines
                lines.extend(repeat(empty_line, len(full_line)))
                continue
            for line in full_line.split('\r'):
                if line:
                    lines.append(line.ljust(cols, '\0'))
    return '\n'.join(lines)


def parse_input(text):
    try:
        cols = int(os.environ['OVERLAID_WINDOW_COLS'])
    except KeyError:
        cols = screen_size().cols
    return convert_text(text, cols)


def run(args, text):
    try:
        pattern, post_processors = functions_for(args)
        text = parse_input(text)
        all_marks = tuple(mark(pattern, post_processors, text, args))
        if not all_marks:
            input(_('No {} found, press Enter to quit.').format(
                'URLs' if args.type == 'url' else 'matches'
                ))
            return

        largest_index = all_marks[-1].index
        offset = max(0, args.hints_offset)
        for m in all_marks:
            m.index = largest_index - m.index + offset
        index_map = {m.index: m for m in all_marks}
    except Exception:
        import traceback
        traceback.print_exc()
        input('Press Enter to quit.')
        raise SystemExit(1)

    return run_loop(args, text, all_marks, index_map)


# CLI {{{
OPTIONS = r'''
--program
type=list
What program to use to open matched text. Defaults to the default open program
for the operating system. Use a value of :file:`-` to paste the match into the
terminal window instead. A value of :file:`@` will copy the match to the clipboard.
A value of :file:`default` will run the default open program. Can be specified
multiple times to run multiple programs.


--type
default=url
choices=url,regex,path,line,hash,word
The type of text to search for.


--regex
default=(?m)^\s*(.+)\s*$
The regular expression to use when :option:`kitty +kitten hints --type`=regex.
The regular expression is in python syntax. If you specify a group in
the regular expression only the group will be matched. This allow you to match
text ignoring a prefix/suffix, as needed. The default expression matches lines.
To match text over multiple lines you should prefix the regular expression with
:code:`(?ms)`, which turns on MULTILINE and DOTALL modes for the regex engine.


--url-prefixes
default={0}
Comma separated list of recognized URL prefixes.


--word-characters
Characters to consider as part of a word. In addition, all characters marked as
alphanumeric in the unicode database will be considered as word characters.
Defaults to the select_by_word_characters setting from kitty.conf.


--minimum-match-length
default=3
type=int
The minimum number of characters to consider a match.


--multiple
type=bool-set
Select multiple matches and perform the action on all of them together at the end.
In this mode, press :kbd:`Esc` to finish selecting.


--multiple-joiner
default=auto
String to use to join multiple selections when copying to the clipboard or
inserting into the terminal. The special strings: "space", "newline", "empty",
"json" and "auto" are interpreted as a space character, a newline an empty
joiner, a JSON serialized list and an automatic choice, based on the type of
text being selected. In addition, integers are interpreted as zero-based
indices into the list of selections. You can use 0 for the first selection and
-1 for the last.


--add-trailing-space
default=auto
choices=auto,always,never
Add trailing space after matched text. Defaults to auto, which adds the space
when used together with --multiple.


--hints-offset
default=1
type=int
The offset (from zero) at which to start hint numbering. Note that only numbers
greater than or equal to zero are respected.


--alphabet
The list of characters to use for hints. The default is to use numbers and lowercase
English alphabets. Specify your preference as a string of characters. Note that
unless you specify the hints offset as zero the first match will be highlighted with
the second character you specify.


'''.format(','.join(sorted(URL_PREFIXES))).format
help_text = 'Select text from the screen using the keyboard. Defaults to searching for URLs.'
usage = ''


def parse_hints_args(args):
    return parse_args(args, OPTIONS, usage, help_text, 'kitty +kitten hints')


def main(args):
    text = ''
    if sys.stdin.isatty():
        if '--help' not in args and '-h' not in args:
            print('You must pass the text to be hinted on STDIN', file=sys.stderr)
            input(_('Press Enter to quit'))
            return
    else:
        text = sys.stdin.buffer.read().decode('utf-8')
        sys.stdin = open(os.ctermid())
    try:
        args, items = parse_hints_args(args[1:])
    except SystemExit as e:
        if e.code != 0:
            print(e.args[0], file=sys.stderr)
            input(_('Press Enter to quit'))
        return
    if items:
        print('Extra command line arguments present: {}'.format(' '.join(items)), file=sys.stderr)
        input(_('Press Enter to quit'))
    return run(args, text)


def handle_result(args, data, target_window_id, boss):
    programs = data['programs'] or ('default',)
    matches = tuple(filter(None, data['match']))
    joiner = data['multiple_joiner']
    try:
        is_int = int(joiner)
    except Exception:
        is_int = None
    text_type = data['type']

    @lru_cache()
    def joined_text():
        if is_int is not None:
            try:
                return matches[is_int]
            except IndexError:
                return matches[-1]
        if joiner == 'json':
            import json
            return json.dumps(matches, ensure_ascii=False, indent='\t')
        if joiner == 'auto':
            q = '\n\r' if text_type in ('line', 'url') else ' '
        else:
            q = {'newline': '\n\r', 'space': ' '}.get(joiner, '')
        return q.join(matches)

    for program in programs:
        if program == '-':
            w = boss.window_id_map.get(target_window_id)
            if w is not None:
                w.paste(joined_text())
        elif program == '@':
            set_clipboard_string(joined_text())
        else:
            cwd = None
            w = boss.window_id_map.get(target_window_id)
            if w is not None:
                cwd = w.cwd_of_child
            program = None if program == 'default' else program
            for m in matches:
                boss.open_url(m, program, cwd=cwd)


handle_result.type_of_input = 'screen'


if __name__ == '__main__':
    # Run with kitty +kitten hints
    ans = main(sys.argv)
    if ans:
        print(ans)
elif __name__ == '__doc__':
    sys.cli_docs['usage'] = usage
    sys.cli_docs['options'] = OPTIONS
    sys.cli_docs['help_text'] = help_text
# }}}
