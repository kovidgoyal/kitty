Transfer files
================

.. warning::
   This kitten is currently experimental, use with care.

Transfer files to and from remote computers over the ``TTY`` device itself.
This means that file transfer works over nested SSH sessions, serial links,
etc. Anywhere you have a terminal device, you can transfer files.

This kitten support transferring entire directory trees, preserving soft and
hard links, file permissions and times, etc. It even supports the `rsync
<https://en.wikipedia.org/wiki/Rsync>`_ protocol to transfer only changes to
large files and to automatically resume interrupted transfers.

.. seealso:: See the :doc:`remote_file` kitten

.. note::
   This kitten (which practically means kitty) must be installed on the remote
   machine. If that is not possible you can use the :doc:`remote_file` kitten
   instead. Or write your own script to use the underlying file transfer
   protocol.

.. versionadded:: 0.24.0

.. include:: ../generated/cli-kitten-transfer.rst
