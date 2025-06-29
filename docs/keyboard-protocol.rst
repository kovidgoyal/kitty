Comprehensive keyboard handling in terminals
==============================================

There are various problems with the current state of keyboard handling in
terminals. They include:

* No way to use modifiers other than ``ctrl`` and ``alt``

* No way to reliably use multiple modifier keys, other than, ``shift+alt`` and
  ``ctrl+alt``.

* Many of the existing escape codes used to encode these events are ambiguous
  with different key presses mapping to the same escape code.

* No way to handle different types of keyboard events, such as press, release or repeat

* No reliable way to distinguish single ``Esc`` key presses from the start of a
  escape sequence. Currently, client programs use fragile timing related hacks
  for this, leading to bugs, for example:
  `neovim #2035 <https://github.com/neovim/neovim/issues/2035>`_.

To solve these issues and others, kitty has created a new keyboard protocol,
that is backward compatible but allows applications to opt-in to support more
advanced usages. The protocol is based on initial work in `fixterms
<http://www.leonerd.org.uk/hacks/fixterms/>`_, however, it corrects various
issues in that proposal, listed at the :ref:`bottom of this document
<fixterms_bugs>`. For public discussion of this spec, see :iss:`3248`.

You can see this protocol with all enhancements in action by running::

    kitten show-key -m kitty

inside the kitty terminal to report key events.

In addition to kitty, this protocol is also implemented in:

* The `alacritty terminal <https://github.com/alacritty/alacritty/pull/7125>`__
* The `ghostty terminal <https://ghostty.org>`__
* The `foot terminal <https://codeberg.org/dnkl/foot/issues/319>`__
* The `iTerm2 terminal <https://gitlab.com/gnachman/iterm2/-/issues/10017>`__
* The `rio terminal <https://github.com/raphamorim/rio/commit/cd463ca37677a0fc48daa8795ea46dadc92b1e95>`__
* The `WezTerm terminal <https://wezfurlong.org/wezterm/config/lua/config/enable_kitty_keyboard.html>`__

Libraries implementing this protocol:

* The `notcurses library <https://github.com/dankamongmen/notcurses/issues/2131>`__
* The `crossterm library <https://github.com/crossterm-rs/crossterm/pull/688>`__
* The `textual library <https://github.com/Textualize/textual/pull/4631>`__
* The vaxis library `go <https://sr.ht/~rockorager/vaxis/>`__ and `zig <https://github.com/rockorager/libvaxis/>`__

Programs implementing this protocol:

* The `Vim text editor <https://github.com/vim/vim/commit/63a2e360cca2c70ab0a85d14771d3259d4b3aafa>`__
* The `Emacs text editor via the kkp package <https://github.com/benjaminor/kkp>`__
* The `Neovim text editor <https://github.com/neovim/neovim/pull/18181>`__
* The `kakoune text editor <https://github.com/mawww/kakoune/issues/4103>`__
* The `dte text editor <https://gitlab.com/craigbarnes/dte/-/issues/138>`__
* The `Helix text editor <https://github.com/helix-editor/helix/pull/4939>`__
* The `far2l file manager <https://github.com/elfmz/far2l/commit/e1f2ee0ef2b8332e5fa3ad7f2e4afefe7c96fc3b>`__
* The `Yazi file manager <https://github.com/sxyazi/yazi>`__
* The `awrit web browser <https://github.com/chase/awrit>`__
* The `Turbo Vision <https://github.com/magiblot/tvision/commit/6e5a7b46c6634079feb2ac98f0b890bbed59f1ba>`__/`Free Vision <https://gitlab.com/freepascal.org/fpc/source/-/issues/40673#note_2061428120>`__ IDEs
* The `aerc email client <https://git.sr.ht/~rjarry/aerc/commit/d73cf33c2c6c3e564ce8aff04acc329a06eafc54>`__

Shells implementing this protocol:

* The `nushell shell <https://github.com/nushell/nushell/pull/10540>`__
* The `fish shell <https://github.com/fish-shell/fish-shell/commit/8bf8b10f685d964101f491b9cc3da04117a308b4>`__

.. versionadded:: 0.20.0

Quickstart
---------------

If you are an application or library developer just interested in using this
protocol to make keyboard handling simpler and more robust in your application,
without too many changes, do the following:

#. Emit the escape code ``CSI > 1 u`` at application startup if using the main
   screen or when entering alternate screen mode, if using the alternate
   screen.
