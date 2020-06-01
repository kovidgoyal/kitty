// Future devs supporting whatever Wayland protocol stabilizes for cursor selection: see _themeAdd.

#include "wl_cursors.h"

#include "internal.h"

#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct {
    struct wl_cursor_theme *theme;
    int                     px;
    int                     refcount;
} _themeData;

struct _wlCursorThemeManager {
    size_t count;
    /** Pointer to the head of an unsorted array of themes with no sentinel.
     *
     * The lack of sort (and thus forcing a linear search) is intentional;
     * in most cases, users are likely to have 1-2 different cursor sizes loaded.
     * For those cases, we get no benefit from sorting and added constant overheads.
     *
     * Don't change this to a flexible array member because that complicates growing/shrinking.
     */
    _themeData *themes;
};

static void
_themeInit(_themeData *dest, const char *name, int px) {
    dest->px = px;
    dest->refcount = 1;
    if (_glfw.wl.shm) {
        dest->theme = wl_cursor_theme_load(name, px, _glfw.wl.shm);
        if(!dest->theme) {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "Wayland: Unable to load cursor theme");
        }
    } else {
        dest->theme = NULL;
    }
}

static struct wl_cursor_theme*
_themeAdd(int px, _wlCursorThemeManager *manager) {
   ++manager->count;
   _themeData *temp = realloc(manager->themes, sizeof(_themeData)*manager->count);
   if (!temp) {
       _glfwInputError(GLFW_OUT_OF_MEMORY,
                       "OOM during cursor theme management.");
       return NULL;
   } else {
       manager->themes = temp;
       _themeInit(manager->themes + manager->count-1,
                   getenv("XCURSOR_THEME"),
                   px);
       return manager->themes[manager->count-1].theme;
   }
}

//WARNING: No input safety checks.
static inline void _themeInc(_themeData
                          *theme) {
    ++(theme->refcount);
}

// WARNING: No input safety checks.
// In particular, doesn't check if theme is actually managed by the manager.
static void
_themeDec(_themeData *theme, _wlCursorThemeManager *manager) {
    if (--(theme->refcount) == 0) {
        wl_cursor_theme_destroy(theme->theme);
        if (--(manager->count) > 0) {
            const _themeData *last_theme = (manager->themes)+(manager->count);
            *theme = *last_theme;
            _themeData *temp = realloc(manager->themes, (manager->count)*sizeof(_themeData));
            // We're shrinking here, so it's not catastrophic if realloc fails.
            if (temp) manager->themes = temp;
        } else {
            free(manager->themes);
            manager->themes = NULL;
        }
    }
}

static _wlCursorThemeManager _default = {0};

_wlCursorThemeManager*
_wlCursorThemeManagerDefault() {
    return &_default;
}

void
_wlCursorThemeManagerDestroy(_wlCursorThemeManager *manager) {
    if (manager) {
        for (size_t i = 0; i < manager->count; ++i) {
            wl_cursor_theme_destroy(manager->themes[i].theme);
        }
        free(manager->themes);
    }
}

static struct wl_cursor_theme*
_wlCursorThemeManagerGet(_wlCursorThemeManager *manager, int px) {
    _themeData *themedata = NULL;
    for (size_t i = 0; i < manager->count; ++i) {
        _themeData *temp = manager->themes+i;
        if (temp->px == px) {
            themedata = temp;
            break;
        }
    }
    if (themedata != NULL) {
        _themeInc(themedata);
        return themedata->theme;
    }
    return _themeAdd(px, manager);
}

struct wl_cursor_theme*
_wlCursorThemeManage(_wlCursorThemeManager *manager, struct wl_cursor_theme *theme, int px) {
    //WARNING: Multiple returns.
    if (manager == NULL) {
        return NULL;
    }
    if (theme != NULL) {
        // Search for the provided theme in the manager.
        _themeData *themedata = NULL;
        for (size_t i = 0; i < manager->count; ++i) {
            _themeData *temp = manager->themes+i;
            if (temp->theme == theme) {
                themedata = temp;
                break;
            }
        }
        if (themedata != NULL) {
            // Search succeeded. Check if we can avoid unnecessary operations.
            if (themedata->px == px) return theme;
            _themeDec(themedata, manager);
        } else {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "Wayland internal: managed theme isn't in the provided manager");
            return theme;
            //^ This is probably the sanest behavior for this situation: do nothing.
        }
    }
    return px > 0 ? _wlCursorThemeManagerGet(manager, px) : NULL;
}

int
_wlCursorPxFromScale(int scale) {
    const char *envStr = getenv("XCURSOR_SIZE");
    if(envStr != NULL) {
        const int retval = atoi(envStr);
        //^ atoi here is fine since 0 is an invalid value.
        if(retval > 0 && retval <= INT_MAX/scale) {
            return retval*scale;
        }
    }
    return 32*scale;
}
