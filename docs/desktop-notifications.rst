.. _desktop_notifications:


Desktop notifications
=======================

|kitty| implements an extensible escape code (OSC 99) to show desktop
notifications. It is easy to use from shell scripts and fully extensible to show
title and body. Clicking on the notification can optionally focus the window it
came from, and/or send an escape code back to the application running in that
window.

The design of the escape code is partially based on the discussion in the
defunct `terminal-wg <https://gitlab.freedesktop.org/terminal-wg/specifications/-/issues/13>`__

The escape code has the form::

    <OSC> 99 ; metadata ; payload <terminator>

Here ``<OSC>`` is :code:`<ESC>]` and ``<terminator>`` is
:code:`<ESC><backslash>`. The ``metadata`` is a section of colon separated
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
    printf '\x1b]99;i=1:p=body;This is cool\x1b\\'

.. tip::

   |kitty| also comes with its own :doc:`statically compiled command line tool </kittens/notify>` to easily display
   notifications, with all their advanced features. For example:

   .. code-block:: sh

        kitten notify "Hello world" A good day to you

The most important key in the metadata is the ``p`` key, it controls how the
payload is interpreted. A value of ``title`` means the payload is setting the
title for the notification. A value of ``body`` means it is setting the body,
and so on, see the table below for full details.

The design of the escape code is fundamentally chunked, this is because
different terminal emulators have different limits on how large a single escape
code can be. Chunking is accomplished by the ``i`` and ``d`` keys. The ``i``
key is the *notification id* which is an :ref:`identifier`.
The ``d`` key stands for *done* and can only take the
values ``0`` and ``1``. A value of ``0`` means the notification is not yet done
and the terminal emulator should hold off displaying it. A non-zero value means
the notification is done, and should be displayed. You can specify the title or
body multiple times and the terminal emulator will concatenate them, thereby
allowing arbitrarily long text (terminal emulators are free to impose a sensible
limit to avoid Denial-of-Service attacks). The size of the payload must be no
longer than ``2048`` bytes, *before being encoded* or ``4096`` encoded bytes.

Both the ``title`` and ``body`` payloads must be either :ref:`safe_utf8` text
or UTF-8 text that is :ref:`base64` encoded, in which case there must be an
``e=1`` key in the metadata to indicate the payload is :ref:`base64`
encoded. No HTML or other markup in the plain text is allowed. It is strictly
plain text, to be interpreted as such.

Allowing users to filter notifications
-------------------------------------------------------

.. versionadded:: 0.36.0
   Specifying application name and notification type

Well behaved applications should identify themselves to the terminal
by means of two keys ``f`` which is the application name and ``t``
which is the notification type. These are free form keys, they can contain
any values, their purpose is to allow users to easily filter out
notifications they do not want. Both keys must have :ref:`base64`
encoded UTF-8 text as their values. The ``t`` key can be specified multiple
times, as notifications can have more than one type. See the `freedesktop.org
spec
<https://specifications.freedesktop.org/notification-spec/notification-spec-latest.html#categories>`__
for examples of notification types.

.. note::
   The application name should generally be set to the filename of the
   applications `desktop file
   <https://specifications.freedesktop.org/desktop-entry-spec/desktop-entry-spec-latest.html#file-naming>`__
   (without the ``.desktop`` part) or the bundle identifier for a macOS
   application. While not strictly necessary, this allows the terminal
   emulator to deduce an icon for the notification when one is not specified.

.. tip::

   |kitty| has sophisticated notification filtering and management
   capabilities via :opt:`filter_notification`.


Being informed when user activates the notification
-------------------------------------------------------

When the user clicks the notification, a couple of things can happen, the
terminal emulator can focus the window from which the notification came, and/or
it can send back an escape code to the application indicating the notification
was activated. This is controlled by the ``a`` key which takes a comma separated
set of values, ``report`` and ``focus``. The value ``focus`` means focus the
window from which the notification was issued and is the default. ``report``
means send an escape code back to the application. The format of the returned
escape code is::

    <OSC> 99 ; i=identifier ; <terminator>