#. All key events will now be sent in only a few forms to your application,
   that are easy to parse unambiguously.
#. Emit the escape sequence ``CSI < u`` at application exit if using the main
   screen or just before leaving alternate screen mode if using the alternate screen,
   to restore whatever the keyboard mode was before step 1.

Key events will all be delivered to your application either as plain UTF-8
text, or using the following escape codes, for those keys that do not produce
text (``CSI`` is the bytes ``0x1b 0x5b``)::

    CSI number ; modifiers [u~]
    CSI 1; modifiers [ABCDEFHPQS]
    0x0d - for the Enter key
    0x7f or 0x08 - for Backspace
    0x09 - for Tab

The ``number`` in the first form above will be either the Unicode codepoint for a
key, such as ``97`` for the :kbd:`a` key, or one of the numbers from the
:ref:`functional` table below. The ``modifiers`` optional parameter encodes any
modifiers active for the key event. The encoding is described in the
:ref:`modifiers` section.

The second form is used for a few functional keys, such as the :kbd:`Home`,
:kbd:`End`, :kbd:`Arrow` keys and :kbd:`F1` ... :kbd:`F4`, they are enumerated in
the :ref:`functional` table below.  Note that if no modifiers are present the
parameters are omitted entirely giving an escape code of the form ``CSI
[ABCDEFHPQS]``.

If you want support for more advanced features such as repeat and release
events, alternate keys for shortcut matching et cetera, these can be turned on
using :ref:`progressive_enhancement` as documented in the rest of this
specification.

An overview
------------------

Key events are divided into two types, those that produce text and those that
do not. When a key event produces text, the text is sent directly as UTF-8
encoded bytes. This is safe as UTF-8 contains no C0 control codes.
When the key event does not have text, the key event is encoded as an escape code. In
legacy compatibility mode (the default) this uses legacy escape codes, so old terminal
applications continue to work. For more advanced features, such as release/repeat
reporting etc., applications can tell the terminal they want this information by
sending an escape code to :ref:`progressively enhance <progressive_enhancement>` the data reported for
key events.

The central escape code used to encode key events is::

    CSI unicode-key-code:alternate-key-codes ; modifiers:event-type ; text-as-codepoints u

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
97;modifiers u``. It *must not* be ``CSI 65; modifiers u``.

If *alternate key reporting* is requested by the program running in the
terminal, the terminal can send two additional Unicode codepoints, the *shifted
key* and *base layout key*, separated by colons. The shifted key is simply the
upper-case version of ``unicode-codepoint``, or more technically, the shifted
version, in the currently active keyboard layout. So `a` becomes `A` and so on,
based on the current keyboard layout. This is needed to be able to match
against a shortcut such as :kbd:`ctrl+plus` which depending on the type of
keyboard could be either :kbd:`ctrl+shift+equal` or :kbd:`ctrl+plus`. Note that
the shifted key must be present only if shift is also present in the modifiers.

The *base layout key* is the key corresponding to the physical key in the
standard PC-101 key layout. So for example, if the user is using a Cyrillic
keyboard with a Cyrillic keyboard layout pressing the :kbd:`ctrl+С` key will
be :kbd:`ctrl+c` in the standard layout. So the terminal should send the *base
layout key* as ``99`` corresponding to the ``c`` key.

If only one alternate key is present, it is the *shifted key*. If the terminal
wants to send only a base layout key but no shifted key, it must use an empty
sub-field for the shifted key, like this::

  CSI unicode-key-code::base-layout-key


.. _modifiers:

Modifiers
~~~~~~~~~~~~~~

This protocol supports six modifier keys, :kbd:`shift`, :kbd:`alt`,
:kbd:`ctrl`, :kbd:`super`, :kbd:`hyper`, :kbd:`meta`, :kbd:`num_lock` and
:kbd:`caps_lock`. Here :kbd:`super` is either the *Windows/Linux* key or the
:kbd:`command` key on mac keyboards. The :kbd:`alt` key is the :kbd:`option`
key on mac keyboards. :kbd:`hyper` and :kbd:`meta` are typically present only
on X11/Wayland based systems with special XKB rules. Modifiers are encoded as a
bit field with::

    shift     0b1         (1)
    alt       0b10        (2)
    ctrl      0b100       (4)
    super     0b1000      (8)
    hyper     0b10000     (16)
    meta      0b100000    (32)
    caps_lock 0b1000000   (64)
    num_lock  0b10000000  (128)

