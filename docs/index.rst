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


To get started see :doc:`quickstart`.

.. only:: dirhtml

   .. include:: intro_vid.rst
