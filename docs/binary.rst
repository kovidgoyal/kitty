Install datty
========================

Binary install
----------------

.. highlight:: sh

You can install pre-built binaries of |datty| if you are on macOS or Linux using
the following simple command:

.. code-block:: sh

    _datty_install_cmd


The binaries will be installed in the standard location for your OS,
:file:`/Applications/datty.app` on macOS and :file:`~/.local/datty.app` on
Linux. The installer only touches files in that directory. To update datty,
simply re-run the command.

.. warning::
   **Do not** copy the datty binary out of the installation folder. If you want
   to add it to your :envvar:`PATH`, create a symlink in :file:`~/.local/bin` or
   :file:`/usr/bin` or wherever. You should create a symlink for the :file:`daddy`
   binary as well. Whichever folder you choose to create the symlink in should
   be in the **systemwide** PATH, a folder added to the PATH in your shell rc
   files will not work when running datty from your desktop environment.


Manually installing
---------------------

If something goes wrong or you simply do not want to run the installer, you can
manually download and install |datty| from the `GitHub releases page
<https://github.com/kovidgoyal/datty/releases>`__. If you are on macOS, download
the :file:`.dmg` and install as normal. If you are on Linux, download the
tarball and extract it into a directory. The |datty| executable will be in the
:file:`bin` sub-directory.


Desktop integration on Linux
--------------------------------

If you want the datty icon to appear in the taskbar and an entry for it to be
present in the menus, you will need to install the :file:`datty.desktop` file.
The details of the following procedure may need to be adjusted for your
particular desktop, but it should work for most major desktop environments.

.. code-block:: sh

    # Create symbolic links to add datty and daddy to PATH (assuming ~/.local/bin is in
    # your system-wide PATH)
    ln -sf ~/.local/datty.app/bin/datty ~/.local/datty.app/bin/daddy ~/.local/bin/
    # Place the datty.desktop file somewhere it can be found by the OS
    cp ~/.local/datty.app/share/applications/datty.desktop ~/.local/share/applications/
    # If you want to open text files and images in datty via your file manager also add the datty-open.desktop file
    cp ~/.local/datty.app/share/applications/datty-open.desktop ~/.local/share/applications/
    # Update the paths to the datty and its icon in the datty desktop file(s)
    sed -i "s|Icon=datty|Icon=$(readlink -f ~)/.local/datty.app/share/icons/hicolor/256x256/apps/datty.png|g" ~/.local/share/applications/datty*.desktop
    sed -i "s|Exec=datty|Exec=$(readlink -f ~)/.local/datty.app/bin/datty|g" ~/.local/share/applications/datty*.desktop
    # Make xdg-terminal-exec (and hence desktop environments that support it use datty)
    echo 'datty.desktop' > ~/.config/xdg-terminals.list

.. note::
    In :file:`datty-open.desktop`, datty is registered to handle some supported
    MIME types. This will cause datty to take precedence on some systems where
    the default apps are not explicitly set. For example, if you expect to use
    other GUI file managers to open dir paths when using commands such as
    :program:`xdg-open`, you should configure the default opener for the MIME
    type ``inode/directory``::

        xdg-mime default org.kde.dolphin.desktop inode/directory

.. note::
    If you use the venerable `stow <https://www.gnu.org/software/stow/>`__
    command to manage your manual installations, the following takes care of the
    above for you (use with :code:`dest=~/.local/stow`)::

        cd ~/.local/stow
        stow -v datty.app


Customizing the installation
--------------------------------

.. _nightly:

* You can install the latest nightly datty build with ``installer``:

  .. code-block:: sh

     _datty_install_cmd \
         installer=nightly

  Nightly builds show the date and hash of the commit they were built from in
  the output of :option:`datty --version`.

  If you want to install it in parallel to the released datty specify a
  different install locations with ``dest``:

  .. code-block:: sh

     _datty_install_cmd \
         installer=nightly dest=/some/other/location

* You can specify a specific version to install, with:

  .. code-block:: sh

     _datty_install_cmd \
         installer=version-0.35.2

* You can tell the installer not to launch |datty| after installing it with
  ``launch=n``:

  .. code-block:: sh

     _datty_install_cmd \
         launch=n

* You can use a previously downloaded dmg/tarball, with ``installer``:

  .. code-block:: sh

     _datty_install_cmd \
         installer=/path/to/dmg or tarball


Uninstalling
----------------

All the installer does is copy the datty files into the install directory. To
uninstall, simply delete that directory.


Building from source
------------------------

|datty| is easy to build from source, follow the :doc:`instructions <build>`.
