#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import sys
from collections import deque
from typing import (
    Any, Callable, Dict, FrozenSet, Generator, Iterable, Iterator, List, Match,
    Optional, Sequence, Set, Tuple, Type, TypeVar, Union, cast
)

from .cli_stub import CLIOptions
from .conf.utils import resolve_config
from .config import KeyAction, MouseMap
from .constants import appname, defconf, is_macos, is_wayland, str_version
from .options_stub import Options as OptionsStub
from .types import MouseEvent, SingleKey
from .typing import BadLineType, SequenceMap, TypedDict


class OptionDict(TypedDict):
    dest: str
    aliases: FrozenSet[str]
    help: str
    choices: FrozenSet[str]
    type: str
    default: Optional[str]
    condition: bool


CONFIG_HELP = '''\
Specify a path to the configuration file(s) to use. All configuration files are
merged onto the builtin {conf_name}.conf, overriding the builtin values. This option
can be specified multiple times to read multiple configuration files in
sequence, which are merged. Use the special value NONE to not load a config
file.

If this option is not specified, config files are searched for in the order:
:file:`$XDG_CONFIG_HOME/{appname}/{conf_name}.conf`, :file:`~/.config/{appname}/{conf_name}.conf`, {macos_confpath}
:file:`$XDG_CONFIG_DIRS/{appname}/{conf_name}.conf`. The first one that exists is used as the
config file.

If the environment variable :env:`KITTY_CONFIG_DIRECTORY` is specified, that
directory is always used and the above searching does not happen.

If :file:`/etc/xdg/{appname}/{conf_name}.conf` exists it is merged before (i.e. with lower
priority) than any user config files. It can be used to specify system-wide
defaults for all users.
'''.replace(
    '{macos_confpath}',
    (':file:`~/Library/Preferences/{appname}/{conf_name}.conf`,' if is_macos else ''), 1
)


def surround(x: str, start: int, end: int) -> str:
    if sys.stdout.isatty():
        x = '\033[{}m{}\033[{}m'.format(start, x, end)
    return x


def emph(x: str) -> str:
    return surround(x, 91, 39)


def cyan(x: str) -> str:
    return surround(x, 96, 39)


def green(x: str) -> str:
    return surround(x, 32, 39)


def blue(x: str) -> str:
    return surround(x, 34, 39)


def yellow(x: str) -> str:
    return surround(x, 93, 39)


def italic(x: str) -> str:
    return surround(x, 3, 23)


def bold(x: str) -> str:
    return surround(x, 1, 22)


def title(x: str) -> str:
    return blue(bold(x))


def opt(text: str) -> str:
    return text


def option(x: str) -> str:
    idx = x.rfind('--')
    if idx < 0:
        idx = x.find('-')
    if idx > -1:
        x = x[idx:]
    parts = map(bold, x.split())
    return ' '.join(parts)


def code(x: str) -> str:
    return x


def kbd(x: str) -> str:
    return x


def env(x: str) -> str:
    return italic(x)


def file(x: str) -> str:
    return italic(x)


def doc(x: str) -> str:
    return f'https://sw.kovidgoyal.net/kitty/{x}.html'


OptionSpecSeq = List[Union[str, OptionDict]]


