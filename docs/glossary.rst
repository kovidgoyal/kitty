:orphan:

Glossary
=========

.. glossary::

   os_window
     kitty has two kinds of windows. Operating System windows, referred to as :term:`OS
     Window <os_window>`, and *kitty windows*. An OS Window consists of one or more kitty
     :term:`tabs <tab>`. Each tab in turn consists of one or more *kitty
     windows* organized in a :term:`layout`.

   tab
     A *tab* refers to a group of :term:`kitty windows <window>`, organized in
     a :term:`layout`. Every :term:`OS Window <os_window>` contains one or more tabs.

   layout
     A *layout* is a system of organizing :term:`kitty windows <window>` in
     groups inside a tab. The layout automatically maintains the size and
     position of the windows, think of a layout as a tiling window manager for
     the terminal. See :doc:`layouts` for details.

   window
     kitty has two kinds of windows. Operating System windows, referred to as :term:`OS
     Window <os_window>`, and *kitty windows*. An OS Window consists of one or more kitty
     :term:`tabs <tab>`. Each tab in turn consists of one or more *kitty
     windows* organized in a :term:`layout`.

   overlay
      An *overlay window* is a :term:`kitty window <window>` that is placed on
      top of an existing kitty window, entirely covering it. Overlays are used
      throughout kitty, for example, to display the :ref:`the scrollback buffer <scrollback>`,
      to display :doc:`hints </kittens/hints>`, for :doc:`unicode input
      </kittens/unicode_input>` etc. Normal overlays are meant for short
      duration popups and so are not considered the :italic:`active window`
      when determining the current working directory or getting input text for
      kittens, launch commands, etc. To create an overlay considered as a
      :italic:`main window` use the :code:`overlay-main` argument to
      :doc:`launch`.

   hyperlinks
      Terminals can have hyperlinks, just like the internet. In kitty you can
      :doc:`control exactly what happens <open_actions>` when clicking on a
      hyperlink, based on the type of link and its URL. See also `Hyperlinks in terminal
      emulators <https://gist.github.com/egmontkob/eb114294efbcd5adb1944c9f3cb5feda>`__.

   kittens
      Small, independent statically compiled command line programs that are designed to run
      inside kitty windows and provide it with lots of powerful and flexible
      features such as viewing images, connecting conveniently to remote
      computers, transferring files, inputting unicode characters, etc.
      They can also be written by users in Python and used to customize and
      extend kitty functionality, see :doc:`kittens_intro` for details.

   easing function
      A function that controls how an animation progresses over time. kitty
      support the `CSS syntax for easing functions
      <https://developer.mozilla.org/en-US/docs/Web/CSS/easing-function>`__.
      Commonly used easing functions are :code:`linear` for a constant rate
      animation and :code:`ease-in-out` for an animation that starts slow,
      becomes fast in the middle and ends slowly. These are used to control
      various animations in kitty, such as :opt:`cursor_blink_interval` and
      :opt:`visual_bell_duration`.

.. _env_vars:

Environment variables
------------------------

Variables that influence kitty behavior
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. envvar:: KITTY_CONFIG_DIRECTORY

   Controls where kitty looks for :file:`kitty.conf` and other configuration
   files. Defaults to :file:`~/.config/kitty`. For full details of the config
   directory lookup mechanism see, :option:`kitty --config`.

.. envvar:: KITTY_CACHE_DIRECTORY

   Controls where kitty stores cache files. Defaults to :file:`~/.cache/kitty`
   or :file:`~/Library/Caches/kitty` on macOS.

.. envvar:: KITTY_RUNTIME_DIRECTORY

   Controls where kitty stores runtime files like sockets. Defaults to
   the :code:`XDG_RUNTIME_DIR` environment variable if that is defined
   otherwise the run directory inside the kitty cache directory is used.

.. envvar:: VISUAL

   The terminal based text editor (such as :program:`vi` or :program:`nano`)
   kitty uses, when, for instance, opening :file:`kitty.conf` in response to
   :sc:`edit_config_file`.

.. envvar:: EDITOR

   Same as :envvar:`VISUAL`. Used if :envvar:`VISUAL` is not set.

.. envvar:: SHELL

   Specifies the default shell kitty will run when :opt:`shell` is set to
   :code:`.`.

.. envvar:: GLFW_IM_MODULE

   Set this to ``ibus`` to enable support for IME under X11.

.. envvar:: KITTY_WAYLAND_DETECT_MODIFIERS

   When set to a non-empty value, kitty attempts to autodiscover XKB modifiers
   under Wayland. This is useful if using non-standard modifiers like hyper. It
   is possible for the autodiscovery to fail; the default Wayland XKB mappings
   are used in this case. See :pull:`3943` for details.

