#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import hashlib
import hmac
from contextlib import suppress
from functools import lru_cache

from kitty.constants import is_macos


@lru_cache(maxsize=8)
def machine_id(salt: str = '') -> str:
    mid = b''
    if is_macos:
        from kitty.fast_data_types import cocoa_get_machine_id
        mid = cocoa_get_machine_id().rstrip().encode()
    else:
        with suppress(OSError), open('/etc/machine-id', 'rb') as f:
            mid = f.read().rstrip()
    if not salt:
        return mid.decode()
    hmac_obj = hmac.new(salt.encode(), mid, hashlib.sha256)
    return hmac_obj.hexdigest()
