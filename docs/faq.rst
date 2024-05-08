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
these characters are followed by a space or en-space (U+2002) in which case
kitty makes use of the extra cell to render them in two cells. This behavior
can be turned off for specific symbols using :opt:`narrow_symbols`.


Using a color theme with a background color does not work well in vim?
-----------------------------------------------------------------------

Sadly, vim has very poor out-of-the-box detection for modern terminal features.
Furthermore, it `recently broke detection even more <https://github.com/vim/vim/issues/11729>`__.
It kind of, but not really, supports terminfo, except it overrides it with its own hard-coded
values when it feels like it. Worst of all, it has no ability to detect modern
features not present in terminfo, at all, even security sensitive ones like
bracketed paste.

Thankfully, probably as a consequence of this lack of detection, vim allows users to
configure these low level details. So, to make vim work well with any modern
terminal, including kitty, add the following to your :file:`~/.vimrc`.

.. code-block:: vim

    " Mouse support
    set mouse=a
    set ttymouse=sgr
    set balloonevalterm
    " Styled and colored underline support
    let &t_AU = "\e[58:5:%dm"
    let &t_8u = "\e[58:2:%lu:%lu:%lum"
    let &t_Us = "\e[4:2m"
    let &t_Cs = "\e[4:3m"
    let &t_ds = "\e[4:4m"
    let &t_Ds = "\e[4:5m"
    let &t_Ce = "\e[4:0m"
    " Strikethrough
    let &t_Ts = "\e[9m"
    let &t_Te = "\e[29m"
    " Truecolor support
    let &t_8f = "\e[38:2:%lu:%lu:%lum"
    let &t_8b = "\e[48:2:%lu:%lu:%lum"
    let &t_RF = "\e]10;?\e\\"
    let &t_RB = "\e]11;?\e\\"
    " Bracketed paste
    let &t_BE = "\e[?2004h"
    let &t_BD = "\e[?2004l"
    let &t_PS = "\e[200~"
    let &t_PE = "\e[201~"
    " Cursor control
    let &t_RC = "\e[?12$p"
    let &t_SH = "\e[%d q"
    let &t_RS = "\eP$q q\e\\"
    let &t_SI = "\e[5 q"
    let &t_SR = "\e[3 q"
    let &t_EI = "\e[1 q"
    let &t_VS = "\e[?12l"
    " Focus tracking
    let &t_fe = "\e[?1004h"
    let &t_fd = "\e[?1004l"
    execute "set <FocusGained>=\<Esc>[I"
    execute "set <FocusLost>=\<Esc>[O"
    " Window title
    let &t_ST = "\e[22;2t"
    let &t_RT = "\e[23;2t"

    " vim hardcodes background color erase even if the terminfo file does
    " not contain bce. This causes incorrect background rendering when
    " using a color theme with a background color in terminals such as
    " kitty that do not support background color erase.
    let &t_ut=''

These settings must be placed **before** setting the ``colorscheme``. It is
also important that the value of the vim ``term`` variable is not changed
after these settings.

I get errors about the terminal being unknown or opening the terminal failing or functional keys like arrow keys don't work?
-------------------------------------------------------------------------------------------------------------------------------

These issues all have the same root cause: the kitty terminfo files not being
available. The most common way this happens is SSHing into a computer that does
not have the kitty terminfo files. The simplest fix for that is running::

    kitten ssh myserver

It will automatically copy over the terminfo files and also magically enable
:doc:`shell integration </shell-integration>` on the remote machine.

This :doc:`ssh kitten <kittens/ssh>` takes all the same command line arguments
as :program:`ssh`, you can alias it to something small in your shell's rc files
to avoid having to type it each time::

    alias s="kitten ssh"

If this does not work, see :ref:`manual_terminfo_copy` for alternative ways to
get the kitty terminfo files onto a remote computer.

The next most common reason for this is if you are running commands as root
using :program:`sudo` or :program:`su`. These programs often filter the
:envvar:`TERMINFO` environment variable which is what points to the kitty
terminfo files.

First, make sure the :envvar:`TERM` is set to ``xterm-kitty`` in the sudo
environment. By default, it should be automatically copied over.

If you are using a well maintained Linux distribution, it will have a
``kitty-terminfo`` package that you can simply install to make the kitty
terminfo files available system-wide. Then the problem will no longer occur.

Alternately, you can configure :program:`sudo` to preserve :envvar:`TERMINFO`
by running ``sudo visudo`` and adding the following line::

    Defaults env_keep += "TERM TERMINFO"

If none of these are suitable for you, you can run sudo as ::

    sudo TERMINFO="$TERMINFO"

This will make :envvar:`TERMINFO` available
in the sudo environment. Create an alias in your shell rc files to make this
convenient::

    alias sudo="sudo TERMINFO=\"$TERMINFO\""

If you have double width characters in your prompt, you may also need to
explicitly set a UTF-8 locale, like::

    export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8


I cannot use the key combination X in program Y?
-------------------------------------------------------

First, run::

    kitten show-key -m kitty

Press the key combination X. If the kitten reports the key press
that means kitty is correctly sending the key press to terminal programs.
You need to report the issue to the developer of the terminal program. Most
likely they have not added support for :doc:`/keyboard-protocol`.

