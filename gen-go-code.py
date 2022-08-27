#!./kitty/launcher/kitty +launch
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>

import json
import io
import os
from contextlib import contextmanager, suppress
from typing import Dict, Iterator, List, Tuple, Union

import kitty.constants as kc
from kittens.tui.operations import Mode
from kitty.rgb import color_names
from kitty.cli import OptionDict, OptionSpecSeq, parse_option_spec
from kitty.options.types import Options
from kitty.key_encoding import config_mod_map
from kitty.key_names import (
    character_key_name_aliases, functional_key_name_aliases
)
from kitty.rc.base import RemoteCommand, all_command_names, command_for_name


changed: List[str] = []


# Utils {{{
def serialize_as_go_string(x: str) -> str:
    return x.replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"')


def serialize_go_dict(x: Union[Dict[str, int], Dict[int, str], Dict[int, int], Dict[str, str]]) -> str:
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


go_type_map = {'bool-set': 'bool', 'bool-reset': 'bool', 'int': 'int', 'float': 'float64', '': 'string', 'list': '[]string', 'choices': 'string'}
go_getter_map = {
    'bool-set': 'GetBool', 'bool-reset': 'GetBool', 'int': 'GetInt', 'float': 'GetFloat64', '': 'GetString',
    'list': 'GetStringArray', 'choices': 'GetString'
}


class Option:

    def __init__(self, cmd_name: str, x: OptionDict) -> None:
        self.cmd_name = cmd_name
        flags = sorted(x['aliases'], key=len)
        short = ''
        self.aliases = []
        if len(flags) > 1 and not flags[0].startswith("--"):
            short = flags[0][1:]
            del flags[0]
        self.short, self.long = short, x['name'].replace('_', '-')
        for f in flags:
            q = f[2:]
            if q != self.long:
                self.aliases.append(q)
        self.usage = serialize_as_go_string(x['help'].strip())
        self.type = x['type']
        self.dest = x['dest']
        self.default = x['default']
        self.obj_dict = x
        self.go_type = go_type_map[self.type]
        self.go_var_name = self.long.replace('-', '_')
        if self.go_var_name == 'type':
            self.go_var_name += '_'

    def to_flag_definition(self, base: str = 'ans.Flags()') -> str:
        if self.type.startswith('bool-'):
            defval = 'false' if self.type == 'bool-set' else 'true'
            if self.short:
                return f'{base}.BoolP("{self.long}", "{self.short}", {defval}, "{self.usage}")'
            return f'{base}.Bool("{self.long}", {defval}, "{self.usage}")'
        elif not self.type:
            defval = f'''"{serialize_as_go_string(self.default or '')}"'''
            if self.short:
                return f'{base}.StringP("{self.long}", "{self.short}", {defval}, "{self.usage}")'
            return f'{base}.String("{self.long}", {defval}, "{self.usage}")'
        elif self.type == 'int':
            if self.short:
                return f'{base}.IntP("{self.long}", "{self.short}", {self.default or 0}, "{self.usage}")'
            return f'{base}.Int("{self.long}", {self.default or 0}, "{self.usage}")'
        elif self.type == 'float':
            if self.short:
                return f'{base}.Float64P("{self.long}", "{self.short}", {self.default or 0}, "{self.usage}")'
            return f'{base}.Float64("{self.long}", {self.default or 0}, "{self.usage}")'
        elif self.type == 'list':
            defval = f'[]string{{"{serialize_as_go_string(self.default)}"}}' if self.default else '[]string{}'
            if self.short:
                return f'{base}.StringArrayP("{self.long}", "{self.short}", {defval}, "{self.usage}")'
            return f'{base}.StringArray("{self.long}", {defval}, "{self.usage}")'
        elif self.type == 'choices':
            choices = sorted(self.obj_dict['choices'])
            choices.remove(self.default or '')
            choices.insert(0, self.default or '')
            cx = ', '.join(f'"{serialize_as_go_string(x)}"' for x in choices)
            if self.short:
                return f'cli.ChoicesP({base}, "{self.long}", "{self.short}", "{self.usage}", {cx})'
            return f'cli.Choices({base}, "{self.long}", "{self.usage}", {cx})'
        else:
            raise TypeError(f'Unknown type of CLI option: {self.type} for {self.long}')

    def set_flag_value(self, cmd: str = 'cmd') -> str:
        func = go_getter_map[self.type]
        ans = f'{self.go_var_name}_temp, err := {cmd}.Flags().{func}("{self.long}")\n if err != nil {{ return err }}'
        ans += f'\noptions_{self.cmd_name}.{self.go_var_name} = {self.go_var_name}_temp'
        return ans


json_field_types: Dict[str, str] = {
    'bool': 'bool', 'str': 'string', 'list.str': '[]string', 'dict.str': 'map[string]string', 'float': 'float64', 'int': 'int',
    'scroll_amount': '[2]interface{}', 'spacing': 'interface{}', 'colors': 'interface{}',
}


def go_field_type(json_field_type: str) -> str:
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

    def __init__(self, line: str) -> None:
        field_def = line.split(':', 1)[0]
        self.required = False
        self.field, self.field_type = field_def.split('/', 1)
        if self.field.endswith('+'):
            self.required = True
            self.field = self.field[:-1]
        self.struct_field_name = self.field[0].upper() + self.field[1:]

    def go_declaration(self) -> str:
        return self.struct_field_name + ' ' + go_field_type(self.field_type) + f'`json:"{self.field},omitempty"`'


