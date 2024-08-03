notify
==================================================

.. only:: man

    Overview
    --------------

Show pop-up system notifications.

.. highlight:: sh

.. versionadded:: 0.36.0
   The notify kitten

The ``notify`` kitten can be used to show pop-up system notifications
from the shell. It even works over SSH. Using it is as simple as::

    kitten notify "Good morning" Hello world, it is a nice day!

To add an icon, use::

    kitten notify --icon-path /path/to/some/image.png "Good morning" Hello world, it is a nice day!
    kitten notify --icon firefox "Good morning" Hello world, it is a nice day!


To be informed when the notification is activated::

    kitten notify --wait-for-completion "Good morning" Hello world, it is a nice day!

Then, the kitten will wait till the notification is either closed or activated.
If activated, a ``0`` is printed to :file:`STDOUT`. You can press the
:kbd:`Esc` or :kbd:`Ctrl+c` keys to abort, closing the notification.

To add buttons to the notification::

    kitten notify --wait-for-completion --button One --button Two "Good morning" Hello world, it is a nice day!

.. program:: kitty +kitten notify

.. tip:: Learn about the underlying :doc:`/desktop-notifications` escape code protocol.

.. include:: /generated/cli-kitten-notify.rst
