#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import sys
import traceback
from enum import Enum, auto
from gettext import gettext as _
from typing import (
    Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple, Union
)

from kitty.cli import create_default_opts, parse_args
from kitty.cli_stub import ThemesCLIOptions
from kitty.config import cached_values_for
from kitty.constants import config_dir
from kitty.fast_data_types import truncate_point_for_length, wcswidth
from kitty.rgb import color_as_sharp, color_from_int
from kitty.typing import KeyEventType
from kitty.utils import ScreenSize

from ..tui.handler import Handler
from ..tui.line_edit import LineEdit
from ..tui.loop import Loop
from ..tui.operations import color_code, styled
from .collection import MARK_AFTER, NoCacheFound, Theme, Themes, load_themes

separator = '║'


def format_traceback(msg: str) -> str:
    return traceback.format_exc() + '\n\n' + styled(msg, fg='red')


def limit_length(text: str, limit: int = 32) -> str:
    x = truncate_point_for_length(text, limit - 1)
    if x >= len(text):
        return text
    return f'{text[:x]}…'


class State(Enum):
    fetching = auto()
    browsing = auto()
    searching = auto()
    accepting = auto()


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


def mark_shortcut(text: str, acc: str) -> str:
    acc_idx = text.lower().index(acc.lower())
    return text[:acc_idx] + styled(text[acc_idx], underline='straight', bold=True, fg_intense=True) + text[acc_idx+1:]


class ThemesList:

    def __init__(self) -> None:
        self.themes = Themes()
        self.current_search: str = ''
        self.display_strings: Tuple[str, ...] = ()
        self.widths: Tuple[int, ...] = ()
        self.max_width = 0
        self.current_idx = 0

    def __bool__(self) -> bool:
        return bool(self.display_strings)

    def __len__(self) -> int:
        return len(self.themes)

    def next(self, delta: int = 1, allow_wrapping: bool = True) -> bool:
        if not self:
            return False
        idx = self.current_idx + delta
        if not allow_wrapping and (idx < 0 or idx >= len(self)):
            return False
        while idx < 0:
            idx += len(self)
        self.current_idx = idx % len(self)
        return True

    def update_themes(self, themes: Themes) -> None:
        self.themes = self.all_themes = themes
        if self.current_search:
            self.themes = self.all_themes.copy()
            self.display_strings = tuple(map(limit_length, self.themes.apply_search(self.current_search)))
        else:
            self.display_strings = tuple(map(limit_length, (t.name for t in self.themes)))
        self.widths = tuple(map(wcswidth, self.display_strings))
        self.max_width = max(self.widths) if self.widths else 0
        self.current_idx = 0

    def update_search(self, search: str = '') -> bool:
        if search == self.current_search:
            return False
        self.current_search = search
        self.update_themes(self.all_themes)
        return True

    def lines(self, num_rows: int) -> Iterator[Tuple[str, int, bool]]:
        if num_rows < 1:
            return
        before_num = min(self.current_idx, num_rows - 1)
        start = self.current_idx - before_num
        for i in range(start, min(start + num_rows, len(self.display_strings))):
            line = self.display_strings[i]
            yield line, self.widths[i], i == self.current_idx

    @property
    def current_theme(self) -> Theme:
        return self.themes[self.current_idx]


