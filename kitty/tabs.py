#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import io
import select
import signal
import struct
from collections import deque
from functools import partial
from itertools import count
from threading import Thread
from time import monotonic
from queue import Queue, Empty

from .child import Child
from .constants import viewport_size, shell_path, appname, set_tab_manager, tab_manager, wakeup, cell_size, MODIFIER_KEYS
from .fast_data_types import (
    glViewport, glBlendFunc, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GLFW_PRESS,
    GLFW_REPEAT, GLFW_MOUSE_BUTTON_1, glfw_post_empty_event
)
from .fonts import set_font_family
from .borders import Borders, BordersProgram
from .char_grid import cursor_shader, cell_shader
from .keys import interpret_text_event, interpret_key_event, get_shortcut
from .layout import Stack
from .shaders import Sprites, ShaderProgram
from .utils import handle_unix_signals
from .window import Window


timer_id = count()


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
        self.glfw_window_title = None
        self.current_tab_bar_height = 0
        self.action_queue = Queue()
        self.pending_resize = None
        self.resize_gl_viewport = False
        self.shutting_down = False
        self.screen_update_delay = opts.repaint_delay / 1000.0
        self.signal_fd = handle_unix_signals()
        self.read_wakeup_fd, self.write_wakeup_fd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self.read_dispatch_map = {self.signal_fd: self.signal_received, self.read_wakeup_fd: self.on_wakeup}
        self.all_writers = []
        self.timers = []
        self.write_dispatch_map = {}
        set_tab_manager(self)
        cell_size.width, cell_size.height = set_font_family(opts.font_family, opts.font_size)
        self.opts, self.args = opts, args
        self.glfw_window = glfw_window
        glfw_window.framebuffer_size_callback = partial(self.queue_action, self.on_window_resize)
        glfw_window.char_mods_callback = partial(self.queue_action, self.on_text_input)
        glfw_window.key_callback = partial(self.queue_action, self.on_key)
        glfw_window.mouse_button_callback = partial(self.queue_action, self.on_mouse_button)
        glfw_window.scroll_callback = partial(self.queue_action, self.on_mouse_scroll)
        glfw_window.cursor_pos_callback = partial(self.queue_action, self.on_mouse_move)
        glfw_window.window_focus_callback = partial(self.queue_action, self.on_focus)
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

    def signal_received(self):
        try:
            data = os.read(self.signal_fd, io.DEFAULT_BUFFER_SIZE)
        except BlockingIOError:
            return
        if data:
            signals = struct.unpack('%uB' % len(data), data)
            if signal.SIGINT in signals or signal.SIGTERM in signals:
                self.shutdown()

    def shutdown(self):
        if not self.shutting_down:
            self.shutting_down = True
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

    def close_window(self, window):
        self.remove_child_fd(window.child_fd)
        for tab in self.tabs:
            if window in tab:
                break
        else:
            return
        tab.remove_window(window)
        window.destroy()
        if len(tab) == 0:
            self.tabs.remove(tab)
            tab.destroy()
            if len(self.tabs) == 0:
                self.shutdown()

    def call_after(self, delay, callback):
        tid = next(timer_id)
        self.timers.append((monotonic() + delay, tid, callback))
        if len(self.timers) > 1:
            self.timers.sort()
        return tid

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
            timeout = max(0, self.timers[0][0] - monotonic()) if self.timers else None
            readers, writers, _ = select.select(all_readers, all_writers, [], timeout)
            for r in readers:
                self.read_dispatch_map[r]()
            for w in writers:
                self.write_dispatch_map[w]()
            timers = []
            callbacks = set()
            for epoch, tid, callback in self.timers:
                if epoch <= monotonic():
                    callback()
                else:
                    timers.append((epoch, tid, callback))
                    callbacks.add(callback)
            update_at = monotonic() + self.screen_update_delay
            before = len(timers)
            for w in self.iterwindows():
                if w.screen.is_dirty() and w.update_screen not in callbacks:
                    timers.append((update_at, next(timer_id), w.update_screen))
            if len(timers) > before:
                timers.sort()
            self.timers = timers

    def on_window_resize(self, window, w, h):
        # debounce resize events
        self.pending_resize = [monotonic(), w, h]
        self.call_after(0.02, self.apply_pending_resize)

    def apply_pending_resize(self):
        if self.pending_resize is None:
            return
        if monotonic() - self.pending_resize[0] < 0.02:
            self.call_after(0.02, self.apply_pending_resize)
            return
        viewport_size.width, viewport_size.height = self.pending_resize[1:]
        for tab in self.tabs:
            tab.relayout()
        self.pending_resize = None
        self.resize_gl_viewport = True
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

    def on_text_input(self, window, codepoint, mods):
        data = interpret_text_event(codepoint, mods)
        if data:
            w = self.active_window
            if w is not None:
                w.write_to_child(data)

    def on_key(self, window, key, scancode, action, mods):
        if action == GLFW_PRESS or action == GLFW_REPEAT:
            func = get_shortcut(self.opts.keymap, mods, key)
            tab = self.active_tab
            window = self.active_window
            if func is not None:
                func = getattr(self, func, getattr(tab, func, getattr(window, func, None)))
                if func is not None:
                    passthrough = func()
                    if not passthrough:
                        return
            if window:
                if window.char_grid.scrolled_by and key not in MODIFIER_KEYS:
                    window.scroll_end()
                data = interpret_key_event(key, scancode, mods)
                if data:
                    window.write_to_child(data)

    def on_focus(self, window, focused):
        w = self.active_window
        if w is not None:
            w.focus_changed(focused)

    def window_for_pos(self, x, y):
        for w in self.active_tab:
            if w.is_visible_in_layout and w.contains(x, y):
                return w

    def on_mouse_button(self, window, button, action, mods):
        w = self.window_for_pos(*window.get_cursor_pos())
        if w is not None:
            if button == GLFW_MOUSE_BUTTON_1 and w is not self.active_window:
                pass  # TODO: Switch focus to this window
            w.on_mouse_button(window, button, action, mods)

    def on_mouse_move(self, window, xpos, ypos):
        w = self.window_for_pos(*window.get_cursor_pos())
        if w is not None:
            w.on_mouse_move(window, xpos, ypos)

    def on_mouse_scroll(self, window, x, y):
        w = self.window_for_pos(*window.get_cursor_pos())
        if w is not None:
            w.on_mouse_scroll(window, x, y)

    # GUI thread API {{{
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
                    with self.cursor_program:
                        active.char_grid.render_cursor(rd, self.cursor_program)

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
    # }}}
