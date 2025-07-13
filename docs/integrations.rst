:tocdepth: 2

Integrations with other tools
================================

kitty provides extremely powerful interfaces such as :doc:`remote-control` and
:doc:`kittens/custom` and :doc:`kittens/icat` that allow it to be integrated
with other tools seamlessly.


Image and document viewers
----------------------------

Powered by kitty's :doc:`graphics-protocol` there exist many tools for viewing
images and other types of documents directly in your terminal, even over SSH.

.. _tool_termpdf:

`termpdf.py <https://github.com/dsanson/termpdf.py>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A terminal PDF/DJVU/CBR viewer

.. _tool_tdf:

`tdf <https://github.com/itsjunetime/tdf>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A terminal PDF viewer

.. _tool_fancy_cat:

`fancy-cat <https://github.com/freref/fancy-cat>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A terminal PDF viewer

.. _tool_meowpdf:

`meowpdf <https://github.com/monoamine11231/meowpdf>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A terminal PDF viewer with GUI-like usage and Vim-like keybindings written in Rust

.. _tool_mcat:

`mcat <https://github.com/Skardyy/mcat>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Display various types of files nicely formatted with images in the terminal

.. _tool_ranger:

`ranger <https://github.com/ranger/ranger>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A terminal file manager, with previews of file contents powered by kitty's
graphics protocol.

.. _tool_nnn:

`nnn <https://github.com/jarun/nnn/>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Another terminal file manager, with previews of file contents powered by kitty's
graphics protocol.

.. _tool_yazi:

`Yazi <https://github.com/sxyazi/yazi>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Blazing fast terminal file manager, with built-in kitty graphics protocol support
(implemented both Classic protocol and Unicode placeholders).

.. _tool_clifm:

`clifm <https://github.com/leo-arch/clifm>`__
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
The shell-like, command line terminal file manager, uses the kitty graphics and
keyboard protocols.

.. _tool_hunter:

`hunter <https://github.com/rabite0/hunter>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Another terminal file manager, with previews of file contents powered by kitty's
graphics protocol.

.. _tool_presentterm:

`presenterm <https://github.com/mfontanini/presenterm>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Show markdown based slides with images in your terminal, powered by the
kitty graphics protocol.

.. _tool_term_image:

`term-image <https://github.com/AnonymouX47/term-image>`__
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Tool to browse images in a terminal using kitty's graphics protocol.

.. _tool_koneko:

`koneko <https://github.com/twenty5151/koneko>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Browse images from the pixiv artist community directly in kitty.

.. _tool_viu:

`viu <https://github.com/atanunq/viu>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
View images in the terminal, similar to kitty's icat.

.. _tool_nb:


`nb <https://github.com/xwmx/nb>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Command line and local web note-taking, bookmarking, archiving, and knowledge
base application that uses kitty's graphics protocol for images.

.. _tool_w3m:

`w3m <https://github.com/tats/w3m>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A text mode WWW browser that supports kitty's graphics protocol to display
images.

.. _tool_awrit:

`awrit <https://github.com/chase/awrit>`__
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A full Chromium based web browser running in the terminal using kitty's
graphics protocol.

.. _tool_chawan:

`chawan <https://sr.ht/~bptato/chawan/>`__
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A text mode WWW browser that supports kitty's graphics protocol to display
images.

.. _tool_mpv:

`mpv <https://github.com/mpv-player/mpv/commit/874e28f4a41a916bb567a882063dd2589e9234e1>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A video player that can play videos in the terminal.

.. code-block:: sh

    mpv --profile=sw-fast --vo=kitty --vo-kitty-use-shm=yes --really-quiet video.mkv

.. _tool_timg:

`timg <https://github.com/hzeller/timg>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A terminal image and video viewer, that displays static and animated images or
plays videos. Fast multi-threaded loading, JPEG exif rotation, grid view and
connecting to the webcam make it a versatile terminal utility.


System and data visualisation tools
---------------------------------------

.. _tool_neofetch:

`neofetch <https://github.com/dylanaraps/neofetch>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A command line system information tool that shows images using kitty's graphics
protocol

.. _tool_matplotlib:

matplotlib
^^^^^^^^^^^^^^

There exist multiple backends for matplotlib to draw images directly in kitty.

* `matplotlib-backend-kitty <https://github.com/jktr/matplotlib-backend-kitty>`__
* `kitcat <https://github.com/mil-ad/kitcat>`__

.. _tool_KittyTerminalImage:

`KittyTerminalImages.jl <https://github.com/simonschoelly/KittyTerminalImages.jl>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Show images from Julia directly in kitty

.. _tool_euporie:

`euporie <https://github.com/joouha/euporie>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A text-based user interface for running and editing Jupyter notebooks, powered
by kitty's graphics protocol for displaying plots

.. _tool_gnuplot:

