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
Type a few letters from the filename and once it becomes the top selection,
press :kbd:`Enter`. You can change the current directory by instead selecting a
directory and pressing the :kbd:`Tab` key. :kbd:`Shift+Tab` goes up one
directory level.

Creating shortcuts to favorite/frequently used directories
------------------------------------------------------------

You can create keyboard shortcuts to quickly switch to any directory in
:file:`choose-files.conf`. For example:

.. code-block:: conf

   map ctrl+t cd /tmp
   map alt+p  cd ~/my/project

Selecting multiple files
-----------------------------

When you wish to select multiple files, start the kitten with :option:`--mode
<kitty +kitten choose_files --mode>`:code:`=files`. Then instead of pressing
:kbd:`Enter`, press :kbd:`Shift+Enter` instead and the file will be added to the list
of selections. You can also hold the :kbd:`Ctrl` key and click on files to add
them to the selections. Similarly, you can hold the :kbd:`Alt` key and click to
select ranges of files (similar to using :kbd:`Shift+click` in a GUI app).
Press :kbd:`Enter` on the last selected file to finish. The list of selected
files is displayed at the bottom of the kitten and you can click on them
to deselect a file. Similarly, pressing :kbd:`Shift+Enter` will un-select a
previously selected file.

Configuration
------------------------

You can configure various aspects of the kitten's operation by creating a
:file:`choose-files.conf` in your :ref:`kitty config folder <confloc>`.
See below for the supported configuration directives.


.. include:: /generated/conf-kitten-choose_files.rst


.. include:: /generated/cli-kitten-choose_files.rst


