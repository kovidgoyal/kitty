#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from gettext import gettext as _
from time import monotonic
from weakref import WeakValueDictionary

from .borders import BordersProgram
from .char_grid import load_shader_programs
from .config import MINIMUM_FONT_SIZE
from .constants import (
    MODIFIER_KEYS, cell_size, is_key_pressed, isosx, mouse_button_pressed,
    mouse_cursor_pos, set_boss, viewport_size, wakeup
)
from .fast_data_types import (
    GL_ONE_MINUS_SRC_ALPHA, GL_SRC_ALPHA, GLFW_CURSOR, GLFW_CURSOR_HIDDEN,
    GLFW_CURSOR_NORMAL, GLFW_MOUSE_BUTTON_1, GLFW_PRESS, GLFW_REPEAT,
    ChildMonitor, Timers as _Timers, glBlendFunc, glfw_post_empty_event,
    glViewport
)
from .fonts.render import set_font_family
from .keys import (
    get_sent_data, get_shortcut, interpret_key_event, interpret_text_event
)
from .session import create_session
from .shaders import Sprites
from .tabs import SpecialWindow, TabManager
from .utils import safe_print

if isosx:
    from .fast_data_types import cocoa_update_title


class Timers(_Timers):

    def __init__(self):
        _Timers.__init__(self)
        self.timer_hash = {}

    def add(self, delay, timer, *args):
        # Needed because bound methods are recreated on every access
        timer = self.timer_hash.setdefault(timer, timer)
        return _Timers.add(self, delay, timer, args) if args else _Timers.add(self, delay, timer)

    def remove(self, timer):
        # Needed because bound methods are recreated on every access
        timer = self.timer_hash.setdefault(timer, timer)
        return _Timers.remove_event(self, timer)


def conditional_run(w, i):
    if w is None or not w.destroyed:
        next(i, None)


class DumpCommands:  # {{{

    def __init__(self, args):
        self.draw_dump_buf = []
        if args.dump_bytes:
            self.dump_bytes_to = open(args.dump_bytes, 'wb')

    def __call__(self, *a):
        if a:
            if a[0] == 'draw':
                if a[1] is None:
                    if self.draw_dump_buf:
                        safe_print('draw', ''.join(self.draw_dump_buf))
                        self.draw_dump_buf = []
                else:
                    self.draw_dump_buf.append(a[1])
            elif a[0] == 'bytes':
                self.dump_bytes_to.write(a[1])
                self.dump_bytes_to.flush()
            else:
                if self.draw_dump_buf:
                    safe_print('draw', ''.join(self.draw_dump_buf))
                    self.draw_dump_buf = []
                safe_print(*a)
# }}}


class Boss:

    daemon = True

    def __init__(self, glfw_window, opts, args):
        self.window_id_map = WeakValueDictionary()
        startup_session = create_session(opts, args)
        self.cursor_blink_zero_time = monotonic()
        self.cursor_blinking = True
        self.window_is_focused = True
        self.glfw_window_title = None
        self.resize_gl_viewport = False
        self.shutting_down = False
        self.ui_timers = Timers()
        self.child_monitor = ChildMonitor(
            opts.repaint_delay / 1000.0, glfw_window.window_id(),
            self.on_child_death, self.update_screen, self.ui_timers, self.render,
            DumpCommands(args) if args.dump_commands or args.dump_bytes else None)
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
        self.tab_manager = TabManager(opts, args)
        self.tab_manager.init(startup_session)
        self.sprites = Sprites()
        self.sprites.do_layout(cell_size.width, cell_size.height)
        self.cell_program, self.cursor_program = load_shader_programs()
        self.borders_program = BordersProgram()
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        self.glfw_window.set_click_cursor(False)
        self.show_mouse_cursor()
        self.start_cursor_blink()

    @property
    def current_tab_bar_height(self):
        return self.tab_manager.tab_bar_height

    def __iter__(self):
        return iter(self.tab_manager)

    def iterwindows(self):
        for t in self:
            yield from t

    def add_child(self, window):
        self.child_monitor.add_child(window.id, window.child_fd, window.screen)
        self.window_id_map[window.id] = window
        wakeup()

    def on_child_death(self, window_id):
        w = self.window_id_map.get(window_id)
        if w is not None:
            w.on_child_death()

    def update_screen(self, window_id):
        w = self.window_id_map.get(window_id)
        if w is not None:
            w.update_screen()

    def close_window(self, window=None):
        if window is None:
            window = self.active_window
        self.child_monitor.mark_for_close(window.screen.child_fd)
        self.gui_close_window()
        window.destroy()
        wakeup()

    def close_tab(self, tab=None):
        if tab is None:
            tab = self.active_tab
        for window in tab:
            self.close_window(window)

    def start(self):
        if not getattr(self, 'io_thread_started', False):
            self.child_monitor.start()
            self.io_thread_started = True

    def on_window_resize(self, window, w, h):
        # debounce resize events
        if w > 100 and h > 100:
            viewport_size.width, viewport_size.height = w, h
            self.tab_manager.resize()
            self.resize_gl_viewport = True
            glfw_post_empty_event()
        else:
            safe_print('Ignoring resize request for sizes under 100x100')

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
        self.resize_windows_after_font_size_change()

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

    def on_text_input(self, window, codepoint, mods):
        w = self.active_window
        if w is not None:
            data = interpret_text_event(codepoint, mods, w)
            if data:
                w.write_to_child(data)

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

    def on_focus(self, window, focused):
        self.window_is_focused = focused
        w = self.active_window
        if w is not None:
            w.focus_changed(focused)

    def display_scrollback(self, data):
        if self.opts.scrollback_in_new_tab:
            self.display_scrollback_in_new_tab(data)
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
        if button == GLFW_MOUSE_BUTTON_1 and w is not old_focus:
            tab.set_active_window(w)
            focus_moved = True
        if focus_moved:
            if old_focus is not None and not old_focus.destroyed:
                old_focus.focus_changed(False)
            w.focus_changed(True)
        w.on_mouse_button(button, action, mods)

    def on_mouse_move(self, window, xpos, ypos):
        mouse_cursor_pos[:2] = xpos, ypos = int(
            xpos * viewport_size.x_ratio), int(ypos * viewport_size.y_ratio)
        self.show_mouse_cursor()
        w = self.window_for_pos(xpos, ypos)
        if w is not None:
            w.on_mouse_move(xpos, ypos)
        else:
            self.change_mouse_cursor(self.in_tab_bar(ypos))

    def on_mouse_scroll(self, window, x, y):
        self.show_mouse_cursor()
        w = self.window_for_pos(*mouse_cursor_pos)
        if w is not None:
            w.on_mouse_scroll(x, y)

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
                self.sprites.render_dirty_sprites()
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
        self.shutting_down = True
        self.child_monitor.shutdown()
        wakeup()
        self.child_monitor.join()
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
                w.paste(text)

    def next_tab(self):
        self.tab_manager.next_tab()

    def previous_tab(self):
        self.tab_manager.next_tab(-1)

    def new_tab(self):
        self.tab_manager.new_tab()

    def move_tab_forward(self):
        self.tab_manager.move_tab(1)

    def move_tab_backward(self):
        self.tab_manager.move_tab(-1)

    def display_scrollback_in_new_tab(self, data):
        self.tab_manager.new_tab(
            special_window=SpecialWindow(
                self.opts.scrollback_pager, data, _('History')))

    # }}}