def parse_option_spec(spec: Optional[str] = None) -> Tuple[OptionSpecSeq, OptionSpecSeq]:
    if spec is None:
        spec = options_spec()
    NORMAL, METADATA, HELP = 'NORMAL', 'METADATA', 'HELP'
    state = NORMAL
    lines = spec.splitlines()
    prev_line = ''
    seq: OptionSpecSeq = []
    disabled: OptionSpecSeq = []
    mpat = re.compile('([a-z]+)=(.+)')
    current_cmd: OptionDict = {
        'dest': '', 'aliases': frozenset(), 'help': '', 'choices': frozenset(),
        'type': '', 'condition': False, 'default': None
    }
    empty_cmd = current_cmd

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
                current_cmd = {
                    'dest': parts[0][2:].replace('-', '_'), 'aliases': frozenset(parts), 'help': '',
                    'choices': frozenset(), 'type': '',
                    'default': None, 'condition': True
                }
                state = METADATA
                continue
            raise ValueError('Invalid option spec, unexpected line: {}'.format(line))
        elif state is METADATA:
            m = mpat.match(line)
            if m is None:
                state = HELP
                current_cmd['help'] += line
            else:
                k, v = m.group(1), m.group(2)
                if k == 'choices':
                    current_cmd['choices'] = frozenset(x.strip() for x in v.split(','))
                else:
                    if k == 'default':
                        current_cmd['default'] = v
                    elif k == 'type':
                        current_cmd['type'] = v
                    elif k == 'dest':
                        current_cmd['dest'] = v
                    elif k == 'condition':
                        current_cmd['condition'] = bool(eval(v))
        elif state is HELP:
            if line:
                spc = '' if current_cmd['help'].endswith('\n') else ' '
                current_cmd['help'] += spc + line
            else:
                if prev_line:
                    current_cmd['help'] += '\n\n'
                else:
                    state = NORMAL
                    (seq if current_cmd.get('condition', True) else disabled).append(current_cmd)
                    current_cmd = empty_cmd
        prev_line = line
    if current_cmd is not empty_cmd:
        (seq if current_cmd.get('condition', True) else disabled).append(current_cmd)

    return seq, disabled


def prettify(text: str) -> str:
    role_map = globals()

    def sub(m: Match) -> str:
        role, text = m.group(1, 2)
        return str(role_map[role](text))

    text = re.sub(r':([a-z]+):`([^`]+)`', sub, text)
    return text


def prettify_rst(text: str) -> str:
    return re.sub(r':([a-z]+):`([^`]+)`(=[^\s.]+)', r':\1:`\2`:code:`\3`', text)


def version(add_rev: bool = False) -> str:
    rev = ''
    from . import fast_data_types
    if add_rev and hasattr(fast_data_types, 'KITTY_VCS_REV'):
        rev = ' ({})'.format(fast_data_types.KITTY_VCS_REV[:10])
    return '{} {}{} created by {}'.format(italic(appname), green(str_version), rev, title('Kovid Goyal'))


def wrap(text: str, limit: int = 80) -> Iterator[str]:
    NORMAL, IN_FORMAT = 'NORMAL', 'IN_FORMAT'
    state = NORMAL
    last_space_at = None
    chars_in_line = 0
    breaks = []
    for i, ch in enumerate(text):
        if state is IN_FORMAT:
            if ch == 'm':
                state = NORMAL
            continue
        if ch == '\033':
            state = IN_FORMAT
            continue
        if ch == ' ':
            last_space_at = i
        if chars_in_line < limit:
            chars_in_line += 1
            continue
        if last_space_at is not None:
            breaks.append(last_space_at)
            last_space_at = None
            chars_in_line = i - breaks[-1]

    lines: List[str] = []
    for b in reversed(breaks):
        lines.append(text[b:].lstrip())
        text = text[:b]
    if text:
        lines.append(text)
    return reversed(lines)


def get_defaults_from_seq(seq: OptionSpecSeq) -> Dict[str, Any]:
    ans: Dict[str, Any] = {}
    for opt in seq:
        if not isinstance(opt, str):
            ans[opt['dest']] = defval_for_opt(opt)
    return ans


default_msg = ('''\
Run the :italic:`{appname}` terminal emulator. You can also specify the :italic:`program`
to run inside :italic:`{appname}` as normal arguments following the :italic:`options`.
For example: {appname} sh -c "echo hello, world. Press ENTER to quit; read"

For comprehensive documentation for kitty, please see: https://sw.kovidgoyal.net/kitty/''').format(appname=appname)


