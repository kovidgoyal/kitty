:tocdepth: 3

The terminal graphics protocol
==================================

The goal of this specification is to create a flexible and performant protocol
that allows the program running in the terminal, hereafter called the *client*,
to render arbitrary pixel (raster) graphics to the screen of the terminal
emulator. The major design goals are

 * Should not require terminal emulators to understand image formats.
 * Should allow specifying graphics to be drawn at individual pixel positions.
 * The graphics should integrate with the text, in particular it should be possible to draw graphics
   below as well as above the text, with alpha blending. The graphics should also scroll with the text, automatically.
 * Should use optimizations when the client is running on the same computer as the terminal emulator.

For some discussion regarding the design choices, see `#33
<https://github.com/kovidgoyal/kitty/issues/33>`_.

To see a quick demo, inside a |kitty| terminal run::

    kitty +kitten icat path/to/some/image.png

You can also see a screenshot with more sophisticated features such as
alpha-blending and text over graphics.

.. image:: https://user-images.githubusercontent.com/1308621/31647475-1188ab66-b326-11e7-8d26-24b937f1c3e8.png
    :alt: Demo of graphics rendering in kitty
    :align: center

Some programs that use the kitty graphics protocol:

 * `termpdf <https://github.com/dsanson/termpdf>`_ - a terminal PDF/DJVU/CBR viewer
 * `ranger <https://github.com/ranger/ranger>`_ - a terminal file manager, with
   image previews, see this `PR <https://github.com/ranger/ranger/pull/1077>`_
 * :doc:`kitty-diff <kittens/diff>` - a side-by-side terminal diff program with support for images
 * `neofetch <https://github.com/dylanaraps/neofetch>`_ - A command line system
   information tool


.. contents::


Getting the window size
-------------------------

In order to know what size of images to display and how to position them, the
client must be able to get the window size in pixels and the number of cells
per row and column. This can be done by using the ``TIOCGWINSZ`` ioctl.  Some
code to demonstrate its use

In C:

.. code-block:: c

    struct ttysize ts;
    ioctl(0, TIOCGWINSZ, &ts);
    printf("number of columns: %i, number of rows: %i, screen width: %i, screen height: %i\n", sz.ws_col, sz.ws_row, sz.ws_xpixel, sz.ws_ypixel);

In Python:

.. code-block:: python

    import array, fcntl, termios
    buf = array.array('H', [0, 0, 0, 0])
    fcntl.ioctl(sys.stdout, termios.TIOCGWINSZ, buf)
    print('number of columns: {}, number of rows: {}, screen width: {}, screen height: {}'.format(*buf))

Note that some terminals return ``0`` for the width and height values. Such
terminals should be modified to return the correct values.  Examples of
terminals that return correct values: ``kitty, xterm``

