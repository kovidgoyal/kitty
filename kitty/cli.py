#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import sys
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from enum import Enum, auto
from re import Match
from typing import Any, TypeVar, Union, cast

from .cli_stub import CLIOptions
from .conf.utils import resolve_config
from .constants import appname, clear_handled_signals, config_dir, default_pager_for_help, defconf, is_macos, str_version, website_url
from .fast_data_types import wcswidth
from .options.types import Options as KittyOpts
from .types import run_once
from .typing import BadLineType, TypedDict
from .utils import shlex_split


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
    aliases: frozenset[str]
    help: str
    choices: frozenset[str]
    type: str
    default: str | None
    condition: bool
    completion: CompletionSpec


def serialize_as_go_string(x: str) -> str:
    return x.replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"')


go_type_map = {
    'bool-set': 'bool', 'bool-reset': 'bool', 'int': 'int', 'float': 'float64',
    '': 'string', 'list': '[]string', 'choices': 'string', 'str': 'string'}


class GoOption:

    def __init__(self, x: OptionDict) -> None:
        flags = sorted(x['aliases'], key=len)
        short = ''
        self.aliases = []
        if len(flags) > 1 and not flags[0].startswith("--"):
            short = flags[0][1:]
        self.short, self.long = short, x['name'].replace('_', '-')
        for f in flags:
            q = f[2:] if f.startswith('--') else f[1:]
            self.aliases.append(q)
        self.type = x['type']
        if x['choices']:
            self.type = 'choices'
        self.default = x['default']
        self.obj_dict = x
        self.go_type = go_type_map[self.type]
        if x['dest']:
            self.go_var_name = ''.join(x.capitalize() for x in x['dest'].replace('-', '_').split('_'))
        else:
            self.go_var_name = ''.join(x.capitalize() for x in self.long.replace('-', '_').split('_'))
        self.help_text = serialize_as_go_string(self.obj_dict['help'].strip())

    def struct_declaration(self) -> str:
        return f'{self.go_var_name} {self.go_type}'

    def as_option(self, cmd_name: str = 'cmd', depth: int = 0, group: str = '') -> str:
        add = f'AddToGroup("{serialize_as_go_string(group)}", ' if group else 'Add('
        aliases = ' '.join(sorted(self.obj_dict['aliases']))
        ans = f'''{cmd_name}.{add}cli.OptionSpec{{
            Name: "{serialize_as_go_string(aliases)}",
            Type: "{self.type}",
            Dest: "{serialize_as_go_string(self.go_var_name)}",
            Help: "{self.help_text}",
        '''
        if self.type in ('choice', 'choices'):
            c = ', '.join(self.sorted_choices)
            cx = ', '.join(f'"{serialize_as_go_string(x)}"' for x in self.sorted_choices)
            ans += f'\nChoices: "{serialize_as_go_string(c)}",\n'
            ans += f'\nCompleter: cli.NamesCompleter("Choices for {self.long}", {cx}),'
        elif self.obj_dict['completion'].type is not CompletionType.none:
            ans += ''.join(self.obj_dict['completion'].as_go_code('Completer', ': ')) + ','
        if depth > 0:
            ans += f'\nDepth: {depth},\n'
        if self.default:
            ans += f'\nDefault: "{serialize_as_go_string(self.default)}",\n'
        return ans + '})'

    @property
    def sorted_choices(self) -> list[str]:
        choices = sorted(self.obj_dict['choices'])
        choices.remove(self.default or '')
        choices.insert(0, self.default or '')
        return choices


def go_options_for_seq(seq: 'OptionSpecSeq') -> Iterator[GoOption]:
    for x in seq:
        if not isinstance(x, str):
            yield GoOption(x)


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


def surround(x: str, start: int, end: int) -> str:
    if sys.stdout.isatty():
        x = f'\033[{start}m{x}\033[{end}m'
    return x


role_map: dict[str, Callable[[str], str]] = {}


