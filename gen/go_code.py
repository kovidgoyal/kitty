#!./kitty/launcher/kitty +launch
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import bz2
import io
import json
import os
import re
import shlex
import struct
import subprocess
import sys
import tarfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from functools import lru_cache
from itertools import chain
from typing import (
    Any,
    BinaryIO,
    Optional,
    TextIO,
    Union,
)

import kitty.constants as kc
from kittens.tui.operations import Mode
from kittens.tui.spinners import spinners
from kitty.actions import get_all_actions
from kitty.cli import (
    GoOption,
    go_options_for_seq,
)
from kitty.conf.generate import gen_go_code
from kitty.conf.types import Definition
from kitty.config import commented_out_default_config
from kitty.guess_mime_type import known_extensions, text_mimes
from kitty.key_encoding import config_mod_map
from kitty.key_names import character_key_name_aliases, functional_key_name_aliases
from kitty.options.types import Options
from kitty.rc.base import RemoteCommand, all_command_names, command_for_name
from kitty.remote_control import global_options_spec
from kitty.rgb import color_names
from kitty.simple_cli_definitions import CompletionSpec, parse_option_spec, serialize_as_go_string

if __name__ == '__main__' and not __package__:
    import __main__
    __main__.__package__ = 'gen'
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


changed: list[str] = []


def newer(dest: str, *sources: str) -> bool:
    try:
        dtime = os.path.getmtime(dest)
    except OSError:
        return True
    for s in chain(sources, (__file__,)):
        with suppress(FileNotFoundError):
            if os.path.getmtime(s) >= dtime:
                return True
    return False



# Utils {{{

def serialize_go_dict(x: Union[dict[str, int], dict[int, str], dict[int, int], dict[str, str]]) -> str:
    ans = []

    def s(x: Union[int, str]) -> str:
        if isinstance(x, int):
            return str(x)
        return f'"{serialize_as_go_string(x)}"'

    for k, v in x.items():
        ans.append(f'{s(k)}: {s(v)}')
    return '{' + ', '.join(ans) + '}'


def replace(template: str, **kw: str) -> str:
    for k, v in kw.items():
        template = template.replace(k, v)
    return template
# }}}

# {{{  Stringer


@lru_cache(maxsize=1)
def enum_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument('--from-string-func-name')
    return p


def stringify_file(path: str) -> None:
    with open(path) as f:
        src = f.read()
    types = {}
    constant_name_maps = {}
    for m in re.finditer(r'^type +(\S+) +\S+ +// *enum *(.*?)$', src, re.MULTILINE):
        args = m.group(2)
        types[m.group(1)] = enum_parser().parse_args(args=shlex.split(args) if args else [])

    def get_enum_def(src: str) -> None:
        type_name = q = ''
        constants = {}
        for line in src.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if not type_name:
                if len(parts) < 2 or parts[1] not in types:
                    return
                type_name = parts[1]
                q = type_name + '_'
            constant_name = parts[0]
            a, sep, b = line.partition('//')
            if sep:
                string_val = b.strip()
            else:
                string_val = constant_name
                if constant_name.startswith(q):
                    string_val = constant_name[len(q):]
            constants[constant_name] = serialize_as_go_string(string_val)
        if constants and type_name:
            constant_name_maps[type_name] = constants

    for m in re.finditer(r'^const +\((.+?)^\)', src, re.MULTILINE|re.DOTALL):
        get_enum_def(m.group(1))

    with replace_if_needed(path.replace('.go', '_stringer_generated.go')):
        print('package', os.path.basename(os.path.dirname(path)))
        print ('import "fmt"')
        print ('import "encoding/json"')
        print()
        for type_name, constant_map in constant_name_maps.items():
            print(f'func (self {type_name}) String() string ''{')
            print('switch self {')
            is_first = True
            for constant_name, string_val in constant_map.items():
                if is_first:
                    print(f'default: return "{string_val}"')
                    is_first = False
                else:
                    print(f'case {constant_name}: return "{string_val}"')
            print('}}')
            print(f'func (self {type_name}) MarshalJSON() ([]byte, error) {{ return json.Marshal(self.String()) }}')
            fsname = types[type_name].from_string_func_name or (type_name + '_from_string')
            print(f'func {fsname}(x string) (ans {type_name}, err error) ''{')
            print('switch x {')
            for constant_name, string_val in constant_map.items():
                print(f'case "{string_val}": return {constant_name}, nil')
            print('}')
            print(f'err = fmt.Errorf("unknown value for enum {type_name}: %#v", x)')
            print('return')
            print('}')
            print(f'func (self *{type_name}) SetString(x string) error ''{')
            print(f's, err := {fsname}(x); if err == nil {{ *self = s }}; return err''}')
            print(f'func (self *{type_name}) UnmarshalJSON(data []byte) (err error)''{')
            print('var x string')
            print('if err = json.Unmarshal(data, &x); err != nil {return err}')
            print('return self.SetString(x)}')


