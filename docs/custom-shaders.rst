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

You can see the code for the custom shaders that ship with kitty :repo_folder:`here
<kitty/shaders/custom>`.

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

Navigation
---------------

.. include:: generated/custom-shaders-navigation.rst



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

A pipeline file (:file:`.pipeline`) is a plain text file that controls how
one or more shaders are assembled into a rendering pipeline. Lines starting
with ``#`` are comments; blank lines are ignored.

**Top-level directives** (outside any group):

``slot end``
    The rendering slot. Currently only ``end`` is supported (the shaders run
    after all of kitty's own rendering is complete). This is the default and
    can be omitted.

``textures a b persist``
    Declares which named textures the pipeline uses. List only the names you
    need — each one causes an off-screen framebuffer to be allocated. The
    available names are ``a``, ``b``, and ``persist``; see :ref:`named_textures`
    below for their semantics.

``var <type> <name> <value>``
    Sets a pipeline-level shader variable. Any ``extern static const``
    declaration in a shader whose name matches ``<name>`` is replaced with
    ``static const <type> <name> = <value>;`` before compilation, baking the
    value in. This is the mechanism for tuning shader parameters without
    touching the shader source. Supported types are ``int``, ``uint``,
    ``float``, ``double``, ``bool`` and their vector variants (``float2``,
    ``float3``, ``float4``, ``int2``, etc.). Pipeline-level variables apply to
    every group; group-level ``var`` directives (see below) take precedence
    within that group.

.. _pipeline_groups:

Groups
_________________

A group is the unit of rendering. Each group runs a chain of shaders in
sequence, with the output color of one shader feeding as the input ``color``
to the next. A pipeline may contain up to 16 groups.

.. code-block:: none

    startgroup
        shaders <name1> [name2 …]
        # optional per-group settings
    endgroup

Directives inside a group:

``shaders <name> [name …]``
    One or more shader names to run in order. Shaders are searched for first
    in the :file:`shaders/` subdirectory of the kitty config directory, then
    among the shaders shipped with kitty.

``var <type> <name> <value>``
    Same as the top-level ``var`` but scoped to this group. Merged with
    pipeline-level vars; the group value wins on conflict.

``viewport_pos <x> <y>``
    The bottom-left corner of this group's rendering region, expressed as
    unit floats in UV coordinates (0,0 = bottom-left of the screen, 1,1 =
    top-right). Defaults to ``0 0``. Ignored for the final group, which
    always covers the full screen.

``viewport_size <w> <h>``
    The width and height of the rendering region as unit floats. Defaults to
    ``1 1``. Ignored for the final group.

``output_texture <name>``
    Where the group writes its output. The default (``default``) ping-pongs
    the backbuffer: the rendered result becomes the new backbuffer that
    subsequent groups read from ``t.backbuffer``. Setting this to ``a``,
    ``b``, or ``persist`` instead writes into the corresponding named texture;
    the backbuffer is left unchanged for the next group. The final group must
    always use the default output.

``animation_start <event>[|<event> …]``
    Events that trigger the start of this group's animation. Multiple events
    are separated by ``|``. If omitted the group runs on every frame
    unconditionally. See *Animation events* below for the full list.

``animation_stop <token>[|<token> …]``
    When to stop the animation. Tokens are separated by ``|`` and may be:

    * An event name — the animation stops when that event fires.
    * An integer — a duration in **milliseconds** after which the animation
      automatically stops. The ``animation_progress`` value will smoothly
      reach ``1.0`` at that point.
    * ``never`` — the animation runs indefinitely until an explicit stop event.

    When ``animation_stop`` is omitted kitty uses
    :opt:`cursor_stop_blinking_after` as the duration.

``animation_curve <curve>``
    A CSS easing function that maps raw elapsed time to the ``animation_progress``
    value delivered to the shader. Supported values:

    * Named curves: ``linear``, ``ease``, ``ease-in``, ``ease-out``,
      ``ease-in-out``, ``step-start``, ``step-end``
    * ``cubic-bezier(x1, y1, x2, y2)``
    * ``linear(p0, p1[, …])``
    * ``steps(n, start|end)``

    Defaults to a linear mapping (no easing).

``animation_step <ms>``
    How many milliseconds between animation frames. Lower values produce
    smoother animation at the cost of more GPU draws. Defaults to ``50`` ms
    (20 fps). The value is clamped to be no smaller than
    :opt:`repaint_delay`.

.. _named_textures:

Named textures
_________________

Named textures are additional off-screen buffers accessible to all shaders in
the pipeline via the ``KittyTextures`` struct (``t.a``, ``t.b``, ``t.persist``).

``a``, ``b``
    Scratch textures that exist for the lifetime of the pipeline. They start
    uninitialized at the start of each draw call. Their typical use is for
    intermediate rendering: a group renders into ``a`` via
    ``output_texture a``, and a later group reads ``t.a`` to combine it with
    the backbuffer.

``persist``
    Like ``a``/``b`` but survives across frames. Whatever is written to
    ``t.persist`` during frame *N* can be read back from ``t.persist`` during
    frame *N+1*. This allows effects that accumulate state over time (e.g.
    simulation steps, trails, fluid simulations).

All three named textures have the same pixel dimensions as the OS window
viewport. They must be declared in the top-level ``textures`` directive before
they can be referenced. A named texture that is the output target for the
current group cannot simultaneously be sampled as input; kitty automatically
substitutes the backbuffer in that case.

**How groups chain together**

The backbuffer starts out as kitty's fully rendered terminal frame. Each group
reads from ``t.backbuffer`` and writes somewhere:

* ``output_texture default`` (the default): the group's output becomes the
  new backbuffer. The next group reads the modified pixels. This is the
  standard way to chain post-processing passes.
* ``output_texture a|b|persist``: the group writes into the named texture
  instead, leaving the backbuffer intact for the next group.

Groups that have ``animation_start`` set are skipped entirely when their
animation is not active, saving GPU work. Groups without any
``animation_start`` run on every frame.

**A minimal pipeline** — one shader, event-driven animation::

    startgroup
        animation_start pointer-left-button-press
        animation_stop 1500
        animation_curve ease-out
        animation_step 16
        shaders pond-ripple
    endgroup

**A two-group pipeline** using named textures::

    textures a

    startgroup
        shaders bloom-prepass
        output_texture a
    endgroup

    startgroup
        shaders bloom-composite
    endgroup

Here the first group renders a glow pre-pass into texture ``a``, and the
second group reads both the original backbuffer (``t.backbuffer``) and the
glow data (``t.a``) to composite the final image. Note that these shaders
aren't shipped with kitty, this is jut an illustrative example.

Animation events
^^^^^^^^^^^^^^^^^^^

Animation events drive when groups start and stop animating. They are used in
the ``animation_start`` and ``animation_stop`` directives. Multiple events can
be combined with ``|`` — any one of them will trigger the action.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Event name
     - When it fires

   * - ``pointer-left-button-press``
     - The left mouse button is pressed inside the OS window. The click
       position is available in ``d.mouse_pos.zw``.

   * - ``os-window-focus-in``
     - The OS window gains keyboard focus. Also fires on the first frame
       immediately after the pipeline is loaded.

   * - ``os-window-focus-out``
     - The OS window loses keyboard focus.

   * - ``window-focus-in``
     - The active kitty window (pane) changes and a new window gains focus.
       The focused window's geometry is in ``d.active_window_geometry``.

   * - ``window-focus-out``
     - A kitty window (pane) loses focus.

   * - ``tab-change``
     - The active tab changes.

   * - ``bell-in-window``
     - A bell (BEL character) is received in any kitty window.

   * - ``user-activity``
     - Any keyboard or mouse input is received.

   * - ``user-idle``
     - The user has been idle (no keyboard or mouse input) long enough to
       trigger the idle threshold.

   * - ``cursor-trail-move``
     - The cursor trail begins moving (requires :opt:`cursor_trail` to be
       enabled in :file:`kitty.conf`). The trail geometry is available via
       ``d.cursor_trail_corners_x``, ``d.cursor_trail_corners_y``, and
       ``d.cursor_trail_edge``. When any group subscribes to this event,
       kitty's built-in cursor trail rendering is suppressed so the shader
       takes over completely.

   * - ``cursor-trail-stop``
     - The cursor trail stops moving. Typically used as an ``animation_stop``
       event paired with ``cursor-trail-move`` as the start event.

Note that if both a start event and a focus-out event fire in the same frame
(for example, a mouse click that simultaneously moves focus away), the
focus-out takes priority and the animation is not (re-)started.