class ThemesHandler(Handler):

    def __init__(self, cached_values: Dict[str, Any], cli_opts: ThemesCLIOptions) -> None:
        self.cached_values = cached_values
        self.cli_opts = cli_opts
        self.state = State.fetching
        self.report_traceback_on_exit: Optional[str] = None
        self.filter_map: Dict[str, Callable[[Theme], bool]] = {
            'dark': dark_filter, 'light': light_filter, 'all': all_filter,
            'recent': create_recent_filter(self.cached_values.get('recent', ()))
        }
        self.themes_list = ThemesList()
        self.colors_set_once = False
        self.line_edit = LineEdit()
        self.tabs = tuple('all dark light recent'.split())
        self.quit_on_next_key_release = -1

    def update_recent(self) -> None:
        r = list(self.cached_values.get('recent', ()))
        if self.themes_list:
            name = self.themes_list.current_theme.name
            r = [name] + [x for x in r if x != name]
            self.cached_values['recent'] = r[:20]

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

    def set_colors_to_current_theme(self) -> bool:
        if not self.themes_list and self.colors_set_once:
            return False
        self.colors_set_once = True
        if self.themes_list:
            o = self.themes_list.current_theme.kitty_opts
        else:
            o = create_default_opts()
        self.cmd.set_default_colors(
            fg=o.foreground, bg=o.background, cursor=o.cursor, select_bg=o.selection_background, select_fg=o.selection_foreground
        )
        self.current_opts = o
        cmds = []
        for i in range(256):
            col = color_as_sharp(color_from_int(o.color_table[i]))
            cmds.append(f'{i};{col}')
        self.print(end='\033]4;' + ';'.join(cmds) + '\033\\')
        return True

    def redraw_after_category_change(self) -> None:
        self.themes_list.update_themes(self.all_themes.filtered(self.filter_map[self.current_category]))
        self.set_colors_to_current_theme()
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
                themes: Union[Themes, str] = load_themes(self.cli_opts.cache_age)
            except Exception:
                themes = format_traceback('Failed to download themes')
            self.asyncio_loop.call_soon_threadsafe(fetching_done, themes)

        self.asyncio_loop.run_in_executor(None, fetch)
        self.draw_screen()

    def draw_fetching_screen(self) -> None:
        self.print('Downloading themes from repository, please wait...')

    def on_fetching_key_event(self, key_event: KeyEventType, in_bracketed_paste: bool = False) -> None:
        if key_event.matches('esc'):
            self.quit_on_next_key_release = 0
            return

    # }}}

    # Theme browsing {{{
    def draw_tab_bar(self) -> None:
        self.print(styled(' ' * self.screen_size.cols, reverse=True), end='\r')

        def draw_tab(text: str, name: str, acc: str) -> None:
            is_active = name == self.current_category
            if is_active:
                text = styled(f'{text} #{len(self.themes_list)}', italic=True)
            else:
                text = mark_shortcut(text, acc)

            self.cmd.styled(f' {text} ', reverse=not is_active)

        for t in self.tabs:
            draw_tab(t.capitalize(), t, t[0])
        self.cmd.sgr('0')
        self.print()

    def draw_bottom_bar(self) -> None:
        self.cmd.set_cursor_position(0, self.screen_size.rows)
        self.print(styled(' ' * self.screen_size.cols, reverse=True), end='\r')
        for (t, sc) in (('search (/)', 's'), ('accept (⏎)', 'c')):
            text = mark_shortcut(t.capitalize(), sc)
            self.cmd.styled(f' {text} ', reverse=True)
        self.cmd.sgr('0')

    def draw_search_bar(self) -> None:
        self.cmd.set_cursor_position(0, self.screen_size.rows)
        self.cmd.clear_to_eol()
        self.line_edit.write(self.write)

    def draw_theme_demo(self) -> None:
        theme = self.themes_list.current_theme
        xstart = self.themes_list.max_width + 3
        sz = self.screen_size.cols - xstart
        if sz < 20:
            return
        sz -= 1
        y = 0
        colors = 'black red green yellow blue magenta cyan white'.split()
        trunc = sz // 8 - 1

        def next_line() -> None:
            nonlocal y
            self.write('\r')
            y += 1
            self.cmd.set_cursor_position(xstart - 1, y)
            self.write(separator + ' ')

        def write_para(text: str) -> None:
            text = re.sub(r'\s+', ' ', text)
            while text:
                sp = truncate_point_for_length(text, sz)
                self.write(text[:sp])
                next_line()
                text = text[sp:]

        def write_colors(bg: Optional[str] = None) -> None:
            for intense in (False, True):
                buf = []
                for c in colors:
                    buf.append(styled(c[:trunc], fg=c, fg_intense=intense))
                self.cmd.styled(' '.join(buf), bg=bg, bg_intense=intense)
                next_line()
            next_line()

        self.cmd.set_cursor_position()
        next_line()
        self.cmd.styled(theme.name.center(sz), bold=True, fg='green')
        next_line()
        if theme.author:
            self.cmd.styled(theme.author.center(sz), italic=True)
            next_line()
        if theme.blurb:
            next_line()
            write_para(theme.blurb)
            next_line()
        write_colors()

        for bg in colors:
            write_colors(bg)

    def draw_browsing_screen(self) -> None:
        self.draw_tab_bar()
        num_rows = self.screen_size.rows - 2
        mw = self.themes_list.max_width + 1
        for line, width, is_current in self.themes_list.lines(num_rows):
            num_rows -= 1
            if is_current:
                line = line.replace(MARK_AFTER, f'\033[{color_code("green")}m')
            self.cmd.styled('>' if is_current else ' ', fg='green')
            self.cmd.styled(line, bold=is_current, fg='green' if is_current else None)
            self.cmd.move_cursor_by(mw - width, 'right')
            self.print(separator)
        if self.themes_list:
            self.draw_theme_demo()
        self.draw_bottom_bar() if self.state is State.browsing else self.draw_search_bar()

    def on_searching_key_event(self, key_event: KeyEventType, in_bracketed_paste: bool = False) -> None:
        if key_event.matches('enter'):
            self.state = State.browsing
            self.draw_bottom_bar()
            return
        if key_event.matches('esc'):
            self.state = State.browsing
            self.themes_list.update_search('')
            self.set_colors_to_current_theme()
            return self.draw_screen()
        if key_event.text:
            self.line_edit.on_text(key_event.text, in_bracketed_paste)
        else:
            if not self.line_edit.on_key(key_event):
                if key_event.matches('left') or key_event.matches('shift+tab'):
                    return self.next_category(-1)
                if key_event.matches('right') or key_event.matches('tab'):
                    return self.next_category(1)
                if key_event.matches('down'):
                    return self.next(delta=1)
                if key_event.matches('up'):
                    return self.next(delta=-1)
                if key_event.matches('page_down'):
                    return self.next(delta=self.screen_size.rows - 3, allow_wrapping=False)
                if key_event.matches('page_up'):
                    return self.next(delta=3 - self.screen_size.rows, allow_wrapping=False)
                return
        if self.line_edit.current_input:
            q = self.line_edit.current_input[1:]
            if self.themes_list.update_search(q):
                self.set_colors_to_current_theme()
                self.draw_screen()
            else:
                self.draw_search_bar()
        else:
            self.state = State.browsing
            self.draw_bottom_bar()

    def on_browsing_key_event(self, key_event: KeyEventType, in_bracketed_paste: bool = False) -> None:
        if key_event.matches('esc') or key_event.matches_text('q'):
            self.quit_on_next_key_release = 0
            return
        for cat in 'all dark light recent'.split():
            if key_event.matches_text(cat[0]) or key_event.matches(f'alt+{cat[0]}'):
                if cat != self.current_category:
                    self.current_category = cat
                    self.redraw_after_category_change()
                return
        if key_event.matches('left') or key_event.matches('shift+tab'):
            return self.next_category(-1)
        if key_event.matches('right') or key_event.matches('tab'):
            return self.next_category(1)
        if key_event.matches_text('j') or key_event.matches('down'):
            return self.next(delta=1)
        if key_event.matches_text('k') or key_event.matches('up'):
            return self.next(delta=-1)
        if key_event.matches('page_down'):
            return self.next(delta=self.screen_size.rows - 3, allow_wrapping=False)
        if key_event.matches('page_up'):
            return self.next(delta=3 - self.screen_size.rows, allow_wrapping=False)
        if key_event.matches_text('s') or key_event.matches('/'):
            return self.start_search()
        if key_event.matches_text('c') or key_event.matches('enter'):
            if not self.themes_list:
                self.cmd.beep()
                return
            self.state = State.accepting
            return self.draw_screen()

    def start_search(self) -> None:
        self.line_edit.clear()
        self.line_edit.add_text('/' + self.themes_list.current_search)
        self.state = State.searching
        self.draw_screen()

    def next_category(self, delta: int = 1) -> None:
        idx = self.tabs.index(self.current_category) + delta + len(self.tabs)
        self.current_category = self.tabs[idx % len(self.tabs)]
        self.redraw_after_category_change()

    def next(self, delta: int = 1, allow_wrapping: bool = True) -> None:
        if self.themes_list.next(delta, allow_wrapping):
            self.set_colors_to_current_theme()
            self.draw_screen()
        else:
            self.cmd.bell()
    # }}}

    # Accepting {{{
    def draw_accepting_screen(self) -> None:
        name = self.themes_list.current_theme.name
        name = styled(name, bold=True, fg="green")
        kc = styled(self.cli_opts.config_file_name, italic=True)

        def ac(x: str) -> str:
            return styled(x, fg='red')

        self.cmd.set_line_wrapping(True)
        self.print(f'You have chosen the {name} theme')
        self.print()
        self.print('What would you like to do?')
        self.print()
        self.print(' ', f'{ac("M")}odify {kc} to load', styled(name, bold=True, fg="green"))
        self.print()
        self.print(' ', f'{ac("P")}lace the theme file in {config_dir} but do not modify {kc}')
        self.print()
        self.print(' ', f'{ac("A")}bort and return to list of themes')
        self.print()
        self.print(' ', f'{ac("Q")}uit')

    def on_accepting_key_event(self, key_event: KeyEventType, in_bracketed_paste: bool = False) -> None:
        if key_event.matches_text('q') or key_event.matches('esc'):
            self.quit_on_next_key_release = 0
            return
        if key_event.matches_text('a'):
            self.state = State.browsing
            self.draw_screen()
            return
        if key_event.matches_text('p'):
            self.themes_list.current_theme.save_in_dir(config_dir)
            self.update_recent()
            self.quit_on_next_key_release = 0
            return
        if key_event.matches_text('m'):
            self.themes_list.current_theme.save_in_conf(config_dir, self.cli_opts.reload_in, self.cli_opts.config_file_name)
            self.update_recent()
            self.quit_on_next_key_release = 0
            return
    # }}}

    def on_key_event(self, key_event: KeyEventType, in_bracketed_paste: bool = False) -> None:
        if self.quit_on_next_key_release > -1 and key_event.is_release:
            self.quit_loop(self.quit_on_next_key_release)
            return
        if self.state is State.fetching:
            self.on_fetching_key_event(key_event, in_bracketed_paste)
        elif self.state is State.browsing:
            self.on_browsing_key_event(key_event, in_bracketed_paste)
        elif self.state is State.searching:
            self.on_searching_key_event(key_event, in_bracketed_paste)
        elif self.state is State.accepting:
            self.on_accepting_key_event(key_event, in_bracketed_paste)

    @Handler.atomic_update
    def draw_screen(self) -> None:
        self.cmd.clear_screen()
        self.enforce_cursor_state()
        self.cmd.set_line_wrapping(False)
        if self.state is State.fetching:
            self.draw_fetching_screen()
        elif self.state in (State.browsing, State.searching):
            self.draw_browsing_screen()
        elif self.state is State.accepting:
            self.draw_accepting_screen()

    def on_resize(self, screen_size: ScreenSize) -> None:
        self.screen_size = screen_size
        self.draw_screen()

    def on_interrupt(self) -> None:
        self.quit_loop(1)

    def on_eot(self) -> None:
        self.quit_loop(1)


