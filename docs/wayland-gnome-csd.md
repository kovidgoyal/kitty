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

The renderer draws a header of at least 38 logical pixels, centered title,
24-pixel circular controls spaced 36 pixels apart, antialiased upper corners
and matching shadows. The header grows to accommodate the selected font and
text scale. Maximized/tiled headers have square corners. Narrow headers hide
minimize/maximize controls before close, when those controls are configured.
A control activates only after a matching press/release.

With `wayland_titlebar_color system`, the palette follows the desktop's color
scheme, including live light/dark transitions. GNOME reports its normal light
appearance as "no preference"; this uses the light palette, independent of the
terminal background. If the portal or color-scheme setting is unavailable, the
fallback is dark; a valid "no preference" reply remains distinguishable from
missing settings. Explicit colors still
take precedence, with contrasting text and controls.

The existing asynchronous portal query also reads these GNOME settings:

| Namespace | Settings used |
| --- | --- |
| `org.gnome.desktop.interface` | `font-name`, `text-scaling-factor` |
| `org.gnome.desktop.wm.preferences` | `titlebar-font`, `titlebar-uses-system-font`, `button-layout` |
| `org.gnome.desktop.wm.preferences` | `action-double-click-titlebar`, `action-middle-click-titlebar`, `action-right-click-titlebar` |

These affect the titlebar, not terminal text. Font preferences select either
GNOME's interface font (bold for the title) or the configured title font.
Family, point size and trailing Bold/Italic/Oblique/Regular/Normal styles are
supported through FreeType/Fontconfig. Text scale is validated between 0.5 and
4.0. Font or scale changes rebuild the cached font/header as needed. Normal
windows keep their terminal content size; docked windows keep their exterior
size while the header changes height.

Button layout respects left/right placement, ordering and omitted controls.
Duplicate or unsupported control names are ignored; malformed layouts retain
the last valid layout. Supported titlebar actions are menu, toggle-maximize,
minimize and none. Unsupported actions such as lower, shade or single-axis
maximize are treated as no action; no equivalent xdg-shell request is used.

Updates are applied live through portal SettingChanged signals, without a new
settings subprocess or blocking query. On backends that omit these GNOME keys,
fallbacks are sans-serif 11, scale 1, controls minimize/maximize/close on the
right, double-click maximize, right-click menu and no middle-click action.

This approximates GNOME appearance. GTK/Yaru CSS, arbitrary Pango font styling,
theme-specific decoration palettes, icon artwork and shadow geometry are not
interpreted. Lower terminal corners remain square. Visual review used Ubuntu
26.10 / GNOME Shell 51.0; Ubuntu 24.10 has not been tested.

The rounded header cutouts contain the same shadow field as the adjacent
surfaces, including inactive opacity. A smooth outer envelope removes the finite
blur buffer's rectangular outline. Shadows use a cached tile, without a
full-window atlas.

## Validation

The renderer test checks buffer bounds at 100/125/150/200% scale, tiny/narrow/normal
widths, focused/unfocused/maximized states, dark/light/dark repainting, explicit
custom colors, control spacing, split/empty layouts, narrow-window priorities,
header growth and header/shadow continuity. A separate test feeds real D-Bus
settings signal messages through the handler to validate appearance, font
selection, text scale, invalid values, duplicate controls and titlebar actions,
without changing desktop settings.

From the repository root:

```sh
gcc -D_GLFW_WAYLAND -Iglfw $(pkg-config --cflags dbus-1) \
    -Wall -Wextra -Werror -Wno-missing-field-initializers -std=c11 -pedantic-errors \
    -ffunction-sections -fdata-sections glfw/tests/gnome_csd.c \
    -Wl,--gc-sections $(pkg-config --libs wayland-client) -lm -o /tmp/kitty-csd-test
/tmp/kitty-csd-test

gcc -D_GLFW_WAYLAND -Iglfw $(pkg-config --cflags dbus-1) \
    -Wall -Wextra -Werror -Wno-missing-field-initializers -std=c11 -pedantic-errors \
    -ffunction-sections -fdata-sections glfw/tests/desktop_appearance.c glfw/dbus_glfw.c \
    -Wl,--gc-sections $(pkg-config --libs dbus-1) -lm -o /tmp/kitty-appearance-test
/tmp/kitty-appearance-test
```

Add `-fsanitize=address,undefined` to the renderer test for memory/UB checks. It
writes a preview to `/tmp/kitty-gnome-csd-preview.ppm`. Manual compositor review
should also cover dynamic/Unicode titles, maximize/restore, fullscreen, focus,
custom colors, theme changes and cancelled button presses.
