#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import io
import select
import signal
import struct
import inspect
from collections import deque
from functools import wraps
from threading import Thread, current_thread
from time import monotonic
from queue import Queue, Empty

from .child import Child
from .constants import (
    viewport_size, shell_path, appname, set_tab_manager, tab_manager, wakeup,
    cell_size, MODIFIER_KEYS, main_thread, mouse_button_pressed
)
from .fast_data_types import (
    glViewport, glBlendFunc, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GLFW_PRESS,
    GLFW_REPEAT, GLFW_MOUSE_BUTTON_1, glfw_post_empty_event,
    GLFW_CURSOR_NORMAL, GLFW_CURSOR, GLFW_CURSOR_HIDDEN,
)
from .fonts import set_font_family
from .borders import Borders, BordersProgram
from .char_grid import cursor_shader, cell_shader
from .constants import is_key_pressed
from .keys import interpret_text_event, interpret_key_event, get_shortcut
from .layout import Stack
from .shaders import Sprites, ShaderProgram
from .timers import Timers
from .utils import handle_unix_signals
from .window import Window


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


class Tab:

    def __init__(self, opts, args):
        self.opts, self.args = opts, args
        self.windows = deque()
        self.borders = Borders(opts)
        self.current_layout = Stack(opts, self.borders.border_width)

    @property
    def is_visible(self):
        return tab_manager().is_tab_visible(self)

    @property
    def active_window(self):
        return self.windows[0] if self.windows else None

    @property
    def title(self):
        return getattr(self.active_window, 'title', appname)

    def visible_windows(self):
        for w in self.windows:
            if w.is_visible_in_layout:
                yield w

    def relayout(self):
        if self.windows:
            self.current_layout(self.windows)
        self.borders(self.windows, self.active_window, self.current_layout.needs_window_borders)

    def launch_child(self, use_shell=False):
        if use_shell:
            cmd = [shell_path]
        else:
            cmd = self.args.args or [shell_path]
        ans = Child(cmd, self.args.directory, self.opts)
        ans.fork()
        return ans

    def new_window(self, use_shell=False):
        child = self.launch_child(use_shell=use_shell)
        window = Window(self, child, self.opts, self.args)
        tab_manager().add_child_fd(child.child_fd, window.read_ready, window.write_ready)
        self.current_layout.add_window(self.windows, window)

    def remove_window(self, window):
        self.current_layout.remove_window(self.windows, window)

    def __iter__(self):
        yield from iter(self.windows)

    def __len__(self):
        return len(self.windows)

    def __contains__(self, window):
        return window in self.windows

    def destroy(self):
        for w in self.windows:
            w.destroy()
        del self.windows

    def render(self):
        self.borders.render(tab_manager().borders_program)