def role(func: Callable[[str], str]) -> Callable[[str], str]:
    role_map[func.__name__] = func
    return func


@role
def emph(x: str) -> str:
    return surround(x, 91, 39)


@role
def cyan(x: str) -> str:
    return surround(x, 96, 39)


@role
def green(x: str) -> str:
    return surround(x, 32, 39)


@role
def blue(x: str) -> str:
    return surround(x, 34, 39)


@role
def yellow(x: str) -> str:
    return surround(x, 93, 39)


@role
def italic(x: str) -> str:
    return surround(x, 3, 23)


@role
def bold(x: str) -> str:
    return surround(x, 1, 22)


@role
def title(x: str) -> str:
    return blue(bold(x))


@role
def opt(text: str) -> str:
    return bold(text)


@role
def option(x: str) -> str:
    idx = x.rfind('--')
    if idx < 0:
        idx = x.find('-')
    if idx > -1:
        x = x[idx:]
    return bold(x.rstrip('>'))


@role
def code(x: str) -> str:
    return cyan(x)


def text_and_target(x: str) -> tuple[str, str]:
    parts = x.split('<', 1)
    return parts[0].strip(), parts[-1].rstrip('>')


@role
def term(x: str) -> str:
    return ref_hyperlink(x, 'term-')


@role
def kbd(x: str) -> str:
    return x


@role
def env(x: str) -> str:
    return ref_hyperlink(x, 'envvar-')


role_map['envvar'] = role_map['env']


@run_once
def hostname() -> str:
    from .utils import get_hostname
    return get_hostname(fallback='localhost')


def hyperlink_for_url(url: str, text: str) -> str:
    if sys.stdout.isatty():
        return f'\x1b]8;;{url}\x1b\\\x1b[4:3;58:5:4m{text}\x1b[4:0;59m\x1b]8;;\x1b\\'
    return text


def hyperlink_for_path(path: str, text: str) -> str:
    path = os.path.abspath(path).replace(os.sep, "/")
    if os.path.isdir(path):
        path += path.rstrip("/") + "/"
    return hyperlink_for_url(f'file://{hostname()}{path}', text)


@role
def file(x: str) -> str:
    if x == 'kitty.conf':
        x = hyperlink_for_path(os.path.join(config_dir, x), x)
    return italic(x)


@role
def doc(x: str) -> str:
    t, q = text_and_target(x)
    if t == q:
        from .conf.types import ref_map
        m = ref_map()['doc']
        q = q.strip('/')
        if q in m:
            x = f'{m[q]} <{t}>'
    return ref_hyperlink(x, 'doc-')


def ref_hyperlink(x: str, prefix: str = '') -> str:
    t, q = text_and_target(x)
    url = f'kitty+doc://{hostname()}/#ref={prefix}{q}'
    t = re.sub(r':([a-z]+):`([^`]+)`', r'\2', t)
    return hyperlink_for_url(url, t)


@role
def ref(x: str) -> str:
    return ref_hyperlink(x)


@role
def ac(x: str) -> str:
    return ref_hyperlink(x, 'action-')


@role
def iss(x: str) -> str:
    return ref_hyperlink(x, 'issues-')


@role
def pull(x: str) -> str:
    return ref_hyperlink(x, 'pull-')


@role
def disc(x: str) -> str:
    return ref_hyperlink(x, 'discussions-')


OptionSpecSeq = list[Union[str, OptionDict]]