In the escape code, the modifier value is encoded as a decimal number which is
``1 + actual modifiers``. So to represent :kbd:`shift` only, the value would be
``1 + 1 = 2``, to represent :kbd:`ctrl+shift` the value would be ``1 + 0b101 =
6`` and so on. If the modifier field is not present in the escape code, its
default value is ``1`` which means no modifiers. If a modifier is *active* when
the key event occurs, i.e. if the key is pressed or the lock (for caps lock/num
lock) is enabled, the key event must have the bit for that modifier set.

When the key event is related to an actual modifier key, the corresponding
modifier's bit must be set to the modifier state including the effect for the
current event. For example, when pressing the :kbd:`LEFT_CONTROL` key, the
``ctrl`` bit must be set and when releasing it, it must be reset. When both
left and right control keys are pressed and one is released, the release event
must have the ``ctrl`` bit set. See :iss:`6913` for discussion of this design.

.. _event_types:

Event types
~~~~~~~~~~~~~~~~

There are three key event types: ``press, repeat and release``. They are
reported (if requested ``0b10``) as a sub-field of the modifiers field
(separated by a colon). If no modifiers are present, the modifiers field must
have the value ``1`` and the event type sub-field the type of event. The
``press`` event type has value ``1`` and is the default if no event type sub
field is present. The ``repeat`` type is ``2`` and the ``release`` type is
``3``. So for example::

    CSI key-code             # this is a press event
    CSI key-code;modifier    # this is a press event
    CSI key-code;modifier:1  # this is a press event
    CSI key-code;modifier:2  # this is a repeat event
    CSI key-code;modifier:3  # this is a release event


.. note:: Key events that result in text are reported as plain UTF-8 text, so
   events are not supported for them, unless the application requests *key
   report mode*, see below.

.. _text_as_codepoints:

Text as code points
~~~~~~~~~~~~~~~~~~~~~

The terminal can optionally send the text associated with key events as a
sequence of Unicode code points. This behavior is opt-in by the :ref:`progressive
enhancement <progressive_enhancement>` mechanism described below. Some examples::

    shift+a -> CSI 97 ; 2 ; 65 u  # The text 'A' is reported as 65
    option+a -> CSI 97 ; ; 229 u  # The text 'å' is reported as 229

If multiple code points are present, they must be separated by colons.  If no
known key is associated with the text the key number ``0`` must be used. The
associated text must not contain control codes (control codes are code points
below U+0020 and codepoints in the C0 and C1 blocks). In the above example, the
:kbd:`option` modifier is consumed by macOS itself to produce the text å
and therefore not reported in the keyboard protocol. On some platforms
composition keys might produce no key information at all, in which case the key
number ``0`` must be used.


Non-Unicode keys
~~~~~~~~~~~~~~~~~~~~~~~

There are many keys that don't correspond to letters from human languages, and
thus aren't represented in Unicode. Think of functional keys, such as
:kbd:`Escape`, :kbd:`Play`, :kbd:`Pause`, :kbd:`F1`, :kbd:`Home`, etc. These
are encoded using Unicode code points from the Private Use Area (``57344 -
63743``). The mapping of key names to code points for these keys is in the
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

   "0b1 (1)", ":ref:`disambiguate`"
   "0b10 (2)", ":ref:`report_events`"
   "0b100 (4)", ":ref:`report_alternates`"
   "0b1000 (8)", ":ref:`report_all_keys`"
   "0b10000 (16)", ":ref:`report_text`"

The program running in the terminal can query the terminal for the
current values of the flags by sending::

    CSI ? u

The terminal will reply with::

    CSI ? flags u

The program can also push/pop the current flags onto a stack in the
terminal with::

    CSI > flags u  # for push, if flags omitted default to zero
    CSI < number u # to pop number entries, defaulting to 1 if unspecified

Terminals should limit the size of the stack as appropriate, to prevent
Denial-of-Service attacks. Terminals must maintain separate stacks for the main
and alternate screens. If a pop request is received that empties the stack,
all flags are reset. If a push request is received and the stack is full, the
oldest entry from the stack must be evicted.

