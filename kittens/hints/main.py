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
from typing import (
    Any, Callable, Dict, Generator, Iterable, List, Optional, Pattern,
    Sequence, Set, Tuple, Type, cast
)

from kitty.cli import parse_args
from kitty.cli_stub import HintsCLIOptions
from kitty.fast_data_types import set_clipboard_string
from kitty.key_encoding import KeyEvent
from kitty.typing import BossType, KittyCommonOpts
from kitty.utils import ScreenSize, screen_size_function, set_primary_selection

from ..tui.handler import Handler, result_handler
from ..tui.loop import Loop
from ..tui.operations import faint, styled


@lru_cache()
def kitty_common_opts() -> KittyCommonOpts:
    import json
    v = os.environ.get('KITTY_COMMON_OPTS')
    if v:
        return cast(KittyCommonOpts, json.loads(v))
    from kitty.config import common_opts_as_dict
    return common_opts_as_dict()


DEFAULT_HINT_ALPHABET = string.digits + string.ascii_lowercase
DEFAULT_REGEX = r'(?m)^\s*(.+)\s*$'


class Mark:

    __slots__ = ('index', 'start', 'end', 'text', 'is_hyperlink', 'group_id', 'groupdict')

    def __init__(
            self,
            index: int, start: int, end: int,
            text: str,
            groupdict: Any,
            is_hyperlink: bool = False,
            group_id: Optional[str] = None
    ):
        self.index, self.start, self.end = index, start, end
        self.text = text
        self.groupdict = groupdict
        self.is_hyperlink = is_hyperlink
        self.group_id = group_id


@lru_cache(maxsize=2048)
def encode_hint(num: int, alphabet: str) -> str:
    res = ''
    d = len(alphabet)
    while not res or num > 0:
        num, i = divmod(num, d)
        res = alphabet[i] + res
    return res


def decode_hint(x: str, alphabet: str = DEFAULT_HINT_ALPHABET) -> int:
    base = len(alphabet)
    index_map = {c: i for i, c in enumerate(alphabet)}
    i = 0
    for char in x:
        i = i * base + index_map[char]
    return i


def highlight_mark(m: Mark, text: str, current_input: str, alphabet: str, colors: Dict[str, str]) -> str:
    hint = encode_hint(m.index, alphabet)
    if current_input and not hint.startswith(current_input):
        return faint(text)
    hint = hint[len(current_input):] or ' '
    text = text[len(hint):]
    return styled(
        hint,
        fg=colors['foreground'],
        bg=colors['background'],
        bold=True
    ) + styled(
        text, fg=colors['text'], fg_intense=True, bold=True
    )


def render(text: str, current_input: str, all_marks: Sequence[Mark], ignore_mark_indices: Set[int], alphabet: str, colors: Dict[str, str]) -> str:
    for mark in reversed(all_marks):
        if mark.index in ignore_mark_indices:
            continue
        mtext = highlight_mark(mark, text[mark.start:mark.end], current_input, alphabet, colors)
        text = text[:mark.start] + mtext + text[mark.end:]

    text = text.replace('\0', '')

    return text.replace('\n', '\r\n').rstrip()