def stringify() -> None:
    for path in (
        'tools/tui/graphics/command.go',
        'tools/rsync/algorithm.go',
        'kittens/transfer/ftc.go',
    ):
        stringify_file(path)
# }}}

# {{{ Bitfields

def make_bitfields() -> None:
    from kitty.fast_data_types import SCALE_BITS, SUBSCALE_BITS, WIDTH_BITS

    from .bitfields import make_bitfield

    def mb(*args: str) -> None:
        output_path, ans = make_bitfield(*args)
        with replace_if_needed(output_path) as buf:
            print(ans, file=buf)

    mb(
        'tools/vt', 'CellAttrs',
        'decoration 3', 'bold 1', 'italic 1', 'reverse 1', 'strike 1', 'dim 1', 'hyperlink_id 16',
    )
    mb('tools/vt', 'Ch', 'is_idx 1', 'ch_or_idx 31')
    mb(
        'tools/vt', 'MultiCell',
        'is_multicell 1', 'natural_width 1', f'scale {SCALE_BITS}', f'subscale_n {SUBSCALE_BITS}', f'subscale_d {SUBSCALE_BITS}',
        f'width {WIDTH_BITS}', f'x {WIDTH_BITS + SCALE_BITS + 1}', f'y {SCALE_BITS + 1}', 'vertical_align 3',
    )
    mb('tools/vt', 'CellColor', 'is_idx 1', 'red 8', 'green 8', 'blue 8')
    mb('tools/vt', 'LineAttrs', 'prompt_kind 2',)
    mb('kittens/choose_files', 'CombinedScore', 'score 16', 'length 16', 'index 32')
# }}}

# Completions {{{

@lru_cache
def kitten_cli_docs(kitten: str) -> Any:
    from kittens.runner import get_kitten_cli_docs
    return get_kitten_cli_docs(kitten)


@lru_cache
def go_options_for_kitten(kitten: str) -> tuple[Sequence[GoOption], Optional[CompletionSpec]]:
    kcd = kitten_cli_docs(kitten)
    if kcd:
        ospec = kcd['options']
        return (tuple(go_options_for_seq(parse_option_spec(ospec())[0])), kcd.get('args_completion'))
    return (), None


def generate_kittens_completion() -> None:
    from kittens.runner import all_kitten_names, get_kitten_wrapper_of
    for kitten in sorted(all_kitten_names()):
        kn = 'kitten_' + kitten
        print(f'{kn} := plus_kitten.AddSubCommand(&cli.Command{{Name:"{kitten}", Group: "Kittens"}})')
        wof = get_kitten_wrapper_of(kitten)
        if wof:
            print(f'{kn}.ArgCompleter = cli.CompletionForWrapper("{serialize_as_go_string(wof)}")')
            print(f'{kn}.OnlyArgsAllowed = true')
            continue
        gopts, ac = go_options_for_kitten(kitten)
        if gopts or ac:
            for opt in gopts:
                print(opt.as_option(kn))
            if ac is not None:
                print(''.join(ac.as_go_code(kn + '.ArgCompleter', ' = ')))
        else:
            print(f'{kn}.HelpText = ""')


@lru_cache
def clone_safe_launch_opts() -> Sequence[GoOption]:
    from kitty.launch import clone_safe_opts, options_spec
    ans = []
    allowed = clone_safe_opts()
    for o in go_options_for_seq(parse_option_spec(options_spec())[0]):
        if o.obj_dict['name'] in allowed:
            ans.append(o)
    return tuple(ans)


def completion_for_launch_wrappers(*names: str) -> None:
    for o in clone_safe_launch_opts():
        for name in names:
            print(o.as_option(name))


