#!/usr/bin/env -S kitty +launch
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import sys
import time

from kitty.shm import SharedMemory

msg = sys.argv[-1]
prompt = os.environ.get('SSH_ASKPASS_PROMPT', '')
is_confirm = prompt == 'confirm'
is_fingerprint_check = '(yes/no/[fingerprint])' in msg
q = {
    'message': msg,
    'type': 'confirm' if is_confirm else 'get_line',
    'is_password': not is_fingerprint_check,
}

data = json.dumps(q)
with SharedMemory(
    size=len(data) + 1 + SharedMemory.num_bytes_for_size, unlink_on_exit=True, prefix=f'askpass-{os.getpid()}-') as shm, \
        open(os.ctermid(), 'wb') as tty:
    shm.write(b'\0')
    shm.write_data_with_size(data)
    shm.flush()
    with open(os.ctermid(), 'wb') as f:
        f.write(f'\x1bP@kitty-ask|{shm.name}\x1b\\'.encode('ascii'))
        f.flush()
    while True:
        # TODO: Replace sleep() with a mutex and condition variable created in the shared memory
        time.sleep(0.05)
        shm.seek(0)
        if shm.read(1) == b'\x01':
            break
    response = json.loads(shm.read_data_with_size())
if is_confirm:
    response = 'yes' if response else 'no'
elif is_fingerprint_check:
    if response.lower() in ('y', 'yes'):
        response = 'yes'
    if response.lower() in ('n', 'no'):
        response = 'no'
if response:
    print(response, flush=True)
