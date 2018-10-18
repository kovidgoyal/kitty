Building kitty from source
==============================

.. image:: https://travis-ci.org/kovidgoyal/kitty.svg?branch=master
  :alt: Build status
  :target: https://travis-ci.org/kovidgoyal/kitty


|kitty| is designed to run from source, for easy hackability. Make sure
the following dependencies are installed first.

Dependencies
----------------

Run-time dependencies:

    * python >= 3.5
    * harfbuzz >= 1.5.0
    * zlib
    * libpng
    * freetype (not needed on macOS)
    * fontconfig (not needed on macOS)
    * ImageMagick (optional, needed to use the ``kitty icat`` tool to display images in the terminal)
    * pygments (optional, need for syntax highlighting in ``kitty +kitten diff``)

Build-time dependencies:

    * gcc or clang
    * pkg-config
    * For building on Linux in addition to the above dependencies you might also need to install the ``-dev`` packages for:
      ``libdbus-1-dev``, ``libxcursor-dev``, ``libxrandr-dev``, ``libxi-dev``, ``libxinerama-dev``, ``libgl1-mesa-dev``, ``libxkbcommon-x11-dev``, ``libfontconfig-dev`` and ``libpython-dev``.
      if they are not already installed by your distro.

Install and run from source
------------------------------

.. code-block:: sh

    git clone https://github.com/kovidgoyal/kitty && cd kitty

Now build the native code parts of |kitty| with the following command::

    make

You can run |kitty|, as::

    python3 .

If that works, you can create a script to launch |kitty|:

.. code-block:: sh

    #!/usr/bin/env python3
    import runpy
    runpy.run_path('/path/to/kitty/dir', run_name='__main__')

And place it in :file:`~/bin` or :file:`/usr/bin` so that you can run |kitty| using
just ``kitty``.


Building kitty.app on macOS from source
-------------------------------------------

Install `imagemagick`, `optipng` and `librsvg` using `brew` or similar (needed
for the logo generation step). And run::

    make app

This :file:`kitty.app` unlike the released one does not include its own copy of
python and the other dependencies. So if you ever un-install/upgrade those dependencies
you might have to rebuild the app.

Note that the released :file:`kitty.dmg` includes all dependencies, unlike the
:file:`kitty.app` built above and is built automatically by using the :file:`kitty` branch of
`build-calibre <https://github.com/kovidgoyal/build-calibre>`_ however, that
is designed to run on Linux and is not for the faint of heart.


Note for Linux/macOS packagers
----------------------------------

The released |kitty| source code is available as a `tarball`_ from
`the GitHub releases page <https://github.com/kovidgoyal/kitty/releases>`_.

While |kitty| does use python, it is not a traditional python package, so please
do not install it in site-packages.
Instead run::

    python3 setup.py linux-package

This will install |kitty| into the directory :file:`linux-package`. You can run |kitty|
with :file:`linux-package/bin/kitty`.  All the files needed to run kitty will be in
:file:`linux-package/lib/kitty`. The terminfo file will be installed into
:file:`linux-package/share/terminfo`. Simply copy these files into :file:`/usr` to install
|kitty|. In other words, :file:`linux-package` is the staging area into which |kitty| is
installed. You can choose a different staging area, by passing the ``--prefix``
argument to :file:`setup.py`.

You should probably split |kitty| into two packages, :file:`kitty-terminfo` that
installs the terminfo file and :file:`kitty` that installs the main program.
This allows users to install the terminfo file on servers into which they ssh,
without needing to install all of |kitty|.

.. note::
        You need a couple of extra dependencies to build linux-package.
        :file:`tic` to compile terminfo files, usually found in the
        development package of :file:`ncurses`. Also, if you are building from
        a git checkout instead of the released source code tarball, you will
        need :file:`sphinx-build` from the `Sphinx documentation generator
        <http://www.sphinx-doc.org/>`_.

This applies to creating packages for |kitty| for macOS package managers such as
brew or MacPorts as well.
