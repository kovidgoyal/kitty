Terminal graphics protocol
=================================

The goal of this specification is to create a flexible and performant protocol
that allows the program running in the terminal, hereafter called the *client*,
to render arbitrary pixel (raster) graphics to the screen of the terminal
emulator. The major design goals are:

* Should not require terminal emulators to understand image formats.
* Should allow specifying graphics to be drawn at individual pixel positions.
* The graphics should integrate with the text, in particular it should be possible to draw graphics
  below as well as above the text, with alpha blending. The graphics should also scroll with the text, automatically.
* Should use optimizations when the client is running on the same computer as the terminal emulator.

For some discussion regarding the design choices, see :iss:`33`.

To see a quick demo, inside a |kitty| terminal run::

    kitten icat path/to/some/image.png

You can also see a screenshot with more sophisticated features such as
alpha-blending and text over graphics.

.. image:: https://user-images.githubusercontent.com/1308621/31647475-1188ab66-b326-11e7-8d26-24b937f1c3e8.png
    :alt: Demo of graphics rendering in kitty
    :align: center

Some programs and libraries that use the kitty graphics protocol:

* `termpdf.py <https://github.com/dsanson/termpdf.py>`_ - a terminal PDF/DJVU/CBR viewer
* `ranger <https://github.com/ranger/ranger>`_ - a terminal file manager, with image previews
* :doc:`kitty-diff <kittens/diff>` - a side-by-side terminal diff program with support for images
* `tpix <https://github.com/jesvedberg/tpix>`_ - a statically compiled binary that can be used to display images and easily installed on remote servers without root access
* `mpv <https://github.com/mpv-player/mpv/commit/874e28f4a41a916bb567a882063dd2589e9234e1>`_ - A video player that can play videos in the terminal
* `pixcat <https://github.com/mirukana/pixcat>`_ - a third party CLI and python library that wraps the graphics protocol
* `neofetch <https://github.com/dylanaraps/neofetch>`_ - A command line system
  information tool
* `viu <https://github.com/atanunq/viu>`_ - a terminal image viewer
* `ctx.graphics <https://ctx.graphics/>`_ - Library for drawing graphics
* `timg <https://github.com/hzeller/timg>`_ - a terminal image and video viewer
* `notcurses <https://github.com/dankamongmen/notcurses>`_ - C library for terminal graphics with bindings for C++, Rust and Python
* `rasterm <https://github.com/BourgeoisBear/rasterm>`_  - Go library to display images in the terminal
* `chafa <https://github.com/hpjansson/chafa>`_  - a terminal image viewer
* `hologram.nvim <https://github.com/edluffy/hologram.nvim>`_  - view images inside nvim
* `image.nvim <https://github.com/3rd/image.nvim>`_ - Bringing images to neovim
* `image_preview.nvim <https://github.com/adelarsq/image_preview.nvim/>`_ - Image preview for neovim
* `kui.nvim <https://github.com/romgrk/kui.nvim>`_  - Build sophisticated UIs inside neovim using the kitty graphics protocol
* `term-image <https://github.com/AnonymouX47/term-image>`_  - A Python library, CLI and TUI to display and browse images in the terminal
* `glkitty <https://github.com/michaeljclark/glkitty>`_ - C library to draw OpenGL shaders in the terminal with a glgears demo
* `twitch-tui <https://github.com/Xithrius/twitch-tui>`_ - Twitch chat in the terminal
* `awrit <https://github.com/chase/awrit>`_ - Chromium-based web browser rendered in Kitty with mouse and keyboard support
* `fzf <https://github.com/junegunn/fzf/commit/d8188fce7b7bea982e7f9050c35e488e49fb8fd0>`_ - A command line fuzzy finder

Other terminals that have implemented the graphics protocol:

* `WezTerm <https://github.com/wez/wezterm/issues/986>`_
* `Konsole <https://invent.kde.org/utilities/konsole/-/merge_requests/594>`_
* `wayst <https://github.com/91861/wayst>`_


Getting the window size
-------------------------

In order to know what size of images to display and how to position them, the
client must be able to get the window size in pixels and the number of cells
per row and column. The cell width is then simply the window size divided by the
number of rows. This can be done by using the ``TIOCGWINSZ`` ioctl. Some
code to demonstrate its use

.. tab:: C

    .. code-block:: c

        #include <stdio.h>
        #include <sys/ioctl.h>

        int main(int argc, char **argv) {
            struct winsize sz;
            ioctl(0, TIOCGWINSZ, &sz);
            printf(
                "number of rows: %i, number of columns: %i, screen width: %i, screen height: %i\n",
                sz.ws_row, sz.ws_col, sz.ws_xpixel, sz.ws_ypixel);
            return 0;
        }


.. tab:: Python

    .. code-block:: python

        import array, fcntl, sys, termios
        buf = array.array('H', [0, 0, 0, 0])
        fcntl.ioctl(sys.stdout, termios.TIOCGWINSZ, buf)
        print((
            'number of rows: {} number of columns: {}'
            'screen width: {} screen height: {}').format(*buf))

.. tab:: Go

    .. code-block:: go

        package main

        import (
            "fmt"
            "os"

            "golang.org/x/sys/unix"
        )

        func main() {
            var err error
            var f *os.File
            if f, err = os.OpenFile("/dev/tty", unix.O_NOCTTY|unix.O_CLOEXEC|unix.O_NDELAY|unix.O_RDWR, 0666); err == nil {
                var sz *unix.Winsize
                if sz, err = unix.IoctlGetWinsize(int(f.Fd()), unix.TIOCGWINSZ); err == nil {
                    fmt.Printf("rows: %v columns: %v width: %v height %v\n", sz.Row, sz.Col, sz.Xpixel, sz.Ypixel)
                    return
                }
            }
            fmt.Fprintln(os.Stderr, err)
            os.Exit(1)
        }


