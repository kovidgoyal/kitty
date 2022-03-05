#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

# After editing this file run ./gen-config.py to apply the changes

from kitty.conf.types import Definition


copy_message = '''\
Copy files and directories from the local computer to the remote one. The
specified files are assumed to be relative to the HOME directory and copied
to the HOME on the server. Directories are copied recursively. If absolute paths
are used, they are copied as is.'''

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
hosts can be used. Multiple hostnames can also be specified separated by spaces.
The hostname can include an optional username in the form :code:`user@host`.
When not specified options apply to all hosts, until the
first hostname specification is found. Note that the hostname this matches
against is the hostname used by the remote computer, not the name you pass
to SSH to connect to it. If you wish to include the same basic configuration for many
different hosts, you can do so with the :code:`include` directive (see :doc:`/conf`).
''')

opt('+copy', '', option_type='copy', add_to_default=False, long_text=f'''
{copy_message} For example::

    copy .vimrc .zshrc .config/some-dir

If a file should be copied to some other destination on the remote machine,
use :code:`--dest`::

    copy --dest some-other-name some-file

Glob patterns can be specified to copy multiple files, with :code:`--glob`::

    copy --glob images/*.png

Files can be excluded when copying with :code:`--exclude`::

    copy --glob --exclude *.jpg --exclude *.bmp images/*

Files whose remote name matches the exclude pattern will not be copied.
For more details, see :ref:`ssh_copy_command`.
''')

opt('+env', '', option_type='env', add_to_default=False, long_text='''
Specify environment variables to set on the remote host. Note that
environment variables can refer to each other, so if you use::

    env MYVAR1=a
    env MYVAR2=$MYVAR1/$HOME/b

The value of MYVAR2 will be :code:`a/<path to home directory>/b`. Using
:code:`VAR=` will set it to the empty string and using just :code:`VAR`
will delete the variable from the child process' environment. The definitions
are processed alphabetically. The special value :code:`_kitty_copy_env_var_`
will cause the value of the variable to be copied from the local machine.
''')

opt('interpreter', 'sh', long_text='''
The interpreter to use on the remote host. Must be either a POSIX complaint shell
or a python executable. If the default sh is not available for broken, using
an alternate interpreter can be useful. Note that as the interpreter is used for
bootstrapping, hostname specific values are matched again the hostname from the
command line args rather than the actual remote hostname.
''')

opt('remote_dir', '.local/share/kitty-ssh-kitten', option_type='relative_dir', long_text='''
The location on the remote computer where the files needed for this kitten
are installed. The location is relative to the HOME directory. Absolute paths or paths
that resolve to a location outside the HOME are not allowed.
''')

opt('shell_integration', 'inherit', long_text='''
Control the shell integration on the remote host. See :ref:`shell_integration`
for details on how this setting works. The special value :code:`inherit` means
use the setting from kitty.conf. This setting is useful for overriding
integration on a per-host basis.''')


egr()  # }}}
