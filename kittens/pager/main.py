#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>


import sys

from kitty.simple_cli_definitions import CompletionSpec

OPTIONS = '''
--role
default=pager
choices=pager,scrollback
The role the pager is used for. The default is a standard less like pager.


--follow
type=bool-set
Follow changes in the specified file, automatically scrolling if currently on the last line.
'''.format

help_text = '''\
Display text in a pager with various features such as searching, copy/paste, etc.
Text can some from the specified file or from STDIN. If no filename is specified
and STDIN is not a TTY, it is used.
'''
usage = '[filename]'


def main(args: list[str]) -> None:
    raise SystemExit('Must be run as kitten pager')


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = 'Pretty, side-by-side diffing of files and images'
    cd['args_completion'] = CompletionSpec.from_string('type:file mime:text/* group:"Text files"')
