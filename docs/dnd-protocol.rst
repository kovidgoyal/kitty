The Drag and Drop protocol
==============================================

.. versionadded:: 0.47.0

This protocol enables drag and drop functionality for terminal programs
that is as good as the drag and drop functionality available for GUI
programs.

There is one central escape code used for this protocol, which is of the form::

    OSC _dnd_code ; metadata ; base64 encoded payload ST

Here, ``OSC`` is the bytes ``ESC ] (0x1b 0x5b)`` and ST is ``ESC \\ (0x1b 0x5c)``.
The ``metadata`` is a colon separated list of ``key=value`` pairs.
The final part of the escape code is the :rfc:`base64 <4648>` encoded payload data,
whose meaning depends on the metadata.

The payload must be no more than 4096 bytes encoded bytes. 4096 is the limit to
be applied after encoding. When the payload is larger than 4096 base64 encoded
bytes, it is chunked up using the ``m`` key. An escape code that has a too long
payload is transmitted in chunks. All but the last chunk must have ``m=1`` in
their metadata. Each chunk must have a payload of no more than 4096 base64
encoded bytes without trailing padding, except the last chunk which may
optionally have trailing padding. Only the first chunk is guaranteed to have
metadata other than the ``m`` key. Subsequent chunks may optionally omit all
metadata except the ``m`` and ``i`` keys. While a chunked transfer is in
progress it is a protocol error to for the sending side to
send any protocol related escape codes other than chunked ones.

All integer values used in this escape code must be 32-bit signed or unsigned
integers encoded in decimal representation.

Accepting drops
-----------------

In order to inform the terminal emulator that the program accepts drops, it
must send the following escape code::

    OSC _dnd_code ; t=a ; payload ST

The payload here is a space separated list of MIME types the program accepts.
The list of MIME types is optional, it is needed if the program wants to accept
exotic or private use MIME types on platforms such as macOS, where the system
does not deliver drop events unless the MIME type is registered.

When the program is done accepting drops, or at exit, it should send the escape
code::

    OSC _dnd_code ; t=A ST

to inform the terminal that it no longer wants drops.

Whenever the user drags something over the window, the terminal will send an
escape code of the form::

    OSC _dnd_code ; t=m:x=x:y=y:X=X:Y=Y ; optional MIME list ST

Here, ``x, y`` identify the cell over which the drag is currently present.
The ``(0, 0)`` cell is at top left of the screen. ``X and Y`` are the pixel
offsets from the top-left. The optional list of MIMES is a space separated
list of MIME types that are available for dropping. To avoid overhead, the
terminal should only send this list for the first move event and subsequently
only if the list changes.

When the drag leaves the window, the terminal will send the same event but
with ``x, y = -1, -1`` to indicate that the drag has left the window. For such
events the list of MIME types must be empty. Note that the terminal must never
send negative cell co-ordinates for any other reason.

The client program must inform the terminal whether it will accept
the potential drop and which MIME types of the set of offered MIME types it
accepts. Until the client does so the terminal will indicate to the OS that
the drop is not accepted. To do so, the client sends an escape code of the
form::

    OSC _dnd_code ; t=m:o=O ; MIME list ST

Here the ``o`` key is the operation the client intends to perform if a drop
occurs which can be either ``1`` for copy or ``2`` for move or ``0`` for not
accepted. The MIME list is the ordered list of MIME types from the offered list
that the client wants. If no MIME type list is present, it is equivalent to no
change in the offered list of MIME types. The list should be ordered in order
of decreasing preference. Some platforms may assume show the user some
indication of the first MIME type in the list.

Metadata reference
---------------------------

The table below shows all the metadata keys as well as what values they can
take, and the default value they take when missing. All integers are 32-bit.

=======  ====================  =========  =================
Key      Value                 Default    Description
=======  ====================  =========  =================
``t``    Single character.     ``a``      The type of drag and drop event.
         ``(a, A,                         ``a`` - start accepting drops
         )``                              ``A`` - stop accepting drops
                                          ``m`` - a drop move event

``m``    Chunking indicator    ``0``      ``0`` or ``i``

``i``    Postive integer       ``0``      This id is for use by multiplexers.
                                          When it is set, all responses from
                                          the terminal in that session will
                                          have it set to the same value.

``o``    Positive integer      ``0``      What drop operation to perform. ``0``
                                          means rejected, ``1`` means copy and
                                          ``2`` means move.

**Keys for location**
-----------------------------------------------------------
``x``    Integer               ``0``      Cell x-coordinate origin is 0, 0 at top left of screen
``y``    Integer               ``0``      Cell y-coordinate origin is 0, 0 at top left of screen
``X``    Integer               ``0``      Pixel x-coordinate origin is 0, 0 at top left of screen
``Y``    Integer               ``0``      Pixel y-coordinate origin is 0, 0 at top left of screen
=======  ====================  =========  =================