def generate_completions_for_kitty() -> None:
    print('package completion\n')
    print('import "github.com/kovidgoyal/kitty/tools/cli"')
    print('import "github.com/kovidgoyal/kitty/tools/cmd/tool"')
    print('import "github.com/kovidgoyal/kitty/tools/cmd/at"')

    print('func kitty(root *cli.Command) {')

    # The kitty exe
    print('k := root.AddSubCommand(&cli.Command{'
          'Name:"kitty", SubCommandIsOptional: true, ArgCompleter: cli.CompleteExecutableFirstArg, SubCommandMustBeFirst: true })')
    print('kt := root.AddSubCommand(&cli.Command{Name:"kitten", SubCommandMustBeFirst: true })')
    print('tool.KittyToolEntryPoints(kt)')
    for opt in go_options_for_seq(parse_option_spec()[0]):
        print(opt.as_option('k'))

    # kitty +
    print('plus := k.AddSubCommand(&cli.Command{Name:"+", Group:"Entry points", ShortDescription: "Various special purpose tools and kittens"})')

    # kitty +launch
    print('plus_launch := plus.AddSubCommand(&cli.Command{'
          'Name:"launch", Group:"Entry points", ShortDescription: "Launch Python scripts", ArgCompleter: complete_plus_launch})')
    print('k.AddClone("", plus_launch).Name = "+launch"')

    # kitty +list-fonts
    print('plus_list_fonts := plus.AddSubCommand(&cli.Command{'
          'Name:"list-fonts", Group:"Entry points", ShortDescription: "List all available monospaced fonts"})')
    print('k.AddClone("", plus_list_fonts).Name = "+list-fonts"')

    # kitty +runpy
    print('plus_runpy := plus.AddSubCommand(&cli.Command{'
          'Name: "runpy", Group:"Entry points", ArgCompleter: complete_plus_runpy, ShortDescription: "Run Python code"})')
    print('k.AddClone("", plus_runpy).Name = "+runpy"')

    # kitty +open
    print('plus_open := plus.AddSubCommand(&cli.Command{'
          'Name:"open", Group:"Entry points", ArgCompleter: complete_plus_open, ShortDescription: "Open files and URLs"})')
    print('for _, og := range k.OptionGroups { plus_open.OptionGroups = append(plus_open.OptionGroups, og.Clone(plus_open)) }')
    print('k.AddClone("", plus_open).Name = "+open"')

    # kitty +kitten
    print('plus_kitten := plus.AddSubCommand(&cli.Command{Name:"kitten", Group:"Kittens", SubCommandMustBeFirst: true})')
    generate_kittens_completion()
    print('k.AddClone("", plus_kitten).Name = "+kitten"')

    # @
    print('at.EntryPoint(k)')

    # clone-in-kitty, edit-in-kitty
    print('cik := root.AddSubCommand(&cli.Command{Name:"clone-in-kitty"})')
    completion_for_launch_wrappers('cik')

    print('}')
    print('func init() {')
    print('cli.RegisterExeForCompletion(kitty)')
    print('}')
# }}}


# rc command wrappers {{{
json_field_types: dict[str, str] = {
    'bool': 'bool', 'str': 'escaped_string', 'list.str': '[]escaped_string', 'dict.str': 'map[escaped_string]escaped_string', 'float': 'float64', 'int': 'int',
    'scroll_amount': 'any', 'spacing': 'any', 'colors': 'any',
}


def go_field_type(json_field_type: str) -> str:
    json_field_type = json_field_type.partition('=')[0]
    q = json_field_types.get(json_field_type)
    if q:
        return q
    if json_field_type.startswith('choices.'):
        return 'string'
    if '.' in json_field_type:
        p, r = json_field_type.split('.', 1)
        p = {'list': '[]', 'dict': 'map[string]'}[p]
        return p + go_field_type(r)
    raise TypeError(f'Unknown JSON field type: {json_field_type}')


class JSONField:

    def __init__(self, line: str, field_to_option_map: dict[str, str], option_map: dict[str, GoOption]) -> None:
        field_def = line.split(':', 1)[0]
        self.required = False
        self.field, self.field_type = field_def.split('/', 1)
        self.go_option_name = field_to_option_map.get(self.field, self.field)
        self.go_option_name = ''.join(x.capitalize() for x in self.go_option_name.split('_'))
        self.omitempty = True
        if fo := option_map.get(self.go_option_name):
            if fo.type in ('int', 'float') and float(fo.default or 0) != 0:
                self.omitempty = False
        self.field_type, self.special_parser = self.field_type.partition('=')[::2]
        if self.field.endswith('+'):
            self.required = True
            self.field = self.field[:-1]
        self.struct_field_name = self.field[0].upper() + self.field[1:]

    def go_declaration(self) -> str:
        omitempty = ',omitempty' if self.omitempty else ''
        return self.struct_field_name + ' ' + go_field_type(self.field_type) + f'`json:"{self.field}{omitempty}"`'


