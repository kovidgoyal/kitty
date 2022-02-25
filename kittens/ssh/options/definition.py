#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

# After editing this file run ./gen-config.py to apply the changes

from kitty.conf.types import Definition


definition = Definition(
    'kittens.ssh',
)

agr = definition.add_group
egr = definition.end_group
opt = definition.add_option

agr('global', 'Global')  # {{{

opt('hostname', '*', option_type='hostname',
    long_text='''
The hostname the following options apply to. A glob pattern to match multiple
hosts can be used. When not specified options apply to all hosts, until the
first hostname specification is found. Note that the hostname this matches
against is the hostname used by the remote computer, not the name you pass
to SSH to connect to it.
'''
    )
egr()  # }}}
