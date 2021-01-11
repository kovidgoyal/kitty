A protocol for comprehensive keyboard handling in terminals
=================================================================

There are various problems with the current state of keyboard handling. They
include:

* No way to use modifiers other than ``Ctrl`` and ``Alt``

* No way to reliably use multiple modifier keys, other than, ``Shift+Alt``.

* No way to handle different types of keyboard events, such as press, release or repeat

* No reliable way to distinguish single ``Esc`` keypresses from the start of a
  escape sequence. Currently, client programs use fragile timing related hacks
  for this, leading to bugs, for example:
  `neovim #2035 <https://github.com/neovim/neovim/issues/2035>`_.

To solve these issues and others, kitty has created a new keyboard protocol,
that is backward compatible but allows applications to opt-in to support more
advanced usages. The protocol is based on initial work in `fixterms
<http://www.leonerd.org.uk/hacks/fixterms/>`_, however, it corrects various
issues in that proposal, listed at the :ref:`bottom of this document
<fixterms_bugs>`.

A basic overview
------------------

Key events are divided into two types, those that produce text and those that
do not. When a key event produces text, the text is sent directly as UTF-8
encoded bytes. This is safe as UTF-8 contains no C0 control codes.
When the key event does not have text, the key event is encoded as an escape code. In
legacy compatibility mode (the default) this uses legacy escape codes, so old terminal
applications continue to work. Key events that could not be represented in
legacy mode are encoded using a ``CSI u`` escape code, that most terminal
programs should just ignore. For more advanced features, such as release/repeat
reporting etc., applications can tell the terminal they want this information by
sending an escape code to toggle the mode.

The central escape code used to encode key events is::

    CSI unicode-key-code:alternate-key-codes ; modifiers:event-type u

Spaces in the above definition are present for clarity and should be ignored.
``CSI`` is the bytes ``0x1b 0x5b``. All parameters are decimal numbers. Fields
are separated by the semi-colon and sub-fields by the colon. Only the
``unicode-key-code`` field is mandatory, everything else is optional. The
escape code is terminated by the ``u`` character (the byte ``0x75``).


.. _key_codes:

Key codes
~~~~~~~~~~~~~~

The ``unicode-key-code`` above is the Unicode codepoint representing the key, as a
decimal number. For example, the :kbd:`A` key is represented as ``97`` which is
the unicode code for lowercase ``a``. Note that the codepoint used is *always*
the lower-case (or more technically, un-shifted) version of the key. If the
user presses, for example, :kbd:`ctrl+shift+a` the escape code would be ``CSI
97;modifiers u``. It *must not* by ``CSI 65; modifiers u``.

If *alternate key reporting* is requested by the program running in the
terminal, the terminal can send two additional Unicode codepoints, the
*shifted key* and *base layout key*, separated by colons.
The shifted key is simply the upper-case version of ``unicode-codepoint``, or
more technically, the shifted version. So `a` becomes `A` and so on, based on
the current keyboard layout. This is needed to be able to match against a
shortcut such as :kbd:`ctrl+plus` which depending on the type of keyboard could
be either :kbd:`ctrl+shift+equal` or :kbd:`ctrl+plus`.

The *base layout key* is the key corresponding to the physical key in the
standard PC-101 key layout. So for example, if the user is using a Cyrillic
keyboard with a Cyrillic keyboard layout pressing the :kbd:`ctrl+ц` key will
be :kbd:`ctrl+c` in the standard layout. So the terminal should send the *base
layout key* as ``99`` corresponding to the ``c`` key.

If only one alternate key is present, it is the *shifted key* if the terminal
wants to send only a base layout key but no shifted key, it must use an empty
sub-field for the shifted key, like this::

  CSI unicode-key-code::base-layout-key


.. _modifiers:

Modifiers
~~~~~~~~~~~~~~

This protocol supports four modifier keys, :kbd:`shift, alt, ctrl and super`.
Here super is either the *Windows/Linux* key or the *Cmd* key on mac keyboards.
Modifiers are encoded as a bit field with::

    shift 0b1     (1)
    alt   0b10    (2)
    ctrl  0b100   (4)
    super 0b1000  (8)