def render_alias_map(alias_map: Dict[str, Tuple[str, ...]]) -> str:
    if not alias_map:
        return ''
    amap = 'switch name {\n'
    for name, aliases in alias_map.items():
        for alias in aliases:
            amap += f'\ncase "{alias}":\nname = "{name}"\n'
    amap += '}'
    return amap


def build_go_code(name: str, cmd: RemoteCommand, seq: OptionSpecSeq, template: str) -> str:
    template = '\n' + template[len('//go:build exclude'):]
    NO_RESPONSE_BASE = 'true' if cmd.no_response else 'false'
    af: List[str] = []
    a = af.append
    alias_map = {}
    od: List[str] = []
    ov: List[str] = []
    for x in seq:
        if isinstance(x, str):
            continue
        o = Option(name, x)
        if o.aliases:
            alias_map[o.long] = tuple(o.aliases)
        a(o.to_flag_definition())
        if o.dest in ('no_response', 'response_timeout'):
            continue
        od.append(f'{o.go_var_name} {o.go_type}')
        ov.append(o.set_flag_value())
    jd: List[str] = []
    for line in cmd.protocol_spec.splitlines():
        line = line.strip()
        if ':' not in line:
            continue
        f = JSONField(line)
        jd.append(f.go_declaration())

    ans = replace(
        template,
        CMD_NAME=name, __FILE__=__file__, CLI_NAME=name.replace('_', '-'),
        SHORT_DESC=serialize_as_go_string(cmd.short_desc),
        LONG_DESC=serialize_as_go_string(cmd.desc.strip()),
        IS_ASYNC='true' if cmd.is_asynchronous else 'false',
        NO_RESPONSE_BASE=NO_RESPONSE_BASE, ADD_FLAGS_CODE='\n'.join(af),
        WAIT_TIMEOUT=str(cmd.response_timeout),
        ALIAS_NORMALIZE_CODE=render_alias_map(alias_map),
        OPTIONS_DECLARATION_CODE='\n'.join(od),
        SET_OPTION_VALUES_CODE='\n'.join(ov),
        JSON_DECLARATION_CODE='\n'.join(jd),
        STRING_RESPONSE_IS_ERROR='true' if cmd.string_return_is_error else 'false',
    )
    return ans


# Constants {{{
def generate_color_names() -> str:
    return 'package style\n\nvar ColorNames = map[string]RGBA{' + '\n'.join(
        f'\t"{name}": RGBA{{ Red:{val.red}, Green:{val.green}, Blue:{val.blue} }},'
        for name, val in color_names.items()
    ) + '\n}' + '\n\nvar ColorTable = [256]uint32{' + ', '.join(
        f'{x}' for x in Options.color_table) + '}\n'


def load_ref_map() -> Dict[str, Dict[str, str]]:
    with open('kitty/docs_ref_map_generated.h') as f:
        raw = f.read()
    raw = raw.split('{', 1)[1].split('}', 1)[0]
    data = json.loads(bytes(bytearray(json.loads(f'[{raw}]'))))
    return data  # type: ignore


def generate_constants() -> str:
    ref_map = load_ref_map()
    dp = ", ".join(map(lambda x: f'"{serialize_as_go_string(x)}"', kc.default_pager_for_help))
    return f'''\
// auto-generated by {__file__} do no edit

package kitty

type VersionType struct {{
    Major, Minor, Patch int
}}
const VersionString string = "{kc.str_version}"
const WebsiteBaseURL string = "{kc.website_base_url}"
const VCSRevision string = ""
const RC_ENCRYPTION_PROTOCOL_VERSION string = "{kc.RC_ENCRYPTION_PROTOCOL_VERSION}"
const IsFrozenBuild bool = false
const HandleTermiosSignals = {Mode.HANDLE_TERMIOS_SIGNALS.value[0]}
var Version VersionType = VersionType{{Major: {kc.version.major}, Minor: {kc.version.minor}, Patch: {kc.version.patch},}}
var DefaultPager []string = []string{{ {dp} }}
var FunctionalKeyNameAliases = map[string]string{serialize_go_dict(functional_key_name_aliases)}
var CharacterKeyNameAliases = map[string]string{serialize_go_dict(character_key_name_aliases)}
var ConfigModMap = map[string]uint16{serialize_go_dict(config_mod_map)}
var RefMap = map[string]string{serialize_go_dict(ref_map['ref'])}
var DocTitleMap = map[string]string{serialize_go_dict(ref_map['doc'])}
'''  # }}}


# Boilerplate {{{

@contextmanager
def replace_if_needed(path: str) -> Iterator[io.StringIO]:
    buf = io.StringIO()
    yield buf
    orig = ''
    with suppress(FileNotFoundError), open(path, 'r') as f:
        orig = f.read()
    new = buf.getvalue()
    if orig != new:
        changed.append(path)
        with open(path, 'w') as f:
            f.write(new)


def update_at_commands() -> None:
    with open('tools/cmd/at/template.go') as f:
        template = f.read()
    for name in all_command_names():
        cmd = command_for_name(name)
        opts = parse_option_spec(cmd.options_spec or '\n\n')[0]
        code = build_go_code(name, cmd, opts, template)
        dest = f'tools/cmd/at/cmd_{name}_generated.go'
        if os.path.exists(dest):
            os.remove(dest)
        with open(dest, 'w') as f:
            f.write(code)


def main() -> None:
    with replace_if_needed('constants_generated.go') as f:
        f.write(generate_constants())
    with replace_if_needed('tools/utils/style/color-names_generated.go') as f:
        f.write(generate_color_names())
    update_at_commands()
    print(json.dumps(changed, indent=2))


if __name__ == '__main__':
    main()  # }}}