.. envvar:: SSH_ASKPASS

   Specify the program for SSH to ask for passwords. When this is set, :doc:`ssh
   kitten </kittens/ssh>` will use this environment variable by default. See
   :opt:`askpass <kitten-ssh.askpass>` for details.

.. envvar:: KITTY_CLONE_SOURCE_CODE

   Set this to some shell code that will be executed in the cloned window with
   :code:`eval` when :ref:`clone-in-kitty <clone_shell>` is used.

.. envvar:: KITTY_CLONE_SOURCE_PATH

   Set this to the path of a file that will be sourced in the cloned window when
   :ref:`clone-in-kitty <clone_shell>` is used.

.. envvar:: KITTY_DEVELOP_FROM

   Set this to the directory path of the kitty source code and its Python code
   will be loaded from there. Only works with official binary builds.

.. envvar:: KITTY_RC_PASSWORD

   Set this to a pass phrase to use the ``kitten @`` remote control command with
   :opt:`remote_control_password`.


Variables that kitty sets when running child programs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. envvar:: LANG

   This is only set on macOS. If the country and language from the macOS user
   settings form an invalid locale, it will be set to :code:`en_US.UTF-8`.

.. envvar:: PATH

   kitty prepends itself to the PATH of its own environment to ensure the
   functions calling :program:`kitty` will work properly.

.. envvar:: KITTY_WINDOW_ID

   An integer that is the id for the kitty :term:`window` the program is running in.
   Can be used with the :doc:`kitty remote control facility <remote-control>`.

.. envvar:: KITTY_PID

   An integer that is the process id for the kitty process in which the program
   is running. Allows programs to tell kitty to reload its config by sending it
   the SIGUSR1 signal.

.. envvar:: KITTY_PUBLIC_KEY

   A public key that programs can use to communicate securely with kitty using
   the remote control protocol. The format is: :code:`protocol:key data`.

.. envvar:: WINDOWID

   The id for the :term:`OS Window <os_window>` the program is running in. Only available
   on platforms that have ids for their windows, such as X11 and macOS.

.. envvar:: TERM

   The name of the terminal, defaults to ``xterm-kitty``. See :opt:`term`.

.. envvar:: TERMINFO

   Path to a directory containing the kitty terminfo database. Or the terminfo
   database itself encoded in base64. See :opt:`terminfo_type`.

.. envvar:: KITTY_INSTALLATION_DIR

   Path to the kitty installation directory.

.. envvar:: COLORTERM

   Set to the value ``truecolor`` to indicate that kitty supports 16 million
   colors.

.. envvar:: KITTY_LISTEN_ON

   Set when the :doc:`remote control <remote-control>` facility is enabled and
   the a socket is used for control via :option:`kitty --listen-on` or :opt:`listen_on`.
   Contains the path to the socket. Avoid the need to use :option:`kitten @ --to` when
   issuing remote control commands. Can also be a file descriptor of the form
   fd:num instead of a socket address, in which case, remote control
   communication should proceed over the specified file descriptor.

.. envvar:: KITTY_PIPE_DATA

   Set to data describing the layout of the screen when running child
   programs using :option:`launch --stdin-source` with the contents of the
   screen/scrollback piped to them.

.. envvar:: KITTY_CHILD_CMDLINE

   Set to the command line of the child process running in the kitty
   window when calling the notification callback program on terminal bell, see
   :opt:`command_on_bell`.

.. envvar:: KITTY_COMMON_OPTS

   Set with the values of some common kitty options when running
   kittens, so kittens can use them without needing to load :file:`kitty.conf`.

.. envvar:: KITTY_SHELL_INTEGRATION

   Set when enabling :ref:`shell_integration`. It is automatically removed by
   the shell integration scripts.

.. envvar:: ZDOTDIR

   Set when enabling :ref:`shell_integration` with :program:`zsh`, allowing
   :program:`zsh` to automatically load the integration script.

.. envvar:: XDG_DATA_DIRS

   Set when enabling :ref:`shell_integration` with :program:`fish`, allowing
   :program:`fish` to automatically load the integration script.

.. envvar:: ENV

   Set when enabling :ref:`shell_integration` with :program:`bash`, allowing
   :program:`bash` to automatically load the integration script.

.. envvar:: KITTY_OS

   Set when using the include directive in kitty.conf. Can take values:
   ``linux``, ``macos``, ``bsd``.

.. envvar:: KITTY_HOLD

   Set to ``1`` when kitty is running a shell because of the ``--hold`` flag. Can
   be used to specialize shell behavior in the shell rc files as desired.

.. envvar:: KITTY_SIMD

   Set it to ``128`` to use 128 bit vector registers, ``256`` to use 256 bit
   vector registers or any other value to prevent kitty from using SIMD CPU
   vector instructions. Warning, this overrides CPU capability detection so
   will cause kitty to crash with SIGILL if your CPU does not support the
   necessary SIMD extensions.
