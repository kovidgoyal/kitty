// Future devs supporting whatever Wayland protocol stabilizes for cursor selection: see _themeAdd.

#include "internal.h"
#include "linux_desktop_settings.h"

#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>

static GLFWWLCursorThemes cursor_themes;

static int
pixels_from_scale(int scale) {
    int factor;
    const char* name;
    glfw_current_cursor_theme(&name, &factor);
    return factor * scale;
}


struct wl_cursor_theme*
glfw_wlc_theme_for_scale(int scale) {
    for (size_t i = 0; i < cursor_themes.count; i++) {
        if (cursor_themes.themes[i].scale == scale) return cursor_themes.themes[i].theme;
    }

    if (cursor_themes.count >= cursor_themes.capacity) {
        cursor_themes.themes = realloc(cursor_themes.themes, sizeof(GLFWWLCursorTheme) * (cursor_themes.count + 16));
        if (!cursor_themes.themes) {
            _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: Out of memory allocating space for cursor themes");
            return NULL;
        }
        cursor_themes.capacity = cursor_themes.count + 16;
    }
    int factor;
    const char* name;
    glfw_current_cursor_theme(&name, &factor);
    struct wl_cursor_theme *ans = wl_cursor_theme_load(name, pixels_from_scale(scale), _glfw.wl.shm);
    if (!ans) {
        _glfwInputError(
            GLFW_PLATFORM_ERROR, "Wayland: wl_cursor_theme_load failed at scale: %d pixels: %d",
            scale, pixels_from_scale(scale)
        );
        return NULL;
    }
    GLFWWLCursorTheme *theme = cursor_themes.themes + cursor_themes.count++;
    theme->scale = scale;
    theme->theme = ans;
    return ans;
}

void
glfw_wlc_destroy(void) {
    for (size_t i = 0; i < cursor_themes.count; i++) {
        wl_cursor_theme_destroy(cursor_themes.themes[i].theme);
    }
    free(cursor_themes.themes);
    cursor_themes.themes = NULL; cursor_themes.capacity = 0; cursor_themes.count = 0;
}
