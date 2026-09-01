#!/usr/bin/env python
# License: GPLv3 Copyright: 2023, Kovid Goyal <kovid at kovidgoyal.net>


import os
import subprocess

from kitty.constants import kitten_exe
from kitty.fast_data_types import shm_unlink
from kitty.shm import SharedMemory

from .base import BaseTest


class SHMTest(BaseTest):
    def test_shm_with_kitten(self):
        data = os.urandom(333)
        with SharedMemory(size=363) as shm:
            shm.write_data_with_size(data)
            cp = subprocess.run([kitten_exe(), '__pytest__', 'shm', 'read', shm.name], stdout=subprocess.PIPE)
            self.assertEqual(cp.returncode, 0)
            self.assertEqual(cp.stdout, data)
            self.assertRaises(FileNotFoundError, shm_unlink, shm.name)
        cp = subprocess.run([kitten_exe(), '__pytest__', 'shm', 'write'], input=data, stdout=subprocess.PIPE)
        self.assertEqual(cp.returncode, 0)
        name = cp.stdout.decode().strip()
        with SharedMemory(name=name, unlink_on_exit=True) as shm:
            q = shm.read_data_with_size()
            self.assertEqual(data, q)

    def test_shm_ownership_verification(self):
        with SharedMemory(size=64, unlink_on_exit=True) as shm:
            shm.verify_owner_and_mode()
            for mode in (0o644, 0o400, 0o660):
                os.fchmod(shm.fileno(), mode)
                with SharedMemory(name=shm.name, readonly=True) as shm2:
                    self.assertRaises(ValueError, shm2.verify_owner_and_mode)
            os.fchmod(shm.fileno(), 0o600)
            with SharedMemory(name=shm.name, readonly=True) as shm2:
                shm2.verify_owner_and_mode()
