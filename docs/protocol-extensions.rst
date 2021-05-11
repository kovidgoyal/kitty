Extensions to the xterm protocol
===================================

|kitty| has a few extensions to the xterm protocol, to enable advanced features.
These are typically in the form of new or re-purposed escape codes. While these
extensions are currently |kitty| specific, it would be nice to get some of them
adopted more broadly, to push the state of terminal emulators forward.

The goal of these extensions is to be as small and unobtrusive as possible,
while filling in some gaps in the existing xterm protocol. In particular, one
of the goals of this specification is explicitly not to "re-imagine" the tty.
The tty should remain what it is -- a device for efficiently processing text
received as a simple byte stream. Another objective is to only move the minimum
possible amount of extra functionality into the terminal program itself. This
is to make it as easy to implement these protocol extensions as possible,
thereby hopefully encouraging their widespread adoption.

If you wish to discuss these extensions, propose additions/changes to them
please do so by opening issues in the `GitHub
<https://github.com/kovidgoyal/kitty/issues>`_ bug tracker.

.. contents::
   :local:

Colored and styled underlines
-------------------------------

|kitty| supports colored and styled (wavy) underlines. This is of particular
use in terminal editors such as vim and emacs to display red, wavy underlines
under mis-spelled words and/or syntax errors. This is done by re-purposing some
SGR escape codes that are not used in modern terminals (`CSI codes
<https://en.wikipedia.org/wiki/ANSI_escape_code#CSI_sequences>`_)