`gnuplot <http://www.gnuplot.info/>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A graphing and data visualization tool that can be made to display its output in
kitty with the following bash snippet:

.. code-block:: sh

    function iplot {
        cat <<EOF | gnuplot
        set terminal pngcairo enhanced font 'Fira Sans,10'
        set autoscale
        set samples 1000
        set output '|kitten icat --stdin yes'
        set object 1 rectangle from screen 0,0 to screen 1,1 fillcolor rgb"#fdf6e3" behind
        plot $@
        set output '/dev/null'
    EOF
    }

Add this to bashrc and then to plot a function, simply do:

.. code-block:: sh

    iplot 'sin(x*3)*exp(x*.2)'

.. _tool_k-nine:

`k-nine <https://github.com/talwrii/kitty-plotnine>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A wrapper around the :code:`plotnine` library which lets you plot data from the command-line with bash one-liners.

.. tool_tgutui:

`tgutui <https://github.com/tgu-ltd/tgutui>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A Terminal Operating Test hardware equipment

.. tool_onefetch:

`onefetch <https://github.com/o2sh/onefetch>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A tool to fetch information about your git repositories

.. tool_patat:

`patat <https://github.com/jaspervdj/patat>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Terminal based presentations using pandoc and kitty's image protocol for
images

.. tool_wttr:

`wttr.in <https://github.com/chubin/wttr.in>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A tool to display weather information in your terminal with curl

.. tool_wl_clipboard:

`wl-clipboard-manager <https://github.com/maximbaz/wl-clipboard-manager>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
View and manage the system clipboard under Wayland in your kitty terminal

.. tool_nemu:

`NEMU <https://github.com/nemuTUI/nemu>`__
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
TUI for QEMU used to manage virtual machines, can display the Virtual Machine
in the terminal using the kitty graphics protocol.

Editor integration
-----------------------

|kitty| can be integrated into many different terminal based text editors to add
features such a split windows, previews, REPLs etc.

.. tool_kakoune:

`kakoune <https://kakoune.org/>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Integrates with kitty to use native kitty windows for its windows/panels and
REPLs.

.. tool_vim_slime:

`vim-slime <https://github.com/jpalardy/vim-slime#kitty>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Uses kitty remote control for a Lisp REPL.

.. tool_vim_kitty_navigator:

`vim-kitty-navigator <https://github.com/knubie/vim-kitty-navigator>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Allows you to navigate seamlessly between vim and kitty splits using a
consistent set of hotkeys.

.. tool_vim_test:

`vim-test <https://github.com/vim-test/vim-test>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Allows easily running tests in a terminal window

.. tool_nvim_image_viewers:

Various image viewing plugins for editors
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
* `snacks.nvim <https://github.com/folke/snacks.nvim>`__ - Enables seamless inline images in various file formats within nvim
* `image.nvim <https://github.com/3rd/image.nvim>`_ - Bringing images to neovim
* `image_preview.nvim <https://github.com/adelarsq/image_preview.nvim/>`_ - Image preview for neovim
* `hologram.nvim <https://github.com/edluffy/hologram.nvim>`_  - view images inside nvim

Scrollback manipulation
-------------------------

.. tool_kitty_scrollback_nvim:

`kitty-scrollback.nvim <https://github.com/mikesmithgh/kitty-scrollback.nvim>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Browse the scrollback buffer with Neovim, with simple key actions for efficient
copy/paste and even execution of commands.

.. tool_kitty_search:

`kitty-search <https://github.com/trygveaa/kitty-kitten-search>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Live incremental search of the scrollback buffer.

.. tool_kitty_grab:

`kitty-grab <https://github.com/yurikhan/kitty_grab>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Keyboard based text selection for the kitty scrollback buffer.

Desktop panels
-------------------------

`kitty panel <https://github.com/5hubham5ingh/kitty-panel>`__
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A system panel for Kitty terminal that displays real-time system metrics using terminal-based utilities.


`pawbar <https://github.com/codelif/pawbar>`__
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A kitten-panel based desktop panel for your desktop

Miscellaneous
------------------

.. tool_doom:

DOOM
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Play the classic shooter DOOM in `kitty <https://github.com/cryptocode/terminal-doom>`__ or even inside `neovim inside kitty
<https://github.com/seandewar/actually-doom.nvim>`__.

.. tool_gattino:

`gattino <https://github.com/salvozappa/gattino>`__
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Integrate kitty with an LLM to convert plain language prompts into shell
commands.

.. tool_kitty_smart_tab:

`kitty-smart-tab <https://github.com/yurikhan/kitty-smart-tab>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Use keys to either control tabs or pass them onto running applications if no
tabs are present

.. tool_kitty_smart_scroll:

`kitty-smart-scroll <https://github.com/yurikhan/kitty-smart-scroll>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Use keys to either scroll or pass them onto running applications if no
scrollback buffer is present

.. tool_kitti3:

`kitti3 <https://github.com/LandingEllipse/kitti3>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Allow using kitty as a drop-down terminal under the i3 window manager

.. tool_weechat_hints:

`weechat-hints <https://github.com/GermainZ/kitty-weechat-hints>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
URL hints kitten for WeeChat that works without having to use WeeChat's
raw-mode.

.. tool_glkitty:

`glkitty <https://github.com/michaeljclark/glkitty>`_
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
C library to draw OpenGL shaders in the terminal with a glgears demo