def parse_option_spec(spec: str | None = None) -> tuple[OptionSpecSeq, OptionSpecSeq]:
    if spec is None:
        spec = options_spec()
    NORMAL, METADATA, HELP = 'NORMAL', 'METADATA', 'HELP'
    state = NORMAL
    lines = spec.splitlines()
    prev_line = ''
    prev_indent = 0
    seq: OptionSpecSeq = []
    disabled: OptionSpecSeq = []
    mpat = re.compile('([a-z]+)=(.+)')
    current_cmd: OptionDict = {
        'dest': '', 'aliases': frozenset(), 'help': '', 'choices': frozenset(),
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
                    'dest': defdest, 'aliases': frozenset(parts), 'help': '',
                    'choices': frozenset(), 'type': '', 'name': defdest,
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
                    current_cmd['choices'] = frozenset(vals)
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


def prettify(text: str) -> str:

    def identity(x: str) -> str:
        return x

    def sub(m: 'Match[str]') -> str:
        role, text = m.group(1, 2)
        return role_map.get(role, identity)(text)

    text = re.sub(r':([a-z]+):`([^`]+)`', sub, text)
    return text


def prettify_rst(text: str) -> str:
    return re.sub(r':([a-z]+):`([^`]+)`(=[^\s.]+)', r':\1:`\2`:code:`\3`', text)


def version(add_rev: bool = False) -> str:
    rev = ''
    from . import fast_data_types
    if add_rev:
        if getattr(fast_data_types, 'KITTY_VCS_REV', ''):
            rev = f' ({fast_data_types.KITTY_VCS_REV[:10]})'
    return '{} {}{} created by {}'.format(italic(appname), green(str_version), rev, title('Kovid Goyal'))


def wrap(text: str, limit: int = 80) -> Iterator[str]:
    if not text.strip():
        yield ''
        return
    in_escape = 0
    current_line: list[str] = []
    escapes: list[str] = []
    current_word: list[str] = []
    current_line_length = 0

    def print_word(ch: str = '') -> Iterator[str]:
        nonlocal current_word, current_line, escapes, current_line_length
        cw = ''.join(current_word)
        w = wcswidth(cw)
        if current_line_length + w > limit:
            yield ''.join(current_line)
            current_line = []
            current_line_length = 0
            cw = cw.strip()
            current_word = [cw]
        if escapes:
            current_line.append(''.join(escapes))
            escapes = []
        if current_word:
            current_line.append(cw)
            current_line_length += w
            current_word = []
        if ch:
            current_word.append(ch)

    for i, ch in enumerate(text):
        if in_escape > 0:
            if in_escape == 1 and ch in '[]':
                in_escape = 2 if ch == '[' else 3
            if (in_escape == 2 and ch == 'm') or (in_escape == 3 and ch == '\\' and text[i-1] == '\x1b'):
                in_escape = 0
            escapes.append(ch)
            continue
        if ch == '\x1b':
            in_escape = 1
            if current_word:
                yield from print_word()
            escapes.append(ch)
            continue
        if current_word and ch.isspace() and ch != '\xa0':
            yield from print_word(ch)
        else:
            current_word.append(ch)
    yield from print_word()
    if current_line:
        yield ''.join(current_line)


def get_defaults_from_seq(seq: OptionSpecSeq) -> dict[str, Any]:
    ans: dict[str, Any] = {}
    for opt in seq:
        if not isinstance(opt, str):
            ans[opt['dest']] = defval_for_opt(opt)
    return ans


default_msg = ('''\
Run the :italic:`{appname}` terminal emulator. You can also specify the
:italic:`program` to run inside :italic:`{appname}` as normal arguments
following the :italic:`options`.
For example: {appname} --hold sh -c "echo hello, world"

For comprehensive documentation for kitty, please see: {url}''').format(
    appname=appname, url=website_url())


class PrintHelpForSeq:

    allow_pager = True

    def __call__(self, seq: OptionSpecSeq, usage: str | None, message: str | None, appname: str) -> None:
        from kitty.utils import screen_size_function
        screen_size = screen_size_function()
        try:
            linesz = min(screen_size().cols, 76)
        except OSError:
            linesz = 76
        blocks: list[str] = []
        a = blocks.append

        def wa(text: str, indent: int = 0, leading_indent: int | None = None) -> None:
            if leading_indent is None:
                leading_indent = indent
            j = '\n' + (' ' * indent)
            lines: list[str] = []
            for ln in text.splitlines():
                lines.extend(wrap(ln, limit=linesz - indent))
            a((' ' * leading_indent) + j.join(lines))

        usage = '[program-to-run ...]' if usage is None else usage
        optstring = '[options] ' if seq else ''
        a('{}: {} {}{}'.format(title('Usage'), bold(yellow(appname)), optstring, usage))
        a('')
        message = message or default_msg
        # replace rst literal code block syntax
        message = message.replace('::\n\n', ':\n\n')
        wa(prettify(message))
        a('')
        if seq:
            a('{}:'.format(title('Options')))
        for opt in seq:
            if isinstance(opt, str):
                a(f'{title(opt)}:')
                continue
            help_text = opt['help']
            if help_text == '!':
                continue  # hidden option
            a('  ' + ', '.join(map(green, sorted(opt['aliases'], reverse=True))))
            defval = opt.get('default')
            if not opt.get('type', '').startswith('bool-'):
                if defval:
                    dt = f'=[{italic(defval)}]'
                    blocks[-1] += dt
            if opt.get('help'):
                t = help_text.replace('%default', str(defval)).strip()
                # replace rst literal code block syntax
                t = t.replace('::\n\n', ':\n\n')
                t = t.replace('#placeholder_for_formatting#', '')
                wa(prettify(t), indent=4)
                if opt.get('choices'):
                    wa('Choices: {}'.format(', '.join(opt['choices'])), indent=4)
                a('')

        text = '\n'.join(blocks) + '\n\n' + version()
        if print_help_for_seq.allow_pager and sys.stdout.isatty():
            import subprocess
            try:
                p = subprocess.Popen(default_pager_for_help, stdin=subprocess.PIPE, preexec_fn=clear_handled_signals)
            except FileNotFoundError:
                print(text)
            else:
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
    usage: str | None,
    message: str | None,
    appname: str | None,
    heading_char: str = '-'
) -> str:
    import textwrap
    blocks: list[str] = []
    a = blocks.append

    usage = '[program-to-run ...]' if usage is None else usage
    optstring = '[options] ' if seq else ''
    a('.. highlight:: sh')
    a('.. code-block:: sh')
    a('')
    a(f'  {appname} {optstring}{usage}')
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
            t = t.replace('#placeholder_for_formatting#', '')
            a('')
            a(textwrap.indent(prettify_rst(t), ' ' * 4))
            if defval is not None:
                a(textwrap.indent(f'Default: :code:`{defval}`', ' ' * 4))
            if opt.get('choices'):
                a(textwrap.indent('Choices: {}'.format(', '.join(f':code:`{c}`' for c in sorted(opt['choices']))), ' ' * 4))
            a('')

    text = '\n'.join(blocks)
    return text


