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

The client starts by sending a start command command::

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
