#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os

is_ci = os.environ.get('CI') == 'true'


def in_isolated_test_env() -> bool:
    """Whether HOME and the XDG dirs point at the throwaway directory created by env_for_python_tests()."""
    return 'KT_ORIGINAL_HOME' in os.environ
