#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>


import os
import subprocess
import time
from urllib.request import urlopen

from .constants import cache_dir, is_macos, logo_png_file, version
from .utils import open_url

CHANGELOG_URL = 'https://sw.kovidgoyal.net/kitty/changelog.html'
RELEASED_VERSION_URL = 'https://sw.kovidgoyal.net/kitty/current-version.txt'
CHECK_INTERVAL = 24 * 60 * 60


def version_notification_log():
    return os.path.join(cache_dir(), 'new-version-notifications.txt')


def notify_new_version(version):
    notify('kitty update available!', 'kitty version {} released'.format('.'.join(map(str, version))))


def get_released_version():
    try:
        raw = urlopen(RELEASED_VERSION_URL).read().decode('utf-8').strip()
    except Exception:
        raw = '0.0.0'
    return tuple(map(int, raw.split('.')))


notified_versions = set()


def save_notification(version):
    notified_versions.add(version)
    version = '.'.join(map(str, version))
    with open(version_notification_log(), 'a') as f:
        print(version, file=f)


def already_notified(version):
    if not hasattr(already_notified, 'read_cache'):
        already_notified.read_cache = True
        with open(version_notification_log()) as f:
            for line in f:
                notified_versions.add(tuple(map(int, line.strip().split('.'))))
    return tuple(version) in notified_versions


if is_macos:
    from .fast_data_types import cocoa_send_notification, cocoa_run_notification_loop

    def notify(title, body, timeout=5000, application='kitty', icon=True, identifier=None):
        if icon is True:
            icon = None
        cocoa_send_notification(identifier, title, body, icon)

    def notification_activated(notification_identifier):
        open_url(CHANGELOG_URL)

    def do_check():
        new_version = get_released_version()
        if new_version > version and not already_notified(new_version):
            save_notification(new_version)
            notify_new_version(new_version)

    def update_check():
        cocoa_run_notification_loop(notification_activated, do_check, CHECK_INTERVAL)

else:
    def notify(title, body, timeout=5000, application='kitty', icon=True, identifier=None):
        cmd = ['notify-send', '-t', str(timeout), '-a', application]
        if icon is True:
            icon = logo_png_file
        if icon:
            cmd.extend(['-i', icon])
        subprocess.Popen(
            cmd + [title, body], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)

    def update_check():
        while True:
            new_version = get_released_version()
            if new_version > version and not already_notified(new_version):
                save_notification(new_version)
                notify_new_version(new_version)
            time.sleep(CHECK_INTERVAL)
