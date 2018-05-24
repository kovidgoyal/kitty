#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import sys
import warnings
from collections import defaultdict
from functools import partial
from gettext import gettext as _

from kitty.cli import CONFIG_HELP, appname, parse_args
from kitty.fast_data_types import wcswidth
from kitty.key_encoding import RELEASE

from ..tui.handler import Handler
from ..tui.images import ImageManager
from ..tui.loop import Loop
from ..tui.operations import styled
from .collect import (
    create_collection, data_for_path, lines_for_path, set_highlight_data
)
from .config import init_config
from .patch import Differ, set_diff_command
from .render import ImageSupportWarning, LineRef, render_diff

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

    image_manager_class = ImageManager

    def __init__(self, args, opts, left, right):
        self.state = INITIALIZING
        self.opts = opts
        self.left, self.right = left, right
        self.report_traceback_on_exit = None
        self.args = args
        self.scroll_pos = self.max_scroll_pos = 0
        self.current_context_count = self.original_context_count = self.args.context
        if self.current_context_count < 0:
            self.current_context_count = self.original_context_count = self.opts.num_context_lines
        self.highlighting_done = False
        self.restore_position = None
        for key_def, action in self.opts.key_definitions.items():
            self.add_shortcut(action, *key_def)

    def perform_action(self, action):
        func, args = action
        if func == 'quit':
            self.quit_loop(0)
            return
        if self.state <= DIFFED:
            if func == 'scroll_by':
                return self.scroll_lines(*args)
            if func == 'scroll_to':
                where = args[0]
                if 'change' in where:
                    return self.scroll_to_next_change(backwards='prev' in where)
                if 'page' in where:
                    amt = self.num_lines * (1 if 'next' in where else -1)
                else:
                    amt = len(self.diff_lines) * (1 if 'end' in where else -1)
                return self.scroll_lines(amt)
            if func == 'change_context':
                new_ctx = self.current_context_count
                to = args[0]
                if to == 'all':
                    new_ctx = 100000
                elif to == 'default':
                    new_ctx = self.original_context_count
                else:
                    new_ctx += to
                return self.change_context_count(new_ctx)

    def create_collection(self):
        self.start_job('collect', create_collection, self.left, self.right)

    def generate_diff(self):
        self.start_job('diff', generate_diff, self.collection, self.current_context_count)

    def calculate_statistics(self):
        self.added_count = self.collection.added_count
        self.removed_count = self.collection.removed_count
        for patch in self.diff_map.values():
            self.added_count += patch.added_count
            self.removed_count += patch.removed_count

    def render_diff(self):
        self.diff_lines = tuple(render_diff(self.collection, self.diff_map, self.args, self.screen_size.cols, self.image_manager))
        self.ref_path_map = defaultdict(list)
        for i, l in enumerate(self.diff_lines):
            self.ref_path_map[l.ref.path].append((i, l.ref))
        self.max_scroll_pos = len(self.diff_lines) - self.num_lines

    @property
    def current_position(self):
        return self.diff_lines[min(len(self.diff_lines) - 1, self.scroll_pos)].ref

    @current_position.setter
    def current_position(self, ref):
        num = None
        if isinstance(ref.extra, LineRef):
            sln = ref.extra.src_line_number
            for i, q in self.ref_path_map[ref.path]:
                if isinstance(q.extra, LineRef):
                    if q.extra.src_line_number >= sln:
                        if q.extra.src_line_number == sln:
                            num = i
                        break
                    num = i
        if num is None:
            for i, q in self.ref_path_map[ref.path]:
                num = i
                break

        if num is not None:
            self.scroll_pos = min(num, self.max_scroll_pos)

    @property
    def num_lines(self):
        return self.screen_size.rows - 1

    def scroll_to_next_change(self, backwards=False):
        if backwards:
            r = range(self.scroll_pos - 1, -1, -1)
        else:
            r = range(self.scroll_pos + 1, len(self.diff_lines))
        for i in r:
            line = self.diff_lines[i]
            if line.is_change_start:
                self.scroll_lines(i - self.scroll_pos)
                return
        self.cmd.bell()

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
        self.draw_status_line()

    def init_terminal_state(self):
        self.cmd.set_line_wrapping(False)
        self.cmd.set_window_title(main.title)
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
        self.cmd.set_scrolling_region()

    def draw_lines(self, num, offset=0):
        offset += self.scroll_pos
        image_involved = False
        limit = len(self.diff_lines)
        for i in range(num):
            lpos = offset + i
            if lpos >= limit:
                text = ''
            else:
                line = self.diff_lines[lpos]
                text = line.text
                if line.image_data is not None:
                    image_involved = True
            self.write('\r\x1b[K' + text + '\x1b[0m')
            if i < num - 1:
                self.write('\n')
        if image_involved:
            self.place_images()

    def place_images(self):
        self.cmd.clear_images_on_screen()
        offset = self.scroll_pos
        limit = len(self.diff_lines)
        in_image = False
        for row in range(self.num_lines):
            lpos = offset + row
            if lpos >= limit:
                break
            line = self.diff_lines[lpos]
            if in_image:
                if line.image_data is None:
                    in_image = False
                continue
            if line.image_data is not None:
                left_placement, right_placement = line.image_data
                if left_placement is not None:
                    self.place_image(row, left_placement, True)
                    in_image = True
                if right_placement is not None:
                    self.place_image(row, right_placement, False)
                    in_image = True

    def place_image(self, row, placement, is_left):
        xpos = (0 if is_left else (self.screen_size.cols // 2)) + placement.image.margin_size
        image_height_in_rows = placement.image.rows
        topmost_visible_row = placement.row
        num_visible_rows = image_height_in_rows - topmost_visible_row
        visible_frac = min(num_visible_rows / image_height_in_rows, 1)
        if visible_frac > 0:
            height = int(visible_frac * placement.image.height)
            top = placement.image.height - height
            self.image_manager.show_image(placement.image.image_id, xpos, row, src_rect=(
                0, top, placement.image.width, height))

    def draw_screen(self):
        self.enforce_cursor_state()
        if self.state < DIFFED:
            self.cmd.clear_screen()
            self.write(_('Calculating diff, please wait...'))
            return
        self.cmd.clear_images_on_screen()
        self.cmd.set_cursor_position(0, 0)
        self.draw_lines(self.num_lines)
        self.draw_status_line()

    def draw_status_line(self):
        if self.state < DIFFED:
            return
        self.cmd.set_cursor_position(0, self.num_lines)
        self.cmd.clear_to_eol()
        scroll_frac = styled('{:.0%}'.format(self.scroll_pos / (self.max_scroll_pos or 1)), fg=self.opts.margin_fg)
        counts = '{}{}{}'.format(
                styled(str(self.added_count), fg=self.opts.highlight_added_bg),
                styled(',', fg=self.opts.margin_fg),
                styled(str(self.removed_count), fg=self.opts.highlight_removed_bg)
        )
        suffix = counts + '  ' + scroll_frac
        prefix = styled(':', fg=self.opts.margin_fg)
        filler = self.screen_size.cols - wcswidth(prefix) - wcswidth(suffix)
        text = '{}{}{}'.format(prefix, ' ' * filler, suffix)
        self.write(text)

    def change_context_count(self, new_ctx):
        new_ctx = max(0, new_ctx)
        if new_ctx != self.current_context_count:
            self.current_context_count = new_ctx
            self.state = COLLECTED
            self.generate_diff()
            self.restore_position = self.current_position
            self.draw_screen()

    def on_text(self, text, in_bracketed_paste=False):
        action = self.shortcut_action(text)
        if action is not None:
            return self.perform_action(action)

    def on_key(self, key_event):
        if key_event.type is RELEASE:
            return
        action = self.shortcut_action(key_event)
        if action is not None:
            return self.perform_action(action)

    def on_resize(self, screen_size):
        self.screen_size = screen_size
        self.set_scrolling_region()
        if self.state > COLLECTED:
            self.image_manager.delete_all_sent_images()
            self.render_diff()
        self.draw_screen()

    def on_job_done(self, job_id, job_result):
        if 'tb' in job_result:
            self.report_traceback_on_exit = job_result['tb']
            self.quit_loop(1)
            return
        if job_id == 'collect':
            self.collection = job_result['result']
            self.state = COLLECTED
            self.generate_diff()
        elif job_id == 'diff':
            diff_map = job_result['result']
            if isinstance(diff_map, str):
                self.report_traceback_on_exit = diff_map
                self.quit_loop(1)
                return
            self.state = DIFFED
            self.diff_map = diff_map
            self.calculate_statistics()
            self.render_diff()
            self.scroll_pos = 0
            if self.restore_position is not None:
                self.current_position = self.restore_position
                self.restore_position = None
            self.draw_screen()
            if initialize_highlighter is not None and not self.highlighting_done:
                from .highlight import StyleNotFound
                self.highlighting_done = True
                try:
                    initialize_highlighter(self.opts.pygments_style)
                except StyleNotFound as e:
                    self.report_traceback_on_exit = str(e)
                    self.quit_loop(1)
                    return
                self.start_job('highlight', highlight_collection, self.collection, self.opts.syntax_aliases)
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
default=-1
Number of lines of context to show between changes. Negative values
use the number set in diff.conf


--config
type=list
{config_help}


--override -o
type=list
Override individual configuration options, can be specified multiple times.
Syntax: |_ name=value|. For example: |_ -o background=gray|

'''.format, config_help=CONFIG_HELP.format(conf_name='diff', appname=appname))


def showwarning(message, category, filename, lineno, file=None, line=None):
    if category is ImageSupportWarning:
        showwarning.warnings.append(message)


showwarning.warnings = []


def main(args):
    warnings.showwarning = showwarning
    msg = 'Show a side-by-side diff of the specified files/directories'
    args, items = parse_args(args[1:], OPTIONS, 'file_or_directory file_or_directory', msg, 'kitty +kitten diff')
    if len(items) != 2:
        raise SystemExit('You must specify exactly two files/directories to compare')
    left, right = items
    main.title = _('{} vs. {}').format(left, right)
    if os.path.isdir(left) != os.path.isdir(right):
        raise SystemExit('The items to be diffed should both be either directories or files. Comparing a directory to a file is not valid.')
    opts = init_config(args)
    set_diff_command(opts.diff_cmd)
    lines_for_path.replace_tab_by = opts.replace_tab_by

    loop = Loop()
    handler = DiffHandler(args, opts, left, right)
    loop.loop(handler)
    for message in showwarning.warnings:
        from kitty.utils import safe_print
        safe_print(message, file=sys.stderr)
    if loop.return_code != 0:
        if handler.report_traceback_on_exit:
            print(handler.report_traceback_on_exit, file=sys.stderr)
            input('Press Enter to quit.')
        raise SystemExit(loop.return_code)


if __name__ == '__main__':
    main(sys.argv)
