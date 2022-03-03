Truly convenient SSH
=========================================

The ssh kitten allows you to login easily to remote servers, and automatically
setup the environment there to be as comfortable as your local shell. You
can specify environment variables to set on the remote server and
files to copy there, making your remote experience just like your
local shell. Additionally, it automatically sets up :ref:`shell_integration` on
the remote server and copies the kitty terminfo database there.

The ssh kitten is a thin wrapper around the traditional `ssh <https://man.openbsd.org/ssh>`__
command line program and supports all the same options and arguments and configuration.
In most scenarios it is in fact a drop in replacement for ``ssh``. To try it
out, simply run:

.. code-block:: sh

    kitty +kitten ssh some-hostname-to-connect-to

You should end up at a shell prompt on the remote server, with shell
integration enabled. If you like it you can add an alias to it in you shell's
rc files:

.. code-block:: sh

    alias s=kitty +kitten ssh

So you can now type just ``s hostname`` to connect.

The ssh kitten can be configured using the :file:`~/.config/kitty/ssh.conf`
file where you can specify environment variables to set on the remote server
and files to copy from your local machine to the remote server. Let's see a
quick example:

.. code-block:: conf

   # Copy the files and directories needed to setup some common tools
   copy .zshrc .vimrc .vim
   # Setup some environment variables
   env SOME_VAR=x
   # COPIED_VAR will have the same value on the remote server as it does locally
   env COPIED_VAR=_kitty_copy_env_var_

   # Create some per hostname settings
   hostname *.myservers.net
   copy env-files
   env SOMETHING=else

   hostname somehost.org
   copy --dest=foo/bar some-file
   copy --glob some/files.*


See below for full details on the syntax and options of :file:`ssh.conf`.


.. include:: /generated/conf-kitten-ssh.rst


.. _ssh_copy_command:

The copy command
--------------------

.. include:: /generated/ssh-copy.rst