class PrintHelpForSeq:

    allow_pager = True

    def __call__(self, seq: OptionSpecSeq, usage: Optional[str], message: Optional[str], appname: str) -> None:
        from kitty.utils import screen_size_function
        screen_size = screen_size_function()
        try:
            linesz = min(screen_size().cols, 76)
        except OSError:
            linesz = 76
        blocks: List[str] = []
        a = blocks.append

        def wa(text: str, indent: int = 0, leading_indent: Optional[int] = None) -> None:
            if leading_indent is None:
                leading_indent = indent
            j = '\n' + (' ' * indent)
            lines: List[str] = []
            for ln in text.splitlines():
                if ln:
                    lines.extend(wrap(ln, limit=linesz - indent))
                else:
                    lines.append('')
            a((' ' * leading_indent) + j.join(lines))

        usage = '[program-to-run ...]' if usage is None else usage
        optstring = '[options] ' if seq else ''
        a('{}: {} {}{}'.format(title('Usage'), bold(yellow(appname)), optstring, usage))
        a('')
        message = message or default_msg
        wa(prettify(message))
        a('')
        if seq:
            a('{}:'.format(title('Options')))
        for opt in seq:
            if isinstance(opt, str):
                a('{}:'.format(title(opt)))
                continue
            help_text = opt['help']
            if help_text == '!':
                continue  # hidden option
            a('  ' + ', '.join(map(green, sorted(opt['aliases']))))
            if not opt.get('type', '').startswith('bool-'):
                blocks[-1] += '={}'.format(italic(opt['dest'].upper()))
            if opt.get('help'):
                defval = opt.get('default')
                t = help_text.replace('%default', str(defval))
                wa(prettify(t.strip()), indent=4)
                if defval is not None:
                    wa('Default: {}'.format(defval), indent=4)
                if opt.get('choices'):
                    wa('Choices: {}'.format(', '.join(opt['choices'])), indent=4)
                a('')

        text = '\n'.join(blocks) + '\n\n' + version()
        if print_help_for_seq.allow_pager and sys.stdout.isatty():
            import subprocess
            p = subprocess.Popen(['less', '-isRXF'], stdin=subprocess.PIPE)
            try:
                p.communicate(text.encode('utf-8'))
            except KeyboardInterrupt:
                raise SystemExit(1)
            raise SystemExit(p.wait())
        else:
            print(text)


print_help_for_seq = PrintHelpForSeq()


def seq_as_rst(
    seq: OptionSpecSeq,
    usage: Optional[str],
    message: Optional[str],
    appname: Optional[str],
    heading_char: str = '-'
) -> str:
    import textwrap
    blocks: List[str] = []
    a = blocks.append

    usage = '[program-to-run ...]' if usage is None else usage
    optstring = '[options] ' if seq else ''
    a('.. highlight:: sh')
    a('.. code-block:: sh')
    a('')
    a('  {} {}{}'.format(appname, optstring, usage))
    a('')
    message = message or default_msg
    a(prettify_rst(message))
    a('')
    if seq:
        a('Options')
        a(heading_char * 30)
    for opt in seq:
        if isinstance(opt, str):
            a(opt)
            a('~' * (len(opt) + 10))
            continue
        help_text = opt['help']
        if help_text == '!':
            continue  # hidden option
        defn = '.. option:: '
        if not opt.get('type', '').startswith('bool-'):
            val_name = ' <{}>'.format(opt['dest'].upper())
        else:
            val_name = ''
        a(defn + ', '.join(o + val_name for o in sorted(opt['aliases'])))
        if opt.get('help'):
            defval = opt.get('default')
            t = help_text.replace('%default', str(defval)).strip()
            a('')
            a(textwrap.indent(prettify_rst(t), ' ' * 4))
            if defval is not None:
                a(textwrap.indent('Default: :code:`{}`'.format(defval), ' ' * 4))
            if opt.get('choices'):
                a(textwrap.indent('Choices: :code:`{}`'.format(', '.join(sorted(opt['choices']))), ' ' * 4))
            a('')

    text = '\n'.join(blocks)
    return text


def as_type_stub(seq: OptionSpecSeq, disabled: OptionSpecSeq, class_name: str, extra_fields: Sequence[str] = ()) -> str:
    from itertools import chain
    ans: List[str] = ['class {}:'.format(class_name)]
    for opt in chain(seq, disabled):
        if isinstance(opt, str):
            continue
        name = opt['dest']
        otype = opt['type'] or 'str'
        if otype in ('str', 'int', 'float'):
            t = otype
            if t == 'str' and defval_for_opt(opt) is None:
                t = 'typing.Optional[str]'
        elif otype == 'list':
            t = 'typing.Sequence[str]'
        elif otype in ('choice', 'choices'):
            if opt['choices']:
                t = 'typing.Literal[{}]'.format(','.join(f'{x!r}' for x in opt['choices']))
            else:
                t = 'str'
        elif otype.startswith('bool-'):
            t = 'bool'
        else:
            raise ValueError('Unknown CLI option type: {}'.format(otype))
        ans.append('    {}: {}'.format(name, t))
    for x in extra_fields:
        ans.append('    {}'.format(x))
    return '\n'.join(ans) + '\n\n\n'


