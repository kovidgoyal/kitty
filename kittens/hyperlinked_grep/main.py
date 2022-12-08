#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import os
import re
import signal
import subprocess
import sys
from typing import Callable, List, cast
from urllib.parse import quote_from_bytes

from kitty.utils import get_hostname


def write_hyperlink(write: Callable[[bytes], None], url: bytes, line: bytes, frag: bytes = b'') -> None:
    text = b'\033]8;;' + url
    if frag:
        text += b'#' + frag
    text += b'\033\\' + line + b'\033]8;;\033\\'
    write(text)


def parse_options(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument('--context-separator', default='--')
    p.add_argument('-c', '--count', action='store_true')
    p.add_argument('--count-matches', action='store_true')
    p.add_argument('--field-context-separator', default='-')
    p.add_argument('--field-match-separator', default='-')
    p.add_argument('--files', action='store_true')
    p.add_argument('-l', '--files-with-matches', action='store_true')
    p.add_argument('--files-without-match', action='store_true')
    p.add_argument('-h', '--help', action='store_true')
    p.add_argument('--json', action='store_true')
    p.add_argument('-I', '--no-filename', action='store_true')
    p.add_argument('--no-heading', action='store_true')
    p.add_argument('-N', '--no-line-number', action='store_true')
    p.add_argument('-0', '--null', action='store_true')
    p.add_argument('--null-data', action='store_true')
    p.add_argument('--path-separator', default=os.path.sep)
    p.add_argument('--stats', action='store_true')
    p.add_argument('--type-list', action='store_true')
    p.add_argument('-V', '--version', action='store_true')
    p.add_argument('--vimgrep', action='store_true')
    p.add_argument(
        '-p', '--pretty',
        default=sys.stdout.isatty(),
        action='store_true',
    )
    p.add_argument('--kitten', action='append')
    args, _ = p.parse_known_args(argv)
    return args


def main() -> None:
    i = 1
    args = parse_options(sys.argv[1:])
    all_link_options = {'matching_lines', 'context_lines', 'file_headers'}
    link_options = set()
    delegate_to_rg = False

    for raw in args.kitten:
        p, _, s = raw.partition('=')
        if p != 'hyperlink':
            raise SystemExit(f'Unknown argument for --kitten: {raw}')
        for option in s.split(','):
            if option == 'all':
                link_options.update(all_link_options)
                delegate_to_rg = False
            elif option == 'none':
                delegate_to_rg = True
                link_options.clear()
            elif option not in all_link_options:
                a = ', '.join(sorted(all_link_options))
                raise SystemExit(f"hyperlink option must be one of all, none, {a}, not '{option}'")
            else:
                link_options.add(option)
                delegate_to_rg = False

    while i < len(sys.argv):
        if sys.argv[i] == '--kitten':
            del sys.argv[i:i+2]
        elif sys.argv[i].startswith('--kitten='):
            del sys.argv[i]
        else:
            i += 1
    if not link_options:  # Default to linking everything if no options given
        link_options.update(all_link_options)
    link_file_headers = 'file_headers' in link_options
    link_context_lines = 'context_lines' in link_options
    link_matching_lines = 'matching_lines' in link_options

    if any((
        args.context_separator != '--',
        args.field_context_separator != '-',
        args.field_match_separator != '-',
        args.help,
        args.json,
        args.no_filename,
        args.null,
        args.null_data,
        args.path_separator != os.path.sep,
        args.type_list,
        args.version,
        not args.pretty,
    )):
        delegate_to_rg = True

    if delegate_to_rg:
        os.execlp('rg', 'rg', *sys.argv[1:])
    cmdline = ['rg', '--pretty', '--with-filename'] + sys.argv[1:]
    try:
        p = subprocess.Popen(cmdline, stdout=subprocess.PIPE)
    except FileNotFoundError:
        raise SystemExit('Could not find the rg executable in your PATH. Is ripgrep installed?')
    assert p.stdout is not None

    def get_quoted_path(x: bytes) -> bytes:
        return quote_from_bytes(os.path.abspath(x)).encode('utf-8')

    write: Callable[[bytes], None] = cast(Callable[[bytes], None], sys.stdout.buffer.write)
    sgr_pat = re.compile(br'\x1b\[.*?m')
    osc_pat = re.compile(b'\x1b\\].*?\x1b\\\\')
    num_pat = re.compile(br'^(\d+)([:-])')
    path_with_count_pat = re.compile(br'(.*?)(:\d+)')
    path_with_linenum_pat = re.compile(br'^(.*?):(\d+):')
    stats_pat = re.compile(br'^\d+ matches$')
    vimgrep_pat = re.compile(br'^(.*?):(\d+):(\d+):')

    in_stats = False
    in_result: bytes = b''
    hostname = get_hostname().encode('utf-8')

    try:
        for line in p.stdout:
            line = osc_pat.sub(b'', line)  # remove any existing hyperlinks
            clean_line = sgr_pat.sub(b'', line).rstrip()  # remove SGR formatting
            if not clean_line:
                in_result = b''
                write(b'\n')
            elif in_stats:
                write(line)
            elif in_result:
                if not args.no_line_number:
                    m = num_pat.match(clean_line)
                    if m is not None:
                        is_match_line = m.group(2) == b':'
                        if (is_match_line and link_matching_lines) or (not is_match_line and link_context_lines):
                            write_hyperlink(write, in_result, line, frag=m.group(1))
                            continue
                write(line)
            else:
                if line.strip():
                    # The option priority should be consistent with ripgrep here.
                    if args.stats and not in_stats and stats_pat.match(clean_line):
                        in_stats = True
                    elif args.count or args.count_matches:
                        m = path_with_count_pat.match(clean_line)
                        if m is not None and link_file_headers:
                            write_hyperlink(write, b'file://' + hostname + get_quoted_path(m.group(1)), line)
                            continue
                    elif args.files or args.files_with_matches or args.files_without_match:
                        if link_file_headers:
                            write_hyperlink(write, get_quoted_path(clean_line), line)
                            continue
                    elif args.vimgrep or args.no_heading:
                        # When the vimgrep option is present, it will take precedence.
                        m = vimgrep_pat.match(clean_line) if args.vimgrep else path_with_linenum_pat.match(clean_line)
                        if m is not None and (link_file_headers or link_matching_lines):
                            write_hyperlink(write, b'file://' + hostname + get_quoted_path(m.group(1)), line, frag=m.group(2))
                            continue
                    else:
                        in_result = b'file://' + hostname + get_quoted_path(clean_line)
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
elif __name__ == '__wrapper_of__':
    cd = sys.cli_docs  # type: ignore
    cd['wrapper_of'] = 'rg'
