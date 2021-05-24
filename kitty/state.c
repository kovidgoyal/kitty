/*
 * state.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"
#include "cleanup.h"
#include <math.h>

GlobalState global_state = {{0}};

#define REMOVER(array, qid, count, destroy, capacity) { \
    for (size_t i = 0; i < count; i++) { \
        if (array[i].id == qid) { \
            destroy(array + i); \
            zero_at_i(array, i); \
            remove_i_from_array(array, i, count); \
            break; \
        } \
    }}

#define WITH_OS_WINDOW(os_window_id) \
    for (size_t o = 0; o < global_state.num_os_windows; o++) { \
        OSWindow *os_window = global_state.os_windows + o; \
        if (os_window->id == os_window_id) {
#define END_WITH_OS_WINDOW break; }}

#define WITH_TAB(os_window_id, tab_id) \
    for (size_t o = 0, tab_found = 0; o < global_state.num_os_windows && !tab_found; o++) { \
        OSWindow *osw = global_state.os_windows + o; \
        if (osw->id == os_window_id) { \
            for (size_t t = 0; t < osw->num_tabs; t++) { \
                if (osw->tabs[t].id == tab_id) { \
                    Tab *tab = osw->tabs + t;
#define END_WITH_TAB tab_found = 1; break; }}}}

#define WITH_WINDOW(os_window_id, tab_id, window_id) \
    for (size_t o = 0, window_found = 0; o < global_state.num_os_windows && !window_found; o++) { \
        OSWindow *osw = global_state.os_windows + o; \
        if (osw->id == os_window_id) { \
            for (size_t t = 0; t < osw->num_tabs && !window_found; t++) { \
                if (osw->tabs[t].id == tab_id) { \
                    Tab *tab = osw->tabs + t; \
                    for (size_t w = 0; w < tab->num_windows; w++) { \
                        if (tab->windows[w].id == window_id) { \
                            Window *window = tab->windows + w;
#define END_WITH_WINDOW window_found = 1; break; }}}}}}


#define WITH_OS_WINDOW_REFS \
    id_type cb_window_id = 0, focused_window_id = 0; \
    if (global_state.callback_os_window) cb_window_id = global_state.callback_os_window->id; \

#define END_WITH_OS_WINDOW_REFS \
    if (cb_window_id || focused_window_id) { \
        global_state.callback_os_window = NULL; \
        for (size_t wn = 0; wn < global_state.num_os_windows; wn++) { \
            OSWindow *wp = global_state.os_windows + wn; \
            if (wp->id == cb_window_id && cb_window_id) global_state.callback_os_window = wp; \
    }}

static inline double
dpi_for_os_window_id(id_type os_window_id) {
    double dpi = 0;
    if (os_window_id) {
        WITH_OS_WINDOW(os_window_id)
            dpi = (os_window->logical_dpi_x + os_window->logical_dpi_y) / 2.;
        END_WITH_OS_WINDOW
    }
    if (dpi == 0) {
        dpi = (global_state.default_dpi.x + global_state.default_dpi.y) / 2.;
    }
    return dpi;
}


static long
pt_to_px(double pt, id_type os_window_id) {
    const double dpi = dpi_for_os_window_id(os_window_id);
    return ((long)round((pt * (dpi / 72.0))));
}


OSWindow*
current_os_window() {
    if (global_state.callback_os_window) return global_state.callback_os_window;
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        if (global_state.os_windows[i].is_focused) return global_state.os_windows + i;
    }
    return global_state.os_windows;
}

OSWindow*
os_window_for_kitty_window(id_type kitty_window_id) {
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = global_state.os_windows + i;
        for (size_t t = 0; t < w->num_tabs; t++) {
            Tab *tab = w->tabs + t;
            for (size_t c = 0; c < tab->num_windows; c++) {
                if (tab->windows[c].id == kitty_window_id) return w;
            }
        }
    }
    return NULL;
}

Window*
window_for_window_id(id_type kitty_window_id) {
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = global_state.os_windows + i;
        for (size_t t = 0; t < w->num_tabs; t++) {
            Tab *tab = w->tabs + t;
            for (size_t c = 0; c < tab->num_windows; c++) {
                if (tab->windows[c].id == kitty_window_id) return tab->windows + c;
            }
        }
    }
    return NULL;
}

static void
send_bgimage_to_gpu(BackgroundImageLayout layout, BackgroundImage *bgimage) {
    RepeatStrategy r;
    switch (layout) {
        case SCALED:
            r = REPEAT_CLAMP; break;
        case MIRRORED:
            r = REPEAT_MIRROR; break;
        case TILING:
        default:
            r = REPEAT_DEFAULT; break;
    }
    bgimage->texture_id = 0;
    send_image_to_gpu(&bgimage->texture_id, bgimage->bitmap, bgimage->width,
            bgimage->height, false, true, OPT(background_image_linear), r);
    free(bgimage->bitmap); bgimage->bitmap = NULL;
}

static void
free_bgimage(BackgroundImage **bgimage, bool release_texture) {
    if (*bgimage && (*bgimage)->refcnt) {
        (*bgimage)->refcnt--;
        if ((*bgimage)->refcnt == 0) {
            free((*bgimage)->bitmap); (*bgimage)->bitmap = NULL;
            if (release_texture) free_texture(&(*bgimage)->texture_id);
            free(*bgimage);
        }
    }
    bgimage = NULL;
}

OSWindow*
add_os_window() {
    WITH_OS_WINDOW_REFS
    ensure_space_for(&global_state, os_windows, OSWindow, global_state.num_os_windows + 1, capacity, 1, true);
    OSWindow *ans = global_state.os_windows + global_state.num_os_windows++;
    zero_at_ptr(ans);
    ans->id = ++global_state.os_window_id_counter;
    ans->tab_bar_render_data.vao_idx = create_cell_vao();
    ans->gvao_idx = create_graphics_vao();
    ans->background_opacity = OPT(background_opacity);

    bool wants_bg = OPT(background_image) && OPT(background_image)[0] != 0;
    if (wants_bg) {
        if (!global_state.bgimage) {
            global_state.bgimage = calloc(1, sizeof(BackgroundImage));
            if (!global_state.bgimage) fatal("Out of memory allocating the global bg image object");
            global_state.bgimage->refcnt++;
            size_t size;
            if (png_path_to_bitmap(OPT(background_image), &global_state.bgimage->bitmap, &global_state.bgimage->width, &global_state.bgimage->height, &size)) {
                send_bgimage_to_gpu(OPT(background_image_layout), global_state.bgimage);
            }
        }
        if (global_state.bgimage->texture_id) {
            ans->bgimage = global_state.bgimage;
            ans->bgimage->refcnt++;
        }
    }

    ans->font_sz_in_pts = global_state.font_sz_in_pts;
    END_WITH_OS_WINDOW_REFS
    return ans;
}

static inline id_type
add_tab(id_type os_window_id) {
    WITH_OS_WINDOW(os_window_id)
        make_os_window_context_current(os_window);
        ensure_space_for(os_window, tabs, Tab, os_window->num_tabs + 1, capacity, 1, true);
        zero_at_i(os_window->tabs, os_window->num_tabs);
        os_window->tabs[os_window->num_tabs].id = ++global_state.tab_id_counter;
        os_window->tabs[os_window->num_tabs].border_rects.vao_idx = create_border_vao();
        return os_window->tabs[os_window->num_tabs++].id;
    END_WITH_OS_WINDOW
    return 0;
}

static inline void
create_gpu_resources_for_window(Window *w) {
    w->render_data.vao_idx = create_cell_vao();
    w->render_data.gvao_idx = create_graphics_vao();
}

static inline void
release_gpu_resources_for_window(Window *w) {
    if (w->render_data.vao_idx > -1) remove_vao(w->render_data.vao_idx);
    w->render_data.vao_idx = -1;
    if (w->render_data.gvao_idx > -1) remove_vao(w->render_data.gvao_idx);
    w->render_data.gvao_idx = -1;
}

static inline void
initialize_window(Window *w, PyObject *title, bool init_gpu_resources) {
    w->id = ++global_state.window_id_counter;
    w->visible = true;
    w->title = title;
    Py_XINCREF(title);
    if (init_gpu_resources) create_gpu_resources_for_window(w);
    else {
        w->render_data.vao_idx = -1;
        w->render_data.gvao_idx = -1;
    }
}

static inline id_type
add_window(id_type os_window_id, id_type tab_id, PyObject *title) {
    WITH_TAB(os_window_id, tab_id);
        ensure_space_for(tab, windows, Window, tab->num_windows + 1, capacity, 1, true);
        make_os_window_context_current(osw);
        zero_at_i(tab->windows, tab->num_windows);
        initialize_window(tab->windows + tab->num_windows, title, true);
        return tab->windows[tab->num_windows++].id;
    END_WITH_TAB;
    return 0;
}

static inline void
update_window_title(id_type os_window_id, id_type tab_id, id_type window_id, PyObject *title) {
    WITH_TAB(os_window_id, tab_id);
    for (size_t i = 0; i < tab->num_windows; i++) {
        if (tab->windows[i].id == window_id) {
            Py_CLEAR(tab->windows[i].title);
            tab->windows[i].title = title;
            Py_INCREF(tab->windows[i].title);
            break;
        }
    }
    END_WITH_TAB;
}

void
set_os_window_title_from_window(Window *w, OSWindow *os_window) {
    if (w->title && w->title != os_window->window_title) {
        Py_XDECREF(os_window->window_title);
        os_window->window_title = w->title;
        Py_INCREF(os_window->window_title);
        set_os_window_title(os_window, PyUnicode_AsUTF8(w->title));
    }
}

void
update_os_window_title(OSWindow *os_window) {
    if (os_window->num_tabs) {
        Tab *tab = os_window->tabs + os_window->active_tab;
        if (tab->num_windows) {
            Window *w = tab->windows + tab->active_window;
            set_os_window_title_from_window(w, os_window);
        }
    }
}

static inline void
destroy_window(Window *w) {
    Py_CLEAR(w->render_data.screen); Py_CLEAR(w->title);
    release_gpu_resources_for_window(w);
}

static inline void
remove_window_inner(Tab *tab, id_type id) {
    id_type active_window_id = 0;
    if (tab->active_window < tab->num_windows) active_window_id = tab->windows[tab->active_window].id;
    REMOVER(tab->windows, id, tab->num_windows, destroy_window, tab->capacity);
    if (active_window_id) {
        for (unsigned int w = 0; w < tab->num_windows; w++) {
            if (tab->windows[w].id == active_window_id) {
                tab->active_window = w; break;
            }
        }
    }
}

static inline void
remove_window(id_type os_window_id, id_type tab_id, id_type id) {
    WITH_TAB(os_window_id, tab_id);
        make_os_window_context_current(osw);
        remove_window_inner(tab, id);
    END_WITH_TAB;
}

typedef struct {
    unsigned int num_windows, capacity;
    Window *windows;
} DetachedWindows;

static DetachedWindows detached_windows = {0};


static void
add_detached_window(Window *w) {
    ensure_space_for(&detached_windows, windows, Window, detached_windows.num_windows + 1, capacity, 8, true);
    memcpy(detached_windows.windows + detached_windows.num_windows++, w, sizeof(Window));
}

static inline void
detach_window(id_type os_window_id, id_type tab_id, id_type id) {
    WITH_TAB(os_window_id, tab_id);
        for (size_t i = 0; i < tab->num_windows; i++) {
            if (tab->windows[i].id == id) {
                make_os_window_context_current(osw);
                release_gpu_resources_for_window(&tab->windows[i]);
                add_detached_window(tab->windows + i);
                zero_at_i(tab->windows, i);
                remove_i_from_array(tab->windows, i, tab->num_windows);
                break;
            }
        }
    END_WITH_TAB;
}


static inline void
resize_screen(OSWindow *os_window, Screen *screen, bool has_graphics) {
    if (screen) {
        screen->cell_size.width = os_window->fonts_data->cell_width;
        screen->cell_size.height = os_window->fonts_data->cell_height;
        screen_dirty_sprite_positions(screen);
        if (has_graphics) screen_rescale_images(screen);
    }
}

static inline void
attach_window(id_type os_window_id, id_type tab_id, id_type id) {
    WITH_TAB(os_window_id, tab_id);
        for (size_t i = 0; i < detached_windows.num_windows; i++) {
            if (detached_windows.windows[i].id == id) {
                ensure_space_for(tab, windows, Window, tab->num_windows + 1, capacity, 1, true);
                Window *w = tab->windows + tab->num_windows++;
                memcpy(w, detached_windows.windows + i, sizeof(Window));
                zero_at_i(detached_windows.windows, i);
                remove_i_from_array(detached_windows.windows, i, detached_windows.num_windows);
                make_os_window_context_current(osw);
                create_gpu_resources_for_window(w);
                if (
                    w->render_data.screen->cell_size.width != osw->fonts_data->cell_width ||
                    w->render_data.screen->cell_size.height != osw->fonts_data->cell_height
                ) resize_screen(osw, w->render_data.screen, true);
                else screen_dirty_sprite_positions(w->render_data.screen);
                w->render_data.screen->reload_all_gpu_data = true;
                break;
            }
        }
    END_WITH_TAB;
}

static inline void
destroy_tab(Tab *tab) {
    for (size_t i = tab->num_windows; i > 0; i--) remove_window_inner(tab, tab->windows[i - 1].id);
    remove_vao(tab->border_rects.vao_idx);
    free(tab->border_rects.rect_buf); tab->border_rects.rect_buf = NULL;
    free(tab->windows); tab->windows = NULL;
}

static inline void
remove_tab_inner(OSWindow *os_window, id_type id) {
    id_type active_tab_id = 0;
    if (os_window->active_tab < os_window->num_tabs) active_tab_id = os_window->tabs[os_window->active_tab].id;
    make_os_window_context_current(os_window);
    REMOVER(os_window->tabs, id, os_window->num_tabs, destroy_tab, os_window->capacity);
    if (active_tab_id) {
        for (unsigned int i = 0; i < os_window->num_tabs; i++) {
            if (os_window->tabs[i].id == active_tab_id) {
                os_window->active_tab = i; break;
            }
        }
    }
}

static inline void
remove_tab(id_type os_window_id, id_type id) {
    WITH_OS_WINDOW(os_window_id)
        remove_tab_inner(os_window, id);
    END_WITH_OS_WINDOW
}

static inline void
destroy_os_window_item(OSWindow *w) {
    for (size_t t = w->num_tabs; t > 0; t--) {
        Tab *tab = w->tabs + t - 1;
        remove_tab_inner(w, tab->id);
    }
    Py_CLEAR(w->window_title); Py_CLEAR(w->tab_bar_render_data.screen);
    if (w->offscreen_texture_id) free_texture(&w->offscreen_texture_id);
    if (w->offscreen_framebuffer) free_framebuffer(&w->offscreen_framebuffer);
    remove_vao(w->tab_bar_render_data.vao_idx);
    remove_vao(w->gvao_idx);
    free(w->tabs); w->tabs = NULL;
    free_bgimage(&w->bgimage, true);
    w->bgimage = NULL;
}

bool
remove_os_window(id_type os_window_id) {
    bool found = false;
    WITH_OS_WINDOW(os_window_id)
        found = true;
        make_os_window_context_current(os_window);
    END_WITH_OS_WINDOW
    if (found) {
        WITH_OS_WINDOW_REFS
            REMOVER(global_state.os_windows, os_window_id, global_state.num_os_windows, destroy_os_window_item, global_state.capacity);
        END_WITH_OS_WINDOW_REFS
        update_os_window_references();
    }
    return found;
}


static inline void
set_active_tab(id_type os_window_id, unsigned int idx) {
    WITH_OS_WINDOW(os_window_id)
        os_window->active_tab = idx;
        os_window->needs_render = true;
    END_WITH_OS_WINDOW
}

static inline void
set_active_window(id_type os_window_id, id_type tab_id, id_type window_id) {
    WITH_WINDOW(os_window_id, tab_id, window_id)
        (void)window;
        tab->active_window = w;
        osw->needs_render = true;
    END_WITH_WINDOW;
}

static inline void
swap_tabs(id_type os_window_id, unsigned int a, unsigned int b) {
    WITH_OS_WINDOW(os_window_id)
        Tab t = os_window->tabs[b];
        os_window->tabs[b] = os_window->tabs[a];
        os_window->tabs[a] = t;
    END_WITH_OS_WINDOW
}

static void
add_borders_rect(id_type os_window_id, id_type tab_id, uint32_t left, uint32_t top, uint32_t right, uint32_t bottom, uint32_t color) {
    WITH_TAB(os_window_id, tab_id)
        BorderRects *br = &tab->border_rects;
        br->is_dirty = true;
        if (!left && !top && !right && !bottom) { br->num_border_rects = 0; return; }
        ensure_space_for(br, rect_buf, BorderRect, br->num_border_rects + 1, capacity, 32, false);
        BorderRect *r = br->rect_buf + br->num_border_rects++;
        r->left = left; r->right = right; r->top = top; r->bottom = bottom; r->color = color;
    END_WITH_TAB
}


void
os_window_regions(OSWindow *os_window, Region *central, Region *tab_bar) {
    if (!global_state.tab_bar_hidden && os_window->num_tabs >= OPT(tab_bar_min_tabs)) {
        switch(OPT(tab_bar_edge)) {
            case TOP_EDGE:
                central->left = 0; central->top = os_window->fonts_data->cell_height; central->right = os_window->viewport_width - 1;
                central->bottom = os_window->viewport_height - 1;
                tab_bar->left = central->left; tab_bar->right = central->right; tab_bar->top = 0;
                tab_bar->bottom = central->top - 1;
                break;
            default:
                central->left = 0; central->top = 0; central->right = os_window->viewport_width - 1;
                central->bottom = os_window->viewport_height - os_window->fonts_data->cell_height - 1;
                tab_bar->left = central->left; tab_bar->right = central->right; tab_bar->top = central->bottom + 1;
                tab_bar->bottom = os_window->viewport_height - 1;
                break;
        }
    } else {
        zero_at_ptr(tab_bar);
        central->left = 0; central->top = 0; central->right = os_window->viewport_width - 1;
        central->bottom = os_window->viewport_height - 1;
    }
}

void
mark_os_window_for_close(OSWindow* w, CloseRequest cr) {
    global_state.has_pending_closes = true;
    w->close_request = cr;
}

static bool
owners_for_window_id(id_type window_id, OSWindow **os_window, Tab **tab) {
    if (os_window) *os_window = NULL;
    if (tab) *tab = NULL;
    for (size_t o = 0; o < global_state.num_os_windows; o++) {
        OSWindow *osw = global_state.os_windows + o;
        for (size_t t = 0; t < osw->num_tabs; t++) {
            Tab *qtab = osw->tabs + t;
            for (size_t w = 0; w < qtab->num_windows; w++) {
                Window *window = qtab->windows + w;
                if (window->id == window_id) {
                    if (os_window) *os_window = osw;
                    if (tab) *tab = qtab;
                    return true;
    }}}}
    return false;
}


bool
make_window_context_current(id_type window_id) {
    OSWindow *os_window;
    if (owners_for_window_id(window_id, &os_window, NULL)) {
        make_os_window_context_current(os_window);
        return true;
    }
    return false;
}

void
send_pending_click_to_window_id(id_type timer_id UNUSED, void *data) {
    id_type window_id = *((id_type*)data);
    for (size_t o = 0; o < global_state.num_os_windows; o++) {
        OSWindow *osw = global_state.os_windows + o;
        for (size_t t = 0; t < osw->num_tabs; t++) {
            Tab *qtab = osw->tabs + t;
            for (size_t w = 0; w < qtab->num_windows; w++) {
                Window *window = qtab->windows + w;
                if (window->id == window_id) {
                    send_pending_click_to_window(window, data);
                    return;
                }
            }
        }
    }
}


// Python API {{{
#define PYWRAP0(name) static PyObject* py##name(PYNOARG)
#define PYWRAP1(name) static PyObject* py##name(PyObject UNUSED *self, PyObject *args)
#define PA(fmt, ...) if(!PyArg_ParseTuple(args, fmt, __VA_ARGS__)) return NULL;
#define ONE_UINT(name) PYWRAP1(name) { name((unsigned int)PyLong_AsUnsignedLong(args)); Py_RETURN_NONE; }
#define TWO_UINT(name) PYWRAP1(name) { unsigned int a, b; PA("II", &a, &b); name(a, b); Py_RETURN_NONE; }
#define THREE_UINT(name) PYWRAP1(name) { unsigned int a, b, c; PA("III", &a, &b, &c); name(a, b, c); Py_RETURN_NONE; }
#define TWO_ID(name) PYWRAP1(name) { id_type a, b; PA("KK", &a, &b); name(a, b); Py_RETURN_NONE; }
#define THREE_ID(name) PYWRAP1(name) { id_type a, b, c; PA("KKK", &a, &b, &c); name(a, b, c); Py_RETURN_NONE; }
#define THREE_ID_OBJ(name) PYWRAP1(name) { id_type a, b, c; PyObject *o; PA("KKKO", &a, &b, &c, &o); name(a, b, c, o); Py_RETURN_NONE; }
#define KI(name) PYWRAP1(name) { id_type a; unsigned int b; PA("KI", &a, &b); name(a, b); Py_RETURN_NONE; }
#define KII(name) PYWRAP1(name) { id_type a; unsigned int b, c; PA("KII", &a, &b, &c); name(a, b, c); Py_RETURN_NONE; }
#define KKI(name) PYWRAP1(name) { id_type a, b; unsigned int c; PA("KKI", &a, &b, &c); name(a, b, c); Py_RETURN_NONE; }
#define KKK(name) PYWRAP1(name) { id_type a, b, c; PA("KKK", &a, &b, &c); name(a, b, c); Py_RETURN_NONE; }
#define KKII(name) PYWRAP1(name) { id_type a, b; unsigned int c, d; PA("KKII", &a, &b, &c, &d); name(a, b, c, d); Py_RETURN_NONE; }
#define KKKK(name) PYWRAP1(name) { id_type a, b, c, d; PA("KKKK", &a, &b, &c, &d); name(a, b, c, d); Py_RETURN_NONE; }
#define KK5I(name) PYWRAP1(name) { id_type a, b; unsigned int c, d, e, f, g; PA("KKIIIII", &a, &b, &c, &d, &e, &f, &g); name(a, b, c, d, e, f, g); Py_RETURN_NONE; }
#define BOOL_SET(name) PYWRAP1(set_##name) { global_state.name = PyObject_IsTrue(args); Py_RETURN_NONE; }

static color_type default_color = 0;

static inline color_type
color_as_int(PyObject *color) {
    if (color == Py_None && default_color) return default_color;
    if (!PyTuple_Check(color)) { PyErr_SetString(PyExc_TypeError, "Not a color tuple"); return 0; }
#define I(n, s) ((PyLong_AsUnsignedLong(PyTuple_GET_ITEM(color, n)) & 0xff) << s)
    return (I(0, 16) | I(1, 8) | I(2, 0)) & 0xffffff;
#undef I
}

static inline monotonic_t
parse_s_double_to_monotonic_t(PyObject *val) {
    return s_double_to_monotonic_t(PyFloat_AsDouble(val));
}

static inline monotonic_t
parse_ms_long_to_monotonic_t(PyObject *val) {
    return ms_to_monotonic_t(PyLong_AsUnsignedLong(val));
}

static int kitty_mod = 0;

static inline int
resolve_mods(int mods) {
    if (mods & GLFW_MOD_KITTY) {
        mods = (mods & ~GLFW_MOD_KITTY) | kitty_mod;
    }
    return mods;
}

static WindowTitleIn
window_title_in(PyObject *title_in) {
    const char *in = PyUnicode_AsUTF8(title_in);
    switch(in[0]) {
        case 'a': return ALL;
        case 'w': return WINDOW;
        case 'm': return MENUBAR;
        case 'n': return NONE;
        default: break;
    }
    return ALL;
}

static BackgroundImageLayout
bglayout(PyObject *layout_name) {
    const char *name = PyUnicode_AsUTF8(layout_name);
    switch(name[0]) {
        case 't': return TILING;
        case 'm': return MIRRORED;
        case 's': return SCALED;
        default: break;
    }
    return TILING;
}

static void
background_image(PyObject *src) {
    if (OPT(background_image)) free(OPT(background_image));
    OPT(background_image) = NULL;
    if (src == Py_None || !PyUnicode_Check(src)) return;
    Py_ssize_t sz;
    const char *s = PyUnicode_AsUTF8AndSize(src, &sz);
    OPT(background_image) = calloc(sz + 1, 1);
    if (OPT(background_image)) memcpy(OPT(background_image), s, sz);
}


static MouseShape
pointer_shape(PyObject *shape_name) {
    const char *name = PyUnicode_AsUTF8(shape_name);
    switch(name[0]) {
        case 'a': return ARROW;
        case 'h': return HAND;
        case 'b': return BEAM;
        default: break;
    }
    return BEAM;
}

static inline void
free_url_prefixes(void) {
    OPT(url_prefixes).num = 0;
    OPT(url_prefixes).max_prefix_len = 0;
    if (OPT(url_prefixes).values) {
        free(OPT(url_prefixes.values));
        OPT(url_prefixes).values = NULL;
    }
}

static void
set_url_prefixes(PyObject *up) {
    free_url_prefixes();
    OPT(url_prefixes).values = calloc(PyTuple_GET_SIZE(up), sizeof(UrlPrefix));
    if (!OPT(url_prefixes).values) { PyErr_NoMemory(); return; }
    OPT(url_prefixes).num = PyTuple_GET_SIZE(up);
    for (size_t i = 0; i < OPT(url_prefixes).num; i++) {
        PyObject *t = PyTuple_GET_ITEM(up, i);
        if (!PyUnicode_Check(t)) { PyErr_SetString(PyExc_TypeError, "url_prefixes must be strings"); return; }
        OPT(url_prefixes).values[i].len = MIN(arraysz(OPT(url_prefixes).values[i].string) - 1, (size_t)PyUnicode_GET_LENGTH(t));
        int kind = PyUnicode_KIND(t);
        OPT(url_prefixes).max_prefix_len = MAX(OPT(url_prefixes).max_prefix_len, OPT(url_prefixes).values[i].len);
        for (size_t x = 0; x < OPT(url_prefixes).values[i].len; x++) {
            OPT(url_prefixes).values[i].string[x] = PyUnicode_READ(kind, PyUnicode_DATA(t), x);
        }
    }
}

#define dict_iter(d) { \
    PyObject *key, *value; Py_ssize_t pos = 0; \
    while (PyDict_Next(d, &pos, &key, &value))

static inline float
PyFloat_AsFloat(PyObject *o) {
    return (float)PyFloat_AsDouble(o);
}

PYWRAP0(next_window_id) {
    return PyLong_FromUnsignedLongLong(global_state.window_id_counter + 1);
}

PYWRAP1(handle_for_window_id) {
    id_type os_window_id;
    PA("K", &os_window_id);
    WITH_OS_WINDOW(os_window_id)
        return PyLong_FromVoidPtr(os_window->handle);
    END_WITH_OS_WINDOW
    PyErr_SetString(PyExc_ValueError, "No such window");
    return NULL;
}

static PyObject* options_object = NULL;

PYWRAP0(get_options) {
    if (!options_object) {
        PyErr_SetString(PyExc_RuntimeError, "Must call set_options() before using get_options()");
        return NULL;
    }
    Py_INCREF(options_object);
    return options_object;
}

PYWRAP1(set_options) {
    PyObject *ret, *opts;
    int is_wayland = 0, debug_rendering = 0, debug_font_fallback = 0;
    PA("O|ppp", &opts, &is_wayland, &debug_rendering, &debug_font_fallback);
    if (opts == Py_None) {
        Py_CLEAR(options_object);
        Py_RETURN_NONE;
    }
    global_state.is_wayland = is_wayland ? true : false;
#ifdef __APPLE__
    global_state.has_render_frames = true;
#endif
    if (global_state.is_wayland) global_state.has_render_frames = true;
    global_state.debug_rendering = debug_rendering ? true : false;
    global_state.debug_font_fallback = debug_font_fallback ? true : false;
#define GA(name) ret = PyObject_GetAttrString(opts, #name); if (ret == NULL) return NULL;
#define SS(name, dest, convert) { GA(name); dest = convert(ret); Py_DECREF(ret); if (PyErr_Occurred()) return NULL; }
#define S(name, convert) SS(name, OPT(name), convert)
    SS(kitty_mod, kitty_mod, PyLong_AsLong);
    S(hide_window_decorations, PyLong_AsUnsignedLong);
    S(visual_bell_duration, parse_s_double_to_monotonic_t);
    S(enable_audio_bell, PyObject_IsTrue);
    S(focus_follows_mouse, PyObject_IsTrue);
    S(cursor_blink_interval, parse_s_double_to_monotonic_t);
    S(cursor_stop_blinking_after, parse_s_double_to_monotonic_t);
    S(background_opacity, PyFloat_AsFloat);
    S(background_image_layout, bglayout);
    S(background_tint, PyFloat_AsFloat);
    S(background_image_linear, PyObject_IsTrue);
    S(dim_opacity, PyFloat_AsFloat);
    S(dynamic_background_opacity, PyObject_IsTrue);
    S(inactive_text_alpha, PyFloat_AsFloat);
    S(scrollback_pager_history_size, PyLong_AsUnsignedLong);
    S(scrollback_fill_enlarged_window, PyObject_IsTrue);
    S(cursor_shape, PyLong_AsLong);
    S(cursor_beam_thickness, PyFloat_AsFloat);
    S(cursor_underline_thickness, PyFloat_AsFloat);
    S(url_style, PyLong_AsUnsignedLong);
    S(tab_bar_edge, PyLong_AsLong);
    S(mouse_hide_wait, parse_s_double_to_monotonic_t);
    S(wheel_scroll_multiplier, PyFloat_AsDouble);
    S(touch_scroll_multiplier, PyFloat_AsDouble);
    S(click_interval, parse_s_double_to_monotonic_t);
    S(resize_debounce_time, parse_s_double_to_monotonic_t);
    S(mark1_foreground, color_as_int);
    S(mark1_background, color_as_int);
    S(mark2_foreground, color_as_int);
    S(mark2_background, color_as_int);
    S(mark3_foreground, color_as_int);
    S(mark3_background, color_as_int);
    S(url_color, color_as_int);
    S(background, color_as_int);
    S(foreground, color_as_int);
    default_color = 0x00ff00;
    S(active_border_color, color_as_int);
    default_color = 0;
    S(inactive_border_color, color_as_int);
    S(bell_border_color, color_as_int);
    S(repaint_delay, parse_ms_long_to_monotonic_t);
    S(input_delay, parse_ms_long_to_monotonic_t);
    S(sync_to_monitor, PyObject_IsTrue);
    S(close_on_child_death, PyObject_IsTrue);
    S(window_alert_on_bell, PyObject_IsTrue);
    S(macos_option_as_alt, PyLong_AsUnsignedLong);
    S(macos_traditional_fullscreen, PyObject_IsTrue);
    S(macos_quit_when_last_window_closed, PyObject_IsTrue);
    S(macos_show_window_title_in, window_title_in);
    S(macos_window_resizable, PyObject_IsTrue);
    S(macos_hide_from_tasks, PyObject_IsTrue);
    S(macos_thicken_font, PyFloat_AsFloat);
    S(tab_bar_min_tabs, PyLong_AsUnsignedLong);
    S(disable_ligatures, PyLong_AsLong);
    S(force_ltr, PyObject_IsTrue);
    S(resize_draw_strategy, PyLong_AsLong);
    S(resize_in_steps, PyObject_IsTrue);
    S(allow_hyperlinks, PyObject_IsTrue);
    S(pointer_shape_when_grabbed, pointer_shape);
    S(default_pointer_shape, pointer_shape);
    S(pointer_shape_when_dragging, pointer_shape);
    S(detect_urls, PyObject_IsTrue);

    GA(tab_bar_style);
    global_state.tab_bar_hidden = PyUnicode_CompareWithASCIIString(ret, "hidden") == 0 ? true: false;
    Py_CLEAR(ret);
    if (PyErr_Occurred()) return NULL;

    PyObject *up = PyObject_GetAttrString(opts, "url_prefixes");
    if (up == NULL) return NULL;
    if (!PyTuple_Check(up)) { PyErr_SetString(PyExc_TypeError, "url_prefixes must be a tuple"); return NULL; }
    set_url_prefixes(up);
    Py_DECREF(up);
    if (PyErr_Occurred()) return NULL;

    PyObject *chars = PyObject_GetAttrString(opts, "select_by_word_characters");
    if (chars == NULL) return NULL;
    for (size_t i = 0; i < MIN((size_t)PyUnicode_GET_LENGTH(chars), sizeof(OPT(select_by_word_characters))/sizeof(OPT(select_by_word_characters[0]))); i++) {
        OPT(select_by_word_characters)[i] = PyUnicode_READ(PyUnicode_KIND(chars), PyUnicode_DATA(chars), i);
    }
    OPT(select_by_word_characters_count) = PyUnicode_GET_LENGTH(chars);
    Py_DECREF(chars);

    GA(keymap);
    Py_DECREF(ret); if (PyErr_Occurred()) return NULL;
    GA(sequence_map);
    Py_DECREF(ret); if (PyErr_Occurred()) return NULL;

    GA(background_image); background_image(ret); Py_CLEAR(ret);

#define read_adjust(name) { \
    PyObject *al = PyObject_GetAttrString(opts, #name); \
    if (PyFloat_Check(al)) { \
        OPT(name##_frac) = (float)PyFloat_AsDouble(al); \
        OPT(name##_px) = 0; \
    } else { \
        OPT(name##_frac) = 0; \
        OPT(name##_px) = (int)PyLong_AsLong(al); \
    } \
    Py_DECREF(al); \
}
    read_adjust(adjust_line_height);
    read_adjust(adjust_column_width);
#undef read_adjust
#undef S
#undef SS
    options_object = opts;
    Py_INCREF(options_object);
    Py_RETURN_NONE;
}

BOOL_SET(in_sequence_mode)

PYWRAP1(set_tab_bar_render_data) {
    ScreenRenderData d = {0};
    id_type os_window_id;
    PA("KffffO", &os_window_id, &d.xstart, &d.ystart, &d.dx, &d.dy, &d.screen);
    WITH_OS_WINDOW(os_window_id)
        Py_CLEAR(os_window->tab_bar_render_data.screen);
        d.vao_idx = os_window->tab_bar_render_data.vao_idx;
        os_window->tab_bar_render_data = d;
        Py_INCREF(os_window->tab_bar_render_data.screen);
    END_WITH_OS_WINDOW
    Py_RETURN_NONE;
}

static PyTypeObject RegionType;
static PyStructSequence_Field region_fields[] = {
    {"left", ""}, {"top", ""}, {"right", ""}, {"bottom", ""}, {"width", ""}, {"height", ""}, {NULL, NULL}
};
static PyStructSequence_Desc region_desc = {"Region", NULL, region_fields, 6};

static inline PyObject*
wrap_region(Region *r) {
    PyObject *ans = PyStructSequence_New(&RegionType);
    if (ans) {
        PyStructSequence_SET_ITEM(ans, 0, PyLong_FromUnsignedLong(r->left));
        PyStructSequence_SET_ITEM(ans, 1, PyLong_FromUnsignedLong(r->top));
        PyStructSequence_SET_ITEM(ans, 2, PyLong_FromUnsignedLong(r->right));
        PyStructSequence_SET_ITEM(ans, 3, PyLong_FromUnsignedLong(r->bottom));
        PyStructSequence_SET_ITEM(ans, 4, PyLong_FromUnsignedLong(r->right - r->left + 1));
        PyStructSequence_SET_ITEM(ans, 5, PyLong_FromUnsignedLong(r->bottom - r->top + 1));
    }
    return ans;
}

PYWRAP1(viewport_for_window) {
    id_type os_window_id;
    int vw = 100, vh = 100;
    unsigned int cell_width = 1, cell_height = 1;
    PA("K", &os_window_id);
    Region central = {0}, tab_bar = {0};
    WITH_OS_WINDOW(os_window_id)
        os_window_regions(os_window, &central, &tab_bar);
        vw = os_window->viewport_width; vh = os_window->viewport_height;
        cell_width = os_window->fonts_data->cell_width; cell_height = os_window->fonts_data->cell_height;
        goto end;
    END_WITH_OS_WINDOW
end:
    return Py_BuildValue("NNiiII", wrap_region(&central), wrap_region(&tab_bar), vw, vh, cell_width, cell_height);
}

PYWRAP1(cell_size_for_window) {
    id_type os_window_id;
    unsigned int cell_width = 0, cell_height = 0;
    PA("K", &os_window_id);
    WITH_OS_WINDOW(os_window_id)
        cell_width = os_window->fonts_data->cell_width; cell_height = os_window->fonts_data->cell_height;
        goto end;
    END_WITH_OS_WINDOW
end:
    return Py_BuildValue("II", cell_width, cell_height);
}


PYWRAP1(os_window_has_background_image) {
    id_type os_window_id;
    PA("K", &os_window_id);
    WITH_OS_WINDOW(os_window_id)
        if (os_window->bgimage && os_window->bgimage->texture_id > 0) { Py_RETURN_TRUE; }
    END_WITH_OS_WINDOW
    Py_RETURN_FALSE;
}

PYWRAP1(mark_os_window_for_close) {
    id_type os_window_id;
    CloseRequest cr = IMPERATIVE_CLOSE_REQUESTED;
    PA("K|i", &os_window_id, &cr);
    WITH_OS_WINDOW(os_window_id)
        mark_os_window_for_close(os_window, cr);
        Py_RETURN_TRUE;
    END_WITH_OS_WINDOW
    Py_RETURN_FALSE;
}

PYWRAP1(set_application_quit_request) {
    CloseRequest cr = IMPERATIVE_CLOSE_REQUESTED;
    PA("|i", &cr);
    global_state.quit_request = cr;
    global_state.has_pending_closes = true;
    request_tick_callback();
    Py_RETURN_NONE;
}

PYWRAP0(current_application_quit_request) {
    return Py_BuildValue("i", global_state.quit_request);
}

PYWRAP1(focus_os_window) {
    id_type os_window_id;
    int also_raise = 1;
    PA("K|p", &os_window_id, &also_raise);
    WITH_OS_WINDOW(os_window_id)
        if (!os_window->is_focused) focus_os_window(os_window, also_raise);
        Py_RETURN_TRUE;
    END_WITH_OS_WINDOW
    Py_RETURN_FALSE;
}

PYWRAP1(set_titlebar_color) {
    id_type os_window_id;
    unsigned int color;
    int use_system_color = 0;
    PA("KI|p", &os_window_id, &color, &use_system_color);
    WITH_OS_WINDOW(os_window_id)
        set_titlebar_color(os_window, color, use_system_color);
        Py_RETURN_TRUE;
    END_WITH_OS_WINDOW
    Py_RETURN_FALSE;
}

PYWRAP1(mark_tab_bar_dirty) {
    id_type os_window_id = PyLong_AsUnsignedLongLong(args);
    WITH_OS_WINDOW(os_window_id)
        os_window->tab_bar_data_updated = false;
    END_WITH_OS_WINDOW
    Py_RETURN_NONE;
}

PYWRAP1(change_background_opacity) {
    id_type os_window_id;
    float opacity;
    PA("Kf", &os_window_id, &opacity);
    WITH_OS_WINDOW(os_window_id)
        os_window->background_opacity = opacity;
        os_window->is_damaged = true;
        Py_RETURN_TRUE;
    END_WITH_OS_WINDOW
    Py_RETURN_FALSE;
}

PYWRAP1(background_opacity_of) {
    id_type os_window_id = PyLong_AsUnsignedLongLong(args);
    WITH_OS_WINDOW(os_window_id)
        return PyFloat_FromDouble((double)os_window->background_opacity);
    END_WITH_OS_WINDOW
    Py_RETURN_NONE;
}

PYWRAP1(set_window_padding) {
    id_type os_window_id, tab_id, window_id;
    unsigned int left, top, right, bottom;
    PA("KKKIIII", &os_window_id, &tab_id, &window_id, &left, &top, &right, &bottom);
    WITH_WINDOW(os_window_id, tab_id, window_id);
        window->padding.left = left; window->padding.top = top; window->padding.right = right; window->padding.bottom = bottom;
    END_WITH_WINDOW;
    Py_RETURN_NONE;
}

PYWRAP1(set_window_render_data) {
#define A(name) &(d.name)
#define B(name) &(g.name)
    id_type os_window_id, tab_id, window_id;
    ScreenRenderData d = {0};
    WindowGeometry g = {0};
    PA("KKKffffOIIII", &os_window_id, &tab_id, &window_id, A(xstart), A(ystart), A(dx), A(dy), A(screen), B(left), B(top), B(right), B(bottom));

    WITH_WINDOW(os_window_id, tab_id, window_id);
        Py_CLEAR(window->render_data.screen);
        d.vao_idx = window->render_data.vao_idx;
        d.gvao_idx = window->render_data.gvao_idx;
        window->render_data = d;
        window->geometry = g;
        Py_INCREF(window->render_data.screen);
    END_WITH_WINDOW;
    Py_RETURN_NONE;
#undef A
#undef B
}

PYWRAP1(update_window_visibility) {
    id_type os_window_id, tab_id, window_id;
    int visible;
    PA("KKKp", &os_window_id, &tab_id, &window_id, &visible);
    WITH_WINDOW(os_window_id, tab_id, window_id);
        bool was_visible = window->visible & 1;
        window->visible = visible & 1;
        if (!was_visible && window->visible) global_state.check_for_active_animated_images = true;
    END_WITH_WINDOW;
    Py_RETURN_NONE;
}


PYWRAP1(sync_os_window_title) {
    id_type os_window_id;
    PA("K", &os_window_id);
    WITH_OS_WINDOW(os_window_id)
        update_os_window_title(os_window);
    END_WITH_OS_WINDOW
    Py_RETURN_NONE;
}


PYWRAP1(pt_to_px) {
    double pt;
    id_type os_window_id = 0;
    PA("d|K", &pt, &os_window_id);
    return PyLong_FromLong(pt_to_px(pt, os_window_id));
}

PYWRAP1(global_font_size) {
    double set_val = -1;
    PA("|d", &set_val);
    if (set_val > 0) global_state.font_sz_in_pts = set_val;
    return Py_BuildValue("d", global_state.font_sz_in_pts);
}

PYWRAP1(os_window_font_size) {
    id_type os_window_id;
    int force = 0;
    double new_sz = -1;
    PA("K|dp", &os_window_id, &new_sz, &force);
    WITH_OS_WINDOW(os_window_id)
        if (new_sz > 0 && (force || new_sz != os_window->font_sz_in_pts)) {
            os_window->font_sz_in_pts = new_sz;
            os_window->fonts_data = NULL;
            os_window->fonts_data = load_fonts_data(os_window->font_sz_in_pts, os_window->logical_dpi_x, os_window->logical_dpi_y);
            send_prerendered_sprites_for_window(os_window);
            resize_screen(os_window, os_window->tab_bar_render_data.screen, false);
            for (size_t ti = 0; ti < os_window->num_tabs; ti++) {
                Tab *tab = os_window->tabs + ti;
                for (size_t wi = 0; wi < tab->num_windows; wi++) {
                    Window *w = tab->windows + wi;
                    resize_screen(os_window, w->render_data.screen, true);
                }
            }
            if (OPT(resize_in_steps)) os_window_update_size_increments(os_window);
        }
        return Py_BuildValue("d", os_window->font_sz_in_pts);
    END_WITH_OS_WINDOW
    return Py_BuildValue("d", 0.0);
}

PYWRAP1(set_boss) {
    Py_CLEAR(global_state.boss);
    global_state.boss = args;
    Py_INCREF(global_state.boss);
    Py_RETURN_NONE;
}

PYWRAP0(get_boss) {
    if (global_state.boss) {
        Py_INCREF(global_state.boss);
        return global_state.boss;
    }
    Py_RETURN_NONE;
}

PYWRAP1(patch_global_colors) {
    PyObject *spec;
    int configured;
    if (!PyArg_ParseTuple(args, "Op", &spec, &configured)) return NULL;
#define P(name) { \
    PyObject *val = PyDict_GetItemString(spec, #name); \
    if (val) { \
        OPT(name) = PyLong_AsLong(val); \
    } \
}
    P(active_border_color); P(inactive_border_color); P(bell_border_color);
    if (configured) {
        P(background); P(url_color);
        P(mark1_background); P(mark1_foreground); P(mark2_background); P(mark2_foreground);
        P(mark3_background); P(mark3_foreground);
    }
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
}

static PyObject*
pyset_background_image(PyObject *self UNUSED, PyObject *args) {
    const char *path;
    PyObject *layout_name = NULL;
    PyObject *os_window_ids;
    int configured = 0;
    PA("zO!|pU", &path, &PyTuple_Type, &os_window_ids, &configured, &layout_name);
    size_t size;
    BackgroundImageLayout layout = layout_name ? bglayout(layout_name) : OPT(background_image_layout);
    BackgroundImage *bgimage = NULL;
    if (path) {
        bgimage = calloc(1, sizeof(BackgroundImage));
        if (!bgimage) return PyErr_NoMemory();
        if (!png_path_to_bitmap(path, &bgimage->bitmap, &bgimage->width, &bgimage->height, &size)) {
            PyErr_Format(PyExc_ValueError, "Failed to load image from: %s", path);
            free(bgimage);
            return NULL;
        }
        send_bgimage_to_gpu(layout, bgimage);
        bgimage->refcnt++;
    }
    if (configured) {
        free_bgimage(&global_state.bgimage, true);
        global_state.bgimage = bgimage;
        if (bgimage) bgimage->refcnt++;
        OPT(background_image_layout) = layout;
    }
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(os_window_ids); i++) {
        id_type os_window_id = PyLong_AsUnsignedLongLong(PyTuple_GET_ITEM(os_window_ids, i));
        WITH_OS_WINDOW(os_window_id)
            make_os_window_context_current(os_window);
            free_bgimage(&os_window->bgimage, true);
            os_window->bgimage = bgimage;
            os_window->render_calls = 0;
            if (bgimage) bgimage->refcnt++;
        END_WITH_OS_WINDOW
    }
    if (bgimage) free_bgimage(&bgimage, true);
    Py_RETURN_NONE;
}

PYWRAP0(destroy_global_data) {
    Py_CLEAR(global_state.boss);
    free(global_state.os_windows); global_state.os_windows = NULL;
    Py_RETURN_NONE;
}

static void
destroy_mock_window(PyObject *capsule) {
    Window *w = PyCapsule_GetPointer(capsule, "Window");
    if (w) {
        destroy_window(w);
        PyMem_Free(w);
    }
}

static PyObject*
pycreate_mock_window(PyObject *self UNUSED, PyObject *args) {
    Screen *screen;
    PyObject *title = NULL;
    if (!PyArg_ParseTuple(args, "O|U", &screen, &title)) return NULL;
    Window *w = PyMem_Calloc(sizeof(Window), 1);
    if (!w) return NULL;
    Py_INCREF(screen);
    PyObject *ans = PyCapsule_New(w, "Window", destroy_mock_window);
    if (ans != NULL) {
        initialize_window(w, title, false);
        w->render_data.screen = screen;
    }
    return ans;
}

static inline void
click_mouse_url(id_type os_window_id, id_type tab_id, id_type window_id) {
    WITH_WINDOW(os_window_id, tab_id, window_id);
    mouse_open_url(window);
    END_WITH_WINDOW;
}

static PyObject*
pymouse_selection(PyObject *self UNUSED, PyObject *args) {
    id_type os_window_id, tab_id, window_id;
    int code, button;
    PA("KKKii", &os_window_id, &tab_id, &window_id, &code, &button);
    WITH_WINDOW(os_window_id, tab_id, window_id);
    mouse_selection(window, code, button);
    END_WITH_WINDOW;
    Py_RETURN_NONE;
}

THREE_ID_OBJ(update_window_title)
THREE_ID(remove_window)
THREE_ID(click_mouse_url)
THREE_ID(detach_window)
THREE_ID(attach_window)
PYWRAP1(resolve_key_mods) { int mods; PA("ii", &kitty_mod, &mods); return PyLong_FromLong(resolve_mods(mods)); }
PYWRAP1(add_tab) { return PyLong_FromUnsignedLongLong(add_tab(PyLong_AsUnsignedLongLong(args))); }
PYWRAP1(add_window) { PyObject *title; id_type a, b; PA("KKO", &a, &b, &title); return PyLong_FromUnsignedLongLong(add_window(a, b, title)); }
PYWRAP0(current_os_window) { OSWindow *w = current_os_window(); if (!w) Py_RETURN_NONE; return PyLong_FromUnsignedLongLong(w->id); }
TWO_ID(remove_tab)
KI(set_active_tab)
KKK(set_active_window)
KII(swap_tabs)
KK5I(add_borders_rect)

#define M(name, arg_type) {#name, (PyCFunction)name, arg_type, NULL}
#define MW(name, arg_type) {#name, (PyCFunction)py##name, arg_type, NULL}

static PyMethodDef module_methods[] = {
    MW(current_os_window, METH_NOARGS),
    MW(next_window_id, METH_NOARGS),
    MW(set_options, METH_VARARGS),
    MW(get_options, METH_NOARGS),
    MW(click_mouse_url, METH_VARARGS),
    MW(mouse_selection, METH_VARARGS),
    MW(set_in_sequence_mode, METH_O),
    MW(resolve_key_mods, METH_VARARGS),
    MW(handle_for_window_id, METH_VARARGS),
    MW(pt_to_px, METH_VARARGS),
    MW(add_tab, METH_O),
    MW(add_window, METH_VARARGS),
    MW(update_window_title, METH_VARARGS),
    MW(remove_tab, METH_VARARGS),
    MW(remove_window, METH_VARARGS),
    MW(detach_window, METH_VARARGS),
    MW(attach_window, METH_VARARGS),
    MW(set_active_tab, METH_VARARGS),
    MW(set_active_window, METH_VARARGS),
    MW(swap_tabs, METH_VARARGS),
    MW(add_borders_rect, METH_VARARGS),
    MW(set_tab_bar_render_data, METH_VARARGS),
    MW(set_window_render_data, METH_VARARGS),
    MW(set_window_padding, METH_VARARGS),
    MW(viewport_for_window, METH_VARARGS),
    MW(cell_size_for_window, METH_VARARGS),
    MW(os_window_has_background_image, METH_VARARGS),
    MW(mark_os_window_for_close, METH_VARARGS),
    MW(set_application_quit_request, METH_VARARGS),
    MW(current_application_quit_request, METH_NOARGS),
    MW(set_titlebar_color, METH_VARARGS),
    MW(focus_os_window, METH_VARARGS),
    MW(mark_tab_bar_dirty, METH_O),
    MW(change_background_opacity, METH_VARARGS),
    MW(background_opacity_of, METH_O),
    MW(update_window_visibility, METH_VARARGS),
    MW(sync_os_window_title, METH_VARARGS),
    MW(global_font_size, METH_VARARGS),
    MW(set_background_image, METH_VARARGS),
    MW(os_window_font_size, METH_VARARGS),
    MW(set_boss, METH_O),
    MW(get_boss, METH_NOARGS),
    MW(patch_global_colors, METH_VARARGS),
    MW(create_mock_window, METH_VARARGS),
    MW(destroy_global_data, METH_NOARGS),

    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static void
finalize(void) {
    while(detached_windows.num_windows--) {
        destroy_window(&detached_windows.windows[detached_windows.num_windows]);
    }
    if (detached_windows.windows) free(detached_windows.windows);
    detached_windows.capacity = 0;
    if (OPT(background_image)) free(OPT(background_image));
    // we leak the texture here since it is not guaranteed
    // that freeing the texture will work during shutdown and
    // the GPU driver should take care of it when the OpenGL context is
    // destroyed.
    free_bgimage(&global_state.bgimage, false);
    global_state.bgimage = NULL;
    free_url_prefixes();
}

bool
init_state(PyObject *module) {
    global_state.font_sz_in_pts = 11.0;
#ifdef __APPLE__
#define DPI 72.0
#else
#define DPI 96.0
#endif
    global_state.default_dpi.x = DPI; global_state.default_dpi.y = DPI;
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    if (PyStructSequence_InitType2(&RegionType, &region_desc) != 0) return false;
    Py_INCREF((PyObject *) &RegionType);
    PyModule_AddObject(module, "Region", (PyObject *) &RegionType);
    PyModule_AddIntConstant(module, "IMPERATIVE_CLOSE_REQUESTED", IMPERATIVE_CLOSE_REQUESTED);
    PyModule_AddIntConstant(module, "NO_CLOSE_REQUESTED", NO_CLOSE_REQUESTED);
    PyModule_AddIntConstant(module, "CLOSE_BEING_CONFIRMED", CLOSE_BEING_CONFIRMED);
    register_at_exit_cleanup_func(STATE_CLEANUP_FUNC, finalize);
    return true;
}
// }}}
