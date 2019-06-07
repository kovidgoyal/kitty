#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>


from .operations import commander


class Handler:

    image_manager_class = None

    def _initialize(self, screen_size, term_manager, schedule_write, tui_loop, debug, image_manager=None):
        self.screen_size = screen_size
        self._term_manager = term_manager
        self._tui_loop = tui_loop
        self._schedule_write = schedule_write
        self.debug = debug
        self.cmd = commander(self)
        self.image_manager = image_manager

    @property
    def asyncio_loop(self):
        return self._tui_loop.asycio_loop

    def add_shortcut(self, action, key, mods=None, is_text=False):
        if not hasattr(self, '_text_shortcuts'):
            self._text_shortcuts, self._key_shortcuts = {}, {}
        if is_text:
            self._text_shortcuts[key] = action
        else:
            self._key_shortcuts[(key, mods or 0)] = action

    def shortcut_action(self, key_event_or_text):
        if isinstance(key_event_or_text, str):
            return self._text_shortcuts.get(key_event_or_text)
        return self._key_shortcuts.get((key_event_or_text.key, key_event_or_text.mods))

    def __enter__(self):
        if self.image_manager is not None:
            self.image_manager.__enter__()
        self.debug.fobj = self
        self.initialize()

    def __exit__(self, *a):
        del self.debug.fobj
        self.finalize()
        if self.image_manager is not None:
            self.image_manager.__exit__(*a)

    def initialize(self):
        pass

    def finalize(self):
        pass

    def on_resize(self, screen_size):
        self.screen_size = screen_size

    def quit_loop(self, return_code=None):
        self._tui_loop.quit(return_code)

    def on_term(self):
        self._tui_loop.quit(1)

    def on_text(self, text, in_bracketed_paste=False):
        pass

    def on_key(self, key_event):
        pass

    def on_mouse(self, mouse_event):
        pass

    def on_interrupt(self):
        pass

    def on_eot(self):
        pass

    def on_kitty_cmd_response(self, response):
        pass

    def on_clipboard_response(self, text, from_primary=False):
        pass

    def on_capability_response(self, name, val):
        pass

    def write(self, data):
        if isinstance(data, str):
            data = data.encode('utf-8')
        self._schedule_write(data)

    def print(self, *args, sep=' ', end='\r\n'):
        data = sep.join(map(str, args)) + end
        self.write(data)

    def suspend(self):
        return self._term_manager.suspend()
