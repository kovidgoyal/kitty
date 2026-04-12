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

In order to inform the terminal emulator that the client accepts drops, it
must send the following escape code::

    OSC _dnd_code ; t=a ; payload ST

The payload here is a space separated list of MIME types the program accepts.
The list of MIME types is optional, it is needed if the program wants to accept
exotic or private use MIME types on platforms such as macOS, where the system
does not deliver drop events unless the MIME type is registered.

When the client is done accepting drops, or at exit, it should send the escape
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

    OSC _dnd_code ; t=r:x=idx ST

Here ``idx`` is a 1-based index into the list of MIME types sent previously.
This will request data for the specified MIME type. The terminal must respond
with a series of escape codes of the form::

    OSC _dnd_code ; t=r:x=idx; base64 encoded data possibly chunked ST

End of data is indicated by an empty payload and ``m=0``. If some error occurs while
getting the data, the terminal must send an escape code of the form::

    OSC _dnd_code ; t=R:x=idx ; POSIX error name ST

Here ``POSIX error name`` is a POSIX symbolic error name such as ``ENOENT`` or
``EIO`` or the value ``EUNKNOWN`` for an unknown error. Unless otherwise noted,
any error response means the drop is terminated.

Once the client program finishes reading all the dropped data it needs, it must
send an escape code of the form::

    OSC _dnd_code ; t=r ST

That is, it must send a request for data with no MIME type specified. The
terminal emulator must then inform the OS that the drop is completed.

Dropping from remote machines
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In order to support dropping of files from remote machines, the client
must inform the terminal of its :ref:`machine id <machine_id>` using the escape code::

    OSC _dnd_code ; t=a:x=1 ; machine id ST

Then, the client must first request the :rfc:`text/uri-list <2483>` MIME
type to get a list of dropped URIs. When responding to this request,
the terminal will send the usual ``t=r`` responses, but, in addition,
if the client has sent its machine id and the terminal determines that
the client is on a different machine based on the id, it will add the ``X=1``
key to its response. The client should use this key to determine if it wants to
request data for entries in the URI list. For every URI in the list, the client can
send the terminal emulator a data request of the form::

    OSC _dnd_code ; t=r:x=idx:y=subidx ST

Here ``idx`` is the one based index of the ``text/uri-list`` MIME type. And
``subidx`` is the one based index into the array of MIME types in
the ``text/uri-list`` entry. The terminal will then read the file and
transmit the data as for a normal MIME data request, except it will have
``y=subidx`` as well in its response, for example::

    OSC _dnd_code ; t=r:x=idx:y=subidx ; base64 encoded data possibly chunked ST

Similarly, error responses are as above, except for the addition of
``y=subidx``, for example::

    OSC _dnd_code ; t=R:x=idx:y=subidx ; POSIX error name ST

Terminals must reply with ``ENOENT`` if the index is out of bounds.
If the client does not first request the ``text/uri-list`` MIME type or that
MIME type is not present in the drop, the terminal must reply with
``EINVAL``. Terminals must support at least ``file://`` URIs.
If the client requests an entry that is not a supported URI type the
terminal must reply with ``EUNKNOWN``.

Terminals must ONLY send data for regular files or directories. Symbolic links must be
resolved and the corresponding file or directory read. If the terminal does not have
permission to read the file it must reply with ``EPERM``. Terminals
must respond with ``EINVAL`` if the file is not a regular file after
resolving symlinks and ``ENOENT`` if the file does not exist. If an
I/O error occurs the terminal must send ``EIO``.

For security reasons, terminals must reply with ``EPERM`` if the drag
originated in the same window as the drop, this prevents malicious programs
from reading files on the computer by starting their own drag. This is a
defense in depth feature since drags can only be started by the terminal, but
it helps in case of accidental drag starts and drops into the same window.

Clients may send multiple requests without waiting for any request to complete.
Terminals may queue requests and respond in any order they choose, including
interleaving responses to different requests. However, for simplicity, this
specification recommends terminals queue requests and respond in first-in,
first-out order. Every response can be matched to a corresponding request
using the ``x``, ``y`` and ``Y`` keys. To prevent Denial of service attacks,
if too many requests are received, terminals must deny the request
with ``EMFILE`` and end the drop.


