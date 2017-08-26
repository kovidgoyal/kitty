#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import inspect
import io
import os
import select
import signal
import struct
from functools import wraps
from gettext import gettext as _
from queue import Empty, Queue
from threading import Thread, current_thread
from time import monotonic

from .borders import BordersProgram
from .char_grid import load_shader_programs
from .config import MINIMUM_FONT_SIZE
from .constants import (
    MODIFIER_KEYS, cell_size, is_key_pressed, isosx, main_thread,
    mouse_button_pressed, mouse_cursor_pos, set_boss, viewport_size, wakeup
)
from .fast_data_types import (
    GL_ONE_MINUS_SRC_ALPHA, GL_SRC_ALPHA, GLFW_CURSOR, GLFW_CURSOR_HIDDEN,
    GLFW_CURSOR_NORMAL, GLFW_MOUSE_BUTTON_1, GLFW_PRESS, GLFW_REPEAT,
    drain_read, glBlendFunc, glfw_post_empty_event, glViewport
)
from .fonts.render import set_font_family
from .keys import (
    get_sent_data, get_shortcut, interpret_key_event, interpret_text_event
)
from .session import create_session
from .shaders import Sprites
from .tabs import SpecialWindow, TabManager
from .timers import Timers
from .utils import handle_unix_signals, pipe2, safe_print

if isosx:
    from .fast_data_types import cocoa_update_title


def conditional_run(w, i):
    if w is None or not w.destroyed:
        next(i, None)


def callback(func):
    ''' Wrapper for function that executes first half (up to a yield statement)
    in the UI thread and the rest in the child thread. If the function yields
    something, the destroyed attribute of that something is checked before
    running the second half. If the function returns before the yield, the
    second half is not run. '''

    assert inspect.isgeneratorfunction(func)

    @wraps(func)
    def f(self, *a):
        i = func(self, *a)
        try:
            w = next(i)
        except StopIteration:
            pass
        else:
            self.queue_action(conditional_run, w, i)

    return f


