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

``m``    Chunking indicator    ``0``      ``0`` or ``i``

``i``    Postive integer       ``0``      This id is for use by multiplexers.
                                          When it is set, all responses from
                                          the terminal in that session will
                                          have it set to the same value.
**Keys for location**
-----------------------------------------------------------
``x``    Positive integer      ``0``      Cell x-coordinate origin is 0, 0 at top left of screen
``y``    Positive integer      ``0``      Cell y-coordinate origin is 0, 0 at top left of screen
``X``    Integer               ``0``      Pixel x-coordinate origin is 0, 0 at top left of screen
``Y``    Integer               ``0``      Pixel y-coordinate origin is 0, 0 at top left of screen
=======  ====================  =========  =================

