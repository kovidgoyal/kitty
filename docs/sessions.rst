.. _sessions:

Sessions
=============

kitty has robust support for sessions. A session is basically a simple text
file where you can define kitty windows, tabs and what programs to run in them
as well as how to layout the windows. kitty also supports actions to easily
:ac:`create and switch between existing sessions <goto_session>`, so that you
can move seamlessly from working on one project to another with a couple of keystrokes.

Let's see a quick example to get a feel of how easy it is to create sessions. First,
a session file to develop a project:

.. code-block:: session

    # Set the layout for the current tab
    layout tall
    # Set the working directory for windows in the current tab
    cd ~/path/to/myproject
    # Create the "main" window and run an editor in it to edit the project files
    launch --title "Edit My Project" /usr/bin/nvim
    # Create a side window to run a shell to build or test project
    launch --title "Build My Project"
    # Create another side window to keep an eye on some useful log file
    launch --title "Log for my project" /usr/bin/tail -f /path/to/project/log/file

Save this file as :file:`~/path/to/myproject/launch.kitty-session`. Now when
you want to work on the project, simply run:

.. code-block:: sh

    kitty --session ~/path/to/myproject/launch.kitty-session

You can also set the session in :file:`kitty.conf` via :opt:`startup_session`.

Thus, it is very easy to create sessions and work on projects. To learn how to
create more complex sessions, see :ref:`complex_sessions`.


.. _goto_session:

Creating/Switching to sessions with a keypress
------------------------------------------------

If you like to manage multiple sessions within a single terminal and
easily swap between them, kitty has you covered. You can use the
:ac:`goto_session` action in kitty.conf, like this:

.. code-block:: conf

   # Press F7 and then c to jump to the "cool" project
   map f7>c goto_session ~/path/to/cool/cool.kitty-session
   # Press F7 and then h to jump to the "hot" project
   map f7>h goto_session ~/path/to/hot/hot.kitty-session
   # Browse and select from the list of known projects defined via goto_session commands
   map f7>/ goto_session
   # Same as above, but the sessions are listed alphabetically instead of by most recent
   map f7>/ goto_session --sort-by=alphabetical
   # Go to the previously active session (larger negative numbers jump further back in history)
   map f7>- goto_session -1

In this manner you can define as many projects/sessions as you like and easily
switch between them with a keypress.

You can also close sessions using the :ac:`close_session` action, which closes
all windows in the session with a single keypress.


Displaying the currently active session name
----------------------------------------------

You can display the name of the currently active session file in the kitty tab
bar using :opt:`tab_title_template`. For example, using the value::

    {session_name} {title}

will show you the name of the session file the current tab was loaded from, as
well as the normal tab title. Or alternatively, you can set the tab title
directly to a project name in the session file itself when creating the tab,
like this::

    new_tab My Project Name

.. _complex_sessions:

More complex sessions
-------------------------

If you want to create more complex sessions, with sophisticated layouts, such
as :ref:`splits_layout`, the easiest way is to set up the state you want to
save manually by first starting kitty like this:

.. code-block:: sh

    kitty -o 'map f1 save_as_session --use-foreground-process --relocatable'

Now create whatever splits and tabs you need and start whatever programs such
as editors, REPLs, debuggers, etc. you want to start in each of them. Once
kitty is the way you want it, press the :kbd:`F1` key, and you will be prompted
for a path at which to save the session file. Specify the path and the session
will be saved there with the exact setup you created. The saved file will even
be opened in your editor for you to review, automatically.

If instead, you want to create these by hand, see the example below which shows
all the major keywords you can use in kitty session files:

.. code-block:: session

    # Set the layout for the current tab
    layout tall
    # Set the working directory for windows in the current tab. Relative paths
    # are resolved with respect to the location of this session file.
    cd ~
    # Create a window and run the specified command in it
    launch zsh
    # Create a window with some environment variables set and run vim in it
    launch --env FOO=BAR vim
    # Set the title for the next window
    launch --title "Chat with x" irssi --profile x
    # Run a short lived command and see its output
    launch --hold message-of-the-day

    # Create a new tab
    # The part after new_tab is the optional tab title which will be displayed in
    # the tab bar, if omitted, the title of the active window will be used instead.
    new_tab my tab
    cd somewhere
    # Set the layouts allowed in this tab
    enabled_layouts tall,stack
    # Set the current layout
    layout stack
    launch zsh

    # Create a new OS window
    # Any definitions specified before the first new_os_window will apply to first OS window.
    new_os_window
    # Set new window size to 80x24 cells
    os_window_size 80c 24c
    # Set the --title for the new OS window
    os_window_title my fancy os window
    # Set the --class for the new OS window
    os_window_class mywindow
    # Set the --name for the new OS window
    os_window_name myname
    # Change the OS window state to normal, fullscreen, maximized or minimized
    os_window_state normal
    launch sh
    # Resize the current window (see the resize_window action for details)
    resize_window wider 2
    # Make the current window the active (focused) window in its tab
    focus
    # Make the current OS Window the globally active window
    focus_os_window
    launch emacs

    # Create a complex layout using multiple splits. Creates two columns of
    # windows with two windows in each column. The windows in the first column are
    # split 50:50. In the second column the windows are not evenly split.
    new_tab complex tab
    layout splits
    # First window, set a user variable on it so we can focus it later
    launch --var window=first
    # Create the second column by splitting the first window vertically
    launch --location=vsplit
    # Create the third window in the second column by splitting the second window horizontally
    # Make it take 40% of the height instead of 50%
    launch --location=hsplit --bias=40
    # Go back to focusing the first window, so that we can split it
    focus_matching_window var:window=first
    # Create the final window in the first column
    launch --location=hsplit


