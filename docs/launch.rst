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
closed. Simply specify the path to a Python module that specifies callback
functions for the events you are interested in, for example:

.. code-block:: python

    from typing import Any, Dict

    from kitty.boss import Boss
    from kitty.window import Window


    def on_resize(boss: Boss, window: Window, data: Dict[str, Any]) -> None:
        # Here data will contain old_geometry and new_geometry

    def on_focus_change(boss: Boss, window: Window, data: Dict[str, Any])-> None:
        # Here data will contain focused

    def on_close(boss: Boss, window: Window, data: Dict[str, Any])-> None:
        # called when window is closed, typically when the program running in
        # it exits

    def on_set_user_var(boss: Boss, window: Window, data: Dict[str, Any]) -> None:
        # called when a "user variable" is set or deleted on a window. Here
        # data will contain key and value

    def on_title_change(boss: Boss, window: Window, data: Dict[str, Any]) -> None:
        # called when the window title is changed on a window. Here
        # data will contain title and from_child. from_child will be True
        # when a title change was requested via escape code from the program
        # running in the terminal

    def on_cmd_startstop(boss: Boss, window: Window, data: Dict[str, Any]) -> None:
        # called when the shell starts/stops executing a command. Here
        # data will contain is_start, cmdline and time.

Every callback is passed a reference to the global ``Boss`` object as well as
the ``Window`` object the action is occurring on. The ``data`` object is a dict
that contains event dependent data. Some useful methods and attributes for the
``Window`` object are: ``as_text(as_ans=False, add_history=False,
add_wrap_markers=False, alternate_screen=False)`` with which you can get the
contents of the window and its scrollback buffer. Similarly,
``window.child.pid`` is the PID of the processes that was launched
in the window and ``window.id`` is the internal kitty ``id`` of the window.


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