class TabManager(Thread):

    daemon = True

    def __init__(self, glfw_window, opts, args):
        Thread.__init__(self, name='ChildMonitor')
        self.cursor_blinking = True
        self.glfw_window_title = None
        self.current_tab_bar_height = 0
        self.action_queue = Queue()
        self.pending_resize = True
        self.resize_gl_viewport = False
        self.shutting_down = False
        self.screen_update_delay = opts.repaint_delay / 1000.0
        self.signal_fd = handle_unix_signals()
        self.read_wakeup_fd, self.write_wakeup_fd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self.read_dispatch_map = {self.signal_fd: self.signal_received, self.read_wakeup_fd: self.on_wakeup}
        self.all_writers = []
        self.timers = Timers()
        self.ui_timers = Timers()
        self.pending_ui_thread_calls = Queue()
        self.write_dispatch_map = {}
        set_tab_manager(self)
        cell_size.width, cell_size.height = set_font_family(opts.font_family, opts.font_size)
        self.opts, self.args = opts, args
        self.glfw_window = glfw_window
        glfw_window.framebuffer_size_callback = self.on_window_resize
        glfw_window.char_mods_callback = self.on_text_input
        glfw_window.key_callback = self.on_key
        glfw_window.mouse_button_callback = self.on_mouse_button
        glfw_window.scroll_callback = self.on_mouse_scroll
        glfw_window.cursor_pos_callback = self.on_mouse_move
        glfw_window.window_focus_callback = self.on_focus
        self.tabs = deque()
        self.tabs.append(Tab(opts, args))
        self.sprites = Sprites()
        self.cell_program = ShaderProgram(*cell_shader)
        self.cursor_program = ShaderProgram(*cursor_shader)
        self.borders_program = BordersProgram()
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        self.sprites.do_layout(cell_size.width, cell_size.height)
        self.queue_action(self.active_tab.new_window, False)
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

    def __iter__(self):
        yield from iter(self.tabs)

    def iterwindows(self):
        for t in self:
            yield from t

    def queue_action(self, func, *args):
        self.action_queue.put((func, args))
        wakeup()

    def on_wakeup(self):
        if not self.shutting_down:
            try:
                os.read(self.read_wakeup_fd, io.DEFAULT_BUFFER_SIZE)
            except (EnvironmentError, BlockingIOError):
                pass
            while True:
                try:
                    func, args = self.action_queue.get_nowait()
                except Empty:
                    break
                try:
                    func(*args)
                except Exception:
                    import traceback
                    traceback.print_exc()

    def add_child_fd(self, child_fd, read_ready, write_ready):
        self.read_dispatch_map[child_fd] = read_ready
        self.write_dispatch_map[child_fd] = write_ready

    def remove_child_fd(self, child_fd):
        self.read_dispatch_map.pop(child_fd, None)
        self.write_dispatch_map.pop(child_fd, None)
        try:
            self.all_writers.remove(child_fd)
        except Exception:
            pass

    def queue_ui_action(self, func, *args):
        self.pending_ui_thread_calls.put((func, args))
        glfw_post_empty_event()

    def close_window(self, window):
        ' Can be called in either thread, will first kill the child (with SIGHUP), then remove the window from the gui '
        if current_thread() is main_thread:
            self.queue_action(self.close_window, window)
        else:
            self.remove_child_fd(window.child_fd)
            window.destroy()
            self.queue_ui_action(self.gui_close_window, window)

    def run(self):
        if self.args.profile:
            import cProfile
            import pstats
            pr = cProfile.Profile()
            pr.enable()
        self.loop()
        if self.args.profile:
            pr.disable()
            pr.create_stats()
            s = pstats.Stats(pr)
            s.dump_stats(self.args.profile)

    def loop(self):
        while not self.shutting_down:
            all_readers = list(self.read_dispatch_map)
            all_writers = [w.child_fd for w in self.iterwindows() if w.write_buf]
            readers, writers, _ = select.select(all_readers, all_writers, [], self.timers.timeout())
            for r in readers:
                self.read_dispatch_map[r]()
            for w in writers:
                self.write_dispatch_map[w]()
            self.timers()
            for w in self.iterwindows():
                if w.screen.is_dirty():
                    self.timers.add_if_missing(self.screen_update_delay, w.update_screen)

    @callback
    def on_window_resize(self, window, w, h):
        # debounce resize events
        self.pending_resize = True
        yield
        self.timers.add(0.02, self.apply_pending_resize, w, h)

    def apply_pending_resize(self, w, h):
        viewport_size.width, viewport_size.height = w, h
        for tab in self.tabs:
            tab.relayout()
        self.resize_gl_viewport = True
        self.pending_resize = False
        glfw_post_empty_event()

    @property
    def active_tab(self):
        return self.tabs[0] if self.tabs else None

    def is_tab_visible(self, tab):
        return self.active_tab is tab

    @property
    def active_window(self):
        t = self.active_tab
        if t is not None:
            return t.active_window

    @callback
    def on_text_input(self, window, codepoint, mods):
        data = interpret_text_event(codepoint, mods)
        if data:
            w = self.active_window
            if w is not None:
                yield w
                w.write_to_child(data)

    @callback
    def on_key(self, window, key, scancode, action, mods):
        is_key_pressed[key] = action == GLFW_PRESS
        self.start_cursor_blink()
        if action == GLFW_PRESS or action == GLFW_REPEAT:
            func = get_shortcut(self.opts.keymap, mods, key)
            tab = self.active_tab
            if func is not None:
                f = getattr(self, func, getattr(tab, func, None))
                if f is not None:
                    passthrough = f()
                    if not passthrough:
                        return
            window = self.active_window
            if window is not None:
                yield window
                if func is not None:
                    f = getattr(window, func, None)
                    if f is not None:
                        passthrough = f()
                        if not passthrough:
                            return
                if window.screen.auto_repeat_enabled() or action == GLFW_PRESS:
                    if window.char_grid.scrolled_by and key not in MODIFIER_KEYS:
                        window.scroll_end()
                    data = interpret_key_event(key, scancode, mods)
                    if data:
                        window.write_to_child(data)

    @callback
    def on_focus(self, window, focused):
        w = self.active_window
        if w is not None:
            yield w
            w.focus_changed(focused)

    def window_for_pos(self, x, y):
        tab = self.active_tab
        if tab is not None:
            for w in tab:
                if w.is_visible_in_layout and w.contains(x, y):
                    return w

    @callback
    def on_mouse_button(self, window, button, action, mods):
        mouse_button_pressed[button] = action == GLFW_PRESS
        self.show_mouse_cursor()
        w = self.window_for_pos(*window.get_cursor_pos())
        if w is None:
            return
        focus_moved = False
        old_focus = self.active_window
        if button == GLFW_MOUSE_BUTTON_1 and w is not old_focus:
            # TODO: Switch focus to this window
            focus_moved = True
        yield
        if focus_moved:
            if old_focus is not None and not old_focus.destroyed:
                old_focus.focus_changed(False)
            w.focus_changed(True)
        w.on_mouse_button(button, action, mods)

    @callback
    def on_mouse_move(self, window, xpos, ypos):
        self.show_mouse_cursor()
        w = self.window_for_pos(*window.get_cursor_pos())
        if w is not None:
            yield w
            w.on_mouse_move(xpos, ypos)

    @callback
    def on_mouse_scroll(self, window, x, y):
        self.show_mouse_cursor()
        w = self.window_for_pos(*window.get_cursor_pos())
        if w is not None:
            yield w
            w.on_mouse_scroll(x, y)

    # GUI thread API {{{

    def show_mouse_cursor(self):
        self.glfw_window.set_input_mode(GLFW_CURSOR, GLFW_CURSOR_NORMAL)
        if self.opts.mouse_hide_wait > 0:
            self.ui_timers.add(self.opts.mouse_hide_wait, self.hide_mouse_cursor)

    def hide_mouse_cursor(self):
        self.glfw_window.set_input_mode(GLFW_CURSOR, GLFW_CURSOR_HIDDEN)

    def change_mouse_cursor(self, click=False):
        self.glfw_window.set_click_cursor(click)

    def start_cursor_blink(self):
        self.cursor_blinking = True
        if self.opts.cursor_stop_blinking_after > 0:
            self.ui_timers.add(self.opts.cursor_stop_blinking_after, self.stop_cursor_blinking)

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
            with self.sprites:
                self.sprites.render_dirty_cells()
                tab.render()
                render_data = {window: window.char_grid.prepare_for_render(self.sprites) for window in tab.visible_windows()}
                active = self.active_window
                with self.cell_program:
                    for window, rd in render_data.items():
                        if rd is not None:
                            window.char_grid.render_cells(rd, self.cell_program, self.sprites)
                rd = render_data.get(active)
                if rd is not None:
                    draw_cursor = True
                    if self.cursor_blinking and self.opts.cursor_blink_interval > 0:
                        now = monotonic()
                        t = int(now * 1000)
                        d = int(self.opts.cursor_blink_interval * 1000)
                        n = t // d
                        draw_cursor = n % 2 == 0
                        self.ui_timers.add_if_missing(((n + 1) * d / 1000) - now, glfw_post_empty_event)
                    if draw_cursor:
                        with self.cursor_program:
                            active.char_grid.render_cursor(rd, self.cursor_program)

    def gui_close_window(self, window):
        for tab in self.tabs:
            if window in tab:
                break
        else:
            return
        tab.remove_window(window)
        if len(tab) == 0:
            self.tabs.remove(tab)
            tab.destroy()
            if len(self.tabs) == 0:
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
        for t in self.tabs:
            t.destroy()
        del self.tabs
        self.sprites.destroy()
        del self.sprites
        del self.glfw_window

    def paste_from_clipboard(self):
        text = self.glfw_window.get_clipboard_string()
        if text:
            w = self.active_window
            if w is not None:
                self.queue_action(w.paste, text)

    # }}}
