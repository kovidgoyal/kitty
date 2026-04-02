The Drag and Drop protocol
==============================================

.. versionadded:: 0.47.0

.. warning:: This protocol is still nuder development.

This protocol enables drag and drop functionality for terminal programs
that is as good as the drag and drop functionality available for GUI
programs.

There is one central escape code used for this protocol, which is of the form::

    OSC _dnd_code ; metadata ; base64 encoded payload ST

Here, ``OSC`` is the bytes ``ESC ] (0x1b 0x5b)`` and ST is ``ESC \\ (0x1b 0x5c)``.
The ``metadata`` is a colon separated list of ``key=value`` pairs.
The final part of the escape code is the payload data, whose meaning depends on the metadata.

The payload must be no more than 4096 bytes. When the payload is larger than 4096
bytes, it is chunked up using the ``m`` key. An escape code that has a too long
payload is transmitted in chunks. All but the last chunk must have ``m=1`` in
their metadata. Each chunk must have a payload of no more than 4096 bytes.
Only the first chunk is guaranteed to have metadata other than the ``m`` key.
Subsequent chunks may optionally omit all
metadata except the ``m`` and ``i`` keys. While a chunked transfer is in
progress it is a protocol error to for the sending side to
send any protocol related escape codes other than chunked ones.

All integer values used in this escape code must be 32-bit signed or unsigned
integers encoded in decimal representation.

When transferring binary data the payload is :rfc:`base64 <4648>` encoded. The
4096 bytes limit applies to *encoded bytes*, that is, it is applied after
encoding. base64 padding bytes are optional and may or may not be present at
the end of the last chunk.

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
send negative cell co-ordinates for any other reason. No more movement escape
codes ``t=m`` will be sent until this drop or another re-enters the window.

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
of decreasing preference. Some platforms may show the user some
indication of the first MIME type in the list.

When the user triggers a drop on the window, the terminal will send an escape
code of the form::

    OSC _dnd_code ; t=M: ... ; MIME list ST

This is the same as the movement escape codes above, except that ``t=M``
(upper case M instead of lower case m), indicating this is a drop.
Once this escape code is received, no more movement escape codes ``t=m``
will be sent until a new drop enters the window. The MIME list here is
mandatory, terminals must send the full list of MIME types available in
the drop. The client program can now request data for the MIME types
it is interested in.

Requesting data is done by sending an escape code of the form::

    OSC _dnd_code ; t=r ; MIME type ST

This will request data for the specified MIME type. The terminal must respond
with a series of escape codes of the form::

    OSC _dnd_code ; t=r ; base64 encoded data ST

End of data is indicated by an empty payload. If some error occurs while
getting the data, the terminal must send an escape code of the form::

    OSC _dnd_code ; t=R ; POSIX error name ST

Here POSIX error name is a POSIX symbolic error name such as ``ENOENT`` or
``EIO`` or the value ``EUNKNOWN`` for an unknown error. Note that if a client
sends a request for another MIME type before the data for the previous MIME type
is completed, the terminal *must* switch over to sending data for the new MIME
type.

Once the client program finishes reading all the dropped data it needs, it must
send an escape code of the form::

    OSC _dnd_code ; t=r ST

That is, it must send a request for data with no MIME type specified. The
terminal emulator must then inform the OS that the drop is completed.

Dropping from remote machines
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In order to support dropping of files from remote machines or to remote
machines, clients can first request the :rfc:`text/uri-list <2483>` MIME
type to get a list of dropped URIs. For every URI in the list, they can
send the terminal emulator a data request of the form::

    OSC _dnd_code ; t=s ; text/uri-list:idx ST

Here ``idx`` is the zero based index into the array of MIME types in
the ``text/uri-list`` entry. The terminal will then read the file and
transmit the data as for a normal MIME data request.

Terminals must reply with ``t=R ; ENOENT`` if the index is out of bounds.
If the client does not first request the ``text/uri-list`` MIME type or that
MIME type is not present in the drop, the terminal must reply with
``t=R ; EINVAL``. Terminals must support at least ``file://`` URIs.
If the client requests an entry that is not a supported URI type the
terminal must reply with ``t=R ; EUNKNOWN``.

Terminals must ONLY send data for regular files. Symbolic links must be
resolved and the corresponding file read. If the terminal does not have
permission to read the file it must reply with ``t=R ; EPERM``. Terminals
must respond with ``t=R ; EINVAL`` if the file is not a regular file after
resolving symlinks and ``t=R ; ENOENT`` if the file does not exist. If an
I/O error occurs the terminal must send ``t=R ; EIO``.


Reading remote directories
+++++++++++++++++++++++++++

If the file is actually a directory the terminal must respond with ``t=d:x=idx ; payload``.
Here payload is a null byte separated list of entries in the directory that are
either regular files, directories or symlinks. The payload must be base64
encoded and might be chunked if the directory has a lot of entries. The first
entry in the list must be a unique identifier for the directory, to prevent
symlink loops. Terminals may use whatever identifier is most suitable for their platforms, clients should
not re-request the contents of a directory whose identifier they have seen
before. On POSIX platforms the identifier would typically be device and inode
number.

``idx`` is an arbitrary 32 bit integer that acts as a handle to this
directory. The client can now read the files in this directory using requests of the form
``t=d:x=idx:y=num``, here ``num`` is the index into the list of
directory entries previously transmitted to the client. Here, ``1`` will
correspond to the first entry in the directory. Once the client is done
reading a directory it should transmit ``t=d:x=idx`` to the terminal. The
terminal can then free any resources associated with that directory. The
directory handle is now invalid and terminals must return ``EINVAL`` if the
client sends a request using and invalid directory handle. It is recommended
that clients traverse directories breadth first to minimise resource usage in
the terminal. Terminals may deny directory traversal requests if too many
resources are used, in order to prevent denial or service attacks. In such
cases the terminal must respond with ``ENOMEM``.

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
                                          ``M`` - a drop dropped event
                                          ``r`` - request dropped data
                                          ``R`` - report an error while retrieving data
                                          ``s`` - request data from the URI list entry
                                          ``d`` - send directory contents

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

