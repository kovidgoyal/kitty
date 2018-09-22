/*
 * mouse.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"
#include "screen.h"
#include "lineops.h"
#include <limits.h>
#include <math.h>
#include "glfw-wrapper.h"
#include "control-codes.h"

static MouseShape mouse_cursor_shape = BEAM;
typedef enum MouseActions { PRESS, RELEASE, DRAG, MOVE } MouseAction;

// Encoding of mouse events {{{
#define SHIFT_INDICATOR  (1 << 2)
#define ALT_INDICATOR (1 << 3)
#define CONTROL_INDICATOR (1 << 4)
#define MOTION_INDICATOR  (1 << 5)
#define EXTRA_BUTTON_INDICATOR (1 << 6)


static inline unsigned int
button_map(int button) {
    switch(button) {
        case GLFW_MOUSE_BUTTON_LEFT:
            return 0;
        case GLFW_MOUSE_BUTTON_RIGHT:
            return 2;
        case GLFW_MOUSE_BUTTON_MIDDLE:
            return 1;
        case GLFW_MOUSE_BUTTON_4:
            return EXTRA_BUTTON_INDICATOR;
        case GLFW_MOUSE_BUTTON_5:
            return EXTRA_BUTTON_INDICATOR | 1;
        default:
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
        cb = button_map(button);
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
    unsigned int x = w->mouse_cell_x + 1, y = w->mouse_cell_y + 1; // 1 based indexing
    Screen *screen = w->render_data.screen;
    return encode_mouse_event_impl(x, y, screen->modes.mouse_tracking_protocol, button, action, mods);

}

// }}}

static inline double
window_left(Window *w, OSWindow *os_window) {
    return w->geometry.left - OPT(window_padding_width) * (os_window->logical_dpi_x / 72.0);
}

static inline double
window_right(Window *w, OSWindow *os_window) {
    return w->geometry.right + OPT(window_padding_width) * (os_window->logical_dpi_x / 72.0);
}

static inline double
window_top(Window *w, OSWindow *os_window) {
    return w->geometry.top - OPT(window_padding_width) * (os_window->logical_dpi_y / 72.0);
}

static inline double
window_bottom(Window *w, OSWindow *os_window) {
    return w->geometry.bottom + OPT(window_padding_width) * (os_window->logical_dpi_y / 72.0);
}

static inline bool
contains_mouse(Window *w, OSWindow *os_window) {
    double x = global_state.callback_os_window->mouse_x, y = global_state.callback_os_window->mouse_y;
    return (w->visible && window_left(w, os_window) <= x && x <= window_right(w, os_window) && window_top(w, os_window) <= y && y <= window_bottom(w, os_window));
}

static inline double
distance_to_window(Window *w, OSWindow *os_window) {
    double x = global_state.callback_os_window->mouse_x, y = global_state.callback_os_window->mouse_y;
    double cx = (window_left(w, os_window) + window_right(w, os_window)) / 2.0;
    double cy = (window_top(w, os_window) + window_bottom(w, os_window)) / 2.0;
    return (x - cx) * (x - cx) + (y - cy) * (y - cy);
}

static bool clamp_to_window = false;

static inline bool
cell_for_pos(Window *w, unsigned int *x, unsigned int *y, OSWindow *os_window) {
    WindowGeometry *g = &w->geometry;
    Screen *screen = w->render_data.screen;
    if (!screen) return false;
    unsigned int qx = 0, qy = 0;
    double mouse_x = global_state.callback_os_window->mouse_x;
    double mouse_y = global_state.callback_os_window->mouse_y;
    double left = window_left(w, os_window), top = window_top(w, os_window), right = window_right(w, os_window), bottom = window_bottom(w, os_window);
    if (clamp_to_window) {
        mouse_x = MIN(MAX(mouse_x, left), right);
        mouse_y = MIN(MAX(mouse_y, top), bottom);
    }
    if (mouse_x < left || mouse_y < top || mouse_x > right || mouse_y > bottom) return false;
    if (mouse_x >= g->right) qx = screen->columns - 1;
    else if (mouse_x >= g->left) qx = (unsigned int)((double)(mouse_x - g->left) / os_window->fonts_data->cell_width);
    if (mouse_y >= g->bottom) qy = screen->lines - 1;
    else if (mouse_y >= g->top) qy = (unsigned int)((double)(mouse_y - g->top) / os_window->fonts_data->cell_height);
    if (qx < screen->columns && qy < screen->lines) {
        *x = qx; *y = qy;
        return true;
    }
    return false;
}

#define HANDLER(name) static inline void name(Window UNUSED *w, int UNUSED button, int UNUSED modifiers, unsigned int UNUSED window_idx)

static inline void
update_drag(bool from_button, Window *w, bool is_release, int modifiers) {
    Screen *screen = w->render_data.screen;
    if (from_button) {
        if (is_release) {
            global_state.active_drag_in_window = 0;
            w->last_drag_scroll_at = 0;
            if (screen->selection.in_progress)
                screen_update_selection(screen, w->mouse_cell_x, w->mouse_cell_y, true);
        }
        else {
            global_state.active_drag_in_window = w->id;
            screen_start_selection(screen, w->mouse_cell_x, w->mouse_cell_y, modifiers == (int)OPT(rectangle_select_modifiers) || modifiers == ((int)OPT(rectangle_select_modifiers) | GLFW_MOD_SHIFT), EXTEND_CELL);
        }
    } else if (screen->selection.in_progress) {
        screen_update_selection(screen, w->mouse_cell_x, w->mouse_cell_y, false);
    }
}


bool
drag_scroll(Window *w, OSWindow *frame) {
    unsigned int margin = frame->fonts_data->cell_height / 2;
    double y = frame->mouse_y;
    bool upwards = y <= (w->geometry.top + margin);
    if (upwards || y >= w->geometry.bottom - margin) {
        Screen *screen = w->render_data.screen;
        if (screen->linebuf == screen->main_linebuf) {
            screen_history_scroll(screen, SCROLL_LINE, upwards);
            update_drag(false, w, false, 0);
            frame->last_mouse_activity_at = monotonic();
            if (mouse_cursor_shape != ARROW) {
                mouse_cursor_shape = ARROW;
                set_mouse_cursor(mouse_cursor_shape);
            }
            return true;
        }
    }
    return false;
}

static inline void
extend_selection(Window *w) {
    Screen *screen = w->render_data.screen;
    if (screen_has_selection(screen)) {
        screen_update_selection(screen, w->mouse_cell_x, w->mouse_cell_y, false);
    }
}

static inline void
extend_url(Screen *screen, Line *line, index_type *x, index_type *y, char_type sentinel) {
    unsigned int count = 0;
    while(count++ < 10) {
        if (*x != line->xnum - 1) break;
        line = screen_visual_line(screen, *y + 1);
        if (!line) break; // we deliberately allow non-continued lines as some programs, like mutt split URLs with newlines at line boundaries
        index_type new_x = line_url_end_at(line, 0, false, sentinel);
        if (!new_x) break;
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
detect_url(Screen *screen, unsigned int x, unsigned int y) {
    bool has_url = false;
    index_type url_start, url_end = 0;
    Line *line = screen_visual_line(screen, y);
    char_type sentinel;
    if (line) {
        url_start = line_url_start_at(line, x);
        sentinel = get_url_sentinel(line, url_start);
        if (url_start < line->xnum) url_end = line_url_end_at(line, x, true, sentinel);
        has_url = url_end > url_start;
    }
    if (has_url) {
        mouse_cursor_shape = HAND;
        index_type y_extended = y;
        extend_url(screen, line, &url_end, &y_extended, sentinel);
        screen_mark_url(screen, url_start, y, url_end, y_extended);
    } else {
        mouse_cursor_shape = BEAM;
        screen_mark_url(screen, 0, 0, 0, 0);
    }
}


HANDLER(handle_move_event) {
    unsigned int x = 0, y = 0;
    if (OPT(focus_follows_mouse)) {
        Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
        if (window_idx != t->active_window) {
            call_boss(switch_focus_to, "I", window_idx);
        }
    }
    if (!cell_for_pos(w, &x, &y, global_state.callback_os_window)) return;
    Screen *screen = w->render_data.screen;
    detect_url(screen, x, y);
    bool mouse_cell_changed = x != w->mouse_cell_x || y != w->mouse_cell_y;
    w->mouse_cell_x = x; w->mouse_cell_y = y;
    bool handle_in_kitty = (
            (screen->modes.mouse_tracking_mode == ANY_MODE ||
            (screen->modes.mouse_tracking_mode == MOTION_MODE && button >= 0)) &&
            !(global_state.callback_os_window->is_key_pressed[GLFW_KEY_LEFT_SHIFT] || global_state.callback_os_window->is_key_pressed[GLFW_KEY_RIGHT_SHIFT])
    ) ? false : true;
    if (handle_in_kitty) {
        if (screen->selection.in_progress && button == GLFW_MOUSE_BUTTON_LEFT) {
            double now = monotonic();
            if ((now - w->last_drag_scroll_at) >= 0.02 || mouse_cell_changed) {
                update_drag(false, w, false, 0);
                w->last_drag_scroll_at = monotonic();
            }
        }
    } else {
        if (!mouse_cell_changed) return;
        int sz = encode_mouse_event(w, MAX(0, button), button >=0 ? DRAG : MOVE, 0);
        if (sz > 0) { mouse_event_buf[sz] = 0; write_escape_code_to_child(screen, CSI, mouse_event_buf); }
    }
}

static inline void
multi_click(Window *w, unsigned int count) {
    Screen *screen = w->render_data.screen;
    index_type start, end;
    bool found_selection = false;
    SelectionExtendMode mode = EXTEND_CELL;
    unsigned int y1 = w->mouse_cell_y, y2 = w->mouse_cell_y;
    switch(count) {
        case 2:
            found_selection = screen_selection_range_for_word(screen, w->mouse_cell_x, &y1, &y2, &start, &end);
            mode = EXTEND_WORD;
            break;
        case 3:
            found_selection = screen_selection_range_for_line(screen, w->mouse_cell_y, &start, &end);
            mode = EXTEND_LINE;
            break;
        default:
            break;
    }
    if (found_selection) {
        screen_start_selection(screen, start, y1, false, mode);
        screen_update_selection(screen, end, y2, false);
    }
}

HANDLER(add_click) {
    ClickQueue *q = &w->click_queue;
    if (q->length == CLICK_QUEUE_SZ) { memmove(q->clicks, q->clicks + 1, sizeof(Click) * (CLICK_QUEUE_SZ - 1)); q->length--; }
    double now = monotonic();
#define N(n) (q->clicks[q->length - n])
    N(0).at = now; N(0).button = button; N(0).modifiers = modifiers;
    q->length++;
    // Now dispatch the multi-click if any
    if (q->length > 2 && N(1).at - N(3).at <= 2 * OPT(click_interval)) {
        multi_click(w, 3);
        q->length = 0;
    } else if (q->length > 1 && N(1).at - N(2).at <= OPT(click_interval)) {
        multi_click(w, 2);
    }
#undef N
}

static inline void
open_url(Window *w) {
    Screen *screen = w->render_data.screen;
    screen_open_url(screen);
}

HANDLER(handle_button_event) {
    Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
    bool is_release = !global_state.callback_os_window->mouse_button_pressed[button];
    if (window_idx != t->active_window) {
        call_boss(switch_focus_to, "I", window_idx);
    }
    Screen *screen = w->render_data.screen;
    if (!screen) return;
    bool handle_in_kitty = (
            modifiers == GLFW_MOD_SHIFT || modifiers == ((int)OPT(rectangle_select_modifiers) | GLFW_MOD_SHIFT) ||
            screen->modes.mouse_tracking_mode == 0 ||
            button == GLFW_MOUSE_BUTTON_MIDDLE ||
            (modifiers == (int)OPT(open_url_modifiers) && button == GLFW_MOUSE_BUTTON_LEFT)
        );
    if (handle_in_kitty) {
        switch(button) {
            case GLFW_MOUSE_BUTTON_LEFT:
                update_drag(true, w, is_release, modifiers);
                if (is_release) {
                    if (modifiers == (int)OPT(open_url_modifiers)) open_url(w);
                } else add_click(w, button, modifiers, window_idx);
                break;
            case GLFW_MOUSE_BUTTON_MIDDLE:
                if (is_release && !modifiers) { call_boss(paste_from_selection, NULL); return; }
                break;
            case GLFW_MOUSE_BUTTON_RIGHT:
                if (is_release) { extend_selection(w); }
                break;
        }
    } else {
        int sz = encode_mouse_event(w, button, is_release ? RELEASE : PRESS, modifiers);
        if (sz > 0) { mouse_event_buf[sz] = 0; write_escape_code_to_child(screen, CSI, mouse_event_buf); }
    }
}

static inline int
currently_pressed_button() {
    for (int i = 0; i < GLFW_MOUSE_BUTTON_5; i++) {
        if (global_state.callback_os_window->mouse_button_pressed[i]) return i;
    }
    return -1;
}

HANDLER(handle_event) {
    switch(button) {
        case -1:
            button = currently_pressed_button();
            handle_move_event(w, button, modifiers, window_idx);
            break;
        case GLFW_MOUSE_BUTTON_LEFT:
        case GLFW_MOUSE_BUTTON_RIGHT:
        case GLFW_MOUSE_BUTTON_MIDDLE:
        case GLFW_MOUSE_BUTTON_4:
        case GLFW_MOUSE_BUTTON_5:
            handle_button_event(w, button, modifiers, window_idx);
            break;
        default:
            break;
    }
}

static inline void
handle_tab_bar_mouse(int button, int UNUSED modifiers) {
    if (button != GLFW_MOUSE_BUTTON_LEFT || !global_state.callback_os_window->mouse_button_pressed[button]) return;
    call_boss(activate_tab_at, "Kd", global_state.callback_os_window->id, global_state.callback_os_window->mouse_x);
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
            if (contains_mouse(t->windows + i, global_state.callback_os_window) && t->windows[i].render_data.screen) {
                *window_idx = i; return t->windows + i;
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
            double d = distance_to_window(w, global_state.callback_os_window);
            if (d < closest_distance) { ans = w; closest_distance = d; *window_idx = i; }
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
    set_mouse_cursor(BEAM);
    Window *w = window_for_event(&window_idx, &in_tab_bar);
    if (w && w->render_data.screen) screen_mark_url(w->render_data.screen, 0, 0, 0, 0);
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

void
mouse_event(int button, int modifiers, int action) {
    MouseShape old_cursor = mouse_cursor_shape;
    bool in_tab_bar;
    unsigned int window_idx = 0;
    Window *w = NULL;
    if (global_state.active_drag_in_window) {
        if (button == -1) {  // drag move
            w = window_for_id(global_state.active_drag_in_window);
            if (w) {
                button = currently_pressed_button();
                if (button == GLFW_MOUSE_BUTTON_LEFT) {
                    clamp_to_window = true;
                    Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
                    for (window_idx = 0; window_idx < t->num_windows && t->windows[window_idx].id != w->id; window_idx++);
                    handle_move_event(w, button, modifiers, window_idx);
                    clamp_to_window = false;
                    return;
                }
            }
        }
        else if (action == GLFW_RELEASE && button == GLFW_MOUSE_BUTTON_LEFT) {
            w = window_for_id(global_state.active_drag_in_window);
            if (w) {
                update_drag(true, w, true, modifiers);
            }
        }
    }
    w = window_for_event(&window_idx, &in_tab_bar);
    if (in_tab_bar) {
        mouse_cursor_shape = HAND;
        handle_tab_bar_mouse(button, modifiers);
    } else if(w) {
        handle_event(w, button, modifiers, window_idx);
    } else if (button == GLFW_MOUSE_BUTTON_LEFT && global_state.callback_os_window->mouse_button_pressed[button]) {
        // initial click, clamp it to the closest window
        w = closest_window_for_event(&window_idx);
        if (w) {
            clamp_to_window = true;
            handle_event(w, button, modifiers, window_idx);
            clamp_to_window = false;
        }
    }
    if (mouse_cursor_shape != old_cursor) {
        set_mouse_cursor(mouse_cursor_shape);
    }
}

void
scroll_event(double UNUSED xoffset, double yoffset, int flags) {
    bool in_tab_bar;
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

    int s;
    bool is_high_resolution = flags & 1;
    if (is_high_resolution) {
        if (yoffset * global_state.callback_os_window->pending_scroll_pixels < 0) {
            global_state.callback_os_window->pending_scroll_pixels = 0;  // change of direction
        }
        double pixels = global_state.callback_os_window->pending_scroll_pixels + yoffset;
        if (fabs(pixels) < global_state.callback_os_window->fonts_data->cell_height) {
            global_state.callback_os_window->pending_scroll_pixels = pixels;
            return;
        }
        s = abs(((int)round(pixels))) / global_state.callback_os_window->fonts_data->cell_height;
        if (pixels < 0) s *= -1;
        global_state.callback_os_window->pending_scroll_pixels = pixels - s * (int) global_state.callback_os_window->fonts_data->cell_height;
    } else {
        s = (int) round(yoffset * OPT(wheel_scroll_multiplier));
        global_state.callback_os_window->pending_scroll_pixels = 0;
    }
    if (s == 0) return;
    bool upwards = s > 0;
    Screen *screen = w->render_data.screen;
    if (screen->linebuf == screen->main_linebuf) {
        screen_history_scroll(screen, abs(s), upwards);
    } else {
        if (screen->modes.mouse_tracking_mode) {
            int sz = encode_mouse_event(w, upwards ? GLFW_MOUSE_BUTTON_4 : GLFW_MOUSE_BUTTON_5, PRESS, 0);
            if (sz > 0) {
                mouse_event_buf[sz] = 0;
                if (is_high_resolution) {
                    for (s = abs(s); s > 0; s--) {
                        write_escape_code_to_child(screen, CSI, mouse_event_buf);
                    }
                } else {
                    // Since we are sending a mouse button 4/5 event, we ignore 's'
                    // and simply send one event per received scroll event
                    write_escape_code_to_child(screen, CSI, mouse_event_buf);
                }
            }
        } else {
            fake_scroll(abs(s), upwards);
        }
    }
}

static PyObject*
test_encode_mouse(PyObject *self UNUSED, PyObject *args) {
    unsigned int x, y;
    int mouse_tracking_protocol, button, action, mods;
    if (!PyArg_ParseTuple(args, "IIiiii", &x, &y, &mouse_tracking_protocol, &button, &action, &mods)) return NULL;
    int sz = encode_mouse_event_impl(x, y, mouse_tracking_protocol, button, action, mods);
    return PyUnicode_FromStringAndSize(mouse_event_buf, sz);
}

static PyMethodDef module_methods[] = {
    METHODB(test_encode_mouse, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_mouse(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