The value of ``identifier`` comes from the ``i`` key in the escape code sent by
the application. If the application sends no identifier, then the terminal
*must* use ``i=0``. (Ideally ``i`` should have been left out from the response,
but for backwards compatibility ``i=0`` is used). Actions can be preceded by a
negative sign to turn them off, so for example if you do not want any action,
turn off the default ``focus`` action with::

    a=-focus

Complete specification of all the metadata keys is in the :ref:`table below <keys_in_notificatons_protocol>`.
If a terminal emulator encounters a key in the metadata it does not understand,
the key *must* be ignored, to allow for future extensibility of this escape
code. Similarly if values for known keys are unknown, the terminal emulator
*should* either ignore the entire escape code or perform a best guess effort to
display it based on what it does understand.


Being informed when a notification is closed
------------------------------------------------

.. versionadded:: 0.36.0
   Notifications of close events

If you wish to be informed when a notification is closed, you can specify
``c=1`` when sending the notification. For example::

    <OSC> 99 ; i=mynotification : c=1 ; hello world <terminator>

Then, the terminal will send the following
escape code to inform when the notification is closed::

    <OSC> 99 ; i=mynotification : p=close ; <terminator>

If no notification id was specified ``i=0`` will be used in the response

If ``a=report`` is specified and the notification is activated/clicked on
then both the activation report and close notification are sent. If the notification
is updated then the close event is not sent unless the updated notification
also requests a close notification.

Note that on some platforms, such as macOS, the OS does not inform applications
when notifications are closed, on such platforms, terminals reply with::

    <OSC> 99 ; i=mynotification : p=close ; untracked <terminator>

This means that the terminal has no way of knowing when the notification is
closed. Instead, applications can poll the terminal to determine which
notifications are still alive (not closed), with::

    <OSC> 99 ; i=myid : p=alive ; <terminator>

The terminal will reply with::

    <OSC> 99 ; i=myid : p=alive ; id1,id2,id3 <terminator>

Here, ``myid`` is present for multiplexer support. The response from the terminal
contains a comma separated list of ids that are still alive.


Updating or closing an existing notification
----------------------------------------------

.. versionadded:: 0.36.0
   The ability to update and close a previous notification

To update a previous notification simply send a new notification with the same
*notification id* (``i`` key) as the one you want to update. If the original
notification is still displayed it will be replaced, otherwise a new
notification is displayed. This can be used, for example, to show progress of
an operation. How smoothly the existing notification is replaced
depends on the underlying OS, for example, on Linux the replacement is usually flicker
free, on macOS it isn't, because of Apple's design choices.
Note that if no ``i`` key is specified, no updating must take place, even if
there is a previous notification without an identifier. The terminal must
treat these as being two unique *unidentified* notifications.

To close a previous notification, send::

    <OSC> i=<notification id> : p=close ; <terminator>

This will close a previous notification with the specified id. If no such
notification exists (perhaps because it was already closed or it was activated)
then the request is ignored. If no ``i`` key is specified, this must be a no-op.


Automatically expiring notifications
-------------------------------------

A notification can be marked as expiring (being closed) automatically after
a specified number of milliseconds using the ``w`` key. The default if
unspecified is ``-1`` which means to use whatever expiry policy the OS has for
notifications. A value of ``0`` means the notification should never expire.
Values greater than zero specify the number of milliseconds after which the
notification should be auto-closed. Note that the value of ``0``
is best effort, some platforms honor it and some do not. Positive values
are robust, since they can be implemented by the terminal emulator itself,
by manually closing the notification after the expiry time. The notification
could still be closed before the expiry time by user interaction or OS policy,
but it is guaranteed to be closed once the expiry time has passed.


Adding icons to notifications
--------------------------------

.. versionadded:: 0.36.0
   Custom icons in notifications

Applications can specify a custom icon to be displayed with a notification.
This can be the application's logo or a symbol such as error or warning
symbols. The simplest way to specify an icon is by *name*, using the ``n``
key. The value of this key is :ref:`base64` encoded UTF-8 text. Names
can be either application names, or symbol names. The terminal emulator
will try to resolve the name based on icons and applications available
on the computer it is running on. The following list of well defined names
must be supported by any terminal emulator implementing this spec.
The ``n`` key can be specified multiple times, the terminal will go through
the list in order and use the first icon that it finds available on the
system.

