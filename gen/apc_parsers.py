#!/usr/bin/env python
# License: GPLv3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import subprocess
import sys
from collections import defaultdict
from typing import Any, DefaultDict, Union

if __name__ == '__main__' and not __package__:
    import __main__
    __main__.__package__ = 'gen'
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KeymapType = dict[str, tuple[str, Union[frozenset[str], str]]]


def resolve_keys(keymap: KeymapType) -> DefaultDict[str, list[str]]:
    ans: DefaultDict[str, list[str]] = defaultdict(list)
    for ch, (attr, atype) in keymap.items():
        if isinstance(atype, str) and atype in ('int', 'uint'):
            q = atype
        else:
            q = 'flag'
        ans[q].append(ch)
    return ans


def enum(keymap: KeymapType) -> str:
    lines = []
    for ch, (attr, atype) in keymap.items():
        lines.append(f"{attr}='{ch}'")
    return '''
    enum KEYS {{
        {}
    }};
    '''.format(',\n'.join(lines))


def parse_key(keymap: KeymapType) -> str:
    lines = []
    for attr, atype in keymap.values():
        vs = atype.upper() if isinstance(atype, str) and atype in ('uint', 'int') else 'FLAG'
        lines.append(f'case {attr}: value_state = {vs}; break;')
    return '        \n'.join(lines)


def parse_flag(keymap: KeymapType, type_map: dict[str, Any], command_class: str) -> str:
    lines = []
    for ch in type_map['flag']:
        attr, allowed_values = keymap[ch]
        q = ' && '.join(f"g.{attr} != '{x}'" for x in sorted(allowed_values))
        lines.append(f'''
            case {attr}: {{
                g.{attr} = parser_buf[pos++];
                if ({q}) {{
                    REPORT_ERROR("Malformed {command_class} control block, unknown flag value for {attr}: 0x%x", g.{attr});
                    return;
                }};
            }}
            break;
        ''')
    return '        \n'.join(lines)


def parse_number(keymap: KeymapType) -> tuple[str, str]:
    int_keys = [f'I({attr})' for attr, atype in keymap.values() if atype == 'int']
    uint_keys = [f'U({attr})' for attr, atype in keymap.values() if atype == 'uint']
    return '; '.join(int_keys), '; '.join(uint_keys)


def cmd_for_report(report_name: str, keymap: KeymapType, type_map: dict[str, Any], payload_allowed: bool, payload_is_base64: bool) -> str:
    def group(atype: str, conv: str) -> tuple[str, str]:
        flag_fmt, flag_attrs = [], []
        cv = {'flag': 'c', 'int': 'i', 'uint': 'I'}[atype]
        for ch in type_map[atype]:
            flag_fmt.append(f's{cv}')
            attr = keymap[ch][0]
            flag_attrs.append(f'"{attr}", {conv}g.{attr}')
        return ' '.join(flag_fmt), ', '.join(flag_attrs)

    flag_fmt, flag_attrs = group('flag', '')
    int_fmt, int_attrs = group('int', '(int)')
    uint_fmt, uint_attrs = group('uint', '(unsigned int)')

    fmt = f'{flag_fmt} {uint_fmt} {int_fmt}'
    if payload_allowed:
        ans = [f'REPORT_VA_COMMAND("K s {{{fmt} ss#}}", self->window_id, "{report_name}",\n']
    else:
        ans = [f'REPORT_VA_COMMAND("K s {{{fmt}}}", self->window_id, "{report_name}",\n']
    if flag_attrs:
        ans.append(f'{flag_attrs},\n')
    if uint_attrs:
        ans.append(f'{uint_attrs},\n')
    if int_attrs:
        ans.append(f'{int_attrs},\n')
    if payload_allowed:
        if payload_is_base64:
            ans.append('"", (char*)parser_buf, g.payload_sz')
        else:
            ans.append('"", (char*)parser_buf + payload_start, g.payload_sz')
    ans.append(');')
    return '\n'.join(ans)


