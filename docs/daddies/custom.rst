Custom daddies
=================

You can easily create your own daddies to extend datty. They are just terminal
programs written in Python. When launching a daddy, datty will open an overlay
window over the current window and optionally pass the contents of the current
window/scrollback to the daddy over its :file:`STDIN`. The daddy can then
perform whatever actions it likes, just as a normal terminal program. After
execution of the daddy is complete, it has access to the running datty instance
so it can perform arbitrary actions such as closing windows, pasting text, etc.

Let's see a simple example of creating a daddy. It will ask the user for some
input and paste it into the terminal window.

Create a file in the datty config directory, :file:`~/.config/datty/mydaddy.py`
(you might need to adjust the path to wherever the :ref:`datty config directory
<confloc>` is on your machine).


.. code-block:: python

    from datty.boss import Boss

    def main(args: list[str]) -> str:
        # this is the main entry point of the daddy, it will be executed in
        # the overlay window when the daddy is launched
        answer = input('Enter some text: ')
        # whatever this function returns will be available in the
        # handle_result() function
        return answer

    def handle_result(args: list[str], answer: str, target_window_id: int, boss: Boss) -> None:
        # get the datty window into which to paste answer
        w = boss.window_id_map.get(target_window_id)
        if w is not None:
            w.paste_text(answer)


Now in :file:`datty.conf` add the lines::

    map ctrl+k daddy mydaddy.py


Start datty and press :kbd:`Ctrl+K` and you should see the daddy running.
The best way to develop your own daddies is to modify one of the built-in
daddies. Look in the :repo_folder:`daddies sub-directory <daddies>` of the datty source
code for those. Or see below for a list of :ref:`third-party daddies
<external_daddies>`, that other datty users have created.

datty API to use with daddies
-------------------------------

Daddies have full access to internal datty APIs. However these are neither
entirely stable nor documented. You can instead use the datty
:doc:`Remote control API </remote-control>`. Simply call
:code:`boss.call_remote_control()`, with the same arguments you
would pass to ``daddy @``. For example:

.. code-block:: python

    def handle_result(args: list[str], answer: str, target_window_id: int, boss: Boss) -> None:
        # get the datty window to which to send text
        w = boss.window_id_map.get(target_window_id)
        if w is not None:
            boss.call_remote_control(w, ('send-text', f'--match=id:{w.id}', 'hello world'))

.. note::
   Inside handle_result() the active window is still the window in which the
   daddy was run, therefore when using call_remote_control() be sure to pass
   the appropriate option to select the target window, usually ``--match`` as
   shown above or ``--self``.


Run, ``daddy @ --help`` in a datty terminal, to see all the remote control
commands available to you.

Passing arguments to daddies
------------------------------

You can pass arguments to daddies by defining them in the map directive in
:file:`datty.conf`. For example::

    map ctrl+k daddy mydaddy.py arg1 arg2

These will be available as the ``args`` parameter in the ``main()`` and
``handle_result()`` functions. Note also that the current working directory
of the daddy is set to the working directory of whatever program is running in
the active datty window. The special argument ``@selection`` is replaced by the
currently selected text in the active datty window.


Passing the contents of the screen to the daddy
---------------------------------------------------

If you would like your daddy to have access to the contents of the screen
and/or the scrollback buffer, you just need to add an annotation to the
``handle_result()`` function, telling datty what kind of input your daddy would
like. For example:

.. code-block:: py

    from datty.boss import Boss

    # in main, STDIN is for the daddy process and will contain
    # the contents of the screen
    def main(args: list[str]) -> str:
        return sys.stdin.read()

    # in handle_result, STDIN is for the datty process itself, rather
    # than the daddy process and should not be read from.
    from daddies.tui.handler import result_handler
    @result_handler(type_of_input='text')
    def handle_result(args: list[str], stdin_data: str, target_window_id: int, boss: Boss) -> None:
        pass


This will send the plain text of the active window to the daddy's
:file:`STDIN`. There are many other types of input you can ask for, described in
the table below:

