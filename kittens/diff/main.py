#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import atexit
import os
import signal
import subprocess
import sys
import tempfile
import warnings
from collections import defaultdict
from contextlib import suppress
from functools import partial
from gettext import gettext as _

from kitty.cli import CONFIG_HELP, parse_args
from kitty.constants import appname
from kitty.fast_data_types import wcswidth
from kitty.key_encoding import ESCAPE, RELEASE, enter_key

from ..tui.handler import Handler
from ..tui.images import ImageManager
from ..tui.line_edit import LineEdit
from ..tui.loop import Loop
from ..tui.operations import styled
from .collect import (
    create_collection, data_for_path, lines_for_path, sanitize,
    set_highlight_data
)
from .config import init_config
from .patch import Differ, set_diff_command, worker_processes
from .render import ImageSupportWarning, LineRef, render_diff
from .search import BadRegex, Search

try:
    from .highlight import initialize_highlighter, highlight_collection
except ImportError:
    initialize_highlighter = highlight_collection = None


INITIALIZING, COLLECTED, DIFFED, COMMAND, MESSAGE = range(5)


def generate_diff(collection, context):
    d = Differ()

    for path, item_type, changed_path in collection:
        if item_type == 'diff':
            is_binary = isinstance(data_for_path(path), bytes) or isinstance(data_for_path(changed_path), bytes)
            if not is_binary:
                d.add_diff(path, changed_path)

    return d(context)


class DiffHandler(Handler):

    image_manager_class = ImageManager

    def __init__(self, args, opts, left, right):
        self.state = INITIALIZING
        self.message = ''
        self.current_search_is_regex = True
        self.current_search = None
        self.line_edit = LineEdit()
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
                if 'match' in where:
                    return self.scroll_to_next_match(backwards='prev' in where)
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
            if func == 'start_search':
                self.start_search(*args)
                return

    def create_collection(self):

        def collect_done(collection):
            self.collection = collection
            self.state = COLLECTED
            self.generate_diff()

        def collect(left, right):
            collection = create_collection(left, right)
            self.asyncio_loop.call_soon_threadsafe(collect_done, collection)

        self.asyncio_loop.run_in_executor(None, collect, self.left, self.right)

    def generate_diff(self):

        def diff_done(diff_map):
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
                self.syntax_highlight()

        def diff(collection, current_context_count):
            diff_map = generate_diff(collection, current_context_count)
            self.asyncio_loop.call_soon_threadsafe(diff_done, diff_map)

        self.asyncio_loop.run_in_executor(None, diff, self.collection, self.current_context_count)

    def syntax_highlight(self):

        def highlighting_done(hdata):
            if isinstance(hdata, str):
                self.report_traceback_on_exit = hdata
                self.quit_loop(1)
                return
            set_highlight_data(hdata)
            self.render_diff()
            self.draw_screen()

        def highlight(*a):
            result = highlight_collection(*a)
            self.asyncio_loop.call_soon_threadsafe(highlighting_done, result)

        self.asyncio_loop.run_in_executor(None, highlight, self.collection, self.opts.syntax_aliases)

    def calculate_statistics(self):
        self.added_count = self.collection.added_count
        self.removed_count = self.collection.removed_count
        for patch in self.diff_map.values():
            self.added_count += patch.added_count
            self.removed_count += patch.removed_count

    def render_diff(self):
        self.diff_lines = tuple(render_diff(self.collection, self.diff_map, self.args, self.screen_size.cols, self.image_manager))
        self.margin_size = render_diff.margin_size
        self.ref_path_map = defaultdict(list)
        for i, l in enumerate(self.diff_lines):
            self.ref_path_map[l.ref.path].append((i, l.ref))
        self.max_scroll_pos = len(self.diff_lines) - self.num_lines
        if self.current_search is not None:
            self.current_search(self.diff_lines, self.margin_size, self.screen_size.cols)

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
            self.scroll_pos = max(0, min(num, self.max_scroll_pos))

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

    def scroll_to_next_match(self, backwards=False, include_current=False):
        if self.current_search is not None:
            offset = 0 if include_current else 1
            if backwards:
                r = range(self.scroll_pos - offset, -1, -1)
            else:
                r = range(self.scroll_pos + offset, len(self.diff_lines))
            for i in r:
                if i in self.current_search:
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
        self.cmd.set_default_colors(
            fg=self.opts.foreground, bg=self.opts.background,
            cursor=self.opts.foreground, select_fg=self.opts.select_fg,
            select_bg=self.opts.select_bg)
        self.cmd.set_cursor_shape('bar')

    def finalize(self):
        self.cmd.set_default_colors()
        self.cmd.set_cursor_visible(True)
        self.cmd.set_scrolling_region()

    def initialize(self):
        self.init_terminal_state()
        self.set_scrolling_region()
        self.draw_screen()
        self.create_collection()

    def enforce_cursor_state(self):
        self.cmd.set_cursor_visible(self.state == COMMAND)

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
            if self.current_search is not None:
                self.current_search.highlight_line(self.write, lpos)
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
        self.enforce_cursor_state()
        self.cmd.set_cursor_position(0, self.num_lines)
        self.cmd.clear_to_eol()
        if self.state is COMMAND:
            self.line_edit.write(self.write)
        elif self.state is MESSAGE:
            self.cmd.styled(self.message, reverse=True)
        else:
            sp = '{:.0%}'.format(self.scroll_pos/self.max_scroll_pos) if self.scroll_pos and self.max_scroll_pos else '0%'
            scroll_frac = styled(sp, fg=self.opts.margin_fg)
            if self.current_search is None:
                counts = '{}{}{}'.format(
                        styled(str(self.added_count), fg=self.opts.highlight_added_bg),
                        styled(',', fg=self.opts.margin_fg),
                        styled(str(self.removed_count), fg=self.opts.highlight_removed_bg)
                )
            else:
                counts = styled('{} matches'.format(len(self.current_search)), fg=self.opts.margin_fg)
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

    def start_search(self, is_regex, is_backward):
        if self.state != DIFFED:
            self.cmd.bell()
            return
        self.state = COMMAND
        self.line_edit.clear()
        self.line_edit.add_text('?' if is_backward else '/')
        self.current_search_is_regex = is_regex
        self.draw_status_line()

    def do_search(self):
        self.current_search = None
        query = self.line_edit.current_input
        if len(query) < 2:
            return
        try:
            self.current_search = Search(self.opts, query[1:], self.current_search_is_regex, query[0] == '?')
        except BadRegex:
            self.state = MESSAGE
            self.message = sanitize(_('Bad regex: {}').format(query[1:]))
            self.cmd.bell()
        else:
            if self.current_search(self.diff_lines, self.margin_size, self.screen_size.cols):
                self.scroll_to_next_match(include_current=True)
            else:
                self.state = MESSAGE
                self.message = sanitize(_('No matches found'))
                self.cmd.bell()

    def on_text(self, text, in_bracketed_paste=False):
        if self.state is COMMAND:
            self.line_edit.on_text(text, in_bracketed_paste)
            self.draw_status_line()
            return
        if self.state is MESSAGE:
            self.state = DIFFED
            self.draw_status_line()
            return
        action = self.shortcut_action(text)
        if action is not None:
            return self.perform_action(action)

    def on_key(self, key_event):
        if self.state is MESSAGE:
            if key_event.type is not RELEASE:
                self.state = DIFFED
                self.draw_status_line()
            return
        if self.state is COMMAND:
            if self.line_edit.on_key(key_event):
                if not self.line_edit.current_input:
                    self.state = DIFFED
                self.draw_status_line()
                return
        if key_event.type is RELEASE:
            return
        if self.state is COMMAND:
            if key_event.key is ESCAPE:
                self.state = DIFFED
                self.draw_status_line()
                return
            if key_event is enter_key:
                self.state = DIFFED
                self.do_search()
                self.line_edit.clear()
                self.draw_screen()
                return
        if self.state >= DIFFED and self.current_search is not None and key_event.key is ESCAPE:
            self.current_search = None
            self.draw_screen()
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
Syntax: :italic:`name=value`. For example: :italic:`-o background=gray`

