# Built-in GNOME-style Wayland decorations

This experimental patch adds an opt-in style to kitty's existing software CSD
renderer. It does not use GTK, libadwaita, a hidden helper window, or a new
library dependency. The unchanged upstream renderer remains the default.

Build normally, then run from this checkout:

```sh
python3 setup.py build --debug
KITTY_WAYLAND_TITLEBAR=gnome ./kitty/launcher/kitty \
    -o linux_display_server=wayland -o hide_window_decorations=no \
    -o wayland_titlebar_color=system
```

The style approximates GNOME/Ubuntu decorations: a 38 logical pixel header,
centered bold title without kitty's decorative prefix, 24 pixel circular controls
with 36 pixel spacing and thin symbolic glyphs, 12 logical pixel antialiased upper corners, matching upper shadow curvature,
and a fixed dark palette independent of the desktop light/dark appearance.
Custom `wayland_titlebar_color` values still work. Maximized/tiled headers have
square corners. Narrow headers hide controls that do not fit, retaining close
first. Button activation requires a matching press and release; hovering and
pressing change the button background. Existing titlebar drag, double-click,
window menu and resize behavior are retained.

This is an approximation, not GTK theme integration. It uses fixed geometry,
colors and right-side control ordering. It reads GNOME's interface font family
and point size through the existing asynchronous desktop portal settings query,
and renders it bold through FreeType/Fontconfig. Font changes redraw the header.
No extra settings process or blocking D-Bus query is added at startup. If the
portal does not expose a font, it uses sans-serif 11. It does not interpret
Yaru/Adwaita CSS or GNOME's button-layout settings. Visual review was performed
on Ubuntu 26.10 / GNOME Shell 51.0; Ubuntu 24.10 has not been tested. The lower terminal corners remain square. Changing the environment
variable requires restarting kitty. Unset it to use upstream decorations.

## Validation

Normal release and debug builds use upstream warning-as-error flags. A standalone
renderer test checks buffer bounds at 100/125/150/200% scale, tiny/narrow/normal
widths, focused/unfocused and light/dark/maximized states, fixed dark colors
under a light desktop theme, explicit custom colors, rounded alpha,
control bounds, shadow curvature, header/shadow continuity, transparent outer
shadow corners and default metrics when the style is disabled.

From the repository root:

```sh
gcc -D_GLFW_WAYLAND -Iglfw $(pkg-config --cflags dbus-1) \
    -Wall -Wextra -Werror -Wno-missing-field-initializers -std=c11 -pedantic-errors \
    -ffunction-sections -fdata-sections glfw/tests/gnome_csd.c \
    -Wl,--gc-sections $(pkg-config --libs wayland-client) -lm -o /tmp/kitty-gnome-csd-test
/tmp/kitty-gnome-csd-test
```

Add `-fsanitize=address,undefined` to run with memory/undefined-behavior checks.
The test writes a titlebar preview to `/tmp/kitty-gnome-csd-preview.ppm`.

For manual review, check title changes (without a fixed `--title`), long and
Unicode titles, custom titlebar colors, resize, maximize/restore, fullscreen,
focus changes, light/dark appearance, and button press cancellation. The renderer
test does not replace checking those interactions in a live compositor.

The rounded header cutouts contain the matching black shadow from the cached
shadow tile, including its inactive opacity. All adjacent decoration surfaces
therefore share one shadow field. A smooth rounded outer envelope removes the
finite blur buffer's rectangular outline. No full-window atlas is allocated.
