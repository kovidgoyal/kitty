Performance
===================

The main goals for |kitty| performance are user perceived latency while typing
and "smoothness" while scrolling as well as CPU usage. |kitty| tries hard to
find an optimum balance for these. To that end it keeps a cache of each
rendered glyph in video RAM so that font rendering is not a bottleneck.
Interaction with child programs takes place in a separate thread from
rendering, to improve smoothness. Parsing of the byte stream is done using
`vector CPU instructions
<https://en.wikipedia.org/wiki/Single_instruction,_multiple_data>`__ for
maximum performance. Updates to the screen typically require sending just a few
bytes to the GPU.

Output from programs is parsed as soon as it is received. kitty redraws the
screen only when something changes and the pacing of redraws is controlled by
the :opt:`render_interval` option. By default, redraws are synced to the
refresh rate of the monitor, using the render frames provided by the windowing
system: the Wayland frame callbacks, the macOS display link, or on X11, the
vertical blank notifications of the Present extension. This means kitty never
draws frames that cannot be displayed, does not cause `screen tearing
<https://en.wikipedia.org/wiki/Screen_tearing>`__, and stops drawing when its
window is hidden. The first redraw after the screen has been idle happens
immediately, so syncing to the monitor does not add latency to typing.

You can also ask kitty to redraw on a schedule instead, using a fixed minimum
interval between frames, or cap the frame rate while still syncing to the
monitor, for example, to save energy on high refresh rate monitors. See
:ref:`conf-kitty-performance` for details.

Benchmarks
-------------

Measuring terminal emulator performance is fairly subtle, there are three main
axes on which performance is measured: Energy usage for typical tasks,
Keyboard to screen latency, and throughput (processing large amounts of data).

Keyboard to screen latency
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This is measured either with dedicated hardware, or software such as `Typometer
<https://pavelfatin.com/typometer/>`__. Third party measurements comparing
kitty with other terminal emulators on various systems show kitty has best in
class keyboard to screen latency.

Note that to minimize latency at the expense of more energy usage, use the
following settings in kitty.conf::

    render_interval 2
    wayland_enable_ime no

This makes kitty redraw as soon as possible after something changes, rather
than waiting for the next refresh of the monitor, while drawing at most 500
frames a second. On X11 without a compositor, this can cause screen tearing.
On Wayland, the compositor will still only show one frame per refresh of the
monitor, so the gains are small.

To reduce energy usage instead, you can limit the frame rate, while still
syncing to the monitor, for example, to about 30 frames a second, with::

    render_interval monitor 33

`Hardware based measurement on macOS
<https://thume.ca/2020/05/20/making-a-latency-tester/>`__ show that kitty and
Apple's Terminal.app share the crown for best latency. These
measurements were done with the now removed ``input_delay`` option at its
default value of ``3 ms`` which means kitty's actual numbers would be even lower.

`Typometer based measurements on Linux
<https://github.com/kovidgoyal/kitty/issues/2701#issuecomment-911089374>`__
show that kitty has far and away the best latency of the terminals tested.

.. _throughput:

Throughput
^^^^^^^^^^^^^^^^

kitty has a builtin kitten to measure throughput, it works by dumping large
amounts of data of different types into the tty device and measuring how fast
the terminal parses and responds to it. To run the tests yourself, run
``kitten __benchmark__`` in the terminal emulator you want to test, where the
kitten binary is part of the kitty install. To compare multiple terminals, use
the :repo_file:`comparative_benchmark.py` script in the kitty source code, which
runs the benchmark in all installed terminals from the set below, on a
Linux+Wayland system.

The measurements below were taken with the same font (DejaVu Sans Mono 11pt),
window size (120x40 cells) and otherwise default settings for all terminals,
on the same computer, running Linux 7.2 under Wayland  with an ``AMD
Ryzen AI 7 PRO 360``, with the terminals pinned to its fast cores. The numbers
are megabytes per second of data that the terminal processes, higher is better.
Entries are in order of decreasing average performance.

===========================  =====  =======  =====  ======  ======  =======
Terminal                     ASCII  Unicode  CSI    Colors  Images  Average
===========================  =====  =======  =====  ======  ======  =======
ghostty 1.4.0                525.8  148.9    156.9  198.0   836.3   373.2
kitty 1.0.0                  385.7  140.8    116.5  188.4   805.3   327.3
foot 1.28.0                  316.6  103.1    63.5   331.8   491.3   261.3
alacritty 0.17.0             162.4  117.7    78.6   240.1   419.5   203.7
ptyxis 50.1                  272.4  95.0     39.1   148.6   263.0   163.6
wezterm 20260716             31.7   38.7     15.4   45.7    274.8   81.2
konsole 26.08.3              46.8   62.7     46.1   113.1   31.8    60.1
xterm 411                    61.8   48.2     < 2.8  53.5    117.3   < 56.7
alacritty 0.17.0 + tmux 3.8  57.2   9.5      24.9   35.6    53.8    36.2
===========================  =====  =======  =====  ======  ======  =======

In this table, each column represents different types of data. The CSI column
is for data consisting of a mix of typical formatting escape codes and some
ASCII only text. The Colors column is for text where every character has
a different 24-bit color. Full results, including all the benchmarks, for the
four fastest terminals are below.

