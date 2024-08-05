#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import os
import string
import subprocess
import sys
from pprint import pformat
from typing import Any, Union

if __name__ == '__main__' and not __package__:
    import __main__
    __main__.__package__ = 'gen'
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

functional_key_defs = '''# {{{
# kitty                     XKB                         macVK  macU
escape                      Escape                      0x35   -
enter                       Return                      0x24   NSCarriageReturnCharacter
tab                         Tab                         0x30   NSTabCharacter
backspace                   BackSpace                   0x33   NSBackspaceCharacter
insert                      Insert                      0x72   Insert
delete                      Delete                      0x75   Delete
left                        Left                        0x7B   LeftArrow
right                       Right                       0x7C   RightArrow
up                          Up                          0x7E   UpArrow
down                        Down                        0x7D   DownArrow
page_up                     Page_Up                     0x74   PageUp
page_down                   Page_Down                   0x79   PageDown
home                        Home                        0x73   Home
end                         End                         0x77   End
caps_lock                   Caps_Lock                   0x39   -
scroll_lock                 Scroll_Lock                 -      ScrollLock
num_lock                    Num_Lock                    0x47   ClearLine
print_screen                Print                       -      PrintScreen
pause                       Pause                       -      Pause
menu                        Menu                        0x6E   Menu
f1                          F1                          0x7A   F1
f2                          F2                          0x78   F2
f3                          F3                          0x63   F3
f4                          F4                          0x76   F4
f5                          F5                          0x60   F5
f6                          F6                          0x61   F6
f7                          F7                          0x62   F7
f8                          F8                          0x64   F8
f9                          F9                          0x65   F9
f10                         F10                         0x6D   F10
f11                         F11                         0x67   F11
f12                         F12                         0x6F   F12
f13                         F13                         0x69   F13
f14                         F14                         0x6B   F14
f15                         F15                         0x71   F15
f16                         F16                         0x6A   F16
f17                         F17                         0x40   F17
f18                         F18                         0x4F   F18
f19                         F19                         0x50   F19
f20                         F20                         0x5A   F20
f21                         F21                         -      F21
f22                         F22                         -      F22
f23                         F23                         -      F23
f24                         F24                         -      F24
f25                         F25                         -      F25
f26                         F26                         -      F26
f27                         F27                         -      F27
f28                         F28                         -      F28
f29                         F29                         -      F29
f30                         F30                         -      F30
f31                         F31                         -      F31
f32                         F32                         -      F32
f33                         F33                         -      F33
f34                         F34                         -      F34
f35                         F35                         -      F35
kp_0                        KP_0                        0x52   -
kp_1                        KP_1                        0x53   -
kp_2                        KP_2                        0x54   -
kp_3                        KP_3                        0x55   -
kp_4                        KP_4                        0x56   -
kp_5                        KP_5                        0x57   -
kp_6                        KP_6                        0x58   -
kp_7                        KP_7                        0x59   -
kp_8                        KP_8                        0x5B   -
kp_9                        KP_9                        0x5C   -
kp_decimal                  KP_Decimal                  0x41   -
kp_divide                   KP_Divide                   0x4B   -
kp_multiply                 KP_Multiply                 0x43   -
kp_subtract                 KP_Subtract                 0x4E   -
kp_add                      KP_Add                      0x45   -
kp_enter                    KP_Enter                    0x4C   NSEnterCharacter
kp_equal                    KP_Equal                    0x51   -
kp_separator                KP_Separator                -      -
kp_left                     KP_Left                     -      -
kp_right                    KP_Right                    -      -
kp_up                       KP_Up                       -      -
kp_down                     KP_Down                     -      -
kp_page_up                  KP_Page_Up                  -      -
kp_page_down                KP_Page_Down                -      -
kp_home                     KP_Home                     -      -
kp_end                      KP_End                      -      -
kp_insert                   KP_Insert                   -      -
kp_delete                   KP_Delete                   -      -
kp_begin                    KP_Begin                    -      -
media_play                  XF86AudioPlay               -      -
media_pause                 XF86AudioPause              -      -
media_play_pause            -                           -      -
media_reverse               -                           -      -
media_stop                  XF86AudioStop               -      -
media_fast_forward          XF86AudioForward            -      -
media_rewind                XF86AudioRewind             -      -
media_track_next            XF86AudioNext               -      -
media_track_previous        XF86AudioPrev               -      -
media_record                XF86AudioRecord             -      -
lower_volume                XF86AudioLowerVolume        -      -
raise_volume                XF86AudioRaiseVolume        -      -
mute_volume                 XF86AudioMute               -      -
left_shift                  Shift_L                     0x38   -
left_control                Control_L                   0x3B   -
left_alt                    Alt_L                       0x3A   -
left_super                  Super_L                     0x37   -
left_hyper                  Hyper_L                     -      -
left_meta                   Meta_L                      -      -
right_shift                 Shift_R                     0x3C   -
right_control               Control_R                   0x3E   -
right_alt                   Alt_R                       0x3D   -
right_super                 Super_R                     0x36   -
right_hyper                 Hyper_R                     -      -
right_meta                  Meta_R                      -      -
iso_level3_shift            ISO_Level3_Shift            -      -
iso_level5_shift            ISO_Level5_Shift            -      -
'''  # }}}

