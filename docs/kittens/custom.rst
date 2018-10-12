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

   def main(args):
      # this is the main entry point of the kitten, it will be executed in
      # the overlay window when the kitten is launched
      answer = input('Enter some text: ')
      # whatever this function returns will be available in the
      # handle_result() function
      return answer

   def handle_result(args, answer, target_window_id, boss):
      # get the kitty window into which to paste answer
      w = boss.window_id_map.get(target_window_id)
      if w is not None:
         w.paste(answer)


Now in :file:`kitty.conf` add the lines::

   map ctrl+k kitten mykitten.py


Start kitty and press :kbd:`ctrl+k` and you should see the kitten running.
The best way to develop your own kittens is to modify one of the built in
kittens. Look in the kittens sub-directory of the kitty source code for those.


Passing arguments to kittens
------------------------------

You can pass arguments to kittens by defining them in the map directive in
:file:`kitty.conf`. For example::

   map ctrl+k kitten mykitten.py arg1 arg2

These will be available as the ``args`` parameter in the ``main()`` and
``handle_result()`` functions. Note also that the current working directory
of the kitten is set to the working directory of whatever program is
running in the active kitty window.


Passing the contents of the screen to the kitten
---------------------------------------------------

If you would like your kitten to have access to the contents of the screen
and/or the scrollback buffer, you just need to add an annotation to the ``handle_result()``
function, telling kitty what kind of input your kitten would like. For example:

.. code-block:: py

   def handle_result(...):
      pass

   handle_result.type_of_input = 'text'

This will send the plain text of the active window to the kitten's
:file:`STDIN`. For text with formatting escape codes, use ``ansi``
instead. If you want line wrap markers as well, use ``screen-ansi``
or just ``screen``. For the scrollback buffer as well, use
``history``, ``ansi-history`` or ``screen-history``.


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

   def handle_result(args, answer, target_window_id, boss):
      tab = boss.active_tab
      if tab is not None:
         if tab.current_layout.name == 'stack':
            tab.last_used_layout()
         else:
            tab.goto_layout('stack')

   handle_result.no_ui = True


Now in kitty.conf add::

   map f11 kitten zoom_toggle.py

Pressing :kbd:`F11` will now act as a zoom toggle function. You can get even
more fancy, switching the kitty OS window to fullscreen as well as changing the
layout, by simply adding the line::

    boss.toggle_fullscreen()


to the handle_result() function, above.
