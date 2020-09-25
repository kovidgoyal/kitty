#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import signal
import socket
import subprocess
import sys
from typing import Callable, cast
from urllib.parse import quote_from_bytes


def write_hyperlink(write: Callable[[bytes], None], url: bytes, line: bytes, frag: bytes = b'') -> None:
    text = b'\033]8;;' + url
    if frag:
        text += b'#' + frag
    text += b'\033\\' + line + b'\033]8;;\033\\'
    write(text)


def main() -> None:
    if not sys.stdout.isatty() and '--pretty' not in sys.argv:
        os.execlp('rg', 'rg', *sys.argv[1:])
    cmdline = ['rg', '--pretty', '--with-filename'] + sys.argv[1:]
    p = subprocess.Popen(cmdline, stdout=subprocess.PIPE)
    assert p.stdout is not None
    write: Callable[[bytes], None] = cast(Callable[[bytes], None], sys.stdout.buffer.write)
    sgr_pat = re.compile(br'\x1b\[.*?m')
    osc_pat = re.compile(b'\x1b\\].*?\x1b\\\\')
    num_pat = re.compile(b'^(\\d+):')

    in_result: bytes = b''
    hostname = socket.gethostname().encode('utf-8')

    try:
        for line in p.stdout:
            line = osc_pat.sub(b'', line)  # remove any existing hyperlinks
            clean_line = sgr_pat.sub(b'', line).rstrip()  # remove SGR formatting
            if not clean_line:
                in_result = b''
                write(b'\n')
                continue
            if in_result:
                m = num_pat.match(clean_line)
                if m is not None:
                    write_hyperlink(write, in_result, line, frag=m.group(1))
            else:
                if line.strip():
                    path = quote_from_bytes(os.path.abspath(clean_line)).encode('utf-8')
                    in_result = b'file://' + hostname + path
                    write_hyperlink(write, in_result, line)
                else:
                    write(line)
    except KeyboardInterrupt:
        p.send_signal(signal.SIGINT)
        p.stdout.close()
    except EOFError:
        p.stdout.close()
    raise SystemExit(p.wait())


if __name__ == '__main__':
    main()
