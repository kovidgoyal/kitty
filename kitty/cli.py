#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
from gettext import gettext as _

from .constants import appname, str_version, isosx, defconf
from .layout import all_layouts


def option_parser():
    parser = argparse.ArgumentParser(
        prog=appname,
        description=_('The {} terminal emulator').format(appname)
    )
    a = parser.add_argument
    a(
        '--class',
        default=appname,
        dest='cls',
        help=_('Set the WM_CLASS property')
    )
    a(
        '--config',
        action='append',
        help=_(
            'Specify a path to the config file(s) to use.'
            ' Can be specified multiple times to read multiple'
            ' config files in sequence, which are merged. Default: {}'
        ).format(defconf)
    )
    a(
        '--override',
        '-o',
        action='append',
        help=_(
            'Override individual configuration options, can be specified'
            ' multiple times. Syntax: name=value. For example: {}'
        ).format('-o font_size=20')
    )
    a(
        '--cmd',
        '-c',
        default=None,
        help=_('Run python code in the kitty context')
    )
    a(
        '-d',
        '--directory',
        default='.',
        help=_('Change to the specified directory when launching')
    )
    a(
        '--version',
        '-v',
        action='version',
        version='{} {} by Kovid Goyal'.format(appname, str_version)
    )
    a(
        '--dump-commands',
        action='store_true',
        default=False,
        help=_('Output commands received from child process to stdout')
    )
    if not isosx:
        a(
            '--detach',
            action='store_true',
            default=False,
            help=_('Detach from the controlling terminal, if any')
        )
    a(
        '--replay-commands',
        default=None,
        help=_('Replay previously dumped commands')
    )
    a(
        '--dump-bytes',
        help=_('Path to file in which to store the raw bytes received from the'
               ' child process. Useful for debugging.')
    )
    a(
        '--debug-gl',
        action='store_true',
        default=False,
        help=_('Debug OpenGL commands. This will cause all OpenGL calls'
               ' to check for errors instead of ignoring them. Useful'
               ' when debugging rendering problems.')
    )
    a(
        '--window-layout',
        default=None,
        choices=frozenset(all_layouts.keys()),
        help=_('The window layout to use on startup')
    )
    a(
        '--session',
        default=None,
        help=_(
            'Path to a file containing the startup session (tabs, windows, layout, programs)'
        )
    )
    a(
        '-1', '--single-instance',
        default=False,
        action='store_true',
        help=_(
            'If specified only a single instance of {0} will run. New invocations will'
            ' instead create a new top-level window in the existing {0} instance. This'
            ' allows {0} to share a single sprite cache on the GPU and also reduces'
            ' startup time. You can also have groups of {0} instances by using the'
            ' {1} option.'
        ).format(appname, '--instance-group')
    )
    a(
        '--instance-group',
        default=None,
        help=_(
            'Used in combination with the --single-instance option. All {0} invocations'
            ' with the same --instance-group will result in new windows being created'
            ' in the first {0} instance with that group.'
        ).format(appname)
    )
    a(
        'args',
        nargs=argparse.REMAINDER,
        help=_(
            'The remaining arguments are used to launch a program other than the default shell. Any further options are passed'
            ' directly to the program being invoked.'
        )
    )
    return parser
