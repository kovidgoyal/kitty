The kitty remote control protocol
==================================

The kitty remote control protocol is a simple protocol that involves sending
data to kitty in the form of JSON. Any individual command of kitty has the
form::

    <ESC>P@kitty-cmd<JSON object><ESC>\

Where ``<ESC>`` is the byte ``0x1b``. The JSON object has the form:

.. code-block:: json

    {
        "cmd": "command name",
        "version": "<kitty version>",
        "no_response": "<Optional Boolean>",
        "kitty_window_id": "<Optional value of the KITTY_WINDOW_ID env var>",
        "payload": "<Optional JSON object>"
    }

The ``version`` above is an array of the form :code:`[0, 14, 2]`. If you are
developing a standalone client, use the kitty version that you are developing
against. Using a version greater than the version of the kitty instance you are
talking to, will cause a failure.

Set ``no_response`` to ``true`` if you don't want a response from kitty.

The optional payload is a JSON object that is specific to the actual command
being sent. The fields in the object for every command are documented below.

As a quick example showing how easy to use this protocol is, we will implement
the ``@ ls`` command from the shell using only shell tools.

First, run kitty as::

    kitty -o allow_remote_control=socket-only --listen-on unix:/tmp/test

Now, in a different terminal, you can get the pretty printed ``@ ls`` output
with the following command line::

    echo -en '\eP@kitty-cmd{"cmd":"ls","version":[0,14,2]}\e\\' | socat - unix:/tmp/test | awk '{ print substr($0, 13, length($0) - 14) }' | jq -c '.data | fromjson' | jq .

There is also the statically compiled stand-alone executable ``kitten``
that can be used for this, available from the `kitty releases
<https://github.com/kovidgoyal/kitty/releases>`__ page::

    kitten @ --help

.. _rc_crypto:

Encrypted communication
--------------------------

.. versionadded:: 0.26.0

When using the :opt:`remote_control_password` option communication to the
terminal is encrypted to keep the password secure. A public key is used from
the :envvar:`KITTY_PUBLIC_KEY` environment variable. Currently, only one
encryption protocol is supported. The protocol number is present in
:envvar:`KITTY_PUBLIC_KEY` as ``1``. The key data in this environment variable
is :rfc:`Base-85 <1924>` encoded.  The algorithm used is `Elliptic Curve Diffie
Helman <https://en.wikipedia.org/wiki/Elliptic-curve_Diffie–Hellman>`__ with
the `X25519 curve <https://en.wikipedia.org/wiki/Curve25519>`__. A time based
nonce is used to minimise replay attacks. The original JSON command has the
fields: ``password`` and ``timestamp`` added. The timestamp is the number of
nanoseconds since the epoch, excluding leap seconds. Commands with a timestamp
more than 5 minutes from the current time are rejected. The command is then
encrypted using AES-256-GCM in authenticated encryption mode, with a symmetric
key that is derived from the ECDH key-pair by running the shared secret through
SHA-256 hashing, once.  An IV of at least 96 bits of CSPRNG data is used. The
tag for authenticated encryption **must** be at least 128 bits long.  The tag
**must** authenticate only the value of the ``encrypted`` field. A new command
is created and transmitted that contains the fields:

.. code-block:: json

    {
        "version": "<kitty version>",
        "iv": "base85 encoded IV",
        "tag": "base85 encoded AEAD tag",
        "pubkey": "base85 encoded ECDH public key of sender",
        "encrypted": "The original command encrypted and base85 encoded"
    }

Async and streaming requests
---------------------------------

Some remote control commands require asynchronous communication, that is, the
response from the terminal can happen after an arbitrary amount of time. For
example, the :code:`select-window` command requires the user to select a window
before a response can be sent. Such command must set the field :code:`async`
in the JSON block above to a random string that serves as a unique id. The
client can cancel an async request in flight by adding the :code:`cancel_async`
field to the JSON block. A async response remains in flight until the terminal
sends a response to the request. Note that cancellation requests dont need to
be encrypted as users must not be prompted for these and the worst a malicious
cancellation request can do is prevent another sync request from getting a
response.

Similar to async requests are *streaming* requests. In these the client has to
send a large amount of data to the terminal and so the request is split into
chunks. In every chunk the JSON block must contain the field ``stream`` set to
``true`` and ``stream_id`` set to a random long string, that should be the same for
all chunks in a request. End of data is indicated by sending a chunk with no data.

.. include:: generated/rc.rst
