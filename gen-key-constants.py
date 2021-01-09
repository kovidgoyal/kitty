#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

functional_key_names = (  # {{{
    'escape',
    'enter',
    'tab',
    'backspace',
    'insert',
    'delete',
    'right',
    'left',
    'down',
    'up',
    'page_up',
    'page_down',
    'home',
    'end',
    'caps_lock',
    'scroll_lock',
    'num_lock',
    'print_screen',
    'pause',
    'f1',
    'f2',
    'f3',
    'f4',
    'f5',
    'f6',
    'f7',
    'f8',
    'f9',
    'f10',
    'f11',
    'f12',
    'f13',
    'f14',
    'f15',
    'f16',
    'f17',
    'f18',
    'f19',
    'f20',
    'f21',
    'f22',
    'f23',
    'f24',
    'f25',
    'f26',
    'f27',
    'f28',
    'f29',
    'f30',
    'f31',
    'f32',
    'f33',
    'f34',
    'f35',
    'kp_0',
    'kp_1',
    'kp_2',
    'kp_3',
    'kp_4',
    'kp_5',
    'kp_6',
    'kp_7',
    'kp_8',
    'kp_9',
    'kp_decimal',
    'kp_divide',
    'kp_multiply',
    'kp_subtract',
    'kp_add',
    'kp_enter',
    'kp_equal',
    'left_shift',
    'left_control',
    'left_alt',
    'left_super',
    'right_shift',
    'right_control',
    'right_alt',
    'right_super',
    'media_play',
    'media_pause',
    'media_play_pause',
    'media_reverse',
    'media_stop',
    'media_fast_forward',
    'media_rewind',
    'media_track_next',
    'media_track_previous',
    'media_record',
    'menu',
)  # }}}
start_code = 0xe000
last_code = start_code + len(functional_key_names) - 1
name_to_code = {n: start_code + i for i, n in enumerate(functional_key_names)}


def generate_glfw_header() -> None:
    lines = [
        '/* start functional key names */',
        'typedef enum {',
        f'  GLFW_FKEY_FIRST = 0x{start_code:x},',
    ]
    for name, code in name_to_code.items():
        lines.append(f'  GLFW_FKEY_{name.upper()} = 0x{code:x},')
    lines.append(f'  GLFW_FKEY_LAST = 0x{last_code:x}')
    lines.append('} GLFWFunctionKey;')
    end_marker = '/* end functional key names */'

    with open('glfw/glfw3.h', 'r+') as f:
        text = f.read()
        start = text.index(lines[0])
        end = text.index(end_marker)
        ntext = text[:start] + '\n'.join(lines) + '\n' + text[end:]
        f.seek(0)
        f.truncate()
        f.write(ntext)


def main() -> None:
    generate_glfw_header()


if __name__ == '__main__':
    main()
