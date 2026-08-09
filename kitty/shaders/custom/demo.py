#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import glob
import math
import os
import shutil
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
_virt_mouse: 'subprocess.Popen[bytes] | None' = None

# Protocol XML for zwlr_virtual_pointer_manager_v1 (wlr-protocols)
_VIRTUAL_POINTER_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<protocol name="wlr_virtual_pointer_unstable_v1">
  <interface name="zwlr_virtual_pointer_v1" version="2">
    <enum name="error">
      <entry name="invalid_axis" value="0"/>
      <entry name="invalid_axis_source" value="1"/>
    </enum>
    <request name="motion">
      <arg name="time" type="uint"/>
      <arg name="dx" type="fixed"/>
      <arg name="dy" type="fixed"/>
    </request>
    <request name="motion_absolute">
      <arg name="time" type="uint"/>
      <arg name="x" type="uint"/>
      <arg name="y" type="uint"/>
      <arg name="x_extent" type="uint"/>
      <arg name="y_extent" type="uint"/>
    </request>
    <request name="button">
      <arg name="time" type="uint"/>
      <arg name="button" type="uint"/>
      <arg name="state" type="uint"/>
    </request>
    <request name="axis">
      <arg name="time" type="uint"/>
      <arg name="axis" type="uint"/>
      <arg name="value" type="fixed"/>
    </request>
    <request name="frame"/>
    <request name="axis_source">
      <arg name="axis_source" type="uint"/>
    </request>
    <request name="axis_stop">
      <arg name="time" type="uint"/>
      <arg name="axis" type="uint"/>
    </request>
    <request name="axis_discrete">
      <arg name="time" type="uint"/>
      <arg name="axis" type="uint"/>
      <arg name="value" type="fixed"/>
      <arg name="discrete" type="int"/>
    </request>
    <request name="destroy" type="destructor"/>
  </interface>
  <interface name="zwlr_virtual_pointer_manager_v1" version="2">
    <request name="create_virtual_pointer">
      <arg name="seat" type="object" interface="wl_seat" allow-null="true"/>
      <arg name="id" type="new_id" interface="zwlr_virtual_pointer_v1"/>
    </request>
    <request name="create_virtual_pointer_with_output" since="2">
      <arg name="seat" type="object" interface="wl_seat" allow-null="true"/>
      <arg name="output" type="object" interface="wl_output" allow-null="true"/>
      <arg name="id" type="new_id" interface="zwlr_virtual_pointer_v1"/>
    </request>
    <request name="destroy" type="destructor"/>
  </interface>
</protocol>
"""

# Daemon that holds a virtual pointer Wayland connection and processes commands on stdin.
# Commands: "move X Y EX EY\\n", "press BTN\\n", "release BTN\\n"
_VIRTUAL_POINTER_C = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <wayland-client-core.h>
#include "virt-pointer-client.h"

static struct zwlr_virtual_pointer_manager_v1 *g_manager;
static struct zwlr_virtual_pointer_v1 *g_pointer;

static void on_global(void *data, struct wl_registry *registry, uint32_t name,
                      const char *interface, uint32_t version)
{
    if (!strcmp(interface, "zwlr_virtual_pointer_manager_v1"))
        g_manager = wl_registry_bind(registry, name,
                                     &zwlr_virtual_pointer_manager_v1_interface,
                                     version > 1 ? 1 : version);
}
static void on_global_remove(void *d, struct wl_registry *r, uint32_t n) { (void)d; (void)r; (void)n; }
static const struct wl_registry_listener reg_listener = { on_global, on_global_remove };

static uint32_t ms_now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)(ts.tv_sec * 1000 + ts.tv_nsec / 1000000);
}

int main(void) {
    struct wl_display *dpy = wl_display_connect(NULL);
    if (!dpy) { fputs("Cannot connect to Wayland display\n", stderr); return 1; }
    struct wl_registry *reg = wl_display_get_registry(dpy);
    wl_registry_add_listener(reg, &reg_listener, NULL);
    wl_display_roundtrip(dpy);
    if (!g_manager) {
        fputs("zwlr_virtual_pointer_manager_v1 not supported by this compositor\n", stderr);
        return 1;
    }
    g_pointer = zwlr_virtual_pointer_manager_v1_create_virtual_pointer(g_manager, NULL);
    wl_display_roundtrip(dpy);

    char line[128];
    while (fgets(line, sizeof(line), stdin)) {
        uint32_t t = ms_now();
        uint32_t a, b, c, d;
        if (sscanf(line, "move %u %u %u %u", &a, &b, &c, &d) == 4) {
            zwlr_virtual_pointer_v1_motion_absolute(g_pointer, t, a, b, c, d);
            zwlr_virtual_pointer_v1_frame(g_pointer);
        } else if (sscanf(line, "press %u", &a) == 1) {
            zwlr_virtual_pointer_v1_button(g_pointer, t, a, 1);
            zwlr_virtual_pointer_v1_frame(g_pointer);
        } else if (sscanf(line, "release %u", &a) == 1) {
            zwlr_virtual_pointer_v1_button(g_pointer, t, a, 0);
            zwlr_virtual_pointer_v1_frame(g_pointer);
        }
        wl_display_flush(dpy);
    }
    zwlr_virtual_pointer_v1_destroy(g_pointer);
    zwlr_virtual_pointer_manager_v1_destroy(g_manager);
    wl_display_disconnect(dpy);
    return 0;
}
"""