.. note::
    The :doc:`launch <launch>` command when used in a session file cannot create
    new OS windows, or tabs.

.. note::
    Environment variables of the form :code:`${NAME}` or :code:`$NAME` are
    expanded in the session file, except in the *arguments* (not options) to the
    launch command. For example:

    .. code-block:: sh

        launch --cwd=$THIS_IS_EXPANDED some-program $THIS_IS_NOT_EXPANDED


Making newly created windows join an existing session
---------------------------------------------------------

Normally, after activating a session, if you create new windows/tabs
they don't belong to the session. If you would prefer to have them belong
to the currently active session, you can use the :ac:`new_window_with_cwd`
and :ac:`new_tab_with_cwd` actions instead, like this::

    map kitty_mod+enter new_window_with_cwd
    map kitty_mod+t new_tab_with_cwd
    map kitty_mod+n new_os_window_with_cwd

This will cause newly created windows and tabs to belong to the currently active
session, if any. Note that adding a window to a session in this way is
temporary, it does not edit the session file. If you wish to update the
session file of the currently active session, you can use the following
mapping for it::

    map f5 save_as_session --relocatable --use-foreground-process --match=session:. .

The two can be combined, using the :ac:`combine` action.
For even more control of what session a window is added to use
the :doc:`launch <launch>` command with the :option:`launch --add-to-session`
flag.


Sessions with remote connections
-------------------------------------

If you use the :doc:`ssh kitten </kittens/ssh>` to connect to remote computers,
:ac:`save_as_session` is smart enough to save the ssh kitten invocation to your
session file, preserving the remote working directory and even the currently
running program on the remote host! Try it, run kitty with::

    kitty -o 'map f1 save_as_session --use-foreground-process --relocatable' --session <(echo "layout vertical\nlaunch\nlaunch")

Now in both windows, run::

    kitten ssh localhost

To connect them both to a remote computer (replace ``localhost`` with another
computer if you like). In one window change the directory to /tmp and in the
other start some program. Then press :kbd:`F1` to save the session file.
When you run the session file in another kitty instance you will see both
windows re-created, as expected with the correct working directories and
running programs.

Managing multi tab sessions in a single OS Window
----------------------------------------------------

The natural way to organise sessions in kitty is one per :term:`os_window`.
However, if you prefer to manage multiple sessions in a single OS Window, you
can configure the kitty tab bar to only show tabs that belong to the currently
active session. To do so, use :opt:`tab_bar_filter` in :file:`kitty.conf` set::

    tab_bar_filter session:~ or session:^$

This will restrict the tab bar to only showing tabs from the currently active
session as well tabs that do not belong to any session. Furthermore, when you
are in a window or tab that does not belong to any session, the tab bar will
show the tabs from the most recent active session, to maintain context.

Keyword reference
---------------------

Below is the list of all supported keywords in session files along with
documentation for them.

``cd [path]``
    Change the working directory for all windows in the current tab to
    ``path``. Relative paths are resolved with respect to the directory
    containing the session file.

``focus``
    Give keyboard focus to the window created by the previous launch command

``focus_matching_window``
    Give keyboard focus to window that matches the specified expression. See
    :ref:`search_syntax` for the syntax for matching expressions.

``focus_os_window``
    Give keyboard focus to the current OS Window. This is guaranteed to work
    only is some other OS Window in the current kitty process has focus,
    otherwise the window manager might block changing focus to prevent *focus
    stealing*.

``enabled_layouts comma separated list of layout names``
    Set the layouts allowed in the current tab. Same syntax as
    :opt:`enabled_layouts`.

``launch```
    Create a new window running the specified command or the default shell if
    no command is specified. See :doc:`launch` for details. Note that creating
    tabs and OS Windows using launch is not supported in session files, use the
    dedicated keywords for these.

``layout name``
    Set the layout for the current tab to the specified layout, including any
    specified options, see :doc:`layouts` for the available alyouts and
    options.

``new_os_window``
    Create a new OS Window. Any OS window related keywords specified before the
    first ``new_os_window`` will apply to the first OS Window.

``new_tab [tab title]``
    Create a new tab with the specified title. If no title is specified, the
    title behaves just as for a regular tab in kitty.

``os_window_title``
    Set the title for the current OS Window. The OS Window will then always
    have this title, it will not change based on the title of the currently active
    window inside the OS Window.

``os_window_class``
    Set the class part of WM_CLASS or Wayland Application Id for the current OS Window

``os_window_name``
    Set the name part of WM_CLASS or Wayland Window tag for the current OS Window

``os_window_size``
    Set the size of the current OS Window, can be specified in pixels or cells.
    For example: 80c 24c is a window of width 80 cells by 24 cells.

``os_window_state``
    Set the state of the current OS Window, can be: ``normal``, ``fullscreen``, ``maximized`` or ``minimized``

``resize_window``
    Resize the current window. See the :ac:`resize_window` action for details.
    For example: resize_window wider 2

``set_layout_state``
    This keyword is only used in session files generated by the
    :ac:`save_as_session` action, it's syntax is undocumented and for internal
    use only.

``title``
    Set the title for the next window. Deprecated, use ``launch --title``
    instead.


.. _save_as_session:

The save_as_session action
------------------------------

This action can be mapped to a key press in :file:`kitty.conf`. It will save
the currently open OS Windows, tabs, windows, running programs, working
directories, etc. into a session file. It is a convenient way to
:ref:`complex_sessions`. The options this action takes are documented below.

.. include:: generated/save-as-session.rst