def defval_for_opt(opt: OptionDict) -> Any:
    dv: Any = opt.get('default')
    typ = opt.get('type', '')
    if typ.startswith('bool-'):
        if dv is None:
            dv = False if typ == 'bool-set' else True
        else:
            dv = dv.lower() in ('true', 'yes', 'y')
    elif typ == 'list':
        dv = []
    elif typ in ('int', 'float'):
        dv = (int if typ == 'int' else float)(dv or 0)
    return dv


class Options:

    def __init__(self, seq: OptionSpecSeq, usage: Optional[str], message: Optional[str], appname: Optional[str]):
        self.alias_map = {}
        self.seq = seq
        self.names_map: Dict[str, OptionDict] = {}
        self.values_map: Dict[str, Any] = {}
        self.usage, self.message, self.appname = usage, message, appname
        for opt in seq:
            if isinstance(opt, str):
                continue
            for alias in opt['aliases']:
                self.alias_map[alias] = opt
            name = opt['dest']
            self.names_map[name] = opt
            self.values_map[name] = defval_for_opt(opt)

    def opt_for_alias(self, alias: str) -> OptionDict:
        opt = self.alias_map.get(alias)
        if opt is None:
            raise SystemExit('Unknown option: {}'.format(emph(alias)))
        return opt

    def needs_arg(self, alias: str) -> bool:
        if alias in ('-h', '--help'):
            print_help_for_seq(self.seq, self.usage, self.message, self.appname or appname)
            raise SystemExit(0)
        opt = self.opt_for_alias(alias)
        if opt['dest'] == 'version':
            print(version())
            raise SystemExit(0)
        typ = opt.get('type', '')
        return not typ.startswith('bool-')

    def process_arg(self, alias: str, val: Any = None) -> None:
        opt = self.opt_for_alias(alias)
        typ = opt.get('type', '')
        name = opt['dest']
        nmap = {'float': float, 'int': int}
        if typ == 'bool-set':
            self.values_map[name] = True
        elif typ == 'bool-reset':
            self.values_map[name] = False
        elif typ == 'list':
            self.values_map.setdefault(name, [])
            self.values_map[name].append(val)
        elif typ == 'choices':
            choices = opt['choices']
            if val not in choices:
                raise SystemExit('{} is not a valid value for the {} option. Valid values are: {}'.format(
                    val, emph(alias), ', '.join(choices)))
            self.values_map[name] = val
        elif typ in nmap:
            f = nmap[typ]
            try:
                self.values_map[name] = f(val)
            except Exception:
                raise SystemExit('{} is not a valid value for the {} option, a number is required.'.format(
                    val, emph(alias)))
        else:
            self.values_map[name] = val


def parse_cmdline(oc: Options, disabled: OptionSpecSeq, ans: Any, args: Optional[List[str]] = None) -> List[str]:
    NORMAL, EXPECTING_ARG = 'NORMAL', 'EXPECTING_ARG'
    state = NORMAL
    dargs = deque(sys.argv[1:] if args is None else args)
    leftover_args: List[str] = []
    current_option = None

    while dargs:
        arg = dargs.popleft()
        if state is NORMAL:
            if arg.startswith('-'):
                if arg == '--':
                    leftover_args = list(dargs)
                    break
                parts = arg.split('=', 1)
                needs_arg = oc.needs_arg(parts[0])
                if not needs_arg:
                    if len(parts) != 1:
                        raise SystemExit('The {} option does not accept arguments'.format(emph(parts[0])))
                    oc.process_arg(parts[0])
                    continue
                if len(parts) == 1:
                    current_option = parts[0]
                    state = EXPECTING_ARG
                    continue
                oc.process_arg(parts[0], parts[1])
            else:
                leftover_args = [arg] + list(dargs)
                break
        elif current_option is not None:
            oc.process_arg(current_option, arg)
            current_option, state = None, NORMAL
    if state is EXPECTING_ARG:
        raise SystemExit('An argument is required for the option: {}'.format(emph(arg)))

    for key, val in oc.values_map.items():
        setattr(ans, key, val)
    for opt in disabled:
        if not isinstance(opt, str):
            setattr(ans, opt['dest'], defval_for_opt(opt))
    return leftover_args


