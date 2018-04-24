#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>


class Handler:

    def _initialize(self, screen_size, quit_loop, wakeup, start_job):
        self.screen_size, self.quit_loop = screen_size, quit_loop
        self.wakeup = wakeup
        self.start_job = start_job

    def __enter__(self):
        self.initialize()

    def __exit__(self, *a):
        del self.write_buf[:]
        self.finalize()

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

    def write(self, data):
        if isinstance(data, str):
            data = data.encode('utf-8')
        self.write_buf.append(data)

    def print(self, *args, sep=' ', end='\r\n'):
        data = sep.join(map(str, args)) + end
        self.write(data)

    def suspend(self):
        return self._term_manager.suspend()
