#!/usr/bin/env python3
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import codecs
import io
import os
import select
import sys
from typing import List, NoReturn, Optional

from kitty.cli import parse_args
from kitty.cli_stub import ClipboardCLIOptions
from kitty.fast_data_types import parse_input_from_terminal

from ..tui.operations import (
    raw_mode, request_from_clipboard, write_to_clipboard
)

OPTIONS = r'''
--get-clipboard
type=bool-set
Output the current contents of the clipboard to STDOUT. Note that by default
kitty will prompt for permission to access the clipboard. Can be controlled
by :opt:`clipboard_control`.


--use-primary
type=bool-set
Use the primary selection rather than the clipboard on systems that support it,
such as X11.


--wait-for-completion
type=bool-set
Wait till the copy to clipboard is complete before exiting. Useful if running
the kitten in a dedicated, ephemeral window.
'''.format
help_text = '''\
Read or write to the system clipboard.

To set the clipboard text, pipe in the new text on STDIN. Use the
:option:`--get-clipboard` option to output the current clipboard contents to
:file:`stdout`. Note that reading the clipboard will cause a permission
popup, see :opt:`clipboard_control` for details.
'''

usage = ''
got_capability_response = False
got_clipboard_response = False
clipboard_contents = ''
clipboard_from_primary = False


def ignore(x: str) -> None:
    pass


def on_text(x: str) -> None:
    if '\x03' in x:
        raise KeyboardInterrupt()
    if '\x04' in x:
        raise EOFError()


def on_dcs(dcs: str) -> None:
    global got_capability_response
    if dcs.startswith('1+r'):
        got_capability_response = True


def on_osc(osc: str) -> None:
    global clipboard_contents, clipboard_from_primary, got_clipboard_response
    idx = osc.find(';')
    if idx <= 0:
        return
    q = osc[:idx]
    if q == '52':
        got_clipboard_response = True
        widx = osc.find(';', idx + 1)
        if widx < idx:
            clipboard_from_primary = osc.find('p', idx + 1) > -1
            clipboard_contents = ''
        else:
            from base64 import standard_b64decode
            clipboard_from_primary = osc.find('p', idx+1, widx) > -1
            data = memoryview(osc.encode('ascii'))
            clipboard_contents = standard_b64decode(data[widx+1:]).decode('utf-8')


def wait_loop(tty_fd: int) -> None:
    os.set_blocking(tty_fd, False)
    decoder = codecs.getincrementaldecoder('utf-8')('ignore')
    with raw_mode(tty_fd):
        buf = ''
        while not got_capability_response and not got_clipboard_response:
            rd = select.select([tty_fd], [], [])[0]
            if rd:
                raw = os.read(tty_fd, io.DEFAULT_BUFFER_SIZE)
                if not raw:
                    raise EOFError()
                data = decoder.decode(raw)
                buf = (buf + data) if buf else data
                buf = parse_input_from_terminal(on_text, on_dcs, ignore, on_osc, ignore, ignore, buf, False)


def main(args: List[str]) -> NoReturn:
    cli_opts, items = parse_args(args[1:], OPTIONS, usage, help_text, 'kitty +kitten clipboard', result_class=ClipboardCLIOptions)
    if items:
        raise SystemExit('Unrecognized extra command line arguments')
    data: Optional[bytes] = None
    if not sys.stdin.isatty():
        data = sys.stdin.buffer.read()
    wait_for_capability_response = False
    data_to_write = []
    if data:
        data_to_write.append(write_to_clipboard(data, cli_opts.use_primary).encode('ascii'))
        if not cli_opts.get_clipboard and cli_opts.wait_for_completion:
            data_to_write.append(b'\x1bP+q544e\x1b\\')
            wait_for_capability_response = True
    if cli_opts.get_clipboard:
        data_to_write.append(request_from_clipboard(cli_opts.use_primary).encode('ascii'))
        wait_for_capability_response = True
    tty_fd = os.open(os.ctermid(), os.O_RDWR | os.O_CLOEXEC)
    retcode = 0
    with open(tty_fd, 'wb', closefd=True) as ttyf:
        for x in data_to_write:
            ttyf.write(x)
        ttyf.flush()
        if wait_for_capability_response:
            try:
                wait_loop(tty_fd)
            except KeyboardInterrupt:
                sys.excepthook = lambda *a: None
                raise
            except EOFError:
                retcode = 1
    if clipboard_contents:
        print(end=clipboard_contents)

    raise SystemExit(retcode)


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
