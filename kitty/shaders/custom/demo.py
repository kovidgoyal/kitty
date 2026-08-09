#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from typing import Any

metadata: dict[str, dict[str, Any]] = {}


def get_hyprland_window_id(pid: int) -> str:
    try:
        result = subprocess.run(['hyprctl', 'clients', '-j'], capture_output=True, text=True, check=True)
        clients = json.loads(result.stdout)
        for client in clients:
            if client.get('pid') == pid:
                return client.get('address')
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        pass
    return ''


def get_window_geometry(window_id: str) -> tuple[int, int, int, int]:
    if not window_id.startswith('0x'):
        window_id = f'0x{window_id}'
    result = subprocess.run(['hyprctl', 'clients', '-j'], capture_output=True, text=True, check=True)
    clients = json.loads(result.stdout)
    for client in clients:
        if client.get('address') == window_id:
            x, y = client.get('at', [0, 0])
            width, height = client.get('size', [0, 0])
            return (x, y, width, height)
    raise KeyError(f'No window with id: {window_id} found')


def record_window_geometry(geometry: tuple[int, int, int, int], m: dict[str, Any], output_filename: str) -> str:
    x, y, width, height = geometry
    geometry_string = f'{x},{y} {width}x{height}'
    duration_seconds = m.get('duration', 5)
    output_filename += '.mkv'
    with suppress(FileNotFoundError):
        os.remove(output_filename)
    cmd = ['wf-recorder', '-g', geometry_string, '-f', output_filename, '-y']
    # lossless recording
    cmd += '-c libx264rgb -p crf=0'.split()
    try:
        print(f'🎬 Starting recording of {geometry_string} for {duration_seconds} seconds...')
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(duration_seconds)
        print('🛑 Stopping recording and saving file...')
        process.send_signal(signal.SIGINT)
        process.wait(timeout=5)
        return output_filename
    except subprocess.TimeoutExpired:
        process.kill()
        raise SystemExit('⚠️ wf-recorder hung and had to be forcefully killed.')
    except FileNotFoundError:
        raise SystemExit("❌ Error: 'wf-recorder' is not installed or not in your PATH.")
    except Exception as e:
        raise SystemExit(f'❌ An error occurred: {e}')


def drive_loop(kitty: subprocess.Popen, which: str, m: dict[str, Any], destdir: str) -> None:
    time.sleep(m.get('initial_sleep', 1))
    winid = ''
    st = time.monotonic()
    while not winid and time.monotonic() - st < 2:
        winid = get_hyprland_window_id(kitty.pid)
    if not winid:
        raise SystemExit('Could not get Hyprland window id for kitty process')
    geom = get_window_geometry(winid)
    output_file = os.path.join(destdir, which)
    lossless_file = record_window_geometry(geom, m, output_file)
    kitty.terminate()
    kitty.wait()
    print('Transcoding saved recording...')
    try:
        for fmt, cmd in {
            'webm': '-c:v libsvtav1 -preset 3 -crf 55 -pix_fmt yuv420p -svtav1-params tune=0:scm=1:enable-intrabc=1:scd=0:enable-hdr=0:aq-mode=0 -g 99999'
        }.items():
            of = f'{output_file}.{fmt}'
            with suppress(FileNotFoundError):
                os.remove(of)
            subprocess.run(['ffmpeg', '-i', lossless_file] + cmd.split() + [of], check=True, capture_output=True)
            print(f'Recording saved: {of}')
    finally:
        os.remove(lossless_file)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit('Must specify exactly one command line argument')
    self = os.path.abspath(__file__)
    which = sys.argv[-1]
    m = metadata.get(which) or {}
    cmd = m.get('cmd', ['nvim', '-R', self])
    kcmd = [
        'kitty',
        '--class=float',
        '--config=NONE',
        '-o',
        'remember_window_size=no',
        '-o',
        'font_size=8',
        '-o',
        'initial_window_width=70c',
        '-o',
        'initial_window_height=20c',
        '-o',
        f'custom_shaders={which}',
    ]
    kitty = subprocess.Popen(kcmd + cmd)
    d = os.path.dirname
    destdir = os.path.join(d(d(d(d(self)))), 'docs', 'screenshots')
    try:
        drive_loop(kitty, which, m, destdir)
    finally:
        if kitty.returncode is None:
            kitty.terminate()
            kitty.wait()


if __name__ == '__main__':
    main()
