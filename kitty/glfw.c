/*
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"
#include "cleanup.h"
#include "monotonic.h"
#include "charsets.h"
#include "control-codes.h"
#include <structmember.h>
#include "glfw-wrapper.h"
#include "gl.h"
#ifdef __APPLE__
#include "cocoa_window.h"
#else
#include "freetype_render_ui_text.h"
#endif
#define debug debug_rendering

typedef struct mouse_cursor {
    GLFWcursor *glfw;
    bool initialized, is_custom;
} mouse_cursor;

static mouse_cursor cursors[GLFW_INVALID_CURSOR+1] = {0};

static void
apply_swap_interval(int val) {
    (void)val;
#ifndef __APPLE__
    if (val < 0) val = OPT(sync_to_monitor) && !global_state.is_wayland ? 1 : 0;
    glfwSwapInterval(val);
#endif
}

void
get_platform_dependent_config_values(void *glfw_window) {
    if (OPT(click_interval) < 0) OPT(click_interval) = glfwGetDoubleClickInterval(glfw_window);
    if (OPT(cursor_blink_interval) < 0) {
        OPT(cursor_blink_interval) = ms_to_monotonic_t(500ll);
#ifdef __APPLE__
        monotonic_t cbi = cocoa_cursor_blink_interval();
        if (cbi >= 0) OPT(cursor_blink_interval) = cbi / 2;
#endif
    }
}

static const char*
appearance_name(GLFWColorScheme appearance) {
    const char *which = NULL;
    switch (appearance) {
        case GLFW_COLOR_SCHEME_NO_PREFERENCE: which = "no_preference"; break;
        case GLFW_COLOR_SCHEME_DARK: which = "dark"; break;
        case GLFW_COLOR_SCHEME_LIGHT: which = "light"; break;
    }
    return which;
}

static void
on_system_color_scheme_change(GLFWColorScheme appearance, bool is_initial_value) {
    const char *which = appearance_name(appearance);
    debug("system color-scheme changed to: %s is_initial_value: %d\n", which, is_initial_value);
    call_boss(on_system_color_scheme_change, "sO", which, is_initial_value ? Py_True : Py_False);
}

static void
on_clipboard_lost(GLFWClipboardType which) {
    call_boss(on_clipboard_lost, "s", which == GLFW_CLIPBOARD ? "clipboard" : "primary");
}

static bool
is_continuation_byte(unsigned char byte) {
    return (byte & 0xC0) == 0x80; // Continuation bytes have the form 10xxxxxx
}

static int
utf8_sequence_length(unsigned char byte) {
    if ((byte & 0x80) == 0) return 1; // 0xxxxxxx: Single-byte ASCII
    if ((byte & 0xE0) == 0xC0) return 2; // 110xxxxx: Two-byte sequence
    if ((byte & 0xF0) == 0xE0) return 3; // 1110xxxx: Three-byte sequence
    if ((byte & 0xF8) == 0xF0) return 4; // 11110xxx: Four-byte sequence
    return -1; // Invalid first byte
}

// Function to remove invalid UTF-8 bytes from the end of a string
static void
remove_invalid_utf8_from_end(char *str, size_t len) {
    if (!len) return;
    // Start from the end of the string and move backward
    size_t i = len - 1;
    while (i > 0) {
        if (is_continuation_byte((unsigned char)str[i])) {
            // Continue backward to find the start of the potential UTF-8 sequence
            size_t start = i;
            while (start > 0 && is_continuation_byte((unsigned char)str[start])) start--;
            // Check if the sequence is valid
            int seq_len = utf8_sequence_length((unsigned char)str[start]);
            if (seq_len > 0 && start + seq_len == len) return; // Valid sequence found, stop trimming
            // Invalid sequence, trim it
            str[start] = '\0';
            len = start;
            i = start - 1;
        } else {
            // Not a continuation byte, check if it's a valid start byte
            int seq_len = utf8_sequence_length((unsigned char)str[i]);
            if (seq_len > 0 && i + seq_len == len) return; // Valid sequence found, stop trimming
            // Invalid byte, trim it
            str[i] = '\0';
            len = i;
            i--;
        }
    }
    // Handle the case where the entire string is invalid
    if (utf8_sequence_length((unsigned char)str[0]) < 0) str[0] = '\0';
}

static void
strip_csi_(const char *title, char *buf, size_t bufsz) {
    enum { NORMAL, IN_ESC, IN_CSI} state = NORMAL;
    char *dest = buf, *last = &buf[bufsz-1];
    *dest = 0; *last = 0;

    for (; *title && dest < last; title++) {
        const unsigned char ch = *title;
        switch (state) {
            case NORMAL: {
                if (ch == 0x1b) { state = IN_ESC; }
                else *(dest++) = ch;
            } break;
            case IN_ESC: {
                if (ch == '[') { state = IN_CSI; }
                else {
                    if (ch >= ' ' && ch != DEL) *(dest++) = ch;
                    state = NORMAL;
                }
            } break;
            case IN_CSI: {
                if (!(('0' <= ch && ch <= '9') || ch == ';' || ch == ':')) {
                    if (ch > DEL) *(dest++) = ch;  // UTF-8 multibyte
                    state = NORMAL;
                }
            } break;
        }
    }
    *dest = 0;
    remove_invalid_utf8_from_end(buf, dest - buf);
}


void
update_menu_bar_title(PyObject *title UNUSED) {
#ifdef __APPLE__
    static char buf[2048];
    strip_csi_(PyUnicode_AsUTF8(title), buf, arraysz(buf));
    RAII_PyObject(stitle, PyUnicode_FromString(buf));
    if (stitle) cocoa_update_menu_bar_title(stitle);
    else PyErr_Print();
#endif
}


void
request_tick_callback(void) {
    glfwPostEmptyEvent();
}

static void
min_size_for_os_window(OSWindow *window, int *min_width, int *min_height) {
    *min_width = MAX(8u, window->fonts_data->fcm.cell_width + 1);
    *min_height = MAX(8u, window->fonts_data->fcm.cell_height + 1);
}


static void get_window_dpi(GLFWwindow *w, double *x, double *y);
static void get_window_content_scale(GLFWwindow *w, float *xscale, float *yscale, double *xdpi, double *ydpi);

static bool
set_layer_shell_config_for(OSWindow *w, GLFWLayerShellConfig *lsc) {
    if (lsc) {
        lsc->related.background_opacity = w->background_opacity;
        lsc->related.background_blur = OPT(background_blur);
        lsc->related.color_space = OPT(macos_colorspace);
        w->hide_on_focus_loss = lsc->hide_on_focus_loss;
    }
    return glfwSetLayerShellConfig(w->handle, lsc);
}

void
update_os_window_viewport(OSWindow *window, bool notify_boss) {
    int w, h, fw, fh;
    glfwGetFramebufferSize(window->handle, &fw, &fh);
    glfwGetWindowSize(window->handle, &w, &h);
    double xdpi = window->fonts_data->logical_dpi_x, ydpi = window->fonts_data->logical_dpi_y, new_xdpi, new_ydpi;
    float xscale, yscale;
    get_window_content_scale(window->handle, &xscale, &yscale, &new_xdpi, &new_ydpi);

    if (fw == window->viewport_width && fh == window->viewport_height && w == window->window_width && h == window->window_height && xdpi == new_xdpi && ydpi == new_ydpi) {
        return; // no change, ignore
    }
    int min_width, min_height; min_size_for_os_window(window, &min_width, &min_height);
    window->viewport_resized_at = monotonic();
    if (w <= 0 || h <= 0 || fw < min_width || fh < min_height || (xscale >=1 && fw < w) || (yscale >= 1 && fh < h)) {
        log_error("Invalid geometry ignored: framebuffer: %dx%d window: %dx%d scale: %f %f\n", fw, fh, w, h, xscale, yscale);
        if (!window->viewport_updated_at_least_once) {
            window->viewport_width = min_width; window->viewport_height = min_height;
            window->window_width = min_width; window->window_height = min_height;
            window->viewport_x_ratio = 1; window->viewport_y_ratio = 1;
            window->viewport_size_dirty = true;
            if (notify_boss) {
                call_boss(on_window_resize, "KiiO", window->id, window->viewport_width, window->viewport_height, Py_False);
            }
        }
        return;
    }
    window->viewport_updated_at_least_once = true;
    window->viewport_width = fw; window->viewport_height = fh;
    double xr = window->viewport_x_ratio, yr = window->viewport_y_ratio;
    window->viewport_x_ratio = (double)window->viewport_width / (double)w;
    window->viewport_y_ratio = (double)window->viewport_height / (double)h;
    bool dpi_changed = (xr != 0.0 && xr != window->viewport_x_ratio) || (yr != 0.0 && yr != window->viewport_y_ratio) || (xdpi != new_xdpi) || (ydpi != new_ydpi);

    window->viewport_size_dirty = true;
    window->viewport_width = MAX(window->viewport_width, min_width);
    window->viewport_height = MAX(window->viewport_height, min_height);
    window->window_width = MAX(w, min_width);
    window->window_height = MAX(h, min_height);
    if (notify_boss) {
        call_boss(on_window_resize, "KiiO", window->id, window->viewport_width, window->viewport_height, dpi_changed ? Py_True : Py_False);
    }
    if (dpi_changed && window->is_layer_shell && window->handle) set_layer_shell_config_for(window, NULL);
}

// callbacks {{{

void
update_os_window_references(void) {
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = global_state.os_windows + i;
        if (w->handle) glfwSetWindowUserPointer(w->handle, w);
    }
}

static OSWindow*
os_window_for_glfw_window(GLFWwindow *w) {
    OSWindow *ans = glfwGetWindowUserPointer(w);
    if (ans != NULL) return ans;
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        if ((GLFWwindow*)(global_state.os_windows[i].handle) == w) {
            return global_state.os_windows + i;
        }
    }
    return NULL;
}

static bool
set_callback_window(GLFWwindow *w) {
    global_state.callback_os_window = os_window_for_glfw_window(w);
    return global_state.callback_os_window != NULL;
}

static bool
is_window_ready_for_callbacks(void) {
    OSWindow *w = global_state.callback_os_window;
    if (w->num_tabs == 0) return false;
    Tab *t = w->tabs + w->active_tab;
    if (t->num_windows == 0) return false;
    return true;
}

#define WINDOW_CALLBACK(name, fmt, ...) call_boss(name, "K" fmt, global_state.callback_os_window->id, __VA_ARGS__)

static void
show_mouse_cursor(GLFWwindow *w) {
    glfwSetInputMode(w, GLFW_CURSOR, GLFW_CURSOR_NORMAL);
}

void
cursor_active_callback(GLFWwindow *w, monotonic_t now) {
    if (OPT(mouse_hide.unhide_wait) == 0) {
        show_mouse_cursor(w);
    } else if (OPT(mouse_hide.unhide_wait) > 0) {
            if (global_state.callback_os_window->mouse_activate_deadline == -1) {
                global_state.callback_os_window->mouse_activate_deadline = OPT(mouse_hide.unhide_wait) + now;
                global_state.callback_os_window->mouse_show_threshold = (int) (monotonic_t_to_s_double(OPT(mouse_hide.unhide_wait)) * OPT(mouse_hide.unhide_threshold));
            } else if (now < global_state.callback_os_window->mouse_activate_deadline) {
                if (global_state.callback_os_window->mouse_show_threshold > 0) {
                    global_state.callback_os_window->mouse_show_threshold--;
                }
            } else {
                if (
                        now < global_state.callback_os_window->mouse_activate_deadline + s_double_to_monotonic_t(0.5) &&
                        global_state.callback_os_window->mouse_show_threshold == 0
                ) {
                    show_mouse_cursor(w);
                }
                global_state.callback_os_window->mouse_activate_deadline = -1;
            }
    }
}

void
blank_os_window(OSWindow *osw) {
    color_type color = OPT(background);
    if (osw->num_tabs > 0) {
        Tab *t = osw->tabs + osw->active_tab;
        if (t->num_windows == 1) {
            Window *w = t->windows + t->active_window;
            Screen *s = w->render_data.screen;
            if (s) {
                color = colorprofile_to_color(s->color_profile, s->color_profile->overridden.default_bg, s->color_profile->configured.default_bg).rgb;
            }
        }
    }
    blank_canvas(osw->is_semi_transparent ? osw->background_opacity : 1.0f, color);
}

static void
window_pos_callback(GLFWwindow* window, int x UNUSED, int y UNUSED) {
    if (!set_callback_window(window)) return;
#ifdef __APPLE__
    // Apple needs IME position to be accurate before the next key event
    OSWindow *osw = global_state.callback_os_window;
    if (osw->is_focused && is_window_ready_for_callbacks()) {
        Tab *tab = osw->tabs + osw->active_tab;
        Window *w = tab->windows + tab->active_window;
        if (w->render_data.screen) update_ime_position(w, w->render_data.screen);
    }
#endif
    global_state.callback_os_window = NULL;
}

static void
window_close_callback(GLFWwindow* window) {
    if (!set_callback_window(window)) return;
    global_state.callback_os_window->close_request = CONFIRMABLE_CLOSE_REQUESTED;
    global_state.has_pending_closes = true;
    request_tick_callback();
    glfwSetWindowShouldClose(window, false);
    global_state.callback_os_window = NULL;
}

static void
window_occlusion_callback(GLFWwindow *window, bool occluded) {
    if (!set_callback_window(window)) return;
    debug("OSWindow %llu occlusion state changed, occluded: %d\n", global_state.callback_os_window->id, occluded);
    if (!occluded) global_state.check_for_active_animated_images = true;
    request_tick_callback();
    global_state.callback_os_window = NULL;
}

static void
window_iconify_callback(GLFWwindow *window, int iconified) {
    if (!set_callback_window(window)) return;
    if (!iconified) global_state.check_for_active_animated_images = true;
    request_tick_callback();
    global_state.callback_os_window = NULL;
}

#ifdef __APPLE__
static void
cocoa_out_of_sequence_render(OSWindow *window) {
    make_os_window_context_current(window);
    window->needs_render = true;
    bool rendered = render_os_window(window, monotonic(), true);
    if (!rendered) {
        blank_os_window(window);
        swap_window_buffers(window);
    }
    window->needs_render = true;
}

static void
cocoa_os_window_resized(GLFWwindow *w) {
    if (!set_callback_window(w)) return;
    if (global_state.callback_os_window->ignore_resize_events) return;
    cocoa_out_of_sequence_render(global_state.callback_os_window);
    global_state.callback_os_window = NULL;
}
#endif



void
change_live_resize_state(OSWindow *w, bool in_progress) {
    if (in_progress != w->live_resize.in_progress) {
        w->live_resize.in_progress = in_progress;
        w->live_resize.num_of_resize_events = 0;
#ifdef __APPLE__
        cocoa_out_of_sequence_render(w);
#else
        GLFWwindow *orig_ctx = make_os_window_context_current(w);
        apply_swap_interval(in_progress ? 0 : -1);
        if (orig_ctx) glfwMakeContextCurrent(orig_ctx);

#endif
    }
}

static void
live_resize_callback(GLFWwindow *w, bool started) {
    if (!set_callback_window(w)) return;
    if (global_state.callback_os_window->ignore_resize_events) return;
    global_state.callback_os_window->live_resize.from_os_notification = true;
    change_live_resize_state(global_state.callback_os_window, true);
    global_state.has_pending_resizes = true;
    if (!started) {
        global_state.callback_os_window->live_resize.os_says_resize_complete = true;
        request_tick_callback();
    }
    global_state.callback_os_window = NULL;
}

static void
framebuffer_size_callback(GLFWwindow *w, int width, int height) {
    if (!set_callback_window(w)) return;
    if (global_state.callback_os_window->ignore_resize_events) return;
    int min_width, min_height; min_size_for_os_window(global_state.callback_os_window, &min_width, &min_height);
    if (width >= min_width && height >= min_height) {
        OSWindow *window = global_state.callback_os_window;
        global_state.has_pending_resizes = true;
        change_live_resize_state(global_state.callback_os_window, true);
        window->live_resize.last_resize_event_at = monotonic();
        window->live_resize.width = MAX(0, width); window->live_resize.height = MAX(0, height);
        window->live_resize.num_of_resize_events++;
        make_os_window_context_current(window);
        update_surface_size(width, height, 0);
        request_tick_callback();
    } else log_error("Ignoring resize request for tiny size: %dx%d", width, height);
    global_state.callback_os_window = NULL;
}

static void
dpi_change_callback(GLFWwindow *w, float x_scale UNUSED, float y_scale UNUSED) {
    if (!set_callback_window(w)) return;
    if (global_state.callback_os_window->ignore_resize_events) return;
    // Ensure update_os_window_viewport() is called in the near future, it will
    // take care of DPI changes.
    OSWindow *window = global_state.callback_os_window;
    change_live_resize_state(global_state.callback_os_window, true);
    global_state.has_pending_resizes = true;
    window->live_resize.last_resize_event_at = monotonic();
    global_state.callback_os_window = NULL;
    request_tick_callback();
}

static void
refresh_callback(GLFWwindow *w) {
    if (!set_callback_window(w)) return;
    if (!global_state.callback_os_window->redraw_count) global_state.callback_os_window->redraw_count++;
    global_state.callback_os_window = NULL;
    request_tick_callback();
}

static int mods_at_last_key_or_button_event = 0;

#ifndef __APPLE__
typedef struct modifier_key_state {
    bool left, right;
} modifier_key_state;

static int
key_to_modifier(uint32_t key, bool *is_left) {
    *is_left = false;
    switch(key) {
        case GLFW_FKEY_LEFT_SHIFT: *is_left = true; /* fallthrough */
        case GLFW_FKEY_RIGHT_SHIFT:
            return GLFW_MOD_SHIFT;
        case GLFW_FKEY_LEFT_CONTROL: *is_left = true; /* fallthrough */
        case GLFW_FKEY_RIGHT_CONTROL:
            return GLFW_MOD_CONTROL;
        case GLFW_FKEY_LEFT_ALT: *is_left = true; /* fallthrough */
        case GLFW_FKEY_RIGHT_ALT:
            return GLFW_MOD_ALT;
        case GLFW_FKEY_LEFT_SUPER: *is_left = true; /* fallthrough */
        case GLFW_FKEY_RIGHT_SUPER:
            return GLFW_MOD_SUPER;
        case GLFW_FKEY_LEFT_HYPER: *is_left = true; /* fallthrough */
        case GLFW_FKEY_RIGHT_HYPER:
            return GLFW_MOD_HYPER;
        case GLFW_FKEY_LEFT_META: *is_left = true; /* fallthrough */
        case GLFW_FKEY_RIGHT_META:
            return GLFW_MOD_META;
        default:
            return -1;
    }
}