Reading remote directories
+++++++++++++++++++++++++++

If the file pointed to by a ``file://`` URL is actually a directory the terminal must instead respond with::

    OSC _dnd_code ; t=r:x=idx:y=subidx:X=handle ; base64 encoded list of dir entries ST

The presence of ``X=handle`` indicates this is a directory response not a regular
file or symlink. For regular files, ``X=0``. For symlinks, ``X=1``.
For directories ``X`` is an arbitrary integer (``handle``) other than ``0`` or ``1``.
Here, the payload is a null byte separated list of entries in the directory that are
either regular files, directories or symlinks. The payload must be base64
encoded and might be chunked if the directory has a lot of entries.

The client can now read the files in this directory using requests of the form::

    OSC _dnd_code ; t=r:Y=handle:x=num ST

Here ``num`` is the 1-based index into the list of directory entries previously transmitted
to the client. The terminal will respond with an escape code of the forms ::

    OSC _dnd_code ; t=r:Y=handle:x=num ; base64 encoded data of regular file ST
    OSC _dnd_code ; t=r:Y=handle:x=num:X=1 ; base64 encoded symlink target ST
    OSC _dnd_code ; t=r:Y=handle:x=num:X=child-handle ; base64 encoded list of entries in sub-dir ST

In case of any errors, the terminal will respond with::

    OSC _dnd_code ; t=R:Y=handle:x=num ; POSIX error name ST

In the above, the ``Y=handle`` and ``x=num`` keys allow the client to know
which directory entry the response concerns. The ``handle`` points to the
parent directory and ``num`` to the entry within the parent dir.

Once the client is done reading a directory it should transmit ``t=r:Y=handle`` to the terminal. The
terminal can then free any resources associated with that directory. The
directory handle is now invalid and terminals must return ``EINVAL`` if the
client sends a request using an invalid directory handle. It is recommended
that clients traverse directories breadth first to minimise resource usage in
the terminal. Terminals may deny directory traversal requests if too many
resources are used, in order to prevent Denial of service attacks. In such
cases the terminal must respond with ``ENOMEM``.


Starting drags
-----------------

Terminal programs can inform the terminal emulator that they
are willing to act as a source of drag data by sending the
sending the escape code::

    OSC _dnd_code ; t=o:x=1 ; optional machine id ST

On exit, or if the program no longer is willing to start drag gestures, it must
send ``t=o:x=2`` to the terminal to indicate it no longer wants to offer drag data.
The ``machine id`` is optional and is used to enable dragging from remote
machines. See :ref:`below <machine_id>` for its semantics.

When the user performs the platform specific gesture to start a drag operation,
the terminal will send the same escape code back to the terminal program
informing it that it can potentially start a drag. The gesture is typically holding the
left mouse button down and dragging a short distance, but this protocol does
not mandate any particular gesture to start drag operations. The terminal, when
sending the event will also set the ``x, y, X, Y`` keys to indicate the cell
and pixel locations in the window of the start drag event.

If the terminal program determines that it wants to start a drag at that
location, it must send the terminal the ``t=o:o=flags`` escape code again, but
with a payload consisting of the space separated MIME types it offers. The
``flags`` indicate what types of operations the client supports, ``1`` for
copy, ``2`` for move and ``3`` for either. The transmission should be chunked
if the list of MIME types is too long. Note that at this time the drag
operation has not actually started, this gives the terminal program the
opportunity to pre-send some data or set one or more images to act as
thumbnails for the drag operation. If the list of MIME types is too long the
terminal may cancel the operation by responding with ``t=E ; EFBIG`` or ``t=E ;
ENOMEM``.

If at the time the terminal receives this request the drag gesture has already
been terminated or the terminal otherwise determines that it is not appropriate
to start the drag, it must reply with ``t=E ; EPERM`` to indicate the drag
offer was not accepted.

For some well known types like ``text/plain`` or ``text/uri-list`` the
terminal program should pre-send the data for them unless it is very large.
This is because some platforms, such as macOS, need pre sent data to be able
to interoperate with native programs. The terminal emulator should reply with
``t=E ; EFBIG`` if too much data is sent and cancel the drag. Terminals must
accept at least 64MB of pre sent data.

