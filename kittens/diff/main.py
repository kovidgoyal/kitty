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
from typing import (
    Any, DefaultDict, Dict, Iterable, List, Optional, Tuple, Union
)

from kitty.cli import CONFIG_HELP, parse_args
from kitty.cli_stub import DiffCLIOptions
from kitty.conf.utils import KittensKeyAction
from kitty.constants import appname
from kitty.fast_data_types import wcswidth
from kitty.key_encoding import EventType, KeyEvent
from kitty.options_stub import DiffOptions
from kitty.utils import ScreenSize

from ..tui.handler import Handler
from ..tui.images import ImageManager, Placement
from ..tui.line_edit import LineEdit
from ..tui.loop import Loop
from ..tui.operations import styled
from . import global_data
from .collect import (
    Collection, create_collection, data_for_path, lines_for_path, sanitize,
    set_highlight_data, add_remote_dir
)
from .config import init_config
from .patch import Differ, Patch, set_diff_command, worker_processes
from .render import (
    ImagePlacement, ImageSupportWarning, Line, LineRef, Reference, render_diff
)
from .search import BadRegex, Search

try:
    from .highlight import (
        DiffHighlight, highlight_collection, initialize_highlighter
    )
    has_highlighter = True
    DiffHighlight
except ImportError:
    has_highlighter = False

    def highlight_collection(collection: 'Collection', aliases: Optional[Dict[str, str]] = None) -> Union[str, Dict[str, 'DiffHighlight']]:
        return ''


INITIALIZING, COLLECTED, DIFFED, COMMAND, MESSAGE = range(5)


def generate_diff(collection: Collection, context: int) -> Union[str, Dict[str, Patch]]:
    d = Differ()

    for path, item_type, changed_path in collection:
        if item_type == 'diff':
            is_binary = isinstance(data_for_path(path), bytes) or isinstance(data_for_path(changed_path), bytes)
            if not is_binary:
                assert changed_path is not None
                d.add_diff(path, changed_path)

    return d(context)