In the escape code, the modifier value is encoded as a decimal number which is
``1 + actual modifiers``. So to represent :kbd:`shift` only, the value would be ``1 +
1 = 2``, to represent :kbd:`ctrl+shift` the value would be ``1 + 0b101 = 5``
and so on. If the modifier field is not present in the escape code, its default
value is ``1`` which means no modifiers.


.. _event_types:

Event types
~~~~~~~~~~~~~~~~

There are three key event types: ``press, repeat and release``. They are
reported (if requested) as a sub-field of the modifiers field (separated by a
colon). If no modifiers are present, the modifiers field must have the value
``1`` and the event type sub-field the type of event. The ``press`` event type
has value ``1`` and is the default if no event type sub field is present. The
``repeat`` type is ``2`` and the ``release`` type is ``3``. So for example::

    CSI key-code;1    # this is a press event
    CSI key-code;1:1  # this is a press event
    CSI key-code;1:2  # this is a repeat event
    CSI key-code:1:3  # this is a release event


.. note:: Key events that result in text are reported as plain UTF-8 text, so
   events are not supported for them, unless the application requests *key
   report mode*, see below.


Non-Unicode keys
~~~~~~~~~~~~~~~~~~~~~~~

There are many keys that don't correspond to letters from human languages, and
thus aren't represented in Unicode. Think of functional keys, such as
:kbd:`Escape, Play, Pause, F1, Home, etc`. These are encoded using Unicode code
points from the Private Use Area (``57344 - 63743``). The mapping of key
names to code points for these keys is in the
:ref:`Functional key definition table below <functional>`.


.. _progressive_enhancement:

Progressive enhancement
--------------------------

While, in theory, every key event could be completely represented by this
protocol and all would be hunk-dory, in reality there is a vast universe of
existing terminal programs that expect legacy control codes for key events and
that are not likely to ever be updated. To support these, in default mode,
the terminal will emit legacy escape codes for compatibility. If a terminal
program wants more robust key handling, it can request it from the terminal,
via the mechanism described here. Each enhancement is described in detail
below. The escape code for requesting enhancements is::

    CSI = flags ; mode u

Here ``flags`` is a decimal encoded integer to specify a set of bit-flags. The
meanings of the flags are given below. The second, ``mode`` parameter is
optional (defaulting to ``1``) and specifies how the flags are applied.
The value ``1`` means all set bits are set and all unset bits are reset.
The value ``2`` means all set bits are set, unset bits are left unchanged.
The value ``3`` means all set bits are reset, unset bits are left unchanged.

.. csv-table:: The progressive enhancement flags
   :header: "Bit", "Meaning"

   "0b1 (1)", "Disambiguate escape codes"
   "0b10 (2)", "Report key event types"
   "0b100 (4)", "Report alternate keys"
   "0b1000 (8)", "Report all keys as ``CSI u`` escape codes"

The program running in the terminal can query the terminal for the
current values of the flags by sending::

    CSI ? u

The terminal will reply with::

    CSI ? flags u

The program can also push/pop the current flags onto a stack in the
terminal with::

    CSI > flags u  # for push, if flags ommitted default to zero
    CSI < number u # to pop number entries, defaulting to 1 if unspecified

Terminals should limit the size of the stack as appropriate, to prevent
Denial-of-Service attacks. Terminals must maintain separate stacks for the main
and alternate screens. If a pop request is received that empties the stack,
all flags are reset. If a push request is received and the stack is full, the
oldest entry from the stack must be evicted.

Disambiguate escape codes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This type of progressive enhancement fixes the problem of some legacy key
press encodings overlapping with other control codes. For instance, pressing
the :kbd:`Esc` key generates the byte ``0x1b`` which also is used to indicate
the start of an escape code. Similarly pressing the key :kbd:`alt+[` will
generate the bytes used for CSI control codes. Turning on this flag will cause
the terminal to report the :kbd:`Esc, alt+letter, ctrl+letter, ctrl+alt+letter`
keys using ``CSI u`` sequences instead of legacy ones. Here letter is any printable
ASCII letter (from 32 (i.e. space) to 126 (i.e. ~)).

