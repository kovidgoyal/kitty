#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import sys
import weakref
from collections import deque
from enum import IntEnum

from .child import cwd_of_process
from .config import build_ansi_color_table
from .constants import (
    ScreenGeometry, WindowGeometry, appname, get_boss, wakeup
)
from .fast_data_types import (
    BLIT_PROGRAM, CELL_BG_PROGRAM, CELL_FG_PROGRAM, CELL_PROGRAM,
    CELL_SPECIAL_PROGRAM, CSI, DCS, DECORATION, DIM, GRAPHICS_PREMULT_PROGRAM,
    GRAPHICS_PROGRAM, OSC, REVERSE, SCROLL_FULL, SCROLL_LINE, SCROLL_PAGE,
    STRIKETHROUGH, Screen, add_window, cell_size_for_window, compile_program,
    get_clipboard_string, glfw_post_empty_event, init_cell_program,
    set_clipboard_string, set_titlebar_color, set_window_render_data,
    update_window_title, update_window_visibility, viewport_for_window
)
from .keys import keyboard_mode_name
from .rgb import to_color
from .terminfo import get_capabilities
from .utils import (
    color_as_int, get_primary_selection, load_shaders, open_cmd, open_url,
    parse_color_set, sanitize_title, set_primary_selection
)


class DynamicColor(IntEnum):
    default_fg, default_bg, cursor_color, highlight_fg, highlight_bg = range(1, 6)


DYNAMIC_COLOR_CODES = {
    10: DynamicColor.default_fg,
    11: DynamicColor.default_bg,
    12: DynamicColor.cursor_color,
    17: DynamicColor.highlight_bg,
    19: DynamicColor.highlight_fg,
}
DYNAMIC_COLOR_CODES.update({k+100: v for k, v in DYNAMIC_COLOR_CODES.items()})


def calculate_gl_geometry(window_geometry, viewport_width, viewport_height, cell_width, cell_height):
    dx, dy = 2 * cell_width / viewport_width, 2 * cell_height / viewport_height
    xmargin = window_geometry.left / viewport_width
    ymargin = window_geometry.top / viewport_height
    xstart = -1 + 2 * xmargin
    ystart = 1 - 2 * ymargin
    return ScreenGeometry(xstart, ystart, window_geometry.xnum, window_geometry.ynum, dx, dy)


def load_shader_programs(semi_transparent=0, cursor_text_color=None):
    compile_program(BLIT_PROGRAM, *load_shaders('blit'))
    v, f = load_shaders('cell')

    def color_as_vec3(x):
        return 'vec3({}, {}, {})'.format(x.red / 255, x.green / 255, x.blue / 255)

    cursor_text_color = color_as_vec3(cursor_text_color) if cursor_text_color else 'bg'
    for which, p in {
            'SIMPLE': CELL_PROGRAM,
            'BACKGROUND': CELL_BG_PROGRAM,
            'SPECIAL': CELL_SPECIAL_PROGRAM,
            'FOREGROUND': CELL_FG_PROGRAM,
    }.items():
        vv, ff = v.replace('WHICH_PROGRAM', which), f.replace('WHICH_PROGRAM', which)
        for gln, pyn in {
                'REVERSE_SHIFT': REVERSE,
                'STRIKE_SHIFT': STRIKETHROUGH,
                'DIM_SHIFT': DIM,
                'DECORATION_SHIFT': DECORATION,
                'CURSOR_TEXT_COLOR': cursor_text_color,
        }.items():
            vv = vv.replace('{{{}}}'.format(gln), str(pyn), 1)
        if semi_transparent:
            vv = vv.replace('#define NOT_TRANSPARENT', '#define TRANSPARENT')
            ff = ff.replace('#define NOT_TRANSPARENT', '#define TRANSPARENT')
        compile_program(p, vv, ff)
    v, f = load_shaders('graphics')
    for which, p in {
            'SIMPLE': GRAPHICS_PROGRAM,
            'PREMULT': GRAPHICS_PREMULT_PROGRAM,
    }.items():
        ff = f.replace('ALPHA_TYPE', which)
        compile_program(p, v, ff)
    init_cell_program()


def setup_colors(screen, opts):
    screen.color_profile.update_ansi_color_table(build_ansi_color_table(opts))
    screen.color_profile.set_configured_colors(*map(color_as_int, (
        opts.foreground, opts.background, opts.cursor, opts.selection_foreground, opts.selection_background)))