def get_runtime_dir() -> str:
    return os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')


def build_virt_mouse(build_dir: str) -> str:
    xml_path = os.path.join(build_dir, 'virt-pointer.xml')
    header_path = os.path.join(build_dir, 'virt-pointer-client.h')
    proto_c_path = os.path.join(build_dir, 'virt-pointer-client.c')
    main_c_path = os.path.join(build_dir, 'virt-pointer-main.c')
    binary_path = os.path.join(build_dir, 'virt-pointer')
    with open(xml_path, 'w') as f:
        f.write(_VIRTUAL_POINTER_XML)
    with open(main_c_path, 'w') as f:
        f.write(_VIRTUAL_POINTER_C)
    subprocess.run(['wayland-scanner', 'client-header', xml_path, header_path], check=True, capture_output=True)
    subprocess.run(['wayland-scanner', 'private-code', xml_path, proto_c_path], check=True, capture_output=True)
    result = subprocess.run(
        ['gcc', '-O2', '-I', build_dir, proto_c_path, main_c_path, '-lwayland-client', '-o', binary_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f'Failed to compile virtual pointer tool:\n{result.stderr}')
    return binary_path


def start_virt_mouse(binary: str, wayland_display: str) -> None:
    global _virt_mouse
    env = {**os.environ, 'WAYLAND_DISPLAY': wayland_display}
    _virt_mouse = subprocess.Popen([binary], stdin=subprocess.PIPE, env=env, text=False)
    time.sleep(0.2)  # allow the virtual pointer to register with the compositor


def stop_virt_mouse() -> None:
    global _virt_mouse
    if _virt_mouse is not None:
        with suppress(Exception):
            assert _virt_mouse.stdin is not None
            _virt_mouse.stdin.close()
        with suppress(subprocess.TimeoutExpired):
            _virt_mouse.wait(timeout=2)
        if _virt_mouse.returncode is None:
            _virt_mouse.kill()
            _virt_mouse.wait()
        _virt_mouse = None


def send_virt_mouse(cmd: str) -> None:
    if _virt_mouse is not None and _virt_mouse.stdin is not None:
        _virt_mouse.stdin.write(cmd.encode())
        _virt_mouse.stdin.flush()


def move_mouse(geometry: tuple[int, int, int, int], x: int, y: int) -> None:
    abs_x = geometry[0] + x
    abs_y = geometry[1] + y
    send_virt_mouse(f'move {abs_x} {abs_y} {SCREEN_WIDTH} {SCREEN_HEIGHT}\n')


def click_mouse() -> None:
    send_virt_mouse('press 272\n')  # BTN_LEFT = 0x110 = 272
    time.sleep(0.05)
    send_virt_mouse('release 272\n')


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
    # Background
    'inside-the-matrix': {'category': 'background', 'tagline': 'See the bones of reality.'},
    'fireworks': {'category': 'background', 'tagline': 'Celebrate the sheer awesomeness of your terminal.'},
    'water': {'category': 'background', 'tagline': 'Pretend you are cool enough to code underwater.'},
    # Mouse
    'pond-ripple': {'animate': pond_ripple, 'category': 'mouse', 'tagline': 'Clicking is like throwing stones in a pond.'},
    'spotlight': {'animate': spotlight, 'category': 'mouse', 'tagline': 'Spotlight your mouse pointer as it moves around.'},
    # Cursor trail
    'cursor-trail-blaze': {'animate': cursor_trail, 'category': 'cursor-trail', 'tagline': 'Set your cursor on fire as it moves around.'},
    'cursor-trail-lightning': {'animate': cursor_trail, 'category': 'cursor-trail', 'tagline': 'Make your cursor shoot lightning as it moves around.'},
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

    with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False, prefix='sway-demo-') as f:
        f.write(SWAY_CONFIG)
        config_file = f.name

    build_dir = tempfile.mkdtemp(prefix='kitty-demo-build-')
    kitty_socket_path = f'@kitty-custom-shader-demo-{os.getpid()}'

    try:
        virt_mouse_binary = build_virt_mouse(build_dir)
        sway_proc, wayland_display, ipc_socket = start_sway(config_file)
        _sway_socket = ipc_socket
        _wayland_display = wayland_display
        _kitty_socket = kitty_socket_path
        wayland_env = {'WAYLAND_DISPLAY': wayland_display}
        # Start virtual pointer daemon before kitty so the seat has pointer
        # capability when kitty connects and creates its wl_pointer object.
        start_virt_mouse(virt_mouse_binary, wayland_display)
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
            stop_virt_mouse()
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
        shutil.rmtree(build_dir, ignore_errors=True)


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
