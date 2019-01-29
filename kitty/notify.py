#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>


import subprocess

from .constants import is_macos, logo_png_file


if is_macos:
    from .fast_data_types import cocoa_send_notification

    def notify(title, body, timeout=5000, application='kitty', icon=True):
        if icon is True:
            icon = None
        cocoa_send_notification(title, body, icon)
else:
    def notify(title, body, timeout=5000, application='kitty', icon=True):
        cmd = ['notify-send', '-t', str(timeout), '-a', application]
        if icon is True:
            icon = logo_png_file
        if icon:
            cmd.extend(['-i', icon])
        subprocess.Popen(
            cmd + [title, body], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
