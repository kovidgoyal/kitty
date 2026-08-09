#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import json
import math
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from threading import Thread
from typing import Any, Literal

DEFAULT_DURATION = 3
DEFAULT_INITIAL_SLEEP = 3


def move_mouse(geomerty: tuple[int, int, int, int], x: int, y: int) -> None:
    x += geomerty[0]
    y += geomerty[1]
    subprocess.run(['hyprctl', 'dispatch', f'hl.dsp.cursor.move({{ x = {x}, y = {y} }})'], check=True, stdout=subprocess.DEVNULL)


def click_mouse() -> None:
    subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.send_key_state({ key = "mouse:272", state = "down", mods = "" })'], check=True, stdout=subprocess.DEVNULL)
    time.sleep(0.05)
    subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.send_key_state({ key = "mouse:272", state = "up", mods = "" })'], check=True, stdout=subprocess.DEVNULL)


def key_event(key: str, mods: str = '', state: Literal['up', 'down'] = 'down') -> None:
    subprocess.run(
        ['hyprctl', 'dispatch', f'hl.dsp.send_key_state({{ key = "{key}", state = "{state}", mods = "{mods}" }})'], check=True, stdout=subprocess.DEVNULL
    )


def press_and_release(key: str, mods: str = '') -> None:
    key_event(key, mods)
    key_event(key, mods, 'up')


def cursor_trail(window_id: str, geomerty: tuple[int, int, int, int]) -> None:
    press_and_release('g')
    press_and_release('g')
    press_and_release('1')
    press_and_release('0')
    press_and_release('j')
    time.sleep(0.2)
    press_and_release('6', 'SHIFT')
    time.sleep(0.2)
    press_and_release('4', 'SHIFT')
    time.sleep(0.1)
    press_and_release('6', 'SHIFT')
    time.sleep(0.1)
    press_and_release('semicolon', 'SHIFT')
    for k in 'hello world':
        if k == ' ':
            k = 'space'
        press_and_release(k)
    time.sleep(0.2)
    press_and_release('Escape')
    time.sleep(0.2)
    press_and_release('4', 'SHIFT')


def pond_ripple(window_id: str, geomerty: tuple[int, int, int, int]) -> None:
    time.sleep(0.1)
    move_mouse(geomerty, 100, 100)
    click_mouse()
    time.sleep(1)
    move_mouse(geomerty, 200, 200)
    click_mouse()


def spotlight(window_id: str, geometry: tuple[int, int, int, int]) -> None:
    width, height = geometry[2], geometry[3]
    cx, cy = width // 2, height // 2
    radius_x = width * 0.35
    radius_y = height * 0.35
    duration = 3.0
    fps = 60
    dt = 1.0 / fps
    t = 0.0
    while t < duration:
        angle = 2 * math.pi * (t / duration)
        x = int(cx + radius_x * math.cos(angle))
        y = int(cy + radius_y * math.sin(angle))
        move_mouse(geometry, x, y)
        time.sleep(dt)
        t += dt


metadata: dict[str, dict[str, Any]] = {
    'inside-the-matrix': {},
    'pond-ripple': {'animate': pond_ripple},
    'spotlight': {'animate': spotlight},
    'cursor-trail-blaze': {'animate': cursor_trail},
    'cursor-trail-lightning': {'animate': cursor_trail},
}


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
    duration_seconds = m.get('duration', DEFAULT_DURATION)
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
    winid = ''
    st = time.monotonic()
    while not winid and time.monotonic() - st < 2:
        winid = get_hyprland_window_id(kitty.pid)
    if not winid:
        raise SystemExit('Could not get Hyprland window id for kitty process')
    geom = get_window_geometry(winid)
    output_file = os.path.join(destdir, which)
    animate = m.get('animate')
    time.sleep(m.get('initial_sleep', DEFAULT_INITIAL_SLEEP))
    if animate is not None:
        t = Thread(target=animate, args=(winid, geom), daemon=True)
        t.start()
    lossless_file = record_window_geometry(geom, m, output_file)
    if animate is not None:
        t.join()
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
            subprocess.run(['ls', '-sh', of])
    finally:
        os.remove(lossless_file)


def main() -> None:
    if len(sys.argv) < 2:
        shaders = list(metadata)
    else:
        shaders = sys.argv[1:]
    try:
        for which in shaders:
            do_one(which)
    except KeyboardInterrupt:
        raise SystemExit('Aborting on user interrupt')


def do_one(which: str) -> None:
    self = os.path.abspath(__file__)
    m = metadata.get(which) or {}
    cmd = m.get('cmd', ['nvim', '-R', '+1', self])
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
        'cursor_trail=1',
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