def go_code_for_remote_command(name: str, cmd: RemoteCommand, template: str) -> str:
    template = '\n' + template[len('//go:build exclude'):]
    af: list[str] = []
    a = af.append
    af.extend(cmd.args.as_go_completion_code('ans'))
    od: list[str] = []
    option_map: dict[str, GoOption] = {}
    for o in rc_command_options(name):
        option_map[o.go_var_name] = o
        a(o.as_option('ans'))
        if o.go_var_name in ('NoResponse', 'ResponseTimeout'):
            continue
        od.append(o.struct_declaration())
    jd: list[str] = []
    json_fields = []
    field_types: dict[str, str] = {}
    for line in cmd.protocol_spec.splitlines():
        line = line.strip()
        if ':' not in line:
            continue
        f = JSONField(line, cmd.field_to_option_map or {}, option_map)
        json_fields.append(f)
        field_types[f.field] = f.field_type
        jd.append(f.go_declaration())
    jc: list[str] = []
    handled_fields: set[str] = set()
    jc.extend(cmd.args.as_go_code(name, field_types, handled_fields))

    unhandled = {}
    used_options = set()
    for field in json_fields:
        if field.go_option_name in option_map:
            o = option_map[field.go_option_name]
            used_options.add(field.go_option_name)
            optstring = f'options_{name}.{o.go_var_name}'
            if field.special_parser:
                optstring = f'{field.special_parser}({optstring})'
            if field.field_type == 'str':
                jc.append(f'payload.{field.struct_field_name} = escaped_string({optstring})')
            elif field.field_type == 'list.str':
                jc.append(f'payload.{field.struct_field_name} = escape_list_of_strings({optstring})')
            elif field.field_type == 'dict.str':
                jc.append(f'payload.{field.struct_field_name} = escape_dict_of_strings({optstring})')
            else:
                jc.append(f'payload.{field.struct_field_name} = {optstring}')
        elif field.field in handled_fields:
            pass
        else:
            unhandled[field.field] = field
    for x in tuple(unhandled):
        if x == 'match_window' and 'Match' in option_map and 'Match' not in used_options:
            used_options.add('Match')
            o = option_map['Match']
            field = unhandled[x]
            if field.field_type == 'str':
                jc.append(f'payload.{field.struct_field_name} = escaped_string(options_{name}.{o.go_var_name})')
            else:
                jc.append(f'payload.{field.struct_field_name} = options_{name}.{o.go_var_name}')
            del unhandled[x]
    if unhandled:
        raise SystemExit(f'Cant map fields: {", ".join(unhandled)} for cmd: {name}')
    if name != 'send_text':
        unused_options = set(option_map) - used_options - {'NoResponse', 'ResponseTimeout'}
        if unused_options:
            raise SystemExit(f'Unused options: {", ".join(unused_options)} for command: {name}')

    argspec = cmd.args.spec
    if argspec:
        argspec = ' ' + argspec
    NO_RESPONSE = 'true' if cmd.disallow_responses else 'false'
    ans = replace(
        template,
        CMD_NAME=name, __FILE__=__file__, CLI_NAME=name.replace('_', '-'),
        SHORT_DESC=serialize_as_go_string(cmd.short_desc),
        LONG_DESC=serialize_as_go_string(cmd.desc.strip()),
        IS_ASYNC='true' if cmd.is_asynchronous else 'false',
        NO_RESPONSE_BASE=NO_RESPONSE, ADD_FLAGS_CODE='\n'.join(af),
        WAIT_TIMEOUT=str(cmd.response_timeout),
        OPTIONS_DECLARATION_CODE='\n'.join(od),
        JSON_DECLARATION_CODE='\n'.join(jd),
        JSON_INIT_CODE='\n'.join(jc), ARGSPEC=argspec,
        STRING_RESPONSE_IS_ERROR='true' if cmd.string_return_is_error else 'false',
        STREAM_WANTED='true' if cmd.reads_streaming_data else 'false',
    )
    return ans
# }}}


# kittens {{{


def generate_conf_parser(kitten: str, defn: Definition) -> None:
    with replace_if_needed(f'kittens/{kitten}/conf_generated.go'):
        print(f'package {kitten}')
        print(gen_go_code(defn))


def generate_extra_cli_parser(name: str, spec: str) -> None:
    print('import "github.com/kovidgoyal/kitty/tools/cli"')
    go_opts = tuple(go_options_for_seq(parse_option_spec(spec)[0]))
    print(f'type {name}_options struct ''{')
    for opt in go_opts:
        print(opt.struct_declaration())
    print('}')
    print(f'func parse_{name}_args(args []string) (*{name}_options, []string, error) ''{')
    print(f'root := cli.Command{{Name: `{name}` }}')
    for opt in go_opts:
        print(opt.as_option('root'))
    print('cmd, err := root.ParseArgs(args)')
    print('if err != nil { return nil, nil, err }')
    print(f'var opts {name}_options')
    print('err = cmd.GetOptionValues(&opts)')
    print('if err != nil { return nil, nil, err }')
    print('return &opts, cmd.Args, nil')
    print('}')


def kittens_needing_cli_parsers() -> Iterator[str]:
    for d in os.scandir('kittens'):
        if not d.is_dir(follow_symlinks=False):
            continue
        if os.path.exists(os.path.join(d.path, 'main.py')) and os.path.exists(os.path.join(d.path, 'main.go')):
            with open(os.path.join(d.path, 'main.py')) as f:
                raw = f.read()
            if 'options' in raw:
                yield d.name


