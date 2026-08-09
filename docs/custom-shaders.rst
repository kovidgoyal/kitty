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

.. highlight:: hlsl

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


Anatomy of a custom shader
----------------------------

Shaders in kitty are written in `slang <https://shader-slang.org/>`__
which is a shading language that compiles down to the actual shading language
used by the underlying platform. A custom shader consists of two parts, the
actual shader which is basically a single function that takes an input color
and some input uniforms and textures and outputs the resulting color. The
second part is a *pipeline* file, which is responsible for specifying how
different custom shaders are grouped together, ow they render, what animation
trigger events they respond to, etc. The two parts are described below.

Custom shaders are run at the very end of the kitty rendering pipeline, when
everything else has already been rendered. Note that all colors are in the
linear RGB color space and co-ordinates are in the traditional UV co-ordinate
system with its origin in the lower left corner and Y increasing upwards.

When you set the :opt:`custom_shaders XXX <custom_shaders>` setting in :file:`kitty.conf` kitty
tries to load a pipeline file with that name and if no pipeline file is found
but a shader with that name is found instead, it is loaded with a default
pipeline file. Loading takes place by first looking in the :file:`shaders`
sub-directory of the kitty config directory, if not found, among the shaders
shipped with kitty. So for shader ``XXX`` first ``XXX.pipeline`` and then
``XXX.slang`` are searched for.

The shader part
^^^^^^^^^^^^^^^^^

This is in a :file:`.slang` file. It must define a function called
``fragment_main()`` whose signature is:

.. literalinclude:: ../kitty/shaders/custom/sample.slang
   :start-at: public float4 fragment_main(
   :end-before: END_FUNCTION_SIGNATURE

The two structs passed into this function have the definition shown below:

.. literalinclude:: ../kitty/shaders/custom/types.slang
   :start-at: public struct KittyCustomShaderData {
   :end-before: END_TYPES_DEFINITION

Shaders take their inputs and use them to transform the color as they see fit.

The pipeline part
^^^^^^^^^^^^^^^^^^^^

TODO

Animation events
^^^^^^^^^^^^^^^^^^^

TODO
