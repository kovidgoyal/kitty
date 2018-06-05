:tocdepth: 2

Configuring kitty
===============================

.. highlight:: ini

|kitty| is highly customizable, everything from keyboard shortcuts, to painting
frames-per-second. See below for an overview of all customization
possibilities.

You can open the config file within kitty by pressing :sc:`edit_config_file`.
You can also display the current configuration by running ``kitty
--debug-config``.

.. _confloc:

|kitty| looks for a config file in the OS config directories (usually
:file:`~/.config/kitty/kitty.conf`) but you can pass a specific path via the
:option:`kitty --config` option or use the ``KITTY_CONFIG_DIRECTORY``
environment variable. See the :option:`kitty --config` option for full details.

You can include secondary config files via the :code:`include` directive.  If
you use a relative path for include, it is resolved with respect to the
location of the current config file. Note that environment variables are
expanded, so :code:`${USER}.conf` becomes :file:`name.conf` if
:code:`USER=name`.  For example::

     include other.conf


.. include:: /generated/conf-kitty.rst