Report event types
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This type of progressive enhancement causes the terminal to report key repeat
and key release events. Normally only key press events are reported and key
repeat events are treated as key press events. See :ref:`event_types` for
details on how these are reported.


Report alternate keys
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This type of progressive enhancement causes the terminal to report alternate
key values in addition to the main value, to aid in shortcut matching. See
:ref:`key_codes` for details on how these are reported.

Legacy key event encoding
--------------------------------

In the default mode, the terminal uses a legacy encoding for key events. In
this encoding, only key press and repeat events are sent and there is no
way to distinguish between them. Text is sent directly as UTF-8 bytes.

Any key events not described in this section are sent using the standard
``CSI u`` encoding. This includes keys that are not encodeable in the legacy
encoding, thereby increasing the space of useable key combinations even without
progressive enhancement.

Legacy functional keys
~~~~~~~~~~~~~~~~~~~~~~~~

These keys are encoded using three schemes::

    CSI number ; modifier ~
    CSI 1 ; modifier {ABCDFHPQRS}
    ESC O {ABCDFHPQRS}

In the above, if there are no modifiers, the modifier parameter is omitted.
The modifier value is encoded as described in the :ref:`modifiers` section,
above. When the second form is used, the number is always ``1`` and must be
omitted if the modifiers field is also absent. The third form becomes the
second form when modifiers are present.

These sequences must match entries in the terminfo database for maximum
compatibility. The table below lists the key, its terminfo entry name and
the escape code used for it by kitty. A different terminal would use whatever
escape code is present in its terminfo database for the key.
Some keys have an alternate representation when the terminal is in *cursor key
mode* (the ``smkx/rmkx`` terminfo capabilities). This form is used only in
*cursor key mode* and only when no modifiers are present.

.. csv-table:: Legacy functional encoding
   :header: "Name", "Terminfo name", "Escape code"

    "INSERT",    "kich1",      "CSI 2 ~"
    "DELETE",    "kdch1",      "CSI 3 ~"
    "PAGE_UP",   "kpp",        "CSI 5 ~"
    "PAGE_DOWN", "knp",        "CSI 6 ~"
    "UP",        "cuu1,kcuu1", "CSI A, ESC O A"
    "DOWN",      "cud1,kcud1", "CSI B, ESC O B"
    "RIGHT",     "cuf1,kcuf1", "CSI C, ESC O C"
    "LEFT",      "cub1,kcub1", "CSI D, ESC O D"
    "HOME",      "home,khome", "CSI H, ESC O H"
    "END",       "-,kend",     "CSI F, ESC O F"
    "F1",        "kf1",        "ESC O P"
    "F2",        "kf2",        "ESC O Q"
    "F3",        "kf3",        "ESC O R"
    "F4",        "kf4",        "ESC O S"
    "F5",        "kf5",        "CSI 15 ~"
    "F6",        "kf6",        "CSI 17 ~"
    "F7",        "kf7",        "CSI 18 ~"
    "F8",        "kf8",        "CSI 19 ~"
    "F9",        "kf9",        "CSI 20 ~"
    "F10",       "kf10",       "CSI 21 ~"
    "F11",       "kf11",       "CSI 23 ~"
    "F12",       "kf12",       "CSI 24 ~"

Finally, there are a few more functional keys that have special cased legacy
encodings:

.. csv-table:: C0 controls
    :header: "Key", "Encodings"

    "Enter",     "Plain - 0xd,  alt+Enter - 0x1b 0x1d"
    "Escape",    "Plain - 0x1b, alt+Esc - 0x1b 0x1b"
    "Backspace", "Plain - 0x7f, alt+Backspace - 0x1b 0x7f, ctrl+Backspace - 0x08"
    "Space",     "Plain - 0x20, ctrl+space - 0x0, alt+space - 0x1b 0x20"
    "Tab",       "Plain - 0x09, shift+tab - CSI Z"

