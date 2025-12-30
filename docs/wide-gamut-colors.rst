Wide gamut color formats
=========================

kitty supports modern wide gamut color formats for precise color specification.
These formats can be used anywhere a color value is accepted in the configuration
(foreground, background, color0-color255, etc.).

OKLCH Colors
------------

OKLCH is a perceptually uniform color space, ideal for creating color themes.
The format is::

    foreground oklch(0.9 0.05 140)
    color1     oklch(0.7 0.25 25)

Parameters:

- **L** (Lightness): 0 to 1, where 0 is black and 1 is white
- **C** (Chroma): 0 to approximately 0.4, represents color saturation
- **H** (Hue): 0 to 360 degrees (0=red, 120=green, 240=blue)

Benefits:

- Perceptually uniform - equal changes produce equal perceived differences
- Adjusting lightness preserves hue (unlike HSL)
- Industry standard for modern color design

Example::

    foreground oklch(0.9 0.05 140)
    color1     oklch(0.65 0.25 29)    # Vibrant red-orange
    color2     oklch(0.65 0.25 142)   # Vibrant green
    color3     oklch(0.70 0.19 90)    # Warm yellow

CIE LAB Colors
--------------

CIE LAB is a device-independent color space designed to approximate human vision.

The format is::

    background lab(20 5 -10)
    color4     lab(50 0 -50)

Parameters:

- **L**: Lightness, 0 to 100 (0 = black, 100 = white)
- **a**: Green (-) to red (+), typically -100 to +100
- **b**: Blue (-) to yellow (+), typically -100 to +100

Example::

    background lab(10 0 0)           # Very dark neutral gray
    foreground lab(90 0 0)           # Very light neutral gray
    color1     lab(50 60 40)         # Red
    color4     lab(50 0 -50)         # Blue

Gamut Mapping
-------------

When you specify colors in OKLCH or CIE LAB formats that are outside the sRGB
color gamut, kitty automatically converts them using the CSS Color Module Level 4
gamut mapping algorithm:

- Preserves the original lightness and hue as much as possible
- Reduces chroma (saturation) until the color fits within the displayable range
- Uses perceptual color difference (deltaE OK) to minimize visible changes
- Maximizes color saturation while staying in gamut

This ensures that wide gamut colors gracefully degrade on standard sRGB displays while
taking full advantage of wide gamut displays when available. The mapping happens
automatically - you don't need to do anything special.

For example, :code:`oklch(0.7 0.4 25)` might be too saturated for sRGB but will be
automatically adjusted to fit while preserving the perceived hue and lightness.

References
----------

- `CSS Color Module Level 4 <https://www.w3.org/TR/css-color-4/>`_
- `OKLCH Color Space <https://bottosson.github.io/posts/oklab/>`_
