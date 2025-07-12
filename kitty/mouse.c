/*
 * mouse.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"
#include "charsets.h"
#include <limits.h>
#include <math.h>
#include "glfw-wrapper.h"
#include "control-codes.h"

extern PyTypeObject Screen_Type;

static MouseShape mouse_cursor_shape = TEXT_POINTER;
typedef enum MouseActions { PRESS, RELEASE, DRAG, MOVE, LEAVE } MouseAction;
#define debug debug_input

// Encoding of mouse events {{{
#define SHIFT_INDICATOR  (1 << 2)
#define ALT_INDICATOR (1 << 3)
#define CONTROL_INDICATOR (1 << 4)
#define MOTION_INDICATOR  (1 << 5)
#define SCROLL_BUTTON_INDICATOR (1 << 6)
#define EXTRA_BUTTON_INDICATOR (1 << 7)
#define LEAVE_INDICATOR (1 << 8)


static unsigned int
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

static unsigned int
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

static int
encode_mouse_event_impl(const MousePosition *mpos, int mouse_tracking_protocol, int button, MouseAction action, int mods) {
    unsigned int cb = encode_button(button);
    switch (action) {
        case MOVE:
            if (cb == UINT_MAX) cb = 3;
            cb += 32;
            break;
        case LEAVE:
            if (mouse_tracking_protocol != SGR_PIXEL_PROTOCOL) return 0;
            cb = LEAVE_INDICATOR | MOTION_INDICATOR;
            break;
        default:
            if (cb == UINT_MAX) return 0;
            break;
    }
    if (action == DRAG || action == MOVE) cb |= MOTION_INDICATOR;
    else if (action == RELEASE && mouse_tracking_protocol < SGR_PROTOCOL) cb = 3;
    if (mods & GLFW_MOD_SHIFT) cb |= SHIFT_INDICATOR;
    if (mods & GLFW_MOD_ALT) cb |= ALT_INDICATOR;
    if (mods & GLFW_MOD_CONTROL) cb |= CONTROL_INDICATOR;
    int x = mpos->cell_x + 1, y = mpos->cell_y + 1;
    switch(mouse_tracking_protocol) {
        case SGR_PIXEL_PROTOCOL:
            x = (int)round(mpos->global_x);
            y = (int)round(mpos->global_y);
            /* fallthrough */
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
    Screen *screen = w->render_data.screen;
    return encode_mouse_event_impl(&w->mouse_pos, screen->modes.mouse_tracking_protocol, button, action, mods);
}

static int
encode_mouse_button(Window *w, int button, MouseAction action, int mods) {
    if (button == GLFW_MOUSE_BUTTON_LEFT) {
        switch(action) {
            case PRESS:
                global_state.tracked_drag_in_window = w->id;
                global_state.tracked_drag_button = button;
                break;
            case RELEASE:
                global_state.tracked_drag_in_window = 0;
                global_state.tracked_drag_button = -1;
                break;
            default:
                break;
        }
    }
    return encode_mouse_event(w, button_map(button), action, mods);
}

static int
encode_mouse_scroll(Window *w, int button, int mods) {
    return encode_mouse_event(w, button, PRESS, mods);
}

// }}}

static Window*
window_for_id(id_type window_id) {
    if (global_state.callback_os_window && global_state.callback_os_window->num_tabs) {
        Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
        for (unsigned int i = 0; i < t->num_windows; i++) {
            Window *w = t->windows + i;
            if (w->id == window_id) return w;
        }
    }
    return window_for_window_id(window_id);
}

static void
send_mouse_leave_event_if_needed(id_type currently_over_window, int modifiers) {
    if (global_state.mouse_hover_in_window != currently_over_window && global_state.mouse_hover_in_window) {
        Window *left_window = window_for_id(global_state.mouse_hover_in_window);
        global_state.mouse_hover_in_window = currently_over_window;
        if (left_window) {
            int sz = encode_mouse_event(left_window, 0, LEAVE, modifiers);
            if (sz > 0) {
                mouse_event_buf[sz] = 0;
                write_escape_code_to_child(left_window->render_data.screen, ESC_CSI, mouse_event_buf);
                debug("Sent mouse leave event to window: %llu\n", left_window->id);
            }
        }
    }
}

static bool
dispatch_mouse_event(Window *w, int button, int count, int modifiers, bool grabbed) {
    bool handled = false;
    if (w->render_data.screen && w->render_data.screen->callbacks != Py_None) {
        PyObject *callback_ret = PyObject_CallMethod(w->render_data.screen->callbacks, "on_mouse_event", "{si si si sO}",
            "button", button, "repeat_count", count, "mods", modifiers, "grabbed", grabbed ? Py_True : Py_False);
        if (callback_ret == NULL) PyErr_Print();
        else {
            handled = callback_ret == Py_True;
            Py_DECREF(callback_ret);
        }
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
            debug("\x1b[33mon_mouse_input\x1b[m: %s button: %s %sgrabbed: %d handled_in_kitty: %d\n", evname, bname, format_mods(modifiers), grabbed, handled);
        }
    }
    return handled;
}

