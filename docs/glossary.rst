:orphan:

Glossary
=========

.. glossary::

   os_window
     datty has two kinds of windows. Operating System windows, referred to as :term:`OS
     Window <os_window>`, and *datty windows*. An OS Window consists of one or more datty
     :term:`tabs <tab>`. Each tab in turn consists of one or more *datty
     windows* organized in a :term:`layout`.

   tab
     A *tab* refers to a group of :term:`datty windows <window>`, organized in
     a :term:`layout`. Every :term:`OS Window <os_window>` contains one or more tabs.

   layout
     A *layout* is a system of organizing :term:`datty windows <window>` in
     groups inside a tab. The layout automatically maintains the size and
     position of the windows, think of a layout as a tiling window manager for
     the terminal. See :doc:`layouts` for details.

   window
     datty has two kinds of windows. Operating System windows, referred to as :term:`OS
     Window <os_window>`, and *datty windows*. An OS Window consists of one or more datty
     :term:`tabs <tab>`. Each tab in turn consists of one or more *datty
     windows* organized in a :term:`layout`.

   overlay
      An *overlay window* is a :term:`datty window <window>` that is placed on
      top of an existing datty window, entirely covering it. Overlays are used
      throughout datty, for example, to display the :ref:`the scrollback buffer <scrollback>`,
      to display :doc:`hints </daddies/hints>`, for :doc:`unicode input
      </daddies/unicode_input>` etc. Normal overlays are meant for short
      duration popups and so are not considered the :italic:`active window`
      when determining the current working directory or getting input text for
      daddies, launch commands, etc. To create an overlay considered as a
      :italic:`main window` use the :code:`overlay-main` argument to
      :doc:`launch`.

   hyperlinks
      Terminals can have hyperlinks, just like the internet. In datty you can
      :doc:`control exactly what happens <open_actions>` when clicking on a
      hyperlink, based on the type of link and its URL. See also `Hyperlinks in terminal
      emulators <https://gist.github.com/egmontkob/eb114294efbcd5adb1944c9f3cb5feda>`__.

   daddies
      Small, independent statically compiled command line programs that are designed to run
      inside datty windows and provide it with lots of powerful and flexible
      features such as viewing images, connecting conveniently to remote
      computers, transferring files, inputting unicode characters, etc.
      They can also be written by users in Python and used to customize and
      extend datty functionality, see :doc:`daddies_intro` for details.
      The vast majority of daddies that ship with datty are written in Go,
      with a small Python shim to handle the in-process part of the
      interaction.

   easing function
      A function that controls how an animation progresses over time. datty
      support the `CSS syntax for easing functions
      <https://developer.mozilla.org/en-US/docs/Web/CSS/easing-function>`__.
      Commonly used easing functions are :code:`linear` for a constant rate
      animation and :code:`ease-in-out` for an animation that starts slow,
      becomes fast in the middle and ends slowly. These are used to control
      various animations in datty, such as :opt:`cursor_blink_interval` and
      :opt:`visual_bell_duration`.

   SIMD
      A programming technique that refers to having a single CPU instruction
      process multiple units of data, also called vector programming. Leads to
      large speedups for various data processing tasks.

.. _env_vars:

Environment variables
------------------------

Variables that influence datty behavior
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. envvar:: DATTY_CONFIG_DIRECTORY

   Controls where datty looks for :file:`datty.conf` and other configuration
   files. Defaults to :file:`~/.config/datty`. For full details of the config
   directory lookup mechanism see, :option:`datty --config`.

.. envvar:: DATTY_CACHE_DIRECTORY

   Controls where datty stores cache files. Defaults to :file:`~/.cache/datty`
   or :file:`~/Library/Caches/datty` on macOS.

.. envvar:: DATTY_RUNTIME_DIRECTORY

   Controls where datty stores runtime files like sockets. On macOS, the
   default is the native per-user cache directory returned by
   :code:`getconf DARWIN_USER_CACHE_DIR`. On other platforms, datty uses
   :code:`XDG_RUNTIME_DIR` if defined, otherwise :file:`/run/user/<uid>` if
   accessible, falling back to the :file:`run` directory inside the datty
   cache directory.

.. envvar:: VISUAL

   The terminal based text editor (such as :program:`vi` or :program:`nano`)
   datty uses, when, for instance, opening :file:`datty.conf` in response to
   :sc:`edit_config_file`.

.. envvar:: EDITOR

   Same as :envvar:`VISUAL`. Used if :envvar:`VISUAL` is not set.

.. envvar:: SHELL

   Specifies the default shell datty will run when :opt:`shell` is set to
   :code:`.`.

.. envvar:: GLFW_IM_MODULE

   Set this to ``ibus`` to enable support for IME under X11.

.. envvar:: DATTY_WAYLAND_DETECT_MODIFIERS

   When set to a non-empty value, datty attempts to autodiscover XKB modifiers
   under Wayland. This is useful if using non-standard modifiers like hyper. It
   is possible for the autodiscovery to fail; the default Wayland XKB mappings
   are used in this case. See :pull:`3943` for details.

