#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import math
import os
import re
import shlex
import signal
import string
import subprocess
from collections import namedtuple
from contextlib import contextmanager
from functools import lru_cache
from time import monotonic

from .constants import isosx
from .fast_data_types import glfw_get_physical_dpi, wcwidth as wcwidth_impl


def safe_print(*a, **k):
    try:
        print(*a, **k)
    except Exception:
        pass


def ceil_int(x):
    return int(math.ceil(x))


@lru_cache(maxsize=2**13)
def wcwidth(c: str) -> int:
    try:
        return wcwidth_impl(ord(c))
    except TypeError:
        return wcwidth_impl(ord(c[0]))


@contextmanager
def timeit(name, do_timing=False):
    if do_timing:
        st = monotonic()
    yield
    if do_timing:
        safe_print('Time for {}: {}'.format(name, monotonic() - st))


def sanitize_title(x):
    return re.sub(r'\s+', ' ', re.sub(r'[\0-\x19]', '', x))


def get_logical_dpi():
    if not hasattr(get_logical_dpi, 'ans'):
        if isosx:
            # TODO: Investigate if this needs a different implementation on OS X
            get_logical_dpi.ans = glfw_get_physical_dpi()
        else:
            raw = subprocess.check_output(['xdpyinfo']).decode('utf-8')
            m = re.search(
                r'^\s*resolution:\s*(\d+)+x(\d+)', raw, flags=re.MULTILINE
            )
            get_logical_dpi.ans = int(m.group(1)), int(m.group(2))
    return get_logical_dpi.ans


def get_dpi():
    if not hasattr(get_dpi, 'ans'):
        pdpi = glfw_get_physical_dpi()
        get_dpi.ans = {'physical': pdpi, 'logical': get_logical_dpi()}
    return get_dpi.ans


# Color names  {{{

color_pat = re.compile(r'^#([a-fA-F0-9]{3}|[a-fA-F0-9]{6})$')
color_pat2 = re.compile(
    r'rgb:([a-f0-9]{2})/([a-f0-9]{2})/([a-f0-9]{2})$', re.IGNORECASE
)

color_names = {
    'aliceblue': 'f0f8ff',
    'antiquewhite': 'faebd7',
    'aqua': '00ffff',
    'aquamarine': '7fffd4',
    'azure': 'f0ffff',
    'beige': 'f5f5dc',
    'bisque': 'ffe4c4',
    'black': '000000',
    'blanchedalmond': 'ffebcd',
    'blue': '0000ff',
    'blueviolet': '8a2be2',
    'brown': 'a52a2a',
    'burlywood': 'deb887',
    'cadetblue': '5f9ea0',
    'chartreuse': '7fff00',
    'chocolate': 'd2691e',
    'coral': 'ff7f50',
    'cornflowerblue': '6495ed',
    'cornsilk': 'fff8dc',
    'crimson': 'dc143c',
    'cyan': '00ffff',
    'darkblue': '00008b',
    'darkcyan': '008b8b',
    'darkgoldenrod': 'b8860b',
    'darkgray': 'a9a9a9',
    'darkgrey': 'a9a9a9',
    'darkgreen': '006400',
    'darkkhaki': 'bdb76b',
    'darkmagenta': '8b008b',
    'darkolivegreen': '556b2f',
    'darkorange': 'ff8c00',
    'darkorchid': '9932cc',
    'darkred': '8b0000',
    'darksalmon': 'e9967a',
    'darkseagreen': '8fbc8f',
    'darkslateblue': '483d8b',
    'darkslategray': '2f4f4f',
    'darkslategrey': '2f4f4f',
    'darkturquoise': '00ced1',
    'darkviolet': '9400d3',
    'deeppink': 'ff1493',
    'deepskyblue': '00bfff',
    'dimgray': '696969',
    'dimgrey': '696969',
    'dodgerblue': '1e90ff',
    'firebrick': 'b22222',
    'floralwhite': 'fffaf0',
    'forestgreen': '228b22',
    'fuchsia': 'ff00ff',
    'gainsboro': 'dcdcdc',
    'ghostwhite': 'f8f8ff',
    'gold': 'ffd700',
    'goldenrod': 'daa520',
    'gray': '808080',
    'grey': '808080',
    'green': '008000',
    'greenyellow': 'adff2f',
    'honeydew': 'f0fff0',
    'hotpink': 'ff69b4',
    'indianred': 'cd5c5c',
    'indigo': '4b0082',
    'ivory': 'fffff0',
    'khaki': 'f0e68c',
    'lavender': 'e6e6fa',
    'lavenderblush': 'fff0f5',
    'lawngreen': '7cfc00',
    'lemonchiffon': 'fffacd',
    'lightblue': 'add8e6',
    'lightcoral': 'f08080',
    'lightcyan': 'e0ffff',
    'lightgoldenrodyellow': 'fafad2',
    'lightgray': 'd3d3d3',
    'lightgrey': 'd3d3d3',
    'lightgreen': '90ee90',
    'lightpink': 'ffb6c1',
    'lightsalmon': 'ffa07a',
    'lightseagreen': '20b2aa',
    'lightskyblue': '87cefa',
    'lightslategray': '778899',
    'lightslategrey': '778899',
    'lightsteelblue': 'b0c4de',
    'lightyellow': 'ffffe0',
    'lime': '00ff00',
    'limegreen': '32cd32',
    'linen': 'faf0e6',
    'magenta': 'ff00ff',
    'maroon': '800000',
    'mediumaquamarine': '66cdaa',
    'mediumblue': '0000cd',
    'mediumorchid': 'ba55d3',
    'mediumpurple': '9370db',
    'mediumseagreen': '3cb371',
    'mediumslateblue': '7b68ee',
    'mediumspringgreen': '00fa9a',
    'mediumturquoise': '48d1cc',
    'mediumvioletred': 'c71585',
    'midnightblue': '191970',
    'mintcream': 'f5fffa',
    'mistyrose': 'ffe4e1',
    'moccasin': 'ffe4b5',
    'navajowhite': 'ffdead',
    'navy': '000080',
    'oldlace': 'fdf5e6',
    'olive': '808000',
    'olivedrab': '6b8e23',
    'orange': 'ffa500',
    'orangered': 'ff4500',
    'orchid': 'da70d6',
    'palegoldenrod': 'eee8aa',
    'palegreen': '98fb98',
    'paleturquoise': 'afeeee',
    'palevioletred': 'db7093',
    'papayawhip': 'ffefd5',
    'peachpuff': 'ffdab9',
    'per': 'cd853f',
    'pink': 'ffc0cb',
    'plum': 'dda0dd',
    'powderblue': 'b0e0e6',
    'purple': '800080',
    'red': 'ff0000',
    'rosybrown': 'bc8f8f',
    'royalblue': '4169e1',
    'saddlebrown': '8b4513',
    'salmon': 'fa8072',
    'sandybrown': 'f4a460',
    'seagreen': '2e8b57',
    'seashell': 'fff5ee',
    'sienna': 'a0522d',
    'silver': 'c0c0c0',
    'skyblue': '87ceeb',
    'slateblue': '6a5acd',
    'slategray': '708090',
    'slategrey': '708090',
    'snow': 'fffafa',
    'springgreen': '00ff7f',
    'steelblue': '4682b4',
    'tan': 'd2b48c',
    'teal': '008080',
    'thistle': 'd8bfd8',
    'tomato': 'ff6347',
    'turquoise': '40e0d0',
    'violet': 'ee82ee',
    'wheat': 'f5deb3',
    'white': 'ffffff',
    'whitesmoke': 'f5f5f5',
    'yellow': 'ffff00',
    'yellowgreen': '9acd32',
}
Color = namedtuple('Color', 'red green blue')

