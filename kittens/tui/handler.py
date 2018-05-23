#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>


from .operations import commander


class Handler:

    image_manager_class = None

    def _initialize(self, screen_size, quit_loop, wakeup, start_job, debug, image_manager=None):
        self.screen_size, self.quit_loop = screen_size, quit_loop
        self.wakeup = wakeup
        self.debug = debug
        self.start_job = start_job
        self.cmd = commander(self)
        self.image_manager = image_manager

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
        del self.write_buf[:]
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

    def on_term(self):
        self.quit_loop(1)

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

    def on_wakeup(self):
        pass

    def on_job_done(self, job_id, job_result):
        pass

    def on_kitty_cmd_response(self, response):
        pass

    def on_clipboard_response(self, text, from_primary=False):
        pass

    def write(self, data):
        if isinstance(data, str):
            data = data.encode('utf-8')
        self.write_buf.append(data)

    def print(self, *args, sep=' ', end='\r\n'):
        data = sep.join(map(str, args)) + end
        self.write(data)

    def suspend(self):
        return self._term_manager.suspend()
