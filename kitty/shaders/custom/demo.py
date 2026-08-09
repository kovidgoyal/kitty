#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import glob
import math
import os
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from threading import Thread
from typing import Any

DEFAULT_DURATION = 3
DEFAULT_INITIAL_SLEEP = 3
SCREEN_WIDTH = 600
SCREEN_HEIGHT = 400

SWAY_CONFIG = f"""\
output HEADLESS-1 resolution {SCREEN_WIDTH}x{SCREEN_HEIGHT} scale 1
default_border none
default_floating_border none
hide_edge_borders both
gaps inner 0
gaps outer 0
bar {{
    mode invisible
}}
"""

# Module-level state, set by do_one() before calling animate functions
_sway_socket: str = ''
_wayland_display: str = ''
_kitty_socket: str = ''


def get_runtime_dir() -> str:
    return os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')


def sway_msg(*args: str) -> None:
    subprocess.run(['swaymsg', '-s', _sway_socket] + list(args), check=True, stdout=subprocess.DEVNULL)


def move_mouse(geometry: tuple[int, int, int, int], x: int, y: int) -> None:
    abs_x = geometry[0] + x
    abs_y = geometry[1] + y
    sway_msg('seat', 'seat0', 'cursor', 'set', str(abs_x), str(abs_y))


def click_mouse() -> None:
    sway_msg('seat', 'seat0', 'cursor', 'press', 'button1')
    time.sleep(0.05)
    sway_msg('seat', 'seat0', 'cursor', 'release', 'button1')


def remote_control(*args: str) -> None:
    subprocess.run(['kitten', '@', '--use-password=never', '--to', f'unix:{_kitty_socket}'] + list(args), check=True, stdout=subprocess.DEVNULL)


def key_event(key: str) -> None:
    remote_control('send-key', key.lower())


def send_text(text: str) -> None:
    remote_control('send-text', text)


def cursor_trail(window_id: str, geometry: tuple[int, int, int, int]) -> None:
    send_text('gg10j')
    time.sleep(0.3)
    send_text('^')
    time.sleep(0.4)
    send_text('$')
    time.sleep(0.3)
    send_text(':hello world')
    time.sleep(0.5)
    key_event('Escape')
    time.sleep(0.2)
    send_text('$')


def pond_ripple(window_id: str, geometry: tuple[int, int, int, int]) -> None:
    time.sleep(0.1)
    move_mouse(geometry, 100, 100)
    click_mouse()
    time.sleep(1)
    move_mouse(geometry, 200, 200)
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


def wait_for_file(path: str, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.1)
    return False


def start_sway(config_file: str) -> tuple['subprocess.Popen[bytes]', str, str]:
    """Start a headless sway compositor. Returns (proc, wayland_display_name, ipc_socket_path)."""
    runtime_dir = get_runtime_dir()
    # Snapshot existing sockets before starting so we can identify the new one
    existing = set(glob.glob(f'{runtime_dir}/wayland-[0-9]*'))
    env: dict[str, str] = {k: v for k, v in os.environ.items()}
    env['WLR_BACKENDS'] = 'headless'
    # Remove parent display to avoid nested-compositor confusion
    env.pop('WAYLAND_DISPLAY', None)
    env.pop('DISPLAY', None)
    proc = subprocess.Popen(
        ['sway', '--config', config_file],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=False,
    )
    # Wait for sway to create its Wayland socket
    deadline = time.monotonic() + 10
    wayland_display = ''
    while time.monotonic() < deadline:
        current = set(glob.glob(f'{runtime_dir}/wayland-[0-9]*'))
        for path in sorted(current - existing):
            if not path.endswith('.lock'):
                wayland_display = os.path.basename(path)
                break
        if wayland_display:
            break
        time.sleep(0.1)
    if not wayland_display:
        proc.kill()
        proc.wait()
        raise SystemExit('Timed out waiting for headless sway Wayland socket')
    # IPC socket path: $XDG_RUNTIME_DIR/sway-ipc.$UID.$PID.sock
    ipc_socket = os.path.join(runtime_dir, f'sway-ipc.{os.getuid()}.{proc.pid}.sock')
    if not wait_for_file(ipc_socket, timeout=10):
        proc.kill()
        proc.wait()
        raise SystemExit(f'Timed out waiting for sway IPC socket: {ipc_socket}')
    return proc, wayland_display, ipc_socket


