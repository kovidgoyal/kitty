#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import sys
from collections.abc import Callable, Iterator, Sequence
from re import Match
from typing import Any, NoReturn, TypeVar, cast

from .cli_stub import CLIOptions
from .conf.utils import resolve_config
from .constants import appname, clear_handled_signals, config_dir, default_pager_for_help, defconf, is_macos, str_version, website_url
from .fast_data_types import parse_cli_from_spec, wcswidth
from .options.types import Options as KittyOpts
from .simple_cli_definitions import (
    CompletionType,
    OptionDict,
    OptionSpecSeq,
    defval_for_opt,
    get_option_maps,
    kitty_options_spec,
    parse_option_spec,
    serialize_as_go_string,
)
from .types import run_once
from .typing_compat import BadLineType

is_macos
go_type_map = {
    'bool-set': 'bool', 'bool-reset': 'bool', 'bool-unset': 'bool', 'int': 'int', 'float': 'float64',
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

    @property
    def flags(self) -> list[str]:
        return sorted(self.obj_dict['aliases'])

    def as_option(self, cmd_name: str = 'cmd', depth: int = 0, group: str = '') -> str:
        add = f'AddToGroup("{serialize_as_go_string(group)}", ' if group else 'Add('
        aliases = ' '.join(self.flags)
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
            ans += f'\n\tDepth: {depth},\n'
        if self.default:
            ans += f'\n\tDefault: "{serialize_as_go_string(self.default)}",\n'
        return ans + '})'

    def as_string_for_commandline(self) -> Iterator[str]:
        # }}}}}}}}}}}]]]]]]]]]]]]]]]]]
        flag = self.flags[0]
        val = f'opts.{self.go_var_name}'
        if self.go_type == '[]string':
            yield f'\tfor _, x := range {val} {{ ans = append(ans, `{flag}=` + x) }}'
            return
        match self.go_type:
            case 'bool':
                yield f'sval = fmt.Sprintf(`%#v`, {val})'
                godef = '`true`' if self.type != 'bool-set' else '`false`'
            case 'int':
                yield f'sval = fmt.Sprintf(`%d`, {val})'
                godef = f"`{self.default or '0'}`"
            case 'string':
                yield f'sval = {val}'
                godef = f'''"{serialize_as_go_string(self.default or '')}"'''
            case 'float64':
                yield f'sval = fmt.Sprintf(`%f`, {val})'
                godef = f"`{self.default or '0'}`"
            case _:
                raise ValueError(f'Unknown type: {self.go_type}')
        yield f'\tif (sval != {godef}) {{ ans = append(ans, `{flag}=` + sval)}}'

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


def help_defval_for_bool(otype: str) -> str:
    if otype == 'bool-set':
        return 'no'
    return 'yes'


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
            if (otype := opt.get('type', '')).startswith('bool-'):
                blocks[-1] += italic(f'[={help_defval_for_bool(otype)}]')
            else:
                dt = f'''=[{italic(defval or '""')}]'''
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
        if (otype := opt.get('type', '')).startswith('bool-'):
            val_name = f' [={help_defval_for_bool(otype)}]'
        else:
            val_name = ' <{}>'.format(opt['dest'].upper())
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


bool_map = {'y': True, 'yes': True, 'true': True, 'n': False, 'no': False, 'false': False}


def to_bool(alias: str, x: str) -> bool:
    try:
        return bool_map[x]
    except KeyError:
        raise SystemExit(f'{x} is not a valid value for {alias}. Valid values are y, yes, true, n, no, false only')


class Options:

    do_print = True

    def __init__(self, seq: OptionSpecSeq, usage: str | None, message: str | None, appname: str | None):
        self.seq = seq
        self.usage, self.message, self.appname = usage, message, appname
        self.names_map, self.alias_map, self.values_map = get_option_maps(seq)
        self.help_called = self.version_called = False

    def handle_help(self) -> NoReturn:
        if self.do_print:
            print_help_for_seq(self.seq, self.usage, self.message, self.appname or appname)
        self.help_called = True
        raise SystemExit(0)

    def handle_version(self) -> NoReturn:
        self.version_called = True
        if self.do_print:
            print(version())
        raise SystemExit(0)


PreparsedCLIFlags = tuple[dict[str, tuple[Any, bool]], list[str]]


def apply_preparsed_cli_flags(preparsed_from_c: PreparsedCLIFlags, ans: Any, create_oc: Callable[[], Options]) -> list[str]:
    for key, (val, is_seen) in preparsed_from_c[0].items():
        if key == 'help' and is_seen and val:
            create_oc().handle_help()
        elif key == 'version' and is_seen and val:
            create_oc().handle_version()
        setattr(ans, key, val)
    return preparsed_from_c[1]


def parse_cmdline(oc: Options, disabled: OptionSpecSeq, ans: Any, args: list[str] | None = None) -> list[str]:
    names_map = oc.names_map.copy()
    values_map = oc.values_map.copy()
    if 'help' not in names_map:
        names_map['help'] = {'type': 'bool-set', 'aliases': ('--help', '-h')}  # type: ignore
        values_map['help'] = False
    if 'version' not in names_map:
        names_map['version'] = {'type': 'bool-set', 'aliases': ('--version', '-v')}  # type: ignore
        values_map['version'] = False
    try:
        preparsed = parse_cli_from_spec(sys.argv[1:] if args is None else args, names_map, values_map)
    except Exception as e:
        raise SystemExit(str(e))
    leftover_args = apply_preparsed_cli_flags(preparsed, ans, lambda: oc)

    for opt in disabled:
        if not isinstance(opt, str):
            setattr(ans, opt['dest'], defval_for_opt(opt))
    return leftover_args



def options_for_completion() -> OptionSpecSeq:
    raw = '--help -h\ntype=bool-set\nShow help for {appname} command line options\n\n{raw}'.format(
            appname=appname, raw=kitty_options_spec())
    return parse_option_spec(raw)[0]


def option_spec_as_rst(
    ospec: Callable[[], str] = kitty_options_spec,
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
    ospec: Callable[[], str] = kitty_options_spec,
    usage: str | None = None,
    message: str | None = None,
    appname: str | None = None,
    result_class: type[T] | None = None,
    preparsed_from_c: PreparsedCLIFlags | None = None,
) -> tuple[T, list[str]]:
    if result_class is not None:
        ans = result_class()
    else:
        ans = cast(T, CLIOptions())

    def create_oc() -> Options:
        options = parse_option_spec(ospec())
        seq, disabled = options
        return Options(seq, usage, message, appname)

    if preparsed_from_c:
        return ans, apply_preparsed_cli_flags(preparsed_from_c, ans, create_oc)

    options = parse_option_spec(ospec())
    seq, disabled = options
    oc = Options(seq, usage, message, appname)
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