def generate(
    function_name: str,
    callback_name: str,
    report_name: str,
    keymap: KeymapType,
    command_class: str,
    initial_key: str = 'a',
    payload_allowed: bool = True,
    payload_is_base64: bool = True,
    start_parsing_at: int = 1,
    field_sep: str = ',',
) -> str:
    type_map = resolve_keys(keymap)
    keys_enum = enum(keymap)
    handle_key = parse_key(keymap)
    flag_keys = parse_flag(keymap, type_map, command_class)
    int_keys, uint_keys = parse_number(keymap)
    report_cmd = cmd_for_report(report_name, keymap, type_map, payload_allowed, payload_is_base64)
    extra_init = ''
    if payload_allowed:
        payload_after_value = "case ';': state = PAYLOAD; break;"
        payload = ', PAYLOAD'
        if payload_is_base64:
            payload_case = f'''
                case PAYLOAD: {{
                    sz = parser_buf_pos - pos;
                    g.payload_sz = MAX(BUF_EXTRA, sz);
                    if (!base64_decode8(parser_buf + pos, sz, parser_buf, &g.payload_sz)) {{
                        g.payload_sz = MAX(BUF_EXTRA, sz);
                        REPORT_ERROR("Failed to parse {command_class} command payload with error: \
    invalid base64 data in chunk of size: %zu with output buffer size: %zu", sz, g.payload_sz); return; }}
                    pos = parser_buf_pos;
                    }} break;
            '''
            callback = f'{callback_name}(self->screen, &g, parser_buf)'
        else:
            payload_case = '''
                case PAYLOAD: {
                    sz = parser_buf_pos - pos;
                    payload_start = pos;
                    g.payload_sz = sz;
                    pos = parser_buf_pos;
                } break;
            '''
            extra_init = 'size_t payload_start = 0;'
            callback = f'{callback_name}(self->screen, &g, parser_buf + payload_start)'

    else:
        payload_after_value = payload = payload_case = ''
        callback = f'{callback_name}(self->screen, &g)'

    return f'''
    #include "base64.h"

static inline void
{function_name}(PS *self, uint8_t *parser_buf, const size_t parser_buf_pos) {{
    unsigned int pos = {start_parsing_at};
    {extra_init}
    enum PARSER_STATES {{ KEY, EQUAL, UINT, INT, FLAG, AFTER_VALUE {payload} }};
    enum PARSER_STATES state = KEY, value_state = FLAG;
    {command_class} g = {{0}};
    unsigned int i, code;
    uint64_t lcode; int64_t accumulator;
    bool is_negative; (void)is_negative;
    size_t sz;
    {keys_enum}
    enum KEYS key = '{initial_key}';
    if (parser_buf[pos] == ';') state = AFTER_VALUE;

    while (pos < parser_buf_pos) {{
        switch(state) {{
            case KEY:
                key = parser_buf[pos++];
                state = EQUAL;
                switch(key) {{
                    {handle_key}
                    default:
                        REPORT_ERROR("Malformed {command_class} control block, invalid key character: 0x%x", key);
                        return;
                }}
                break;

            case EQUAL:
                if (parser_buf[pos++] != '=') {{
                    REPORT_ERROR("Malformed {command_class} control block, no = after key, found: 0x%x instead", parser_buf[pos-1]);
                    return;
                }}
                state = value_state;
                break;

            case FLAG:
                switch(key) {{
                    {flag_keys}
                    default:
                        break;
                }}
                state = AFTER_VALUE;
                break;

            case INT:
#define READ_UINT \\
                for (i = pos, accumulator=0; i < MIN(parser_buf_pos, pos + 10); i++) {{ \\
                    int64_t n = parser_buf[i] - '0'; if (n < 0 || n > 9) break; \\
                    accumulator += n * digit_multipliers[i - pos]; \\
                }} \\
                if (i == pos) {{ REPORT_ERROR("Malformed {command_class} control block, expecting an integer value for key: %c", key & 0xFF); return; }} \\
                lcode = accumulator / digit_multipliers[i - pos - 1]; pos = i; \\
                if (lcode > UINT32_MAX) {{ REPORT_ERROR("Malformed {command_class} control block, number is too large"); return; }} \\
                code = lcode;

                is_negative = false;
                if(parser_buf[pos] == '-') {{ is_negative = true; pos++; }}
#define I(x) case x: g.x = is_negative ? 0 - (int32_t)code : (int32_t)code; break
                READ_UINT;
                switch(key) {{
                    {int_keys};
                    default: break;
                }}
                state = AFTER_VALUE;
                break;
#undef I
            case UINT:
                READ_UINT;
#define U(x) case x: g.x = code; break
                switch(key) {{
                    {uint_keys};
                    default: break;
                }}
                state = AFTER_VALUE;
                break;
#undef U
#undef READ_UINT

            case AFTER_VALUE:
                switch (parser_buf[pos++]) {{
                    default:
                        REPORT_ERROR("Malformed {command_class} control block, expecting a {field_sep} or semi-colon after a value, found: 0x%x",
                                     parser_buf[pos - 1]);
                        return;
                    case '{field_sep}':
                        state = KEY;
                        break;
                    {payload_after_value}
                }}
                break;

            {payload_case}

        }} // end switch
    }} // end while

    switch(state) {{
        case EQUAL:
            REPORT_ERROR("Malformed {command_class} control block, no = after key"); return;
        case INT:
        case UINT:
            REPORT_ERROR("Malformed {command_class} control block, expecting an integer value"); return;
        case FLAG:
            REPORT_ERROR("Malformed {command_class} control block, expecting a flag value"); return;
        default:
            break;
    }}

    {report_cmd}

    {callback};
}}
    '''


