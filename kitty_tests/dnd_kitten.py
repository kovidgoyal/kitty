#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import errno
import fnmatch
import itertools
import os
import random
import shutil
import stat
import tempfile
import uuid
from base64 import standard_b64encode
from functools import partial
from urllib.parse import unquote, urlparse

from kitty.constants import kitten_exe
from kitty.fast_data_types import (
    DND_CODE,
    GLFW_DRAG_OPERATION_COPY,
    GLFW_DRAG_OPERATION_MOVE,
    dnd_set_test_write_func,
    dnd_test_cleanup_fake_window,
    dnd_test_create_fake_window,
    dnd_test_drag_finish,
    dnd_test_drag_get_data,
    dnd_test_drag_notify,
    dnd_test_fake_drop_data,
    dnd_test_fake_drop_event,
    dnd_test_force_drag_dropped,
    dnd_test_probe_state,
    dnd_test_start_drag_offer,
)
from kitty.utils import as_file_url

from . import PTY, BaseTest
from .dnd import WriteCapture


class Capture(WriteCapture):

    def __call__(self, window_id: int, data: bytes) -> None:
        self.pty.write_to_child(data)


def create_fs(base, include_toplevel_working_symlink=True):
    join = partial(os.path.join, base)
    def w(sz, *path):
        if sz == 0:
            sz = random.randint(5713, 9879)
        with open(join(*path), 'wb') as f:
            f.write(b'x' * sz)
    os.makedirs(join('d1', 'sd', 'ssd'))
    os.mkdir(join('d2'))
    os.symlink('/' + str(uuid.uuid4()), join('s1'))  # non-existent
    if include_toplevel_working_symlink:
        os.symlink('d1', join('sd'))
    os.symlink('/', join('d1', 'sa'))  # absolute symlink in sub dir
    os.symlink('../d1', join('d1', 'sr'))
    w(4096 * 3 + 113, 'some-image.png')
    w(0, 'd1', 'f1')
    w(0, 'd1', 'f2')
    w(0, 'd1', 'sd', 'f1')
    w(0, 'd1', 'sd', 'ssd', 'f1')
    os.symlink('../moose', join('d1', 'sd', 'ssd', 's1'))


