.. _shell_integration:

Shell integration
-------------------

kitty has the ability to integrate closely within common shells, such as `zsh
<https://www.zsh.org/>`__, `fish <https://fishshell.com>`__ and `bash
<https://www.gnu.org/software/bash/>`__ to enable features such as jumping to
previous prompts in the scrollback, viewing the output of the last command in
:program:`less`, using the mouse to move the cursor while editing prompts, etc.

.. versionadded:: 0.24.0

Features
-------------

* Open the output of the last command in a pager such as :program:`less`
  (:sc:`show_last_command_output`)

* Jump to the previous/next prompt in the scrollback
  (:sc:`scroll_to_previous_prompt` /  :sc:`scroll_to_next_prompt`)

* Click with the mouse anywhere in the current command to move the cursor there

* Hold :kbd:`Ctrl+Shift` and right-click on any command output in the scrollback
  to view it in a pager

* The current working directory or the command being executed are automatically
  displayed in the kitty window titlebar/tab title

* The text cursor is changed to a bar when editing commands at the shell prompt

* :ref:`clone_shell` with all environment variables and the working directory
  copied

* :ref:`Edit files in new kitty windows <edit_file>` even over SSH

* Glitch free window resizing even with complex prompts. Achieved by erasing
  the prompt on resize and allowing the shell to redraw it cleanly.

* Sophisticated completion for the :program:`kitty` command in the shell.

* When confirming a quit command if a window is sitting at a shell prompt,
  it is not counted (for details, see :opt:`confirm_os_window_close`)


Configuration
---------------

Shell integration is controlled by the :opt:`shell_integration` option. By
default, all integration features are enabled. Individual features can be turned
off or it can be disabled entirely as well. The :opt:`shell_integration` option
takes a space separated list of keywords:

disabled
    Turn off all shell integration. The shell's launch environment is not
    modified and :envvar:`KITTY_SHELL_INTEGRATION` is not set. Useful for
    :ref:`manual integration <manual_shell_integration>`.

no-rc
    Do not modify the shell's launch environment to enable integration. Useful
    if you prefer to load the kitty shell integration code yourself, either as
    part of :ref:`manually integration <manual_shell_integration>` or because
    you have some other software that sets up shell integration.
    This will still set the :envvar:`KITTY_SHELL_INTEGRATION` environment
    variable when kitty runs the shell.

no-cursor
    Turn off changing of the text cursor to a bar when editing shell command
    line.

no-title
    Turn off setting the kitty window/tab title based on shell state.
    Note that for the fish shell kitty relies on fish's native title setting
    functionality instead.

no-cwd
    Turn off reporting the current working directory. This is used to allow
    :ac:`new_window_with_cwd` and similar to open windows logged into remote
    machines using the :doc:`ssh kitten <kittens/ssh>` automatically with the
    same working directory as the current window.
    Note that for the fish shell this will not disable its built-in current
    working directory reporting.

no-prompt-mark
    Turn off marking of prompts. This disables jumping to prompt, browsing
    output of last command and click to move cursor functionality.

no-complete
    Turn off completion for the kitty command.
    Note that for the fish shell this does not take effect, since fish already
    comes with a kitty completion script.


More ways to browse command output
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

You can add further key and mouse bindings to browse the output of commands
easily. For example to select the output of a command by right clicking the
mouse on the output, define the following in :file:`kitty.conf`:

.. code:: conf

    mouse_map right press ungrabbed mouse_select_command_output

Now, when you right click on the output, the entire output is selected, ready
to be copied.

The feature to jump to previous prompts (
:sc:`scroll_to_previous_prompt` and :sc:`scroll_to_next_prompt`) and mouse
actions (:ac:`mouse_select_command_output` and :ac:`mouse_show_command_output`)
can be integrated with browsing command output as well. For example, define the
following mapping in :file:`kitty.conf`:

.. code:: conf

    map f1 show_last_visited_command_output

Now, pressing :kbd:`F1` will cause the output of the last jumped to command or
the last mouse clicked command output to be opened in a pager for easy browsing.

In addition, You can define shortcut to get the first command output on screen.
For example, define the following in :file:`kitty.conf`:

.. code:: conf

    map f1 show_first_command_output_on_screen

Now, pressing :kbd:`F1` will cause the output of the first command output on
screen to be opened in a pager.