# }}}


def to_color(raw, validate=False):
    x = raw.strip().lower()
    m = color_pat.match(x)
    val = None
    if m is not None:
        val = m.group(1)
        if len(val) == 3:
            val = ''.join(2 * s for s in val)
    else:
        m = color_pat2.match(x)
        if m is not None:
            val = m.group(1) + m.group(2) + m.group(3)
        else:
            val = color_names.get(x)
    if val is None:
        if validate:
            raise ValueError('Invalid color name: {}'.format(raw))
        return
    return Color(int(val[:2], 16), int(val[2:4], 16), int(val[4:], 16))


def color_as_int(val):
    return val[0] << 16 | val[1] << 8 | val[2]


def color_from_int(val):
    return Color((val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF)


def parse_color_set(raw):
    parts = raw.split(';')
    for c, spec in [parts[i:i + 2] for i in range(0, len(parts), 2)]:
        try:
            c = int(c)
            if c < 0 or c > 255:
                raise IndexError('Out of bounds')
            r, g, b = to_color(spec)
            yield c, r << 16 | g << 8 | b
        except Exception:
            continue


def pipe2():
    try:
        read_fd, write_fd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    except AttributeError:
        import fcntl
        read_fd, write_fd = os.pipe()
        for fd in (read_fd, write_fd):
            flag = fcntl.fcntl(fd, fcntl.F_GETFD)
            fcntl.fcntl(fd, fcntl.F_SETFD, flag | fcntl.FD_CLOEXEC)
            flag = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flag | os.O_NONBLOCK)
    return read_fd, write_fd


def handle_unix_signals():
    read_fd, write_fd = pipe2()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda x, y: None)
        signal.siginterrupt(sig, False)
    signal.set_wakeup_fd(write_fd)
    return read_fd


def get_primary_selection():
    if isosx:
        return ''  # There is no primary selection on OS X
    # glfw has no way to get the primary selection
    # https://github.com/glfw/glfw/issues/894
    return subprocess.check_output(['xsel', '-p']).decode('utf-8')


def base64_encode(
    integer,
    chars=string.ascii_uppercase + string.ascii_lowercase + string.digits +
    '+/'
):
    ans = ''
    while True:
        integer, remainder = divmod(integer, 64)
        ans = chars[remainder] + ans
        if integer == 0:
            break
    return ans


def set_primary_selection(text):
    if isosx:
        return  # There is no primary selection on OS X
    if isinstance(text, str):
        text = text.encode('utf-8')
    p = subprocess.Popen(['xsel', '-i', '-p'], stdin=subprocess.PIPE)
    p.stdin.write(text), p.stdin.close()
    p.wait()


def open_url(url, program='default'):
    if program == 'default':
        cmd = ['open'] if isosx else ['xdg-open']
    else:
        cmd = shlex.split(program)
    cmd.append(url)
    subprocess.Popen(cmd).wait()