.. envvar:: SSH_ASKPASS

   Specify the program for SSH to ask for passwords. When this is set, :doc:`ssh
   daddy </daddies/ssh>` will use this environment variable by default. See
   :opt:`askpass <daddy-ssh.askpass>` for details.

.. envvar:: DATTY_CLONE_SOURCE_CODE

   Set this to some shell code that will be executed in the cloned window with
   :code:`eval` when :ref:`clone-in-datty <clone_shell>` is used.

.. envvar:: DATTY_CLONE_SOURCE_PATH

   Set this to the path of a file that will be sourced in the cloned window when
   :ref:`clone-in-datty <clone_shell>` is used.

.. envvar:: DATTY_DEVELOP_FROM

   Set this to the directory path of the datty source code and its Python code
   will be loaded from there. Only works with official binary builds.

.. envvar:: DATTY_RC_PASSWORD

   Set this to a pass phrase to use the ``daddy @`` remote control command with
   :opt:`remote_control_password`.


Variables that datty sets when running child programs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. envvar:: LANG

   This is only set on macOS. If the country and language from the macOS user
   settings form an invalid locale, it will be set to :code:`en_US.UTF-8`.

.. envvar:: PATH

   datty prepends itself to the PATH of its own environment to ensure the
   functions calling :program:`datty` will work properly.

.. envvar:: DATTY_WINDOW_ID

   An integer that is the id for the datty :term:`window` the program is running in.
   Can be used with the :doc:`datty remote control facility <remote-control>`.

.. envvar:: DATTY_PID

   An integer that is the process id for the datty process in which the program
   is running. Allows programs to tell datty to reload its config by sending it
   the SIGUSR1 signal.

.. envvar:: DATTY_PUBLIC_KEY

   A public key that programs can use to communicate securely with datty using
   the remote control protocol. The format is: :code:`protocol:key data`.

.. envvar:: WINDOWID

   The id for the :term:`OS Window <os_window>` the program is running in. Only available
   on platforms that have ids for their windows, such as X11 and macOS.

.. envvar:: TERM

   The name of the terminal, defaults to ``xterm-datty``. See :opt:`term`.

.. envvar:: TERMINFO

   Path to a directory containing the datty terminfo database. Or the terminfo
   database itself encoded in base64. See :opt:`terminfo_type`.

.. envvar:: DATTY_INSTALLATION_DIR

   Path to the datty installation directory.

.. envvar:: COLORTERM

   Set to the value ``truecolor`` to indicate that datty supports 16 million
   colors.

.. envvar:: DATTY_LISTEN_ON

   Set when the :doc:`remote control <remote-control>` facility is enabled and
   the a socket is used for control via :option:`datty --listen-on` or :opt:`listen_on`.
   Contains the path to the socket. Avoid the need to use :option:`daddy @ --to` when
   issuing remote control commands. Can also be a file descriptor of the form
   fd:num instead of a socket address, in which case, remote control
   communication should proceed over the specified file descriptor.

.. envvar:: DATTY_PIPE_DATA

   Set to data describing the layout of the screen when running child
   programs using :option:`launch --stdin-source` with the contents of the
   screen/scrollback piped to them.

.. envvar:: DATTY_CHILD_CMDLINE

   Set to the command line of the child process running in the datty
   window when calling the notification callback program on terminal bell, see
   :opt:`command_on_bell`.

.. envvar:: DATTY_COMMON_OPTS

   Set with the values of some common datty options when running
   daddies, so daddies can use them without needing to load :file:`datty.conf`.

.. envvar:: DATTY_SHELL_INTEGRATION

   Set when enabling :ref:`shell_integration`. It is automatically removed by
   the shell integration scripts.

.. envvar:: DATTY_SI_RUN_COMMAND_AT_STARTUP

   Set this to an expression that the datty shell integration scripts will
   ``eval`` after the shell is started. Note that this environment variable
   is ignored when present in the environment in which datty itself is launched
   in. It is most useful with the ``--env`` flag for the :doc:`launch <launch>`
   action.

.. envvar:: ZDOTDIR

   Set when enabling :ref:`shell_integration` with :program:`zsh`, allowing
   :program:`zsh` to automatically load the integration script.

.. envvar:: XDG_DATA_DIRS

   Set when enabling :ref:`shell_integration` with :program:`fish`, allowing
   :program:`fish` to automatically load the integration script.

.. envvar:: ENV

   Set when enabling :ref:`shell_integration` with :program:`bash`, allowing
   :program:`bash` to automatically load the integration script.

.. envvar:: DATTY_OS

   Set when using the include directive in datty.conf. Can take values:
   ``linux``, ``macos``, ``bsd``.

.. envvar:: DATTY_HOLD

   Set to ``1`` when datty is running a shell because of the ``--hold`` flag. Can
   be used to specialize shell behavior in the shell rc files as desired.

.. envvar:: DATTY_SIMD

   Set it to ``128`` to use 128 bit vector registers, ``256`` to use 256 bit
   vector registers, or ``512`` to use AVX-512 on x86-64. Any other value
   prevents datty from using SIMD CPU vector instructions. Warning, this
   overrides CPU capability detection so will cause datty to crash with SIGILL
   if your CPU does not support the necessary SIMD extensions.