def record_output(m: dict[str, Any], output_filename: str, wayland_env: dict[str, str]) -> str:
    duration_seconds = m.get('duration', DEFAULT_DURATION)
    output_filename += '.mkv'
    with suppress(FileNotFoundError):
        os.remove(output_filename)
    cmd = ['wf-recorder', '-o', 'HEADLESS-1', '-f', output_filename, '-y']
    # lossless recording
    cmd += '-c libx264rgb -p crf=0'.split()
    env = {**os.environ, **wayland_env}
    try:
        print(f'🎬 Starting recording for {duration_seconds} seconds...')
        process = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(duration_seconds)
        print('🛑 Stopping recording and saving file...')
        process.send_signal(signal.SIGINT)
        process.wait(timeout=3)
        return output_filename
    except FileNotFoundError:
        raise SystemExit("❌ Error: 'wf-recorder' is not installed or not in your PATH.")
    except Exception as e:
        raise SystemExit(f'❌ An error occurred: {e}')


def drive_loop(kitty: 'subprocess.Popen[bytes]', which: str, m: dict[str, Any], destdir: str, wayland_env: dict[str, str]) -> None:
    st = m.get('initial_sleep', DEFAULT_INITIAL_SLEEP)
    print(f'Waiting for {st} seconds before recording...')
    time.sleep(st)
    geometry = (0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)
    output_file = os.path.join(destdir, which)
    animate = m.get('animate')
    if animate is not None:
        t = Thread(target=animate, args=('', geometry), daemon=True)
        t.start()
    lossless_file = record_output(m, output_file, wayland_env)
    if animate is not None:
        t.join()
    kitty.terminate()
    kitty.wait()
    print('Transcoding saved recording...')
    try:
        for fmt, cmd in {
            'webm': '-r 60 -c:v libsvtav1 -preset 3 -crf 55 -pix_fmt yuv420p -svtav1-params tune=0:scm=1:enable-intrabc=1:scd=0:aq-mode=0 -g 99999'
        }.items():
            of = f'{output_file}.{fmt}'
            with suppress(FileNotFoundError):
                os.remove(of)
            # subprocess.run(['mpv', lossless_file])
            cp = subprocess.run(['ffmpeg', '-i', lossless_file] + cmd.split() + [of], capture_output=True)
            if cp.returncode != 0:
                sys.stderr.buffer.write(cp.stderr)
                raise SystemExit(cp.returncode)
            print(f'Recording saved: {of}')
            subprocess.run(['ls', '-sh', of])
    finally:
        os.remove(lossless_file)


def do_one(which: str) -> None:
    global _sway_socket, _wayland_display, _kitty_socket
    print('Generating demo video for custon shader:', which)
    self = os.path.abspath(__file__)
    m = metadata.get(which) or {}
    cmd = m.get('cmd', ['nvim', '-R', '+1', self])
    d = os.path.dirname
    destdir = os.path.join(d(d(d(d(self)))), 'docs', 'screenshots')
    os.environ.pop('KITTY_PUBLIC_KEY', None)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False, prefix='sway-demo-') as f:
        f.write(SWAY_CONFIG)
        config_file = f.name

    kitty_socket_path = f'@kitty-custom-shader-demo-{os.getpid()}'

    try:
        sway_proc, wayland_display, ipc_socket = start_sway(config_file)
        _sway_socket = ipc_socket
        _wayland_display = wayland_display
        _kitty_socket = kitty_socket_path
        wayland_env = {'WAYLAND_DISPLAY': wayland_display}
        try:
            kcmd = [
                'kitty',
                '--start-as=fullscreen',
                '--config=NONE',
                '-o',
                'font_size=8',
                '-o',
                'cursor_trail=1',
                '-o',
                f'custom_shaders={which}',
                '-o',
                'allow_remote_control=socket-only',
                f'--listen-on=unix:{kitty_socket_path}',
            ]
            kitty_env: dict[str, str] = {k: v for k, v in os.environ.items()}
            kitty_env.update(wayland_env)
            kitty = subprocess.Popen(kcmd + cmd, env=kitty_env, text=False)
            try:
                drive_loop(kitty, which, m, destdir, wayland_env)
            finally:
                if kitty.returncode is None:
                    kitty.terminate()
                    kitty.wait()
        finally:
            sway_proc.terminate()
            with suppress(subprocess.TimeoutExpired):
                sway_proc.wait(timeout=5)
            if sway_proc.returncode is None:
                sway_proc.kill()
                sway_proc.wait()
    finally:
        with suppress(FileNotFoundError):
            os.remove(config_file)
        with suppress(FileNotFoundError):
            os.remove(kitty_socket_path)


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


if __name__ == '__main__':
    main()
