:orphan:

Making your keyboard dance
==============================

.. highlight:: conf

kitty has extremely powerful facilities for mapping keyboard actions.
Things like combining actions, multi-key mappings, modal mappings,
mappings that send arbitrary text, and mappings dependent on the program
currently running in kitty.

Let's start with the basics. You can map a key press to an action in kitty using
the following syntax::

    map ctrl+a new_window_with_cwd

This will map the key press :kbd:`Ctrl+a` to open a new :term:`window`
with the working directory set to the working directory of the current window.
This is the basic operation of the map directive, the tip of the iceberg, for
more read the sections below.


Combining multiple actions on a single keypress
-----------------------------------------------------

Multiple actions can be combined on a single keypress, like a macro. To do this
map the key press to the :ac:`combine` action::

    map key combine <separator> action1 <separator> action2 <separator> action3 ...

For example::

    map kitty_mod+e combine : new_window : next_layout

This will create a new window and switch to the next available layout. You can
also run arbitrarily powerful scripts on a key press. There are two major
techniques for doing this, using remote control scripts or using kittens.

Remote control scripts
^^^^^^^^^^^^^^^^^^^^^^^^^

These can be written in any language and use the "kitten" binary to control
kitty via its extensive :doc:`Remote control <remote-control>` API. First,
if you just want to run a single remote control command on a key press,
you can just do::

    map f1 remote_control set-spacing margin=30

This will run the ``set-spacing`` command, changing window margins to 30 pixels. For
more complex scripts, write a script file in any language you like and save it
somewhere, preferably in the kitty configuration directory. Do not forget to make it
executable. In the script file you run remote control commands by running the
"kitten" binary, for example:

.. code-block:: sh

   #!/bin/sh

   kitten @ set-spacing margin=30
   kitten @ new_window
   ...

The script can perform arbitrarily complex logic and actions, limited only by
the remote control API, that you can browse by running ``kitten @ --help``.
To run the script you created on a key press, use::

    map f1 remote_control_script /path/to/myscript


Kittens
^^^^^^^^^^^^^

Here, kittens refer to Python scripts. The scripts have two parts, one that
runs as a regular command line program inside a kitty window to, for example,
ask the user for some input and a second part that runs inside the kitty
process itself and can perform any operation on the kitty UI, which is itself
implemented in Python. However, the kitty internal API is not documented and
can (very rarely) change, so kittens are harder to get started with than remote
control scripts. To run a kitten on a key press::

    map f1 kitten mykitten.py

Many of kitty's features are themselves implemented as kittens, for example,
:doc:`/kittens/unicode_input`, :doc:`/kittens/hints` and
:doc:`/kittens/themes`. To learn about writing your own kittens, see
:doc:`/kittens/custom`.

Syntax for specifying keys
-----------------------------

A mapping maps a key press to some action. In their most basic form, keypresses
are :code:`modifier+key`. Keys are identified simply by their lowercase Unicode
characters. For example: :code:`a` for the :kbd:`A` key, :code:`[` for the left
square bracket key, etc.  For functional keys, such as :kbd:`Enter` or
:kbd:`Escape`, the names are present at :ref:`Functional key definitions
<functional>`. For modifier keys, the names are :kbd:`ctrl` (:kbd:`control`,
:kbd:`⌃`), :kbd:`shift` (:kbd:`⇧`), :kbd:`alt` (:kbd:`opt`, :kbd:`option`,
:kbd:`⌥`), :kbd:`super` (:kbd:`cmd`, :kbd:`command`, :kbd:`⌘`).

Additionally, you can use the name :opt:`kitty_mod` as a modifier, the default
value of which is :kbd:`ctrl+shift`. The default kitty shortcuts are defined
using this value, so by changing it in :file:`kitty.conf` you can change
all the modifiers used by all the default shortcuts.

On Linux, you can also use XKB names for functional keys that don't have kitty
names. See :link:`XKB keys
<https://github.com/xkbcommon/libxkbcommon/blob/master/include/xkbcommon/xkbcommon-keysyms.h>`
for a list of key names. The name to use is the part after the :code:`XKB_KEY_`
prefix. Note that you can only use an XKB key name for keys that are not known
as kitty keys.