class Window:

    def __init__(self, tab, child, opts, args, override_title=None):
        self.action_on_close = None
        self.layout_data = None
        self.pty_resized_once = False
        self.needs_attention = False
        self.override_title = override_title
        self.overlay_window_id = None
        self.overlay_for = None
        self.default_title = os.path.basename(child.argv[0] or appname)
        self.child_title = self.default_title
        self.title_stack = deque(maxlen=10)
        self.allow_remote_control = child.allow_remote_control
        self.id = add_window(tab.os_window_id, tab.id, self.title)
        if not self.id:
            raise Exception('No tab with id: {} in OS Window: {} was found, or the window counter wrapped'.format(tab.id, tab.os_window_id))
        self.tab_id = tab.id
        self.os_window_id = tab.os_window_id
        self.tabref = weakref.ref(tab)
        self.clipboard_control_buffers = {'p': '', 'c': ''}
        self.destroyed = False
        self.click_queue = deque(maxlen=3)
        self.geometry = WindowGeometry(0, 0, 0, 0, 0, 0)
        self.needs_layout = True
        self.is_visible_in_layout = True
        self.child, self.opts = child, opts
        cell_width, cell_height = cell_size_for_window(self.os_window_id)
        self.screen = Screen(self, 24, 80, opts.scrollback_lines, cell_width, cell_height, self.id)
        setup_colors(self.screen, opts)

    @property
    def title(self):
        return self.override_title or self.child_title

    def __repr__(self):
        return 'Window(title={}, id={}, overlay_for={}, overlay_window_id={})'.format(
                self.title, self.id, self.overlay_for, self.overlay_window_id)

    def as_dict(self, is_focused=False):
        return dict(
            id=self.id,
            is_focused=is_focused,
            title=self.override_title or self.title,
            pid=self.child.pid,
            cwd=self.child.current_cwd or self.child.cwd,
            cmdline=self.child.cmdline,
            env=self.child.environ,
        )

    @property
    def current_colors(self):
        return self.screen.color_profile.as_dict()

    def matches(self, field, pat):
        if field == 'id':
            return pat.pattern == str(self.id)
        if field == 'pid':
            return pat.pattern == str(self.child.pid)
        if field == 'title':
            return pat.search(self.override_title or self.title) is not None
        if field in 'cwd':
            return pat.search(self.child.current_cwd or self.child.cwd) is not None
        if field == 'cmdline':
            for x in self.child.cmdline:
                if pat.search(x) is not None:
                    return True
            return False
        if field == 'env':
            key_pat, val_pat = pat
            for key, val in self.child.environ.items():
                if key_pat.search(key) is not None and (
                        val_pat is None or val_pat.search(val) is not None):
                    return True
        return False

    def set_visible_in_layout(self, window_idx, val):
        val = bool(val)
        if val is not self.is_visible_in_layout:
            self.is_visible_in_layout = val
            update_window_visibility(self.os_window_id, self.tab_id, self.id, window_idx, val)
            if val:
                self.refresh()

    def refresh(self):
        self.screen.mark_as_dirty()
        wakeup()

    def update_position(self, window_geometry):
        central, tab_bar, vw, vh, cw, ch = viewport_for_window(self.os_window_id)
        self.screen_geometry = sg = calculate_gl_geometry(window_geometry, vw, vh, cw, ch)
        return sg

    def set_geometry(self, window_idx, new_geometry):
        if self.destroyed:
            return
        if self.needs_layout or new_geometry.xnum != self.screen.columns or new_geometry.ynum != self.screen.lines:
            boss = get_boss()
            self.screen.resize(new_geometry.ynum, new_geometry.xnum)
            current_pty_size = (
                self.screen.lines, self.screen.columns,
                max(0, new_geometry.right - new_geometry.left), max(0, new_geometry.bottom - new_geometry.top))
            sg = self.update_position(new_geometry)
            self.needs_layout = False
            boss.child_monitor.resize_pty(self.id, *current_pty_size)
            if not self.pty_resized_once:
                self.pty_resized_once = True
                self.child.mark_terminal_ready()
        else:
            sg = self.update_position(new_geometry)
        self.geometry = g = new_geometry
        set_window_render_data(self.os_window_id, self.tab_id, self.id, window_idx, sg.xstart, sg.ystart, sg.dx, sg.dy, self.screen, *g[:4])

    def contains(self, x, y):
        g = self.geometry
        return g.left <= x <= g.right and g.top <= y <= g.bottom

    def close(self):
        get_boss().close_window(self)

    def send_text(self, *args):
        mode = keyboard_mode_name(self.screen)
        required_mode, text = args[-2:]
        required_mode = frozenset(required_mode.split(','))
        if not required_mode & {mode, 'all'}:
            return True
        if not text:
            return True
        self.write_to_child(text)

    def write_to_child(self, data):
        if data:
            if get_boss().child_monitor.needs_write(self.id, data) is not True:
                print('Failed to write to child %d as it does not exist' % self.id, file=sys.stderr)

    def title_updated(self):
        update_window_title(self.os_window_id, self.tab_id, self.id, self.title)
        t = self.tabref()
        if t is not None:
            t.title_changed(self)
        glfw_post_empty_event()

    def set_title(self, title):
        if title:
            title = sanitize_title(title)
        self.override_title = title or None
        self.title_updated()

    # screen callbacks {{{
    def use_utf8(self, on):
        get_boss().child_monitor.set_iutf8(self.window_id, on)

    def focus_changed(self, focused):
        if focused:
            self.needs_attention = False
            if self.screen.focus_tracking_enabled:
                self.screen.send_escape_code_to_child(CSI, 'I')
        else:
            if self.screen.focus_tracking_enabled:
                self.screen.send_escape_code_to_child(CSI, 'O')

    def title_changed(self, new_title):
        self.child_title = sanitize_title(new_title or self.default_title)
        if self.override_title is None:
            self.title_updated()

    def icon_changed(self, new_icon):
        pass  # TODO: Implement this

    @property
    def is_active(self):
        return get_boss().active_window is self

    def on_bell(self):
        if not self.is_active:
            self.needs_attention = True
            tab = self.tabref()
            if tab is not None:
                tab.on_bell(self)

    def change_titlebar_color(self):
        val = self.opts.macos_titlebar_color
        if val:
            if (val & 0xff) == 1:
                val = self.screen.color_profile.default_bg
            else:
                val = val >> 8
            set_titlebar_color(self.os_window_id, val)

    def change_colors(self, changes):
        dirtied = default_bg_changed = False

        def item(raw):
            if raw is None:
                return 0
            val = to_color(raw)
            return None if val is None else (color_as_int(val) << 8) | 2

        for which, val in changes.items():
            val = item(val)
            if val is None:
                continue
            dirtied = True
            setattr(self.screen.color_profile, which.name, val)
            if which.name == 'default_bg':
                default_bg_changed = True
        if dirtied:
            self.screen.mark_as_dirty()
        if default_bg_changed:
            get_boss().default_bg_changed_for(self.id)

    def report_color(self, code, r, g, b):
        r |= r << 8
        g |= g << 8
        b |= b << 8
        self.screen.send_escape_code_to_child(OSC, '{};rgb:{:04x}/{:04x}/{:04x}'.format(code, r, g, b))

    def set_dynamic_color(self, code, value):
        if isinstance(value, bytes):
            value = value.decode('utf-8')
        color_changes = {}
        for val in value.split(';'):
            w = DYNAMIC_COLOR_CODES.get(code)
            if w is not None:
                if val == '?':
                    col = getattr(self.screen.color_profile, w.name)
                    self.report_color(str(code), col >> 16, (col >> 8) & 0xff, col & 0xff)
                else:
                    if code >= 110:
                        val = None
                    color_changes[w] = val
            code += 1
        if color_changes:
            self.change_colors(color_changes)
            glfw_post_empty_event()

    def set_color_table_color(self, code, value):
        cp = self.screen.color_profile
        if code == 4:
            changed = False
            for c, val in parse_color_set(value):
                if val is None:  # color query
                    self.report_color('4;{}'.format(c), *self.screen.color_profile.as_color((c << 8) | 1))
                else:
                    changed = True
                    cp.set_color(c, val)
            if changed:
                self.refresh()
        elif code == 104:
            if not value.strip():
                cp.reset_color_table()
            else:
                for c in value.split(';'):
                    try:
                        c = int(c)
                    except Exception:
                        continue
                    if 0 <= c <= 255:
                        cp.reset_color(c)
            self.refresh()

    def request_capabilities(self, q):
        self.screen.send_escape_code_to_child(DCS, get_capabilities(q))

    def handle_remote_cmd(self, cmd):
        get_boss().handle_remote_cmd(cmd, self)

    def handle_remote_print(self, msg):
        from base64 import standard_b64decode
        msg = standard_b64decode(msg).decode('utf-8')
        print(msg, end='', file=sys.stderr)
        sys.stderr.flush()

    def send_cmd_response(self, response):
        self.screen.send_escape_code_to_child(DCS, '@kitty-cmd' + json.dumps(response))

    def clipboard_control(self, data):
        where, text = data.partition(';')[::2]
        if text == '?':
            response = None
            if 's' in where or 'c' in where:
                response = get_clipboard_string() if 'read-clipboard' in self.opts.clipboard_control else ''
                loc = 'c'
            elif 'p' in where:
                response = get_primary_selection() if 'read-primary' in self.opts.clipboard_control else ''
                loc = 'p'
            response = response or ''
            from base64 import standard_b64encode
            self.screen.send_escape_code_to_child(OSC, '52;{};{}'.format(
                loc, standard_b64encode(response.encode('utf-8')).decode('ascii')))

        else:
            from base64 import standard_b64decode
            try:
                text = standard_b64decode(text).decode('utf-8')
            except Exception:
                text = ''

            def write(key, func):
                if text:
                    if len(self.clipboard_control_buffers[key]) > 1024*1024:
                        self.clipboard_control_buffers[key] = ''
                    self.clipboard_control_buffers[key] += text
                else:
                    self.clipboard_control_buffers[key] = ''
                func(self.clipboard_control_buffers[key])

            if 's' in where or 'c' in where:
                if 'write-clipboard' in self.opts.clipboard_control:
                    write('c', set_clipboard_string)
            if 'p' in where:
                if self.opts.copy_on_select:
                    if 'write-clipboard' in self.opts.clipboard_control:
                        write('c', set_clipboard_string)
                if 'write-primary' in self.opts.clipboard_control:
                    write('p', set_primary_selection)

    def manipulate_title_stack(self, pop, title, icon):
        if title:
            if pop:
                if self.title_stack:
                    self.child_title = self.title_stack.pop()
                    self.title_updated()
            else:
                if self.child_title:
                    self.title_stack.append(self.child_title)
    # }}}

    def text_for_selection(self):
        return ''.join(self.screen.text_for_selection())

    def destroy(self):
        self.destroyed = True
        if self.screen is not None:
            # Remove cycles so that screen is de-allocated immediately
            self.screen.reset_callbacks()
        self.screen = None

    def as_text(self, as_ansi=False, add_history=False, add_pager_history=False, add_wrap_markers=False, alternate_screen=False):
        lines = []
        add_history = add_history and not (self.screen.is_using_alternate_linebuf() ^ alternate_screen)
        if alternate_screen:
            f = self.screen.as_text_alternate
        else:
            f = self.screen.as_text_non_visual if add_history else self.screen.as_text
        f(lines.append, as_ansi, add_wrap_markers)
        if add_history:
            h = []
            if add_pager_history:
                # assert as_ansi and add_wrap_markers?
                self.screen.historybuf.pagerhist_as_text(h.append)
            self.screen.historybuf.as_text(h.append, as_ansi, add_wrap_markers)
            lines = h + lines
        return ''.join(lines)

    @property
    def cwd_of_child(self):
        # TODO: Maybe use the cwd of the leader of the foreground process
        # group in the session of the child process?
        pid = self.child.pid
        if pid is not None:
            return cwd_of_process(pid) or None

    # actions {{{

    def show_scrollback(self):
        data = self.as_text(as_ansi=True, add_history=True, add_pager_history=True, add_wrap_markers=True)
        data = data.replace('\r\n', '\n').replace('\r', '\n')
        lines = data.count('\n')
        input_line_number = (lines - (self.screen.lines - 1) - self.screen.scrolled_by)
        cmd = [x.replace('INPUT_LINE_NUMBER', str(input_line_number)) for x in self.opts.scrollback_pager]
        get_boss().display_scrollback(self, data, cmd)

    def paste(self, text):
        if text and not self.destroyed:
            if isinstance(text, str):
                text = text.encode('utf-8')
            if self.screen.in_bracketed_paste_mode:
                while True:
                    new_text = text.replace(b'\033[201~', b'').replace(b'\x9b201~', b'')
                    if len(text) == len(new_text):
                        break
                    text = new_text
            else:
                # Workaround for broken editors like nano that cannot handle
                # newlines in pasted text see https://github.com/kovidgoyal/kitty/issues/994
                text = b'\r'.join(text.splitlines())
            self.screen.paste(text)

    def copy_to_clipboard(self):
        text = self.text_for_selection()
        if text:
            set_clipboard_string(text)

    def pass_selection_to_program(self, *args):
        cwd = self.cwd_of_child
        text = self.text_for_selection()
        if text:
            if args:
                open_cmd(args, text, cwd=cwd)
            else:
                open_url(text, cwd=cwd)

    def scroll_line_up(self):
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_LINE, True)

    def scroll_line_down(self):
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_LINE, False)

    def scroll_page_up(self):
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_PAGE, True)

    def scroll_page_down(self):
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_PAGE, False)

    def scroll_home(self):
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_FULL, True)

    def scroll_end(self):
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_FULL, False)
    # }}}