def as_type_stub(seq: OptionSpecSeq, disabled: OptionSpecSeq, class_name: str, extra_fields: Sequence[str] = ()) -> str:
    from itertools import chain
    ans: list[str] = [f'class {class_name}:']
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
            raise ValueError(f'Unknown CLI option type: {otype}')
        ans.append(f'    {name}: {t}')
    for x in extra_fields:
        ans.append(f'    {x}')
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

    def __init__(self, seq: OptionSpecSeq, usage: str | None, message: str | None, appname: str | None):
        self.alias_map = {}
        self.seq = seq
        self.names_map: dict[str, OptionDict] = {}
        self.values_map: dict[str, Any] = {}
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
            raise SystemExit(f'Unknown option: {emph(alias)}')
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


def parse_cmdline(oc: Options, disabled: OptionSpecSeq, ans: Any, args: list[str] | None = None) -> list[str]:
    NORMAL, EXPECTING_ARG = 'NORMAL', 'EXPECTING_ARG'
    state = NORMAL
    dargs = deque(sys.argv[1:] if args is None else args)
    leftover_args: list[str] = []
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
                        raise SystemExit(f'The {emph(parts[0])} option does not accept arguments')
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
        raise SystemExit(f'An argument is required for the option: {emph(arg)}')

    for key, val in oc.values_map.items():
        setattr(ans, key, val)
    for opt in disabled:
        if not isinstance(opt, str):
            setattr(ans, opt['dest'], defval_for_opt(opt))
    return leftover_args


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


