#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import sys
from functools import partial
from gettext import gettext as _

from kitty.cli import CONFIG_HELP, appname, parse_args
from kitty.key_encoding import (
    DOWN, END, ESCAPE, HOME, PAGE_DOWN, PAGE_UP, RELEASE, UP
)

from ..tui.handler import Handler
from ..tui.loop import Loop
from .collect import create_collection, data_for_path, set_highlight_data
from .config import init_config
from .patch import Differ
from .render import render_diff

try:
    from .highlight import initialize_highlighter, highlight_collection
except ImportError:
    initialize_highlighter = None


INITIALIZING, COLLECTED, DIFFED = range(3)


def generate_diff(collection, context):
    d = Differ()

    for path, item_type, changed_path in collection:
        if item_type == 'diff':
            is_binary = isinstance(data_for_path(path), bytes)
            if not is_binary:
                d.add_diff(path, changed_path)

    return d(context)


class DiffHandler(Handler):

    def __init__(self, args, opts, left, right):
        self.state = INITIALIZING
        self.opts = opts
        self.left, self.right = left, right
        self.report_traceback_on_exit = None
        self.args = args
        self.scroll_pos = self.max_scroll_pos = 0

    def create_collection(self):
        self.start_job('collect', create_collection, self.left, self.right)

    def generate_diff(self):
        self.start_job('diff', generate_diff, self.collection, self.args.context)

    def render_diff(self):
        self.diff_lines = tuple(render_diff(self.collection, self.diff_map, self.args, self.screen_size.cols))
        self.max_scroll_pos = len(self.diff_lines) - self.num_lines

    @property
    def num_lines(self):
        return self.screen_size.rows - 1

    def set_scrolling_region(self):
        self.cmd.set_scrolling_region(self.screen_size, 0, self.num_lines - 2)

    def scroll_lines(self, amt=1):
        new_pos = max(0, min(self.scroll_pos + amt, self.max_scroll_pos))
        if new_pos == self.scroll_pos:
            self.cmd.bell()
            return
        if abs(new_pos - self.scroll_pos) >= self.num_lines - 1:
            self.scroll_pos = new_pos
            self.draw_screen()
            return
        self.enforce_cursor_state()
        self.cmd.scroll_screen(amt)
        self.scroll_pos = new_pos
        if amt < 0:
            self.cmd.set_cursor_position(0, 0)
            self.draw_lines(-amt)
        else:
            self.cmd.set_cursor_position(0, self.num_lines - amt)
            self.draw_lines(amt, self.num_lines - amt)

    def init_terminal_state(self):
        self.cmd.set_line_wrapping(False)
        self.cmd.set_window_title('kitty +diff')
        self.cmd.set_default_colors(self.opts.foreground, self.opts.background)

    def initialize(self):
        self.init_terminal_state()
        self.set_scrolling_region()
        self.draw_screen()
        self.create_collection()

    def enforce_cursor_state(self):
        self.cmd.set_cursor_visible(self.state > DIFFED)

    def finalize(self):
        self.cmd.set_cursor_visible(True)
        self.cmd.set_default_colors()

    def draw_lines(self, num, offset=0):
        offset += self.scroll_pos
        for i in range(num):
            lpos = offset + i
            if lpos >= len(self.diff_lines):
                text = ''
            else:
                text = self.diff_lines[lpos].text
            self.write('\r' + text + '\x1b[0m')
            if i < num - 1:
                self.write('\n')

    def draw_screen(self):
        self.enforce_cursor_state()
        if self.state < DIFFED:
            self.cmd.clear_screen()
            self.write(_('Calculating diff, please wait...'))
            return
        self.cmd.clear_screen()
        self.draw_lines(self.num_lines)
        self.draw_status_line()

    def draw_status_line(self):
        self.cmd.set_cursor_position(0, self.num_lines)
        self.cmd.clear_to_eol()
        self.write(':')

    def on_text(self, text, in_bracketed_paste=False):
        if text == 'q':
            if self.state <= DIFFED:
                self.quit_loop(0)
                return
        if self.state is DIFFED:
            if text in 'jk':
                self.scroll_lines(1 if text == 'j' else -1)
                return

    def on_key(self, key_event):
        if key_event.type is RELEASE:
            return
        if key_event.key is ESCAPE:
            if self.state <= DIFFED:
                self.quit_loop(0)
                return
        if self.state is DIFFED:
            if key_event.key is UP or key_event.key is DOWN:
                self.scroll_lines(1 if key_event.key is DOWN else -1)
                return
            if key_event.key is PAGE_UP or key_event.key is PAGE_DOWN:
                amt = self.num_lines * (1 if key_event.key is PAGE_DOWN else -1)
                self.scroll_lines(amt)
                return
            if key_event.key is HOME or key_event.key is END:
                amt = len(self.diff_lines) * (1 if key_event.key is END else -1)
                self.scroll_lines(amt)
                return

    def on_resize(self, screen_size):
        self.screen_size = screen_size
        self.set_scrolling_region()
        if self.state > COLLECTED:
            self.render_diff()
        self.draw_screen()

    def on_job_done(self, job_id, job_result):
        if 'tb' in job_result:
            self.report_traceback_on_exit = job_result['tb']
            self.quit_loop(1)
            return
        if job_id == 'collect':
            self.collection = job_result['result']
            self.generate_diff()
        elif job_id == 'diff':
            diff_map = job_result['result']
            if isinstance(diff_map, str):
                self.report_traceback_on_exit = diff_map
                self.quit_loop(1)
                return
            self.state = DIFFED
            self.diff_map = diff_map
            self.render_diff()
            self.draw_screen()
            if initialize_highlighter is not None:
                initialize_highlighter()
                self.start_job('highlight', highlight_collection, self.collection)
        elif job_id == 'highlight':
            hdata = job_result['result']
            if isinstance(hdata, str):
                self.report_traceback_on_exit = diff_map
                self.quit_loop(1)
                return
            set_highlight_data(hdata)
            self.render_diff()
            self.draw_screen()

    def on_interrupt(self):
        self.quit_loop(1)

    def on_eot(self):
        self.quit_loop(1)


OPTIONS = partial('''\
--context
type=int
default=3
Number of lines of context to show between changes.


--config
type=list
{config_help}


--override -o
type=list
Override individual configuration options, can be specified multiple times.
Syntax: |_ name=value|. For example: |_ -o background=gray|

'''.format, config_help=CONFIG_HELP.format(conf_name='diff', appname=appname))


def main(args):
    msg = 'Show a side-by-side diff of the specified files/directories'
    args, items = parse_args(args[1:], OPTIONS, 'file_or_directory file_or_directory', msg, 'kitty +kitten diff')
    if len(items) != 2:
        raise SystemExit('You must specify exactly two files/directories to compare')
    left, right = items
    if os.path.isdir(left) != os.path.isdir(right):
        raise SystemExit('The items to be diffed should both be either directories or files. Comparing a directory to a file is not valid.')
    opts = init_config(args)

    loop = Loop()
    handler = DiffHandler(args, opts, left, right)
    loop.loop(handler)
    if loop.return_code != 0:
        if handler.report_traceback_on_exit:
            print(handler.report_traceback_on_exit, file=sys.stderr)
        raise SystemExit(loop.return_code)


def handle_result(args, current_char, target_window_id, boss):
    pass


if __name__ == '__main__':
    main(sys.argv)