.. table:: Universally available icon names

   ======================== ==============================================
   Name                     Description
   ======================== ==============================================
   ``error``                An error symbol
   ``warn``, ``warning``    A warning symbol
   ``info``                 A symbol denoting an informational message
   ``question``             A symbol denoting asking the user a question
   ``help``                 A symbol denoting a help message
   ``file-manager``         A symbol denoting a generic file manager application
   ``system-monitor``       A symbol denoting a generic system monitoring/information application
   ``text-editor``          A symbol denoting a generic text editor application
   ======================== ==============================================

If an icon name is an application name it should be an application identifier,
such as the filename of the application's :file:`.desktop` file on Linux or its
bundle identifier on macOS. For example if the cross-platform application
FooBar has a desktop file named: :file:`foo-bar.desktop` and a bundle
identifier of ``net.foo-bar-website.foobar`` then it should use the icon names
``net.foo-bar-website.foobar`` *and* ``foo-bar`` so that terminals running on
both platforms can find the application icon.

If no icon is specified, but the ``f`` key (application name) is specified, the
terminal emulator should use the value of the ``f`` key to try to find a
suitable icon.

Adding icons by transmitting icon data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This can be done by using the ``p=icon`` key. Then, the payload is the icon
image in any of the ``PNG``, ``JPEG`` or ``GIF`` image formats. It is recommended
to use an image size of ``256x256`` for icons. Since icons are binary data,
they must be transmitted encoded, with ``e=1``.

When both an icon name and an image are specified, the terminal emulator must
first try to find a locally available icon matching the name and only if one
is not found, fallback to the provided image. This is so that users are
presented with icons from their current icon theme, where possible.

Transmitted icon data can be cached using the ``g`` key. The value of the ``g``
key must be a random globally unique UUID like :ref:`identifier`. Then, the
terminal emulator will cache the transmitted data using that key. The cache
should exist for as long as the terminal emulator remains running. Thus, in
future notifications, the application can simply send the ``g`` key to display
a previously cached icon image with needing to re-transmit the actual data with
``p=icon``. The ``g`` key refers only to the icon data, multiple different
notifications with different icon or application names can use the same ``g``
key to refer to the same icon. Terminal multiplexers must cache icon data
themselves and refresh it in the underlying terminal implementation when
detaching and then re-attaching. This means that applications once started
need to transmit icon data only once until they are quit.

.. note::
   To avoid DoS attacks terminal implementations can impose a reasonable max size
   on the icon cache and evict icons in order of last used. Thus theoretically,
   a previously cached icon may become unavailable, but given that icons are
   small images, practically this is not an issue in all but the most resource
   constrained environments, and the failure mode is simply that the icon is not
   displayed.

.. note::
   How the icon is displayed depends on the underlying OS notifications
   implementation. For example, on Linux, typically a single icon is displayed.
   On macOS, both the terminal emulator's icon and the specified custom icon
   are displayed.


Adding buttons to the notification
---------------------------------------

Buttons can be added to the notification using the *buttons* payload, with ``p=buttons``.
Buttons are a list of UTF-8 text separated by the Unicode Line Separator
character (U+2028) which is the UTF-8 bytes ``0xe2 0x80 0xa8``. They can be
sent either as :ref:`safe_utf8` or :ref:`base64`. When the user clicks on one
of the buttons, and reporting is enabled with ``a=report``, the terminal will
send an escape code of the form::

    <OSC> 99 ; i=identifier ; button_number <terminator>

Here, `button_number` is a number from 1 onwards, where 1 corresponds
to the first button, two to the second and so on. If the user activates the
notification as a whole, and not a specific button, the response, as described
above is::

    <OSC> 99 ; i=identifier ; <terminator>

If no identifier was specified when creating the notification, ``i=0`` is used.
The terminal *must not* send a response unless report is requested with
``a=report``.

