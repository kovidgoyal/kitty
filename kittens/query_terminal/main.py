#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import re
import sys
from binascii import hexlify, unhexlify
from contextlib import suppress
from typing import get_args

from kitty.conf.utils import OSNames, os_name
from kitty.constants import appname, str_version
from kitty.options.types import Options
from kitty.terminfo import names


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
        self.pat = re.compile(f'\x1bP([01])\\+r{self.encoded_query_name}(.*?)\x1b\\\\'.encode('ascii'))

    def query_code(self) -> str:
        return f"\x1bP+q{self.encoded_query_name}\x1b\\"

    def decode_response(self, res: bytes | memoryview) -> str:
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
    def get_result(opts: Options, window_id: int, os_window_id: int) -> str:
        raise NotImplementedError()


all_queries: dict[str, type[Query]] = {}


def query(cls: type[Query]) -> type[Query]:
    all_queries[cls.name] = cls
    return cls


@query
class TerminalName(Query):
    name: str = 'name'
    override_query_name: str = 'name'
    help_text: str = f'Terminal name (e.g. :code:`{names[0]}`)'

    @staticmethod
    def get_result(opts: Options, window_id: int, os_window_id: int) -> str:
        return appname


@query
class TerminalVersion(Query):
    name: str = 'version'
    help_text: str = f'Terminal version (e.g. :code:`{str_version}`)'

    @staticmethod
    def get_result(opts: Options, window_id: int, os_window_id: int) -> str:
        return str_version


@query
class AllowHyperlinks(Query):
    name: str = 'allow_hyperlinks'
    help_text: str = 'The config option :opt:`allow_hyperlinks` in :file:`kitty.conf` for allowing hyperlinks can be :code:`yes`, :code:`no` or :code:`ask`'

    @staticmethod
    def get_result(opts: Options, window_id: int, os_window_id: int) -> str:
        return 'ask' if opts.allow_hyperlinks == 0b11 else ('yes' if opts.allow_hyperlinks else 'no')


@query
class FontFamily(Query):
    name: str = 'font_family'
    help_text: str = 'The current font\'s PostScript name'

    @staticmethod
    def get_result(opts: Options, window_id: int, os_window_id: int) -> str:
        from kitty.fast_data_types import current_fonts
        cf = current_fonts(os_window_id)
        return cf['medium'].postscript_name()


@query
class BoldFont(Query):
    name: str = 'bold_font'
    help_text: str = 'The current bold font\'s PostScript name'

    @staticmethod
    def get_result(opts: Options, window_id: int, os_window_id: int) -> str:
        from kitty.fast_data_types import current_fonts
        cf = current_fonts(os_window_id)
        return cf['bold'].postscript_name()


@query
class ItalicFont(Query):
    name: str = 'italic_font'
    help_text: str = 'The current italic font\'s PostScript name'

    @staticmethod
    def get_result(opts: Options, window_id: int, os_window_id: int) -> str:
        from kitty.fast_data_types import current_fonts
        cf = current_fonts(os_window_id)
        return cf['italic'].postscript_name()


@query
class BiFont(Query):
    name: str = 'bold_italic_font'
    help_text: str = 'The current bold-italic font\'s PostScript name'

    @staticmethod
    def get_result(opts: Options, window_id: int, os_window_id: int) -> str:
        from kitty.fast_data_types import current_fonts
        cf = current_fonts(os_window_id)
        return cf['bi'].postscript_name()


@query
class FontSize(Query):
    name: str = 'font_size'
    help_text: str = 'The current font size in pts'

    @staticmethod
    def get_result(opts: Options, window_id: int, os_window_id: int) -> str:
        from kitty.fast_data_types import current_fonts
        cf = current_fonts(os_window_id)
        return f'{cf["font_sz_in_pts"]:g}'

