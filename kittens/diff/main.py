#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from functools import partial

from kitty.conf.types import Definition
from kitty.constants import appname
from kitty.simple_cli_definitions import CONFIG_HELP, CompletionSpec


def main(args: list[str]) -> None:
    raise SystemExit('Must be run as kitten diff')

definition = Definition(
    '!kittens.diff',
)

agr = definition.add_group
egr = definition.end_group
opt = definition.add_option
map = definition.add_map
mma = definition.add_mouse_map

# diff {{{
agr('diff', 'Diffing')

opt('syntax_aliases', 'pyj:py pyi:py recipe:py', ctype='strdict_ _:', option_type='syntax_aliases',
    long_text='''
File extension aliases for syntax highlight. For example, to syntax highlight
:file:`file.xyz` as :file:`file.abc` use a setting of :code:`xyz:abc`.
Multiple aliases must be separated by spaces.
'''
    )

opt('num_context_lines', '3', option_type='positive_int',
    long_text='The number of lines of context to show around each change.'
    )

opt('diff_cmd', 'auto',
    long_text='''
The diff command to use. Must contain the placeholder :code:`_CONTEXT_` which
will be replaced by the number of lines of context. A few special values are allowed:
:code:`auto` will automatically pick an available diff implementation. :code:`builtin`
will use the anchored diff algorithm from the Go standard library. :code:`git` will
use the git command to do the diffing. :code:`diff` will use the diff command to
do the diffing.
'''
    )

opt('replace_tab_by', '\\x20\\x20\\x20\\x20', option_type='python_string',
    long_text='The string to replace tabs with. Default is to use four spaces.'
    )

opt('+ignore_name', '', ctype='string',
    add_to_default=False,
    long_text='''
A glob pattern that is matched against only the filename of files and directories. Matching
files and directories are ignored when scanning the filesystem to look for files to diff.
Can be specified multiple times to use multiple patterns. For example::

    ignore_name .git
    ignore_name *~
    ignore_name *.pyc
''',
    )

egr()  # }}}

# colors {{{
agr('colors', 'Colors')

opt('color_scheme', 'auto', choices=('auto', 'light', 'dark'), long_text='''
Whether to use the light or dark colors. The default of :code:`auto` means
to follow the parent terminal color scheme. Note that the actual colors used
for dark schemes are set by the :code:`dark_*` settings below and the non-prefixed
settings are used for light colors.
''')

opt('pygments_style', 'default', long_text='''
The pygments color scheme to use for syntax highlighting. See :link:`pygments
builtin styles <https://pygments.org/styles/>` for a list of schemes. Note that
this **does not** change the colors used for diffing,
only the colors used for syntax highlighting. To change the general colors use the settings below.
This sets the colors used for light color schemes, use :opt:`dark_pygments_style` to change the
colors for dark color schemes.
'''
    )

opt('dark_pygments_style', 'github-dark', long_text='''
The pygments color scheme to use for syntax highlighting with dark colors. See :link:`pygments
builtin styles <https://pygments.org/styles/>` for a list of schemes. Note that
this **does not** change the colors used for diffing,
only the colors used for syntax highlighting. To change the general colors use the settings below.
This sets the colors used for dark color schemes, use :opt:`pygments_style` to change the
colors for light color schemes.''')

opt('foreground', 'black', option_type='to_color', long_text='Basic colors')
opt('dark_foreground', '#f8f8f2', option_type='to_color')

dark_bg = '#212830'
opt('background', 'white', option_type='to_color',)
opt('dark_background', dark_bg, option_type='to_color',)

opt('title_fg', 'black', option_type='to_color', long_text='Title colors')
opt('dark_title_fg', 'white', option_type='to_color')

opt('title_bg', 'white', option_type='to_color',)
opt('dark_title_bg', dark_bg, option_type='to_color',)

opt('margin_bg', '#fafbfc', option_type='to_color', long_text='Margin colors')
opt('dark_margin_bg', dark_bg, option_type='to_color')

opt('margin_fg', '#aaaaaa', option_type='to_color')
opt('dark_margin_fg', '#aaaaaa', option_type='to_color')

opt('removed_bg', '#ffeef0', option_type='to_color', long_text='Removed text backgrounds')
opt('dark_removed_bg', '#352c33', option_type='to_color')

opt('highlight_removed_bg', '#fdb8c0', option_type='to_color')
opt('dark_highlight_removed_bg', '#5c3539', option_type='to_color')

opt('removed_margin_bg', '#ffdce0', option_type='to_color')
opt('dark_removed_margin_bg', '#5c3539', option_type='to_color')

opt('added_bg', '#e6ffed', option_type='to_color', long_text='Added text backgrounds')
opt('dark_added_bg', '#263834', option_type='to_color')

opt('highlight_added_bg', '#acf2bd', option_type='to_color')
opt('dark_highlight_added_bg', '#31503d', option_type='to_color')

opt('added_margin_bg', '#cdffd8', option_type='to_color')
opt('dark_added_margin_bg', '#31503d', option_type='to_color')