.. note:: The main and alternate screens in the terminal emulator must maintain
   their own, independent, keyboard mode stacks. This is so that a program that
   uses the alternate screen such as an editor, can change the keyboard mode
   in the alternate screen only, without affecting the mode in the main screen
   or even knowing what that mode is. Without this, and if no stack is
   implemented for keyboard modes (such as in some legacy terminal emulators)
   the editor would have to somehow know what the keyboard mode of the main
   screen is and restore to that mode on exit.

.. _disambiguate:

Disambiguate escape codes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This type of progressive enhancement (``0b1``) fixes the problem of some legacy key press
encodings overlapping with other control codes. For instance, pressing the
:kbd:`Esc` key generates the byte ``0x1b`` which also is used to indicate the
start of an escape code. Similarly pressing the key :kbd:`alt+[` will generate
the bytes used for CSI control codes.

Turning on this flag will cause the terminal to report the :kbd:`Esc`, :kbd:`alt+key`,
:kbd:`ctrl+key`, :kbd:`ctrl+alt+key`, :kbd:`shift+alt+key` keys using ``CSI u`` sequences instead
of legacy ones. Here key is any ASCII key as described in :ref:`legacy_text`.
Additionally, all non text keypad keys will be reported as separate keys with ``CSI u``
encoding, using dedicated numbers from the :ref:`table below <functional>`.

With this flag turned on, all key events that do not generate text are
represented in one of the following two forms::

    CSI number; modifier u
    CSI 1; modifier [~ABCDEFHPQS]

This makes it very easy to parse key events in an application. In particular,
:kbd:`ctrl+c` will no longer generate the ``SIGINT`` signal, but instead be
delivered as a ``CSI u`` escape code. This has the nice side effect of making it
much easier to integrate into the application event loop. The only exceptions
are the :kbd:`Enter`, :kbd:`Tab` and :kbd:`Backspace` keys which still generate the same
bytes as in legacy mode this is to allow the user to type and execute commands
in the shell such as ``reset`` after a program that sets this mode crashes
without clearing it. Note that the Lock modifiers are not reported for text
producing keys, to keep them usable in legacy programs. To get lock modifiers
for all keys use the :ref:`report_all_keys` enhancement.

.. _report_events:

Report event types
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This progressive enhancement (``0b10``) causes the terminal to report key repeat
and key release events. Normally only key press events are reported and key
repeat events are treated as key press events. See :ref:`event_types` for
details on how these are reported.

.. note::

   The :kbd:`Enter`, :kbd:`Tab` and :kbd:`Backspace` keys will not have release
   events unless :ref:`report_all_keys` is also set, so that the user can still
   type reset at a shell prompt when a program that sets this mode ends without
   resetting it.

.. _report_alternates:

Report alternate keys
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This progressive enhancement (``0b100``) causes the terminal to report
alternate key values *in addition* to the main value, to aid in shortcut
matching. See :ref:`key_codes` for details on how these are reported. Note that
this flag is a pure enhancement to the form of the escape code used to
represent key events, only key events represented as escape codes due to the
other enhancements in effect will be affected by this enhancement. In other
words, only if a key event was already going to be represented as an escape
code due to one of the other enhancements will this enhancement affect it.

.. _report_all_keys:

Report all keys as escape codes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Key events that generate text, such as plain key presses without modifiers,
result in just the text being sent, in the legacy protocol. There is no way to
be notified of key repeat/release events. These types of events are needed for
some applications, such as games (think of movement using the ``WASD`` keys).

This progressive enhancement (``0b1000``) turns on key reporting even for key
events that generate text. When it is enabled, text will not be sent, instead
only key events are sent. If the text is needed as well, combine with the
Report associated text enhancement below.

Additionally, with this mode, events for pressing modifier keys are reported.
Note that *all* keys are reported as escape codes, including :kbd:`Enter`,
:kbd:`Tab`, :kbd:`Backspace` etc. Note that this enhancement implies all keys
are automatically disambiguated as well, since they are represented in their
canonical escape code form.

.. _report_text:

Report associated text
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This progressive enhancement (``0b10000``) *additionally* causes key events that
generate text to be reported as ``CSI u`` escape codes with the text embedded
in the escape code. See :ref:`text_as_codepoints` above for details on the
mechanism. Note that this flag is an enhancement to :ref:`report_all_keys`
and is undefined if used without it.

.. _detection:

Detection of support for this protocol
------------------------------------------