If the kitten does not report it, it means that the key is bound to some action
in kitty. You can unbind it in :file:`kitty.conf` with:

.. code-block:: conf

   map X no_op

Here X is the keys you press on the keyboard. So for example
:kbd:`ctrl+shift+1`.


How do I change the colors in a running kitty instance?
------------------------------------------------------------

The easiest way to do it is to use the :doc:`themes kitten </kittens/themes>`,
to choose a new color theme. Simply run::

    kitten themes

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
   fonts. There is no need, simply install the standalone ``Symbols Nerd Font Mono``
   (the file :file:`NerdFontsSymbolsOnly.zip` from the `Nerd Fonts releases page
   <https://github.com/ryanoasis/nerd-fonts/releases>`__). kitty should pick up
   symbols from it automatically, and you can tell it to do so explicitly in
   case it doesn't with the :opt:`symbol_map` directive::

        # Nerd Fonts v3.1.0

        symbol_map U+e000-U+e00a,U+ea60-U+ebeb,U+e0a0-U+e0c8,U+e0ca,U+e0cc-U+e0d4,U+e200-U+e2a9,U+e300-U+e3e3,U+e5fa-U+e6b1,U+e700-U+e7c5,U+f000-U+f2e0,U+f300-U+f372,U+f400-U+f532,U+f0001-U+f1af0 Symbols Nerd Font Mono

   Those Unicode symbols not in the `Unicode private use areas
   <https://en.wikipedia.org/wiki/Private_Use_Areas>`__ are
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

.. image:: https://github.com/k0nserv/kitty-icon/raw/main/kitty.iconset/icon_256x256.png
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

.. image:: https://github.com/eccentric-j/eccentric-icons/raw/main/icons/kitty-terminal/2d/kitty-preview.png
   :target: https://github.com/eccentric-j/eccentric-icons
   :width: 256

.. image:: https://github.com/eccentric-j/eccentric-icons/raw/main/icons/kitty-terminal/3d/kitty-preview.png
   :target: https://github.com/eccentric-j/eccentric-icons
   :width: 256

.. image:: https://github.com/sodapopcan/kitty-icon/raw/main/kitty.app.png
   :target: https://github.com/sodapopcan/kitty-icon
   :width: 256

On macOS and X11 you can put :file:`kitty.app.icns` (macOS only) or :file:`kitty.app.png` in the
:ref:`kitty configuration directory <confloc>`, and this icon will be applied
automatically at startup. On X11, this will set the icon for kitty windows.

Unfortunately, on macOS, Apple's Dock does not change its cached icon so the
custom icon will revert when kitty is quit. Run the following to force the Dock
to update its cached icons:

.. code-block:: sh

    rm /var/folders/*/*/*/com.apple.dock.iconcache; killall Dock

If you prefer not to keep a custom icon in the kitty config folder, on macOS, you can
also set it with the following command:

.. code-block:: sh

    # Set kitty.icns as the icon for currently running kitty
    kitty +runpy 'from kitty.fast_data_types import cocoa_set_app_icon; import sys; cocoa_set_app_icon(*sys.argv[1:]); print("OK")' kitty.icns

    # Set the icon for app bundle specified by the path
    kitty +runpy 'from kitty.fast_data_types import cocoa_set_app_icon; import sys; cocoa_set_app_icon(*sys.argv[1:]); print("OK")' /path/to/icon.png /Applications/kitty.app

You can also change the icon manually by following the steps:

#. Find :file:`kitty.app` in the Applications folder, select it and press :kbd:`⌘+I`
#. Drag :file:`kitty.icns` onto the application icon in the kitty info pane
#. Delete the icon cache and restart Dock:

.. code-block:: sh

    rm /var/folders/*/*/*/com.apple.dock.iconcache; killall Dock


How do I map key presses in kitty to different keys in the terminal program?
--------------------------------------------------------------------------------------

This is accomplished by using ``map`` with :ac:`send_key` in :file:`kitty.conf`.
For example::

    map alt+s send_key ctrl+s

This causes the program running in kitty to receive the :kbd:`ctrl+s` key when
you press the :kbd:`alt+s` key. To see this in action, run::

    kitten show-key -m kitty

Which will print out what key events it receives. To send arbitrary text rather
than a key press, see :sc:`send_text <send_text>` instead.


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

Using ancient versions of tmux such as 1.8 will cause gibberish on screen when
pressing keys (:iss:`3541`).

If you are using tmux with multiple terminals or you start it under one terminal
and then switch to another and these terminals have different :envvar:`TERM`
variables, tmux will break. You will need to restart it as tmux does not support
multiple terminfo definitions.

Displaying images while inside programs such as nvim or ranger may not work
depending on whether those programs have adopted support for the :ref:`unicode
placeholders <graphics_unicode_placeholders>` workaround that kitty created
for tmux refusing to support images.

If you use any of the advanced features that kitty has innovated, such as
:doc:`styled underlines </underlines>`, :doc:`desktop notifications
</desktop-notifications>`, :doc:`extended keyboard support
</keyboard-protocol>`, :doc:`file transfer </kittens/transfer>`, :doc:`the ssh
kitten </kittens/ssh>`, :doc:`shell integration </shell-integration>` etc. they may or may not work,
depending on the whims of tmux's maintainer, your version of tmux, etc.


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
