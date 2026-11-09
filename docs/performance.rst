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
are megabytes per second of data that the terminal processes, higher is better,
and are the median of several runs.
Entries are in order of decreasing average performance.

===========================  =====  =======  =====  ======  ======  =======
Terminal                     ASCII  Unicode  CSI    Colors  Images  Average
===========================  =====  =======  =====  ======  ======  =======
kitty 1.0.0                  564.3  178.4    200.1  282.4   794.5   403.9
ghostty 1.4.0                496.7  145.4    151.7  185.6   792.6   354.4
foot 1.28.0                  284.8  99.5     62.0   318.3   488.5   250.6
alacritty 0.17.0             159.0  117.2    75.9   236.0   414.5   200.5
ptyxis 50.1                  271.9  95.4     38.4   145.6   249.2   160.1
wezterm 20260716             29.1   37.3     14.2   43.9    268.1   78.5
konsole 26.08.3              44.1   60.6     45.4   110.9   31.0    58.4
xterm 411                    58.7   44.7     < 2.8  41.0    91.2    < 47.7
alacritty 0.17.0 + tmux 3.8  54.8   9.0      24.3   33.2    53.2    34.9
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
      ascii              564.3  566.6 M  0.71      399
      unicode            178.4  103.3 M  3.88      693
      scrollback         415.9  417.6 M  0.96      399
      render             541.7  543.9 M  0.74      399
      unique_unicode     78.2   -        11.19     875
      csi                200.1  -        2.50      500
      long_escape_codes  818.3  -        4.79      3920
      truecolor_text     282.4  -        3.54      1000
      palette16_text     336.9  -        2.97      1000
      halfblocks         362.3  -        2.76      1001
      images             794.5  -        3.36      2667
      =================  =====  =======  ========  =========


   .. tab-item:: ghostty

      =================  =====  =======  ========  =========
      Benchmark          MB/s   Cells/s  Time (s)  Data (MB)
      =================  =====  =======  ========  =========
      ascii              496.7  498.7 M  0.80      399
      unicode            145.4  84.2 M   4.76      692
      scrollback         369.9  371.4 M  1.08      399
      render             385.3  386.8 M  1.04      399
      unique_unicode     62.7   -        13.95     875
      csi                151.7  -        3.30      500
      long_escape_codes  808.0  -        4.85      3920
      truecolor_text     185.6  -        5.39      1000
      palette16_text     248.5  -        4.02      1000
      halfblocks         189.2  -        5.29      1001
      images             792.6  -        3.37      2667
      =================  =====  =======  ========  =========

   .. tab-item:: foot

      =================  =====  =======  ========  =========
      Benchmark          MB/s   Cells/s  Time (s)  Data (MB)
      =================  =====  =======  ========  =========
      ascii              284.8  286.0 M  1.40      399
      unicode            99.5   57.6 M   6.96      693
      scrollback         275.4  276.5 M  1.45      399
      render             249.3  250.3 M  1.60      399
      unique_unicode     9.8    -        89.35     875
      csi                62.0   -        8.06      500
      long_escape_codes  266.8  -        14.69     3920
      truecolor_text     318.3  -        3.14      1000
      palette16_text     311.3  -        3.21      1000
      halfblocks         296.3  -        3.38      1001
      images             488.5  -        5.46      2667
      =================  =====  =======  ========  =========

   .. tab-item:: alacritty

      =================  =====  =======  ========  =========
      Benchmark          MB/s   Cells/s  Time (s)  Data (MB)
      =================  =====  =======  ========  =========
      ascii              159.0  159.7 M  2.51      399
      unicode            117.2  67.9 M   5.91      692
      scrollback         80.3   80.7 M   4.97      399
      render             155.1  155.7 M  2.57      399
      unique_unicode     57.2   -        15.30     875
      csi                75.9   -        6.58      500
      long_escape_codes  158.9  -        24.67     3920
      truecolor_text     236.0  -        4.24      1000
      palette16_text     236.3  -        4.23      1000
      halfblocks         254.2  -        3.94      1001
      images             414.5  -        6.43      2667
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
   benchmark is an upper bound. konsole did not complete the unique_unicode
   benchmark in that time. The Images column is only meaningful for
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