An application can query the terminal for support of this protocol by sending
the escape code querying for the :ref:`current progressive enhancement
<progressive_enhancement>` status
followed by request for the `primary device attributes
<https://vt100.net/docs/vt510-rm/DA1.html>`__. If an answer for the device
attributes is received without getting back an answer for the progressive
enhancement the terminal does not support this protocol.

.. note::
   Terminal implementations of this protocol are **strongly** encouraged to
   implement all progressive enhancements. It does not make sense to
   implement only a subset. Nonetheless, there are likely to be some terminal
   implementations that do not do so, applications can detect such
   implementations by first setting the desired progressive enhancements and
   then querying for the :ref:`current progressive enhancement <progressive_enhancement>`

Legacy key event encoding
--------------------------------

In the default mode, the terminal uses a legacy encoding for key events. In
this encoding, only key press and repeat events are sent and there is no
way to distinguish between them. Text is sent directly as UTF-8 bytes.

Any key events not described in this section are sent using the standard
``CSI u`` encoding. This includes keys that are not encodable in the legacy
encoding, thereby increasing the space of usable key combinations even without
progressive enhancement.

Legacy functional keys
~~~~~~~~~~~~~~~~~~~~~~~~

These keys are encoded using three schemes::

    CSI number ; modifier ~
    CSI 1 ; modifier {ABCDEFHPQS}
    SS3 {ABCDEFHPQRS}

In the above, if there are no modifiers, the modifier parameter is omitted.
The modifier value is encoded as described in the :ref:`modifiers` section,
above. When the second form is used, the number is always ``1`` and must be
omitted if the modifiers field is also absent. The third form becomes the
second form when modifiers are present (``SS3 is the bytes 0x1b 0x4f``).

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
    "UP",        "cuu1,kcuu1", "CSI A, SS3 A"
    "DOWN",      "cud1,kcud1", "CSI B, SS3 B"
    "RIGHT",     "cuf1,kcuf1", "CSI C, SS3 C"
    "LEFT",      "cub1,kcub1", "CSI D, SS3 D"
    "HOME",      "home,khome", "CSI H, SS3 H"
    "END",       "-,kend",     "CSI F, SS3 F"
    "F1",        "kf1",        "SS3 P"
    "F2",        "kf2",        "SS3 Q"
    "F3",        "kf3",        "SS3 R"
    "F4",        "kf4",        "SS3 S"
    "F5",        "kf5",        "CSI 15 ~"
    "F6",        "kf6",        "CSI 17 ~"
    "F7",        "kf7",        "CSI 18 ~"
    "F8",        "kf8",        "CSI 19 ~"
    "F9",        "kf9",        "CSI 20 ~"
    "F10",       "kf10",       "CSI 21 ~"
    "F11",       "kf11",       "CSI 23 ~"
    "F12",       "kf12",       "CSI 24 ~"
    "MENU",      "kf16",       "CSI 29 ~"

There are a few more functional keys that have special cased legacy encodings.
These are present because they are commonly used and for the sake of legacy
terminal applications that get confused when seeing CSI u escape codes:

.. csv-table:: C0 controls
    :header: "Key", "No mods", "Ctrl", "Alt", "Shift", "Ctrl + Shift", "Alt + Shift", "Ctrl + Alt"

    "Enter",     "0xd",  "0xd",  "0x1b 0xd",  "0xd",   "0xd",   "0x1b 0xd",   "0x1b 0xd"
    "Escape",    "0x1b", "0x1b", "0x1b 0x1b", "0x1b",  "0x1b",  "0x1b 0x1b",  "0x1b 0x1b"
    "Backspace", "0x7f", "0x8",  "0x1b 0x7f", "0x7f",  "0x8",   "0x1b 0x7f",  "0x1b 0x8"
    "Tab",       "0x9",  "0x9",  "0x1b 0x9",  "CSI Z", "CSI Z", "0x1b CSI Z", "0x1b 0x9"
    "Space",     "0x20", "0x0",  "0x1b 0x20", "0x20",  "0x0",   "0x1b 0x20",  "0x1b 0x0"

Note that :kbd:`Backspace` and :kbd:`ctrl+Backspace` are swapped in some
terminals, this can be detected using the ``kbs`` terminfo property that
must correspond to the :kbd:`Backspace` key.

All keypad keys are reported as their equivalent non-keypad keys. To
distinguish these, use the :ref:`disambiguate <disambiguate>` flag.

