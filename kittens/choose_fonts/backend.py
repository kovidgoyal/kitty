#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

import json
import string
import sys
import tempfile
from typing import Any, Dict, Tuple, TypedDict

from kitty.conf.utils import to_color
from kitty.constants import kitten_exe
from kitty.fonts import Descriptor
from kitty.fonts.common import face_from_descriptor, get_font_files, get_variable_data_for_descriptor
from kitty.fonts.list import create_family_groups
from kitty.fonts.render import display_bitmap
from kitty.options.types import Options
from kitty.options.utils import parse_font_spec
from kitty.utils import screen_size_function


def send_to_kitten(x: Any) -> None:
    sys.stdout.buffer.write(json.dumps(x).encode())
    sys.stdout.buffer.write(b'\n')
    sys.stdout.buffer.flush()


class TextStyle(TypedDict):
    font_size: float
    dpi_x: float
    dpi_y: float
    foreground: str
    background: str


FamilyKey = Tuple[str, ...]


def opts_from_cmd(cmd: Dict[str, Any]) -> Tuple[Options, FamilyKey, float, float]:
    opts = Options()
    ts: TextStyle = cmd['text_style']
    opts.font_size = ts['font_size']
    opts.foreground = to_color(ts['foreground'])
    opts.background = to_color(ts['background'])
    family_key = []
    if 'font_family' in cmd:
        opts.font_family = parse_font_spec(cmd['font_family'])
        family_key.append(cmd['font_family'])
    if 'bold_font' in cmd:
        opts.bold_font = parse_font_spec(cmd['bold_font'])
        family_key.append(cmd['bold_font'])
    if 'italic_font' in cmd:
        opts.italic_font = parse_font_spec(cmd['italic_font'])
        family_key.append(cmd['italic_font'])
    if 'bold_italic_font' in cmd:
        opts.bold_italic_font = parse_font_spec(cmd['bold_italic_font'])
        family_key.append(cmd['bold_italic_font'])
    return opts, tuple(family_key), ts['dpi_x'], ts['dpi_y']


BaseKey = Tuple[FamilyKey, int, int]
FaceKey = Tuple[str, BaseKey]
SAMPLE_TEXT = string.ascii_lowercase + ' ' + string.digits + ' ' + string.ascii_uppercase + ' ' + string.punctuation


def render_face_sample(font: Descriptor, opts: Options, dpi_x: float, dpi_y: float, width: int, height: int) -> bytes:
    face = face_from_descriptor(font)
    face.set_size(opts.font_size, dpi_x, dpi_y)
    return face.render_sample_text(SAMPLE_TEXT, width, height, opts.foreground.rgb)


def render_family_sample(
    opts: Options, family_key: FamilyKey, dpi_x: float, dpi_y: float, width: int, height: int, output_dir: str,
    cache: Dict[FaceKey, str]
) -> Dict[str, str]:
    base_key: BaseKey = family_key, width, height
    ans: Dict[str, str] = {}
    font_files = get_font_files(opts)
    for x in family_key:
        key: FaceKey = x, base_key
        if x == 'font_family':
            desc = font_files['medium']
        elif x == 'bold_font':
            desc = font_files['bold']
        elif x == 'italic_font':
            desc = font_files['italic']
        elif x == 'bold_italic_font':
            desc = font_files['bi']
        cached = cache.get(key)
        if cached is not None:
            ans[x] = cached
        else:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.rgba', dir=output_dir) as tf:
                tf.write(render_face_sample(desc, opts, dpi_x, dpi_y, width, height))
            cache[key] = ans[x] = tf.name
    return ans


def main() -> None:
    cache: Dict[FaceKey, str] = {}
    for line in sys.stdin.buffer:
        cmd = json.loads(line)
        action = cmd.get('action', '')
        if action == 'list_monospaced_fonts':
            send_to_kitten(create_family_groups())
        elif action == 'read_variable_data':
            ans = []
            for descriptor in cmd['descriptors']:
                ans.append(get_variable_data_for_descriptor(descriptor))
            send_to_kitten(ans)
        elif action == 'render_family_samples':
            opts, family_key, dpi_x, dpi_y = opts_from_cmd(cmd)
            send_to_kitten(render_family_sample(opts, family_key, dpi_x, dpi_y, cmd['width'], cmd['height'], cmd['output_dir'], cache))
        else:
            raise SystemExit(f'Unknown action: {action}')


def query_kitty() -> Dict[str, str]:
    import subprocess
    ans = {}
    for line in subprocess.check_output([kitten_exe(), 'query-terminal']).decode().splitlines():
        k, sep, v = line.partition(':')
        if sep == ':':
            ans[k] = v.strip()
    return ans


def showcase(family: str) -> None:
    q = query_kitty()
    opts = Options()
    opts.foreground = to_color(q['foreground'])
    opts.background = to_color(q['background'])
    opts.font_size = float(q['font_size'])
    opts.font_family = parse_font_spec(family)
    font_files = get_font_files(opts)
    desc = font_files['medium']
    ss = screen_size_function()()
    width = ss.cell_width * ss.cols
    height = 5 * ss.cell_height
    bitmap = render_face_sample(desc, opts, float(q['dpi_x']), float(q['dpi_y']), width, height)
    display_bitmap(bitmap, width, height)
