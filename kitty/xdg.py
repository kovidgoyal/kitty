#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
from contextlib import suppress

from kitty.types import run_once


@run_once
def xdg_data_dirs() -> tuple[str, ...]:
    return tuple(os.environ.get('XDG_DATA_DIRS', '/usr/local/share/:/usr/share/').split(os.pathsep))


@run_once
def xdg_data_home() -> str:
    return os.environ.get('XDG_DATA_HOME', os.path.expanduser('~/.local/share/'))


@run_once
def icon_dirs() -> list[str]:
    ans = []

    def a(x: str) -> None:
        if os.path.isdir(x):
            ans.append(x)

    a(os.path.join(xdg_data_home(), 'icons'))
    a(os.path.expanduser('~/.icons'))
    for x in xdg_data_dirs():
        a(os.path.join(x, 'icons'))
    return ans


class XDGIconCache:
    def __init__(self) -> None:
        self.existing_icon_names: set[str] = set()
        self.scanned = False

    def find_inherited_themes(self, basedir: str, seen_indexes: set[str], themes_to_search: set[str]) -> bool:
        if basedir not in seen_indexes:
            seen_indexes.add(basedir)
            with suppress(OSError), open(os.path.join(basedir, 'index.theme')) as f:
                raw = f.read()
                if m := re.search(r'^Inherits\s*=\s*(.+?)$', raw, re.MULTILINE):
                    for x in m.group(1).split(','):
                        themes_to_search.add(x.strip())
                return True
        return False

    def scan(self) -> None:
        themes_to_search: set[str] = set()
        self.scanned = True
        seen_indexes: set[str] = set()
        for icdir in icon_dirs():
            if self.find_inherited_themes(os.path.join(icdir, 'default'), seen_indexes, themes_to_search):
                break
        themes_to_search.add('hicolor')
        while True:
            before = len(themes_to_search)
            for icdir in icon_dirs():
                for theme in tuple(themes_to_search):
                    self.find_inherited_themes(os.path.join(icdir, theme), seen_indexes, themes_to_search)
            if len(themes_to_search) == before:
                break
        for icdir in icon_dirs():
            for theme in themes_to_search:
                self.scan_theme_dir(os.path.join(icdir, theme))
        self.scan_theme_dir('/usr/share/pixmaps')

    def scan_theme_dir(self, base: str) -> None:
        with suppress(OSError):
            for dirpath, dirnames, filenames in os.walk(base):
                for q in filenames:
                    icon_name, sep, ext = q.lower().rpartition('.')
                    if sep == '.' and ext in ('svg', 'png', 'xpm'):
                        self.existing_icon_names.add(icon_name)

    def icon_exists(self, name: str) -> bool:
        if not self.scanned:
            self.scan()
        return name.lower() in self.existing_icon_names


xdg_icon_cache = XDGIconCache()
icon_exists = xdg_icon_cache.icon_exists


class AppIconCache:
    def __init__(self) -> None:
        self.scanned = False
        self.lcase_app_name_to_path: dict[str, str] = {}
        self.lcase_full_name_to_path: dict[str, str] = {}
        self.icon_name_cache: dict[str, str] = {}

    def scan(self) -> None:
        self.scanned = True
        for d in xdg_data_dirs():
            d = os.path.join(d, 'applications')
            with suppress(OSError):
                for dirpath, dirnames, filenames in os.walk(d):
                    for fname in filenames:
                        if fname.endswith('.desktop'):
                            path = os.path.join(dirpath, fname)
                            self.process_desktop_file(path, os.path.relpath(path, d))

    def process_desktop_file(self, path: str, relpath: str) -> None:
        # file_id = relpath.replace('/', '-')
        bname = os.path.basename(relpath)
        parts = bname.split('.')[:-1]
        appname = parts[-1]
        self.lcase_app_name_to_path[appname.lower()] = path
        self.lcase_full_name_to_path['.'.join(parts).lower()] = path

    def icon_for_appname(self, appname: str) -> str:
        if not self.scanned:
            self.scan()
        q = appname.lower()
        if not appname or q in ('kitty', 'kitten', 'kitten-notify'):
            return ''
        path = self.lcase_full_name_to_path.get(q) or self.lcase_app_name_to_path.get(q)
        if not path:
            return ''
        ans = self.icon_name_cache.get(path)
        if ans is None:
            try:
                ans = self.icon_name_cache[path] = self.icon_name_from_desktop_file(path)
            except OSError:
                ans = self.icon_name_cache[path] = ''

        return ans

    def icon_name_from_desktop_file(self, path: str) -> str:
        with open(path) as f:
            raw = f.read()
        if m := re.search(r'^Icon\s*=\s*(.+?)\s*?$', raw, re.MULTILINE):
            return m.group(1)
        return ''


app_icon_cache = AppIconCache()
icon_for_appname = app_icon_cache.icon_for_appname


def desktop_file_id_for_appname(appname: str) -> str:
    # Return the desktop file id (without the .desktop suffix) of the
    # installed desktop file for appname. Matches either appname.desktop or
    # reverse DNS names such as net.kovidgoyal.appname.desktop. Earlier
    # directories take precedence as per the XDG spec.
    q = appname.lower()
    suffix_match = ''
    for d in (xdg_data_home(),) + xdg_data_dirs():
        d = os.path.join(d, 'applications')
        with suppress(OSError):
            for dirpath, dirnames, filenames in os.walk(d):
                for fname in filenames:
                    if not fname.endswith('.desktop'):
                        continue
                    file_id = os.path.relpath(os.path.join(dirpath, fname), d).replace(os.sep, '-')[: -len('.desktop')]
                    name = fname[: -len('.desktop')].lower()
                    if name == q:
                        return file_id
                    if not suffix_match and name.rpartition('.')[2] == q:
                        suffix_match = file_id
    return suffix_match


@run_once
def kitty_desktop_entry() -> str:
    # The name of the desktop file kitty was launched from, without the
    # .desktop suffix, for use as the desktop-entry hint in notifications.
    from .constants import appname

    if flatpak_id := os.environ.get('FLATPAK_ID'):
        return flatpak_id
    if (gio_df := os.environ.get('GIO_LAUNCHED_DESKTOP_FILE')) and os.environ.get('GIO_LAUNCHED_DESKTOP_FILE_PID') == str(os.getpid()):
        bname = os.path.basename(gio_df)
        if bname.endswith('.desktop'):
            return bname[: -len('.desktop')]
    return desktop_file_id_for_appname(appname)
