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

extern void set_click_cursor(bool yes);
static bool has_click_cursor = false;

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
    unsigned int qx = (unsigned int)((double)global_state.mouse_x / global_state.cell_width);
    unsigned int qy = (unsigned int)((double)global_state.mouse_y / global_state.cell_height);
    bool ret = false;
    Screen *screen = w->render_data.screen;
    if (screen && qx <= screen->columns && qy <= screen->lines) {
        *x = qx; *y = qy; ret = true;
    }
    return ret;
}

void 
handle_move_event(Window *w, int UNUSED button, int UNUSED modifiers, unsigned int UNUSED window_idx) {
    unsigned int x, y;
    if (cell_for_pos(w, &x, &y)) {
        Line *line = screen_visual_line(w->render_data.screen, y);
        has_click_cursor = (line && line_url_start_at(line, x) < line->xnum) ? true : false;
        if (x != w->mouse_cell_x || y != w->mouse_cell_y) {
            w->mouse_cell_x = x; w->mouse_cell_y = y;
        }
    }
}

void 
handle_button_event(Window *w, int button, int modifiers, unsigned int window_idx) {
    Tab *t = global_state.tabs + global_state.active_tab;
    bool is_release = !global_state.mouse_button_pressed[button];
    if (window_idx != t->active_window) {
        if (is_release) call_boss(switch_focus_to, "I", window_idx);
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
                // TODO: update_drag
                if (is_release) {
                    if (modifiers == (int)OPT(open_url_modifiers)) {
                        // TODO: click_url
                    } else if (!modifiers) {
                        // TODO: handle multi click
                    }
                }
                break;
            case GLFW_MOUSE_BUTTON_MIDDLE:
                if (is_release && !modifiers) { call_boss(paste_from_selection, NULL); return; }
                break;
        }
    } else {
    }
}

void 
handle_event(Window *w, int button, int modifiers, unsigned int window_idx) {
    switch(button) {
        case -1:
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

void handle_tab_bar_mouse(int button, int UNUSED modifiers) {
    if (button != GLFW_MOUSE_BUTTON_LEFT || !global_state.mouse_button_pressed[button]) return;
    call_boss(activate_tab_at, "d", global_state.mouse_x);
}

void
mouse_event(int button, int modifiers) {
    bool old_has_click_cursor = has_click_cursor;
    bool in_tab_bar = global_state.num_tabs > 1 && global_state.mouse_y >= global_state.viewport_height - global_state.cell_height ? true : false;
    has_click_cursor = false;
    if (in_tab_bar) { 
        has_click_cursor = true;
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
    if (has_click_cursor != old_has_click_cursor) {
        set_click_cursor(has_click_cursor);
    }
}