You can also add shortcut to scroll to the last jumped position. For example,
define the following in :file:`kitty.conf`:

.. code:: conf

    map f1 scroll_to_prompt 0


How it works
-----------------

At startup, kitty detects if the shell you have configured (either system wide
or the :opt:`shell` option in :file:`kitty.conf`) is a supported shell. If so,
kitty injects some shell specific code into the shell, to enable shell
integration. How it does so varies for different shells.


.. tab:: zsh

   For zsh, kitty sets the :envvar:`ZDOTDIR` environment variable to make zsh
   load kitty's :file:`.zshenv` which restores the original value of
   :envvar:`ZDOTDIR` and sources the original :file:`.zshenv`. It then loads
   the shell integration code. The remainder of zsh's startup process proceeds
   as normal.

.. tab:: fish

    For fish, to make it automatically load the integration code provided by
    kitty, the integration script directory path is prepended to the
    :envvar:`XDG_DATA_DIRS` environment variable. This is only applied to the
    fish process and will be cleaned up by the integration script after startup.
    No files are added or modified.

.. tab:: bash

    For bash, kitty starts bash in POSIX mode, using the environment variable
    :envvar:`ENV` to load the shell integration script. This prevents bash from
    loading any startup files itself. The loading of the startup files is done
    by the integration script, after disabling POSIX mode. From the perspective
    of those scripts there should be no difference to running vanilla bash.


Then, when launching the shell, kitty sets the environment variable
:envvar:`KITTY_SHELL_INTEGRATION` to the value of the :opt:`shell_integration`
option. The shell integration code reads the environment variable, turns on the
specified integration functionality and then unsets the variable so as to not
pollute the system.

The actual shell integration code uses hooks provided by each shell to send
special escape codes to kitty, to perform the various tasks. You can see the
code used for each shell below:

.. raw:: html

    <details>
    <summary>Click to toggle shell integration code</summary>

.. tab:: zsh

    .. literalinclude:: ../shell-integration/zsh/kitty-integration
        :language: zsh


.. tab:: fish

    .. literalinclude:: ../shell-integration/fish/vendor_conf.d/kitty-shell-integration.fish
        :language: fish
        :force:

.. tab:: bash

    .. literalinclude:: ../shell-integration/bash/kitty.bash
        :language: bash

.. raw:: html

   </details>


Shell integration over SSH
----------------------------

The easiest way to have shell integration work when SSHing into remote systems
is to use the :doc:`ssh kitten <kittens/ssh>`. Simply run::

    kitty +kitten ssh hostname

And, by magic, you will be logged into the remote system with fully functional
shell integration. Alternately, you can :ref:`setup shell integration manually
<manual_shell_integration>`, by copying the kitty shell integration scripts to
the remote server and editing the shell rc files there, as described below.


.. _clone_shell:

Clone the current shell into a new window
-----------------------------------------------

You can clone the current shell into a new kitty window by simply running the
:command:`clone-in-kitty` command, for example:

.. code-block:: sh

    clone-in-kitty
    clone-in-kitty --type=tab
    clone-in-kitty --title "I am a clone"

This will open a new window running a new shell instance but with all
environment variables and the current working directory copied. This even works
over SSH when using :doc:`kittens/ssh`.

The :command:`clone-in-kitty` command takes almost all the same arguments as the
:doc:`launch <launch>` command, so you can open a new tab instead or a new OS
window, etc. Arguments of launch that can cause code execution or that don't
make sense when cloning are ignored. Most prominently, the following options are
ignored: :option:`--allow-remote-control <launch --allow-remote-control>`,
:option:`--copy-cmdline <launch --copy-cmdline>`, :option:`--copy-env <launch
--copy-env>`, :option:`--stdin-source <launch --stdin-source>`,
:option:`--marker <launch --marker>` and :option:`--watcher <launch --watcher>`.

:command:`clone-in-kitty` can be configured to source arbitrary code in the
cloned window using environment variables. It will automatically clone virtual
environments created by the :link:`Python venv module
<https://docs.python.org/3/library/venv.html>` or :link:`Conda
<https://conda.io/>`. In addition, setting the
env var :envvar:`KITTY_CLONE_SOURCE_CODE` to some shell code will cause that
code to be run in the cloned window with :code:`eval`. Similarly, setting
:envvar:`KITTY_CLONE_SOURCE_PATH` to the path of a file will cause that file to
be sourced in the cloned window. This can be controlled by
:opt:`clone_source_strategies`.

