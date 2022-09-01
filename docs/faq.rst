Frequently Asked Questions
==============================

.. highlight:: sh

Some special symbols are rendered small/truncated in kitty?
-----------------------------------------------------------

The number of cells a Unicode character takes up are controlled by the Unicode
standard. All characters are rendered in a single cell unless the Unicode
standard says they should be rendered in two cells. When a symbol does not fit,
it will either be rescaled to be smaller or truncated (depending on how much
extra space it needs). This is often different from other terminals which just
let the character overflow into neighboring cells, which is fine if the
neighboring cell is empty, but looks terrible if it is not.

Some programs, like Powerline, vim with fancy gutter symbols/status-bar, etc.
use Unicode characters from the private use area to represent symbols. Often
these symbols are wide and should be rendered in two cells. However, since
private use area symbols all have their width set to one in the Unicode
standard, |kitty| renders them either smaller or truncated. The exception is if
these characters are followed by a space or empty cell in which case kitty
makes use of the extra cell to render them in two cells. This behavior can be
turned off for specific symbols using :opt:`narrow_symbols`.


Using a color theme with a background color does not work well in vim?
-----------------------------------------------------------------------

First make sure you have not changed the :envvar:`TERM` environment variable, it
should be ``xterm-kitty``. vim uses *background color erase* even if the
terminfo file does not contain the ``bce`` capability. This is a bug in vim. You
can work around it by adding the following to your vimrc::

    let &t_ut=''

See :doc:`here <deccara>` for why |kitty| does not support background color
erase.


I get errors about the terminal being unknown or opening the terminal failing when SSHing into a different computer?
-----------------------------------------------------------------------------------------------------------------------

This happens because the |kitty| terminfo files are not available on the server.
You can ssh in using the following command which will automatically copy the
terminfo files to the server::

    kitty +kitten ssh myserver

This :doc:`ssh kitten <kittens/ssh>` takes all the same command line arguments
as :program:`ssh`, you can alias it to something small in your shell's rc files
to avoid having to type it each time::

    alias s="kitty +kitten ssh"

If the ssh kitten fails, use the following one-liner instead (it is slower as it
needs to ssh into the server twice, but will work with most servers)::

    infocmp -a xterm-kitty | ssh myserver tic -x -o \~/.terminfo /dev/stdin

If you are behind a proxy (like Balabit) that prevents this, or :program:`tic`
comes with macOS that does not support reading from STDIN, you must redirect the
first command to a file, copy that to the server and run :program:`tic`
manually. If you connect to a server, embedded or Android system that doesn't
have :program:`tic`, copy over your local file terminfo to the other system as
:file:`~/.terminfo/x/xterm-kitty`.

Really, the correct solution for this is to convince the OpenSSH maintainers to
have :program:`ssh` do this automatically, if possible, when connecting to a
server, so that all terminals work transparently.

If the server is running FreeBSD, or another system that relies on termcap
rather than terminfo, you will need to convert the terminfo file on your local
machine by running (on local machine with |kitty|)::

    infocmp -CrT0 xterm-kitty

The output of this command is the termcap description, which should be appended
to :file:`/usr/share/misc/termcap` on the remote server. Then run the following
command to apply your change (on the server)::

    cap_mkdb /usr/share/misc/termcap


Keys such as arrow keys, backspace, delete, home/end, etc. do not work when using su or sudo?
-------------------------------------------------------------------------------------------------

Make sure the :envvar:`TERM` environment variable, is ``xterm-kitty``.  And
either the :envvar:`TERMINFO` environment variable points to a directory
containing :file:`x/xterm-kitty` or that file is under :file:`~/.terminfo/x/`.

For macOS, you may also need to put that file under :file:`~/.terminfo/78/`::

    mkdir -p ~/.terminfo/{78,x}
    ln -snf ../x/xterm-kitty ~/.terminfo/78/xterm-kitty
    tic -x -o ~/.terminfo "$KITTY_INSTALLATION_DIR/terminfo/kitty.terminfo"

Note that :program:`sudo` might remove :envvar:`TERMINFO`. Then setting it at
the shell prompt can be too late, because command line editing may not be
reinitialized. In that case you can either ask :program:`sudo` to set it or if
that is not supported, insert an :program:`env` command before starting the
shell, or, if not possible, after sudo start another shell providing the right
terminfo path::

    sudo … TERMINFO=$HOME/.terminfo bash -i
    sudo … env TERMINFO=$HOME/.terminfo bash -i
    TERMINFO=/home/ORIGINALUSER/.terminfo exec bash -i

