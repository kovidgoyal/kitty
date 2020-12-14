Custom kittens
=================

You can easily create your own kittens to extend kitty. They are just
terminal programs written in Python. When launching a kitten, kitty will
open an overlay window over the current window and optionally pass the
contents of the current window/scrollback to the kitten over its :file:`STDIN`.
The kitten can then perform whatever actions it likes, just as a normal
terminal program. After execution of the kitten is complete, it has access
to the running kitty instance so it can perform arbitrary actions
such as closing windows, pasting text, etc.

Let's see a simple example of creating a kitten. It will ask the user for some
input and paste it into the terminal window.

Create a file in the kitty config folder, :file:`~/.config/kitty/mykitten.py`
(you might need to adjust the path to wherever the kitty config folder is on
your machine).


.. code-block:: python

    from typing import List
    from kitty.boss import Boss

    def main(args: List[str]) -> str:
        # this is the main entry point of the kitten, it will be executed in
        # the overlay window when the kitten is launched
        answer = input('Enter some text: ')
        # whatever this function returns will be available in the
        # handle_result() function
        return answer

    def handle_result(args: List[str], answer: str, target_window_id: int, boss: Boss) -> None:
        # get the kitty window into which to paste answer
        w = boss.window_id_map.get(target_window_id)
        if w is not None:
            w.paste(answer)


Now in :file:`kitty.conf` add the lines::

    map ctrl+k kitten mykitten.py


Start kitty and press :kbd:`ctrl+k` and you should see the kitten running.
The best way to develop your own kittens is to modify one of the built in
kittens. Look in the kittens sub-directory of the kitty source code for those.
Or see below for a list of :ref:`third-party kittens <external_kittens>`,
that other kitty users have created.


Passing arguments to kittens
------------------------------

You can pass arguments to kittens by defining them in the map directive in
:file:`kitty.conf`. For example::

    map ctrl+k kitten mykitten.py arg1 arg2

These will be available as the ``args`` parameter in the ``main()`` and
``handle_result()`` functions. Note also that the current working directory
of the kitten is set to the working directory of whatever program is
running in the active kitty window. The special argument ``@selection``
is replaced by the currently selected text in the active kitty window.


Passing the contents of the screen to the kitten
---------------------------------------------------

If you would like your kitten to have access to the contents of the screen
and/or the scrollback buffer, you just need to add an annotation to the ``handle_result()``
function, telling kitty what kind of input your kitten would like. For example:

.. code-block:: py

    # in main, STDIN is for the kitten process and will contain
    # the contents of the screen
    def main(args):
        return sys.stdin.read()

    # in handle_result, STDIN is for the kitty process itself, rather
    # than the kitten process and should not be read from.
    from kittens.tui.handler import result_handler
    @result_handler(type_of_input='text')
    def handle_result(args, stdin_data, target_window_id, boss):
        pass


This will send the plain text of the active window to the kitten's
:file:`STDIN`. For text with formatting escape codes, use ``ansi``
instead. If you want line wrap markers as well, use ``screen-ansi``
or just ``screen``. For the scrollback buffer as well, use
``history``, ``ansi-history`` or ``screen-history``. To get
the currently selected text, use ``selection``.


Using kittens to script kitty, without any terminal UI
-----------------------------------------------------------

If you would like your kitten to script kitty, without bothering to write a
terminal program, you can tell the kittens system to run the
``handle_result()`` function without first running the ``main()`` function.

For example, here is a kitten that "zooms/unzooms" the current terminal window
by switching to the stack layout or back to the previous layout.

Create a file in the kitty config folder, :file:`~/.config/kitty/zoom_toggle.py`

.. code-block:: py

    def main(args):
        pass

    from kittens.tui.handler import result_handler
    @result_handler(no_ui=True)
    def handle_result(args, answer, target_window_id, boss):
        tab = boss.active_tab
        if tab is not None:
            if tab.current_layout.name == 'stack':
                tab.last_used_layout()
            else:
                tab.goto_layout('stack')


Now in kitty.conf add::

    map f11 kitten zoom_toggle.py

Pressing :kbd:`F11` will now act as a zoom toggle function. You can get even
more fancy, switching the kitty OS window to fullscreen as well as changing the
layout, by simply adding the line::

    boss.toggle_fullscreen()


To the ``handle_result()`` function, above.


.. _send_mouse_event:

Sending mouse events
--------------------

If the program running in a window is receiving mouse events you can simulate
those using::

    from kitty.fast_data_types import send_mouse_event
    send_mouse_event(screen, x, y, button, action, mods)

``screen`` is the ``screen`` attribute of the window you want to send the event
to. ``x`` and ``y`` are the 0-indexed coordinates. ``button`` is a number using
the same numbering as X11 (left: ``1``, middle: ``2``, right: ``3``, scroll up:
``4``, scroll down: ``5``, scroll left: ``6``, scroll right: ``7``, back:
``8``, forward: ``9``). ``action`` is one of ``PRESS``, ``RELEASE``, ``DRAG``
or ``MOVE``. ``mods`` is a bitmask of ``GLFW_MOD_{mod}`` where ``{mod}`` is one
of ``SHIFT``, ``CONTROL`` or ``ALT``. All the mentioned constants are imported
from ``kitty.fast_data_types``.

For example, to send a left click at position x: 2, y: 3 to the active window::

    from kitty.fast_data_types import send_mouse_event, PRESS
    send_mouse_event(boss.active_window.screen, 2, 3, 1, PRESS, 0)

The function will only send the event if the program is receiving events of
that type, and will return ``True`` if it sent the event, and ``False`` if not.


Debugging kittens
--------------------

The part of the kitten that runs in ``main()`` is just a normal program and
the output of print statements will be visible in the kitten window. Or
alternately, you can use::

    from kittens.tui.loop import debug
    debug('whatever')

The ``debug()`` function is just like ``print()`` except that the output
will appear in the ``STDOUT`` of the kitty process inside which the kitten is
running.

The ``handle_result()`` part of the kitten runs inside the kitty process.
The output of print statements will go to the ``STDOUT`` of the kitty process.
So if you run kitty from another kitty instance, the output will be visible
in the first kitty instance.

.. _external_kittens:

Kittens created by kitty users
---------------------------------------------

`vim-kitty-navigator <https://github.com/knubie/vim-kitty-navigator>`_
    Allows you to navigate seamlessly between vim and kitty splits using a consistent set of hotkeys.

`smart-scroll <https://github.com/yurikhan/kitty-smart-scroll>`_
    Makes the kitty scroll bindings work in full screen applications

`insert password <https://github.com/kovidgoyal/kitty/issues/1222>`_
    Insert a password from a CLI password manager, taking care to only do it at
    a password prompt.

`weechat-hints <https://github.com/GermainZ/kitty-weechat-hints>`_
    URL hints kitten for WeeChat that works without having to use WeeChat's
    raw-mode.
