// Declarations for a HiDPI-aware cursor theme manager.

#include <wayland-cursor.h>

typedef struct _wlCursorThemeManager _wlCursorThemeManager;

/** Returns a pointer to a wlCursorThemeManagerInstance.
 * Repeatedly calling this function will return the same instance.
 *
 * The retrieved instance must be destroyed with _wlCursorThemeManagerDestroy.
 */
_wlCursorThemeManager* _wlCursorThemeManagerDefault(void);

/** Set a wl_cursor_theme pointer variable to a pointer to a managed cursor theme.
 * Pass the desired px as the third argument.
 * Returns a pointer to a managed theme, or NULL if the desired px is 0 or an error occurs.
 *
 * The passed theme pointer must either be NULL or a pointer to a theme managed by the passed manager.
 * The provided pointer may be invalidated if it's non-NULL.
 */
struct wl_cursor_theme*
_wlCursorThemeManage(_wlCursorThemeManager*, struct wl_cursor_theme*, int);

void _wlCursorThemeManagerDestroy(_wlCursorThemeManager*);

/** Helper method to determine the appropriate size in pixels for a given scale.
 *
 * Reads XCURSOR_SIZE if it's set and is valid, else defaults to 32*scale.
 */
int _wlCursorPxFromScale(int);
