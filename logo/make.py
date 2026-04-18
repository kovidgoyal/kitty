#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from typing import Any

SRC = 'kitty.svg'
base = os.path.dirname(os.path.abspath(__file__))

# To generate this template create an icon using Icon Composer on macOS and in
# the saved .icon (which is a folder) look for icon.js
icon_settings:dict[str, Any] = {
  'fill-specializations' : [
    {
      'value' : {
        'automatic-gradient' : 'extended-gray:1.00000,1.00000'
      }
    },
    {
      'appearance' : 'dark',
      'value' : {
        'automatic-gradient' : 'display-p3:0.20500,0.20500,0.20500,1.00000'
      }
    }
  ],
  'groups' : [
    {
      'layers' : [
        {
          'blend-mode' : 'normal',
          'glass' : False,
          'hidden' : False,
          'image-name' : 'icon.svg',
          'name' : 'icon',
          'opacity' : 1,
          'position' : {
            'scale' : 0.9,
            'translation-in-points' : [
              0,
              0
            ]
          }
        }
      ],
      'shadow' : {
        'kind' : 'neutral',
        'opacity' : 0.5
      },
      'translucency' : {
        'enabled' : True,
        'value' : 0.5
      }
    }
  ],
  'supported-platforms' : {
    'circles' : [
      'watchOS'
    ],
    'squares' : 'shared'
  }
}

def abspath(x: str) -> str:
    return os.path.abspath(os.path.join(base, x))


def run(*args: str) -> None:
    try:
        subprocess.check_call(args)
    except OSError:
        raise SystemExit(f'You are missing the {args[0]} program needed to generate the kitty logo')


def get_svg_viewbox(file_path: str) -> tuple[float, ...]:
    import xml.etree.ElementTree as ET
    tree = ET.parse(file_path)
    root = tree.getroot()
    viewbox = root.get('viewBox')
    if viewbox:
        return tuple(float(x) for x in viewbox.split())
    width = root.get('width')
    height = root.get('height')
    return (0.0, 0.0, float(width or 0), float(height or 0))


def create_icon(name: str, svg_path: str, output_path: str) -> str:
    view_box = get_svg_viewbox(svg_path)
    sz = view_box[-1]
    scale = 0.9 * 1024 / sz
    icon_dir = os.path.join(output_path, f'{name}.icon')
    if os.path.exists(icon_dir):
        shutil.rmtree(icon_dir)
    os.mkdir(icon_dir)
    s = deepcopy(icon_settings)
    for group in s['groups']:
        for layer in group['layers']:
            layer['image-name'] = os.path.basename(svg_path)
            layer['name'] = name
            layer['position']['scale'] = scale
    with open(os.path.join(icon_dir, 'icon.json'), 'w') as f:
        json.dump(s, f, indent=2)
    assets_dir = os.path.join(icon_dir, 'Assets')
    os.mkdir(assets_dir)
    shutil.copy(svg_path, assets_dir)
    return icon_dir


def create_assets() -> None:
    actool = [
        'xcrun', 'actool', '--warnings', '--platform', 'macosx', '--compile', base,
        '--minimum-deployment-target', '15.0', '--output-partial-info-plist', '/dev/stdout',
    ]
    icon = create_icon('kitty', abspath(SRC), base)
    run(*(actool + ['--app-icon', 'kitty', icon]))
    shutil.rmtree(icon)


def render(output: str, sz: int = 256) -> None:
    src = abspath(SRC)
    print(f'Rendering {os.path.basename(src)} at {sz}x{sz}...')
    run('rsvg-convert', '-w', str(sz), '-h', str(sz), '-o', output, src)
    run('optipng', '-quiet', '-o7', '-strip', 'all', output)


def main() -> None:
    if 'darwin' in sys.platform.lower():
        create_assets()
        if sys.argv[-1] == 'remote-macos':
            return
    else:
        run('ssh', 'ox', 'zsh', '-ilc', '~/bin/update-kitty && python3 ~/kitty-src/logo/make.py remote-macos')
        run('rsync', '-avz', '--include=*.icns', '--include=*.car', '--exclude=*', 'ox:~/kitty-src/logo/', base + '/')
    render(abspath('kitty.png'))
    render(abspath('kitty-128.png'), sz=128)


if __name__ == '__main__':
    main()