@query
class DpiX(Query):
    name: str = 'dpi_x'
    help_text: str = 'The current DPI on the x-axis'

    @staticmethod
    def get_result(opts: Options, window_id: int, os_window_id: int) -> str:
        from kitty.fast_data_types import current_fonts
        cf = current_fonts(os_window_id)
        return f'{cf["logical_dpi_x"]:g}'

@query
class DpiY(Query):
    name: str = 'dpi_y'
    help_text: str = 'The current DPI on the y-axis'

    @staticmethod
    def get_result(opts: Options, window_id: int, os_window_id: int) -> str:
        from kitty.fast_data_types import current_fonts
        cf = current_fonts(os_window_id)
        return f'{cf["logical_dpi_y"]:g}'


@query
class Foreground(Query):
    name: str = 'foreground'
    help_text: str = 'The current foreground color as a 24-bit # color code'

    @staticmethod
    def get_result(opts: Options, window_id: int, os_window_id: int) -> str:
        from kitty.fast_data_types import get_boss, get_options
        boss = get_boss()
        w = boss.window_id_map.get(window_id)
        if w is None:
            return opts.foreground.as_sharp
        return (w.screen.color_profile.default_fg or get_options().foreground).as_sharp


@query
class Background(Query):
    name: str = 'background'
    help_text: str = 'The current background color as a 24-bit # color code'

    @staticmethod
    def get_result(opts: Options, window_id: int, os_window_id: int) -> str:
        from kitty.fast_data_types import get_boss, get_options
        boss = get_boss()
        w = boss.window_id_map.get(window_id)
        if w is None:
            return opts.background.as_sharp
        return (w.screen.color_profile.default_bg or get_options().background).as_sharp


@query
class BackgroundOpacity(Query):
    name: str = 'background_opacity'
    help_text: str = 'The current background opacity as a number between 0 and 1'

    @staticmethod
    def get_result(opts: Options, window_id: int, os_window_id: int) -> str:
        from kitty.fast_data_types import background_opacity_of
        ans = background_opacity_of(os_window_id)
        if ans is None:
            ans = 1.0
        return f'{ans:g}'


@query
class ClipboardControl(Query):
    name: str = 'clipboard_control'
    help_text: str = 'The config option :opt:`clipboard_control` in :file:`kitty.conf` for allowing reads/writes to/from the clipboard'

    @staticmethod
    def get_result(opts: Options, window_id: int, os_window_id: int) -> str:
        return ' '.join(opts.clipboard_control)


@query
class OSName(Query):
    name: str = 'os_name'
    help_text: str = f'The name of the OS the terminal is running on. kitty returns values: {", ".join(sorted(get_args(OSNames)))}'

    @staticmethod
    def get_result(opts: Options, window_id: int, os_window_id: int) -> OSNames:
        return os_name()


def get_result(name: str, window_id: int, os_window_id: int) -> str | None:
    from kitty.fast_data_types import get_options
    q = all_queries.get(name)
    if q is None:
        return None
    return q.get_result(get_options(), window_id, os_window_id)


def options_spec() -> str:
    return '''\
--wait-for
type=float
default=10
The amount of time (in seconds) to wait for a response from the terminal, after
querying it.
'''


help_text = '''\
Query the terminal this kitten is run in for various capabilities. This sends
escape codes to the terminal and based on its response prints out data about
supported capabilities. Note that this is a blocking operation, since it has to
wait for a response from the terminal. You can control the maximum wait time via
the :code:`--wait-for` option.

The output is lines of the form::

    query: data

If a particular :italic:`query` is unsupported by the running kitty version, the
:italic:`data` will be blank.

Note that when calling this from another program, be very careful not to perform
any I/O on the terminal device until this kitten exits.

Available queries are:

{}

'''.format('\n'.join(
    f':code:`{name}`:\n  {c.help_text}\n' for name, c in all_queries.items()))
usage = '[query1 query2 ...]'


if __name__ == '__main__':
    raise SystemExit('Should be run as kitten hints')
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = options_spec
    cd['help_text'] = help_text
    cd['short_desc'] = 'Query the terminal for various capabilities'
