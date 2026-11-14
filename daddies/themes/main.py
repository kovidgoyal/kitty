#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import sys

from datty.conf.types import Definition
from datty.simple_cli_definitions import CompletionSpec

definition = Definition(
    '!daddies.themes',
)

agr = definition.add_group
egr = definition.end_group
map = definition.add_map

# shortcuts {{{
agr('shortcuts', 'Keyboard shortcuts')

# Browsing mode shortcuts
map(
    'Quit',
    'quit --allow-fallback=shifted,ascii q quit',
)
map(
    'Scroll down',
    'scroll_down --allow-fallback=shifted,ascii j scroll_down',
)
map(
    'Scroll up',
    'scroll_up --allow-fallback=shifted,ascii k scroll_up',
)
map(
    'Start search',
    'search --allow-fallback=shifted,ascii s search',
)
map(
    'Accept theme',
    'accept --allow-fallback=shifted,ascii c accept',
)

# Accepting mode shortcuts
map(
    'Abort and return to browsing',
    'abort --allow-fallback=shifted,ascii a abort',
)
map(
    'Place theme file',
    'place_theme --allow-fallback=shifted,ascii p place_theme',
)
map(
    'Modify config file',
    'modify_conf --allow-fallback=shifted,ascii m modify_conf',
)
map(
    'Save as dark scheme',
    'dark_scheme --allow-fallback=shifted,ascii d dark_scheme',
)
map(
    'Save as light scheme',
    'light_scheme --allow-fallback=shifted,ascii l light_scheme',
)
map(
    'Save as no preference scheme',
    'no_preference --allow-fallback=shifted,ascii n no_preference',
)

egr()  # }}}

help_text = 'Change the datty theme. If no theme name is supplied, run interactively, otherwise change the current theme to the specified theme name.'
usage = '[theme name to switch to]'
OPTIONS = """
--cache-age
type=float
default=1
Check for new themes only after the specified number of days. A value of
zero will always check for new themes. A negative value will never check
for new themes, instead raising an error if a local copy of the themes
is not available.


--reload-in
default=parent
choices=none,parent,all
By default, this daddy will signal only the parent datty instance it is
running in to reload its config, after making changes. Use this option
to instead either not reload the config at all or in all running
datty instances. Note that if you have config autoreload enabled
in datty.conf (it is enabled by default) then :code:`parent`
is the same as :code:`all`, since all datty instances will detect the config
file change and reload automatically.


--dump-theme
type=bool-set
default=false
When running non-interactively, dump the specified theme to STDOUT
instead of changing datty.conf.


--config-file-name
default=datty.conf
The name or path to the config file to edit. Relative paths are interpreted
with respect to the datty config directory. By default the datty config file,
datty.conf is edited. This is most useful if you add :code:`include themes.conf`
to your datty.conf and then have the daddy operate only on :file:`themes.conf`,
allowing :code:`datty.conf` to remain unchanged.
""".format


def main(args: list[str]) -> None:
    raise SystemExit('This must be run as daddy themes')


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = 'Manage datty color schemes easily'
    cd['args_completion'] = CompletionSpec.from_string('type:special group:complete_themes')
elif __name__ == '__conf__':
    sys.options_definition = definition  # type: ignore