shift_map = {x[0]: x[1] for x in '`~ 1! 2@ 3# 4$ 5% 6^ 7& 8* 9( 0) -_ =+ [{ ]} \\| ;: \'" ,< .> /?'.split()}
shift_map.update({x: x.upper() for x in string.ascii_lowercase})
functional_encoding_overrides = {
    'insert': 2, 'delete': 3, 'page_up': 5, 'page_down': 6,
    'home': 7, 'end': 8, 'tab': 9, 'f1': 11, 'f2': 12, 'f3': 13, 'enter': 13, 'f4': 14,
    'f5': 15, 'f6': 17, 'f7': 18, 'f8': 19, 'f9': 20, 'f10': 21,
    'f11': 23, 'f12': 24, 'escape': 27, 'backspace': 127
}
different_trailer_functionals = {
    'up': 'A', 'down': 'B', 'right': 'C', 'left': 'D', 'kp_begin': 'E', 'end': 'F', 'home': 'H',
    'f1': 'P', 'f2': 'Q', 'f3': '~', 'f4': 'S', 'enter': 'u', 'tab': 'u',
    'backspace': 'u', 'escape': 'u'
}

macos_ansi_key_codes = {  # {{{
    0x1D: ord('0'),
    0x12: ord('1'),
    0x13: ord('2'),
    0x14: ord('3'),
    0x15: ord('4'),
    0x17: ord('5'),
    0x16: ord('6'),
    0x1A: ord('7'),
    0x1C: ord('8'),
    0x19: ord('9'),
    0x00: ord('a'),
    0x0B: ord('b'),
    0x08: ord('c'),
    0x02: ord('d'),
    0x0E: ord('e'),
    0x03: ord('f'),
    0x05: ord('g'),
    0x04: ord('h'),
    0x22: ord('i'),
    0x26: ord('j'),
    0x28: ord('k'),
    0x25: ord('l'),
    0x2E: ord('m'),
    0x2D: ord('n'),
    0x1F: ord('o'),
    0x23: ord('p'),
    0x0C: ord('q'),
    0x0F: ord('r'),
    0x01: ord('s'),
    0x11: ord('t'),
    0x20: ord('u'),
    0x09: ord('v'),
    0x0D: ord('w'),
    0x07: ord('x'),
    0x10: ord('y'),
    0x06: ord('z'),

    0x27: ord('\''),
    0x2A: ord('\\'),
    0x2B: ord(','),
    0x18: ord('='),
    0x32: ord('`'),
    0x21: ord('['),
    0x1B: ord('-'),
    0x2F: ord('.'),
    0x1E: ord(']'),
    0x29: ord(';'),
    0x2C: ord('/'),
    0x31: ord(' '),
}  # }}}