def options_spec() -> str:
    if not hasattr(options_spec, 'ans'):
        OPTIONS = '''
--class --app-id
dest=cls
default={appname}
condition=not is_macos
Set the class part of the :italic:`WM_CLASS` window property. On Wayland, it
sets the app id.


--name
condition=not is_macos
Set the name part of the :italic:`WM_CLASS` property. Defaults to using the
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


--wait-for-single-instance-window-close
type=bool-set
Normally, when using :option:`{appname} --single-instance`, :italic:`{appname}`
will open a new window in an existing instance and quit immediately. With this
option, it will not quit till the newly opened window is closed. Note that if no
previous instance is found, then :italic:`{appname}` will wait anyway,
regardless of this option.


{listen_on_defn} To start in headless mode,
without an actual window, use :option:`{appname} --start-as`=hidden.


--start-as
type=choices
default=normal
choices=normal,fullscreen,maximized,minimized,hidden
Control how the initial kitty window is created.


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
        setattr(options_spec, 'ans', OPTIONS.format(
            appname=appname, conf_name=appname, listen_on_defn=listen_on_defn,
            config_help=CONFIG_HELP.format(appname=appname, conf_name=appname),
        ))
    ans: str = getattr(options_spec, 'ans')
    return ans


def options_for_completion() -> OptionSpecSeq:
    raw = '--help -h\ntype=bool-set\nShow help for {appname} command line options\n\n{raw}'.format(
            appname=appname, raw=options_spec())
    return parse_option_spec(raw)[0]


def option_spec_as_rst(
    ospec: Callable[[], str] = options_spec,
    usage: str | None = None, message: str | None = None, appname: str | None = None,
    heading_char: str = '-'
) -> str:
    options = parse_option_spec(ospec())
    seq, disabled = options
    oc = Options(seq, usage, message, appname)
    return seq_as_rst(oc.seq, oc.usage, oc.message, oc.appname, heading_char=heading_char)


T = TypeVar('T')


def parse_args(
    args: list[str] | None = None,
    ospec: Callable[[], str] = options_spec,
    usage: str | None = None,
    message: str | None = None,
    appname: str | None = None,
    result_class: type[T] | None = None,
) -> tuple[T, list[str]]:
    options = parse_option_spec(ospec())
    seq, disabled = options
    oc = Options(seq, usage, message, appname)
    if result_class is not None:
        ans = result_class()
    else:
        ans = cast(T, CLIOptions())
    return ans, parse_cmdline(oc, disabled, ans, args=args)


SYSTEM_CONF = f'/etc/xdg/{appname}/{appname}.conf'


def default_config_paths(conf_paths: Sequence[str]) -> tuple[str, ...]:
    return tuple(resolve_config(SYSTEM_CONF, defconf, conf_paths))


@run_once
def override_pat() -> 're.Pattern[str]':
    return re.compile(r'^([a-zA-Z0-9_]+)[ \t]*=')


def parse_override(x: str) -> str:
    # Does not cover the case where `name =` when `=` is the value.
    return override_pat().sub(r'\1 ', x.lstrip())


def create_opts(args: CLIOptions, accumulate_bad_lines: list[BadLineType] | None = None) -> KittyOpts:
    from .config import load_config
    config = default_config_paths(args.config)
    overrides = map(parse_override, args.override or ())
    opts = load_config(*config, overrides=overrides, accumulate_bad_lines=accumulate_bad_lines)
    return opts


def create_default_opts() -> KittyOpts:
    from .config import load_config
    config = default_config_paths(())
    opts = load_config(*config)
    return opts
