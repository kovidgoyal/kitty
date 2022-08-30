#!/usr/bin/env python
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
    i = 1
    all_link_options = ['matching_lines', 'context_lines', 'file_headers']
    link_options = set()
    while i < len(sys.argv):
        if sys.argv[i] == '--kitten':
            if len(sys.argv) < i + 2 or not sys.argv[i + 1].startswith("hyperlink="):
                raise SystemExit("--kitten argument must be followed by hyperlink=(all|matching_lines|context_lines|file_headers)")
            for option in sys.argv[i + 1].split('=')[1].split(','):
                if option == 'all':
                    link_options.update(all_link_options)
                elif option not in all_link_options:
                    raise SystemExit(f"hyperlink option must be one of all, matching_lines, context_lines, or file_headers, not '{option}'")
                else:
                    link_options.add(option)
            del sys.argv[i:i+2]
        else:
            i += 1
    if len(link_options) == 0: # Default to linking everything if no options given
        link_options.update(all_link_options)
    link_file_headers = 'file_headers' in link_options
    link_context_lines = 'context_lines' in link_options
    link_matching_lines = 'matching_lines' in link_options

    if not sys.stdout.isatty() and '--pretty' not in sys.argv and '-p' not in sys.argv:
        os.execlp('rg', 'rg', *sys.argv[1:])
    cmdline = ['rg', '--pretty', '--with-filename'] + sys.argv[1:]
    try:
        p = subprocess.Popen(cmdline, stdout=subprocess.PIPE)
    except FileNotFoundError:
        raise SystemExit('Could not find the rg executable in your PATH. Is ripgrep installed?')
    assert p.stdout is not None
    write: Callable[[bytes], None] = cast(Callable[[bytes], None], sys.stdout.buffer.write)
    sgr_pat = re.compile(br'\x1b\[.*?m')
    osc_pat = re.compile(b'\x1b\\].*?\x1b\\\\')
    num_pat = re.compile(br'^(\d+)([:-])')

    in_result: bytes = b''
    hostname = socket.gethostname().encode('utf-8')

    try:
        for line in p.stdout:
            line = osc_pat.sub(b'', line)  # remove any existing hyperlinks
            clean_line = sgr_pat.sub(b'', line).rstrip()  # remove SGR formatting
            if not clean_line:
                in_result = b''
                write(b'\n')
            elif in_result:
                m = num_pat.match(clean_line)
                if m is not None:
                    is_match_line = m.group(2) == b':'
                    if (is_match_line and link_matching_lines) or (not is_match_line and link_context_lines):
                        write_hyperlink(write, in_result, line, frag=m.group(1))
                        continue
                write(line)
            else:
                if line.strip():
                    path = quote_from_bytes(os.path.abspath(clean_line)).encode('utf-8')
                    in_result = b'file://' + hostname + path
                    if link_file_headers:
                        write_hyperlink(write, in_result, line)
                        continue
                write(line)
    except KeyboardInterrupt:
        p.send_signal(signal.SIGINT)
    except (EOFError, BrokenPipeError):
        pass
    finally:
        p.stdout.close()
    raise SystemExit(p.wait())


if __name__ == '__main__':
    main()