class Boss(Thread):

    daemon = True

    def __init__(self, glfw_window, opts, args):
        Thread.__init__(self, name='ChildMonitor')
        startup_session = create_session(opts, args)
        self.cursor_blink_zero_time = monotonic()
        self.cursor_blinking = True
        self.window_is_focused = True
        self.glfw_window_title = None
        self.action_queue = Queue()
        self.pending_resize = False
        self.resize_gl_viewport = False
        self.shutting_down = False
        self.screen_update_delay = opts.repaint_delay / 1000.0
        self.signal_fd = handle_unix_signals()
        self.read_wakeup_fd, self.write_wakeup_fd = pipe2()
        self.read_dispatch_map = {
            self.signal_fd: self.signal_received,
            self.read_wakeup_fd: self.on_wakeup}
        self.timers = Timers()
        self.ui_timers = Timers()
        self.pending_ui_thread_calls = Queue()
        self.write_dispatch_map = {}
        set_boss(self)
        self.current_font_size = opts.font_size
        cell_size.width, cell_size.height = set_font_family(opts)
        self.opts, self.args = opts, args
        self.glfw_window = glfw_window
        glfw_window.framebuffer_size_callback = self.on_window_resize
        glfw_window.char_mods_callback = self.on_text_input
        glfw_window.key_callback = self.on_key
        glfw_window.mouse_button_callback = self.on_mouse_button
        glfw_window.scroll_callback = self.on_mouse_scroll
        glfw_window.cursor_pos_callback = self.on_mouse_move
        glfw_window.window_focus_callback = self.on_focus
        self.tab_manager = TabManager(opts, args, startup_session)
        self.sprites = Sprites()
        self.cell_program, self.cursor_program = load_shader_programs()
        self.borders_program = BordersProgram()
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        self.sprites.do_layout(cell_size.width, cell_size.height)
        self.glfw_window.set_click_cursor(False)
        self.show_mouse_cursor()
        self.start_cursor_blink()

    def signal_received(self):
        try:
            data = os.read(self.signal_fd, io.DEFAULT_BUFFER_SIZE)
        except BlockingIOError:
            return
        if data:
            signals = struct.unpack('%uB' % len(data), data)
            if signal.SIGINT in signals or signal.SIGTERM in signals:
                if not self.shutting_down:
                    self.glfw_window.set_should_close(True)
                    glfw_post_empty_event()

    @property
    def current_tab_bar_height(self):
        return self.tab_manager.tab_bar_height

    def __iter__(self):
        return iter(self.tab_manager)

    def iterwindows(self):
        for t in self:
            yield from t

    def queue_action(self, func, *args):
        self.action_queue.put((func, args))
        wakeup()

    def on_wakeup(self):
        if not self.shutting_down:
            drain_read(self.read_wakeup_fd)
            while True:
                try:
                    func, args = self.action_queue.get_nowait()
                except Empty:
                    break
                try:
                    func(*args)
                except Exception:
                    import traceback
                    safe_print(traceback.format_exc())

    def add_child_fd(self, child_fd, read_ready, write_ready):
        self.read_dispatch_map[child_fd] = read_ready
        self.write_dispatch_map[child_fd] = write_ready

    def remove_child_fd(self, child_fd):
        self.read_dispatch_map.pop(child_fd, None)
        self.write_dispatch_map.pop(child_fd, None)

    def queue_ui_action(self, func, *args):
        self.pending_ui_thread_calls.put((func, args))
        glfw_post_empty_event()

    def close_window(self, window=None):
        ' Can be called in either thread, will first kill the child, then remove the window from the gui '
        if window is None:
            window = self.active_window
        if current_thread() is main_thread:
            self.queue_action(self.close_window, window)
        else:
            self.remove_child_fd(window.child_fd)
            window.destroy()
            self.queue_ui_action(self.gui_close_window, window)

    def close_tab(self, tab=None):
        ' Can be called in either thread, will first kill all children, then remove the tab from the gui '
        if tab is None:
            tab = self.active_tab
        if current_thread() is main_thread:
            self.queue_action(self.close_tab, tab)
        else:
            for window in tab:
                self.remove_child_fd(window.child_fd)
                window.destroy()
                self.queue_ui_action(self.gui_close_window, window)

    def run(self):
        while not self.shutting_down:
            all_readers = list(self.read_dispatch_map)
            all_writers = [
                w.child_fd for w in self.iterwindows() if w.write_buf]
            readers, writers, _ = select.select(
                all_readers, all_writers, [], self.timers.timeout())
            for r in readers:
                self.read_dispatch_map[r]()
            for w in writers:
                self.write_dispatch_map[w]()
            self.timers()
            for w in self.iterwindows():
                if w.screen.is_dirty():
                    self.timers.add_if_missing(
                        self.screen_update_delay, w.update_screen)

    @callback
    def on_window_resize(self, window, w, h):
        # debounce resize events
        self.pending_resize = True
        yield
        self.timers.add(0.02, self.apply_pending_resize, w, h)

    def apply_pending_resize(self, w, h):
        viewport_size.width, viewport_size.height = w, h
        self.tab_manager.resize()
        self.resize_gl_viewport = True
        self.pending_resize = False
        glfw_post_empty_event()

    def increase_font_size(self):
        self.change_font_size(
            min(
                self.opts.font_size * 5, self.current_font_size +
                self.opts.font_size_delta))

    def decrease_font_size(self):
        self.change_font_size(
            max(
                MINIMUM_FONT_SIZE, self.current_font_size -
                self.opts.font_size_delta))

    def restore_font_size(self):
        self.change_font_size(self.opts.font_size)

    def change_font_size(self, new_size):
        if new_size == self.current_font_size:
            return
        self.current_font_size = new_size
        cell_size.width, cell_size.height = set_font_family(
            self.opts, override_font_size=self.current_font_size)
        self.sprites.do_layout(cell_size.width, cell_size.height)
        self.queue_action(self.resize_windows_after_font_size_change)

    def resize_windows_after_font_size_change(self):
        self.tab_manager.resize()
        glfw_post_empty_event()

    def tabbar_visibility_changed(self):
        self.tab_manager.resize(only_tabs=True)
        glfw_post_empty_event()

    @property
    def active_tab(self):
        return self.tab_manager.active_tab

    def is_tab_visible(self, tab):
        return self.active_tab is tab

    @property
    def active_window(self):
        t = self.active_tab
        if t is not None:
            return t.active_window

    @callback
    def on_text_input(self, window, codepoint, mods):
        w = self.active_window
        if w is not None:
            yield w
            if w is not None:
                data = interpret_text_event(codepoint, mods, w)
                if data:
                    w.write_to_child(data)

    @callback
    def on_key(self, window, key, scancode, action, mods):
        is_key_pressed[key] = action == GLFW_PRESS
        self.start_cursor_blink()
        self.cursor_blink_zero_time = monotonic()
        func = None
        if action == GLFW_PRESS or action == GLFW_REPEAT:
            func = get_shortcut(self.opts.keymap, mods, key, scancode)
            if func is not None:
                f = getattr(self, func, None)
                if f is not None:
                    passthrough = f()
                    if not passthrough:
                        return
        tab = self.active_tab
        if tab is None:
            return
        window = self.active_window
        if window is None:
            return
        yield window
        if func is not None:
            f = getattr(tab, func, getattr(window, func, None))
            if f is not None:
                passthrough = f()
                if not passthrough:
                    return
        if window.char_grid.scrolled_by and key not in MODIFIER_KEYS and action == GLFW_PRESS:
            window.scroll_end()
        data = get_sent_data(
            self.opts.send_text_map, key, scancode, mods, window, action
        ) or interpret_key_event(key, scancode, mods, window, action)
        if data:
            window.write_to_child(data)

    @callback
    def on_focus(self, window, focused):
        self.window_is_focused = focused
        w = self.active_window
        if w is not None:
            yield w
            w.focus_changed(focused)

    def display_scrollback(self, data):
        if self.opts.scrollback_in_new_tab:
            self.queue_ui_action(self.display_scrollback_in_new_tab, data)
        else:
            tab = self.active_tab
            if tab is not None:
                tab.new_special_window(
                    SpecialWindow(
                        self.opts.scrollback_pager, data, _('History')))

    def window_for_pos(self, x, y):
        tab = self.active_tab
        if tab is not None:
            for w in tab:
                if w.is_visible_in_layout and w.contains(x, y):
                    return w

    def in_tab_bar(self, y):
        th = self.current_tab_bar_height
        return th > 0 and y >= viewport_size.height - th

    @callback
    def on_mouse_button(self, window, button, action, mods):
        mouse_button_pressed[button] = action == GLFW_PRESS
        self.show_mouse_cursor()
        x, y = mouse_cursor_pos
        w = self.window_for_pos(x, y)
        if w is None:
            if self.in_tab_bar(y):
                if button == GLFW_MOUSE_BUTTON_1 and action == GLFW_PRESS:
                    self.tab_manager.activate_tab_at(x)
            return
        focus_moved = False
        old_focus = self.active_window
        tab = self.active_tab
        yield
        if button == GLFW_MOUSE_BUTTON_1 and w is not old_focus:
            tab.set_active_window(w)
            focus_moved = True
        if focus_moved:
            if old_focus is not None and not old_focus.destroyed:
                old_focus.focus_changed(False)
            w.focus_changed(True)
        w.on_mouse_button(button, action, mods)

    @callback
    def on_mouse_move(self, window, xpos, ypos):
        mouse_cursor_pos[:2] = xpos, ypos = int(
            xpos * viewport_size.x_ratio), int(ypos * viewport_size.y_ratio)
        self.show_mouse_cursor()
        w = self.window_for_pos(xpos, ypos)
        if w is not None:
            yield w
            w.on_mouse_move(xpos, ypos)
        else:
            self.change_mouse_cursor(self.in_tab_bar(ypos))

    @callback
    def on_mouse_scroll(self, window, x, y):
        self.show_mouse_cursor()
        w = self.window_for_pos(*mouse_cursor_pos)
        if w is not None:
            yield w
            w.on_mouse_scroll(x, y)

    # GUI thread API {{{

    def show_mouse_cursor(self):
        self.glfw_window.set_input_mode(GLFW_CURSOR, GLFW_CURSOR_NORMAL)
        if self.opts.mouse_hide_wait > 0:
            self.ui_timers.add(
                self.opts.mouse_hide_wait, self.hide_mouse_cursor)

    def hide_mouse_cursor(self):
        self.glfw_window.set_input_mode(GLFW_CURSOR, GLFW_CURSOR_HIDDEN)

    def change_mouse_cursor(self, click=False):
        self.glfw_window.set_click_cursor(click)

    def request_attention(self):
        try:
            self.glfw_window.request_window_attention()
        except AttributeError:
            pass  # needs glfw 3.3

    def start_cursor_blink(self):
        self.cursor_blinking = True
        if self.opts.cursor_stop_blinking_after > 0:
            self.ui_timers.add(
                self.opts.cursor_stop_blinking_after,
                self.stop_cursor_blinking)

    def stop_cursor_blinking(self):
        self.cursor_blinking = False

    def render(self):
        if self.pending_resize:
            return
        if self.resize_gl_viewport:
            glViewport(0, 0, viewport_size.width, viewport_size.height)
            self.resize_gl_viewport = False
        tab = self.active_tab
        if tab is not None:
            if tab.title != self.glfw_window_title:
                self.glfw_window_title = tab.title
                self.glfw_window.set_title(self.glfw_window_title)
                if isosx:
                    cocoa_update_title(self.glfw_window_title)
            with self.sprites:
                self.sprites.render_dirty_cells()
                tab.render()
                render_data = {
                    window:
                    window.char_grid.prepare_for_render(self.cell_program)
                    for window in tab.visible_windows()
                    if not window.needs_layout}
                with self.cell_program:
                    self.tab_manager.render(self.cell_program, self.sprites)
                    for window, rd in render_data.items():
                        if rd is not None:
                            window.render_cells(
                                rd, self.cell_program, self.sprites)
                active = self.active_window
                rd = render_data.get(active)
                if rd is not None:
                    draw_cursor = True
                    if self.cursor_blinking and self.opts.cursor_blink_interval > 0 and self.window_is_focused:
                        now = monotonic() - self.cursor_blink_zero_time
                        t = int(now * 1000)
                        d = int(self.opts.cursor_blink_interval * 1000)
                        n = t // d
                        draw_cursor = n % 2 == 0
                        self.ui_timers.add_if_missing(
                            ((n + 1) * d / 1000) - now, glfw_post_empty_event)
                    if draw_cursor:
                        with self.cursor_program:
                            active.char_grid.render_cursor(
                                rd, self.cursor_program,
                                self.window_is_focused)

    def gui_close_window(self, window):
        window.char_grid.destroy(self.cell_program)
        for tab in self.tab_manager:
            if window in tab:
                break
        else:
            return
        tab.remove_window(window)
        if len(tab) == 0:
            self.tab_manager.remove(tab)
            tab.destroy()
            if len(self.tab_manager) == 0:
                if not self.shutting_down:
                    self.glfw_window.set_should_close(True)
                    glfw_post_empty_event()

    def destroy(self):
        # Must be called in the main thread as it manipulates signal handlers
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        self.shutting_down = True
        wakeup()
        self.join()
        for t in self.tab_manager:
            t.destroy()
        del self.tab_manager
        self.sprites.destroy()
        del self.sprites
        del self.glfw_window

    def paste_from_clipboard(self):
        text = self.glfw_window.get_clipboard_string()
        if text:
            w = self.active_window
            if w is not None:
                self.queue_action(w.paste, text)

    def next_tab(self):
        self.queue_action(self.tab_manager.next_tab)

    def previous_tab(self):
        self.queue_action(self.tab_manager.next_tab, -1)

    def new_tab(self):
        self.tab_manager.new_tab()

    def move_tab_forward(self):
        self.queue_action(self.tab_manager.move_tab, 1)

    def move_tab_backward(self):
        self.queue_action(self.tab_manager.move_tab, -1)

    def display_scrollback_in_new_tab(self, data):
        self.tab_manager.new_tab(
            special_window=SpecialWindow(
                self.opts.scrollback_pager, data, _('History')))

    # }}}
