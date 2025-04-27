#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import string
import sys
import tempfile
from typing import TYPE_CHECKING, Any, Literal, Optional, TypedDict

from kitty.cli import create_default_opts
from kitty.conf.utils import to_color
from kitty.constants import kitten_exe
from kitty.fonts import Descriptor
from kitty.fonts.common import (
    face_from_descriptor,
    get_axis_map,
    get_font_files,
    get_named_style,
    get_variable_data_for_descriptor,
    get_variable_data_for_face,
    is_variable,
    spec_for_face,
)
from kitty.fonts.features import Type, known_features
from kitty.fonts.list import create_family_groups
from kitty.fonts.render import display_bitmap
from kitty.options.types import Options
from kitty.options.utils import parse_font_spec
from kitty.typing_compat import NotRequired
from kitty.utils import screen_size_function

if TYPE_CHECKING:
    from kitty.fast_data_types import FeatureData

def setup_debug_print() -> bool:
    if 'KITTY_STDIO_FORWARDED' in os.environ:
        try:
            fd = int(os.environ['KITTY_STDIO_FORWARDED'])
        except Exception:
            return False
        try:
            sys.stdout = open(fd, 'w', closefd=False)
            return True
        except OSError:
            return False
    return False


def send_to_kitten(x: Any) -> None:
    f = sys.__stdout__
    assert f is not None
    try:
        f.buffer.write(json.dumps(x).encode())
        f.buffer.write(b'\n')
        f.buffer.flush()
    except BrokenPipeError:
        raise SystemExit('Pipe to kitten was broken while sending data to it')


class TextStyle(TypedDict):
    font_size: float
    dpi_x: float
    dpi_y: float
    foreground: str
    background: str


OptNames = Literal['font_family', 'bold_font', 'italic_font', 'bold_italic_font']
FamilyKey = tuple[OptNames, ...]


def opts_from_cmd(cmd: dict[str, Any]) -> tuple[Options, FamilyKey, float, float]:
    opts = Options()
    ts: TextStyle = cmd['text_style']
    opts.font_size = ts['font_size']
    opts.foreground = to_color(ts['foreground'])
    opts.background = to_color(ts['background'])
    family_key = []
    def d(k: OptNames) -> None:
        if k in cmd:
            setattr(opts, k, parse_font_spec(cmd[k]))
            family_key.append(k)
    d('font_family')
    d('bold_font')
    d('italic_font')
    d('bold_italic_font')
    return opts, tuple(family_key), ts['dpi_x'], ts['dpi_y']


BaseKey = tuple[str, int, int]
FaceKey = tuple[str, BaseKey]
RenderedSample = tuple[bytes, dict[str, Any]]
RenderedSampleTransmit = dict[str, Any]
SAMPLE_TEXT = string.ascii_lowercase + ' ' + string.digits + ' ' + string.ascii_uppercase + ' ' + string.punctuation


class FD(TypedDict):
    is_index: bool
    name: NotRequired[str]
    tooltip: NotRequired[str]
    sample: NotRequired[str]
    params: NotRequired[tuple[str, ...]]



def get_features(features: dict[str, Optional['FeatureData']]) -> dict[str, FD]:
    ans = {}
    for tag, data in features.items():
        kf = known_features.get(tag)
        if kf is None or kf.type is Type.hidden:
            continue
        fd: FD = {'is_index': kf.type is Type.index}
        ans[tag] = fd
        if data is not None:
            if n := data.get('name'):
                fd['name'] = n
            if n := data.get('tooltip'):
                fd['tooltip'] = n
            if n := data.get('sample'):
                fd['sample'] = n
            if p := data.get('params'):
                fd['params'] = p
    return ans


