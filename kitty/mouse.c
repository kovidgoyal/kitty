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

static inline bool
contains_mouse(Window *w) {
    WindowGeometry *g = &w->geometry;
    double x = global_state.callback_os_window->mouse_x, y = global_state.callback_os_window->mouse_y;
    return (w->visible && g->left <= x && x <= g->right && g->top <= y && y <= g->bottom);
}

static inline bool
cell_for_pos(Window *w, unsigned int *x, unsigned int *y) {
    WindowGeometry *g = &w->geometry;
    unsigned int qx = (unsigned int)((double)(global_state.callback_os_window->mouse_x - g->left) / global_state.cell_width);
    unsigned int qy = (unsigned int)((double)(global_state.callback_os_window->mouse_y - g->top) / global_state.cell_height);
    bool ret = false;
    Screen *screen = w->render_data.screen;
    if (screen && qx <= screen->columns && qy <= screen->lines) {
        *x = qx; *y = qy; ret = true;
    }
    return ret;
}

#define HANDLER(name) static inline void name(Window UNUSED *w, int UNUSED button, int UNUSED modifiers, unsigned int UNUSED window_idx)

static inline void
update_drag(bool from_button, Window *w, bool is_release, int modifiers) {
    Screen *screen = w->render_data.screen;
    if (from_button) {
        if (is_release) screen_update_selection(screen, w->mouse_cell_x, w->mouse_cell_y, true);
        else screen_start_selection(screen, w->mouse_cell_x, w->mouse_cell_y, modifiers == (int)OPT(rectangle_select_modifiers));
    } else if (screen->selection.in_progress) {
        screen_update_selection(screen, w->mouse_cell_x, w->mouse_cell_y, false);
        call_boss(set_primary_selection, NULL);
    }
}


bool
drag_scroll(Window *w, OSWindow *frame) {
    unsigned int margin = global_state.cell_height / 2;
    double x = frame->mouse_x, y = frame->mouse_y;
    if (y < w->geometry.top || y > w->geometry.bottom) return false;
    if (x < w->geometry.left || x > w->geometry.right) return false;
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
extend_url(Screen *screen, Line *line, index_type *x, index_type *y) {
    unsigned int count = 0;
    while(count++ < 10) {
        if (*x != line->xnum - 1) break;
        line = screen_visual_line(screen, *y + 1);
        if (!line) break; // we deliberately allow non-continued lines as some programs, like mutt split URLs with newlines at line boundaries
        index_type new_x = line_url_end_at(line, 0, false);
        if (!new_x) break;
        *y += 1; *x = new_x;
    }
}

static inline void
detect_url(Screen *screen, unsigned int x, unsigned int y) {
    bool has_url = false;
    index_type url_start, url_end = 0;
    Line *line = screen_visual_line(screen, y);
    if (line) {
        url_start = line_url_start_at(line, x);
        if (url_start < line->xnum) url_end = line_url_end_at(line, x, true);
        has_url = url_end > url_start;
    }
    if (has_url) {
        mouse_cursor_shape = HAND;
        index_type y_extended = y;
        extend_url(screen, line, &url_end, &y_extended);
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
    if (!cell_for_pos(w, &x, &y)) return;
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
    switch(count) {
        case 2:
            found_selection = screen_selection_range_for_word(screen, w->mouse_cell_x, w->mouse_cell_y, &start, &end);
            break;
        case 3:
            found_selection = screen_selection_range_for_line(screen, w->mouse_cell_y, &start, &end);
            break;
        default:
            break;
    }
    if (found_selection) {
        screen_start_selection(screen, start, w->mouse_cell_y, false);
        screen_update_selection(screen, end, w->mouse_cell_y, true);
        call_boss(set_primary_selection, NULL);
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
            modifiers == GLFW_MOD_SHIFT ||
            screen->modes.mouse_tracking_mode == 0 ||
            button == GLFW_MOUSE_BUTTON_MIDDLE ||
            (modifiers == (int)OPT(open_url_modifiers) && button == GLFW_MOUSE_BUTTON_LEFT)
        );
    if (handle_in_kitty) {
        switch(button) {
            case GLFW_MOUSE_BUTTON_LEFT:
                update_drag(true, w, is_release, modifiers);
                if (is_release) {
                    if (modifiers == (int)OPT(open_url_modifiers)) {
                        open_url(w);
                    } else {
                        if (is_release) add_click(w, button, modifiers, window_idx);
                    }
                }
                break;
            case GLFW_MOUSE_BUTTON_MIDDLE:
                if (is_release && !modifiers) { call_boss(paste_from_selection, NULL); return; }
                break;
        }
    } else {
        int sz = encode_mouse_event(w, button, is_release ? RELEASE : PRESS, modifiers);
        if (sz > 0) { mouse_event_buf[sz] = 0; write_escape_code_to_child(screen, CSI, mouse_event_buf); }
    }
}

HANDLER(handle_event) {
    switch(button) {
        case -1:
            for (int i = 0; i < GLFW_MOUSE_BUTTON_5; i++) { if (global_state.callback_os_window->mouse_button_pressed[i]) { button = i; break; } }
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

static inline Window*
window_for_event(unsigned int *window_idx, bool *in_tab_bar) {
    *in_tab_bar = global_state.callback_os_window->num_tabs > 1 && global_state.callback_os_window->mouse_y >= global_state.callback_os_window->viewport_height - global_state.cell_height;
    if (!*in_tab_bar && global_state.callback_os_window->num_tabs > 0) {
        Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
        for (unsigned int i = 0; i < t->num_windows; i++) {
            if (contains_mouse(t->windows + i) && t->windows[i].render_data.screen) {
                *window_idx = i; return t->windows + i;
            }
        }
    }
    return NULL;

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
mouse_event(int button, int modifiers) {
    MouseShape old_cursor = mouse_cursor_shape;
    bool in_tab_bar;
    unsigned int window_idx = 0;
    Window *w = window_for_event(&window_idx, &in_tab_bar);
    if (in_tab_bar) {
        mouse_cursor_shape = HAND;
        handle_tab_bar_mouse(button, modifiers);
    } else if(w) {
        handle_event(w, button, modifiers, window_idx);
    }
    if (mouse_cursor_shape != old_cursor) {
        set_mouse_cursor(mouse_cursor_shape);
    }
}

void
scroll_event(double UNUSED xoffset, double yoffset) {
    int s = (int) round(yoffset * OPT(wheel_scroll_multiplier));
    if (s == 0) return;
    bool upwards = s > 0;
    bool in_tab_bar;
    unsigned int window_idx = 0;
    Window *w = window_for_event(&window_idx, &in_tab_bar);
    if (w) {
        Screen *screen = w->render_data.screen;
        if (screen->linebuf == screen->main_linebuf) {
            screen_history_scroll(screen, abs(s), upwards);
        } else {
            if (screen->modes.mouse_tracking_mode) {
                int sz = encode_mouse_event(w, upwards ? GLFW_MOUSE_BUTTON_4 : GLFW_MOUSE_BUTTON_5, PRESS, 0);
                if (sz > 0) { mouse_event_buf[sz] = 0; write_escape_code_to_child(screen, CSI, mouse_event_buf); }
            } else {
                fake_scroll(abs(s), upwards);
            }
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
