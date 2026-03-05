The Drag and Drop protocol
==============================================

.. versionadded:: 0.47.0

This protocol enables drag and drop functionality for terminal programs
that is as good as the drag and drop functionality available for GUI
programs.

There is one central escape code used for this protocol, which is of the form::

    OSC _dnd_code ; metadata ; base64 encoded payload ST

Here, ``OSC`` is the bytes ``ESC ] (0x1b 0x5b)``. The ``metadata`` is a colon
separated list of ``key=value`` pairs. The final part of the escape code is the
:rfc:`base64 <4648>` encoded payload data, whose meaning depends on the
metadata. The payload must be no more than 4096 bytes *before base64 encoding*.

Accepting drops
-----------------

In order to inform the terminal emulator that the program accepts drops, it
must, send the following escape code::

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
``t``    Single character.     ``a``      The overall action this graphics command is performing.
         ``(a, A,                         ``t`` - transmit data, ``T`` - transmit data and display image,
         )``                              ``q`` - query terminal, ``p`` - put (display) previous transmitted image,
                                          ``d`` - delete image, ``f`` - transmit data for animation frames,
                                          ``a`` - control animation, ``c`` - compose animation frames