class Hints(Handler):

    def __init__(self, text: str, all_marks: Sequence[Mark], index_map: Dict[int, Mark], args: HintsCLIOptions):
        self.text, self.index_map = text, index_map
        self.alphabet = args.alphabet or DEFAULT_HINT_ALPHABET
        self.colors = {'foreground': args.hints_foreground_color,
                       'background': args.hints_background_color,
                       'text': args.hints_text_color}
        self.all_marks = all_marks
        self.ignore_mark_indices: Set[int] = set()
        self.args = args
        self.window_title = args.window_title or (_('Choose URL') if args.type == 'url' else _('Choose text'))
        self.multiple = args.multiple
        self.match_suffix = self.get_match_suffix(args)
        self.chosen: List[Mark] = []
        self.reset()

    @property
    def text_matches(self) -> List[str]:
        return [m.text + self.match_suffix for m in self.chosen]

    @property
    def groupdicts(self) -> List[Any]:
        return [m.groupdict for m in self.chosen]

    def get_match_suffix(self, args: HintsCLIOptions) -> str:
        if args.add_trailing_space == 'always':
            return ' '
        if args.add_trailing_space == 'never':
            return ''
        return ' ' if args.multiple else ''

    def reset(self) -> None:
        self.current_input = ''
        self.current_text: Optional[str] = None

    def init_terminal_state(self) -> None:
        self.cmd.set_cursor_visible(False)
        self.cmd.set_window_title(self.window_title)
        self.cmd.set_line_wrapping(False)

    def initialize(self) -> None:
        self.init_terminal_state()
        self.draw_screen()

    def on_text(self, text: str, in_bracketed_paste: bool = False) -> None:
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
                self.chosen.append(matches[0])
                if self.multiple:
                    self.ignore_mark_indices.add(matches[0].index)
                    self.reset()
                else:
                    self.quit_loop(0)
                    return
            self.current_text = None
            self.draw_screen()

    def on_key(self, key_event: KeyEvent) -> None:
        if key_event.matches('backspace'):
            self.current_input = self.current_input[:-1]
            self.current_text = None
            self.draw_screen()
        elif key_event.matches('enter') and self.current_input:
            try:
                idx = decode_hint(self.current_input, self.alphabet)
                self.chosen.append(self.index_map[idx])
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
        elif key_event.matches('esc'):
            self.quit_loop(0 if self.multiple else 1)

    def on_interrupt(self) -> None:
        self.quit_loop(1)

    def on_eot(self) -> None:
        self.quit_loop(1)

    def on_resize(self, new_size: ScreenSize) -> None:
        self.draw_screen()

    def draw_screen(self) -> None:
        if self.current_text is None:
            self.current_text = render(self.text, self.current_input, self.all_marks, self.ignore_mark_indices, self.alphabet, self.colors)
        self.cmd.clear_screen()
        self.write(self.current_text)


def regex_finditer(pat: Pattern, minimum_match_length: int, text: str) -> Generator[Tuple[int, int, Dict], None, None]:
    has_named_groups = bool(pat.groupindex)
    for m in pat.finditer(text):
        s, e = m.span(0 if has_named_groups else pat.groups)
        while e > s + 1 and text[e-1] == '\0':
            e -= 1
        if e - s >= minimum_match_length:
            yield s, e, m.groupdict()


closing_bracket_map = {'(': ')', '[': ']', '{': '}', '<': '>', '*': '*', '"': '"', "'": "'"}
opening_brackets = ''.join(closing_bracket_map)
PostprocessorFunc = Callable[[str, int, int], Tuple[int, int]]
postprocessor_map: Dict[str, PostprocessorFunc] = {}


def postprocessor(func: PostprocessorFunc) -> PostprocessorFunc:
    postprocessor_map[func.__name__] = func
    return func


class InvalidMatch(Exception):
    """Raised when a match turns out to be invalid."""
    pass


@postprocessor
def url(text: str, s: int, e: int) -> Tuple[int, int]:
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
def brackets(text: str, s: int, e: int) -> Tuple[int, int]:
    # Remove matching brackets
    if s < e <= len(text):
        before = text[s]
        if before in '({[<' and text[e-1] == closing_bracket_map[before]:
            s += 1
            e -= 1
    return s, e


@postprocessor
def quotes(text: str, s: int, e: int) -> Tuple[int, int]:
    # Remove matching quotes
    if s < e <= len(text):
        before = text[s]
        if before in '\'"' and text[e-1] == before:
            s += 1
            e -= 1
    return s, e


@postprocessor
def ip(text: str, s: int, e: int) -> Tuple[int, int]:
    from ipaddress import ip_address

    # Check validity of IPs (or raise InvalidMatch)
    ip = text[s:e]

    try:
        ip_address(ip)
    except Exception:
        raise InvalidMatch("Invalid IP")

    return s, e


def mark(pattern: str, post_processors: Iterable[PostprocessorFunc], text: str, args: HintsCLIOptions) -> Generator[Mark, None, None]:
    pat = re.compile(pattern)
    for idx, (s, e, groupdict) in enumerate(regex_finditer(pat, args.minimum_match_length, text)):
        try:
            for func in post_processors:
                s, e = func(text, s, e)
        except InvalidMatch:
            continue

        mark_text = text[s:e].replace('\n', '').replace('\0', '')
        yield Mark(idx, s, e, mark_text, groupdict)


def run_loop(args: HintsCLIOptions, text: str, all_marks: Sequence[Mark], index_map: Dict[int, Mark], extra_cli_args: Sequence[str] = ()) -> Dict[str, Any]:
    loop = Loop()
    handler = Hints(text, all_marks, index_map, args)
    loop.loop(handler)
    if handler.chosen and loop.return_code == 0:
        return {
            'match': handler.text_matches, 'programs': args.program,
            'multiple_joiner': args.multiple_joiner, 'customize_processing': args.customize_processing,
            'type': args.type, 'groupdicts': handler.groupdicts, 'extra_cli_args': extra_cli_args,
            'linenum_action': args.linenum_action,
            'cwd': os.getcwd(),
        }
    raise SystemExit(loop.return_code)


