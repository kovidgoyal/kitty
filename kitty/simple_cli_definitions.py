#!/usr/bin/env python
# License: GPLv3 Copyright: 2025, Kovid Goyal <kovid at kovidgoyal.net>

# This module must be runnable by a vanilla python interpreter
# as it is used to generate C code when building kitty

import re
import sys
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Iterator, TypedDict

try:
    from kitty.constants import appname, is_macos
except ImportError:
    is_macos = 'darwin' in sys.platform.lower()
try:
    from kitty.utils import shlex_split as ksplit
    def shlex_split(text: str) -> Iterator[str]:
        yield from ksplit(text)
except ImportError:
    from shlex import split as psplit

    def shlex_split(text: str) -> Iterator[str]:
        yield from psplit(text)


def serialize_as_go_string(x: str) -> str:
    return x.replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"')


class CompletionType(Enum):
    file = auto()
    directory = auto()
    keyword = auto()
    special = auto()
    none = auto()


class CompletionRelativeTo(Enum):
    cwd = auto()
    config_dir = auto()


@dataclass
class CompletionSpec:

    type: CompletionType = CompletionType.none
    kwds: tuple[str,...] = ()
    extensions: tuple[str,...] = ()
    mime_patterns: tuple[str,...] = ()
    group: str = ''
    relative_to: CompletionRelativeTo = CompletionRelativeTo.cwd

    @staticmethod
    def from_string(raw: str) -> 'CompletionSpec':
        self = CompletionSpec()
        for x in shlex_split(raw):
            ck, vv = x.split(':', 1)
            if ck == 'type':
                self.type = getattr(CompletionType, vv)
            elif ck == 'kwds':
                self.kwds += tuple(vv.split(','))
            elif ck == 'ext':
                self.extensions += tuple(vv.split(','))
            elif ck == 'group':
                self.group = vv
            elif ck == 'mime':
                self.mime_patterns += tuple(vv.split(','))
            elif ck == 'relative':
                if vv == 'conf':
                    self.relative_to = CompletionRelativeTo.config_dir
                else:
                    raise ValueError(f'Unknown completion relative to value: {vv}')
            else:
                raise KeyError(f'Unknown completion property: {ck}')
        return self

    def as_go_code(self, go_name: str, sep: str = ': ') -> Iterator[str]:
        completers = []
        if self.kwds:
            kwds = (f'"{serialize_as_go_string(x)}"' for x in self.kwds)
            g = (self.group if self.type is CompletionType.keyword else '') or "Keywords"
            completers.append(f'cli.NamesCompleter("{serialize_as_go_string(g)}", ' + ', '.join(kwds) + ')')
        relative_to = 'CONFIG' if self.relative_to is CompletionRelativeTo.config_dir else 'CWD'
        if self.type is CompletionType.file:
            g = serialize_as_go_string(self.group or 'Files')
            added = False
            if self.extensions:
                added = True
                pats = (f'"*.{ext}"' for ext in self.extensions)
                completers.append(f'cli.FnmatchCompleter("{g}", cli.{relative_to}, ' + ', '.join(pats) + ')')
            if self.mime_patterns:
                added = True
                completers.append(f'cli.MimepatCompleter("{g}", cli.{relative_to}, ' + ', '.join(f'"{p}"' for p in self.mime_patterns) + ')')
            if not added:
                completers.append(f'cli.FnmatchCompleter("{g}", cli.{relative_to}, "*")')
        if self.type is CompletionType.directory:
            g = serialize_as_go_string(self.group or 'Directories')
            completers.append(f'cli.DirectoryCompleter("{g}", cli.{relative_to})')
        if self.type is CompletionType.special:
            completers.append(self.group)
        if len(completers) > 1:
            yield f'{go_name}{sep}cli.ChainCompleters(' + ', '.join(completers) + ')'
        elif completers:
            yield f'{go_name}{sep}{completers[0]}'


