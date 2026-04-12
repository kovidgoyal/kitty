/*
 * state.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "cleanup.h"
#include "dnd.h"
#include "options/to-c-generated.h"
#include <math.h>
#include <sys/mman.h>

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

static double
dpi_for_os_window(const OSWindow *os_window) {
    double dpi = (os_window->fonts_data->logical_dpi_x + os_window->fonts_data->logical_dpi_y) / 2.;
    if (dpi == 0) dpi = (global_state.default_dpi.x + global_state.default_dpi.y) / 2.;
    return dpi;
}

static double
dpi_for_os_window_id(id_type os_window_id) {
    double dpi = 0;
    if (os_window_id) {
        WITH_OS_WINDOW(os_window_id)
            dpi = dpi_for_os_window(os_window);
        END_WITH_OS_WINDOW
    }
    if (dpi == 0) {
        dpi = (global_state.default_dpi.x + global_state.default_dpi.y) / 2.;
    }
    return dpi;
}

static long
pt_to_px_for_os_window(double pt, const OSWindow *w) {
    const double dpi = dpi_for_os_window(w);
    return ((long)round((pt * (dpi / 72.0))));
}

static long
pt_to_px(double pt, id_type os_window_id) {
    const double dpi = dpi_for_os_window_id(os_window_id);
    return ((long)round((pt * (dpi / 72.0))));
}


OSWindow*
current_os_window(void) {
    if (global_state.callback_os_window) return global_state.callback_os_window;
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        if (global_state.os_windows[i].is_focused) return global_state.os_windows + i;
    }
    return global_state.os_windows;
}

static id_type
last_focused_os_window_id(void) {
    id_type ans = 0, max_fc_count = 0;
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = &global_state.os_windows[i];
        if (w->last_focused_counter > max_fc_count) {
            ans = w->id; max_fc_count = w->last_focused_counter;
        }
    }
    return ans;
}

static id_type
current_focused_os_window_id(void) {
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = &global_state.os_windows[i];
        if (w->is_focused) { return w->id; }
    }
    return 0;
}


OSWindow*
os_window_for_id(id_type os_window_id) {
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = global_state.os_windows + i;
        if (w->id == os_window_id) return w;
    }
    return NULL;
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
free_bgimage_bitmap(BackgroundImage *bgimage) {
    if (!bgimage->bitmap) return;
    if (bgimage->mmap_size) {
        if (munmap(bgimage->bitmap, bgimage->mmap_size) != 0) log_error("Failed to unmap BackgroundImage with error: %s", strerror(errno));
    } else free(bgimage->bitmap);
    bgimage->bitmap = NULL;
    bgimage->mmap_size = 0;
}

static bool
send_bgimage_to_gpu(BackgroundImageLayout layout, BackgroundImage *bgimage) {
    RepeatStrategy r = REPEAT_DEFAULT;
    switch (layout) {
        case SCALED:
        case CLAMPED:
        case CENTER_CLAMPED:
        case CENTER_SCALED:
            r = REPEAT_CLAMP; break;
        case MIRRORED:
            r = REPEAT_MIRROR; break;
        case TILING:
            r = REPEAT_DEFAULT; break;
    }
    bgimage->texture_id = 0;
    size_t delta = bgimage->mmap_size ? bgimage->mmap_size - ((size_t)4) * bgimage->width * bgimage->height : 0;
    send_image_to_gpu(&bgimage->texture_id, bgimage->bitmap + delta, bgimage->width,
            bgimage->height, false, true, OPT(background_image_linear), r);
    free_bgimage_bitmap(bgimage);
    return bgimage->texture_id > 0;
}

static void
free_bgimage(BackgroundImage **bgimage, bool release_texture) {
    if (*bgimage && (*bgimage)->refcnt) {
        (*bgimage)->refcnt--;
        if ((*bgimage)->refcnt == 0) {
            free_bgimage_bitmap(*bgimage);
            if (release_texture) free_texture(&(*bgimage)->texture_id);
            free(*bgimage);
        }
    }
    *bgimage = NULL;
}

static void
free_global_background_images(bool release_texture) {
    if (global_state.background_images.images) {
        for (size_t i = 0; i < global_state.background_images.count; i++)
            free_bgimage(&global_state.background_images.images[i], release_texture);
        free(global_state.background_images.images);
        global_state.background_images.images = NULL;
    }
    zero_at_ptr(&global_state.background_images);
}

static void
ensure_background_images_generation(bool release_texture) {
    if (global_state.background_images.generation == OPT(background_images).generation) return;
    free_global_background_images(release_texture);
    global_state.background_images.generation = OPT(background_images).generation;
    global_state.background_images.entries_attempted = 0;
    if (OPT(background_images).count) {
        global_state.background_images.images = calloc(
                OPT(background_images).count, sizeof(global_state.background_images.images[0]));
        if (!global_state.background_images.images) fatal("Out of memory");
    }
}

static unsigned bg_image_id_counter = 0;

static BackgroundImage*
global_background_image(size_t idx) {
    ensure_background_images_generation(true);
    while (global_state.background_images.count <= idx && global_state.background_images.entries_attempted < OPT(background_images).count) {
        size_t j = global_state.background_images.entries_attempted++;
        BackgroundImage *img = calloc(1, sizeof(BackgroundImage));
        if (!img) fatal("Out of memory");
        if (image_path_to_bitmap(OPT(background_images).paths[j], &img->bitmap, &img->width, &img->height, &img->mmap_size)) {
            if (send_bgimage_to_gpu(OPT(background_image_layout), img)) {
                img->refcnt++;
                img->id = ++bg_image_id_counter;
                global_state.background_images.images[global_state.background_images.count++] = img;
            } else free(img);
        } else free(img);
    }
    return global_state.background_images.count > idx ? global_state.background_images.images[idx] : NULL;
}

BackgroundImage*
background_image_for_os_window(OSWindow *w) {
    if (w->background_image.no_image) return NULL;
    if (w->background_image.override) return w->background_image.override;
    BackgroundImage *ans = NULL;
    if (w->background_image.global_bg_images_idx && (
        ans = global_background_image(w->background_image.global_bg_images_idx))) return ans;
    return global_background_image(0);
}

static size_t
increment_bg_image_idx(size_t idx, int delta) {
    if (delta == 0) return idx;
    if (delta > 0) {
        size_t new_idx = idx + delta;
        return global_background_image(new_idx) ? new_idx : 0;
    }
    if ((unsigned)abs(delta) <= idx) return idx + delta;
    // wrap to last image, which means we need to load all
    if (OPT(background_images).count > 0) global_background_image(OPT(background_images).count - 1);
    return global_state.background_images.count ? global_state.background_images.count - 1 : 0;
}

OSWindow*
add_os_window(void) {
    WITH_OS_WINDOW_REFS
    ensure_space_for(&global_state, os_windows, OSWindow, global_state.num_os_windows + 1, capacity, 1, true);
    OSWindow *ans = global_state.os_windows + global_state.num_os_windows++;
    zero_at_ptr(ans);
    ans->id = ++global_state.os_window_id_counter;
    ans->tab_bar_render_data.vao_idx = create_cell_vao();
    ans->background_opacity.alpha = OPT(background_opacity);
    ans->created_at = monotonic();
    END_WITH_OS_WINDOW_REFS
    return ans;
}

static id_type
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

static void
create_gpu_resources_for_window(Window *w) {
    w->render_data.vao_idx = create_cell_vao();
    w->window_title_render_data.vao_idx = create_cell_vao();
}

static void
release_gpu_resources_for_window(Window *w) {
    if (w->render_data.vao_idx > -1) remove_vao(w->render_data.vao_idx);
    w->render_data.vao_idx = -1;
    if (w->window_title_render_data.vao_idx > -1) remove_vao(w->window_title_render_data.vao_idx);
    w->window_title_render_data.vao_idx = -1;
    Py_CLEAR(w->window_title_render_data.screen);
}

static bool
set_window_logo(Window *w, const char *path, const ImageAnchorPosition pos, float alpha, bool is_default, char *png_data, size_t png_data_size) {
    bool ok = false;
    if (path && path[0]) {
        window_logo_id_t wl = find_or_create_window_logo(global_state.all_window_logos, path, png_data, png_data_size);
        if (wl) {
            if (w->window_logo.id) decref_window_logo(global_state.all_window_logos, w->window_logo.id);
            w->window_logo.id = wl;
            w->window_logo.position = pos;
            w->window_logo.alpha = alpha;
            ok = true;
        }
    } else {
        if (w->window_logo.id) {
            decref_window_logo(global_state.all_window_logos, w->window_logo.id);
            w->window_logo.id = 0;
        }
        ok = true;
    }
    w->window_logo.using_default = is_default;
    if (ok && w->render_data.screen) w->render_data.screen->is_dirty = true;
    return ok;
}

static void
initialize_window(Window *w, PyObject *title, bool init_gpu_resources) {
    w->id = ++global_state.window_id_counter;
    w->visible = true;
    w->title = title;
    Py_XINCREF(title);
    w->scrollbar.is_hovering = false;
    if (!set_window_logo(w, OPT(default_window_logo), OPT(window_logo_position), OPT(window_logo_alpha), true, NULL, 0)) {
        log_error("Failed to load default window logo: %s", OPT(default_window_logo));
        if (PyErr_Occurred()) PyErr_Print();
    }
    if (init_gpu_resources) create_gpu_resources_for_window(w);
    else {
        w->render_data.vao_idx = -1;
    }
}

static id_type
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

static void
update_window_title(id_type os_window_id, id_type tab_id, id_type window_id, PyObject *title) {
    WITH_WINDOW(os_window_id, tab_id, window_id)
        Py_CLEAR(window->title);
        if (title) window->title = Py_NewRef(title);
    END_WITH_WINDOW;
}

void
set_os_window_title_from_window(Window *w, OSWindow *os_window) {
    if (os_window->disallow_title_changes || os_window->title_is_overriden) return;
    if (w->title && w->title != os_window->window_title) {
        Py_CLEAR(os_window->window_title);
        os_window->window_title = Py_NewRef(w->title);
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

static void
destroy_window(Window *w) {
    drop_free_data(w);
    drag_free_offer(w);
    free(w->pending_clicks.clicks); zero_at_ptr(&w->pending_clicks);
    free(w->buffered_keys.key_data); zero_at_ptr(&w->buffered_keys);
    Py_CLEAR(w->render_data.screen); Py_CLEAR(w->title);
    Py_CLEAR(w->title_bar_data.last_drawn_title_object_id);
    free(w->title_bar_data.buf); w->title_bar_data.buf = NULL;
    Py_CLEAR(w->url_target_bar_data.last_drawn_title_object_id);
    free(w->url_target_bar_data.buf); w->url_target_bar_data.buf = NULL;
    release_gpu_resources_for_window(w);
    if (w->window_logo.id) {
        decref_window_logo(global_state.all_window_logos, w->window_logo.id);
        w->window_logo.id = 0;
    }
}

static void
remove_window_inner(Tab *tab, id_type id) {
    id_type active_window_id = 0;
    if (tab->active_window < tab->num_windows) active_window_id = tab->windows[tab->active_window].id;
    REMOVER(tab->windows, id, tab->num_windows, destroy_window, tab->capacity);
    if (active_window_id) {
        for (unsigned int w = 0; w < tab->num_windows; w++) {
            if (tab->windows[w].id == active_window_id) {
                tab->active_window = w; return;
            }
        }
    }
    if (tab->active_window >= tab->num_windows) tab->active_window = 0;
}

static void
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

static void
detach_window(id_type os_window_id, id_type tab_id, id_type id) {
    WITH_TAB(os_window_id, tab_id);
        for (size_t i = 0; i < tab->num_windows; i++) {
            if (tab->windows[i].id == id) {
                make_os_window_context_current(osw);
                release_gpu_resources_for_window(&tab->windows[i]);
                add_detached_window(tab->windows + i);
                zero_at_i(tab->windows, i);
                remove_i_from_array(tab->windows, i, tab->num_windows);
                if (tab->active_window >= tab->num_windows) tab->active_window = tab->num_windows ? tab->num_windows - 1 : 0;
                break;
            }
        }
    END_WITH_TAB;
}


static void
resize_screen(OSWindow *os_window, Screen *screen, bool has_graphics) {
    if (screen) {
        screen->cell_size.width = os_window->fonts_data->fcm.cell_width;
        screen->cell_size.height = os_window->fonts_data->fcm.cell_height;
        screen_dirty_sprite_positions(screen);
        if (has_graphics) screen_rescale_images(screen);
    }
}

static void
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
                    w->render_data.screen->cell_size.width != osw->fonts_data->fcm.cell_width ||
                    w->render_data.screen->cell_size.height != osw->fonts_data->fcm.cell_height
                ) resize_screen(osw, w->render_data.screen, true);
                else screen_dirty_sprite_positions(w->render_data.screen);
                w->render_data.screen->reload_all_gpu_data = true;
                break;
            }
        }
    END_WITH_TAB;
}

static void
destroy_tab(Tab *tab) {
    for (size_t i = tab->num_windows; i > 0; i--) remove_window_inner(tab, tab->windows[i - 1].id);
    remove_vao(tab->border_rects.vao_idx);
    free(tab->border_rects.rect_buf); tab->border_rects.rect_buf = NULL;
    free(tab->windows); tab->windows = NULL;
}

static void
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

static void
remove_tab(id_type os_window_id, id_type id) {
    WITH_OS_WINDOW(os_window_id)
        remove_tab_inner(os_window, id);
    END_WITH_OS_WINDOW
}

static void
destroy_os_window_item(OSWindow *w) {
    for (size_t t = w->num_tabs; t > 0; t--) {
        Tab *tab = w->tabs + t - 1;
        remove_tab_inner(w, tab->id);
    }
    Py_CLEAR(w->window_title); Py_CLEAR(w->tab_bar_render_data.screen);
    remove_vao(w->tab_bar_render_data.vao_idx);
    free(w->tabs); w->tabs = NULL;
    free_bgimage(&w->background_image.override, true);
    zero_at_ptr(&w->background_image);
    if (w->indirect_output.framebuffer_id) free_framebuffer(&w->indirect_output.framebuffer_id);
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
        if (global_state.num_os_windows == 0) {
            if (global_state.layers_render_texture.texture_id) free_texture(&global_state.layers_render_texture.texture_id);
            if (global_state.layers_render_texture.framebuffer_id) free_framebuffer(&global_state.layers_render_texture.framebuffer_id);
            global_state.layers_render_texture.width = 0; global_state.layers_render_texture.height = 0;
        }
    }
    return found;
}

static void
mark_os_window_dirty(id_type os_window_id) {
    WITH_OS_WINDOW(os_window_id)
        os_window->needs_render = true;
    END_WITH_OS_WINDOW
}

static void
set_active_tab(id_type os_window_id, unsigned int idx) {
    WITH_OS_WINDOW(os_window_id)
        os_window->active_tab = idx;
        os_window->needs_render = true;
    END_WITH_OS_WINDOW
}

static void
set_active_window(id_type os_window_id, id_type tab_id, id_type window_id) {
    WITH_TAB(os_window_id, tab_id)
        tab->active_window = 0;
        for (unsigned w = 0; w < tab->num_windows; w++) {
            if (tab->windows[w].id == window_id) {
                tab->active_window = w; break;
            }
        }
        osw->needs_render = true;
        set_os_window_chrome(osw);
    END_WITH_TAB;
}

static bool
buffer_keys_in_window(id_type os_window_id, id_type tab_id, id_type window_id, bool enable) {
    WITH_WINDOW(os_window_id, tab_id, window_id)
        window->buffered_keys.enabled = enable;
        if (!enable) dispatch_buffered_keys(window);
        return true;
    END_WITH_WINDOW;
    return false;
}

static bool
set_redirect_keys_to_overlay(id_type os_window_id, id_type tab_id, id_type window_id, id_type overlay_id) {
    WITH_WINDOW(os_window_id, tab_id, window_id)
        window->redirect_keys_to_overlay = overlay_id;
        return true;
    END_WITH_WINDOW;
    return false;
}


static void
swap_tabs(id_type os_window_id, unsigned int a, unsigned int b) {
    WITH_OS_WINDOW(os_window_id)
        Tab t = os_window->tabs[b];
        os_window->tabs[b] = os_window->tabs[a];
        os_window->tabs[a] = t;
    END_WITH_OS_WINDOW
}

static PyObject*
pyreorder_tabs(PyObject *self UNUSED, PyObject *args) {
    if (PyTuple_GET_SIZE(args) < 2) Py_RETURN_NONE;
    id_type os_window_id = PyLong_AsUnsignedLongLong(PyTuple_GET_ITEM(args, 0));
    WITH_OS_WINDOW(os_window_id)
        if (PyTuple_GET_SIZE(args) != (Py_ssize_t)(os_window->num_tabs + 1)) { PyErr_SetString(PyExc_ValueError, "number of tabs not correct"); return NULL; }
        if (!os_window->num_tabs) Py_RETURN_NONE;
        RAII_ALLOC(Tab, tabs, calloc(os_window->capacity, sizeof(Tab)));
        RAII_ALLOC(char, used, calloc(os_window->num_tabs, sizeof(char)));
        if (!tabs || !used) { return PyErr_NoMemory(); }
        for (Py_ssize_t i = 1; i < PyTuple_GET_SIZE(args); i++) {
            id_type tab_id = PyLong_AsUnsignedLongLong(PyTuple_GET_ITEM(args, i));
            bool found = false;
            for (size_t t = 0; t < os_window->num_tabs; t++) {
                if (os_window->tabs[t].id == tab_id) {
                    tabs[i-1] = os_window->tabs[t];
                    found = true;
                    if (used[t]) {
                        PyErr_SetString(PyExc_ValueError, "duplicate tab ids found"); return NULL;
                    }
                    used[t] = 1;
                    break;
                }
            }
            if (!found) { PyErr_SetString(PyExc_ValueError, "tab id not found"); return NULL; }
        }
        free(os_window->tabs); os_window->tabs = tabs; tabs = NULL;
    END_WITH_OS_WINDOW
    Py_RETURN_NONE;
}

static PyObject*
pyset_borders_rects(PyObject *self UNUSED, PyObject *args) {
    id_type os_window_id, tab_id;
    PyObject *rects;
    if (!PyArg_ParseTuple(args, "KKO!", &os_window_id, &tab_id, &PyList_Type, &rects)) return NULL;
    WITH_TAB(os_window_id, tab_id)
        BorderRects *br = &tab->border_rects;
        br->is_dirty = true;
        br->num_border_rects = PyList_GET_SIZE(rects);
        ensure_space_for(br, rect_buf, BorderRect, br->num_border_rects + 1, capacity, 32, false);
        for (unsigned i = 0; i < br->num_border_rects; i++) {
            PyObject *pr = PyList_GET_ITEM(rects, i);
            unsigned long color; long long border_type;
            BorderRect *r = br->rect_buf + i;
            int horizontal;
            if (!PyArg_ParseTuple(
                pr, "IIIIkLp", &r->px.left, &r->px.top, &r->px.right, &r->px.bottom, &color, &border_type, &horizontal
            )) return NULL;
            r->left = gl_pos_x(r->px.left, osw->viewport_width);
            r->top = gl_pos_y(r->px.top, osw->viewport_height);
            r->right = r->left + gl_size(r->px.right - r->px.left, osw->viewport_width);
            r->bottom = r->top - gl_size(r->px.bottom - r->px.top, osw->viewport_height);
            r->color = color; r->border_type = border_type; r->horizontal = horizontal;
        }
    END_WITH_TAB
    Py_RETURN_NONE;
}


static unsigned
vertical_tab_bar_cols(const OSWindow *os_window, long margin_outer, long margin_inner) {
    unsigned cell_width = MAX(1u, os_window->fonts_data->fcm.cell_width);
    long available_width = (long)os_window->viewport_width - margin_outer - margin_inner;
    if (available_width <= 0) return 0;
    unsigned available_cols = MAX(1u, (unsigned)available_width / cell_width);
    unsigned title_cols = OPT(tab_title_max_length) > 0 ? (unsigned)OPT(tab_title_max_length) : 20u;
    unsigned desired_cols = title_cols + 8u;
    unsigned soft_max = available_cols / 3u;
    if (soft_max < 6u) soft_max = available_cols;
    return MAX(1u, MIN(available_cols, MIN(desired_cols, MAX(1u, soft_max))));
}

void
os_window_regions(const OSWindow *os_window, Region *central, Region *tab_bar) {
    if (!OPT(tab_bar_hidden) && os_window->num_tabs && !os_window->has_too_few_tabs) {
        long margin_outer = pt_to_px_for_os_window(OPT(tab_bar_margin_height.outer), os_window);
        long margin_inner = pt_to_px_for_os_window(OPT(tab_bar_margin_height.inner), os_window);
        central->left = 0; central->right = os_window->viewport_width;
        central->top = 0; central->bottom = os_window->viewport_height;
        switch(OPT(tab_bar_edge)) {
            case TOP_EDGE: {
                unsigned tab_bar_height = os_window->fonts_data->fcm.cell_height + margin_inner + margin_outer;
                central->top = tab_bar_height;
                central->bottom = os_window->viewport_height;
                central->top = MIN(central->top, central->bottom);
                tab_bar->top = margin_outer;
                tab_bar->left = central->left; tab_bar->right = central->right;
                tab_bar->bottom = tab_bar->top + os_window->fonts_data->fcm.cell_height;
                break;
            }
            case LEFT_EDGE: {
                unsigned left_cols = vertical_tab_bar_cols(os_window, margin_outer, margin_inner);
                if (!left_cols) {
                    zero_at_ptr(tab_bar);
                    return;
                }
                unsigned left_width = left_cols * os_window->fonts_data->fcm.cell_width;
                central->left = MIN((long)(left_width + margin_inner + margin_outer), (long)central->right);
                tab_bar->left = margin_outer;
                tab_bar->right = tab_bar->left + left_width;
                tab_bar->top = central->top;
                tab_bar->bottom = central->bottom;
                break;
            }
            case RIGHT_EDGE: {
                unsigned right_cols = vertical_tab_bar_cols(os_window, margin_outer, margin_inner);
                if (!right_cols) {
                    zero_at_ptr(tab_bar);
                    return;
                }
                unsigned right_width = right_cols * os_window->fonts_data->fcm.cell_width;
                central->right = MAX(0, (long)os_window->viewport_width - (long)(right_width + margin_inner + margin_outer));
                tab_bar->left = central->right + margin_inner;
                tab_bar->right = tab_bar->left + right_width;
                tab_bar->top = central->top;
                tab_bar->bottom = central->bottom;
                break;
            }
            default: {
                unsigned tab_bar_height = os_window->fonts_data->fcm.cell_height + margin_inner + margin_outer;
                central->top = 0;
                long bottom = os_window->viewport_height - tab_bar_height;
                central->bottom = MAX(0, bottom);
                tab_bar->top = central->bottom + margin_inner;
                tab_bar->left = central->left; tab_bar->right = central->right;
                tab_bar->bottom = tab_bar->top + os_window->fonts_data->fcm.cell_height;
                break;
            }
        }
    } else {
        zero_at_ptr(tab_bar);
        central->left = 0; central->top = 0; central->right = os_window->viewport_width;
        central->bottom = os_window->viewport_height;
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
    if (owners_for_window_id(window_id, &os_window, NULL) && os_window->handle) {
        make_os_window_context_current(os_window);
        return true;
    }
    return false;
}

void
dispatch_pending_clicks(id_type timer_id UNUSED, void *data UNUSED) {
    bool dispatched = false;
    do {  // dispatching a click can cause windows/tabs/etc to close so do it one at a time.
        const monotonic_t now = monotonic();
        dispatched = false;
        for (size_t o = 0; o < global_state.num_os_windows && !dispatched; o++) {
            OSWindow *osw = global_state.os_windows + o;
            for (size_t t = 0; t < osw->num_tabs && !dispatched; t++) {
                Tab *qtab = osw->tabs + t;
                for (size_t w = 0; w < qtab->num_windows && !dispatched; w++) {
                    Window *window = qtab->windows + w;
                    for (size_t i = 0; i < window->pending_clicks.num && !dispatched; i++) {
                        if (now - window->pending_clicks.clicks[i].at >= OPT(click_interval)) {
                            dispatched = true;
                            send_pending_click_to_window(window, i);
                        }
                    }
                }
            }
        }
    } while (dispatched);
}

bool
update_ime_position_for_window(id_type window_id, bool force, int update_focus) {
    for (size_t o = 0; o < global_state.num_os_windows; o++) {
        OSWindow *osw = global_state.os_windows + o;
        for (size_t t = 0; t < osw->num_tabs; t++) {
            Tab *qtab = osw->tabs + t;
            for (size_t w = 0; w < qtab->num_windows; w++) {
                Window *window = qtab->windows + w;
                if (window->id == window_id) {
                    // The screen may not be ready after the new window is created and focused, and still needs to enable IME.
                    if ((window->render_data.screen && (force || osw->is_focused)) || update_focus > 0) {
                        OSWindow *orig = global_state.callback_os_window;
                        global_state.callback_os_window = osw;
                        if (update_focus) update_ime_focus(osw, update_focus > 0);
                        if (update_focus >= 0 && window->render_data.screen) {
                            update_ime_position(window, window->render_data.screen);
                        }
                        global_state.callback_os_window = orig;
                        return true;
                    }
                    return false;
                }
            }
        }
    }
    return false;
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
#define K(name) PYWRAP1(name) { id_type a; PA("K", &a); name(a); Py_RETURN_NONE; }
#define KI(name) PYWRAP1(name) { id_type a; unsigned int b; PA("KI", &a, &b); name(a, b); Py_RETURN_NONE; }
#define KII(name) PYWRAP1(name) { id_type a; unsigned int b, c; PA("KII", &a, &b, &c); name(a, b, c); Py_RETURN_NONE; }
#define KKI(name) PYWRAP1(name) { id_type a, b; unsigned int c; PA("KKI", &a, &b, &c); name(a, b, c); Py_RETURN_NONE; }
#define KKK(name) PYWRAP1(name) { id_type a, b, c; PA("KKK", &a, &b, &c); name(a, b, c); Py_RETURN_NONE; }
#define KKII(name) PYWRAP1(name) { id_type a, b; unsigned int c, d; PA("KKII", &a, &b, &c, &d); name(a, b, c, d); Py_RETURN_NONE; }
#define KKKK(name) PYWRAP1(name) { id_type a, b, c, d; PA("KKKK", &a, &b, &c, &d); name(a, b, c, d); Py_RETURN_NONE; }
#define KK5I(name) PYWRAP1(name) { id_type a, b; unsigned int c, d, e, f, g; PA("KKIIIII", &a, &b, &c, &d, &e, &f, &g); name(a, b, c, d, e, f, g); Py_RETURN_NONE; }
#define BOOL_SET(name) PYWRAP1(set_##name) { global_state.name = PyObject_IsTrue(args); Py_RETURN_NONE; }
#define dict_iter(d) { \
    PyObject *key, *value; Py_ssize_t pos = 0; \
    while (PyDict_Next(d, &pos, &key, &value))

PYWRAP1(update_ime_position_for_window) {
    id_type window_id;
    int force = 0;
    int update_focus = 0;
    PA("K|pi", &window_id, &force, &update_focus);
    if (update_ime_position_for_window(window_id, force, update_focus)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

PYWRAP0(next_window_id) {
    return PyLong_FromUnsignedLongLong(global_state.window_id_counter + 1);
}

PYWRAP0(last_focused_os_window_id) {
    return PyLong_FromUnsignedLongLong(last_focused_os_window_id());
}

PYWRAP0(current_focused_os_window_id) {
    return PyLong_FromUnsignedLongLong(current_focused_os_window_id());
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


PYWRAP0(get_options) {
    if (!global_state.options_object) {
        PyErr_SetString(PyExc_RuntimeError, "Must call set_options() before using get_options()");
        return NULL;
    }
    Py_INCREF(global_state.options_object);
    return global_state.options_object;
}

PYWRAP1(set_options) {
    PyObject *opts;
    int is_wayland = 0, debug_rendering = 0, debug_font_fallback = 0;
    PA("O|ppp", &opts, &is_wayland, &debug_rendering, &debug_font_fallback);
    if (opts == Py_None) {
        Py_CLEAR(global_state.options_object);
        Py_RETURN_NONE;
    }
#ifdef __APPLE__
    global_state.is_apple = true;
    global_state.has_render_frames = true;
#endif
    global_state.is_wayland = is_wayland ? true : false;
    if (global_state.is_wayland) global_state.has_render_frames = true;
    global_state.debug_rendering = debug_rendering ? true : false;
    global_state.debug_font_fallback = debug_font_fallback ? true : false;
    if (!convert_opts_from_python_opts(opts, &global_state.opts)) return NULL;
    global_state.options_object = opts;
    Py_INCREF(global_state.options_object);
    Py_RETURN_NONE;
}

PYWRAP1(set_ignore_os_keyboard_processing) {
    set_ignore_os_keyboard_processing(PyObject_IsTrue(args));
    Py_RETURN_NONE;
}

static void
init_window_render_data(WindowRenderData *d, const WindowGeometry g, Screen *screen) {
    d->geometry = g;
    Py_CLEAR(d->screen); d->screen = (Screen*)Py_NewRef(screen);
}

PYWRAP1(set_tab_bar_render_data) {
    WindowGeometry g;
    id_type os_window_id;
    Screen *screen;
    PA("KOIIII", &os_window_id, &screen, &g.left, &g.top, &g.right, &g.bottom);
    WITH_OS_WINDOW(os_window_id)
        init_window_render_data(&os_window->tab_bar_render_data, g, screen);
    END_WITH_OS_WINDOW
    Py_RETURN_NONE;
}

PYWRAP1(set_window_drag_overlay) {
    id_type os_window_id, tab_id, window_id;
    int quadrant;
    PA("KKKi", &os_window_id, &tab_id, &window_id, &quadrant);
    WITH_WINDOW(os_window_id, tab_id, window_id)
        Screen *s = window->render_data.screen;
        if (s) {
            if (quadrant == 0) {
                s->start_drag_overlay_at = 0;
                s->drag_overlay_quadrant = 0;
            } else if (s->drag_overlay_quadrant != (uint8_t)quadrant) {
                s->start_drag_overlay_at = monotonic();
                s->drag_overlay_quadrant = (uint8_t)quadrant;
            }
        }
    END_WITH_WINDOW
    Py_RETURN_NONE;
}

PYWRAP1(set_window_title_bar_render_data) {
    WindowGeometry g = {0};
    id_type os_window_id, tab_id, window_id;
    Screen *screen;
    PA("KKKOIIII", &os_window_id, &tab_id, &window_id, &screen, &g.left, &g.top, &g.right, &g.bottom);
    WITH_WINDOW(os_window_id, tab_id, window_id)
        init_window_render_data(&window->window_title_render_data, g, screen);
        screen->reload_all_gpu_data = true;
    END_WITH_WINDOW
    Py_RETURN_NONE;
}

static PyTypeObject RegionType;
static PyStructSequence_Field region_fields[] = {
    {"left", ""}, {"top", ""}, {"right", ""}, {"bottom", ""}, {"width", ""}, {"height", ""}, {NULL, NULL}
};
static PyStructSequence_Desc region_desc = {"Region", NULL, region_fields, 6};

static PyObject*
wrap_region(Region *r) {
    PyObject *ans = PyStructSequence_New(&RegionType);
    if (ans) {
        PyStructSequence_SET_ITEM(ans, 0, PyLong_FromUnsignedLong(r->left));
        PyStructSequence_SET_ITEM(ans, 1, PyLong_FromUnsignedLong(r->top));
        PyStructSequence_SET_ITEM(ans, 2, PyLong_FromUnsignedLong(r->right));
        PyStructSequence_SET_ITEM(ans, 3, PyLong_FromUnsignedLong(r->bottom));
        PyStructSequence_SET_ITEM(ans, 4, PyLong_FromUnsignedLong(r->right - r->left));
        PyStructSequence_SET_ITEM(ans, 5, PyLong_FromUnsignedLong(r->bottom - r->top));
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
        cell_width = os_window->fonts_data->fcm.cell_width; cell_height = os_window->fonts_data->fcm.cell_height;
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
        cell_width = os_window->fonts_data->fcm.cell_width; cell_height = os_window->fonts_data->fcm.cell_height;
        goto end;
    END_WITH_OS_WINDOW
end:
    return Py_BuildValue("II", cell_width, cell_height);
}


PYWRAP1(os_window_has_background_image) {
    id_type os_window_id;
    PA("K", &os_window_id);
    WITH_OS_WINDOW(os_window_id)
        if (background_image_for_os_window(os_window) != NULL) Py_RETURN_TRUE;
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
    const char *activation_token = NULL;
    PA("K|pz", &os_window_id, &also_raise, &activation_token);
    WITH_OS_WINDOW(os_window_id)
        if (!os_window->is_focused || (activation_token && activation_token[0])) focus_os_window(os_window, also_raise, activation_token);
        Py_RETURN_TRUE;
    END_WITH_OS_WINDOW
    Py_RETURN_FALSE;
}

PYWRAP1(run_with_activation_token) {
    for (size_t o = 0; o < global_state.num_os_windows; o++) {
        OSWindow *os_window = global_state.os_windows + o;
        if (os_window->is_focused) {
            run_with_activation_token_in_os_window(os_window, args);
            Py_RETURN_TRUE;
        }
    }
    id_type os_window_id = last_focused_os_window_id();
    if (!os_window_id) {
        if (!global_state.num_os_windows) Py_RETURN_FALSE;
        os_window_id = global_state.os_windows[0].id;
    }
    for (size_t o = 0; o < global_state.num_os_windows; o++) {
        OSWindow *os_window = global_state.os_windows + o;
        if (os_window->id == os_window_id) {
            run_with_activation_token_in_os_window(os_window, args);
            Py_RETURN_TRUE;
        }
    }
    Py_RETURN_FALSE;
}

PYWRAP1(set_os_window_chrome) {
    id_type os_window_id;
    PA("K", &os_window_id);
    WITH_OS_WINDOW(os_window_id)
        set_os_window_chrome(os_window);
        Py_RETURN_TRUE;
    END_WITH_OS_WINDOW
    Py_RETURN_FALSE;
}

PYWRAP1(mark_tab_bar_dirty) {
    id_type os_window_id; int should_be_shown;
    PA("Kp", &os_window_id, &should_be_shown);
    WITH_OS_WINDOW(os_window_id)
        os_window->has_too_few_tabs = !should_be_shown;
        os_window->tab_bar_data_updated = false;
    END_WITH_OS_WINDOW
    Py_RETURN_NONE;
}

PYWRAP1(is_tab_bar_visible) {
    id_type os_window_id;
    PA("K", &os_window_id);
    if (!OPT(tab_bar_hidden)) {
        WITH_OS_WINDOW(os_window_id)
            return (os_window->num_tabs == 0 || os_window->has_too_few_tabs) ? Py_NewRef(Py_False) : Py_NewRef(Py_True);
        END_WITH_OS_WINDOW
    }
    Py_RETURN_FALSE;
}


PYWRAP1(change_background_opacity) {
    id_type os_window_id;
    float opacity;
    PA("Kf", &os_window_id, &opacity);
    WITH_OS_WINDOW(os_window_id)
        os_window->background_opacity.alpha = opacity;
        if (!os_window->redraw_count) os_window->redraw_count++;
        set_os_window_chrome(os_window);  // on macOS titlebar opacity can depend on background_opacity
        Py_RETURN_TRUE;
    END_WITH_OS_WINDOW
    Py_RETURN_FALSE;
}

PYWRAP1(background_opacity_of) {
    id_type os_window_id = PyLong_AsUnsignedLongLong(args);
    if (PyErr_Occurred()) return NULL;
    WITH_OS_WINDOW(os_window_id)
        return PyFloat_FromDouble((double)effective_os_window_alpha(os_window));
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
#define B(name) &(g.name)
#define S(name) &(g.spaces.name)
    id_type os_window_id, tab_id, window_id;
    WindowGeometry g = {0};
    Screen *screen;
    PA("KKKOIIIIIIII", &os_window_id, &tab_id, &window_id, &screen,
       B(left), B(top), B(right), B(bottom),
       S(left), S(top), S(right), S(bottom));

    WITH_WINDOW(os_window_id, tab_id, window_id);
        init_window_render_data(&window->render_data, g, screen);
    END_WITH_WINDOW;
    Py_RETURN_NONE;
#undef B
#undef S
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

PYWRAP1(set_os_window_title) {
    id_type os_window_id;
    PyObject *title;
    PA("KU", &os_window_id, &title);
    WITH_OS_WINDOW(os_window_id)
        if (os_window->disallow_title_changes) break;
        if (PyUnicode_GetLength(title)) {
            os_window->title_is_overriden = true;
            Py_XDECREF(os_window->window_title);
            os_window->window_title = title;
            Py_INCREF(title);
            set_os_window_title(os_window, PyUnicode_AsUTF8(title));
        } else {
            os_window->title_is_overriden = false;
            if (os_window->window_title) set_os_window_title(os_window, PyUnicode_AsUTF8(os_window->window_title));
            update_os_window_title(os_window);
        }
    END_WITH_OS_WINDOW
    Py_RETURN_NONE;
}

PYWRAP1(get_os_window_title) {
    id_type os_window_id;
    PA("K", &os_window_id);
    WITH_OS_WINDOW(os_window_id)
        if (os_window->window_title) return Py_BuildValue("O", os_window->window_title);
    END_WITH_OS_WINDOW
    Py_RETURN_NONE;
}

PYWRAP1(os_window_is_invisible) {
    id_type os_window_id = PyLong_AsUnsignedLongLong(args);
    if (PyErr_Occurred()) return NULL;
    WITH_OS_WINDOW(os_window_id)
        if (should_os_window_be_rendered(os_window)) { Py_RETURN_FALSE; }
        Py_RETURN_TRUE;
    END_WITH_OS_WINDOW
    Py_RETURN_FALSE;
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
    if (set_val > 0) OPT(font_size) = set_val;
    return Py_BuildValue("d", OPT(font_size));
}

PYWRAP1(os_window_font_size) {
    id_type os_window_id;
    int force = 0;
    double new_sz = -1;
    PA("K|dp", &os_window_id, &new_sz, &force);
    WITH_OS_WINDOW(os_window_id)
        if (new_sz > 0 && (force || new_sz != os_window->fonts_data->font_sz_in_pts)) {
            on_os_window_font_size_change(os_window, new_sz);
            send_prerendered_sprites_for_window(os_window);
            resize_screen(os_window, os_window->tab_bar_render_data.screen, false);
            for (size_t ti = 0; ti < os_window->num_tabs; ti++) {
                Tab *tab = os_window->tabs + ti;
                for (size_t wi = 0; wi < tab->num_windows; wi++) {
                    Window *w = tab->windows + wi;
                    resize_screen(os_window, w->render_data.screen, true);
                }
            }
            // On Wayland with CSD title needs to be re-rendered in a different font size
            if (os_window->window_title && global_state.is_wayland) set_os_window_title(os_window, NULL);
        }
        return Py_BuildValue("d", os_window->fonts_data->font_sz_in_pts);
    END_WITH_OS_WINDOW
    return Py_BuildValue("d", 0.0);
}

PYWRAP1(set_os_window_size) {
    id_type os_window_id;
    int width, height;
    PA("Kii", &os_window_id, &width, &height);
    WITH_OS_WINDOW(os_window_id)
        set_os_window_size(os_window, width, height);
        Py_RETURN_TRUE;
    END_WITH_OS_WINDOW
    Py_RETURN_FALSE;
}

PYWRAP1(get_os_window_size) {
    id_type os_window_id;
    PA("K", &os_window_id);
    WITH_OS_WINDOW(os_window_id)
        double xdpi, ydpi;
        float xscale, yscale;
        int width, height, fw, fh;
        get_os_window_size(os_window, &width, &height, &fw, &fh);
        get_os_window_content_scale(os_window, &xdpi, &ydpi, &xscale, &yscale);
        unsigned int cell_width = os_window->fonts_data->fcm.cell_width, cell_height = os_window->fonts_data->fcm.cell_height;
        return Py_BuildValue("{si si si si sf sf sd sd sI sI sO}",
            "width", width, "height", height, "framebuffer_width", fw, "framebuffer_height", fh,
            "xscale", xscale, "yscale", yscale, "xdpi", xdpi, "ydpi", ydpi,
            "cell_width", cell_width, "cell_height", cell_height, "is_layer_shell", os_window->is_layer_shell ? Py_True : Py_False);
    END_WITH_OS_WINDOW
    Py_RETURN_NONE;
}

PYWRAP1(get_os_window_pos) {
    id_type os_window_id;
    PA("K", &os_window_id);
    WITH_OS_WINDOW(os_window_id)
        int x, y;
        get_os_window_pos(os_window, &x, &y);
        return Py_BuildValue("ii", x, y);
    END_WITH_OS_WINDOW
    Py_RETURN_NONE;
}

PYWRAP1(set_os_window_pos) {
    id_type os_window_id;
    int x, y;
    PA("Kii", &os_window_id, &x, &y);
    WITH_OS_WINDOW(os_window_id)
        set_os_window_pos(os_window, x, y);
    END_WITH_OS_WINDOW
    Py_RETURN_NONE;
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

PYWRAP0(apply_options_update) {
    for (size_t o = 0; o < global_state.num_os_windows; o++) {
        OSWindow *os_window = global_state.os_windows + o;
        get_platform_dependent_config_values(os_window->handle);
        os_window->background_opacity.alpha = OPT(background_opacity);
        set_os_window_chrome(os_window);
        if (!os_window->redraw_count) os_window->redraw_count++;
        for (size_t t = 0; t < os_window->num_tabs; t++) {
            Tab *tab = os_window->tabs + t;
            for (size_t w = 0; w < tab->num_windows; w++) {
                Window *window = tab->windows + w;
                if (window->window_logo.using_default) {
                    set_window_logo(window, OPT(default_window_logo), OPT(window_logo_position), OPT(window_logo_alpha), true, NULL, 0);
                }
            }
        }
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
        if (val == Py_None) OPT(name) = 0; \
        else if (PyLong_Check(val)) OPT(name) = PyLong_AsLong(val); \
    } \
}
    P(active_border_color); P(inactive_border_color); P(bell_border_color); P(tab_bar_background);
    P(tab_bar_margin_color); P(macos_titlebar_color); P(wayland_titlebar_color);
    P(scrollbar_handle_color); P(scrollbar_track_color);
    if (configured) {
        P(background); P(url_color);
    }
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
}

PYWRAP1(update_tab_bar_edge_colors) {
    id_type os_window_id;
    PA("K", &os_window_id);
    WITH_OS_WINDOW(os_window_id)
        if (os_window->tab_bar_render_data.screen) {
            if (get_line_edge_colors(os_window->tab_bar_render_data.screen, &os_window->tab_bar_edge_color.left, &os_window->tab_bar_edge_color.right)) { Py_RETURN_TRUE; }
        }
    END_WITH_OS_WINDOW
    Py_RETURN_FALSE;
}

static PyObject*
pyset_background_image(PyObject *self UNUSED, PyObject *args, PyObject *kw) {
    const char *path;
    PyObject *layout_name = NULL, *pylinear = NULL, *pytint = NULL, *pytint_gaps = NULL;
    PyObject *os_window_ids;
    int configured = 0;
    char *png_data = NULL; Py_ssize_t png_data_size = 0;
    int global_index = -1; int is_increment = 0;
    static char *kwds[] = {
        "path", "os_window_ids", "configured", "layout_name", "png_data", "linear", "tint", "tint_gaps", "global_index",
        "is_increment",
    NULL};
    if (!PyArg_ParseTupleAndKeywords(args, kw, "zO!|pOy#OOOip", kwds, &path, &PyTuple_Type, &os_window_ids, &configured, &layout_name, &png_data, &png_data_size, &pylinear, &pytint, &pytint_gaps, &global_index, &is_increment)) return NULL;
    size_t size;
    BackgroundImageLayout layout = PyUnicode_Check(layout_name) ? bglayout(layout_name) : OPT(background_image_layout);
    BackgroundImage *bgimage = NULL;
    if (path) {
        bgimage = calloc(1, sizeof(BackgroundImage));
        if (!bgimage) return PyErr_NoMemory();
        bool ok;
        if (png_data && png_data_size) {
            ok = png_from_data(png_data, png_data_size, path, &bgimage->bitmap, &bgimage->width, &bgimage->height, &size);
        } else {
            ok = image_path_to_bitmap(path, &bgimage->bitmap, &bgimage->width, &bgimage->height, &bgimage->mmap_size);
        }
        if (!ok) {
            PyErr_Format(PyExc_ValueError, "Failed to load image from: %s", path);
            free(bgimage);
            return NULL;
        }
        bgimage->id = ++bg_image_id_counter;
        if (!send_bgimage_to_gpu(layout, bgimage)) {
            PyErr_Format(PyExc_ValueError, "Failed to send image to GPU image from: %s", path);
            free(bgimage);
            return NULL;
        }
        bgimage->refcnt++;
    }
    if (configured) {
        if (bgimage) {
            if (global_background_image(0)) {
                free_bgimage(&global_state.background_images.images[0], true);
            } else {
                free_global_background_images(true);
                global_state.background_images.images = calloc(1, sizeof(global_state.background_images.images[0]));
                if (!global_state.background_images.images) fatal("Out of memory");
                global_state.background_images.count = 1;
                global_state.background_images.generation = OPT(background_images).generation;
            }
            global_state.background_images.images[0] = bgimage;
            bgimage->refcnt++;
            if (OPT(background_images).count > 0) {
                free(OPT(background_images).paths[0]);
                char *new_path = strdup(path);
                if (!new_path) fatal("Out of memory");
                OPT(background_images).paths[0] = new_path;
            }
        } else free_global_background_images(true);
        OPT(background_image_layout) = layout;
        if (pylinear && pylinear != Py_None) convert_from_python_background_image_linear(pylinear, &global_state.opts);
        if (pytint && pytint != Py_None) convert_from_python_background_tint(pytint, &global_state.opts);
        if (pytint_gaps && pytint_gaps != Py_None) convert_from_python_background_tint_gaps(pytint_gaps, &global_state.opts);
    }
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(os_window_ids); i++) {
        id_type os_window_id = PyLong_AsUnsignedLongLong(PyTuple_GET_ITEM(os_window_ids, i));
        WITH_OS_WINDOW(os_window_id)
            unsigned idx = os_window->background_image.global_bg_images_idx;
            make_os_window_context_current(os_window);
            free_bgimage(&os_window->background_image.override, true);
            zero_at_ptr(&os_window->background_image);
            os_window->render_calls = 0;
            if (bgimage) {
                if (!configured) {  // configured means we use the zero index global image
                    os_window->background_image.override = bgimage;
                    bgimage->refcnt++;
                }
            } else if (is_increment) {
                os_window->background_image.global_bg_images_idx = increment_bg_image_idx(idx, global_index);
            } else if (global_index < 0) os_window->background_image.no_image = true;
            else os_window->background_image.global_bg_images_idx = global_index;
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

PYWRAP0(wakeup_main_loop) {
    wakeup_main_loop();
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

static bool
click_mouse_url(id_type os_window_id, id_type tab_id, id_type window_id) {
    bool clicked = false;
    WITH_WINDOW(os_window_id, tab_id, window_id);
    clicked = mouse_open_url(window);
    END_WITH_WINDOW;
    return clicked;
}

static bool
click_mouse_cmd_output(id_type os_window_id, id_type tab_id, id_type window_id, int select_cmd_output) {
    bool handled = false;
    WITH_WINDOW(os_window_id, tab_id, window_id);
    handled = mouse_set_last_visited_cmd_output(window);
    if (select_cmd_output && handled) handled = mouse_select_cmd_output(window);
    END_WITH_WINDOW;
    return handled;
}

static bool
move_cursor_to_mouse_if_in_prompt(id_type os_window_id, id_type tab_id, id_type window_id) {
    bool moved = false;
    WITH_WINDOW(os_window_id, tab_id, window_id);
    moved = move_cursor_to_mouse_if_at_shell_prompt(window);
    END_WITH_WINDOW;
    return moved;
}

static PyObject*
pyupdate_pointer_shape(PyObject *self UNUSED, PyObject *args) {
    id_type os_window_id;
    PA("K", &os_window_id);
    WITH_OS_WINDOW(os_window_id);
    OSWindow *orig = global_state.callback_os_window;
    global_state.callback_os_window = os_window;
    update_mouse_pointer_shape();
    global_state.callback_os_window = orig;
    END_WITH_OS_WINDOW;
    Py_RETURN_NONE;
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

PYWRAP1(get_window_logo_settings_if_not_default) {
    id_type os_window_id, tab_id, window_id;
    PA("KKK", &os_window_id, &tab_id, &window_id);
    WITH_WINDOW(os_window_id, tab_id, window_id);
        if (window->window_logo.instance != NULL && window->window_logo.id && !window->window_logo.using_default) {
            WindowLogo *wl = find_window_logo(global_state.all_window_logos, window->window_logo.id);
            if (wl != NULL && wl->load_from_disk_ok) {
                const char *path = window_logo_path_for_id(global_state.all_window_logos, window->window_logo.id);
                if (path) {
                    ImageAnchorPosition *p = &window->window_logo.position;
                    return Py_BuildValue("sfN", path, window->window_logo.alpha, Py_BuildValue(
                        "ffff", p->image_x, p->image_y, p->canvas_x, p->canvas_y));
                }
            }
        }
    END_WITH_WINDOW;
    Py_RETURN_NONE;
}

PYWRAP1(set_window_logo) {
    id_type os_window_id, tab_id, window_id;
    const char *path; PyObject *position;
    float alpha = 0.5;
    char *png_data = NULL; Py_ssize_t png_data_size = 0;
    PA("KKKsUf|y#", &os_window_id, &tab_id, &window_id, &path, &position, &alpha, &png_data, &png_data_size);
    bool ok = false;
    WITH_WINDOW(os_window_id, tab_id, window_id);
    ok = set_window_logo(window, path, PyObject_IsTrue(position) ? bganchor(position) : OPT(window_logo_position), (0 <= alpha && alpha <= 1) ? alpha : OPT(window_logo_alpha), false, png_data, png_data_size);
    END_WITH_WINDOW;
    if (ok) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}


PYWRAP1(click_mouse_url) {
    id_type a, b, c; PA("KKK", &a, &b, &c);
    if (click_mouse_url(a, b, c)) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

PYWRAP1(click_mouse_cmd_output) {
    id_type a, b, c; int d; PA("KKKp", &a, &b, &c, &d);
    if (click_mouse_cmd_output(a, b, c, d)) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

PYWRAP1(move_cursor_to_mouse_if_in_prompt) {
    id_type a, b, c; PA("KKK", &a, &b, &c);
    if (move_cursor_to_mouse_if_in_prompt(a, b, c)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

PYWRAP1(redirect_mouse_handling) {
    global_state.redirect_mouse_handling = PyObject_IsTrue(args) ? true : false;
    Py_RETURN_NONE;
}

PYWRAP1(buffer_keys_in_window) {
    int enabled = 1;
    id_type a, b, c; PA("KKK|p", &a, &b, &c, &enabled);
    if (buffer_keys_in_window(a, b, c, enabled)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

THREE_ID_OBJ(update_window_title)
THREE_ID(remove_window)
THREE_ID(detach_window)
THREE_ID(attach_window)
PYWRAP1(add_tab) { return PyLong_FromUnsignedLongLong(add_tab(PyLong_AsUnsignedLongLong(args))); }
PYWRAP1(add_window) { PyObject *title; id_type a, b; PA("KKO", &a, &b, &title); return PyLong_FromUnsignedLongLong(add_window(a, b, title)); }
PYWRAP0(current_os_window) { OSWindow *w = current_os_window(); if (!w) Py_RETURN_NONE; return PyLong_FromUnsignedLongLong(w->id); }
TWO_ID(remove_tab)
KI(set_active_tab)
K(mark_os_window_dirty)
KKK(set_active_window)
KII(swap_tabs)
KKKK(set_redirect_keys_to_overlay)

static PyObject*
os_window_focus_counters(PyObject *self UNUSED, PyObject *args UNUSED) {
    RAII_PyObject(ans, PyDict_New());
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = &global_state.os_windows[i];
        RAII_PyObject(key, PyLong_FromUnsignedLongLong(w->id));
        RAII_PyObject(val, PyLong_FromUnsignedLongLong(w->last_focused_counter));
        if (!key || !val) return NULL;
        if (PyDict_SetItem(ans, key, val) != 0) return NULL;
    }
    Py_INCREF(ans);
    return ans;
}

static PyObject*
get_mouse_data_for_window(PyObject *self UNUSED, PyObject *args) {
    id_type os_window_id, tab_id, window_id;
    PA("KKK", &os_window_id, &tab_id, &window_id);
    WITH_WINDOW(os_window_id, tab_id, window_id)
        return Py_BuildValue("{sI sI sO}", "cell_x", window->mouse_pos.cell_x, "cell_y", window->mouse_pos.cell_y,
                "in_left_half_of_cell", window->mouse_pos.in_left_half_of_cell ? Py_True: Py_False);
    END_WITH_WINDOW
    Py_RETURN_NONE;
}

#define tbd global_state.tab_being_dragged
static PyObject*
set_tab_being_dragged(PyObject *self UNUSED, PyObject *args) {
    zero_at_ptr(&tbd);
    if (!PyArg_ParseTuple(args, "|Kpdd", &tbd.id, &tbd.drag_started, &tbd.x, &tbd.y)) return NULL;
    Py_RETURN_NONE;
}

static PyObject*
get_tab_being_dragged(PyObject *self UNUSED, PyObject *args UNUSED) {
    return Py_BuildValue("KOdd", tbd.id, tbd.drag_started ? Py_True : Py_False, tbd.x, tbd.y);
}
#undef tbd

#define wbd global_state.window_being_dragged
static PyObject*
set_window_being_dragged(PyObject *self UNUSED, PyObject *args) {
    zero_at_ptr(&wbd);
    if (!PyArg_ParseTuple(args, "|Kpdd", &wbd.id, &wbd.drag_started, &wbd.x, &wbd.y)) return NULL;
    Py_RETURN_NONE;
}

static PyObject*
get_window_being_dragged(PyObject *self UNUSED, PyObject *args UNUSED) {
    return Py_BuildValue("KOdd", wbd.id, wbd.drag_started ? Py_True : Py_False, wbd.x, wbd.y);
}
#undef wbd

static PyObject*
request_callback_with_thumbnail(PyObject *self UNUSED, PyObject *args) {
    unsigned long long os_window_id, window_id = 0;
    const char *callback; int include_tab_bar = 0;
    double scale = 0.25; unsigned max_width = 480;
    if (!PyArg_ParseTuple(args, "sK|KpdI", &callback, &os_window_id, &window_id, &include_tab_bar, &scale, &max_width)) return NULL;
    WITH_OS_WINDOW(os_window_id)
        global_state.thumbnail_callback.os_window = os_window->id;
        global_state.thumbnail_callback.window = window_id;
        global_state.thumbnail_callback.include_tab_bar = include_tab_bar;
        snprintf(global_state.thumbnail_callback.callback, arraysz(global_state.thumbnail_callback.callback), "%s", callback);
        global_state.thumbnail_callback.max_width = max_width;
        global_state.thumbnail_callback.scale = scale;
        mark_os_window_dirty(os_window_id);
    END_WITH_OS_WINDOW
    Py_RETURN_NONE;
}


#define M(name, arg_type) {#name, (PyCFunction)name, arg_type, NULL}
#define MW(name, arg_type) {#name, (PyCFunction)py##name, arg_type, NULL}

static PyMethodDef module_methods[] = {
    M(os_window_focus_counters, METH_NOARGS),
    M(get_mouse_data_for_window, METH_VARARGS),
    M(request_callback_with_thumbnail, METH_VARARGS),
    M(set_tab_being_dragged, METH_VARARGS),
    M(get_tab_being_dragged, METH_NOARGS),
    M(set_window_being_dragged, METH_VARARGS),
    M(get_window_being_dragged, METH_NOARGS),
    MW(update_pointer_shape, METH_VARARGS),
    MW(current_os_window, METH_NOARGS),
    MW(next_window_id, METH_NOARGS),
    MW(last_focused_os_window_id, METH_NOARGS),
    MW(current_focused_os_window_id, METH_NOARGS),
    MW(set_options, METH_VARARGS),
    MW(get_options, METH_NOARGS),
    MW(click_mouse_url, METH_VARARGS),
    MW(click_mouse_cmd_output, METH_VARARGS),
    MW(move_cursor_to_mouse_if_in_prompt, METH_VARARGS),
    MW(redirect_mouse_handling, METH_O),
    MW(mouse_selection, METH_VARARGS),
    MW(set_window_logo, METH_VARARGS),
    MW(get_window_logo_settings_if_not_default, METH_VARARGS),
    MW(set_ignore_os_keyboard_processing, METH_O),
    MW(handle_for_window_id, METH_VARARGS),
    MW(update_ime_position_for_window, METH_VARARGS),
    MW(pt_to_px, METH_VARARGS),
    MW(add_tab, METH_O),
    MW(add_window, METH_VARARGS),
    MW(update_window_title, METH_VARARGS),
    MW(remove_tab, METH_VARARGS),
    MW(remove_window, METH_VARARGS),
    MW(detach_window, METH_VARARGS),
    MW(attach_window, METH_VARARGS),
    MW(set_active_tab, METH_VARARGS),
    MW(mark_os_window_dirty, METH_VARARGS),
    MW(set_redirect_keys_to_overlay, METH_VARARGS),
    MW(buffer_keys_in_window, METH_VARARGS),
    MW(set_active_window, METH_VARARGS),
    MW(swap_tabs, METH_VARARGS),
    MW(reorder_tabs, METH_VARARGS),
    MW(set_borders_rects, METH_VARARGS),
    MW(set_tab_bar_render_data, METH_VARARGS),
    MW(set_window_title_bar_render_data, METH_VARARGS),
    MW(set_window_render_data, METH_VARARGS),
    MW(set_window_drag_overlay, METH_VARARGS),
    MW(set_window_padding, METH_VARARGS),
    MW(viewport_for_window, METH_VARARGS),
    MW(cell_size_for_window, METH_VARARGS),
    MW(os_window_has_background_image, METH_VARARGS),
    MW(mark_os_window_for_close, METH_VARARGS),
    MW(set_application_quit_request, METH_VARARGS),
    MW(current_application_quit_request, METH_NOARGS),
    MW(set_os_window_chrome, METH_VARARGS),
    MW(focus_os_window, METH_VARARGS),
    MW(mark_tab_bar_dirty, METH_VARARGS),
    MW(is_tab_bar_visible, METH_VARARGS),
    MW(run_with_activation_token, METH_O),
    MW(change_background_opacity, METH_VARARGS),
    MW(background_opacity_of, METH_O),
    MW(update_window_visibility, METH_VARARGS),
    MW(sync_os_window_title, METH_VARARGS),
    MW(get_os_window_title, METH_VARARGS),
    MW(set_os_window_title, METH_VARARGS),
    MW(get_os_window_pos, METH_VARARGS),
    MW(set_os_window_pos, METH_VARARGS),
    MW(global_font_size, METH_VARARGS),
    {"set_background_image", (PyCFunction)(void (*) (void))pyset_background_image, METH_VARARGS | METH_KEYWORDS, ""},
    MW(os_window_font_size, METH_VARARGS),
    MW(set_os_window_size, METH_VARARGS),
    MW(get_os_window_size, METH_VARARGS),
    MW(os_window_is_invisible, METH_O),
    MW(update_tab_bar_edge_colors, METH_VARARGS),
    MW(set_boss, METH_O),
    MW(get_boss, METH_NOARGS),
    MW(apply_options_update, METH_NOARGS),
    MW(patch_global_colors, METH_VARARGS),
    MW(create_mock_window, METH_VARARGS),
    MW(destroy_global_data, METH_NOARGS),
    MW(wakeup_main_loop, METH_NOARGS),

    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static void
finalize(void) {
    while(detached_windows.num_windows--) {
        destroy_window(&detached_windows.windows[detached_windows.num_windows]);
    }
    if (detached_windows.windows) free(detached_windows.windows);
    detached_windows.capacity = 0;
    Py_CLEAR(global_state.options_object);
    free_animation(OPT(animation.cursor));
    free_animation(OPT(animation.visual_bell));
    // we leak the texture here since it is not guaranteed
    // that freeing the texture will work during shutdown and
    // the GPU driver should take care of it when the OpenGL context is
    // destroyed.
    free_global_background_images(false);
    free_window_logo_table(&global_state.all_window_logos);
    free_drag_source();
    Py_CLEAR(global_state.drop_dest.data);
    zero_at_ptr(&global_state.drop_dest);

    free_allocs_in_options(&global_state.opts);
}

bool
init_state(PyObject *module) {
    OPT(font_size) = 11.0;
#ifdef __APPLE__
#define DPI 72.0
#else
#define DPI 96.0
#endif
    global_state.default_dpi.x = DPI; global_state.default_dpi.y = DPI;
    global_state.all_window_logos = alloc_window_logo_table();
    if (!global_state.all_window_logos) { PyErr_NoMemory(); return false; }
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    if (PyStructSequence_InitType2(&RegionType, &region_desc) != 0) return false;
    Py_INCREF((PyObject *) &RegionType);
    PyModule_AddObject(module, "Region", (PyObject *) &RegionType);
    PyModule_AddIntConstant(module, "IMPERATIVE_CLOSE_REQUESTED", IMPERATIVE_CLOSE_REQUESTED);
    PyModule_AddIntConstant(module, "NO_CLOSE_REQUESTED", NO_CLOSE_REQUESTED);
    PyModule_AddIntConstant(module, "CLOSE_BEING_CONFIRMED", CLOSE_BEING_CONFIRMED);
    PyModule_AddIntMacro(module, WINDOW_NORMAL);
    PyModule_AddIntMacro(module, WINDOW_FULLSCREEN);
    PyModule_AddIntMacro(module, WINDOW_MAXIMIZED);
    PyModule_AddIntMacro(module, WINDOW_HIDDEN);
    PyModule_AddIntMacro(module, WINDOW_MINIMIZED);
    PyModule_AddIntMacro(module, LEFT_EDGE);
    PyModule_AddIntMacro(module, RIGHT_EDGE);
    PyModule_AddIntMacro(module, TOP_EDGE);
    PyModule_AddIntMacro(module, BOTTOM_EDGE);
    register_at_exit_cleanup_func(STATE_CLEANUP_FUNC, finalize);
    return true;
}
// }}}