def escape(chars: str) -> str:
    return chars.replace('\\', '\\\\').replace('-', r'\-').replace(']', r'\]')


def functions_for(args: HintsCLIOptions) -> Tuple[str, List[PostprocessorFunc]]:
    post_processors = []
    if args.type == 'url':
        if args.url_prefixes == 'default':
            url_prefixes = kitty_common_opts()['url_prefixes']
        else:
            url_prefixes = tuple(args.url_prefixes.split(','))
        from .url_regex import url_delimiters
        pattern = '(?:{})://[^{}]{{3,}}'.format(
            '|'.join(url_prefixes), url_delimiters
        )
        post_processors.append(url)
    elif args.type == 'path':
        pattern = r'(?:\S*/\S+)|(?:\S+[.][a-zA-Z0-9]{2,7})'
        post_processors.extend((brackets, quotes))
    elif args.type == 'line':
        pattern = '(?m)^\\s*(.+)[\\s\0]*$'
    elif args.type == 'hash':
        pattern = '[0-9a-f]{7,128}'
    elif args.type == 'ip':
        pattern = (
            # # IPv4 with no validation
            r"((?:\d{1,3}\.){3}\d{1,3}"
            r"|"
            # # IPv6 with no validation
            r"(?:[a-fA-F0-9]{0,4}:){2,7}[a-fA-F0-9]{1,4})"
        )
        post_processors.append(ip)
    elif args.type == 'word':
        chars = args.word_characters
        if chars is None:
            chars = kitty_common_opts()['select_by_word_characters']
        pattern = r'(?u)[{}\w]{{{},}}'.format(escape(chars), args.minimum_match_length)
        post_processors.extend((brackets, quotes))
    else:
        pattern = args.regex
    return pattern, post_processors


def convert_text(text: str, cols: int) -> str:
    lines: List[str] = []
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


def parse_input(text: str) -> str:
    try:
        cols = int(os.environ['OVERLAID_WINDOW_COLS'])
    except KeyError:
        cols = screen_size_function()().cols
    return convert_text(text, cols)


def linenum_marks(text: str, args: HintsCLIOptions, Mark: Type[Mark], extra_cli_args: Sequence[str], *a: Any) -> Generator[Mark, None, None]:
    regex = args.regex
    if regex == DEFAULT_REGEX:
        regex = r'(?P<path>(?:\S*/\S+?)|(?:\S+[.][a-zA-Z0-9]{2,7})):(?P<line>\d+)'
    yield from mark(regex, [brackets, quotes], text, args)


def load_custom_processor(customize_processing: str) -> Any:
    if customize_processing.startswith('::import::'):
        import importlib
        m = importlib.import_module(customize_processing[len('::import::'):])
        return {k: getattr(m, k) for k in dir(m)}
    if customize_processing == '::linenum::':
        return {'mark': linenum_marks, 'handle_result': linenum_handle_result}
    from kitty.constants import resolve_custom_file
    custom_path = resolve_custom_file(customize_processing)
    import runpy
    return runpy.run_path(custom_path, run_name='__main__')


def remove_sgr(text: str) -> str:
    return re.sub(r'\x1b\[.*?m', '', text)


def process_hyperlinks(text: str) -> Tuple[str, Tuple[Mark, ...]]:
    hyperlinks: List[Mark] = []
    removed_size = idx = 0
    active_hyperlink_url: Optional[str] = None
    active_hyperlink_id: Optional[str] = None
    active_hyperlink_start_offset = 0

    def add_hyperlink(end: int) -> None:
        nonlocal idx, active_hyperlink_url, active_hyperlink_id, active_hyperlink_start_offset
        assert active_hyperlink_url is not None
        hyperlinks.append(Mark(
            idx, active_hyperlink_start_offset, end,
            active_hyperlink_url,
            groupdict={},
            is_hyperlink=True, group_id=active_hyperlink_id
        ))
        active_hyperlink_url = active_hyperlink_id = None
        active_hyperlink_start_offset = 0
        idx += 1

    def process_hyperlink(m: 're.Match') -> str:
        nonlocal removed_size, active_hyperlink_url, active_hyperlink_id, active_hyperlink_start_offset
        raw = m.group()
        start = m.start() - removed_size
        removed_size += len(raw)
        if active_hyperlink_url is not None:
            add_hyperlink(start)
        raw = raw[4:-2]
        parts = raw.split(';', 1)
        if len(parts) == 2 and parts[1]:
            active_hyperlink_url = parts[1]
            active_hyperlink_start_offset = start
            if parts[0]:
                for entry in parts[0].split(':'):
                    if entry.startswith('id=') and len(entry) > 3:
                        active_hyperlink_id = entry[3:]
                        break

        return ''

    text = re.sub(r'\x1b\]8.+?\x1b\\', process_hyperlink, text)
    if active_hyperlink_url is not None:
        add_hyperlink(len(text))
    return text, tuple(hyperlinks)