static void
update_modifier_state_on_modifier_key_event(GLFWkeyevent *ev, int key_modifier, bool is_left) {
    // Update mods state to be what the kitty keyboard protocol requires, as on Linux modifier key events do not update modifier bits
    static modifier_key_state all_states[8] = {0};
    modifier_key_state *state = all_states + MIN((unsigned)__builtin_ctz(key_modifier), sizeof(all_states)-1);
    const int modifier_was_set_before_event = ev->mods & key_modifier;
    const bool is_release = ev->action == GLFW_RELEASE;
    if (modifier_was_set_before_event) {
        // a press with modifier already set means other modifier key is pressed
        if (!is_release) { if (is_left) state->right = true; else state->left = true;  }
    } else {
        // if modifier is not set before event, means both keys are released
        state->left = false; state->right = false;
    }
    if (is_release) {
        if (is_left) state->left = false; else state->right = false;
        if (modifier_was_set_before_event && !state->left && !state->right) ev->mods &= ~key_modifier;
    } else {
        if (is_left) state->left = true; else state->right = true;
        ev->mods |= key_modifier;
    }
}
#endif

static void
key_callback(GLFWwindow *w, GLFWkeyevent *ev) {
    if (!set_callback_window(w)) return;
#ifndef __APPLE__
    bool is_left;
    int key_modifier = key_to_modifier(ev->key, &is_left);
    if (key_modifier != -1) update_modifier_state_on_modifier_key_event(ev, key_modifier, is_left);
#endif
    mods_at_last_key_or_button_event = ev->mods;
    global_state.callback_os_window->cursor_blink_zero_time = monotonic();
    if (is_window_ready_for_callbacks() && !ev->fake_event_on_focus_change) on_key_input(ev);
    global_state.callback_os_window = NULL;
    request_tick_callback();
}

static void
cursor_enter_callback(GLFWwindow *w, int entered) {
    if (!set_callback_window(w)) return;
    double x, y;
    glfwGetCursorPos(w, &x, &y);
    monotonic_t now = monotonic();
    global_state.callback_os_window->last_mouse_activity_at = now;
    global_state.callback_os_window->mouse_x = x * global_state.callback_os_window->viewport_x_ratio;
    global_state.callback_os_window->mouse_y = y * global_state.callback_os_window->viewport_y_ratio;
    if (entered) {
        debug_input("Mouse cursor entered window: %llu at %fx%f\n", global_state.callback_os_window->id, x, y);
        cursor_active_callback(w, now);
        if (is_window_ready_for_callbacks()) enter_event(mods_at_last_key_or_button_event);
    } else {
        debug_input("Mouse cursor left window: %llu\n", global_state.callback_os_window->id);
        if (is_window_ready_for_callbacks()) leave_event(mods_at_last_key_or_button_event);
    }
    request_tick_callback();
    global_state.callback_os_window = NULL;
}

static void
mouse_button_callback(GLFWwindow *w, int button, int action, int mods) {
    if (!set_callback_window(w)) return;
    monotonic_t now = monotonic();
    cursor_active_callback(w, now);
    mods_at_last_key_or_button_event = mods;
    OSWindow *window = global_state.callback_os_window;
    window->last_mouse_activity_at = now;
    if (button >= 0 && (unsigned int)button < arraysz(global_state.callback_os_window->mouse_button_pressed)) {
        if (!window->has_received_cursor_pos_event) {  // ensure mouse position is correct
            window->has_received_cursor_pos_event = true;
            double x, y;
            glfwGetCursorPos(w, &x, &y);
            window->mouse_x = x * window->viewport_x_ratio;
            window->mouse_y = y * window->viewport_y_ratio;
            if (is_window_ready_for_callbacks()) mouse_event(-1, mods, -1);
        }
        global_state.callback_os_window->mouse_button_pressed[button] = action == GLFW_PRESS ? true : false;
        if (is_window_ready_for_callbacks()) mouse_event(button, mods, action);
    }
    request_tick_callback();
    global_state.callback_os_window = NULL;
}

static void
cursor_pos_callback(GLFWwindow *w, double x, double y) {
    if (!set_callback_window(w)) return;
    monotonic_t now = monotonic();
    cursor_active_callback(w, now);
    global_state.callback_os_window->last_mouse_activity_at = now;
    global_state.callback_os_window->cursor_blink_zero_time = now;
    global_state.callback_os_window->mouse_x = x * global_state.callback_os_window->viewport_x_ratio;
    global_state.callback_os_window->mouse_y = y * global_state.callback_os_window->viewport_y_ratio;
    global_state.callback_os_window->has_received_cursor_pos_event = true;
    if (is_window_ready_for_callbacks()) mouse_event(-1, mods_at_last_key_or_button_event, -1);
    request_tick_callback();
    global_state.callback_os_window = NULL;
}

static void
scroll_callback(GLFWwindow *w, double xoffset, double yoffset, int flags, int mods) {
    if (!set_callback_window(w)) return;
    monotonic_t now = monotonic();
    if (OPT(mouse_hide.scroll_unhide)) {
        cursor_active_callback(w, now);
    }
    global_state.callback_os_window->last_mouse_activity_at = now;
    if (is_window_ready_for_callbacks()) scroll_event(xoffset, yoffset, flags, mods);
    request_tick_callback();
    global_state.callback_os_window = NULL;
}

static id_type focus_counter = 0;

static void
set_os_window_visibility(OSWindow *w, int set_visible) {
    if (set_visible) {
        glfwShowWindow(w->handle);
        w->needs_render = true;
        w->keep_rendering_till_swap = 256;  // try this many times
        request_tick_callback();
    } else glfwHideWindow(w->handle);
}

static void
update_os_window_visibility_based_on_focus(id_type timer_id UNUSED, void*d) {
    OSWindow * osw = os_window_for_id((uintptr_t)d);
    if (osw && osw->hide_on_focus_loss && !osw->is_focused) set_os_window_visibility(osw, 0);
}

static void
window_focus_callback(GLFWwindow *w, int focused) {
    if (!set_callback_window(w)) return;
#define osw global_state.callback_os_window
    debug_input("\x1b[35mon_focus_change\x1b[m: window id: 0x%llu focused: %d\n", osw->id, focused);
    bool focus_changed = osw->is_focused != focused;
    osw->is_focused = focused ? true : false;
    monotonic_t now = monotonic();
    id_type wid = osw->id;
    if (focused) {
        cursor_active_callback(w, now);
        focus_in_event();
        osw->last_focused_counter = ++focus_counter;
        global_state.check_for_active_animated_images = true;
    }
    osw->last_mouse_activity_at = now;
    osw->cursor_blink_zero_time = now;
    if (is_window_ready_for_callbacks()) {
        WINDOW_CALLBACK(on_focus, "O", focused ? Py_True : Py_False);
        if (!osw || osw->id != wid) osw = os_window_for_id(wid);
        if (osw) {
            GLFWIMEUpdateEvent ev = { .type = GLFW_IME_UPDATE_FOCUS, .focused = focused };
            glfwUpdateIMEState(osw->handle, &ev);
            if (focused) {
                Tab *tab = osw->tabs + osw->active_tab;
                Window *window = tab->windows + tab->active_window;
                if (window->render_data.screen) update_ime_position(window, window->render_data.screen);
            }
        }
    }
    request_tick_callback();
    if (osw && osw->handle && !focused && focus_changed && osw->hide_on_focus_loss && glfwGetWindowAttrib(osw->handle, GLFW_VISIBLE)) {
        add_main_loop_timer(0, false, update_os_window_visibility_based_on_focus, (void*)(uintptr_t)osw->id, NULL);
    }
    osw = NULL;
#undef osw
}

static int
drop_callback(GLFWwindow *w, const char *mime, const char *data, size_t sz) {
    if (!set_callback_window(w)) return 0;
#define RETURN(x) { global_state.callback_os_window = NULL; return x; }
    if (!data) {
        if (strcmp(mime, "text/uri-list") == 0) RETURN(3);
        if (strcmp(mime, "text/plain;charset=utf-8") == 0) RETURN(2);
        if (strcmp(mime, "text/plain") == 0) RETURN(1);
        RETURN(0);
    }
    WINDOW_CALLBACK(on_drop, "sy#", mime, data, (Py_ssize_t)sz);
    request_tick_callback();
    RETURN(0);
#undef RETURN
}

static void
application_close_requested_callback(int flags) {
    if (flags) {
        global_state.quit_request = IMPERATIVE_CLOSE_REQUESTED;
        global_state.has_pending_closes = true;
        request_tick_callback();
    } else {
        if (global_state.quit_request == NO_CLOSE_REQUESTED) {
            global_state.has_pending_closes = true;
            global_state.quit_request = CONFIRMABLE_CLOSE_REQUESTED;
            request_tick_callback();
        }
    }
}

static char*
get_current_selection(void) {
    if (!global_state.boss) return NULL;
    PyObject *ret = PyObject_CallMethod(global_state.boss, "get_active_selection", NULL);
    if (!ret) { PyErr_Print(); return NULL; }
    char* ans = NULL;
    if (PyUnicode_Check(ret)) ans = strdup(PyUnicode_AsUTF8(ret));
    Py_DECREF(ret);
    return ans;
}

static bool
has_current_selection(void) {
    if (!global_state.boss) return false;
    PyObject *ret = PyObject_CallMethod(global_state.boss, "has_active_selection", NULL);
    if (!ret) { PyErr_Print(); return false; }
    bool ans = ret == Py_True;
    Py_DECREF(ret);
    return ans;
}

void prepare_ime_position_update_event(OSWindow *osw, Window *w, Screen *screen, GLFWIMEUpdateEvent *ev);

static bool
get_ime_cursor_position(GLFWwindow *glfw_window, GLFWIMEUpdateEvent *ev) {
    bool ans = false;
    OSWindow *osw = os_window_for_glfw_window(glfw_window);
    if (osw && osw->is_focused && osw->num_tabs > 0) {
        Tab *tab = osw->tabs + osw->active_tab;
        if (tab->num_windows > 0) {
            Window *w = tab->windows + tab->active_window;
            Screen *screen = w->render_data.screen;
            if (screen) {
                prepare_ime_position_update_event(osw, w, screen, ev);
                ans = true;
            }
        }
    }
    return ans;
}


#ifdef __APPLE__
static bool
apple_url_open_callback(const char* url) {
    set_cocoa_pending_action(LAUNCH_URLS, url);
    return true;
}


bool
draw_window_title(OSWindow *window UNUSED, const char *text, color_type fg, color_type bg, uint8_t *output_buf, size_t width, size_t height) {
    static char buf[2048];
    strip_csi_(text, buf, arraysz(buf));
    return cocoa_render_line_of_text(buf, fg, bg, output_buf, width, height);
}


uint8_t*
draw_single_ascii_char(const char ch, size_t *result_width, size_t *result_height) {
    uint8_t *ans = render_single_ascii_char_as_mask(ch, result_width, result_height);
    if (PyErr_Occurred()) PyErr_Print();
    return ans;
}

#else

static FreeTypeRenderCtx csd_title_render_ctx = NULL;

static bool
ensure_csd_title_render_ctx(void) {
    if (!csd_title_render_ctx) {
        csd_title_render_ctx = create_freetype_render_context(NULL, true, false);
        if (!csd_title_render_ctx) {
            if (PyErr_Occurred()) PyErr_Print();
            return false;
        }
    }
    return true;
}

static bool
draw_text_callback(GLFWwindow *window, const char *text, uint32_t fg, uint32_t bg, uint8_t *output_buf, size_t width, size_t height, float x_offset, float y_offset, size_t right_margin, bool is_single_glyph) {
    if (!set_callback_window(window)) return false;
    if (!ensure_csd_title_render_ctx()) return false;
    double xdpi, ydpi;
    get_window_dpi(window, &xdpi, &ydpi);
    unsigned px_sz = 2 * height / 3;
    static char title[2048];
    if (!is_single_glyph) {
        snprintf(title, sizeof(title), " ❭ %s", text);
        text = title;
    }
    bool ok = render_single_line(csd_title_render_ctx, text, px_sz, fg, bg, output_buf, width, height, x_offset, y_offset, right_margin, is_single_glyph);
    if (!ok && PyErr_Occurred()) PyErr_Print();
    return ok;
}

bool
draw_window_title(OSWindow *window, const char *text, color_type fg, color_type bg, uint8_t *output_buf, size_t width, size_t height) {
    if (!ensure_csd_title_render_ctx()) return false;
    static char buf[2048];
    strip_csi_(text, buf, arraysz(buf));
    unsigned px_sz = (unsigned)(window->fonts_data->font_sz_in_pts * window->fonts_data->logical_dpi_y / 72.);
    px_sz = MIN(px_sz, 3 * height / 4);
#define RGB2BGR(x) (x & 0xFF000000) | ((x & 0xFF0000) >> 16) | (x & 0x00FF00) | ((x & 0x0000FF) << 16)
    bool ok = render_single_line(csd_title_render_ctx, buf, px_sz, RGB2BGR(fg), RGB2BGR(bg), output_buf, width, height, 0, 0, 0, false);
#undef RGB2BGR
    if (!ok && PyErr_Occurred()) PyErr_Print();
    return ok;
}

uint8_t*
draw_single_ascii_char(const char ch, size_t *result_width, size_t *result_height) {
    if (!ensure_csd_title_render_ctx()) return NULL;
    uint8_t *ans = render_single_ascii_char_as_mask(csd_title_render_ctx, ch, result_width, result_height);
    if (PyErr_Occurred()) PyErr_Print();
    return ans;
}
#endif
// }}}

static void
set_glfw_mouse_cursor(GLFWwindow *w, GLFWCursorShape shape) {
    if (!cursors[shape].initialized) {
        cursors[shape].initialized = true;
        cursors[shape].glfw = glfwCreateStandardCursor(shape);
    }
    if (cursors[shape].glfw) glfwSetCursor(w, cursors[shape].glfw);
}

static void
set_glfw_mouse_pointer_shape_in_window(GLFWwindow *w, MouseShape type) {
    switch(type) {
        case INVALID_POINTER: break;
        /* start enum to glfw (auto generated by gen-key-constants.py do not edit) */
        case DEFAULT_POINTER: set_glfw_mouse_cursor(w, GLFW_DEFAULT_CURSOR); break;
        case TEXT_POINTER: set_glfw_mouse_cursor(w, GLFW_TEXT_CURSOR); break;
        case POINTER_POINTER: set_glfw_mouse_cursor(w, GLFW_POINTER_CURSOR); break;
        case HELP_POINTER: set_glfw_mouse_cursor(w, GLFW_HELP_CURSOR); break;
        case WAIT_POINTER: set_glfw_mouse_cursor(w, GLFW_WAIT_CURSOR); break;
        case PROGRESS_POINTER: set_glfw_mouse_cursor(w, GLFW_PROGRESS_CURSOR); break;
        case CROSSHAIR_POINTER: set_glfw_mouse_cursor(w, GLFW_CROSSHAIR_CURSOR); break;
        case CELL_POINTER: set_glfw_mouse_cursor(w, GLFW_CELL_CURSOR); break;
        case VERTICAL_TEXT_POINTER: set_glfw_mouse_cursor(w, GLFW_VERTICAL_TEXT_CURSOR); break;
        case MOVE_POINTER: set_glfw_mouse_cursor(w, GLFW_MOVE_CURSOR); break;
        case E_RESIZE_POINTER: set_glfw_mouse_cursor(w, GLFW_E_RESIZE_CURSOR); break;
        case NE_RESIZE_POINTER: set_glfw_mouse_cursor(w, GLFW_NE_RESIZE_CURSOR); break;
        case NW_RESIZE_POINTER: set_glfw_mouse_cursor(w, GLFW_NW_RESIZE_CURSOR); break;
        case N_RESIZE_POINTER: set_glfw_mouse_cursor(w, GLFW_N_RESIZE_CURSOR); break;
        case SE_RESIZE_POINTER: set_glfw_mouse_cursor(w, GLFW_SE_RESIZE_CURSOR); break;
        case SW_RESIZE_POINTER: set_glfw_mouse_cursor(w, GLFW_SW_RESIZE_CURSOR); break;
        case S_RESIZE_POINTER: set_glfw_mouse_cursor(w, GLFW_S_RESIZE_CURSOR); break;
        case W_RESIZE_POINTER: set_glfw_mouse_cursor(w, GLFW_W_RESIZE_CURSOR); break;
        case EW_RESIZE_POINTER: set_glfw_mouse_cursor(w, GLFW_EW_RESIZE_CURSOR); break;
        case NS_RESIZE_POINTER: set_glfw_mouse_cursor(w, GLFW_NS_RESIZE_CURSOR); break;
        case NESW_RESIZE_POINTER: set_glfw_mouse_cursor(w, GLFW_NESW_RESIZE_CURSOR); break;
        case NWSE_RESIZE_POINTER: set_glfw_mouse_cursor(w, GLFW_NWSE_RESIZE_CURSOR); break;
        case ZOOM_IN_POINTER: set_glfw_mouse_cursor(w, GLFW_ZOOM_IN_CURSOR); break;
        case ZOOM_OUT_POINTER: set_glfw_mouse_cursor(w, GLFW_ZOOM_OUT_CURSOR); break;
        case ALIAS_POINTER: set_glfw_mouse_cursor(w, GLFW_ALIAS_CURSOR); break;
        case COPY_POINTER: set_glfw_mouse_cursor(w, GLFW_COPY_CURSOR); break;
        case NOT_ALLOWED_POINTER: set_glfw_mouse_cursor(w, GLFW_NOT_ALLOWED_CURSOR); break;
        case NO_DROP_POINTER: set_glfw_mouse_cursor(w, GLFW_NO_DROP_CURSOR); break;
        case GRAB_POINTER: set_glfw_mouse_cursor(w, GLFW_GRAB_CURSOR); break;
        case GRABBING_POINTER: set_glfw_mouse_cursor(w, GLFW_GRABBING_CURSOR); break;
/* end enum to glfw */
    }
}

