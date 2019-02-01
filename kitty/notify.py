#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>

import subprocess

from .constants import is_macos, logo_png_file

if is_macos:
    from .fast_data_types import cocoa_send_notification

    def notify(
        title,
        body,
        timeout=5000,
        application='kitty',
        icon=True,
        identifier=None
    ):
        if icon is True:
            icon = None
        cocoa_send_notification(identifier, title, body, icon)

else:

    # libnotify depends on GTK, so we are not using it, instead
    # use the command line notify-send wrapper it provides
    # May want to just implement this in glfw using DBUS

    def notify(
        title,
        body,
        timeout=-1,
        application='kitty',
        icon=True,
        identifier=None
    ):
        cmd = ['notify-send', '-a', application]
        if timeout > -1:
            cmd.append('-t'), cmd.append(str(timeout))
        if icon is True:
            icon = logo_png_file
        if icon:
            cmd.extend(['-i', icon])
        subprocess.Popen(
            cmd + [title, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
