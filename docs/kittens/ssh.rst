Truly convenient SSH
=========================================

.. only:: man

   Overview
   ----------------

* Automatic :ref:`shell_integration` on remote hosts

* Easily :ref:`clone local shell/editor config <real_world_ssh_kitten_config>` on remote hosts

* Automatic :opt:`re-use of existing connections <kitten-ssh.share_connections>` to avoid connection setup latency

* Make the kitten binary available in the remote host :opt:`on demand <kitten-ssh.remote_kitty>`

* Easily :opt:`change terminal colors <kitten-ssh.color_scheme>` when connecting to remote hosts

* Automatically :opt:`forward the kitty remote control socket <kitten-ssh.forward_remote_control>` to configured hosts

.. versionadded:: 0.25.0
   Automatic shell integration, file transfer and reuse of connections

.. versionadded:: 0.30.0
   Automatic forwarding of remote control sockets

The ssh kitten allows you to login easily to remote hosts, and automatically
setup the environment there to be as comfortable as your local shell. You can
specify environment variables to set on the remote host and files to copy there,
making your remote experience just like your local shell. Additionally, it
automatically sets up :ref:`shell_integration` on the remote host and copies the
kitty terminfo database there.

The ssh kitten is a thin wrapper around the traditional `ssh <https://man.openbsd.org/ssh>`__
command line program and supports all the same options and arguments and configuration.
In interactive usage scenarios it is a drop in replacement for :program:`ssh`.
To try it out, simply run:

.. code-block:: sh

    kitten ssh some-hostname-to-connect-to

You should end up at a shell prompt on the remote host, with shell integration
enabled. If you like it you can add an alias to it in your shell's rc files:

.. code-block:: sh

    alias s="kitten ssh"

So now you can just type ``s hostname`` to connect.

If you define a mapping in :file:`kitty.conf` such as::

    map f1 new_window_with_cwd

Then, pressing :kbd:`F1` will open a new window automatically logged into the
same host using the ssh kitten, at the same directory.

The ssh kitten can be configured using the :file:`~/.config/kitty/ssh.conf` file
where you can specify environment variables to set on the remote host and files
to copy from the local to the remote host. Let's see a quick example:

.. code-block:: conf

   # Copy the files and directories needed to setup some common tools
   copy .zshrc .vimrc .vim
   # Setup some environment variables
   env SOME_VAR=x
   # COPIED_VAR will have the same value on the remote host as it does locally
   env COPIED_VAR=_kitty_copy_env_var_

   # Create some per hostname settings
   hostname someserver-*
   copy env-files
   env SOMETHING=else

   hostname someuser@somehost
   copy --dest=foo/bar some-file
   copy --glob some/files.*


See below for full details on the syntax and options of :file:`ssh.conf`.
Additionally, you can pass config options on the command line:

.. code-block:: sh

   kitten ssh --kitten interpreter=python servername

The :code:`--kitten` argument can be specified multiple times, with directives
from :file:`ssh.conf`. These override the final options used for the matched host, as if they
had been appended to the end of the matching section for that host in
:file:`ssh.conf`. They apply only to the host being SSHed to by this invocation,
so any :opt:`hostname <kitten-ssh.hostname>` directives are ignored.

.. warning::

   Due to limitations in the design of SSH, any typing you do before the
   shell prompt appears may be lost. So ideally don't start typing till you see
   the shell prompt. 😇


.. _real_world_ssh_kitten_config:

A real world example
----------------------

Suppose you often SSH into a production server, and you would like to setup
your shell and editor there using your custom settings. However, other people
could SSH in as well and you don't want to clobber their settings. Here is how
this could be achieved using the ssh kitten with :program:`zsh` and
:program:`vim` as the shell and editor, respectively:

.. code-block:: conf

   # Have these settings apply to servers in my organization
   hostname myserver-*

   # Setup zsh to read its files from my-conf/zsh
   env ZDOTDIR=$HOME/my-conf/zsh
   copy --dest my-conf/zsh/.zshrc .zshrc
   copy --dest my-conf/zsh/.zshenv .zshenv
   # If you use other zsh init files add them in a similar manner

   # Setup vim to read its config from my-conf/vim
   env VIMINIT=$HOME/my-conf/vim/vimrc
   env VIMRUNTIME=$HOME/my-conf/vim
   copy --dest my-conf/vim .vim
   copy --dest my-conf/vim/vimrc .vimrc


How it works
----------------

The ssh kitten works by having SSH transmit and execute a POSIX sh (or
:opt:`optionally <kitten-ssh.interpreter>` Python) bootstrap script on the
remote host using an :opt:`interpreter <kitten-ssh.interpreter>`. This script
reads setup data over the TTY device, which kitty sends as a Base64 encoded
compressed tarball. The script extracts it and places the :opt:`files <kitten-ssh.copy>`
and sets the :opt:`environment variables <kitten-ssh.env>` before finally
launching the :opt:`login shell <kitten-ssh.login_shell>` with :opt:`shell
integration <kitten-ssh.shell_integration>` enabled. The data is requested by
the kitten over the TTY with a random one time password. kitty reads the request
and if the password matches a password pre-stored in shared memory on the
localhost by the kitten, the transmission is allowed. If your local
`OpenSSH <https://www.openssh.com/>`__ version is >= 8.4 then the data is
transmitted instantly without any roundtrip delay.

.. note::

   When connecting to BSD hosts, it is possible the bootstrap script will fail
   or run slowly, because the default shells are crippled in various ways.
   Your best bet is to install Python on the remote, make sure the login shell
   is something POSIX sh compliant, and use :code:`python` as the
   :opt:`interpreter <kitten-ssh.interpreter>` in :file:`ssh.conf`.


.. note::

   This may or may not work when using terminal multiplexers, depending on
   whether they passthrough the escape codes and if the values of the
   environment variables :envvar:`KITTY_PID` and :envvar:`KITTY_WINDOW_ID` are
   correct in the current session (they can be wrong when connecting to a tmux
   session running in a different window) and the ssh kitten is run in the
   currently active multiplexer window.

.. include:: /generated/conf-kitten-ssh.rst


.. _ssh_copy_command:

The copy command
--------------------

.. include:: /generated/ssh-copy.rst


.. _manual_terminfo_copy:

Copying terminfo files manually
-------------------------------------

Sometimes, the ssh kitten can fail, or maybe you dont like to use it. In such
cases, the terminfo files can be copied over manually to a server with the
following one liner::

    infocmp -a xterm-kitty | ssh myserver tic -x -o \~/.terminfo /dev/stdin

If you are behind a proxy (like Balabit) that prevents this, or you are SSHing
into macOS where the :program:`tic` does not support reading from :file:`STDIN`,
you must redirect the first command to a file, copy that to the server and run :program:`tic`
manually. If you connect to a server, embedded, or Android system that doesn't
have :program:`tic`, copy over your local file terminfo to the other system as
:file:`~/.terminfo/x/xterm-kitty`.

If the server is running a relatively modern Linux distribution and you have
root access to it, you could simply install the ``kitty-terminfo`` package on
the server to make the terminfo files available.

Really, the correct solution for this is to convince the OpenSSH maintainers to
have :program:`ssh` do this automatically, if possible, when connecting to a
server, so that all terminals work transparently.

If the server is running FreeBSD, or another system that relies on termcap
rather than terminfo, you will need to convert the terminfo file on your local
machine by running (on local machine with |kitty|)::

    infocmp -CrT0 xterm-kitty

The output of this command is the termcap description, which should be appended
to :file:`/usr/share/misc/termcap` on the remote server. Then run the following
command to apply your change (on the server)::

    cap_mkdb /usr/share/misc/termcap
