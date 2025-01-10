#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import os
import stat
from collections.abc import Generator
from contextlib import suppress

DEFAULT_DIRCOLORS = r"""# {{{
# Configuration file for dircolors, a utility to help you set the
# LS_COLORS environment variable used by GNU ls with the --color option.
# Copyright (C) 1996-2019 Free Software Foundation, Inc.
# Copying and distribution of this file, with or without modification,
# are permitted provided the copyright notice and this notice are preserved.
# The keywords COLOR, OPTIONS, and EIGHTBIT (honored by the
# slackware version of dircolors) are recognized but ignored.
# Below are TERM entries, which can be a glob patterns, to match
# against the TERM environment variable to determine if it is colorizable.
TERM Eterm
TERM ansi
TERM *color*
TERM con[0-9]*x[0-9]*
TERM cons25
TERM console
TERM cygwin
TERM dtterm
TERM gnome
TERM hurd
TERM jfbterm
TERM konsole
TERM kterm
TERM linux
TERM linux-c
TERM mlterm
TERM putty
TERM rxvt*
TERM screen*
TERM st
TERM terminator
TERM tmux*
TERM vt100
TERM xterm*
# Below are the color init strings for the basic file types.
# One can use codes for 256 or more colors supported by modern terminals.
# The default color codes use the capabilities of an 8 color terminal
# with some additional attributes as per the following codes:
# Attribute codes:
# 00=none 01=bold 04=underscore 05=blink 07=reverse 08=concealed
# Text color codes:
# 30=black 31=red 32=green 33=yellow 34=blue 35=magenta 36=cyan 37=white
# Background color codes:
# 40=black 41=red 42=green 43=yellow 44=blue 45=magenta 46=cyan 47=white
#NORMAL 00 # no color code at all
#FILE 00 # regular file: use no color at all
RESET 0 # reset to "normal" color
DIR 01;34 # directory
LINK 01;36 # symbolic link. (If you set this to 'target' instead of a
 # numerical value, the color is as for the file pointed to.)
MULTIHARDLINK 00 # regular file with more than one link
FIFO 40;33 # pipe
SOCK 01;35 # socket
DOOR 01;35 # door
BLK 40;33;01 # block device driver
CHR 40;33;01 # character device driver
ORPHAN 40;31;01 # symlink to nonexistent file, or non-stat'able file ...
MISSING 00 # ... and the files they point to
SETUID 37;41 # file that is setuid (u+s)
SETGID 30;43 # file that is setgid (g+s)
CAPABILITY 30;41 # file with capability
STICKY_OTHER_WRITABLE 30;42 # dir that is sticky and other-writable (+t,o+w)
OTHER_WRITABLE 34;42 # dir that is other-writable (o+w) and not sticky
STICKY 37;44 # dir with the sticky bit set (+t) and not other-writable
# This is for files with execute permission:
EXEC 01;32
# List any file extensions like '.gz' or '.tar' that you would like ls
# to colorize below. Put the extension, a space, and the color init string.
# (and any comments you want to add after a '#')
# If you use DOS-style suffixes, you may want to uncomment the following:
#.cmd 01;32 # executables (bright green)
#.exe 01;32
#.com 01;32
#.btm 01;32
#.bat 01;32
# Or if you want to colorize scripts even if they do not have the
# executable bit actually set.
#.sh 01;32
#.csh 01;32
 # archives or compressed (bright red)
.tar 01;31
.tgz 01;31
.arc 01;31
.arj 01;31
.taz 01;31
.lha 01;31
.lz4 01;31
.lzh 01;31
.lzma 01;31
.tlz 01;31
.txz 01;31
.tzo 01;31
.t7z 01;31
.zip 01;31
.z 01;31
.dz 01;31
.gz 01;31
.lrz 01;31
.lz 01;31
.lzo 01;31
.xz 01;31
.zst 01;31
.tzst 01;31
.bz2 01;31
.bz 01;31
.tbz 01;31
.tbz2 01;31
.tz 01;31
.deb 01;31
.rpm 01;31
.jar 01;31
.war 01;31
.ear 01;31
.sar 01;31
.rar 01;31
.alz 01;31
.ace 01;31
.zoo 01;31
.cpio 01;31
.7z 01;31
.rz 01;31
.cab 01;31
.wim 01;31
.swm 01;31
.dwm 01;31
.esd 01;31
# image formats
.jpg 01;35
.jpeg 01;35
.mjpg 01;35
.mjpeg 01;35
.gif 01;35
.bmp 01;35
.pbm 01;35
.pgm 01;35
.ppm 01;35
.tga 01;35
.xbm 01;35
.xpm 01;35
.tif 01;35
.tiff 01;35
.png 01;35
.svg 01;35
.svgz 01;35
.mng 01;35
.pcx 01;35
.mov 01;35
.mpg 01;35
.mpeg 01;35
.m2v 01;35
.mkv 01;35
.webm 01;35
.ogm 01;35
.mp4 01;35
.m4v 01;35
.mp4v 01;35
.vob 01;35
.qt 01;35
.nuv 01;35
.wmv 01;35
.asf 01;35
.rm 01;35
.rmvb 01;35
.flc 01;35
.avi 01;35
.fli 01;35
.flv 01;35
.gl 01;35
.dl 01;35
.xcf 01;35
.xwd 01;35
.yuv 01;35
.cgm 01;35
.emf 01;35
# https://wiki.xiph.org/MIME_Types_and_File_Extensions
.ogv 01;35
.ogx 01;35
# audio formats
.aac 00;36
.au 00;36
.flac 00;36
.m4a 00;36
.mid 00;36
.midi 00;36
.mka 00;36
.mp3 00;36
.mpc 00;36
.ogg 00;36
.ra 00;36
.wav 00;36
# https://wiki.xiph.org/MIME_Types_and_File_Extensions
.oga 00;36
.opus 00;36
.spx 00;36
.xspf 00;36
"""  # }}}

