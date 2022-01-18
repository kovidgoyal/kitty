Colored and styled underlines
================================

|kitty| supports colored and styled (wavy) underlines. This is of particular
use in terminal editors such as vim and emacs to display red, wavy underlines
under mis-spelled words and/or syntax errors. This is done by re-purposing some
SGR escape codes that are not used in modern terminals (`CSI codes
<https://en.wikipedia.org/wiki/ANSI_escape_code#CSI_(Control_Sequence_Introducer)_sequences>`_)

To set the underline style::

    <ESC>[4:0m  # this is no underline
    <ESC>[4:1m  # this is a straight underline
    <ESC>[4:2m  # this is a double underline
    <ESC>[4:3m  # this is a curly underline
    <ESC>[4:4m  # this is a dotted underline
    <ESC>[4:5m  # this is a dashed underline
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
