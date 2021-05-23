/*
 * mouse.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"
#include "screen.h"
#include "lineops.h"
#include "charsets.h"
#include <limits.h>
#include <math.h>
#include "glfw-wrapper.h"
#include "control-codes.h"
#include "monotonic.h"

extern PyTypeObject Screen_Type;

static MouseShape mouse_cursor_shape = BEAM;
typedef enum MouseActions { PRESS, RELEASE, DRAG, MOVE } MouseAction;
#define debug(...) if (OPT(debug_keyboard)) printf(__VA_ARGS__);

// Encoding of mouse events {{{
#define SHIFT_INDICATOR  (1 << 2)
#define ALT_INDICATOR (1 << 3)
#define CONTROL_INDICATOR (1 << 4)
#define MOTION_INDICATOR  (1 << 5)
#define SCROLL_BUTTON_INDICATOR (1 << 6)
#define EXTRA_BUTTON_INDICATOR (1 << 7)


static inline unsigned int
button_map(int button) {
    switch(button) {
        case GLFW_MOUSE_BUTTON_LEFT:
            return 1;
        case GLFW_MOUSE_BUTTON_RIGHT:
            return 3;
        case GLFW_MOUSE_BUTTON_MIDDLE:
            return 2;
        case GLFW_MOUSE_BUTTON_4:
        case GLFW_MOUSE_BUTTON_5:
        case GLFW_MOUSE_BUTTON_6:
        case GLFW_MOUSE_BUTTON_7:
        case GLFW_MOUSE_BUTTON_8:
            return button + 5;
        default:
            return UINT_MAX;
    }
}

static inline unsigned int
encode_button(unsigned int button) {
    if (button >= 8 && button <= 11) {
        return (button - 8) | EXTRA_BUTTON_INDICATOR;
    } else if (button >= 4 && button <= 7) {
        return (button - 4) | SCROLL_BUTTON_INDICATOR;
    } else if (button >= 1 && button <= 3) {
        return button - 1;
    } else {
        return UINT_MAX;
    }
}

static char mouse_event_buf[64];

static inline int
encode_mouse_event_impl(unsigned int x, unsigned int y, int mouse_tracking_protocol, int button, MouseAction action, int mods) {
    unsigned int cb = 0;
    if (action == MOVE) {
        cb = 3;
    } else {
        cb = encode_button(button);
        if (cb == UINT_MAX) return 0;
    }
    if (action == DRAG || action == MOVE) cb |= MOTION_INDICATOR;
    else if (action == RELEASE && mouse_tracking_protocol != SGR_PROTOCOL) cb = 3;
    if (mods & GLFW_MOD_SHIFT) cb |= SHIFT_INDICATOR;
    if (mods & GLFW_MOD_ALT) cb |= ALT_INDICATOR;
    if (mods & GLFW_MOD_CONTROL) cb |= CONTROL_INDICATOR;
    switch(mouse_tracking_protocol) {
        case SGR_PROTOCOL:
            return snprintf(mouse_event_buf, sizeof(mouse_event_buf), "<%d;%d;%d%s", cb, x, y, action == RELEASE ? "m" : "M");
            break;
        case URXVT_PROTOCOL:
            return snprintf(mouse_event_buf, sizeof(mouse_event_buf), "%d;%d;%dM", cb + 32, x, y);
            break;
        case UTF8_PROTOCOL:
            mouse_event_buf[0] = 'M'; mouse_event_buf[1] = cb + 32;
            unsigned int sz = 2;
            sz += encode_utf8(x + 32, mouse_event_buf + sz);
            sz += encode_utf8(y + 32, mouse_event_buf + sz);
            return sz;
            break;
        default:
            if (x > 223 || y > 223) return 0;
            else {
                mouse_event_buf[0] = 'M'; mouse_event_buf[1] = cb + 32; mouse_event_buf[2] = x + 32; mouse_event_buf[3] = y + 32;
                return 4;
            }
            break;
    }
    return 0;
}

static int
encode_mouse_event(Window *w, int button, MouseAction action, int mods) {
    unsigned int x = w->mouse_pos.cell_x + 1, y = w->mouse_pos.cell_y + 1; // 1 based indexing
    Screen *screen = w->render_data.screen;
    return encode_mouse_event_impl(x, y, screen->modes.mouse_tracking_protocol, button, action, mods);
}

static int
encode_mouse_button(Window *w, int button, MouseAction action, int mods) {
    return encode_mouse_event(w, button_map(button), action, mods);
}

static int
encode_mouse_scroll(Window *w, bool upwards, int mods) {
    return encode_mouse_event(w, upwards ? 4 : 5, PRESS, mods);
}

// }}}

static bool
dispatch_mouse_event(Window *w, int button, int count, int modifiers, bool grabbed) {
    bool handled = false;
    if (w->render_data.screen && w->render_data.screen->callbacks != Py_None) {
        if (OPT(debug_keyboard)) {
            const char *evname = "move";
            switch(count) {
                case -3: evname = "doubleclick"; break;
                case -2: evname = "click"; break;
                case -1: evname = "release"; break;
                case 1: evname = "press"; break;
                case 2: evname = "doublepress"; break;
                case 3: evname = "triplepress"; break;
            }
            const char *bname = "unknown";
            switch(button) {
                case GLFW_MOUSE_BUTTON_LEFT: bname = "left"; break;
                case GLFW_MOUSE_BUTTON_MIDDLE: bname = "middle"; break;
                case GLFW_MOUSE_BUTTON_RIGHT: bname = "right"; break;
                case GLFW_MOUSE_BUTTON_4: bname = "b4"; break;
                case GLFW_MOUSE_BUTTON_5: bname = "b5"; break;
                case GLFW_MOUSE_BUTTON_6: bname = "b6"; break;
                case GLFW_MOUSE_BUTTON_7: bname = "b7"; break;
                case GLFW_MOUSE_BUTTON_8: bname = "b8"; break;
            }
            debug("\x1b[33mon_mouse_input\x1b[m: %s button: %s %sgrabbed: %d\n", evname, bname, format_mods(modifiers), grabbed);
        }
        PyObject *callback_ret = PyObject_CallMethod(w->render_data.screen->callbacks, "on_mouse_event", "{si si si sO}",
            "button", button, "repeat_count", count, "mods", modifiers, "grabbed", grabbed ? Py_True : Py_False);
        if (callback_ret == NULL) PyErr_Print();
        else {
            handled = callback_ret == Py_True;
            Py_DECREF(callback_ret);
        }
    }
    return handled;
}

static inline unsigned int
window_left(Window *w) {
    return w->geometry.left - w->padding.left;
}

static inline unsigned int
window_right(Window *w) {
    return w->geometry.right + w->padding.right;
}

static inline unsigned int
window_top(Window *w) {
    return w->geometry.top - w->padding.top;
}

static inline unsigned int
window_bottom(Window *w) {
    return w->geometry.bottom + w->padding.bottom;
}

static inline bool
contains_mouse(Window *w) {
    double x = global_state.callback_os_window->mouse_x, y = global_state.callback_os_window->mouse_y;
    return (w->visible && window_left(w) <= x && x <= window_right(w) && window_top(w) <= y && y <= window_bottom(w));
}

static inline double
distance_to_window(Window *w) {
    double x = global_state.callback_os_window->mouse_x, y = global_state.callback_os_window->mouse_y;
    double cx = (window_left(w) + window_right(w)) / 2.0;
    double cy = (window_top(w) + window_bottom(w)) / 2.0;
    return (x - cx) * (x - cx) + (y - cy) * (y - cy);
}

static bool clamp_to_window = false;

static inline bool
cell_for_pos(Window *w, unsigned int *x, unsigned int *y, bool *in_left_half_of_cell, OSWindow *os_window) {
    WindowGeometry *g = &w->geometry;
    Screen *screen = w->render_data.screen;
    if (!screen) return false;
    unsigned int qx = 0, qy = 0;
    bool in_left_half = true;
    double mouse_x = global_state.callback_os_window->mouse_x;
    double mouse_y = global_state.callback_os_window->mouse_y;
    double left = window_left(w), top = window_top(w), right = window_right(w), bottom = window_bottom(w);
    if (clamp_to_window) {
        mouse_x = MIN(MAX(mouse_x, left), right);
        mouse_y = MIN(MAX(mouse_y, top), bottom);
    }
    w->mouse_pos.x = mouse_x - left; w->mouse_pos.y = mouse_y - top;
    if (mouse_x < left || mouse_y < top || mouse_x > right || mouse_y > bottom) return false;
    if (mouse_x >= g->right) {
        qx = screen->columns - 1;
        in_left_half = false;
    } else if (mouse_x >= g->left) {
        double xval = (double)(mouse_x - g->left) / os_window->fonts_data->cell_width;
        double fxval = floor(xval);
        qx = (unsigned int)fxval;
        in_left_half = (xval - fxval <= 0.5) ? true : false;
    }
    if (mouse_y >= g->bottom) qy = screen->lines - 1;
    else if (mouse_y >= g->top) qy = (unsigned int)((double)(mouse_y - g->top) / os_window->fonts_data->cell_height);
    if (qx < screen->columns && qy < screen->lines) {
        *x = qx; *y = qy;
        *in_left_half_of_cell = in_left_half;
        return true;
    }
    return false;
}

#define HANDLER(name) static inline void name(Window UNUSED *w, int UNUSED button, int UNUSED modifiers, unsigned int UNUSED window_idx)

static inline void
set_mouse_cursor_when_dragging(void) {
    if (mouse_cursor_shape != OPT(pointer_shape_when_dragging)) {
        mouse_cursor_shape = OPT(pointer_shape_when_dragging);
        set_mouse_cursor(mouse_cursor_shape);
    }
}

static inline void
update_drag(Window *w) {
    Screen *screen = w->render_data.screen;
    if (screen && screen->selections.in_progress) {
        screen_update_selection(screen, w->mouse_pos.cell_x, w->mouse_pos.cell_y, w->mouse_pos.in_left_half_of_cell, false, false);
    }
    set_mouse_cursor_when_dragging();
}

static inline bool
do_drag_scroll(Window *w, bool upwards) {
    Screen *screen = w->render_data.screen;
    if (screen->linebuf == screen->main_linebuf) {
        screen_history_scroll(screen, SCROLL_LINE, upwards);
        update_drag(w);
        if (mouse_cursor_shape != ARROW) {
            mouse_cursor_shape = ARROW;
            set_mouse_cursor(mouse_cursor_shape);
        }
        return true;
    }
    return false;
}

bool
drag_scroll(Window *w, OSWindow *frame) {
    unsigned int margin = frame->fonts_data->cell_height / 2;
    double y = frame->mouse_y;
    bool upwards = y <= (w->geometry.top + margin);
    if (upwards || y >= w->geometry.bottom - margin) {
        if (do_drag_scroll(w, upwards)) {
            frame->last_mouse_activity_at = monotonic();
            return true;
        }
    }
    return false;
}

static inline void
extend_selection(Window *w, bool ended) {
    Screen *screen = w->render_data.screen;
    if (screen_has_selection(screen)) {
        screen_update_selection(screen, w->mouse_pos.cell_x, w->mouse_pos.cell_y, w->mouse_pos.in_left_half_of_cell, ended, false);
    }
}

static inline void
extend_url(Screen *screen, Line *line, index_type *x, index_type *y, char_type sentinel) {
    unsigned int count = 0;
    while(count++ < 10) {
        if (*x != line->xnum - 1) break;
        bool next_line_starts_with_url_chars = false;
        line = screen_visual_line(screen, *y + 2);
        if (line) next_line_starts_with_url_chars = line_startswith_url_chars(line);
        line = screen_visual_line(screen, *y + 1);
        if (!line) break;
        // we deliberately allow non-continued lines as some programs, like
        // mutt split URLs with newlines at line boundaries
        index_type new_x = line_url_end_at(line, 0, false, sentinel, next_line_starts_with_url_chars);
        if (!new_x && !line_startswith_url_chars(line)) break;
        *y += 1; *x = new_x;
    }
}

static inline char_type
get_url_sentinel(Line *line, index_type url_start) {
    char_type before = 0, sentinel;
    if (url_start > 0 && url_start < line->xnum) before = line->cpu_cells[url_start - 1].ch;
    switch(before) {
        case '"':
        case '\'':
        case '*':
            sentinel = before; break;
        case '(':
            sentinel = ')'; break;
        case '[':
            sentinel = ']'; break;
        case '{':
            sentinel = '}'; break;
        case '<':
            sentinel = '>'; break;
        default:
            sentinel = 0; break;
    }
    return sentinel;
}

static inline void
set_mouse_cursor_for_screen(Screen *screen) {
    mouse_cursor_shape = screen->modes.mouse_tracking_mode == NO_TRACKING ? OPT(default_pointer_shape): OPT(pointer_shape_when_grabbed);
}

static inline void
detect_url(Screen *screen, unsigned int x, unsigned int y) {
    bool has_url = false;
    index_type url_start, url_end = 0;
    Line *line = screen_visual_line(screen, y);
    if (line->cpu_cells[x].hyperlink_id) {
        mouse_cursor_shape = HAND;
        screen_mark_hyperlink(screen, x, y);
        return;
    }
    char_type sentinel;
    if (line) {
        url_start = line_url_start_at(line, x);
        sentinel = get_url_sentinel(line, url_start);
        if (url_start < line->xnum) {
            bool next_line_starts_with_url_chars = false;
            if (y < screen->lines - 1) {
                line = screen_visual_line(screen, y+1);
                next_line_starts_with_url_chars = line_startswith_url_chars(line);
                line = screen_visual_line(screen, y);
            }
            url_end = line_url_end_at(line, x, true, sentinel, next_line_starts_with_url_chars);
        }
        has_url = url_end > url_start;
    }
    if (has_url) {
        mouse_cursor_shape = HAND;
        index_type y_extended = y;
        extend_url(screen, line, &url_end, &y_extended, sentinel);
        screen_mark_url(screen, url_start, y, url_end, y_extended);
    } else {
        set_mouse_cursor_for_screen(screen);
        screen_mark_url(screen, 0, 0, 0, 0);
    }
}

static inline void
handle_mouse_movement_in_kitty(Window *w, int button, bool mouse_cell_changed) {
    Screen *screen = w->render_data.screen;
    if (screen->selections.in_progress && (button == global_state.active_drag_button)) {
        monotonic_t now = monotonic();
        if ((now - w->last_drag_scroll_at) >= ms_to_monotonic_t(20ll) || mouse_cell_changed) {
            update_drag(w);
            w->last_drag_scroll_at = now;
        }
    }

}

HANDLER(handle_move_event) {
    modifiers &= ~GLFW_LOCK_MASK;
    unsigned int x = 0, y = 0;
    if (OPT(focus_follows_mouse)) {
        Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
        if (window_idx != t->active_window) {
            call_boss(switch_focus_to, "K", t->windows[window_idx].id);
        }
    }
    bool in_left_half_of_cell = false;
    if (!cell_for_pos(w, &x, &y, &in_left_half_of_cell, global_state.callback_os_window)) return;
    Screen *screen = w->render_data.screen;
    if(OPT(detect_urls)) detect_url(screen, x, y);
    bool mouse_cell_changed = x != w->mouse_pos.cell_x || y != w->mouse_pos.cell_y;
    bool cell_half_changed = in_left_half_of_cell != w->mouse_pos.in_left_half_of_cell;
    w->mouse_pos.cell_x = x; w->mouse_pos.cell_y = y;
    w->mouse_pos.in_left_half_of_cell = in_left_half_of_cell;
    bool in_tracking_mode = (
        screen->modes.mouse_tracking_mode == ANY_MODE ||
        (screen->modes.mouse_tracking_mode == MOTION_MODE && button >= 0));
    bool handle_in_kitty = !in_tracking_mode || global_state.active_drag_in_window == w->id;
    if (handle_in_kitty) {
        handle_mouse_movement_in_kitty(w, button, mouse_cell_changed | cell_half_changed);
    } else {
        if (!mouse_cell_changed) return;
        int sz = encode_mouse_button(w, MAX(0, button), button >=0 ? DRAG : MOVE, modifiers);
        if (sz > 0) { mouse_event_buf[sz] = 0; write_escape_code_to_child(screen, CSI, mouse_event_buf); }
    }
}

static inline double
distance(double x1, double y1, double x2, double y2) {
    return sqrt((x1 - x2) * (x1 - x2) + (y1 - y2) * (y1 - y2));
}

static inline void
clear_click_queue(Window *w, int button) {
    if (0 <= button && button <= (ssize_t)arraysz(w->click_queues)) w->click_queues[button].length = 0;
}

#define N(n) (q->clicks[q->length - n])

static bool
release_is_click(Window *w, int button) {
    ClickQueue *q = &w->click_queues[button];
    double click_allowed_radius = 1.2 * (global_state.callback_os_window ? global_state.callback_os_window->fonts_data->cell_height : 20);
    monotonic_t now = monotonic();
    return (q->length > 0 && distance(N(1).x, N(1).y, w->mouse_pos.x, w->mouse_pos.y) <= click_allowed_radius && now - N(1).at < OPT(click_interval));
}

static unsigned
multi_click_count(Window *w, int button) {
    ClickQueue *q = &w->click_queues[button];
    double multi_click_allowed_radius = 1.2 * (global_state.callback_os_window ? global_state.callback_os_window->fonts_data->cell_height : 20);
    if (q->length > 2) {
        // possible triple-click
        if (
                N(1).at - N(3).at <= 2 * OPT(click_interval) &&
                distance(N(1).x, N(1).y, N(3).x, N(3).y) <= multi_click_allowed_radius
           ) return 3;
    }
    if (q->length > 1) {
        // possible double-click
        if (
                N(1).at - N(2).at <= OPT(click_interval) &&
                distance(N(1).x, N(1).y, N(2).x, N(2).y) <= multi_click_allowed_radius
           ) return 2;
    }
    return q->length ? 1 : 0;
}


static void
add_press(Window *w, int button, int modifiers) {
    if (button < 0 || button > (ssize_t)arraysz(w->click_queues)) return;
    modifiers &= ~GLFW_LOCK_MASK;
    ClickQueue *q = &w->click_queues[button];
    if (q->length == CLICK_QUEUE_SZ) { memmove(q->clicks, q->clicks + 1, sizeof(Click) * (CLICK_QUEUE_SZ - 1)); q->length--; }
    monotonic_t now = monotonic();
    N(0).at = now; N(0).button = button; N(0).modifiers = modifiers; N(0).x = w->mouse_pos.x; N(0).y = w->mouse_pos.y;
    q->length++;
    Screen *screen = w->render_data.screen;
    int count = multi_click_count(w, button);
    if (count > 1) {
        if (screen) dispatch_mouse_event(w, button, count, modifiers, screen->modes.mouse_tracking_mode != 0);
        if (count > 2) q->length = 0;
    }
}
#undef N

void
mouse_open_url(Window *w) {
    Screen *screen = w->render_data.screen;
    detect_url(screen, w->mouse_pos.cell_x, w->mouse_pos.cell_y);
    screen_open_url(screen);
}

typedef struct PendingClick {
    id_type window_id;
    int button, count, modifiers;
    bool grabbed;
    monotonic_t at;
} PendingClick;

static void
free_pending_click(id_type timer_id UNUSED, void *pc) { free(pc); }

void
send_pending_click_to_window(Window *w, void *data) {
    PendingClick *pc = (PendingClick*)data;
    ClickQueue *q = &w->click_queues[pc->button];
    // only send click if no presses have happened since the release that triggered the click
    if (q->length && q->clicks[q->length - 1].at <= pc->at) {
        dispatch_mouse_event(w, pc->button, pc->count, pc->modifiers, pc->grabbed);
    }
}

static void
dispatch_possible_click(Window *w, int button, int modifiers) {
    Screen *screen = w->render_data.screen;
    int count = multi_click_count(w, button);
    if (release_is_click(w, button)) {
        PendingClick *pc = calloc(sizeof(PendingClick), 1);
        if (pc) {
            pc->window_id = w->id;
            pc->at = monotonic();
            pc->button = button;
            pc->count = count == 2 ? -3 : -2;
            pc->modifiers = modifiers;
            pc->grabbed = screen->modes.mouse_tracking_mode != 0;
            add_main_loop_timer(OPT(click_interval), false, send_pending_click_to_window_id, pc, free_pending_click);
        }
    }
}

HANDLER(handle_button_event) {
    modifiers &= ~GLFW_LOCK_MASK;
    Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
    bool is_release = !global_state.callback_os_window->mouse_button_pressed[button];
    if (window_idx != t->active_window && !is_release) {
        call_boss(switch_focus_to, "K", t->windows[window_idx].id);
    }
    Screen *screen = w->render_data.screen;
    if (!screen) return;
    if (!dispatch_mouse_event(w, button, is_release ? -1 : 1, modifiers, screen->modes.mouse_tracking_mode != 0)) {
        if (screen->modes.mouse_tracking_mode != 0) {
            int sz = encode_mouse_button(w, button, is_release ? RELEASE : PRESS, modifiers);
            if (sz > 0) { mouse_event_buf[sz] = 0; write_escape_code_to_child(screen, CSI, mouse_event_buf); }
        }
    }
    if (is_release) dispatch_possible_click(w, button, modifiers);
    else add_press(w, button, modifiers);
}

static inline int
currently_pressed_button(void) {
    for (int i = 0; i <= GLFW_MOUSE_BUTTON_LAST; i++) {
        if (global_state.callback_os_window->mouse_button_pressed[i]) return i;
    }
    return -1;
}

HANDLER(handle_event) {
    modifiers &= ~GLFW_LOCK_MASK;
    if (button == -1) {
        button = currently_pressed_button();
        handle_move_event(w, button, modifiers, window_idx);
    } else {
        handle_button_event(w, button, modifiers, window_idx);
    }
}

static inline void
handle_tab_bar_mouse(int button, int UNUSED modifiers) {
    static monotonic_t last_click_at = 0;
    if (button != GLFW_MOUSE_BUTTON_LEFT || !global_state.callback_os_window->mouse_button_pressed[button]) return;
    monotonic_t now = monotonic();
    bool is_double = now - last_click_at <= OPT(click_interval);
    last_click_at = is_double ? 0 : now;
    call_boss(activate_tab_at, "KdO", global_state.callback_os_window->id, global_state.callback_os_window->mouse_x, is_double ? Py_True : Py_False);
}

static inline bool
mouse_in_region(Region *r) {
    if (r->left == r->right) return false;
    if (global_state.callback_os_window->mouse_y < r->top || global_state.callback_os_window->mouse_y > r->bottom) return false;
    if (global_state.callback_os_window->mouse_x < r->left || global_state.callback_os_window->mouse_x > r->right) return false;
    return true;
}

static inline Window*
window_for_id(id_type window_id) {
    Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
    for (unsigned int i = 0; i < t->num_windows; i++) {
        Window *w = t->windows + i;
        if (w->id == window_id) return w;
    }
    return NULL;
}

static inline Window*
window_for_event(unsigned int *window_idx, bool *in_tab_bar) {
    Region central, tab_bar;
    os_window_regions(global_state.callback_os_window, &central, &tab_bar);
    *in_tab_bar = mouse_in_region(&tab_bar);
    if (!*in_tab_bar && global_state.callback_os_window->num_tabs > 0) {
        Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
        for (unsigned int i = 0; i < t->num_windows; i++) {
            if (contains_mouse(t->windows + i) && t->windows[i].render_data.screen) {
                *window_idx = i;
                return t->windows + i;
            }
        }
    }
    return NULL;
}

static inline Window*
closest_window_for_event(unsigned int *window_idx) {
    Window *ans = NULL;
    double closest_distance = UINT_MAX;
    if (global_state.callback_os_window->num_tabs > 0) {
        Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
        for (unsigned int i = 0; i < t->num_windows; i++) {
            Window *w = t->windows + i;
            if (w->visible) {
                double d = distance_to_window(w);
                if (d < closest_distance) { ans = w; closest_distance = d; *window_idx = i; }
            }
        }
    }
    return ans;
}

void
focus_in_event() {
    // Ensure that no URL is highlighted and the mouse cursor is in default shape
    bool in_tab_bar;
    unsigned int window_idx = 0;
    mouse_cursor_shape = BEAM;
    Window *w = window_for_event(&window_idx, &in_tab_bar);
    if (w && w->render_data.screen) {
        screen_mark_url(w->render_data.screen, 0, 0, 0, 0);
        set_mouse_cursor_for_screen(w->render_data.screen);
    }
    set_mouse_cursor(mouse_cursor_shape);
}

void
enter_event() {
#ifdef __APPLE__
    // On cocoa there is no way to configure the window manager to
    // focus windows on mouse enter, so we do it ourselves
    if (OPT(focus_follows_mouse) && !global_state.callback_os_window->is_focused) {
        focus_os_window(global_state.callback_os_window, false);
    }
#endif
}

static void
end_drag(Window *w) {
    Screen *screen = w->render_data.screen;
    global_state.active_drag_in_window = 0;
    global_state.active_drag_button = -1;
    w->last_drag_scroll_at = 0;
    if (screen->selections.in_progress) {
        screen_update_selection(screen, w->mouse_pos.cell_x, w->mouse_pos.cell_y, w->mouse_pos.in_left_half_of_cell, true, false);
    }
}

typedef enum MouseSelectionType {
    MOUSE_SELECTION_NORMAL,
    MOUSE_SELECTION_EXTEND,
    MOUSE_SELECTION_RECTANGLE,
    MOUSE_SELECTION_WORD,
    MOUSE_SELECTION_LINE,
    MOUSE_SELECTION_LINE_FROM_POINT,
} MouseSelectionType;


void
mouse_selection(Window *w, int code, int button) {
    global_state.active_drag_in_window = w->id;
    global_state.active_drag_button = button;
    Screen *screen = w->render_data.screen;
    index_type start, end;
    unsigned int y1, y2;
#define S(mode) {\
        screen_start_selection(screen, w->mouse_pos.cell_x, w->mouse_pos.cell_y, w->mouse_pos.in_left_half_of_cell, false, mode); \
        screen_update_selection(screen, w->mouse_pos.cell_x, w->mouse_pos.cell_y, w->mouse_pos.in_left_half_of_cell, false, true); }

    switch((MouseSelectionType)code) {
        case MOUSE_SELECTION_NORMAL:
            screen_start_selection(screen, w->mouse_pos.cell_x, w->mouse_pos.cell_y, w->mouse_pos.in_left_half_of_cell, false, EXTEND_CELL);
            break;
        case MOUSE_SELECTION_RECTANGLE:
            screen_start_selection(screen, w->mouse_pos.cell_x, w->mouse_pos.cell_y, w->mouse_pos.in_left_half_of_cell, true, EXTEND_CELL);
            break;
        case MOUSE_SELECTION_WORD:
            if (screen_selection_range_for_word(screen, w->mouse_pos.cell_x, w->mouse_pos.cell_y, &y1, &y2, &start, &end, true)) S(EXTEND_WORD);
            break;
        case MOUSE_SELECTION_LINE:
            if (screen_selection_range_for_line(screen, w->mouse_pos.cell_y, &start, &end)) S(EXTEND_LINE);
            break;
        case MOUSE_SELECTION_LINE_FROM_POINT:
            if (screen_selection_range_for_line(screen, w->mouse_pos.cell_y, &start, &end) && end > w->mouse_pos.cell_x) S(EXTEND_LINE_FROM_POINT);
            break;
        case MOUSE_SELECTION_EXTEND:
            extend_selection(w, false);
            break;
    }
    set_mouse_cursor_when_dragging();
#undef S
}


void
mouse_event(int button, int modifiers, int action) {
    MouseShape old_cursor = mouse_cursor_shape;
    bool in_tab_bar;
    unsigned int window_idx = 0;
    Window *w = NULL;
    debug("%s mouse_button: %d %s", action == GLFW_RELEASE ? "\x1b[32mRelease\x1b[m" : (button < 0 ? "\x1b[36mMove\x1b[m" : "\x1b[31mPress\x1b[m"), button, format_mods(modifiers));
    if (global_state.active_drag_in_window) {
        if (button == -1) {  // drag move
            w = window_for_id(global_state.active_drag_in_window);
            if (w) {
                button = currently_pressed_button();
                if (button == global_state.active_drag_button) {
                    clamp_to_window = true;
                    Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
                    for (window_idx = 0; window_idx < t->num_windows && t->windows[window_idx].id != w->id; window_idx++);
                    handle_move_event(w, button, modifiers, window_idx);
                    clamp_to_window = false;
                    debug("handled as drag move\n");
                    return;
                }
            }
        }
        else if (action == GLFW_RELEASE && button == global_state.active_drag_button) {
            w = window_for_id(global_state.active_drag_in_window);
            if (w) {
                end_drag(w);
                debug("handled as drag end\n");
                dispatch_possible_click(w, button, modifiers);
                return;
            }
        }
    }
    w = window_for_event(&window_idx, &in_tab_bar);
    if (in_tab_bar) {
        mouse_cursor_shape = HAND;
        handle_tab_bar_mouse(button, modifiers);
        debug("handled by tab bar\n");
    } else if (w) {
        debug("grabbed: %d\n", w->render_data.screen->modes.mouse_tracking_mode != 0);
        handle_event(w, button, modifiers, window_idx);
    } else if (button == GLFW_MOUSE_BUTTON_LEFT && global_state.callback_os_window->mouse_button_pressed[button]) {
        // initial click, clamp it to the closest window
        w = closest_window_for_event(&window_idx);
        if (w) {
            clamp_to_window = true;
            debug("grabbed: %d\n", w->render_data.screen->modes.mouse_tracking_mode != 0);
            handle_event(w, button, modifiers, window_idx);
            clamp_to_window = false;
        } else debug("no window for event\n");
    }
    if (mouse_cursor_shape != old_cursor) {
        set_mouse_cursor(mouse_cursor_shape);
    }
}

void
scroll_event(double UNUSED xoffset, double yoffset, int flags, int modifiers) {
    bool in_tab_bar;
    static id_type window_for_momentum_scroll = 0;
    static bool main_screen_for_momentum_scroll = false;
    unsigned int window_idx = 0;
    Window *w = window_for_event(&window_idx, &in_tab_bar);
    if (!w && !in_tab_bar) {
        // allow scroll events even if window is not currently focused (in
        // which case on some platforms such as macOS the mouse location is zeroed so
        // window_for_event() does not work).
        Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
        if (t) w = t->windows + t->active_window;
    }
    if (!w) return;
    Screen *screen = w->render_data.screen;

    enum MomentumData { NoMomentumData, MomentumPhaseBegan, MomentumPhaseStationary, MomentumPhaseActive, MomentumPhaseEnded, MomentumPhaseCancelled, MomentumPhaseMayBegin };
    enum MomentumData momentum_data = (flags >> 1) & 7;

    switch(momentum_data) {
        case NoMomentumData:
            break;
        case MomentumPhaseBegan:
            window_for_momentum_scroll = w->id;
            main_screen_for_momentum_scroll = screen->linebuf == screen->main_linebuf;
            break;
        case MomentumPhaseStationary:
        case MomentumPhaseActive:
            if (window_for_momentum_scroll != w->id || main_screen_for_momentum_scroll != (screen->linebuf == screen->main_linebuf)) return;
            break;
        case MomentumPhaseEnded:
        case MomentumPhaseCancelled:
            window_for_momentum_scroll = 0;
            break;
        case MomentumPhaseMayBegin:
        default:
            break;
    }
    if (yoffset == 0.0) return;

    int s;
    bool is_high_resolution = flags & 1;

    if (is_high_resolution) {
        yoffset *= OPT(touch_scroll_multiplier);
        if (yoffset * screen->pending_scroll_pixels < 0) {
            screen->pending_scroll_pixels = 0;  // change of direction
        }
        double pixels = screen->pending_scroll_pixels + yoffset;
        if (fabs(pixels) < global_state.callback_os_window->fonts_data->cell_height) {
            screen->pending_scroll_pixels = pixels;
            return;
        }
        s = (int)round(pixels) / (int)global_state.callback_os_window->fonts_data->cell_height;
        screen->pending_scroll_pixels = pixels - s * (int) global_state.callback_os_window->fonts_data->cell_height;
    } else {
        if (!screen->modes.mouse_tracking_mode) {
            // Dont use multiplier if we are sending events to the application
            yoffset *= OPT(wheel_scroll_multiplier);
        } else if (OPT(wheel_scroll_multiplier) < 0) {
            // ensure that changing scroll direction still works, even though
            // we are not using wheel_scroll_multiplier
            yoffset *= -1;
        }
        s = (int) round(yoffset);
        // apparently on cocoa some mice generate really small yoffset values
        // when scrolling slowly https://github.com/kovidgoyal/kitty/issues/1238
        if (s == 0 && yoffset != 0) s = yoffset > 0 ? 1 : -1;
        screen->pending_scroll_pixels = 0;
    }
    if (s == 0) return;
    bool upwards = s > 0;
    if (screen->modes.mouse_tracking_mode) {
        int sz = encode_mouse_scroll(w, upwards, modifiers);
        if (sz > 0) {
            mouse_event_buf[sz] = 0;
            for (s = abs(s); s > 0; s--) {
                write_escape_code_to_child(screen, CSI, mouse_event_buf);
            }
        }
    } else {
        if (screen->linebuf == screen->main_linebuf) screen_history_scroll(screen, abs(s), upwards);
        else fake_scroll(w, abs(s), upwards);
    }
}

static PyObject*
send_mouse_event(PyObject *self UNUSED, PyObject *args) {
    Screen *screen;
    unsigned int x, y;
    int button, action, mods;
    if (!PyArg_ParseTuple(args, "O!IIiii", &Screen_Type, &screen, &x, &y, &button, &action, &mods)) return NULL;

    MouseTrackingMode mode = screen->modes.mouse_tracking_mode;
    if (mode == ANY_MODE || (mode == MOTION_MODE && action != MOVE) || (mode == BUTTON_MODE && (action == PRESS || action == RELEASE))) {
        int sz = encode_mouse_event_impl(x + 1, y + 1, screen->modes.mouse_tracking_protocol, button, action, mods);
        if (sz > 0) {
            mouse_event_buf[sz] = 0;
            write_escape_code_to_child(screen, CSI, mouse_event_buf);
            Py_RETURN_TRUE;
        }
    }
    Py_RETURN_FALSE;
}

static PyObject*
test_encode_mouse(PyObject *self UNUSED, PyObject *args) {
    unsigned int x, y;
    int mouse_tracking_protocol, button, action, mods;
    if (!PyArg_ParseTuple(args, "IIiiii", &x, &y, &mouse_tracking_protocol, &button, &action, &mods)) return NULL;
    int sz = encode_mouse_event_impl(x, y, mouse_tracking_protocol, button, action, mods);
    return PyUnicode_FromStringAndSize(mouse_event_buf, sz);
}

static PyObject*
mock_mouse_selection(PyObject *self UNUSED, PyObject *args) {
    PyObject *capsule;
    int button, code;
    if (!PyArg_ParseTuple(args, "O!ii", &PyCapsule_Type, &capsule, &button, &code)) return NULL;
    Window *w = PyCapsule_GetPointer(capsule, "Window");
    if (!w) return NULL;
    mouse_selection(w, code, button);
    Py_RETURN_NONE;
}

static PyObject*
send_mock_mouse_event_to_window(PyObject *self UNUSED, PyObject *args) {
    PyObject *capsule;
    int button, modifiers, is_release, clear_clicks, in_left_half_of_cell;
    unsigned int x, y;
    if (!PyArg_ParseTuple(args, "O!iipIIpp", &PyCapsule_Type, &capsule, &button, &modifiers, &is_release, &x, &y, &clear_clicks, &in_left_half_of_cell)) return NULL;
    Window *w = PyCapsule_GetPointer(capsule, "Window");
    if (!w) return NULL;
    if (clear_clicks) clear_click_queue(w, button);
    bool mouse_cell_changed = x != w->mouse_pos.cell_x || y != w->mouse_pos.cell_y || w->mouse_pos.in_left_half_of_cell != in_left_half_of_cell;
    w->mouse_pos.x = 10 * x; w->mouse_pos.y = 20 * y;
    w->mouse_pos.cell_x = x; w->mouse_pos.cell_y = y;
    w->mouse_pos.in_left_half_of_cell = in_left_half_of_cell;
    static int last_button_pressed = GLFW_MOUSE_BUTTON_LEFT;
    if (button < 0) {
        if (button == -2) do_drag_scroll(w, true);
        else if (button == -3) do_drag_scroll(w, false);
        else handle_mouse_movement_in_kitty(w, last_button_pressed, mouse_cell_changed);
    } else {
        if (global_state.active_drag_in_window && is_release && button == global_state.active_drag_button) {
            end_drag(w);
        } else {
            dispatch_mouse_event(w, button, is_release ? -1 : 1, modifiers, false);
            if (!is_release) {
                last_button_pressed = button;
                add_press(w, button, modifiers);
            }
        }
    }
    Py_RETURN_NONE;
}

static PyMethodDef module_methods[] = {
    METHODB(send_mouse_event, METH_VARARGS),
    METHODB(test_encode_mouse, METH_VARARGS),
    METHODB(send_mock_mouse_event_to_window, METH_VARARGS),
    METHODB(mock_mouse_selection, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_mouse(PyObject *module) {
    PyModule_AddIntMacro(module, PRESS);
    PyModule_AddIntMacro(module, RELEASE);
    PyModule_AddIntMacro(module, DRAG);
    PyModule_AddIntMacro(module, MOVE);
    PyModule_AddIntMacro(module, MOUSE_SELECTION_NORMAL);
    PyModule_AddIntMacro(module, MOUSE_SELECTION_EXTEND);
    PyModule_AddIntMacro(module, MOUSE_SELECTION_RECTANGLE);
    PyModule_AddIntMacro(module, MOUSE_SELECTION_WORD);
    PyModule_AddIntMacro(module, MOUSE_SELECTION_LINE);
    PyModule_AddIntMacro(module, MOUSE_SELECTION_LINE_FROM_POINT);
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