Note that :kbd:`Backspace` and :kbd:`ctrl+backspace` are swapped in some
terminals.

Legacy text keys
~~~~~~~~~~~~~~~~~~~



.. _functional:

Functional key definitions
----------------------------

All numbers are in the Unicode Private Use Area (``57344 - 63743``) except
for a handful of keys that use numbers under 32 and 127 (C0 control codes) for legacy
compatibility reasons.

.. {{{
.. start functional key table (auto generated by gen-key-constants.py do not edit)

.. csv-table:: Functional key codes
   :header: "Name", "CSI sequence"

   "ESCAPE",                 "CSI 57344 ... u"
   "ENTER",                  "CSI 13 ... u"
   "TAB",                    "CSI 9 ... u"
   "BACKSPACE",              "CSI 127 ... u"
   "INSERT",                 "CSI 2 ... ~"
   "DELETE",                 "CSI 3 ... ~"
   "LEFT",                   "CSI 1 ... D"
   "RIGHT",                  "CSI 1 ... C"
   "UP",                     "CSI 1 ... A"
   "DOWN",                   "CSI 1 ... B"
   "PAGE_UP",                "CSI 5 ... ~"
   "PAGE_DOWN",              "CSI 6 ... ~"
   "HOME",                   "CSI 1 ... H or CSI 7 ... ~"
   "END",                    "CSI 1 ... F or CSI 8 ... ~"
   "CAPS_LOCK",              "CSI 57358 ... u"
   "SCROLL_LOCK",            "CSI 57359 ... u"
   "NUM_LOCK",               "CSI 57360 ... u"
   "PRINT_SCREEN",           "CSI 57361 ... u"
   "PAUSE",                  "CSI 57362 ... u"
   "MENU",                   "CSI 57363 ... u"
   "F1",                     "CSI 1 ... P or CSI 11 ... ~"
   "F2",                     "CSI 1 ... Q or CSI 12 ... ~"
   "F3",                     "CSI 1 ... R or CSI 57366 ... ~"
   "F4",                     "CSI 1 ... S or CSI 14 ... ~"
   "F5",                     "CSI 15 ... ~"
   "F6",                     "CSI 17 ... ~"
   "F7",                     "CSI 18 ... ~"
   "F8",                     "CSI 19 ... ~"
   "F9",                     "CSI 20 ... ~"
   "F10",                    "CSI 21 ... ~"
   "F11",                    "CSI 23 ... ~"
   "F12",                    "CSI 24 ... ~"
   "F13",                    "CSI 57376 ... u"
   "F14",                    "CSI 57377 ... u"
   "F15",                    "CSI 57378 ... u"
   "F16",                    "CSI 57379 ... u"
   "F17",                    "CSI 57380 ... u"
   "F18",                    "CSI 57381 ... u"
   "F19",                    "CSI 57382 ... u"
   "F20",                    "CSI 57383 ... u"
   "F21",                    "CSI 57384 ... u"
   "F22",                    "CSI 57385 ... u"
   "F23",                    "CSI 57386 ... u"
   "F24",                    "CSI 57387 ... u"
   "F25",                    "CSI 57388 ... u"
   "F26",                    "CSI 57389 ... u"
   "F27",                    "CSI 57390 ... u"
   "F28",                    "CSI 57391 ... u"
   "F29",                    "CSI 57392 ... u"
   "F30",                    "CSI 57393 ... u"
   "F31",                    "CSI 57394 ... u"
   "F32",                    "CSI 57395 ... u"
   "F33",                    "CSI 57396 ... u"
   "F34",                    "CSI 57397 ... u"
   "F35",                    "CSI 57398 ... u"
   "KP_0",                   "CSI 57399 ... u"
   "KP_1",                   "CSI 57400 ... u"
   "KP_2",                   "CSI 57401 ... u"
   "KP_3",                   "CSI 57402 ... u"
   "KP_4",                   "CSI 57403 ... u"
   "KP_5",                   "CSI 57404 ... u"
   "KP_6",                   "CSI 57405 ... u"
   "KP_7",                   "CSI 57406 ... u"
   "KP_8",                   "CSI 57407 ... u"
   "KP_9",                   "CSI 57408 ... u"
   "KP_DECIMAL",             "CSI 57409 ... u"
   "KP_DIVIDE",              "CSI 57410 ... u"
   "KP_MULTIPLY",            "CSI 57411 ... u"
   "KP_SUBTRACT",            "CSI 57412 ... u"
   "KP_ADD",                 "CSI 57413 ... u"
   "KP_ENTER",               "CSI 57414 ... u"
   "KP_EQUAL",               "CSI 57415 ... u"
   "KP_SEPARATOR",           "CSI 57416 ... u"
   "KP_LEFT",                "CSI 57417 ... u"
   "KP_RIGHT",               "CSI 57418 ... u"
   "KP_UP",                  "CSI 57419 ... u"
   "KP_DOWN",                "CSI 57420 ... u"
   "KP_PAGE_UP",             "CSI 57421 ... u"
   "KP_PAGE_DOWN",           "CSI 57422 ... u"
   "KP_HOME",                "CSI 57423 ... u"
   "KP_END",                 "CSI 57424 ... u"
   "KP_INSERT",              "CSI 57425 ... u"
   "KP_DELETE",              "CSI 57426 ... u"
   "LEFT_SHIFT",             "CSI 57427 ... u"
   "LEFT_CONTROL",           "CSI 57428 ... u"
   "LEFT_ALT",               "CSI 57429 ... u"
   "LEFT_SUPER",             "CSI 57430 ... u"
   "RIGHT_SHIFT",            "CSI 57431 ... u"
   "RIGHT_CONTROL",          "CSI 57432 ... u"
   "RIGHT_ALT",              "CSI 57433 ... u"
   "RIGHT_SUPER",            "CSI 57434 ... u"
   "MEDIA_PLAY",             "CSI 57435 ... u"
   "MEDIA_PAUSE",            "CSI 57436 ... u"
   "MEDIA_PLAY_PAUSE",       "CSI 57437 ... u"
   "MEDIA_REVERSE",          "CSI 57438 ... u"
   "MEDIA_STOP",             "CSI 57439 ... u"
   "MEDIA_FAST_FORWARD",     "CSI 57440 ... u"
   "MEDIA_REWIND",           "CSI 57441 ... u"
   "MEDIA_TRACK_NEXT",       "CSI 57442 ... u"
   "MEDIA_TRACK_PREVIOUS",   "CSI 57443 ... u"
   "MEDIA_RECORD",           "CSI 57444 ... u"
   "LOWER_VOLUME",           "CSI 57445 ... u"
   "RAISE_VOLUME",           "CSI 57446 ... u"
   "MUTE_VOLUME",            "CSI 57447 ... u"

.. end functional key table
.. }}}