def render_face_sample(font: Descriptor, opts: Options, dpi_x: float, dpi_y: float, width: int, height: int, sample_text: str = '') -> RenderedSample:
    face = face_from_descriptor(font, opts.font_size, dpi_x, dpi_y)
    face.set_size(opts.font_size, dpi_x, dpi_y)
    metadata = {
        'variable_data': get_variable_data_for_face(face),
        'style': font['style'],
        'psname': face.postscript_name(),
        'features': get_features(face.get_features()),
        'applied_features': face.applied_features(),
        'spec': spec_for_face(font['family'], face).as_setting,
        'cell_width': 0, 'cell_height': 0, 'canvas_height': 0, 'canvas_width': width,
    }
    if is_variable(font):
        ns = get_named_style(face)
        if ns:
            metadata['variable_named_style'] = ns
        metadata['variable_axis_map'] = get_axis_map(face)
    bitmap, cell_width, cell_height = face.render_sample_text(sample_text or SAMPLE_TEXT, width, height, opts.foreground.rgb)
    metadata['cell_width'] = cell_width
    metadata['cell_height'] = cell_height
    metadata['canvas_height'] = len(bitmap) // (4 *width)
    return bitmap, metadata


def render_family_sample(
    opts: Options, family_key: FamilyKey, dpi_x: float, dpi_y: float, width: int, height: int, output_dir: str,
    cache: dict[FaceKey, RenderedSampleTransmit]
) -> dict[str, RenderedSampleTransmit]:
    base_key: BaseKey = opts.font_family.created_from_string, width, height
    ans: dict[str, RenderedSampleTransmit] = {}
    font_files = get_font_files(opts)
    for x in family_key:
        key: FaceKey = x + ': ' + str(getattr(opts, x)), base_key
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
                bitmap, metadata = render_face_sample(desc, opts, dpi_x, dpi_y, width, height)
                tf.write(bitmap)
            metadata['path'] = tf.name
            cache[key] = ans[x] = metadata
    return ans


ResolvedFace = dict[Literal['family', 'spec', 'setting'], str]


def spec_for_descriptor(d: Descriptor, font_size: float) -> str:
    face = face_from_descriptor(d, font_size, 288, 288)
    return spec_for_face(d['family'], face).as_setting


def resolved_faces(opts: Options) -> dict[OptNames, ResolvedFace]:
    font_files = get_font_files(opts)
    ans: dict[OptNames, ResolvedFace] = {}
    def d(key: Literal['medium', 'bold', 'italic', 'bi'], opt_name: OptNames) -> None:
        descriptor = font_files[key]
        ans[opt_name] = {
                'family': descriptor['family'], 'spec': spec_for_descriptor(descriptor, opts.font_size),
                'setting': getattr(opts, opt_name).created_from_string
        }
    d('medium', 'font_family')
    d('bold', 'bold_font')
    d('italic', 'italic_font')
    d('bi', 'bold_italic_font')
    return ans


def main() -> None:
    setup_debug_print()
    cache: dict[FaceKey, RenderedSampleTransmit] = {}
    for line in sys.stdin.buffer:
        cmd = json.loads(line)
        action = cmd.get('action', '')
        if action == 'list_monospaced_fonts':
            opts = create_default_opts()
            send_to_kitten({'fonts': create_family_groups(), 'resolved_faces': resolved_faces(opts)})
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


def query_kitty() -> dict[str, str]:
    import subprocess
    ans = {}
    for line in subprocess.check_output([kitten_exe(), 'query-terminal']).decode().splitlines():
        k, sep, v = line.partition(':')
        if sep == ':':
            ans[k] = v.strip()
    return ans


def showcase(family: str = 'family="Fira Code"', sample_text: str = '') -> None:
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
    bitmap, m = render_face_sample(desc, opts, float(q['dpi_x']), float(q['dpi_y']), width, height, sample_text=sample_text)
    display_bitmap(bitmap, m['canvas_width'], m['canvas_height'])


def test_render(spec: str = 'family="Fira Code"', width: int = 1560, height: int = 116, font_size: float = 12, dpi: float = 288) -> None:
    opts = Options()
    opts.font_family = parse_font_spec(spec)
    opts.font_size = font_size
    opts.foreground = to_color('white')
    desc = get_font_files(opts)['medium']
    bitmap, m = render_face_sample(desc, opts, float(dpi), float(dpi), width, height)
    display_bitmap(bitmap, m['canvas_width'], m['canvas_height'])