functional_key_names: list[str] = []
name_to_code: dict[str, int] = {}
name_to_xkb: dict[str, str] = {}
name_to_vk: dict[str, int] = {}
name_to_macu: dict[str, str] = {}
start_code = 0xe000
for line in functional_key_defs.splitlines():
    line = line.strip()
    if not line or line.startswith('#'):
        continue
    parts = line.split()
    name = parts[0]
    functional_key_names.append(name)
    name_to_code[name] = len(name_to_code) + start_code
    if parts[1] != '-':
        name_to_xkb[name] = parts[1]
    if parts[2] != '-':
        name_to_vk[name] = int(parts[2], 16)
    if parts[3] != '-':
        val = parts[3]
        if not val.startswith('NS'):
            val = f'NS{val}FunctionKey'
        name_to_macu[name] = val
last_code = start_code + len(functional_key_names) - 1
ctrl_mapping = {
    ' ': 0, '@': 0, 'a': 1, 'b': 2, 'c': 3, 'd': 4, 'e': 5, 'f': 6, 'g': 7,
    'h': 8, 'i': 9, 'j': 10, 'k': 11, 'l': 12, 'm': 13, 'n': 14, 'o': 15, 'p': 16,
    'q': 17, 'r': 18, 's': 19, 't': 20, 'u': 21, 'v': 22, 'w': 23, 'x': 24,
    'y': 25, 'z': 26, '[': 27, '\\': 28, ']': 29, '^': 30, '~': 30, '/': 31,
    '_': 31, '?': 127, '0': 48, '1': 49, '2': 0, '3': 27, '4': 28,
    '5': 29, '6': 30, '7': 31, '8': 127, '9': 57
}


def patch_file(path: str, what: str, text: str, start_marker: str = '/* ', end_marker: str = ' */') -> None:
    simple_start_q = f'{start_marker}start {what}{end_marker}'
    start_q = f'{start_marker}start {what} (auto generated by gen-key-constants.py do not edit){end_marker}'
    end_q = f'{start_marker}end {what}{end_marker}'

    with open(path, 'r+') as f:
        raw = f.read()
        try:
            start = raw.index(start_q)
        except ValueError:
            try:
                start = raw.index(simple_start_q)
            except ValueError:
                raise SystemExit(f'Failed to find "{simple_start_q}" in {path}')
        try:
            end = raw.index(end_q)
        except ValueError:
            raise SystemExit(f'Failed to find "{end_q}" in {path}')
        raw = f'{raw[:start]}{start_q}\n{text}\n{raw[end:]}'
        f.seek(0)
        f.truncate(0)
        f.write(raw)
    if path.endswith('.go'):
        subprocess.check_call(['go', 'fmt', path])


def serialize_dict(x: dict[Any, Any]) -> str:
    return pformat(x, indent=4).replace('{', '{\n ', 1)


def serialize_go_dict(x: Union[dict[str, int], dict[int, str], dict[int, int]]) -> str:
    ans = []

    def s(x: Union[int, str]) -> str:
        if isinstance(x, int):
            return str(x)
        return f'"{x}"'

    for k, v in x.items():
        ans.append(f'{s(k)}: {s(v)}')
    return '{' + ', '.join(ans) + '}'


def generate_glfw_header() -> None:
    lines = [
        'typedef enum {',
        f'  GLFW_FKEY_FIRST = 0x{start_code:x}u,',
    ]
    klines, pyi, names, knames = [], [], [], []
    for name, code in name_to_code.items():
        lines.append(f'  GLFW_FKEY_{name.upper()} = 0x{code:x}u,')
        klines.append(f'    ADDC(GLFW_FKEY_{name.upper()});')
        pyi.append(f'GLFW_FKEY_{name.upper()}: int')
        names.append(f'    case GLFW_FKEY_{name.upper()}: return "{name.upper()}";')
        knames.append(f'            case GLFW_FKEY_{name.upper()}: return PyUnicode_FromString("{name}");')
    lines.append(f'  GLFW_FKEY_LAST = 0x{last_code:x}u')
    lines.append('} GLFWFunctionKey;')
    patch_file('glfw/glfw3.h', 'functional key names', '\n'.join(lines))
    patch_file('kitty/glfw.c', 'glfw functional keys', '\n'.join(klines))
    patch_file('kitty/fast_data_types.pyi', 'glfw functional keys', '\n'.join(pyi), start_marker='# ', end_marker='')
    patch_file('glfw/input.c', 'functional key names', '\n'.join(names))
    patch_file('kitty/glfw.c', 'glfw functional key names', '\n'.join(knames))


