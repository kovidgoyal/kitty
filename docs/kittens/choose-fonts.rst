Changing kitty fonts
========================

.. only:: man

    Overview
    --------------

Terminal aficionados spend all day staring at text, as such, getting text
rendering just right is very important. kitty has extremely powerful facilities
for fine-tuning text rendering. It supports `OpenType features
<https://en.wikipedia.org/wiki/List_of_typographic_features>`__ to select
alternate glyph shapes, and `Variable fonts
<https://en.wikipedia.org/wiki/Variable_font>`__ to control the weight or
spacing of a font precisely. You can also :opt:`select which font is used to
render particular unicode codepoints <symbol_map>` and you can :opt:`modify
font metrics <modify_font>` and even :opt:`adjust the gamma curves
<text_composition_strategy>` used for rendering text onto the background color.

The first step is to select the font faces kitty will use for rendering
regular, bold and italic text. kitty comes with a convenient UI for choosing fonts,
in the form of the *choose-fonts* kitten. Simply run::

    kitten choose-fonts

and follow the on screen prompts.

First, choose the family you want, the list of families can be easily filtered by
typing a few letters from the family name you are looking for. The family
selection screen shows you a preview of how the family looks.

.. image:: ../screenshots/family-selection.png
   :alt: Choosing a family with the choose fonts kitten
   :width: 600

Once you select a family by pressing the :kbd:`Enter` key, you
are shown previews of what the regular, bold and italic faces look like
for that family. You can choose to fine tune any of the faces. Start with
fine-tuning the regular face by pressing the :kbd:`R` key. The other styles
will be automatically adjusted based on what you select for the regular face.

.. image:: ../screenshots/font-fine-tune.png
   :alt: Fine tune a font by choosing a precise weight and features
   :width: 600

You can choose a specific style or font feature by clicking on it. A precise
value for any variable axes can be selected using the slider, in the screenshot
above the font supports precise weight adjustment. If you are lucky the font
designer has included descriptive names for font features, which will be
displayed, if not, consult the documentation of the font to see what each feature does.

