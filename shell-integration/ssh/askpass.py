#!/usr/bin/env -S kitty +launch
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import struct
import sys

from kitty.shm import SharedMemory

msg = sys.argv[-1]
prompt = os.environ.get('SSH_ASKPASS_PROMPT', '')
is_confirm = prompt == 'confirm'
ask_cmdline = ['-m', msg, '--type', 'yesno' if is_confirm else 'password']
if is_confirm:
    ask_cmdline += ['--default', 'y']
data = json.dumps(ask_cmdline).encode('utf-8')
sz = struct.pack('>I', len(data))
with SharedMemory(size=len(data) + len(sz) + 1, unlink_on_exit=True, prefix=f'askpass-{os.getpid()}-') as shm, open(os.ctermid(), 'wb') as tty:
    shm.write(b'\0')
    shm.write(sz)
    shm.write(data)
    shm.flush()
    print(f'\x1bP@kitty-ask|{shm.name}\x1b\\', flush=True)