To set the underline style::

    <ESC>[4:0m  # this is no underline
    <ESC>[4:1m  # this is a straight underline
    <ESC>[4:2m  # this is a double underline
    <ESC>[4:3m  # this is a curly underline
    <ESC>[4:4m  # this is a dotted underline (not implemented in kitty)
    <ESC>[4:5m  # this is a dashed underline (not implemented in kitty)
    <ESC>[4m    # this is a straight underline (for backwards compat)
    <ESC>[24m   # this is no underline (for backwards compat)

To set the underline color (this is reserved and as far as I can tell not actually used for anything)::

    <ESC>[58...m

This works exactly like the codes ``38, 48`` that are used to set foreground and
background color respectively.

To reset the underline color (also previously reserved and unused)::

    <ESC>[59m

The underline color must remain the same under reverse video, if it has a
color, if not, it should follow the foreground color.

To detect support for this feature in a terminal emulator, query the terminfo database
for the ``Su`` boolean capability.

Graphics rendering
---------------------

See :doc:`/graphics-protocol` for a description
of this protocol to enable drawing of arbitrary raster images in the terminal.


.. _extended-key-protocol:

Keyboard handling
-------------------

kitty has a :doc:`keyboard protocol <keyboard-protocol>` for reporting key
presses to terminal applications that solves all key handling issues in
terminal applications.

.. _ext_styles:

Setting text styles/colors in arbitrary regions of the screen
------------------------------------------------------------------

There already exists an escape code to set *some* text attributes in arbitrary
regions of the screen, `DECCARA
<https://vt100.net/docs/vt510-rm/DECCARA.html>`_.  However, it is limited to
only a few attributes. |kitty| extends this to work with *all* SGR attributes.
So, for example, this can be used to set the background color in an arbitrary
region of the screen.

The motivation for this extension is the various problems with the existing
solution for erasing to background color, namely the *background color erase
(bce)* capability. See
`this discussion <https://github.com/kovidgoyal/kitty/issues/160#issuecomment-346470545>`_
and `this FAQ <https://invisible-island.net/ncurses/ncurses.faq.html#bce_mismatches>`_
for a summary of problems with *bce*.

For example, to set the background color to blue in a
rectangular region of the screen from (3, 4) to (10, 11), you use::

    <ESC>[2*x<ESC>[4;3;11;10;44$r<ESC>[*x


Saving and restoring colors
---------------------------------------------------------------------------------

It is often useful for a full screen application with its own color themes to
set the default foreground, background, selection and cursor colors and the
ANSI color table. This allows for various performance optimizations when
drawing the screen. The problem is that if the user previously used the escape
codes to change these colors herself, then running the full screen application
will lose her changes even after it exits. To avoid this, kitty introduces a
new pair of *OSC* escape codes to push and pop the current color values from a
stack::

    <ESC>]30001<ESC>\  # push onto stack
    <ESC>]30101<ESC>\  # pop from stack

These escape codes save/restore the colors, default
background, default foreground, selection background, selection foreground and
cursor color and the 256 colors of the ANSI color table.

.. note:: In July 2020, after several years, XTerm copied this protocol
   extension, without acknowledgement, and using incompatible escape codes
   (XTPUSHCOLORS, XTPOPCOLORS, XTREPORTCOLORS). And they decided to save not
   just the dynamic colors but the entire ANSI color table. In the interests of
   promoting interoperability, kitty added support for XTerm's escape codes as
   well, and changed this extension to also save/restore the entire ANSI color
   table.


Pasting to clipboard
----------------------

|kitty| implements the OSC 52 escape code protocol to get/set the clipboard
contents (controlled via the :opt:`clipboard_control` setting). There is one
difference in kitty's implementation compared to some other terminal emulators.
|kitty| allows sending arbitrary amounts of text to the clipboard. It does so
by modifying the protocol slightly. Successive OSC 52 escape codes to set the
clipboard will concatenate, so::

    <ESC>]52;c;<payload1><ESC>\
    <ESC>]52;c;<payload2><ESC>\

will result in the clipboard having the contents ``payload1 + payload2``. To
send a new string to the clipboard send an OSC 52 sequence with an invalid payload
first, for example::

    <ESC>]52;c;!<ESC>\

Here ``!`` is not valid base64 encoded text, so it clears the clipboard.
Further, since it is invalid, it should be ignored by terminal emulators
that do not support this extension, thereby making it safe to use, simply
always send it before starting a new OSC 52 paste, even if you aren't chunking
up large pastes, that way kitty won't concatenate your paste, and it will have
no ill-effects in other terminal emulators.

In case you're using software that can't be easily adapted to this
protocol extension, it can be disabled by specifying ``no-append`` to the
:opt:`clipboard_control` setting.


.. _unscroll:

Unscrolling the screen
-----------------------

This is a small extension to the `SD (Pan up) escape code
<https://vt100.net/docs/vt510-rm/SD.html>`_ from the VT-420 terminal. The
``SD`` escape code normally causes the text on screen to scroll down by the
specified number of lines, with empty lines appearing at the top of the screen.
This extension allows the new lines to be filled in from the scrollback buffer
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
<https://www.ecma-international.org/publications-and-standards/standards/ecma-48/>`_
and unused for any other purpose as far as I can tell. So for example, to
unscroll three lines, the escape code would be::

    CSI 3 + T

See `discussion here
<https://gitlab.freedesktop.org/terminal-wg/specifications/-/issues/30>`_.

.. versionadded:: 0.20.2


.. _desktop_notifications:


Desktop notifications
---------------------------------

|kitty| implements an extensible escape code (OSC 99) to show desktop
notifications. It is easy to use from shell scripts and fully extensible to
show title and body.  Clicking on the notification can optionally focus the
window it came from, and/or send an escape code back to the application running
in that window.

The design of the escape code is partially based on the discussion in
the defunct
`terminal-wg <https://gitlab.freedesktop.org/terminal-wg/specifications/-/issues/13>`_

The escape code has the form::

    <OSC> 99 ; metadata ; payload <terminator>

Here ``<OSC>`` is :code:`<ESC>]` and ``<terminator>`` is
:code:`<ESC><backslash>`.  The metadata is a section of colon separated
:code:`key=value` pairs. Every key must be a single character from the set
:code:`a-zA-Z` and every value must be a word consisting of characters from
the set :code:`a-zA-Z0-9-_/\+.,(){}[]*&^%$#@!`~`. The payload must be
interpreted based on the metadata section. The two semi-colons *must* always be
present even when no metadata is present.

Before going into details, lets see how one can display a simple, single line
notification from a shell script::

    printf '\x1b]99;;Hello world\x1b\\'

To show a message with a title and a body::

    printf '\x1b]99;i=1:d=0;Hello world\x1b\\'
    printf '\x1b]99;i=1:d=1:p=body;This is cool\x1b\\'

The most important key in the metadata is the ``p`` key, it controls how the
payload is interpreted. A value of ``title`` means the payload is setting the
title for the notification. A value of ``body`` means it is setting the body,
and so on, see the table below for full details.

The design of the escape code is fundamentally chunked, this is because
different terminal emulators have different limits on how large a single escape
code can be. Chunking is accomplished by the ``i`` and ``d`` keys. The ``i``
key is the *notification id* which can be any string containing the characters
``[a-zA-Z0-9_-+.]``. The ``d`` key stands for *done* and
can only take the values ``0`` and ``1``. A value of ``0`` means the
notification is not yet done and the terminal emulator should hold off
displaying it. A value of ``1`` means the notification is done, and should be
displayed. You can specify the title or body multiple times and the terminal
emulator will concatenate them, thereby allowing arbitrarily long text
(terminal emulators are free to impose a sensible limit to avoid
Denial-of-Service attacks).

Both the ``title`` and ``body`` payloads must be either UTF-8 encoded plain
text with no embedded escape codes, or UTF-8 text that is base64 encoded, in
which case there must be an ``e=1`` key in the metadata to indicate the payload
is base64 encoded.

When the user clicks the notification, a couple of things can happen, the
terminal emulator can focus the window from which the notification came, and/or
it can send back an escape code to the application indicating the notification
was activated. This is controlled by the ``a`` key which takes a comma
separated set of values, ``report`` and ``focus``. The value ``focus`` means
focus the window from which the notification was issued and is the default.
``report`` means send an escape code back to the application. The format of the
returned escape code is::

    <OSC> 99 ; i=identifier ; <terminator>

The value of ``identifier`` comes from the ``i`` key in the escape code sent by
the application. If the application sends no identifier, then the terminal
*must* use ``i=0``. Actions can be preceded by a negative sign to turn them
off, so for example if you do not want any action, turn off the default
``focus`` action with::

    a=-focus

Complete specification of all the metadata keys is in the table below. If a
terminal emulator encounters a key in the metadata it does not understand,
the key *must* be ignored, to allow for future extensibility of this escape
code. Similarly if values for known keys are unknown, the terminal emulator
*should* either ignore the entire escape code or perform a best guess effort
to display it based on what it does understand.

.. note::
   It is possible to extend this escape code to allow specifying an icon for
   the notification, however, given that some platforms, such as macOS, dont
   allow displaying custom icons on a notification, at all, it was decided to
   leave it out of the spec for the time being.

   Similarly, features such as scheduled notifications could be added in future
   revisions.


=======  ====================  =========  =================
Key      Value                 Default    Description
=======  ====================  =========  =================
``a``    Comma separated list  ``focus``  What action to perform when the
         of ``report``,                   notification is clicked
         ``focus``, with
         optional leading
         ``-``

``d``    ``0`` or ``1``        ``1``      Indicates if the notification is
                                          complete or not.

``e``    ``0`` or ``1``        ``0``      If set to ``1`` means the payload is base64 encoded UTF-8,
                                          otherwise it is plain UTF-8 text with no C0 control codes in it

``i``    ``[a-zA-Z0-9-_+.]``   ``0``      Identifier for the notification

``p``    One of ``title`` or   ``title``  Whether the payload is the notification title or body. If a
         ``body``.                        notification has no title, the body will be used as title.
=======  ====================  =========  =================


.. note::
   |kitty| also supports the legacy OSC 9 protocol developed by iTerm2 for
   desktop notifications.
