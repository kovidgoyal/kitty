Miscellaneous protocol extensions
==============================================

These are a few small protocol extensions kitty implements, primarily for use
by its own kitten, they are documented here for completeness.


Simple save/restore of all terminal modes
--------------------------------------------

XTerm has the XTSAVE/XTRESTORE escape codes to save and restore terminal
private modes. However, they require specifying an explicit list of modes to
save/restore. kitty extends this protocol to specify that when no modes are
specified, all side-effect free modes should be saved/restored. By side-effects
we mean things that can affect other terminal state such as cursor position or
screen contents. Examples of modes that have side effects are: `DECOM
<https://vt100.net/docs/vt510-rm/DECOM.html>`__ and `DECCOLM
<https://vt100.net/docs/vt510-rm/DECCOLM.html>`__.

This allows TUI applications to easily save and restore emulator state without
needing to maintain lists of modes.


Independent control of bold and faint SGR properties
-------------------------------------------------------

In common terminal usage, bold is set via SGR 1 and faint by SGR 2. However,
there is only one number to reset these attributes, SGR 22, which resets both.
There is no way to reset one and not the other. kitty uses 221 and 222 to reset
bold and faint independently.

.. _mouse_leave_window:

Reporting when the mouse leaves the window
----------------------------------------------

kitty extends the SGR Pixel mouse reporting protocol created by xterm to
also report when the mouse leaves the window. This event is delivered
encoded as a normal SGR pixel event except that the eight bit is set on the
first number. Additionally, bit 5 is set to indicate this is a motion related event.
The remaining bits 1-7 (except 5) are used to encode button and modifier information.
When bit 8 is set it means the event is a mouse has left the window event,
and all other bits should be ignored. The pixel position values must also
be ignored as they may not be accurate.

An escape code to move the contents of the screen into the scrollback
-------------------------------------------------------------------------------------

The escape code is ``\x1b [ 22 J`` (ignoring spaces present for clarity). It
moves all screen contents (text and images) into the scrollback leaving the
screen in the same state as it would be if the standard screen clear escape
code had been used ``\x1b [ 2 J``.


.. _program_status:

Reporting the status of a program
-------------------------------------

kitty supports the `Program Status Protocol (OSC 7501)
<https://www.superlogical.com/rex/docs/build/program-status>`__, revision 0.4,
which lets a program tell the terminal what it is doing: idle, working,
finished, blocked waiting on the user or failed, and why. For example::

    printf '\e]7501;state=working:app=rsync:progress=40\e\\'

kitty keeps the records reported by programs per window and applies the
lifetime rules of the specification:

* :code:`working`, :code:`blocked` and :code:`idle` records are dropped when a
  new shell prompt starts (needs :ref:`shell_integration`) or when a program
  run with :option:`launch --hold` exits

* :code:`done` and :code:`error` records are kept until the window is focused
  or a key is pressed in it

* a full reset removes every record

The limit on the length of an :code:`id` is 263 bytes rather than the 128 bytes
in the specification, as 263 bytes is what the limits on the length and number
of its segments allow.

The status is shown in the tab bar via the :code:`tab.program_status` field of
:opt:`tab_title_template`, is reported in the output of ``kitten @ ls``, and
:ref:`watchers <watchers>` can react to it via
:code:`on_program_status_change`.


kitty specific private escape codes
---------------------------------------

These are a family of escape codes used by kitty for various things including
remote control. They are all DCS (Device Control String) escape codes starting
with ``\x1b P @ kitty-`` (ignoring spaces present for clarity).
