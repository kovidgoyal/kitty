#!/usr/bin/env python3
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import sys
from contextlib import suppress
from typing import TYPE_CHECKING, Dict, List, NamedTuple, Optional, Tuple

from kitty.cli import parse_args
from kitty.cli_stub import AskCLIOptions
from kitty.constants import cache_dir
from kitty.fast_data_types import wcswidth
from kitty.typing import BossType, TypedDict
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
choices=line,yesno,choices
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
'''


class Response(TypedDict):
    items: List[str]
    response: Optional[str]


class Choice(NamedTuple):
    text: str
    idx: int
    color: str


class Range(NamedTuple):
    start: int
    end: int
    y: int

    def has_point(self, x: int, y: int) -> bool:
        return y == self.y and self.start <= x <= self.end


class Choose(Handler):
    mouse_tracking = MouseTracking.buttons_only

    def __init__(self, cli_opts: AskCLIOptions) -> None:
        self.cli_opts = cli_opts
        self.response = 'n' if cli_opts.type == 'yesno' else ''
        self.allowed = frozenset('yn')
        self.choices: Dict[str, Choice] = {}
        self.clickable_ranges: Dict[str, Range] = {}
        if cli_opts.type != 'yesno':
            allowed = []
            for choice in cli_opts.choices:
                color = 'green'
                letter, text = choice.split(':', maxsplit=1)
                if ';' in letter:
                    letter, color = letter.split(';', maxsplit=1)
                letter = letter.lower()
                idx = text.lower().index(letter)
                allowed.append(letter)
                self.choices[letter] = Choice(text, idx, color)
            self.allowed = frozenset(allowed)

    def initialize(self) -> None:
        self.cmd.set_cursor_visible(False)
        self.draw_screen()

    def finalize(self) -> None:
        self.cmd.set_cursor_visible(True)

    @Handler.atomic_update
    def draw_screen(self) -> None:
        self.cmd.clear_screen()
        y = 1
        if self.cli_opts.message:
            self.cmd.styled(self.cli_opts.message, bold=True)
            y += wcswidth(self.cli_opts.message) // self.screen_size.cols
        self.print()
        if self.cli_opts.type == 'yesno':
            self.draw_yesno(y)
        else:
            self.draw_choice(y)

    def draw_choice(self, y: int) -> None:
        x = 0
        self.clickable_ranges.clear()
        for letter, choice in self.choices.items():
            text = choice.text[:choice.idx]
            text += styled(choice.text[choice.idx], fg=choice.color)
            text += choice.text[choice.idx + 1:]
            text += '  '
            sz = wcswidth(text)
            if sz + x >= self.screen_size.cols:
                y += 1
                x = 0
                self.print()
            self.clickable_ranges[letter] = Range(x, x + sz - 1, y)
            x += sz
            self.print(text, end='')

    def draw_yesno(self, y: int) -> None:
        self.clickable_ranges = {'y': Range(2, 4, y), 'n': Range(8, 9, y)}
        self.print(' ', styled('Y', fg='green') + 'es', ' ', styled('N', fg='red') + 'o')

    def on_text(self, text: str, in_bracketed_paste: bool = False) -> None:
        text = text.lower()
        if text in self.allowed:
            self.response = text
            self.quit_loop(0)

    def on_click(self, ev: MouseEvent) -> None:
        for letter, r in self.clickable_ranges.items():
            if r.has_point(ev.cell_x, ev.cell_y):
                self.response = letter
                self.quit_loop(0)
                break

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
