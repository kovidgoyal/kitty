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

agr('scanning', 'Filesystem scanning')  # {{{

opt('show_hidden', 'last', choices=('last', 'yes', 'y', 'true', 'no', 'n', 'false'), long_text='''
Whether to show hidden files. The default value of :code:`last` means remember the last
used value. This setting can be toggled withing the program.''')

opt('sort_by_last_modified', 'last', choices=('last', 'yes', 'y', 'true', 'no', 'n', 'false'), long_text='''
Whether to sort the list of entries by last modified, instead of name. Note that sorting only applies
before any query is entered. Once a query is entered entries are sorted by their matching score.
The default value of :code:`last` means remember the last
used value. This setting can be toggled withing the program.''')

opt('respect_ignores', 'last', choices=('last', 'yes', 'y', 'true', 'no', 'n', 'false'), long_text='''
Whether to respect .gitignore and .ignore files and the :opt:`ignore` setting.
The default value of :code:`last` means remember the last used value.
This setting can be toggled withing the program.''')

opt('+ignore', '', add_to_default=False, long_text='''
An ignore pattern to ignore matched files. Uses the same sytax as :code:`.gitignore` files (see :code:`man gitignore`).
Anchored patterns match with respect to whatever directory is currently being displayed.
Can be specified multiple times to use multiple patterns. Note that every pattern
has to be checked against every file, so use sparingly.
''')
egr()  # }}}

agr('appearance', 'Appearance')  # {{{

opt('show_preview', 'last', choices=('last', 'yes', 'y', 'true', 'no', 'n', 'false'), long_text='''
Whether to show a preview of the current file/directory. The default value of :code:`last` means remember the last
used value. This setting can be toggled withing the program.''')

opt('pygments_style', 'default', long_text='''
The pygments color scheme to use for syntax highlighting of file previews. See :link:`pygments
builtin styles <https://pygments.org/styles/>` for a list of schemes.
This sets the colors used for light color schemes, use :opt:`dark_pygments_style` to change the
colors for dark color schemes.
''')

opt('dark_pygments_style', 'github-dark', long_text='''
The pygments color scheme to use for syntax highlighting with dark colors. See :link:`pygments
builtin styles <https://pygments.org/styles/>` for a list of schemes.
This sets the colors used for dark color schemes, use :opt:`pygments_style` to change the
colors for light color schemes.''')

opt('syntax_aliases', 'pyj:py pyi:py recipe:py', ctype='strdict_ _:', option_type='syntax_aliases',
    long_text='''
File extension aliases for syntax highlight. For example, to syntax highlight
:file:`file.xyz` as :file:`file.abc` use a setting of :code:`xyz:abc`.
Multiple aliases must be separated by spaces.
''')

egr()  # }}}

agr('shortcuts', 'Keyboard shortcuts')  # {{{
map('Quit', 'quit esc quit')
map('Quit', 'quit ctrl+c quit')

map('Accept current result', 'accept enter accept')
map('Select current result', 'select shift+enter select', long_text='''
When selecting multiple files, this will add the current file to the list of selected files.
You can also toggle the selected status of a file by holding down the :kbd:`Ctrl` key and clicking on
it. Similarly, the :kbd:`Alt` key can be held to click and extend the range of selected files.
''')
map('Type file name', 'typename ctrl+enter typename', long_text='''
Type a file name/path rather than filtering the list of existing files.
Useful when specifying a file or directory name for saving that does not yet exist.
When choosing existing directories, will accept the directory whoose
contents are being currently displayed as the choice.
Does not work when selecting files to open rather than to save.
''')

map('Next result', 'next_result down next 1')
map('Previous result', 'prev_result up next -1')
map('Left result', 'left_result left next left')
map('Right result', 'right_result right next right')
map('First result on screen', 'first_result_on_screen home next first_on_screen')
map('Last result on screen', 'last_result_on_screen end next last_on_screen')
map('First result', 'first_result_on_screen ctrl+home next first')
map('Last result', 'last_result_on_screen ctrl+end next last')

map('Change to currently selected dir', 'cd_current tab cd .')
map('Change to parent directory', 'cd_parent shift+tab cd ..')
map('Change to root directory', 'cd_root ctrl+/ cd /')
map('Change to home directory', 'cd_home ctrl+~ cd ~')
map('Change to home directory', 'cd_home ctrl+` cd ~')
map('Change to home directory', 'cd_home ctrl+shift+` cd ~')
map('Change to temp directory', 'cd_tmp ctrl+t cd /tmp')

map('Next filter', 'next_filter ctrl+f 1')
map('Previous filter', 'prev_filter alt+f -1')

map('Toggle showing dotfiles', 'toggle_dotfiles alt+h toggle dotfiles')
map('Toggle showing ignored files', 'toggle_ignorefiles alt+i toggle ignorefiles')
map('Toggle sorting by dates', 'toggle_sort_by_dates alt+d toggle sort_by_dates')
map('Toggle showing preview', 'toggle_preview alt+p toggle preview')

egr()  # }}}

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


--display-title
type=bool-set
Show the window title at the top, useful when this kitten is used in an
OS window without a title bar.


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
Select one or more files, quickly, using fuzzy finding, by typing just a few characters from
the file name. Browse matching files, using the arrow keys to navigate matches and press :kbd:`Enter`
to select. The :kbd:`Tab` key can be used to change to a sub-folder. See the :doc:`online docs </kittens/choose-files>`
for full details.
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
