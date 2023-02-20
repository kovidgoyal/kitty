#!/usr/bin/env python
# License: GPLv3 Copyright: 2023, Kovid Goyal <kovid at kovidgoyal.net>


import os
import subprocess

from kitty.constants import kitten_exe
from kitty.fast_data_types import shm_unlink
from kitty.shm import SharedMemory

from . import BaseTest


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