# special file?
special_types = (
    (stat.S_IFLNK,  'ln'),  # symlink
    (stat.S_IFIFO,  'pi'),  # pipe (FIFO)
    (stat.S_IFSOCK, 'so'),  # socket
    (stat.S_IFBLK,  'bd'),  # block device
    (stat.S_IFCHR,  'cd'),  # character device
    (stat.S_ISUID,  'su'),  # setuid
    (stat.S_ISGID,  'sg'),  # setgid
)

CODE_MAP = {
    'RESET': 'rs',
    'DIR': 'di',
    'LINK': 'ln',
    'MULTIHARDLINK': 'mh',
    'FIFO': 'pi',
    'SOCK': 'so',
    'DOOR': 'do',
    'BLK': 'bd',
    'CHR': 'cd',
    'ORPHAN': 'or',
    'MISSING': 'mi',
    'SETUID': 'su',
    'SETGID': 'sg',
    'CAPABILITY': 'ca',
    'STICKY_OTHER_WRITABLE': 'tw',
    'OTHER_WRITABLE': 'ow',
    'STICKY': 'st',
    'EXEC': 'ex',
}


def stat_at(file: str, cwd: int | str | None = None, follow_symlinks: bool = False) -> os.stat_result:
    dirfd: int | None = None
    need_to_close = False
    if isinstance(cwd, str):
        dirfd = os.open(cwd, os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0))
        need_to_close = True
    elif isinstance(cwd, int):
        dirfd = cwd

    try:
        return os.stat(file, dir_fd=dirfd, follow_symlinks=follow_symlinks)
    finally:
        if need_to_close and dirfd is not None:
            os.close(dirfd)


