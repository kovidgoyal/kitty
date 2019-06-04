#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import shutil
import subprocess
import sys

from kitty.cli import parse_args
from kitty.constants import is_macos

OPTIONS = r'''
--lines
type=int
default=1
The number of lines shown in the panel (the height of the panel). Applies to horizontal panels.


--columns
type=int
default=20
The number of columns shown in the panel (the width of the panel). Applies to vertical panels.


--edge
choices=top,bottom,left,right
default=top
Which edge of the screen to place the panel on. Note that some window managers
(such as i3) do not support placing docked windows on the left and right edges.


--config -c
type=list
Path to config file to use for kitty when drawing the panel.


--override -o
type=list
Override individual kitty configuration options, can be specified multiple times.
Syntax: :italic:`name=value`. For example: :option:`kitty +kitten panel -o` font_size=20
'''.format


args = None
help_text = 'Use a command line program to draw a GPU accelerated panel on your X11 desktop'
usage = 'program-to-run'


def parse_panel_args(args):
    return parse_args(args, OPTIONS, usage, help_text, 'kitty +kitten panel')


def call_xprop(*cmd, silent=False):
    cmd = ['xprop'] + list(cmd)
    try:
        cp = subprocess.run(cmd, stdout=subprocess.DEVNULL if silent else None)
    except FileNotFoundError:
        raise SystemExit('You must have the xprop program installed')
    if cp.returncode != 0:
        raise SystemExit(cp.returncode)


def create_strut(
    win_id,
    left=0, right=0, top=0, bottom=0, left_start_y=0, left_end_y=0,
    right_start_y=0, right_end_y=0, top_start_x=0, top_end_x=0,
    bottom_start_x=0, bottom_end_x=0
):
    call_xprop(
            '-id',
            str(int(win_id)), '-format', '_NET_WM_STRUT_PARTIAL', '32cccccccccccc',
            '-set', '_NET_WM_STRUT_PARTIAL',
            '{left},{right},{top},{bottom},'
            '{left_start_y},{left_end_y},{right_start_y},{right_end_y},'
            '{top_start_x},{top_end_x},{bottom_start_x},{bottom_end_x}'.format(**locals())
    )


def create_top_strut(win_id, width, height):
    create_strut(win_id, top=height, top_end_x=width)


def create_bottom_strut(win_id, width, height):
    create_strut(win_id, bottom=height, bottom_end_x=width)


def create_left_strut(win_id, width, height):
    create_strut(win_id, left=width, left_end_y=height)


def create_right_strut(win_id, width, height):
    create_strut(win_id, right=width, right_end_y=height)


def setup_x11_window(win_id):
    call_xprop(
            '-id', str(win_id), '-format', '_NET_WM_WINDOW_TYPE', '32a',
            '-set', '_NET_WM_WINDOW_TYPE', '_NET_WM_WINDOW_TYPE_DOCK'
    )
    func = globals()['create_{}_strut'.format(args.edge)]
    func(win_id, initial_window_size_func.width, initial_window_size_func.height)


def initial_window_size_func(opts, *a):
    from kitty.fast_data_types import glfw_primary_monitor_size, set_smallest_allowed_resize

    def initial_window_size(cell_width, cell_height, dpi_x, dpi_y, xscale, yscale):
        monitor_width, monitor_height = glfw_primary_monitor_size()
        if args.edge in {'top', 'bottom'}:
            h = initial_window_size_func.height = cell_height * args.lines + 1
            initial_window_size_func.width = monitor_width
            set_smallest_allowed_resize(100, h)
        else:
            w = initial_window_size_func.width = cell_width * args.columns + 1
            initial_window_size_func.height = monitor_height
            set_smallest_allowed_resize(w, 100)
        return initial_window_size_func.width, initial_window_size_func.height

    return initial_window_size


def main(sys_args):
    global args
    if is_macos or not os.environ.get('DISPLAY'):
        raise SystemExit('Currently the panel kitten is supported only on X11 desktops')
    if not shutil.which('xprop'):
        raise SystemExit('The xprop program is required for the panel kitten')
    args, items = parse_panel_args(sys_args[1:])
    if not items:
        raise SystemExit('You must specify the program to run')
    sys.argv = ['kitty']
    if args.config:
        sys.argv.append('--config={}'.format(args.config))
    for override in args.override:
        sys.argv.append('--override={}'.format(override))
    sys.argv.extend(items)
    from kitty.main import run_app, main
    run_app.cached_values_name = 'panel'
    run_app.first_window_callback = setup_x11_window
    run_app.initial_window_size_func = initial_window_size_func
    main()


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    sys.cli_docs['usage'] = usage
    sys.cli_docs['options'] = OPTIONS
    sys.cli_docs['help_text'] = help_text
