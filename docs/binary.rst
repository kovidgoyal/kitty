kitty - Binary install
========================

.. |ins| replace:: curl -L :literal:`https://sw.kovidgoyal.net/kitty/installer.sh` | sh /dev/stdin

.. highlight:: sh

You can install pre-built binaries of |kitty| if you are on macOS or Linux using
the following simple command:

.. parsed-literal::
    :class: pre

    |ins|


The binaries will be installed in the standard location for your OS,
:file:`/Applications/kitty.app` on macOS and :file:`~/.local/kitty.app` on
Linux. The installer only touches files in that directory. To update kitty,
simply re-run the command.


Manually installing
---------------------

If something goes wrong or you simply do not want to run the installer, you can
manually download and install |kitty| from the `GitHub releases page
<https://github.com/kovidgoyal/kitty/releases>`_. If you are on macOS, download
the :file:`.dmg` and install as normal. If you are on Linux, download the tarball
and extract it into a directory. The |kitty| executable will be in the
:file:`bin` sub-directory.

Desktop integration on Linux
--------------------------------

If you want the kitty icon to appear in the taskbar and an entry for it to be
present in the menus, you will need to install the :file:`kitty.desktop` file.
The details of the following procedure may need to be adjusted for your
particular desktop, but it should work for most major desktop environments.

.. code-block:: sh

    # Create a symbolic link to add kitty to PATH (assuming ~/.local/bin is in
    # your PATH)
    ln -s ~/.local/kitty.app/bin/kitty ~/.local/bin/
    # Place the kitty.desktop file somewhere it can be found by the OS
    cp ~/.local/kitty.app/share/applications/kitty.desktop ~/.local/share/applications
    # Update the path to the kitty icon in the kitty.desktop file
    sed -i "s/Icon\=kitty/Icon\=\/home\/$USER\/.local\/kitty.app\/share\/icons\/hicolor\/256x256\/apps\/kitty.png/g" ~/.local/share/applications/kitty.desktop



Customizing the installation
--------------------------------

* You can specify a different install location, with ``dest``:

  .. parsed-literal::
     :class: pre

     |ins| \\
         dest=/some/other/location

* You can tell the installer not to launch |kitty| after installing it with
  ``launch=n``:

  .. parsed-literal::
     :class: pre

     |ins| \\
         launch=n

* You can use a previously downloaded dmg/tarball, with ``installer``:

  .. parsed-literal::
     :class: pre

     |ins| \\
         installer=/path/to/dmg or tarball

Uninstalling
----------------

All the installer does is copy the kitty files into the install directory. To
uninstall, simply delete that directory.


Building from source
------------------------

|kitty| is easy to build from source, follow the :doc:`instructions <build>`.
