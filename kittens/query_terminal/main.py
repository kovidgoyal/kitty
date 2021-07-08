#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import re
import sys
from binascii import hexlify, unhexlify
from contextlib import suppress
from typing import Dict, Iterable, List, Type, Optional

from kitty.cli import parse_args
from kitty.cli_stub import QueryTerminalCLIOptions
from kitty.constants import appname, str_version
from kitty.options.types import Options
from kitty.terminfo import names
from kitty.utils import TTYIO


class Query:
    name: str = ''
    ans: str = ''
    help_text: str = ''
    override_query_name: str = ''

    @property
    def query_name(self) -> str:
        return self.override_query_name or f'kitty-query-{self.name}'

    def __init__(self) -> None:
        self.encoded_query_name = hexlify(self.query_name.encode('utf-8')).decode('ascii')
        self.pat = re.compile('\x1bP([01])\\+r{}(.*?)\x1b\\\\'.format(self.encoded_query_name).encode('ascii'))

    def query_code(self) -> str:
        return "\x1bP+q{}\x1b\\".format(self.encoded_query_name)

    def decode_response(self, res: bytes) -> str:
        return unhexlify(res).decode('utf-8')

    def more_needed(self, buffer: bytes) -> bool:
        m = self.pat.search(buffer)
        if m is None:
            return True
        if m.group(1) == b'1':
            q = m.group(2)
            if q.startswith(b'='):
                with suppress(Exception):
                    self.ans = self.decode_response(memoryview(q)[1:])
        return False

    def output_line(self) -> str:
        return self.ans

    @staticmethod
    def get_result(opts: Options) -> str:
        raise NotImplementedError()


all_queries: Dict[str, Type[Query]] = {}


def query(cls: Type[Query]) -> Type[Query]:
    all_queries[cls.name] = cls
    return cls


@query
class TerminalName(Query):
    name: str = 'name'
    override_query_name: str = 'name'
    help_text: str = f'Terminal name ({names[0]})'

    @staticmethod
    def get_result(opts: Options) -> str:
        return appname


@query
class TerminalVersion(Query):
    name: str = 'version'
    help_text: str = 'Terminal version, for e.g.: 0.19.2'

    @staticmethod
    def get_result(opts: Options) -> str:
        return str_version


@query
class AllowHyperlinks(Query):
    name: str = 'allow_hyperlinks'
    help_text: str = 'yes, no or ask'

    @staticmethod
    def get_result(opts: Options) -> str:
        return 'ask' if opts.allow_hyperlinks == 0b11 else ('yes' if opts.allow_hyperlinks else 'no')


@query
class AllowResizeCSI(Query):
    name: str = 'allow_resize_csi'
    help_text: str = 'yes or no'

    @staticmethod
    def get_result(opts: Options) -> str:
        return 'yes' if opts.allow_resize_csi else 'no'


@query
class FontFamily(Query):
    name: str = 'font_family'
    help_text: str = 'The current font\'s PostScript name'

    @staticmethod
    def get_result(opts: Options) -> str:
        from kitty.fast_data_types import current_fonts
        cf = current_fonts()
        return str(cf['medium'].display_name())


@query
class BoldFont(Query):
    name: str = 'bold_font'
    help_text: str = 'The current bold font\'s PostScript name'

    @staticmethod
    def get_result(opts: Options) -> str:
        from kitty.fast_data_types import current_fonts
        cf = current_fonts()
        return str(cf['bold'].display_name())


@query
class ItalicFont(Query):
    name: str = 'italic_font'
    help_text: str = 'The current italic font\'s PostScript name'

    @staticmethod
    def get_result(opts: Options) -> str:
        from kitty.fast_data_types import current_fonts
        cf = current_fonts()
        return str(cf['italic'].display_name())


@query
class BiFont(Query):
    name: str = 'bold_italic_font'
    help_text: str = 'The current bold-italic font\'s PostScript name'

    @staticmethod
    def get_result(opts: Options) -> str:
        from kitty.fast_data_types import current_fonts
        cf = current_fonts()
        return str(cf['bi'].display_name())


@query
class FontSize(Query):
    name: str = 'font_size'
    help_text: str = 'The current overall font size (individual windows can have different per window font sizes)'

    @staticmethod
    def get_result(opts: Options) -> str:
        return f'{opts.font_size:g}'


def get_result(name: str) -> Optional[str]:
    from kitty.fast_data_types import get_options
    q = all_queries.get(name)
    if q is None:
        return None
    return q.get_result(get_options())


def do_queries(queries: Iterable, cli_opts: QueryTerminalCLIOptions) -> Dict[str, str]:
    actions = tuple(all_queries[x]() for x in queries)
    qstring = ''.join(a.query_code() for a in actions)
    received = b''

    def more_needed(data: bytes) -> bool:
        nonlocal received
        received += data
        for a in actions:
            if a.more_needed(received):
                return True
        return False

    with TTYIO() as ttyio:
        ttyio.send(qstring)
        ttyio.recv(more_needed, timeout=cli_opts.wait_for)

    return {a.name: a.output_line() for a in actions}


def options_spec() -> str:
    return '''\
--wait-for
type=float
default=10
The amount of time (in seconds) to wait for a response from the terminal, after
querying it.
'''


help_text = '''\
Query the terminal this kitten is run in for various
capabilities. This sends escape codes to the terminal
and based on its response prints out data about supported
capabilities. Note that this is a blocking operation, since
it has to wait for a response from the terminal. You can control
the maximum wait time via the ``--wait-for`` option.

The output is lines of the form::

  query: data

If a particular query is unsupported by the running kitty version,
the data will be blank.

Note that when calling this from another program, be very
careful not to perform any I/O on the terminal device
until the kitten exits.

Available queries are::

{}
'''.format('  ' + '\n  '.join(
    f'{name}: {c.help_text}' for name, c in all_queries.items()))
usage = '[query1 query2 ...]'


def main(args: List[str] = sys.argv) -> None:
    cli_opts, items_ = parse_args(
        args[1:],
        options_spec,
        usage,
        help_text,
        '{} +kitten query_terminal'.format(appname),
        result_class=QueryTerminalCLIOptions
    )
    queries: List[str] = list(items_)
    if 'all' in queries or not queries:
        queries = sorted(all_queries)
    else:
        extra = frozenset(queries) - frozenset(all_queries)
        if extra:
            raise SystemExit(f'Unknown queries: {", ".join(extra)}')

    for key, val in do_queries(queries, cli_opts).items():
        print(key + ':', val)


if __name__ == '__main__':
    main()
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = options_spec
    cd['help_text'] = help_text