def generate_xkb_mapping() -> None:
    lines, rlines = [], []
    for name, xkb in name_to_xkb.items():
        lines.append(f'        case XKB_KEY_{xkb}: return GLFW_FKEY_{name.upper()};')
        rlines.append(f'        case GLFW_FKEY_{name.upper()}: return XKB_KEY_{xkb};')
    patch_file('glfw/xkb_glfw.c', 'xkb to glfw', '\n'.join(lines))
    patch_file('glfw/xkb_glfw.c', 'glfw to xkb', '\n'.join(rlines))


def generate_functional_table() -> None:
    lines = [
        '',
        '.. csv-table:: Functional key codes',
        '   :header: "Name", "CSI", "Name", "CSI"',
        ''
    ]
    line_items = []
    enc_lines = []
    tilde_trailers = set()
    for name, code in name_to_code.items():
        if name in functional_encoding_overrides or name in different_trailer_functionals:
            trailer = different_trailer_functionals.get(name, '~')
            if trailer == '~':
                tilde_trailers.add(code)
            code = oc = functional_encoding_overrides.get(name, code)
            code = code if trailer in '~u' else 1
            enc_lines.append((' ' * 8) + f"case GLFW_FKEY_{name.upper()}: S({code}, '{trailer}');")
            if code == 1 and name not in ('up', 'down', 'left', 'right'):
                trailer += f' or {oc} ~'
        else:
            trailer = 'u'
        line_items.append(name.upper())
        line_items.append(f'``{code}\xa0{trailer}``')
    for li in chunks(line_items, 4):
        lines.append('   ' + ', '.join(f'"{x}"' for x in li))
    lines.append('')
    patch_file('docs/keyboard-protocol.rst', 'functional key table', '\n'.join(lines), start_marker='.. ', end_marker='')
    patch_file('kitty/key_encoding.c', 'special numbers', '\n'.join(enc_lines))
    code_to_name = {v: k.upper() for k, v in name_to_code.items()}
    csi_map = {v: name_to_code[k] for k, v in functional_encoding_overrides.items()}
    letter_trailer_codes: dict[str, int] = {
        v: functional_encoding_overrides.get(k, name_to_code.get(k, 0))
        for k, v in different_trailer_functionals.items() if v in 'ABCDEHFPQRSZ'}
    text = f'functional_key_number_to_name_map = {serialize_dict(code_to_name)}'
    text += f'\ncsi_number_to_functional_number_map = {serialize_dict(csi_map)}'
    text += f'\nletter_trailer_to_csi_number_map = {letter_trailer_codes!r}'
    text += f'\ntilde_trailers = {tilde_trailers!r}'
    patch_file('kitty/key_encoding.py', 'csi mapping', text, start_marker='# ', end_marker='')
    text = f'var functional_key_number_to_name_map = map[int]string{serialize_go_dict(code_to_name)}\n'
    text += f'\nvar csi_number_to_functional_number_map = map[int]int{serialize_go_dict(csi_map)}\n'
    text += f'\nvar letter_trailer_to_csi_number_map = map[string]int{serialize_go_dict(letter_trailer_codes)}\n'
    tt = ', '.join(f'{x}: true' for x in tilde_trailers)
    text += '\nvar tilde_trailers = map[int]bool{' + f'{tt}' + '}\n'
    patch_file('tools/tui/loop/key-encoding.go', 'csi mapping', text, start_marker='// ', end_marker='')