.. _fixterms_bugs:

Bugs in fixterms
-------------------

  * No way to disambiguate :kbd:`Esc` keypresses, other than using 8-bit controls
    which are undesirable for other reasons
  * Incorrectly claims special keys are sometimes encoded using ``CSI letter`` encodings when it
    is actually ``ESC O letter``.
  * ``Enter`` and ``F3`` are both assigned the number 13.
  * Makes no mention of cursor key mode and how it changes encodings
  * Incorrectly encoding shifted keys when shift modifier is used, for
    instance, for :kbd:`ctrl+shift+I`.
  * No way to have non-conflicting escape codes for :kbd:`alt+letter,
    ctrl+letter, ctrl+alt+letter` key presses
  * No way to specify both shifted and unshifted keys for robust shortcut
    matching (think matching :kbd:`ctrl+shift+equal` and :kbd:`ctrl+plus`)
  * No way to specify alternate layout key. This is useful for keyboard layouts
    such as Cyrillic where you want the shortcut :kbd:`ctrl+c` to work when
    pressing the :kbd:`ctrl+ц` on the keyboard.
  * No way to report repeat and release key events, only key press events
  * No way to report key events for presses that generate text, useful for
    gaming. Think of using the :kbd:`WASD` keys to control movement.
  * Only a small subset of all possible functional keys are assigned numbers.
