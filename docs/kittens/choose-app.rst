Choosing applications to open files with
==========================================

.. only:: man

    Overview
    --------------

.. versionadded:: 1.0.0

The choose-app kitten opens files and URLs with the appropriate application, as
a replacement for :program:`xdg-open`. When it does not already know which
application to use, it lets you choose one, quickly, with just a few key
strokes. It finds installed applications the same way the KDE and GNOME
desktops do, from the :file:`.desktop` files and the :file:`mimeapps.list`
files on your system, and shows them as a grid of icons, with the applications
recommended for the type of file first.

Simply run it as::

    kitten choose-app some-file.pdf https://example.com

When you are asked to choose, type a few letters from the name of the application and once it becomes the
selected one, press :kbd:`Enter`. The letters do not need to be adjacent, as
long as they are in the same order as in the name, so :kbd:`lbw` matches
:guilabel:`LibreOffice Writer`. Applications also match their descriptions,
keywords and the names of their programs. You can also use the arrow keys or
the mouse to select an application. Use :option:`--ask <kitty +kitten choose_app --ask>`
to always be asked, like the :guilabel:`Open with` menu of file managers.

.. note:: Application icons are displayed using the :doc:`graphics protocol
   </graphics-protocol>`. To display icons in the SVG format, used by most
   icon themes, either :program:`rsvg-convert` from `librsvg
   <https://gitlab.gnome.org/GNOME/librsvg>`__ or `ImageMagick
   <https://imagemagick.org>`__ must be installed. Rendered icons are cached
   in the kitty cache directory. The icon theme configured for your desktop is
   used, automatically switching to its dark or light variant, if any,
   depending on the background color of the terminal.


macOS
--------

The kitten works on macOS as well, as a nicer, interactive, version of the
:program:`open` command, though it is not a drop-in replacement for it, as it
does not support the various options of :program:`open`. Applications are found
in the standard :file:`Applications` folders and the applications for a type of
file are the ones Finder shows in its :guilabel:`Open With` menu, with the
default one first. Since almost every type of file has a default application on
macOS, you are asked to choose, unless you have remembered an application or
have an :opt:`open_with <kitten-choose_app.open_with>` rule for the type of file. To use the default
application without asking instead, turn on :opt:`use_system_defaults <kitten-choose_app.use_system_defaults>`.

Applications are identified by their bundle identifiers, for example,
:code:`com.apple.Preview`, so use :code:`desktop:com.apple.Preview` to refer
to an application in :opt:`open_with <kitten-choose_app.open_with>`. Types of
files that have no MIME type use MIME types of the form
:code:`x-apple-uti/com.apple.rtfd`. Use :code:`--action=list` to see the
identifiers of the applications and the MIME type for a file.


Remembering choices
----------------------

Every application you choose is remembered and shown first the next time you
open the same type of file. If you also want the application to be used for
that type of file in future, without asking, turn on the :guilabel:`remember`
option, by clicking on it or pressing :sc:`kitten-choose_app.toggle_remember`,
before choosing. You can make this the default with
:opt:`remember_choice <kitten-choose_app.remember_choice>`. To forget the application
remembered for a type of file, use::

    kitten choose-app --action=forget some-file.pdf


Using a command instead of an application
---------------------------------------------

To open files with a program that does not have a :file:`.desktop` file, or
with particular command line arguments, press :sc:`kitten-choose_app.use_command` or click :guilabel:`command`. Any text already typed
in the search box is used as the start of the command. Press :kbd:`Tab` to
complete program names and file paths and the :kbd:`Up` and :kbd:`Down` keys to
use previously typed commands. A preview of the exact command line that will be
run is shown below. In the command, :code:`%f` is replaced by the path to a single file,
:code:`%F` by the paths to all the files and :code:`%u` and :code:`%U` by URLs. If none
of them are present, the path to the file is added at the end. Turn on
:guilabel:`run in terminal` with :sc:`kitten-choose_app.toggle_terminal`
for terminal programs, such as editors.


How files are opened
------------------------------------------------

Each file is opened with, in order of preference:

#. The application specified by the first matching :opt:`open_with <kitten-choose_app.open_with>` in :file:`choose-app.conf`
#. The application you chose to remember for its type of file
#. The default application for its type of file configured for your desktop in :file:`mimeapps.list`, unless
   :opt:`use_system_defaults <kitten-choose_app.use_system_defaults>` is turned off

If none of these exist, you are asked to choose, once for every type of file.
When run in a terminal, the kitten asks in that terminal, otherwise it asks in
an overlay :doc:`panel </kittens/panel>` on top of all other windows, which
requires your compositor to support panels. This can be controlled with :option:`--ask-in <kitty +kitten choose_app --ask-in>`.
Applications are run in the
background and terminal programs are run in a new kitty window, which can be
changed with :opt:`terminal <kitten-choose_app.terminal>`. Applications whose
:file:`.desktop` file says they can be started via D-Bus are started that
way, falling back to running them normally if that fails. The exit codes are the same as
those of :program:`xdg-open`.

To have all programs that use :program:`xdg-open` use this kitten instead,
create an executable file named :file:`xdg-open` in a directory that is before
:file:`/usr/bin` in your :envvar:`PATH`, for example :file:`~/.local/bin/xdg-open`,
with the contents:

.. code-block:: sh

    #!/bin/sh
    exec kitten choose-app "$@"

Note that some programs, particularly sandboxed ones such as Flatpaks, instead
use the OpenURI desktop portal to open files, which shows a chooser
provided by your desktop. Similarly, some programs use the GIO library from GNOME
which opens files with the default applications from :file:`mimeapps.list` directly.


Specifying the programs to open files with
----------------------------------------------

You can specify the programs used to open different types of files and URLs in
:file:`choose-app.conf`, using :opt:`open_with <kitten-choose_app.open_with>`. For example:

.. code-block:: conf

    # Open images with imv, all of them in a single instance
    open_with mime:image/* imv %F
    # Open PDF and EPUB files with zathura
    open_with ext:pdf,epub zathura %f
    # Open all files in the notes folder with neovim, in a terminal
    open_with glob:~/notes/** terminal:nvim %F
    # Open web links with an installed application
    open_with scheme:https,http desktop:firefox

To see which applications can open a file, and which one would be used to open
it, without asking, use::

    kitten choose-app --action=list some-file.pdf


Choosing an application without opening files
------------------------------------------------

To only choose an application, for use in scripts and other programs, use::

    kitten choose-app --action=print some-file.pdf

This always asks you to choose and prints the chosen application to
:file:`STDOUT`, instead of opening the file, see :option:`--output-format <kitty +kitten choose_app --output-format>`.


Configuration
------------------------

You can configure various aspects of the kitten's operation by creating a
:file:`choose-app.conf` in your :ref:`kitty config folder <confloc>`.
See below for the supported configuration directives.


.. include:: /generated/conf-kitten-choose_app.rst


.. include:: /generated/cli-kitten-choose_app.rst