WATCHER_DEFINITION = '''
--watcher -w
type=list
Path to a python file. Appropriately named functions in this file will be called
for various events, such as when the window is resized, focused or closed. See the section
on watchers in the launch command documentation :doc:`launch`. Relative paths are
resolved relative to the kitty config directory.'''


def options_spec() -> str:
    if not hasattr(options_spec, 'ans'):
        OPTIONS = '''
--class
dest=cls
default={appname}
condition=not is_macos
Set the class part of the :italic:`WM_CLASS` window property. On Wayland, it sets the app id.


--name
condition=not is_macos
Set the name part of the :italic:`WM_CLASS` property (defaults to using the value from :option:`{appname} --class`)


--title -T
Set the window title. This will override any title set by the program running inside kitty. So
only use this if you are running a program that does not set titles. If combined
with :option:`{appname} --session` the title will be used for all windows created by the
session, that do not set their own titles.


--config -c
type=list
{config_help}


--override -o
type=list
Override individual configuration options, can be specified multiple times.
Syntax: :italic:`name=value`. For example: :option:`kitty -o` font_size=20


--directory --working-directory -d
default=.
Change to the specified directory when launching


--detach
type=bool-set
condition=not is_macos
Detach from the controlling terminal, if any


--session
Path to a file containing the startup :italic:`session` (tabs, windows, layout, programs).
Use - to read from STDIN. See the README file for details and an example.


{watcher}
Note that this watcher will be added only to all initially created windows, not new windows
created after startup.


--hold
type=bool-set
Remain open after child process exits. Note that this only affects the first
window. You can quit by either using the close window shortcut or pressing any key.


--single-instance -1
type=bool-set
If specified only a single instance of :italic:`{appname}` will run. New invocations will
instead create a new top-level window in the existing :italic:`{appname}` instance. This
allows :italic:`{appname}` to share a single sprite cache on the GPU and also reduces
startup time. You can also have separate groups of :italic:`{appname}` instances by using the
:option:`kitty --instance-group` option


--instance-group
Used in combination with the :option:`kitty --single-instance` option. All :italic:`{appname}` invocations
with the same :option:`kitty --instance-group` will result in new windows being created
in the first :italic:`{appname}` instance within that group


--wait-for-single-instance-window-close
type=bool-set
Normally, when using :option:`--single-instance`, :italic:`{appname}` will open a new window in an existing
instance and quit immediately. With this option, it will not quit till the newly opened
window is closed. Note that if no previous instance is found, then :italic:`{appname}` will wait anyway,
regardless of this option.


--listen-on
Tell kitty to listen on the specified address for control
messages. For example, :option:`{appname} --listen-on`=unix:/tmp/mykitty or
:option:`{appname} --listen-on`=tcp:localhost:12345. On Linux systems, you can
also use abstract UNIX sockets, not associated with a file, like this:
:option:`{appname} --listen-on`=unix:@mykitty. Environment variables
in the setting are expanded and relative paths are resolved with
respect to the temporary directory. To control kitty, you can send
it commands with :italic:`kitty @` using the :option:`kitty @ --to` option to
specify this address. This option will be ignored, unless you set
:opt:`allow_remote_control` to yes in :file:`kitty.conf`. Note that if you run
:italic:`kitty @` within a kitty window, there is no need to specify the :italic:`--to`
option as it is read automatically from the environment. For UNIX sockets, this
can also be specified in :file:`kitty.conf`.


--start-as
type=choices
default=normal
choices=normal,fullscreen,maximized,minimized
Control how the initial kitty window is created.


# Debugging options

--version -v
type=bool-set
The current {appname} version


--dump-commands
type=bool-set
Output commands received from child process to stdout


--replay-commands
Replay previously dumped commands. Specify the path to a dump file previously created by --dump-commands. You
can open a new kitty window to replay the commands with::

    kitty sh -c "kitty --replay-commands /path/to/dump/file; read"


--dump-bytes
Path to file in which to store the raw bytes received from the child process


--debug-rendering --debug-gl
type=bool-set
Debug rendering commands. This will cause all OpenGL calls to check for errors
instead of ignoring them. Also prints out miscellaneous debug information.
Useful when debugging rendering problems


--debug-input --debug-keyboard
dest=debug_keyboard
type=bool-set
This option will cause kitty to print out key and mouse events as they are received


--debug-font-fallback
type=bool-set
Print out information about the selection of fallback fonts for characters not present in the main font.


--debug-config
type=bool-set
Print out information about the system and kitty configuration. Note that this only
reads the standard kitty.conf not any extra configuration or alternative conf files
that were specified on the command line.


--execute -e
type=bool-set
!
'''
        setattr(options_spec, 'ans', OPTIONS.format(
            appname=appname, config_help=CONFIG_HELP.format(appname=appname, conf_name=appname),
            watcher=WATCHER_DEFINITION
        ))
    ans: str = getattr(options_spec, 'ans')
    return ans


