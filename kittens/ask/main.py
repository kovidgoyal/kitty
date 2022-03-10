#!/usr/bin/env python3
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import sys
from contextlib import suppress
from typing import (
    TYPE_CHECKING, Callable, Dict, List, NamedTuple, Optional, Tuple
)

from kitty.cli import parse_args
from kitty.cli_stub import AskCLIOptions
from kitty.constants import cache_dir
from kitty.fast_data_types import truncate_point_for_length, wcswidth
from kitty.typing import BossType, KeyEventType, TypedDict
from kitty.utils import ScreenSize

from ..tui.handler import Handler, result_handler
from ..tui.loop import Loop, MouseEvent
from ..tui.operations import MouseTracking, alternate_screen, styled

if TYPE_CHECKING:
    import readline
else:
    readline = None


def get_history_items() -> List[str]:
    return list(map(readline.get_history_item, range(1, readline.get_current_history_length() + 1)))


def sort_key(item: str) -> Tuple[int, str]:
    return len(item), item.lower()


class HistoryCompleter:

    def __init__(self, name: Optional[str] = None):
        self.matches: List[str] = []
        self.history_path = None
        if name:
            ddir = os.path.join(cache_dir(), 'ask')
            with suppress(FileExistsError):
                os.makedirs(ddir)
            self.history_path = os.path.join(ddir, name)

    def complete(self, text: str, state: int) -> Optional[str]:
        response = None
        if state == 0:
            history_values = get_history_items()
            if text:
                self.matches = sorted(
                        (h for h in history_values if h and h.startswith(text)), key=sort_key)
            else:
                self.matches = []
        try:
            response = self.matches[state]
        except IndexError:
            response = None
        return response

    def __enter__(self) -> 'HistoryCompleter':
        if self.history_path:
            with suppress(Exception):
                readline.read_history_file(self.history_path)
            readline.set_completer(self.complete)
        return self

    def __exit__(self, *a: object) -> None:
        if self.history_path:
            readline.write_history_file(self.history_path)


def option_text() -> str:
    return '''\
--type -t
choices=line,yesno,choices,password
default=line
Type of input. Defaults to asking for a line of text.


--message -m
The message to display to the user. If not specified a default
message is shown.


--name -n
The name for this question. Used to store history of previous answers which can
be used for completions and via the browse history readline bindings.


--choice -c
type=list
dest=choices
A choice for the choices type. Every choice has the syntax: letter:text Where
letter is the accelerator key and text is the corresponding text.  There can be
an optional color specification after the letter to indicate what color it should
be.
For example: y:Yes and n;red:No


--default -d
A default choice or text. If unspecified, it is "y" for :code:`yesno`, the first choice
for :code:`choices` and empty for others. The default choice is selected when the user
presses the Enter key.
'''


class Response(TypedDict):
    items: List[str]
    response: Optional[str]


class Choice(NamedTuple):
    text: str
    idx: int
    color: str
    letter: str


class Range(NamedTuple):
    start: int
    end: int
    y: int

    def has_point(self, x: int, y: int) -> bool:
        return y == self.y and self.start <= x <= self.end


def truncate_at_space(text: str, width: int) -> Tuple[str, str]:
    p = truncate_point_for_length(text, width)
    if p < len(text):
        i = text.rfind(' ', 0, p + 1)
        if i > 0 and p - i < 12:
            p = i + 1
    return text[:p], text[p:]


def extra_for(width: int, screen_width: int) -> int:
    return max(0, screen_width - width) // 2 + 1