class OptionDict(TypedDict):
    dest: str
    name: str
    aliases: tuple[str, ...]
    help: str
    choices: tuple[str, ...]
    type: str
    default: str | None
    condition: bool
    completion: CompletionSpec


OptionSpecSeq = list[str | OptionDict]


def parse_option_spec(spec: str | None = None) -> tuple[OptionSpecSeq, OptionSpecSeq]:
    if spec is None:
        spec = kitty_options_spec()
    NORMAL, METADATA, HELP = 'NORMAL', 'METADATA', 'HELP'
    state = NORMAL
    lines = spec.splitlines()
    prev_line = ''
    prev_indent = 0
    seq: OptionSpecSeq = []
    disabled: OptionSpecSeq = []
    mpat = re.compile('([a-z]+)=(.+)')
    current_cmd: OptionDict = {
        'dest': '', 'aliases': (), 'help': '', 'choices': (),
        'type': '', 'condition': False, 'default': None, 'completion': CompletionSpec(), 'name': ''
    }
    empty_cmd = current_cmd

    def indent_of_line(x: str) -> int:
        return len(x) - len(x.lstrip())

    for line in lines:
        line = line.rstrip()
        if state is NORMAL:
            if not line:
                continue
            if line.startswith('# '):
                seq.append(line[2:])
                continue
            if line.startswith('--'):
                parts = line.split(' ')
                defdest = parts[0][2:].replace('-', '_')
                current_cmd = {
                    'dest': defdest, 'aliases': tuple(parts), 'help': '',
                    'choices': tuple(), 'type': '', 'name': defdest,
                    'default': None, 'condition': True, 'completion': CompletionSpec(),
                }
                state = METADATA
                continue
            raise ValueError(f'Invalid option spec, unexpected line: {line}')
        elif state is METADATA:
            m = mpat.match(line)
            if m is None:
                state = HELP
                current_cmd['help'] += line
            else:
                k, v = m.group(1), m.group(2)
                if k == 'choices':
                    vals = tuple(x.strip() for x in v.split(','))
                    if not current_cmd['type']:
                        current_cmd['type'] = 'choices'
                    if current_cmd['type'] != 'choices':
                        raise ValueError(f'Cannot specify choices for an option of type: {current_cmd["type"]}')
                    current_cmd['choices'] = tuple(vals)
                    if current_cmd['default'] is None:
                        current_cmd['default'] = vals[0]
                else:
                    if k == 'default':
                        current_cmd['default'] = v
                    elif k == 'type':
                        if v == 'choice':
                            v = 'choices'
                        current_cmd['type'] = v
                    elif k == 'dest':
                        current_cmd['dest'] = v
                    elif k == 'condition':
                        current_cmd['condition'] = bool(eval(v))
                    elif k == 'completion':
                        current_cmd['completion'] = CompletionSpec.from_string(v)
        elif state is HELP:
            if line:
                current_indent = indent_of_line(line)
                if current_indent > 1:
                    if prev_indent == 0:
                        current_cmd['help'] += '\n'
                    else:
                        line = line.strip()
                prev_indent = current_indent
                spc = '' if current_cmd['help'].endswith('\n') else ' '
                current_cmd['help'] += spc + line
            else:
                prev_indent = 0
                if prev_line:
                    current_cmd['help'] += '\n' if current_cmd['help'].endswith('::') else '\n\n'
                else:
                    state = NORMAL
                    (seq if current_cmd.get('condition', True) else disabled).append(current_cmd)
                    current_cmd = empty_cmd
        prev_line = line
    if current_cmd is not empty_cmd:
        (seq if current_cmd.get('condition', True) else disabled).append(current_cmd)

    return seq, disabled


def defval_for_opt(opt: OptionDict) -> Any:
    dv: Any = opt.get('default')
    typ = opt.get('type', '')
    if typ.startswith('bool-'):
        if dv is None:
            dv = False if typ == 'bool-set' else True
        else:
            dv = dv.lower() in ('true', 'yes', 'y')
    elif typ == 'list':
        dv = list(shlex_split(dv)) if dv else []
    elif typ in ('int', 'float'):
        dv = (int if typ == 'int' else float)(dv or 0)
    return dv


