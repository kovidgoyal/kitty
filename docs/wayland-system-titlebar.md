# GNOME system titlebar for Kitty on Wayland

This implementation draws a real GTK 4 / libadwaita `AdwHeaderBar` into Kitty's
existing Wayland decoration surface. It uses the same styling engine as Files:
fonts, light/dark appearance, icons, button layout, and upper corner shape come
from GTK and libadwaita rather than a copied palette. The native
`default-decoration` style uses a compact titlebar (37 px with the current
system theme), rather than the taller toolbar/header style used by Files.
GTK never maps its helper window and is restricted to the Wayland backend. Its implicit GTK renderer is
also forced to Cairo during realization, so creating it does not initialize an
unused Vulkan/OpenGL device. The previous `GSK_RENDERER` environment value is
restored immediately and is not imposed on terminal children.

Kitty continues to handle window movement, edge resizing, double-click to
maximize/restore, the window menu, and minimize/maximize/close requests using
its existing Wayland code. Buttons use the actual GTK allocations for hit
testing, including fractional scaling, and activate only after a press and
release on the same button. Theme and button-layout notifications redraw open
windows. Maximized/tiled windows have square upper corners.

Build with GTK >= 4.12 and libadwaita >= 1.4 development packages installed:

```sh
KITTY_BUILD_GNOME_TITLEBAR=1 python3 setup.py build --debug
```

Use system development libraries consistently. Kitty's prebuilt development
dependencies may include older GLib or HarfBuzz versions incompatible with the
GTK installed by the operating system. Do not mix those versions in one process.

Enable at startup:

```sh
KITTY_WAYLAND_TITLEBAR=system ./kitty/launcher/kitty \
  -o linux_display_server=wayland -o hide_window_decorations=no \
  -o wayland_titlebar_color=system
```

For dynamic titles, launch without `--title`. That standard Kitty option pins
an OS window title and prevents it from following the active tab. The native
headerbar otherwise follows each application title update, including Unicode
spinner frames, through the same callback as the original decorations.

The original renderer remains the default. Unset `KITTY_WAYLAND_TITLEBAR` to use
it. Builds without `KITTY_BUILD_GNOME_TITLEBAR=1` do not require GTK or libadwaita.
The existing custom `wayland_titlebar_color` setting remains supported; `system`
uses the native theme. `hide_window_decorations` and fullscreen behavior still
use Kitty's existing decoration lifecycle.

The upper corners use the rounded background clip emitted by GTK for the
system window style; the radius is not hard-coded. The surrounding shadows
also come from GTK's actual CSS shadow nodes, with
separate focused/unfocused styles and their full blur extent. They follow the
same rounded upper outline. The full shadow is rendered once before it is split
across Wayland subsurfaces, and its outer blur envelope is also rounded to avoid
a faint rectangular halo when focused.
The bottom corners of the terminal content remain square.
Changes to the system font size that alter the headerbar's required height
currently require restarting Kitty. Hover/press animations are disabled in the
helper GTK context because its hidden window has no running frame clock;
hover/press states are drawn immediately. This does not change desktop settings.

Run the native rendering integration test inside a Wayland session:

```sh
gcc -D_GLFW_WAYLAND -DKITTY_GNOME_TITLEBAR -Iglfw \
  glfw/tests/native_titlebar.c glfw/wl_native_titlebar.c \
  $(pkg-config --cflags --libs libadwaita-1 dbus-1) -lm \
  -o /tmp/kitty-native-titlebar-test
/tmp/kitty-native-titlebar-test
python3 test.py --module glfw
```

The test checks native theme changes, button positions and capabilities,
100/150/200% rendering, buffer bounds, upper corner alpha, square maximized
corners, full native shadow extents without a clipped outer edge, shadow buffer
bounds at fractional scales, very narrow windows, and cleanup. It saves previews
in `/tmp/kitty-titlebar-*.png` and `/tmp/kitty-native-shadow-*.png`.
Physical mouse gestures should also be checked on the intended compositor.

Local validation also exercised startup with the existing user configuration,
title changes, resizing, maximize/restore, fullscreen/restore, and clean exit on
GNOME Wayland. Kitty's process-wide Cairo/Fontconfig reset is skipped when GTK
was initialized, because GTK/Pango keep shared font caches alive until process
exit; resetting them prematurely causes a shutdown assertion. Per-window
renderer/widget resources and Kitty's own font resources are still released.


Source-build startup measurements on the same Ubuntu/GNOME session, with a
clean configuration, a 1000x600 logical-pixel client, one warmup excluded and
ten timed launches (median time until the child shell writes its ready marker,
not first-visible-frame latency):

| Build | Startup median |
| --- | ---: |
| Installed upstream release | 131 ms |
| Initial local GTK titlebar build | 534 ms |
| Optimized local GTK titlebar build | 279 ms |
| Same optimized build, GTK titlebar disabled | 164 ms |

The optimized installation uses release compiler flags, a Cairo-only hidden
GTK renderer, and precompiled optimized (`-OO`) Python standard-library bytecode.
The bytecode cache change is a local source-build installation improvement, not
a change to this renderer: without writable/preinstalled `.opt-2.pyc` caches,
the system Python recompiles several standard-library modules at every launch.
The remaining roughly 115 ms enabling the native titlebar is mostly libadwaita
initialization on this machine. These are warm-cache desktop measurements and
should not be interpreted as a frame-rate or scrolling benchmark.
