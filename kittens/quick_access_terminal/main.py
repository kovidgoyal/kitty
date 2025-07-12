#!/usr/bin/env python
# License: GPLv3 Copyright: 2025, Kovid Goyal <kovid at kovidgoyal.net>

import re
import sys

from kitty.conf.types import Definition
from kitty.constants import appname
from kitty.simple_cli_definitions import CONFIG_HELP, get_option_maps, grab_keyboard_docs, panel_options_spec, parse_option_spec

help_text = 'A quick access terminal window that you can bring up instantly with a keypress or a command.'

definition = Definition(
    '!kittens.quick_access_terminal',
)

agr = definition.add_group
egr = definition.end_group
opt = definition.add_option

panel_opts = get_option_maps(parse_option_spec(panel_options_spec())[0])[0]

def migrate_help(x: str) -> str:
    def sub(m: re.Match[str]) -> str:
        return f':opt:`{m.group(1)}`'

    ans = re.sub(r':option:`--(\S+?)`', sub, x)
    return ans.replace('Use the special value :code:`list`', 'Run :code:`kitten panel --output-name list`')


def help_of(x: str) -> str:
    return migrate_help(panel_opts[x]['help'])


agr('qat', 'Window appearance')

opt('lines', '25', long_text=panel_opts['lines']['help'])

opt('columns', '80', long_text=panel_opts['columns']['help'])

opt('edge', 'top', choices=panel_opts['edge']['choices'], long_text=help_of('edge'))

opt('background_opacity', '0.85', option_type='unit_float', long_text='''
The background opacity of the window. This works the same as the kitty
option of the same name, it is present here as it has a different
default value for the quick access terminal.
''')

opt('hide_on_focus_loss', 'no', option_type='to_bool', long_text='''
Hide the window when it loses keyboard focus automatically. Using this option
will force :opt:`focus_policy` to :code:`on-demand`.
''')

opt('grab_keyboard', 'no', option_type='to_bool', long_text=grab_keyboard_docs)

opt('margin_left', '0', option_type='int', long_text=help_of('margin_left'))

opt('margin_right', '0', option_type='int', long_text=help_of('margin_right'))

opt('margin_top', '0', option_type='int', long_text=help_of('margin_top'))

opt('margin_bottom', '0', option_type='int', long_text=help_of('margin_bottom'))

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


opt('output_name', '', long_text=help_of('output_name'))

opt('start_as_hidden', 'no', option_type='to_bool',
    long_text='Whether to start the quick access terminal hidden. Useful if you are starting it as part of system startup.')

opt('focus_policy', 'exclusive', choices=panel_opts['focus_policy']['choices'], long_text=help_of('focus_policy'))



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


--debug-input
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