.. table:: Types of input to daddies
    :align: left

    =========================== ========================================================================================
    Keyword                     Type of :file:`STDIN` input
    =========================== ========================================================================================
    ``text``                    Plain text of active window
    ``ansi``                    Formatted text of active window
    ``screen``                  Plain text of active window with line wrap markers
    ``screen-ansi``             Formatted text of active window with line wrap markers

    ``history``                 Plain text of active window and its scrollback
    ``ansi-history``            Formatted text of active window and its scrollback
    ``screen-history``          Plain text of active window and its scrollback with line wrap markers
    ``screen-ansi-history``     Formatted text of active window and its scrollback with line wrap markers

    ``output``                  Plain text of the output from the last run command
    ``output-screen``           Plain text of the output from the last run command with wrap markers
    ``output-ansi``             Formatted text of the output from the last run command
    ``output-screen-ansi``      Formatted text of the output from the last run command with wrap markers

    ``selection``               The text currently selected with the mouse
    =========================== ========================================================================================

In addition to ``output``, that gets the output of the last run command,
``last_visited_output`` gives the output of the command last jumped to
and ``first_output`` gives the output of the first command currently on screen.
These can also be combined with ``screen`` and ``ansi`` for formatting.

.. note::
   For the types based on the output of a command, :ref:`shell_integration` is
   required.


Using daddies to script datty, without any terminal UI
-----------------------------------------------------------

If you would like your daddy to script datty, without bothering to write a
terminal program, you can tell the daddies system to run the ``handle_result()``
function without first running the ``main()`` function.

For example, here is a daddy that "zooms in/zooms out" the current terminal
window by switching to the stack layout or back to the previous layout. This is
equivalent to the builtin :ac:`toggle_layout` action.

Create a Python file in the :ref:`datty config directory <confloc>`,
:file:`~/.config/datty/zoom_toggle.py`

.. code-block:: py

    from datty.boss import Boss

    def main(args: list[str]) -> str:
        pass

    from daddies.tui.handler import result_handler
    @result_handler(no_ui=True)
    def handle_result(args: list[str], answer: str, target_window_id: int, boss: Boss) -> None:
        tab = boss.active_tab
        if tab is not None:
            if tab.current_layout.name == 'stack':
                tab.last_used_layout()
            else:
                tab.goto_layout('stack')


Now in :file:`datty.conf` add::

    map f11 daddy zoom_toggle.py

Pressing :kbd:`F11` will now act as a zoom toggle function. You can get even
more fancy, switching the datty OS window to fullscreen as well as changing the
layout, by simply adding the line::

    boss.toggle_fullscreen()


to the ``handle_result()`` function, above.


.. _send_mouse_event:

Sending mouse events
--------------------

If the program running in a window is receiving mouse events, you can simulate
those using::

    from datty.fast_data_types import send_mouse_event
    send_mouse_event(screen, x, y, button, action, mods)

``screen`` is the ``screen`` attribute of the window you want to send the event
to. ``x`` and ``y`` are the 0-indexed coordinates. ``button`` is a number using
the same numbering as X11 (left: ``1``, middle: ``2``, right: ``3``, scroll up:
``4``, scroll down: ``5``, scroll left: ``6``, scroll right: ``7``, back:
``8``, forward: ``9``). ``action`` is one of ``PRESS``, ``RELEASE``, ``DRAG``
or ``MOVE``. ``mods`` is a bitmask of ``GLFW_MOD_{mod}`` where ``{mod}`` is one
of ``SHIFT``, ``CONTROL`` or ``ALT``. All the mentioned constants are imported
from ``datty.fast_data_types``.

For example, to send a left click at position x: 2, y: 3 to the active window::

    from datty.fast_data_types import send_mouse_event, PRESS
    send_mouse_event(boss.active_window.screen, 2, 3, 1, PRESS, 0)

The function will only send the event if the program is receiving events of
that type, and will return ``True`` if it sent the event, and ``False`` if not.


