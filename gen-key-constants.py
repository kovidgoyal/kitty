#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Dict, List


functional_key_defs = '''\
# kitty                     XKB                         macOS
escape                      Escape                      -
enter                       Return                      -
tab                         Tab                         -
backspace                   BackSpace                   -
insert                      Insert                      -
delete                      Delete                      -
left                        Left                        -
right                       Right                       -
up                          Up                          -
down                        Down                        -
page_up                     Page_Up                     -
page_down                   Page_Down                   -
home                        Home                        -
end                         End                         -
caps_lock                   Caps_Lock                   -
scroll_lock                 Scroll_Lock                 -
num_lock                    Num_Lock                    -
print_screen                Print                       -
pause                       Pause                       -
menu                        Menu                        -
f1                          F1                          -
f2                          F2                          -
f3                          F3                          -
f4                          F4                          -
f5                          F5                          -
f6                          F6                          -
f7                          F7                          -
f8                          F8                          -
f9                          F9                          -
f10                         F10                         -
f11                         F11                         -
f12                         F12                         -
f13                         F13                         -
f14                         F14                         -
f15                         F15                         -
f16                         F16                         -
f17                         F17                         -
f18                         F18                         -
f19                         F19                         -
f20                         F20                         -
f21                         F21                         -
f22                         F22                         -
f23                         F23                         -
f24                         F24                         -
f25                         F25                         -
f26                         F26                         -
f27                         F27                         -
f28                         F28                         -
f29                         F29                         -
f30                         F30                         -
f31                         F31                         -
f32                         F32                         -
f33                         F33                         -
f34                         F34                         -
f35                         F35                         -
kp_0                        KP_0                        -
kp_1                        KP_1                        -
kp_2                        KP_2                        -
kp_3                        KP_3                        -
kp_4                        KP_4                        -
kp_5                        KP_5                        -
kp_6                        KP_6                        -
kp_7                        KP_7                        -
kp_8                        KP_8                        -
kp_9                        KP_9                        -
kp_decimal                  KP_Decimal                  -
kp_divide                   KP_Divide                   -
kp_multiply                 KP_Multiply                 -
kp_subtract                 KP_Subtract                 -
kp_add                      KP_Add                      -
kp_enter                    KP_Enter                    -
kp_equal                    KP_Equal                    -
left_shift                  Shift_L                     -
left_control                Control_L                   -
left_alt                    Alt_L                       -
left_super                  Super_L                     -
right_shift                 Shift_R                     -
right_control               Control_R                   -
right_alt                   Alt_R                       -
right_super                 Super_R                     -
media_play                  XF86AudioPlay               -
media_pause                 XF86AudioPause              -
media_play_pause            -                           -
media_reverse               -                           -
media_stop                  XF86AudioStop               -
media_fast_forward          XF86AudioForward            -
media_rewind                XF86AudioRewind             -
media_track_next            XF86AudioNext               -
media_track_previous        XF86AudioPrev               -
media_record                XF86AudioRecord             -
lower_volume                XF86AudioLowerVolume        -
raise_volume                XF86AudioRaiseVolume        -
mute_volume                 XF86AudioMute               -
'''
functional_key_names: List[str] = []
name_to_code: Dict[str, int] = {}
name_to_xkb: Dict[str, str] = {}
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
last_code = start_code + len(functional_key_names) - 1


def patch_file(path: str, what: str, text: str, start_marker: str = '/* ', end_marker: str = ' */') -> None:
    start_q = f'{start_marker}start {what} (auto generated by gen-key-constants.py do not edit){end_marker}'
    end_q = f'{start_marker}end {what}{end_marker}'

    with open(path, 'r+') as f:
        raw = f.read()
        start = raw.index(start_q)
        end = raw.index(end_q)
        raw = raw[:start] + start_q + '\n' + text + '\n' + raw[end:]
        f.seek(0)
        f.truncate(0)
        f.write(raw)


def generate_glfw_header() -> None:
    lines = [
        'typedef enum {',
        f'  GLFW_FKEY_FIRST = 0x{start_code:x},',
    ]
    for name, code in name_to_code.items():
        lines.append(f'  GLFW_FKEY_{name.upper()} = 0x{code:x},')
    lines.append(f'  GLFW_FKEY_LAST = 0x{last_code:x}')
    lines.append('} GLFWFunctionKey;')
    patch_file('glfw/glfw3.h', 'functional key names', '\n'.join(lines))


def generate_xkb_mapping() -> None:
    lines, rlines = [], []
    for name, xkb in name_to_xkb.items():
        lines.append(f'        case XKB_KEY_{xkb}: return GLFW_FKEY_{name.upper()};')
        rlines.append(f'        case GLFW_FKEY_{name.upper()}: return XKB_KEY_{xkb};')
    patch_file('glfw/xkb_glfw.c', 'xkb to glfw', '\n'.join(lines))
    patch_file('glfw/xkb_glfw.c', 'glfw to xkb', '\n'.join(rlines))


def main() -> None:
    generate_glfw_header()
    generate_xkb_mapping()


if __name__ == '__main__':
    main()