.. note::

   The appearance of the buttons depends on the underlying OS implementation.
   On most Linux systems, the buttons appear as individual buttons on the
   notification. On macOS they appear as a drop down menu that is accessible
   when hovering the notification. Generally, using more than two or three
   buttons is not a good idea.

.. _notifications_query:

Playing a sound with notifications
-----------------------------------------

.. versionadded:: 0.36.0
   The ability to control the sound played with notifications

By default, notifications may or may not have a sound associated with them
depending on the policies of the OS notifications service. Sometimes it
might be useful to ensure a notification is not accompanied by a sound.
This can be done by using the ``s`` key which accepts :ref:`base64` encoded
UTF-8 text as its value. The set of known sounds names is in the table below,
any other names are implementation dependent, for instance, on Linux, terminal emulators will
probably support the `standard sound names
<https://specifications.freedesktop.org/sound-naming-spec/latest/#names>`__

.. table:: Standard sound names

   ======================== ==============================================
   Name                     Description
   ======================== ==============================================
   ``system``               The default system sound for a notification, which may be some kind of beep or just silence
   ``silent``               No sound must accompany the notification
   ``error``                A sound associated with error messages
   ``warn``, ``warning``    A sound associated with warning messages
   ``info``                 A sound associated with information messages
   ``question``             A sound associated with questions
   ======================== ==============================================

Support for sound names can be queried as described below.


Querying for support
-------------------------

.. versionadded:: 0.36.0
   The ability to query for support

An application can query the terminal emulator for support of this protocol, by
sending the following escape code::

    <OSC> 99 ; i=<some identifier> : p=? ; <terminator>

A conforming terminal must respond with an escape code of the form::

    <OSC> 99 ; i=<some identifier> : p=? ; key=value : key=value <terminator>

The identifier is present to support terminal multiplexers, so that they know
which window to redirect the query response too.

Here, the ``key=value`` parts specify details about what the terminal
implementation supports. Currently, the following keys are defined:

=======  ================================================================================
Key      Value
=======  ================================================================================
``a``    Comma separated list of actions from the ``a`` key that the terminal
         implements. If no actions are supported, the ``a`` key must be absent from the
         query response.

``c``    ``c=1`` if the terminal supports close events, otherwise the ``c``
         must be omitted.

``o``    Comma separated list of occasions from the ``o`` key that the
         terminal implements. If no occasions are supported, the value
         ``o=always`` must be sent in the query response.

``p``    Comma separated list of supported payload types (i.e. values of the
         ``p`` key that the terminal implements). These must contain at least
         ``title``.

``s``    Comma separated list of sound names from the table of standard sound names above.
         Terminals will report the list of standard sound names they support.
         Terminals *should* support at least ``system`` and ``silent``.

``u``    Comma separated list of urgency values that the terminal implements.
         If urgency is not supported, the ``u`` key must be absent from the
         query response.

``w``    ``w=1`` if the terminal supports auto expiring of notifications.
=======  ================================================================================

In the future, if this protocol expands, more keys might be added. Clients must
ignore keys they do not understand in the query response.

To check if a terminal emulator supports this notifications protocol the best way is to
send the above *query action* followed by a request for the `primary device
attributes <https://vt100.net/docs/vt510-rm/DA1.html>`_. If you get back an
answer for the device attributes without getting back an answer for the *query
action* the terminal emulator does not support this notifications protocol.

.. _keys_in_notificatons_protocol:

Specification of all keys used in the protocol
--------------------------------------------------

=======  ====================  ========== =================
Key      Value                 Default    Description
=======  ====================  ========== =================
``a``    Comma separated list  ``focus``  What action to perform when the
         of ``report``,                   notification is clicked
         ``focus``, with
         optional leading
         ``-``

``c``    ``0`` or ``1``        ``0``      When non-zero an escape code is sent to the application when the notification is closed.

``d``    ``0`` or ``1``        ``1``      Indicates if the notification is
                                          complete or not. A non-zero value
                                          means it is complete.

