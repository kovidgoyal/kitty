#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import sys

from kitty.simple_cli_definitions import CompletionSpec

OPTIONS = r"""
--list
type=bool-set
Instead of asking the user to choose, print the applications that can open
each of the specified files or URLs as JSON. The applications are listed in
order of preference, the system default application, if any, first.
""".format

help_text = """\
Choose an application to open the specified files or URLs with. Applications
are found the same way as the KDE and GNOME desktops do, from the installed
:file:`.desktop` files and the :file:`mimeapps.list` files.
"""

usage = '[file or URL ...]'


def main(args: list[str]) -> None:
    raise SystemExit('This must be run as kitten choose-app')


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = 'Choose an application to open files and URLs with'
    cd['args_completion'] = CompletionSpec.from_string('type:file group:"Files"')
