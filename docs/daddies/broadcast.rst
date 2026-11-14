broadcast
==================================================

.. only:: man

    Overview
    --------------

*Type text in all datty windows simultaneously*

The ``broadcast`` daddy can be used to type text simultaneously in all
:term:`datty windows <window>` (or a subset as desired).

To use it, simply create a mapping in :file:`datty.conf` such as::

    map f1 launch --allow-remote-control daddy broadcast

Then press the :kbd:`F1` key and whatever you type in the newly created window
will be sent to all datty windows.

You can use the options described below to control which windows are selected.

For example, only broadcast to other windows in the current tab::

    map f1 launch --allow-remote-control daddy broadcast --match-tab state:focused

.. program:: datty +daddy broadcast


.. include:: /generated/cli-daddy-broadcast.rst
