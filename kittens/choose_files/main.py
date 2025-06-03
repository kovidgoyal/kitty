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
opt('+modify_score', r'(^|/)\.[^/]+(/|$) *= 0.1', add_to_default=True, long_text='''
Modify the score of items matching the specified regular expression (matches against the absolute path).
Can be used to make certain files and directories less or more prominent in the results.
Can be specified multiple times. The default includes rules to reduce the score of hidden items and
items in some well known cache folder names. Only applies when some actual search expression is provided.
The syntax is :code:`regular-expression operator value`. Supported operators are: :code:`*=, +=, -=, /=`.
''')
opt('+modify_score', '(^|/)__pycache__(/|$) *= 0.1', add_to_default=True)
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


--mode
type=choices
choices=file,files,save-file,dir,save-dir,dirs,dir-for-files
default=file
The type of object(s) to select


--suggested-save-file-name
A suggested name when picking a save file.


--suggested-save-file-path
Path to an existing file to use as the save file.
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