'''.format, config_help=CONFIG_HELP.format(conf_name='diff', appname=appname))


def showwarning(message, category, filename, lineno, file=None, line=None):
    if category is ImageSupportWarning:
        showwarning.warnings.append(message)


showwarning.warnings = []
help_text = 'Show a side-by-side diff of the specified files/directories. You can also use ssh:hostname:remote-file-path to diff remote files.'
usage = 'file_or_directory_left file_or_directory_right'


def terminate_processes(processes):
    for pid in processes:
        with suppress(Exception):
            os.kill(pid, signal.SIGKILL)


def get_remote_file(path):
    if path.startswith('ssh:'):
        parts = path.split(':', 2)
        if len(parts) == 3:
            hostname, rpath = parts[1:]
            with tempfile.NamedTemporaryFile(suffix='-' + os.path.basename(rpath), prefix='remote:', delete=False) as tf:
                atexit.register(os.remove, tf.name)
                p = subprocess.Popen(['ssh', hostname, 'cat', rpath], stdout=tf)
                if p.wait() != 0:
                    raise SystemExit(p.returncode)
                return tf.name
    return path


def main(args):
    warnings.showwarning = showwarning
    args, items = parse_args(args[1:], OPTIONS, usage, help_text, 'kitty +kitten diff')
    if len(items) != 2:
        raise SystemExit('You must specify exactly two files/directories to compare')
    left, right = items
    main.title = _('{} vs. {}').format(left, right)
    if os.path.isdir(left) != os.path.isdir(right):
        raise SystemExit('The items to be diffed should both be either directories or files. Comparing a directory to a file is not valid.')
    opts = init_config(args)
    set_diff_command(opts.diff_cmd)
    lines_for_path.replace_tab_by = opts.replace_tab_by
    left, right = map(get_remote_file, (left, right))
    for f in left, right:
        if not os.path.exists(f):
            raise SystemExit('{} does not exist'.format(f))

    loop = Loop()
    handler = DiffHandler(args, opts, left, right)
    loop.loop(handler)
    for message in showwarning.warnings:
        from kitty.utils import safe_print
        safe_print(message, file=sys.stderr)
    highlight_processes = getattr(highlight_collection, 'processes', ())
    terminate_processes(tuple(highlight_processes))
    terminate_processes(tuple(worker_processes))
    if loop.return_code != 0:
        if handler.report_traceback_on_exit:
            print(handler.report_traceback_on_exit, file=sys.stderr)
            input('Press Enter to quit.')
        raise SystemExit(loop.return_code)


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    sys.cli_docs['usage'] = usage
    sys.cli_docs['options'] = OPTIONS
    sys.cli_docs['help_text'] = help_text
elif __name__ == '__conf__':
    from .config import all_options
    sys.all_options = all_options
