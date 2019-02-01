#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>

import os
import subprocess
import time
from collections import namedtuple
from urllib.request import urlopen

from .config import atomic_save
from .constants import cache_dir, get_boss, version
from .fast_data_types import add_timer, monitor_pid
from .notify import notify
from .utils import open_url

CHANGELOG_URL = 'https://sw.kovidgoyal.net/kitty/changelog.html'
RELEASED_VERSION_URL = 'https://sw.kovidgoyal.net/kitty/current-version.txt'
CHECK_INTERVAL = 24 * 60 * 60
Notification = namedtuple('Notification', 'version time_of_last_notification count')


def notification_activated():
    open_url(CHANGELOG_URL)


def version_notification_log():
    override = getattr(version_notification_log, 'override', None)
    if override:
        return override
    return os.path.join(cache_dir(), 'new-version-notifications-1.txt')


def notify_new_version(release_version):
    notify(
            'kitty update available!',
            'kitty version {} released'.format('.'.join(map(str, release_version))),
            identifier='new-version',
    )


def get_released_version():
    try:
        raw = urlopen(RELEASED_VERSION_URL).read().decode('utf-8').strip()
    except Exception:
        raw = '0.0.0'
    return raw


def parse_line(line):
    parts = line.split(',')
    version, timestamp, count = parts
    version = tuple(map(int, version.split('.')))
    return Notification(version, float(timestamp), int(count))


def read_cache():
    notified_versions = {}
    try:
        with open(version_notification_log()) as f:
            for line in f:
                try:
                    n = parse_line(line)
                except Exception:
                    continue
                notified_versions[n.version] = n
    except FileNotFoundError:
        pass
    return notified_versions


def already_notified(version):
    notified_versions = read_cache()
    return version in notified_versions


def save_notification(version):
    notified_versions = read_cache()
    if version in notified_versions:
        v = notified_versions[version]
        notified_versions[version] = v._replace(time_of_last_notification=time.time(), count=v.count + 1)
    else:
        notified_versions[version] = Notification(version, time.time(), 1)
    lines = []
    for version in sorted(notified_versions):
        n = notified_versions[version]
        lines.append('{},{},{}'.format(
            '.'.join(map(str, n.version)), n.time_of_last_notification, n.count))
    atomic_save('\n'.join(lines).encode('utf-8'), version_notification_log())


def process_current_release(raw):
    release_version = tuple(map(int, raw.split('.')))
    if release_version > version and not already_notified(release_version):
        save_notification(release_version)
        notify_new_version(release_version)


def update_check(timer_id=None):
    p = subprocess.Popen([
        'kitty', '+runpy', 'from kitty.update_check import *; import time; time.sleep(2); print(get_released_version())'
    ], stdout=subprocess.PIPE)
    monitor_pid(p.pid)
    get_boss().set_update_check_process(p)


def run_update_check(interval=24 * 60 * 60):
    update_check()
    add_timer('update_check', update_check, interval)