void
set_mouse_cursor(MouseShape type) {
    if (global_state.callback_os_window) {
        GLFWwindow *w = (GLFWwindow*)global_state.callback_os_window->handle;
        set_glfw_mouse_pointer_shape_in_window(w, type);
    }
}

static GLFWimage logo = {0};

static PyObject*
set_default_window_icon(PyObject UNUSED *self, PyObject *args) {
    size_t sz;
    unsigned int width, height;
    const char *path;
    uint8_t *data;
    if(!PyArg_ParseTuple(args, "s", &path)) return NULL;
    if (png_path_to_bitmap(path, &data, &width, &height, &sz)) {
#ifndef __APPLE__
        if (!global_state.is_wayland && (width > 128 || height > 128)) {
            return PyErr_Format(PyExc_ValueError, "The window icon is too large (%dx%d). On X11 max window icon size is: 128x128. Create a file called ~/.config/kitty.app-128.png containing a 128x128 image to use as the window icon on X11.", width, height);
        }
#endif
        logo.width = width; logo.height = height;
        logo.pixels = data;
    }
    Py_RETURN_NONE;
}

static PyObject*
set_os_window_icon(PyObject UNUSED *self, PyObject *args) {
    size_t sz;
    unsigned int width, height;
    PyObject *what = NULL;
    uint8_t *data;
    unsigned long long id;
    if(!PyArg_ParseTuple(args, "K|O", &id, &what)) return NULL;
    OSWindow *os_window = os_window_for_id(id);
    if (!os_window) { PyErr_Format(PyExc_KeyError, "No OS Window with id: %llu", id); return NULL; }
    if (!what || what == Py_None) {
        glfwSetWindowIcon(os_window->handle, 0, NULL);
        Py_RETURN_NONE;
    }
    if (PyUnicode_Check(what)) {
        const char *path = PyUnicode_AsUTF8(what);
        if (png_path_to_bitmap(path, &data, &width, &height, &sz)) {
            GLFWimage img = { .pixels = data, .width = width, .height = height };
            glfwSetWindowIcon(os_window->handle, 1, &img);
            free(data);
        } else {
            PyErr_Format(PyExc_ValueError, "%s is not a valid PNG image", path);
            return NULL;
        }
        Py_RETURN_NONE;
    }
    RAII_PY_BUFFER(buf);
    if(!PyArg_ParseTuple(args, "Ky*", &id, &buf)) return NULL;
    if (png_from_data(buf.buf, buf.len, "<data>", &data, &width, &height, &sz)) {
        GLFWimage img = { .pixels = data, .width = width, .height = height };
        glfwSetWindowIcon(os_window->handle, 1, &img);
    } else {
        PyErr_Format(PyExc_ValueError, "The supplied data of %lu bytes is not a valid PNG image", (unsigned long)buf.len);
        return NULL;
    }
    Py_RETURN_NONE;
}



void*
make_os_window_context_current(OSWindow *w) {
    GLFWwindow *current_context = glfwGetCurrentContext();
    if (w->handle != current_context) {
        glfwMakeContextCurrent(w->handle);
        return current_context;
    }
    return NULL;
}

void
get_os_window_size(OSWindow *os_window, int *w, int *h, int *fw, int *fh) {
    if (w && h) glfwGetWindowSize(os_window->handle, w, h);
    if (fw && fh) glfwGetFramebufferSize(os_window->handle, fw, fh);
}

void
set_os_window_size(OSWindow *os_window, int x, int y) {
    glfwSetWindowSize(os_window->handle, x, y);
}

void
get_os_window_pos(OSWindow *os_window, int *x, int *y) {
    glfwGetWindowPos(os_window->handle, x, y);
}

void
set_os_window_pos(OSWindow *os_window, int x, int y) {
    glfwSetWindowPos(os_window->handle, x, y);
}

static void
dpi_from_scale(float xscale, float yscale, double *xdpi, double *ydpi) {
#ifdef __APPLE__
    const double factor = 72.0;
#else
    const double factor = 96.0;
#endif
    *xdpi = xscale * factor;
    *ydpi = yscale * factor;
}

static void
get_window_content_scale(GLFWwindow *w, float *xscale, float *yscale, double *xdpi, double *ydpi) {
    // if you change this function also change createSurface() in wl_window.c
    *xscale = 1; *yscale = 1;
    if (w) glfwGetWindowContentScale(w, xscale, yscale);
    else {
        GLFWmonitor *monitor = glfwGetPrimaryMonitor();
        if (monitor) glfwGetMonitorContentScale(monitor, xscale, yscale);
    }
    // check for zero, negative, NaN or excessive values of xscale/yscale
    if (*xscale <= 0.0001 || *xscale != *xscale || *xscale >= 24) *xscale = 1.0;
    if (*yscale <= 0.0001 || *yscale != *yscale || *yscale >= 24) *yscale = 1.0;
    dpi_from_scale(*xscale, *yscale, xdpi, ydpi);
}

static void
get_window_dpi(GLFWwindow *w, double *x, double *y) {
    float xscale, yscale;
    get_window_content_scale(w, &xscale, &yscale, x, y);
}

void
get_os_window_content_scale(OSWindow *os_window, double *xdpi, double *ydpi, float *xscale, float *yscale) {
    get_window_content_scale(os_window->handle, xscale, yscale, xdpi, ydpi);
}

static bool
do_toggle_fullscreen(OSWindow *w, unsigned int flags, bool restore_sizes) {
    int width, height, x, y;
    glfwGetWindowSize(w->handle, &width, &height);
    if (!global_state.is_wayland) glfwGetWindowPos(w->handle, &x, &y);
    bool was_maximized = glfwGetWindowAttrib(w->handle, GLFW_MAXIMIZED);
    if (glfwToggleFullscreen(w->handle, flags)) {
        w->before_fullscreen.is_set = true;
        w->before_fullscreen.w = width; w->before_fullscreen.h = height; w->before_fullscreen.x = x; w->before_fullscreen.y = y;
        w->before_fullscreen.was_maximized = was_maximized;
        return true;
    }
    if (w->before_fullscreen.is_set && restore_sizes) {
        glfwSetWindowSize(w->handle, w->before_fullscreen.w, w->before_fullscreen.h);
        if (!global_state.is_wayland) glfwSetWindowPos(w->handle, w->before_fullscreen.x, w->before_fullscreen.y);
        if (w->before_fullscreen.was_maximized) glfwMaximizeWindow(w->handle);
    }
    return false;
}

static bool
toggle_fullscreen_for_os_window(OSWindow *w) {
    if (!w || !w->handle) return false;
    if (!w->is_layer_shell) {
#ifdef __APPLE__
        if (!OPT(macos_traditional_fullscreen)) return do_toggle_fullscreen(w, 1, false);
#endif
        return do_toggle_fullscreen(w, 0, true);
    }
    const GLFWLayerShellConfig *prev = glfwGetLayerShellConfig(w->handle);
    if (!prev) return false;
    GLFWLayerShellConfig lsc;
    memcpy(&lsc, prev, sizeof(lsc));
    if (prev->type == GLFW_LAYER_SHELL_OVERLAY || prev->type == GLFW_LAYER_SHELL_TOP) {
        if (prev->was_toggled_to_fullscreen) {
            lsc.edge = prev->previous.edge;
            lsc.requested_bottom_margin = prev->previous.requested_bottom_margin;
            lsc.requested_top_margin = prev->previous.requested_top_margin;
            lsc.requested_left_margin = prev->requested_left_margin;
            lsc.requested_right_margin = prev->requested_right_margin;
            lsc.was_toggled_to_fullscreen = false;
            glfwSetLayerShellConfig(w->handle, &lsc);
            return true;
        }
        if (prev->edge == GLFW_EDGE_TOP || prev->edge == GLFW_EDGE_BOTTOM || prev->edge == GLFW_EDGE_LEFT || prev->edge == GLFW_EDGE_RIGHT) {
            lsc.edge = GLFW_EDGE_CENTER;
            lsc.previous.edge = prev->edge;
            lsc.previous.requested_right_margin = prev->requested_right_margin;
            lsc.previous.requested_left_margin = prev->requested_left_margin;
            lsc.previous.requested_top_margin = prev->requested_top_margin;
            lsc.previous.requested_bottom_margin = prev->requested_bottom_margin;
            lsc.requested_bottom_margin = 0; lsc.requested_top_margin = 0; lsc.requested_left_margin = 0; lsc.requested_right_margin = 0;
            lsc.was_toggled_to_fullscreen = true;
            glfwSetLayerShellConfig(w->handle, &lsc);
            return true;
        }
    }
    return false;
}

bool
is_os_window_fullscreen(OSWindow *w) {
    unsigned int flags = 0;
    if (!w || !w->handle) return false;
    if (w->is_layer_shell) {
        const GLFWLayerShellConfig *c = glfwGetLayerShellConfig(w->handle);
        return c && c->was_toggled_to_fullscreen;
    }
#ifdef __APPLE__
    if (!OPT(macos_traditional_fullscreen)) flags = 1;
#endif
    return glfwIsFullscreen(w->handle, flags);
}

static bool
toggle_maximized_for_os_window(OSWindow *w) {
    bool maximized = false;
    if (w && w->handle && !w->is_layer_shell) {
        if (glfwGetWindowAttrib(w->handle, GLFW_MAXIMIZED)) {
            glfwRestoreWindow(w->handle);
        } else {
            glfwMaximizeWindow(w->handle);
            maximized = true;
        }
    }
    return maximized;
}

static void
change_state_for_os_window(OSWindow *w, int state) {
    if (!w || !w->handle) return;
    switch (state) {
        case WINDOW_MAXIMIZED:
            if (!w->is_layer_shell) glfwMaximizeWindow(w->handle);
            break;
        case WINDOW_MINIMIZED:
            if (!w->is_layer_shell) glfwIconifyWindow(w->handle);
            break;
        case WINDOW_FULLSCREEN:
            if (!is_os_window_fullscreen(w)) toggle_fullscreen_for_os_window(w);
            break;
        case WINDOW_NORMAL:
            if (is_os_window_fullscreen(w)) toggle_fullscreen_for_os_window(w);
            else if (!w->is_layer_shell) glfwRestoreWindow(w->handle);
            break;
        case WINDOW_HIDDEN:
            glfwHideWindow(w->handle); break;
    }
}

#ifdef __APPLE__
static GLFWwindow *apple_preserve_common_context = NULL;

static int
filter_option(int key UNUSED, int mods, unsigned int native_key UNUSED, unsigned long flags) {
    mods &= ~(GLFW_MOD_NUM_LOCK | GLFW_MOD_CAPS_LOCK);
    if ((mods == GLFW_MOD_ALT) || (mods == (GLFW_MOD_ALT | GLFW_MOD_SHIFT))) {
        if (OPT(macos_option_as_alt) == 3) return 1;
        if (cocoa_alt_option_key_pressed(flags)) return 1;
    }
    return 0;
}

static bool
on_application_reopen(int has_visible_windows) {
    if (has_visible_windows) return true;
    set_cocoa_pending_action(NEW_OS_WINDOW, NULL);
    return false;
}

static bool
intercept_cocoa_fullscreen(GLFWwindow *w) {
    if (!OPT(macos_traditional_fullscreen) || !set_callback_window(w)) return false;
    toggle_fullscreen_for_os_window(global_state.callback_os_window);
    global_state.callback_os_window = NULL;
    return true;
}
#endif

static void
init_window_chrome_state(WindowChromeState *s, color_type active_window_bg, bool is_semi_transparent, float background_opacity) {
    zero_at_ptr(s);
    const bool should_blur = background_opacity < 1.f && OPT(background_blur) > 0 && is_semi_transparent;
#define SET_TCOL(val) \
        s->use_system_color = false; \
        switch (val & 0xff) { \
            case 0: s->use_system_color = true; s->color = active_window_bg; break; \
            case 1: s->color = active_window_bg; break; \
            default: s->color = val >> 8; break; \
        }

#ifdef __APPLE__
    if (OPT(macos_titlebar_color) < 0) {
        s->use_system_color = true;
        s->system_color = -OPT(macos_titlebar_color);
    } else {
        unsigned long val = OPT(macos_titlebar_color);
        SET_TCOL(val);
    }
    s->macos_colorspace = OPT(macos_colorspace);
    s->resizable = OPT(macos_window_resizable);
#else
    if (global_state.is_wayland) { SET_TCOL(OPT(wayland_titlebar_color)); }
#endif
    s->background_blur = should_blur ? OPT(background_blur) : 0;
    s->hide_window_decorations = OPT(hide_window_decorations);
    s->show_title_in_titlebar = (OPT(macos_show_window_title_in) & WINDOW) != 0;
    s->background_opacity = background_opacity;
}

static void
apply_window_chrome_state(GLFWwindow *w, WindowChromeState new_state, int width, int height, bool window_decorations_changed) {
#ifdef __APPLE__
    glfwCocoaSetWindowChrome(w,
        new_state.color, new_state.use_system_color, new_state.system_color,
        new_state.background_blur, new_state.hide_window_decorations,
        new_state.show_title_in_titlebar, new_state.macos_colorspace,
        new_state.background_opacity, new_state.resizable
    );
    // Need to resize the window again after hiding decorations or title bar to take up screen space
    if (window_decorations_changed) glfwSetWindowSize(w, width, height);
#else
        if (window_decorations_changed) {
            bool hide_window_decorations = new_state.hide_window_decorations & 1;
            glfwSetWindowAttrib(w, GLFW_DECORATED, !hide_window_decorations);
            glfwSetWindowSize(w, width, height);
        }
        glfwSetWindowBlur(w, new_state.background_blur);
        if (global_state.is_wayland) {
            if (glfwWaylandSetTitlebarColor) glfwWaylandSetTitlebarColor(w, new_state.color, new_state.use_system_color);
        }
#endif
}

void
set_os_window_chrome(OSWindow *w) {
    if (!w->handle || w->is_layer_shell) return;
    color_type bg = OPT(background);
    if (w->num_tabs > w->active_tab) {
        Tab *tab = w->tabs + w->active_tab;
        if (tab->num_windows > tab->active_window) {
            Window *window = tab->windows + tab->active_window;
            ColorProfile *c;
            if (window->render_data.screen && (c=window->render_data.screen->color_profile)) {
                bg = colorprofile_to_color(c, c->overridden.default_bg, c->configured.default_bg).rgb;
            }
        }
    }

    WindowChromeState new_state;
    init_window_chrome_state(&new_state, bg, w->is_semi_transparent, w->background_opacity);
    if (memcmp(&new_state, &w->last_window_chrome, sizeof(WindowChromeState)) != 0) {
        int width, height;
        glfwGetWindowSize(w->handle, &width, &height);
        bool window_decorations_changed = new_state.hide_window_decorations != w->last_window_chrome.hide_window_decorations;
        apply_window_chrome_state(w->handle, new_state, width, height, window_decorations_changed);
        w->last_window_chrome = new_state;
    }
}

static PyObject*
native_window_handle(GLFWwindow *w) {
#ifdef __APPLE__
    void *ans = glfwGetCocoaWindow(w);
    return PyLong_FromVoidPtr(ans);
#endif
    if (glfwGetX11Window) return PyLong_FromUnsignedLong(glfwGetX11Window(w));
    return Py_None;
}

static PyObject* edge_spacing_func = NULL;

static double
edge_spacing(GLFWEdge which) {
    const char* edge = "top";
    switch(which) {
        case GLFW_EDGE_TOP: edge = "top"; break;
        case GLFW_EDGE_BOTTOM: edge = "bottom"; break;
        case GLFW_EDGE_LEFT: edge = "left"; break;
        case GLFW_EDGE_RIGHT: edge = "right"; break;
        case GLFW_EDGE_CENTER: case GLFW_EDGE_NONE: case GLFW_EDGE_CENTER_SIZED: return 0;
    }
    if (!edge_spacing_func) {
        log_error("Attempt to call edge_spacing() without first setting edge_spacing_func");
        return 100;
    }
    RAII_PyObject(ret, PyObject_CallFunction(edge_spacing_func, "s", edge));
    if (!ret) { PyErr_Print(); return 100; }
    if (!PyFloat_Check(ret)) { log_error("edge_spacing_func() return something other than a float"); return 100; }
    return PyFloat_AsDouble(ret);
}

