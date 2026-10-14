#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

# The state of Claude Code running in kitty windows (working, waiting for the
# user, done), recorded by Claude Code hooks per kitty window.

import json
import os


def status_dir() -> str:
    return os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'), 'kitty-fork', 'claude-status')


def status_for_window(window_id: int) -> str:
    ' One of working, waiting, done or the empty string when unknown '
    try:
        with open(os.path.join(status_dir(), f'{os.getpid()}-{window_id}.json')) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return ''
    state = data.get('state') if isinstance(data, dict) else ''
    return state if state in ('working', 'waiting', 'done') else ''
