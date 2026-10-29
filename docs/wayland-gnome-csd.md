# Built-in GNOME-style Wayland decorations

Kitty's client-side decorations use a GNOME-style software renderer. It does not
use GTK, libadwaita, a hidden helper window, or a new library dependency. This is
the only CSD renderer; no environment variable or special build flag is needed.
Existing compositor/server-side decoration negotiation is unchanged.

Build normally, then run from this checkout:

```sh
python3 setup.py build
./kitty/launcher/kitty \
    -o linux_display_server=wayland -o hide_window_decorations=no \
    -o wayland_titlebar_color=system
```

The renderer draws a 38 logical-pixel header, centered bold title, 24-pixel
circular controls spaced 36 pixels apart, antialiased upper corners and matching
shadows. Maximized/tiled headers have square corners. Narrow headers prioritize
the close control. A control activates only after a matching press/release.
Existing movement, resizing, maximize/restore, menu and fullscreen behavior is
preserved.

With `wayland_titlebar_color system`, the palette follows the desktop's color
scheme, including live light/dark transitions. When the desktop expresses no
preference, the palette follows the terminal background's luminance. An explicit
`wayland_titlebar_color` takes precedence, with contrasting text and controls.

The interface font family and point size come from the existing asynchronous
portal settings query and are rendered bold through FreeType/Fontconfig. Font
changes redraw the header. No settings subprocess or additional blocking query
is added at startup. If no font is exposed, the fallback is sans-serif 11.

This approximates GNOME's appearance; it does not interpret GTK/Yaru CSS, arbitrary
Pango font-description styling, GNOME button layout or text scaling settings.
The lower terminal corners remain square. Visual review used Ubuntu 26.10 /
GNOME Shell 51.0; Ubuntu 24.10 has not been tested.

The rounded header cutouts contain the same shadow field as the adjacent
surfaces, including inactive opacity. A smooth outer envelope removes the finite
blur buffer's rectangular outline. Shadows use a cached tile, without a
full-window atlas.

## Validation

The renderer test checks buffer bounds at 100/125/150/200% scale, tiny/narrow/normal
widths, focused/unfocused/maximized states, dark/light/dark repainting, explicit
custom colors, control spacing and header/shadow continuity. A separate test
feeds real D-Bus appearance signal messages to the portal handler without
changing desktop settings.

From the repository root:

```sh
gcc -D_GLFW_WAYLAND -Iglfw $(pkg-config --cflags dbus-1) \
    -Wall -Wextra -Werror -Wno-missing-field-initializers -std=c11 -pedantic-errors \
    -ffunction-sections -fdata-sections glfw/tests/gnome_csd.c \
    -Wl,--gc-sections $(pkg-config --libs wayland-client) -lm -o /tmp/kitty-csd-test
/tmp/kitty-csd-test

gcc -D_GLFW_WAYLAND -Iglfw $(pkg-config --cflags dbus-1) \
    -Wall -Wextra -Werror -Wno-missing-field-initializers -std=c11 -pedantic-errors \
    -ffunction-sections -fdata-sections glfw/tests/desktop_appearance.c \
    -Wl,--gc-sections $(pkg-config --libs dbus-1) -o /tmp/kitty-appearance-test
/tmp/kitty-appearance-test
```

Add `-fsanitize=address,undefined` to the renderer test for memory/UB checks. It
writes a preview to `/tmp/kitty-gnome-csd-preview.ppm`. Manual compositor review
should also cover dynamic/Unicode titles, maximize/restore, fullscreen, focus,
custom colors, theme changes and cancelled button presses.
