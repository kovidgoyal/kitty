Documentation for the kitty remote control protocol
======================================================

The kitty remote control protocol is a simple protocol that involves sending
data to kitty in the form of JSON. Any individual command ot kitty has the
form::

    <ESC>P@kitty-cmd<JSON object><ESC>\

Where ``<ESC>`` is the byte ``0x1b``. The JSON object has the form::

    {
        'cmd': "command name",
        'version': "kitty version",
        'no_response': Optional Boolean,
        'payload': <Optional JSON object>,
    }

The ``version`` above is a string of the form :code:`0.14.2`. If you are developing a
standalone client, use the kitty version that you are developing against. Using
a version greater than the version of the kitty instance you are talking to,
will cause a failure.

Set ``no_response`` to True if you dont want a response from kitty.

The optional payload is a JSON object that is specific to the actual command being sent.
The fields in the object for every command are documented below.

.. include:: generated/rc.rst
