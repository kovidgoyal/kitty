#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>


import sys
from typing import Any

from kitty.cli import parse_args
from kitty.cli_stub import RCOptions, ResizeCLIOptions
from kitty.constants import version
from kitty.key_encoding import CTRL, EventType, KeyEvent
from kitty.rc.base import command_for_name, parse_subcommand_cli
from kitty.remote_control import encode_send, parse_rc_args
from kitty.utils import ScreenSize

from ..tui.handler import Handler
from ..tui.loop import Loop
from ..tui.operations import styled

global_opts = RCOptions()


class Resize(Handler):

    print_on_fail: str | None = None

    def __init__(self, opts: ResizeCLIOptions):
        self.opts = opts

    def initialize(self) -> None:
        global global_opts
        global_opts = parse_rc_args(['kitty', '@resize-window'])[0]
        self.original_size = self.screen_size
        self.cmd.set_cursor_visible(False)
        self.cmd.set_line_wrapping(False)
        self.draw_screen()

    def do_window_resize(self, is_decrease: bool = False, is_horizontal: bool = True, reset: bool = False, multiplier: int = 1) -> None:
        resize_window = command_for_name('resize_window')
        increment = self.opts.horizontal_increment if is_horizontal else self.opts.vertical_increment
        increment *= multiplier
        if is_decrease:
            increment *= -1
        axis = 'reset' if reset else ('horizontal' if is_horizontal else 'vertical')
        cmdline = [resize_window.name, '--self', f'--increment={increment}', '--axis=' + axis]
        opts, items = parse_subcommand_cli(resize_window, cmdline)
        payload = resize_window.message_to_kitty(global_opts, opts, items)
        send = {'cmd': resize_window.name, 'version': version, 'payload': payload, 'no_response': False}
        self.write(encode_send(send))

    def on_kitty_cmd_response(self, response: dict[str, Any]) -> None:
        if not response.get('ok'):
            err = response['error']
            if response.get('tb'):
                err += '\n' + response['tb']
            self.print_on_fail = err
            self.quit_loop(1)
            return
        res = response.get('data')
        if res:
            self.cmd.bell()

    def on_text(self, text: str, in_bracketed_paste: bool = False) -> None:
        text = text.upper()
        if text in 'WNTSR':
            self.do_window_resize(is_decrease=text in 'NS', is_horizontal=text in 'WN', reset=text == 'R')
        elif text == 'Q':
            self.quit_loop(0)

    def on_key(self, key_event: KeyEvent) -> None:
        if key_event.type is EventType.RELEASE:
            return
        if key_event.matches('esc'):
            self.quit_loop(0)
            return
        if key_event.key in ('w', 'n', 't', 's') and key_event.mods_without_locks == CTRL:
            self.do_window_resize(is_decrease=key_event.key in 'ns', is_horizontal=key_event.key in 'wn', multiplier=2)

    def on_resize(self, new_size: ScreenSize) -> None:
        self.draw_screen()

    def draw_screen(self) -> None:
        self.cmd.clear_screen()
        print = self.print
        print(styled('Resize this window', bold=True, fg='gray', fg_intense=True))
        print()
        print('Press one of the following keys:')
        print('  {}ider'.format(styled('W', fg='green')))
        print('  {}arrower'.format(styled('N', fg='green')))
        print('  {}aller'.format(styled('T', fg='green')))
        print('  {}horter'.format(styled('S', fg='green')))
        print('  {}eset'.format(styled('R', fg='red')))
        print()
        print('Press {} to quit resize mode'.format(styled('Esc', italic=True)))
        print('Hold down {} to double step size'.format(styled('Ctrl', italic=True)))
        print()
        print(styled('Sizes', bold=True, fg='white', fg_intense=True))
        print(f'Original: {self.original_size.rows} rows {self.original_size.cols} cols')
        print('Current:  {} rows {} cols'.format(
            styled(str(self.screen_size.rows), fg='magenta'), styled(str(self.screen_size.cols), fg='magenta')))


OPTIONS = r'''
--horizontal-increment
default=2
type=int
The base horizontal increment.


--vertical-increment
default=2
type=int
The base vertical increment.
'''.format


def main(args: list[str]) -> None:
    msg = 'Resize the current window'
    try:
        cli_opts, items = parse_args(args[1:], OPTIONS, '', msg, 'resize_window', result_class=ResizeCLIOptions)
    except SystemExit as e:
        if e.code != 0:
            print(e.args[0], file=sys.stderr)
            input('Press Enter to quit')
        return

    loop = Loop()
    handler = Resize(cli_opts)
    loop.loop(handler)
    if handler.print_on_fail:
        print(handler.print_on_fail, file=sys.stderr)
        input('Press Enter to quit')
    raise SystemExit(loop.return_code)
