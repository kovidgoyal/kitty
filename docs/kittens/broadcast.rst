broadcast - type text in all kitty windows
==================================================

The ``broadcast`` kitten can be used to type text simultaneously in
all kitty windows (or a subset as desired).

To use it, simply create a mapping in :file:`kitty.conf` such as::

    map F1 launch --allow-remote-control kitty +kitten broadcast

Then press the :kbd:`F1` key and whatever you type in the newly created widow
will be sent to all kitty windows.

You can use the options described below to control which windows
are selected.

.. program:: kitty +kitten broadcast


Command Line Interface
--------------------------

.. include:: /generated/cli-kitten-broadcast.rst
