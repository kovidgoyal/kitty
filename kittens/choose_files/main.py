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

def main(args: list[str]) -> None:
    raise SystemExit('This must be run as kitten choose-files')


usage = '[directory to start choosing files in]'


OPTIONS = '''
--mode
type=choices
choices=file,files,save-file,dir,save-dir,dirs,save-files
default=file
The type of object(s) to select


--file-filter
type=list
A list of filters to restrict the displayed files. Can be either mimetypes, or glob style patterns. Can be specified multiple times.
The syntax is :code:`type:expression:Descriptive Name`.
For example: :code:`mime:image/png:Images` and :code:`mime:image/gif:Images` and :code:`glob:*.[tT][xX][Tt]:Text files`.
Note that glob patterns are case-sensitive. The mimetype specification is treated as a glob expressions as well, so you can,
for example, use :code:`mime:text/*` to match all text files. The first filter in the list will be applied by default. Use a filter
such as :code:`glob:*:All` to match all files. Note that filtering only appies to files, not directories.


--suggested-save-file-name
A suggested name when picking a save file.


--suggested-save-file-path
Path to an existing file to use as the save file.


--title
Window title to use for this chooser


--override -o
type=list
Override individual configuration options, can be specified multiple times.
Syntax: :italic:`name=value`.


--config
type=list
completion=type:file ext:conf group:"Config files" kwds:none,NONE
{config_help}


--write-output-to
Path to a file to which the output is written in addition to STDOUT.


--output-format
choices=text,json
default=text
The format in which to write the output.


--write-pid-to
Path to a file to which to write the process ID (PID) of this process to.
'''.format(config_help=CONFIG_HELP.format(conf_name='choose-files', appname=appname)).format


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