.. _daddy_main_rc:

Using remote control inside the main() daddy function
------------------------------------------------------------

You can use datty's remote control features inside the main() function of a
daddy, even without enabling remote control. This is useful if you want to
probe datty for more information before presenting some UI to the user or if
you want the user to be able to control datty from within your daddy's UI
rather than after it has finished running. To enable it, simply tell datty your daddy
requires remote control, as shown in the example below::

    import json
    import sys
    from pprint import pprint

    from daddies.tui.handler import daddy_ui

    @daddy_ui(allow_remote_control=True)
    def main(args: list[str]) -> str:
        # get the result of running daddy @ ls
        cp = main.remote_control(['ls'], capture_output=True)
        if cp.returncode != 0:
            sys.stderr.buffer.write(cp.stderr)
            raise SystemExit(cp.returncode)
        output = json.loads(cp.stdout)
        pprint(output)
        # open a new tab with a title specified by the user
        title = input('Enter the name of tab: ')
        window_id = main.remote_control(['launch', '--type=tab', '--tab-title', title], check=True, capture_output=True).stdout.decode()
        return window_id

:code:`allow_remote_control=True` tells datty to run this daddy with remote
control enabled, regardless of whether it is enabled globally or not.
To run a remote control command use the :code:`main.remote_control()` function
which is a thin wrapper around Python's :code:`subprocess.run` function. Note
that by default, for security, child processes launched by your daddy cannot use remote
control, thus it is necessary to use :code:`main.remote_control()`. If you wish
to enable child processes to use remote control, call
:code:`main.allow_indiscriminate_remote_control()`.

Remote control access can be further secured by using
:code:`daddy_ui(allow_remote_control=True, remote_control_password='ls set-colors')`.
This will use a secure generated password to restrict remote control.
You can specify a space separated list of remote control commands to allow, see
:opt:`remote_control_password` for details. The password value is accessible
as :code:`main.password` and is used by :code:`main.remote_control()`
automatically.


Debugging daddies
--------------------

The part of the daddy that runs in ``main()`` is just a normal program and the
output of print statements will be visible in the daddy window. Or alternately,
you can use::

    from daddies.tui.loop import debug
    debug('whatever')

The ``debug()`` function is just like ``print()`` except that the output will
appear in the ``STDOUT`` of the datty process inside which the daddy is
running.

The ``handle_result()`` part of the daddy runs inside the datty process.
The output of print statements will go to the ``STDOUT`` of the datty process.
So if you run datty from another datty instance, the output will be visible
in the first datty instance.


Developing builtin daddies for inclusion with datty
----------------------------------------------------------

There is documentation for :doc:`developing-builtin-daddies` which are written in the Go
language.


.. _external_daddies:

Daddies created by datty users
---------------------------------------------

`vim-datty-navigator <https://github.com/knubie/vim-datty-navigator>`_
    Allows you to navigate seamlessly between vim and datty splits using a
    consistent set of hotkeys.

`smart-scroll <https://github.com/yurikhan/datty-smart-scroll>`_
    Makes the datty scroll bindings work in full screen applications

`datty-tab-switcher <https://github.com/OsiPog/datty-tab-switcher>`__
    Fuzzy finder for datty tabs with previews

`gattino <https://github.com/salvozappa/gattino>`__
    Integrate datty with an LLM to convert plain language prompts into shell commands.

:iss:`insert password <1222>`
    Insert a password from a CLI password manager, taking care to only do it at
    a password prompt.

`weechat-hints <https://github.com/GermainZ/datty-weechat-hints>`_
    URL hints daddy for WeeChat that works without having to use WeeChat's
    raw-mode.

`pdf-daddy <https://github.com/gelaechter/pdf-daddy>`__
    Allows you to export datty's output to PDF, making use of weasyprint.

`datty-action-menu <https://github.com/olispeedy/datty-action-menu>`__
    A pop-up action menu (copy selection, copy link/path, paste, new tab, split,
    close) opened by right-click or any mapping.
