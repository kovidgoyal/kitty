The kitty remote control protocol
==================================

The kitty remote control protocol is a simple protocol that involves sending
data to kitty in the form of JSON. Any individual command of kitty has the
form::

    <ESC>P@kitty-cmd<JSON object><ESC>\

Where ``<ESC>`` is the byte ``0x1b``. The JSON object has the form::

    {
        "cmd": "command name",
        "version": <kitty version>,
        "no_response": <Optional Boolean>,
        "payload": <Optional JSON object>,
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

Encrypted communication
--------------------------

When using the :opt:`remote_control_password` option communication to the terminal is
encrypted to keep the password secure. A public key is used from the
:envvar:`KITTY_PUBLIC_KEY` environment variable. Currently, only one encryption
protocol is supported. The protocol number is present in
:envvar:`KITTY_PUBLIC_KEY` as ``1``. The key data in this environment variable is Base-85 encoded.
The algorithm used is Elliptic Curve Diffie Helman with the X25519 curve. A
time based nonce is used to avoid replay attacks. The original JSON command has
the fields: ``password`` and ``timestamp`` added. The timestamp is the number
of nanoseconds since the epoch, excluding leap seconds. Commands with a
timestamp more than 5 minutes from the current time are rejected. The command is then
encrypted using AES-256-GCM in AEAD mode, with a secret key that is derived from the ECDH
key-pair by running the shared secret through SHA-256 hashing, once. An IV of
96 bits of CSRNG data is used. The tag for AEAD must be 128 bits long. A new
command is created that contains the fields::

    version: copied form the original command
    iv: base85 encoded IV
    tag: base85 encoded AEAD tag
    pubkey: base85 encoded ECDH public key of sender
    enc_proto: The first field from KITTY_PUBLIC_KEY, currently always ``1``
    encrypted: The original command encrypted

.. include:: generated/rc.rst
