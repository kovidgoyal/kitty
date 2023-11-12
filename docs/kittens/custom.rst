Custom kittens
=================

You can easily create your own kittens to extend kitty. They are just terminal
programs written in Python. When launching a kitten, kitty will open an overlay
window over the current window and optionally pass the contents of the current
window/scrollback to the kitten over its :file:`STDIN`. The kitten can then
perform whatever actions it likes, just as a normal terminal program. After
execution of the kitten is complete, it has access to the running kitty instance
so it can perform arbitrary actions such as closing windows, pasting text, etc.

Let's see a simple example of creating a kitten. It will ask the user for some
input and paste it into the terminal window.

Create a file in the kitty config directory, :file:`~/.config/kitty/mykitten.py`
(you might need to adjust the path to wherever the :ref:`kitty config directory
<confloc>` is on your machine).


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
            w.paste_text(answer)


Now in :file:`kitty.conf` add the lines::

    map ctrl+k kitten mykitten.py


Start kitty and press :kbd:`Ctrl+K` and you should see the kitten running.
The best way to develop your own kittens is to modify one of the built-in
kittens. Look in the `kittens sub-directory
<https://github.com/kovidgoyal/kitty/tree/master/kittens>`__ of the kitty source
code for those. Or see below for a list of :ref:`third-party kittens
<external_kittens>`, that other kitty users have created.

kitty API to use with kittens
-------------------------------

Kittens have full access to internal kitty APIs. However these are neither
entirely stable nor documented. You can instead use the kitty
:doc:`Remote control API </remote-control>`. Simply call
:code:`boss.call_remote_control()`, with the same arguments you
would pass to ``kitten @``. For example:

.. code-block:: python

    def handle_result(args: List[str], answer: str, target_window_id: int, boss: Boss) -> None:
        # get the kitty window to which to send text
        w = boss.window_id_map.get(target_window_id)
        if w is not None:
            boss.call_remote_control(w, ('send-text', f'--match=id:{w.id}', 'hello world'))

.. note::
   Inside handle_result() the active window is still the window in which the
   kitten was run, therefore when using call_remote_control() be sure to pass
   the appropriate option to select the target window, usually ``--match`` as
   shown above or ``--self``.


Passing arguments to kittens
------------------------------

You can pass arguments to kittens by defining them in the map directive in
:file:`kitty.conf`. For example::

    map ctrl+k kitten mykitten.py arg1 arg2

These will be available as the ``args`` parameter in the ``main()`` and
``handle_result()`` functions. Note also that the current working directory
of the kitten is set to the working directory of whatever program is running in
the active kitty window. The special argument ``@selection`` is replaced by the
currently selected text in the active kitty window.


Passing the contents of the screen to the kitten
---------------------------------------------------

If you would like your kitten to have access to the contents of the screen
and/or the scrollback buffer, you just need to add an annotation to the
``handle_result()`` function, telling kitty what kind of input your kitten would
like. For example:

.. code-block:: py

    from typing import List
    from kitty.boss import Boss

    # in main, STDIN is for the kitten process and will contain
    # the contents of the screen
    def main(args: List[str]) -> str:
        return sys.stdin.read()

    # in handle_result, STDIN is for the kitty process itself, rather
    # than the kitten process and should not be read from.
    from kittens.tui.handler import result_handler
    @result_handler(type_of_input='text')
    def handle_result(args: List[str], stdin_data: str, target_window_id: int, boss: Boss) -> None:
        pass


This will send the plain text of the active window to the kitten's
:file:`STDIN`. There are many other types of input you can ask for, described in
the table below:

.. table:: Types of input to kittens
    :align: left

    =========================== =======================================================================================================
    Keyword                     Type of :file:`STDIN` input
    =========================== =======================================================================================================
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
    =========================== =======================================================================================================

In addition to ``output``, that gets the output of the last run command,
``last_visited_output`` gives the output of the command last jumped to
and ``first_output`` gives the output of the first command currently on screen.
These can also be combined with ``screen`` and ``ansi`` for formatting.

.. note::
   For the types based on the output of a command, :ref:`shell_integration` is
   required.


Using kittens to script kitty, without any terminal UI
-----------------------------------------------------------

If you would like your kitten to script kitty, without bothering to write a
terminal program, you can tell the kittens system to run the ``handle_result()``
function without first running the ``main()`` function.

For example, here is a kitten that "zooms in/zooms out" the current terminal
window by switching to the stack layout or back to the previous layout. This is
equivalent to the builtin :ac:`toggle_layout` action.

Create a Python file in the :ref:`kitty config directory <confloc>`,
:file:`~/.config/kitty/zoom_toggle.py`

