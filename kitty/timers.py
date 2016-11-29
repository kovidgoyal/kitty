#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections import namedtuple
from operator import itemgetter
from time import monotonic


Event = namedtuple('Event', 'at callback args')
get_at = itemgetter(0)


class Timers:

    def __init__(self):
        self.timers = []

    def add(self, delay, callback, *args):
        self.remove(callback)
        self.timers.append(Event(monotonic() + delay, callback, args))
        self.timers.sort(key=get_at)

    def add_if_missing(self, delay, callback, *args):
        for ev in self.timers:
            if ev.callback is callback:
                break
        else:
            self.add(delay, callback, *args)

    def remove(self, callback):
        for i, ev in enumerate(self.timers):
            if ev.callback is callback:
                break
        else:
            return
        del self.timers[i]

    def timeout(self):
        if self.timers:
            return max(0, self.timers[0][0] - monotonic())

    def __call__(self):
        if self.timers:
            now = monotonic()
            for i, ev in enumerate(self.timers):
                if ev[0] <= now:
                    try:
                        ev.callback(*ev.args)
                    except Exception:
                        import traceback
                        traceback.print_exc()
                else:
                    break
            else:
                del self.timers[:]
                return
            del self.timers[:i]
