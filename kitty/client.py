#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

# Replay the log from --dump-commands. To use first run
# kitty --dump-commands > file.txt
# then run
# kitty --replay-commands file.txt
# will replay the commands and pause at the end waiting for user to press enter

import sys
from contextlib import suppress
from typing import Any

CSI = '\x1b['
OSC = '\x1b]'


def write(x: str) -> None:
    sys.stdout.write(x)
    sys.stdout.flush()


def set_title(*args: Any) -> None:
    pass


def set_icon(*args: Any) -> None:
    pass


def screen_bell() -> None:
    pass


def screen_normal_keypad_mode() -> None:
    write('\x1b>')


def screen_alternate_keypad_mode() -> None:
    write('\x1b=')


def screen_cursor_position(y: int, x: int) -> None:
    write(f'{CSI}{y};{x}H')


def screen_cursor_forward(amt: int) -> None:
    write(f'{CSI}{amt}C')


def screen_save_cursor() -> None:
    write('\x1b7')


def screen_restore_cursor() -> None:
    write('\x1b8')


def screen_cursor_back1(amt: int) -> None:
    write(f'{CSI}{amt}D')


def screen_save_modes() -> None:
    write(f'{CSI}?s')


def screen_restore_modes() -> None:
    write(f'{CSI}?r')


def screen_designate_charset(which: int, to: int) -> None:
    w = '()'[int(which)]
    t = chr(int(to))
    write(f'\x1b{w}{t}')


def select_graphic_rendition(*a: int) -> None:
    write(f'{CSI}{";".join(map(str, a))}m')


def deccara(*a: int) -> None:
    write(f'{CSI}{";".join(map(str, a))}$r')


def screen_cursor_to_column(c: int) -> None:
    write(f'{CSI}{c}G')


def screen_cursor_to_line(ln: int) -> None:
    write(f'{CSI}{ln}d')


def screen_set_mode(x: int, private: bool) -> None:
    write(f'{CSI}{"?" if private else ""}{x}h')


def screen_save_mode(x: int, private: bool) -> None:
    write(f'{CSI}{"?" if private else ""}{x}s')


def screen_reset_mode(x: int, private: bool) -> None:
    write(f'{CSI}{"?" if private else ""}{x}l')


def screen_restore_mode(x: int, private: bool) -> None:
    write(f'{CSI}{"?" if private else ""}{x}r')


def screen_set_margins(t: int, b: int) -> None:
    write(f'{CSI}{t};{b}r')


def screen_indexn(n: int) -> None:
    write(f'{CSI}{n}S')


def screen_delete_characters(count: int) -> None:
    write(f'{CSI}{count}P')


def screen_push_colors(which: int) -> None:
    write(f'{CSI}{which}#P')


def screen_pop_colors(which: int) -> None:
    write(f'{CSI}{which}#Q')


def screen_report_colors() -> None:
    write(f'{CSI}#R')


def screen_repeat_character(num: int) -> None:
    write(f'{CSI}{num}b')


def screen_insert_characters(count: int) -> None:
    write(f'{CSI}{count}@')


def screen_scroll(count: int) -> None:
    write(f'{CSI}{count}S')


def screen_erase_in_display(how: int, private: bool) -> None:
    write(f'{CSI}{"?" if private else ""}{how}J')


def screen_erase_in_line(how: int, private: bool) -> None:
    write(f'{CSI}{"?" if private else ""}{how}K')


def screen_delete_lines(num: int) -> None:
    write(f'{CSI}{num}M')


def screen_cursor_up2(count: int) -> None:
    write(f'{CSI}{count}A')


def screen_cursor_down(count: int) -> None:
    write(f'{CSI}{count}B')


def screen_report_key_encoding_flags() -> None:
    write(f'{CSI}?u')


def screen_set_key_encoding_flags(flags: int, how: int) -> None:
    write(f'{CSI}={flags};{how}u')


def screen_push_key_encoding_flags(flags: int) -> None:
    write(f'{CSI}>{flags}u')


def screen_pop_key_encoding_flags(flags: int) -> None:
    write(f'{CSI}<{flags}u')


def screen_carriage_return() -> None:
    write('\r')


def screen_linefeed() -> None:
    write('\n')


def screen_tab() -> None:
    write('\t')


def screen_backspace() -> None:
    write('\x08')


def screen_set_cursor(mode: int, secondary: int) -> None:
    write(f'{CSI}{secondary} q')


def screen_insert_lines(num: int) -> None:
    write(f'{CSI}{num}L')


def draw(*a: str) -> None:
    write(' '.join(a))


def screen_manipulate_title_stack(op: int, which: int) -> None:
    write(f'{CSI}{op};{which}t')


def report_device_attributes(mode: int, char: int) -> None:
    x = CSI
    if char:
        x += chr(char)
    if mode:
        x += str(mode)
    write(f'{CSI}{x}c')


def screen_decsace(mode: int) -> None:
    write(f'{CSI}{mode}*x')


def screen_set_8bit_controls(mode: int) -> None:
    write(f'\x1b {"G" if mode else "F"}')


def write_osc(code: int, string: str = '') -> None:
    if string:
        write(f'{OSC}{code};{string}\x07')
    else:
        write(f'{OSC}{code}\x07')


set_color_table_color = process_cwd_notification = write_osc
clipboard_control_pending: str = ''


def set_dynamic_color(payload: str) -> None:
    code, data = payload.partition(' ')[::2]
    write_osc(int(code), data)


def shell_prompt_marking(payload: str) -> None:
    write_osc(133, payload)


def clipboard_control(payload: str) -> None:
    global clipboard_control_pending
    code, data = payload.split(';', 1)
    if code == '-52':
        if clipboard_control_pending:
            clipboard_control_pending += data.lstrip(';')
        else:
            clipboard_control_pending = payload
        return
    if clipboard_control_pending:
        clipboard_control_pending += data.lstrip(';')
        payload = clipboard_control_pending
        clipboard_control_pending = ''
    write(f'{OSC}{payload}\x07')


def replay(raw: str) -> None:
    specials = {
        'draw', 'set_title', 'set_icon', 'set_dynamic_color', 'set_color_table_color',
        'process_cwd_notification', 'clipboard_control', 'shell_prompt_marking'
    }
    for line in raw.splitlines():
        if line.strip() and not line.startswith('#'):
            cmd, rest = line.partition(' ')[::2]
            if cmd in specials:
                globals()[cmd](rest)
            else:
                r = map(int, rest.split()) if rest else ()
                globals()[cmd](*r)


def main(path: str) -> None:
    with open(path) as f:
        raw = f.read()
    replay(raw)
    with suppress(EOFError, KeyboardInterrupt):
        input()