Finally, you can use raw system key codes to map keys, again only for keys that
are not known as kitty keys. To see the system key code for a key, start kitty
with the :option:`kitty --debug-input` option, kitty will output some debug text
for every key event. In that text look for :code:`native_code`, the value
of that becomes the key name in the shortcut. For example:

.. code-block:: none

    on_key_input: glfw key: 0x61 native_code: 0x61 action: PRESS mods: none text: 'a'

Here, the key name for the :kbd:`A` key is :code:`0x61` and you can use it with::

    map ctrl+0x61 something

This maps :kbd:`Ctrl+A` to something.


Multi-key mappings
--------------------

A mapping in kitty can involve pressing multiple keys in sequence, with the
syntax shown below::

    map key1>key2>key3 action

For example::

    map ctrl+f>2 set_font_size 20

The default mappings to run the :doc:`hints kitten </kittens/hints>` to select text on the screen are
examples of multi-key mappings.

Unmapping default shortcuts
-----------------------------

kitty comes with dozens of default keyboard mappings for common operations. See
:doc:`actions` for the full list of actions and the default shortcuts that map
to them. You can unmap an individual shortcut, so that it is passed on to the
program running inside kitty, by mapping it to nothing, for example::

    map kitty_mod+enter

This unmaps the default shortcut :sc:`new_window` to open a new window. Almost
all default shortcuts are of the form ``modifier + key`` where the
modifier defaults to :kbd:`Ctrl+Shift` and can be changed using the :opt:`kitty_mod` setting
in :file:`kitty.conf`.

If you want to clear all default shortcuts, you can use
:opt:`clear_all_shortcuts` in :file:`kitty.conf`.

If you would like kitty to completely ignore a key event, not even sending it to
the program running in the terminal, map it to :ac:`discard_event`::

    map kitty_mod+f1 discard_event

.. _conditional_mappings:

Conditional mappings depending on the state of the focused window
----------------------------------------------------------------------

Sometimes, you may want different mappings to be active when running a
particular program in kitty, perhaps because it has some native functionality
that duplicates kitty functions or there is a conflict, etc. kitty has the
ability to create mappings that work only when the currently focused window
matches some criteria, such as when it has a particular title or user variable.

Let's see some examples::

    map --when-focus-on title:keyboard.protocol kitty_mod+t

This will cause :kbd:`kitty_mod+t` (the default shortcut for opening a new tab)
to be unmapped only when the focused window
has :code:`keyboard protocol` in its title. Run the show-key kitten as::

    kitten show-key -m kitty

Press :kbd:`ctrl+shift+t` and instead of a new tab opening, you will
see the key press being reported by the kitten. :code:`--when-focus-on` can test
the focused window using very powerful criteria, see :ref:`search_syntax` for
details. A more practical example unmaps the key when the focused window is
running an editor::

    map --when-focus-on var:in_editor kitty_mod+c

In order to make this work, you need to configure your editor as show below:

.. tab:: vim

   In :file:`~/.vimrc` add:
    .. code-block:: vim

        let &t_ti = &t_ti . "\033]1337;SetUserVar=in_editor=MQo\007"
        let &t_te = &t_te . "\033]1337;SetUserVar=in_editor\007"

.. tab:: neovim

   In :file:`~/.config/nvim/init.lua` add:

    .. code-block:: lua

        vim.api.nvim_create_autocmd({ "VimEnter", "VimResume" }, {
            group = vim.api.nvim_create_augroup("KittySetVarVimEnter", { clear = true }),
            callback = function()
                io.stdout:write("\x1b]1337;SetUserVar=in_editor=MQo\007")
            end,
        })

        vim.api.nvim_create_autocmd({ "VimLeave", "VimSuspend" }, {
            group = vim.api.nvim_create_augroup("KittyUnsetVarVimLeave", { clear = true }),
            callback = function()
                io.stdout:write("\x1b]1337;SetUserVar=in_editor\007")
            end,
        })

These cause the editor to set the :code:`in_editor` variable in kitty and unset it when exiting.
As a result, the :kbd:`ctrl+shift+c` key will be passed to the editor instead of
copying to clipboard. In the editor, you can map it to copy to the clipboard,
thereby allowing use of a common shortcut both inside and outside the editor
for copying to clipboard.