def get_option_maps(seq: OptionSpecSeq) -> tuple[dict[str, OptionDict], dict[str, OptionDict], dict[str, Any]]:
    names_map: dict[str, OptionDict] = {}
    alias_map: dict[str, OptionDict] = {}
    values_map: dict[str, Any] = {}
    for opt in seq:
        if isinstance(opt, str):
            continue
        for alias in opt['aliases']:
            alias_map[alias] = opt
        name = opt['dest']
        names_map[name] = opt
        values_map[name] = defval_for_opt(opt)
    return names_map, alias_map, values_map


def c_str(x: str) -> str:
    x = x.replace('\\', r'\\')
    return f'"{x}"'


def add_list_values(*values: str) -> Iterator[str]:
    yield f'\tflag.defval.listval.items = alloc_for_cli(spec, {len(values)} * sizeof(flag.defval.listval.items[0]));'
    yield '\tif (!flag.defval.listval.items) OOM;'
    yield f'\tflag.defval.listval.count = {len(values)};'
    yield f'\tflag.defval.listval.capacity = {len(values)};'
    for n, value in enumerate(values):
        yield f'\tflag.defval.listval.items[{n}] = {c_str(value)};'


def generate_c_for_opt(name: str, defval: Any, opt: OptionDict) -> Iterator[str]:
    yield f'\tflag = (FlagSpec){{.dest={c_str(name)},}};'
    match opt['type']:
        case 'bool-set' | 'bool-reset':
            yield '\tflag.defval.type = CLI_VALUE_BOOL;'
            yield f'\tflag.defval.boolval = {"true" if defval else "false"};'
        case 'int':
            yield '\tflag.defval.type = CLI_VALUE_INT;'
            yield f'\tflag.defval.intval = {defval};'
        case 'float':
            yield '\tflag.defval.type = CLI_VALUE_FLOAT;'
            yield f'\tflag.defval.floatval = {defval};'
        case 'list':
            yield '\tflag.defval.type = CLI_VALUE_LIST;'
            if defval:
                yield from add_list_values(*defval)
        case 'choices':
            yield '\tflag.defval.type = CLI_VALUE_CHOICE;'
            yield f'\tflag.defval.strval = {c_str(defval)};'
            yield from add_list_values(*opt['choices'])
        case _:
            yield '\tflag.defval.type = CLI_VALUE_STRING;'
            if defval is not None:
                yield f'\tflag.defval.strval = {c_str(defval)};'


def generate_c_parser_for(funcname: str, spec: str) -> Iterator[str]:
    seq, disabled = parse_option_spec(spec)
    names_map, _, defaults_map = get_option_maps(seq)
    if 'help' not in names_map:
        names_map['help'] = {'type': 'bool-set', 'aliases': ('--help', '-h')}  # type: ignore
        defaults_map['help'] = False
    if 'version' not in names_map:
        names_map['version'] = {'type': 'bool-set', 'aliases': ('--version', '-v')}  # type: ignore
        defaults_map['version'] = False

    yield f'static void\nparse_cli_for_{funcname}(CLISpec *spec, int argc, char **argv) {{'  # }}
    yield '\tFlagSpec flag;'
    for name, opt in names_map.items():
        for alias in opt['aliases']:
            yield f'\tif (vt_is_end(vt_insert(&spec->alias_map, {c_str(alias)}, {c_str(name)}))) OOM;'
        yield from generate_c_for_opt(name, defaults_map[name], opt)
        yield '\tif (vt_is_end(vt_insert(&spec->flag_map, flag.dest, flag))) OOM;'
    for d in disabled:
        if not isinstance(d, str):
            yield from generate_c_for_opt(d['dest'], defval_for_opt(d), d)
            yield '\tif (vt_is_end(vt_insert(&spec->disabled_map, flag.dest, flag))) OOM;'

    yield '\tparse_cli_loop(spec, true, argc, argv);'
    yield '}'


