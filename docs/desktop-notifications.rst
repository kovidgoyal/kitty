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
    printf '\x1b]99;i=1:d=1:p=body;This is cool\x1b\\'

The most important key in the metadata is the ``p`` key, it controls how the
payload is interpreted. A value of ``title`` means the payload is setting the
title for the notification. A value of ``body`` means it is setting the body,
and so on, see the table below for full details.

The design of the escape code is fundamentally chunked, this is because
different terminal emulators have different limits on how large a single escape
code can be. Chunking is accomplished by the ``i`` and ``d`` keys. The ``i``
key is the *notification id* which can be any string containing the characters
``[a-zA-Z0-9_-+.]``. The ``d`` key stands for *done* and can only take the
values ``0`` and ``1``. A value of ``0`` means the notification is not yet done
and the terminal emulator should hold off displaying it. A value of ``1`` means
the notification is done, and should be displayed. You can specify the title or
body multiple times and the terminal emulator will concatenate them, thereby
allowing arbitrarily long text (terminal emulators are free to impose a sensible
limit to avoid Denial-of-Service attacks). The size of the payload must be no
longer than ``2048`` bytes, *before being encoded*.

Both the ``title`` and ``body`` payloads must be either UTF-8 encoded plain
text with no embedded escape codes, or UTF-8 text that is :rfc:`base64 <4648>`
encoded, in which case there must be an ``e=1`` key in the metadata to indicate
the payload is :rfc:`base64 <4648>` encoded.

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
   the notification, however, given that some platforms, such as legacy versions
   of macOS, don't allow displaying custom images on a notification, it was
   decided to leave it out of the spec for the time being.

   Similarly, features such as scheduled notifications could be added in future
   revisions.

Being informed when a notification is closed
------------------------------------------------

.. versionadded:: 0.36.0
   Notifications of close events were added in kitty version 0.36.0

If you wish to be informed when a notification is closed, you can specify
``c=1`` when sending the notification. For example::

    <OSC> 99 ; i=mynotification : c=1 ; hello world <terminator>

Then, the terminal will send the following
escape code to inform when the notification is closed::

    <OSC> 99 ; i=mynotification : p=close ; <terminator>

If no notification id was specified ``i=0`` will be used.
If ``a=report`` is specified and the notification is activated/clicked on
then both the activation report and close notification are sent.

.. note::
   Close events are best effort, some platforms such as macOS do not have
   events when notifications are closed. Applications can use the
   :ref:`notifications_query` to check if close events are supported
   by the current terminal emulator.


Closing an existing notification
----------------------------------

.. versionadded:: 0.36.0
   The ability to close a previous notification was added in kitty 0.36.0

To close a previous notification, send::

    <OSC> i=<notification id> : p=close ; <terminator>

This will close a previous notification with the specified id. If no such
notification exists (perhaps because it was already closed or it was activated)
then the request is ignored.

.. _notifications_query:

Querying for support
-------------------------

.. versionadded:: 0.36.0
   The ability to query for support was added in kitty 0.36.0

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

``o``    Comma separated list of occassions from the ``o`` key that the
         terminal implements. If no occassions are supported, the value
         ``o=always`` must be sent in the query response.

``u``    Comma separated list of urgency values that the terminal implements.
         If urgency is not supported, the ``u`` key must be absent from the
         query response.

``p``    Comma spearated list of supported payload types (i.e. values of the
         ``p`` key that the terminal implements). These must contain at least
         ``title`` and ``body``.

``c``    ``c=1`` if the terminal supports close events, otherwise the ``c``
         must be omitted.
=======  ================================================================================

In the future, if this protocol expands, more keys might be added. Clients must
ignore keys they dont understand in the query response.

To check if a terminal emulator supports this notifications protocol the best way is to
send the above *query action* followed by a request for the `primary device
attributes <https://vt100.net/docs/vt510-rm/DA1.html>`_. If you get back an
answer for the device attributes without getting back an answer for the *query
action* the terminal emulator does not support this notifications protocol.

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

``d``    ``0`` or ``1``        ``1``      Indicates if the notification is
                                          complete or not.

``e``    ``0`` or ``1``        ``0``      If set to ``1`` means the payload is :rfc:`base64 <4648>` encoded UTF-8,
                                          otherwise it is plain UTF-8 text with no C0 control codes in it

``i``    ``[a-zA-Z0-9-_+.]``   ``0``      Identifier for the notification. Make these globally unqiue,
                                          like an UUID, so that termial multiplxers can
                                          direct responses to the correct window.

``p``    One of ``title``,     ``title``  Whether the payload is the notification title or body or query. If a
         ``body``,                        notification has no title, the body will be used as title. Terminal
         ``close``,                       emulators should ignore payloads of unknown type to allow for future
         ``?``                            expansion of this protocol.


``o``    One of ``always``,    ``always`` When to honor the notification request. ``unfocused`` means when the window
         ``unfocused`` or                 the notification is sent on does not have keyboard focus. ``invisible``
         ``invisible``                    means the window both is unfocused
                                          and not visible to the user, for example, because it is in an inactive tab or
                                          its OS window is not currently active.
                                          ``always`` is the default and always honors the request.

``u``    ``0, 1 or 2``         ``unset``  The *urgency* of the notification. ``0`` is low, ``1`` is normal and ``2`` is critical.
                                          If not specified normal is used.

``c``    ``0`` or ``1``        ``0``      When non-zero an escape code is sent to the application when the notification is closed.
=======  ====================  ========== =================


.. versionadded:: 0.35.0
   Support for the ``u`` key to specify urgency

.. versionadded:: 0.31.0
   Support for the ``o`` key to prevent notifications from focused windows


.. note::
   |kitty| also supports the `legacy OSC 9 protocol developed by iTerm2
   <https://iterm2.com/documentation-escape-codes.html>`__ for desktop
   notifications.
