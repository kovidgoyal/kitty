#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import os
import sys
import traceback
from enum import Enum, auto
from typing import (
    Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple, Union
)

from kitty.config import cached_values_for
from kitty.fast_data_types import wcswidth
from kitty.typing import KeyEventType
from kitty.utils import ScreenSize

from ..tui.handler import Handler
from ..tui.loop import Loop
from ..tui.operations import styled
from .collection import Theme, Themes, load_themes


def format_traceback(msg: str) -> str:
    return traceback.format_exc() + '\n\n' + styled(msg, fg='red')


class State(Enum):
    fetching = auto()
    browsing = auto()


def dark_filter(q: Theme) -> bool:
    return q.is_dark


def light_filter(q: Theme) -> bool:
    return not q.is_dark


def all_filter(q: Theme) -> bool:
    return True


def create_recent_filter(names: Iterable[str]) -> Callable[[Theme], bool]:
    allowed = frozenset(names)

    def recent_filter(q: Theme) -> bool:
        return q.name in allowed

    return recent_filter


class ThemesList:

    def __init__(self) -> None:
        self.themes = Themes()
        self.current_search: str = ''
        self.display_strings: Tuple[str, ...] = ()
        self.widths: Tuple[int, ...] = ()
        self.max_width = 0
        self.current_idx = 0

    def update_themes(self, themes: Themes) -> None:
        self.themes = themes
        if self.current_search:
            self.display_strings = tuple(self.themes.apply_search(self.current_search))
        else:
            self.display_strings = tuple(t.name for t in self.themes)
        self.widths = tuple(map(wcswidth, self.display_strings))
        self.max_width = max(self.widths) if self.widths else 0

    def update_search(self, search: str = '') -> None:
        if search == self.current_search:
            return
        self.current_search = search
        self.update_themes(self.themes)

    def lines(self, num_rows: int) -> Iterator[str]:
        if num_rows < 1:
            return
        before_num = min(self.current_idx, num_rows - 1)
        start = self.current_idx - before_num
        for i in range(start, min(start + num_rows, len(self.display_strings))):
            line = self.display_strings[i]
            if i == self.current_idx:
                line = styled(line, reverse=True)
            yield line


class ThemesHandler(Handler):

    def __init__(self, cached_values: Dict[str, Any]) -> None:
        self.cached_values = cached_values
        self.state = State.fetching
        self.report_traceback_on_exit: Optional[str] = None
        self.filter_map: Dict[str, Callable[[Theme], bool]] = {
            'dark': dark_filter, 'light': light_filter, 'all': all_filter,
            'recent': create_recent_filter(self.cached_values.get('recent', ()))
        }
        self.themes_list = ThemesList()

    def enforce_cursor_state(self) -> None:
        self.cmd.set_cursor_visible(self.state == State.fetching)

    def init_terminal_state(self) -> None:
        self.cmd.save_colors()
        self.cmd.set_line_wrapping(False)
        self.cmd.set_window_title('Choose a theme for kitty')
        self.cmd.set_cursor_shape('bar')

    def initialize(self) -> None:
        self.init_terminal_state()
        self.draw_screen()
        self.fetch_themes()

    def finalize(self) -> None:
        self.cmd.restore_colors()
        self.cmd.set_cursor_visible(True)

    @property
    def current_category(self) -> str:
        cat: str = self.cached_values.get('category', 'all')
        if cat not in self.filter_map:
            cat = 'all'
        return cat

    @current_category.setter
    def current_category(self, cat: str) -> None:
        if cat not in self.filter_map:
            cat = 'all'
        self.cached_values['category'] = cat

    def redraw_after_category_change(self) -> None:
        self.themes_list.update_themes(self.all_themes.filtered(self.filter_map[self.current_category]))
        self.draw_screen()

    # Theme fetching {{{
    def fetch_themes(self) -> None:

        def fetching_done(themes_or_exception: Union[Themes, str]) -> None:
            if isinstance(themes_or_exception, str):
                self.report_traceback_on_exit = themes_or_exception
                self.quit_loop(1)
                return
            self.all_themes: Themes = themes_or_exception
            self.state = State.browsing
            self.redraw_after_category_change()

        def fetch() -> None:
            try:
                themes: Union[Themes, str] = load_themes()
            except Exception:
                themes = format_traceback('Failed to download themes')
            self.asyncio_loop.call_soon_threadsafe(fetching_done, themes)

        self.asyncio_loop.run_in_executor(None, fetch)
        self.draw_screen()

    def draw_fetching_screen(self) -> None:
        self.print('Downloading themes from repository, please wait...')

    def on_fetching_key_event(self, key_event: KeyEventType, in_bracketed_paste: bool = False) -> None:
        if key_event.matches('esc'):
            self.quit_loop(0)

    # }}}

    # Theme browsing {{{
    def draw_tab_bar(self) -> None:
        pass

    def draw_browsing_screen(self) -> None:
        self.draw_tab_bar()
    # }}}

    def on_key_event(self, key_event: KeyEventType, in_bracketed_paste: bool = False) -> None:
        if self.state is State.fetching:
            self.on_fetching_key_event(key_event, in_bracketed_paste)

    def draw_screen(self) -> None:
        self.cmd.clear_screen()
        self.enforce_cursor_state()
        if self.state is State.fetching:
            self.draw_fetching_screen()
        elif self.state is State.browsing:
            self.draw_browsing_screen()

    def on_resize(self, screen_size: ScreenSize) -> None:
        self.screen_size = screen_size

    def on_interrupt(self) -> None:
        self.quit_loop(1)

    def on_eot(self) -> None:
        self.quit_loop(1)


def main(args: List[str]) -> None:
    loop = Loop()
    with cached_values_for('themes-kitten') as cached_values:
        handler = ThemesHandler(cached_values)
        loop.loop(handler)
    if loop.return_code != 0:
        if handler.report_traceback_on_exit:
            print(handler.report_traceback_on_exit, file=sys.stderr)
            input('Press Enter to quit.')
    if handler.state is State.fetching:
        # asycio uses non-daemonic threads in its ThreadPoolExecutor
        # so we will hang here till the download completes without
        # os._exit
        os._exit(loop.return_code)
    raise SystemExit(loop.return_code)


if __name__ == '__main__':
    main(sys.argv)
