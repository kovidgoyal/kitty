#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import subprocess
import sys
from collections import deque

from .config import defaults, load_config
from .constants import appname, defconf, is_macos, is_wayland, str_version
from .layout import all_layouts

OPTIONS = '''
--class
dest=cls
default={appname}
condition=not is_macos
Set the class part of the |_ WM_CLASS| window property


--name
condition=not is_macos
Set the name part of the |_ WM_CLASS| property (defaults to using the value from |_ --class|)


--title
Set the window title. This will override any title set by the program running inside kitty. So
only use this if you are running a program that does not set titles.


--config
type=list
Specify a path to the configuration file(s) to use. All configuration files are
merged onto the builtin kitty.conf, overriding the builtin values. This option
can be specified multiple times to read multiple configuration files in
sequence, which are merged. Use the special value NONE to not load a config
file.

If this option is not specified, config files are searched for in the order:
"$XDG_CONFIG_HOME/kitty/kitty.conf", "~/.config/kitty/kitty.conf", {macos_confpath}
"$XDG_CONFIG_DIRS/kitty/kitty.conf". The first one that exists is used as the
config file.

If the environment variable "KITTY_CONFIG_DIRECTORY" is specified, that
directory is always used and the above searching does not happen.

If "/etc/xdg/kitty/kitty.conf" exists it is merged before (i.e. with lower
priority) than any user config files. It can be used to specify system-wide
defaults for all users.


--override -o
type=list
Override individual configuration options, can be specified multiple times.
Syntax: |_ name=value|. For example: |_ -o font_size=20|


--cmd -c
Run python code in the kitty context


--directory -d
default=.
Change to the specified directory when launching


--detach
type=bool-set
condition=not is_macos
Detach from the controlling terminal, if any


--window-layout
type=choices
choices={window_layout_choices}
The window layout to use on startup.


--session
Path to a file containing the startup |_ session| (tabs, windows, layout, programs).
See the README file for details and an example.


--single-instance -1
type=bool-set
If specified only a single instance of |_ {appname}| will run. New invocations will
instead create a new top-level window in the existing |_ {appname}| instance. This
allows |_ {appname}| to share a single sprite cache on the GPU and also reduces
startup time. You can also have separate groups of |_ {appname}| instances by using the
|_ --instance-group| option


--instance-group
Used in combination with the |_ --single-instance| option. All |_ {appname}| invocations
with the same |_ --instance-group| will result in new windows being created
in the first |_ {appname}| instance within that group


--listen-on
Tell kitty to listen on the specified address for control
messages. For example, |_ --listen-on=unix:/tmp/mykitty| or
|_ --listen-on=tcp:localhost:12345|. On Linux systems, you can also use abstract
UNIX sockets, not associated with a file, like this: |_ --listen-on=unix:@mykitty|.
To control kitty, you can send it commands with |_ kitty @| using the |_ --to| option
to specify this address. Note that this option will be ignored, unless you set
|_ allow_remote_control| to yes in |_ kitty.conf|


# Debugging options

--version -v
The current {appname} version


--dump-commands
type=bool-set
Output commands received from child process to stdout


--replay-commands
type=bool-set
Replay previously dumped commands


--dump-bytes
Path to file in which to store the raw bytes received from the child process


--debug-gl
type=bool-set
Debug OpenGL commands. This will cause all OpenGL calls to check for errors instead of ignoring them. Useful when debugging rendering problems


--debug-font-fallback
type=bool-set
Print out information about the selection of fallback fonts for characters not present in the main font.


--debug-config
type=bool-set
Print out information about the system and kitty configuration.
'''


def surround(x, start, end):
    if sys.stdout.isatty():
        x = '\033[{}m{}\033[{}m'.format(start, x, end)
    return x


def emph(x):
    return surround(x, 91, 39)


def cyan(x):
    return surround(x, 96, 39)


def green(x):
    return surround(x, 32, 39)


def blue(x):
    return surround(x, 34, 39)


def yellow(x):
    return surround(x, 93, 39)


def italic(x):
    return surround(x, 3, 23)


def bold(x):
    return surround(x, 1, 22)


def title(x):
    return blue(bold(x))