static void
calculate_layer_shell_window_size(
    GLFWwindow *window, float xscale, float yscale, unsigned *cell_width, unsigned *cell_height, double *left_edge_spacing, double *top_edge_spacing, double *right_edge_spacing, double *bottom_edge_spacing) {
    OSWindow *os_window = os_window_for_glfw_window(window);
    double xdpi, ydpi;
    dpi_from_scale(xscale, yscale, &xdpi, &ydpi);
    FONTS_DATA_HANDLE fonts_data = load_fonts_data(os_window ? os_window->fonts_data->font_sz_in_pts : OPT(font_size), xdpi, ydpi);
    *cell_width = fonts_data->fcm.cell_width; *cell_height = fonts_data->fcm.cell_height;
    double x_factor = xdpi / 72., y_factor = ydpi / 72.;
    *left_edge_spacing = edge_spacing(GLFW_EDGE_LEFT) * x_factor;
    *top_edge_spacing = edge_spacing(GLFW_EDGE_TOP) * y_factor;
    *right_edge_spacing = edge_spacing(GLFW_EDGE_RIGHT) * x_factor;
    *bottom_edge_spacing = edge_spacing(GLFW_EDGE_BOTTOM) * y_factor;
}

static PyObject*
layer_shell_config_to_python(const GLFWLayerShellConfig *c) {
    RAII_PyObject(ans, PyDict_New()); if (!ans) return ans;
#define fl(x) PyLong_FromLong((long)x)
#define fu(x) PyLong_FromUnsignedLong((unsigned long)x)
#define b(x) Py_NewRef(x ? Py_True : Py_False)
#define A(attr, convert) RAII_PyObject(attr, convert(c->attr)); if (!attr) return NULL; if (PyDict_SetItemString(ans, #attr, attr) != 0) return NULL;
    A(type, fl);
    A(output_name, PyUnicode_FromString);
    A(edge, fl);
    A(focus_policy, fl);
    A(x_size_in_cells, fu);
    A(y_size_in_cells, fu);
    A(x_size_in_pixels, fu);
    A(y_size_in_pixels, fu);
    A(requested_top_margin, fl);
    A(requested_left_margin, fl);
    A(requested_bottom_margin, fl);
    A(requested_right_margin, fl);
    A(requested_exclusive_zone, fl);
    A(hide_on_focus_loss, b)
    A(override_exclusive_zone, b);
#undef A
#undef fl
#undef fu
#undef b
    return Py_NewRef(ans);
}

static bool
layer_shell_config_from_python(PyObject *p, GLFWLayerShellConfig *ans) {
    memset(ans, 0, sizeof(GLFWLayerShellConfig));
    ans->size_callback = calculate_layer_shell_window_size;
#define A(attr, type_check, convert) RAII_PyObject(attr, PyObject_GetAttrString(p, #attr)); if (attr == NULL) return false; if (!type_check(attr)) { PyErr_SetString(PyExc_TypeError, #attr " not of the correct type"); return false; }; ans->attr = convert(attr);
    A(type, PyLong_Check, PyLong_AsLong);
    A(edge, PyLong_Check, PyLong_AsLong);
    A(focus_policy, PyLong_Check, PyLong_AsLong);
    A(x_size_in_cells, PyLong_Check, PyLong_AsUnsignedLong);
    A(y_size_in_cells, PyLong_Check, PyLong_AsUnsignedLong);
    A(x_size_in_pixels, PyLong_Check, PyLong_AsUnsignedLong);
    A(y_size_in_pixels, PyLong_Check, PyLong_AsUnsignedLong);
    A(requested_top_margin, PyLong_Check, PyLong_AsLong);
    A(requested_left_margin, PyLong_Check, PyLong_AsLong);
    A(requested_bottom_margin, PyLong_Check, PyLong_AsLong);
    A(requested_right_margin, PyLong_Check, PyLong_AsLong);
    A(requested_exclusive_zone, PyLong_Check, PyLong_AsLong);
    A(override_exclusive_zone, PyBool_Check, PyLong_AsLong);
    A(hide_on_focus_loss, PyBool_Check, PyLong_AsLong);
#undef A
#define A(attr) { \
    RAII_PyObject(attr, PyObject_GetAttrString(p, #attr)); if (attr == NULL) return false; \
    if (!PyUnicode_Check(attr)) { PyErr_SetString(PyExc_TypeError, #attr " not a string"); return false; };\
    Py_ssize_t sz; const char *t = PyUnicode_AsUTF8AndSize(attr, &sz); \
    if (sz > (ssize_t)sizeof(ans->attr)-1) { PyErr_Format(PyExc_ValueError, "%s: %s is too long", #attr, t); return false; } \
    memcpy(ans->attr, t, sz); }

    A(output_name);
    return true;
#undef A
}

static void
os_window_update_size_increments(OSWindow *window) {
    if (OPT(resize_in_steps)) {
        if (window->handle && window->fonts_data) glfwSetWindowSizeIncrements(
                window->handle, window->fonts_data->fcm.cell_width, window->fonts_data->fcm.cell_height);
    } else {
        if (window->handle) glfwSetWindowSizeIncrements(
                window->handle, GLFW_DONT_CARE, GLFW_DONT_CARE);
    }
}


static PyObject*
create_os_window(PyObject UNUSED *self, PyObject *args, PyObject *kw) {
    int x = INT_MIN, y = INT_MIN, window_state = WINDOW_NORMAL, disallow_override_title = 0;
    char *title, *wm_class_class, *wm_class_name;
    PyObject *optional_window_state = NULL, *load_programs = NULL, *get_window_size, *pre_show_callback, *optional_x = NULL, *optional_y = NULL, *layer_shell_config = NULL;
    static const char* kwlist[] = {"get_window_size", "pre_show_callback", "title", "wm_class_name", "wm_class_class", "window_state", "load_programs", "x", "y", "disallow_override_title", "layer_shell_config", NULL};
    if (!PyArg_ParseTupleAndKeywords(args, kw, "OOsss|OOOOpO", (char**)kwlist,
        &get_window_size, &pre_show_callback, &title, &wm_class_name, &wm_class_class, &optional_window_state, &load_programs, &optional_x, &optional_y, &disallow_override_title, &layer_shell_config)) return NULL;
    GLFWLayerShellConfig *lsc = NULL, lsc_stack = {0};
    if (optional_window_state && optional_window_state != Py_None) {
        if (!PyLong_Check(optional_window_state)) { PyErr_SetString(PyExc_TypeError, "window_state must be an int"); return NULL; }
        window_state = (int) PyLong_AsLong(optional_window_state);
    }
    if (layer_shell_config && layer_shell_config != Py_None ) {
        if (!glfwIsLayerShellSupported()) {
            PyErr_SetString(PyExc_RuntimeError, "The window manager/compositor does not support the primitives needed to make panels.");
            return NULL;
        }
        lsc = &lsc_stack;
    } else {
        if (optional_x && optional_x != Py_None) { if (!PyLong_Check(optional_x)) { PyErr_SetString(PyExc_TypeError, "x must be an int"); return NULL;} x = (int)PyLong_AsLong(optional_x); }
        if (optional_y && optional_y != Py_None) { if (!PyLong_Check(optional_y)) { PyErr_SetString(PyExc_TypeError, "y must be an int"); return NULL;} y = (int)PyLong_AsLong(optional_y); }
        if (window_state < WINDOW_NORMAL || window_state > WINDOW_HIDDEN) window_state = WINDOW_NORMAL;
    }
    if (PyErr_Occurred()) return NULL;
    if (lsc && window_state != WINDOW_HIDDEN) window_state = WINDOW_NORMAL;

    static bool is_first_window = true;
    if (is_first_window) {
        glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, OPENGL_REQUIRED_VERSION_MAJOR);
        glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, OPENGL_REQUIRED_VERSION_MINOR);
        glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, true);
        // We don't use depth and stencil buffers
        glfwWindowHint(GLFW_DEPTH_BITS, 0);
        glfwWindowHint(GLFW_STENCIL_BITS, 0);
        glfwSetApplicationCloseCallback(application_close_requested_callback);
        glfwSetCurrentSelectionCallback(get_current_selection);
        glfwSetHasCurrentSelectionCallback(has_current_selection);
        glfwSetIMECursorPositionCallback(get_ime_cursor_position);
        glfwSetSystemColorThemeChangeCallback(on_system_color_scheme_change);
        glfwSetClipboardLostCallback(on_clipboard_lost);
        // Request SRGB output buffer
        // Prevents kitty from starting on Wayland + NVIDIA, sigh: https://github.com/kovidgoyal/kitty/issues/7021
        // Remove after https://github.com/NVIDIA/egl-wayland/issues/85 is fixed.
        // Also apparently mesa has introduced a bug with sRGB surfaces and Wayland.
        // Sigh. Wayland is such a pile of steaming crap.
        // See https://github.com/kovidgoyal/kitty/issues/7174#issuecomment-2000033873
        if (!global_state.is_wayland) glfwWindowHint(GLFW_SRGB_CAPABLE, true);
#ifdef __APPLE__
        cocoa_set_activation_policy(OPT(macos_hide_from_tasks) || lsc != NULL);
        glfwWindowHint(GLFW_COCOA_GRAPHICS_SWITCHING, true);
        glfwSetApplicationShouldHandleReopen(on_application_reopen);
        glfwSetApplicationWillFinishLaunching(cocoa_application_lifecycle_event);
#endif
    }
    if (OPT(hide_window_decorations) & 1) glfwWindowHint(GLFW_DECORATED, false);

    const bool set_blur = OPT(background_blur) > 0 && OPT(background_opacity) < 1.f;
    glfwWindowHint(GLFW_BLUR_RADIUS, set_blur ? OPT(background_blur) : 0);
#ifdef __APPLE__
    glfwWindowHint(GLFW_COCOA_COLOR_SPACE, OPT(macos_colorspace));
#else
    glfwWindowHintString(GLFW_X11_INSTANCE_NAME, wm_class_name);
    glfwWindowHintString(GLFW_X11_CLASS_NAME, wm_class_class);
    glfwWindowHintString(GLFW_WAYLAND_APP_ID, wm_class_class);
#endif

    if (global_state.num_os_windows >= MAX_CHILDREN) {
        PyErr_SetString(PyExc_ValueError, "Too many windows");
        return NULL;
    }
    bool want_semi_transparent = (1.0 - OPT(background_opacity) >= 0.01) || OPT(dynamic_background_opacity);
    glfwWindowHint(GLFW_TRANSPARENT_FRAMEBUFFER, want_semi_transparent);
    uint32_t bgcolor = OPT(background);
    uint32_t bgalpha = (uint32_t)((MAX(0.f, MIN((OPT(background_opacity) * 255), 255.f))));
    glfwWindowHint(GLFW_WAYLAND_BGCOLOR, ((bgalpha & 0xff) << 24) | bgcolor);
    // We use a temp window to avoid the need to set the window size after
    // creation, which causes a resize event and all the associated processing.
    // The temp window is used to get the DPI. On Wayland no temp window can be
    // used, so start with window visible unless hidden window requested.
    glfwWindowHint(GLFW_VISIBLE, window_state != WINDOW_HIDDEN && global_state.is_wayland);
    GLFWwindow *common_context = global_state.num_os_windows ? global_state.os_windows[0].handle : NULL;
    GLFWwindow *temp_window = NULL;
#ifdef __APPLE__
    if (!apple_preserve_common_context) {
        apple_preserve_common_context = glfwCreateWindow(640, 480, "kitty", NULL, common_context, NULL);
    }
    if (!common_context) common_context = apple_preserve_common_context;
#endif
    float xscale, yscale;
    double xdpi, ydpi;
    if (global_state.is_wayland) {
        // Cannot use temp window on Wayland as scale is only sent by compositor after window is displayed
        get_window_content_scale(NULL, &xscale, &yscale, &xdpi, &ydpi);
        for (unsigned i = 0; i < global_state.num_os_windows; i++) {
            OSWindow *osw = global_state.os_windows + i;
            if (osw->handle && glfwGetWindowAttrib(osw->handle, GLFW_FOCUSED)) {
                get_window_content_scale(osw->handle, &xscale, &yscale, &xdpi, &ydpi);
                break;
            }
        }
    } else {
#define glfw_failure { \
        PyErr_Format(PyExc_OSError, "Failed to create GLFWwindow. This usually happens because of old/broken OpenGL drivers. kitty requires working OpenGL %d.%d drivers.", OPENGL_REQUIRED_VERSION_MAJOR, OPENGL_REQUIRED_VERSION_MINOR); \
        return NULL; }

        temp_window = glfwCreateWindow(640, 480, "temp", NULL, common_context, NULL);
        if (temp_window == NULL) glfw_failure;
        get_window_content_scale(temp_window, &xscale, &yscale, &xdpi, &ydpi);
    }
    FONTS_DATA_HANDLE fonts_data = load_fonts_data(OPT(font_size), xdpi, ydpi);
    PyObject *ret = PyObject_CallFunction(get_window_size, "IIddff", fonts_data->fcm.cell_width, fonts_data->fcm.cell_height, fonts_data->logical_dpi_x, fonts_data->logical_dpi_y, xscale, yscale);
    if (ret == NULL) return NULL;
    int width = PyLong_AsLong(PyTuple_GET_ITEM(ret, 0)), height = PyLong_AsLong(PyTuple_GET_ITEM(ret, 1));
    Py_CLEAR(ret);
    if (lsc) {
        if (!layer_shell_config_from_python(layer_shell_config, lsc)) return NULL;
        lsc->expected.xscale = xscale; lsc->expected.yscale = yscale;
    }
    GLFWwindow *glfw_window = glfwCreateWindow(width, height, title, NULL, temp_window ? temp_window : common_context, lsc);
    if (temp_window) { glfwDestroyWindow(temp_window); temp_window = NULL; }
    if (glfw_window == NULL) glfw_failure;
#undef glfw_failure
    glfwMakeContextCurrent(glfw_window);
    if (is_first_window) gl_init();
    // Will make the GPU automatically apply SRGB gamma curve on the resulting framebuffer
    glEnable(GL_FRAMEBUFFER_SRGB);
    bool is_semi_transparent = glfwGetWindowAttrib(glfw_window, GLFW_TRANSPARENT_FRAMEBUFFER);
    // blank the window once so that there is no initial flash of color
    // changing, in case the background color is not black
    blank_canvas(is_semi_transparent ? OPT(background_opacity) : 1.0f, OPT(background));
    apply_swap_interval(-1);
    // On Wayland the initial swap is allowed only after the first XDG configure event
    if (glfwAreSwapsAllowed(glfw_window)) glfwSwapBuffers(glfw_window);
    glfwSetInputMode(glfw_window, GLFW_LOCK_KEY_MODS, true);
    PyObject *pret = PyObject_CallFunction(pre_show_callback, "N", native_window_handle(glfw_window));
    if (pret == NULL) return NULL;
    Py_DECREF(pret);
    if (x != INT_MIN && y != INT_MIN) glfwSetWindowPos(glfw_window, x, y);
    if (!global_state.is_apple && !global_state.is_wayland && window_state != WINDOW_HIDDEN) glfwShowWindow(glfw_window);
    if (global_state.is_wayland || global_state.is_apple) {
        float n_xscale, n_yscale;
        double n_xdpi, n_ydpi;
        get_window_content_scale(glfw_window, &n_xscale, &n_yscale, &n_xdpi, &n_ydpi);
        if (n_xdpi != xdpi || n_ydpi != ydpi || lsc) {
            // this can happen if the window is moved by the OS to a different monitor when shown or with fractional scales on Wayland
            // it can also happen with layer shell windows if the callback is
            // called before the window is fully created
            xdpi = n_xdpi; ydpi = n_ydpi;
            fonts_data = load_fonts_data(OPT(font_size), xdpi, ydpi);
        }
    }
    if (is_first_window) {
        PyObject *ret = PyObject_CallFunction(load_programs, "O", is_semi_transparent ? Py_True : Py_False);
        if (ret == NULL) return NULL;
        Py_DECREF(ret);
        get_platform_dependent_config_values(glfw_window);
        GLint encoding;
        glGetFramebufferAttachmentParameteriv(GL_FRAMEBUFFER, GL_BACK_LEFT, GL_FRAMEBUFFER_ATTACHMENT_COLOR_ENCODING, &encoding);
        if (encoding != GL_SRGB) log_error("The output buffer does not support sRGB color encoding, colors will be incorrect.");
        is_first_window = false;

    }
    OSWindow *w = add_os_window();
    w->handle = glfw_window;
    w->disallow_title_changes = disallow_override_title;
    if (lsc != NULL) {
        w->is_layer_shell = true;
        w->hide_on_focus_loss = lsc->hide_on_focus_loss;
    }
    update_os_window_references();
    if (!w->is_layer_shell || (global_state.is_apple && w->is_layer_shell && lsc->focus_policy == GLFW_FOCUS_EXCLUSIVE)) {
        for (size_t i = 0; i < global_state.num_os_windows; i++) {
            // On some platforms (macOS) newly created windows don't get the initial focus in event
            OSWindow *q = global_state.os_windows + i;
            q->is_focused = q == w ? true : false;
        }
    }
    w->fonts_data = fonts_data;
    w->shown_once = true;
    w->last_focused_counter = ++focus_counter;
    os_window_update_size_increments(w);
#ifdef __APPLE__
    if (OPT(macos_option_as_alt)) glfwSetCocoaTextInputFilter(glfw_window, filter_option);
    glfwSetCocoaToggleFullscreenIntercept(glfw_window, intercept_cocoa_fullscreen);
    glfwCocoaSetWindowResizeCallback(glfw_window, cocoa_os_window_resized);
#endif
    send_prerendered_sprites_for_window(w);
    if (logo.pixels && logo.width && logo.height) glfwSetWindowIcon(glfw_window, 1, &logo);
    set_glfw_mouse_pointer_shape_in_window(glfw_window, OPT(default_pointer_shape));
    update_os_window_viewport(w, false);
    glfwSetWindowPosCallback(glfw_window, window_pos_callback);
    // missing size callback
    glfwSetWindowCloseCallback(glfw_window, window_close_callback);
    glfwSetWindowRefreshCallback(glfw_window, refresh_callback);
    glfwSetWindowFocusCallback(glfw_window, window_focus_callback);
    glfwSetWindowOcclusionCallback(glfw_window, window_occlusion_callback);
    glfwSetWindowIconifyCallback(glfw_window, window_iconify_callback);
    // missing maximize/restore callback
    glfwSetFramebufferSizeCallback(glfw_window, framebuffer_size_callback);
    glfwSetLiveResizeCallback(glfw_window, live_resize_callback);
    glfwSetWindowContentScaleCallback(glfw_window, dpi_change_callback);
    glfwSetMouseButtonCallback(glfw_window, mouse_button_callback);
    glfwSetCursorPosCallback(glfw_window, cursor_pos_callback);
    glfwSetCursorEnterCallback(glfw_window, cursor_enter_callback);
    glfwSetScrollCallback(glfw_window, scroll_callback);
    glfwSetKeyboardCallback(glfw_window, key_callback);
    glfwSetDropCallback(glfw_window, drop_callback);
    monotonic_t now = monotonic();
    w->is_focused = true;
    w->cursor_blink_zero_time = now;
    w->last_mouse_activity_at = now;
    w->mouse_activate_deadline = -1;
    w->mouse_show_threshold = 0;
    w->is_semi_transparent = is_semi_transparent;
    if (want_semi_transparent && !w->is_semi_transparent) {
        static bool warned = false;
        if (!warned) {
            log_error("Failed to enable transparency. This happens when your desktop environment does not support compositing.");
            warned = true;
        }
    }
    init_window_chrome_state(&w->last_window_chrome, OPT(background), w->is_semi_transparent, w->background_opacity);
    if (w->is_layer_shell) {
        if (global_state.is_apple) set_layer_shell_config_for(w, lsc);
    } else apply_window_chrome_state(
            w->handle, w->last_window_chrome, width, height, global_state.is_apple ? OPT(hide_window_decorations) != 0 : false);
    // Update window state
    // We do not call glfwWindowHint to set GLFW_MAXIMIZED before the window is created.
    // That would cause the window to be set to maximize immediately after creation and use the wrong initial size when restored.
    if (window_state != WINDOW_NORMAL) change_state_for_os_window(w, window_state);
#ifdef __APPLE__
    // macOS: Show the window after it is ready
    if (window_state != WINDOW_HIDDEN) glfwShowWindow(glfw_window);
#endif
    w->redraw_count = 1;
    debug("OS Window created\n");
    return PyLong_FromUnsignedLongLong(w->id);
}

void
on_os_window_font_size_change(OSWindow *os_window, double new_sz) {
    double xdpi, ydpi; float xscale, yscale;
    get_os_window_content_scale(os_window, &xdpi, &ydpi, &xscale, &yscale);
    os_window->fonts_data = load_fonts_data(new_sz, xdpi, ydpi);
    os_window_update_size_increments(os_window);
    if (os_window->is_layer_shell) set_layer_shell_config_for(os_window, NULL);
}

#ifdef __APPLE__
static bool
window_in_same_cocoa_workspace(void *w, size_t *source_workspaces, size_t source_workspace_count) {
    static size_t workspaces[64];
    size_t workspace_count = cocoa_get_workspace_ids(w, workspaces, arraysz(workspaces));
    for (size_t i = 0; i < workspace_count; i++) {
        for (size_t s = 0; s < source_workspace_count; s++) {
            if (source_workspaces[s] == workspaces[i]) return true;
        }
    }
    return false;
}

static void
cocoa_focus_last_window(id_type source_window_id, size_t *source_workspaces, size_t source_workspace_count) {
    id_type highest_focus_number = 0;
    OSWindow *window_to_focus = NULL;
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = global_state.os_windows + i;
        if (
                w->id != source_window_id && w->handle && w->shown_once &&
                w->last_focused_counter >= highest_focus_number &&
                (!source_workspace_count || window_in_same_cocoa_workspace(glfwGetCocoaWindow(w->handle), source_workspaces, source_workspace_count))
        ) {
            highest_focus_number = w->last_focused_counter;
            window_to_focus = w;
        }
    }
    if (window_to_focus) {
        glfwFocusWindow(window_to_focus->handle);
    }
}
#endif