help_text = (
    'Change the kitty theme. If no theme name is supplied, run interactively, otherwise'
    ' change the current theme to the specified theme name.'
)
usage = '[theme name to switch to]'
OPTIONS = '''
--cache-age
type=float
default=1
Check for new themes only after the specified number of days. A value of
zero will always check for new themes. A negative value will never check
for new themes, instead raising an error if a local copy of the themes
is not available.


--reload-in
default=parent
choices=none,parent,all
By default, this kitten will signal only the parent kitty instance it is
running in to reload its config, after making changes. Use this option
to instead either not reload the config at all or in all running
kitty instances.


--dump-theme
type=bool-set
default=false
When running non-interactively, dump the specified theme to STDOUT
instead of changing kitty.conf.


--config-file-name
default=kitty.conf
The name or path to the config file to edit. Relative paths are interpreted
with respect to the kitty config directory. By default the kitty config file,
kitty.conf is edited.
'''.format


def parse_themes_args(args: List[str]) -> Tuple[ThemesCLIOptions, List[str]]:
    return parse_args(args, OPTIONS, usage, help_text, 'kitty +kitten themes', result_class=ThemesCLIOptions)


def non_interactive(cli_opts: ThemesCLIOptions, theme_name: str) -> None:
    try:
        themes = load_themes(cli_opts.cache_age)
    except NoCacheFound as e:
        raise SystemExit(str(e))
    try:
        theme = themes[theme_name]
    except KeyError:
        theme_name = theme_name.replace('\\', '')
        try:
            theme = themes[theme_name]
        except KeyError:
            raise SystemExit(f'No theme named: {theme_name}')
    if cli_opts.dump_theme:
        print(theme.raw)
        return
    theme.save_in_conf(config_dir, cli_opts.reload_in, cli_opts.config_file_name)


def main(args: List[str]) -> None:
    try:
        cli_opts, items = parse_themes_args(args[1:])
    except SystemExit as e:
        if e.code != 0:
            print(e.args[0], file=sys.stderr)
            input(_('Press Enter to quit'))
        return None
    if len(items) > 1:
        items = [' '.join(items)]
    if len(items) == 1:
        return non_interactive(cli_opts, items[0])

    loop = Loop()
    with cached_values_for('themes-kitten') as cached_values:
        handler = ThemesHandler(cached_values, cli_opts)
        loop.loop(handler)
    if loop.return_code != 0:
        if handler.report_traceback_on_exit:
            print(handler.report_traceback_on_exit, file=sys.stderr)
            input('Press Enter to quit.')
    if handler.state is State.fetching:
        # asyncio uses non-daemonic threads in its ThreadPoolExecutor
        # so we will hang here till the download completes without
        # os._exit
        os._exit(loop.return_code)
    raise SystemExit(loop.return_code)


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