static unsigned int
window_left(Window *w) {
    return w->geometry.left - w->padding.left;
}

static unsigned int
window_right(Window *w) {
    return w->geometry.right + w->padding.right;
}

static unsigned int
window_top(Window *w) {
    return w->geometry.top - w->padding.top;
}

static unsigned int
window_bottom(Window *w) {
    return w->geometry.bottom + w->padding.bottom;
}

static bool
contains_mouse(Window *w) {
    double x = global_state.callback_os_window->mouse_x, y = global_state.callback_os_window->mouse_y;
    return (w->visible && window_left(w) <= x && x <= window_right(w) && window_top(w) <= y && y <= window_bottom(w));
}

static double
distance_to_window(Window *w) {
    double x = global_state.callback_os_window->mouse_x, y = global_state.callback_os_window->mouse_y;
    double cx = (window_left(w) + window_right(w)) / 2.0;
    double cy = (window_top(w) + window_bottom(w)) / 2.0;
    return (x - cx) * (x - cx) + (y - cy) * (y - cy);
}

static bool clamp_to_window = false;

static bool
cell_for_pos(Window *w, unsigned int *x, unsigned int *y, bool *in_left_half_of_cell, OSWindow *os_window) {
    WindowGeometry *g = &w->geometry;
    Screen *screen = w->render_data.screen;
    if (!screen) return false;
    unsigned int qx = 0, qy = 0;
    bool in_left_half = true;
    double mouse_x = global_state.callback_os_window->mouse_x;
    double mouse_y = global_state.callback_os_window->mouse_y;
    double left = g->left, top = g->top, right = g->right, bottom = g->bottom;
    w->mouse_pos.global_x = mouse_x - left; w->mouse_pos.global_y = mouse_y - top;
    if (clamp_to_window) {
        mouse_x = MIN(MAX(mouse_x, left), right);
        mouse_y = MIN(MAX(mouse_y, top), bottom);
    }
    if (mouse_x < left || mouse_y < top || mouse_x > right || mouse_y > bottom) return false;
    if (mouse_x >= g->right) {
        qx = screen->columns - 1;
        in_left_half = false;
    } else if (mouse_x >= g->left) {
        double xval = (double)(mouse_x - g->left) / os_window->fonts_data->fcm.cell_width;
        double fxval = floor(xval);
        qx = (unsigned int)fxval;
        in_left_half = (xval - fxval <= 0.5) ? true : false;
    }
    if (mouse_y >= g->bottom) qy = screen->lines - 1;
    else if (mouse_y >= g->top) qy = (unsigned int)((double)(mouse_y - g->top) / os_window->fonts_data->fcm.cell_height);
    if (qx < screen->columns && qy < screen->lines) {
        *x = qx; *y = qy;
        *in_left_half_of_cell = in_left_half;
        return true;
    }
    return false;
}

#define HANDLER(name) static void name(Window UNUSED *w, int UNUSED button, int UNUSED modifiers, unsigned int UNUSED window_idx)

static void
set_mouse_cursor_when_dragging(Screen *screen) {
    MouseShape expected_shape = OPT(pointer_shape_when_dragging);
    if (screen && screen->selections.count && screen->selections.items[0].rectangle_select) expected_shape = OPT(pointer_shape_when_dragging_rectangle);
    if (mouse_cursor_shape != expected_shape) {
        mouse_cursor_shape = expected_shape;
        set_mouse_cursor(mouse_cursor_shape);
    }
}

static void
update_drag(Window *w) {
    Screen *screen = w->render_data.screen;
    if (screen && screen->selections.in_progress) {
        screen_update_selection(screen, w->mouse_pos.cell_x, w->mouse_pos.cell_y, w->mouse_pos.in_left_half_of_cell, (SelectionUpdate){0});
    }
    set_mouse_cursor_when_dragging(screen);
}

static bool
do_drag_scroll(Window *w, bool upwards) {
    Screen *screen = w->render_data.screen;
    if (screen->linebuf == screen->main_linebuf) {
        screen_history_scroll(screen, SCROLL_LINE, upwards);
        update_drag(w);
        if (mouse_cursor_shape != DEFAULT_POINTER) {
            mouse_cursor_shape = DEFAULT_POINTER;
            set_mouse_cursor(mouse_cursor_shape);
        }
        return true;
    }
    return false;
}