void
destroy_os_window(OSWindow *w) {
#ifdef __APPLE__
    static size_t source_workspaces[64];
    size_t source_workspace_count = 0;
#endif
    if (w->handle) {
#ifdef __APPLE__
        source_workspace_count = cocoa_get_workspace_ids(glfwGetCocoaWindow(w->handle), source_workspaces, arraysz(source_workspaces));
#endif
        // Ensure mouse cursor is visible and reset to default shape, needed on macOS
        show_mouse_cursor(w->handle);
        glfwSetCursor(w->handle, NULL);
        glfwDestroyWindow(w->handle);
    }
    w->handle = NULL;
#ifdef __APPLE__
    // On macOS when closing a window, any other existing windows belonging to the same application do not
    // automatically get focus, so we do it manually.
    cocoa_focus_last_window(w->id, source_workspaces, source_workspace_count);
#endif
}

void
focus_os_window(OSWindow *w, bool also_raise, const char *activation_token) {
    if (w->handle) {
#ifdef __APPLE__
        if (!also_raise) cocoa_focus_window(glfwGetCocoaWindow(w->handle));
        else glfwFocusWindow(w->handle);
        (void)activation_token;
#else
        if (global_state.is_wayland && activation_token && activation_token[0] && also_raise) {
            glfwWaylandActivateWindow(w->handle, activation_token);
            return;
        }
        glfwFocusWindow(w->handle);
#endif
    }
}

// Global functions {{{
static void
error_callback(int error, const char* description) {
    log_error("[glfw error %d]: %s", error, description);
}


#ifndef __APPLE__
static PyObject *dbus_notification_callback = NULL;

static PyObject*
dbus_set_notification_callback(PyObject *self UNUSED, PyObject *callback) {
    Py_CLEAR(dbus_notification_callback);
    if (callback && callback != Py_None) {
        dbus_notification_callback = callback; Py_INCREF(callback);
        GLFWDBUSNotificationData d = {.timeout=-99999, .urgency=255};
        if (!glfwDBusUserNotify) {
            PyErr_SetString(PyExc_RuntimeError, "Failed to load glfwDBusUserNotify, did you call glfw_init?");
            return NULL;
        }
        glfwDBusUserNotify(&d, NULL, NULL);
    }
    Py_RETURN_NONE;
}

#define send_dbus_notification_event_to_python(event_type, a, b) { \
    if (dbus_notification_callback) { \
        const char call_args_fmt[] = {'s', \
            _Generic((a), unsigned long : 'k', unsigned long long : 'K'), _Generic((b), unsigned long : 'k', const char* : 's') }; \
        RAII_PyObject(ret, PyObject_CallFunction(dbus_notification_callback, call_args_fmt, event_type, a, b)); \
        if (!ret) PyErr_Print(); \
    } \
}


static void
dbus_user_notification_activated(uint32_t notification_id, int type, const char* action) {
    unsigned long nid = notification_id;
    const char *stype = "activated";
    switch (type) {
        case 0: stype = "closed"; break;
        case 1: stype = "activation_token"; break;
        case -1: stype = "capabilities"; break;
    }
    send_dbus_notification_event_to_python(stype, nid, action);
}
#endif

static PyObject*
opengl_version_string(PyObject *self UNUSED, PyObject *args UNUSED) {
    return PyUnicode_FromString(global_state.gl_version ? gl_version_string() : "");
}

static PyObject*
glfw_init(PyObject UNUSED *self, PyObject *args) {
    const char* path;
    int debug_keyboard = 0, debug_rendering = 0, wayland_enable_ime = 0;
    PyObject *edge_sf;
    if (!PyArg_ParseTuple(args, "sO|ppp", &path, &edge_sf, &debug_keyboard, &debug_rendering, &wayland_enable_ime)) return NULL;
    if (!PyCallable_Check(edge_sf)) { PyErr_SetString(PyExc_TypeError, "edge_spacing_func must be a callable"); return NULL; }
    Py_CLEAR(edge_spacing_func);
#ifdef __APPLE__
    cocoa_set_uncaught_exception_handler();
#endif
    const char* err = load_glfw(path);
    if (err) { PyErr_SetString(PyExc_RuntimeError, err); return NULL; }
    glfwSetErrorCallback(error_callback);
    glfwInitHint(GLFW_DEBUG_KEYBOARD, debug_keyboard);
    glfwInitHint(GLFW_DEBUG_RENDERING, debug_rendering);
    OPT(debug_keyboard) = debug_keyboard != 0;
    glfwInitHint(GLFW_WAYLAND_IME, wayland_enable_ime != 0);
#ifdef __APPLE__
    glfwInitHint(GLFW_COCOA_CHDIR_RESOURCES, 0);
    glfwInitHint(GLFW_COCOA_MENUBAR, 0);
#else
    if (glfwDBusSetUserNotificationHandler) {
        glfwDBusSetUserNotificationHandler(dbus_user_notification_activated);
    }
#endif
    bool supports_window_occlusion = false;
    bool ok = glfwInit(monotonic_start_time, &supports_window_occlusion);
    if (ok) {
#ifdef __APPLE__
        glfwSetCocoaURLOpenCallback(apple_url_open_callback);
#else
        glfwSetDrawTextFunction(draw_text_callback);
#endif
        get_window_dpi(NULL, &global_state.default_dpi.x, &global_state.default_dpi.y);
        edge_spacing_func = edge_sf; Py_INCREF(edge_spacing_func);
    }
    return Py_BuildValue("OO", ok ? Py_True : Py_False, supports_window_occlusion ? Py_True : Py_False);
}

static PyObject*
glfw_terminate(PYNOARG) {
    for (size_t i = 0; i < arraysz(cursors); i++) {
        if (cursors[i].is_custom && cursors[i].glfw) {
            glfwDestroyCursor(cursors[i].glfw);
            cursors[i] = (mouse_cursor){0};
        }
    }
    glfwTerminate();
    Py_CLEAR(edge_spacing_func);
    Py_RETURN_NONE;
}

static PyObject*
get_physical_dpi(GLFWmonitor *m) {
    int width = 0, height = 0;
    glfwGetMonitorPhysicalSize(m, &width, &height);
    if (width == 0 || height == 0) { PyErr_SetString(PyExc_ValueError, "Failed to get primary monitor size"); return NULL; }
    const GLFWvidmode *vm = glfwGetVideoMode(m);
    if (vm == NULL) { PyErr_SetString(PyExc_ValueError, "Failed to get video mode for monitor"); return NULL; }
    float dpix = (float)(vm->width / (width / 25.4));
    float dpiy = (float)(vm->height / (height / 25.4));
    return Py_BuildValue("ff", dpix, dpiy);
}

static PyObject*
glfw_get_physical_dpi(PYNOARG) {
    GLFWmonitor *m = glfwGetPrimaryMonitor();
    if (m == NULL) { PyErr_SetString(PyExc_ValueError, "Failed to get primary monitor"); return NULL; }
    return get_physical_dpi(m);
}

static PyObject*
glfw_get_system_color_theme(PyObject UNUSED *self, PyObject *args) {
    int query_if_unintialized = 1;
    if (!PyArg_ParseTuple(args, "|p", &query_if_unintialized)) return NULL;
    if (!glfwGetCurrentSystemColorTheme) {
        PyErr_SetString(PyExc_RuntimeError, "must initialize GFLW before calling this function"); return NULL;
    }
    const char *which = appearance_name(glfwGetCurrentSystemColorTheme(query_if_unintialized));
    return PyUnicode_FromString(which);
}

static PyObject*
glfw_get_key_name(PyObject UNUSED *self, PyObject *args) {
    int key, native_key;
    if (!PyArg_ParseTuple(args, "ii", &key, &native_key)) return NULL;
    if (key) {
        switch (key) {
            /* start glfw functional key names (auto generated by gen-key-constants.py do not edit) */
            case GLFW_FKEY_ESCAPE: return PyUnicode_FromString("escape");
            case GLFW_FKEY_ENTER: return PyUnicode_FromString("enter");
            case GLFW_FKEY_TAB: return PyUnicode_FromString("tab");
            case GLFW_FKEY_BACKSPACE: return PyUnicode_FromString("backspace");
            case GLFW_FKEY_INSERT: return PyUnicode_FromString("insert");
            case GLFW_FKEY_DELETE: return PyUnicode_FromString("delete");
            case GLFW_FKEY_LEFT: return PyUnicode_FromString("left");
            case GLFW_FKEY_RIGHT: return PyUnicode_FromString("right");
            case GLFW_FKEY_UP: return PyUnicode_FromString("up");
            case GLFW_FKEY_DOWN: return PyUnicode_FromString("down");
            case GLFW_FKEY_PAGE_UP: return PyUnicode_FromString("page_up");
            case GLFW_FKEY_PAGE_DOWN: return PyUnicode_FromString("page_down");
            case GLFW_FKEY_HOME: return PyUnicode_FromString("home");
            case GLFW_FKEY_END: return PyUnicode_FromString("end");
            case GLFW_FKEY_CAPS_LOCK: return PyUnicode_FromString("caps_lock");
            case GLFW_FKEY_SCROLL_LOCK: return PyUnicode_FromString("scroll_lock");
            case GLFW_FKEY_NUM_LOCK: return PyUnicode_FromString("num_lock");
            case GLFW_FKEY_PRINT_SCREEN: return PyUnicode_FromString("print_screen");
            case GLFW_FKEY_PAUSE: return PyUnicode_FromString("pause");
            case GLFW_FKEY_MENU: return PyUnicode_FromString("menu");
            case GLFW_FKEY_F1: return PyUnicode_FromString("f1");
            case GLFW_FKEY_F2: return PyUnicode_FromString("f2");
            case GLFW_FKEY_F3: return PyUnicode_FromString("f3");
            case GLFW_FKEY_F4: return PyUnicode_FromString("f4");
            case GLFW_FKEY_F5: return PyUnicode_FromString("f5");
            case GLFW_FKEY_F6: return PyUnicode_FromString("f6");
            case GLFW_FKEY_F7: return PyUnicode_FromString("f7");
            case GLFW_FKEY_F8: return PyUnicode_FromString("f8");
            case GLFW_FKEY_F9: return PyUnicode_FromString("f9");
            case GLFW_FKEY_F10: return PyUnicode_FromString("f10");
            case GLFW_FKEY_F11: return PyUnicode_FromString("f11");
            case GLFW_FKEY_F12: return PyUnicode_FromString("f12");
            case GLFW_FKEY_F13: return PyUnicode_FromString("f13");
            case GLFW_FKEY_F14: return PyUnicode_FromString("f14");
            case GLFW_FKEY_F15: return PyUnicode_FromString("f15");
            case GLFW_FKEY_F16: return PyUnicode_FromString("f16");
            case GLFW_FKEY_F17: return PyUnicode_FromString("f17");
            case GLFW_FKEY_F18: return PyUnicode_FromString("f18");
            case GLFW_FKEY_F19: return PyUnicode_FromString("f19");
            case GLFW_FKEY_F20: return PyUnicode_FromString("f20");
            case GLFW_FKEY_F21: return PyUnicode_FromString("f21");
            case GLFW_FKEY_F22: return PyUnicode_FromString("f22");
            case GLFW_FKEY_F23: return PyUnicode_FromString("f23");
            case GLFW_FKEY_F24: return PyUnicode_FromString("f24");
            case GLFW_FKEY_F25: return PyUnicode_FromString("f25");
            case GLFW_FKEY_F26: return PyUnicode_FromString("f26");
            case GLFW_FKEY_F27: return PyUnicode_FromString("f27");
            case GLFW_FKEY_F28: return PyUnicode_FromString("f28");
            case GLFW_FKEY_F29: return PyUnicode_FromString("f29");
            case GLFW_FKEY_F30: return PyUnicode_FromString("f30");
            case GLFW_FKEY_F31: return PyUnicode_FromString("f31");
            case GLFW_FKEY_F32: return PyUnicode_FromString("f32");
            case GLFW_FKEY_F33: return PyUnicode_FromString("f33");
            case GLFW_FKEY_F34: return PyUnicode_FromString("f34");
            case GLFW_FKEY_F35: return PyUnicode_FromString("f35");
            case GLFW_FKEY_KP_0: return PyUnicode_FromString("kp_0");
            case GLFW_FKEY_KP_1: return PyUnicode_FromString("kp_1");
            case GLFW_FKEY_KP_2: return PyUnicode_FromString("kp_2");
            case GLFW_FKEY_KP_3: return PyUnicode_FromString("kp_3");
            case GLFW_FKEY_KP_4: return PyUnicode_FromString("kp_4");
            case GLFW_FKEY_KP_5: return PyUnicode_FromString("kp_5");
            case GLFW_FKEY_KP_6: return PyUnicode_FromString("kp_6");
            case GLFW_FKEY_KP_7: return PyUnicode_FromString("kp_7");
            case GLFW_FKEY_KP_8: return PyUnicode_FromString("kp_8");
            case GLFW_FKEY_KP_9: return PyUnicode_FromString("kp_9");
            case GLFW_FKEY_KP_DECIMAL: return PyUnicode_FromString("kp_decimal");
            case GLFW_FKEY_KP_DIVIDE: return PyUnicode_FromString("kp_divide");
            case GLFW_FKEY_KP_MULTIPLY: return PyUnicode_FromString("kp_multiply");
            case GLFW_FKEY_KP_SUBTRACT: return PyUnicode_FromString("kp_subtract");
            case GLFW_FKEY_KP_ADD: return PyUnicode_FromString("kp_add");
            case GLFW_FKEY_KP_ENTER: return PyUnicode_FromString("kp_enter");
            case GLFW_FKEY_KP_EQUAL: return PyUnicode_FromString("kp_equal");
            case GLFW_FKEY_KP_SEPARATOR: return PyUnicode_FromString("kp_separator");
            case GLFW_FKEY_KP_LEFT: return PyUnicode_FromString("kp_left");
            case GLFW_FKEY_KP_RIGHT: return PyUnicode_FromString("kp_right");
            case GLFW_FKEY_KP_UP: return PyUnicode_FromString("kp_up");
            case GLFW_FKEY_KP_DOWN: return PyUnicode_FromString("kp_down");
            case GLFW_FKEY_KP_PAGE_UP: return PyUnicode_FromString("kp_page_up");
            case GLFW_FKEY_KP_PAGE_DOWN: return PyUnicode_FromString("kp_page_down");
            case GLFW_FKEY_KP_HOME: return PyUnicode_FromString("kp_home");
            case GLFW_FKEY_KP_END: return PyUnicode_FromString("kp_end");
            case GLFW_FKEY_KP_INSERT: return PyUnicode_FromString("kp_insert");
            case GLFW_FKEY_KP_DELETE: return PyUnicode_FromString("kp_delete");
            case GLFW_FKEY_KP_BEGIN: return PyUnicode_FromString("kp_begin");
            case GLFW_FKEY_MEDIA_PLAY: return PyUnicode_FromString("media_play");
            case GLFW_FKEY_MEDIA_PAUSE: return PyUnicode_FromString("media_pause");
            case GLFW_FKEY_MEDIA_PLAY_PAUSE: return PyUnicode_FromString("media_play_pause");
            case GLFW_FKEY_MEDIA_REVERSE: return PyUnicode_FromString("media_reverse");
            case GLFW_FKEY_MEDIA_STOP: return PyUnicode_FromString("media_stop");
            case GLFW_FKEY_MEDIA_FAST_FORWARD: return PyUnicode_FromString("media_fast_forward");
            case GLFW_FKEY_MEDIA_REWIND: return PyUnicode_FromString("media_rewind");
            case GLFW_FKEY_MEDIA_TRACK_NEXT: return PyUnicode_FromString("media_track_next");
            case GLFW_FKEY_MEDIA_TRACK_PREVIOUS: return PyUnicode_FromString("media_track_previous");
            case GLFW_FKEY_MEDIA_RECORD: return PyUnicode_FromString("media_record");
            case GLFW_FKEY_LOWER_VOLUME: return PyUnicode_FromString("lower_volume");
            case GLFW_FKEY_RAISE_VOLUME: return PyUnicode_FromString("raise_volume");
            case GLFW_FKEY_MUTE_VOLUME: return PyUnicode_FromString("mute_volume");
            case GLFW_FKEY_LEFT_SHIFT: return PyUnicode_FromString("left_shift");
            case GLFW_FKEY_LEFT_CONTROL: return PyUnicode_FromString("left_control");
            case GLFW_FKEY_LEFT_ALT: return PyUnicode_FromString("left_alt");
            case GLFW_FKEY_LEFT_SUPER: return PyUnicode_FromString("left_super");
            case GLFW_FKEY_LEFT_HYPER: return PyUnicode_FromString("left_hyper");
            case GLFW_FKEY_LEFT_META: return PyUnicode_FromString("left_meta");
            case GLFW_FKEY_RIGHT_SHIFT: return PyUnicode_FromString("right_shift");
            case GLFW_FKEY_RIGHT_CONTROL: return PyUnicode_FromString("right_control");
            case GLFW_FKEY_RIGHT_ALT: return PyUnicode_FromString("right_alt");
            case GLFW_FKEY_RIGHT_SUPER: return PyUnicode_FromString("right_super");
            case GLFW_FKEY_RIGHT_HYPER: return PyUnicode_FromString("right_hyper");
            case GLFW_FKEY_RIGHT_META: return PyUnicode_FromString("right_meta");
            case GLFW_FKEY_ISO_LEVEL3_SHIFT: return PyUnicode_FromString("iso_level3_shift");
            case GLFW_FKEY_ISO_LEVEL5_SHIFT: return PyUnicode_FromString("iso_level5_shift");
/* end glfw functional key names */
        }
        char buf[8] = {0};
        encode_utf8(key, buf);
        return PyUnicode_FromString(buf);
    }
    if (!glfwGetKeyName) {
        return PyUnicode_FromFormat("0x%x", native_key);
    }
    return Py_BuildValue("z", glfwGetKeyName(key, native_key));
}


