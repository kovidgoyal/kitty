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
before any actual data is transmitted, unless a :ref:`pre-shared password is
provided <bypass_auth>`.

There can be either send or receive sessions. In send sessions files are sent
from remote client to the terminal emulator and vice versa for receive sessions.
Every session basically consists of sending metadata for the files first and
then sending the actual data. The session is a series of commands, every command
carrying the session id (which should be a random unique-ish identifier, to
avoid conflicts). The session is bi-directional with commands going both to and
from the terminal emulator. Every command in a session also carries an
``action`` field that specifies what the command does. The remaining fields in
the command are dependent on the nature of the command.

Let's look at some simple examples of sessions to get a feel for the protocol.


Sending files to the computer running the terminal emulator
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

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


Receiving files from the computer running terminal emulator
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The client starts by sending a start receive command::

    → action=receive id=someid size=num_of_paths

It then sends a list of ``num_of_paths`` paths it is interested in
receiving::

    → action=file id=someid file_id=f1 name=/some/path
    → action=file id=someid file_id=f2 name=/some/path2
    ...

The client must then wait for responses from the terminal emulator. It
is an error to send anymore commands to the terminal until an ``OK``
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

The client must not send requests for directories and absolute symlinks.
The terminal emulator replies with the data for the files, as a sequence of
``data`` commands each with a chunk of data no larger than ``4096`` bytes,
for each file (the terminal emulator must send the data for
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

Canceling a session
----------------------

A client can decide to cancel a session at any time (for example if the user
presses :kbd:`ctrl+c`). To cancel a session it sends a ``cancel`` action to the
terminal emulator::

    → action=cancel id=someid

The terminal emulator drops the session and sends a cancel acknowledgement::

    ← action=status id=someid status=CANCELED

The client **must** wait for the canceled response from the emulator discarding
any other responses till the cancel is received. If it does not wait, after
it quits the responses might end up being printed to screen.

Quieting responses from the terminal
-------------------------------------

The above protocol includes lots of messages from the terminal acknowledging
receipt of data, granting permission etc., acknowledging cancel requests, etc.
For extremely simple clients like shell scripts, it might be useful to suppress
these responses, which can be done by adding the ``quiet`` key to the start
session command::

    → action=send id=someid quiet=1

The key can take the values ``1`` - meaning suppress acknowledgement responses
or ``2`` - meaning suppress all responses including errors. Only actual data
responses are sent. Note that in particular this means acknowledgement of
permission for the transfer to go ahead is suppressed, so this is typically
useful only with :ref:`bypass_auth`.

.. _file_metadata:

File metadata
-----------------

File metadata includes file paths, permissions and modification times. They are
somewhat tricky as different operating systems support different kinds of
metadata. This specification defines a common minimum set which should work
across most operating systems.

File paths
    File paths must be valid UTF-8 encoded POSIX paths (i.e. using the forward slash
    ``/`` as a separator). Linux systems allow non UTF-8 file paths, these
    are not supported. A leading ``~/`` means a path is relative to the
    ``HOME`` directory. All path must be either absolute (i.e. with a leading
    ``/``) or relative to the HOME directory. Individual components of the
    path must be no longer than 255 UTF-8 bytes. Total path length must be no
    more than 4096 bytes. Paths from Windows systems must use the forward slash
    as the separator, the first path component must be the drive letter with a
    colon. For example: :file:`C:\\some\\file.txt` is represented as
    :file:`/C:/some/file.txt`. For maximum portability, the following
    characters *should* be omitted from paths (however implementations are free
    to try to support them returning errors for non-representable paths)::

        \ * : < > ? | /

File modification times
    Must be represented as the number of nanoseconds since the UNIX epoch. An
    individual file system may not store file metadata with this level of
    accuracy in which case it should use the closest possible approximation.

File permissions
    Represented as a number with the usual UNIX read, write and execute bits.
    In addition, the sticky, set-group-id and set-user-id bits may be present.
    Implementations should make a best effort to preserve as many bits as
    possible. On Windows, there is only a read-only bit. When reading file
    metadata all the ``WRITE`` bits should be set if the read only bit is clear
    and cleared if it is set. When writing files, the read-only bit should be
    set if the bit indicating write permission for the user is clear. The other
    UNIX bits must be ignored when writing. When reading, all the ``READ`` bits
    should always be set and all the ``EXECUTE`` bits should be set if the file is
    directly executable by the Windows Operating system. There is no attempt to
    map Window's ACLs to permission bits.


Symbolic and hard links
---------------------------

Symbolic and hard links can be preserved by this protocol.

.. note::
   In the following when target paths of symlinks are sent as actual paths, they must be
   encoded in the same way as discussed in :ref:`file_metadata`. It is up to
   the receiving side to translate them into appropriate paths for the local
   operating system. This may not always be possible, in which case either the
   symlink should not be created or a broken symlink should be created.


Sending links to the terminal emulator
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When sending files to the terminal emulator, the file command has the form::

    → action=file id=someid file_id=f1 name=/path/to/link file_type=link
    → action=file id=someid file_id=f2 name=/path/to/symlink file_type=symlink

Then, when the client is sending data for the files, for hardlinks, the data
will be the ``file_id`` of the target file (assuming the target file is also
being transmitted, otherwise the hard link should be transmitted as a plain
file)::

    → action=end_data id=someid file_id=f1 data=target_file_id_encoded_as_utf8

For symbolic links, the data is a little more complex. If the symbolic link is
to a destination being transmitted, the data has the form::

    → action=end_data id=someid file_id=f1 data=fid:target_file_id_encoded_as_utf8
    → action=end_data id=someid file_id=f1 data=fid_abs:target_file_id_encoded_as_utf8

The ``fid_abs`` form is used if the symlink uses an absolute path, ``fid`` if
it uses a relative path. If the symlink is to a destination that is not being
transmitted, then the prefix ``path:`` and the actual path in the symlink is
transmitted.

Receiving links from the terminal emulator
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When receiving files from the terminal emulator, link data is transmitted in
two parts. First when the emulator sends the initial file listing to the
client, the ``file_type`` is set to the link type and the ``data`` field is set
to file_id of the target file if the target file is included in the listing.
For example::

    ← action=file id=someid file_id=f1 status=file_id1 ...
    ← action=file id=someid file_id=f1 status=file_id2 file_type=symlink data=file_id1 ...

Here the rest of the metadata has been left out for clarity. Notice that the
second file is symlink whose ``data`` field is set to the file id of the first
file (the value of the ``status`` field of the first file). The same technique
is used for hard links.

The client should not request data for hard links, instead creating them
directly after transmission is complete. For symbolic links the terminal
must send the actual symbolic link target as a UTF-8 encoded path in the
data field. The client can use this path either as-is (when the target is not
a transmitted file) or to decide whether to create the symlink with a relative
or absolute path when the target is a transmitted file.


Transmitting binary deltas
-----------------------------

Repeated transfer of large files that have only changed a little between
the receiving and sending side can be sped up significantly by transmitting
binary deltas of only the changed portions. This protocol has built-in support
for doing that. This support uses the `rsync algorithm
<https://rsync.samba.org/tech_report/tech_report.html>`__. In this algorithm, first the
receiving side sends a file signature that contains hashes of blocks
in the file. Then the sending side sends only those blocks that have changed.
The receiving side applies these deltas to the file to update it till it matches
the file on the sending side.

The modification to the basic protocol consists of setting the
``transmission_type`` key to ``rsync`` when requesting a file. This triggers
transmission of signatures and deltas instead of file data. The details are
different for sending and receiving.

Sending to the terminal emulator
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When sending the metadata of the file it wants to transfer, the client adds the
``transmission_type`` key::

    → action=file id=someid file_id=f1 name=/path/to/destination transmission_type=rsync

The ``STARTED`` response from the terminal will have ``transmission_type`` set
to ``rsync`` if the file exists and the terminal is able to send signature data::

    ← action=status id=someid file_id=f1 status=STARTED transmission_type=rsync

The terminal then transmits the signature using ``data`` commands::

    ← action=data id=someid file_id=f1 data=...
    ...
    ← action=end_data id=someid file_id=f1 data=...

Once the client receives and processes the full signature, it transmits the
file delta to the terminal as ``data`` commands::

    → action=data id=someid file_id=f1 data=...
    → action=data id=someid file_id=f1 data=...
    ...
    → action=end_data id=someid file_id=f1 data=...

The terminal then uses this delta to update the file.

Receiving from the terminal emulator
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When the client requests file data from the terminal emulator, it can
add the ``transmission_type=rsync`` key to indicate it will be sending
a signature for that file::

    → action=file id=someid file_id=f1 name=/some/path transmission_type=rsync

The client then sends the signature using ``data`` commands::

    → action=data id=someid file_id=f1 data=...
    ...
    → action=end_data id=someid file_id=f1 data=...

After receiving the signature the terminal replies with the delta as a series
of ``data`` commands::

    ← action=data id=someid file_id=f1 data=...
    ...
    ← action=end_data id=someid file_id=f1 data=...

The client then uses this delta to update the file.

The format of signatures and deltas
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In what follows, all integers must be encoded in little-endian format,
regardless of the architecture of the machines involved. The XXH3 hash family
refers to `the xxHash algorithm
<https://github.com/Cyan4973/xxHash/blob/dev/doc/xxhash_spec.md>`__.

A signature first has a 12 byte header of the form:

.. code::

    uint16 version
    uint16 checksum_type
    uint16 strong_hash_type
    uint16 weak_hash_type
    uint32 block_size

These fields define the parameters to the rsync algorithm. Allowed values are
currently all zero except for ``block_size``, which is usually the square root
of the file size, but implementations are free to use any algorithm they like
to arrive at the block size.

``checksum_type`` must be ``0`` which indicates using the XXH3-128 bit hash
to verify file integrity after transmission.

``strong_hash_type`` must be ``0`` which indicates using the XXH3-64 bit hash
to identify blocks.

``weak_hash_type`` must be ``0`` which indicates using the `rsync rolling
checksum hash <https://rsync.samba.org/tech_report/node3.html>`__ to identify
blocks, weakly.

After the header comes the list of block signatures. The number of blocks is
unknown allowing for streaming, the transfer protocol takes care of indicating
end-of-stream via an ``action=end_data`` packet. Each signature in the list is of the form:

.. code::

   uint64 index
   uint32 weak_hash
   uint64 strong_hash

Here, ``index`` is the zero-based block number. ``weak_hash`` is the weak, but easy
to calculate hash of the block and strong hash is a stronger hash of the block
that is very unlikely to collide.

The algorithms used for these hashes are specified by the signature header
above. Given the ``block_size`` from the header and ``index`` the position of a
block in the file is: ``index * block_size``.

Once the sending side receives the signature, it calculates a *delta* based on
the actual file contents and transmits that delta to the receiving side. The delta
is of the form of a list of *operations*. An operation is a single byte
denoting the operation type followed by variable length data depending on the
type. The types of operations are:

``Block (type=0)``
    Followed by an 8 byte ``uint64`` that is the block index. It means copy the
    specified block from the existing file to the output, unmodified.

``Data (type=1)``
    Followed by a 4 byte ``uint32`` that is the size of the payload and then the
    payload itself. The payload must be written to the output.

``Hash (type=2)``
    Followed by a 2 byte ``uint16`` specifying the size of the hash checksum and
    then the checksum itself. The checksum of the output file must match this
    checksum. The algorithm used to calculate the checksum is specified in the
    signature header.

``BlockRange (type=3)``
    Followed by an 8 byte ``uint64`` that is the starting block index and then
    a 4 byte ``uint32`` (``N``) that is the number of additional blocks. Works just
    like ``Block`` above, except that after copying the block an additional (``N``) more
    blocks must be copied.


Compression
--------------

Individual files can be transmitted compressed if needed.
Currently, only :rfc:`1950` ZLIB based deflate compression is
supported, which is specified using the ``compression=zlib`` key when
requesting a file. For example when sending files to the terminal emulator,
when sending the file metadata the ``compression`` key can also be
specified::

    → action=file id=someid file_id=f1 name=/path/to/destination compression=zlib

Similarly when receiving files from the terminal emulator, the final file
command that the client sends to the terminal requesting the start of the
transfer of data for the file can include the ``compression`` key::

    → action=file id=someid file_id=f1 name=/some/path compression=zlib

.. _bypass_auth:

Bypassing explicit user authorization
------------------------------------------

In order to bypass the requirement of interactive user authentication,
this protocol has the ability to use a pre-shared secret (password).
When initiating a transfer session the client sends a hash of the password and
the session id::

    → action=send id=someid bypass=sha256:hash_value

For example, suppose that the session id is ``mysession`` and the
shared secret is ``mypassword``. Then the value of the ``bypass``
key above is ``sha256:SHA256("mysession" + ";" + "mypassword")``, which
is::

    → action=send id=mysession bypass=sha256:192bd215915eeaa8c2b2a4c0f8f851826497d12b30036d8b5b1b4fc4411caf2c

The value of ``bypass`` is of the form ``hash_function_name : hash_value``
(without spaces). Currently, only the SHA256 hash function is supported.

.. warning::
   Hashing does not effectively hide the value of the password. So this
   functionality should only be used in secure/trusted contexts. While there
   exist hash functions harder to compute than SHA256, they are unsuitable as
   they will introduce a lot of latency to starting a session and in any case
   there is no mathematical proof that **any** hash function is not brute-forceable.

Terminal implementations are free to use their own more advanced hashing
schemes, with prefixes other than those starting with ``sha``, which are
reserved. For instance, kitty uses a scheme based on public key encryption
via :envvar:`KITTY_PUBLIC_KEY`. For details of this scheme, see the
``check_bypass()`` function in the kitty source code.

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
    A string consisting only of characters from the set ``[0-9a-zA-Z_:./@-]``
    Note that the semi-colon is missing from this set.

integer
    A base-10 number composed of the characters ``[0-9]`` with a possible
    leading ``-`` sign. When missing the value is zero.

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
