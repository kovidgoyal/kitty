/*
 * mouse.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"
#include "screen.h"
#include "lineops.h"
#include <GLFW/glfw3.h>

extern void set_mouse_cursor(MouseShape);
static MouseShape mouse_cursor_shape = BEAM;

#define call_boss(name, ...) { \
    PyObject *cret_ = PyObject_CallMethod(global_state.boss, #name, __VA_ARGS__); \
    if (cret_ == NULL) { PyErr_Print(); } \
    else Py_DECREF(cret_); \
}

static inline bool
contains_mouse(Window *w) {
    WindowGeometry *g = &w->geometry;
    double x = global_state.mouse_x, y = global_state.mouse_y;
    return (w->visible && g->left <= x && x <= g->right && g->top <= y && y <= g->bottom) ? true : false;
}

static inline bool
cell_for_pos(Window *w, unsigned int *x, unsigned int *y) {
    WindowGeometry *g = &w->geometry;
    unsigned int qx = (unsigned int)((double)(global_state.mouse_x - g->left) / global_state.cell_width);
    unsigned int qy = (unsigned int)((double)(global_state.mouse_y - g->top) / global_state.cell_height);
    bool ret = false;
    Screen *screen = w->render_data.screen;
    if (screen && qx <= screen->columns && qy <= screen->lines) {
        *x = qx; *y = qy; ret = true;
    }
    return ret;
}

#define HANDLER(name) static inline void name(Window UNUSED *w, int UNUSED button, int UNUSED modifiers, unsigned int UNUSED window_idx)

static inline void
update_drag(bool from_button, Window *w, bool is_release) {
    Screen *screen = w->render_data.screen;
    if (from_button) {
        if (is_release) screen_update_selection(screen, w->mouse_cell_x, w->mouse_cell_y, true);
        else screen_start_selection(screen, w->mouse_cell_x, w->mouse_cell_y);
    } else if (screen->selection.in_progress) {
        screen_update_selection(screen, w->mouse_cell_x, w->mouse_cell_y, false);
        call_boss(set_primary_selection, NULL);
    }
}


bool
drag_scroll(Window *w) {
    unsigned int margin = global_state.cell_height / 2;
    double x = global_state.mouse_x, y = global_state.mouse_y;
    if (y < w->geometry.top || y > w->geometry.bottom) return false;
    if (x < w->geometry.left || x > w->geometry.right) return false;
    bool upwards = y <= w->geometry.top + margin ? true : false;
    if (upwards || y >= w->geometry.bottom - margin) {
        Screen *screen = w->render_data.screen;
        if (screen->linebuf == screen->main_linebuf) {
            screen_history_scroll(screen, SCROLL_LINE, upwards);
            update_drag(false, w, false);
            global_state.last_mouse_activity_at = monotonic();
            if (mouse_cursor_shape != ARROW) {
                mouse_cursor_shape = ARROW;
                set_mouse_cursor(mouse_cursor_shape);
            }
            return true;
        }
    }
    return false;
}


HANDLER(handle_move_event) {
    unsigned int x, y;
    if (!cell_for_pos(w, &x, &y)) return;
    Line *line = screen_visual_line(w->render_data.screen, y);
    mouse_cursor_shape = (line && line_url_start_at(line, x) < line->xnum) ? HAND : BEAM;
    bool mouse_cell_changed = x != w->mouse_cell_x || y != w->mouse_cell_y ? true : false;
    w->mouse_cell_x = x; w->mouse_cell_y = y;
    Screen *screen = w->render_data.screen;
    bool handle_in_kitty = (
            (screen->modes.mouse_tracking_mode == ANY_MODE ||
            (screen->modes.mouse_tracking_mode == MOTION_MODE && button >= 0)) &&
            !(global_state.is_key_pressed[GLFW_KEY_LEFT_SHIFT] || global_state.is_key_pressed[GLFW_KEY_RIGHT_SHIFT])
    ) ? false : true;
    if (handle_in_kitty) {
        if (screen->selection.in_progress && button == GLFW_MOUSE_BUTTON_LEFT) {
            double now = monotonic();
            if ((now - w->last_drag_scroll_at) >= 0.02 || mouse_cell_changed) {
                update_drag(false, w, false);
                w->last_drag_scroll_at = monotonic();
            }
        }
    } else {
        if (!mouse_cell_changed) return;
        // TODO: Implement this
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
        screen_start_selection(screen, start, w->mouse_cell_y);
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

HANDLER(handle_button_event) {
    Tab *t = global_state.tabs + global_state.active_tab;
    bool is_release = !global_state.mouse_button_pressed[button];
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
        ) ? true : false;
    if (handle_in_kitty) {
        switch(button) {
            case GLFW_MOUSE_BUTTON_LEFT:
                update_drag(true, w, is_release);
                if (is_release) {
                    if (modifiers == (int)OPT(open_url_modifiers)) {
                        // TODO: click_url
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
        // TODO: Implement this
    }
}

HANDLER(handle_event) {
    switch(button) {
        case -1:
            for (int i = 0; i < GLFW_MOUSE_BUTTON_5; i++) { if (global_state.mouse_button_pressed[i]) { button = i; break; } }
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
    if (button != GLFW_MOUSE_BUTTON_LEFT || !global_state.mouse_button_pressed[button]) return;
    call_boss(activate_tab_at, "d", global_state.mouse_x);
}

void
mouse_event(int button, int modifiers) {
    MouseShape old_cursor = mouse_cursor_shape;
    bool in_tab_bar = global_state.num_tabs > 1 && global_state.mouse_y >= global_state.viewport_height - global_state.cell_height ? true : false;
    if (in_tab_bar) { 
        mouse_cursor_shape = HAND;
        handle_tab_bar_mouse(button, modifiers); 
    } else {
        Tab *t = global_state.tabs + global_state.active_tab;
        for (unsigned int i = 0; i < t->num_windows; i++) {
            if (contains_mouse(t->windows + i) && t->windows[i].render_data.screen) {
                handle_event(t->windows + i, button, modifiers, i);
                break;
            }
        }
    }
    if (mouse_cursor_shape != old_cursor) {
        set_mouse_cursor(mouse_cursor_shape);
    }
}
