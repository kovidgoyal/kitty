Tabs and Windows
-------------------

|kitty| is capable of running multiple programs organized into tabs and windows.
The top level of organization is the :term:`OS window <os_window>`. Each OS
window consists of one or more :term:`tabs <tab>`. Each tab consists of one or more
:term:`kitty windows <window>`. The kitty windows can be arranged in multiple
different :term:`layouts <layout>`, like windows are organized in a tiling
window manager. The keyboard controls (which are :ref:`all customizable
<conf-kitty-shortcuts>`) for tabs and windows are:

Scrolling
~~~~~~~~~~~~~~

=========================   =======================
Action                      Shortcut
=========================   =======================
Line up                     :sc:`scroll_line_up` (also :kbd:`⌥+⌘+⇞` and :kbd:`⌘+↑` on macOS)
Line down                   :sc:`scroll_line_down` (also :kbd:`⌥+⌘+⇟` and :kbd:`⌘+↓` on macOS)
Page up                     :sc:`scroll_page_up` (also :kbd:`⌘+⇞` on macOS)
Page down                   :sc:`scroll_page_down` (also :kbd:`⌘+⇟` on macOS)
Top                         :sc:`scroll_home` (also :kbd:`⌘+↖` on macOS)
Bottom                      :sc:`scroll_end` (also :kbd:`⌘+↘` on macOS)
Previous shell prompt       :sc:`scroll_to_previous_prompt` (see :ref:`shell_integration`)
Next shell prompt           :sc:`scroll_to_next_prompt` (see :ref:`shell_integration`)
Browse scrollback in less   :sc:`show_scrollback`
Browse last cmd output      :sc:`show_last_command_output` (see :ref:`shell_integration`)
=========================   =======================

The scroll actions only take effect when the terminal is in the main screen.
When the alternate screen is active (for example when using a full screen
program like an editor) the key events are instead passed to program running in the
terminal.

Tabs
~~~~~~~~~~~

========================    =======================
Action                      Shortcut
========================    =======================
New tab                     :sc:`new_tab` (also :kbd:`⌘+t` on macOS)
Close tab                   :sc:`close_tab` (also :kbd:`⌘+w` on macOS)
Next tab                    :sc:`next_tab` (also :kbd:`⇧+⌃+⇥` and :kbd:`⇧+⌘+]` on macOS)
Previous tab                :sc:`previous_tab` (also :kbd:`⇧+⌃+⇥` and :kbd:`⇧+⌘+[` on macOS)
Next layout                 :sc:`next_layout`
Move tab forward            :sc:`move_tab_forward`
Move tab backward           :sc:`move_tab_backward`
Set tab title               :sc:`set_tab_title` (also :kbd:`⇧+⌘+i` on macOS)
========================    =======================


Windows
~~~~~~~~~~~~~~~~~~

========================    =======================
Action                      Shortcut
========================    =======================
New window                  :sc:`new_window` (also :kbd:`⌘+↩` on macOS)
New OS window               :sc:`new_os_window` (also :kbd:`⌘+n` on macOS)
Close window                :sc:`close_window` (also :kbd:`⇧+⌘+d` on macOS)
Resize window               :sc:`start_resizing_window` (also :kbd:`⌘+r` on macOS)
Next window                 :sc:`next_window`
Previous window             :sc:`previous_window`
Move window forward         :sc:`move_window_forward`
Move window backward        :sc:`move_window_backward`
Move window to top          :sc:`move_window_to_top`
Visually focus window       :sc:`focus_visible_window`
Visually swap window        :sc:`swap_with_window`
Focus specific window       :sc:`first_window`, :sc:`second_window` ... :sc:`tenth_window`
                            (also :kbd:`⌘+1`, :kbd:`⌘+2` ... :kbd:`⌘+9` on macOS)
                            (clockwise from the top-left)
========================    =======================

Additionally, you can define shortcuts in :file:`kitty.conf` to focus
neighboring windows and move windows around (similar to window movement in
:program:`vim`)::

   map ctrl+left neighboring_window left
   map shift+left move_window right
   map ctrl+down neighboring_window down
   map shift+down move_window up
   ...

You can also define a shortcut to switch to the previously active window::

   map ctrl+p nth_window -1

:ac:`nth_window` will focus the nth window for positive numbers (starting from
zero) and the previously active windows for negative numbers.

To switch to the nth OS window, you can define :ac:`nth_os_window`. Only
positive numbers are accepted, starting from one.

.. _detach_window:

You can define shortcuts to detach the current window and move it to another tab
or another OS window::

    # moves the window into a new OS window
    map ctrl+f2 detach_window
    # moves the window into a new tab
    map ctrl+f3 detach_window new-tab
    # moves the window into the previously active tab
    map ctrl+f3 detach_window tab-prev
    # moves the window into the tab at the left of the active tab
    map ctrl+f3 detach_window tab-left
    # moves the window into a new tab created to the left of the active tab
    map ctrl+f3 detach_window new-tab-left
    # asks which tab to move the window into
    map ctrl+f4 detach_window ask

Similarly, you can detach the current tab, with::

    # moves the tab into a new OS window
    map ctrl+f2 detach_tab
    # asks which OS Window to move the tab into
    map ctrl+f4 detach_tab ask

Finally, you can define a shortcut to close all windows in a tab other than the
currently active window::

    map f9 close_other_windows_in_tab


Other keyboard shortcuts
----------------------------------

The full list of actions that can be mapped to key presses is available
:doc:`here </actions>`. To learn how to do more sophisticated keyboard
mappings, such as modal mappings, per application mappings, etc. see
:doc:`mapping`.

==================================  =======================
Action                              Shortcut
==================================  =======================
Show this help                      :sc:`show_kitty_doc`
Copy to clipboard                   :sc:`copy_to_clipboard` (also :kbd:`⌘+c` on macOS)
Paste from clipboard                :sc:`paste_from_clipboard` (also :kbd:`⌘+v` on macOS)
Paste from selection                :sc:`paste_from_selection`
Pass selection to program           :sc:`pass_selection_to_program`
Increase font size                  :sc:`increase_font_size` (also :kbd:`⌘++` on macOS)
Decrease font size                  :sc:`decrease_font_size` (also :kbd:`⌘+-` on macOS)
Restore font size                   :sc:`reset_font_size` (also :kbd:`⌘+0` on macOS)
Toggle fullscreen                   :sc:`toggle_fullscreen` (also :kbd:`⌃+⌘+f` on macOS)
Toggle maximized                    :sc:`toggle_maximized`
Input Unicode character             :sc:`input_unicode_character` (also :kbd:`⌃+⌘+space` on macOS)
Open URL in web browser             :sc:`open_url`
Reset the terminal                  :sc:`reset_terminal` (also :kbd:`⌥+⌘+r` on macOS)
Edit :file:`kitty.conf`             :sc:`edit_config_file` (also :kbd:`⌘+,` on macOS)
Reload :file:`kitty.conf`           :sc:`reload_config_file` (also :kbd:`⌃+⌘+,` on macOS)
Debug :file:`kitty.conf`            :sc:`debug_config` (also :kbd:`⌥+⌘+,` on macOS)
Open a |kitty| shell                :sc:`kitty_shell`
Increase background opacity         :sc:`increase_background_opacity`
Decrease background opacity         :sc:`decrease_background_opacity`
Full background opacity             :sc:`full_background_opacity`
Reset background opacity            :sc:`reset_background_opacity`
==================================  =======================