bool
drag_scroll(Window *w, OSWindow *frame) {
    unsigned int margin = frame->fonts_data->fcm.cell_height / 2;
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

static void
extend_selection(Window *w, bool ended, bool extend_nearest) {
    Screen *screen = w->render_data.screen;
    if (screen_has_selection(screen)) {
        screen_update_selection(screen, w->mouse_pos.cell_x, w->mouse_pos.cell_y, w->mouse_pos.in_left_half_of_cell,
                (SelectionUpdate){.ended=ended, .set_as_nearest_extend=extend_nearest});
    }
}

static void
set_mouse_cursor_for_screen(Screen *screen) {
    MouseShape s = screen_pointer_shape(screen);
    if (s != INVALID_POINTER) {
        mouse_cursor_shape = s;
    } else {
        if (screen->modes.mouse_tracking_mode == NO_TRACKING) {
            mouse_cursor_shape = OPT(default_pointer_shape);
        } else {
            mouse_cursor_shape = OPT(pointer_shape_when_grabbed);
        }
    }
}

static void
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

static void
detect_url(Screen *screen, unsigned int x, unsigned int y) {
    int hid = screen_detect_url(screen, x, y);
    screen->current_hyperlink_under_mouse.id = 0;
    if (hid != 0) {
        mouse_cursor_shape = POINTER_POINTER;
        if (hid > 0) {
            screen->current_hyperlink_under_mouse.id = (hyperlink_id_type)hid;
            screen->current_hyperlink_under_mouse.x = x;
            screen->current_hyperlink_under_mouse.y = y;
        }
    } else set_mouse_cursor_for_screen(screen);
}

static bool
should_handle_in_kitty(Window *w, Screen *screen, int button) {
    bool in_tracking_mode = (
        screen->modes.mouse_tracking_mode == ANY_MODE ||
        (screen->modes.mouse_tracking_mode == MOTION_MODE && button >= 0));
    return !in_tracking_mode || global_state.active_drag_in_window == w->id;
}

static bool
set_mouse_position(Window *w, bool *mouse_cell_changed, bool *cell_half_changed) {
    unsigned int x = 0, y = 0;
    bool in_left_half_of_cell = false;
    if (!cell_for_pos(w, &x, &y, &in_left_half_of_cell, global_state.callback_os_window)) return false;
    *mouse_cell_changed = x != w->mouse_pos.cell_x || y != w->mouse_pos.cell_y;
    *cell_half_changed = in_left_half_of_cell != w->mouse_pos.in_left_half_of_cell;
    w->mouse_pos.cell_x = x; w->mouse_pos.cell_y = y;
    w->mouse_pos.in_left_half_of_cell = in_left_half_of_cell;
    return true;
}

HANDLER(handle_move_event) {
    modifiers &= ~GLFW_LOCK_MASK;
    if (OPT(focus_follows_mouse)) {
        Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
        if (window_idx != t->active_window) {
            call_boss(switch_focus_to, "K", t->windows[window_idx].id);
        }
    }
    bool mouse_cell_changed = false;
    bool cell_half_changed = false;
    if (!set_mouse_position(w, &mouse_cell_changed, &cell_half_changed)) return;
    Screen *screen = w->render_data.screen;
    if (OPT(detect_urls)) detect_url(screen, w->mouse_pos.cell_x, w->mouse_pos.cell_y);
    if (should_handle_in_kitty(w, screen, button)) {
        handle_mouse_movement_in_kitty(w, button, mouse_cell_changed | cell_half_changed);
    } else {
        if (!mouse_cell_changed && screen->modes.mouse_tracking_protocol != SGR_PIXEL_PROTOCOL) return;
        int sz = encode_mouse_button(w, button, button >=0 ? DRAG : MOVE, modifiers);
        if (sz > 0) { mouse_event_buf[sz] = 0; write_escape_code_to_child(screen, ESC_CSI, mouse_event_buf); }
    }
}

static double
distance(double x1, double y1, double x2, double y2) {
    return sqrt((x1 - x2) * (x1 - x2) + (y1 - y2) * (y1 - y2));
}

static void
clear_click_queue(Window *w, int button) {
    if (0 <= button && button <= (ssize_t)arraysz(w->click_queues)) w->click_queues[button].length = 0;
}

#define N(n) (q->clicks[q->length - n])

static double
radius_for_multiclick(void) {
    return 0.5 * (global_state.callback_os_window ? global_state.callback_os_window->fonts_data->fcm.cell_height : 8);
}

static bool
release_is_click(const Window *w, int button) {
    const ClickQueue *q = &w->click_queues[button];
    monotonic_t now = monotonic();
    return (q->length > 0 && distance(N(1).x, N(1).y, MAX(0, w->mouse_pos.global_x), MAX(0, w->mouse_pos.global_y)) <= radius_for_multiclick() && now - N(1).at < OPT(click_interval));
}

static unsigned
multi_click_count(const Window *w, int button) {
    const ClickQueue *q = &w->click_queues[button];
    double multi_click_allowed_radius = radius_for_multiclick();
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
    if (button < 0 || button >= (ssize_t)arraysz(w->click_queues)) return;
    modifiers &= ~GLFW_LOCK_MASK;
    ClickQueue *q = &w->click_queues[button];
    if (q->length == CLICK_QUEUE_SZ) { memmove(q->clicks, q->clicks + 1, sizeof(Click) * (CLICK_QUEUE_SZ - 1)); q->length--; }
    monotonic_t now = monotonic();
    static unsigned long num = 0;
    N(0).at = now; N(0).button = button; N(0).modifiers = modifiers; N(0).x = MAX(0, w->mouse_pos.global_x); N(0).y = MAX(0, w->mouse_pos.global_y); N(0).num = ++num;
    q->length++;
    Screen *screen = w->render_data.screen;
    int count = multi_click_count(w, button);
    if (count > 1) {
        if (screen) dispatch_mouse_event(w, button, count, modifiers, screen->modes.mouse_tracking_mode != 0);
        if (count > 2) q->length = 0;
    }
}
#undef N

bool
mouse_open_url(Window *w) {
    Screen *screen = w->render_data.screen;
    detect_url(screen, w->mouse_pos.cell_x, w->mouse_pos.cell_y);
    return screen_open_url(screen);
}

bool
mouse_set_last_visited_cmd_output(Window *w) {
    Screen *screen = w->render_data.screen;
    return screen_set_last_visited_prompt(screen, w->mouse_pos.cell_y);
}

bool
mouse_select_cmd_output(Window *w) {
    Screen *screen = w->render_data.screen;
    return screen_select_cmd_output(screen, w->mouse_pos.cell_y);
}

bool
move_cursor_to_mouse_if_at_shell_prompt(Window *w) {
    Screen *screen = w->render_data.screen;
    int y = screen_cursor_at_a_shell_prompt(screen);
    if (y < 0 || (unsigned)y > w->mouse_pos.cell_y) return false;

    if (screen_prompt_supports_click_events(screen)) {
        int sz = encode_mouse_event_impl(&w->mouse_pos, SGR_PROTOCOL, 1, PRESS, 0);
        if (sz > 0) {
            mouse_event_buf[sz] = 0;
            write_escape_code_to_child(screen, ESC_CSI, mouse_event_buf);
            return true;
        }

        return false;
    } else {
        return screen_fake_move_cursor_to_position(screen, w->mouse_pos.cell_x, w->mouse_pos.cell_y);
    }
}


void
send_pending_click_to_window(Window *w, int i) {
    const id_type wid = w->id;
    if (i < 0) {
        while(true) {
            w = window_for_id(wid);
            if (!w || !w->pending_clicks.num) break;
            send_pending_click_to_window(w, w->pending_clicks.num - 1);
        }
        return;
    }
    PendingClick pc = w->pending_clicks.clicks[i];
    remove_i_from_array(w->pending_clicks.clicks, (unsigned)i, w->pending_clicks.num);
    const ClickQueue *q = &w->click_queues[pc.button];
    // only send click if no presses have happened since the release that triggered
    // the click or if the subsequent press is too far or too late for a double click
    if (!q->length) return;
#define press(n) q->clicks[q->length - n]
    if (
            press(1).at <= pc.at || // latest press is before click release
            (q->length > 1 && press(2).num == pc.press_num &&  (   // penultimate press is the press that belongs to this click
                press(1).at - press(2).at > OPT(click_interval) ||  // too long between the presses for it to be a double click
                distance(press(1).x, press(1).y, press(2).x, press(2).y) > pc.radius_for_multiclick  // presses are too far apart
            ))
    ) {
        MousePosition current_pos = w->mouse_pos;
        w->mouse_pos = pc.mouse_pos;
        dispatch_mouse_event(w, pc.button, pc.count, pc.modifiers, pc.grabbed);
        w = window_for_id(wid);
        if (w) w->mouse_pos = current_pos;
    }
#undef press
}

static void
dispatch_possible_click(Window *w, int button, int modifiers) {
    Screen *screen = w->render_data.screen;
    int count = multi_click_count(w, button);
    if (release_is_click(w, button)) {
        ensure_space_for(&(w->pending_clicks), clicks, PendingClick, w->pending_clicks.num + 1, capacity, 4, true);
        PendingClick *pc = w->pending_clicks.clicks + w->pending_clicks.num++;
        zero_at_ptr(pc);
        const ClickQueue *q = &w->click_queues[button];
        pc->press_num = q->length ? q->clicks[q->length - 1].num : 0;
        pc->window_id = w->id;
        pc->mouse_pos = w->mouse_pos;
        pc->at = monotonic();
        pc->button = button;
        pc->count = count == 2 ? -3 : -2;
        pc->modifiers = modifiers;
        pc->grabbed = screen->modes.mouse_tracking_mode != 0;
        pc->radius_for_multiclick = radius_for_multiclick();
        add_main_loop_timer(OPT(click_interval), false, dispatch_pending_clicks, NULL, NULL);
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
    bool a, b;
    if (!set_mouse_position(w, &a, &b)) return;
    id_type wid = w->id;
    if (!dispatch_mouse_event(w, button, is_release ? -1 : 1, modifiers, screen->modes.mouse_tracking_mode != 0)) {
        if (screen->modes.mouse_tracking_mode != 0) {
            int sz = encode_mouse_button(w, button, is_release ? RELEASE : PRESS, modifiers);
            if (sz > 0) { mouse_event_buf[sz] = 0; write_escape_code_to_child(screen, ESC_CSI, mouse_event_buf); }
        }
    }
    // the windows array might have been re-alloced in dispatch_mouse_event
    w = NULL;
    for (size_t i = 0; i < t->num_windows && !w; i++) if (t->windows[i].id == wid) w = t->windows + i;
    if (w) {
        if (is_release) dispatch_possible_click(w, button, modifiers);
        else add_press(w, button, modifiers);
    }
}

static int
currently_pressed_button(void) {
    for (int i = 0; i <= GLFW_MOUSE_BUTTON_LAST; i++) {
        if (global_state.callback_os_window->mouse_button_pressed[i]) return i;
    }
    return -1;
}

HANDLER(handle_event) {
    modifiers &= ~GLFW_LOCK_MASK;
    set_mouse_cursor_for_screen(w->render_data.screen);
    send_mouse_leave_event_if_needed(w->id, modifiers);
    global_state.mouse_hover_in_window = w->id;
    if (button == -1) {
        button = currently_pressed_button();
        handle_move_event(w, button, modifiers, window_idx);
    } else {
        handle_button_event(w, button, modifiers, window_idx);
    }
}

static void
handle_tab_bar_mouse(int button, int modifiers, int action) {
    send_mouse_leave_event_if_needed(0, modifiers);
    if (button > -1) {  // dont report motion events, as they are expensive and useless
        call_boss(handle_click_on_tab, "Kdiii", global_state.callback_os_window->id, global_state.callback_os_window->mouse_x, button, modifiers, action);
    }
}

static bool
mouse_in_region(Region *r) {
    if (r->left == r->right) return false;
    if (global_state.callback_os_window->mouse_y < r->top || global_state.callback_os_window->mouse_y > r->bottom) return false;
    if (global_state.callback_os_window->mouse_x < r->left || global_state.callback_os_window->mouse_x > r->right) return false;
    return true;
}

static Window*
window_for_event(unsigned int *window_idx, bool *in_tab_bar) {
    Region central, tab_bar;
    os_window_regions(global_state.callback_os_window, &central, &tab_bar);
    const bool in_central = mouse_in_region(&central);
    *in_tab_bar = false;
    const OSWindow* w = global_state.callback_os_window;
    if (!in_central) {
        if (
                (tab_bar.top < central.top && w->mouse_y <= central.top) ||
                (tab_bar.bottom > central.bottom && w->mouse_y >= central.bottom)
           ) *in_tab_bar = true;
    }
    if (in_central && global_state.callback_os_window->num_tabs > 0) {
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

static Window*
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
focus_in_event(void) {
    // Ensure that no URL is highlighted and the mouse cursor is in default shape
    bool in_tab_bar;
    unsigned int window_idx = 0;
    mouse_cursor_shape = TEXT_POINTER;
    Window *w = window_for_event(&window_idx, &in_tab_bar);
    if (w && w->render_data.screen) {
        screen_mark_url(w->render_data.screen, 0, 0, 0, 0);
        set_mouse_cursor_for_screen(w->render_data.screen);
    }
    set_mouse_cursor(mouse_cursor_shape);
}

void
update_mouse_pointer_shape(void) {
    mouse_cursor_shape = TEXT_POINTER;
    bool in_tab_bar;
    unsigned int window_idx = 0;
    Window *w = window_for_event(&window_idx, &in_tab_bar);
    if (in_tab_bar) { mouse_cursor_shape = POINTER_POINTER; }
    else if (w && w->render_data.screen) {
        screen_mark_url(w->render_data.screen, 0, 0, 0, 0);
        set_mouse_cursor_for_screen(w->render_data.screen);
    }
    set_mouse_cursor(mouse_cursor_shape);
}

void
leave_event(int modifiers) {
    if (global_state.redirect_mouse_handling || global_state.active_drag_in_window || global_state.tracked_drag_in_window || !global_state.mouse_hover_in_window) return;
    send_mouse_leave_event_if_needed(0, modifiers);
}

void
enter_event(int modifiers) {
#ifdef __APPLE__
    // On cocoa there is no way to configure the window manager to
    // focus windows on mouse enter, so we do it ourselves
    if (OPT(focus_follows_mouse) && !global_state.callback_os_window->is_focused) {
        id_type wid = global_state.callback_os_window->id;
        focus_os_window(global_state.callback_os_window, false, NULL);
        if (!global_state.callback_os_window) {
            global_state.callback_os_window = os_window_for_id(wid);
            if (!global_state.callback_os_window) return;
        }
    }
#endif
    // If the mouse is grabbed send a move event to update the cursor position
    // since the last report.
    if (global_state.redirect_mouse_handling || global_state.active_drag_in_window || global_state.tracked_drag_in_window) return;
    unsigned window_idx; bool in_tab_bar;
    Window *w = window_for_event(&window_idx, &in_tab_bar);
    send_mouse_leave_event_if_needed(w ? w->id : 0, modifiers);
    if (!w || in_tab_bar) return;
    global_state.mouse_hover_in_window = w->id;
    bool mouse_cell_changed = false, cell_half_changed = false;
    if (!set_mouse_position(w, &mouse_cell_changed, &cell_half_changed)) return;
    Screen *screen = w->render_data.screen;
    int button = currently_pressed_button();
    if (!screen || should_handle_in_kitty(w, screen, button)) return;
    int sz = encode_mouse_button(w, button, button >=0 ? DRAG : MOVE, modifiers);
    if (sz > 0) { mouse_event_buf[sz] = 0; write_escape_code_to_child(screen, ESC_CSI, mouse_event_buf); }
}

static void
end_drag(Window *w) {
    Screen *screen = w->render_data.screen;
    global_state.active_drag_in_window = 0;
    global_state.active_drag_button = -1;
    w->last_drag_scroll_at = 0;
    if (screen->selections.in_progress) {
        screen_update_selection(screen, w->mouse_pos.cell_x, w->mouse_pos.cell_y, w->mouse_pos.in_left_half_of_cell, (SelectionUpdate){.ended=true});
    }
}

typedef enum MouseSelectionType {
    MOUSE_SELECTION_NORMAL,
    MOUSE_SELECTION_EXTEND,
    MOUSE_SELECTION_RECTANGLE,
    MOUSE_SELECTION_WORD,
    MOUSE_SELECTION_LINE,
    MOUSE_SELECTION_LINE_FROM_POINT,
    MOUSE_SELECTION_WORD_AND_LINE_FROM_POINT,
    MOUSE_SELECTION_MOVE_END,
    MOUSE_SELECTION_UPTO_SURROUNDING_WHITESPACE,
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
        screen_update_selection(screen, w->mouse_pos.cell_x, w->mouse_pos.cell_y, w->mouse_pos.in_left_half_of_cell, (SelectionUpdate){.start_extended_selection=true}); }

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
        case MOUSE_SELECTION_WORD_AND_LINE_FROM_POINT:
            if (screen_selection_range_for_line(screen, w->mouse_pos.cell_y, &start, &end) && end > w->mouse_pos.cell_x) S(EXTEND_WORD_AND_LINE_FROM_POINT);
            break;
        case MOUSE_SELECTION_EXTEND:
            extend_selection(w, false, true);
            break;
        case MOUSE_SELECTION_MOVE_END:
            extend_selection(w, false, false);
            break;
        case MOUSE_SELECTION_UPTO_SURROUNDING_WHITESPACE:
            // TODO: Implement me for people migrating from urxvt
            break;
    }
    set_mouse_cursor_when_dragging(screen);
#undef S
}


void
mouse_event(const int button, int modifiers, int action) {
    MouseShape old_cursor = mouse_cursor_shape;
    bool in_tab_bar;
    unsigned int window_idx = 0;
    Window *w = NULL;
    if (OPT(debug_keyboard)) {
        if (button < 0) { debug("%s x: %.1f y: %.1f ", "\x1b[36mMove\x1b[m", global_state.callback_os_window->mouse_x, global_state.callback_os_window->mouse_y); }
        else { debug("%s mouse_button: %d %s", action == GLFW_RELEASE ? "\x1b[32mRelease\x1b[m" : "\x1b[31mPress\x1b[m", button, format_mods(modifiers)); }
    }
    if (global_state.redirect_mouse_handling) {
        w = window_for_event(&window_idx, &in_tab_bar);
        call_boss(mouse_event, "OK iiii dd",
                (in_tab_bar ? Py_True : Py_False), (w ? w->id : 0),
                action, modifiers, button, currently_pressed_button(),
                global_state.callback_os_window->mouse_x, global_state.callback_os_window->mouse_y
        );
        debug("mouse handling redirected\n");
        return;
    }
    if (global_state.active_drag_in_window) {
        if (button == -1) {  // drag move
            w = window_for_id(global_state.active_drag_in_window);
            if (w) {
                if (currently_pressed_button() == global_state.active_drag_button) {
                    clamp_to_window = true;
                    Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
                    for (window_idx = 0; window_idx < t->num_windows && t->windows[window_idx].id != w->id; window_idx++);
                    handle_move_event(w, currently_pressed_button(), modifiers, window_idx);
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
    if (global_state.tracked_drag_in_window) {
        if (button == -1) {  // drag move
            w = window_for_id(global_state.tracked_drag_in_window);
            if (w) {
                if (currently_pressed_button() == GLFW_MOUSE_BUTTON_LEFT) {
                    if (w->render_data.screen->modes.mouse_tracking_mode >= MOTION_MODE && w->render_data.screen->modes.mouse_tracking_protocol == SGR_PIXEL_PROTOCOL) {
                        clamp_to_window = true;
                        Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
                        for (window_idx = 0; window_idx < t->num_windows && t->windows[window_idx].id != w->id; window_idx++);
                        handle_move_event(w, global_state.tracked_drag_button, modifiers, window_idx);
                        clamp_to_window = false;
                        debug("sent to child as drag move\n");
                        return;
                    }
                }
            }
        } else if (action == GLFW_RELEASE && button == GLFW_MOUSE_BUTTON_LEFT) {
            w = window_for_id(global_state.tracked_drag_in_window);
            if (w && w->render_data.screen->modes.mouse_tracking_mode >= BUTTON_MODE && w->render_data.screen->modes.mouse_tracking_protocol >= SGR_PROTOCOL) {
                global_state.tracked_drag_in_window = 0;
                clamp_to_window = true;
                Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
                for (window_idx = 0; window_idx < t->num_windows && t->windows[window_idx].id != w->id; window_idx++);
                debug("sent to child as drag end\n");
                handle_button_event(w, button, modifiers, window_idx);
                clamp_to_window = false;
                return;
            }
        }
    }
    w = window_for_event(&window_idx, &in_tab_bar);
    if (in_tab_bar) {
        mouse_cursor_shape = POINTER_POINTER;
        handle_tab_bar_mouse(button, modifiers, action);
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
    } else debug("\n");
    if (mouse_cursor_shape != old_cursor) set_mouse_cursor(mouse_cursor_shape);
}

static int
scale_scroll(MouseTrackingMode mouse_tracking_mode, double offset, bool is_high_resolution, double *pending_scroll_pixels, int cell_size) {
// scale the scroll by the multiplier unless the mouse is grabbed. If the mouse is grabbed only change direction.
#define SCALE_SCROLL(which) { double scale = OPT(which); if (mouse_tracking_mode) scale /= fabs(scale); offset *= scale; }
    int s = 0;
    if (is_high_resolution) {
        SCALE_SCROLL(touch_scroll_multiplier);
        double pixels = *pending_scroll_pixels + offset;
        if (fabs(pixels) < cell_size) {
            *pending_scroll_pixels = pixels;
            return 0;
        }
        s = (int)round(pixels) / cell_size;
        *pending_scroll_pixels = pixels - s * cell_size;
    } else {
        SCALE_SCROLL(wheel_scroll_multiplier);
        s = (int) round(offset);
        if (offset != 0) {
            const int min_lines = mouse_tracking_mode ? 1 : OPT(wheel_scroll_min_lines);
            if (min_lines > 0 && abs(s) < min_lines) s = offset > 0 ? min_lines : -min_lines;
            // Always add the minimum number of lines when it is negative
            else if (min_lines < 0) s = offset > 0 ? s - min_lines : s + min_lines;
            // apparently on cocoa some mice generate really small yoffset values
            // when scrolling slowly https://github.com/kovidgoyal/kitty/issues/1238
            if (s == 0) s = offset > 0 ? 1 : -1;
        }
        *pending_scroll_pixels = 0;
    }
    return s;
#undef SCALE_SCROLL
}

void
scroll_event(double xoffset, double yoffset, int flags, int modifiers) {
    debug("\x1b[36mScroll\x1b[m xoffset: %f yoffset: %f flags: %x modifiers: %s\n", xoffset, yoffset, flags, format_mods(modifiers));
    bool in_tab_bar;
    static id_type window_for_momentum_scroll = 0;
    static bool main_screen_for_momentum_scroll = false;
    unsigned int window_idx = 0;
    // allow scroll events even if window is not currently focused (in
    // which case on some platforms such as macOS the mouse location is zeroed so
    // window_for_event() does not work).
    OSWindow *osw = global_state.callback_os_window;
    if (!osw->is_focused && osw->handle) {
        double mouse_x, mouse_y;
        glfwGetCursorPos((GLFWwindow*)osw->handle, &mouse_x, &mouse_y);
        osw->mouse_x = mouse_x * osw->viewport_x_ratio;
        osw->mouse_y = mouse_y * osw->viewport_y_ratio;
    }
    Window *w = window_for_event(&window_idx, &in_tab_bar);
    if (!w && !in_tab_bar) {
        // fallback to last active window
        Tab *t = osw->tabs + osw->active_tab;
        if (t) w = t->windows + t->active_window;
    }
    if (!w) return;
    // Also update mouse cursor position while kitty OS window is not focused.
    // Allows scroll events to be delivered to the child with correct pointer coordinates even when
    // the window is not focused on macOS
    if (!osw->is_focused) {
        unsigned int x = 0, y = 0;
        bool in_left_half_of_cell;
        if (cell_for_pos(w, &x, &y, &in_left_half_of_cell, osw)) {
            w->mouse_pos.cell_x = x; w->mouse_pos.cell_y = y;
            w->mouse_pos.in_left_half_of_cell = in_left_half_of_cell;
        }
    }
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
    int s;
    bool is_high_resolution = flags & 1;

    if (yoffset != 0.0) {
        s = scale_scroll(screen->modes.mouse_tracking_mode, yoffset, is_high_resolution, &screen->pending_scroll_pixels_y, global_state.callback_os_window->fonts_data->fcm.cell_height);
        if (s) {
            bool upwards = s > 0;
            if (screen->modes.mouse_tracking_mode) {
                int sz = encode_mouse_scroll(w, upwards ? 4 : 5, modifiers);
                if (sz > 0) {
                    mouse_event_buf[sz] = 0;
                    for (s = abs(s); s > 0; s--) {
                        write_escape_code_to_child(screen, ESC_CSI, mouse_event_buf);
                    }
                }
            } else {
                if (screen->linebuf == screen->main_linebuf) {
                    screen_history_scroll(screen, abs(s), upwards);
                    if (screen->selections.in_progress) update_drag(w);
                }
                else fake_scroll(w, abs(s), upwards);
            }
        }
    }
    if (xoffset != 0.0) {
        s = scale_scroll(screen->modes.mouse_tracking_mode, xoffset, is_high_resolution, &screen->pending_scroll_pixels_x, global_state.callback_os_window->fonts_data->fcm.cell_width);
        if (s) {
            if (screen->modes.mouse_tracking_mode) {
                int sz = encode_mouse_scroll(w, s > 0 ? 6 : 7, modifiers);
                if (sz > 0) {
                    mouse_event_buf[sz] = 0;
                    for (s = abs(s); s > 0; s--) {
                        write_escape_code_to_child(screen, ESC_CSI, mouse_event_buf);
                    }
                }
            }
        }
    }

}

static PyObject*
send_mouse_event(PyObject *self UNUSED, PyObject *args, PyObject *kw) {
    Screen *screen;
    int x, y, px=0, py=0, in_left_half_of_cell=0;

    int button, action, mods;
    static const char* kwlist[] = {"screen", "cell_x", "cell_y", "button", "action", "mods", "pixel_x", "pixel_y", "in_left_half_of_cell", NULL};
    if (!PyArg_ParseTupleAndKeywords(args, kw, "O!iiiii|iip", (char**)kwlist,
                &Screen_Type, &screen, &x, &y, &button, &action, &mods, &px, &py, &in_left_half_of_cell)) return NULL;

    MouseTrackingMode mode = screen->modes.mouse_tracking_mode;
    if (mode == ANY_MODE || (mode == MOTION_MODE && action != MOVE) || (mode == BUTTON_MODE && (action == PRESS || action == RELEASE))) {
        MousePosition mpos = {.cell_x = x, .cell_y = y, .global_x = px, .global_y = py, .in_left_half_of_cell = in_left_half_of_cell};
        int sz = encode_mouse_event_impl(&mpos, screen->modes.mouse_tracking_protocol, button, action, mods);
        if (sz > 0) {
            mouse_event_buf[sz] = 0;
            write_escape_code_to_child(screen, ESC_CSI, mouse_event_buf);
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
    MousePosition mpos = {.cell_x = x - 1, .cell_y = y - 1};
    int sz = encode_mouse_event_impl(&mpos, mouse_tracking_protocol, button, action, mods);
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
    w->mouse_pos.global_x = 10 * x; w->mouse_pos.global_y = 20 * y;
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
    {"send_mouse_event", (PyCFunction)(void (*) (void))(send_mouse_event), METH_VARARGS | METH_KEYWORDS, NULL},
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
    PyModule_AddIntMacro(module, MOUSE_SELECTION_WORD_AND_LINE_FROM_POINT);
    PyModule_AddIntMacro(module, MOUSE_SELECTION_MOVE_END);
    PyModule_AddIntMacro(module, MOUSE_SELECTION_UPTO_SURROUNDING_WHITESPACE);
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
