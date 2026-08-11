#!./kitty/launcher/kitty +launch
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

from kitty.constants import glfw_path
from kitty.fast_data_types import GLFW_FKEY_ESCAPE as KEY_ESCAPE
from kitty.fast_data_types import GLFW_MOUSE_BUTTON_LEFT as MOUSE_BUTTON_LEFT
from kitty.fast_data_types import GLFW_PRESS as PRESS
from kitty.fast_data_types import GLFW_RELEASE as RELEASE
from kitty.fast_data_types import (
    glfw_wayland_inject_init,
    glfw_wayland_inject_key,
    glfw_wayland_inject_mouse_button,
    glfw_wayland_inject_mouse_motion_absolute,
    glfw_wayland_inject_terminate,
)

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


def move_mouse(geometry: tuple[int, int, int, int], x: int, y: int) -> None:
    abs_x = geometry[0] + x
    abs_y = geometry[1] + y
    glfw_wayland_inject_mouse_motion_absolute(abs_x, abs_y, SCREEN_WIDTH, SCREEN_HEIGHT)


def click_mouse() -> None:
    glfw_wayland_inject_mouse_button(MOUSE_BUTTON_LEFT, PRESS)
    time.sleep(0.05)
    glfw_wayland_inject_mouse_button(MOUSE_BUTTON_LEFT, RELEASE)


def remote_control(*args: str) -> None:
    subprocess.run(['kitten', '@', '--use-password=never', '--to', f'unix:{_kitty_socket}'] + list(args), check=True, stdout=subprocess.DEVNULL)


def key_event(key: int) -> None:
    glfw_wayland_inject_key(key, PRESS)
    time.sleep(0.02)
    glfw_wayland_inject_key(key, RELEASE)


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
    key_event(KEY_ESCAPE)
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


def window_focus(window_id: str, geometry: tuple[int, int, int, int]) -> None:
    time.sleep(0.2)
    remote_control('focus-window', '-m', 'id:2')
    time.sleep(1)
    remote_control('focus-window', '-m', 'id:3')
    time.sleep(1)
    remote_control('focus-window', '-m', 'id:1')


def tab_change(window_id: str, geometry: tuple[int, int, int, int]) -> None:
    time.sleep(0.2)
    remote_control('focus-tab', '-m', 'id:2')
    time.sleep(1.5)
    remote_control('focus-tab', '-m', 'id:1')


metadata: dict[str, dict[str, Any]] = {
    # Background
    'inside-the-matrix': {'category': 'background', 'tagline': 'See the bones of reality.'},
    'northern-lights': {'category': 'background', 'tagline': 'The ethereal Aurora Borealis.', 'cmd': []},
    'fireworks': {'category': 'background', 'tagline': 'Celebrate the sheer awesomeness of your terminal.'},
    'water': {'category': 'background', 'tagline': 'Pretend you are cool enough to code underwater.'},
    # Mouse
    'pond-ripple': {'animate': pond_ripple, 'category': 'mouse', 'tagline': 'Clicking is like throwing stones in a pond.'},
    'spotlight': {'animate': spotlight, 'category': 'mouse', 'tagline': 'Spotlight your mouse pointer as it moves around.'},
    # Cursor trail
    'cursor-trail-blaze': {'animate': cursor_trail, 'category': 'cursor-trail', 'tagline': 'Set your cursor on fire as it moves around.'},
    'cursor-trail-lightning': {'animate': cursor_trail, 'category': 'cursor-trail', 'tagline': 'Make your cursor shoot lightning as it moves around.'},
    # Navigation
    'dim-inactive-windows': {
        'animate': window_focus,
        'category': 'navigation',
        'tagline': 'Make the active window standout more.',
        'session': 'launch kitten run-shell ls -l\nlaunch kitten run-shell bat -P setup.py\nlaunch kitten run-shell echo Hello World',
    },
    'tab-change': {
        'animate': tab_change,
        'category': 'navigation',
        'tagline': 'Highlight the active window on focus change.',
        'session': 'new_tab My Shell\nlaunch kitten run-shell ls\nnew_tab My Code\nlaunch nvim -R {self}',
    },
    'focus-highlight': {
        'animate': window_focus,
        'category': 'navigation',
        'tagline': 'Briefly highlight the active window on focus change.',
        'session': 'launch kitten run-shell ls -l\nlaunch kitten run-shell bat -P setup.py\nlaunch kitten run-shell echo Hello World',
    },
    # Retro terminals
    'crt': {'category': 'retro', 'title': 'Cathode Ray Tube', 'tagline': 'Your terminal deserves to have curves.', 'duration': 2},
    'crt-blue': {'category': 'retro', 'title': 'CRT Blue', 'tagline': 'Do you have the blues?', 'duration': 2},
    'tft': {'category': 'retro', 'title': 'Thin Film LCD', 'tagline': 'You are too modern for CRT', 'duration': 2},
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
        for fmt, cmd in {'webm': '-r 60 -c:v libsvtav1 -preset 6 -crf 35 -pix_fmt yuv420p -svtav1-params tune=0 -g 99999'}.items():
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


def get_destdir() -> str:
    self = os.path.abspath(__file__)
    d = os.path.dirname
    return os.path.join(d(d(d(d(self)))), '.cache', 'custom-shader-demos')


def do_one(which: str) -> None:
    global _sway_socket, _wayland_display, _kitty_socket
    print('Generating demo video for custon shader:', which)
    self = os.path.abspath(__file__)
    destdir = get_destdir()
    m = metadata.get(which) or {}
    cmd = m.get('cmd', ['nvim', '-R', '+1', self])
    os.makedirs(destdir, exist_ok=True)
    os.environ.pop('KITTY_PUBLIC_KEY', None)
    session = m.get('session', '').format(self=self)

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

        # Connect our virtual pointer and keyboard to the compositor before
        # starting kitty so the seat advertises pointer and keyboard capability
        # when kitty creates its wl_pointer and wl_keyboard objects.
        glfw_wayland_inject_init(glfw_path('wayland'), wayland_display)
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
            kcmd += ['--session=-'] if session else cmd
            kitty_env: dict[str, str] = {k: v for k, v in os.environ.items()}
            kitty_env.update(wayland_env)
            kitty = subprocess.Popen(kcmd, env=kitty_env, text=False, stdin=subprocess.PIPE)
            assert kitty.stdin is not None
            kitty.stdin.write(session.encode())
            kitty.stdin.close()
            try:
                drive_loop(kitty, which, m, destdir, wayland_env)
            finally:
                if kitty.returncode is None:
                    kitty.terminate()
                    kitty.wait()
        finally:
            glfw_wayland_inject_terminate()
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
        if shaders == ['upload']:
            cmd = ['rsync', '--info=progress2', '--checksum', '--compress'] + glob.glob(os.path.join(get_destdir(), '*.webm')) + ['dl1:/srv/download/videos/']
            print('Uploading changed demo video files...', flush=True)
            os.execlp(cmd[0], *cmd)
    try:
        for which in shaders:
            do_one(which)
    except KeyboardInterrupt:
        raise SystemExit('Aborting on user interrupt')


if __name__ == '__main__':
    main()