def generate_legacy_text_key_maps() -> None:
    tests = []
    tp = ' ' * 8
    shift, alt, ctrl = 1, 2, 4

    def simple(c: str) -> None:
        shifted = shift_map.get(c, c)
        ctrled = chr(ctrl_mapping.get(c, ord(c)))
        call = f'enc(ord({c!r}), shifted_key=ord({shifted!r})'
        for m in range(16):
            if m == 0:
                tests.append(f'{tp}ae({call}), {c!r})')
            elif m == shift:
                tests.append(f'{tp}ae({call}, mods=shift), {shifted!r})')
            elif m == alt:
                tests.append(f'{tp}ae({call}, mods=alt), "\\x1b" + {c!r})')
            elif m == ctrl:
                tests.append(f'{tp}ae({call}, mods=ctrl), {ctrled!r})')
            elif m == shift | alt:
                tests.append(f'{tp}ae({call}, mods=shift | alt), "\\x1b" + {shifted!r})')
            elif m == ctrl | alt:
                tests.append(f'{tp}ae({call}, mods=ctrl | alt), "\\x1b" + {ctrled!r})')

    for k in shift_map:
        simple(k)

    patch_file('kitty_tests/keys.py', 'legacy letter tests', '\n'.join(tests), start_marker='# ', end_marker='')


def chunks(lst: list[Any], n: int) -> Any:
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def generate_ctrl_mapping() -> None:
    lines = [
        '.. csv-table:: Emitted bytes when :kbd:`ctrl` is held down and a key is pressed',
        '   :header: "Key", "Byte", "Key", "Byte", "Key", "Byte"',
        ''
    ]
    items = []
    mi = []
    for k in sorted(ctrl_mapping):
        prefix = '\\' if k == '\\' else ('SPC' if k == ' ' else '')
        items.append(prefix + k)
        val = str(ctrl_mapping[k])
        items.append(val)
        if k in "\\'":
            k = f'\\{k}'
        mi.append(f"        case '{k}': return {val};")

    for line_items in chunks(items, 6):
        lines.append('   ' + ', '.join(f'"{x}"' for x in line_items))
    lines.append('')
    patch_file('docs/keyboard-protocol.rst', 'ctrl mapping', '\n'.join(lines), start_marker='.. ', end_marker='')
    patch_file('kitty/key_encoding.c', 'ctrl mapping', '\n'.join(mi))


def generate_macos_mapping() -> None:
    lines = []
    for k in sorted(macos_ansi_key_codes):
        v = macos_ansi_key_codes[k]
        lines.append(f'        case 0x{k:x}: return 0x{v:x};')
    patch_file('glfw/cocoa_window.m', 'vk to unicode', '\n'.join(lines))
    lines = []
    for name, vk in name_to_vk.items():
        lines.append(f'        case 0x{vk:x}: return GLFW_FKEY_{name.upper()};')
    patch_file('glfw/cocoa_window.m', 'vk to functional', '\n'.join(lines))
    lines = []
    for name, mac in name_to_macu.items():
        lines.append(f'        case {mac}: return GLFW_FKEY_{name.upper()};')
    patch_file('glfw/cocoa_window.m', 'macu to functional', '\n'.join(lines))
    lines = []
    for name, mac in name_to_macu.items():
        lines.append(f'        case GLFW_FKEY_{name.upper()}: return {mac};')
    patch_file('glfw/cocoa_window.m', 'functional to macu', '\n'.join(lines))


def main(args: list[str]=sys.argv) -> None:
    generate_glfw_header()
    generate_xkb_mapping()
    generate_functional_table()
    generate_legacy_text_key_maps()
    generate_ctrl_mapping()
    generate_macos_mapping()


if __name__ == '__main__':
    import runpy
    m = runpy.run_path(os.path.dirname(os.path.abspath(__file__)))
    m['main']([sys.executable, 'key-constants'])
