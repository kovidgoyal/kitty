#!/usr/bin/env python
# License: GPLv3 Copyright: 2025, Kovid Goyal <kovid at kovidgoyal.net>

import sys

from kitty.conf.types import Definition
from kitty.constants import appname
from kitty.simple_cli_definitions import CONFIG_HELP, CompletionSpec

definition = Definition(
    '!kittens.choose_files',
)

agr = definition.add_group
egr = definition.end_group
opt = definition.add_option
map = definition.add_map
mma = definition.add_mouse_map

agr('scan', 'Scanning the filesystem')
opt(
    '+exclude_directory',
    '^/proc$',
    add_to_default=True,
    long_text='''
Regular expression to exclude directories. Matching directories will not be recursed into, but
you can still or change into them to inspect their contents. Can be specified multiple times. Matches against the absolute path to the directory.
If the pattern starts with :code:`!`, the :code:`!` is removed and the remaining pattern is removed from the list of patterns. This
can be used to remove the default excluded directory patterns.
''',
)
opt('+exclude_directory', '^/dev$', add_to_default=True)
opt('+exclude_directory', '^/sys$', add_to_default=True)
opt('+exclude_directory', '/__pycache__$', add_to_default=True)

opt('max_depth', '4', option_type='positive_int', long_text='''
The maximum depth to which to scan the filesystem for matches. Using large values will slow things down considerably. The better
approach is to use a small value and first change to the directory of interest then actually select the file of interest.
''')
egr()

def main(args: list[str]) -> None:
    raise SystemExit('This must be run as kitten choose-files')


usage = '[directory to start choosing files in]'


OPTIONS = '''
--override -o
type=list
Override individual configuration options, can be specified multiple times.
Syntax: :italic:`name=value`.


--config
type=list
completion=type:file ext:conf group:"Config files" kwds:none,NONE
{config_help}


'''.format(config_help=CONFIG_HELP.format(conf_name='diff', appname=appname)).format


help_text = '''\
'''


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = 'Choose files, fast'
    cd['args_completion'] = CompletionSpec.from_string('type:directory')
elif __name__ == '__conf__':
    sys.options_definition = definition  # type: ignore
