File transfer over the TTY
===============================

There are sometimes situations where the TTY is the only convenient pipe
between two connected systems, for example, nested SSH sessions, a serial
line, etc. In such scenarios, it is useful to be able to transfer files
over the TTY.

This protocol provides the ability to transfer regular files, directories and
links (both symbolic and hard) preserving most of their metadata. It can
optionally use compression and transmit only binary diffs to speed up
transfers. However, since all data is base64 encoded for transmission over the
TTY, this protocol will never be competitive with more direct file transfer
mechanisms.

Overall design
----------------

The basic design of this protocol is around transfer "sessions". Since
untrusted software should not be able to read/write to another machines
filesystem, a session must be approved by the user in the terminal emulator
before any actual data is transmitted.

There can be either send or receive sessions. In send sessions files are sent
from from remote client to the terminal emulator and vice versa for receive
sessions. Every session basically consists of sending metadata for the files
first and then sending the actual data. The session is a series of commands,
every command carrying the session id (which should be a random unique-ish
identifier, to avoid conflicts). The session is bi-directional with commands
going both to and from the terminal emulator. Every command in a session
also carries an ``action`` field that specifies what the command does. The
remaining fields in the command are dependent on the nature of the command.

Let's look at some simple examples of sessions to get a feel for the protocol.


Sending files to the terminal emulator
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The client starts by sending a start send command::

    → action=send id=someid

It then waits for a status message from the terminal either
allowing the transfer or refusing it. Until this message is received
the client is not allowed to send any more commands for the session.
The terminal emulator should drop a session if it receives any commands
before sending an ``OK`` response. If the user accepts the transfer,
the terminal will send::

    ← action=status id=someid status=OK

Or if the transfer is refused::

    ← action=status id=someid status=EPERM:User refused the transfer

The client then sends one or more ``file`` commands with the metadata of the file it wants
to transfer::

    → action=file id=someid file_id=f1 name=/path/to/destination
    → action=file id=someid file_id=f2 name=/path/to/destination2 ftype=directory

The terminal responds with either ``OK`` for directories or ``STARTED`` for
files::

    ← action=status id=someid file_id=f1 status=STARTED
    ← action=status id=someid file_id=f2 status=OK

If there was an error with the file, for example, if the terminal does not have
permission to write to the specified location, it will instead respond with an
error, such as::

    ← action=status id=someid file_id=f1 status=EPERM:No permission

The client sends data for files using ``data`` commands. It does not need to
wait for the ``STARTED`` from the terminal for this, the terminal must discard data
for files that are not ``STARTED``. Data for a file is sent in individual
chunks of no larger than ``4096`` bytes. For example::


    → action=data id=someid file_id=f1 data=chunk of bytes
    → action=data id=someid file_id=f1 data=chunk of bytes
    ...
    → action=end_data id=someid file_id=f1 data=chunk of bytes

The sequence of data transmission for a file is ended with an ``end_data``
command. After each data packet is received the terminal replies with
an acknowledgement of the form::

    ← action=status id=someid file_id=f1 status=PROGRESS size=bytes written

After ``end_data`` the terminal replies with::

    ← action=status id=someid file_id=f1 status=OK size=bytes written

If an error occurs while writing the data, the terminal replies with an error
code and ignores further commands about that file, for example::

    ← action=status id=someid file_id=f1 status=EIO:Failed to write to file

Once the client has finished sending as many files as it wants to, it ends
the session with::

    → action=finish id=someid

At this point the terminal commits the session, applying file metadata,
creating links, etc. If any errors occur it responds with an error message,
such as::

    ← action=status id=someid status=Some error occurred


Receiving files to the terminal emulator
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The client starts by sending a start receive command::

    → action=receive id=someid size=num_of_paths

It then sends a list of ``num_of_paths`` paths it is interested in
receiving::

    → action=file id=someid file_id=f1 name=/some/path
    → action=file id=someid file_id=f2 name=/some/path2
    ...

The client must then wait for responses from the terminal emulator. It
is an error to send anymore commands to to the terminal until an ``OK``
response is received from the terminal. The terminal wait for the user to accept
the request. If accepted, it sends::

    ← action=status id=someid status=OK

If permission is denied it sends::

    ← action=status id=someid status=EPERM:User refused the transfer

The terminal then sends the metadata for all requested files. If any of them
are directories, it traverses the directories recursively, listing all files.
Note that symlinks must not be followed, but sent as symlinks::

    ← action=file id=someid file_id=f1 mtime=XXX permissions=XXX name=/absolute/path status=file_id1 size=size_in_bytes file_type=type parent=file_id of parent
    ← action=file id=someid file_id=f1 mtime=XXX permissions=XXX name=/absolute/path2 status=file_id2 size=size_in_bytes file_type=type parent=file_id of parent
    ...