def generate_c_parsers() -> Iterator[str]:
    yield '#pragma once'
    yield '// generated by simple_cli_definitions.py do NOT edit!'
    yield '#include "cli-parser.h"'
    yield from generate_c_parser_for('kitty', kitty_options_spec())
    yield ''
    yield ''
    yield from generate_c_parser_for('panel_kitten', build_panel_cli_spec({}))
    yield ''


# kitty CLI spec {{{
grab_keyboard_docs = """\
Grab the keyboard. This means global shortcuts defined in the OS will be passed to kitty instead. Useful if
you want to create an OS modal window. How well this
works depends on the OS/window manager/desktop environment. On Wayland it works only if the compositor implements
the :link:`inhibit-keyboard-shortcuts protocol <https://wayland.app/protocols/keyboard-shortcuts-inhibit-unstable-v1>`.
On macOS Apple doesn't allow applications to grab the keyboard without special permissions, so it doesn't work.
"""

listen_on_defn = f'''\
--listen-on
completion=type:special group:complete_kitty_listen_on
Listen on the specified socket address for control messages. For example,
:option:`{appname} --listen-on`=unix:/tmp/mykitty or :option:`{appname}
--listen-on`=tcp:localhost:12345. On Linux systems, you can also use abstract
UNIX sockets, not associated with a file, like this: :option:`{appname}
--listen-on`=unix:@mykitty. Environment variables are expanded and relative
paths are resolved with respect to the temporary directory. To control kitty,
you can send commands to it with :italic:`kitten @` using the
:option:`kitten @ --to` option to specify this address. Note that if you run
:italic:`kitten @` within a kitty window, there is no need to specify the
:option:`kitten @ --to` option as it will automatically read from the
environment. Note that this will be ignored unless :opt:`allow_remote_control`
is set to either: :code:`yes`, :code:`socket` or :code:`socket-only`. This can
also be specified in :file:`kitty.conf`.
'''

wait_for_single_instance_defn = f'''\
--wait-for-single-instance-window-close
type=bool-set
Normally, when using :option:`{appname} --single-instance`, :italic:`{appname}`
will open a new window in an existing instance and quit immediately. With this
option, it will not quit till the newly opened window is closed. Note that if no
previous instance is found, then :italic:`{appname}` will wait anyway,
regardless of this option.
'''

CONFIG_HELP = '''\
Specify a path to the configuration file(s) to use. All configuration files are
merged onto the builtin :file:`{conf_name}.conf`, overriding the builtin values.
This option can be specified multiple times to read multiple configuration files
in sequence, which are merged. Use the special value :code:`NONE` to not load
any config file.

If this option is not specified, config files are searched for in the order:
:file:`$XDG_CONFIG_HOME/{appname}/{conf_name}.conf`,
:file:`~/.config/{appname}/{conf_name}.conf`,{macos_confpath}
:file:`$XDG_CONFIG_DIRS/{appname}/{conf_name}.conf`. The first one that exists
is used as the config file.

If the environment variable :envvar:`KITTY_CONFIG_DIRECTORY` is specified, that
directory is always used and the above searching does not happen.

If :file:`/etc/xdg/{appname}/{conf_name}.conf` exists, it is merged before (i.e.
with lower priority) than any user config files. It can be used to specify
system-wide defaults for all users. You can use either :code:`-` or
:file:`/dev/stdin` to read the config from STDIN.
'''.replace(
    '{macos_confpath}',
    (' :file:`~/Library/Preferences/{appname}/{conf_name}.conf`,' if is_macos else ''), 1
)


