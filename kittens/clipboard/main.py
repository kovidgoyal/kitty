#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from kitty.cli import parse_args

from ..tui.handler import Handler
from ..tui.loop import Loop


class Clipboard(Handler):

    def __init__(self, data_to_send, args):
        self.args = args
        self.print_on_fail = None
        self.clipboard_contents = None
        self.data_to_send = data_to_send

    def initialize(self):
        if self.data_to_send is not None:
            self.cmd.write_to_clipboard(self.data_to_send, self.args.use_primary)
        if not self.args.get_clipboard:
            self.quit_loop(0)
            return
        self.cmd.request_from_clipboard(self.args.use_primary)

    def on_clipboard_response(self, text, from_primary=False):
        self.clipboard_contents = text
        self.quit_loop(0)


OPTIONS = r'''
--get-clipboard
default=False
type=bool-set
Output the current contents of the clipboard to stdout. Note that this
will not work if you have not enabled the option to allow reading the clipboard
in kitty.conf


--use-primary
default=False
type=bool-set
Use the primary selection rather than the clipboard on systems that support it,
such as X11.
'''.format


def main(args):
    msg = '''\
Read or write to the system clipboard.

To set the clipboard text, pipe in the new text on stdin. Use the --get-clipboard option \
to output the current clipboard contents to stdout. Note that you must enable reading of clipboard in kitty.conf first. '''
    args, items = parse_args(args[1:], OPTIONS, '', msg, 'clipboard')
    if items:
        raise SystemExit('Unrecognized extra command line arguments')
    data = None
    if not sys.stdin.isatty():
        data = sys.stdin.buffer.read()
        sys.stdin = open('/dev/tty', 'r')
    loop = Loop()
    handler = Clipboard(data, args)
    loop.loop(handler)
    if loop.return_code == 0 and handler.clipboard_contents:
        sys.stdout.write(handler.clipboard_contents)
        sys.stdout.flush()
    if handler.print_on_fail:
        print(handler.print_on_fail, file=sys.stderr)
        input('Press Enter to quit')
    raise SystemExit(loop.return_code)


if __name__ == '__main__':
    main(sys.argv)
