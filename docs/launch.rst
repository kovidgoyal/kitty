Launching programs in new windows/tabs
========================================

.. program:: launch


|kitty| has a :code:`launch` action that can be used to run arbitrary programs
in news windows/tabs. It can be mapped to user defined shortcuts in kitty.conf.
It is very powerful and allows sending the contents of
the current window to the launched program, as well as many other options.

In the simplest form, you can use it to open a new kitty window running the
shell, as shown below::

    map f1 launch

To run a different program simply pass the command line as arguments to
launch::

    map f1 launch vim path/to/some/file


To open a new window with the same working directory as the currently
active window::

    map f1 launch --cwd=current

To open the new window in a new tab::

    map f1 launch --type=tab

To pass the contents of the current screen and scrollback to the started process::

    map f1 launch --stdin-source=@screen_scrollback less

There are many more powerful options, refer to the complete list below.

The piping environment
--------------------------

When using :option:`launch --stdin-source`, the program to which the data is
piped has a special environment variable declared, ``KITTY_PIPE_DATA`` whose
contents are::

   KITTY_PIPE_DATA={scrolled_by}:{cursor_x},{cursor_y}:{lines},{columns}

where ``scrolled_by`` is the number of lines kitty is currently scrolled by,
``cursor_(x|y)`` is the position of the cursor on the screen with ``(1,1)``
being the top left corner and ``{lines},{columns}`` being the number of rows
and columns of the screen.


Syntax reference
------------------

.. include:: /generated/launch.rst