:command:`clone-in-kitty` works by asking the shell to serialize its internal
state (mainly CWD and env vars) and this state is transmitted to kitty and
restored by the shell integration scripts in the cloned window.


.. _edit_file:

Edit files in new kitty windows even over SSH
------------------------------------------------

.. code-block:: sh

   edit-in-kitty myfile.txt
   edit-in-kitty --type tab --title "Editing My File" myfile.txt
   # open myfile.txt at line 75 (works with vim, neovim, emacs, nano, micro)
   edit-in-kitty +75 myfile.txt

The :command:`edit-in-kitty` command allows you to seamlessly edit files
in your default :opt:`editor` in new kitty windows. This works even over
SSH (if you use the :doc:`ssh kitten <kittens/ssh>`), allowing you
to easily edit remote files in your local editor with all its bells and
whistles.

The :command:`edit-in-kitty` command takes almost all the same arguments as the
:doc:`launch <launch>` command, so you can open a new tab instead or a new OS
window, etc. Not all arguments are supported, see the discussion in the
:ref:`clone_shell` section above.

In order to avoid remote code execution, kitty will only execute the configured
editor and pass the file path to edit to it.


.. _manual_shell_integration:

Manual shell integration
----------------------------

The automatic shell integration is designed to be minimally intrusive, as such
it wont work for sub-shells, terminal multiplexers, containers, etc.
For such systems, you should setup manual shell integration by adding some code
to your shells startup files to load the shell integration script.

First, in :file:`kitty.conf` set:

.. code-block:: conf

    shell_integration disabled

Then in your shell's rc file, add the lines:

.. tab:: zsh

    .. code-block:: sh

        if test -n "$KITTY_INSTALLATION_DIR"; then
            export KITTY_SHELL_INTEGRATION="enabled"
            autoload -Uz -- "$KITTY_INSTALLATION_DIR"/shell-integration/zsh/kitty-integration
            kitty-integration
            unfunction kitty-integration
        fi

.. tab:: fish

    .. code-block:: fish

        if set -q KITTY_INSTALLATION_DIR
            set --global KITTY_SHELL_INTEGRATION enabled
            source "$KITTY_INSTALLATION_DIR/shell-integration/fish/vendor_conf.d/kitty-shell-integration.fish"
            set --prepend fish_complete_path "$KITTY_INSTALLATION_DIR/shell-integration/fish/vendor_completions.d"
        end


.. tab:: bash

    .. code-block:: sh

        if test -n "$KITTY_INSTALLATION_DIR"; then
            export KITTY_SHELL_INTEGRATION="enabled"
            source "$KITTY_INSTALLATION_DIR/shell-integration/bash/kitty.bash"
        fi

The value of :envvar:`KITTY_SHELL_INTEGRATION` is the same as that for
:opt:`shell_integration`, except if you want to disable shell integration
completely, in which case simply do not set the
:envvar:`KITTY_SHELL_INTEGRATION` variable at all.

In a container, you will need to install the kitty shell integration scripts
and make sure the :envvar:`KITTY_INSTALLATION_DIR` environment variable is set
to point to the location of the scripts.

Integration with other shells
-------------------------------

There exist third-party integrations to use these features for various other
shells:

* Jupyter console and IPython via a patch (:iss:`4475`)
* `xonsh <https://github.com/xonsh/xonsh/issues/4623>`__


Notes for shell developers
-----------------------------

The protocol used for marking the prompt is very simple. You should consider
adding it to your shell as a builtin. Many modern terminals make use of it, for
example: kitty, iTerm2, WezTerm, DomTerm

Just before starting to draw the PS1 prompt send the escape code::

    <OSC>133;A<ST>

Just before starting to draw the PS2 prompt send the escape code::

    <OSC>133;A;k=s<ST>

Just before running a command/program, send the escape code::

    <OSC>133;C<ST>

Here ``<OSC>`` is the bytes ``0x1b 0x5d`` and ``<ST>`` is the bytes ``0x1b
0x5c``. This is exactly what is needed for shell integration in kitty. For the
full protocol, that also marks the command region, see `the iTerm2 docs
<https://iterm2.com/documentation-escape-codes.html>`_.