You can configure :program:`sudo` to preserve :envvar:`TERMINFO` by running
``sudo visudo`` and adding the following line::

    Defaults env_keep += "TERM TERMINFO"

If you have double width characters in your prompt, you may also need to
explicitly set a UTF-8 locale, like::

    export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8


How do I change the colors in a running kitty instance?
------------------------------------------------------------

The easiest way to do it is to use the :doc:`themes kitten </kittens/themes>`,
to choose a new color theme. Simply run::

    kitty +kitten themes

And choose your theme from the list.

You can also define keyboard shortcuts to set colors, for example::

    map f1 set_colors --configured /path/to/some/config/file/colors.conf

Or you can enable :doc:`remote control <remote-control>` for |kitty| and use
:ref:`at-set-colors`. The shortcut mapping technique has the same syntax as the
remote control command, for details, see :ref:`at-set-colors`.

To change colors when SSHing into a remote host, use the :opt:`color_scheme
<kitten-ssh.color_scheme>` setting for the :doc:`ssh kitten <kittens/ssh>`.

Additionally, You can use the
`OSC terminal escape codes <https://invisible-island.net/xterm/ctlseqs/ctlseqs.html#h3-Operating-System-Commands>`__
to set colors. Examples of using OSC escape codes to set colors::

    Change the default foreground color:
    printf '\x1b]10;#ff0000\x1b\\'
    Change the default background color:
    printf '\x1b]11;blue\x1b\\'
    Change the cursor color:
    printf '\x1b]12;blue\x1b\\'
    Change the selection background color:
    printf '\x1b]17;blue\x1b\\'
    Change the selection foreground color:
    printf '\x1b]19;blue\x1b\\'
    Change the nth color (0 - 255):
    printf '\x1b]4;n;green\x1b\\'

You can use various syntaxes/names for color specifications in the above
examples. See `XParseColor <https://linux.die.net/man/3/xparsecolor>`__
for full details.

If a ``?`` is given rather than a color specification, kitty will respond
with the current value for the specified color.


How do I specify command line options for kitty on macOS?
---------------------------------------------------------------

Apple does not want you to use command line options with GUI applications. To
workaround that limitation, |kitty| will read command line options from the file
:file:`<kitty config dir>/macos-launch-services-cmdline` when it is launched
from the GUI, i.e. by clicking the |kitty| application icon or using
``open -a kitty``. Note that this file is *only read* when running via the GUI.

You can, of course, also run |kitty| from a terminal with command line options,
using: :file:`/Applications/kitty.app/Contents/MacOS/kitty`.

And within |kitty| itself, you can always run |kitty| using just ``kitty`` as it
cleverly adds itself to the :envvar:`PATH`.


I catted a binary file and now kitty is hung?
-----------------------------------------------

**Never** output unknown binary data directly into a terminal.

Terminals have a single channel for both data and control. Certain bytes
are control codes. Some of these control codes are of arbitrary length, so if
the binary data you output into the terminal happens to contain the starting
sequence for one of these control codes, the terminal will hang waiting for the
closing sequence. Press :sc:`reset_terminal` to reset the terminal.

If you do want to cat unknown data, use ``cat -v``.


kitty is not able to use my favorite font?
---------------------------------------------

|kitty| achieves its stellar performance by caching alpha masks of each rendered
character on the GPU, and rendering them all in parallel. This means it is a
strictly character cell based display. As such it can use only monospace fonts,
since every cell in the grid has to be the same size. Furthermore, it needs
fonts to be freely resizable, so it does not support bitmapped fonts.

.. note::
   If you are trying to use a font patched with `Nerd Fonts
   <https://nerdfonts.com/>`__ symbols, don't do that as patching destroys
   fonts. There is no need, simply install the standalone ``Symbols Nerd Font``
   (the file :file:`NerdFontsSymbolsOnly.zip` from the `Nerd Fonts releases page
   <https://github.com/ryanoasis/nerd-fonts/releases>`__). kitty should pick up
   symbols from it automatically, and you can tell it to do so explicitly in
   case it doesn't with the :opt:`symbol_map` directive::

        symbol_map U+23FB-U+23FE,U+2665,U+26A1,U+2B58,U+E000-U+E00A,U+E0A0-U+E0A3,U+E0B0-U+E0C8,U+E0CA,U+E0CC-U+E0D2,U+E0D4,U+E200-U+E2A9,U+E300-U+E3E3,U+E5FA-U+E62F,U+E700-U+E7C5,U+F000-U+F2E0,U+F300-U+F31C,U+F400-U+F4A9,U+F500-U+F8FF Symbols Nerd Font

   Those Unicode symbols beyond the ``E000-F8FF`` Unicode private use area are
   not included.

