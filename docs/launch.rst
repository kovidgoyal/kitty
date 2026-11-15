The :command:`launch` command
--------------------------------

.. program:: launch


|kitty| has a :code:`launch` action that can be used to run arbitrary programs
in new windows/tabs. It can be mapped to user defined shortcuts in
:file:`kitty.conf`. It is very powerful and allows sending the contents of the
current window to the launched program, as well as many other options.

In the simplest form, you can use it to open a new kitty window running the
shell, as shown below::

    map f1 launch

To run a different program simply pass the command line as arguments to launch::

    map f1 launch vim path/to/some/file

To open a new window with the same working directory as the currently active
window::

    map f1 launch --cwd=current

To open the new window in a new tab::

    map f1 launch --type=tab

To open a window docked to the bottom of the active window, using ten lines,
see :ref:`docks`::

    map f1 launch --type=window-dock --dock-edge=bottom --dock-size=10

To run multiple commands in a shell, use::

    map f1 launch sh -c "ls && exec zsh"

To pass the contents of the current screen and scrollback to the started
process::

    map f1 launch --stdin-source=@screen_scrollback less

There are many more powerful options, refer to the complete list below.

.. note::
    To avoid duplicating launch actions with frequently used parameters, you can
    use :opt:`action_alias` to define launch action aliases. For example::

        action_alias launch_tab launch --cwd=current --type=tab
        map f1 launch_tab vim
        map f2 launch_tab emacs

    The :kbd:`F1` key will now open :program:`vim` in a new tab with the current
    windows working directory.


The piping environment
--------------------------

When using :option:`launch --stdin-source`, the program to which the data is
piped has a special environment variable declared, :envvar:`KITTY_PIPE_DATA`
whose contents are::

   KITTY_PIPE_DATA={scrolled_by}:{cursor_x},{cursor_y}:{lines},{columns}

where ``scrolled_by`` is the number of lines kitty is currently scrolled by,
``cursor_(x|y)`` is the position of the cursor on the screen with ``(1,1)``
being the top left corner and ``{lines},{columns}`` being the number of rows
and columns of the screen.


Special arguments
-------------------

There are a few special placeholder arguments that can be specified as part of
the command line:


``@selection``
    Replaced by the currently selected text.

``@active-kitty-window-id``
    Replaced by the id of the currently active kitty window.

``@line-count``
    Replaced by the number of lines in STDIN. Only present when passing some
    data to STDIN.

``@input-line-number``
    Replaced by the number of lines a pager should scroll to match the current
    scroll position in kitty. See :opt:`scrollback_pager` for details.

``@scrolled-by``
    Replaced by the number of lines kitty is currently scrolled by.

``@cursor-x``
    Replaced by the current cursor x position with 1 being the leftmost cell.

``@cursor-y``
    Replaced by the current cursor y position with 1 being the topmost cell.

``@first-line-on-screen``
    Replaced by the first line on screen. Can be used for pager positioning.

``@last-line-on-screen``
    Replaced by the last line on screen. Can be used for pager positioning.


For example::

    map f1 launch my-program @active-kitty-window-id


.. _watchers:

Watching launched windows
---------------------------

The :option:`launch --watcher` option allows you to specify Python functions
that will be called at specific events, such as when the window is resized or
closed. Note that you can also specify watchers that are loaded for all windows,
via :opt:`watcher`. To create a watcher, specify the path to a Python module
that specifies callback functions for the events you are interested in, for
create :file:`~/.config/kitty/mywatcher.py` and use :option:`launch --watcher` = :file:`mywatcher.py`:

