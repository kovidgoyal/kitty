Pasting to clipboard
=======================

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