class Choose(Handler):
    mouse_tracking = MouseTracking.buttons_only

    def __init__(self, cli_opts: AskCLIOptions) -> None:
        self.cli_opts = cli_opts
        self.choices: Dict[str, Choice] = {}
        self.clickable_ranges: Dict[str, List[Range]] = {}
        if cli_opts.type == 'yesno':
            self.allowed = frozenset('yn')
        else:
            allowed = []
            for choice in cli_opts.choices:
                letter, text = choice.split(':', maxsplit=1)
                color = ''
                if ';' in letter:
                    letter, color = letter.split(';', maxsplit=1)
                letter = letter.lower()
                idx = text.lower().index(letter)
                allowed.append(letter)
                self.choices[letter] = Choice(text, idx, color, letter)
            self.allowed = frozenset(allowed)
        self.response = ''
        self.response_on_accept = cli_opts.default or ''
        if cli_opts.type in ('yesno', 'choices') and self.response_on_accept not in self.allowed:
            self.response_on_accept = 'y' if cli_opts.type == 'yesno' else tuple(self.choices.keys())[0]

    def initialize(self) -> None:
        self.cmd.set_cursor_visible(False)
        self.draw_screen()

    def finalize(self) -> None:
        self.cmd.set_cursor_visible(True)

    def draw_long_text(self, text: str) -> int:
        y = 0
        width = self.screen_size.cols - 2
        while text:
            t, text = truncate_at_space(text, width)
            t = t.strip()
            self.print(' ' * extra_for(wcswidth(t), width), styled(t, bold=True), sep='')
            y += 1
        return y

    @Handler.atomic_update
    def draw_screen(self) -> None:
        self.cmd.clear_screen()
        y = max(0, self.screen_size.rows // 2 - 2)
        self.print(end='\r\n'*y)
        if self.cli_opts.message:
            for line in self.cli_opts.message.splitlines():
                y += self.draw_long_text(line)
        if self.screen_size.rows > 2:
            self.print()
            y += 1
        if self.cli_opts.type == 'yesno':
            self.draw_yesno(y)
        else:
            self.draw_choice(y)

    def draw_choice_boxes(self, y: int, *choices: Choice) -> None:
        self.clickable_ranges.clear()
        width = self.screen_size.cols - 2
        current_line_length = 0
        current_line: List[Tuple[str, str]] = []
        lines: List[List[Tuple[str, str]]] = []
        sep, sep_sz = '  ', 2

        for choice in choices:
            self.clickable_ranges[choice.letter] = []
            text = ' ' + choice.text[:choice.idx]
            text += styled(choice.text[choice.idx], fg=choice.color or 'green')
            text += choice.text[choice.idx + 1:] + ' '
            sz = wcswidth(text)
            if sz + sep_sz + current_line_length > width:
                lines.append(current_line)
                current_line = []
                current_line_length = 0
            current_line.append((choice.letter, text))
            current_line_length += sz
        if current_line:
            lines.append(current_line)

        def top(text: str) -> str:
            return '╭' + '─' * wcswidth(text) + '╮'

        def middle(text: str) -> str:
            return f'│{text}│'

        def bottom(text: str) -> str:
            return '╰' + '─' * wcswidth(text) + '╯'

        def highlight(text: str, only_edges: bool = False) -> str:
            if only_edges:
                return styled(text[0], fg='yellow') + text[1:-1] + styled(text[-1], fg='yellow')
            return styled(text, fg='yellow')

        def print_line(add_borders: Callable[[str], str], *items: Tuple[str, str], is_last: bool = False) -> None:
            nonlocal y
            texts = []
            positions = []
            x = 0
            for (letter, text) in items:
                positions.append((letter, x, wcswidth(text) + 2))
                text = add_borders(text)
                if letter == self.response_on_accept:
                    text = highlight(text, only_edges=add_borders is middle)
                text += sep
                x += wcswidth(text)
                texts.append(text)
            line = ''.join(texts).rstrip()
            offset = extra_for(wcswidth(line), width)
            for (letter, x, sz) in positions:
                x += offset
                self.clickable_ranges[letter].append(Range(x, x + sz - 1, y))
            self.print(' ' * offset, line, sep='', end='' if is_last else '\r\n')
            y += 1

        for boxed_line in lines:
            print_line(top, *boxed_line)
            print_line(middle, *boxed_line)
            print_line(bottom, *boxed_line, is_last=boxed_line is lines[-1])

    def draw_choice(self, y: int) -> None:
        if y + 3 <= self.screen_size.rows:
            self.draw_choice_boxes(y, *self.choices.values())
            return
        self.clickable_ranges.clear()
        current_line = ''
        current_ranges: Dict[str, int] = {}
        width = self.screen_size.cols - 2

        def commit_line(end: str = '\r\n') -> None:
            nonlocal current_line, y
            x = extra_for(wcswidth(current_line), width)
            self.print(' ' * x + current_line, end=end)
            for letter, sz in current_ranges.items():
                self.clickable_ranges[letter] = [Range(x, x + sz - 3, y)]
                x += sz
            current_ranges.clear()
            y += 1
            current_line = ''

        for letter, choice in self.choices.items():
            text = choice.text[:choice.idx]
            text += styled(choice.text[choice.idx], fg=choice.color or 'green', underline='straight' if letter == self.response_on_accept else None)
            text += choice.text[choice.idx + 1:]
            text += '  '
            sz = wcswidth(text)
            if sz + wcswidth(current_line) >= width:
                commit_line()
            current_line += text
            current_ranges[letter] = sz
        if current_line:
            commit_line(end='')

    def draw_yesno(self, y: int) -> None:
        yes = styled('Y', fg='green') + 'es'
        no = styled('N', fg='red') + 'o'
        if y + 3 <= self.screen_size.rows:
            self.draw_choice_boxes(y, Choice('Yes', 0, 'green', 'y'), Choice('No', 0, 'red', 'n'))
            return
        sep = ' ' * 3
        text = yes + sep + no
        w = wcswidth(text)
        x = extra_for(w, self.screen_size.cols - 2)
        nx = x + wcswidth(yes) + len(sep)
        self.clickable_ranges = {'y': [Range(x, x + wcswidth(yes) - 1, y)], 'n': [Range(nx, nx + wcswidth(no) - 1, y)]}
        self.print(' ' * x + text, end='')

    def on_text(self, text: str, in_bracketed_paste: bool = False) -> None:
        text = text.lower()
        if text in self.allowed:
            self.response = text
            self.quit_loop(0)
        elif self.cli_opts.type == 'yesno':
            self.on_interrupt()

    def on_key(self, key_event: KeyEventType) -> None:
        if key_event.matches('esc'):
            self.on_interrupt()
        elif key_event.matches('enter'):
            self.response = self.response_on_accept
            self.quit_loop(0)

    def on_click(self, ev: MouseEvent) -> None:
        for letter, ranges in self.clickable_ranges.items():
            for r in ranges:
                if r.has_point(ev.cell_x, ev.cell_y):
                    self.response = letter
                    self.quit_loop(0)
                    return

    def on_resize(self, screen_size: ScreenSize) -> None:
        self.screen_size = screen_size
        self.draw_screen()

    def on_interrupt(self) -> None:
        self.quit_loop(1)
    on_eot = on_interrupt


def main(args: List[str]) -> Response:
    # For some reason importing readline in a key handler in the main kitty process
    # causes a crash of the python interpreter, probably because of some global
    # lock
    global readline
    msg = 'Ask the user for input'
    try:
        cli_opts, items = parse_args(args[1:], option_text, '', msg, 'kitty ask', result_class=AskCLIOptions)
    except SystemExit as e:
        if e.code != 0:
            print(e.args[0])
            input('Press enter to quit...')
        raise SystemExit(e.code)

    if cli_opts.type in ('yesno', 'choices'):
        loop = Loop()
        handler = Choose(cli_opts)
        loop.loop(handler)
        return {'items': items, 'response': handler.response}

    if cli_opts.type == 'password':
        import getpass
        if cli_opts.message:
            print(styled(cli_opts.message, bold=True))
        q = getpass.getpass()
        return {'items': items, 'response': q or ''}

    import readline as rl
    readline = rl
    from kitty.shell import init_readline
    init_readline()
    response = None

    with alternate_screen(), HistoryCompleter(cli_opts.name):
        if cli_opts.message:
            print(styled(cli_opts.message, bold=True))

        prompt = '> '
        with suppress(KeyboardInterrupt, EOFError):
            if cli_opts.default:
                def prefill_text() -> None:
                    readline.insert_text(cli_opts.default or '')
                    readline.redisplay()
                readline.set_pre_input_hook(prefill_text)
                response = input(prompt)
                readline.set_pre_input_hook()
            else:
                response = input(prompt)
    return {'items': items, 'response': response}


@result_handler()
def handle_result(args: List[str], data: Response, target_window_id: int, boss: BossType) -> None:
    if data['response'] is not None:
        func, *args = data['items']
        getattr(boss, func)(data['response'], *args)


if __name__ == '__main__':
    ans = main(sys.argv)
    if ans:
        print(ans)
