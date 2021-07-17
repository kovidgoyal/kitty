Glossary
=========

.. glossary::

   os_window
     kitty has two kinds of windows. Operating System windows, refered to as :term:`OS
     Window <os_window>`, and *kitty windows*. An OS Window consists of one or more kitty
     :term:`tabs <tab>`. Each tab in turn consists of one or more *kitty
     windows* organized in a :term:`layout`.

   tab
     A *tab* refers to a group of :term:`kitty windows <window>`, organized in
     a :term:`layout`. Every :term:`OS Window <os_window>` contains one or more tabs.

   layout
     A *layout* is a system of organizing :term:`kitty windows <window>` in
     groups inside a tab. The layout automatically maintains the size and
     position of the windows, think of a layout as a tiling window manager for
     the terminal. See :doc:`layouts` for details.

   window
     kitty has two kinds of windows. Operating System windows, refered to as :term:`OS
     Window <os_window>`, and *kitty windows*. An OS Window consists of one or more kitty
     :term:`tabs <tab>`. Each tab in turn consists of one or more *kitty
     windows* organized in a :term:`layout`.

   overlay
      An *overlay window* is a :term:`kitty window <window>` that is placed on
      top of an existing kitty window, entirely covering it. Overlays are used
      throught kitty, for example, to display the :ref:`the scrollback buffer <scrollback>`,
      to display :doc:`hints </kittens/hints>`, for :doc:`unicode input
      </kittens/unicode-input>` etc.