def options_for_completion() -> OptionSpecSeq:
    raw = '--help -h\ntype=bool-set\nShow help for {appname} command line options\n\n{raw}'.format(
            appname=appname, raw=options_spec())
    return parse_option_spec(raw)[0]


def option_spec_as_rst(
    ospec: Callable[[], str] = options_spec,
    usage: Optional[str] = None, message: Optional[str] = None, appname: Optional[str] = None,
    heading_char: str = '-'
) -> str:
    options = parse_option_spec(ospec())
    seq, disabled = options
    oc = Options(seq, usage, message, appname)
    return seq_as_rst(oc.seq, oc.usage, oc.message, oc.appname, heading_char=heading_char)


T = TypeVar('T')


def parse_args(
    args: Optional[List[str]] = None,
    ospec: Callable[[], str] = options_spec,
    usage: Optional[str] = None,
    message: Optional[str] = None,
    appname: Optional[str] = None,
    result_class: Optional[Type[T]] = None,
) -> Tuple[T, List[str]]:
    options = parse_option_spec(ospec())
    seq, disabled = options
    oc = Options(seq, usage, message, appname)
    if result_class is not None:
        ans = result_class()
    else:
        ans = cast(T, CLIOptions())
    return ans, parse_cmdline(oc, disabled, ans, args=args)


SYSTEM_CONF = '/etc/xdg/kitty/kitty.conf'
ShortcutMap = Dict[Tuple[SingleKey, ...], KeyAction]


def mod_to_names(mods: int) -> Generator[str, None, None]:
    from .fast_data_types import (
        GLFW_MOD_ALT, GLFW_MOD_CAPS_LOCK, GLFW_MOD_CONTROL, GLFW_MOD_HYPER,
        GLFW_MOD_META, GLFW_MOD_NUM_LOCK, GLFW_MOD_SHIFT, GLFW_MOD_SUPER
    )
    modmap = {'shift': GLFW_MOD_SHIFT, 'alt': GLFW_MOD_ALT, 'ctrl': GLFW_MOD_CONTROL, ('cmd' if is_macos else 'super'): GLFW_MOD_SUPER,
              'hyper': GLFW_MOD_HYPER, 'meta': GLFW_MOD_META, 'num_lock': GLFW_MOD_NUM_LOCK, 'caps_lock': GLFW_MOD_CAPS_LOCK}
    for name, val in modmap.items():
        if mods & val:
            yield name


def print_shortcut(key_sequence: Iterable[SingleKey], action: KeyAction) -> None:
    from .fast_data_types import glfw_get_key_name
    keys = []
    for key_spec in key_sequence:
        names = []
        mods, is_native, key = key_spec
        names = list(mod_to_names(mods))
        if key:
            kname = glfw_get_key_name(0, key) if is_native else glfw_get_key_name(key, 0)
            names.append(kname or f'{key}')
        keys.append('+'.join(names))

    print('\t', ' > '.join(keys), action)


def print_shortcut_changes(defns: ShortcutMap, text: str, changes: Set[Tuple[SingleKey, ...]]) -> None:
    if changes:
        print(title(text))

        for k in sorted(changes):
            print_shortcut(k, defns[k])


def compare_keymaps(final: ShortcutMap, initial: ShortcutMap) -> None:
    added = set(final) - set(initial)
    removed = set(initial) - set(final)
    changed = {k for k in set(final) & set(initial) if final[k] != initial[k]}
    print_shortcut_changes(final, 'Added shortcuts:', added)
    print_shortcut_changes(initial, 'Removed shortcuts:', removed)
    print_shortcut_changes(final, 'Changed shortcuts:', changed)