.. code-block:: python

    # ~/.config/kitty/mywatcher.py
    from typing import Any

    from kitty.boss import Boss
    from kitty.window import Window


    def on_load(boss: Boss, data: dict[str, Any]) -> None:
        # This is a special function that is called just once when this watcher
        # module is first loaded, can be used to perform any initialization/one
        # time setup. Any exceptions in this function are printed to kitty's
        # STDERR but otherwise ignored.
        ...

    def on_resize(boss: Boss, window: Window, data: dict[str, Any]) -> None:
        # Here data will contain old_geometry and new_geometry
        # Note that resize is also called the first time a window is created
        # which can be detected as old_geometry will have all zero values, in
        # particular, old_geometry.xnum and old_geometry.ynum will be zero.
        ...

    def on_focus_change(boss: Boss, window: Window, data: dict[str, Any])-> None:
        # Here data will contain focused
        ...

    def on_close(boss: Boss, window: Window, data: dict[str, Any])-> None:
        # called when window is closed, typically when the program running in
        # it exits. data contains reason, cause and confirmed. reason is what
        # was closed and cause is why, one of:
        #   reason='window': only this window was closed, cause is:
        #       'program_exit': the program running in the window exited
        #       'closed': kitty closed the window, for example, because the
        #                 user closed it or its tab or because of a remote
        #                 control command
        #   reason='os_window': the OS window containing this window was
        #       closed, cause is 'closed'
        #   reason='quit': kitty is quitting, cause is:
        #       'action': the quit action, for example, via a keyboard
        #                 shortcut, menu or remote control
        #       'os_request': the OS asked kitty to quit, for example, via
        #                     the Dock on macOS
        #       'logout': the user is logging out or shutting down. On Linux
        #                 this is reported only when
        #                 restore_session_after_logout is enabled, otherwise
        #                 it is reported as 'signal'
        #       'signal': kitty received SIGTERM, SIGINT or SIGHUP
        #       'fatal_error': kitty lost its connection to the display
        #                      server
        #       'unknown': none of the above
        # confirmed is True if the user confirmed closing the window, its
        # tab, its OS window or quitting kitty in a confirmation dialog.
        ...

    def on_set_user_var(boss: Boss, window: Window, data: dict[str, Any]) -> None:
        # called when a "user variable" is set or deleted on a window. Here
        # data will contain key and value
        ...

    def on_title_change(boss: Boss, window: Window, data: dict[str, Any]) -> None:
        # called when the window title is changed on a window. Here
        # data will contain title and from_child. from_child will be True
        # when a title change was requested via escape code from the program
        # running in the terminal
        ...

    def on_cwd_change(boss: Boss, window: Window, data: dict[str, Any]) -> None:
        # called when the program running in the window reports a change in
        # its working directory via the OSC 7 escape code, as done by the
        # kitty shell integration. data contains cwd, the reported directory and
        # host, the hostname from the reported URL (empty if absent). Note that
        # the directory may be on a remote machine, for example, when using the
        # ssh kitten.
        ...

    def on_cmd_startstop(boss: Boss, window: Window, data: dict[str, Any]) -> None:
        # called when the shell starts/stops executing a command. Here
        # data will contain is_start, cmdline and time.
        ...

    def on_program_status_change(boss: Boss, window: Window, data: dict[str, Any]) -> None:
        # called when the program status (OSC 7501) records of the window
        # change. Here data will contain program_status, the list of current
        # records, each a dict with keys: id, state, kind, progress, app,
        # title and msg.
        ...

    def on_color_scheme_preference_change(boss: Boss, window: Window, data: dict[str, Any]) -> None:
        # called when the color scheme preference of this window changes from
        # light to dark or vice versa. data contains is_dark and via_escape_code
        # the latter will be true if the color scheme was changed via escape
        # code received from the program running in the window
        ...

    def on_tab_bar_dirty(boss: Boss, window: Window, data: dict[str, Any]) -> None:
        # called when any changes happen to the tab bar, such a new tabs being
        # created, tab titles changing, tabs moving, etc. Useful to display the
        # tab bar externally to kitty. This is called even if the tab bar is
        # hidden. Note that this is called only in *global watchers*, that is
        # watchers defined in kitty.conf or using the --watcher command line
        # flag. data contains tab_manager which is the object responsible for
        # managing all tabs in a single OS Window.
        ...

    def on_quit(boss: Boss, window: Window, data: dict[str, Any]) -> None:
        # called when kitty is about to quit. This is called in *global watchers*
        # only. It is called twice: once before the quit confirmation dialog is
        # shown (data['confirmed'] will be False) and once after the user has
        # confirmed quitting (data['confirmed'] will be True). Setting
        # data['aborted'] to True will abort the quit in both cases.
        ...


Every callback is passed a reference to the global ``Boss`` object as well as
the ``Window`` object the action is occurring on. The ``data`` object is a dict
that contains event dependent data. You have full access to kitty internals in
the watcher scripts, however kitty internals are not documented/stable so for
most things you are better off using the kitty :doc:`Remote control API </remote-control>`.
Simply call :code:`boss.call_remote_control()`, with the same arguments you
would pass to ``kitten @``. For example:

.. code-block:: python

    def on_resize(boss: Boss, window: Window, data: dict[str, Any]) -> None:
        # send some text to the resized window
        boss.call_remote_control(window, ('send-text', f'--match=id:{window.id}', 'hello world'))

Run, ``kitten @ --help`` in a kitty terminal, to see all the remote control
commands available to you.


.. _launch_wrapper:

Wrapping the programs run in new windows
-------------------------------------------

.. versionadded:: 0.50.1

You can have kitty run the program in every new window via a wrapper command of
your choosing, for example, to open new windows inside the same container or
development environment as the window they are opened from. To do so, create
the file :file:`launch_wrapper.py` in the kitty config directory, defining a
function named ``prefix_for_launch()``. kitty calls it just before starting the
program in a new window and runs the program with the list of strings it returns
placed before the command. Return ``None`` or an empty list to run the program
unchanged. For example:

.. code-block:: python

    # ~/.config/kitty/launch_wrapper.py
    from collections.abc import Sequence

    from kitty.launch_wrapper import LaunchContext


    def in_nix_shell(pid: int) -> bool:
        # Whether a process was started inside a nix develop shell, detected
        # from the environment variables it was started with
        try:
            with open(f'/proc/{pid}/environ', 'rb') as f:
                return b'IN_NIX_SHELL=' in f.read()
        except OSError:
            return False


    def prefix_for_launch(ctx: LaunchContext) -> Sequence[str] | None:
        # Open new windows in the nix develop environment of their working
        # directory, when opened from a window in a nix develop shell
        if ctx.source_pid is not None and in_nix_shell(ctx.source_pid):
            return ['nix', 'develop', '--command']
        return None

The function is passed a ``LaunchContext`` object with the following fields:

``argv``
    The command that will be run, as a tuple of strings
``cwd``
    The working directory the command will run in
``env``
    A read-only mapping of the environment variables the command will be run
    with, including the ones kitty sets for :ref:`shell_integration` and
    :doc:`remote control <remote-control>`
``is_default_shell``
    True if the command is the shell from :opt:`shell`
``window_id``
    The id of the new window
``launch_type``
    The type of the new window, the same as the values of :option:`launch --type`,
    such as ``window``, ``tab``, ``os-window`` or ``overlay``
``source_window_id``
    The id of the window the new one is opened from, or ``None``. This is the
    window the working directory is taken from when using :option:`launch --cwd`
    and the like, otherwise the active window
``source_pid``
    The process id of the foreground process in the source window, or ``None``.
    You can use it to find out the environment the source window is running
    in, by reading files such as :file:`/proc/{pid}/environ`,
    :file:`/proc/{pid}/cgroup` or :file:`/proc/{pid}/cmdline` on Linux.
``user_vars``
    A read-only mapping of the user variables set via :option:`launch --var`.
    Since user variables are saved in :doc:`sessions <sessions>`, you can use
    them to start a restored window via the same wrapper as the original,
    for example, by setting a user variable from a :ref:`watcher <watchers>`.

The wrapper is used for windows created at your request: by the
:doc:`launch <launch>` command, including via :doc:`remote control
<remote-control>` and in :doc:`sessions <sessions>`, by actions such as
:ac:`new_window`, :ac:`new_tab` and :ac:`new_os_window`, the new tab button in
the tab bar, the macOS menus and the first window kitty creates on startup. It
is not used for windows kitty creates internally, such as for kittens, the
scrollback pager, error messages, or the editor run by :program:`edit-in-kitty`.
It is also not used for background processes or programs run via the legacy
`pipe` action.

Keep the following in mind when writing a wrapper:

* The wrapper must run its arguments as the command, with the working directory
  and environment it receives from kitty. In particular, it must pass through
  the environment variables kitty sets, otherwise features such as
  :ref:`shell_integration` and remote control will not work in the new window.
  Use ``ctx.env`` to see what they are.

* kitty may insert its own helper programs between the wrapper and
  ``ctx.argv``, such as :program:`kitten run-shell` to set up shell integration.
  These must be able to run wherever the wrapper runs the command. This is the
  case for wrappers that share the host filesystem, such as :program:`toolbox`,
  :program:`distrobox`, :code:`nix develop -c` and :code:`direnv exec`.

* On macOS, when the shell is run via :program:`/usr/bin/login`, the wrapper
  runs inside it, with the home directory as its working directory. Use
  ``ctx.cwd`` if the wrapper needs to know the actual working directory.

* The function is called synchronously, whenever a window is created, so keep
  it fast. If it fails, the error is reported and the program is run without
  a wrapper, so that you can still open windows to fix it.

* The wrapper is not saved in :doc:`sessions <sessions>`, the function is
  called again when a session is restored.

The file is re-loaded when the kitty config is reloaded, and is ignored when
kitty is run with :option:`kitty --config` = :code:`NONE`.

Why a prefix, rather than a new command and environment?
____________________________________________________________

A prefix can do anything a replacement could, as the wrapper is a program you
control: it can change the environment and working directory before running
the command, or not run it at all. However, kitty needs to know what the
command is, to set up :ref:`shell_integration`, which depends on the shell
being run, to track the processes running in the window, to save the window
in :doc:`sessions <sessions>` and to clone it with :program:`clone-in-kitty`.
With a prefix, kitty keeps knowing the actual command and can skip over
the wrapper when needed. A replacement command would silently break these
features.

Finding executables
-----------------------

When you specify a command to run as just a name rather than an absolute path,
it is searched for in the system-wide :envvar:`PATH` environment variable. Note
that this **may not** be the value of :envvar:`PATH` inside a shell, as shell
startup scripts often change the value of this variable. If it is not found
there, then a system specific list of default paths is searched. If it is still
not found, then your shell is run and the value of :envvar:`PATH` inside the
shell is used.

See :opt:`exe_search_path` for details and how to control this.

Syntax reference
------------------

.. include:: /generated/launch.rst
