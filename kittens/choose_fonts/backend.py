#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

import json
import sys
from typing import Any

from kitty.fonts.common import get_variable_data_for_descriptor
from kitty.fonts.list import create_family_groups


def send_to_kitten(x: Any) -> None:
    sys.stdout.buffer.write(json.dumps(x).encode())
    sys.stdout.buffer.write(b'\n')
    sys.stdout.buffer.flush()


def main() -> None:
    for line in sys.stdin.buffer:
        cmd = json.loads(line)
        action = cmd.get('action', '')
        if action == 'list_monospaced_fonts':
            send_to_kitten(create_family_groups())
        elif action == 'read_variable_data':
            ans = []
            for descriptor in cmd['descriptors']:
                ans.append(get_variable_data_for_descriptor(descriptor))
            send_to_kitten(ans)
        else:
            raise SystemExit(f'Unknown action: {action}')