If your font is not listed in ``kitty +list-fonts`` it means that it is not
monospace or is a bitmapped font. On Linux you can list all monospace fonts
with::

    fc-list : family spacing outline scalable | grep -e spacing=100 -e spacing=90 | grep -e outline=True | grep -e scalable=True

Note that the spacing property is calculated by fontconfig based on actual glyph
widths in the font. If for some reason fontconfig concludes your favorite
monospace font does not have ``spacing=100`` you can override it by using the
following :file:`~/.config/fontconfig/fonts.conf`::

    <?xml version="1.0"?>
    <!DOCTYPE fontconfig SYSTEM "fonts.dtd">
    <fontconfig>
    <match target="scan">
        <test name="family">
            <string>Your Font Family Name</string>
        </test>
        <edit name="spacing">
            <int>100</int>
        </edit>
    </match>
    </fontconfig>

After creating (or modifying) this file, you may need to run the following
command to rebuild your fontconfig cache::

    fc-cache -r

Then, the font will be available in ``kitty +list-fonts``.


How can I assign a single global shortcut to bring up the kitty terminal?
-----------------------------------------------------------------------------

Bringing up applications on a single key press is the job of the window
manager/desktop environment. For ways to do it with kitty (or indeed any
terminal) in different environments,
see :iss:`here <45>`.


I do not like the kitty icon!
-------------------------------

There are many alternate icons available, click on an icon to visit its
homepage:

.. image:: https://github.com/k0nserv/kitty-icon/raw/main/icon_512x512.png
   :target: https://github.com/k0nserv/kitty-icon
   :width: 256

.. image:: https://github.com/DinkDonk/kitty-icon/raw/main/kitty-dark.png
   :target: https://github.com/DinkDonk/kitty-icon
   :width: 256

.. image:: https://github.com/DinkDonk/kitty-icon/raw/main/kitty-light.png
   :target: https://github.com/DinkDonk/kitty-icon
   :width: 256

.. image:: https://github.com/hristost/kitty-alternative-icon/raw/main/kitty_icon.png
   :target: https://github.com/hristost/kitty-alternative-icon
   :width: 256

.. image:: https://github.com/igrmk/whiskers/raw/main/whiskers.svg
   :target: https://github.com/igrmk/whiskers
   :width: 256

.. image:: https://github.com/samholmes/whiskers/raw/main/whiskers.png
   :target: https://github.com/samholmes/whiskers
   :width: 256

On macOS you can change the icon by following the steps:

#. Find :file:`kitty.app` in the Applications folder, select it and press :kbd:`⌘+I`
#. Drag :file:`kitty.icns` onto the application icon in the kitty info pane
#. Delete the icon cache and restart Dock::

    $ rm /var/folders/*/*/*/com.apple.dock.iconcache; killall Dock


How do I map key presses in kitty to different keys in the terminal program?
--------------------------------------------------------------------------------------

This is accomplished by using ``map`` with :sc:`send_text <send_text>` in :file:`kitty.conf`.
For example::

    map alt+s send_text normal,application \x13

This maps :kbd:`alt+s` to :kbd:`ctrl+s`. To figure out what bytes to use for
the :sc:`send_text <send_text>` you can use the ``show_key`` kitten. Run::

    kitty +kitten show_key

Then press the key you want to emulate. Note that this kitten will only show
keys that actually reach the terminal program, in particular, keys mapped to
actions in kitty will not be shown. To check those first map them to
:ac:`no_op`. You can also start a kitty instance without any shortcuts to
interfere::

    kitty -o clear_all_shortcuts=yes kitty +kitten show_key


How do I open a new window or tab with the same working directory as the current window?
--------------------------------------------------------------------------------------------

In :file:`kitty.conf` add the following::

    map f1 launch --cwd=current
    map f2 launch --cwd=current --type=tab

Pressing :kbd:`F1` will open a new kitty window with the same working directory
as the current window. The :doc:`launch command <launch>` is very powerful,
explore :doc:`its documentation <launch>`.


Things behave differently when running kitty from system launcher vs. from another terminal?
-----------------------------------------------------------------------------------------------

This will be because of environment variables. When you run kitty from the
system launcher, it gets a default set of system environment variables. When
you run kitty from another terminal, you are actually running it from a shell,
and the shell's rc files will have setup a whole different set of environment
variables which kitty will now inherit.

You need to make sure that the environment variables you define in your shell's
rc files are either also defined system wide or via the :opt:`env` directive in
:file:`kitty.conf`. Common environment variables that cause issues are those
related to localization, such as :envvar:`LANG`, ``LC_*`` and loading of
configuration files such as ``XDG_*``, :envvar:`KITTY_CONFIG_DIRECTORY`.

