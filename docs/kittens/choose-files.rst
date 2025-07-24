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
filtering by file type, file type icons, content previews and
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


Hidden and ignored files
--------------------------

By default, the kitten does not process hidden files and directories (whose
names start with a period). This can be :opt:`changed in the configuration <kitten-choose_files.show_hidden>`
and also at runtime via the clickable link to the right of the search input.

Similarly, the kitten respects both :file:`.gitignore` and :file:`.ignore`
files, by default. This can also be changed both :opt:`in configuration
<kitten-choose_files.respect_ignores>` or at runtime. Note that
:file:`.gitignore` files are only respected if there is also a :file:`.git`
directory present. The kitten also supports the global :file:`.gitignore` file,
though it applies only inside git working trees. You can specify :opt:`global ignore
patterns <kitten-choose_files.ignore>`, that apply everywhere in :file:`choose-files.conf`.


Selecting non-existent files (save file names)
-------------------------------------------------

This kitten can also be used to select non-existent files, that is a new file
for a :guilabel:`Save file` type of dialog using :option:`--mode <kitty +kitten
choose_files --mode>`:code:`=save-file`. Once you have changed to the directory
you want the file to be in (using the :kbd:`Tab` key),
press :kbd:`Ctrl+Enter` and you will be able to type in the file name.


Selecting directories
---------------------------

This kitten can also be used to select directories,
for an :guilabel:`Open directory` type of dialog using :option:`--mode <kitty +kitten
choose_files --mode>`:code:`=dir`. Once you have changed to the directory
you want, press :kbd:`Ctrl+Enter` to accept it. Or if you are in a parent
directory you can select a descendant directory by pressing :kbd:`Enter`, the
same as you would for selecting a file to open.


Configuration
------------------------

You can configure various aspects of the kitten's operation by creating a
:file:`choose-files.conf` in your :ref:`kitty config folder <confloc>`.
See below for the supported configuration directives.


.. include:: /generated/conf-kitten-choose_files.rst


.. include:: /generated/cli-kitten-choose_files.rst