def parse_option_spec(spec=OPTIONS):
    NORMAL, METADATA, HELP = 'NORMAL', 'METADATA', 'HELP'
    state = NORMAL
    lines = spec.splitlines()
    prev_line = ''
    seq = []
    disabled = []
    mpat = re.compile('([a-z]+)=(.+)')
    current_cmd = None

    for line in lines:
        line = line.strip()
        if state is NORMAL:
            if not line:
                continue
            if line.startswith('# '):
                seq.append(line[2:])
                continue
            if line.startswith('--'):
                parts = line.split(' ')
                current_cmd = {'dest': parts[0][2:].replace('-', '_'), 'aliases': frozenset(parts), 'help': ''}
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
                if k == 'condition':
                    v = eval(v)
                current_cmd[k] = v
                if k == 'choices':
                    current_cmd['choices'] = {x.strip() for x in current_cmd['choices'].split(',')}
        elif state is HELP:
            if line:
                current_cmd['help'] += ' ' + line.lstrip()
            else:
                if prev_line:
                    current_cmd['help'] += '\n\n\t'
                else:
                    state = NORMAL
                    (seq if current_cmd.get('condition', True) else disabled).append(current_cmd)
                    current_cmd = None
        prev_line = line
    if current_cmd is not None:
        (seq if current_cmd.get('condition', True) else disabled).append(current_cmd)

    return seq, disabled


def prettify(text):

    def sub(m):
        t = m.group(2)
        for ch in m.group(1):
            t = {'C': cyan, '_': italic, '*': bold, 'G': green, 'T': title}[ch](t)
        return t

    text = re.sub(r'[|]([a-zA-Z_*]+?) (.+?)[|]', sub, text)
    return text


def version(add_rev=False):
    rev = ''
    from . import fast_data_types
    if add_rev and hasattr(fast_data_types, 'KITTY_VCS_REV'):
        rev = ' ({})'.format(fast_data_types.KITTY_VCS_REV[:10])
    return '{} {}{} created by {}'.format(italic(appname), green(str_version), rev, title('Kovid Goyal'))


def wrap(text, limit=80):
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

    lines = []
    for b in reversed(breaks):
        lines.append(text[b:].lstrip())
        text = text[:b]
    if text:
        lines.append(text)
    return reversed(lines)


def print_help_for_seq(seq, usage, message, appname):
    from kitty.icat import screen_size
    screen_size.changed = True
    try:
        linesz = min(screen_size().cols, 76)
    except EnvironmentError:
        linesz = 76
    blocks = []
    a = blocks.append

    def wa(text, indent=0, leading_indent=None):
        if leading_indent is None:
            leading_indent = indent
        j = '\n' + (' ' * indent)
        lines = []
        for l in text.splitlines():
            if l:
                lines.extend(wrap(l, limit=linesz - indent))
            else:
                lines.append('')
        a((' ' * leading_indent) + j.join(lines))

    usage = '[program-to-run ...]' if usage is None else usage
    optstring = '[options] ' if seq else ''
    a('{}: {} {}{}'.format(title('Usage'), bold(yellow(appname)), optstring, usage))
    a('')
    message = message or (
        'Run the |G {appname}| terminal emulator. You can also specify the |_ program| to run inside |_ {appname}| as normal'
        ' arguments following the |_ options|. For example: {appname} /bin/sh'
    ).format(appname=appname)
    wa(prettify(message))
    a('')
    if seq:
        a('{}:'.format(title('Options')))
    for opt in seq:
        if isinstance(opt, str):
            a('{}:'.format(title(opt)))
            continue
        a('  ' + ', '.join(map(green, sorted(opt['aliases']))))
        if not opt.get('type', '').startswith('bool-'):
            blocks[-1] += '={}'.format(italic(opt['dest'].upper()))
        if opt.get('help'):
            defval = opt.get('default')
            t = opt['help'].replace('%default', str(defval))
            wa(prettify(t.strip()), indent=4)
            if defval is not None:
                wa('Default: {}'.format(defval), indent=4)
            if 'choices' in opt:
                wa('Choices: {}'.format(', '.join(opt['choices'])), indent=4)
            a('')

    text = '\n'.join(blocks) + '\n\n' + version()
    if print_help_for_seq.allow_pager and sys.stdout.isatty():
        p = subprocess.Popen(['less', '-isRXF'], stdin=subprocess.PIPE)
        p.communicate(text.encode('utf-8'))
        raise SystemExit(p.wait())
    else:
        print(text)


print_help_for_seq.allow_pager = True


def defval_for_opt(opt):
    dv = opt.get('default')
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

    def __init__(self, seq, usage, message, appname):
        self.alias_map = {}
        self.seq = seq
        self.names_map = {}
        self.values_map = {}
        self.usage, self.message, self.appname = usage, message, appname
        for opt in seq:
            if isinstance(opt, str):
                continue
            for alias in opt['aliases']:
                self.alias_map[alias] = opt
            name = opt['dest']
            self.names_map[name] = opt
            self.values_map[name] = defval_for_opt(opt)

    def opt_for_alias(self, alias):
        opt = self.alias_map.get(alias)
        if opt is None:
            raise SystemExit('Unknown option: {}'.format(emph(alias)))
        return opt

    def needs_arg(self, alias):
        if alias in ('-h', '--help'):
            print_help_for_seq(self.seq, self.usage, self.message, self.appname or appname)
            raise SystemExit(0)
        opt = self.opt_for_alias(alias)
        if opt['dest'] == 'version':
            print(version())
            raise SystemExit(0)
        typ = opt.get('type', '')
        return not typ.startswith('bool-')

    def process_arg(self, alias, val=None):
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


