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
also report when the mouse leaves the window. This is event is delivered
encoded as a normal SGR pixel event except that the eight bit is set on the
first number. Additionally, bit 5 is set to indicate this is a motion related event.
The remaining bits 1-7 (except 5) are used to encode button and modifier information.
When bit 8 is set it means the event is a mouse has left the window event,
and all other bits should be ignored. The pixel position values must also
be ignored as they may not be accurate.


kitty specific private escape codes
---------------------------------------

These are a family of escape codes used by kitty for various things including
remote control. They are all DCS (Device Control String) escape codes starting
with ``\x1b P @ kitty-`` (ignoring spaces present for clarity).
