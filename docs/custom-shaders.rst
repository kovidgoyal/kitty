Custom Shaders
===================

.. versionadded:: 0.49.0

.. highlight:: conf

Custom shaders in kitty are event driven and allow for all manner of visual
effects from the fun and blingy to useful visual aides. Users can write their
own custom shaders or use some from the large set that ship with kitty.
Browse the categories below to watch some custom shaders that ship with kitty in
action. To use a custom shader add :opt:`custom_shaders` to :file:`kitty.conf`,
for example::

    custom_shaders inside-the-matrix

.. role:: small-dim(raw)
   :format: html
   :class: sd-text-muted small code literal


Cursor trails
----------------

You must have enable cursor trails with something like ``cursor_trail 1`` in :file:`kitty.conf` for
these shaders to take effect.

.. include:: generated/custom-shaders-cursor-trails.rst

Animated backgrounds
---------------------

.. include:: generated/custom-shaders-backgrounds.rst

Mouse effects
---------------

.. include:: generated/custom-shaders-mouse.rst