class Namespace:

    def __init__(self, kwargs):
        for name in kwargs:
            setattr(self, name, kwargs[name])


def parse_cmdline(oc, disabled, args=None):
    NORMAL, EXPECTING_ARG = 'NORMAL', 'EXPECTING_ARG'
    state = NORMAL
    if args is None:
        args = sys.argv[1:]
    args = deque(args)
    current_option = None

    while args:
        arg = args.popleft()
        if state is NORMAL:
            if arg.startswith('-'):
                if arg == '--':
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
                args = [arg] + list(args)
                break
        else:
            oc.process_arg(current_option, arg)
            current_option, state = None, NORMAL
    if state is EXPECTING_ARG:
        raise SystemExit('An argument is required for the option: {}'.format(emph(arg)))

    ans = Namespace(oc.values_map)
    for opt in disabled:
        setattr(ans, opt['dest'], defval_for_opt(opt))
    return ans, list(args)


def options_spec():
    if not hasattr(options_spec, 'ans'):
        options_spec.ans = OPTIONS.format(
            appname=appname, macos_confpath='~/Library/Preferences/kitty/kitty.conf, ' if is_macos else '',
            window_layout_choices=', '.join(all_layouts)
        )
    return options_spec.ans


def parse_args(args=None, ospec=options_spec, usage=None, message=None, appname=None):
    options = parse_option_spec(ospec())
    seq, disabled = options
    oc = Options(seq, usage, message, appname)
    return parse_cmdline(oc, disabled, args=args)


SYSTEM_CONF = '/etc/xdg/kitty/kitty.conf'


def resolve_config(config_files_on_cmd_line):
    if config_files_on_cmd_line:
        if 'NONE' not in config_files_on_cmd_line:
            yield SYSTEM_CONF
            for cf in config_files_on_cmd_line:
                yield cf
    else:
        yield SYSTEM_CONF
        yield defconf


def print_shortcut(key, action):
    if not getattr(print_shortcut, 'maps', None):
        from kitty.keys import defines
        v = vars(defines)
        mmap = {m.split('_')[-1].lower(): x for m, x in v.items() if m.startswith('GLFW_MOD_')}
        kmap = {k.split('_')[-1].lower(): x for k, x in v.items() if k.startswith('GLFW_KEY_')}
        krmap = {v: k for k, v in kmap.items()}
        print_shortcut.maps = mmap, krmap
    mmap, krmap = print_shortcut.maps
    names = []
    mods, key = key
    for name, val in mmap.items():
        if mods & val:
            names.append(name)
    if key:
        names.append(krmap[key])
    print('\t', '+'.join(names), action)


def compare_keymaps(final, initial):
    added = set(final) - set(initial)
    removed = set(initial) - set(final)
    changed = {k for k in set(final) & set(initial) if final[k] != initial[k]}
    if added:
        print(title('Added shortcuts:'))
        for k in added:
            print_shortcut(k, final[k])
    if removed:
        print(title('Removed shortcuts:'))
        for k in removed:
            print_shortcut(k, initial[k])
    if changed:
        print(title('Changed shortcuts:'))
        for k in changed:
            print_shortcut(k, final[k])


def compare_opts(opts):
    print('\nConfig options different from defaults:')
    for f in sorted(defaults._fields):
        if getattr(opts, f) != getattr(defaults, f):
            if f == 'keymap':
                compare_keymaps(opts.keymap, defaults.keymap)
            else:
                print(title('{:20s}'.format(f)), getattr(opts, f))


def create_opts(args, debug_config=False):
    config = tuple(resolve_config(args.config))
    if debug_config:
        print(version(add_rev=True))
        print(' '.join(os.uname()))
        if is_macos:
            print(' '.join(subprocess.check_output(['sw_vers']).decode('utf-8').splitlines()).strip())
        else:
            print('Running under:', green('Wayland' if is_wayland else 'X11'))
        if os.path.exists('/etc/issue'):
            print(open('/etc/issue', encoding='utf-8', errors='replace').read().strip())
        if os.path.exists('/etc/lsb-release'):
            print(open('/etc/lsb-release', encoding='utf-8', errors='replace').read().strip())
        config = tuple(x for x in config if os.path.exists(x))
        if config:
            print(green('Loaded config files:'), ', '.join(config))
    overrides = (a.replace('=', ' ', 1) for a in args.override or ())
    opts = load_config(*config, overrides=overrides)
    if debug_config:
        compare_opts(opts)
    return opts