def kitten_clis() -> None:
    from kittens.runner import get_kitten_conf_docs, get_kitten_extra_cli_parsers
    for kitten in kittens_needing_cli_parsers():
        defn = get_kitten_conf_docs(kitten)
        if defn is not None:
            generate_conf_parser(kitten, defn)
        ecp = get_kitten_extra_cli_parsers(kitten)
        if ecp:
            for name, spec in ecp.items():
                with replace_if_needed(f'kittens/{kitten}/{name}_cli_generated.go'):
                    print(f'package {kitten}')
                    generate_extra_cli_parser(name, spec)

        with replace_if_needed(f'kittens/{kitten}/cli_generated.go'):
            od = []
            ser = []
            kcd = kitten_cli_docs(kitten)
            has_underscore = '_' in kitten
            print(f'package {kitten}')
            print('import "fmt"')
            print('import "github.com/kovidgoyal/kitty/tools/cli"')
            print('var _ = fmt.Sprintf')
            print('func create_cmd(root *cli.Command, run_func func(*cli.Command, *Options, []string)(int, error)) {')
            print('ans := root.AddSubCommand(&cli.Command{')
            print(f'Name: "{kitten}",')
            if kcd:
                print(f'ShortDescription: "{serialize_as_go_string(kcd["short_desc"])}",')
                if kcd['usage']:
                    print(f'Usage: "[options] {serialize_as_go_string(kcd["usage"])}",')
                print(f'HelpText: "{serialize_as_go_string(kcd["help_text"])}",')
            print('Run: func(cmd *cli.Command, args []string) (int, error) {')
            print('opts := Options{}')
            print('err := cmd.GetOptionValues(&opts)')
            print('if err != nil { return 1, err }')
            print('return run_func(cmd, &opts, args)},')
            if has_underscore:
                print('Hidden: true,')
            print('})')
            gopts, ac = go_options_for_kitten(kitten)
            for opt in gopts:
                print(opt.as_option('ans'))
                od.append(opt.struct_declaration())
                ser.append('\n'.join(opt.as_string_for_commandline()))
            if ac is not None:
                print(''.join(ac.as_go_code('ans.ArgCompleter', ' = ')))
            if not kcd:
                print('specialize_command(ans)')
            if has_underscore:
                print("clone := root.AddClone(ans.Group, ans)")
                print('clone.Hidden = false')
                print(f'clone.Name = "{serialize_as_go_string(kitten.replace("_", "-"))}"')
            print('}')
            print('type Options struct {')
            print('\n'.join(od))
            print('}')
            print('func (opts Options) AsCommandLine() (ans []string) {')
            if ser:
                print('\t sval := ""')
                print('\t _ = sval')
                for x in ser:
                    print('\t' + x)
            print('return')
            print('}')

# }}}


# Constants {{{

def generate_spinners() -> str:
    ans = ['package tui', 'import "time"', 'func NewSpinner(name string) *Spinner {', 'var ans *Spinner', 'switch name {']
    a = ans.append
    for name, spinner in spinners.items():
        a(f'case "{serialize_as_go_string(name)}":')
        a('ans = &Spinner{')
        a(f'Name: "{serialize_as_go_string(name)}",')
        a(f'interval: {spinner["interval"]},')
        frames = ', '.join(f'"{serialize_as_go_string(x)}"' for x in spinner['frames'])
        a(f'frames: []string{{{frames}}},')
        a('}')
    a('}')
    a('if ans != nil {')
    a('ans.interval *= time.Millisecond')
    a('ans.current_frame = -1')
    a('ans.last_change_at = time.Now().Add(-ans.interval)')
    a('}')
    a('return ans}')
    return '\n'.join(ans)


def generate_color_names() -> str:
    selfg = "" if Options.selection_foreground is None else Options.selection_foreground.as_sharp
    selbg = "" if Options.selection_background is None else Options.selection_background.as_sharp
    cursor = "" if Options.cursor is None else Options.cursor.as_sharp
    return 'package style\n\nvar ColorNames = map[string]RGBA{' + '\n'.join(
        f'\t"{name}": RGBA{{ Red:{val.red}, Green:{val.green}, Blue:{val.blue} }},'
        for name, val in color_names.items()
    ) + '\n}' + '\n\nvar ColorTable = [256]uint32{' + ', '.join(
        f'{x}' for x in Options.color_table) + '}\n' + f'''
var DefaultColors = struct {{
Foreground, Background, Cursor, SelectionFg, SelectionBg string
}}{{
Foreground: "{Options.foreground.as_sharp}",
Background: "{Options.background.as_sharp}",
Cursor: "{cursor}",
SelectionFg: "{selfg}",
SelectionBg: "{selbg}",
}}
'''


def load_ref_map() -> dict[str, dict[str, str]]:
    with open('kitty/docs_ref_map_generated.h') as f:
        raw = f.read()
    raw = raw.split('{', 1)[1].split('}', 1)[0]
    data = json.loads(bytes(bytearray(json.loads(f'[{raw}]'))))
    return data  # type: ignore