You can also use the *CSI t* escape code to get the screen size. Send
``<ESC>[14t`` to *stdout* and kitty will reply on *stdin* with
``<ESC>[4;<height>;<width>t`` where *height* and *width* are the window size in
pixels. This escape code is supported in many terminals, not just kitty.

A minimal example
------------------

Some minimal python code to display PNG images in kitty, using the most basic
features of the graphics protocol:

.. code-block:: python

   import sys
   from base64 import standard_b64encode

   def serialize_gr_command(cmd, payload=None):
      cmd = ','.join('{}={}'.format(k, v) for k, v in cmd.items())
      ans = []
      w = ans.append
      w(b'\033_G'), w(cmd.encode('ascii'))
      if payload:
         w(b';')
         w(payload)
      w(b'\033\\')
      return b''.join(ans)

   def write_chunked(cmd, data):
      data = standard_b64encode(data)
      while data:
         chunk, data = data[:4096], data[4096:]
         m = 1 if data else 0
         cmd['m'] = m
         sys.stdout.buffer.write(serialize_gr_command(cmd, chunk))
         sys.stdout.flush()
         cmd.clear()

   write_chunked({'a': 'T', 'f': 100}, open(sys.argv[-1], 'rb').read())


Save this script as :file:`png.py`, then you can use it to display any PNG
file in kitty as::

   python png.py file.png


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
indicates PNG data. The PNG format is supported for convenience and a compact way
of transmitting paletted images.

RGB and RGBA data
~~~~~~~~~~~~~~~~~~~

In these formats the pixel data is stored directly as 3 or 4 bytes per pixel, respectively.
When specifying images in this format, the image dimensions **must** be sent in the control data.
For example::

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

The client can send compressed image data to the terminal emulator, by specifying the
``o`` key. Currently, only zlib based deflate compression is supported, which is specified using
``o=z``. For example::

    <ESC>_Gf=24,s=10,v=20,o=z;<payload><ESC>\

This is the same as the example from the RGB data section, except that the
payload is now compressed using deflate. The terminal emulator will decompress
it before rendering. You can specify compression for any format. The terminal
emulator will decompress before interpreting the pixel data.


The transmission medium
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The transmission medium is specified using the ``t`` key. The ``t`` key defaults to ``d``
and can take the values:

==================    ============
Value of `t`          Meaning
==================    ============
``d``                 Direct (the data is transmitted within the escape code itself)
``f``                 A simple file
``t``                 A temporary file, the terminal emulator will delete the file after reading the pixel data
``s``                 A `POSIX shared memory object <http://man7.org/linux/man-pages/man7/shm_overview.7.html>`_.
                      The terminal emulator will delete it after reading the pixel data
==================    ============

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
base64 encoded then chunked up into chunks no larger than ``4096`` bytes. The client
then sends the graphics escape code as usual, with the addition of an ``m`` key that
must have the value ``1`` for all but the last chunk, where it must be ``0``. For example,
if the data is split into three chunks, the client would send the following
sequence of escape codes to the terminal emulator::

    <ESC>_Gs=100,v=30,m=1;<encoded pixel data first chunk><ESC>\
    <ESC>_Gm=1;<encoded pixel data second chunk><ESC>\
    <ESC>_Gm=0;<encoded pixel data last chunk><ESC>\

Note that only the first escape code needs to have the full set of control
codes such as width, height, format etc. Subsequent chunks must have
only the ``m`` key. The client **must** finish sending all chunks for a single image
before sending any other graphics related escape codes.


Detecting available transmission mediums
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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


Display images on screen
-----------------------------

Every transmitted image can be displayed an arbitrary number of times on the
screen, in different locations, using different parts of the source image, as
needed. You can either simultaneously transmit and display an image using the
action ``a=T``, or first transmit the image with a id, such as ``i=10`` and then display
it with ``a=p,i=10`` which will display the previously transmitted image at the current
cursor position. When specifying an image id, the terminal emulator will reply with an
acknowledgement code, which will be either::

    <ESC>_Gi=<id>;OK<ESC>\

when the image referred to by id was found, or::

    <ESC>_Gi=<id>;ENOENT:<some detailed error msg><ESC>\

when the image with the specified id was not found. This is similar to the
scheme described above for querying available transmission media, except that
here we are querying if the image with the specified id is available or needs to
be re-transmitted.

Controlling displayed image layout
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The image is rendered at the current cursor position, from the upper left corner of
the current cell. You can also specify extra ``X=3`` and ``Y=4`` pixel offsets to display from
a different origin within the cell. Note that the offsets must be smaller that the size of the cell.

By default, the entire image will be displayed (images wider than the available
width will be truncated on the right edge). You can choose a source rectangle (in pixels)
as the part of the image to display. This is done with the keys: ``x, y, w, h`` which specify
the top-left corner, width and height of the source rectangle.

You can also ask the terminal emulator to display the image in a specified rectangle
(num of columns / num of lines), using the control codes ``c,r``. ``c`` is the number of columns
and `r` the number of rows. The image will be scaled (enlarged/shrunk) as needed to fit
the specified area. Note that if you specify a start cell offset via the ``X,Y`` keys, it is not
added to the number of rows/columns.

Finally, you can specify the image *z-index*, i.e. the vertical stacking order. Images
placed in the same location with different z-index values will be blended if
they are semi-transparent. You can specify z-index values using the ``z`` key.
Negative z-index values mean that the images will be drawn under the text. This
allows rendering of text on top of images.

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
``a`` or ``A``       Delete all images visible on screen
``i`` or ``I``       Delete all images with the specified id, specified using the ``i`` key.
``c`` or ``C``       Delete all images that intersect with the current cursor position.
``p`` or ``P``       Delete all images that intersect a specific cell, the cell is specified using the ``x`` and ``y`` keys
``q`` or ``Q``       Delete all images that intersect a specific cell having a specific z-index. The cell and z-index is specified using the ``x``, ``y`` and ``z`` keys.
``x`` or ``X``       Delete all images that intersect the specified column, specified using the ``x`` key.
``y`` or ``Y``       Delete all images that intersect the specified row, specified using the ``y`` key.
``z`` or ``Z``       Delete all images that have the specified z-index, specified using the ``z`` key.
=================    ============



Some examples::

    <ESC>_Ga=d<ESC>\         # delete all visible images
    <ESC>_Ga=d,i=10<ESC>\    # delete the image with id=10
    <ESC>_Ga=Z,z=-1<ESC>\    # delete the images with z-index -1, also freeing up image data
    <ESC>_Ga=P,x=3,y=4<ESC>\ # delete all images that intersect the cell at (3, 4)

Image persistence and storage quotas
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In order to avoid *Denial-of-Service* attacks, terminal emulators should have a
maximum storage quota for image data. It should allow at least a few full
screen images.  For example the quota in kitty is 320MB per buffer. When adding
a new image, if the total size exceeds the quota, the terminal emulator should
delete older images to make space for the new one.


Control data reference
---------------------------

The table below shows all the control data keys as well as what values they can
take, and the default value they take when missing. All integers are 32-bit.

=======  ====================  =========  =================
Key      Value                 Default    Description
=======  ====================  =========  =================
``a``    Single character.     ``t``      The overall action this graphics command is performing.
         ``(t, T, q, p, d)``
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
``o``    Single character.     ``null``   The type of data compression.
         ``only z``
``m``    zero or one           ``0``      Whether there is more chunked data available.
**Keys for image display**
-----------------------------------------------------------
``x``    Positive integer      ``0``      The left edge (in pixels) of the image area to display
``y``    Positive integer      ``0``      The top edge (in pixels) of the image area to display
``w``    Positive integer      ``0``      The width (in pixels) of the image area to display. By default, the entire width is used.
``h``    Positive integer      ``0``      The height (in pixels) of the image area to display. By default, the entire height is used
``X``    Positive integer      ``0``      The x-offset within the first cell at which to start displaying the image
``Y``    Positive integer      ``0``      The y-offset within the first cell at which to start displaying the image
``c``    Positive integer      ``0``      The number of columns to display the image over
``r``    Positive integer      ``0``      The number of rows to display the image over
``z``    Integer               ``0``      The *z-index* vertical stacking order of the image
**Keys for deleting images**
-----------------------------------------------------------
``d``    Single character.     ``a``      What to delete.
         ``(a, A, c, C, i,
         I, p, P, q, Q, x, X,
         y, Y, z, Z)``.
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