static PyObject*
glfw_window_hint(PyObject UNUSED *self, PyObject *args) {
    int key, val;
    if (!PyArg_ParseTuple(args, "ii", &key, &val)) return NULL;
    glfwWindowHint(key, val);
    Py_RETURN_NONE;
}


// }}}

static PyObject*
toggle_secure_input(PYNOARG) {
#ifdef __APPLE__
    cocoa_toggle_secure_keyboard_entry();
#endif
    Py_RETURN_NONE;
}

static PyObject*
cocoa_hide_app(PYNOARG) {
#ifdef __APPLE__
    cocoa_hide();
#endif
    Py_RETURN_NONE;
}

static PyObject*
cocoa_hide_other_apps(PYNOARG) {
#ifdef __APPLE__
    cocoa_hide_others();
#endif
    Py_RETURN_NONE;
}

static void
ring_audio_bell(OSWindow *w) {
    static monotonic_t last_bell_at = -1;
    monotonic_t now = monotonic();
    if (last_bell_at >= 0 && now - last_bell_at <= ms_to_monotonic_t(100ll)) return;
    last_bell_at = now;
#ifdef __APPLE__
    (void)w;
    cocoa_system_beep(OPT(bell_path));
#else
    if (OPT(bell_path)) play_canberra_sound(OPT(bell_path), "kitty bell", true, "event", OPT(bell_theme));
    else {
        if (!global_state.is_wayland || !glfwWaylandBeep(w ? w->handle : NULL)) play_canberra_sound(
                "bell", "kitty bell", false, "event", OPT(bell_theme));
    }
#endif
}

static PyObject*
ring_bell(PyObject *self UNUSED, PyObject *args) {
    unsigned long long os_window_id = 0;
    if (!PyArg_ParseTuple(args, "|K", &os_window_id)) return NULL;
    OSWindow *w = os_window_for_id(os_window_id);
    ring_audio_bell(w);
    Py_RETURN_NONE;
}

static PyObject*
get_content_scale_for_window(PYNOARG) {
    OSWindow *w = global_state.callback_os_window ? global_state.callback_os_window : global_state.os_windows;
    float xscale, yscale;
    glfwGetWindowContentScale(w->handle, &xscale, &yscale);
    return Py_BuildValue("ff", xscale, yscale);
}

static void
activation_token_callback(GLFWwindow *window UNUSED, const char *token, void *data) {
    if (!token || !token[0]) {
        token = "";
        log_error("Wayland: Did not get activation token from compositor. Use a better compositor.");
    }
    PyObject *ret = PyObject_CallFunction(data, "s", token);
    if (ret == NULL) PyErr_Print();
    else Py_DECREF(ret);
    Py_CLEAR(data);
}

void
run_with_activation_token_in_os_window(OSWindow *w, PyObject *callback) {
    if (global_state.is_wayland) {
        Py_INCREF(callback);
        glfwWaylandRunWithActivationToken(w->handle, activation_token_callback, callback);
    }
}

static PyObject*
toggle_fullscreen(PyObject UNUSED *self, PyObject *args) {
    id_type os_window_id = 0;
    if (!PyArg_ParseTuple(args, "|K", &os_window_id)) return NULL;
    OSWindow *w = os_window_id ? os_window_for_id(os_window_id) : current_os_window();
    if (!w) Py_RETURN_NONE;
    if (toggle_fullscreen_for_os_window(w)) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

static PyObject*
toggle_maximized(PyObject UNUSED *self, PyObject *args) {
    id_type os_window_id = 0;
    if (!PyArg_ParseTuple(args, "|K", &os_window_id)) return NULL;
    OSWindow *w = os_window_id ? os_window_for_id(os_window_id) : current_os_window();
    if (!w) Py_RETURN_NONE;
    if (toggle_maximized_for_os_window(w)) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

static PyObject*
cocoa_minimize_os_window(PyObject UNUSED *self, PyObject *args) {
    id_type os_window_id = 0;
    if (!PyArg_ParseTuple(args, "|K", &os_window_id)) return NULL;
#ifdef __APPLE__
    OSWindow *w = os_window_id ? os_window_for_id(os_window_id) : current_os_window();
    if (!w || !w->handle || w->is_layer_shell) Py_RETURN_NONE;
    if (!glfwGetCocoaWindow) { PyErr_SetString(PyExc_RuntimeError, "Failed to load glfwGetCocoaWindow"); return NULL; }
    void *window = glfwGetCocoaWindow(w->handle);
    if (!window) Py_RETURN_NONE;
    cocoa_minimize(window);
#else
    PyErr_SetString(PyExc_RuntimeError, "cocoa_minimize_os_window() is only supported on macOS");
    return NULL;
#endif
    Py_RETURN_NONE;
}

static PyObject*
change_os_window_state(PyObject *self UNUSED, PyObject *args) {
    int state;
    id_type wid = 0;
    if (!PyArg_ParseTuple(args, "i|K", &state, &wid)) return NULL;
    OSWindow *w = wid ? os_window_for_id(wid) : current_os_window();
    if (!w || !w->handle) Py_RETURN_NONE;
    if (state < WINDOW_NORMAL || state > WINDOW_MINIMIZED) {
        PyErr_SetString(PyExc_ValueError, "Unknown window state");
        return NULL;
    }
    change_state_for_os_window(w, state);
    Py_RETURN_NONE;
}

void
request_window_attention(id_type kitty_window_id, bool audio_bell) {
    OSWindow *w = os_window_for_kitty_window(kitty_window_id);
    if (w) {
        if (audio_bell) ring_audio_bell(w);
        if (OPT(window_alert_on_bell)) glfwRequestWindowAttention(w->handle);
        glfwPostEmptyEvent();
    }
}

void
set_os_window_title(OSWindow *w, const char *title) {
    if (!title) {
        if (global_state.is_wayland) glfwWaylandRedrawCSDWindowTitle(w->handle);
        return;
    }
    static char buf[2048];
    strip_csi_(title, buf, arraysz(buf));
    glfwSetWindowTitle(w->handle, buf);
}

void
hide_mouse(OSWindow *w) {
    glfwSetInputMode(w->handle, GLFW_CURSOR, GLFW_CURSOR_HIDDEN);
    w->mouse_activate_deadline = -1;
}

bool
is_mouse_hidden(OSWindow *w) {
    return w->handle && glfwGetInputMode(w->handle, GLFW_CURSOR) == GLFW_CURSOR_HIDDEN;
}


void
swap_window_buffers(OSWindow *os_window) {
    if (glfwAreSwapsAllowed(os_window->handle)) {
        glfwSwapBuffers(os_window->handle);
        os_window->keep_rendering_till_swap = 0;
    }
}

void
wakeup_main_loop(void) {
    glfwPostEmptyEvent();
}

bool
should_os_window_be_rendered(OSWindow* w) {
    return (
            glfwGetWindowAttrib(w->handle, GLFW_ICONIFIED)
            || !glfwGetWindowAttrib(w->handle, GLFW_VISIBLE)
            || glfwGetWindowAttrib(w->handle, GLFW_OCCLUDED)
            || !glfwAreSwapsAllowed(w->handle)
       ) ? false : true;
}

static PyObject*
primary_monitor_size(PYNOARG) {
    GLFWmonitor* monitor = glfwGetPrimaryMonitor();
    const GLFWvidmode* mode = glfwGetVideoMode(monitor);
    if (mode == NULL) { PyErr_SetString(PyExc_ValueError, "Failed to get video mode for primary monitor"); return NULL; }
    return Py_BuildValue("ii", mode->width, mode->height);
}

static PyObject*
get_monitor_workarea(PYNOARG) {
    int count = 0;
    GLFWmonitor **monitors = glfwGetMonitors(&count);
    if (count <= 0 || !monitors) return PyTuple_New(0);
    RAII_PyObject(result, PyTuple_New(count)); if (!result) return NULL;
    for (int i = 0; i < count; i++) {
        int xpos, ypos, width, height;
        glfwGetMonitorWorkarea(monitors[i], &xpos, &ypos, &width, &height);
        PyObject *monitor_workarea = Py_BuildValue("iiii", xpos, ypos, width, height);
        if (!monitor_workarea) return NULL;
        PyTuple_SET_ITEM(result, i, monitor_workarea);
    }
    return Py_NewRef(result);
}

static PyObject*
get_monitor_names(PYNOARG) {
    int count = 0;
    GLFWmonitor **monitors = glfwGetMonitors(&count);
    if (count <= 0 || !monitors) return PyTuple_New(0);
    RAII_PyObject(result, PyTuple_New(count)); if (!result) return NULL;
    for (int i = 0; i < count; i++) {
        const char *name = glfwGetMonitorName(monitors[i]);
        const char *description = glfwGetMonitorDescription(monitors[i]);
        PyObject *x = Py_BuildValue("ss", name, description);
        if (!x) return NULL;
        PyTuple_SET_ITEM(result, i, x);
    }
    return Py_NewRef(result);
}


static PyObject*
primary_monitor_content_scale(PYNOARG) {
    GLFWmonitor* monitor = glfwGetPrimaryMonitor();
    float xscale = 1.0, yscale = 1.0;
    if (monitor) glfwGetMonitorContentScale(monitor, &xscale, &yscale);
    return Py_BuildValue("ff", xscale, yscale);
}

static PyObject*
x11_display(PYNOARG) {
    if (glfwGetX11Display) {
        return PyLong_FromVoidPtr(glfwGetX11Display());
    } else log_error("Failed to load glfwGetX11Display");
    Py_RETURN_NONE;
}

static PyObject*
wayland_compositor_data(PYNOARG) {
    pid_t pid = -1;
    const char *missing_capabilities = NULL;
    if (global_state.is_wayland && glfwWaylandCompositorPID) {
        pid = glfwWaylandCompositorPID();
        missing_capabilities = glfwWaylandMissingCapabilities();
    }
    return Py_BuildValue("Ls", (long long)pid, missing_capabilities);
}

static PyObject*
x11_window_id(PyObject UNUSED *self, PyObject *os_wid) {
    OSWindow *w = os_window_for_id(PyLong_AsUnsignedLongLong(os_wid));
    if (!w) { PyErr_SetString(PyExc_ValueError, "No OSWindow with the specified id found"); return NULL; }
    if (!glfwGetX11Window) { PyErr_SetString(PyExc_RuntimeError, "Failed to load glfwGetX11Window"); return NULL; }
    return PyLong_FromUnsignedLong(glfwGetX11Window(w->handle));
}

static PyObject*
cocoa_window_id(PyObject UNUSED *self, PyObject *os_wid) {
    OSWindow *w = os_window_for_id(PyLong_AsUnsignedLongLong(os_wid));
    if (!w) { PyErr_SetString(PyExc_ValueError, "No OSWindow with the specified id found"); return NULL; }
    if (!glfwGetCocoaWindow) { PyErr_SetString(PyExc_RuntimeError, "Failed to load glfwGetCocoaWindow"); return NULL; }
#ifdef __APPLE__
    return Py_BuildValue("l", (long)cocoa_window_number(glfwGetCocoaWindow(w->handle)));
#else
    PyErr_SetString(PyExc_RuntimeError, "cocoa_window_id() is only supported on Mac");
    return NULL;
#endif
}

static GLFWCursorShape
pointer_name_to_glfw_name(const char *name) {
    /* start name to glfw (auto generated by gen-key-constants.py do not edit) */
    if (strcmp(name, "arrow") == 0) return GLFW_DEFAULT_CURSOR;
    if (strcmp(name, "beam") == 0) return GLFW_TEXT_CURSOR;
    if (strcmp(name, "text") == 0) return GLFW_TEXT_CURSOR;
    if (strcmp(name, "pointer") == 0) return GLFW_POINTER_CURSOR;
    if (strcmp(name, "hand") == 0) return GLFW_POINTER_CURSOR;
    if (strcmp(name, "help") == 0) return GLFW_HELP_CURSOR;
    if (strcmp(name, "wait") == 0) return GLFW_WAIT_CURSOR;
    if (strcmp(name, "progress") == 0) return GLFW_PROGRESS_CURSOR;
    if (strcmp(name, "crosshair") == 0) return GLFW_CROSSHAIR_CURSOR;
    if (strcmp(name, "cell") == 0) return GLFW_CELL_CURSOR;
    if (strcmp(name, "vertical-text") == 0) return GLFW_VERTICAL_TEXT_CURSOR;
    if (strcmp(name, "move") == 0) return GLFW_MOVE_CURSOR;
    if (strcmp(name, "e-resize") == 0) return GLFW_E_RESIZE_CURSOR;
    if (strcmp(name, "ne-resize") == 0) return GLFW_NE_RESIZE_CURSOR;
    if (strcmp(name, "nw-resize") == 0) return GLFW_NW_RESIZE_CURSOR;
    if (strcmp(name, "n-resize") == 0) return GLFW_N_RESIZE_CURSOR;
    if (strcmp(name, "se-resize") == 0) return GLFW_SE_RESIZE_CURSOR;
    if (strcmp(name, "sw-resize") == 0) return GLFW_SW_RESIZE_CURSOR;
    if (strcmp(name, "s-resize") == 0) return GLFW_S_RESIZE_CURSOR;
    if (strcmp(name, "w-resize") == 0) return GLFW_W_RESIZE_CURSOR;
    if (strcmp(name, "ew-resize") == 0) return GLFW_EW_RESIZE_CURSOR;
    if (strcmp(name, "ns-resize") == 0) return GLFW_NS_RESIZE_CURSOR;
    if (strcmp(name, "nesw-resize") == 0) return GLFW_NESW_RESIZE_CURSOR;
    if (strcmp(name, "nwse-resize") == 0) return GLFW_NWSE_RESIZE_CURSOR;
    if (strcmp(name, "zoom-in") == 0) return GLFW_ZOOM_IN_CURSOR;
    if (strcmp(name, "zoom-out") == 0) return GLFW_ZOOM_OUT_CURSOR;
    if (strcmp(name, "alias") == 0) return GLFW_ALIAS_CURSOR;
    if (strcmp(name, "copy") == 0) return GLFW_COPY_CURSOR;
    if (strcmp(name, "not-allowed") == 0) return GLFW_NOT_ALLOWED_CURSOR;
    if (strcmp(name, "no-drop") == 0) return GLFW_NO_DROP_CURSOR;
    if (strcmp(name, "grab") == 0) return GLFW_GRAB_CURSOR;
    if (strcmp(name, "grabbing") == 0) return GLFW_GRABBING_CURSOR;
/* end name to glfw */
    return GLFW_INVALID_CURSOR;
}

static PyObject*
is_css_pointer_name_valid(PyObject *self UNUSED, PyObject *name) {
    if (!PyUnicode_Check(name)) { PyErr_SetString(PyExc_TypeError, "pointer name must be a string"); return NULL; }
    const char *q = PyUnicode_AsUTF8(name);
    if (strcmp(q, "default") == 0) { Py_RETURN_TRUE; }
    if (pointer_name_to_glfw_name(q) == GLFW_INVALID_CURSOR) { Py_RETURN_FALSE; }
    Py_RETURN_TRUE;
}

static const char*
glfw_name_to_css_pointer_name(GLFWCursorShape q) {
    switch(q) {
        case GLFW_INVALID_CURSOR: return "";
        /* start glfw to css (auto generated by gen-key-constants.py do not edit) */
        case GLFW_DEFAULT_CURSOR: return "default";
        case GLFW_TEXT_CURSOR: return "text";
        case GLFW_POINTER_CURSOR: return "pointer";
        case GLFW_HELP_CURSOR: return "help";
        case GLFW_WAIT_CURSOR: return "wait";
        case GLFW_PROGRESS_CURSOR: return "progress";
        case GLFW_CROSSHAIR_CURSOR: return "crosshair";
        case GLFW_CELL_CURSOR: return "cell";
        case GLFW_VERTICAL_TEXT_CURSOR: return "vertical-text";
        case GLFW_MOVE_CURSOR: return "move";
        case GLFW_E_RESIZE_CURSOR: return "e-resize";
        case GLFW_NE_RESIZE_CURSOR: return "ne-resize";
        case GLFW_NW_RESIZE_CURSOR: return "nw-resize";
        case GLFW_N_RESIZE_CURSOR: return "n-resize";
        case GLFW_SE_RESIZE_CURSOR: return "se-resize";
        case GLFW_SW_RESIZE_CURSOR: return "sw-resize";
        case GLFW_S_RESIZE_CURSOR: return "s-resize";
        case GLFW_W_RESIZE_CURSOR: return "w-resize";
        case GLFW_EW_RESIZE_CURSOR: return "ew-resize";
        case GLFW_NS_RESIZE_CURSOR: return "ns-resize";
        case GLFW_NESW_RESIZE_CURSOR: return "nesw-resize";
        case GLFW_NWSE_RESIZE_CURSOR: return "nwse-resize";
        case GLFW_ZOOM_IN_CURSOR: return "zoom-in";
        case GLFW_ZOOM_OUT_CURSOR: return "zoom-out";
        case GLFW_ALIAS_CURSOR: return "alias";
        case GLFW_COPY_CURSOR: return "copy";
        case GLFW_NOT_ALLOWED_CURSOR: return "not-allowed";
        case GLFW_NO_DROP_CURSOR: return "no-drop";
        case GLFW_GRAB_CURSOR: return "grab";
        case GLFW_GRABBING_CURSOR: return "grabbing";
/* end glfw to css */
    }
    return "";
}

static PyObject*
pointer_name_to_css_name(PyObject *self UNUSED, PyObject *name) {
    if (!PyUnicode_Check(name)) { PyErr_SetString(PyExc_TypeError, "pointer name must be a string"); return NULL; }
    GLFWCursorShape s = pointer_name_to_glfw_name(PyUnicode_AsUTF8(name));
    return PyUnicode_FromString(glfw_name_to_css_pointer_name(s));
}

static PyObject*
set_custom_cursor(PyObject *self UNUSED, PyObject *args) {
    int x=0, y=0;
    Py_ssize_t sz;
    PyObject *images;
    const char *shape;
    if (!PyArg_ParseTuple(args, "sO!|ii", &shape, &PyTuple_Type, &images, &x, &y)) return NULL;
    static GLFWimage gimages[16] = {{0}};
    size_t count = MIN((size_t)PyTuple_GET_SIZE(images), arraysz(gimages));
    for (size_t i = 0; i < count; i++) {
        if (!PyArg_ParseTuple(PyTuple_GET_ITEM(images, i), "s#ii", &gimages[i].pixels, &sz, &gimages[i].width, &gimages[i].height)) return NULL;
        if ((Py_ssize_t)gimages[i].width * gimages[i].height * 4 != sz) {
            PyErr_SetString(PyExc_ValueError, "The image data size does not match its width and height");
            return NULL;
        }
    }
    GLFWCursorShape gshape = pointer_name_to_glfw_name(shape);
    if (gshape == GLFW_INVALID_CURSOR) { PyErr_Format(PyExc_KeyError, "Unknown pointer shape: %s", shape); return NULL; }
    GLFWcursor *c = glfwCreateCursor(gimages, x, y, count);
    if (c == NULL) { PyErr_SetString(PyExc_ValueError, "Failed to create custom cursor from specified images"); return NULL; }
    if (cursors[gshape].initialized && cursors[gshape].is_custom && cursors[gshape].glfw) {
        glfwDestroyCursor(cursors[gshape].glfw);
    }
    cursors[gshape].initialized = true; cursors[gshape].is_custom = true; cursors[gshape].glfw = c;
    Py_RETURN_NONE;
}

#ifdef __APPLE__
void
get_cocoa_key_equivalent(uint32_t key, int mods, char *cocoa_key, size_t key_sz, int *cocoa_mods) {
    memset(cocoa_key, 0, key_sz);
    uint32_t ans = glfwGetCocoaKeyEquivalent(key, mods, cocoa_mods);
    if (ans) encode_utf8(ans, cocoa_key);
}

static void
cocoa_frame_request_callback(GLFWwindow *window) {
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        if (global_state.os_windows[i].handle == window) {
            global_state.os_windows[i].render_state = RENDER_FRAME_READY;
            global_state.os_windows[i].last_render_frame_received_at = monotonic();
            request_tick_callback();
            break;
        }
    }
}

void
request_frame_render(OSWindow *w) {
    glfwCocoaRequestRenderFrame(w->handle, cocoa_frame_request_callback);
    w->render_state = RENDER_FRAME_REQUESTED;
}

static PyObject*
py_recreate_global_menu(PyObject *self UNUSED, PyObject *args UNUSED) {
    cocoa_recreate_global_menu();
    Py_RETURN_NONE;
}

static PyObject*
py_clear_global_shortcuts(PyObject *self UNUSED, PyObject *args UNUSED) {
    cocoa_clear_global_shortcuts();
    Py_RETURN_NONE;
}
#else

static void
wayland_frame_request_callback(id_type os_window_id) {
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        if (global_state.os_windows[i].id == os_window_id) {
            global_state.os_windows[i].render_state = RENDER_FRAME_READY;
            global_state.os_windows[i].last_render_frame_received_at = monotonic();
            request_tick_callback();
            break;
        }
    }
}

