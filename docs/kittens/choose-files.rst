Selecting files, fast
========================

.. only:: man

    Overview
    --------------

.. versionadded:: 0.43.0

The choose-files kitten is designed to allow you to select files, very fast,
with just a few key strokes. It operates like `fzf
<https://github.com/junegunn/fzf/>`__ and similar fuzzy finders, except that
it is specialised for finding files. As such it supports features such as
filtering by file type, file type icons, content previews (coming soon) and
so on, out of the box. It can be used as a drop in (but much more efficient and
keyboard friendly) replacement for the :guilabel:`File open and save`
dialog boxes common to GUI programs. On Linux, with the help of the
:doc:`desktop-ui </kittens/desktop-ui>` kitten, you can even convince
most GUI programs on your computer to use this kitten instead of regular file
dialogs.

Simply run it as::

    kitten choose-files

to select a single file from the tree rooted at the current working directory.

Configuration
------------------------

You can configure various aspects of the kitten's operation by creating a
:file:`choose-files.conf` in your :ref:`kitty config folder <confloc>`.
See below for the supported configuration directives.


.. include:: /generated/conf-kitten-choose_files.rst


.. include:: /generated/cli-kitten-choose_files.rst