.. code-block:: py

    from typing import List
    from kitty.boss import Boss

    def main(args: List[str]) -> str:
        pass

    from kittens.tui.handler import result_handler
    @result_handler(no_ui=True)
    def handle_result(args: List[str], answer: str, target_window_id: int, boss: Boss) -> None:
        tab = boss.active_tab
        if tab is not None:
            if tab.current_layout.name == 'stack':
                tab.last_used_layout()
            else:
                tab.goto_layout('stack')


Now in :file:`kitty.conf` add::

    map f11 kitten zoom_toggle.py

Pressing :kbd:`F11` will now act as a zoom toggle function. You can get even
more fancy, switching the kitty OS window to fullscreen as well as changing the
layout, by simply adding the line::

    boss.toggle_fullscreen()


to the ``handle_result()`` function, above.


.. _send_mouse_event:

Sending mouse events
--------------------

If the program running in a window is receiving mouse events, you can simulate
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

The part of the kitten that runs in ``main()`` is just a normal program and the
output of print statements will be visible in the kitten window. Or alternately,
you can use::

    from kittens.tui.loop import debug
    debug('whatever')

The ``debug()`` function is just like ``print()`` except that the output will
appear in the ``STDOUT`` of the kitty process inside which the kitten is
running.

The ``handle_result()`` part of the kitten runs inside the kitty process.
The output of print statements will go to the ``STDOUT`` of the kitty process.
So if you run kitty from another kitty instance, the output will be visible
in the first kitty instance.


Adding options to kittens
----------------------------

If you would like to use kitty's config framework to make your kittens
configurable, you will need some boilerplate. Put the following files in the
directory of your kitten.

:file:`kitten_options_definition.py`

.. code-block:: python

    from kitty.conf.types import Action, Definition

    definition = Definition(
        '!kitten_options_utils',
        Action(
            'map', 'parse_map',
            {'key_definitions': 'kitty.conf.utils.KittensKeyMap'},
            ['kitty.types.ParsedShortcut', 'kitty.conf.utils.KeyAction']
        ),
    )

    agr = definition.add_group
    egr = definition.end_group
    opt = definition.add_option
    map = definition.add_map

    # main options {{{
    agr('main', 'Main')

    opt('some_option', '33',
        option_type='some_option_parser',
        long_text='''
    Help text for this option
    '''
        )
    egr()  # }}}

    # shortcuts {{{
    agr('shortcuts', 'Keyboard shortcuts')

    map('Quit', 'quit q quit')
    egr()  # }}}


:file:`kitten_options_utils.py`

.. code-block:: python

    from kitty.conf.utils import KittensKeyDefinition, key_func, parse_kittens_key

    func_with_args, args_funcs = key_func()
    FuncArgsType = Tuple[str, Sequence[Any]]

    def some_option_parser(val: str) -> int:
        return int(val) + 3000

    def parse_map(val: str) -> Iterable[KittensKeyDefinition]:
        x = parse_kittens_key(val, args_funcs)
        if x is not None:
            yield x

Then run::

    kitty +runpy 'from kitty.conf.generate import main; main()' /path/to/kitten_options_definition.py

You can parse and read the options in your kitten using the following code:

.. code-block:: python

    from .kitten_options_types import Options, defaults
    from kitty.conf.utils import load_config as _load_config, parse_config_base
    from typing import Optional, Iterable, Dict, Any

    def load_config(*paths: str, overrides: Optional[Iterable[str]] = None) -> Options:
        from .kitten_options_parse import  (
            create_result_dict, merge_result_dicts, parse_conf_item
        )

        def parse_config(lines: Iterable[str]) -> Dict[str, Any]:
            ans: Dict[str, Any] = create_result_dict()
            parse_config_base(
                lines,
                parse_conf_item,
                ans,
            )
            return ans

        overrides = tuple(overrides) if overrides is not None else ()
        opts_dict, found_paths = _load_config(defaults, parse_config, merge_result_dicts, *paths, overrides=overrides)
        opts = Options(opts_dict)
        opts.config_paths = found_paths
        opts.all_config_paths = paths
        opts.config_overrides = overrides
        return opts

See `the code <https://github.com/kovidgoyal/kitty/tree/master/kittens/diff>`__
for the builtin :doc:`diff kitten </kittens/diff>` for examples of creating more
options and keyboard shortcuts.

.. _external_kittens:

Kittens created by kitty users
---------------------------------------------

`vim-kitty-navigator <https://github.com/knubie/vim-kitty-navigator>`_
    Allows you to navigate seamlessly between vim and kitty splits using a
    consistent set of hotkeys.

`smart-scroll <https://github.com/yurikhan/kitty-smart-scroll>`_
    Makes the kitty scroll bindings work in full screen applications

:iss:`insert password <1222>`
    Insert a password from a CLI password manager, taking care to only do it at
    a password prompt.

`weechat-hints <https://github.com/GermainZ/kitty-weechat-hints>`_
    URL hints kitten for WeeChat that works without having to use WeeChat's
    raw-mode.