void
request_frame_render(OSWindow *w) {
    // Some Wayland compositors are too fragile to handle multiple
    // render frame requests, see https://github.com/kovidgoyal/kitty/issues/2329
    if (w->render_state != RENDER_FRAME_REQUESTED) {
        w->render_state = RENDER_FRAME_REQUESTED;
        glfwRequestWaylandFrameEvent(w->handle, w->id, wayland_frame_request_callback);
    }
}

void
dbus_notification_created_callback(unsigned long long notification_id, uint32_t new_notification_id, void* data UNUSED) {
    unsigned long new_id = new_notification_id;
    send_dbus_notification_event_to_python("created", notification_id, new_id);
}

static PyObject*
dbus_send_notification(PyObject *self UNUSED, PyObject *args, PyObject *kw) {
    int timeout = -1, urgency = 1; unsigned int replaces = 0;
    GLFWDBUSNotificationData d = {0};
    static const char* kwlist[] = {"app_name", "app_icon", "title", "body", "actions", "timeout", "urgency", "replaces", "category", "muted", NULL};
    PyObject *actions = NULL;
    if (!PyArg_ParseTupleAndKeywords(args, kw, "ssssO!|iiIsp", (char**)kwlist,
        &d.app_name, &d.icon, &d.summary, &d.body, &PyDict_Type, &actions, &timeout, &urgency, &replaces, &d.category, &d.muted)) return NULL;
    if (!glfwDBusUserNotify) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to load glfwDBusUserNotify, did you call glfw_init?");
        return NULL;
    }
    d.timeout = timeout;
    d.urgency = urgency & 3;
    d.replaces = replaces;
    RAII_ALLOC(const char*, aclist, calloc(2*PyDict_Size(actions), sizeof(d.actions[0])));
    if (!aclist) { return PyErr_NoMemory(); }
    PyObject *key, *value; Py_ssize_t pos = 0;
    d.num_actions = 0;
    while (PyDict_Next(actions, &pos, &key, &value)) {
        if (!PyUnicode_Check(key) || !PyUnicode_Check(value)) { PyErr_SetString(PyExc_TypeError, "actions must be strings"); return NULL; }
        if (PyUnicode_GET_LENGTH(key) == 0 || PyUnicode_GET_LENGTH(value) == 0) { PyErr_SetString(PyExc_TypeError, "actions must be non-empty strings"); return NULL; }
        aclist[d.num_actions] = PyUnicode_AsUTF8(key); if (!aclist[d.num_actions++]) return NULL;
        aclist[d.num_actions] = PyUnicode_AsUTF8(value); if (!aclist[d.num_actions++]) return NULL;
    }
    d.actions = aclist;
    unsigned long long notification_id = glfwDBusUserNotify(&d, dbus_notification_created_callback, NULL);
    return PyLong_FromUnsignedLongLong(notification_id);
}

static PyObject*
dbus_close_notification(PyObject *self UNUSED, PyObject *args) {
    unsigned int id;
    if (!PyArg_ParseTuple(args, "I", &id)) return NULL;
    GLFWDBUSNotificationData d = {.timeout=-9999, .urgency=255};
    if (!glfwDBusUserNotify) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to load glfwDBusUserNotify, did you call glfw_init?");
        return NULL;
    }
    if (glfwDBusUserNotify(&d, NULL, &id)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}


#endif

static PyObject*
get_click_interval(PyObject *self UNUSED, PyObject *args UNUSED) {
    return PyFloat_FromDouble(monotonic_t_to_s_double(OPT(click_interval)));
}

id_type
add_main_loop_timer(monotonic_t interval, bool repeats, timer_callback_fun callback, void *callback_data, timer_callback_fun free_callback) {
    return glfwAddTimer(interval, repeats, callback, callback_data, free_callback);
}

void
update_main_loop_timer(id_type timer_id, monotonic_t interval, bool enabled) {
    glfwUpdateTimer(timer_id, interval, enabled);
}

void
remove_main_loop_timer(id_type timer_id) {
    glfwRemoveTimer(timer_id);
}

void
run_main_loop(tick_callback_fun cb, void* cb_data) {
    glfwRunMainLoop(cb, cb_data);
}

void
stop_main_loop(void) {
#ifdef __APPLE__
    if (apple_preserve_common_context) glfwDestroyWindow(apple_preserve_common_context);
    apple_preserve_common_context = NULL;
#endif
    glfwStopMainLoop();
}

static PyObject*
strip_csi(PyObject *self UNUSED, PyObject *src) {
    if (!PyUnicode_Check(src)) { PyErr_SetString(PyExc_TypeError, "Unicode string expected"); return NULL; }
    Py_ssize_t sz;
    const char *title = PyUnicode_AsUTF8AndSize(src, &sz);
    if (!title) return NULL;
    RAII_ALLOC(char, buf, malloc(sz + 1));
    if (!buf) { return PyErr_NoMemory(); }
    strip_csi_(title, buf, sz + 1);
    return PyUnicode_FromString(buf);
}

void
set_ignore_os_keyboard_processing(bool enabled) {
    glfwSetIgnoreOSKeyboardProcessing(enabled);
}

static void
decref_pyobj(void *x) {
    Py_XDECREF(x);
}

static GLFWDataChunk
get_clipboard_data(const char *mime_type, void *iter, GLFWClipboardType ct) {
    GLFWDataChunk ans = {.iter=iter, .free=decref_pyobj};
    if (global_state.boss == NULL) return ans;
    if (iter == NULL) {
        PyObject *c = PyObject_GetAttrString(global_state.boss, ct == GLFW_PRIMARY_SELECTION ? "primary_selection" : "clipboard");
        if (c == NULL) { return ans; }
        PyObject *i = PyObject_CallFunction(c, "s", mime_type);
        Py_DECREF(c);
        if (!i) { return ans; }
        ans.iter = i;
        return ans;
    }
    if (mime_type == NULL) {
        Py_XDECREF(iter);
        return ans;
    }

    PyObject *ret = PyObject_CallFunctionObjArgs(iter, NULL);
    if (ret == NULL) return ans;
    ans.data = PyBytes_AS_STRING(ret);
    ans.sz = PyBytes_GET_SIZE(ret);
    ans.free_data = ret;
    return ans;
}

static PyObject*
set_clipboard_data_types(PyObject *self UNUSED, PyObject *args) {
    PyObject *mta;
    int ctype;
    if (!PyArg_ParseTuple(args, "iO!", &ctype, &PyTuple_Type, &mta)) return NULL;
    if (glfwSetClipboardDataTypes) {
        const char **mime_types = calloc(PyTuple_GET_SIZE(mta), sizeof(char*));
        if (!mime_types) return PyErr_NoMemory();
        for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(mta); i++) mime_types[i] = PyUnicode_AsUTF8(PyTuple_GET_ITEM(mta, i));
        glfwSetClipboardDataTypes(ctype, mime_types, PyTuple_GET_SIZE(mta), get_clipboard_data);
        free(mime_types);
    } else log_error("GLFW not initialized cannot set clipboard data");
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
}

static bool
write_clipboard_data(void *callback, const char *data, size_t sz) {
    Py_ssize_t z = sz;
    if (data == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "is_self_offer");
        return false;
    }
    PyObject *ret = PyObject_CallFunction(callback, "y#", data, z);
    bool ok = false;
    if (ret != NULL) { ok = true; Py_DECREF(ret); }
    return ok;
}

static PyObject*
get_clipboard_mime(PyObject *self UNUSED, PyObject *args) {
    int ctype;
    const char *mime;
    PyObject *callback;
    if (!PyArg_ParseTuple(args, "izO", &ctype, &mime, &callback)) return NULL;
    glfwGetClipboard(ctype, mime, write_clipboard_data, callback);
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
}

static PyObject*
is_layer_shell_supported(PyObject *self UNUSED, PyObject *args UNUSED) {
    return Py_NewRef(glfwIsLayerShellSupported() ? Py_True : Py_False);
}

static PyObject*
toggle_os_window_visibility(PyObject *self UNUSED, PyObject *args) {
    unsigned long long wid;
    int set_visible = -1;
    if (!PyArg_ParseTuple(args, "K|p", &wid, &set_visible)) return NULL;
    OSWindow *w = os_window_for_id(wid);
    if (!w || !w->handle) Py_RETURN_FALSE;
    bool is_visible = glfwGetWindowAttrib(w->handle, GLFW_VISIBLE) != 0;
    if (set_visible == -1) set_visible = !is_visible;
    else if (set_visible == is_visible) Py_RETURN_FALSE;
    set_os_window_visibility(w, set_visible);
    Py_RETURN_TRUE;
}

static PyObject*
layer_shell_config_for_os_window(PyObject *self UNUSED, PyObject *wid) {
    if (!PyLong_Check(wid)) { PyErr_SetString(PyExc_TypeError, "os_window_id must be a int"); return NULL; }
#ifdef __APPLE__
    (void)layer_shell_config_to_python;
    Py_RETURN_NONE;
#else
    if (!global_state.is_wayland) Py_RETURN_NONE;
    id_type id = PyLong_AsUnsignedLongLong(wid);
    OSWindow *w = os_window_for_id(id);
    if (!w || !w->handle) Py_RETURN_NONE;
    const GLFWLayerShellConfig *c = glfwGetLayerShellConfig(w->handle);
    if (!c) Py_RETURN_NONE;
    return layer_shell_config_to_python(c);
#endif
}

static PyObject*
set_layer_shell_config(PyObject *self UNUSED, PyObject *args) {
    unsigned long long wid; PyObject *pylsc;
    if (!PyArg_ParseTuple(args, "KO", &wid, &pylsc)) return NULL;
    OSWindow *window = os_window_for_id(wid);
    if (!window || !window->handle || !window->is_layer_shell) Py_RETURN_FALSE;
    GLFWLayerShellConfig lsc = {0};
    if (!layer_shell_config_from_python(pylsc, &lsc)) return NULL;
    return Py_NewRef(set_layer_shell_config_for(window, &lsc) ? Py_True : Py_False);
}

static PyObject*
grab_keyboard(PyObject *self UNUSED, PyObject *action) {
    return Py_NewRef(glfwGrabKeyboard(action == Py_None ? 2 : PyObject_IsTrue(action)) ? Py_True : Py_False);
}

// Boilerplate {{{

