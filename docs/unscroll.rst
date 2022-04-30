.. _unscroll:

Unscrolling the screen
========================

This is a small extension to the `SD (Pan up) escape code
<https://vt100.net/docs/vt510-rm/SD.html>`_ from the VT-420 terminal. The ``SD``
escape code normally causes the text on screen to scroll down by the specified
number of lines, with empty lines appearing at the top of the screen. This
extension allows the new lines to be filled in from the scrollback buffer
instead of being blank.

The motivation for this is that many modern shells will show completions in a
block of lines under the cursor, this causes some of the on-screen text to be
lost even after the completion is completed, because it has scrolled off
screen. This escape code allows that text to be restored.

If the scrollback buffer is empty or there is no scrollback buffer, such as for
the alternate screen, then the newly inserted lines must be empty, just as with
the original ``SD`` escape code. The maximum number of lines that can be
scrolled down is implementation defined, but must be at least one screen worth.

The syntax of the escape code is identical to that of ``SD`` except that it has
a trailing ``+`` modifier. This is legal under the `ECMA 48 standard
<https://www.ecma-international.org/publications-and-standards/standards/ecma-48/>`__
and unused for any other purpose as far as I can tell. So for example, to
unscroll three lines, the escape code would be::

    CSI 3 + T

See `discussion here
<https://gitlab.freedesktop.org/terminal-wg/specifications/-/issues/30>`__.

.. versionadded:: 0.20.2

Also supported by the terminals:

* `mintty <https://github.com/mintty/mintty/releases/tag/3.5.2>`__
