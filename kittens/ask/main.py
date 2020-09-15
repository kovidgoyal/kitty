#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import sys
from contextlib import suppress
from typing import TYPE_CHECKING, List, Optional, Tuple

from kitty.cli import parse_args
from kitty.cli_stub import AskCLIOptions
from kitty.constants import cache_dir
from kitty.typing import BossType

from ..tui.handler import result_handler
from ..tui.operations import alternate_screen, styled
from ..tui.utils import get_key_press

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


try:
    from typing import TypedDict
except ImportError:
    TypedDict = dict


class Response(TypedDict):
    items: List[str]
    response: Optional[str]


def choice(cli_opts: AskCLIOptions, items: List[str]) -> Response:
    with alternate_screen():
        if cli_opts.message:
            print(styled(cli_opts.message, bold=True))
        print()
        allowed = ''
        for choice in cli_opts.choices:
            color = 'green'
            letter, text = choice.split(':', maxsplit=1)
            if ';' in letter:
                letter, color = letter.split(';', maxsplit=1)
            letter = letter.lower()
            idx = text.lower().index(letter)
            allowed += letter
            print(text[:idx], styled(text[idx], fg=color), text[idx + 1:], sep='', end='  ')
        print()
        response = get_key_press(allowed, '')
        return {'items': items, 'response': response}


def yesno(cli_opts: AskCLIOptions, items: List[str]) -> Response:
    with alternate_screen():
        if cli_opts.message:
            print(styled(cli_opts.message, bold=True))
        print()
        print(' ', styled('Y', fg='green') + 'es', ' ', styled('N', fg='red') + 'o')
        response = get_key_press('yn', 'n')
        return {'items': items, 'response': response}


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

    if cli_opts.type == 'yesno':
        return yesno(cli_opts, items)
    if cli_opts.type == 'choices':
        return choice(cli_opts, items)

    import readline as rl
    readline = rl
    from kitty.shell import init_readline
    init_readline(readline)
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