Pre sent data is sent with escape codes of the form::

    OSC _dnd_code ; t=p:x=idx ; base64 encoded data ST

Here ``idx`` is the zero based index into the list of previously sent MIME
types indicating this data is for that MIME type. Transmission should be chunked
using the ``m`` key. End of data is indicated by sending the escape code with no
payload and ``m=0``. Terminal programs should pre-read this data and only send
the ``t=o`` key indicating the offer if the data is available.

To associate one or more images with the drag operation, the terminal program
must transmit the data for the image with the ``idx`` value above being a
negative number starting with ``-1`` for the first image and so on. Clients
**must** transmit all images consecutively in order, starting with the first,
then the second and so on. When transmitting images, the image data format is
specified using the ``y`` key. A value of ``y=24`` mean 24bit RGB data and
``y=32`` means 32bit RGBA data. Colors in the RGB/A data must be in the sRGB
color space. Using ``y=100`` means the data is a PNG image. Additionally, the
``X`` and ``Y`` keys must be used to specify the width and height of the image
data in pixels. If the size of the transmitted data does not match the image
dimensions the terminal must replay with ``t=E ; EINVAL``. Terminals are free
to impose a limit on the amount of image data, to avoid Denial-of-service
attacks. If the image data is too much or the image is too large they must
reply with ``t=E ; EFBIG`` and abort the drag. By default, the drag will be
started using the first image, if any. During the drag, the terminal program
can change the image by sending::

    OSC _dnd_code ; t=P:x=idx ST

Where ``idx`` is now a zero based index with zero being the first image and so on.
Sending an ``idx`` out of bounds means the drag image should be removed.

Once the terminal program has sent all data and images for the drag
operation, it indicates the drag should be started by sending ``t=P:x=-1``. At
this time if the user has already cancelled the drag or the terminal determines
the drag operation is not allowed, it must respond with ``t=E ; EPERM``. If any
other error occurs starting the drag operation, it must respond with the appropriate
POSIX error code. If it determines that the image data after conversion to
display format is too large, it must respond with ``t=E ; EFBIG``. If the drag
operation is successfully started, it must respond with ``t=E ; OK``.

As the drag progresses, status changes are reported using the ``t=e`` escape
code. The variants are listed in the table below:

.. list-table:: Drag offer events

   * - Code
     - Description
   * - ``t=e : x=1 : y=idx``
     - The drag has been accepted by a client. ``idx`` is a zero based index into the list of MIME types
       pointing to the MIME type the client is likely to want
   * - ``t=e : x=2 : o=O``
     - The action the client is likely to perform has changed to the value indicated by the ``o`` key
   * - ``t=e : x=3``
     - The drag offer has been dropped onto a client, there are likely to be requests for data in the near future
   * - ``t=e : x=4 : y=0 or 1``
     - The drag is finished. If ``y=1`` then the drag was canceled by the user.
   * - ``t=e : x=5 : y=idx``
     - Request data for the MIME type at the zero based index ``idx`` in the list of MIME types

The client program should respond to data requests with escape codes of the
form::

    OSC _dnd_code ; t=e:y=idx:m=0 or 1 ; base64 encoded data ST

This, is the data for the MIME type identified by ``idx`` which is a zero based
index into the list of MIME types. The data should be chunked using the
``m`` key. End of data is denoted by ``m=0`` and an empty payload. If an error
occurs the client should send::

    OSC _dnd_code ; t=E:y=idx ; POSIX error name ST

Where ``POSIX error name`` is a POSIX symbolic error name such as ``ENOENT``
if the MIME type is not found or ``EIO`` if an IO error occurred and so on.

If the client wants to cancel the full drag at any time, it should send:

    OSC _dnd_code ; t=E:y=-1 ST

If ``t=e`` or ``t=E`` escape codes are sent to the terminal before the drag is
started and the terminal has responded with ``t=E ; OK``, the terminal must respond
with ``t=E ; EINVAL`` and abort the drag.

Dragging to remote machines
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