Here the ``file_id`` field is set to the ``file_id`` value sent from the client
and the ``status`` field is set to the actual file id for each file. This is
because a file query sent from the client can result in multiple actual files if
it is a directory. The ``parent`` field is the actual ``file_id`` of the directory
containing this file and is set for entries that are generated from client
requests that match directories. This allows the client to build an unambiguous picture
of the file tree.

Once all the files are listed, the terminal sends an ``OK`` response that also
specifies the absolute path to the home directory for the user account running
the terminal::

    ← action=status id=someid status=OK name=/path/to/home

If an error occurs while listing any of the files asked for by the client,
the terminal will send an error response like::

    ← action=status id=someid file_id=f1 status=ENOENT: Does not exist

Here, ``file_id`` is the same as was sent by the client in its initial query.

Now, the client can send requests for file data using the paths sent by the
terminal emulator::

    → action=file id=someid file_id=f1 name=/some/path
    ...

The terminal emulator replies with the data for the files, as a sequence of
``data`` commands for each file (the terminal emulator should send the data for
one file at a time)::


    ← action=data id=someid file_id=f1 data=chunk of bytes
    ...
    ← action=end_data id=someid file_id=f1 data=chunk of bytes

If any errors occur reading file data, the terminal emulator sends an error
message for the file, for example::

    ← action=status id=someid file_id=f1 status=EIO:Could not read

Once the client is done reading data for all the files it expects, it
terminates the session with::

    → action=finished id=someid

Quieting response from the terminal
-------------------------------------

TODO:

File metadata
-----------------

TODO:

Symbolic and hard links
---------------------------

TODO:

Transmitting binary deltas
-----------------------------

TODO:

Compression
--------------

TODO:


Bypassing explicit user authorization
------------------------------------------

TODO:

Encoding of transfer commands as escape codes
------------------------------------------------

Transfer commands are encoded as ``OSC`` escape codes of the form::

    <OSC> 5113 ; key=value ; key=value ... <ST>

Here ``OSC`` is the bytes ``0x1b 0x5d`` and ``ST`` is the bytes
``0x1b 0x5c``. Keys are words containing only the characters ``[a-zA-Z0-9_]``
and ``value`` is arbitrary data, whose encoding is dependent on the value of
``key``. Unknown keys **must** be ignored when decoding a command.
The number ``5113`` is a constant and is unused by any known OSC codes. It is
the numeralization of the word ``file``.


.. table:: The keys and value types for this protocol
    :align: left

    ================= ======== ============== =======================================================================
    Key               Key name Value type     Notes
    ================= ======== ============== =======================================================================
    action            ac       enum           send, file, data, end_data, receive, cancel, status, finish
    compression       zip      enum           none, zlib
    file_type         ft       enum           regular, directory, symlink, link
    transmission_type tt       enum           simple, rsync
    id                id       safe_string    A unique-ish value, to avoid collisions
    file_id           fid      safe_string    Must be unique per file in a session
    bypass            pw       safe_string    hash of the bypass password and the session id
    quiet             q        integer        0 - verbose, 1 - only errors, 2 - totally silent
    mtime             mod      integer        the modification time of file in nanoseconds since the UNIX epoch
    permissions       prm      integer        the UNIX file permissions bits
    size              sz       integer        size in bytes
    name              n        base64_string  The path to a file
    status            st       base64_string  Status messages
    parent            pr       safe_string    The file id of the parent directory
    data              d        base64_bytes   Binary data
    ================= ======== ============== =======================================================================

The ``Key name`` is the actual serialized name of the key sent in the escape
code. So for example, ``permissions=123`` is serialized as ``prm=123``. This
is done to reduce overhead.

The value types are:

enum
    One from a permitted set of values, for example::

        ac=file

safe_string
    A string consisting only of characters from the set ``[0-9a-zA-Z_:.,/!@#$%^&*()[]{}~`?"'\\|=+-]``
    Note that the semi-colon is missing from this set.

integer
    A base-10 number composed of the characters ``[0-9]`` with a possible
    leading ``-`` sign

base64_string
    A base64 encoded UTF-8 string using the standard base64 encoding

base64_bytes
    Binary data encoded using the standard base64 encoding


An example of serializing an escape code is shown below::

    action=send id=test name=somefile size=3 data=01 02 03

becomes::

    <OSC> 5113 ; ac=send ; id=test ; n=c29tZWZpbGU= ; sz=3 ; d=AQID <ST>

Here ``c29tZWZpbGU`` is the base64 encoded form of somefile and ``AQID`` is the
base64 encoded form of the bytes ``0x01 0x02 0x03``. The spaces in the encoded
form are present for clarity and should be ignored.