Terminals may choose what they want to do about functional keys that have no
legacy encoding. kitty chooses to encode these using ``CSI u`` encoding even in
legacy mode, so that they become usable even in programs that do not
understand the full kitty keyboard protocol. However, terminals may instead choose to
ignore such keys in legacy mode instead, or have an option to control this behavior.

.. _legacy_text:

Legacy text keys
~~~~~~~~~~~~~~~~~~~

For legacy compatibility, the keys :kbd:`a`-:kbd:`z` :kbd:`0`-:kbd:`9`
:kbd:`\`` :kbd:`-` :kbd:`=` :kbd:`[` :kbd:`]` :kbd:`\\` :kbd:`;` :kbd:`'`
:kbd:`,` :kbd:`.` :kbd:`/` with the modifiers :kbd:`shift`, :kbd:`alt`,
:kbd:`ctrl`, :kbd:`shift+alt`, :kbd:`ctrl+alt` are output using the following
algorithm:

#. If the :kbd:`alt` key is pressed output the byte for ``ESC (0x1b)``
#. If the :kbd:`ctrl` modifier is pressed map the key using the table
   in :ref:`ctrl_mapping`.
#. Otherwise, if the :kbd:`shift` modifier is pressed, output the shifted key,
   for example, ``A`` for ``a`` and ``$`` for ``4``.
#. Otherwise, output the key unmodified

Additionally, :kbd:`ctrl+space` is output as the NULL byte ``(0x0)``.

Any other combination of modifiers with these keys is output as the appropriate
``CSI u`` escape code.

.. csv-table:: Example encodings
   :header: "Key", "Plain", "shift", "alt", "ctrl", "shift+alt", "alt+ctrl", "ctrl+shift"

    "i", "i (105)", "I (73)", "ESC i", ") (41)", "ESC I", "ESC )", "CSI 105; 6 u"
    "3", "3 (51)", "# (35)", "ESC 3", "3 (51)", "ESC #", "ESC 3", "CSI 51; 6 u"
    ";", "; (59)", ": (58)", "ESC ;", "; (59)", "ESC :", "ESC ;", "CSI 59; 6 u"

.. note::
   Many of the legacy escape codes are ambiguous with multiple different key
   presses yielding the same escape code(s), for example, :kbd:`ctrl+i` is the
   same as :kbd:`tab`, :kbd:`ctrl+m` is the same as :kbd:`Enter`, :kbd:`ctrl+r`
   is the same :kbd:`ctrl+shift+r`, etc. To resolve these use the
   :ref:`disambiguate progressive enhancement <disambiguate>`.


.. _functional:

Functional key definitions
----------------------------

All numbers are in the Unicode Private Use Area (``57344 - 63743``) except
for a handful of keys that use numbers under 32 and 127 (C0 control codes) for legacy
compatibility reasons.