To support dragging files to remote machines, when requesting the data for the
``text/uri-list`` MIME type, terminal emulators can add the ``Y=1`` key.
Terminals can examine the :ref:`machine_id` sent with the enable drag offers
``t=o`` escape code to decide whether to use ``Y=1`` or not. On
receipt of this key, the client should first send the ``text/uri-list`` as
normal and then a series of responses for every ``file://`` URL type in the
list of the form::

    OSC _dnd_code ; t=k:x=idx:m=0 or 1 ; base64 encoded file data ST
    OSC _dnd_code ; t=k:x=idx:X=1:m=0 or 1 ; base64 encoded symlink target ST
    OSC _dnd_code ; t=k:x=idx:X=handle:m=0 or 1 ; base64 encoded null separated list of directory entries ST

These represent possibly chunked data for files, symlinks and directories, as
denoted by the ``X`` key. As above, end of data for an individual entry is
indicated by an escape code with ``m=0`` and no payload. ``idx`` is the one
based index into the list of entries in the ``text/uri-list`` MIME type.
``file://`` URLs that point to symlinks must be resolved to files or
directories and sent. So actual symlinks will appear only when recursing
through directories as described below. Only regular files should be sent.

Terminals should write the transmitted data into a temporary directory
and replace the entries in the ``text/uri-list`` data with the transmitted
files/directories.

Every directory must be transmitted with ``X=handle``. The payload
is a null separated list of regular files, directories and symlinks in the
directory. ``handle`` is an integer other than ``0`` or ``1``
that serves as an identifier for the directory. Directories must be traversed
in breadth first order. The children of a directory are reported by
adding ``Y=parent-handle:y=num`` to the escape codes above. Here
``parent-handle`` is the handle of the directory being traversed and ``num``
is the one based index into the list of entries in the directory. Thus, the
set of keys ``x, y, Y`` uniquely determine an entry.

Once all data is transmitted, the client informs the terminal emulator of
completion with::

    OSC _dnd_code ; t=k ; ST

At this point, the terminal should send the modified data for ``text/uri-list``
to the drop destination.

If any error occurs in the client while reading the data, it can inform
the terminal using::

    OSC _dnd_code ; t=E ; POSIX error name ST

The terminal must then abort the drag.

Terminals are free to impose resource limits on how much data they accept,
if a limit is breached or some errors occurs, they can abort the drag and
inform the client of it with::

    OSC _dnd_code ; t=E ; POSIX error name ST

The error code for too many resources is ``EMFILE`` for IO errors is ``EIO``
and so on.

Multiplexers
-----------------

To support multiplexers, the ``i`` key exists. When the terminal receives and
``t=a`` or ``t=o`` escape code that has the ``i`` key set, all escape codes it
sends to the terminal program must include the ``i`` key with the same value.
This allows terminal multiplexers to direct the response codes to the correct
client.

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
                                          ``R`` - report an error
                                          ``o`` - start offering drags or start a drag
                                          ``p`` - present data for drag offers
                                          ``P`` - Change drag image or start drag
                                          ``e`` - a drag offer event occurred
                                          ``E`` - a drag offer data error occurred
                                          ``k`` - data for uri-list items in drag offer

``m``    Chunking indicator    ``0``      ``0`` or ``1``

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


.. _machine_id:

Machine id
-----------------

The machine id is used to detect when the source and destination machines for a
drag and drop are different. It is of the form: ``version:ASCII printable
chars``. The leading ``version`` field allows for changing the format or
semantics of this field in the future. The actual id is the machine id which
is:

.. tab:: macOS

   The value returned by the ``IOPlatformUUID`` system function.

.. tab:: Windows

   The contents of the :file:`HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid`
   registry key.

.. tab:: Other

   The contents of the :file:`/etc/machine-id` file with trailing whitespace removed

This machine id is then hashed using a :rfc:`HMAC <2104>` with :rfc:`SHA-256
<6234>` as the digest algorithm and the key being the ASCII bytes:
``tty-dnd-protocol-machine-id``. The hashing is done so as to not easily leak
the actual machine id and to ensure that the value is of fixed size and
consisting only of ASCII printable characters. This gives a final value of::

    1:hashed machine id hexadecimal encoded

In the future, the ``version`` field may increase if the hashing algorithm is
changed. If the terminal sees a version it does not understand, it must assume
that the machine id does not match, aka the source and destination machines are
different. This assumption means that remote drag and drop will still work, just with
reduced performance in case of version mismatch.
