#!/usr/bin/env python
# License: GPLv3 Copyright: 2025, Kovid Goyal <kovid at kovidgoyal.net>

import sys

from kitty.conf.types import Definition
from kitty.constants import appname
from kitty.simple_cli_definitions import CONFIG_HELP

help_text = 'A quick access terminal window that you can bring up instantly with a keypress or a command.'

definition = Definition(
    '!kittens.quick_access_terminal',
)

agr = definition.add_group
egr = definition.end_group
opt = definition.add_option

agr('qat', 'Window appearance')

opt('lines', '25',
    long_text='''
The number of lines shown in the window, when the window is along the top or bottom edges of the screen.
If it has the suffix :code:`px` then it sets the height of the window in pixels instead of lines.
''',)

opt('columns', '80',
    long_text='''
The number of columns shown in the window, when the window is along the left or right edges of the screen.
If it has the suffix :code:`px` then it sets the width of the window in pixels instead of columns.
''',)

opt('edge', 'top', choices=('top', 'bottom', 'left', 'right'),
    long_text='Which edge of the screen to place the window along')

opt('background_opacity', '0.85', option_type='unit_float', long_text='''
The background opacity of the window. This works the same as the kitty
option of the same name, it is present here as it has a different
default value for the quick access terminal.
''')

opt('hide_on_focus_loss', 'no', option_type='to_bool', long_text='''
Hide the window when it loses keyboard focus automatically. Using this option
will force :opt:`focus_policy` to :code:`on-demand`.
''')

opt('margin_left', '0', option_type='int',
    long_text='Set the left margin for the window, in pixels. Has no effect for windows on the right edge of the screen.')

opt('margin_right', '0', option_type='int',
    long_text='Set the right margin for the window, in pixels. Has no effect for windows on the left edge of the screen.')

opt('margin_top', '0', option_type='int',
    long_text='Set the top margin for the window, in pixels. Has no effect for windows on the bottom edge of the screen.')

opt('margin_bottom', '0', option_type='int',
    long_text='Set the bottom margin for the window, in pixels. Has no effect for windows on the top edge of the screen.')

opt('+kitty_conf', '',
    long_text='Path to config file to use for kitty when drawing the window. Can be specified multiple times. By default, the'
    ' normal kitty.conf is used. Relative paths are resolved with respect to the kitty config directory.'
)

opt('+kitty_override', '', long_text='Override individual kitty configuration options, can be specified multiple times.'
    ' Syntax: :italic:`name=value`. For example: :code:`font_size=20`.'
)

opt('app_id', f'{appname}-quick-access',
    long_text='On Wayland set the :italic:`namespace` of the layer shell surface.'
    ' On X11 set the WM_CLASS assigned to the quick access window. (Linux only)')


opt('output_name', '', long_text='''
The panel can only be displayed on a single monitor (output) at a time. This allows
you to specify which output is used, by name. If not specified the compositor will choose an
output automatically, typically the last output the user interacted with or the primary monitor.
You can get a list of available outputs by running: :code:`kitten panel --output-name list`.
''')

opt('start_as_hidden', 'no', option_type='to_bool',
    long_text='Whether to start the quick access terminal hidden. Useful if you are starting it as part of system startup.')

opt('focus_policy', 'exclusive', choices=('exclusive', 'on-demand'), long_text='''
How to manage window focus. A value of :code:`exclusive` means prevent other windows from getting focus.
However, whether this works is entirely dependent on the compositor/desktop environment.
It does not have any effect on macOS and KDE, for example. Note that on sway using :code:`on-demand` means
the compositor will not focus the window when it appears until you click on it, which is why the default is set
to :code:`exclusive`.
''')



def options_spec() -> str:
    return f'''
--config -c
type=list
completion=type:file ext:conf group:"Config files" kwds:none,NONE
{CONFIG_HELP.format(conf_name='quick-access-terminal', appname=appname)}


--override -o
type=list
Override individual configuration options, can be specified multiple times.
Syntax: :italic:`name=value`. For example: :italic:`-o lines=12`


--detach
type=bool-set
Detach from the controlling terminal, if any, running in an independent child process,
the parent process exits immediately.


--detached-log
Path to a log file to store STDOUT/STDERR when using :option:`--detach`


--instance-group
default=quick-access
The unique name of this quick access terminal Use a different name if you want multiple such terminals.


--debug-rendering
type=bool-set
For debugging interactions with the compositor/window manager.
'''

def main(args: list[str]) -> None:
    raise SystemExit('This kitten should be run as: kitten quick-access-terminal')


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd: dict = sys.cli_docs  # type: ignore
    cd['usage'] = '[cmdline-to-run ...]'
    cd['options'] = options_spec
    cd['help_text'] = help_text
    cd['short_desc'] = help_text
elif __name__ == '__conf__':
    sys.options_definition = definition  # type: ignore