.. {{{
.. start functional key table (auto generated by gen-key-constants.py do not edit)

.. csv-table:: Functional key codes
   :header: "Name", "CSI", "Name", "CSI"

   "ESCAPE", "``27 u``", "ENTER", "``13 u``"
   "TAB", "``9 u``", "BACKSPACE", "``127 u``"
   "INSERT", "``2 ~``", "DELETE", "``3 ~``"
   "LEFT", "``1 D``", "RIGHT", "``1 C``"
   "UP", "``1 A``", "DOWN", "``1 B``"
   "PAGE_UP", "``5 ~``", "PAGE_DOWN", "``6 ~``"
   "HOME", "``1 H or 7 ~``", "END", "``1 F or 8 ~``"
   "CAPS_LOCK", "``57358 u``", "SCROLL_LOCK", "``57359 u``"
   "NUM_LOCK", "``57360 u``", "PRINT_SCREEN", "``57361 u``"
   "PAUSE", "``57362 u``", "MENU", "``57363 u``"
   "F1", "``1 P or 11 ~``", "F2", "``1 Q or 12 ~``"
   "F3", "``13 ~``", "F4", "``1 S or 14 ~``"
   "F5", "``15 ~``", "F6", "``17 ~``"
   "F7", "``18 ~``", "F8", "``19 ~``"
   "F9", "``20 ~``", "F10", "``21 ~``"
   "F11", "``23 ~``", "F12", "``24 ~``"
   "F13", "``57376 u``", "F14", "``57377 u``"
   "F15", "``57378 u``", "F16", "``57379 u``"
   "F17", "``57380 u``", "F18", "``57381 u``"
   "F19", "``57382 u``", "F20", "``57383 u``"
   "F21", "``57384 u``", "F22", "``57385 u``"
   "F23", "``57386 u``", "F24", "``57387 u``"
   "F25", "``57388 u``", "F26", "``57389 u``"
   "F27", "``57390 u``", "F28", "``57391 u``"
   "F29", "``57392 u``", "F30", "``57393 u``"
   "F31", "``57394 u``", "F32", "``57395 u``"
   "F33", "``57396 u``", "F34", "``57397 u``"
   "F35", "``57398 u``", "KP_0", "``57399 u``"
   "KP_1", "``57400 u``", "KP_2", "``57401 u``"
   "KP_3", "``57402 u``", "KP_4", "``57403 u``"
   "KP_5", "``57404 u``", "KP_6", "``57405 u``"
   "KP_7", "``57406 u``", "KP_8", "``57407 u``"
   "KP_9", "``57408 u``", "KP_DECIMAL", "``57409 u``"
   "KP_DIVIDE", "``57410 u``", "KP_MULTIPLY", "``57411 u``"
   "KP_SUBTRACT", "``57412 u``", "KP_ADD", "``57413 u``"
   "KP_ENTER", "``57414 u``", "KP_EQUAL", "``57415 u``"
   "KP_SEPARATOR", "``57416 u``", "KP_LEFT", "``57417 u``"
   "KP_RIGHT", "``57418 u``", "KP_UP", "``57419 u``"
   "KP_DOWN", "``57420 u``", "KP_PAGE_UP", "``57421 u``"
   "KP_PAGE_DOWN", "``57422 u``", "KP_HOME", "``57423 u``"
   "KP_END", "``57424 u``", "KP_INSERT", "``57425 u``"
   "KP_DELETE", "``57426 u``", "KP_BEGIN", "``1 E or 57427 ~``"
   "MEDIA_PLAY", "``57428 u``", "MEDIA_PAUSE", "``57429 u``"
   "MEDIA_PLAY_PAUSE", "``57430 u``", "MEDIA_REVERSE", "``57431 u``"
   "MEDIA_STOP", "``57432 u``", "MEDIA_FAST_FORWARD", "``57433 u``"
   "MEDIA_REWIND", "``57434 u``", "MEDIA_TRACK_NEXT", "``57435 u``"
   "MEDIA_TRACK_PREVIOUS", "``57436 u``", "MEDIA_RECORD", "``57437 u``"
   "LOWER_VOLUME", "``57438 u``", "RAISE_VOLUME", "``57439 u``"
   "MUTE_VOLUME", "``57440 u``", "LEFT_SHIFT", "``57441 u``"
   "LEFT_CONTROL", "``57442 u``", "LEFT_ALT", "``57443 u``"
   "LEFT_SUPER", "``57444 u``", "LEFT_HYPER", "``57445 u``"
   "LEFT_META", "``57446 u``", "RIGHT_SHIFT", "``57447 u``"
   "RIGHT_CONTROL", "``57448 u``", "RIGHT_ALT", "``57449 u``"
   "RIGHT_SUPER", "``57450 u``", "RIGHT_HYPER", "``57451 u``"
   "RIGHT_META", "``57452 u``", "ISO_LEVEL3_SHIFT", "``57453 u``"
   "ISO_LEVEL5_SHIFT", "``57454 u``"

.. end functional key table
.. }}}

.. note::
    The escape codes above of the form ``CSI 1 letter`` will omit the
    ``1`` if there are no modifiers, since ``1`` is the default value.

.. note::
   The original version of this specification allowed F3 to be encoded as both
   CSI R and CSI ~. However, CSI R conflicts with the Cursor Position Report,
   so it was removed.

.. _ctrl_mapping:

Legacy :kbd:`ctrl` mapping of ASCII keys
------------------------------------------

When the :kbd:`ctrl` key and another key are pressed on the keyboard, terminals
map the result *for some keys* to a *C0 control code* i.e. an value from ``0 -
31``. This mapping was historically dependent on the layout of hardware
terminal keyboards and is not specified anywhere, completely. The best known
reference is `Table 3-5 in the VT-100 docs <https://vt100.net/docs/vt100-ug/chapter3.html>`_.

