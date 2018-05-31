Configuring kitty
===============================

|kitty| is highly customizable, everything from keyboard shortcuts, to painting
frames-per-second. See the heavily commented default config file below for an
overview of all customization possibilities.

You can open the config file within kitty by pressing |sc_edit_config_file|.
You can also display the current configuration by running ``kitty
--debug-config``.



.. literalinclude:: ../kitty/kitty.conf
    :language: ini


.. _confloc:

|kitty| looks for a config file in the OS config directories (usually
:file:`~/.config/kitty/kitty.conf` and additionally
:file:`~/Library/Preferences/kitty/kitty.conf` on macOS) but you can pass a
specific path via the :option:`kitty --config` option or use the ``KITTY_CONFIG_DIRECTORY``
environment variable. See the :option:`kitty --config` option 
for full details. 
