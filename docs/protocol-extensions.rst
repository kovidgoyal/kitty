Terminal protocol extensions
===================================

|kitty| has extensions to the legacy terminal protocol, to enable advanced
features. These are typically in the form of new or re-purposed escape codes.
While these extensions are currently |kitty| specific, it would be nice to get
some of them adopted more broadly, to push the state of terminal emulators
forward.

The goal of these extensions is to be as small and unobtrusive as possible,
while filling in some gaps in the existing xterm protocol. In particular, one of
the goals of this specification is explicitly not to "re-imagine" the TTY. The
TTY should remain what it is -- a device for efficiently processing text
received as a simple byte stream. Another objective is to only move the minimum
possible amount of extra functionality into the terminal program itself. This is
to make it as easy to implement these protocol extensions as possible, thereby
hopefully encouraging their widespread adoption.

If you wish to discuss these extensions, propose additions or changes to them,
please do so by opening issues in the `GitHub bug tracker
<https://github.com/kovidgoyal/kitty/issues>`__.


.. toctree::
   :maxdepth: 1

   underlines
   graphics-protocol
   keyboard-protocol
   text-sizing-protocol
   file-transfer-protocol
   desktop-notifications
   pointer-shapes
   unscroll
   color-stack
   deccara
   clipboard
   misc-protocol