def generate_constants() -> str:
    from kittens.hints.main import DEFAULT_REGEX
    from kittens.query_terminal.main import all_queries
    from kitty.colors import ThemeFile
    from kitty.config import option_names_for_completion
    from kitty.fast_data_types import FILE_TRANSFER_CODE
    from kitty.options.utils import allowed_shell_integration_values, url_style_map
    from kitty.simple_cli_definitions import CONFIG_HELP
    del sys.modules['kittens.hints.main']
    del sys.modules['kittens.query_terminal.main']
    ref_map = load_ref_map()
    with open('kitty/data-types.h') as dt:
        m = re.search(r'^#define IMAGE_PLACEHOLDER_CHAR (\S+)', dt.read(), flags=re.M)
        assert m is not None
        placeholder_char = int(m.group(1), 16)
    dp = ", ".join(map(lambda x: f'"{serialize_as_go_string(x)}"', kc.default_pager_for_help))
    url_prefixes = ','.join(f'"{x}"' for x in Options.url_prefixes)
    option_names = '`' + '\n'.join(option_names_for_completion()) + '`'
    url_style = {v:k for k, v in url_style_map.items()}[Options.url_style]
    query_names = ', '.join(f'"{name}"' for name in all_queries)
    return f'''\
package kitty

type VersionType struct {{
    Major, Minor, Patch int
}}
const VersionString string = "{kc.str_version}"
const WebsiteBaseURL string = "{kc.website_base_url}"
const FileTransferCode int = {FILE_TRANSFER_CODE}
const ImagePlaceholderChar rune = {placeholder_char}
const SSHControlMasterTemplate = "{kc.ssh_control_master_template}"
const RC_ENCRYPTION_PROTOCOL_VERSION string = "{kc.RC_ENCRYPTION_PROTOCOL_VERSION}"
var VCSRevision string = ""
var IsFrozenBuild string = ""
var IsStandaloneBuild string = ""
const HandleTermiosSignals = {Mode.HANDLE_TERMIOS_SIGNALS.value[0]}
const HintsDefaultRegex = `{DEFAULT_REGEX}`
const DefaultTermName = `{Options.term}`
const DefaultUrlStyle = `{url_style}`
const DefaultUrlColor = `{Options.url_color.as_sharp}`
const ConfigHelp = "{serialize_as_go_string(CONFIG_HELP)}"
var Version VersionType = VersionType{{Major: {kc.version.major}, Minor: {kc.version.minor}, Patch: {kc.version.patch},}}
var DefaultPager []string = []string{{ {dp} }}
var FunctionalKeyNameAliases = map[string]string{serialize_go_dict(functional_key_name_aliases)}
var CharacterKeyNameAliases = map[string]string{serialize_go_dict(character_key_name_aliases)}
var ConfigModMap = map[string]uint16{serialize_go_dict(config_mod_map)}
var RefMap = map[string]string{serialize_go_dict(ref_map['ref'])}
var DocTitleMap = map[string]string{serialize_go_dict(ref_map['doc'])}
var AllowedShellIntegrationValues = []string{{ {str(sorted(allowed_shell_integration_values))[1:-1].replace("'", '"')} }}
var QueryNames = []string{{ {query_names} }}
var CommentedOutDefaultConfig = "{serialize_as_go_string(commented_out_default_config())}"
var KittyConfigDefaults = struct {{
Term, Shell_integration, Select_by_word_characters, Url_excluded_characters, Shell string
Wheel_scroll_multiplier int
Url_prefixes []string
}}{{
Term: "{Options.term}", Shell_integration: "{' '.join(Options.shell_integration)}", Url_prefixes: []string{{ {url_prefixes} }},
Select_by_word_characters: `{Options.select_by_word_characters}`, Wheel_scroll_multiplier: {Options.wheel_scroll_multiplier},
Shell: "{Options.shell}", Url_excluded_characters: "{Options.url_excluded_characters}",
}}
const OptionNames = {option_names}
const DarkThemeFileName = "{ThemeFile.dark.value}"
const LightThemeFileName = "{ThemeFile.light.value}"
const NoPreferenceThemeFileName = "{ThemeFile.no_preference.value}"
'''  # }}}


# Boilerplate {{{

@contextmanager
def replace_if_needed(path: str, show_diff: bool = False) -> Iterator[io.StringIO]:
    buf = io.StringIO()
    origb = sys.stdout
    sys.stdout = buf
    try:
        yield buf
    finally:
        sys.stdout = origb
    orig = ''
    with suppress(FileNotFoundError), open(path) as f:
        orig = f.read()
    new = buf.getvalue()
    new = f'// Code generated by {os.path.basename(__file__)}; DO NOT EDIT.\n\n' + new
    if orig != new:
        changed.append(path)
        if show_diff:
            with open(path + '.new', 'w') as f:
                f.write(new)
                subprocess.run(['diff', '-Naurp', path, f.name], stdout=open('/dev/tty', 'w'))
                os.remove(f.name)
        with open(path, 'w') as f:
            f.write(new)


