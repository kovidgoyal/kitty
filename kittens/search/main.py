#!/usr/bin/env python


import sys

from kitty.conf.types import Definition

definition = Definition(
    '!kittens.search',
)

agr = definition.add_group
egr = definition.end_group
map = definition.add_map

# shortcuts {{{
agr('shortcuts', 'Keyboard shortcuts')

map(
    'Move selection up',
    'selection_up ctrl+k selection_up',
)
map(
    'Move selection down',
    'selection_down ctrl+j selection_down',
)

egr()  # }}}

OPTIONS = r"""
--selection
default=
Help text for the selected text to pre-populate search.
""".format

usage = ''
short_description = ''
help_text = 'Search using the search kitten'

if __name__ == '__main__':
    raise SystemExit('This kitten must be used only from a kitty.conf mapping')
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = help_text
elif __name__ == '__conf__':
    sys.options_definition = definition  # type: ignore