def write_header(text: str, path: str) -> None:
    with open(path, 'w') as f:
        print(f'// This file is generated by {os.path.basename(__file__)} do not edit!', file=f, end='\n\n')
        print('#pragma once', file=f)
        print(text, file=f)
    subprocess.check_call(['clang-format', '-i', path])


def parsers() -> None:
    flag = frozenset
    keymap: KeymapType = {
        'a': ('action', flag('tTqpdfac')),
        'd': ('delete_action', flag('aAiIcCfFnNpPqQrRxXyYzZ')),
        't': ('transmission_type', flag('dfts')),
        'o': ('compressed', flag('z')),
        'f': ('format', 'uint'),
        'm': ('more', 'uint'),
        'i': ('id', 'uint'),
        'I': ('image_number', 'uint'),
        'p': ('placement_id', 'uint'),
        'q': ('quiet', 'uint'),
        'w': ('width', 'uint'),
        'h': ('height', 'uint'),
        'x': ('x_offset', 'uint'),
        'y': ('y_offset', 'uint'),
        'v': ('data_height', 'uint'),
        's': ('data_width', 'uint'),
        'S': ('data_sz', 'uint'),
        'O': ('data_offset', 'uint'),
        'c': ('num_cells', 'uint'),
        'r': ('num_lines', 'uint'),
        'X': ('cell_x_offset', 'uint'),
        'Y': ('cell_y_offset', 'uint'),
        'z': ('z_index', 'int'),
        'C': ('cursor_movement', 'uint'),
        'U': ('unicode_placement', 'uint'),
        'P': ('parent_id', 'uint'),
        'Q': ('parent_placement_id', 'uint'),
        'H': ('offset_from_parent_x', 'int'),
        'V': ('offset_from_parent_y', 'int'),
    }
    text = generate('parse_graphics_code', 'screen_handle_graphics_command', 'graphics_command', keymap, 'GraphicsCommand')
    write_header(text, 'kitty/parse-graphics-command.h')
    keymap = {
        'w': ('width', 'uint'),
        's': ('scale', 'uint'),
        'n': ('subscale_n', 'uint'),
        'd': ('subscale_d', 'uint'),
        'v': ('vertical_align', 'uint'),
        'h': ('horizontal_align', 'uint'),
    }
    text = generate(
        'parse_multicell_code', 'screen_handle_multicell_command', 'multicell_command', keymap, 'MultiCellCommand',
        payload_is_base64=False, start_parsing_at=0, field_sep=':')
    write_header(text, 'kitty/parse-multicell-command.h')


def main(args: list[str]=sys.argv) -> None:
    parsers()


if __name__ == '__main__':
    import runpy
    m = runpy.run_path(os.path.dirname(os.path.abspath(__file__)))
    m['main']([sys.executable, 'apc-parsers'])