@lru_cache(maxsize=256)
def rc_command_options(name: str) -> tuple[GoOption, ...]:
    cmd = command_for_name(name)
    return tuple(go_options_for_seq(parse_option_spec(cmd.options_spec or '\n\n')[0]))


def update_at_commands() -> None:
    with open('tools/cmd/at/template.go') as f:
        template = f.read()
    for name in all_command_names():
        cmd = command_for_name(name)
        code = go_code_for_remote_command(name, cmd, template)
        dest = f'tools/cmd/at/cmd_{name}_generated.go'
        with replace_if_needed(dest) as f:
            f.write(code)
    struct_def = []
    opt_def = []
    for o in go_options_for_seq(parse_option_spec(global_options_spec())[0]):
        struct_def.append(o.struct_declaration())
        opt_def.append(o.as_option(depth=1, group="Global options"))
    sdef = '\n'.join(struct_def)
    odef = '\n'.join(opt_def)
    code = f'''
package at
import "github.com/kovidgoyal/kitty/tools/cli"
type rc_global_options struct {{
{sdef}
}}
var rc_global_opts rc_global_options

func add_rc_global_opts(cmd *cli.Command) {{
{odef}
}}
'''
    with replace_if_needed('tools/cmd/at/global_opts_generated.go') as f:
        f.write(code)


def update_completion() -> None:
    with replace_if_needed('tools/cmd/completion/kitty_generated.go'):
        generate_completions_for_kitty()

    with replace_if_needed('tools/cmd/at/kitty_actions_generated.go'):
        print("package at")
        print("const KittyActionNames = `", end='')
        for grp, actions in get_all_actions().items():
            for ac in actions:
                print(ac.name)
        print('`')

    with replace_if_needed('tools/cmd/edit_in_kitty/launch_generated.go'):
        print('package edit_in_kitty')
        print('import "github.com/kovidgoyal/kitty/tools/cli"')
        print('func AddCloneSafeOpts(cmd *cli.Command) {')
        completion_for_launch_wrappers('cmd')
        print(''.join(CompletionSpec.from_string('type:file mime:text/* group:"Text files"').as_go_code('cmd.ArgCompleter', ' = ')))
        print('}')


def define_enum(package_name: str, type_name: str, items: str, underlying_type: str = 'uint') -> str:
    actions = []
    for x in items.splitlines():
        x = x.strip()
        if x:
            actions.append(x)
    ans = [f'package {package_name}', 'import "strconv"', f'type {type_name} {underlying_type}', 'const (']
    stringer = [f'func (ac {type_name}) String() string ''{', 'switch(ac) {']
    for i, ac in enumerate(actions):
        stringer.append(f'case {ac}: return "{ac}"')
        if i == 0:
            ac = ac + f' {type_name} = iota'
        ans.append(ac)
    ans.append(')')
    stringer.append('}\nreturn strconv.Itoa(int(ac)) }')
    return '\n'.join(ans + stringer)


def generate_readline_actions() -> str:
    return define_enum('readline', 'Action', '''\
        ActionNil

        ActionBackspace
        ActionDelete
        ActionMoveToStartOfLine
        ActionMoveToEndOfLine
        ActionMoveToStartOfDocument
        ActionMoveToEndOfDocument
        ActionMoveToEndOfWord
        ActionMoveToStartOfWord
        ActionCursorLeft
        ActionCursorRight
        ActionEndInput
        ActionAcceptInput
        ActionCursorUp
        ActionHistoryPreviousOrCursorUp
        ActionCursorDown
        ActionHistoryNextOrCursorDown
        ActionHistoryNext
        ActionHistoryPrevious
        ActionHistoryFirst
        ActionHistoryLast
        ActionHistoryIncrementalSearchBackwards
        ActionHistoryIncrementalSearchForwards
        ActionTerminateHistorySearchAndApply
        ActionTerminateHistorySearchAndRestore
        ActionClearScreen
        ActionAddText
        ActionAbortCurrentLine

        ActionStartKillActions
        ActionKillToEndOfLine
        ActionKillToStartOfLine
        ActionKillNextWord
        ActionKillPreviousWord
        ActionKillPreviousSpaceDelimitedWord
        ActionEndKillActions
        ActionYank
        ActionPopYank

        ActionNumericArgumentDigit0
        ActionNumericArgumentDigit1
        ActionNumericArgumentDigit2
        ActionNumericArgumentDigit3
        ActionNumericArgumentDigit4
        ActionNumericArgumentDigit5
        ActionNumericArgumentDigit6
        ActionNumericArgumentDigit7
        ActionNumericArgumentDigit8
        ActionNumericArgumentDigit9
        ActionNumericArgumentDigitMinus

        ActionCompleteForward
        ActionCompleteBackward
    ''')


