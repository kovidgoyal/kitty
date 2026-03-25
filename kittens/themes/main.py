#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import sys

from kitty.conf.types import Definition
from kitty.simple_cli_definitions import CompletionSpec

definition = Definition(
    '!kittens.themes',
)

agr = definition.add_group
egr = definition.end_group
map = definition.add_map

# shortcuts {{{
agr('shortcuts', 'Keyboard shortcuts')

# Browsing mode shortcuts
map('Quit',
    'quit --allow-fallback=shifted,ascii q quit',
    )
map('Scroll down',
    'scroll_down --allow-fallback=shifted,ascii j scroll_down',
    )
map('Scroll up',
    'scroll_up --allow-fallback=shifted,ascii k scroll_up',
    )
map('Start search',
    'search --allow-fallback=shifted,ascii s search',
    )
map('Accept theme',
    'accept --allow-fallback=shifted,ascii c accept',
    )

# Accepting mode shortcuts
map('Abort and return to browsing',
    'abort --allow-fallback=shifted,ascii a abort',
    )
map('Place theme file',
    'place_theme --allow-fallback=shifted,ascii p place_theme',
    )
map('Modify config file',
    'modify_conf --allow-fallback=shifted,ascii m modify_conf',
    )
map('Save as dark scheme',
    'dark_scheme --allow-fallback=shifted,ascii d dark_scheme',
    )
map('Save as light scheme',
    'light_scheme --allow-fallback=shifted,ascii l light_scheme',
    )
map('Save as no preference scheme',
    'no_preference --allow-fallback=shifted,ascii n no_preference',
    )

egr()  # }}}

help_text = (
    'Change the kitty theme. If no theme name is supplied, run interactively, otherwise'
    ' change the current theme to the specified theme name.'
)
usage = '[theme name to switch to]'
OPTIONS = '''
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
By default, this kitten will signal only the parent kitty instance it is
running in to reload its config, after making changes. Use this option
to instead either not reload the config at all or in all running
kitty instances.


--dump-theme
type=bool-set
default=false
When running non-interactively, dump the specified theme to STDOUT
instead of changing kitty.conf.


--config-file-name
default=kitty.conf
The name or path to the config file to edit. Relative paths are interpreted
with respect to the kitty config directory. By default the kitty config file,
kitty.conf is edited. This is most useful if you add :code:`include themes.conf`
to your kitty.conf and then have the kitten operate only on :file:`themes.conf`,
allowing :code:`kitty.conf` to remain unchanged.
'''.format

def main(args: list[str]) -> None:
    raise SystemExit('This must be run as kitten themes')

if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = 'Manage kitty color schemes easily'
    cd['args_completion'] = CompletionSpec.from_string('type:special group:complete_themes')
elif __name__ == '__conf__':
    sys.options_definition = definition  # type: ignore