def flatten_sequence_map(m: SequenceMap) -> ShortcutMap:
    ans: Dict[Tuple[SingleKey, ...], KeyAction] = {}
    for key_spec, rest_map in m.items():
        for r, action in rest_map.items():
            ans[(key_spec,) + (r)] = action
    return ans


def compare_mousemaps(final: MouseMap, initial: MouseMap) -> None:
    added = set(final) - set(initial)
    removed = set(initial) - set(final)
    changed = {k for k in set(final) & set(initial) if final[k] != initial[k]}

    def print_mouse_action(trigger: MouseEvent, action: KeyAction) -> None:
        names = list(mod_to_names(trigger.mods)) + [f'b{trigger.button+1}']
        when = {-1: 'repeat', 1: 'press', 2: 'doublepress', 3: 'triplepress'}.get(trigger.repeat_count, trigger.repeat_count)
        grabbed = 'grabbed' if trigger.grabbed else 'ungrabbed'
        print('\t', '+'.join(names), when, grabbed, action)

    def print_changes(defns: MouseMap, changes: Set[MouseEvent], text: str) -> None:
        if changes:
            print(title(text))
            for k in sorted(changes):
                print_mouse_action(k, defns[k])

    print_changes(final, added, 'Added mouse actions:')
    print_changes(initial, removed, 'Removed mouse actions:')
    print_changes(final, changed, 'Changed mouse actions:')


def compare_opts(opts: OptionsStub) -> None:
    from .config import defaults, load_config
    print('\nConfig options different from defaults:')
    default_opts = load_config()
    ignored = ('key_definitions', 'keymap', 'sequence_map', 'mousemap', 'mouse_mappings')
    changed_opts = [
        f for f in sorted(defaults._fields)  # type: ignore
        if f not in ignored and getattr(opts, f) != getattr(defaults, f)
    ]
    field_len = max(map(len, changed_opts)) if changed_opts else 20
    fmt = '{{:{:d}s}}'.format(field_len)
    for f in changed_opts:
        print(title(fmt.format(f)), getattr(opts, f))

    compare_mousemaps(opts.mousemap, default_opts.mousemap)
    final_, initial_ = opts.keymap, default_opts.keymap
    final: ShortcutMap = {(k,): v for k, v in final_.items()}
    initial: ShortcutMap = {(k,): v for k, v in initial_.items()}
    final_s, initial_s = map(flatten_sequence_map, (opts.sequence_map, default_opts.sequence_map))
    final.update(final_s)
    initial.update(initial_s)
    compare_keymaps(final, initial)


def create_opts(args: CLIOptions, debug_config: bool = False, accumulate_bad_lines: Optional[List[BadLineType]] = None) -> OptionsStub:
    from .config import load_config
    config = tuple(resolve_config(SYSTEM_CONF, defconf, args.config))
    if debug_config:
        print(version(add_rev=True))
        print(' '.join(os.uname()))
        if is_macos:
            import subprocess
            print(' '.join(subprocess.check_output(['sw_vers']).decode('utf-8').splitlines()).strip())
        if os.path.exists('/etc/issue'):
            with open('/etc/issue', encoding='utf-8', errors='replace') as f:
                print(f.read().strip())
        if os.path.exists('/etc/lsb-release'):
            with open('/etc/lsb-release', encoding='utf-8', errors='replace') as f:
                print(f.read().strip())
        config = tuple(x for x in config if os.path.exists(x))
        if config:
            print(green('Loaded config files:'), ', '.join(config))
    overrides = (a.replace('=', ' ', 1) for a in args.override or ())
    opts = load_config(*config, overrides=overrides, accumulate_bad_lines=accumulate_bad_lines)
    if debug_config:
        if not is_macos:
            print('Running under:', green('Wayland' if is_wayland(opts) else 'X11'))
        compare_opts(opts)
    return opts


def create_default_opts() -> OptionsStub:
    from .config import load_config
    config = tuple(resolve_config(SYSTEM_CONF, defconf, ()))
    opts = load_config(*config)
    return opts
