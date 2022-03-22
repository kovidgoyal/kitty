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

agr('bootstrap', 'Host bootstrap configuration')  # {{{

opt('hostname', '*', option_type='hostname', long_text='''
The hostname that the following options apply to. A glob pattern to match multiple
hosts can be used. Multiple hostnames can also be specified separated by spaces.
The hostname can include an optional username in the form :code:`user@host`.
When not specified options apply to all hosts, until the
first hostname specification is found. Note that matching of hostname is done against
the name you specify on the command line to connect to the remote computer.
If you wish to include the same basic configuration for many
different hosts, you can do so with the :ref:`include <include>` directive.
''')

opt('interpreter', 'sh', long_text='''
The interpreter to use on the remote host. Must be either a POSIX complaint shell
or a python executable. If the default sh is not available or broken, using
an alternate interpreter can be useful.
''')

opt('remote_dir', '.local/share/kitty-ssh-kitten', option_type='relative_dir', long_text='''
The location on the remote computer where the files needed for this kitten
are installed. The location is relative to the HOME directory. Absolute paths or paths
that resolve to a location outside the HOME are not allowed.
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
egr()  # }}}

agr('shell', 'Login shell environment')  # {{{

opt('shell_integration', 'inherited', long_text='''
Control the shell integration on the remote host. See :ref:`shell_integration`
for details on how this setting works. The special value :code:`inherited` means
use the setting from :file:`kitty.conf`. This setting is useful for overriding
integration on a per-host basis.
''')

opt('login_shell', '', long_text='''
The login shell to execute on the remote host. By default, the remote user account's
login shell is used.
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

opt('cwd', '', long_text='''
The working directory on the remote host to change to. Env vars in this
value are expanded. The default is empty so no changing is done, which
usually means the home directory is used.
''')
egr()  # }}}

agr('ssh', 'SSH configuration')  # {{{

opt('share_connections', 'yes', option_type='to_bool', long_text='''
Within a single kitty instance, all connections to a particular server can be
shared. This reduces startup latency for subsequent connections and means that you have
to enter the password only once. Under the hood, it uses SSH ControlMasters and
these are automatically cleaned up by kitty when it quits.
''')

opt('askpass', 'unless-set', choices=('unless-set', 'ssh', 'native'), long_text='''
Control the program SSH uses to ask for passwords or confirmation of host keys
etc. The default is to use kitty's native askpass, unless the SSH_ASKPASS
environment variable is set. Set it to :code:`ssh` to not interfere with the
normal ssh askpass mechanism at all, which typically means that ssh will prompt
at the terminal. Set it to :code:`native` to always use kitty's native,
built-in askpass implementation. Note that not using the kitty askpass implementation
means that SSH might need to use the terminal before the connection is established
so the kitten cannot use the terminal to send data without an extra roundtrip,
adding to initial connection latency.
''')
egr()  # }}}
