broadcast
==================================================

.. only:: man

    Overview
    --------------

*Type text in all kitty windows simultaneously*

The ``broadcast`` kitten can be used to type text simultaneously in all
:term:`kitty windows <window>` (or a subset as desired).

To use it, simply create a mapping in :file:`kitty.conf` such as::

    map f1 launch --allow-remote-control kitty +kitten broadcast

Then press the :kbd:`F1` key and whatever you type in the newly created window
will be sent to all kitty windows.

You can use the options described below to control which windows are selected.

For example, only broadcast to other windows in the current tab::

    map f1 launch --allow-remote-control kitty +kitten broadcast --match-tab state:focused

.. program:: kitty +kitten broadcast


.. include:: /generated/cli-kitten-broadcast.rst
