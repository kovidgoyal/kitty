#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from gettext import gettext as _
from weakref import WeakValueDictionary

from .config import MINIMUM_FONT_SIZE
from .constants import cell_size, set_boss, viewport_size, wakeup
from .fast_data_types import (
    GLFW_KEY_DOWN, GLFW_KEY_UP, ChildMonitor, destroy_global_data,
    destroy_sprite_map, glfw_post_empty_event, layout_sprite_map
)
from .fonts.render import render_cell_wrapper, set_font_family
from .keys import get_key_map, get_sent_data, get_shortcut
from .session import create_session
from .tabs import SpecialWindow, TabManager
from .utils import (
    get_primary_selection, open_url, safe_print, set_primary_selection
)
from .window import load_shader_programs


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
        self.cursor_blinking = True
        self.window_is_focused = True
        self.glfw_window_title = None
        self.shutting_down = False
        self.child_monitor = ChildMonitor(
            glfw_window.window_id(),
            self.on_child_death,
            DumpCommands(args) if args.dump_commands or args.dump_bytes else None)
        set_boss(self)
        self.current_font_size = opts.font_size
        cell_size.width, cell_size.height = set_font_family(opts)
        self.opts, self.args = opts, args
        self.glfw_window = glfw_window
        glfw_window.framebuffer_size_callback = self.on_window_resize
        glfw_window.window_focus_callback = self.on_focus
        load_shader_programs()
        self.tab_manager = TabManager(opts, args)
        self.tab_manager.init(startup_session)
        self.activate_tab_at = self.tab_manager.activate_tab_at
        layout_sprite_map(cell_size.width, cell_size.height, render_cell_wrapper)

    @property
    def current_tab_bar_height(self):
        return self.tab_manager.tab_bar_height

    def __iter__(self):
        return iter(self.tab_manager)

    def iterwindows(self):
        for t in self:
            yield from t

    def add_child(self, window):
        self.child_monitor.add_child(window.id, window.child.pid, window.child.child_fd, window.screen)
        self.window_id_map[window.id] = window

    def on_child_death(self, window_id):
        w = self.window_id_map.pop(window_id, None)
        if w is not None:
            w.on_child_death()

    def close_window(self, window=None):
        if window is None:
            window = self.active_window
        self.child_monitor.mark_for_close(window.id)

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
        viewport_size.width, viewport_size.height = w, h
        self.tab_manager.resize()

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
        w, h = cell_size.width, cell_size.height
        windows = tuple(filter(None, self.window_id_map.values()))
        cell_size.width, cell_size.height = set_font_family(
            self.opts, override_font_size=self.current_font_size)
        layout_sprite_map(cell_size.width, cell_size.height, render_cell_wrapper)
        for window in windows:
            window.screen.rescale_images(w, h)
        self.resize_windows_after_font_size_change()
        for window in windows:
            window.screen.refresh_sprite_positions()
        self.tab_manager.refresh_sprite_positions()

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

    def dispatch_special_key(self, key, scancode, action, mods):
        # Handles shortcuts, return True if the key was consumed
        funcargs = get_shortcut(self.opts.keymap, mods, key, scancode)
        func = funcargs.partition(' ')[::2][0]
        args = funcargs.partition(' ')[::2][1:]
        if func is not None:
            f = getattr(self, func, None)
            if f is not None:
                passthrough = f()
                if passthrough is not True:
                    return True
        tab = self.active_tab
        if tab is None:
            return False
        window = self.active_window
        if window is None:
            return False
        if func is not None:
            f = getattr(tab, func, getattr(window, func, None))
            if func == 'pipe_selection_to_new_tab':
                passthrough = f(args)
                if passthrough is not True:
                    return True
            elif f is not None:
                passthrough = f()
                if passthrough is not True:
                    return True
        data = get_sent_data(
            self.opts.send_text_map, key, scancode, mods, window, action
        )
        if data:
            window.write_to_child(data)
            return True
        return False

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

    def switch_focus_to(self, window_idx):
        tab = self.active_tab
        tab.set_active_window_idx(window_idx)
        old_focus = tab.active_window
        if not old_focus.destroyed:
            old_focus.focus_changed(False)
        tab.active_window.focus_changed(True)

    def send_fake_scroll(self, window_idx, amt, upwards):
        tab = self.active_tab
        w = tab.windows[window_idx]
        k = get_key_map(w.screen)[GLFW_KEY_UP if upwards else GLFW_KEY_DOWN]
        w.write_to_child(k * amt)

    def open_url(self, url):
        if url:
            open_url(url, self.opts.open_url_with)

    def gui_close_window(self, window):
        window.destroy()
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
        destroy_sprite_map()
        destroy_global_data()
        del self.glfw_window

    def paste_to_active_window(self, text):
        if text:
            w = self.active_window
            if w is not None:
                w.paste(text)

    def paste_from_clipboard(self):
        text = self.glfw_window.get_clipboard_string()
        self.paste_to_active_window(text)

    def paste_from_selection(self):
        text = get_primary_selection()
        self.paste_to_active_window(text)

    def set_primary_selection(self):
        w = self.active_window
        if w is not None and not w.destroyed:
            text = w.text_for_selection()
            if text:
                set_primary_selection(text)

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
