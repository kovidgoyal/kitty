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

agr('host', 'Host environment')  # {{{

opt('hostname', '*', option_type='hostname',
    long_text='''
The hostname the following options apply to. A glob pattern to match multiple
hosts can be used. When not specified options apply to all hosts, until the
first hostname specification is found. Note that the hostname this matches
against is the hostname used by the remote computer, not the name you pass
to SSH to connect to it.
'''
    )

opt('remote_dir', '.local/share/kitty-ssh-kitten', long_text='''
The location on the remote computer where the files needed for this kitten
are installed. The location is relative to the HOME directory.
'''
    )

opt('+env', '', option_type='env', add_to_default=False, long_text='''
Specify environment variables to set on the remote host. Note that
environment variables can refer to each other, so if you use::

    env MYVAR1=a
    env MYVAR2=$MYVAR1/$HOME/b

The value of MYVAR2 will be :code:`a/<path to home directory>/b`. Using
:code:`VAR=` will set it to the empty string and using just :code:`VAR`
will delete the variable from the child process' environment. The definitions
are processed alphabetically.
''')
egr()  # }}}