``e``    ``0`` or ``1``        ``0``      If set to ``1`` means the payload is :ref:`base64` encoded UTF-8,
                                          otherwise it is plain UTF-8 text with no C0 control codes in it

``f``    :ref:`base64`         ``unset``  The name of the application sending the notification. Can be used to filter out notifications.
         encoded UTF-8
         application name

``g``    :ref:`identifier`     ``unset``  Identifier for icon data. Make these globally unique,
                                          like an UUID.

``i``    :ref:`identifier`     ``unset``  Identifier for the notification. Make these globally unique,
                                          like an UUID, so that terminal multiplexers can
                                          direct responses to the correct window. Note that for backwards
                                          compatibility reasons i=0 is special and should not be used.

``n``    :ref:`base64`         ``unset``  Icon name. Can be specified multiple times.
         encoded UTF-8
         application name

``o``    One of ``always``,    ``always`` When to honor the notification request. ``unfocused`` means when the window
         ``unfocused`` or                 the notification is sent on does not have keyboard focus. ``invisible``
         ``invisible``                    means the window both is unfocused
                                          and not visible to the user, for example, because it is in an inactive tab or
                                          its OS window is not currently active.
                                          ``always`` is the default and always honors the request.

``p``    One of ``title``,     ``title``  Type of the payload. If a notification has no title, the body will be used as title.
         ``body``,                        A notification with not title and no body is ignored. Terminal
         ``close``,                       emulators should ignore payloads of unknown type to allow for future
         ``icon``,                        expansion of this protocol.
         ``?``, ``alive``,
         ``buttons``

``s``    :ref:`base64`         ``system`` The sound name to play with the notification. ``silent`` means no sound.
         encoded sound                    ``system`` means to play the default sound, if any, of the platform notification service.
         name                             Other names are implementation dependent.

``t``    :ref:`base64`         ``unset``  The type of the notification. Used to filter out notifications. Can be specified multiple times.
         encoded UTF-8
         notification type

``u``    ``0, 1 or 2``         ``unset``  The *urgency* of the notification. ``0`` is low, ``1`` is normal and ``2`` is critical.
                                          If not specified normal is used.


``w``    ``>=-1``              ``-1``     The number of milliseconds to auto-close the notification after.
=======  ====================  ========== =================


.. versionadded:: 0.35.0
   Support for the ``u`` key to specify urgency

.. versionadded:: 0.31.0
   Support for the ``o`` key to prevent notifications from focused windows


.. note::
   |kitty| also supports the `legacy OSC 9 protocol developed by iTerm2
   <https://iterm2.com/documentation-escape-codes.html>`__ for desktop
   notifications.


.. _base64:

Base64
---------------

The base64 encoding used in the this specification is the one defined in
:rfc:`4648`. When a base64 payload is chunked, either the chunking should be
done before encoding or after. When the chunking is done before encoding, no
more than 2048 bytes of data should be encoded per chunk and the encoded data
**must** include the base64 padding bytes, if any. When the chunking is done
after encoding, each encoded chunk must be no more than 4096 bytes in size.
There may or may not be padding bytes at the end of the last chunk, terminals
must handle either case.


.. _safe_utf8:

Escape code safe UTF-8
--------------------------

This must be valid UTF-8 as per the spec in :rfc:`3629`. In addition, in order
to make it safe for transmission embedded inside an escape code, it must
contain none of the C0 and C1 control characters, that is, the Unicode
characters: U+0000 (NUL) - U+1F (Unit separator), U+7F (DEL) and U+80 (PAD) - U+9F
(APC). Note that in particular, this means that no newlines, carriage returns,
tabs, etc. are allowed.


.. _identifier:

Identifier
----------------

Any string consisting solely of characters from the set ``[a-zA-Z0-9_-+.]``,
that is, the letters ``a-z``, ``A-Z``, the underscore, the hyphen, the plus
sign and the period. Applications should make these globally unique, like a
UUID for maximum robustness.


.. important::
   Terminals **must** sanitize ids received from client programs before sending
   them back in responses, to mitigate input injection based attacks. That is, they must
   either reject ids containing characters not from the above set, or remove
   bad characters when reading ids sent to them.