class Dircolors:

    def __init__(self) -> None:
        self.codes: dict[str, str] = {}
        self.extensions: dict[str, str] = {}
        if not self.load_from_environ() and not self.load_from_file():
            self.load_defaults()

    def clear(self) -> None:
        self.codes.clear()
        self.extensions.clear()

    def load_from_file(self) -> bool:
        for candidate in (os.path.expanduser('~/.dir_colors'), '/etc/DIR_COLORS'):
            with suppress(Exception):
                with open(candidate) as f:
                    return self.load_from_dircolors(f.read())
        return False

    def load_from_lscolors(self, lscolors: str) -> bool:
        self.clear()
        if not lscolors:
            return False

        for item in lscolors.split(':'):
            try:
                code, color = item.split('=', 1)
            except ValueError:
                continue
            if code.startswith('*.'):
                self.extensions[code[1:]] = color
            else:
                self.codes[code] = color

        return bool(self.codes or self.extensions)

    def load_from_environ(self, envvar: str = 'LS_COLORS') -> bool:
        return self.load_from_lscolors(os.environ.get(envvar) or '')

    def load_from_dircolors(self, database: str, strict: bool = False) -> bool:
        self.clear()

        for line in database.splitlines():
            line = line.split('#')[0].strip()
            if not line:
                continue

            split = line.split()
            if len(split) != 2:
                if strict:
                    raise ValueError(f'Warning: unable to parse dircolors line "{line}"')
                continue

            key, val = split
            if key == 'TERM':
                continue
            if key in CODE_MAP:
                self.codes[CODE_MAP[key]] = val
            elif key.startswith('.'):
                self.extensions[key] = val
            elif strict:
                raise ValueError(f'Warning: unable to parse dircolors line "{line}"')

        return bool(self.codes or self.extensions)

    def load_defaults(self) -> bool:
        self.clear()
        return self.load_from_dircolors(DEFAULT_DIRCOLORS, True)

    def generate_lscolors(self) -> str:
        """ Output the database in the format used by the LS_COLORS environment variable. """

        def gen_pairs() -> Generator[tuple[str, str], None, None]:
            for pair in self.codes.items():
                yield pair
            for pair in self.extensions.items():
                # change .xyz to *.xyz
                yield '*' + pair[0], pair[1]

        return ':'.join('{}={}'.format(*pair) for pair in gen_pairs())

    def _format_code(self, text: str, code: str) -> str:
        val = self.codes.get(code)
        return '\033[{}m{}\033[{}m'.format(val, text, self.codes.get('rs', '0')) if val else text

    def _format_ext(self, text: str, ext: str) -> str:
        val = self.extensions.get(ext, '0')
        return '\033[{}m{}\033[{}m'.format(val, text, self.codes.get('rs', '0')) if val else text

    def format_mode(self, text: str, sr: os.stat_result) -> str:
        mode = sr.st_mode
        if stat.S_ISDIR(mode):
            if (mode & (stat.S_ISVTX | stat.S_IWOTH)) == (stat.S_ISVTX | stat.S_IWOTH):
                # sticky and world-writable
                return self._format_code(text, 'tw')
            if mode & stat.S_ISVTX:
                # sticky but not world-writable
                return self._format_code(text, 'st')
            if mode & stat.S_IWOTH:
                # world-writable but not sticky
                return self._format_code(text, 'ow')
            # normal directory
            return self._format_code(text, 'di')

        for mask, code in special_types:
            if (mode & mask) == mask:
                return self._format_code(text, code)

        # executable file?
        if mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            return self._format_code(text, 'ex')

        # regular file, format according to its extension
        ext = os.path.splitext(text)[1]
        if ext:
            return self._format_ext(text, ext)
        return text

    def __call__(self, path: str, text: str, cwd: int | str | None = None) -> str:
        follow_symlinks = self.codes.get('ln') == 'target'
        try:
            sr = stat_at(path, cwd, follow_symlinks)
        except OSError:
            return text
        return self.format_mode(text, sr)


def develop() -> None:
    import sys
    print(Dircolors()(sys.argv[-1], sys.argv[-1]))
