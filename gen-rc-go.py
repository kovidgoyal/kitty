#!./kitty/launcher/kitty +launch
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>

import os
import subprocess
import sys
from typing import Dict, List, Tuple

import kitty.constants as kc
from kitty.cli import OptionDict, OptionSpecSeq, parse_option_spec
from kitty.rc.base import RemoteCommand, all_command_names, command_for_name


def serialize_as_go_string(x: str) -> str:
    return x.replace('\n', '\\n').replace('"', '\\"')


def replace(template: str, **kw: str) -> str:
    for k, v in kw.items():
        template = template.replace(k, v)
    return template


go_type_map = {'bool-set': 'bool', 'int': 'int', 'float': 'float64', '': 'string', 'list': '[]string', 'choices': 'string'}


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
        if self.type == 'bool-set':
            if self.short:
                return f'{base}.BoolP("{self.long}", "{self.short}", false, "{self.usage}")'
            return f'{base}.Bool("{self.long}", false, "{self.usage}")'
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
        if self.type.startswith('bool-'):
            func = 'GetBool'
        elif not self.type or self.type == 'choices':
            func = 'GetString'
        elif self.type == 'int':
            func = 'GetInt'
        elif self.type == 'float':
            func = 'GetFloat64'
        elif self.type == 'list':
            func = 'GetStringArray'
        else:
            raise TypeError(f'Unknown type of CLI option: {self.type} for {self.long}')
        ans = f'{self.go_var_name}_temp, err := {cmd}.Flags().{func}("{self.long}")\n if err != nil {{ return err }}'
        ans += f'\noptions_{self.cmd_name}.{self.go_var_name} = {self.go_var_name}_temp'
        return ans


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
        if o.dest == 'no_response':
            continue
        od.append(f'{o.go_var_name} {o.go_type}')
        ov.append(o.set_flag_value())

    ans = replace(
        template,
        CMD_NAME=name, __FILE__=__file__, CLI_NAME=name.replace('_', '-'),
        SHORT_DESC=serialize_as_go_string(cmd.short_desc),
        LONG_DESC=serialize_as_go_string(cmd.desc.strip()),
        NO_RESPONSE_BASE=NO_RESPONSE_BASE, ADD_FLAGS_CODE='\n'.join(af),
        WAIT_TIMEOUT=str(cmd.response_timeout),
        ALIAS_NORMALIZE_CODE=render_alias_map(alias_map),
        OPTIONS_DECLARATION_CODE='\n'.join(od),
        SET_OPTION_VALUES_CODE='\n'.join(ov),
    )
    return ans


def main() -> None:
    if 'prewarmed' in getattr(sys, 'kitty_run_data'):
        os.environ.pop('KITTY_PREWARM_SOCKET')
        os.execlp(sys.executable, sys.executable, '+launch', __file__, *sys.argv[1:])
    with open('constants_generated.go', 'w') as f:
        dp = ", ".join(map(lambda x: f'"{serialize_as_go_string(x)}"', kc.default_pager_for_help))
        f.write(f'''\
// auto-generated by {__file__} do no edit

package kitty

type VersionType struct {{
    Major, Minor, Patch int
}}
var VersionString string = "{kc.str_version}"
var WebsiteBaseURL string = "{kc.website_base_url}"
var Version VersionType = VersionType{{Major: {kc.version.major}, Minor: {kc.version.minor}, Patch: {kc.version.patch},}}
var DefaultPager []string = []string{{ {dp} }}
var VCSRevision string = ""
var RC_ENCRYPTION_PROTOCOL_VERSION string = "{kc.RC_ENCRYPTION_PROTOCOL_VERSION}"
var IsFrozenBuild bool = false
''')
    with open('tools/cmd/at/template.go') as f:
        template = f.read()
    for name in all_command_names():
        cmd = command_for_name(name)
        opts = parse_option_spec(cmd.options_spec or '\n\n')[0]
        code = build_go_code(name, cmd, opts, template)
        dest = f'tools/cmd/at/{name}_generated.go'
        if os.path.exists(dest):
            os.remove(dest)
        with open(dest, 'w') as f:
            f.write(code)
    cp = subprocess.run('gofmt -s -w tools/cmd/at'.split())
    if cp.returncode != 0:
        raise SystemExit(cp.returncode)


if __name__ == '__main__':
    main()
