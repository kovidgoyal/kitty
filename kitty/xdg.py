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


@run_once
def xdg_config_home() -> str:
    return os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config')


def read_ini_value(path: str, section: str, key: str) -> str:
    # Minimal reader for the INI style files used by GTK and KDE. KDE keys
    # can have flags such as Theme[$e] which are ignored.
    header = f'[{section}]'
    in_section = False
    with suppress(OSError), open(path, errors='replace') as f:
        for line in f:
            line = line.strip()
            if line.startswith('['):
                in_section = line == header
            elif in_section:
                k, sep, v = line.partition('=')
                if sep and k.partition('[')[0].strip() == key:
                    return v.strip().strip('"\'')
    return ''


def icon_theme_from_config_files() -> str:
    cfg = xdg_config_home()
    kde = (os.path.join(cfg, 'kdeglobals'), 'Icons', 'Theme')
    gtk = [(os.path.join(cfg, f'gtk-{v}', 'settings.ini'), 'Settings', 'gtk-icon-theme-name') for v in ('4.0', '3.0')]
    is_kde = 'KDE' in os.environ.get('XDG_CURRENT_DESKTOP', '').upper().split(':')
    for path, section, key in ([kde] + gtk) if is_kde else (gtk + [kde]):
        if ans := read_ini_value(path, section, key):
            return ans
    return ''


def icon_theme_name() -> str:
    # The icon theme from the desktop settings portal, falling back to the
    # KDE and GTK config files. Empty if no theme is configured.
    from .fast_data_types import glfw_get_icon_theme_name

    return glfw_get_icon_theme_name() or icon_theme_from_config_files()


class XDGIconCache:
    def __init__(self) -> None:
        self.existing_icon_names: set[str] = set()
        self.scanned_theme: str | None = None

    def themes_to_search(self, theme: str) -> list[str]:
        # theme and all the themes it inherits from. The inherits of all
        # index.theme files for a theme are used, so that a theme that has
        # no Inherits in one base dir, such as a cursor only default theme
        # in the users home, does not hide the ones in the other base dirs.
        ans: list[str] = []
        queue = [theme]
        while queue:
            t = queue.pop(0)
            if t in ans:
                continue
            ans.append(t)
            for icdir in icon_dirs():
                with suppress(OSError), open(os.path.join(icdir, t, 'index.theme'), errors='replace') as f:
                    if m := re.search(r'^Inherits\s*=\s*(.+?)\s*$', f.read(), re.MULTILINE):
                        queue.extend(x for x in (x.strip() for x in m.group(1).split(',')) if x)
        if 'hicolor' not in ans:
            ans.append('hicolor')
        return ans

    def scan(self, theme: str) -> None:
        self.scanned_theme = theme
        self.existing_icon_names = set()
        for t in self.themes_to_search(theme or 'default'):
            for icdir in icon_dirs():
                self.scan_theme_dir(os.path.join(icdir, t))
        self.scan_theme_dir('/usr/share/pixmaps')

    def scan_theme_dir(self, base: str) -> None:
        with suppress(OSError):
            for dirpath, dirnames, filenames in os.walk(base):
                for q in filenames:
                    icon_name, sep, ext = q.lower().rpartition('.')
                    if sep == '.' and ext in ('svg', 'png', 'xpm'):
                        self.existing_icon_names.add(icon_name)

    def icon_exists(self, name: str, theme: str | None = None) -> bool:
        if theme is None:
            theme = icon_theme_name()
        if theme != self.scanned_theme:
            self.scan(theme)
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
        # Earlier directories take precedence as per the XDG spec
        for d in (xdg_data_home(),) + xdg_data_dirs():
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
        self.lcase_app_name_to_path.setdefault(appname.lower(), path)
        self.lcase_full_name_to_path.setdefault('.'.join(parts).lower(), path)

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
