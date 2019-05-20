#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys


from ..tui.handler import Handler
from ..tui.loop import Loop

from . import subseq_matcher


def match(
    input_data,
    query,
    threads=0,
    positions=False,
    level1='/',
    level2='-_0123456789',
    level3='.',
    limit=0,
    mark_before='',
    mark_after='',
    delimiter='\n'
):
    if isinstance(input_data, str):
        input_data = input_data.encode('utf-8')
    if isinstance(input_data, bytes):
        input_data = input_data.split(delimiter.encode('utf-8'))
    else:
        input_data = [x.encode('utf-8') if isinstance(x, str) else x for x in input_data]
    query = query.lower()
    level1 = level1.lower()
    level2 = level2.lower()
    level3 = level3.lower()
    data = subseq_matcher.match(
        input_data, (level1, level2, level3), query,
        positions, limit, threads,
        mark_before, mark_after, delimiter)
    if data is None:
        return []
    return list(filter(None, data.split(delimiter or '\n')))


class ChooseHandler(Handler):

    def initialize(self):
        pass

    def on_text(self, text, in_bracketed_paste=False):
        pass

    def on_key(self, key_event):
        pass

    def on_interrupt(self):
        self.quit_loop(1)

    def on_eot(self):
        self.quit_loop(1)


def main(args):
    loop = Loop()
    handler = ChooseHandler()
    loop.loop(handler)
    raise SystemExit(loop.return_code)


if __name__ == '__main__':
    main(sys.argv)