Sending arbitrary text or keys to the program running in kitty
--------------------------------------------------------------------------------

This is accomplished by using ``map`` with :sc:`send_text <send_text>` in :file:`kitty.conf`.
For example::

    map f1 send_text normal,application Hello, world!

Now, pressing :kbd:`f1` will cause ``Hello, world!`` to show up at your shell
prompt. To have the shell execute a command sent via ``send_text`` you need to
also simulate pressing the enter key which is ``\r``. For example::

    map f1 send_text normal,application echo Hello, world!\r

Now, if you press :kbd:`f1` when at shell prompt it will run the ``echo Hello,
world!`` command.

To have one key press send another key press, use :ac:`send_key`::

    map alt+s send_key ctrl+s

This causes the program running in kitty to receive the :kbd:`ctrl+s` key when
you press the :kbd:`alt+s` key. To see this in action, run::

    kitten show-key -m kitty

Which will print out what key events it receives.

.. _modal_mappings:

Modal mappings
--------------------------

kitty has the ability, like vim, to use *modal* key maps. Except that unlike
vim it allows you to define your own arbitrary number of modes. To create a new
mode, use ``map --new-mode <my mode name> <shortcut to enter mode>``. For
example, lets create a mode to manage windows: switching focus, moving the window, etc.::

    # Create a new "manage windows" mode (mw)
    map --new-mode mw kitty_mod+f7

    # Switch focus to the neighboring window in the indicated direction using arrow keys
    map --mode mw left neighboring_window left
    map --mode mw right neighboring_window right
    map --mode mw up neighboring_window up
    map --mode mw down neighboring_window down

    # Move the active window in the indicated direction
    map --mode mw shift+up move_window up
    map --mode mw shift+left move_window left
    map --mode mw shift+right move_window right
    map --mode mw shift+down move_window down

    # Resize the active window
    map --mode mw n resize_window narrower
    map --mode mw w resize_window wider
    map --mode mw t resize_window taller
    map --mode mw s resize_window shorter

    # Exit the manage window mode
    map --mode mw esc pop_keyboard_mode

Now, if you run kitty as:

.. code-block:: sh

    kitty -o enabled_layouts=vertical --session <(echo "launch\nlaunch\nlaunch")

Press :kbd:`Ctrl+Shift+F7` to enter the mode and then press the up and
down arrow keys to focus the next/previous window. Press :kbd:`Shift+Up` or
:kbd:`Shift+Down` to move the active window up and down. Press :kbd:`t` to make
the active window taller and :kbd:`s` to make it shorter. To exit the mode
press :kbd:`Esc`.

Pressing an unknown key while in a custom keyboard mode by default
beeps. This can be controlled by the ``map --on-unknown`` option as shown
below::

    # Beep on unknown keys
    map --new-mode XXX --on-unknown beep ...
    # Ignore unknown keys silently
    map --new-mode XXX --on-unknown ignore ...
    # Beep and exit the keyboard mode on unknown key
    map --new-mode XXX --on-unknown end ...
    # Pass unknown keys to the program running in the active window
    map --new-mode XXX --on-unknown passthrough ...

When a key matches an action in a custom keyboard mode, the action is performed
and the custom keyboard mode remains in effect. If you would rather have the
keyboard mode end after the action you can use ``map --on-action`` as shown
below::

    # Have this keyboard mode automatically exit after performing any action
    map --new-mode XXX --on-action end ...


All mappable actions
------------------------

There is a list of :doc:`all mappable actions <actions>`.

Debugging mapping issues
------------------------------

To debug mapping issues, kitty has several facilities. First, when you run
kitty with the ``--debug-input`` command line flag it outputs details
about all key events it receives form the system and how they are handled.

To see what key events are sent to applications, run kitty like this::

    kitty kitten show-key

Press the keys you want to debug and the kitten will print out the bytes it
receives. Note that this uses the legacy terminal keyboard protocol that does
not support all keys and key events. To debug the :doc:`full kitty keyboard
protocol that <keyboard-protocol>` that is nowadays being adopted by more and
more programs, use::

    kitty kitten show-key -m kitty