class DiffHandler(Handler):

    image_manager_class = ImageManager

    def __init__(self, args: DiffCLIOptions, opts: DiffOptions, left: str, right: str) -> None:
        self.state = INITIALIZING
        self.message = ''
        self.current_search_is_regex = True
        self.current_search: Optional[Search] = None
        self.line_edit = LineEdit()
        self.opts = opts
        self.left, self.right = left, right
        self.report_traceback_on_exit: Union[str, Dict[str, Patch], None] = None
        self.args = args
        self.scroll_pos = self.max_scroll_pos = 0
        self.current_context_count = self.original_context_count = self.args.context
        if self.current_context_count < 0:
            self.current_context_count = self.original_context_count = self.opts.num_context_lines
        self.highlighting_done = False
        self.restore_position: Optional[Reference] = None
        for key_def, action in self.opts.key_definitions.items():
            self.add_shortcut(action, key_def)

    def perform_action(self, action: KittensKeyAction) -> None:
        func, args = action
        if func == 'quit':
            self.quit_loop(0)
            return
        if self.state <= DIFFED:
            if func == 'scroll_by':
                return self.scroll_lines(int(args[0]))
            if func == 'scroll_to':
                where = str(args[0])
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
                    new_ctx += int(to)
                return self.change_context_count(new_ctx)
            if func == 'start_search':
                self.start_search(bool(args[0]), bool(args[1]))
                return

    def create_collection(self) -> None:

        def collect_done(collection: Collection) -> None:
            self.collection = collection
            self.state = COLLECTED
            self.generate_diff()

        def collect(left: str, right: str) -> None:
            collection = create_collection(left, right)
            self.asyncio_loop.call_soon_threadsafe(collect_done, collection)

        self.asyncio_loop.run_in_executor(None, collect, self.left, self.right)

    def generate_diff(self) -> None:

        def diff_done(diff_map: Union[str, Dict[str, Patch]]) -> None:
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
            if has_highlighter and not self.highlighting_done:
                from .highlight import StyleNotFound
                self.highlighting_done = True
                try:
                    initialize_highlighter(self.opts.pygments_style)
                except StyleNotFound as e:
                    self.report_traceback_on_exit = str(e)
                    self.quit_loop(1)
                    return
                self.syntax_highlight()

        def diff(collection: Collection, current_context_count: int) -> None:
            diff_map = generate_diff(collection, current_context_count)
            self.asyncio_loop.call_soon_threadsafe(diff_done, diff_map)

        self.asyncio_loop.run_in_executor(None, diff, self.collection, self.current_context_count)

    def syntax_highlight(self) -> None:

        def highlighting_done(hdata: Union[str, Dict[str, 'DiffHighlight']]) -> None:
            if isinstance(hdata, str):
                self.report_traceback_on_exit = hdata
                self.quit_loop(1)
                return
            set_highlight_data(hdata)
            self.render_diff()
            self.draw_screen()

        def highlight(collection: Collection, aliases: Optional[Dict[str, str]] = None) -> None:
            result = highlight_collection(collection, aliases)
            self.asyncio_loop.call_soon_threadsafe(highlighting_done, result)

        self.asyncio_loop.run_in_executor(None, highlight, self.collection, self.opts.syntax_aliases)

    def calculate_statistics(self) -> None:
        self.added_count = self.collection.added_count
        self.removed_count = self.collection.removed_count
        for patch in self.diff_map.values():
            self.added_count += patch.added_count
            self.removed_count += patch.removed_count

    def render_diff(self) -> None:
        self.diff_lines: Tuple[Line, ...] = tuple(render_diff(self.collection, self.diff_map, self.args, self.screen_size.cols, self.image_manager))
        self.margin_size = render_diff.margin_size
        self.ref_path_map: DefaultDict[str, List[Tuple[int, Reference]]] = defaultdict(list)
        for i, l in enumerate(self.diff_lines):
            self.ref_path_map[l.ref.path].append((i, l.ref))
        self.max_scroll_pos = len(self.diff_lines) - self.num_lines
        if self.current_search is not None:
            self.current_search(self.diff_lines, self.margin_size, self.screen_size.cols)

    @property
    def current_position(self) -> Reference:
        return self.diff_lines[min(len(self.diff_lines) - 1, self.scroll_pos)].ref

    @current_position.setter
    def current_position(self, ref: Reference) -> None:
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
    def num_lines(self) -> int:
        return self.screen_size.rows - 1

    def scroll_to_next_change(self, backwards: bool = False) -> None:
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

    def scroll_to_next_match(self, backwards: bool = False, include_current: bool = False) -> None:
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

    def set_scrolling_region(self) -> None:
        self.cmd.set_scrolling_region(self.screen_size, 0, self.num_lines - 2)

    def scroll_lines(self, amt: int = 1) -> None:
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

    def init_terminal_state(self) -> None:
        self.cmd.set_line_wrapping(False)
        self.cmd.set_window_title(global_data.title)
        self.cmd.set_default_colors(
            fg=self.opts.foreground, bg=self.opts.background,
            cursor=self.opts.foreground, select_fg=self.opts.select_fg,
            select_bg=self.opts.select_bg)
        self.cmd.set_cursor_shape('bar')

    def finalize(self) -> None:
        self.cmd.set_default_colors()
        self.cmd.set_cursor_visible(True)
        self.cmd.set_scrolling_region()

    def initialize(self) -> None:
        self.init_terminal_state()
        self.set_scrolling_region()
        self.draw_screen()
        self.create_collection()

    def enforce_cursor_state(self) -> None:
        self.cmd.set_cursor_visible(self.state == COMMAND)

    def draw_lines(self, num: int, offset: int = 0) -> None:
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

    def update_image_placement_for_resend(self, image_id: int, pl: Placement) -> bool:
        offset = self.scroll_pos
        limit = len(self.diff_lines)
        in_image = False

        def adjust(row: int, candidate: ImagePlacement, is_left: bool) -> bool:
            if candidate.image.image_id == image_id:
                q = self.xpos_for_image(row, candidate, is_left)
                if q is not None:
                    pl.x = q[0]
                    pl.y = row
                    return True
            return False

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
                    if adjust(row, left_placement, True):
                        return True
                    in_image = True
                if right_placement is not None:
                    if adjust(row, right_placement, False):
                        return True
                    in_image = True
        return False

    def place_images(self) -> None:
        self.image_manager.update_image_placement_for_resend = self.update_image_placement_for_resend
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

    def xpos_for_image(self, row: int, placement: ImagePlacement, is_left: bool) -> Optional[Tuple[int, float]]:
        xpos = (0 if is_left else (self.screen_size.cols // 2)) + placement.image.margin_size
        image_height_in_rows = placement.image.rows
        topmost_visible_row = placement.row
        num_visible_rows = image_height_in_rows - topmost_visible_row
        visible_frac = min(num_visible_rows / image_height_in_rows, 1)
        if visible_frac <= 0:
            return None
        return xpos, visible_frac

    def place_image(self, row: int, placement: ImagePlacement, is_left: bool) -> None:
        q = self.xpos_for_image(row, placement, is_left)
        if q is not None:
            xpos, visible_frac = q
            height = int(visible_frac * placement.image.height)
            top = placement.image.height - height
            self.image_manager.show_image(placement.image.image_id, xpos, row, src_rect=(
                0, top, placement.image.width, height))

    def draw_screen(self) -> None:
        self.enforce_cursor_state()
        if self.state < DIFFED:
            self.cmd.clear_screen()
            self.write(_('Calculating diff, please wait...'))
            return
        self.cmd.clear_images_on_screen()
        self.cmd.set_cursor_position(0, 0)
        self.draw_lines(self.num_lines)
        self.draw_status_line()

    def draw_status_line(self) -> None:
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

    def change_context_count(self, new_ctx: int) -> None:
        new_ctx = max(0, new_ctx)
        if new_ctx != self.current_context_count:
            self.current_context_count = new_ctx
            self.state = COLLECTED
            self.generate_diff()
            self.restore_position = self.current_position
            self.draw_screen()

    def start_search(self, is_regex: bool, is_backward: bool) -> None:
        if self.state != DIFFED:
            self.cmd.bell()
            return
        self.state = COMMAND
        self.line_edit.clear()
        self.line_edit.add_text('?' if is_backward else '/')
        self.current_search_is_regex = is_regex
        self.draw_status_line()

    def do_search(self) -> None:
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

    def on_key_event(self, key_event: KeyEvent, in_bracketed_paste: bool = False) -> None:
        if key_event.text:
            if self.state is COMMAND:
                self.line_edit.on_text(key_event.text, in_bracketed_paste)
                self.draw_status_line()
                return
            if self.state is MESSAGE:
                self.state = DIFFED
                self.draw_status_line()
                return
        else:
            if self.state is MESSAGE:
                if key_event.type is not EventType.RELEASE:
                    self.state = DIFFED
                    self.draw_status_line()
                return
            if self.state is COMMAND:
                if self.line_edit.on_key(key_event):
                    if not self.line_edit.current_input:
                        self.state = DIFFED
                    self.draw_status_line()
                    return
                if key_event.matches('enter'):
                    self.state = DIFFED
                    self.do_search()
                    self.line_edit.clear()
                    self.draw_screen()
                    return
                if key_event.matches('esc'):
                    self.state = DIFFED
                    self.draw_status_line()
                    return
            if self.state >= DIFFED and self.current_search is not None and key_event.matches('esc'):
                self.current_search = None
                self.draw_screen()
                return
            if key_event.type is EventType.RELEASE:
                return
        action = self.shortcut_action(key_event)
        if action is not None:
            return self.perform_action(action)

    def on_resize(self, screen_size: ScreenSize) -> None:
        self.screen_size = screen_size
        self.set_scrolling_region()
        if self.state > COLLECTED:
            self.image_manager.delete_all_sent_images()
            self.render_diff()
        self.draw_screen()

    def on_interrupt(self) -> None:
        self.quit_loop(1)

    def on_eot(self) -> None:
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


class ShowWarning:

    def __init__(self) -> None:
        self.warnings: List[str] = []

    def __call__(self, message: Any, category: Any, filename: str, lineno: int, file: object = None, line: object = None) -> None:
        if category is ImageSupportWarning and isinstance(message, str):
            showwarning.warnings.append(message)


showwarning = ShowWarning()
help_text = 'Show a side-by-side diff of the specified files/directories. You can also use ssh:hostname:remote-file-path to diff remote files.'
usage = 'file_or_directory_left file_or_directory_right'


def terminate_processes(processes: Iterable[int]) -> None:
    for pid in processes:
        with suppress(Exception):
            os.kill(pid, signal.SIGKILL)


def get_ssh_file(hostname: str, rpath: str) -> str:
    import io
    import shutil
    import tarfile
    tdir = tempfile.mkdtemp(suffix=f'-{hostname}')
    add_remote_dir(tdir)
    atexit.register(shutil.rmtree, tdir)
    is_abs = rpath.startswith('/')
    rpath = rpath.lstrip('/')
    cmd = ['ssh', hostname, 'tar', '-c', '-f', '-']
    if is_abs:
        cmd.extend(('-C', '/'))
    cmd.append(rpath)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    assert p.stdout is not None
    raw = p.stdout.read()
    if p.wait() != 0:
        raise SystemExit(p.returncode)
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as tf:
        members = tf.getmembers()
        tf.extractall(tdir)
        if len(members) == 1:
            for root, dirs, files in os.walk(tdir):
                if files:
                    return os.path.join(root, files[0])
        return os.path.abspath(os.path.join(tdir, rpath))


def get_remote_file(path: str) -> str:
    if path.startswith('ssh:'):
        parts = path.split(':', 2)
        if len(parts) == 3:
            return get_ssh_file(parts[1], parts[2])
    return path


def main(args: List[str]) -> None:
    warnings.showwarning = showwarning
    cli_opts, items = parse_args(args[1:], OPTIONS, usage, help_text, 'kitty +kitten diff', result_class=DiffCLIOptions)
    if len(items) != 2:
        raise SystemExit('You must specify exactly two files/directories to compare')
    left, right = items
    global_data.title = _('{} vs. {}').format(left, right)
    opts = init_config(cli_opts)
    set_diff_command(opts.diff_cmd)
    lines_for_path.replace_tab_by = opts.replace_tab_by
    left, right = map(get_remote_file, (left, right))
    if os.path.isdir(left) != os.path.isdir(right):
        raise SystemExit('The items to be diffed should both be either directories or files. Comparing a directory to a file is not valid.')
    for f in left, right:
        if not os.path.exists(f):
            raise SystemExit('{} does not exist'.format(f))

    loop = Loop()
    handler = DiffHandler(cli_opts, opts, left, right)
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
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
elif __name__ == '__conf__':
    from .config_data import all_options
    sys.all_options = all_options  # type: ignore
