#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


import os
from collections.abc import Callable, Generator, Sequence
from typing import Any

from kitty.fast_data_types import wcswidth
from kitty.utils import ScreenSize, screen_size_function

from .operations import styled


def directory_completions(path: str, qpath: str, prefix: str = '') -> Generator[str, None, None]:
    try:
        entries = os.scandir(qpath)
    except OSError:
        return
    for x in entries:
        try:
            is_dir = x.is_dir()
        except OSError:
            is_dir = False
        name = x.name + (os.sep if is_dir else '')
        if not prefix or name.startswith(prefix):
            if path:
                yield os.path.join(path, name)
            else:
                yield name


def expand_path(path: str) -> str:
    return os.path.abspath(os.path.expandvars(os.path.expanduser(path)))


def find_completions(path: str) -> Generator[str, None, None]:
    if path and path[0] == '~':
        if path == '~':
            yield '~' + os.sep
            return
        if os.sep not in path:
            qpath = os.path.expanduser(path)
            if qpath != path:
                yield path + os.sep
                return
    qpath = expand_path(path)
    if not path or path.endswith(os.sep):
        yield from directory_completions(path, qpath)
    else:
        yield from directory_completions(os.path.dirname(path), os.path.dirname(qpath), os.path.basename(qpath))


def print_table(items: Sequence[str], screen_size: ScreenSize, dir_colors: Callable[[str, str], str]) -> None:
    max_width = 0
    item_widths = {}
    for item in items:
        item_widths[item] = w = wcswidth(item)
        max_width = max(w, max_width)
    col_width = max_width + 2
    num_of_cols = max(1, screen_size.cols // col_width)
    cr = 0
    at_start = False
    for item in items:
        w = item_widths[item]
        left = col_width - w
        print(dir_colors(expand_path(item), item), ' ' * left, sep='', end='')
        at_start = False
        cr = (cr + 1) % num_of_cols
        if not cr:
            print()
            at_start = True
    if not at_start:
        print()


class PathCompleter:

    def __init__(self, prompt: str = '> '):
        self.prompt = prompt
        self.prompt_len = wcswidth(self.prompt)

    def __enter__(self) -> 'PathCompleter':
        import readline

        from .dircolors import Dircolors
        if 'libedit' in readline.__doc__:
            readline.parse_and_bind("bind -e")
            readline.parse_and_bind("bind '\t' rl_complete")
        else:
            readline.parse_and_bind('tab: complete')
            readline.parse_and_bind('set colored-stats on')
            readline.set_completer_delims(' \t\n`!@#$%^&*()-=+[{]}\\|;:\'",<>?')
        readline.set_completion_display_matches_hook(self.format_completions)
        self.original_completer = readline.get_completer()
        readline.set_completer(self)
        self.cache: dict[str, tuple[str, ...]] = {}
        self.dircolors = Dircolors()
        return self

    def format_completions(self, substitution: str, matches: Sequence[str], longest_match_length: int) -> None:
        import readline
        print()
        files, dirs = [], []
        for m in matches:
            if m.endswith('/'):
                if len(m) > 1:
                    m = m[:-1]
                dirs.append(m)
            else:
                files.append(m)

        ss = screen_size_function()()
        if dirs:
            print(styled('Directories', bold=True, fg_intense=True))
            print_table(dirs, ss, self.dircolors)
        if files:
            print(styled('Files', bold=True, fg_intense=True))
            print_table(files, ss, self.dircolors)

        buf = readline.get_line_buffer()
        x = readline.get_endidx()
        buflen = wcswidth(buf)
        print(self.prompt, buf, sep='', end='')
        if x < buflen:
            pos = x + self.prompt_len
            print(f"\r\033[{pos}C", end='')
        print(sep='', end='', flush=True)

    def __call__(self, text: str, state: int) -> str | None:
        options = self.cache.get(text)
        if options is None:
            options = self.cache[text] = tuple(find_completions(text))
        if options and state < len(options):
            return options[state]
        return None

    def __exit__(self, *a: Any) -> bool:
        import readline
        del self.cache
        readline.set_completer(self.original_completer)
        readline.set_completion_display_matches_hook()
        return True

    def input(self) -> str:
        with self:
            return input(self.prompt)
        return ''


def get_path(prompt: str = '> ') -> str:
    return PathCompleter(prompt).input()


def develop() -> None:
    PathCompleter().input()
