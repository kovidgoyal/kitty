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
   hostname someserver-*
   copy env-files
   env SOMETHING=else

   hostname somehost
   copy --dest=foo/bar some-file
   copy --glob some/files.*


See below for full details on the syntax and options of :file:`ssh.conf`.


A real world example
----------------------

Suppose you often SSH into a production server, and you would like to setup
your shell and editor there using your custom settings. However, other people
could SSH in as well and you don't want to clobber their settings. Here is how
this could be achieved using the ssh kitten with zsh and vim as the shell and
editor, respectively:

.. code-block:: conf

   # Have these settings apply to servers in my organization
   hostname myserver-*

   # Setup zsh to read its files from my-conf/zsh
   env ZDOTDIR $HOME/my-conf/zsh
   copy --dest my-conf/zsh/.zshrc .zshrc
   copy --dest my-conf/zsh/.zshenv .zshenv
   # If you use other zsh init files add them in a similar manner

   # Setup vim to read its config from my-conf/vim
   env VIMINIT $HOME/my-conf/vim/vimrc
   env VIMRUNTIME $HOME/my-conf/vim
   copy --dest my-conf/vim .vim
   copy --dest my-conf/vim/vimrc .vimrc


.. include:: /generated/conf-kitten-ssh.rst


.. _ssh_copy_command:

The copy command
--------------------

.. include:: /generated/ssh-copy.rst
