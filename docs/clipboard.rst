Copying all data types to the clipboard
==============================================

There already exists an escape code to allow terminal programs to
read/write plain text data from the system clipboard, *OSC 52*.
kitty introduces a more advanced protocol that supports:

* Copy arbitrary data including images, rich text documents, etc.
* Allow terminals to ask the user for permission to access the clipboard and
  report permission denied

The escape code is *OSC 5522*, an extension of *OSC 52*. The basic format
of the escape code is::

    <OSC>5522;metadata;payload<ST>

Here, *metadata* is a colon separated list of key-value pairs and payload is
base64 encoded data. :code:`OSC` is :code:`<ESC>[`.
:code:`ST` is the string terminator, :code:`<ESC>\\`.

Reading data from the system clipboard
----------------------------------------

To read data from the system clipboard, the escape code is::

    <OSC>5522;type=read;<base 64 encoded space separated list of mime types to read><ST>

For example, to read plain text and PNG data, the payload would be::

    text/plain image/png

encoded as base64. To read from the primary selection instead of the
clipboard, add the key ``loc=primary`` to the metadata section.

To get the list of MIME types available on the clipboard the payload must be
just a period (``.``), encoded as base64.

The terminal emulator will reply with a sequence of escape codes of the form::

    <OSC>5522;type=read:status=OK<ST>
    <OSC>5522;type=read:status=DATA:mime=<base 64 encoded mime type>;<base64 encoded data><ST>
    <OSC>5522;type=read:status=DATA:mime=<base 64 encoded mime type>;<base64 encoded data><ST>
    .
    .
    .
    <OSC>5522;type=read:status=DONE<ST>

Here, the ``status=DATA`` packets deliver the data (as base64 encoded bytes)
associated with each MIME type. The terminal emulator should chunk up the data
for an individual type. A recommended size for each chunk is 4096 bytes. All
the chunks for a given type must be transmitted sequentially and only once they
are done the chunks for the next type, if any, should be sent. The end of data
is indicated by a ``status=DONE`` packet.

If an error occurs, instead of the opening ``status=OK`` packet the terminal
must send a ``status=ERRORCODE`` packet. The error code must be one of:

``status=ENOSYS``
    Sent if the requested clipboard type is not available. For example, primary
    selection is not available on all systems and ``loc=primary`` was used.

``status=EPERM``
    Sent if permission to read from the clipboard was denied by the system or
    the user.

``status=EBUSY``
    Sent if there is some temporary problem, such as multiple clients in a
    multiplexer trying to access the clipboard simultaneously.

Terminals should ask the user for permission before allowing a read request.
However, if a read request only wishes to list the available data types on the
clipboard, it should be allowed without a permission prompt. This is so that
the user is not presented with a double permission prompt for reading the
available MIME types and then reading the actual data.


Writing data to the system clipboard
----------------------------------------

To write data to the system clipboard, the terminal programs sends the
following sequence of packets::

    <OSC>5522;type=write<ST>
    <OSC>5522;type=wdata:mime=<base64 encoded mime type>;<base 64 encoded chunk of data for this type><ST>
    <OSC>5522;type=wdata:mime=<base64 encoded mime type>;<base 64 encoded chunk of data for this type><ST>
    .
    .
    .
    <OSC>5522;type=wdata<ST>

The final packet with no mime and no data indicates end of transmission. The
data for every MIME type should be split into chunks of no more than 4096
bytes. All the chunks for a given MIME type must be sent sequentially, before
sending chunks for the next MIME type. After the transmission is complete, the
terminal replies with a single packet indicating success::

    <OSC>5522;type=write:status=DONE<ST>

If an error occurs the terminal can, at any time, send an error packet of the
form::

    <OSC>5522;type=write:status=ERRORCODE<ST>

Here ``ERRORCODE`` must be one of:

``status=EIO``
    An I/O error occurred while processing the data
``status=EINVAL``
    One of the packets was invalid, usually because of invalid base64 encoding.
``status=ENOSYS``
    The client asked to write to the primary selection with (``loc=primary``) and that is not
    available on the system
``status=EPERM``
    Sent if permission to write to the clipboard was denied by the system or
    the user.
``status=EBUSY``
    Sent if there is some temporary problem, such as multiple clients in a
    multiplexer trying to access the clipboard simultaneously.

Once an error occurs, the terminal must ignore all further OSC 5522 write related packets until it
sees the start of a new write with a ``type=write`` packet.

The client can send to the primary selection instead of the clipboard by adding
``loc=primary`` to the initial ``type=write`` packet.

Finally, clients have the ability to *alias* MIME types when sending data to
the clipboard. To do that, the client must send a ``type=walias`` packet of the
form::

    <OSC>5522;type=walias;mime=<base64 encoded target MIME type>;<base64 encoded, space separated list of aliases><ST>

The effect of an alias is that the system clipboard will make available all the
aliased MIME types, with the same data as was transmitted for the target MIME
type. This saves bandwidth, allowing the client to only transmit one copy of
the data, but create multiple references to it in the system clipboard. Alias
packets can be sent anytime after the initial write packet and before the end
of data packet.


Support for terminal multiplexers
------------------------------------

Since this protocol involves two way communication between the terminal
emulator and the client program, multiplexers need a way to know which window
to send responses from the terminal to. In order to make this possible, the
metadata portion of this escape code includes an optional ``id`` field. If
present the terminal emulator must send it back unchanged with every response.
Valid ids must include only characters from the set: ``[a-zA-Z0-9-_+.]``. Any
other characters must be stripped out from the id by the terminal emulator
before retransmitting it.

Note that when using a terminal multiplexer it is possible for two different
programs to overwrite each others clipboard requests. This is fundamentally
unavoidable since the system clipboard is a single global shared resource.
However, there is an additional complication where responses form this protocol
could get lost if, for instance, multiple write requests are received
simultaneously. It is up to well designed multiplexers to ensure that only a
single request is in flight at a time. The multiplexer can abort requests by
sending back the ``EBUSY`` error code indicating some other window is trying
to access the clipboard.