.. tab:: Bash

    .. code-block:: sh

        #!/bin/bash

        # This uses the kitten standalone binary from kitty to get the pixel sizes
        # since we can't do IOCTLs directly. Fortunately, kitten is a static exe
        # pre-built for every Unix like OS under the sun.

        builtin read -r rows cols < <(command stty size)
        IFS=x builtin read -r width height < <(command kitten icat --print-window-size); builtin unset IFS
        builtin echo "number of rows: $rows number of columns: $cols screen width: $width screen height: $height"


Note that some terminals return ``0`` for the width and height values. Such
terminals should be modified to return the correct values.  Examples of
terminals that return correct values: ``kitty, xterm``

You can also use the *CSI t* escape code to get the screen size. Send
``<ESC>[14t`` to ``STDOUT`` and kitty will reply on ``STDIN`` with
``<ESC>[4;<height>;<width>t`` where ``height`` and ``width`` are the window
size in pixels. This escape code is supported in many terminals, not just
kitty.

A minimal example
------------------

Some minimal code to display PNG images in kitty, using the most basic
features of the graphics protocol:

.. tab:: Bash

    .. code-block:: sh

        #!/bin/bash
        transmit_png() {
            data=$(base64 "$1")
            data="${data//[[:space:]]}"
            builtin local pos=0
            builtin local chunk_size=4096
            while [ $pos -lt ${#data} ]; do
                builtin printf "\e_G"
                [ $pos = "0" ] && printf "a=T,f=100,"
                builtin local chunk="${data:$pos:$chunk_size}"
                pos=$(($pos+$chunk_size))
                [ $pos -lt ${#data} ] && builtin printf "m=1"
                [ ${#chunk} -gt 0 ] && builtin printf ";%s" "${chunk}"
                builtin printf "\e\\"
            done
        }

        transmit_png "$1"

.. tab:: Python

    .. code-block:: python

        #!/usr/bin/python
        import sys
        from base64 import standard_b64encode

        def serialize_gr_command(**cmd):
            payload = cmd.pop('payload', None)
            cmd = ','.join(f'{k}={v}' for k, v in cmd.items())
            ans = []
            w = ans.append
            w(b'\033_G'), w(cmd.encode('ascii'))
            if payload:
                w(b';')
                w(payload)
            w(b'\033\\')
            return b''.join(ans)

        def write_chunked(**cmd):
            data = standard_b64encode(cmd.pop('data'))
            while data:
                chunk, data = data[:4096], data[4096:]
                m = 1 if data else 0
                sys.stdout.buffer.write(serialize_gr_command(payload=chunk, m=m,
                                                            **cmd))
                sys.stdout.flush()
                cmd.clear()

        with open(sys.argv[-1], 'rb') as f:
            write_chunked(a='T', f=100, data=f.read())


Save this script as :file:`send-png`, then you can use it to display any PNG
file in kitty as::

    chmod +x send-png
    ./send-png file.png


The graphics escape code
---------------------------

All graphics escape codes are of the form::

    <ESC>_G<control data>;<payload><ESC>\

This is a so-called *Application Programming Command (APC)*. Most terminal
emulators ignore APC codes, making it safe to use.

The control data is a comma-separated list of ``key=value`` pairs.  The payload
is arbitrary binary data, base64-encoded to prevent interoperation problems
with legacy terminals that get confused by control codes within an APC code.
The meaning of the payload is interpreted based on the control data.

The first step is to transmit the actual image data.

.. _transferring_pixel_data:

Transferring pixel data
--------------------------

The first consideration when transferring data between the client and the
terminal emulator is the format in which to do so. Since there is a vast and
growing number of image formats in existence, it does not make sense to have
every terminal emulator implement support for them. Instead, the client should
send simple pixel data to the terminal emulator. The obvious downside to this
is performance, especially when the client is running on a remote machine.
Techniques for remedying this limitation are discussed later. The terminal
emulator must understand pixel data in three formats, 24-bit RGB, 32-bit RGBA and
PNG. This is specified using the ``f`` key in the control data. ``f=32`` (which is the
default) indicates 32-bit RGBA data and ``f=24`` indicates 24-bit RGB data and ``f=100``
indicates PNG data. The PNG format is supported both for convenience, and as a compact way
of transmitting paletted images.

RGB and RGBA data
~~~~~~~~~~~~~~~~~~~

In these formats the pixel data is stored directly as 3 or 4 bytes per pixel,
respectively. The colors in the data **must** be in the *sRGB color space*.  When
specifying images in this format, the image dimensions **must** be sent in the
control data. For example::

    <ESC>_Gf=24,s=10,v=20;<payload><ESC>\

Here the width and height are specified using the ``s`` and ``v`` keys respectively. Since
``f=24`` there are three bytes per pixel and therefore the pixel data must be ``3 * 10 * 20 = 600``
bytes.

PNG data
~~~~~~~~~~~~~~~

In this format any PNG image can be transmitted directly.  For example::

    <ESC>_Gf=100;<payload><ESC>\


The PNG format is specified using the ``f=100`` key. The width and height of
the image will be read from the PNG data itself. Note that if you use both PNG and
compression, then you must provide the ``S`` key with the size of the PNG data.


Compression
~~~~~~~~~~~~~

The client can send compressed image data to the terminal emulator, by
specifying the ``o`` key. Currently, only :rfc:`1950` ZLIB based deflate
compression is supported, which is specified using ``o=z``. For example::

    <ESC>_Gf=24,s=10,v=20,o=z;<payload><ESC>\

This is the same as the example from the RGB data section, except that the
payload is now compressed using deflate (this occurs prior to base64-encoding).
The terminal emulator will decompress it before rendering. You can specify
compression for any format. The terminal emulator will decompress before
interpreting the pixel data.


The transmission medium
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The transmission medium is specified using the ``t`` key. The ``t`` key defaults to ``d``
and can take the values:

==================    ============
Value of `t`          Meaning
==================    ============
``d``                 Direct (the data is transmitted within the escape code itself)
``f``                 A simple file (regular files only, not named pipes, device files, etc.)
``t``                 A temporary file, the terminal emulator will delete the file after reading the pixel data. For security reasons
                      the terminal emulator should only delete the file if it
                      is in a known temporary directory, such as :file:`/tmp`,
                      :file:`/dev/shm`, :file:`TMPDIR env var if present` and any platform
                      specific temporary directories and the file has the
                      string :code:`tty-graphics-protocol` in its full file path.
``s``                 A *shared memory object*, which on POSIX systems is a
                      `POSIX shared memory object <https://pubs.opengroup.org/onlinepubs/9699919799/functions/shm_open.html>`_
                      and on Windows is a
                      `Named shared memory object <https://docs.microsoft.com/en-us/windows/win32/memory/creating-named-shared-memory>`_.
                      The terminal emulator must read the data from the memory
                      object and then unlink and close it on POSIX and just
                      close it on Windows.
==================    ============

When opening files, the terminal emulator must follow symlinks. In case of
symlink loops or too many symlinks, it should fail and respond with an error,
similar to reporting any other kind of I/O error. Since the file paths come
from potentially untrusted sources, terminal emulators **must** refuse to read
any device/socket/etc. special files. Only regular files are allowed.
Additionally, terminal emulators may refuse to read files in *sensitive*
parts of the filesystem, such as :file:`/proc`, :file:`/sys`, :file:`/dev/`, etc.

Local client
^^^^^^^^^^^^^^

First let us consider the local client techniques (files and shared memory). Some examples::

    <ESC>_Gf=100,t=f;<encoded /path/to/file.png><ESC>\

Here we tell the terminal emulator to read PNG data from the specified file of
the specified size::

    <ESC>_Gs=10,v=2,t=s,o=z;<encoded /some-shared-memory-name><ESC>\

Here we tell the terminal emulator to read compressed image data from
the specified shared memory object.

The client can also specify a size and offset to tell the terminal emulator
to only read a part of the specified file. The is done using the ``S`` and ``O``
keys respectively. For example::

    <ESC>_Gs=10,v=2,t=s,S=80,O=10;<encoded /some-shared-memory-name><ESC>\

This tells the terminal emulator to read ``80`` bytes starting from the offset ``10``
inside the specified shared memory buffer.


Remote client
^^^^^^^^^^^^^^^^

Remote clients, those that are unable to use the filesystem/shared memory to
transmit data, must send the pixel data directly using escape codes. Since
escape codes are of limited maximum length, the data will need to be chunked up
for transfer. This is done using the ``m`` key. The pixel data must first be
base64 encoded then chunked up into chunks no larger than ``4096`` bytes. All
chunks, except the last, must have a size that is a multiple of 4. The client
then sends the graphics escape code as usual, with the addition of an ``m`` key
that must have the value ``1`` for all but the last chunk, where it must be
``0``. For example, if the data is split into three chunks, the client would
send the following sequence of escape codes to the terminal emulator::

    <ESC>_Gs=100,v=30,m=1;<encoded pixel data first chunk><ESC>\
    <ESC>_Gm=1;<encoded pixel data second chunk><ESC>\
    <ESC>_Gm=0;<encoded pixel data last chunk><ESC>\

Note that only the first escape code needs to have the full set of control
codes such as width, height, format, etc. Subsequent chunks **must** have only
the ``m`` and optionally ``q`` keys. When sending animation frame data, subsequent
chunks **must** also specify the ``a=f`` key. The client **must** finish sending
all chunks for a single image before sending any other graphics related escape
codes. Note that the cursor position used to display the image **must** be the
position when the final chunk is received. Finally, terminals must not display
anything, until the entire sequence is received and validated.


Querying support and available transmission mediums
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Since a client has no a-priori knowledge of whether it shares a filesystem/shared memory
with the terminal emulator, it can send an id with the control data, using the ``i`` key
(which can be an arbitrary positive integer up to 4294967295, it must not be zero).
If it does so, the terminal emulator will reply after trying to load the image, saying
whether loading was successful or not. For example::

    <ESC>_Gi=31,s=10,v=2,t=s;<encoded /some-shared-memory-name><ESC>\

to which the terminal emulator will reply (after trying to load the data)::

    <ESC>_Gi=31;error message or OK<ESC>\

Here the ``i`` value will be the same as was sent by the client in the original
request.  The message data will be a ASCII encoded string containing only
printable characters and spaces. The string will be ``OK`` if reading the pixel
data succeeded or an error message.

Sometimes, using an id is not appropriate, for example, if you do not want to
replace a previously sent image with the same id, or if you are sending a dummy
image and do not want it stored by the terminal emulator. In that case, you can
use the *query action*, set ``a=q``. Then the terminal emulator will try to load
the image and respond with either OK or an error, as above, but it will not
replace an existing image with the same id, nor will it store the image.

As of May 2023, kitty has a complete implementation of this protocol and
WezTerm has a mostly complete implementation. Konsole and wayst have partial
support. We intend that any terminal emulator that wishes to support it can do so. To
check if a terminal emulator supports the graphics protocol the best way is to
send the above *query action* followed by a request for the `primary device
attributes <https://vt100.net/docs/vt510-rm/DA1.html>`_. If you get back an
answer for the device attributes without getting back an answer for the *query
action* the terminal emulator does not support the graphics protocol.

This means that terminal emulators that support the graphics protocol, **must**
reply to *query actions* immediately without processing other input. Most
terminal emulators handle input in a FIFO manner, anyway.

So for example, you could send::

      <ESC>_Gi=31,s=1,v=1,a=q,t=d,f=24;AAAA<ESC>\<ESC>[c

If you get back a response to the graphics query, the terminal emulator supports
the protocol, if you get back a response to the device attributes query without
a response to the graphics query, it does not.


Display images on screen
-----------------------------

Every transmitted image can be displayed an arbitrary number of times on the
screen, in different locations, using different parts of the source image, as
needed. Each such display of an image is called a *placement*.  You can either
simultaneously transmit and display an image using the action ``a=T``, or first
transmit the image with a id, such as ``i=10`` and then display it with
``a=p,i=10`` which will display the previously transmitted image at the current
cursor position. When specifying an image id, the terminal emulator will reply
to the placement request with an acknowledgement code, which will be either::

    <ESC>_Gi=<id>;OK<ESC>\

when the image referred to by id was found, or::

    <ESC>_Gi=<id>;ENOENT:<some detailed error msg><ESC>\

when the image with the specified id was not found. This is similar to the
scheme described above for querying available transmission media, except that
here we are querying if the image with the specified id is available or needs to
be re-transmitted.

Since there can be many placements per image, you can also give placements an
id. To do so add the ``p`` key with a number between ``1`` and ``4294967295``.
When you specify a placement id, it will be added to the acknowledgement code
above. Every placement is uniquely identified by the pair of the ``image id``
and the ``placement id``. If you specify a placement id for an image that does
not have an id (i.e. has id=0), it will be ignored. In particular this means
there can exist multiple images with ``image id=0, placement id=0``. Not
specifying a placement id or using ``p=0`` for multiple put commands (``a=p``)
with the same non-zero image id results in multiple placements the image.

An example response::

    <ESC>_Gi=<image id>,p=<placement id>;OK<ESC>\

If you send two placements with the same ``image id`` and ``placement id`` the
second one will replace the first. This can be used to resize or move
placements around the screen, without flicker.


.. versionadded:: 0.19.3
   Support for specifying placement ids (see :doc:`kittens/query_terminal` to query kitty version)


Controlling displayed image layout
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The image is rendered at the current cursor position, from the upper left corner of
the current cell. You can also specify extra ``X=3`` and ``Y=4`` pixel offsets to display from
a different origin within the cell. Note that the offsets must be smaller than the size of the cell.

By default, the entire image will be displayed (images wider than the available
width will be truncated on the right edge). You can choose a source rectangle (in pixels)
as the part of the image to display. This is done with the keys: ``x, y, w, h`` which specify
the top-left corner, width and height of the source rectangle. The displayed
area is the intersection of the specified rectangle with the source image
rectangle.

You can also ask the terminal emulator to display the image in a specified rectangle
(num of columns / num of lines), using the control codes ``c,r``. ``c`` is the number of columns
and `r` the number of rows. The image will be scaled (enlarged/shrunk) as needed to fit
the specified area. Note that if you specify a start cell offset via the ``X,Y`` keys, it is not
added to the number of rows/columns. If only one of either ``r`` or ``c`` is
specified, the other one is computed based on the source image aspect ratio, so
that the image is displayed without distortion.

Finally, you can specify the image *z-index*, i.e. the vertical stacking order. Images
placed in the same location with different z-index values will be blended if
they are semi-transparent. You can specify z-index values using the ``z`` key.
Negative z-index values mean that the images will be drawn under the text. This
allows rendering of text on top of images. Negative z-index values below
INT32_MIN/2 (-1,073,741,824) will be drawn under cells with non-default background
colors. If two images with the same z-index overlap then the image with the
lower id is considered to have the lower z-index. If the images have the same
z-index and the same id, then the behavior is undefined.

.. note:: After placing an image on the screen the cursor must be moved to the
   right by the number of cols in the image placement rectangle and down by the
   number of rows in the image placement rectangle. If either of these cause
   the cursor to leave either the screen or the scroll area, the exact
   positioning of the cursor is undefined, and up to implementations.
   The client can ask the terminal emulator to not move the cursor at all
   by specifying ``C=1`` in the command, which sets the cursor movement policy
   to no movement for placing the current image.

.. versionadded:: 0.20.0
   Support for the C=1 cursor movement policy


.. _graphics_unicode_placeholders:

Unicode placeholders
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. versionadded:: 0.28.0
   Support for image display via Unicode placeholders

You can also use a special Unicode character ``U+10EEEE`` as a placeholder for
an image. This approach is less flexible, but it allows using images inside
any host application that supports Unicode, foreground colors (tmux, vim, weechat, etc.),
and a way to pass escape codes through to the underlying terminal.

The central idea is that we use a single *Private Use* Unicode character as a
*placeholder* to indicate to the terminal that an image is supposed to be
displayed at that cell. Since this character is just normal text, Unicode aware
application will move it around as needed when they redraw their screens,
thereby automatically moving the displayed image as well, even though they know
nothing about the graphics protocol. So an image is first created using the
normal graphics protocol escape codes (albeit in quiet mode (``q=2``) so that there are
no responses from the terminal that could confuse the host application). Then,
the actual image is displayed by getting the host application to emit normal
text consisting of ``U+10EEEE`` and various diacritics (Unicode combining
characters) and colors.

To use it, first create an image as you would normally with the graphics
protocol with (``q=2``), but do not create a placement for it, that is, do not
display it. Then, create a *virtual image placement* by specifying ``U=1`` and
the desired number of lines and columns::

    <ESC>_Ga=p,U=1,i=<image_id>,c=<columns>,r=<rows><ESC>\

The creation of the placement need not be a separate escape code, it can be
combined with ``a=T`` to both transmit and create the virtual placement with a
single code.

The image will eventually be fit to the specified rectangle, its aspect ratio
preserved. Finally, the image can be actually displayed by using the
placeholder character, encoding the image ID in its foreground color. The row
and column values are specified with diacritics listed in
:download:`rowcolumn-diacritics.txt <../gen/rowcolumn-diacritics.txt>`.  For
example, here is how you can print a ``2x2`` placeholder for image ID ``42``:

.. code-block:: sh

    printf "\e[38;5;42m\U10EEEE\U0305\U0305\U10EEEE\U0305\U030D\e[39m\n"
    printf "\e[38;5;42m\U10EEEE\U030D\U0305\U10EEEE\U030D\U030D\e[39m\n"

Here, ``U+305`` is the diacritic corresponding to the number ``0``
and ``U+30D`` corresponds to ``1``. So these two commands create the following
``2x2`` placeholder:

========== ==========
(0, 0)     (0, 1)
(1, 0)     (1, 1)
========== ==========

This will cause the image with ID ``42`` to be displayed in a ``2x2`` grid.
Ideally, you would print out as many cells as the number of rows and columns
specified when creating the virtual placement, but in case of a mismatch only
part of the image will be displayed.

By using only the foreground color for image ID you are limited to either 8-bit IDs in 256 color
mode or 24-bit IDs in true color mode. Since IDs are in a global namespace
there can easily be collisions. If you need more bits for the image
ID, you can specify the most significant byte via a third diacritic. For
example, this is the placeholder for the image ID ``33554474 = 42 + (2 << 24)``:

.. code-block:: sh

    printf "\e[38;5;42m\U10EEEE\U0305\U0305\U030E\U10EEEE\U0305\U030D\U030E\n"
    printf "\e[38;5;42m\U10EEEE\U030D\U0305\U030E\U10EEEE\U030D\U030D\U030E\n"

Here, ``U+30E`` is the diacritic corresponding to the number ``2``.

You can also specify a placement ID using the underline color (if it's omitted
or zero, the terminal may choose any virtual placement of the given image). The
background color is interpreted as the background color, visible if the image is
transparent. Other text attributes are reserved for future use.

Row, column and most significant byte diacritics may also be omitted, in which
case the placeholder cell will inherit the missing values from the placeholder
cell to the left, following the algorithm:

- If no diacritics are present, and the previous placeholder cell has the same
  foreground and underline colors, then the row of the current cell will be the
  row of the cell to the left, the column will be the column of the cell to the
  left plus one, and the most significant image ID byte will be the most
  significant image ID byte of the cell to the left.
- If only the row diacritic is present, and the previous placeholder cell has
  the same row and the same foreground and underline colors, then the column of
  the current cell will be the column of the cell to the left plus one, and the
  most significant image ID byte will be the most significant image ID byte of
  the cell to the left.
- If only the row and column diacritics are present, and the previous
  placeholder cell has the same row, the same foreground and underline colors,
  and its column is one less than the current column, then the most significant
  image ID byte of the current cell will be the most significant image ID byte
  of the cell to the left.

These rules are applied left-to-right, which allows specifying only row
diacritics of the first column, i.e. here is a 2 rows by 3 columns placeholder:

.. code-block:: sh

    printf "\e[38;5;42m\U10EEEE\U0305\U10EEEE\U10EEEE\n"
    printf "\e[38;5;42m\U10EEEE\U030D\U10EEEE\U10EEEE\n"

This will not work for horizontal scrolling and overlapping images since the two
given rules will fail to guess the missing information. In such cases, the
terminal may apply other heuristics (but it doesn't have to).

It is important to distinguish between virtual image placements and real images
displayed on top of Unicode placeholders. Virtual placements are invisible and only play
the role of prototypes for real images. Virtual placements can be deleted by a
deletion command only when the `d` key is equal to ``i``, ``I``, ``r``, ``R``, ``n`` or ``N``.
The key values ``a``, ``c``, ``p``, ``q``, ``x``, ``y``, ``z`` and their capital
variants never affect virtual placements because they do not have a physical
location on the screen.

Real images displayed on top of Unicode placeholders are not considered
placements from the protocol perspective. They cannot be manipulated using
graphics commands, instead they should be moved, deleted, or modified by
manipulating the underlying Unicode placeholder as normal text.

.. _relative_image_placement:

Relative placements
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. versionadded:: 0.31.0
   Support for positioning images relative to other images

You can specify that a placement is positioned relative to another placement.
This is particularly useful in combination with
:ref:`graphics_unicode_placeholders` above. It can be used to specify a single
transparent pixel image using a Unicode placeholder, which moves around
naturally with the text, the real image(s) can base their position relative to
the placeholder.

To specify that a placement should be relative to another, use the
``P=<image_id>,Q=<placement_id>`` keys, when creating the relative placement.
For example::

    <ESC>_Ga=p,i=<image_id>,p=<placement_id>,P=<parent_img_id>,Q=<parent_placement_id><ESC>\

This will create a *relative placement* that refers to the *parent placement*
specified by the ``P`` and ``Q`` keys. When the parent placement moves, the
relative placement moves along with it. The relative placement can be offset
from the parent's location by a specified number of cells, using the ``H`` and
``V`` keys for horizontal and vertical displacement. Positive values move right
and down. Negative values move left and up. The origin is the top left cell of
the parent placement.

The lifetime of a relative placement is tied to the lifetime of its parent. If
its parent is deleted, it is deleted as well. If the image that the relative
placement is a placement of, has no more placements, the image is deleted as
well. Thus, a parent and its relative placements form a *group* that is managed
together.

A relative placement can refer to another relative placement as its parent.
Thus the relative placements can form a chain. It is implementation dependent
how long a chain of such placements is allowed, but implementation must allow
a chain of length at least 8. If the implementation max depth is exceeded, the
terminal must respond with the ``ETOODEEP`` error code.

Virtual placements created for Unicode placeholder based images cannot also be
relative placements. However, a relative placement can refer to a virtual
placement as its parent. When a virtual placement is the parent, its position
is derived from all the actual Unicode placeholder images that refer to it.
The x position is the minimum of all the placeholder x positions and the y
position is the minimum of all the placeholder y positions. If a client
attempts to make a virtual placement relative the terminal must respond with
the ``EINVAL`` error code.

Terminals are required to reject the creation of a relative placement
that would create a cycle, such as when A is relative to B and B is relative to
C and C is relative to A. In such cases, the terminal must respond with the
``ECYCLE`` error code.

If a client attempts to create a reference to a placement that does not exist
the terminal must respond with the ``ENOPARENT`` error code.

.. note::
   Since a relative placement gets its position specified based on another
   placement, instead of the cursor, the cursor must not move after a relative
   position, regardless of the value of the ``C`` key to control cursor
   movement.


Deleting images
---------------------

Images can be deleted by using the delete action ``a=d``. If specified without any
other keys, it will delete all images visible on screen. To delete specific images,
use the `d` key as described in the table below. Note that each value of d has
both a lowercase and an uppercase variant. The lowercase variant only deletes the
images without necessarily freeing up the stored image data, so that the images can be
re-displayed without needing to resend the data. The uppercase variants will delete
the image data as well, provided that the image is not referenced elsewhere, such as in the
scrollback buffer. The values of the ``x`` and ``y`` keys are the same as cursor positions (i.e.
``x=1, y=1`` is the top left cell).

=================    ============
Value of ``d``       Meaning
=================    ============
``a`` or ``A``       Delete all placements visible on screen
``i`` or ``I``       Delete all images with the specified id, specified using the ``i`` key. If you specify a ``p`` key for the placement                          id as well, then only the placement with the specified image id and placement id will be deleted.
``n`` or ``N``       Delete newest image with the specified number, specified using the ``I`` key. If you specify a ``p`` key for the
                     placement id as well, then only the placement with the specified number and placement id will be deleted.
``c`` or ``C``       Delete all placements that intersect with the current cursor position.
``f`` or ``F``       Delete animation frames.
``p`` or ``P``       Delete all placements that intersect a specific cell, the cell is specified using the ``x`` and ``y`` keys
``q`` or ``Q``       Delete all placements that intersect a specific cell having a specific z-index. The cell and z-index is specified using the ``x``, ``y`` and ``z`` keys.
``r`` or ``R``       Delete all images whose id is greater than or equal to the value of the ``x`` key and less than or equal to the value of the ``y`` (added in kitty version 0.33.0).
``x`` or ``X``       Delete all placements that intersect the specified column, specified using the ``x`` key.
``y`` or ``Y``       Delete all placements that intersect the specified row, specified using the ``y`` key.
``z`` or ``Z``       Delete all placements that have the specified z-index, specified using the ``z`` key.
=================    ============


Note when all placements for an image have been deleted, the image is also
deleted, if the capital letter form above is specified. Also, when the terminal
is running out of quota space for new images, existing images without
placements will be preferentially deleted.

Some examples::

    <ESC>_Ga=d<ESC>\              # delete all visible placements
    <ESC>_Ga=d,d=i,i=10<ESC>\     # delete the image with id=10, without freeing data
    <ESC>_Ga=d,d=i,i=10,p=7<ESC>\ # delete the image with id=10 and placement id=7, without freeing data
    <ESC>_Ga=d,d=Z,z=-1<ESC>\     # delete the placements with z-index -1, also freeing up image data
    <ESC>_Ga=d,d=p,x=3,y=4<ESC>\  # delete all placements that intersect the cell at (3, 4), without freeing data


Suppressing responses from the terminal
-------------------------------------------

If you are using the graphics protocol from a limited client, such as a shell
script, it might be useful to avoid having to process responses from the
terminal. For this, you can use the ``q`` key. Set it to ``1`` to suppress
``OK`` responses and to ``2`` to suppress failure responses.

.. versionadded:: 0.19.3
   The ability to suppress responses (see :doc:`kittens/query_terminal` to query kitty version)


Requesting image ids from the terminal
-------------------------------------------

If you are writing a program that is going to share the screen with other
programs and you still want to use image ids, it is not possible to know
what image ids are free to use. In this case, instead of using the ``i``
key to specify an image id use the ``I`` key to specify an image number
instead. These numbers are not unique.
When creating a new image, even if an existing image has the same number a new
one is created. And the terminal will reply with the id of the newly created
image. For example, when creating an image with ``I=13``, the terminal will
send the response::

    <ESC>_Gi=99,I=13;OK<ESC>\

Here, the value of ``i`` is the id for the newly created image and the value of
``I`` is the same as was sent in the creation command.

All future commands that refer to images using the image number, such as
creating placements or deleting images, will act on only the newest image with
that number. This allows the client program to send a bunch of commands dealing
with an image by image number without waiting for a response from the terminal
with the image id. Once such a response is received, the client program should
use the ``i`` key with the image id for all future communication.

.. note:: Specifying both ``i`` and ``I`` keys in any command is an error. The
   terminal must reply with an EINVAL error message, unless silenced.

.. versionadded:: 0.19.3
   The ability to use image numbers (see :doc:`kittens/query_terminal` to query kitty version)


.. _animation_protocol:

Animation
-------------------------------------------

.. versionadded:: 0.20.0
   Animation support (see :doc:`kittens/query_terminal` to query kitty version)

When designing support for animation, the two main considerations were:

#. There should be a way for both client and terminal driven animations.
   Since there is unknown and variable latency between client and terminal,
   especially over SSH, client driven animations are not sufficient.

#. Animations often consist of small changes from one frame to the next, the
   protocol should thus allow transmitting these deltas for efficiency and
   performance reasons.

Animation support is added to the protocol by adding two new modes for the
``a`` (action) key. A ``f`` mode for transmitting frame data and an ``a`` mode
for controlling the animation of an image. Animation proceeds in two steps,
first a normal image is created as described earlier. Then animation frames are
added to the image to make it into an animation. Since every animation is
associated with a single image, all animation escape codes must specify either
the ``i`` or ``I`` keys to identify the image being operated on.


Transferring animation frame data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Transferring animation frame data is very similar to
:ref:`transferring_pixel_data` above. The main difference is that the image
the frame belongs to must be specified and it is possible to transmit data for
only part of a frame, declaring the rest of the frame to be filled in by data
from a previous frame, or left blank. To transfer frame data the ``a=f``
key must be used in all escape codes.

First, to transfer a simple frame that has data for the full image area, the
escape codes used are exactly the same as for transferring image data, with the
addition of: ``a=f,i=<image id>`` or ``a=f,I=<image number>``.

If the frame has data for only a part of the image, you can specify the
rectangle for it using the ``x, y, s, v`` keys, for example::

    x=10,y=5,s=100,v=200  # A 100x200 rectangle with its top left corner at (10, 5)

Frames are created by composing the transmitted data onto a background canvas.
This canvas can be either a single color, or the pixels from a previous frame.
The composition can be of two types, either a simple replacement (``X=1``) key
or a full alpha blend (the default).

To use a background color for the canvas, specify the ``Y`` key as a 32-bit
RGBA color. For example::

    Y=4278190335 # 0xff0000ff opaque red
    Y=16711816   # 0x00ff0088 translucent green (alpha=0.53)

The default background color when none is specified is ``0`` i.e. a black,
transparent pixel.

To use the data from a previous frame, specify the ``c`` key which is a 1-based
frame number. Thus ``c=1`` refers to the root frame (the base image data),
``c=2`` refers to the second frame and so on.

If the frame is composed of multiple rectangular blocks, these can be expressed
by using the ``r`` key. When specifying the ``r`` key the data for an existing
frame is edited. The same composition operation as above happens, but now the
background canvas is the existing frame itself. ``r`` is a 1-based index, so
``r=1`` is the root frame (base image data), ``r=2`` is the second frame and so
on.

Finally, while transferring frame data, the frame *gap* can also be specified
using the ``z`` key. The gap is the number of milliseconds to wait before
displaying the next frame when the animation is running. A value of ``z=0`` is
ignored, ``z=positive number`` sets the gap to the specified number of
milliseconds and ``z=negative number`` creates a *gapless* frame. Gapless
frames are not displayed to the user since they are instantly skipped over,
however they can be useful as the base data for subsequent frames. For example,
for an animation where the background remains the same and a small object or two
move.

Controlling animations
~~~~~~~~~~~~~~~~~~~~~~~~~~

Clients can control animations by using the ``a=a`` key in the escape code sent
to the terminal.

The simplest is client driven animations, where the client transmits the frame
data and then also instructs the terminal to make a particular frame the current
frame.  To change the current frame, use the ``c`` key::

    <ESC>_Ga=a,i=3,c=7<ESC>\

This will make the seventh frame in the image with id ``3`` the current frame.

However, client driven animations can be sub-optimal, since the latency between
the client and terminal is unknown and variable especially over the network.
Also they require the client to remain running for the lifetime of the
animation, which is not desirable for cat like utilities.

Terminal driven animations are achieved by the client specifying *gaps* (time
in milliseconds) between frames and instructing the terminal to stop or start
the animation.

The animation state is controlled by the ``s`` key. ``s=1`` stops the
animation. ``s=2`` runs the animation, but in *loading* mode, in this mode when
reaching the last frame, instead of looping, the terminal will wait for the
arrival of more frames. ``s=3`` runs the animation normally, after the last
frame, the terminal loops back to the first frame. The number of loops can be
controlled by the ``v`` key. ``v=0`` is ignored, ``v=1`` is loop infinitely,
and any other positive number is loop ``number - 1`` times. Note that stopping
the animation resets the loop counter.

Finally, the *gap* for frames can be set using the ``z`` key. This can be
specified either when the frame is created as part of the transmit escape code
or separately using the animation control escape code. The *gap* is the time in
milliseconds to wait before displaying the next frame in the animation.
For example::

    <ESC>_Ga=a,i=7,r=3,z=48<ESC>\

This sets the gap for the third frame of the image with id ``7`` to ``48``
milliseconds. Note that *gapless* frames are not displayed to the user since
the next frame comes immediately, however they can be useful to store base data
for subsequent frames, such as in an animation with an object moving against a
static background.

In particular, the first frame or *root frame* is created with the base image
data and has no gap, so its gap must be set using this control code.

Composing animation frames
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. versionadded:: 0.22.0
   Support for frame composition

Clients can *compose* animation frames, this means that they can compose pixels
in rectangular regions from one frame onto another frame. This allows for fast
and low band-width modification of frames.

To achieve this use the ``a=c`` key. The source frame is specified with
``r=frame number`` and the destination frame as ``c=frame number``. The size of
the rectangle is specified as ``w=width,h=height`` pixels. If unspecified, the
full image width and height are used. The offset of the rectangle from the
top-left corner for the source frame is specified by the ``x,y`` keys and the
destination frame by the ``X,Y`` keys. The composition operation is specified
by the ``C`` key with the default being to alpha blend the source rectangle
onto the destination rectangle. With ``C=1`` it will be a simple replacement
of pixels. For example::

    <ESC>_Gi=1,r=7,c=9,w=23,h=27,X=4,Y=8,x=1,y=3<ESC>\

Will compose a ``23x27`` rectangle located at ``(4, 8)`` in the ``7th frame``
onto the rectangle located at ``(1, 3)`` in the ``9th frame``. These will be
in the image with ``id=1``.

If the frames or the image are not found the terminal emulator must
respond with `ENOENT`. If the rectangles go out of bounds of the image
the terminal must respond with `EINVAL`. If the source and destination frames are
the same and the rectangles overlap, the terminal must respond with `EINVAL`.


.. note::
   In kitty, doing a composition will cause a frame to be *fully rendered*
   potentially increasing its storage requirements, when the frame was previously
   stored as a set of operations on other frames. If this happens and there
   is not enough storage space, kitty will respond with ENOSPC.


Image persistence and storage quotas
-----------------------------------------

In order to avoid *Denial-of-Service* attacks, terminal emulators should have a
maximum storage quota for image data. It should allow at least a few full
screen images.  For example the quota in kitty is 320MB per buffer. When adding
a new image, if the total size exceeds the quota, the terminal emulator should
delete older images to make space for the new one. In kitty, for animations,
the additional frame data is stored on disk and has a separate, larger quota of
five times the base quota.


Control data reference
---------------------------

The table below shows all the control data keys as well as what values they can
take, and the default value they take when missing. All integers are 32-bit.

=======  ====================  =========  =================
Key      Value                 Default    Description
=======  ====================  =========  =================
``a``    Single character.     ``t``      The overall action this graphics command is performing.
         ``(a, c, d, f, ``                ``t`` - transmit data, ``T`` - transmit data and display image,
         ``p, q, t, T)``                  ``q`` - query terminal, ``p`` - put (display) previous transmitted image,
                                          ``d`` - delete image, ``f`` - transmit data for animation frames,
                                          ``a`` - control animation, ``c`` - compose animation frames

``q``    ``0, 1, 2``           ``0``      Suppress responses from the terminal to this graphics command.

**Keys for image transmission**
-----------------------------------------------------------
``f``    Positive integer.     ``32``     The format in which the image data is sent.
         ``(24, 32, 100)``.
``t``    Single character.     ``d``      The transmission medium used.
         ``(d, f, t, s)``.
``s``    Positive integer.     ``0``      The width of the image being sent.
``v``    Positive integer.     ``0``      The height of the image being sent.
``S``    Positive integer.     ``0``      The size of data to read from a file.
``O``    Positive integer.     ``0``      The offset from which to read data from a file.
``i``    Positive integer.
         ``(0 - 4294967295)``  ``0``      The image id
``I``    Positive integer.
         ``(0 - 4294967295)``  ``0``      The image number
``p``    Positive integer.
         ``(0 - 4294967295)``  ``0``      The placement id
``o``    Single character.     ``null``   The type of data compression.
         ``only z``
``m``    zero or one           ``0``      Whether there is more chunked data available.

**Keys for image display**
-----------------------------------------------------------
``x``    Positive integer      ``0``      The left edge (in pixels) of the image area to display
``y``    Positive integer      ``0``      The top edge (in pixels) of the image area to display
``w``    Positive integer      ``0``      The width (in pixels) of the image area to display. By default, the entire width is used
``h``    Positive integer      ``0``      The height (in pixels) of the image area to display. By default, the entire height is used
``X``    Positive integer      ``0``      The x-offset within the first cell at which to start displaying the image
``Y``    Positive integer      ``0``      The y-offset within the first cell at which to start displaying the image
``c``    Positive integer      ``0``      The number of columns to display the image over
``r``    Positive integer      ``0``      The number of rows to display the image over
``C``    Positive integer      ``0``      Cursor movement policy. ``0`` is the default, to move the cursor to after the image.
                                          ``1`` is to not move the cursor at all when placing the image.
``U``    Positive integer      ``0``      Set to ``1`` to create a virtual placement for a Unicode placeholder.
``z``    32-bit integer        ``0``      The *z-index* vertical stacking order of the image
``P``    Positive integer      ``0``      The id of a parent image for relative placement
``Q``    Positive integer      ``0``      The id of a placement in the parent image for relative placement
``H``    32-bit integer        ``0``      The offset in cells in the horizontal direction for relative placement
``V``    32-bit integer        ``0``      The offset in cells in the vertical direction for relative placement

**Keys for animation frame loading**
-----------------------------------------------------------
``x``    Positive integer      ``0``      The left edge (in pixels) of where the frame data should be updated
``y``    Positive integer      ``0``      The top edge (in pixels) of where the frame data should be updated
``c``    Positive integer      ``0``      The 1-based frame number of the frame whose image data serves as the base data
                                          when creating a new frame, by default the base data is black, fully transparent pixels
``r``    Positive integer      ``0``      The 1-based frame number of the frame that is being edited. By default, a new frame is created
``z``    32-bit integer        ``0``      The gap (in milliseconds) of this frame from the next one. A value of
                                          zero is ignored. Negative values create a *gapless* frame. If not specified,
                                          frames have a default gap of ``40ms``. The root frame defaults to zero gap.
``X``    Positive integer      ``0``      The composition mode for blending pixels when creating a new frame or
                                          editing a frame's data. The default is full alpha blending. ``1`` means a
                                          simple overwrite.
``Y``    Positive integer      ``0``      The background color for pixels not
                                          specified in the frame data. Must be in 32-bit RGBA format

**Keys for animation frame composition**
-----------------------------------------------------------

``c``    Positive integer      ``0``      The 1-based frame number of the frame whose image data serves as the overlaid data
``r``    Positive integer      ``0``      The 1-based frame number of the frame that is being edited.
``x``    Positive integer      ``0``      The left edge (in pixels) of the destination rectangle
``y``    Positive integer      ``0``      The top edge (in pixels) of the destination rectangle
``w``    Positive integer      ``0``      The width (in pixels) of the source and destination rectangles. By default, the entire width is used
``h``    Positive integer      ``0``      The height (in pixels) of the source and destination rectangles. By default, the entire height is used
``X``    Positive integer      ``0``      The left edge (in pixels) of the source rectangle
``Y``    Positive integer      ``0``      The top edge (in pixels) of the source rectangle
``C``    Positive integer      ``0``      The composition mode for blending
                                          pixels. Default is full alpha blending. ``1`` means a simple overwrite.


**Keys for animation control**
-----------------------------------------------------------
``s``    Positive integer      ``0``      ``1`` - stop animation, ``2`` - run animation, but wait for new frames, ``3`` - run animation
``r``    Positive integer      ``0``      The 1-based frame number of the frame that is being affected
``z``    32-bit integer        ``0``      The gap (in milliseconds) of this frame from the next one. A value of
                                          zero is ignored. Negative values create a *gapless* frame.
``c``    Positive integer      ``0``      The 1-based frame number of the frame that should be made the current frame
``v``    Positive integer      ``0``      The number of loops to play. ``0`` is
                                          ignored, ``1`` is play infinite and is the default and larger number
                                          means play that number ``-1`` loops


**Keys for deleting images**
-----------------------------------------------------------
``d``    Single character.     ``a``      What to delete.
         ``(
         a, A, c, C, n, N,
         i, I, p, P, q, Q, r,
         R, x, X, y, Y, z, Z
         )``.
=======  ====================  =========  =================


Interaction with other terminal actions
--------------------------------------------

When resetting the terminal, all images that are visible on the screen must be
cleared.  When switching from the main screen to the alternate screen buffer
(1049 private mode) all images in the alternate screen must be cleared, just as
all text is cleared. The clear screen escape code (usually ``<ESC>[2J``) should
also clear all images. This is so that the clear command works.

The other commands to erase text must have no effect on graphics.
The dedicated delete graphics commands must be used for those.

When scrolling the screen (such as when using index cursor movement commands,
or scrolling through the history buffer), images must be scrolled along with
text. When page margins are defined and the index commands are used, only
images that are entirely within the page area (between the margins) must be
scrolled. When scrolling them would cause them to extend outside the page area,
they must be clipped.
