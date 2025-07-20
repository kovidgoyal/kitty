#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

OPTIONS = '''\
--align
type=choices
choices=center,left,right
default=center
Horizontal alignment for the displayed image.


--place
Choose where on the screen to display the image. The image will be scaled to fit
into the specified rectangle. The syntax for specifying rectangles is
<:italic:`width`>x<:italic:`height`>@<:italic:`left`>x<:italic:`top`>.
All measurements are in cells (i.e. cursor positions) with the origin
:italic:`(0, 0)` at the top-left corner of the screen. Note that the :option:`--align`
option will horizontally align the image within this rectangle. By default, the image
is horizontally centered within the rectangle. Using place will cause the cursor to
be positioned at the top left corner of the image, instead of on the line after the image.


--scale-up
type=bool-set
When used in combination with :option:`--place` it will cause images that are
smaller than the specified area to be scaled up to use as much of the specified
area as possible.


--background
default=none
Specify a background color, this will cause transparent images to be composited
on top of the specified color.


--mirror
default=none
type=choices
choices=none,horizontal,vertical,both
Mirror the image about a horizontal or vertical axis or both.


--clear
type=bool-set
Remove all images currently displayed on the screen. Note that
this cannot work with terminal multiplexers such as tmux since
only the multiplexer can know the position of the screen.


--transfer-mode
type=choices
choices=detect,file,stream,memory
default=detect
Which mechanism to use to transfer images to the terminal. The default is to
auto-detect. :italic:`file` means to use a temporary file, :italic:`memory` means
to use shared memory, :italic:`stream` means to send the data via terminal
escape codes. Note that if you use the :italic:`file` or :italic:`memory` transfer
modes and you are connecting over a remote session then image display will not
work.


--detect-support
type=bool-set
Detect support for image display in the terminal. If not supported, will exit
with exit code 1, otherwise will exit with code 0 and print the supported
transfer mode to stderr, which can be used with the :option:`--transfer-mode`
option.


--detection-timeout
type=float
default=10
The amount of time (in seconds) to wait for a response from the terminal, when
detecting image display support.


--use-window-size
Instead of querying the terminal for the window size, use the specified size, which must
be of the format: width_in_cells,height_in_cells,width_in_pixels,height_in_pixels


--print-window-size
type=bool-set
Print out the window size as <:italic:`width`>x<:italic:`height`> (in pixels) and quit. This is a
convenience method to query the window size if using :code:`kitten icat`
from a scripting language that cannot make termios calls.


--stdin
type=choices
choices=detect,yes,no
default=detect
Read image data from STDIN. The default is to do it automatically, when STDIN is
not a terminal, but you can turn it off or on explicitly, if needed.


--silent
type=bool-set
Not used, present for legacy compatibility.


--engine
type=choices
choices=auto,builtin,magick
default=auto
The engine used for decoding and processing of images. The default is to use
the most appropriate engine.  The :code:`builtin` engine uses Go's native
imaging libraries. The :code:`magick` engine uses ImageMagick which requires
it to be installed on the system.


--z-index -z
default=0
Z-index of the image. When negative, text will be displayed on top of the image.
Use a double minus for values under the threshold for drawing images under cell
background colors. For example, :code:`--1` evaluates as -1,073,741,825.


--loop -l
default=-1
type=int
Number of times to loop animations. Negative values loop forever. Zero means
only the first frame of the animation is displayed. Otherwise, the animation
is looped the specified number of times.


--hold
type=bool-set
Wait for a key press before exiting after displaying the images.


--unicode-placeholder
type=bool-set
Use the Unicode placeholder method to display the images. Useful to display
images from within full screen terminal programs that do not understand the
kitty graphics protocol such as multiplexers or editors. See
:ref:`graphics_unicode_placeholders` for details. Note that when using this
method, images placed (with :option:`--place`) that do not fit on the screen,
will get wrapped at the screen edge instead of getting truncated. This
wrapping is per line and therefore the image will look like it is interleaved
with blank lines.


--passthrough
type=choices
choices=detect,tmux,none
default=detect
Whether to surround graphics commands with escape sequences that allow them to passthrough
programs like tmux. The default is to detect when running inside tmux and automatically use
the tmux passthrough escape codes. Note that when this option is enabled it implies
:option:`--unicode-placeholder` as well.


--image-id
type=int
default=0
The graphics protocol id to use for the created image. Normally, a random id is created if needed.
This option allows control of the id. When multiple images are sent, sequential ids starting from the specified id
are used. Valid ids are from 1 to 4294967295. Numbers outside this range are automatically wrapped.


--no-trailing-newline -n
type=bool-set
By default, the cursor is moved to the next line after displaying an image. This option, prevents that. Should not be used
when catting multiple images. Also has no effect when the :option:`--place` option is used.
'''

help_text = (
        'A cat like utility to display images in the terminal.'
        ' You can specify multiple image files and/or directories.'
        ' Directories are scanned recursively for image files. If STDIN'
        ' is not a terminal, image data will be read from it as well.'
        ' You can also specify HTTP(S) or FTP URLs which will be'
        ' automatically downloaded and displayed.'
)
usage = 'image-file-or-url-or-directory ...'


if __name__ == '__main__':
    raise SystemExit('This should be run as kitten icat')
elif __name__ == '__doc__':
    import sys

    from kitty.simple_cli_definitions import CompletionSpec
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = lambda: OPTIONS.format()
    cd['help_text'] = help_text
    cd['short_desc'] = 'Display images in the terminal'
    cd['args_completion'] = CompletionSpec.from_string('type:file mime:image/* group:Images')