def kitty_options_spec() -> str:
    if not hasattr(kitty_options_spec, 'ans'):
        OPTIONS = '''
--class --app-id
dest=cls
default={appname}
condition=not is_macos
On Wayland set the :italic:`application id`. On X11 set the class part of the :italic:`WM_CLASS` window property.


--name --os-window-tag
condition=not is_macos
On Wayland, set the :italic:`window tag`, when specified.
On X11, set the name part of the :italic:`WM_CLASS` property, when unset, defaults to using the
value from :option:`{appname} --class`.


--title -T
Set the OS window title. This will override any title set by the program running
inside kitty, permanently fixing the OS window's title. So only use this if you
are running a program that does not set titles.


--config -c
type=list
completion=type:file ext:conf group:"Config files" kwds:none,NONE
{config_help}


--override -o
type=list
completion=type:special group:complete_kitty_override
Override individual configuration options, can be specified multiple times.
Syntax: :italic:`name=value`. For example: :option:`{appname} -o` font_size=20


--directory --working-directory -d
default=.
completion=type:directory
Change to the specified directory when launching.


--detach
type=bool-set
Detach from the controlling terminal, if any. On macOS
use :code:`open -a kitty.app -n` instead.


--detached-log
Path to a log file to store STDOUT/STDERR when using :option:`--detach`


--session
completion=type:file ext:session relative:conf group:"Session files"
Path to a file containing the startup :italic:`session` (tabs, windows, layout,
programs). Use - to read from STDIN. See :ref:`sessions` for details and
an example. Environment variables in the file name are expanded,
relative paths are resolved relative to the kitty configuration directory.
The special value :code:`none` means no session will be used, even if
the :opt:`startup_session` option has been specified in kitty.conf.
Note that using this option means the command line arguments to kitty specifying
a program to run are ignored.


--hold
type=bool-set
Remain open, at a shell prompt, after child process exits. Note that this only
affects the first window. You can quit by either using the close window
shortcut or running the exit command.


--single-instance -1
type=bool-set
If specified only a single instance of :italic:`{appname}` will run. New
invocations will instead create a new top-level window in the existing
:italic:`{appname}` instance. This allows :italic:`{appname}` to share a single
sprite cache on the GPU and also reduces startup time. You can also have
separate groups of :italic:`{appname}` instances by using the :option:`{appname}
--instance-group` option.


--instance-group
Used in combination with the :option:`{appname} --single-instance` option. All
:italic:`{appname}` invocations with the same :option:`{appname}
--instance-group` will result in new windows being created in the first
:italic:`{appname}` instance within that group.


{wait_for_single_instance_defn}


{listen_on_defn} To start in headless mode,
without an actual window, use :option:`{appname} --start-as`=hidden.


--start-as
type=choices
default=normal
choices=normal,fullscreen,maximized,minimized,hidden
Control how the initial kitty window is created.


--position
The position, for example 10x20, on screen at which to place the first kitty OS Window.
This may or may not work depending on the policies of the desktop
environment/window manager. It never works on Wayland.
See also :opt:`remember_window_position` to have kitty automatically try
to restore the previous window position.


--grab-keyboard
type=bool-set
{grab_keyboard_docs}


# Debugging options

--version -v
type=bool-set
The current {appname} version.


--dump-commands
type=bool-set
Output commands received from child process to STDOUT.


--replay-commands
Replay previously dumped commands. Specify the path to a dump file previously
created by :option:`{appname} --dump-commands`. You
can open a new kitty window to replay the commands with::

    {appname} sh -c "{appname} --replay-commands /path/to/dump/file; read"


--dump-bytes
Path to file in which to store the raw bytes received from the child process.


--debug-rendering --debug-gl
type=bool-set
Debug rendering commands. This will cause all OpenGL calls to check for errors
instead of ignoring them. Also prints out miscellaneous debug information.
Useful when debugging rendering problems.


--debug-input --debug-keyboard
dest=debug_keyboard
type=bool-set
Print out key and mouse events as they are received.


--debug-font-fallback
type=bool-set
Print out information about the selection of fallback fonts for characters not
present in the main font.


--watcher
completion=type:file ext:py relative:conf group:"Watcher files"
This option is deprecated in favor of the :opt:`watcher` option in
:file:`{conf_name}.conf` and should not be used.


--execute -e
type=bool-set
!
'''
        setattr(kitty_options_spec, 'ans', OPTIONS.format(
            appname=appname, conf_name=appname, listen_on_defn=listen_on_defn,
            grab_keyboard_docs=grab_keyboard_docs, wait_for_single_instance_defn=wait_for_single_instance_defn,
            config_help=CONFIG_HELP.format(appname=appname, conf_name=appname
        )))
    ans: str = getattr(kitty_options_spec, 'ans')
    return ans
