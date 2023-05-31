kitty
==========================================================

*The fast, feature-rich, GPU based terminal emulator*

.. toctree::
    :hidden:

    quickstart
    overview
    faq
    support
    performance
    changelog
    integrations
    protocol-extensions
    press-mentions


.. tab:: Fast

   * Offloads rendering to the GPU for :doc:`lower system load <performance>`
   * Uses threaded rendering for :iss:`absolutely minimal latency <2701#issuecomment-636497270>`
   * Performance tradeoffs can be :ref:`tuned <conf-kitty-performance>`

.. tab:: Capable

   * Graphics, with :doc:`images and animations <graphics-protocol>`
   * Ligatures and emoji, with :opt:`per glyph font substitution <symbol_map>`
   * :term:`Hyperlinks<hyperlinks>`, with :doc:`configurable actions <open_actions>`

.. tab:: Scriptable

   * Control from :doc:`scripts or the shell <remote-control>`
   * Extend with :ref:`kittens <kittens>` using the Python language
   * Use :ref:`startup sessions <sessions>` to specify working environments

.. tab:: Composable

   * Programmable tabs, :ref:`splits <splits_layout>` and multiple :doc:`layouts <layouts>` to manage windows
   * Browse the :ref:`entire history <scrollback>` or the :sc:`output from the last command <show_last_command_output>`
     comfortably in pagers and editors
   * Edit or download :doc:`remote files <kittens/remote_file>` in an existing SSH session

.. tab:: Cross-platform

   * Linux
   * macOS
   * Various BSDs

.. tab:: Innovative

   Pioneered various extensions to move the entire terminal ecosystem forward

   * :doc:`graphics-protocol`
   * :doc:`keyboard-protocol`
   * Lots more in :doc:`protocol-extensions`


.. only:: dirhtml

    .. raw:: html

        <video controls width="640" height="360" poster="_static/poster.png">
            <source src="https://download.calibre-ebook.com/videos/kitty.mp4" type="video/mp4">
            <source src="https://download.calibre-ebook.com/videos/kitty.webm" type="video/webm">
        </video>

    .. rst-class:: caption caption-text

        Watch kitty in action!


To get started see :doc:`quickstart`.

.. only:: dirhtml

    .. raw:: html

        <div id="timestamps-for-intro-video" class="timestamp-list">

    Timestamps for the above video:

    00:00
        Intro
    00:39
        Pager: View command output in same window: :kbd:`Ctrl+Shift+g`
    01:43
        Pager: View command output in a separate window
    02:14
        Pager: Uses shell integration in kitty
    02:27
        Tab text: The output of cwd and last cmd
    03:03
        Open files from ls output with mouse: :kbd:`Ctrl+Shift+Right-click`
    04:04
        Open files from ls output with keyboard: :kbd:`Ctrl+Shift+P>y`
    04:26
        Open files on click: ``ls --hyperlink=auto``
    05:03
        Open files on click: Filetype settings in open-actions.conf
    05:45
        hyperlinked-grep kitten: Open grep output in editor
    07:18
        Remote-file kitten: View remote files locally
    08:31
        Remote-file kitten: Edit remote files locally
    10:01
        icat kitten: View images directly
    10:36
        icat kitten: Download & display image/gif from internet
    11:03
        Kitty Graphics Protocol: Live image preview in ranger
    11:25
        icat kitten: Display image from remote server
    12:04
        unicode-input kitten: Emojis in terminal
    12:54
        Windows: Intro
    13:36
        Windows: Switch focus: :kbd:`Ctrl+Shift+win_nr`
    13:48
        Windows: Visual selection: :kbd:`Ctrl+Shift+F7`
    13:58
        Windows: Simultaneous input
    14:15
        Interactive Kitty Shell: :kbd:`Ctrl+Shift+Esc`
    14:36
        Broadcast text: ``launch --allow-remote-control kitty +kitten broadcast``
    15:18
        Kitty Remote Control Protocol
    15:52
        Interactive Kitty Shell: Help
    16:34
        Choose theme interactively: ``kitty +kitten themes -h``
    17:23
        Choose theme by name: ``kitty +kitten themes [options] [theme_name]``

    .. raw:: html

        </div>
