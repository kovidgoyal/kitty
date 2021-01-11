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
issues in that proposal, namely:

  * No way to disambiguate :kbd:`Esc` keypresses, other than using 8-bit controls
    which are undesirable for other reasons
  * Incorrectly encoding shifted keys when shift modifier is used
  * No way to have non-conflicting escape codes for :kbd:`alt+letter,
    ctrl+letter, ctrl+alt+letter` key presses
  * No way to specify both shifted and unshifted keys for robust shortcut
    matching (think matching :kbd:`ctrl+shift+equal` and :kbd:`ctrl+plus`)
  * No way to specify alternate layout key. This is useful for keyboard layouts
    such as Cyrillic where you want the shortcut :kbd:`ctrl+c` to work when
    pressing the :kbd:`ctrl+ц` on the keyboard.
  * No way to report repeat and release key events, only key press events
  * No way to report key events without text, useful for gaming. Think of using
    the :kbd:`WASD` keys to control movement.
  * A very small subset of all possible functional keys are specified.


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
points from the Private Use Area (``0xe000 - 0xf8ff``). The mapping of key
names to code points for these keys is in the
:ref:`Functional key definition table below <functional>`.


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
   "0b1000 (8)", "Report all keys as CSIu escape codes"

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
keys using CSIu sequences instead of legacy ones. Here letter is any printable
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

.. _functional:

Functional key definitions
----------------------------

.. {{{
.. start functional key table (auto generated by gen-key-constants.py do not edit)

.. csv-table:: Functional key codes
   :header: "Name", "Codepoint (base-16)"

   "ESCAPE", "E000"
   "ENTER", "E001"
   "TAB", "E002"
   "BACKSPACE", "E003"
   "INSERT", "E004"
   "DELETE", "E005"
   "LEFT", "E006"
   "RIGHT", "E007"
   "UP", "E008"
   "DOWN", "E009"
   "PAGE_UP", "E00A"
   "PAGE_DOWN", "E00B"
   "HOME", "E00C"
   "END", "E00D"
   "CAPS_LOCK", "E00E"
   "SCROLL_LOCK", "E00F"
   "NUM_LOCK", "E010"
   "PRINT_SCREEN", "E011"
   "PAUSE", "E012"
   "MENU", "E013"
   "F1", "E014"
   "F2", "E015"
   "F3", "E016"
   "F4", "E017"
   "F5", "E018"
   "F6", "E019"
   "F7", "E01A"
   "F8", "E01B"
   "F9", "E01C"
   "F10", "E01D"
   "F11", "E01E"
   "F12", "E01F"
   "F13", "E020"
   "F14", "E021"
   "F15", "E022"
   "F16", "E023"
   "F17", "E024"
   "F18", "E025"
   "F19", "E026"
   "F20", "E027"
   "F21", "E028"
   "F22", "E029"
   "F23", "E02A"
   "F24", "E02B"
   "F25", "E02C"
   "F26", "E02D"
   "F27", "E02E"
   "F28", "E02F"
   "F29", "E030"
   "F30", "E031"
   "F31", "E032"
   "F32", "E033"
   "F33", "E034"
   "F34", "E035"
   "F35", "E036"
   "KP_0", "E037"
   "KP_1", "E038"
   "KP_2", "E039"
   "KP_3", "E03A"
   "KP_4", "E03B"
   "KP_5", "E03C"
   "KP_6", "E03D"
   "KP_7", "E03E"
   "KP_8", "E03F"
   "KP_9", "E040"
   "KP_DECIMAL", "E041"
   "KP_DIVIDE", "E042"
   "KP_MULTIPLY", "E043"
   "KP_SUBTRACT", "E044"
   "KP_ADD", "E045"
   "KP_ENTER", "E046"
   "KP_EQUAL", "E047"
   "KP_SEPARATOR", "E048"
   "KP_LEFT", "E049"
   "KP_RIGHT", "E04A"
   "KP_UP", "E04B"
   "KP_DOWN", "E04C"
   "KP_PAGE_UP", "E04D"
   "KP_PAGE_DOWN", "E04E"
   "KP_HOME", "E04F"
   "KP_END", "E050"
   "KP_INSERT", "E051"
   "KP_DELETE", "E052"
   "LEFT_SHIFT", "E053"
   "LEFT_CONTROL", "E054"
   "LEFT_ALT", "E055"
   "LEFT_SUPER", "E056"
   "RIGHT_SHIFT", "E057"
   "RIGHT_CONTROL", "E058"
   "RIGHT_ALT", "E059"
   "RIGHT_SUPER", "E05A"
   "MEDIA_PLAY", "E05B"
   "MEDIA_PAUSE", "E05C"
   "MEDIA_PLAY_PAUSE", "E05D"
   "MEDIA_REVERSE", "E05E"
   "MEDIA_STOP", "E05F"
   "MEDIA_FAST_FORWARD", "E060"
   "MEDIA_REWIND", "E061"
   "MEDIA_TRACK_NEXT", "E062"
   "MEDIA_TRACK_PREVIOUS", "E063"
   "MEDIA_RECORD", "E064"
   "LOWER_VOLUME", "E065"
   "RAISE_VOLUME", "E066"
   "MUTE_VOLUME", "E067"

.. end functional key table
.. }}}