def run(args: HintsCLIOptions, text: str, extra_cli_args: Sequence[str] = ()) -> Optional[Dict[str, Any]]:
    try:
        text = parse_input(remove_sgr(text))
        text, hyperlinks = process_hyperlinks(text)
        pattern, post_processors = functions_for(args)
        if args.type == 'linenum':
            args.customize_processing = '::linenum::'
        if args.type == 'hyperlink':
            all_marks = hyperlinks
        elif args.customize_processing:
            m = load_custom_processor(args.customize_processing)
            if 'mark' in m:
                all_marks = tuple(m['mark'](text, args, Mark, extra_cli_args))
            else:
                all_marks = tuple(mark(pattern, post_processors, text, args))
        else:
            all_marks = tuple(mark(pattern, post_processors, text, args))
        if not all_marks:
            none_of = {'url': 'URLs', 'hyperlink': 'hyperlinks'}.get(args.type, 'matches')
            input(_('No {} found, press Enter to quit.').format(none_of))
            return None

        largest_index = all_marks[-1].index
        offset = max(0, args.hints_offset)
        for m in all_marks:
            if args.ascending:
                m.index += offset
            else:
                m.index = largest_index - m.index + offset
        index_map = {m.index: m for m in all_marks}
    except Exception:
        import traceback
        traceback.print_exc()
        input('Press Enter to quit.')
        raise SystemExit(1)

    return run_loop(args, text, all_marks, index_map, extra_cli_args)


# CLI {{{
OPTIONS = r'''
--program
type=list
What program to use to open matched text. Defaults to the default open program
for the operating system. Use a value of :file:`-` to paste the match into the
terminal window instead. A value of :file:`@` will copy the match to the
clipboard. A value of :file:`*` will copy the match to the primary selection
(on systems that support primary selections). A value of :file:`default` will
run the default open program. Can be specified multiple times to run multiple
programs.


--type
default=url
choices=url,regex,path,line,hash,word,linenum,hyperlink,ip
The type of text to search for. A value of :code:`linenum` is special, it looks
for error messages using the pattern specified with :option:`--regex`, which
must have the named groups, :code:`path` and :code:`line`. If not specified,
will look for :code:`path:line`. The :option:`--linenum-action` option
controls where to display the selected error message, other options are ignored.


--regex
default={default_regex}
The regular expression to use when :option:`kitty +kitten hints --type`=regex.
The regular expression is in python syntax. If you specify a numbered group in
the regular expression only the group will be matched. This allow you to match
text ignoring a prefix/suffix, as needed. The default expression matches lines.
To match text over multiple lines you should prefix the regular expression with
:code:`(?ms)`, which turns on MULTILINE and DOTALL modes for the regex engine.
If you specify named groups and a :option:`kitty +kitten hints --program` then
the program will be passed arguments corresponding to each named group of
the form key=value.


--linenum-action
default=self
type=choice
choices=self,window,tab,os_window,background
Where to perform the action on matched errors. :code:`self` means the current
window, :code:`window` a new kitty window, :code:`tab` a new tab,
:code:`os_window` a new OS window and :code:`background` run in the background.
The action to perform on the matched errors. The actual action is whatever
arguments are provided to the kitten, for example: :code:`kitty + kitten hints
--type=linenum --linenum-action=tab vim +{line} {path}` will open the matched
path at the matched line number in vim in a new kitty tab.


--url-prefixes
default=default
Comma separated list of recognized URL prefixes. Defaults, to
the list of prefixes defined in kitty.conf.


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


--ascending
type=bool-set
Have the hints increase from top to bottom instead of decreasing from top to bottom.


--hints-foreground-color
default=black
type=str
The foreground color for hints


--hints-background-color
default=green
type=str
The background color for hints


--hints-text-color
default=gray
type=str
The foreground color for text pointed to by the hints


--customize-processing
Name of a python file in the kitty config directory which will be imported to provide
custom implementations for pattern finding and performing actions
on selected matches. See https://sw.kovidgoyal.net/kitty/kittens/hints.html
for details. You can also specify absolute paths to load the script from elsewhere.


--window-title
The window title for the hints window, default title is selected based on
the type of text being hinted.
'''.format(
    default_regex=DEFAULT_REGEX,
    line='{{line}}', path='{{path}}'
).format
help_text = 'Select text from the screen using the keyboard. Defaults to searching for URLs.'
usage = ''