The table below provides a mapping that is a commonly used superset of the table above.
Any ASCII keys not in the table must be left untouched by :kbd:`ctrl`.

.. {{{
.. start ctrl mapping (auto generated by gen-key-constants.py do not edit)
.. csv-table:: Emitted bytes when :kbd:`ctrl` is held down and a key is pressed
   :header: "Key", "Byte", "Key", "Byte", "Key", "Byte"

   "SPC ", "0", "/", "31", "0", "48"
   "1", "49", "2", "0", "3", "27"
   "4", "28", "5", "29", "6", "30"
   "7", "31", "8", "127", "9", "57"
   "?", "127", "@", "0", "[", "27"
   "\\", "28", "]", "29", "^", "30"
   "_", "31", "a", "1", "b", "2"
   "c", "3", "d", "4", "e", "5"
   "f", "6", "g", "7", "h", "8"
   "i", "9", "j", "10", "k", "11"
   "l", "12", "m", "13", "n", "14"
   "o", "15", "p", "16", "q", "17"
   "r", "18", "s", "19", "t", "20"
   "u", "21", "v", "22", "w", "23"
   "x", "24", "y", "25", "z", "26"
   "~", "30"

.. end ctrl mapping
.. }}}

.. _fixterms_bugs:

Bugs in fixterms
-------------------

The following is a list of errata in the `original fixterms proposal
<http://www.leonerd.org.uk/hacks/fixterms/>`_, corrected in this
specification.

* No way to disambiguate :kbd:`Esc` key presses, other than using 8-bit controls
  which are undesirable for other reasons

* Incorrectly claims special keys are sometimes encoded using ``CSI letter`` encodings when it
  is actually ``SS3 letter`` in all terminals newer than a VT-52, which is
  pretty much everything.

* :kbd:`ctrl+shift+tab` should be ``CSI 9 ; 6 u`` not ``CSI 1 ; 5 Z``
  (shift+tab is not a separate key from tab)

* No support for the :kbd:`super` modifier.

* Makes no mention of cursor key mode and how it changes encodings

* Incorrectly encoding shifted keys when shift modifier is used, for instance,
  for :kbd:`ctrl+shift+i` is encoded as :kbd:`ctrl+I`.

* No way to have non-conflicting escape codes for :kbd:`alt+letter`,
  :kbd:`ctrl+letter`, :kbd:`ctrl+alt+letter` key presses

* No way to specify both shifted and unshifted keys for robust shortcut
  matching (think matching :kbd:`ctrl+shift+equal` and :kbd:`ctrl+plus`)

* No way to specify alternate layout key. This is useful for keyboard layouts
  such as Cyrillic where you want the shortcut :kbd:`ctrl+c` to work when
  pressing the :kbd:`ctrl+С` on the keyboard.

* No way to report repeat and release key events, only key press events

* No way to report key events for presses that generate text, useful for
  gaming. Think of using the :kbd:`WASD` keys to control movement.

* Only a small subset of all possible functional keys are assigned numbers.

* Claims the ``CSI u`` escape code has no fixed meaning, but has been used for
  decades as ``SCORC`` for instance by xterm and ansi.sys and `DECSMBV
  <https://vt100.net/docs/vt510-rm/DECSMBV.html>`_ by the VT-510 hardware
  terminal. This doesn't really matter since these uses are for communication
  to the terminal not from the terminal.

* Handwaves that :kbd:`ctrl` *tends to* mask with ``0x1f``. In actual fact it
  does this only for some keys. The action of :kbd:`ctrl` is not specified and
  varies between terminals, historically because of different keyboard layouts.


Why xterm's modifyOtherKeys should not be used
---------------------------------------------------

* Does not support release events

* Does not fix the issue of :kbd:`Esc` key presses not being distinguishable from
  escape codes.

* Does not fix the issue of some keypresses generating identical bytes and thus
  being indistinguishable

* There is no robust way to query it or manage its state from a program running
  in the terminal.

* No support for shifted keys.

* No support for alternate keyboard layouts.

* No support for modifiers beyond the basic four.

* No support for lock keys like Num lock and Caps lock.

* Is completely unspecified. The most discussion of it available anywhere is
  `here <https://invisible-island.net/xterm/modified-keys.html>`__
  And it contains no specification of what numbers to assign to what function
  keys beyond running a Perl script on an X11 system!!
