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
the terminal parses and responds to it. The measurements below were taken with
the same font, font size and window size for all terminals, and default
settings, on the same computer. They clearly show kitty has the fastest
throughput. To run the tests yourself, run ``kitten __benchmark__`` in the
terminal emulator you want to test, where the kitten binary is part of the
kitty install.

The numbers are megabytes per second of data that the terminal
processes. Measurements were taken under Linux/X11 with an ``AMD Ryzen 7 PRO
5850U``. Entries are in order of decreasing performance. kitty is twice
as fast as the next best.

================   ======  ======= ===== ====== =======
Terminal           ASCII   Unicode CSI   Images Average
================   ======  ======= ===== ====== =======
kitty 0.33         121.8   105.0   59.8  251.6  134.55
gnometerm 3.50.1   33.4    55.0    16.1  142.8  61.83
alacritty 0.13.1   43.1    46.5    32.5  94.1   54.05
wezterm 20230712   16.4    26.0    11.1  140.5  48.5
xterm 389          47.7    18.3    0.6   56.3   30.72
konsole 23.08.04   25.2    37.7    23.6  23.4   27.48
alacritty+tmux     30.3    7.8     14.7  46.1   24.73
================   ======  ======= ===== ====== =======

In this table, each column represents different types of data. The CSI column
is for data consisting of a mix of typical formatting escape codes and some
ASCII only text.

.. note::

   The benchmark kitten suppresses actual rendering, to better focus on parser
   speed, except in its ``render`` benchmark. However, modern terminals
   typically render asynchronously, therefore the numbers from that benchmark
   are not really useful for comparison, as it is just a game about how much
   input to *batch* before rendering the next frame.
   However, even with rendering enabled kitty is still faster than all the
   rest. For brevity those numbers are not included.

.. note::

   foot, iterm2 and Terminal.app are left out as they do not run under X11.
   Alacritty+tmux is included just to show the effect of putting a terminal
   multiplexer into the mix (halving throughput) and because alacritty isn't
   remotely comparable to any of the other terminals feature wise without tmux.

.. note::

   konsole, gnome-terminal and xterm do not support the `Synchronized update
   <https://gitlab.com/gnachman/iterm2/-/wikis/synchronized-updates-spec>`__
   escape code used to suppress rendering, if and when they gain support for it
   their numbers are likely to improve by ``20 - 50%``, depending on how well they
   implement it.


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

