// Declarations for a HiDPI-aware cursor theme manager.

#include <wayland-cursor.h>

typedef struct {
    struct wl_cursor_theme *theme;
    int scale;
} GLFWWLCursorTheme;


typedef struct {
    GLFWWLCursorTheme *themes;
    size_t count, capacity;
} GLFWWLCursorThemes;


struct wl_cursor_theme* glfw_wlc_theme_for_scale(int scale);
void glfw_wlc_destroy(void);