# }}}


# panel CLI spec {{{
panel_defaults = {
    'lines': '1', 'columns': '1',
    'margin_left': '0', 'margin_top': '0', 'margin_right': '0', 'margin_bottom': '0',
    'edge': 'top', 'layer': 'bottom', 'override': '', 'cls': f'{appname}-panel',
    'focus_policy': 'not-allowed', 'exclusive_zone': '-1', 'override_exclusive_zone': 'no',
    'single_instance': 'no', 'instance_group': '', 'toggle_visibility': 'no',
    'start_as_hidden': 'no', 'detach': 'no', 'detached_log': '',
}

def build_panel_cli_spec(defaults: dict[str, str]) -> str:
    d = panel_defaults.copy()
    d.update(defaults)
    return r'''
--lines
default={lines}
The number of lines shown in the panel. Ignored for background, centered, and vertical panels.
If it has the suffix :code:`px` then it sets the height of the panel in pixels instead of lines.


--columns
default={columns}
The number of columns shown in the panel. Ignored for background, centered, and horizontal panels.
If it has the suffix :code:`px` then it sets the width of the panel in pixels instead of columns.


--margin-top
type=int
default={margin_top}
Set the top margin for the panel, in pixels. Has no effect for bottom edge panels.
Only works on macOS and Wayland compositors that supports the wlr layer shell protocol.


--margin-left
type=int
default={margin_left}
Set the left margin for the panel, in pixels. Has no effect for right edge panels.
Only works on macOS and Wayland compositors that supports the wlr layer shell protocol.


--margin-bottom
type=int
default={margin_bottom}
Set the bottom margin for the panel, in pixels. Has no effect for top edge panels.
Only works on macOS and Wayland compositors that supports the wlr layer shell protocol.


--margin-right
type=int
default={margin_right}
Set the right margin for the panel, in pixels. Has no effect for left edge panels.
Only works on macOS and Wayland compositors that supports the wlr layer shell protocol.


--edge
choices=top,bottom,left,right,background,center,center-sized,none
default={edge}
Which edge of the screen to place the panel on. Note that some window managers
(such as i3) do not support placing docked windows on the left and right edges.
The value :code:`background` means make the panel the "desktop wallpaper".
Note that when using sway if you set a background in your sway config it will
cover the background drawn using this kitten.
Additionally, there are three more values: :code:`center`, :code:`center-sized` and :code:`none`.
The value :code:`center` anchors the panel to all sides and covers the entire
display (on macOS the part of the display not covered by titlebar and dock).
The panel can be shrunk and placed using the margin parameters.
The value :code:`none` anchors the panel to the top left corner and should be
placed using the margin parameters. Its size is set by :option:`--lines`
and :option:`--columns`. The value :code:`center-sized` is just like :code:`none` except
that the panel is centered instead of in the top left corner and the margins have no effect.


--layer
choices=background,bottom,top,overlay
default={layer}
On a Wayland compositor that supports the wlr layer shell protocol, specifies the layer
on which the panel should be drawn. This parameter is ignored and set to
:code:`background` if :option:`--edge` is set to :code:`background`. On macOS, maps
these to appropriate NSWindow *levels*.


--config -c
type=list
Path to config file to use for kitty when drawing the panel.


--override -o
type=list
default={override}
Override individual kitty configuration options, can be specified multiple times.
Syntax: :italic:`name=value`. For example: :option:`kitty +kitten panel -o` font_size=20


--output-name
The panel can only be displayed on a single monitor (output) at a time. This allows
you to specify which output is used, by name. If not specified the compositor will choose an
output automatically, typically the last output the user interacted with or the primary monitor.
Use the special value :code:`list` to get a list of available outputs. Use :code:`listjson` for
a json encoded output.


--class --app-id
dest=cls
default={cls}
condition=not is_macos
On Wayland set the :italic:`namespace` of the layer shell surface. On X11 set the class part of the :italic:`WM_CLASS` window property.


--name --os-window-tag
condition=not is_macos
On X11 sets the name part of the :italic:`WM_CLASS` property on X11,
when unspecified uses the value from :option:`{appname} --class` on X11.


--focus-policy
choices=not-allowed,exclusive,on-demand
default={focus_policy}
On a Wayland compositor that supports the wlr layer shell protocol, specify the focus policy for keyboard
interactivity with the panel. Please refer to the wlr layer shell protocol documentation for more details.
Note that different Wayland compositors behave very differently with :code:`exclusive`, your mileage may vary.
On macOS, :code:`exclusive` and :code:`on-demand` are currently the same.


--hide-on-focus-loss
type=bool-set
Automatically hide the panel window when it loses focus. Using this option will force :option:`--focus-policy`
to :code:`on-demand`. Note that on Wayland, depending on the compositor, this can result in the window never
becoming visible.


--grab-keyboard
type=bool-set
{grab_keyboard_docs}


--exclusive-zone
type=int
default={exclusive_zone}
On a Wayland compositor that supports the wlr layer shell protocol, request a given exclusive zone for the panel.
Please refer to the wlr layer shell documentation for more details on the meaning of exclusive and its value.
If :option:`--edge` is set to anything other than :code:`center` or :code:`none`, this flag will not have any
effect unless the flag :option:`--override-exclusive-zone` is also set.
If :option:`--edge` is set to :code:`background`, this option has no effect.
Ignored on X11 and macOS.


--override-exclusive-zone
type=bool-set
default={override_exclusive_zone}
On a Wayland compositor that supports the wlr layer shell protocol, override the default exclusive zone.
This has effect only if :option:`--edge` is set to :code:`top`, :code:`left`, :code:`bottom` or :code:`right`.
Ignored on X11 and macOS.


--single-instance -1
type=bool-set
default={single_instance}
If specified only a single instance of the panel will run. New
invocations will instead create a new top-level window in the existing
panel instance.


--instance-group
default={instance_group}
Used in combination with the :option:`--single-instance` option. All
panel invocations with the same :option:`--instance-group` will result
in new panels being created in the first panel instance within that group.


{wait_for_single_instance_defn}


{listen_on_defn}


--toggle-visibility
type=bool-set
default={toggle_visibility}
When set and using :option:`--single-instance` will toggle the visibility of the
existing panel rather than creating a new one.


--start-as-hidden
type=bool-set
default={start_as_hidden}
Start in hidden mode, useful with :option:`--toggle-visibility`.


--detach
type=bool-set
default={detach}
Detach from the controlling terminal, if any, running in an independent child process,
the parent process exits immediately.


--detached-log
default={detached_log}
Path to a log file to store STDOUT/STDERR when using :option:`--detach`


--debug-rendering
type=bool-set
For internal debugging use.


--debug-input
type=bool-set
For internal debugging use.
'''.format(
    appname=appname, listen_on_defn=listen_on_defn, grab_keyboard_docs=grab_keyboard_docs,
    wait_for_single_instance_defn=wait_for_single_instance_defn, **d)


def panel_options_spec() -> str:
    return build_panel_cli_spec(panel_defaults)

# }}}