def generate_mimetypes() -> str:
    import mimetypes
    if not mimetypes.inited:
        mimetypes.init()
    ans = ['package utils', 'import "sync"', 'var only_once sync.Once', 'var builtin_types_map map[string]string',
           'func set_builtins() {', 'builtin_types_map = map[string]string{',]
    for k, v in mimetypes.types_map.items():
        ans.append(f'  "{serialize_as_go_string(k)}": "{serialize_as_go_string(v)}",')
    ans.append('}}')
    return '\n'.join(ans)


def generate_textual_mimetypes() -> str:
    ans = ['package utils', 'var KnownTextualMimes = map[string]bool{',]
    for k in text_mimes:
        ans.append(f'  "{serialize_as_go_string(k)}": true,')
    ans.append('}')
    ans.append('var KnownExtensions = map[string]string{')
    for k, v in known_extensions.items():
        ans.append(f'  ".{serialize_as_go_string(k)}": "{serialize_as_go_string(v)}",')
    ans.append('}')
    return '\n'.join(ans)


def write_compressed_data(data: bytes, d: BinaryIO) -> None:
    d.write(struct.pack('<I', len(data)))
    d.write(bz2.compress(data))


def generate_unicode_names(src: TextIO, dest: BinaryIO) -> None:
    num_names, num_of_words = map(int, next(src).split())
    gob = io.BytesIO()
    gob.write(struct.pack('<II', num_names, num_of_words))
    for line in src:
        line = line.strip()
        if line:
            a, aliases = line.partition('\t')[::2]
            cp, name = a.partition(' ')[::2]
            ename = name.encode()
            record = struct.pack('<IH', int(cp), len(ename)) + ename
            if aliases:
                record += aliases.encode()
            gob.write(struct.pack('<H', len(record)) + record)
    write_compressed_data(gob.getvalue(), dest)


def generate_ssh_kitten_data() -> None:
    files = {
        'terminfo/kitty.terminfo', 'terminfo/x/' + Options.term,
    }
    for dirpath, dirnames, filenames in os.walk('shell-integration'):
        for f in filenames:
            path = os.path.join(dirpath, f)
            files.add(path.replace(os.sep, '/'))
    dest = 'tools/tui/shell_integration/data_generated.bin'

    def normalize(t: tarfile.TarInfo) -> tarfile.TarInfo:
        t.uid = t.gid = 0
        t.uname = t.gname = ''
        t.mtime = 0
        return t

    if newer(dest, *files):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w') as tf:
            for f in sorted(files):
                tf.add(f, filter=normalize)
        with open(dest, 'wb') as d:
            write_compressed_data(buf.getvalue(), d)


def start_simdgen() -> 'subprocess.Popen[bytes]':
    return subprocess.Popen(['go', 'run', 'generate.go'], cwd='tools/simdstring', stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main(args: list[str]=sys.argv) -> None:
    simdgen_process = start_simdgen()
    with replace_if_needed('constants_generated.go') as f:
        f.write(generate_constants())
    with replace_if_needed('tools/utils/style/color-names_generated.go') as f:
        f.write(generate_color_names())
    with replace_if_needed('tools/tui/readline/actions_generated.go') as f:
        f.write(generate_readline_actions())
    with replace_if_needed('tools/tui/spinners_generated.go') as f:
        f.write(generate_spinners())
    with replace_if_needed('tools/utils/mimetypes_generated.go') as f:
        f.write(generate_mimetypes())
    with replace_if_needed('tools/utils/mimetypes_textual_generated.go') as f:
        f.write(generate_textual_mimetypes())
    if newer('tools/unicode_names/data_generated.bin', 'tools/unicode_names/names.txt'):
        with open('tools/unicode_names/data_generated.bin', 'wb') as dest, open('tools/unicode_names/names.txt') as src:
            generate_unicode_names(src, dest)
    generate_ssh_kitten_data()

    update_completion()
    update_at_commands()
    kitten_clis()
    stringify()
    make_bitfields()
    print(json.dumps(changed, indent=2))
    stdout, stderr = simdgen_process.communicate()
    if simdgen_process.wait() != 0:
        print('Failed to generate SIMD ASM', file=sys.stderr)
        sys.stdout.buffer.write(stdout)
        sys.stderr.buffer.write(stderr)
        raise SystemExit(simdgen_process.returncode)


if __name__ == '__main__':
    import runpy
    m = runpy.run_path(os.path.dirname(os.path.abspath(__file__)))
    m['main']([sys.executable, 'go-code'])
# }}}
