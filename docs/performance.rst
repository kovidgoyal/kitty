Performance
===================

The main goals for |kitty| performance are user perceived latency while typing
and "smoothness" while scrolling as well as CPU usage. |kitty| tries hard to
find an optimum balance for these. To that end it keeps a cache of each rendered
glyph in video RAM so that font rendering is not a bottleneck. Interaction with
child programs takes place in a separate thread from rendering, to improve
smoothness.

There are two config options you can tune to adjust the performance,
:opt:`repaint_delay` and :opt:`input_delay`. These control the artificial delays
introduced into the render loop to reduce CPU usage. See
:ref:`conf-kitty-performance` for details. See also the :opt:`sync_to_monitor`
option to further decrease latency at the cost of some `screen tearing
<https://en.wikipedia.org/wiki/Screen_tearing>`__ while scrolling.

You can generate detailed per-function performance data using
`gperftools <https://github.com/gperftools/gperftools>`__. Build |kitty| with
``make profile``. Run kitty and perform the task you want to analyse, for
example, scrolling a large file with :program:`less`. After you quit, function
call statistics will be printed to STDOUT and you can use tools like
*KCachegrind* for more detailed analysis.

Here are some CPU usage numbers for the task of scrolling a file continuously in
:program:`less`. The CPU usage is for the terminal process and X together and is
measured using :program:`htop`. The measurements are taken at the same font and
window size for all terminals on a ``Intel(R) Core(TM) i7-4820K CPU @ 3.70GHz``
CPU with a ``Advanced Micro Devices, Inc. [AMD/ATI] Cape Verde XT [Radeon HD
7770/8760 / R7 250X]`` GPU.

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


.. _perf-cat:

.. note::

    Some people have asked why kitty does not perform better than terminal XXX
    in the test of sinking large amounts of data, such as catting a large text
    file. The answer is because this is not a goal for kitty. kitty deliberately
    throttles input parsing and output rendering to minimize resource usage
    while still being able to sink output faster than any real world program can
    produce it. Reducing CPU usage, and hence battery drain while achieving
    instant response times and smooth scrolling to a human eye is a far more
    important goal.