static PyMethodDef module_methods[] = {
    METHODB(set_custom_cursor, METH_VARARGS),
    METHODB(is_css_pointer_name_valid, METH_O),
    METHODB(toggle_os_window_visibility, METH_VARARGS),
    METHODB(layer_shell_config_for_os_window, METH_O),
    METHODB(set_layer_shell_config, METH_VARARGS),
    METHODB(grab_keyboard, METH_O),
    METHODB(pointer_name_to_css_name, METH_O),
    {"create_os_window", (PyCFunction)(void (*) (void))(create_os_window), METH_VARARGS | METH_KEYWORDS, NULL},
    METHODB(set_default_window_icon, METH_VARARGS),
    METHODB(set_os_window_icon, METH_VARARGS),
    METHODB(set_clipboard_data_types, METH_VARARGS),
    METHODB(get_clipboard_mime, METH_VARARGS),
    METHODB(toggle_secure_input, METH_NOARGS),
    METHODB(get_content_scale_for_window, METH_NOARGS),
    METHODB(ring_bell, METH_VARARGS),
    METHODB(toggle_fullscreen, METH_VARARGS),
    METHODB(toggle_maximized, METH_VARARGS),
    METHODB(change_os_window_state, METH_VARARGS),
    METHODB(glfw_window_hint, METH_VARARGS),
    METHODB(x11_display, METH_NOARGS),
    METHODB(wayland_compositor_data, METH_NOARGS),
    METHODB(get_click_interval, METH_NOARGS),
    METHODB(is_layer_shell_supported, METH_NOARGS),
    METHODB(x11_window_id, METH_O),
    METHODB(strip_csi, METH_O),
#ifndef __APPLE__
    METHODB(dbus_close_notification, METH_VARARGS),
    METHODB(dbus_set_notification_callback, METH_O),
    {"dbus_send_notification", (PyCFunction)(void (*) (void))(dbus_send_notification), METH_KEYWORDS | METH_VARARGS, NULL},
#else
    {"cocoa_recreate_global_menu", (PyCFunction)py_recreate_global_menu, METH_NOARGS, ""},
    {"cocoa_clear_global_shortcuts", (PyCFunction)py_clear_global_shortcuts, METH_NOARGS, ""},
#endif
    METHODB(cocoa_window_id, METH_O),
    METHODB(cocoa_hide_app, METH_NOARGS),
    METHODB(cocoa_hide_other_apps, METH_NOARGS),
    METHODB(cocoa_minimize_os_window, METH_VARARGS),
    {"glfw_init", (PyCFunction)glfw_init, METH_VARARGS, ""},
    METHODB(opengl_version_string, METH_NOARGS),
    {"glfw_terminate", (PyCFunction)glfw_terminate, METH_NOARGS, ""},
    {"glfw_get_physical_dpi", (PyCFunction)glfw_get_physical_dpi, METH_NOARGS, ""},
    {"glfw_get_key_name", (PyCFunction)glfw_get_key_name, METH_VARARGS, ""},
    {"glfw_get_system_color_theme", (PyCFunction)glfw_get_system_color_theme, METH_VARARGS, ""},
    {"glfw_primary_monitor_size", (PyCFunction)primary_monitor_size, METH_NOARGS, ""},
    {"glfw_get_monitor_workarea", (PyCFunction)get_monitor_workarea, METH_NOARGS, ""},
    {"glfw_get_monitor_names", (PyCFunction)get_monitor_names, METH_NOARGS, ""},
    {"glfw_primary_monitor_content_scale", (PyCFunction)primary_monitor_content_scale, METH_NOARGS, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

void cleanup_glfw(void) {
    if (logo.pixels) free(logo.pixels);
    logo.pixels = NULL;
    Py_CLEAR(edge_spacing_func);
#ifndef __APPLE__
    Py_CLEAR(dbus_notification_callback);
    release_freetype_render_context(csd_title_render_ctx);
#endif
}

bool
init_glfw(PyObject *m) {
    if (PyModule_AddFunctions(m, module_methods) != 0) return false;
    register_at_exit_cleanup_func(GLFW_CLEANUP_FUNC, cleanup_glfw);

// constants {{{
#define ADDC(n) if(PyModule_AddIntConstant(m, #n, n) != 0) return false;
    ADDC(GLFW_RELEASE);
    ADDC(GLFW_PRESS);
    ADDC(GLFW_REPEAT);
    ADDC(true); ADDC(false);
    ADDC(GLFW_PRIMARY_SELECTION); ADDC(GLFW_CLIPBOARD);
    ADDC(GLFW_LAYER_SHELL_NONE); ADDC(GLFW_LAYER_SHELL_PANEL); ADDC(GLFW_LAYER_SHELL_BACKGROUND); ADDC(GLFW_LAYER_SHELL_TOP); ADDC(GLFW_LAYER_SHELL_OVERLAY);
    ADDC(GLFW_FOCUS_NOT_ALLOWED); ADDC(GLFW_FOCUS_EXCLUSIVE); ADDC(GLFW_FOCUS_ON_DEMAND);
    ADDC(GLFW_EDGE_TOP); ADDC(GLFW_EDGE_BOTTOM); ADDC(GLFW_EDGE_LEFT); ADDC(GLFW_EDGE_RIGHT); ADDC(GLFW_EDGE_CENTER); ADDC(GLFW_EDGE_NONE);
    ADDC(GLFW_EDGE_CENTER_SIZED);
    ADDC(GLFW_COLOR_SCHEME_NO_PREFERENCE); ADDC(GLFW_COLOR_SCHEME_DARK); ADDC(GLFW_COLOR_SCHEME_LIGHT);

    /* start glfw functional keys (auto generated by gen-key-constants.py do not edit) */
    ADDC(GLFW_FKEY_ESCAPE);
    ADDC(GLFW_FKEY_ENTER);
    ADDC(GLFW_FKEY_TAB);
    ADDC(GLFW_FKEY_BACKSPACE);
    ADDC(GLFW_FKEY_INSERT);
    ADDC(GLFW_FKEY_DELETE);
    ADDC(GLFW_FKEY_LEFT);
    ADDC(GLFW_FKEY_RIGHT);
    ADDC(GLFW_FKEY_UP);
    ADDC(GLFW_FKEY_DOWN);
    ADDC(GLFW_FKEY_PAGE_UP);
    ADDC(GLFW_FKEY_PAGE_DOWN);
    ADDC(GLFW_FKEY_HOME);
    ADDC(GLFW_FKEY_END);
    ADDC(GLFW_FKEY_CAPS_LOCK);
    ADDC(GLFW_FKEY_SCROLL_LOCK);
    ADDC(GLFW_FKEY_NUM_LOCK);
    ADDC(GLFW_FKEY_PRINT_SCREEN);
    ADDC(GLFW_FKEY_PAUSE);
    ADDC(GLFW_FKEY_MENU);
    ADDC(GLFW_FKEY_F1);
    ADDC(GLFW_FKEY_F2);
    ADDC(GLFW_FKEY_F3);
    ADDC(GLFW_FKEY_F4);
    ADDC(GLFW_FKEY_F5);
    ADDC(GLFW_FKEY_F6);
    ADDC(GLFW_FKEY_F7);
    ADDC(GLFW_FKEY_F8);
    ADDC(GLFW_FKEY_F9);
    ADDC(GLFW_FKEY_F10);
    ADDC(GLFW_FKEY_F11);
    ADDC(GLFW_FKEY_F12);
    ADDC(GLFW_FKEY_F13);
    ADDC(GLFW_FKEY_F14);
    ADDC(GLFW_FKEY_F15);
    ADDC(GLFW_FKEY_F16);
    ADDC(GLFW_FKEY_F17);
    ADDC(GLFW_FKEY_F18);
    ADDC(GLFW_FKEY_F19);
    ADDC(GLFW_FKEY_F20);
    ADDC(GLFW_FKEY_F21);
    ADDC(GLFW_FKEY_F22);
    ADDC(GLFW_FKEY_F23);
    ADDC(GLFW_FKEY_F24);
    ADDC(GLFW_FKEY_F25);
    ADDC(GLFW_FKEY_F26);
    ADDC(GLFW_FKEY_F27);
    ADDC(GLFW_FKEY_F28);
    ADDC(GLFW_FKEY_F29);
    ADDC(GLFW_FKEY_F30);
    ADDC(GLFW_FKEY_F31);
    ADDC(GLFW_FKEY_F32);
    ADDC(GLFW_FKEY_F33);
    ADDC(GLFW_FKEY_F34);
    ADDC(GLFW_FKEY_F35);
    ADDC(GLFW_FKEY_KP_0);
    ADDC(GLFW_FKEY_KP_1);
    ADDC(GLFW_FKEY_KP_2);
    ADDC(GLFW_FKEY_KP_3);
    ADDC(GLFW_FKEY_KP_4);
    ADDC(GLFW_FKEY_KP_5);
    ADDC(GLFW_FKEY_KP_6);
    ADDC(GLFW_FKEY_KP_7);
    ADDC(GLFW_FKEY_KP_8);
    ADDC(GLFW_FKEY_KP_9);
    ADDC(GLFW_FKEY_KP_DECIMAL);
    ADDC(GLFW_FKEY_KP_DIVIDE);
    ADDC(GLFW_FKEY_KP_MULTIPLY);
    ADDC(GLFW_FKEY_KP_SUBTRACT);
    ADDC(GLFW_FKEY_KP_ADD);
    ADDC(GLFW_FKEY_KP_ENTER);
    ADDC(GLFW_FKEY_KP_EQUAL);
    ADDC(GLFW_FKEY_KP_SEPARATOR);
    ADDC(GLFW_FKEY_KP_LEFT);
    ADDC(GLFW_FKEY_KP_RIGHT);
    ADDC(GLFW_FKEY_KP_UP);
    ADDC(GLFW_FKEY_KP_DOWN);
    ADDC(GLFW_FKEY_KP_PAGE_UP);
    ADDC(GLFW_FKEY_KP_PAGE_DOWN);
    ADDC(GLFW_FKEY_KP_HOME);
    ADDC(GLFW_FKEY_KP_END);
    ADDC(GLFW_FKEY_KP_INSERT);
    ADDC(GLFW_FKEY_KP_DELETE);
    ADDC(GLFW_FKEY_KP_BEGIN);
    ADDC(GLFW_FKEY_MEDIA_PLAY);
    ADDC(GLFW_FKEY_MEDIA_PAUSE);
    ADDC(GLFW_FKEY_MEDIA_PLAY_PAUSE);
    ADDC(GLFW_FKEY_MEDIA_REVERSE);
    ADDC(GLFW_FKEY_MEDIA_STOP);
    ADDC(GLFW_FKEY_MEDIA_FAST_FORWARD);
    ADDC(GLFW_FKEY_MEDIA_REWIND);
    ADDC(GLFW_FKEY_MEDIA_TRACK_NEXT);
    ADDC(GLFW_FKEY_MEDIA_TRACK_PREVIOUS);
    ADDC(GLFW_FKEY_MEDIA_RECORD);
    ADDC(GLFW_FKEY_LOWER_VOLUME);
    ADDC(GLFW_FKEY_RAISE_VOLUME);
    ADDC(GLFW_FKEY_MUTE_VOLUME);
    ADDC(GLFW_FKEY_LEFT_SHIFT);
    ADDC(GLFW_FKEY_LEFT_CONTROL);
    ADDC(GLFW_FKEY_LEFT_ALT);
    ADDC(GLFW_FKEY_LEFT_SUPER);
    ADDC(GLFW_FKEY_LEFT_HYPER);
    ADDC(GLFW_FKEY_LEFT_META);
    ADDC(GLFW_FKEY_RIGHT_SHIFT);
    ADDC(GLFW_FKEY_RIGHT_CONTROL);
    ADDC(GLFW_FKEY_RIGHT_ALT);
    ADDC(GLFW_FKEY_RIGHT_SUPER);
    ADDC(GLFW_FKEY_RIGHT_HYPER);
    ADDC(GLFW_FKEY_RIGHT_META);
    ADDC(GLFW_FKEY_ISO_LEVEL3_SHIFT);
    ADDC(GLFW_FKEY_ISO_LEVEL5_SHIFT);
/* end glfw functional keys */
// --- Modifiers ---------------------------------------------------------------
    ADDC(GLFW_MOD_SHIFT);
    ADDC(GLFW_MOD_CONTROL);
    ADDC(GLFW_MOD_ALT);
    ADDC(GLFW_MOD_SUPER);
    ADDC(GLFW_MOD_HYPER);
    ADDC(GLFW_MOD_META);
    ADDC(GLFW_MOD_KITTY);
    ADDC(GLFW_MOD_CAPS_LOCK);
    ADDC(GLFW_MOD_NUM_LOCK);

// --- Mouse -------------------------------------------------------------------
    ADDC(GLFW_MOUSE_BUTTON_1);
    ADDC(GLFW_MOUSE_BUTTON_2);
    ADDC(GLFW_MOUSE_BUTTON_3);
    ADDC(GLFW_MOUSE_BUTTON_4);
    ADDC(GLFW_MOUSE_BUTTON_5);
    ADDC(GLFW_MOUSE_BUTTON_6);
    ADDC(GLFW_MOUSE_BUTTON_7);
    ADDC(GLFW_MOUSE_BUTTON_8);
    ADDC(GLFW_MOUSE_BUTTON_LAST);
    ADDC(GLFW_MOUSE_BUTTON_LEFT);
    ADDC(GLFW_MOUSE_BUTTON_RIGHT);
    ADDC(GLFW_MOUSE_BUTTON_MIDDLE);


// --- Joystick ----------------------------------------------------------------
    ADDC(GLFW_JOYSTICK_1);
    ADDC(GLFW_JOYSTICK_2);
    ADDC(GLFW_JOYSTICK_3);
    ADDC(GLFW_JOYSTICK_4);
    ADDC(GLFW_JOYSTICK_5);
    ADDC(GLFW_JOYSTICK_6);
    ADDC(GLFW_JOYSTICK_7);
    ADDC(GLFW_JOYSTICK_8);
    ADDC(GLFW_JOYSTICK_9);
    ADDC(GLFW_JOYSTICK_10);
    ADDC(GLFW_JOYSTICK_11);
    ADDC(GLFW_JOYSTICK_12);
    ADDC(GLFW_JOYSTICK_13);
    ADDC(GLFW_JOYSTICK_14);
    ADDC(GLFW_JOYSTICK_15);
    ADDC(GLFW_JOYSTICK_16);
    ADDC(GLFW_JOYSTICK_LAST);


// --- Error codes -------------------------------------------------------------
    ADDC(GLFW_NOT_INITIALIZED);
    ADDC(GLFW_NO_CURRENT_CONTEXT);
    ADDC(GLFW_INVALID_ENUM);
    ADDC(GLFW_INVALID_VALUE);
    ADDC(GLFW_OUT_OF_MEMORY);
    ADDC(GLFW_API_UNAVAILABLE);
    ADDC(GLFW_VERSION_UNAVAILABLE);
    ADDC(GLFW_PLATFORM_ERROR);
    ADDC(GLFW_FORMAT_UNAVAILABLE);

// ---
    ADDC(GLFW_FOCUSED);
    ADDC(GLFW_ICONIFIED);
    ADDC(GLFW_RESIZABLE);
    ADDC(GLFW_VISIBLE);
    ADDC(GLFW_DECORATED);
    ADDC(GLFW_AUTO_ICONIFY);
    ADDC(GLFW_FLOATING);

// ---
    ADDC(GLFW_RED_BITS);
    ADDC(GLFW_GREEN_BITS);
    ADDC(GLFW_BLUE_BITS);
    ADDC(GLFW_ALPHA_BITS);
    ADDC(GLFW_DEPTH_BITS);
    ADDC(GLFW_STENCIL_BITS);
    ADDC(GLFW_ACCUM_RED_BITS);
    ADDC(GLFW_ACCUM_GREEN_BITS);
    ADDC(GLFW_ACCUM_BLUE_BITS);
    ADDC(GLFW_ACCUM_ALPHA_BITS);
    ADDC(GLFW_AUX_BUFFERS);
    ADDC(GLFW_STEREO);
    ADDC(GLFW_SAMPLES);
    ADDC(GLFW_SRGB_CAPABLE);
    ADDC(GLFW_REFRESH_RATE);
    ADDC(GLFW_DOUBLEBUFFER);

// ---
    ADDC(GLFW_CLIENT_API);
    ADDC(GLFW_CONTEXT_VERSION_MAJOR);
    ADDC(GLFW_CONTEXT_VERSION_MINOR);
    ADDC(GLFW_CONTEXT_REVISION);
    ADDC(GLFW_CONTEXT_ROBUSTNESS);
    ADDC(GLFW_OPENGL_FORWARD_COMPAT);
    ADDC(GLFW_CONTEXT_DEBUG);
    ADDC(GLFW_OPENGL_PROFILE);

// ---
    ADDC(GLFW_OPENGL_API);
    ADDC(GLFW_OPENGL_ES_API);

// ---
    ADDC(GLFW_NO_ROBUSTNESS);
    ADDC(GLFW_NO_RESET_NOTIFICATION);
    ADDC(GLFW_LOSE_CONTEXT_ON_RESET);

// ---
    ADDC(GLFW_OPENGL_ANY_PROFILE);
    ADDC(GLFW_OPENGL_CORE_PROFILE);
    ADDC(GLFW_OPENGL_COMPAT_PROFILE);

// ---
    ADDC(GLFW_CURSOR);
    ADDC(GLFW_STICKY_KEYS);
    ADDC(GLFW_STICKY_MOUSE_BUTTONS);

// ---
    ADDC(GLFW_CURSOR_NORMAL);
    ADDC(GLFW_CURSOR_HIDDEN);
    ADDC(GLFW_CURSOR_DISABLED);

// ---
    ADDC(GLFW_CONNECTED);
    ADDC(GLFW_DISCONNECTED);
#undef ADDC
// }}}

    return true;
}