class TestDnDKitten(BaseTest):

    def assert_trees_equal(self, a: str, b: str, ignored='.dnd-kitten-drop-*'):
        a_name = os.path.relpath(a, self.test_dir)
        b_name = os.path.relpath(b, self.test_dir)
        entries_a = list(itertools.filterfalse(lambda x: fnmatch.fnmatch(x, ignored), os.listdir(a)))
        entries_b = list(itertools.filterfalse(lambda x: fnmatch.fnmatch(x, ignored), os.listdir(b)))
        self.assertEqual(set(entries_a), set(entries_b), f'readdir() different for {a_name} vs {b_name}')
        for x in entries_a:
            ca, cb = os.path.join(a, x), os.path.join(b, x)
            sta, stb = os.lstat(ca), os.lstat(cb)
            self.assertEqual(
                stat.S_IFMT(sta.st_mode), stat.S_IFMT(stb.st_mode), f'type mismatch for {a_name}/{x} vs {b_name}/{x}')
            if stat.S_ISDIR(sta.st_mode):
                self.assert_trees_equal(ca, cb)
            elif stat.S_ISLNK(sta.st_mode):
                self.assertEqual(os.readlink(ca), os.readlink(cb))
            elif stat.S_ISREG(sta.st_mode):
                self.assert_files_have_same_content(ca, cb)

    def setUp(self):
        capture = Capture()
        dnd_set_test_write_func(capture)
        os_window_id, window_id = dnd_test_create_fake_window()
        capture.window_id = window_id
        capture.os_window_id = os_window_id
        self.capture = capture
        self.test_dir = os.path.realpath(self.enterContext(tempfile.TemporaryDirectory()))
        self.kitten_wd = os.path.join(self.test_dir, 'kitten')
        os.mkdir(self.kitten_wd)
        self.src_data_dir = os.path.join(self.test_dir, 'src')
        os.mkdir(self.src_data_dir)
        self.messages_from_kitten = ''
        self.set_options({'tab_bar_style': 'hidden'})

    def send_dnd_command_to_kitten(self, payload=b'', as_base64=False, flush=False, t='T', **metadata):
        header = f'\x1b]{DND_CODE};'
        metadata['t'] = t
        for k, v in metadata.items():
            header = header + f'{k}={v}:'
        self.pty.write_to_child(header.encode())
        if not payload:
            self.pty.write_to_child(b'\x1b\\', flush=flush)
            return
        if isinstance(payload, str):
            payload = payload.encode()
        payload = memoryview(standard_b64encode(payload) if as_base64 else payload)
        for i in range(0, len(payload), 4096):
            end = i + 4096
            is_last = end >= len(payload)
            chunk = payload[i:min(i+4096, len(payload))]
            if i == 0:
                self.pty.write_to_child(f'm={0 if is_last else 1};'.encode())
            else:
                self.pty.write_to_child(f'\x1b]{DND_CODE};m={0 if is_last else 1};'.encode())
            self.pty.write_to_child(chunk)
            self.pty.write_to_child(b'\x1b\\', flush=is_last and flush)

    def finish_setup(self, remote_client: bool = False, cli_args = ()):
        cmd = [kitten_exe(), 'dnd']
        cmd += list(cli_args)
        self.pty = self.enterContext(PTY(argv=cmd, cwd=self.kitten_wd, rows=25, columns=80, window_id=self.capture.window_id))
        self.capture.pty = self.pty
        self.pty.callbacks.printbuf = self
        self.screen = self.pty.screen
        self.reset_kitten(remote_client, clear_tdir=False)
        self.assertTrue(self.probe_state('drop_wanted'))
        self.assertEqual(remote_client, self.probe_state('drop_is_remote_client'))
        if self.probe_state('drag_can_offer'):
            self.assertEqual(remote_client, self.probe_state('drag_is_remote_client'))

    def reset_kitten(self, remote_client: bool, clear_tdir=True):
        if clear_tdir:
            self.send_dnd_command_to_kitten('PING')
            self.wait_for_responses('PONG')
            shutil.rmtree(self.kitten_wd)
            os.mkdir(self.kitten_wd)
            shutil.rmtree(self.src_data_dir)
            os.mkdir(self.src_data_dir)
        self.send_dnd_command_to_kitten('SETUP_REMOTE' if remote_client else 'SETUP_LOCAL')
        self.wait_for_responses('SETUP_DONE')

    def get_button_geometry(self, are_present: bool = True):
        self.send_dnd_command_to_kitten('GEOMETRY')
        self.pty.wait_till(lambda: bool(self.messages_from_kitten))
        self.assertTrue(self.messages_from_kitten.startswith('GEOMETRY') and self.messages_from_kitten.endswith('\n'),
                        f'Unexpected messages from kitten: {self.messages_from_kitten!r}')
        q, self.messages_from_kitten = self.messages_from_kitten.rstrip(), ''
        parts = tuple(map(int, q.split(':')[1:]))
        copy, move = parts[:4], parts[4:]
        if are_present:
            self.assertGreater(copy[2], 4)
            self.assertGreater(move[2], 4)
        else:
            self.assertEqual(copy, (0,0,0,0))
            self.assertEqual(move, (0,0,0,0))
        return copy, move

    def append(self, text):
        self.messages_from_kitten += text

    def wait_for_responses(self, *responses, timeout=10):
        q = '\n'.join(responses)
        def wait_till():
            return q == self.messages_from_kitten.strip()
        try:
            self.pty.wait_till(wait_till, timeout, lambda: f'Responses so far: Expected:\n{q!r}\nActual:\n{self.messages_from_kitten.strip()!r}\n')
        finally:
            self.messages_from_kitten = ''

    def wait_for_state(self, q, expected, timeout=10):
        self.pty.wait_till(lambda: self.probe_state(q) == expected, timeout, lambda: f'{q}: {self.probe_state(q)!r}')

    def probe_state(self, which: str):
        return dnd_test_probe_state(self.capture.window_id, which)

    def roundtrip(self):
        self.send_dnd_command_to_kitten('PING')
        self.wait_for_responses('PONG')

    def exit_kitten(self):
        self.pty.write_to_child('\x1b[27u')  # ]
        self.pty.wait_till_child_exits(require_exit_code=0)

    def tearDown(self):
        dnd_set_test_write_func(None)
        dnd_test_cleanup_fake_window(self.capture.os_window_id)
        self.capture = None
        self.screen = None
        self.pty = None

    def test_dnd_kitten_drop(self):
        img_drop_path = 'images/image.png'
        self.finish_setup(cli_args=(f'--drop=image/png:{img_drop_path}', '--confirm-drop-overwrite'))
        with self.subTest(remote=False):
            self.dnd_kitten_drop(False, img_drop_path)
        self.reset_kitten(True)
        with self.subTest(remote=True):
            self.dnd_kitten_drop(True, img_drop_path)
        self.exit_kitten()

    def dnd_kitten_drop(self, remote_client, img_drop_path):
        copy, move = self.get_button_geometry()
        all_mimes = 'text/uri-list a/b c/d'
        for b, expected in ((copy, GLFW_DRAG_OPERATION_COPY), (move, GLFW_DRAG_OPERATION_MOVE)):
            dnd_test_fake_drop_event(self.capture.window_id, False, all_mimes.split(), b[0] + 1, b[1] + 1)
            self.wait_for_state('drop_action', expected)
            self.assertEqual('text/uri-list', self.probe_state('drop_mimes').rstrip('\x00'))
        self.send_dnd_command_to_kitten('DROP_MIMES')
        self.wait_for_responses(all_mimes)
        dnd_test_fake_drop_event(self.capture.window_id, False)
        self.send_dnd_command_to_kitten('DROP_MIMES')
        self.wait_for_responses('')
        large_mimes = ((all_mimes + ' ') * 300).rstrip()
        self.assertGreater(len(large_mimes), 4096)
        dnd_test_fake_drop_event(self.capture.window_id, False, large_mimes.split(), copy[0] + 1, copy[1] + 1)
        self.wait_for_state('drop_action', GLFW_DRAG_OPERATION_COPY)
        self.send_dnd_command_to_kitten('DROP_MIMES')
        self.wait_for_responses(large_mimes)
        del large_mimes
        dnd_test_fake_drop_event(self.capture.window_id, False)
        self.send_dnd_command_to_kitten('DROP_MIMES')
        self.wait_for_responses('')
        all_mimes += ' image/png'
        dnd_test_fake_drop_event(self.capture.window_id, False, all_mimes.split(), copy[0] + 1, copy[1] + 1)
        self.wait_for_state('drop_action', GLFW_DRAG_OPERATION_COPY)
        self.assertEqual('text/uri-list\x00image/png', self.probe_state('drop_mimes').rstrip('\x00'))
        dnd_test_fake_drop_event(self.capture.window_id, True, all_mimes.split(), copy[0] + 1, copy[1] + 1)
        self.send_dnd_command_to_kitten('DROP_MIMES')
        self.wait_for_responses(all_mimes)
        self.assertEqual('text/uri-list\x00image/png', self.probe_state('drop_mimes').rstrip('\x00'))
        self.wait_for_state('drop_data_requests', ((1,0,0), (4,0,0)))
        self.assertEqual('text/uri-list', self.probe_state('drop_getting_data_for_mime'))
        create_fs(self.src_data_dir)
        uri_list, path_list = [], []
        for x in sorted(os.listdir(self.src_data_dir)):
            uri_list.append(as_file_url(self.src_data_dir, x))
        uri_list = ['moose:cow', '# file:///frog/march'] + uri_list
        uri_list.insert(3, 'ignore://me')
        for x in uri_list:
            if x.startswith('#'):
                continue
            if x.startswith('file://'):
                path_list.append(unquote(urlparse(x).path))
            else:
                path_list.append('')
        dnd_test_fake_drop_data(self.capture.window_id, 'text/uri-list', '\r\n'.join(uri_list).encode())
        self.assertEqual('image/png', self.probe_state('drop_getting_data_for_mime'))

        def send_file_in_chunks(f, mime, sz=3072):
            while True:
                chunk = f.read(sz)
                if not chunk:
                    break
                dnd_test_fake_drop_data(self.capture.window_id, mime, chunk, 0, True)
            dnd_test_fake_drop_data(self.capture.window_id, mime, b'')

        self.send_dnd_command_to_kitten('DROP_IS_REMOTE')
        self.wait_for_responses(str(remote_client))

        with open(os.path.join(self.src_data_dir, 'some-image.png'), 'rb') as f:
            send_file_in_chunks(f, 'image/png', 1117)

        self.send_dnd_command_to_kitten('DROP_URI_LIST')
        self.wait_for_responses('|'.join(path_list))
        jn = os.path.join
        self.assert_files_have_same_content(jn(self.src_data_dir, 'some-image.png'), jn(self.kitten_wd, img_drop_path))
        shutil.rmtree(os.path.dirname(jn(self.kitten_wd, img_drop_path)))
        self.wait_for_state('last_drop_action', GLFW_DRAG_OPERATION_COPY)
        self.wait_for_state('drop_action', 0)
        self.assert_trees_equal(self.src_data_dir, self.kitten_wd)

        # ---- edge case: blank lines in text/uri-list are treated as empty entries ----
        # RFC 2483 allows blank lines; parse_uri_list should skip them cleanly.
        with tempfile.NamedTemporaryFile(dir=self.src_data_dir, suffix='.txt', delete=False) as tf:
            tf.write(b'edge case blank line test')
            edge_file = tf.name
        blank_line_uri_list = ('\r\n' + as_file_url(self.src_data_dir, os.path.basename(edge_file)) + '\r\n\r\n').encode()
        dnd_test_fake_drop_event(self.capture.window_id, False, ['text/uri-list'], copy[0]+1, copy[1]+1)
        self.wait_for_state('drop_action', GLFW_DRAG_OPERATION_COPY)
        dnd_test_fake_drop_event(self.capture.window_id, True, ['text/uri-list'], copy[0]+1, copy[1]+1)
        self.wait_for_state('drop_data_requests', ((1, 0, 0),))
        dnd_test_fake_drop_data(self.capture.window_id, 'text/uri-list', blank_line_uri_list)
        self.wait_for_state('drop_action', 0)
        # The file should have been copied despite surrounding blank lines in the URI list.
        self.assertTrue(os.path.exists(jn(self.kitten_wd, os.path.basename(edge_file))),
                        'File from URI list with surrounding blank lines should be copied to destination')
        os.unlink(edge_file)

        # ---- overwrite confirmation: Enter key allows the overwrite ----
        # kitten_wd already has 'some-image.png'; dropping the same filename again triggers confirmation.
        enter_content = b'overwrite-enter-test-content'
        overwrite_uri = (as_file_url(self.src_data_dir, 'some-image.png') + '\r\n').encode()

        def do_overwrite_drop(src_content, key_press, action=GLFW_DRAG_OPERATION_COPY):
            with open(jn(self.src_data_dir, 'some-image.png'), 'wb') as f:
                f.write(src_content)
            orig_content = b'content-to-be-overwritten'
            path = jn(self.kitten_wd, 'some-image.png')
            os.unlink(path)
            with open(path, 'wb') as f:
                f.write(orig_content)
            expected_dest_content = src_content if action == GLFW_DRAG_OPERATION_COPY else orig_content
            dnd_test_fake_drop_event(self.capture.window_id, False, ['text/uri-list'], copy[0]+1, copy[1]+1)
            self.wait_for_state('drop_action', GLFW_DRAG_OPERATION_COPY)
            dnd_test_fake_drop_event(self.capture.window_id, True, ['text/uri-list'], copy[0]+1, copy[1]+1)
            self.wait_for_state('drop_data_requests', ((1, 0, 0),))
            dnd_test_fake_drop_data(self.capture.window_id, 'text/uri-list', overwrite_uri)
            self.pty.wait_till(lambda: 'overwrite existing' in self.pty.screen_contents())
            self.pty.write_to_child(key_press)
            self.wait_for_state('last_drop_action', action)
            self.wait_for_state('drop_action', 0)
            with open(jn(self.kitten_wd, 'some-image.png'), 'rb') as f:
                self.assertEqual(expected_dest_content, f.read())

        do_overwrite_drop(enter_content, '\x1b[13u')
        do_overwrite_drop(b'overwrite-esc-test-content', '\x1b[27u', 0)  # ]]]
        # After rejection the staged file must be removed immediately, not left in the temp dir.
        self.roundtrip()
        self.assert_no_staged_files()

        # ---- move operation: source items deleted for local client only ----
        move_file = jn(self.src_data_dir, 'move_test.txt')
        move_dir = jn(self.src_data_dir, 'move_test_dir')
        move_link = jn(self.src_data_dir, 'move_test_link')
        os.makedirs(move_dir)
        with open(jn(move_dir, 'inside.txt'), 'wb') as f:
            f.write(b'nested file in move dir')
        with open(move_file, 'wb') as f:
            f.write(b'move test content')
        os.symlink('nonexistent_target', move_link)
        move_uri = (
            as_file_url(self.src_data_dir, 'move_test.txt') + '\r\n' +
            as_file_url(self.src_data_dir, 'move_test_dir') + '\r\n' +
            as_file_url(self.src_data_dir, 'move_test_link') + '\r\n'
        ).encode()
        dnd_test_fake_drop_event(self.capture.window_id, False, ['text/uri-list'], move[0]+1, move[1]+1)
        self.wait_for_state('drop_action', GLFW_DRAG_OPERATION_MOVE)
        dnd_test_fake_drop_event(self.capture.window_id, True, ['text/uri-list'], move[0]+1, move[1]+1)
        self.wait_for_state('drop_data_requests', ((1, 0, 0),))
        dnd_test_fake_drop_data(self.capture.window_id, 'text/uri-list', move_uri)
        self.wait_for_state('last_drop_action', GLFW_DRAG_OPERATION_MOVE)
        self.wait_for_state('drop_action', 0)
        self.roundtrip()
        if remote_client:
            # Remote move: source items must NOT be deleted (the source app handles deletion)
            self.assertTrue(os.path.exists(move_file), 'remote move: source file must not be deleted')
            self.assertTrue(os.path.isdir(move_dir), 'remote move: source directory must not be deleted')
            self.assertTrue(os.path.lexists(move_link), 'remote move: source symlink must not be deleted')
        else:
            # Local move: source items must be deleted after successful move
            self.assertFalse(os.path.exists(move_file), 'local move: source file must be deleted')
            self.assertFalse(os.path.exists(move_dir), 'local move: source directory must be deleted')
            self.assertFalse(os.path.lexists(move_link), 'local move: source symlink must be deleted')

    def assert_files_have_same_content(self, a, b):
        with open(a, 'rb') as fa, open(b, 'rb') as fb:
            self.assertEqual(fa.read(), fb.read(), f'{a} ({os.path.getsize(a)}) != {b} ({os.path.getsize(b)})')

    def assert_no_staged_files(self):
        '''Assert that no dropped files linger in any staging subdirectory.'''
        for entry in os.listdir(self.kitten_wd):
            if fnmatch.fnmatch(entry, '.dnd-kitten-drop-*'):
                base = os.path.join(self.kitten_wd, entry)
                for sub in os.listdir(base):
                    sub_path = os.path.join(base, sub)
                    if os.path.isdir(sub_path):
                        leftover = os.listdir(sub_path)
                        self.assertEqual(
                            [], leftover,
                            f'Staged files must not remain in temp dir after drop is finalised: {sub_path}: {leftover}')

    def _do_overwrite_no_confirm_drop(self, remote_client):
        '''Drop a file that already exists at the destination without --confirm-drop-overwrite.
        The existing file must be replaced silently and the staging dir must be empty afterwards.'''
        jn = os.path.join
        copy, _ = self.get_button_geometry()

        src_content = b'replacement content from source'
        dest_orig_content = b'original destination content'

        with open(jn(self.src_data_dir, 'overwrite_me.txt'), 'wb') as f:
            f.write(src_content)
        dest_path = jn(self.kitten_wd, 'overwrite_me.txt')
        with open(dest_path, 'wb') as f:
            f.write(dest_orig_content)

        uri_list = (as_file_url(self.src_data_dir, 'overwrite_me.txt') + '\r\n').encode()
        dnd_test_fake_drop_event(self.capture.window_id, False, ['text/uri-list'], copy[0] + 1, copy[1] + 1)
        self.wait_for_state('drop_action', GLFW_DRAG_OPERATION_COPY)
        dnd_test_fake_drop_event(self.capture.window_id, True, ['text/uri-list'], copy[0] + 1, copy[1] + 1)
        self.wait_for_state('drop_data_requests', ((1, 0, 0),))
        dnd_test_fake_drop_data(self.capture.window_id, 'text/uri-list', uri_list)
        self.wait_for_state('last_drop_action', GLFW_DRAG_OPERATION_COPY)
        self.wait_for_state('drop_action', 0)
        self.roundtrip()

        # The existing file at the destination must be replaced with the source content.
        with open(dest_path, 'rb') as f:
            self.assertEqual(
                src_content, f.read(),
                'Existing file must be replaced when --confirm-drop-overwrite is not set')

        # The staging directory must be empty: the file must have been moved, not left behind.
        self.assert_no_staged_files()

    def test_dnd_kitten_overwrite_no_confirm(self):
        '''Without --confirm-drop-overwrite, dropping a file onto an existing file must replace it
        silently and must not leave the dropped file in the temporary staging directory.'''
        self.finish_setup(cli_args=())
        with self.subTest(remote=False):
            self._do_overwrite_no_confirm_drop(False)
        self.reset_kitten(True)
        with self.subTest(remote=True):
            self._do_overwrite_no_confirm_drop(True)
        self.exit_kitten()

    def test_dnd_kitten_drag(self):
        from .graphics import png_data
        drag_thumbnail = os.path.join(self.test_dir, 'drag.png')
        with open(drag_thumbnail, 'wb') as f:
            f.write(png_data)
        img_drag_path = 'image.png'
        def create_files():
            with open(os.path.join(self.kitten_wd, img_drag_path), 'wb') as f:
                self.img_drag_data = os.urandom(10113)
                f.write(self.img_drag_data)
            create_fs(self.src_data_dir)
        create_files()
        tl = tuple(os.path.join(self.src_data_dir, x) for x in os.listdir(self.src_data_dir))
        self.finish_setup(cli_args=(f'--drag-thumbnail={drag_thumbnail}', f'--drag=image/png:{img_drag_path}') + tl) # )))
        with self.subTest(remote_client=False):
            self.dnd_kitten_drag(False, img_drag_path)
        self.reset_kitten(True)
        create_files()
        with self.subTest(remote_client=True):
            self.dnd_kitten_drag(True, img_drag_path)
        self.exit_kitten()
        self.img_drag_data = None

    def read_drag_data(self, mime):
        # self.pty.log_data_flow = True
        ans = b''
        while True:
            try:
                chunk = dnd_test_drag_get_data(self.capture.window_id, mime)
                if not chunk:
                    break
                ans += chunk
            except OSError as err:
                if err.errno == errno.EAGAIN:
                    self.pty.process_input_from_child()
                    continue
                chunk = ans = b''
                raise
        return ans

    def dnd_kitten_drag(self, remote_client, img_drop_path):
        # self.pty.log_data_flow = True
        copy, move = self.get_button_geometry()
        self.wait_for_state('can_offer', True)
        self.wait_for_state('drag_operations', 0)
        def wait_for_drag_active(active=True):
            self.send_dnd_command_to_kitten('DRAG_ACTIVE')
            self.wait_for_responses('DRAG_ACTIVE' if active else 'DRAG_INACTIVE')
            if active:
                self.send_dnd_command_to_kitten('DRAG_OK')
                self.wait_for_responses('DRAG_OK')
        def start_drag(x, y, expected):
            dnd_test_start_drag_offer(self.capture.window_id, x, y)
            wait_for_drag_active()
            self.wait_for_state('drag_operations', expected)
            self.wait_for_state('drag_thumbnail_size', 4)
        def end_drag(canceled=True):
            dnd_test_drag_finish(self.capture.window_id, canceled)
            wait_for_drag_active(False)
            self.wait_for_state('drag_operations', 0)
        start_drag(move[0] + 1, move[1] + 1, 2)
        self.assertEqual(set(self.probe_state('drag_mimes')), {'image/png', 'text/uri-list'})
        end_drag()
        start_drag(copy[0] + 1, copy[1] + 1, 1)
        end_drag()
        start_drag(1, 1, 3)
        dnd_test_drag_notify(self.capture.window_id, 0, 'text/uri-list')
        dnd_test_drag_notify(self.capture.window_id, 1, '', GLFW_DRAG_OPERATION_MOVE)
        dnd_test_force_drag_dropped(self.capture.window_id)
        dnd_test_drag_notify(self.capture.window_id, 2)
        self.send_dnd_command_to_kitten('DRAG_STATUS')
        self.wait_for_responses('text/uri-list:2:true')
        self.assertEqual(self.img_drag_data, self.read_drag_data('image/png'))
        # if remote_client:
        #     self.pty.log_data_flow = True
        uri_list = self.read_drag_data('text/uri-list').decode().splitlines()
        paths = set()
        for line in uri_list:
            line = line.strip()
            if line and not line.startswith('#'):
                purl = urlparse(line)
                if purl.scheme == 'file':
                    paths.add(purl.path)
                    if remote_client:
                        self.assertNotEqual(self.src_data_dir, os.path.dirname(purl.path))
                    else:
                        self.assertEqual(self.src_data_dir, os.path.dirname(purl.path))
        src_items = set(os.listdir(self.src_data_dir))
        self.assertEqual(src_items, {os.path.basename(x) for x in paths})
        if remote_client:
            for actual in paths:
                expected = os.path.join(self.src_data_dir, os.path.basename(actual))
                if os.path.isdir(actual):
                    self.assert_trees_equal(expected, actual)
                elif os.path.islink(actual):
                    self.assertEqual(os.readlink(expected), os.readlink(actual))
                else:
                    self.assert_files_have_same_content(expected, actual)
        src_items_before = set(os.listdir(self.src_data_dir))
        end_drag(False)
        if remote_client:
            # After a move drag finishes, all source files from text/uri-list should be deleted
            for name in src_items_before:
                item_path = os.path.join(self.src_data_dir, name)
                self.assertFalse(os.path.lexists(item_path), f'move drag: {name} should have been deleted from source')
