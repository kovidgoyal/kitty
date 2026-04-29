#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

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
    dnd_test_fake_drop_data,
    dnd_test_fake_drop_event,
    dnd_test_probe_state,
)
from kitty.utils import as_file_url

from . import PTY, BaseTest
from .dnd import WriteCapture


class Capture(WriteCapture):

    def __call__(self, window_id: int, data: bytes) -> None:
        self.pty.write_to_child(data)


def create_fs(base, include_toplevel_working_symlink=False):
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

    def wait_for_confirm_pending(self, timeout=10):
        """Poll until the kitten reports that an overwrite confirmation is pending."""
        self.messages_from_kitten = ''
        self.send_dnd_command_to_kitten('CONFIRM_PENDING', flush=True)

        def check():
            if self.messages_from_kitten.strip() == 'True':
                self.messages_from_kitten = ''
                return True
            if self.messages_from_kitten.strip() == 'False':
                # Not yet pending; ask again on the next iteration
                self.messages_from_kitten = ''
                self.send_dnd_command_to_kitten('CONFIRM_PENDING', flush=True)
            return False

        self.pty.wait_till(check, timeout, lambda: 'Timed out waiting for overwrite confirmation to become pending')

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
        create_fs(self.src_data_dir, include_toplevel_working_symlink=not remote_client)
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
        with open(jn(self.src_data_dir, 'some-image.png'), 'wb') as f:
            f.write(enter_content)

        overwrite_uri = (as_file_url(self.src_data_dir, 'some-image.png') + '\r\n').encode()

        def do_overwrite_drop():
            dnd_test_fake_drop_event(self.capture.window_id, False, ['text/uri-list'], copy[0]+1, copy[1]+1)
            self.wait_for_state('drop_action', GLFW_DRAG_OPERATION_COPY)
            dnd_test_fake_drop_event(self.capture.window_id, True, ['text/uri-list'], copy[0]+1, copy[1]+1)
            self.wait_for_state('drop_data_requests', ((1, 0, 0),))
            dnd_test_fake_drop_data(self.capture.window_id, 'text/uri-list', overwrite_uri)

        do_overwrite_drop()
        self.wait_for_confirm_pending()
        self.pty.write_to_child('\x1b[13u')  # Enter key: confirm overwrite
        self.wait_for_state('drop_action', 0)
        with open(jn(self.kitten_wd, 'some-image.png'), 'rb') as f:
            self.assertEqual(f.read(), enter_content,
                             'Enter key should have confirmed the overwrite')

        # ---- overwrite confirmation: Esc key cancels the overwrite ----
        esc_content = b'overwrite-esc-test-content'
        with open(jn(self.src_data_dir, 'some-image.png'), 'wb') as f:
            f.write(esc_content)

        do_overwrite_drop()
        self.wait_for_confirm_pending()
        self.pty.write_to_child('\x1b[27u')  # Esc key: cancel overwrite
        self.wait_for_state('last_drop_action', 0)
        with open(jn(self.kitten_wd, 'some-image.png'), 'rb') as f:
            self.assertEqual(f.read(), enter_content,
                             'Esc key should have cancelled the overwrite; file must be unchanged')

    def assert_files_have_same_content(self, a, b):
        with open(a, 'rb') as fa, open(b, 'rb') as fb:
            self.assertEqual(fa.read(), fb.read(), f'{a} ({os.path.getsize(a)}) != {b} ({os.path.getsize(b)})')