.. tab-set::

   .. tab-item:: kitty

      =================  =====  =======  ========  =========
      Benchmark          MB/s   Cells/s  Time (s)  Data (MB)
      =================  =====  =======  ========  =========
      ascii              385.7  387.3 M  1.04      399
      unicode            140.8  81.6 M   4.91      692
      scrollback         270.0  271.1 M  1.48      399
      render             370.0  371.5 M  1.08      399
      unique_unicode     51.3   -        17.07     875
      csi                116.5  -        4.29      500
      long_escape_codes  812.4  -        4.83      3920
      truecolor_text     188.4  -        5.31      1000
      palette16_text     223.3  -        4.48      1000
      halfblocks         261.5  -        3.83      1001
      images             805.3  -        3.31      2667
      =================  =====  =======  ========  =========


   .. tab-item:: ghostty

      =================  =====  =======  ========  =========
      Benchmark          MB/s   Cells/s  Time (s)  Data (MB)
      =================  =====  =======  ========  =========
      ascii              525.8  527.9 M  0.76      399
      unicode            148.9  86.2 M   4.65      693
      scrollback         384.0  385.5 M  1.04      399
      render             406.6  408.2 M  0.98      399
      unique_unicode     65.3   -        13.39     875
      csi                156.9  -        3.19      500
      long_escape_codes  829.0  -        4.73      3920
      truecolor_text     198.0  -        5.05      1000
      palette16_text     256.2  -        3.90      1000
      halfblocks         199.7  -        5.01      1001
      images             836.3  -        3.19      2667
      =================  =====  =======  ========  =========

   .. tab-item:: foot

      =================  =====  =======  ========  =========
      Benchmark          MB/s   Cells/s  Time (s)  Data (MB)
      =================  =====  =======  ========  =========
      ascii              316.6  317.9 M  1.26      399
      unicode            103.1  59.7 M   6.71      692
      scrollback         295.6  296.8 M  1.35      399
      render             294.1  295.3 M  1.36      399
      unique_unicode     11.3   -        77.68     875
      csi                63.5   -        7.87      500
      long_escape_codes  283.8  -        13.81     3920
      truecolor_text     331.8  -        3.01      1000
      palette16_text     329.4  -        3.04      1000
      halfblocks         306.1  -        3.27      1001
      images             491.3  -        5.43      2667
      =================  =====  =======  ========  =========

   .. tab-item:: alacritty

      =================  =====  =======  ========  =========
      Benchmark          MB/s   Cells/s  Time (s)  Data (MB)
      =================  =====  =======  ========  =========
      ascii              162.4  163.1 M  2.46      399
      unicode            117.7  68.2 M   5.88      692
      scrollback         82.0   82.4 M   4.87      399
      render             158.5  159.1 M  2.52      399
      unique_unicode     59.8   -        14.64     875
      csi                78.6   -        6.36      500
      long_escape_codes  146.2  -        26.82     3920
      truecolor_text     240.1  -        4.16      1000
      palette16_text     236.5  -        4.23      1000
      halfblocks         259.2  -        3.86      1001
      images             419.5  -        6.36      2667
      =================  =====  =======  ========  =========

.. note::

   The benchmark kitten suppresses actual rendering, to better focus on parser
   speed, except in its ``render`` benchmark. However, modern terminals
   typically render asynchronously, therefore the numbers from that benchmark
   are not really useful for comparison, as it is just a game about how much
   input to *batch* before rendering the next frame.

.. note::

   iTerm2 and Terminal.app are left out as they do not run under Linux. ptyxis
   uses the same VTE terminal widget as GNOME Terminal. Alacritty+tmux is
   included to show the effect of putting a terminal multiplexer into the mix
   and because alacritty isn't remotely comparable to any of the other
   terminals feature wise without tmux.

.. note::

   Each benchmark was given a maximum of 180 seconds per terminal. xterm did
   not complete the CSI benchmark in that time, so its number for that
   benchmark is an upper bound. The Images column is only meaningful for
   terminals that support the :doc:`kitty graphics protocol
   <graphics-protocol>`, other terminals simply discard the image data.

.. note::

   Terminals that do not support the `Synchronized update
   <https://gitlab.com/gnachman/iterm2/-/wikis/synchronized-updates-spec>`__
   escape code used to suppress rendering, render while the benchmark is running,
   which lowers their numbers.


Energy usage
^^^^^^^^^^^^^^^^^

Sadly, I do not have the infrastructure to measure actual energy usage so CPU
usage will have to stand in for it. Here are some CPU usage numbers for the
task of scrolling a file continuously in :program:`less`. The CPU usage is for
the terminal process and X together and is measured using :program:`htop`. The
measurements are taken at the same font and window size for all terminals on a
``Intel(R) Core(TM) i7-4820K CPU @ 3.70GHz`` CPU with a ``Advanced Micro
Devices, Inc. [AMD/ATI] Cape Verde XT [Radeon HD 7770/8760 / R7 250X]`` GPU.

==============   =========================
Terminal         CPU usage (X + terminal)
==============   =========================
|kitty|          6 - 8%
xterm            5 - 7% (but scrolling was extremely janky)
termite          10 - 13%
urxvt            12 - 14%
gnome-terminal   15 - 17%
konsole          29 - 31%
==============   =========================

As you can see, |kitty| uses much less CPU than all terminals, except xterm, but
its scrolling "smoothness" is much better than that of xterm (at least to my,
admittedly biased, eyes).

Instrumenting kitty
-----------------------

To profile kitty performance on Linux, first install ``perf`` and run::

    sudo setcap cap_sys_admin,cap_sys_ptrace,cap_syslog=ep /usr/bin/perf

Then build kitty with::

    make profile

Finally get benchmark and profiling results using::

    ./benchmark.py --perf

