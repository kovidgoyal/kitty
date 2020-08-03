// Future devs supporting whatever Wayland protocol stabilizes for cursor selection: see _themeAdd.

#include "internal.h"

#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>

static int
pixels_from_scale(int scale) {
    static bool queried_env = false;
    static int factor = 32;
    if (!queried_env) {
        const char *env = getenv("XCURSOR_SIZE");
        if (env) {
            const int retval = atoi(env);
            if (retval > 0 && retval < 2048) factor = retval;
        }
        queried_env = true;
    }
    return factor * scale;
}


struct wl_cursor_theme*
glfw_wlc_theme_for_scale(int scale) {
    GLFWWLCursorThemes *t = &_glfw.wl.cursor_themes;
    for (size_t i = 0; i < t->count; i++) {
        if (t->themes[i].scale == scale) return t->themes[i].theme;
    }

    if (t->count >= t->capacity) {
        t->themes = realloc(t->themes, sizeof(GLFWWLCursorTheme) * (t->count + 16));
        if (!t->themes) {
            _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: Out of memory allocating space for cursor themes");
            return NULL;
        }
        t->capacity = t->count + 16;
    }
    struct wl_cursor_theme *ans = wl_cursor_theme_load(getenv("XCURSOR_THEME"), pixels_from_scale(scale), _glfw.wl.shm);
    if (!ans) {
        _glfwInputError(
            GLFW_PLATFORM_ERROR, "Wayland: wl_cursor_theme_load failed at scale: %d pixels: %d",
            scale, pixels_from_scale(scale)
        );
        return NULL;
    }
    GLFWWLCursorTheme *theme = t->themes + t->count++;
    theme->scale = scale;
    theme->theme = ans;
    return ans;
}

void
glfw_wlc_destroy(void) {
    GLFWWLCursorThemes *t = &_glfw.wl.cursor_themes;

    for (size_t i = 0; i < t->count; i++) {
        wl_cursor_theme_destroy(t->themes[i].theme);
    }
    free(t->themes);
    t->themes = NULL; t->capacity = 0; t->count = 0;
}
