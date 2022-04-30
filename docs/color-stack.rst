Saving and restoring colors
==============================

It is often useful for a full screen application with its own color themes to
set the default foreground, background, selection and cursor colors and the ANSI
color table. This allows for various performance optimizations when drawing the
screen. The problem is that if the user previously used the escape codes to
change these colors themselves, then running the full screen application will
lose those changes even after it exits. To avoid this, kitty introduces a new
pair of *OSC* escape codes to push and pop the current color values from a
stack::

    <ESC>]30001<ESC>\  # push onto stack
    <ESC>]30101<ESC>\  # pop from stack

These escape codes save/restore the colors, default background, default
foreground, selection background, selection foreground and cursor color and the
256 colors of the ANSI color table.

.. note:: In July 2020, after several years, xterm copied this protocol
   extension, without acknowledgement, and using incompatible escape codes
   (XTPUSHCOLORS, XTPOPCOLORS, XTREPORTCOLORS). And they decided to save not
   just the dynamic colors but the entire ANSI color table. In the interests of
   promoting interoperability, kitty added support for xterm's escape codes as
   well, and changed this extension to also save/restore the entire ANSI color
   table.