opt('filler_bg', '#fafbfc', option_type='to_color', long_text='Filler (empty) line background')
opt('dark_filler_bg', '#262c36', option_type='to_color')

opt('margin_filler_bg', 'none', option_type='to_color_or_none', long_text='Filler (empty) line background in margins, defaults to the filler background')
opt('dark_margin_filler_bg', 'none', option_type='to_color_or_none')


opt('hunk_margin_bg', '#dbedff', option_type='to_color', long_text='Hunk header colors')
opt('dark_hunk_margin_bg', '#0c2d6b', option_type='to_color')

opt('hunk_bg', '#f1f8ff', option_type='to_color')
opt('dark_hunk_bg', '#253142', option_type='to_color')

opt('search_bg', '#444', option_type='to_color', long_text='Highlighting')
opt('dark_search_bg', '#2c599c', option_type='to_color')

opt('search_fg', 'white', option_type='to_color')
opt('dark_search_fg', 'white', option_type='to_color')

opt('select_bg', '#b4d5fe', option_type='to_color')
opt('dark_select_bg', '#2c599c', option_type='to_color')

opt('select_fg', 'black', option_type='to_color_or_none')
opt('dark_select_fg', 'white', option_type='to_color_or_none')
egr()  # }}}

# shortcuts {{{
agr('shortcuts', 'Keyboard shortcuts')

map('Quit',
    'quit q quit',
    )
map('Quit',
    'quit esc quit',
    )

map('Scroll down',
    'scroll_down j scroll_by 1',
    )
map('Scroll down',
    'scroll_down down scroll_by 1',
    )

map('Scroll up',
    'scroll_up k scroll_by -1',
    )
map('Scroll up',
    'scroll_up up scroll_by -1',
    )

map('Scroll to top',
    'scroll_top home scroll_to start',
    )

map('Scroll to bottom',
    'scroll_bottom end scroll_to end',
    )

map('Scroll to next page',
    'scroll_page_down page_down scroll_to next-page',
    )
map('Scroll to next page',
    'scroll_page_down space scroll_to next-page',
    )
map('Scroll to next page',
    'scroll_page_down ctrl+f scroll_to next-page',
    )

map('Scroll to previous page',
    'scroll_page_up page_up scroll_to prev-page',
    )
map('Scroll to previous page',
    'scroll_page_up ctrl+b scroll_to prev-page',
    )

map('Scroll down half page',
    'scroll_half_page_down ctrl+d scroll_to next-half-page',
    )
map('Scroll up half page',
    'scroll_half_page_up ctrl+u scroll_to prev-half-page',
    )

map('Scroll to next change',
    'next_change n scroll_to next-change',
    )

map('Scroll to previous change',
    'prev_change p scroll_to prev-change',
    )

map('Scroll to next file',
    'next_file shift+j scroll_to next-file',
    )

map('Scroll to previous file',
    'prev_file shift+k scroll_to prev-file',
    )

map('Show all context',
    'all_context a change_context all',
    )

map('Show default context',
    'default_context = change_context default',
    )

map('Increase context',
    'increase_context + change_context 5',
    )

map('Decrease context',
    'decrease_context - change_context -5',
    )

map('Search forward',
    'search_forward / start_search regex forward',
    )

map('Search backward',
    'search_backward ? start_search regex backward',
    )

map('Scroll to next search match',
    'next_match . scroll_to next-match',
    )
map('Scroll to next search match',
    'next_match > scroll_to next-match',
    )

map('Scroll to previous search match',
    'prev_match , scroll_to prev-match',
    )
map('Scroll to previous search match',
    'prev_match < scroll_to prev-match',
    )

map('Search forward (no regex)',
    'search_forward_simple f start_search substring forward',
    )

map('Search backward (no regex)',
    'search_backward_simple b start_search substring backward',
    )

map('Copy selection to clipboard', 'copy_to_clipboard y copy_to_clipboard')
map('Copy selection to clipboard or exit if no selection is present', 'copy_to_clipboard_or_exit ctrl+c copy_to_clipboard_or_exit')

egr()  # }}}

OPTIONS = partial('''\
--context
type=int
default=-1
Number of lines of context to show between changes. Negative values use the
number set in :file:`diff.conf`.


--config
type=list
completion=type:file ext:conf group:"Config files" kwds:none,NONE
{config_help}


--override -o
type=list
Override individual configuration options, can be specified multiple times.
Syntax: :italic:`name=value`. For example: :italic:`-o background=gray`

'''.format, config_help=CONFIG_HELP.format(conf_name='diff', appname=appname))
help_text = 'Show a side-by-side diff of the specified files/directories. You can also use :italic:`ssh:hostname:remote-file-path` to diff remote files.'
usage = 'file_or_directory_left file_or_directory_right'



if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = 'Pretty, side-by-side diffing of files and images'
    cd['args_completion'] = CompletionSpec.from_string('type:file mime:text/* mime:image/* group:"Text and image files"')
elif __name__ == '__conf__':
    sys.options_definition = definition  # type: ignore