To see the environment variables that kitty sees, you can add the following
mapping to :file:`kitty.conf`::

    map f1 show_kitty_env_vars

then pressing :kbd:`F1` will show you the environment variables kitty sees.

This problem is most common on macOS, as Apple makes it exceedingly difficult to
setup environment variables system-wide, so people end up putting them in all
sorts of places where they may or may not work.


I am using tmux and have a problem
--------------------------------------

First, terminal multiplexers are :iss:`a bad idea <391#issuecomment-638320745>`,
do not use them, if at all possible. kitty contains features that do all of what
tmux does, but better, with the exception of remote persistence (:iss:`391`).
If you still want to use tmux, read on.

Image display will not work, see `tmux issue
<https://github.com/tmux/tmux/issues/1391>`__.

Using ancient versions of tmux such as 1.8 will cause gibberish on screen when
pressing keys (:iss:`3541`).

If you are using tmux with multiple terminals or you start it under one terminal
and then switch to another and these terminals have different :envvar:`TERM`
variables, tmux will break. You will need to restart it as tmux does not support
multiple terminfo definitions.

If you use any of the advanced features that kitty has innovated, such as
:doc:`styled underlines </underlines>`, :doc:`desktop notifications
</desktop-notifications>`, :doc:`extended keyboard support
</keyboard-protocol>`, etc. they may or may not work, depending on the whims of
tmux's maintainer, your version of tmux, etc.


I opened and closed a lot of windows/tabs and top shows kitty's memory usage is very high?
-------------------------------------------------------------------------------------------

:program:`top` is not a good way to measure process memory usage. That is
because on modern systems, when allocating memory to a process, the C library
functions will typically allocate memory in large blocks, and give the process
chunks of these blocks. When the process frees a chunk, the C library will not
necessarily release the underlying block back to the OS. So even though the
application has released the memory, :program:`top` will still claim the process
is using it.

To check for memory leaks, instead use a tool like `Valgrind
<https://valgrind.org/>`__. Run::

    PYTHONMALLOC=malloc valgrind --tool=massif kitty

Now open lots of tabs/windows, generate lots of output using tools like find/yes
etc. Then close all but one window. Do some random work for a few seconds in
that window, maybe run yes or find again. Then quit kitty and run::

    massif-visualizer massif.out.*

You will see the allocations graph goes up when you opened the windows, then
goes back down when you closed them, indicating there were no memory leaks.

For those interested, you can get a similar profile out of :program:`valgrind`
as you get with :program:`top` by adding ``--pages-as-heap=yes`` then you will
see that memory allocated in malloc is not freed in free. This can be further
refined if you use ``glibc`` as your C library by setting the environment
variable ``MALLOC_MMAP_THRESHOLD_=64``. This will cause free to actually free
memory allocated in sizes of more than 64 bytes. With this set, memory usage
will climb high, then fall when closing windows, but not fall all the way back.
The remaining used memory can be investigated using valgrind again, and it will
come from arenas in the GPU drivers and the per thread arenas glibc's malloc
maintains. These too allocate memory in large blocks and don't release it back
to the OS immediately.


Why does kitty sometimes start slowly on my Linux system?
-------------------------------------------------------------------------------------------

|kitty| takes no longer (within 100ms) to start than other similar GPU terminal
emulators, (and may be faster than some). If |kitty| occasionally takes a long
time to start, it could be a power management issue with the graphics card. On
a multi-GPU system (which many modern laptops are, having a power efficient GPU
that's built into the processor and a power hungry dedicated one that's usually
off), even if the answer of the GPU will only be "don't use me".

For example, if you have a system with an AMD CPU and an NVIDIA GPU, and you
know that you want to use the lower powered card to save battery life and
because kitty does not require a powerful GPU to function, you can choose not
to wake up the dedicated card, which has been reported on at least one system
(:iss:`4292`) to take ≈2 seconds, by running |kitty| as::

    MESA_LOADER_DRIVER_OVERRIDE=radeonsi __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json kitty

The correct command will depend on your situation and hardware.
``__EGL_VENDOR_LIBRARY_FILENAMES`` instructs the GL dispatch library to use
:file:`libEGL_mesa.so` and ignore :file:`libEGL_nvidia.so` also available on the
system, which will wake the NVIDIA card during device enumeration.
``MESA_LOADER_DRIVER_OVERRIDE`` also assures that Mesa won't offer any NVIDIA
card during enumeration, and will instead just use :file:`radeonsi_dri.so`.