def parse_hints_args(args: List[str]) -> Tuple[HintsCLIOptions, List[str]]:
    return parse_args(args, OPTIONS, usage, help_text, 'kitty +kitten hints', result_class=HintsCLIOptions)


def main(args: List[str]) -> Optional[Dict[str, Any]]:
    text = ''
    if sys.stdin.isatty():
        if '--help' not in args and '-h' not in args:
            print('You must pass the text to be hinted on STDIN', file=sys.stderr)
            input(_('Press Enter to quit'))
            return None
    else:
        text = sys.stdin.buffer.read().decode('utf-8')
        sys.stdin = open(os.ctermid())
    try:
        opts, items = parse_hints_args(args[1:])
    except SystemExit as e:
        if e.code != 0:
            print(e.args[0], file=sys.stderr)
            input(_('Press Enter to quit'))
        return None
    if items and not (opts.customize_processing or opts.type == 'linenum'):
        print('Extra command line arguments present: {}'.format(' '.join(items)), file=sys.stderr)
        input(_('Press Enter to quit'))
    try:
        return run(opts, text, items)
    except Exception:
        import traceback
        traceback.print_exc()
        input(_('Press Enter to quit'))


def linenum_handle_result(args: List[str], data: Dict[str, Any], target_window_id: int, boss: BossType, extra_cli_args: Sequence[str], *a: Any) -> None:
    for m, g in zip(data['match'], data['groupdicts']):
        if m:
            path, line = g['path'], g['line']
            path = os.path.expanduser(path.split(':')[-1])
            line = int(line)
            break
    else:
        return

    cmd = [x.format(path=path, line=line) for x in extra_cli_args or ('vim', '+{line}', '{path}')]
    w = boss.window_id_map.get(target_window_id)
    action = data['linenum_action']

    if action == 'self':
        if w is not None:
            import shlex
            text = ' '.join(shlex.quote(arg) for arg in cmd)
            w.paste_bytes(text + '\r')
    elif action == 'background':
        import subprocess
        subprocess.Popen(cmd, cwd=data['cwd'])
    else:
        getattr(boss, {
            'window': 'new_window_with_cwd', 'tab': 'new_tab_with_cwd', 'os_window': 'new_os_window_with_cwd'
            }[action])(*cmd)


@result_handler(type_of_input='screen-ansi')
def handle_result(args: List[str], data: Dict[str, Any], target_window_id: int, boss: BossType) -> None:
    if data['customize_processing']:
        m = load_custom_processor(data['customize_processing'])
        if 'handle_result' in m:
            m['handle_result'](args, data, target_window_id, boss, data['extra_cli_args'])
            return None

    programs = data['programs'] or ('default',)
    matches: List[str] = []
    groupdicts = []
    for m, g in zip(data['match'], data['groupdicts']):
        if m:
            matches.append(m)
            groupdicts.append(g)
    joiner = data['multiple_joiner']
    try:
        is_int: Optional[int] = int(joiner)
    except Exception:
        is_int = None
    text_type = data['type']

    @lru_cache()
    def joined_text() -> str:
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
        elif program == '*':
            set_primary_selection(joined_text())
        else:
            cwd = data['cwd']
            program = None if program == 'default' else program
            if text_type == 'hyperlink':
                w = boss.window_id_map.get(target_window_id)
                for m in matches:
                    if w is not None:
                        w.open_url(m, hyperlink_id=1, cwd=cwd)
            else:
                for m, groupdict in zip(matches, groupdicts):
                    if groupdict:
                        m = []
                        for k, v in groupdict.items():
                            m.append('{}={}'.format(k, v or ''))
                    boss.open_url(m, program, cwd=cwd)


if __name__ == '__main__':
    # Run with kitty +kitten hints
    ans = main(sys.argv)
    if ans:
        print(ans)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
# }}}
