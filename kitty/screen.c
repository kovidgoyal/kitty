/*
 * screen.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define EXTRA_INIT { \
    PyModule_AddIntMacro(module, SCROLL_LINE); PyModule_AddIntMacro(module, SCROLL_PAGE); PyModule_AddIntMacro(module, SCROLL_FULL); \
    if (PyModule_AddFunctions(module, module_methods) != 0) return false; \
}

#include "control-codes.h"
#include "state.h"
#include "iqsort.h"
#include "fonts.h"
#include "lineops.h"
#include "hyperlink.h"
#include <structmember.h>
#include <limits.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include "unicode-data.h"
#include "modes.h"
#include "wcwidth-std.h"
#include "wcswidth.h"
#include <stdalign.h>
#include "keys.h"
#include "vt-parser.h"

static const ScreenModes empty_modes = {0, .mDECAWM=true, .mDECTCEM=true, .mDECARM=true};

#define CSI_REP_MAX_REPETITIONS 65535u

// Constructor/destructor {{{

static void
clear_selection(Selections *selections) {
    selections->in_progress = false;
    selections->extend_mode = EXTEND_CELL;
    selections->count = 0;
}

static void
init_tabstops(bool *tabstops, index_type count) {
    // In terminfo we specify the number of initial tabstops (it) as 8
    for (unsigned int t=0; t < count; t++) {
        tabstops[t] = t % 8 == 0 ? true : false;
    }
}

static bool
init_overlay_line(Screen *self, index_type columns, bool keep_active) {
    PyMem_Free(self->overlay_line.cpu_cells);
    PyMem_Free(self->overlay_line.gpu_cells);
    PyMem_Free(self->overlay_line.original_line.cpu_cells);
    PyMem_Free(self->overlay_line.original_line.gpu_cells);
    self->overlay_line.cpu_cells = PyMem_Calloc(columns, sizeof(CPUCell));
    self->overlay_line.gpu_cells = PyMem_Calloc(columns, sizeof(GPUCell));
    self->overlay_line.original_line.cpu_cells = PyMem_Calloc(columns, sizeof(CPUCell));
    self->overlay_line.original_line.gpu_cells = PyMem_Calloc(columns, sizeof(GPUCell));
    if (!self->overlay_line.cpu_cells || !self->overlay_line.gpu_cells ||
        !self->overlay_line.original_line.cpu_cells || !self->overlay_line.original_line.gpu_cells) {
        PyErr_NoMemory(); return false;
    }
    if (!keep_active) {
        self->overlay_line.is_active = false;
        self->overlay_line.xnum = 0;
    }
    self->overlay_line.is_dirty = true;
    self->overlay_line.ynum = 0;
    self->overlay_line.xstart = 0;
    self->overlay_line.cursor_x = 0;
    self->overlay_line.last_ime_pos.x = 0;
    self->overlay_line.last_ime_pos.y = 0;

    return true;
}

static void deactivate_overlay_line(Screen *self);
static void update_overlay_position(Screen *self);
static void render_overlay_line(Screen *self, Line *line, FONTS_DATA_HANDLE fonts_data);
static void update_overlay_line_data(Screen *self, uint8_t *data);

#define CALLBACK(...) \
    if (self->callbacks != Py_None) { \
        PyObject *callback_ret = PyObject_CallMethod(self->callbacks, __VA_ARGS__); \
        if (callback_ret == NULL) PyErr_Print(); else Py_DECREF(callback_ret); \
    }

static PyObject*
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    Screen *self;
    int ret = 0;
    PyObject *callbacks = Py_None, *test_child = Py_None;
    unsigned int columns=80, lines=24, scrollback=0, cell_width=10, cell_height=20;
    id_type window_id=0;
    if (!PyArg_ParseTuple(args, "|OIIIIIKO", &callbacks, &lines, &columns, &scrollback, &cell_width, &cell_height, &window_id, &test_child)) return NULL;

    self = (Screen *)type->tp_alloc(type, 0);
    if (self != NULL) {
        if ((ret = pthread_mutex_init(&self->write_buf_lock, NULL)) != 0) {
            Py_CLEAR(self); PyErr_Format(PyExc_RuntimeError, "Failed to create Screen write_buf_lock mutex: %s", strerror(ret));
            return NULL;
        }
        self->vt_parser = alloc_vt_parser(window_id);
        if (self->vt_parser == NULL) { Py_CLEAR(self); return PyErr_NoMemory(); }
        self->reload_all_gpu_data = true;
        self->cell_size.width = cell_width; self->cell_size.height = cell_height;
        self->columns = columns; self->lines = lines;
        self->write_buf_sz = BUFSIZ;
        self->write_buf = PyMem_RawMalloc(self->write_buf_sz);
        if (self->write_buf == NULL) { Py_CLEAR(self); return PyErr_NoMemory(); }
        self->window_id = window_id;
        self->modes = empty_modes;
        self->saved_modes = empty_modes;
        self->is_dirty = true;
        self->scroll_changed = false;
        self->margin_top = 0; self->margin_bottom = self->lines - 1;
        self->history_line_added_count = 0;
        reset_vt_parser(self->vt_parser);
        self->callbacks = callbacks; Py_INCREF(callbacks);
        self->test_child = test_child; Py_INCREF(test_child);
        self->cursor = alloc_cursor();
        self->color_profile = alloc_color_profile();
        self->main_linebuf = alloc_linebuf(lines, columns); self->alt_linebuf = alloc_linebuf(lines, columns);
        self->linebuf = self->main_linebuf;
        self->historybuf = alloc_historybuf(MAX(scrollback, lines), columns, OPT(scrollback_pager_history_size));
        self->main_grman = grman_alloc();
        self->alt_grman = grman_alloc();
        self->active_hyperlink_id = 0;

        self->grman = self->main_grman;
        self->disable_ligatures = OPT(disable_ligatures);
        self->main_tabstops = PyMem_Calloc(2 * self->columns, sizeof(bool));
        if (
            self->cursor == NULL || self->main_linebuf == NULL || self->alt_linebuf == NULL ||
            self->main_tabstops == NULL || self->historybuf == NULL || self->main_grman == NULL ||
            self->alt_grman == NULL || self->color_profile == NULL
        ) {
            Py_CLEAR(self); return NULL;
        }
        self->main_grman->window_id = self->window_id; self->alt_grman->window_id = self->window_id;
        self->alt_tabstops = self->main_tabstops + self->columns;
        self->tabstops = self->main_tabstops;
        init_tabstops(self->main_tabstops, self->columns);
        init_tabstops(self->alt_tabstops, self->columns);
        self->key_encoding_flags = self->main_key_encoding_flags;
        if (!init_overlay_line(self, self->columns, false)) { Py_CLEAR(self); return NULL; }
        self->hyperlink_pool = alloc_hyperlink_pool();
        if (!self->hyperlink_pool) { Py_CLEAR(self); return PyErr_NoMemory(); }
        self->as_ansi_buf.hyperlink_pool = self->hyperlink_pool;
    }
    return (PyObject*) self;
}

static Line* range_line_(Screen *self, int y);

void
screen_reset(Screen *self) {
    screen_pause_rendering(self, false, 0);
    self->main_pointer_shape_stack.count = 0; self->alternate_pointer_shape_stack.count = 0;
    if (self->linebuf == self->alt_linebuf) screen_toggle_screen_buffer(self, true, true);
    if (screen_is_overlay_active(self)) {
        deactivate_overlay_line(self);
        // Cancel IME composition
        update_ime_position_for_window(self->window_id, false, -1);
    }
    Py_CLEAR(self->last_reported_cwd);
    self->cursor_render_info.render_even_when_unfocused = false;
    memset(self->main_key_encoding_flags, 0, sizeof(self->main_key_encoding_flags));
    memset(self->alt_key_encoding_flags, 0, sizeof(self->alt_key_encoding_flags));
    self->display_window_char = 0;
    self->prompt_settings.val = 0;
    self->last_graphic_char = 0;
    self->main_savepoint.is_valid = false;
    self->alt_savepoint.is_valid = false;
    linebuf_clear(self->linebuf, BLANK_CHAR);
    historybuf_clear(self->historybuf);
    clear_hyperlink_pool(self->hyperlink_pool);
    grman_clear(self->grman, false, self->cell_size);
    self->modes = empty_modes;
    self->saved_modes = empty_modes;
    self->active_hyperlink_id = 0;
#define R(name) self->color_profile->overridden.name.val = 0
    R(default_fg); R(default_bg); R(cursor_color); R(highlight_fg); R(highlight_bg);
#undef R
    reset_vt_parser(self->vt_parser);
    self->margin_top = 0; self->margin_bottom = self->lines - 1;
    screen_normal_keypad_mode(self);
    init_tabstops(self->main_tabstops, self->columns);
    init_tabstops(self->alt_tabstops, self->columns);
    cursor_reset(self->cursor);
    self->is_dirty = true;
    clear_selection(&self->selections);
    clear_selection(&self->url_ranges);
    screen_cursor_position(self, 1, 1);
    set_dynamic_color(self, 110, NULL);
    set_dynamic_color(self, 111, NULL);
    set_color_table_color(self, 104, NULL);
}

void
screen_dirty_sprite_positions(Screen *self) {
    self->is_dirty = true;
    for (index_type i = 0; i < self->lines; i++) {
        linebuf_mark_line_dirty(self->main_linebuf, i);
        linebuf_mark_line_dirty(self->alt_linebuf, i);
    }
    for (index_type i = 0; i < self->historybuf->count; i++) historybuf_mark_line_dirty(self->historybuf, i);
}

static HistoryBuf*
realloc_hb(HistoryBuf *old, unsigned int lines, unsigned int columns, ANSIBuf *as_ansi_buf) {
    HistoryBuf *ans = alloc_historybuf(lines, columns, 0);
    if (ans == NULL) { PyErr_NoMemory(); return NULL; }
    ans->pagerhist = old->pagerhist; old->pagerhist = NULL;
    historybuf_rewrap(old, ans, as_ansi_buf);
    return ans;
}


typedef struct CursorTrack {
    index_type num_content_lines;
    bool is_beyond_content;
    struct { index_type x, y; } before;
    struct { index_type x, y; } after;
    struct { index_type x, y; } temp;
} CursorTrack;

static LineBuf*
realloc_lb(LineBuf *old, unsigned int lines, unsigned int columns, index_type *nclb, index_type *ncla, HistoryBuf *hb, CursorTrack *a, CursorTrack *b, ANSIBuf *as_ansi_buf) {
    LineBuf *ans = alloc_linebuf(lines, columns);
    if (ans == NULL) { PyErr_NoMemory(); return NULL; }
    a->temp.x = a->before.x; a->temp.y = a->before.y;
    b->temp.x = b->before.x; b->temp.y = b->before.y;
    linebuf_rewrap(old, ans, nclb, ncla, hb, &a->temp.x, &a->temp.y, &b->temp.x, &b->temp.y, as_ansi_buf);
    return ans;
}

static bool
is_selection_empty(const Selection *s) {
    int start_y = (int)s->start.y - (int)s->start_scrolled_by, end_y = (int)s->end.y - (int)s->end_scrolled_by;
    return s->start.x == s->end.x && s->start.in_left_half_of_cell == s->end.in_left_half_of_cell && start_y == end_y;
}

static void
index_selection(const Screen *self, Selections *selections, bool up) {
    for (size_t i = 0; i < selections->count; i++) {
        Selection *s = selections->items + i;
        if (up) {
            if (s->start.y == 0) s->start_scrolled_by += 1;
            else {
                s->start.y--;
                if (s->input_start.y) s->input_start.y--;
                if (s->input_current.y) s->input_current.y--;
                if (s->initial_extent.start.y) s->initial_extent.start.y--;
                if (s->initial_extent.end.y) s->initial_extent.end.y--;
            }
            if (s->end.y == 0) s->end_scrolled_by += 1;
            else s->end.y--;
        } else {
            if (s->start.y >= self->lines - 1) s->start_scrolled_by -= 1;
            else {
                s->start.y++;
                if (s->input_start.y < self->lines - 1) s->input_start.y++;
                if (s->input_current.y < self->lines - 1) s->input_current.y++;
            }
            if (s->end.y >= self->lines - 1) s->end_scrolled_by -= 1;
            else s->end.y++;
        }
    }
}


#define INDEX_GRAPHICS(amtv) { \
    bool is_main = self->linebuf == self->main_linebuf; \
    static ScrollData s; \
    s.amt = amtv; s.limit = is_main ? -self->historybuf->ynum : 0; \
    s.has_margins = self->margin_top != 0 || self->margin_bottom != self->lines - 1; \
    s.margin_top = top; s.margin_bottom = bottom; \
    grman_scroll_images(self->grman, &s, self->cell_size); \
}


#define INDEX_DOWN \
    linebuf_reverse_index(self->linebuf, top, bottom); \
    linebuf_clear_line(self->linebuf, top, true); \
    if (self->linebuf == self->main_linebuf && self->last_visited_prompt.is_set) { \
        if (self->last_visited_prompt.scrolled_by > 0) self->last_visited_prompt.scrolled_by--; \
        else if(self->last_visited_prompt.y < self->lines - 1) self->last_visited_prompt.y++; \
        else self->last_visited_prompt.is_set = false; \
    } \
    INDEX_GRAPHICS(1) \
    self->is_dirty = true; \
    index_selection(self, &self->selections, false);


static void
prevent_current_prompt_from_rewrapping(Screen *self) {
    if (!self->prompt_settings.redraws_prompts_at_all) return;
    int y = self->cursor->y;
    while (y >= 0) {
        linebuf_init_line(self->main_linebuf, y);
        Line *line = self->linebuf->line;
        switch (line->attrs.prompt_kind) {
            case UNKNOWN_PROMPT_KIND:
                break;
            case PROMPT_START:
            case SECONDARY_PROMPT:
                goto found;
                break;
            case OUTPUT_START:
                return;
        }
        y--;
    }
found:
    if (y < 0) return;
    // we have identified a prompt at which the cursor is present, the shell
    // will redraw this prompt. However when doing so it gets confused if the
    // cursor vertical position relative to the first prompt line changes. This
    // can easily be seen for instance in zsh when a right side prompt is used
    // so when resizing, simply blank all lines after the current
    // prompt and trust the shell to redraw them.
    for (; y < (int)self->main_linebuf->ynum; y++) {
        linebuf_clear_line(self->main_linebuf, y, false);
        linebuf_init_line(self->main_linebuf, y);
        if (y <= (int)self->cursor->y) {
            // this is needed because screen_resize() checks to see if the cursor is beyond the content,
            // so insert some fake content
            Line *line = self->linebuf->line;
            // we use a space as readline does not erase to bottom of screen so we fake it with spaces
            line->cpu_cells[0].ch = ' ';
        }
    }
}

static bool
screen_resize(Screen *self, unsigned int lines, unsigned int columns) {
    screen_pause_rendering(self, false, 0);
    lines = MAX(1u, lines); columns = MAX(1u, columns);

    bool is_main = self->linebuf == self->main_linebuf;
    index_type num_content_lines_before, num_content_lines_after;
    bool dummy_output_inserted = false;
    if (is_main && self->cursor->x == 0 && self->cursor->y < self->lines && self->linebuf->line_attrs[self->cursor->y].prompt_kind == OUTPUT_START) {
        linebuf_init_line(self->linebuf, self->cursor->y);
        if (!self->linebuf->line->cpu_cells[0].ch) {
            // we have a blank output start line, we need it to be preserved by
            // reflow, so insert a dummy char
            self->linebuf->line->cpu_cells[self->cursor->x++].ch = '<';
            dummy_output_inserted = true;
        }
    }
    unsigned int lines_after_cursor_before_resize = self->lines - self->cursor->y;
    CursorTrack cursor = {.before = {self->cursor->x, self->cursor->y}};
    CursorTrack main_saved_cursor = {.before = {self->main_savepoint.cursor.x, self->main_savepoint.cursor.y}};
    CursorTrack alt_saved_cursor = {.before = {self->alt_savepoint.cursor.x, self->alt_savepoint.cursor.y}};
#define setup_cursor(which) { \
    which.after.x = which.temp.x; which.after.y = which.temp.y; \
    which.is_beyond_content = num_content_lines_before > 0 && self->cursor->y >= num_content_lines_before; \
    which.num_content_lines = num_content_lines_after; \
}
    // Resize overlay line
    if (!init_overlay_line(self, columns, true)) return false;

    // Resize main linebuf
    HistoryBuf *nh = realloc_hb(self->historybuf, self->historybuf->ynum, columns, &self->as_ansi_buf);
    if (nh == NULL) return false;
    Py_CLEAR(self->historybuf); self->historybuf = nh;
    if (is_main) prevent_current_prompt_from_rewrapping(self);
    LineBuf *n = realloc_lb(self->main_linebuf, lines, columns, &num_content_lines_before, &num_content_lines_after, self->historybuf, &cursor, &main_saved_cursor, &self->as_ansi_buf);
    if (n == NULL) return false;
    Py_CLEAR(self->main_linebuf); self->main_linebuf = n;
    if (is_main) setup_cursor(cursor);
    /* printf("old_cursor: (%u, %u) new_cursor: (%u, %u) beyond_content: %d\n", self->cursor->x, self->cursor->y, cursor.after.x, cursor.after.y, cursor.is_beyond_content); */
    setup_cursor(main_saved_cursor);
    grman_remove_all_cell_images(self->main_grman);
    grman_resize(self->main_grman, self->lines, lines, self->columns, columns, num_content_lines_before, num_content_lines_after);

    // Resize alt linebuf
    n = realloc_lb(self->alt_linebuf, lines, columns, &num_content_lines_before, &num_content_lines_after, NULL, &cursor, &alt_saved_cursor, &self->as_ansi_buf);
    if (n == NULL) return false;
    Py_CLEAR(self->alt_linebuf); self->alt_linebuf = n;
    if (!is_main) setup_cursor(cursor);
    setup_cursor(alt_saved_cursor);
    grman_remove_all_cell_images(self->alt_grman);
    grman_resize(self->alt_grman, self->lines, lines, self->columns, columns, num_content_lines_before, num_content_lines_after);
#undef setup_cursor

    self->linebuf = is_main ? self->main_linebuf : self->alt_linebuf;
    /* printf("\nold_size: (%u, %u) new_size: (%u, %u)\n", self->columns, self->lines, columns, lines); */
    self->lines = lines; self->columns = columns;
    self->margin_top = 0; self->margin_bottom = self->lines - 1;

    PyMem_Free(self->main_tabstops);
    self->main_tabstops = PyMem_Calloc(2*self->columns, sizeof(bool));
    if (self->main_tabstops == NULL) { PyErr_NoMemory(); return false; }
    self->alt_tabstops = self->main_tabstops + self->columns;
    self->tabstops = self->main_tabstops;
    init_tabstops(self->main_tabstops, self->columns);
    init_tabstops(self->alt_tabstops, self->columns);
    self->is_dirty = true;
    clear_selection(&self->selections);
    clear_selection(&self->url_ranges);
    self->last_visited_prompt.is_set = false;
#define S(c, w) c->x = MIN(w.after.x, self->columns - 1); c->y = MIN(w.after.y, self->lines - 1);
    S(self->cursor, cursor);
    S((&(self->main_savepoint.cursor)), main_saved_cursor);
    S((&(self->alt_savepoint.cursor)), alt_saved_cursor);
#undef S
    if (cursor.is_beyond_content) {
        self->cursor->y = cursor.num_content_lines;
        if (self->cursor->y >= self->lines) { self->cursor->y = self->lines - 1; screen_index(self); }
    }
    if (is_main && OPT(scrollback_fill_enlarged_window)) {
        const unsigned int top = 0, bottom = self->lines-1;
        Savepoint *sp = is_main ? &self->main_savepoint : &self->alt_savepoint;
        while (self->cursor->y + 1 < self->lines && self->lines - self->cursor->y > lines_after_cursor_before_resize) {
            if (!historybuf_pop_line(self->historybuf, self->alt_linebuf->line)) break;
            INDEX_DOWN;
            linebuf_copy_line_to(self->main_linebuf, self->alt_linebuf->line, 0);
            self->cursor->y++;
            sp->cursor.y = MIN(sp->cursor.y + 1, self->lines - 1);
        }
    }
    if (dummy_output_inserted && self->cursor->y < self->lines) {
        linebuf_init_line(self->linebuf, self->cursor->y);
        self->linebuf->line->cpu_cells[0].ch = 0;
        self->cursor->x = 0;
    }
    return true;
}

void
screen_rescale_images(Screen *self) {
    grman_remove_all_cell_images(self->main_grman);
    grman_remove_all_cell_images(self->alt_grman);
    grman_rescale(self->main_grman, self->cell_size);
    grman_rescale(self->alt_grman, self->cell_size);
}


static PyObject*
reset_callbacks(Screen *self, PyObject *a UNUSED) {
    Py_CLEAR(self->callbacks);
    self->callbacks = Py_None;
    Py_INCREF(self->callbacks);
    Py_RETURN_NONE;
}

static void
dealloc(Screen* self) {
    pthread_mutex_destroy(&self->write_buf_lock);
    free_vt_parser(self->vt_parser); self->vt_parser = NULL;
    Py_CLEAR(self->main_grman);
    Py_CLEAR(self->alt_grman);
    Py_CLEAR(self->last_reported_cwd);
    PyMem_RawFree(self->write_buf);
    Py_CLEAR(self->callbacks);
    Py_CLEAR(self->test_child);
    Py_CLEAR(self->cursor);
    Py_CLEAR(self->main_linebuf);
    Py_CLEAR(self->alt_linebuf);
    Py_CLEAR(self->historybuf);
    Py_CLEAR(self->color_profile);
    Py_CLEAR(self->marker);
    PyMem_Free(self->overlay_line.cpu_cells);
    PyMem_Free(self->overlay_line.gpu_cells);
    PyMem_Free(self->overlay_line.original_line.cpu_cells);
    PyMem_Free(self->overlay_line.original_line.gpu_cells);
    Py_CLEAR(self->overlay_line.overlay_text);
    PyMem_Free(self->main_tabstops);
    Py_CLEAR(self->paused_rendering.linebuf);
    free(self->selections.items);
    free(self->url_ranges.items);
    free(self->paused_rendering.url_ranges.items);
    free(self->paused_rendering.selections.items);
    free_hyperlink_pool(self->hyperlink_pool);
    free(self->as_ansi_buf.buf);
    free(self->last_rendered_window_char.canvas);
    Py_TYPE(self)->tp_free((PyObject*)self);
} // }}}

// Draw text {{{
typedef struct text_loop_state {
    bool image_placeholder_marked;
    const CPUCell cc; const GPUCell g;
    CPUCell *cp; GPUCell *gp;
} text_loop_state;

static void
continue_to_next_line(Screen *self) {
    linebuf_set_last_char_as_continuation(self->linebuf, self->cursor->y, true);
    self->cursor->x = 0;
    screen_linefeed(self);
}

static bool
selection_has_screen_line(const Selections *selections, const int y) {
    for (size_t i = 0; i < selections->count; i++) {
        const Selection *s = selections->items + i;
        if (!is_selection_empty(s)) {
            int start = (int)s->start.y - s->start_scrolled_by;
            int end = (int)s->end.y - s->end_scrolled_by;
            int top = MIN(start, end);
            int bottom = MAX(start, end);
            if (top <= y && y <= bottom) return true;
        }
    }
    return false;
}

static void
init_text_loop_line(Screen *self, text_loop_state *s) {
    if (self->modes.mIRM) {
        linebuf_init_line(self->linebuf, self->cursor->y);
        s->cp = self->linebuf->line->cpu_cells; s->gp = self->linebuf->line->gpu_cells;
    } else linebuf_init_cells(self->linebuf, self->cursor->y, &s->cp, &s->gp);
    if (selection_has_screen_line(&self->selections, self->cursor->y)) clear_selection(&self->selections);
    linebuf_mark_line_dirty(self->linebuf, self->cursor->y);
    s->image_placeholder_marked = false;
}


static void
move_widened_char(Screen *self, text_loop_state *s, CPUCell* cpu_cell, GPUCell *gpu_cell, index_type xpos, index_type ypos) {
    self->cursor->x = xpos; self->cursor->y = ypos;
    CPUCell src_cpu = *cpu_cell, *dest_cpu;
    GPUCell src_gpu = *gpu_cell, *dest_gpu;
    memcpy(cpu_cell, &s->cc, sizeof(s->cc));
    memcpy(gpu_cell, &s->g, sizeof(s->g));

    if (self->modes.mDECAWM) {  // overflow goes onto next line
        continue_to_next_line(self);
        init_text_loop_line(self, s);
        dest_cpu = s->cp; dest_gpu = s->gp;
        self->cursor->x = MIN(2u, self->columns);
    } else {
        dest_cpu = cpu_cell - 1;
        dest_gpu = gpu_cell - 1;
        self->cursor->x = self->columns;
    }
    *dest_cpu = src_cpu; *dest_gpu = src_gpu;
    memcpy(dest_cpu + 1 , &s->cc, sizeof(s->cc));
    memcpy(dest_gpu + 1, &s->g, sizeof(s->g));
    dest_gpu[1].attrs.width = 0;
}

void
set_active_hyperlink(Screen *self, char *id, char *url) {
    if (OPT(allow_hyperlinks)) {
        if (!url || !url[0]) {
            self->active_hyperlink_id = 0;
            return;
        }
        self->active_hyperlink_id = get_id_for_hyperlink(self, id, url);
    }
}

hyperlink_id_type
remap_hyperlink_ids(Screen *self, hyperlink_id_type *map) {
#define PROCESS_CELL(cell) { hid = (cell).hyperlink_id; if (hid) { if (!map[hid]) map[hid] = ++num; (cell).hyperlink_id = map[hid]; }}
    hyperlink_id_type num = 0, hid;
    if (self->historybuf->count) {
        for (index_type y = self->historybuf->count; y-- > 0;) {
            CPUCell *cells = historybuf_cpu_cells(self->historybuf, y);
            for (index_type x = 0; x < self->historybuf->xnum; x++) {
                PROCESS_CELL(cells[x]);
            }
        }
    }
    LineBuf *second = self->linebuf, *first = second == self->main_linebuf ? self->alt_linebuf : self->main_linebuf;
    for (index_type i = 0; i < self->lines * self->columns; i++) {
        PROCESS_CELL(first->cpu_cell_buf[i]);
    }
    for (index_type i = 0; i < self->lines * self->columns; i++) {
        PROCESS_CELL(second->cpu_cell_buf[i]);
    }
    return num;
#undef PROCESS_CELL
}


static bool is_flag_pair(char_type a, char_type b) {
    return is_flag_codepoint(a) && is_flag_codepoint(b);
}

static bool
draw_second_flag_codepoint(Screen *self, char_type ch) {
    index_type xpos = 0, ypos = 0;
    if (self->cursor->x > 1) {
        ypos = self->cursor->y;
        xpos = self->cursor->x - 2;
    } else if (self->cursor->y > 0 && self->columns > 1) {
        ypos = self->cursor->y - 1;
        xpos = self->columns - 2;
    } else return false;

    CPUCell *cp; GPUCell *gp;
    linebuf_init_cells(self->linebuf, ypos, &cp, &gp);
    CPUCell *cell = cp + xpos;
    if (!is_flag_pair(cell->ch, ch) || cell->cc_idx[0]) return false;
    line_add_combining_char(cp, gp, ch, xpos);
    return true;
}

static void
zero_cells(text_loop_state *s, CPUCell *c, GPUCell *g) {
    memcpy(c, &s->cc, sizeof(s->cc));
    memcpy(g, &s->g, sizeof(s->g));
}

static void
draw_combining_char(Screen *self, text_loop_state *s, char_type ch) {
    bool has_prev_char = false;
    index_type xpos = 0, ypos = 0;
    if (self->cursor->x > 0) {
        ypos = self->cursor->y;
        xpos = self->cursor->x - 1;
        has_prev_char = true;
    } else if (self->cursor->y > 0) {
        ypos = self->cursor->y - 1;
        xpos = self->columns - 1;
        has_prev_char = true;
    }
    if (has_prev_char) {
        CPUCell *cp; GPUCell *gp;
        linebuf_init_cells(self->linebuf, ypos, &cp, &gp);
        line_add_combining_char(cp, gp, ch, xpos);
        if (ch == 0xfe0f) {  // emoji presentation variation marker makes default text presentation emoji (narrow emoji) into wide emoji
            CPUCell *cpu_cell = cp + xpos;
            GPUCell *gpu_cell = gp + xpos;
            if (gpu_cell->attrs.width != 2 && cpu_cell->cc_idx[0] == VS16 && is_emoji_presentation_base(cpu_cell->ch)) {
                gpu_cell->attrs.width = 2;
                if (xpos + 1 < self->columns) {
                    zero_cells(s, cp + xpos + 1, gp + xpos + 1);
                    gp[xpos + 1].attrs.width = 0;
                    self->cursor->x++;
                } else move_widened_char(self, s, cpu_cell, gpu_cell, xpos, ypos);
            }
        } else if (ch == 0xfe0e) {
            CPUCell *cpu_cell = cp + xpos;
            GPUCell *gpu_cell = gp + xpos;
            if (gpu_cell->attrs.width == 0 && cpu_cell->ch == 0 && xpos > 0) {
                cpu_cell--; gpu_cell--;
            }
            if (gpu_cell->attrs.width == 2 && cpu_cell->cc_idx[0] == VS15 && is_emoji_presentation_base(cpu_cell->ch)) {
                gpu_cell->attrs.width = 1;
                self->cursor->x--;
            }
        }
    }
}

static void
screen_on_input(Screen *self) {
    if (!self->has_activity_since_last_focus && !self->has_focus && self->callbacks != Py_None) {
        PyObject *ret = PyObject_CallMethod(self->callbacks, "on_activity_since_last_focus", NULL);
        if (ret == NULL) PyErr_Print();
        else {
            if (ret == Py_True) self->has_activity_since_last_focus = true;
            Py_DECREF(ret);
        }
    }
}

static void
ensure_cursor_not_on_wide_char_trailer_for_insert(Screen *self, text_loop_state *s) {
    if (UNLIKELY(self->cursor->x > 0 && s->gp[self->cursor->x - 1].attrs.width == 2)) {
        zero_cells(s, s->cp + self->cursor->x - 1, s->gp + self->cursor->x - 1);
        s->cp[self->cursor->x-1].ch = ' ';
        zero_cells(s, s->cp + self->cursor->x, s->gp + self->cursor->x);
    }
}

static void
draw_text_loop(Screen *self, const uint32_t *chars, size_t num_chars, text_loop_state *s) {
    init_text_loop_line(self, s);
    if ((' ' >= chars[0] && chars[0] < 0x7f) || !is_combining_char(chars[0])) ensure_cursor_not_on_wide_char_trailer_for_insert(self, s);
    for (size_t i = 0; i < num_chars; i++) {
        uint32_t ch = chars[i];
        if (ch < ' ') {
            switch (ch) {
                case BEL:
                    screen_bell(self); break;
                case BS:
                    screen_backspace(self); break;
                case HT:
                    screen_tab(self); break;
                case LF:
                case VT:
                case FF:
                    screen_linefeed(self); init_text_loop_line(self, s); break;
                case CR:
                    screen_carriage_return(self); break;
                default:
                    break;
            }
            continue;
        }
        int char_width = 1;
        if (ch > 0x7f) {  // not printable ASCII
            if (is_ignored_char(ch)) continue;
            if (UNLIKELY(is_combining_char(ch))) {
                if (UNLIKELY(is_flag_codepoint(ch))) {
                    if (draw_second_flag_codepoint(self, ch)) continue;
                } else {
                    draw_combining_char(self, s, ch);
                    continue;
                }
            }
            char_width = wcwidth_std(ch);
            if (UNLIKELY(char_width < 1)) {
                if (char_width == 0) continue;
                char_width = 1;
            }
        }
        self->last_graphic_char = ch;
        if (UNLIKELY(self->columns < self->cursor->x + (unsigned int)char_width)) {
            if (self->modes.mDECAWM) {
                continue_to_next_line(self);
                init_text_loop_line(self, s);
            } else {
                self->cursor->x = self->columns - char_width;
                ensure_cursor_not_on_wide_char_trailer_for_insert(self, s);
            }
        }
        if (self->modes.mIRM) line_right_shift(self->linebuf->line, self->cursor->x, char_width);
        if (UNLIKELY(!s->image_placeholder_marked && ch == IMAGE_PLACEHOLDER_CHAR)) {
            linebuf_set_line_has_image_placeholders(self->linebuf, self->cursor->y, true);
            s->image_placeholder_marked = true;
        }
        zero_cells(s, s->cp + self->cursor->x, s->gp + self->cursor->x);
        s->cp[self->cursor->x].ch = ch;
        self->cursor->x++;
        if (char_width == 2) {
            s->gp[self->cursor->x-1].attrs.width = 2;
            zero_cells(s, s->cp + self->cursor->x, s->gp + self->cursor->x);
            s->gp[self->cursor->x].attrs.width = 0;
            self->cursor->x++;
        }
    }
#undef init_line
}

static void
draw_text(Screen *self, const uint32_t *chars, size_t num_chars) {
    self->is_dirty = true;
    const bool force_underline = OPT(underline_hyperlinks) == UNDERLINE_ALWAYS && self->active_hyperlink_id != 0;
    CellAttrs attrs = cursor_to_attrs(self->cursor, 1);
    if (force_underline) attrs.decoration = OPT(url_style);
    text_loop_state s={
        .cc=(CPUCell){.hyperlink_id=self->active_hyperlink_id},
        .g=(GPUCell){
            .attrs=attrs,
            .fg=self->cursor->fg & COL_MASK, .bg=self->cursor->bg & COL_MASK,
            .decoration_fg=force_underline ? ((OPT(url_color) & COL_MASK) << 8) | 2 : self->cursor->decoration_fg & COL_MASK,
        }
    };
    draw_text_loop(self, chars, num_chars, &s);
}

void
screen_draw_text(Screen *self, const uint32_t *chars, size_t num_chars) {
    screen_on_input(self);
    draw_text(self, chars, num_chars);
}

static void
draw_codepoint(Screen *self, char_type ch) {
    uint32_t lch = self->last_graphic_char;
    draw_text(self, &ch, 1);
    self->last_graphic_char = lch;
}

void
screen_align(Screen *self) {
    self->margin_top = 0; self->margin_bottom = self->lines - 1;
    screen_cursor_position(self, 1, 1);
    linebuf_clear(self->linebuf, 'E');
}

// }}}

// Graphics {{{

void
screen_alignment_display(Screen *self) {
    // https://www.vt100.net/docs/vt510-rm/DECALN.html
    screen_cursor_position(self, 1, 1);
    self->margin_top = 0; self->margin_bottom = self->lines - 1;
    for (unsigned int y = 0; y < self->linebuf->ynum; y++) {
        linebuf_init_line(self->linebuf, y);
        line_clear_text(self->linebuf->line, 0, self->linebuf->xnum, 'E');
        linebuf_mark_line_dirty(self->linebuf, y);
    }
}

void
select_graphic_rendition(Screen *self, int *params, unsigned int count, bool is_group, Region *region_) {
    if (region_) {
        Region region = *region_;
        if (!region.top) region.top = 1;
        if (!region.left) region.left = 1;
        if (!region.bottom) region.bottom = self->lines;
        if (!region.right) region.right = self->columns;
        if (self->modes.mDECOM) {
            region.top += self->margin_top; region.bottom += self->margin_top;
        }
        region.left -= 1; region.top -= 1; region.right -= 1; region.bottom -= 1;  // switch to zero based indexing
        if (self->modes.mDECSACE) {
            index_type x = MIN(region.left, self->columns - 1);
            index_type num = region.right >= x ? region.right - x + 1 : 0;
            num = MIN(num, self->columns - x);
            for (index_type y = region.top; y < MIN(region.bottom + 1, self->lines); y++) {
                linebuf_init_line(self->linebuf, y);
                apply_sgr_to_cells(self->linebuf->line->gpu_cells + x, num, params, count, is_group);
            }
        } else {
            index_type x, num;
            if (region.top == region.bottom) {
                linebuf_init_line(self->linebuf, region.top);
                x = MIN(region.left, self->columns-1);
                num = MIN(self->columns - x, region.right - x + 1);
                apply_sgr_to_cells(self->linebuf->line->gpu_cells + x, num, params, count, is_group);
            } else {
                for (index_type y = region.top; y < MIN(region.bottom + 1, self->lines); y++) {
                    if (y == region.top) { x = MIN(region.left, self->columns - 1); num = self->columns - x; }
                    else if (y == region.bottom) { x = 0; num = MIN(region.right + 1, self->columns); }
                    else { x = 0; num = self->columns; }
                    linebuf_init_line(self->linebuf, y);
                    apply_sgr_to_cells(self->linebuf->line->gpu_cells + x, num, params, count, is_group);
                }
            }
        }
    } else cursor_from_sgr(self->cursor, params, count, is_group);
}

static void
write_to_test_child(Screen *self, const char *data, size_t sz) {
    PyObject *r = PyObject_CallMethod(self->test_child, "write", "y#", data, sz); if (r == NULL) PyErr_Print(); Py_CLEAR(r);
}

static bool
write_to_child(Screen *self, const char *data, size_t sz) {
    bool written = false;
    if (self->window_id) written = schedule_write_to_child(self->window_id, 1, data, sz);
    if (self->test_child != Py_None) { write_to_test_child(self, data, sz); }
    return written;
}

static void
get_prefix_and_suffix_for_escape_code(unsigned char which, const char ** prefix, const char ** suffix) {
    *suffix = "\033\\";
    switch(which) {
        case ESC_DCS:
            *prefix = "\033P";
            break;
        case ESC_CSI:
            *prefix = "\033["; *suffix = "";
            break;
        case ESC_OSC:
            *prefix = "\033]";
            break;
        case ESC_PM:
            *prefix = "\033^";
            break;
        case ESC_APC:
            *prefix = "\033_";
            break;
        default:
            fatal("Unknown escape code to write: %u", which);
    }
}

bool
write_escape_code_to_child(Screen *self, unsigned char which, const char *data) {
    bool written = false;
    const char *prefix, *suffix;
    get_prefix_and_suffix_for_escape_code(which, &prefix, &suffix);
    if (self->window_id) {
        if (suffix[0]) {
            written = schedule_write_to_child(self->window_id, 3, prefix, strlen(prefix), data, strlen(data), suffix, strlen(suffix));
        } else {
            written = schedule_write_to_child(self->window_id, 2, prefix, strlen(prefix), data, strlen(data));
        }
    }
    if (self->test_child != Py_None) {
        write_to_test_child(self, prefix, strlen(prefix));
        write_to_test_child(self, data, strlen(data));
        if (suffix[0]) write_to_test_child(self, suffix, strlen(suffix));
    }
    return written;
}

static bool
write_escape_code_to_child_python(Screen *self, unsigned char which, PyObject *data) {
    bool written = false;
    const char *prefix, *suffix;
    get_prefix_and_suffix_for_escape_code(which, &prefix, &suffix);
    if (self->window_id) written = schedule_write_to_child_python(self->window_id, prefix, data, suffix);
    if (self->test_child != Py_None) {
        write_to_test_child(self, prefix, strlen(prefix));
        for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(data); i++) {
            PyObject *t = PyTuple_GET_ITEM(data, i);
            if (PyBytes_Check(t)) write_to_test_child(self, PyBytes_AS_STRING(t), PyBytes_GET_SIZE(t));
            else {
                Py_ssize_t sz;
                const char *d = PyUnicode_AsUTF8AndSize(t, &sz);
                if (d) write_to_test_child(self, d, sz);
            }
        }
        if (suffix[0]) write_to_test_child(self, suffix, strlen(suffix));
    }
    return written;
}

static bool
cursor_within_margins(Screen *self) {
    return self->margin_top <= self->cursor->y && self->cursor->y <= self->margin_bottom;
}

// Remove all cell images from a portion of the screen and mark lines that
// contain image placeholders as dirty to make sure they are redrawn. This is
// needed when we perform commands that may move some lines without marking them
// as dirty (like screen_insert_lines) and at the same time don't move image
// references (i.e. unlike screen_scroll, which moves everything).
static void
screen_dirty_line_graphics(Screen *self, const unsigned int top, const unsigned int bottom, const bool main_buf) {
    bool need_to_remove = false;
    const unsigned int limit = MIN(bottom+1, self->lines);
    LineBuf *linebuf = main_buf ? self->main_linebuf : self->alt_linebuf;
    for (unsigned int y = top; y < limit; y++) {
        if (linebuf->line_attrs[y].has_image_placeholders) {
            need_to_remove = true;
            linebuf_mark_line_dirty(linebuf, y);
            self->is_dirty = true;
        }
    }
    if (need_to_remove)
        grman_remove_cell_images(main_buf ? self->main_grman : self->alt_grman, top, bottom);
}

void
screen_handle_graphics_command(Screen *self, const GraphicsCommand *cmd, const uint8_t *payload) {
    unsigned int x = self->cursor->x, y = self->cursor->y;
    const char *response = grman_handle_command(self->grman, cmd, payload, self->cursor, &self->is_dirty, self->cell_size);
    if (response != NULL) write_escape_code_to_child(self, ESC_APC, response);
    if (x != self->cursor->x || y != self->cursor->y) {
        bool in_margins = cursor_within_margins(self);
        if (self->cursor->x >= self->columns) { self->cursor->x = 0; self->cursor->y++; }
        if (self->cursor->y > self->margin_bottom) screen_scroll(self, self->cursor->y - self->margin_bottom);
        screen_ensure_bounds(self, false, in_margins);
    }
    if (cmd->unicode_placement) {
        // Make sure the placeholders are redrawn if we add or change a virtual placement.
        screen_dirty_line_graphics(self, 0, self->lines, self->linebuf == self->main_linebuf);
    }
}
// }}}

// Modes {{{


void
screen_toggle_screen_buffer(Screen *self, bool save_cursor, bool clear_alt_screen) {
    bool to_alt = self->linebuf == self->main_linebuf;
    self->active_hyperlink_id = 0;
    if (to_alt) {
        if (clear_alt_screen) {
            linebuf_clear(self->alt_linebuf, BLANK_CHAR);
            grman_clear(self->alt_grman, true, self->cell_size);
        }
        if (save_cursor) screen_save_cursor(self);
        self->linebuf = self->alt_linebuf;
        self->tabstops = self->alt_tabstops;
        self->key_encoding_flags = self->alt_key_encoding_flags;
        self->grman = self->alt_grman;
        screen_cursor_position(self, 1, 1);
        cursor_reset(self->cursor);
    } else {
        self->linebuf = self->main_linebuf;
        self->tabstops = self->main_tabstops;
        self->key_encoding_flags = self->main_key_encoding_flags;
        if (save_cursor) screen_restore_cursor(self);
        self->grman = self->main_grman;
    }
    screen_history_scroll(self, SCROLL_FULL, false);
    self->is_dirty = true;
    self->grman->layers_dirty = true;
    clear_selection(&self->selections);
    global_state.check_for_active_animated_images = true;
}

void screen_normal_keypad_mode(Screen UNUSED *self) {} // Not implemented as this is handled by the GUI
void screen_alternate_keypad_mode(Screen UNUSED *self) {}  // Not implemented as this is handled by the GUI

static void
set_mode_from_const(Screen *self, unsigned int mode, bool val) {
#define SIMPLE_MODE(name) \
    case name: \
        self->modes.m##name = val; break;

#define MOUSE_MODE(name, attr, value) \
    case name: \
        self->modes.attr = val ? value : 0; break;

    bool private;
    switch(mode) {
        SIMPLE_MODE(LNM)
        SIMPLE_MODE(IRM)
        SIMPLE_MODE(DECARM)
        SIMPLE_MODE(BRACKETED_PASTE)
        SIMPLE_MODE(FOCUS_TRACKING)
        SIMPLE_MODE(HANDLE_TERMIOS_SIGNALS)
        MOUSE_MODE(MOUSE_BUTTON_TRACKING, mouse_tracking_mode, BUTTON_MODE)
        MOUSE_MODE(MOUSE_MOTION_TRACKING, mouse_tracking_mode, MOTION_MODE)
        MOUSE_MODE(MOUSE_MOVE_TRACKING, mouse_tracking_mode, ANY_MODE)
        MOUSE_MODE(MOUSE_UTF8_MODE, mouse_tracking_protocol, UTF8_PROTOCOL)
        MOUSE_MODE(MOUSE_SGR_MODE, mouse_tracking_protocol, SGR_PROTOCOL)
        MOUSE_MODE(MOUSE_SGR_PIXEL_MODE, mouse_tracking_protocol, SGR_PIXEL_PROTOCOL)
        MOUSE_MODE(MOUSE_URXVT_MODE, mouse_tracking_protocol, URXVT_PROTOCOL)

        case DECSCLM:
        case DECNRCM:
            break;  // we ignore these modes
        case DECCKM:
            self->modes.mDECCKM = val;
            break;
        case DECTCEM:
            self->modes.mDECTCEM = val;
            break;
        case DECSCNM:
            // Render screen in reverse video
            if (self->modes.mDECSCNM != val) {
                self->modes.mDECSCNM = val;
                self->is_dirty = true;
            }
            break;
        case DECOM:
            self->modes.mDECOM = val;
            // According to `vttest`, DECOM should also home the cursor, see
            // vttest/main.c:369.
            screen_cursor_position(self, 1, 1);
            break;
        case DECAWM:
            self->modes.mDECAWM = val; break;
        case DECCOLM:
            self->modes.mDECCOLM = val;
            if (val) {
                // When DECCOLM mode is set, the screen is erased and the cursor
                // moves to the home position.
                screen_erase_in_display(self, 2, false);
                screen_cursor_position(self, 1, 1);
            }
            break;
        case CONTROL_CURSOR_BLINK:
            self->cursor->non_blinking = !val;
            break;
        case SAVE_CURSOR:
            screen_save_cursor(self);
            break;
        case TOGGLE_ALT_SCREEN_1:
        case TOGGLE_ALT_SCREEN_2:
        case ALTERNATE_SCREEN:
            if (val && self->linebuf == self->main_linebuf) screen_toggle_screen_buffer(self, mode == ALTERNATE_SCREEN, mode == ALTERNATE_SCREEN);
            else if (!val && self->linebuf != self->main_linebuf) screen_toggle_screen_buffer(self, mode == ALTERNATE_SCREEN, mode == ALTERNATE_SCREEN);
            break;
        case 7727 << 5:
            log_error("Application escape mode is not supported, the extended keyboard protocol should be used instead");
            break;
        case PENDING_MODE << 5:
            if (!screen_pause_rendering(self, val, 0)) {
                log_error("Pending mode change to already current mode (%d) requested. Either pending mode expired or there is an application bug.", val);
            }
            break;
        default:
            private = mode >= 1 << 5;
            if (private) mode >>= 5;
            log_error("%s %s %u %s", ERROR_PREFIX, "Unsupported screen mode: ", mode, private ? "(private)" : "");
    }
#undef SIMPLE_MODE
#undef MOUSE_MODE
}

void
screen_set_mode(Screen *self, unsigned int mode) {
    set_mode_from_const(self, mode, true);
}

void
screen_decsace(Screen *self, unsigned int val) {
    self->modes.mDECSACE = val == 2 ? true : false;
}

void
screen_reset_mode(Screen *self, unsigned int mode) {
    set_mode_from_const(self, mode, false);
}

uint8_t
screen_current_key_encoding_flags(Screen *self) {
    for (unsigned i = arraysz(self->main_key_encoding_flags); i-- > 0; ) {
        if (self->key_encoding_flags[i] & 0x80) return self->key_encoding_flags[i] & 0x7f;
    }
    return 0;
}

void
screen_report_key_encoding_flags(Screen *self) {
    char buf[16] = {0};
    if (OPT(debug_keyboard)) {
        debug("\x1b[35mReporting key encoding flags: %u\x1b[39m\n", screen_current_key_encoding_flags(self));
    }
    snprintf(buf, sizeof(buf), "?%uu", screen_current_key_encoding_flags(self));
    write_escape_code_to_child(self, ESC_CSI, buf);
}

void
screen_set_key_encoding_flags(Screen *self, uint32_t val, uint32_t how) {
    unsigned idx = 0;
    for (unsigned i = arraysz(self->main_key_encoding_flags); i-- > 0; ) {
        if (self->key_encoding_flags[i] & 0x80) { idx = i; break; }
    }
    uint8_t q = val & 0x7f;
    if (how == 1) self->key_encoding_flags[idx] = q;
    else if (how == 2) self->key_encoding_flags[idx] |= q;
    else if (how == 3) self->key_encoding_flags[idx] &= ~q;
    self->key_encoding_flags[idx] |= 0x80;
    if (OPT(debug_keyboard)) {
        debug("\x1b[35mSet key encoding flags to: %u\x1b[39m\n", screen_current_key_encoding_flags(self));
    }
}

void
screen_push_key_encoding_flags(Screen *self, uint32_t val) {
    uint8_t q = val & 0x7f;
    const unsigned sz = arraysz(self->main_key_encoding_flags);
    unsigned current_idx = 0;
    for (unsigned i = arraysz(self->main_key_encoding_flags); i-- > 0; ) {
        if (self->key_encoding_flags[i] & 0x80) { current_idx = i; break; }
    }
    if (current_idx == sz - 1) memmove(self->key_encoding_flags, self->key_encoding_flags + 1, (sz - 1) * sizeof(self->main_key_encoding_flags[0]));
    else self->key_encoding_flags[current_idx++] |= 0x80;
    self->key_encoding_flags[current_idx] = 0x80 | q;
    if (OPT(debug_keyboard)) {
        debug("\x1b[35mPushed key encoding flags to: %u\x1b[39m\n", screen_current_key_encoding_flags(self));
    }
}

void
screen_pop_key_encoding_flags(Screen *self, uint32_t num) {
    for (unsigned i = arraysz(self->main_key_encoding_flags); num && i-- > 0; ) {
        if (self->key_encoding_flags[i] & 0x80) { num--; self->key_encoding_flags[i] = 0; }
    }
    if (OPT(debug_keyboard)) {
        debug("\x1b[35mPopped key encoding flags to: %u\x1b[39m\n", screen_current_key_encoding_flags(self));
    }
}

// }}}

// Cursor {{{

MouseShape
screen_pointer_shape(Screen *self) {
    if (self->linebuf == self->main_linebuf) {
        if (self->main_pointer_shape_stack.count) return self->main_pointer_shape_stack.stack[self->main_pointer_shape_stack.count-1];
    } else {
        if (self->alternate_pointer_shape_stack.count) return self->alternate_pointer_shape_stack.stack[self->alternate_pointer_shape_stack.count-1];
    }
    return INVALID_POINTER;
}

static PyObject*
current_pointer_shape(Screen *self, PyObject *args UNUSED) {
    MouseShape s = screen_pointer_shape(self);
    const char *ans = "0";
    switch(s) {
        case INVALID_POINTER: break;
        /* start enum to css (auto generated by gen-key-constants.py do not edit) */
        case DEFAULT_POINTER: ans = "default"; break;
        case TEXT_POINTER: ans = "text"; break;
        case POINTER_POINTER: ans = "pointer"; break;
        case HELP_POINTER: ans = "help"; break;
        case WAIT_POINTER: ans = "wait"; break;
        case PROGRESS_POINTER: ans = "progress"; break;
        case CROSSHAIR_POINTER: ans = "crosshair"; break;
        case CELL_POINTER: ans = "cell"; break;
        case VERTICAL_TEXT_POINTER: ans = "vertical-text"; break;
        case MOVE_POINTER: ans = "move"; break;
        case E_RESIZE_POINTER: ans = "e-resize"; break;
        case NE_RESIZE_POINTER: ans = "ne-resize"; break;
        case NW_RESIZE_POINTER: ans = "nw-resize"; break;
        case N_RESIZE_POINTER: ans = "n-resize"; break;
        case SE_RESIZE_POINTER: ans = "se-resize"; break;
        case SW_RESIZE_POINTER: ans = "sw-resize"; break;
        case S_RESIZE_POINTER: ans = "s-resize"; break;
        case W_RESIZE_POINTER: ans = "w-resize"; break;
        case EW_RESIZE_POINTER: ans = "ew-resize"; break;
        case NS_RESIZE_POINTER: ans = "ns-resize"; break;
        case NESW_RESIZE_POINTER: ans = "nesw-resize"; break;
        case NWSE_RESIZE_POINTER: ans = "nwse-resize"; break;
        case ZOOM_IN_POINTER: ans = "zoom-in"; break;
        case ZOOM_OUT_POINTER: ans = "zoom-out"; break;
        case ALIAS_POINTER: ans = "alias"; break;
        case COPY_POINTER: ans = "copy"; break;
        case NOT_ALLOWED_POINTER: ans = "not-allowed"; break;
        case NO_DROP_POINTER: ans = "no-drop"; break;
        case GRAB_POINTER: ans = "grab"; break;
        case GRABBING_POINTER: ans = "grabbing"; break;
/* end enum to css */
    }
    return PyUnicode_FromString(ans);
}

static PyObject*
change_pointer_shape(Screen *self, PyObject *args) {
    char op; const char *css_name, *b;
    if (!PyArg_ParseTuple(args, "ss", &b, &css_name)) return NULL;
    op = b[0];
    uint8_t *count, *stack;
    if (self->main_linebuf == self->linebuf) { count = &self->main_pointer_shape_stack.count; stack = self->main_pointer_shape_stack.stack; }
    else { count = &self->alternate_pointer_shape_stack.count; stack = self->alternate_pointer_shape_stack.stack; }
    if (op == '<') {
        if (*count) *count -= 1;
    } else {
        MouseShape s = INVALID_POINTER;
        if (css_name[0] == 0) s = INVALID_POINTER;
        /* start css to enum (auto generated by gen-key-constants.py do not edit) */
        else if (strcmp("default", css_name) == 0) s = DEFAULT_POINTER;
        else if (strcmp("text", css_name) == 0) s = TEXT_POINTER;
        else if (strcmp("pointer", css_name) == 0) s = POINTER_POINTER;
        else if (strcmp("help", css_name) == 0) s = HELP_POINTER;
        else if (strcmp("wait", css_name) == 0) s = WAIT_POINTER;
        else if (strcmp("progress", css_name) == 0) s = PROGRESS_POINTER;
        else if (strcmp("crosshair", css_name) == 0) s = CROSSHAIR_POINTER;
        else if (strcmp("cell", css_name) == 0) s = CELL_POINTER;
        else if (strcmp("vertical-text", css_name) == 0) s = VERTICAL_TEXT_POINTER;
        else if (strcmp("move", css_name) == 0) s = MOVE_POINTER;
        else if (strcmp("e-resize", css_name) == 0) s = E_RESIZE_POINTER;
        else if (strcmp("ne-resize", css_name) == 0) s = NE_RESIZE_POINTER;
        else if (strcmp("nw-resize", css_name) == 0) s = NW_RESIZE_POINTER;
        else if (strcmp("n-resize", css_name) == 0) s = N_RESIZE_POINTER;
        else if (strcmp("se-resize", css_name) == 0) s = SE_RESIZE_POINTER;
        else if (strcmp("sw-resize", css_name) == 0) s = SW_RESIZE_POINTER;
        else if (strcmp("s-resize", css_name) == 0) s = S_RESIZE_POINTER;
        else if (strcmp("w-resize", css_name) == 0) s = W_RESIZE_POINTER;
        else if (strcmp("ew-resize", css_name) == 0) s = EW_RESIZE_POINTER;
        else if (strcmp("ns-resize", css_name) == 0) s = NS_RESIZE_POINTER;
        else if (strcmp("nesw-resize", css_name) == 0) s = NESW_RESIZE_POINTER;
        else if (strcmp("nwse-resize", css_name) == 0) s = NWSE_RESIZE_POINTER;
        else if (strcmp("zoom-in", css_name) == 0) s = ZOOM_IN_POINTER;
        else if (strcmp("zoom-out", css_name) == 0) s = ZOOM_OUT_POINTER;
        else if (strcmp("alias", css_name) == 0) s = ALIAS_POINTER;
        else if (strcmp("copy", css_name) == 0) s = COPY_POINTER;
        else if (strcmp("not-allowed", css_name) == 0) s = NOT_ALLOWED_POINTER;
        else if (strcmp("no-drop", css_name) == 0) s = NO_DROP_POINTER;
        else if (strcmp("grab", css_name) == 0) s = GRAB_POINTER;
        else if (strcmp("grabbing", css_name) == 0) s = GRABBING_POINTER;
        else if (strcmp("left_ptr", css_name) == 0) s = DEFAULT_POINTER;
        else if (strcmp("xterm", css_name) == 0) s = TEXT_POINTER;
        else if (strcmp("ibeam", css_name) == 0) s = TEXT_POINTER;
        else if (strcmp("pointing_hand", css_name) == 0) s = POINTER_POINTER;
        else if (strcmp("hand2", css_name) == 0) s = POINTER_POINTER;
        else if (strcmp("hand", css_name) == 0) s = POINTER_POINTER;
        else if (strcmp("question_arrow", css_name) == 0) s = HELP_POINTER;
        else if (strcmp("whats_this", css_name) == 0) s = HELP_POINTER;
        else if (strcmp("clock", css_name) == 0) s = WAIT_POINTER;
        else if (strcmp("watch", css_name) == 0) s = WAIT_POINTER;
        else if (strcmp("half-busy", css_name) == 0) s = PROGRESS_POINTER;
        else if (strcmp("left_ptr_watch", css_name) == 0) s = PROGRESS_POINTER;
        else if (strcmp("tcross", css_name) == 0) s = CROSSHAIR_POINTER;
        else if (strcmp("plus", css_name) == 0) s = CELL_POINTER;
        else if (strcmp("cross", css_name) == 0) s = CELL_POINTER;
        else if (strcmp("fleur", css_name) == 0) s = MOVE_POINTER;
        else if (strcmp("pointer-move", css_name) == 0) s = MOVE_POINTER;
        else if (strcmp("right_side", css_name) == 0) s = E_RESIZE_POINTER;
        else if (strcmp("top_right_corner", css_name) == 0) s = NE_RESIZE_POINTER;
        else if (strcmp("top_left_corner", css_name) == 0) s = NW_RESIZE_POINTER;
        else if (strcmp("top_side", css_name) == 0) s = N_RESIZE_POINTER;
        else if (strcmp("bottom_right_corner", css_name) == 0) s = SE_RESIZE_POINTER;
        else if (strcmp("bottom_left_corner", css_name) == 0) s = SW_RESIZE_POINTER;
        else if (strcmp("bottom_side", css_name) == 0) s = S_RESIZE_POINTER;
        else if (strcmp("left_side", css_name) == 0) s = W_RESIZE_POINTER;
        else if (strcmp("sb_h_double_arrow", css_name) == 0) s = EW_RESIZE_POINTER;
        else if (strcmp("split_h", css_name) == 0) s = EW_RESIZE_POINTER;
        else if (strcmp("sb_v_double_arrow", css_name) == 0) s = NS_RESIZE_POINTER;
        else if (strcmp("split_v", css_name) == 0) s = NS_RESIZE_POINTER;
        else if (strcmp("size_bdiag", css_name) == 0) s = NESW_RESIZE_POINTER;
        else if (strcmp("size-bdiag", css_name) == 0) s = NESW_RESIZE_POINTER;
        else if (strcmp("size_fdiag", css_name) == 0) s = NWSE_RESIZE_POINTER;
        else if (strcmp("size-fdiag", css_name) == 0) s = NWSE_RESIZE_POINTER;
        else if (strcmp("zoom_in", css_name) == 0) s = ZOOM_IN_POINTER;
        else if (strcmp("zoom_out", css_name) == 0) s = ZOOM_OUT_POINTER;
        else if (strcmp("dnd-link", css_name) == 0) s = ALIAS_POINTER;
        else if (strcmp("dnd-copy", css_name) == 0) s = COPY_POINTER;
        else if (strcmp("forbidden", css_name) == 0) s = NOT_ALLOWED_POINTER;
        else if (strcmp("crossed_circle", css_name) == 0) s = NOT_ALLOWED_POINTER;
        else if (strcmp("dnd-no-drop", css_name) == 0) s = NO_DROP_POINTER;
        else if (strcmp("openhand", css_name) == 0) s = GRAB_POINTER;
        else if (strcmp("hand1", css_name) == 0) s = GRAB_POINTER;
        else if (strcmp("closedhand", css_name) == 0) s = GRABBING_POINTER;
        else if (strcmp("dnd-none", css_name) == 0) s = GRABBING_POINTER;
/* end css to enum */
        if (s == INVALID_POINTER && css_name[0] != 0) { PyErr_Format(PyExc_KeyError, "Not a known pointer shape: %s", css_name); return NULL; }
        if (op == '=') {
            if (!*count) *count += 1;
            stack[*count - 1] = s;
        } else if (op == '>') {
            if ((*count + 1u) >= arraysz(self->main_pointer_shape_stack.stack)) {
                remove_i_from_array(stack, 0, *count);
            }
            *count += 1;
            stack[*count - 1] = s;
        } else {
            PyErr_SetString(PyExc_KeyError, "Not a known stack operation");
            return NULL;
        }
    }
    Py_RETURN_NONE;
}

unsigned long
screen_current_char_width(Screen *self) {
    unsigned long ans = 1;
    if (self->cursor->x < self->columns - 1 && self->cursor->y < self->lines) {
        ans = linebuf_char_width_at(self->linebuf, self->cursor->x, self->cursor->y);
    }
    return ans;
}

bool
screen_is_cursor_visible(const Screen *self) {
    return self->modes.mDECTCEM;
}

void
screen_backspace(Screen *self) {
    screen_cursor_back(self, 1, -1);
}

void
screen_tab(Screen *self) {
    // Move to the next tab space, or the end of the screen if there aren't anymore left.
    unsigned int found = 0;
    for (unsigned int i = self->cursor->x + 1; i < self->columns; i++) {
        if (self->tabstops[i]) { found = i; break; }
    }
    if (!found) found = self->columns - 1;
    if (found != self->cursor->x) {
        if (self->cursor->x < self->columns) {
            linebuf_init_line(self->linebuf, self->cursor->y);
            combining_type diff = found - self->cursor->x;
            CPUCell *cpu_cell = self->linebuf->line->cpu_cells + self->cursor->x;
            bool ok = true;
            for (combining_type i = 0; i < diff; i++) {
                CPUCell *c = cpu_cell + i;
                if (c->ch != ' ' && c->ch != 0) { ok = false; break; }
            }
            if (ok) {
                for (combining_type i = 0; i < diff; i++) {
                    CPUCell *c = cpu_cell + i;
                    c->ch = ' '; zero_at_ptr_count(c->cc_idx, arraysz(c->cc_idx));
                }
                cpu_cell->ch = '\t';
                cpu_cell->cc_idx[0] = diff;
            }
        }
        self->cursor->x = found;
    }
}

void
screen_backtab(Screen *self, unsigned int count) {
    // Move back count tabs
    if (!count) count = 1;
    int i;
    while (count > 0 && self->cursor->x > 0) {
        count--;
        for (i = self->cursor->x - 1; i >= 0; i--) {
            if (self->tabstops[i]) { self->cursor->x = i; break; }
        }
        if (i <= 0) self->cursor->x = 0;
    }
}

void
screen_clear_tab_stop(Screen *self, unsigned int how) {
    switch(how) {
        case 0:
            if (self->cursor->x < self->columns) self->tabstops[self->cursor->x] = false;
            break;
        case 2:
            break;  // no-op
        case 3:
            for (unsigned int i = 0; i < self->columns; i++) self->tabstops[i] = false;
            break;
        default:
            log_error("%s %s %u", ERROR_PREFIX, "Unsupported clear tab stop mode: ", how);
            break;
    }
}

void
screen_set_tab_stop(Screen *self) {
    if (self->cursor->x < self->columns)
        self->tabstops[self->cursor->x] = true;
}

void
screen_cursor_back(Screen *self, unsigned int count/*=1*/, int move_direction/*=-1*/) {
    if (count == 0) count = 1;
    if (move_direction < 0 && count > self->cursor->x) self->cursor->x = 0;
    else self->cursor->x += move_direction * count;
    screen_ensure_bounds(self, false, cursor_within_margins(self));
}

void
screen_cursor_forward(Screen *self, unsigned int count/*=1*/) {
    screen_cursor_back(self, count, 1);
}

void
screen_cursor_up(Screen *self, unsigned int count/*=1*/, bool do_carriage_return/*=false*/, int move_direction/*=-1*/) {
    bool in_margins = cursor_within_margins(self);
    if (count == 0) count = 1;
    if (move_direction < 0 && count > self->cursor->y) self->cursor->y = 0;
    else self->cursor->y += move_direction * count;
    if (do_carriage_return) self->cursor->x = 0;
    screen_ensure_bounds(self, true, in_margins);
}

void
screen_cursor_up1(Screen *self, unsigned int count/*=1*/) {
    screen_cursor_up(self, count, true, -1);
}

void
screen_cursor_down(Screen *self, unsigned int count/*=1*/) {
    screen_cursor_up(self, count, false, 1);
}

void
screen_cursor_down1(Screen *self, unsigned int count/*=1*/) {
    screen_cursor_up(self, count, true, 1);
}

void
screen_cursor_to_column(Screen *self, unsigned int column) {
    unsigned int x = MAX(column, 1u) - 1;
    if (x != self->cursor->x) {
        self->cursor->x = x;
        screen_ensure_bounds(self, false, cursor_within_margins(self));
    }
}

#define INDEX_UP \
    linebuf_index(self->linebuf, top, bottom); \
    INDEX_GRAPHICS(-1) \
    if (self->linebuf == self->main_linebuf && self->margin_top == 0) { \
        /* Only add to history when no top margin has been set */ \
        linebuf_init_line(self->linebuf, bottom); \
        historybuf_add_line(self->historybuf, self->linebuf->line, &self->as_ansi_buf); \
        self->history_line_added_count++; \
        if (self->last_visited_prompt.is_set) { \
            if (self->last_visited_prompt.scrolled_by < self->historybuf->count) self->last_visited_prompt.scrolled_by++; \
            else self->last_visited_prompt.is_set = false; \
        } \
    } \
    linebuf_clear_line(self->linebuf, bottom, true); \
    self->is_dirty = true; \
    index_selection(self, &self->selections, true);

void
screen_index(Screen *self) {
    // Move cursor down one line, scrolling screen if needed
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (self->cursor->y == bottom) {
        INDEX_UP;
    } else screen_cursor_down(self, 1);
}

void
screen_scroll(Screen *self, unsigned int count) {
    // Scroll the screen up by count lines, not moving the cursor
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    while (count > 0) {
        count--;
        INDEX_UP;
    }
}

void
screen_reverse_index(Screen *self) {
    // Move cursor up one line, scrolling screen if needed
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (self->cursor->y == top) {
        INDEX_DOWN;
    } else screen_cursor_up(self, 1, false, -1);
}

static void
_reverse_scroll(Screen *self, unsigned int count, bool fill_from_scrollback) {
    // Scroll the screen down by count lines, not moving the cursor
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    fill_from_scrollback = fill_from_scrollback && self->linebuf == self->main_linebuf;
    if (fill_from_scrollback) {
        unsigned limit = MAX(self->lines, self->historybuf->count);
        count = MIN(limit, count);
    } else count = MIN(self->lines, count);
    while (count-- > 0) {
        bool copied = false;
        if (fill_from_scrollback) copied = historybuf_pop_line(self->historybuf, self->alt_linebuf->line);
        INDEX_DOWN;
        if (copied) linebuf_copy_line_to(self->main_linebuf, self->alt_linebuf->line, 0);
    }
}

void
screen_reverse_scroll(Screen *self, unsigned int count) {
    _reverse_scroll(self, count, false);
}

void
screen_reverse_scroll_and_fill_from_scrollback(Screen *self, unsigned int count) {
    _reverse_scroll(self, count, true);
}


void
screen_carriage_return(Screen *self) {
    if (self->cursor->x != 0) {
        self->cursor->x = 0;
    }
}

void
screen_linefeed(Screen *self) {
    bool in_margins = cursor_within_margins(self);
    screen_index(self);
    if (self->modes.mLNM) screen_carriage_return(self);
    screen_ensure_bounds(self, false, in_margins);
}

#define buffer_push(self, ans) { \
    ans = (self)->buf + (((self)->start_of_data + (self)->count) % SAVEPOINTS_SZ); \
    if ((self)->count == SAVEPOINTS_SZ) (self)->start_of_data = ((self)->start_of_data + 1) % SAVEPOINTS_SZ; \
    else (self)->count++; \
}

#define buffer_pop(self, ans) { \
    if ((self)->count == 0) ans = NULL; \
    else { \
        (self)->count--; \
        ans = (self)->buf + (((self)->start_of_data + (self)->count) % SAVEPOINTS_SZ); \
    } \
}

void
screen_save_cursor(Screen *self) {
    Savepoint *sp = self->linebuf == self->main_linebuf ? &self->main_savepoint : &self->alt_savepoint;
    cursor_copy_to(self->cursor, &(sp->cursor));
    sp->mDECOM = self->modes.mDECOM;
    sp->mDECAWM = self->modes.mDECAWM;
    sp->mDECSCNM = self->modes.mDECSCNM;
    sp->is_valid = true;
}

static void
copy_specific_mode(Screen *self, unsigned int mode, const ScreenModes *src, ScreenModes *dest) {
#define SIMPLE_MODE(name) case name: dest->m##name = src->m##name; break;
#define SIDE_EFFECTS(name) case name: if (do_side_effects) set_mode_from_const(self, name, src->m##name); else dest->m##name = src->m##name; break;

    const bool do_side_effects = dest == &self->modes;

    switch(mode) {
        SIMPLE_MODE(LNM)  // kitty extension
        SIMPLE_MODE(IRM)  // kitty extension
        SIMPLE_MODE(DECARM)
        SIMPLE_MODE(BRACKETED_PASTE)
        SIMPLE_MODE(FOCUS_TRACKING)
        SIMPLE_MODE(DECCKM)
        SIMPLE_MODE(DECTCEM)
        SIMPLE_MODE(DECAWM)
        case MOUSE_BUTTON_TRACKING: case MOUSE_MOTION_TRACKING: case MOUSE_MOVE_TRACKING:
            dest->mouse_tracking_mode = src->mouse_tracking_mode; break;
        case MOUSE_UTF8_MODE: case MOUSE_SGR_MODE: case MOUSE_URXVT_MODE:
            dest->mouse_tracking_protocol = src->mouse_tracking_protocol; break;
        case DECSCLM:
        case DECNRCM:
            break;  // we ignore these modes
        case DECSCNM:
            if (dest->mDECSCNM != src->mDECSCNM) {
                dest->mDECSCNM = src->mDECSCNM;
                if (do_side_effects) self->is_dirty = true;
            }
            break;
        SIDE_EFFECTS(DECOM)
        SIDE_EFFECTS(DECCOLM)
    }
#undef SIMPLE_MODE
#undef SIDE_EFFECTS
}

void
screen_save_mode(Screen *self, unsigned int mode) { // XTSAVE
    copy_specific_mode(self, mode, &self->modes, &self->saved_modes);
}

void
screen_restore_mode(Screen *self, unsigned int mode) { // XTRESTORE
    copy_specific_mode(self, mode, &self->saved_modes, &self->modes);
}

static void
copy_specific_modes(Screen *self, const ScreenModes *src, ScreenModes *dest) {
    copy_specific_mode(self, LNM, src, dest);
    copy_specific_mode(self, IRM, src, dest);
    copy_specific_mode(self, DECARM, src, dest);
    copy_specific_mode(self, BRACKETED_PASTE, src, dest);
    copy_specific_mode(self, FOCUS_TRACKING, src, dest);
    copy_specific_mode(self, DECCKM, src, dest);
    copy_specific_mode(self, DECTCEM, src, dest);
    copy_specific_mode(self, DECAWM, src, dest);
    copy_specific_mode(self, MOUSE_BUTTON_TRACKING, src, dest);
    copy_specific_mode(self, MOUSE_UTF8_MODE, src, dest);
    copy_specific_mode(self, DECSCNM, src, dest);
}

void
screen_save_modes(Screen *self) {
    // kitty extension to XTSAVE that saves a bunch of no side-effect modes
    copy_specific_modes(self, &self->modes, &self->saved_modes);
}

void
screen_restore_cursor(Screen *self) {
    Savepoint *sp = self->linebuf == self->main_linebuf ? &self->main_savepoint : &self->alt_savepoint;
    if (!sp->is_valid) {
        screen_cursor_position(self, 1, 1);
        screen_reset_mode(self, DECOM);
        screen_reset_mode(self, DECSCNM);
    } else {
        set_mode_from_const(self, DECOM, sp->mDECOM);
        set_mode_from_const(self, DECAWM, sp->mDECAWM);
        set_mode_from_const(self, DECSCNM, sp->mDECSCNM);
        cursor_copy_to(&(sp->cursor), self->cursor);
        screen_ensure_bounds(self, false, false);
    }
}

void
screen_restore_modes(Screen *self) {
    // kitty extension to XTRESTORE that saves a bunch of no side-effect modes
    copy_specific_modes(self, &self->saved_modes, &self->modes);
}

void
screen_ensure_bounds(Screen *self, bool force_use_margins/*=false*/, bool in_margins) {
    unsigned int top, bottom;
    if (in_margins && (force_use_margins || self->modes.mDECOM)) {
        top = self->margin_top; bottom = self->margin_bottom;
    } else {
        top = 0; bottom = self->lines - 1;
    }
    self->cursor->x = MIN(self->cursor->x, self->columns - 1);
    self->cursor->y = MAX(top, MIN(self->cursor->y, bottom));
}

void
screen_cursor_position(Screen *self, unsigned int line, unsigned int column) {
    bool in_margins = cursor_within_margins(self);
    line = (line == 0 ? 1 : line) - 1;
    column = (column == 0 ? 1: column) - 1;
    if (self->modes.mDECOM) {
        line += self->margin_top;
        line = MAX(self->margin_top, MIN(line, self->margin_bottom));
    }
    self->cursor->x = column; self->cursor->y = line;
    screen_ensure_bounds(self, false, in_margins);
}

void
screen_cursor_to_line(Screen *self, unsigned int line) {
    screen_cursor_position(self, line, self->cursor->x + 1);
}

int
screen_cursor_at_a_shell_prompt(const Screen *self) {
    if (self->cursor->y >= self->lines || self->linebuf != self->main_linebuf || !screen_is_cursor_visible(self)) return -1;
    for (index_type y=self->cursor->y + 1; y-- > 0; ) {
        switch(self->linebuf->line_attrs[y].prompt_kind) {
            case OUTPUT_START:
                return -1;
            case PROMPT_START:
            case SECONDARY_PROMPT:
                return y;
            case UNKNOWN_PROMPT_KIND:
                break;
        }
    }
    return -1;
}

bool
screen_fake_move_cursor_to_position(Screen *self, index_type start_x, index_type start_y) {
    SelectionBoundary a = {.x=start_x, .y=start_y}, b = {.x=self->cursor->x, .y=self->cursor->y};
    SelectionBoundary *start, *end; int key;
    if (a.y < b.y || (a.y == b.y && a.x < b.x)) { start = &a; end = &b; key = GLFW_FKEY_LEFT; }
    else { start = &b; end = &a; key = GLFW_FKEY_RIGHT; }
    unsigned int count = 0;

    for (unsigned y = start->y, x = start->x; y <= end->y && y < self->lines; y++) {
        unsigned x_limit = y == end->y ? end->x : self->columns;
        x_limit = MIN(x_limit, self->columns);
        bool found_non_empty_cell = false;
        while (x < x_limit) {
            unsigned int w = linebuf_char_width_at(self->linebuf, x, y);
            if (w == 0) {
                // we only stop counting the cells in the line at an empty cell
                // if at least one non-empty cell is found. zsh uses empty cells
                // between the end of the text ad the right prompt. fish uses empty
                // cells at the start of a line when editing multiline text
                if (!found_non_empty_cell) { x++; continue; }
                count += 1;
                break;
            }
            found_non_empty_cell = true;
            x += w;
            count += 1;  // zsh requires a single arrow press to move past dualwidth chars
        }
        if (!found_non_empty_cell) count++;  // blank line
        x = 0;
    }
    if (count) {
        GLFWkeyevent ev = { .key = key, .action = GLFW_PRESS };
        char output[KEY_BUFFER_SIZE+1] = {0};
        int num = encode_glfw_key_event(&ev, false, 0, output);
        if (num != SEND_TEXT_TO_CHILD) {
            for (unsigned i = 0; i < count; i++) write_to_child(self, output, num);
        }
    }
    return count > 0;
}

// }}}

// Editing {{{

void
screen_erase_in_line(Screen *self, unsigned int how, bool private) {
    /*Erases a line in a specific way.

        :param int how: defines the way the line should be erased in:

            * ``0`` -- Erases from cursor to end of line, including cursor
              position.
            * ``1`` -- Erases from beginning of line to cursor,
              including cursor position.
            * ``2`` -- Erases complete line.
        :param bool private: when ``True`` character attributes are left
                             unchanged.
        */
    unsigned int s = 0, n = 0;
    switch(how) {
        case 0:
            s = self->cursor->x;
            n = self->columns - self->cursor->x;
            break;
        case 1:
            n = self->cursor->x + 1;
            break;
        case 2:
            n = self->columns;
            break;
        default:
            break;
    }
    if (n > 0) {
        screen_dirty_line_graphics(self, self->cursor->y, self->cursor->y, self->linebuf == self->main_linebuf);
        linebuf_init_line(self->linebuf, self->cursor->y);
        if (private) {
            line_clear_text(self->linebuf->line, s, n, BLANK_CHAR);
        } else {
            line_apply_cursor(self->linebuf->line, self->cursor, s, n, true);
        }
        self->is_dirty = true;
        if (selection_has_screen_line(&self->selections, self->cursor->y)) clear_selection(&self->selections);
        linebuf_mark_line_dirty(self->linebuf, self->cursor->y);
    }
}

static void
dirty_scroll(Screen *self) {
    self->scroll_changed = true;
    screen_pause_rendering(self, false, 0);
}

static void
screen_clear_scrollback(Screen *self) {
    historybuf_clear(self->historybuf);
    if (self->scrolled_by != 0) {
        self->scrolled_by = 0;
        dirty_scroll(self);
    }
}

static Line* visual_line_(Screen *self, int y_);

static void
screen_move_into_scrollback(Screen *self) {
    if (self->linebuf != self->main_linebuf || self->margin_top != 0 || self->margin_bottom != self->lines - 1) return;
    unsigned int num_of_lines_to_move = self->lines;
    while (num_of_lines_to_move) {
        Line *line = visual_line_(self, num_of_lines_to_move-1);
        if (!line_is_empty(line)) break;
        num_of_lines_to_move--;
    }
    if (num_of_lines_to_move) {
        unsigned int top, bottom;
        for (; num_of_lines_to_move; num_of_lines_to_move--) {
            top = 0, bottom = num_of_lines_to_move - 1;
            INDEX_UP
        }
    }
}

void
screen_erase_in_display(Screen *self, unsigned int how, bool private) {
    /* Erases display in a specific way.

        :param int how: defines the way the screen should be erased:

            * ``0`` -- Erases from cursor to end of screen, including
              cursor position.
            * ``1`` -- Erases from beginning of screen to cursor,
              including cursor position.
            * ``2`` -- Erases complete display. All lines are erased
              and changed to single-width. Cursor does not move.
            * ``22`` -- Copy screen contents into scrollback if in main screen,
              then do the same as ``2``.
            * ``3`` -- Erase complete display and scrollback buffer as well.
        :param bool private: when ``True`` character attributes are left unchanged
    */
    unsigned int a, b;
    switch(how) {
        case 0:
            a = self->cursor->y + 1; b = self->lines; break;
        case 1:
            a = 0; b = self->cursor->y; break;
        case 22:
            screen_move_into_scrollback(self);
            how = 2;
            /* fallthrough */
        case 2:
        case 3:
            grman_clear(self->grman, how == 3, self->cell_size);
            a = 0; b = self->lines; break;
        default:
            return;
    }
    if (b > a) {
        if (how != 3) screen_dirty_line_graphics(self, a, b, self->linebuf == self->main_linebuf);
        for (unsigned int i=a; i < b; i++) {
            linebuf_init_line(self->linebuf, i);
            if (private) {
                line_clear_text(self->linebuf->line, 0, self->columns, BLANK_CHAR);
                linebuf_set_last_char_as_continuation(self->linebuf, i, false);
            } else {
                line_apply_cursor(self->linebuf->line, self->cursor, 0, self->columns, true);
            }
            linebuf_clear_attrs_and_dirty(self->linebuf, i);
        }
        self->is_dirty = true;
        clear_selection(&self->selections);
    }
    if (how < 2) {
        screen_erase_in_line(self, how, private);
        if (how == 1) linebuf_clear_attrs_and_dirty(self->linebuf, self->cursor->y);
    }
    if (how == 3 && self->linebuf == self->main_linebuf) {
        screen_clear_scrollback(self);
    }
}

void
screen_insert_lines(Screen *self, unsigned int count) {
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (count == 0) count = 1;
    if (top <= self->cursor->y && self->cursor->y <= bottom) {
        screen_dirty_line_graphics(self, top, bottom, self->linebuf == self->main_linebuf);
        linebuf_insert_lines(self->linebuf, count, self->cursor->y, bottom);
        self->is_dirty = true;
        clear_selection(&self->selections);
        screen_carriage_return(self);
    }
}

static void
screen_scroll_until_cursor_prompt(Screen *self) {
    bool in_margins = cursor_within_margins(self);
    int q = screen_cursor_at_a_shell_prompt(self);
    unsigned int y = q > -1 ? (unsigned int)q : self->cursor->y;
    unsigned int num_lines_to_scroll = MIN(self->margin_bottom, y);
    unsigned int final_y = num_lines_to_scroll <= self->cursor->y ? self->cursor->y - num_lines_to_scroll : 0;
    self->cursor->y = self->margin_bottom;
    while (num_lines_to_scroll--) screen_index(self);
    self->cursor->y = final_y;
    screen_ensure_bounds(self, false, in_margins);
}

void
screen_delete_lines(Screen *self, unsigned int count) {
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (count == 0) count = 1;
    if (top <= self->cursor->y && self->cursor->y <= bottom) {
        screen_dirty_line_graphics(self, top, bottom, self->linebuf == self->main_linebuf);
        linebuf_delete_lines(self->linebuf, count, self->cursor->y, bottom);
        self->is_dirty = true;
        clear_selection(&self->selections);
        screen_carriage_return(self);
    }
}

void
screen_insert_characters(Screen *self, unsigned int count) {
    const unsigned int bottom = self->lines ? self->lines - 1 : 0;
    if (count == 0) count = 1;
    if (self->cursor->y <= bottom) {
        unsigned int x = self->cursor->x;
        unsigned int num = MIN(self->columns - x, count);
        linebuf_init_line(self->linebuf, self->cursor->y);
        line_right_shift(self->linebuf->line, x, num);
        line_apply_cursor(self->linebuf->line, self->cursor, x, num, true);
        linebuf_mark_line_dirty(self->linebuf, self->cursor->y);
        self->is_dirty = true;
        if (selection_has_screen_line(&self->selections, self->cursor->y)) clear_selection(&self->selections);
    }
}

void
screen_repeat_character(Screen *self, unsigned int count) {
    if (self->last_graphic_char) {
        if (count == 0) count = 1;
        unsigned int num = MIN(count, CSI_REP_MAX_REPETITIONS);
        alignas(64) uint32_t buf[64];
        for (unsigned i = 0; i < arraysz(buf); i++) buf[i] = self->last_graphic_char;
        for (unsigned i = 0; i < num; i += arraysz(buf)) screen_draw_text(self, buf, MIN(num - i, arraysz(buf)));
    }
}

void
screen_delete_characters(Screen *self, unsigned int count) {
    // Delete characters, later characters are moved left
    const unsigned int bottom = self->lines ? self->lines - 1 : 0;
    if (count == 0) count = 1;
    if (self->cursor->y <= bottom) {
        unsigned int x = self->cursor->x;
        unsigned int num = MIN(self->columns - x, count);
        linebuf_init_line(self->linebuf, self->cursor->y);
        left_shift_line(self->linebuf->line, x, num);
        line_apply_cursor(self->linebuf->line, self->cursor, self->columns - num, num, true);
        linebuf_mark_line_dirty(self->linebuf, self->cursor->y);
        self->is_dirty = true;
        if (selection_has_screen_line(&self->selections, self->cursor->y)) clear_selection(&self->selections);
    }
}

void
screen_erase_characters(Screen *self, unsigned int count) {
    // Delete characters replacing them by spaces
    if (count == 0) count = 1;
    unsigned int x = self->cursor->x;
    unsigned int num = MIN(self->columns - x, count);
    linebuf_init_line(self->linebuf, self->cursor->y);
    line_apply_cursor(self->linebuf->line, self->cursor, x, num, true);
    linebuf_mark_line_dirty(self->linebuf, self->cursor->y);
    self->is_dirty = true;
    if (selection_has_screen_line(&self->selections, self->cursor->y)) clear_selection(&self->selections);
}

// }}}

// Device control {{{

bool
screen_invert_colors(Screen *self) {
    return self->paused_rendering.expires_at ? self->paused_rendering.inverted : (self->modes.mDECSCNM ? true : false);
}

void
screen_bell(Screen *self) {
    if (self->ignore_bells.start) {
        monotonic_t now = monotonic();
        if (now < self->ignore_bells.start + self->ignore_bells.duration) {
            self->ignore_bells.start = now;
            return;
        }
        self->ignore_bells.start = 0;
    }
    request_window_attention(self->window_id, OPT(enable_audio_bell));
    if (OPT(visual_bell_duration) > 0.0f) self->start_visual_bell_at = monotonic();
    CALLBACK("on_bell", NULL);
}

void
report_device_attributes(Screen *self, unsigned int mode, char start_modifier) {
    if (mode == 0) {
        switch(start_modifier) {
            case 0:
                write_escape_code_to_child(self, ESC_CSI, "?62;c");
                break;
            case '>':
                write_escape_code_to_child(self, ESC_CSI, ">1;" xstr(PRIMARY_VERSION) ";" xstr(SECONDARY_VERSION) "c");  // VT-220 + primary version + secondary version
                break;
        }
    }
}

void
screen_xtversion(Screen *self, unsigned int mode) {
    if (mode == 0) {
        write_escape_code_to_child(self, ESC_DCS, ">|kitty(" XT_VERSION ")");
    }
}

void
screen_report_size(Screen *self, unsigned int which) {
    char buf[32] = {0};
    unsigned int code = 0;
    unsigned int width = 0, height = 0;
    switch(which) {
        case 14:
            code = 4;
            width = self->cell_size.width * self->columns;
            height = self->cell_size.height * self->lines;
            break;
        case 16:
            code = 6;
            width = self->cell_size.width;
            height = self->cell_size.height;
            break;
        case 18:
            code = 8;
            width = self->columns;
            height = self->lines;
            break;
    }
    if (code) {
        snprintf(buf, sizeof(buf), "%u;%u;%ut", code, height, width);
        write_escape_code_to_child(self, ESC_CSI, buf);
    }
}

void
screen_manipulate_title_stack(Screen *self, unsigned int op, unsigned int which) {
    CALLBACK("manipulate_title_stack", "OOO",
        op == 23 ? Py_True : Py_False,
        which == 0 || which == 2 ? Py_True : Py_False,
        which == 0 || which == 1 ? Py_True : Py_False
    );
}

void
report_device_status(Screen *self, unsigned int which, bool private) {
    // We don't implement the private device status codes, since I haven't come
    // across any programs that use them
    unsigned int x, y;
    static char buf[64];
    switch(which) {
        case 5:  // device status
            write_escape_code_to_child(self, ESC_CSI, "0n");
            break;
        case 6:  // cursor position
            x = self->cursor->x; y = self->cursor->y;
            if (x >= self->columns) {
                if (y < self->lines - 1) { x = 0; y++; }
                else x--;
            }
            if (self->modes.mDECOM) y -= MAX(y, self->margin_top);
            // 1-based indexing
            int sz = snprintf(buf, sizeof(buf) - 1, "%s%u;%uR", (private ? "?": ""), y + 1, x + 1);
            if (sz > 0) write_escape_code_to_child(self, ESC_CSI, buf);
            break;
    }
}

void
report_mode_status(Screen *self, unsigned int which, bool private) {
    unsigned int q = private ? which << 5 : which;
    unsigned int ans = 0;
    char buf[50] = {0};
    switch(q) {
#define KNOWN_MODE(x) \
        case x: \
            ans = self->modes.m##x ? 1 : 2; break;
        KNOWN_MODE(LNM);
        KNOWN_MODE(IRM);
        KNOWN_MODE(DECTCEM);
        KNOWN_MODE(DECSCNM);
        KNOWN_MODE(DECOM);
        KNOWN_MODE(DECAWM);
        KNOWN_MODE(DECCOLM);
        KNOWN_MODE(DECARM);
        KNOWN_MODE(DECCKM);
        KNOWN_MODE(BRACKETED_PASTE);
        KNOWN_MODE(FOCUS_TRACKING);
#undef KNOWN_MODE
        case ALTERNATE_SCREEN:
            ans = self->linebuf == self->alt_linebuf ? 1 : 2; break;
        case MOUSE_BUTTON_TRACKING:
            ans = self->modes.mouse_tracking_mode == BUTTON_MODE ? 1 : 2; break;
        case MOUSE_MOTION_TRACKING:
            ans = self->modes.mouse_tracking_mode == MOTION_MODE ? 1 : 2; break;
        case MOUSE_MOVE_TRACKING:
            ans = self->modes.mouse_tracking_mode == ANY_MODE ? 1 : 2; break;
        case MOUSE_SGR_MODE:
            ans = self->modes.mouse_tracking_protocol == SGR_PROTOCOL ? 1 : 2; break;
        case MOUSE_UTF8_MODE:
            ans = self->modes.mouse_tracking_protocol == UTF8_PROTOCOL ? 1 : 2; break;
        case MOUSE_SGR_PIXEL_MODE:
            ans = self->modes.mouse_tracking_protocol == SGR_PIXEL_PROTOCOL ? 1 : 2; break;
        case PENDING_UPDATE:
            ans = self->paused_rendering.expires_at ? 1 : 2; break;
    }
    int sz = snprintf(buf, sizeof(buf) - 1, "%s%u;%u$y", (private ? "?" : ""), which, ans);
    if (sz > 0) write_escape_code_to_child(self, ESC_CSI, buf);
}

void
screen_set_margins(Screen *self, unsigned int top, unsigned int bottom) {
    if (!top) top = 1;
    if (!bottom) bottom = self->lines;
    top = MIN(self->lines, top);
    bottom = MIN(self->lines, bottom);
    top--; bottom--;  // 1 based indexing
    if (bottom > top) {
        // Even though VT102 and VT220 require DECSTBM to ignore regions
        // of width less than 2, some programs (like aptitude for example)
        // rely on it. Practicality beats purity.
        self->margin_top = top; self->margin_bottom = bottom;
        // The cursor moves to the home position when the top and
        // bottom margins of the scrolling region (DECSTBM) changes.
        screen_cursor_position(self, 1, 1);
    }
}

void
screen_set_cursor(Screen *self, unsigned int mode, uint8_t secondary) {
    uint8_t shape; bool blink;
    switch(secondary) {
        case 0: // DECLL
            break;
        case '"':  // DECCSA
            break;
        case ' ': // DECSCUSR
            shape = 0; blink = true;
            if (mode > 0) {
                blink = mode % 2;
                shape = (mode < 3) ? CURSOR_BLOCK : (mode < 5) ? CURSOR_UNDERLINE : (mode < 7) ? CURSOR_BEAM : NO_CURSOR_SHAPE;
            }
            if (shape != self->cursor->shape || blink != !self->cursor->non_blinking) {
                self->cursor->shape = shape; self->cursor->non_blinking = !blink;
            }
            break;
    }
}

void
set_title(Screen *self, PyObject *title) {
    CALLBACK("title_changed", "O", title);
}

void
desktop_notify(Screen *self, unsigned int osc_code, PyObject *data) {
    CALLBACK("desktop_notify", "IO", osc_code, data);
}

void
set_icon(Screen *self, PyObject *icon) {
    CALLBACK("icon_changed", "O", icon);
}

void
set_dynamic_color(Screen *self, unsigned int code, PyObject *color) {
    if (color == NULL) { CALLBACK("set_dynamic_color", "I", code); }
    else { CALLBACK("set_dynamic_color", "IO", code, color); }
}

void
clipboard_control(Screen *self, int code, PyObject *data) {
    if (code == 52 || code == -52) { CALLBACK("clipboard_control", "OO", data, code == -52 ? Py_True: Py_False); }
    else { CALLBACK("clipboard_control", "OO", data, Py_None);}
}

void
file_transmission(Screen *self, PyObject *data) {
    CALLBACK("file_transmission", "O", data);
}

static void
parse_prompt_mark(Screen *self, char *buf, PromptKind *pk) {
    char *saveptr, *str = buf;
    while (true) {
        const char *token = strtok_r(str, ";", &saveptr); str = NULL;
        if (token == NULL) return;
        if (strcmp(token, "k=s") == 0) *pk = SECONDARY_PROMPT;
        else if (strcmp(token, "redraw=0") == 0) self->prompt_settings.redraws_prompts_at_all = 0;
    }
}

void
shell_prompt_marking(Screen *self, char *buf) {
    if (self->cursor->y < self->lines) {
        char ch = buf[0];
        switch (ch) {
            case 'A': {
                PromptKind pk = PROMPT_START;
                self->prompt_settings.redraws_prompts_at_all = 1;
                parse_prompt_mark(self, buf+1, &pk);
                self->linebuf->line_attrs[self->cursor->y].prompt_kind = pk;
                if (pk == PROMPT_START)
                    CALLBACK("cmd_output_marking", "O", Py_False);
            } break;
            case 'C':
                self->linebuf->line_attrs[self->cursor->y].prompt_kind = OUTPUT_START;
                CALLBACK("cmd_output_marking", "O", Py_True);
                break;
        }
    }
    if (global_state.debug_rendering) fprintf(stderr, "prompt_marking: x=%d y=%d op=%s\n", self->cursor->x, self->cursor->y, buf);
}

static bool
screen_history_scroll_to_prompt(Screen *self, int num_of_prompts_to_jump) {
    if (self->linebuf != self->main_linebuf) return false;
    unsigned int old = self->scrolled_by;
    if (num_of_prompts_to_jump == 0) {
        if (!self->last_visited_prompt.is_set || self->last_visited_prompt.scrolled_by > self->historybuf->count || self->last_visited_prompt.y >= self->lines) return false;
        self->scrolled_by = self->last_visited_prompt.scrolled_by;
    } else {
        int delta = num_of_prompts_to_jump < 0 ? -1 : 1;
        num_of_prompts_to_jump = num_of_prompts_to_jump < 0 ? -num_of_prompts_to_jump : num_of_prompts_to_jump;
        int y = -self->scrolled_by;
#define ensure_y_ok if (y >= (int)self->lines || -y > (int)self->historybuf->count) return false;
        ensure_y_ok;
        while (num_of_prompts_to_jump) {
            y += delta;
            ensure_y_ok;
            if (range_line_(self, y)->attrs.prompt_kind == PROMPT_START) {
                num_of_prompts_to_jump--;
            }
        }
#undef ensure_y_ok
        self->scrolled_by = y >= 0 ? 0 : -y;
        screen_set_last_visited_prompt(self, 0);
    }
    if (old != self->scrolled_by) dirty_scroll(self);
    return old != self->scrolled_by;
}

void
set_color_table_color(Screen *self, unsigned int code, PyObject *color) {
    if (color == NULL) { CALLBACK("set_color_table_color", "I", code); }
    else { CALLBACK("set_color_table_color", "IO", code, color); }
}

void
process_cwd_notification(Screen *self, unsigned int code, const char *data, size_t sz) {
    if (code == 7) {
        PyObject *x = PyBytes_FromStringAndSize(data, sz);
        if (x) {
            Py_CLEAR(self->last_reported_cwd);
            self->last_reported_cwd = x;
        } else { PyErr_Clear(); }
    }  // we ignore OSC 6 document reporting as we dont have a use for it
}

bool
screen_send_signal_for_key(Screen *self, char key) {
    int ret = 0;
    if (self->callbacks != Py_None) {
        int cchar = key;
        PyObject *callback_ret = PyObject_CallMethod(self->callbacks, "send_signal_for_key", "c", cchar);
        if (callback_ret) {
            ret = PyObject_IsTrue(callback_ret);
            Py_DECREF(callback_ret);
        } else { PyErr_Print(); }
    }
    return ret != 0;
}

void
screen_push_colors(Screen *self, unsigned int idx) {
    if (colorprofile_push_colors(self->color_profile, idx)) self->color_profile->dirty = true;
}

void
screen_pop_colors(Screen *self, unsigned int idx) {
    color_type bg_before = colorprofile_to_color(self->color_profile, self->color_profile->overridden.default_bg, self->color_profile->configured.default_bg).rgb;
    if (colorprofile_pop_colors(self->color_profile, idx)) {
        self->color_profile->dirty = true;
        color_type bg_after = colorprofile_to_color(self->color_profile, self->color_profile->overridden.default_bg, self->color_profile->configured.default_bg).rgb;
        CALLBACK("color_profile_popped", "O", bg_before == bg_after ? Py_False : Py_True);
    }
}

void
screen_report_color_stack(Screen *self) {
    unsigned int idx, count;
    colorprofile_report_stack(self->color_profile, &idx, &count);
    char buf[128] = {0};
    snprintf(buf, arraysz(buf), "%u;%u#Q", idx, count);
    write_escape_code_to_child(self, ESC_CSI, buf);
}

void screen_handle_kitty_dcs(Screen *self, const char *callback_name, PyObject *cmd) {
    CALLBACK(callback_name, "O", cmd);
}

void
screen_request_capabilities(Screen *self, char c, const char *query) {
    static char buf[128];
    int shape = 0;
    switch(c) {
        case '+': {
            CALLBACK("request_capabilities", "s", query);
        } break;
        case '$':
            // report status DECRQSS
            if (strcmp(" q", query) == 0) {
                // cursor shape DECSCUSR
                switch(self->cursor->shape) {
                    case NO_CURSOR_SHAPE:
                    case NUM_OF_CURSOR_SHAPES:
                        shape = 1; break;
                    case CURSOR_BLOCK:
                        shape = self->cursor->non_blinking ? 2 : 0; break;
                    case CURSOR_UNDERLINE:
                        shape = self->cursor->non_blinking ? 4 : 3; break;
                    case CURSOR_BEAM:
                        shape = self->cursor->non_blinking ? 6 : 5; break;
                }
                shape = snprintf(buf, sizeof(buf), "1$r%d q", shape);
            } else if (strcmp("m", query) == 0) {
                // SGR
                shape = snprintf(buf, sizeof(buf), "1$r%sm", cursor_as_sgr(self->cursor));
            } else if (strcmp("r", query) == 0) { // DECSTBM
                shape = snprintf(buf, sizeof(buf), "1$r%u;%ur", self->margin_top + 1, self->margin_bottom + 1);
            } else if (strcmp("*x", query) == 0) { // DECSACE
                shape = snprintf(buf, sizeof(buf), "1$r%d*x", self->modes.mDECSACE ? 1 : 0);
            } else {
                shape = snprintf(buf, sizeof(buf), "0$r");
            }
            if (shape > 0) write_escape_code_to_child(self, ESC_DCS, buf);
            break;
    }
}

// }}}

// Rendering {{{

void
screen_check_pause_rendering(Screen *self, monotonic_t now) {
    if (self->paused_rendering.expires_at && now > self->paused_rendering.expires_at) screen_pause_rendering(self, false, 0);
}

static bool
copy_selections(Selections *dest, const Selections *src) {
    if (dest->capacity < src->count) {
        dest->items = realloc(dest->items, sizeof(dest->items[0]) * src->count);
        if (!dest->items) { dest->capacity = 0; dest->count = 0; return false; }
        dest->capacity = src->count;
    }
    dest->count = src->count;
    for (unsigned i = 0; i < dest->count; i++) memcpy(dest->items + i, src->items + i, sizeof(dest->items[0]));
    return true;
}

bool
screen_pause_rendering(Screen *self, bool pause, int for_in_ms) {
    if (!pause) {
        if (!self->paused_rendering.expires_at) return false;
        self->paused_rendering.expires_at = 0;
        self->is_dirty = true;
        return true;
    }
    if (self->paused_rendering.expires_at) return false;
    if (for_in_ms <= 0) for_in_ms = 2000;
    self->paused_rendering.expires_at = monotonic() + ms_to_monotonic_t(for_in_ms);
    self->paused_rendering.inverted = self->modes.mDECSCNM ? true : false;
    self->paused_rendering.scrolled_by = self->scrolled_by;
    self->paused_rendering.cell_data_updated = false;
    memcpy(&self->paused_rendering.cursor, self->cursor, sizeof(self->paused_rendering.cursor));
    memcpy(&self->paused_rendering.color_profile, self->color_profile, sizeof(self->paused_rendering.color_profile));
    if (!self->paused_rendering.linebuf || self->paused_rendering.linebuf->xnum != self->columns || self->paused_rendering.linebuf->ynum != self->lines) {
        if (self->paused_rendering.linebuf) Py_CLEAR(self->paused_rendering.linebuf);
        self->paused_rendering.linebuf = alloc_linebuf(self->lines, self->columns);
        if (!self->paused_rendering.linebuf) { PyErr_Clear(); self->paused_rendering.expires_at = 0; return false; }
    }
    for (index_type y = 0; y < self->lines; y++) {
        Line *src = visual_line_(self, y);
        linebuf_init_line(self->paused_rendering.linebuf, y);
        copy_line(src, self->linebuf->line);
        self->paused_rendering.linebuf->line_attrs[y] = src->attrs;
    }
    copy_selections(&self->paused_rendering.selections, &self->selections);
    copy_selections(&self->paused_rendering.url_ranges, &self->url_ranges);
    return true;
}

static color_type
effective_cell_edge_color(char_type ch, color_type fg, color_type bg, bool is_left_edge) {
    START_ALLOW_CASE_RANGE
    if (ch == 0x2588) return fg; // full block
    if (is_left_edge) {
        switch (ch) {
            case 0x2589 ... 0x258f: // left eighth blocks
            case 0xe0b0: case 0xe0b4: case 0xe0b8: case 0xe0bc:  // powerline blocks
            case 0x1fb6a: // 🭪
                return fg;
        }
    } else {
        switch (ch) {
            case 0x2590:  // right half block
            case 0x1fb87 ... 0x1fb8b:  // eighth right blocks
            case 0xe0b2: case 0xe0b6: case 0xe0ba: case 0xe0be:
            case 0x1fb68: // 🭨
                return fg;
        }
    }
    return bg;
    END_ALLOW_CASE_RANGE
}


bool
get_line_edge_colors(Screen *self, color_type *left, color_type *right) {
    // Return the color at the left and right edges of the line with the cursor on it
    Line *line = range_line_(self, self->cursor->y);
    if (!line) return false;
    color_type left_cell_fg = OPT(foreground), left_cell_bg = OPT(background), right_cell_bg = OPT(background), right_cell_fg = OPT(foreground);
    index_type cell_color_x = 0;
    char_type left_char = line_get_char(line, cell_color_x);
    bool reversed = false;
    colors_for_cell(line, self->color_profile, &cell_color_x, &left_cell_fg, &left_cell_bg, &reversed);
    if (line->xnum > 0) cell_color_x = line->xnum - 1;
    char_type right_char = line_get_char(line, cell_color_x);
    colors_for_cell(line, self->color_profile, &cell_color_x, &right_cell_fg, &right_cell_bg, &reversed);
    *left = effective_cell_edge_color(left_char, left_cell_fg, left_cell_bg, true);
    *right = effective_cell_edge_color(right_char, right_cell_fg, right_cell_bg, false);
    return true;
}


static void
update_line_data(Line *line, unsigned int dest_y, uint8_t *data) {
    size_t base = sizeof(GPUCell) * dest_y * line->xnum;
    memcpy(data + base, line->gpu_cells, line->xnum * sizeof(GPUCell));
}


static void
screen_reset_dirty(Screen *self) {
    self->is_dirty = false;
    self->history_line_added_count = 0;
}

static bool
screen_has_marker(Screen *self) {
    return self->marker != NULL;
}

static uint32_t diacritic_to_rowcolumn(combining_type m) {
    char_type c = codepoint_for_mark(m);
    return diacritic_to_num(c);
}

static uint32_t color_to_id(color_type c) {
    // Just take 24 most significant bits of the color. This works both for
    // 24-bit and 8-bit colors.
    return (c >> 8) & 0xffffff;
}

// Scan the line and create cell images in place of unicode placeholders
// reserved for image placement.
static void
screen_render_line_graphics(Screen *self, Line *line, int32_t row) {
    // If there are no image placeholders now, no need to rescan the line.
    if (!line->attrs.has_image_placeholders)
        return;
    // Remove existing images.
    grman_remove_cell_images(self->grman, row, row);
    // The placeholders might be erased. We will update the attribute.
    line->attrs.has_image_placeholders = false;
    index_type i;
    uint32_t run_length = 0;
    uint32_t prev_img_id_lower24bits = 0;
    uint32_t prev_placement_id = 0;
    // Note that the following values are 1-based, zero means unknown or incorrect.
    uint32_t prev_img_id_higher8bits = 0;
    uint32_t prev_img_row = 0;
    uint32_t prev_img_col = 0;
    for (i = 0; i < line->xnum; i++) {
        CPUCell *cpu_cell = line->cpu_cells + i;
        GPUCell *gpu_cell = line->gpu_cells + i;
        uint32_t cur_img_id_lower24bits = 0;
        uint32_t cur_placement_id = 0;
        uint32_t cur_img_id_higher8bits = 0;
        uint32_t cur_img_row = 0;
        uint32_t cur_img_col = 0;
        if (cpu_cell->ch == IMAGE_PLACEHOLDER_CHAR) {
            line->attrs.has_image_placeholders = true;
            // The lower 24 bits of the image id are encoded in the foreground
            // color, and the placement id is (optionally) in the underline color.
            cur_img_id_lower24bits = color_to_id(gpu_cell->fg);
            cur_placement_id = color_to_id(gpu_cell->decoration_fg);
            // If the char has diacritics, use them as row and column indices.
            if (cpu_cell->cc_idx[0])
                cur_img_row = diacritic_to_rowcolumn(cpu_cell->cc_idx[0]);
            if (cpu_cell->cc_idx[1])
                cur_img_col = diacritic_to_rowcolumn(cpu_cell->cc_idx[1]);
            // The third diacritic is used to encode the higher 8 bits of the
            // image id (optional).
            if (cpu_cell->cc_idx[2])
                cur_img_id_higher8bits = diacritic_to_rowcolumn(cpu_cell->cc_idx[2]);
        }
        // The current run is continued if the lower 24 bits of the image id and
        // the placement id are the same as in the previous cell and everything
        // else is unknown or compatible with the previous cell.
        if (run_length > 0 && cur_img_id_lower24bits == prev_img_id_lower24bits &&
            cur_placement_id == prev_placement_id &&
            (!cur_img_row || cur_img_row == prev_img_row) &&
            (!cur_img_col || cur_img_col == prev_img_col + 1) &&
            (!cur_img_id_higher8bits || cur_img_id_higher8bits == prev_img_id_higher8bits)) {
            // This cell continues the current run.
            run_length++;
            // If some values are unknown, infer them from the previous cell.
            cur_img_row = MAX(prev_img_row, 1u);
            cur_img_col = prev_img_col + 1;
            cur_img_id_higher8bits = MAX(prev_img_id_higher8bits, 1u);
        } else {
            // This cell breaks the current run. Render the current run if it
            // has a non-zero length.
            if (run_length > 0) {
                uint32_t img_id = prev_img_id_lower24bits | (prev_img_id_higher8bits - 1) << 24;
                grman_put_cell_image(
                    self->grman, row, i - run_length, img_id,
                    prev_placement_id, prev_img_col - run_length,
                    prev_img_row - 1, run_length, 1, self->cell_size);
            }
            // Start a new run.
            if (cpu_cell->ch == IMAGE_PLACEHOLDER_CHAR) {
                run_length = 1;
                if (!cur_img_col) cur_img_col = 1;
                if (!cur_img_row) cur_img_row = 1;
                if (!cur_img_id_higher8bits) cur_img_id_higher8bits = 1;
            }
        }
        prev_img_id_lower24bits = cur_img_id_lower24bits;
        prev_img_id_higher8bits = cur_img_id_higher8bits;
        prev_placement_id = cur_placement_id;
        prev_img_row = cur_img_row;
        prev_img_col = cur_img_col;
    }
    if (run_length > 0) {
        // Render the last run.
        uint32_t img_id = prev_img_id_lower24bits | (prev_img_id_higher8bits - 1) << 24;
        grman_put_cell_image(self->grman, row, i - run_length, img_id,
                             prev_placement_id, prev_img_col - run_length,
                             prev_img_row - 1, run_length, 1, self->cell_size);
    }
}

// This functions is similar to screen_update_cell_data, but it only updates
// line graphics (cell images) and then marks lines as clean. It's used
// exclusively for testing unicode placeholders.
static void
screen_update_only_line_graphics_data(Screen *self) {
    unsigned int history_line_added_count = self->history_line_added_count;
    index_type lnum;
    if (self->scrolled_by) self->scrolled_by = MIN(self->scrolled_by + history_line_added_count, self->historybuf->count);
    screen_reset_dirty(self);
    self->scroll_changed = false;
    for (index_type y = 0; y < MIN(self->lines, self->scrolled_by); y++) {
        lnum = self->scrolled_by - 1 - y;
        historybuf_init_line(self->historybuf, lnum, self->historybuf->line);
        screen_render_line_graphics(self, self->historybuf->line, y - self->scrolled_by);
        if (self->historybuf->line->attrs.has_dirty_text) {
            historybuf_mark_line_clean(self->historybuf, lnum);
        }
    }
    for (index_type y = self->scrolled_by; y < self->lines; y++) {
        lnum = y - self->scrolled_by;
        linebuf_init_line(self->linebuf, lnum);
        if (self->linebuf->line->attrs.has_dirty_text) {
            screen_render_line_graphics(self, self->linebuf->line, y - self->scrolled_by);
            linebuf_mark_line_clean(self->linebuf, lnum);
        }
    }
}

void
screen_update_cell_data(Screen *self, void *address, FONTS_DATA_HANDLE fonts_data, bool cursor_has_moved) {
    if (self->paused_rendering.expires_at) {
        if (!self->paused_rendering.cell_data_updated) {
            LineBuf *linebuf = self->paused_rendering.linebuf;
            for (index_type y = 0; y < self->lines; y++) {
                linebuf_init_line(linebuf, y);
                if (linebuf->line->attrs.has_dirty_text) {
                    render_line(fonts_data, linebuf->line, y, &self->paused_rendering.cursor, self->disable_ligatures);
                    screen_render_line_graphics(self, linebuf->line, y);
                    if (linebuf->line->attrs.has_dirty_text && screen_has_marker(self)) mark_text_in_line(self->marker, linebuf->line);
                    linebuf_mark_line_clean(linebuf, y);
                }
                update_line_data(linebuf->line, y, address);
            }
        }
        return;
    }
    const bool is_overlay_active = screen_is_overlay_active(self);
    unsigned int history_line_added_count = self->history_line_added_count;
    index_type lnum;
    bool was_dirty = self->is_dirty;
    screen_reset_dirty(self);
    update_overlay_position(self);
    if (self->scrolled_by) self->scrolled_by = MIN(self->scrolled_by + history_line_added_count, self->historybuf->count);
    self->scroll_changed = false;
    for (index_type y = 0; y < MIN(self->lines, self->scrolled_by); y++) {
        lnum = self->scrolled_by - 1 - y;
        historybuf_init_line(self->historybuf, lnum, self->historybuf->line);
        // we render line graphics even if the line is not dirty as graphics commands received after
        // the unicode placeholder was first scanned can alter it.
        screen_render_line_graphics(self, self->historybuf->line, y - self->scrolled_by);
        if (self->historybuf->line->attrs.has_dirty_text) {
            render_line(fonts_data, self->historybuf->line, lnum, self->cursor, self->disable_ligatures);
            if (screen_has_marker(self)) mark_text_in_line(self->marker, self->historybuf->line);
            historybuf_mark_line_clean(self->historybuf, lnum);
        }
        update_line_data(self->historybuf->line, y, address);
    }
    for (index_type y = self->scrolled_by; y < self->lines; y++) {
        lnum = y - self->scrolled_by;
        linebuf_init_line(self->linebuf, lnum);
        if (self->linebuf->line->attrs.has_dirty_text ||
            (cursor_has_moved && (self->cursor->y == lnum || self->last_rendered.cursor_y == lnum))) {
            render_line(fonts_data, self->linebuf->line, lnum, self->cursor, self->disable_ligatures);
            screen_render_line_graphics(self, self->linebuf->line, y - self->scrolled_by);
            if (self->linebuf->line->attrs.has_dirty_text && screen_has_marker(self)) mark_text_in_line(self->marker, self->linebuf->line);
            if (is_overlay_active && lnum == self->overlay_line.ynum) render_overlay_line(self, self->linebuf->line, fonts_data);
            linebuf_mark_line_clean(self->linebuf, lnum);
        }
        update_line_data(self->linebuf->line, y, address);
    }
    if (is_overlay_active && self->overlay_line.ynum + self->scrolled_by < self->lines) {
        if (self->overlay_line.is_dirty) {
            linebuf_init_line(self->linebuf, self->overlay_line.ynum);
            render_overlay_line(self, self->linebuf->line, fonts_data);
        }
        update_overlay_line_data(self, address);
    }
    if (was_dirty) clear_selection(&self->url_ranges);
}

static bool
selection_boundary_less_than(const SelectionBoundary *a, const SelectionBoundary *b) {
    // y -values must be absolutized (aka adjusted with scrolled_by)
    // this means the oldest line has the highest value and is thus the least
    if (a->y > b->y) return true;
    if (a->y < b->y) return false;
    if (a->x < b->x) return true;
    if (a->x > b->x) return false;
    if (a->in_left_half_of_cell && !b->in_left_half_of_cell) return true;
    return false;
}

static index_type
num_cells_between_selection_boundaries(const Screen *self, const SelectionBoundary *a, const SelectionBoundary *b) {
    const SelectionBoundary *before, *after;
    if (selection_boundary_less_than(a, b)) { before = a; after = b; }
    else { before = b; after = a; }
    index_type ans = 0;
    if (before->y + 1 < after->y) ans += self->columns * (after->y - before->y - 1);
    if (before->y == after->y) ans += after->x - before->x;
    else ans += (self->columns - before->x) + after->x;
    return ans;
}

static index_type
num_lines_between_selection_boundaries(const SelectionBoundary *a, const SelectionBoundary *b) {
    const SelectionBoundary *before, *after;
    if (selection_boundary_less_than(a, b)) { before = a; after = b; }
    else { before = b; after = a; }
    return before->y - after->y;
}

typedef Line*(linefunc_t)(Screen*, int);

static Line*
init_line(Screen *self, index_type y) {
    linebuf_init_line(self->linebuf, y);
    if (y == 0 && self->linebuf == self->main_linebuf) {
        if (history_buf_endswith_wrap(self->historybuf)) self->linebuf->line->attrs.is_continued = true;
    }
    return self->linebuf->line;
}

static Line*
visual_line_(Screen *self, int y_) {
    index_type y = MAX(0, y_);
    if (self->scrolled_by) {
        if (y < self->scrolled_by) {
            historybuf_init_line(self->historybuf, self->scrolled_by - 1 - y, self->historybuf->line);
            return self->historybuf->line;
        }
        y -= self->scrolled_by;
    }
    return init_line(self, y);
}

static Line*
range_line_(Screen *self, int y) {
    if (y < 0) {
        historybuf_init_line(self->historybuf, -(y + 1), self->historybuf->line);
        return self->historybuf->line;
    }
    return init_line(self, y);
}

static Line*
checked_range_line(Screen *self, int y) {
    if (
        (y < 0 && -(y + 1) >= (int)self->historybuf->count) || y >= (int)self->lines
    ) return NULL;
    return range_line_(self, y);
}

static bool
selection_is_left_to_right(const Selection *self) {
    return self->input_start.x < self->input_current.x || (self->input_start.x == self->input_current.x && self->input_start.in_left_half_of_cell);
}

static void
iteration_data(const Selection *sel, IterationData *ans, unsigned x_limit, int min_y, unsigned add_scrolled_by) {
    memset(ans, 0, sizeof(IterationData));
    const SelectionBoundary *start = &sel->start, *end = &sel->end;
    int start_y = (int)start->y - sel->start_scrolled_by, end_y = (int)end->y - sel->end_scrolled_by;
    // empty selection
    if (start->x == end->x && start_y == end_y && start->in_left_half_of_cell == end->in_left_half_of_cell) return;

    if (sel->rectangle_select) {
        // empty selection
        if (start->x == end->x && (!start->in_left_half_of_cell || end->in_left_half_of_cell)) return;

        ans->y = MIN(start_y, end_y); ans->y_limit = MAX(start_y, end_y) + 1;
        index_type x, x_limit;
        bool left_to_right = selection_is_left_to_right(sel);

        if (start->x == end->x) {
            x = start->x; x_limit = start->x + 1;
        } else {
            if (left_to_right) {
                x = start->x + (start->in_left_half_of_cell ? 0 : 1);
                x_limit = 1 + end->x + (end->in_left_half_of_cell ? -1: 0);
            } else {
                x = end->x + (end->in_left_half_of_cell ? 0 : 1);
                x_limit = 1 + start->x + (start->in_left_half_of_cell ? -1 : 0);
            }
        }
        ans->first.x = x; ans->body.x = x; ans->last.x = x;
        ans->first.x_limit = x_limit; ans->body.x_limit = x_limit; ans->last.x_limit = x_limit;
    } else {
        index_type line_limit = x_limit;

        if (start_y == end_y) {
            if (start->x == end->x) {
                if (start->in_left_half_of_cell && !end->in_left_half_of_cell) {
                    // single cell selection
                    ans->first.x = start->x; ans->body.x = start->x; ans->last.x = start->x;
                    ans->first.x_limit = start->x + 1; ans->body.x_limit = start->x + 1; ans->last.x_limit = start->x + 1;
                } else return; // empty selection
            }
            // single line selection
            else if (start->x <= end->x) {
                ans->first.x = start->x + (start->in_left_half_of_cell ? 0 : 1);
                ans->first.x_limit = 1 + end->x + (end->in_left_half_of_cell ? -1 : 0);
            } else {
                ans->first.x = end->x + (end->in_left_half_of_cell ? 0 : 1);
                ans->first.x_limit = 1 + start->x + (start->in_left_half_of_cell ? -1 : 0);
            }
        } else if (start_y < end_y) { // downwards
            ans->body.x_limit = line_limit;
            ans->first.x_limit = line_limit;
            ans->first.x = start->x + (start->in_left_half_of_cell ? 0 : 1);
            ans->last.x_limit = 1 + end->x + (end->in_left_half_of_cell ? -1 : 0);
        } else { // upwards
            ans->body.x_limit = line_limit;
            ans->first.x_limit = line_limit;
            ans->first.x = end->x + (end->in_left_half_of_cell ? 0 : 1);
            ans->last.x_limit = 1 + start->x + (start->in_left_half_of_cell ? -1 : 0);
        }
        ans->y = MIN(start_y, end_y); ans->y_limit = MAX(start_y, end_y) + 1;

    }
    ans->y += add_scrolled_by; ans->y_limit += add_scrolled_by;
    ans->y = MAX(ans->y, min_y);
    ans->y_limit = MAX(ans->y, ans->y_limit);  // iteration is from y to y_limit
}

static XRange
xrange_for_iteration(const IterationData *idata, const int y, const Line *line) {
    XRange ans = {.x_limit=xlimit_for_line(line)};
    if (y == idata->y) {
        ans.x_limit = MIN(idata->first.x_limit, ans.x_limit);
        ans.x = idata->first.x;
    } else if (y == idata->y_limit - 1) {
        ans.x_limit = MIN(idata->last.x_limit, ans.x_limit);
        ans.x = idata->last.x;
    } else {
        ans.x_limit = MIN(idata->body.x_limit, ans.x_limit);
        ans.x = idata->body.x;
    }
    return ans;
}

static bool
iteration_data_is_empty(const Screen *self, const IterationData *idata) {
    if (idata->y >= idata->y_limit) return true;
    index_type xl = MIN(idata->first.x_limit, self->columns);
    if (idata->first.x < xl) return false;
    xl = MIN(idata->body.x_limit, self->columns);
    if (idata->body.x < xl) return false;
    xl = MIN(idata->last.x_limit, self->columns);
    if (idata->last.x < xl) return false;
    return true;
}

static void
apply_selection(Screen *self, uint8_t *data, Selection *s, uint8_t set_mask) {
    iteration_data(s, &s->last_rendered, self->columns, -self->historybuf->count, self->scrolled_by);
    Line *line;

    for (int y = MAX(0, s->last_rendered.y); y < s->last_rendered.y_limit && y < (int)self->lines; y++) {
        if (self->paused_rendering.expires_at) {
            linebuf_init_line(self->paused_rendering.linebuf, y);
            line = self->paused_rendering.linebuf->line;
        } else line = visual_line_(self, y);
        uint8_t *line_start = data + self->columns * y;
        XRange xr = xrange_for_iteration(&s->last_rendered, y, line);
        for (index_type x = xr.x; x < xr.x_limit; x++) line_start[x] |= set_mask;
    }
    s->last_rendered.y = MAX(0, s->last_rendered.y);
}

bool
screen_has_selection(Screen *self) {
    IterationData idata;
    for (size_t i = 0; i < self->selections.count; i++) {
        Selection *s = self->selections.items + i;
        if (!is_selection_empty(s)) {
            iteration_data(s, &idata, self->columns, -self->historybuf->count, self->scrolled_by);
            if (!iteration_data_is_empty(self, &idata)) return true;
        }
    }
    return false;
}

void
screen_apply_selection(Screen *self, void *address, size_t size) {
    memset(address, 0, size);
    Selections *sel = self->paused_rendering.expires_at ? &self->paused_rendering.selections : &self->selections;
    for (size_t i = 0; i < sel->count; i++) apply_selection(self, address, sel->items + i, 1);
    sel->last_rendered_count = sel->count;
    sel = self->paused_rendering.expires_at ? &self->paused_rendering.url_ranges : &self->url_ranges;
    for (size_t i = 0; i < sel->count; i++) {
        Selection *s = sel->items + i;
        if (OPT(underline_hyperlinks) == UNDERLINE_NEVER && s->is_hyperlink) continue;
        apply_selection(self, address, s, 2);
    }
    sel->last_rendered_count = sel->count;
}

static index_type
limit_without_trailing_whitespace(const Line *line, index_type limit) {
    if (!limit) return limit;
    if (limit > line->xnum) limit = line->xnum;
    while (limit > 0) {
        CPUCell *cell = line->cpu_cells + limit - 1;
        if (cell->cc_idx[0]) break;
        switch(cell->ch) {
            case ' ': case '\t': case '\n': case '\r': case 0: break;
            default:
                return limit;
        }
        limit--;
    }
    return limit;
}

static PyObject*
text_for_range(Screen *self, const Selection *sel, bool insert_newlines, bool strip_trailing_whitespace) {
    IterationData idata;
    iteration_data(sel, &idata, self->columns, -self->historybuf->count, 0);
    int limit = MIN((int)self->lines, idata.y_limit);
    PyObject *ans = PyTuple_New(limit - idata.y);
    if (!ans) return NULL;
    for (int i = 0, y = idata.y; y < limit; y++, i++) {
        Line *line = range_line_(self, y);
        XRange xr = xrange_for_iteration(&idata, y, line);
        index_type x_limit = xr.x_limit;
        if (strip_trailing_whitespace) {
            index_type new_limit = limit_without_trailing_whitespace(line, x_limit);
            if (new_limit != x_limit) {
                x_limit = new_limit;
                if (!x_limit) {
                    PyObject *text = PyUnicode_FromString("\n");
                    if (text == NULL) { Py_DECREF(ans); return PyErr_NoMemory(); }
                    PyTuple_SET_ITEM(ans, i, text);
                    continue;
                }
            }
        }
        PyObject *text = unicode_in_range(line, xr.x, x_limit, true, insert_newlines && y != limit-1, false);
        if (text == NULL) { Py_DECREF(ans); return PyErr_NoMemory(); }
        PyTuple_SET_ITEM(ans, i, text);
    }
    return ans;
}

static PyObject*
ansi_for_range(Screen *self, const Selection *sel, bool insert_newlines, bool strip_trailing_whitespace) {
    IterationData idata;
    iteration_data(sel, &idata, self->columns, -self->historybuf->count, 0);
    int limit = MIN((int)self->lines, idata.y_limit);
    RAII_PyObject(ans, PyTuple_New(limit - idata.y + 1));
    RAII_PyObject(nl, PyUnicode_FromString("\n"));
    if (!ans || !nl) return NULL;
    ANSIBuf output = {0};
    const GPUCell *prev_cell = NULL;
    bool has_escape_codes = false;
    bool need_newline = false;
    for (int i = 0, y = idata.y; y < limit; y++, i++) {
        Line *line = range_line_(self, y);
        XRange xr = xrange_for_iteration(&idata, y, line);
        output.len = 0;
        char_type prefix_char = need_newline ? '\n' : 0;
        index_type x_limit = xr.x_limit;
        if (strip_trailing_whitespace) {
            index_type new_limit = limit_without_trailing_whitespace(line, x_limit);
            if (new_limit != x_limit) {
                x_limit = new_limit;
                if (!x_limit) {
                    PyTuple_SET_ITEM(ans, i, nl);
                    continue;
                }
            }
        }
        if (line_as_ansi(line, &output, &prev_cell, xr.x, x_limit, prefix_char)) has_escape_codes = true;
        need_newline = insert_newlines && !line->gpu_cells[line->xnum-1].attrs.next_char_was_wrapped;
        PyObject *t = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, output.buf, output.len);
        if (!t) return NULL;
        PyTuple_SET_ITEM(ans, i, t);
    }
    PyObject *t = PyUnicode_FromFormat("%s%s", has_escape_codes ? "\x1b[m" : "", output.active_hyperlink_id ? "\x1b]8;;\x1b\\" : "");
    if (!t) return NULL;
    PyTuple_SET_ITEM(ans, PyTuple_GET_SIZE(ans) - 1, t);
    Py_INCREF(ans);
    return ans;
}


static hyperlink_id_type
hyperlink_id_for_range(Screen *self, const Selection *sel) {
    IterationData idata;
    iteration_data(sel, &idata, self->columns, -self->historybuf->count, 0);
    for (int i = 0, y = idata.y; y < idata.y_limit && y < (int)self->lines; y++, i++) {
        Line *line = range_line_(self, y);
        XRange xr = xrange_for_iteration(&idata, y, line);
        for (index_type x = xr.x; x < xr.x_limit; x++) {
            if (line->cpu_cells[x].hyperlink_id) return line->cpu_cells[x].hyperlink_id;
        }
    }
    return 0;
}

static PyObject*
extend_tuple(PyObject *a, PyObject *b) {
    Py_ssize_t bs = PyTuple_GET_SIZE(b);
    if (bs < 1) return a;
    Py_ssize_t off = PyTuple_GET_SIZE(a);
    if (_PyTuple_Resize(&a, off + bs) != 0) return NULL;
    for (Py_ssize_t y = 0; y < bs; y++) {
        PyObject *t = PyTuple_GET_ITEM(b, y);
        Py_INCREF(t);
        PyTuple_SET_ITEM(a, off + y, t);
    }
    return a;
}

static PyObject*
current_url_text(Screen *self, PyObject *args UNUSED) {
    PyObject *empty_string = PyUnicode_FromString(""), *ans = NULL;
    if (!empty_string) return NULL;
    for (size_t i = 0; i < self->url_ranges.count; i++) {
        Selection *s = self->url_ranges.items + i;
        if (!is_selection_empty(s)) {
            PyObject *temp = text_for_range(self, s, false, false);
            if (!temp) goto error;
            PyObject *text = PyUnicode_Join(empty_string, temp);
            Py_CLEAR(temp);
            if (!text) goto error;
            if (ans) {
                PyObject *t = ans;
                ans = PyUnicode_Concat(ans, text);
                Py_CLEAR(text); Py_CLEAR(t);
                if (!ans) goto error;
            } else ans = text;
        }
    }
    Py_CLEAR(empty_string);
    if (!ans) Py_RETURN_NONE;
    return ans;
error:
    Py_CLEAR(empty_string); Py_CLEAR(ans);
    return NULL;
}


bool
screen_open_url(Screen *self) {
    if (!self->url_ranges.count) return false;
    hyperlink_id_type hid = hyperlink_id_for_range(self, self->url_ranges.items);
    if (hid) {
        const char *url = get_hyperlink_for_id(self->hyperlink_pool, hid, true);
        if (url) {
            CALLBACK("open_url", "sH", url, hid);
            return true;
        }
    }
    PyObject *text = current_url_text(self, NULL);
    if (!text) {
        if (PyErr_Occurred()) PyErr_Print();
        return false;
    }
    bool found = false;
    if (PyUnicode_Check(text)) {
        CALLBACK("open_url", "OH", text, 0);
        found = true;
    }
    Py_CLEAR(text);
    return found;
}

// }}}

// URLs {{{
static void
extend_url(Screen *screen, Line *line, index_type *x, index_type *y, char_type sentinel, bool newlines_allowed) {
    unsigned int count = 0;
    bool has_newline = false;
    index_type orig_y = *y;
    while(count++ < 10) {
        has_newline = !line->gpu_cells[line->xnum-1].attrs.next_char_was_wrapped;
        if (*x != line->xnum - 1 || (!newlines_allowed && has_newline)) break;
        bool next_line_starts_with_url_chars = false;
        line = screen_visual_line(screen, *y + 2);
        if (line) {
            next_line_starts_with_url_chars = line_startswith_url_chars(line);
            has_newline = !line->attrs.is_continued;
            if (next_line_starts_with_url_chars && has_newline && !newlines_allowed) next_line_starts_with_url_chars = false;
            if (sentinel && next_line_starts_with_url_chars && line->cpu_cells[0].ch == sentinel) next_line_starts_with_url_chars = false;
        }
        line = screen_visual_line(screen, *y + 1);
        if (!line) break;
        index_type new_x = line_url_end_at(line, 0, false, sentinel, next_line_starts_with_url_chars);
        if (!new_x && !line_startswith_url_chars(line)) break;
        *y += 1; *x = new_x;
    }
    if (sentinel && *x == 0 && *y > orig_y) {
        line = screen_visual_line(screen, *y);
        if (line && line->cpu_cells[0].ch == sentinel) {
            *y -= 1; *x = line->xnum - 1;
        }
    }
}

static char_type
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

int
screen_detect_url(Screen *screen, unsigned int x, unsigned int y) {
    bool has_url = false;
    index_type url_start, url_end = 0;
    Line *line = screen_visual_line(screen, y);
    if (!line || x >= screen->columns) return 0;
    hyperlink_id_type hid;
    if ((hid = line->cpu_cells[x].hyperlink_id)) {
        screen_mark_hyperlink(screen, x, y);
        return hid;
    }
    char_type sentinel = 0;
    bool newlines_allowed = !is_excluded_from_url('\n');
    if (line) {
        url_start = line_url_start_at(line, x);
        if (url_start < line->xnum) {
            bool next_line_starts_with_url_chars = false;
            if (y < screen->lines - 1) {
                line = screen_visual_line(screen, y+1);
                next_line_starts_with_url_chars = line_startswith_url_chars(line);
                if (next_line_starts_with_url_chars && !newlines_allowed && !line->attrs.is_continued) next_line_starts_with_url_chars = false;
                line = screen_visual_line(screen, y);
            }
            sentinel = get_url_sentinel(line, url_start);
            url_end = line_url_end_at(line, x, true, sentinel, next_line_starts_with_url_chars);
        }
        has_url = url_end > url_start;
    }
    if (has_url) {
        index_type y_extended = y;
        extend_url(screen, line, &url_end, &y_extended, sentinel, newlines_allowed);
        screen_mark_url(screen, url_start, y, url_end, y_extended);
    } else {
        screen_mark_url(screen, 0, 0, 0, 0);
    }
    return has_url ? -1 : 0;
}

// }}}

// IME Overlay {{{
bool
screen_is_overlay_active(Screen *self) {
    return self->overlay_line.is_active;
}

static void
deactivate_overlay_line(Screen *self) {
    if (self->overlay_line.is_active && self->overlay_line.xnum && self->overlay_line.ynum < self->lines) {
        self->is_dirty = true;
        linebuf_mark_line_dirty(self->linebuf, self->overlay_line.ynum);
    }
    self->overlay_line.is_active = false;
    self->overlay_line.is_dirty = true;
    self->overlay_line.ynum = 0;
    self->overlay_line.xstart = 0;
    self->overlay_line.cursor_x = 0;
}

void
screen_update_overlay_text(Screen *self, const char *utf8_text) {
    if (screen_is_overlay_active(self)) deactivate_overlay_line(self);
    if (!utf8_text || !utf8_text[0]) return;
    PyObject *text = PyUnicode_FromString(utf8_text);
    if (!text) return;
    Py_XDECREF(self->overlay_line.overlay_text);
    // Calculate the total number of cells for initial overlay cursor position
    RAII_PyObject(text_len, wcswidth_std(NULL, text));
    self->overlay_line.overlay_text = text;
    self->overlay_line.is_active = true;
    self->overlay_line.is_dirty = true;
    self->overlay_line.xstart = self->cursor->x;
    self->overlay_line.xnum = !text_len ? 0 : PyLong_AsLong(text_len);
    self->overlay_line.text_len = self->overlay_line.xnum;
    self->overlay_line.cursor_x = MIN(self->overlay_line.xstart + self->overlay_line.xnum, self->columns);
    self->overlay_line.ynum = self->cursor->y;
    cursor_copy_to(self->cursor, &(self->overlay_line.original_line.cursor));
    linebuf_mark_line_dirty(self->linebuf, self->overlay_line.ynum);
    self->is_dirty = true;
    // Since we are typing, scroll to the bottom
    if (self->scrolled_by != 0) {
        self->scrolled_by = 0;
        dirty_scroll(self);
    }
}

static void
screen_draw_overlay_line(Screen *self) {
    if (!self->overlay_line.overlay_text) return;
    // Right-align the overlay to ensure that the pre-edit text just entered is visible when the cursor is near the end of the line.
    index_type xstart = self->overlay_line.text_len <= self->columns ? self->columns - self->overlay_line.text_len : 0;
    if (self->overlay_line.xstart < xstart) xstart = self->overlay_line.xstart;
    index_type columns_exceeded = self->overlay_line.text_len <= self->columns ? 0 : self->overlay_line.text_len - self->columns;
    bool orig_line_wrap_mode = self->modes.mDECAWM;
    bool orig_cursor_enable_mode = self->modes.mDECTCEM;
    bool orig_insert_replace_mode = self->modes.mIRM;
    self->modes.mDECAWM = false;
    self->modes.mDECTCEM = false;
    self->modes.mIRM = false;
    Cursor *orig_cursor = self->cursor;
    self->cursor = &(self->overlay_line.original_line.cursor);
    self->cursor->reverse ^= true;
    self->cursor->x = xstart;
    self->cursor->y = self->overlay_line.ynum;
    self->overlay_line.xnum = 0;
    if (xstart > 0) {
        // When the cursor is on the second cell of a full-width character for whatever reason,
        // make sure the first character in the overlay is visible.
        GPUCell *g = self->linebuf->line->gpu_cells + (xstart - 1);
        if (g->attrs.width > 1) line_set_char(self->linebuf->line, xstart - 1, 0, 0, NULL, 0);
    }
    index_type before;
    const int kind = PyUnicode_KIND(self->overlay_line.overlay_text);
    const void *data = PyUnicode_DATA(self->overlay_line.overlay_text);
    const Py_ssize_t sz = PyUnicode_GET_LENGTH(self->overlay_line.overlay_text);
    for (Py_ssize_t pos = 0; pos < sz; pos++) {
        before = self->cursor->x;
        draw_codepoint(self, PyUnicode_READ(kind, data, pos));
        index_type len = self->cursor->x - before;
        if (columns_exceeded > 0) {
            // Reset the cursor to maintain right alignment when the overlay exceeds the screen width.
            if (columns_exceeded > len) {
                columns_exceeded -= len;
                len = 0;
            } else {
                len = len > columns_exceeded ? len - columns_exceeded : 0;
                columns_exceeded = 0;
                if (len > 0) {
                    // When the last character is full width and only half moved out, make sure the next character is visible.
                    GPUCell *g = self->linebuf->line->gpu_cells + (len - 1);
                    if (g->attrs.width > 1) line_set_char(self->linebuf->line, len - 1, 0, 0, NULL, 0);
                }
            }
            self->cursor->x = len;
        }
        self->overlay_line.xnum += len;
    }
    self->overlay_line.cursor_x = self->cursor->x;
    self->cursor->reverse ^= true;
    self->cursor = orig_cursor;
    self->modes.mDECAWM = orig_line_wrap_mode;
    self->modes.mDECTCEM = orig_cursor_enable_mode;
    self->modes.mIRM = orig_insert_replace_mode;
}

static void
update_overlay_position(Screen *self) {
    if (screen_is_overlay_active(self) && screen_is_cursor_visible(self)) {
        bool cursor_update = false;
        if (self->cursor->x != self->overlay_line.xstart) {
            cursor_update = true;
            self->overlay_line.xstart = self->cursor->x;
            self->overlay_line.cursor_x = MIN(self->overlay_line.xstart + self->overlay_line.xnum, self->columns);
        }
        if (self->cursor->y != self->overlay_line.ynum) {
            cursor_update = true;
            linebuf_mark_line_dirty(self->linebuf, self->overlay_line.ynum);
            self->overlay_line.ynum = self->cursor->y;
        }
        if (cursor_update) {
            linebuf_mark_line_dirty(self->linebuf, self->overlay_line.ynum);
            self->overlay_line.is_dirty = true;
            self->is_dirty = true;
        }
    }
}

static void
render_overlay_line(Screen *self, Line *line, FONTS_DATA_HANDLE fonts_data) {
#define ol self->overlay_line
    line_save_cells(line, 0, line->xnum, ol.original_line.gpu_cells, ol.original_line.cpu_cells);
    screen_draw_overlay_line(self);
    render_line(fonts_data, line, ol.ynum, self->cursor, self->disable_ligatures);
    line_save_cells(line, 0, line->xnum, ol.gpu_cells, ol.cpu_cells);
    line_reset_cells(line, 0, line->xnum, ol.original_line.gpu_cells, ol.original_line.cpu_cells);
    ol.is_dirty = false;
    const index_type y = MIN(ol.ynum + self->scrolled_by, self->lines - 1);
    if (ol.last_ime_pos.x != ol.cursor_x || ol.last_ime_pos.y != y) {
        ol.last_ime_pos.x = ol.cursor_x; ol.last_ime_pos.y = y;
        update_ime_position_for_window(self->window_id, false, 0);
    }
#undef ol
}

static void
update_overlay_line_data(Screen *self, uint8_t *data) {
    const size_t base = sizeof(GPUCell) * (self->overlay_line.ynum + self->scrolled_by) * self->columns;
    memcpy(data + base, self->overlay_line.gpu_cells, self->columns * sizeof(GPUCell));
}

// }}}

// Python interface {{{
#define WRAP0(name) static PyObject* name(Screen *self, PyObject *a UNUSED) { screen_##name(self); Py_RETURN_NONE; }
#define WRAP0x(name) static PyObject* xxx_##name(Screen *self, PyObject *a UNUSED) { screen_##name(self); Py_RETURN_NONE; }
#define WRAP1(name, defval) static PyObject* name(Screen *self, PyObject *args) { unsigned int v=defval; if(!PyArg_ParseTuple(args, "|I", &v)) return NULL; screen_##name(self, v); Py_RETURN_NONE; }
#define WRAP1B(name, defval) static PyObject* name(Screen *self, PyObject *args) { unsigned int v=defval; int b=false; if(!PyArg_ParseTuple(args, "|Ip", &v, &b)) return NULL; screen_##name(self, v, b); Py_RETURN_NONE; }
#define WRAP1E(name, defval, ...) static PyObject* name(Screen *self, PyObject *args) { unsigned int v=defval; if(!PyArg_ParseTuple(args, "|I", &v)) return NULL; screen_##name(self, v, __VA_ARGS__); Py_RETURN_NONE; }
#define WRAP2(name, defval1, defval2) static PyObject* name(Screen *self, PyObject *args) { unsigned int a=defval1, b=defval2; if(!PyArg_ParseTuple(args, "|II", &a, &b)) return NULL; screen_##name(self, a, b); Py_RETURN_NONE; }
#define WRAP2B(name) static PyObject* name(Screen *self, PyObject *args) { unsigned int a, b; int p; if(!PyArg_ParseTuple(args, "IIp", &a, &b, &p)) return NULL; screen_##name(self, a, b, (bool)p); Py_RETURN_NONE; }

WRAP0(garbage_collect_hyperlink_pool)

static PyObject*
has_selection(Screen *self, PyObject *a UNUSED) {
    if (screen_has_selection(self)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static PyObject*
hyperlinks_as_list(Screen *self, PyObject *args UNUSED) {
    return screen_hyperlinks_as_list(self);
}

static PyObject*
hyperlink_for_id(Screen *self, PyObject *val) {
    unsigned long id = PyLong_AsUnsignedLong(val);
    if (id > HYPERLINK_MAX_NUMBER) { PyErr_SetString(PyExc_IndexError, "Out of bounds"); return NULL; }
    return Py_BuildValue("s", get_hyperlink_for_id(self->hyperlink_pool, id, true));
}

static Line* get_visual_line(void *x, int y) { return visual_line_(x, y); }
static Line* get_range_line(void *x, int y) { return range_line_(x, y); }

static PyObject*
as_text(Screen *self, PyObject *args) {
    return as_text_generic(args, self, get_visual_line, self->lines, &self->as_ansi_buf, false);
}

static PyObject*
as_text_non_visual(Screen *self, PyObject *args) {
    return as_text_generic(args, self, get_range_line, self->lines, &self->as_ansi_buf, false);
}

static PyObject*
as_text_for_history_buf(Screen *self, PyObject *args) {
    return as_text_history_buf(self->historybuf, args, &self->as_ansi_buf);
}

static PyObject*
as_text_generic_wrapper(Screen *self, PyObject *args, get_line_func get_line) {
    return as_text_generic(args, self, get_line, self->lines, &self->as_ansi_buf, false);
}

static PyObject*
as_text_alternate(Screen *self, PyObject *args) {
    LineBuf *original = self->linebuf;
    self->linebuf = original == self->main_linebuf ? self->alt_linebuf : self->main_linebuf;
    PyObject *ans = as_text_generic_wrapper(self, args, get_range_line);
    self->linebuf = original;
    return ans;
}

typedef struct OutputOffset {
    Screen *screen;
    int start;
    unsigned num_lines;
    bool reached_upper_limit;
} OutputOffset;

static Line*
get_line_from_offset(void *x, int y) {
    OutputOffset *r = x;
    return range_line_(r->screen, r->start + y);
}

static bool
find_cmd_output(Screen *self, OutputOffset *oo, index_type start_screen_y, unsigned int scrolled_by, int direction, bool on_screen_only) {
    bool found_prompt = false, found_output = false, found_next_prompt = false;
    int start = 0, end = 0;
    int init_y = start_screen_y - scrolled_by, y1 = init_y, y2 = init_y;
    const int upward_limit = -self->historybuf->count;
    const int downward_limit = self->lines - 1;
    const int screen_limit = -scrolled_by + downward_limit;
    Line *line = NULL;

    // find around
    if (direction == 0) {
        line = checked_range_line(self, y1);
        if (line && line->attrs.prompt_kind == PROMPT_START) {
            found_prompt = true;
            // change direction to downwards to find command output
            direction = 1;
        } else if (line && line->attrs.prompt_kind == OUTPUT_START && !line->attrs.is_continued) {
            found_output = true; start = y1;
            found_prompt = true;
            // keep finding the first output start upwards
        }
        y1--; y2++;
    }

    // find upwards
    if (direction <= 0) {
        // find around: only needs to find the first output start
        // find upwards: find prompt after the output, and the first output
        while (y1 >= upward_limit) {
            line = checked_range_line(self, y1);
            if (line && line->attrs.prompt_kind == PROMPT_START && !line->attrs.is_continued) {
                if (direction == 0) {
                    // find around: stop at prompt start
                    start = y1 + 1;
                    break;
                }
                found_next_prompt = true; end = y1;
            } else if (line && line->attrs.prompt_kind == OUTPUT_START && !line->attrs.is_continued) {
                start = y1;
                break;
            }
            y1--;
        }
        if (y1 < upward_limit) {
            oo->reached_upper_limit = true;
            start = upward_limit;
        }
        found_output = true; found_prompt = true;
    }

    // find downwards
    if (direction >= 0) {
        while (y2 <= downward_limit) {
            if (on_screen_only && !found_output && y2 > screen_limit) break;
            line = checked_range_line(self, y2);
            if (line && line->attrs.prompt_kind == PROMPT_START) {
                if (!found_prompt) found_prompt = true;
                else if (found_output && !found_next_prompt) {
                    found_next_prompt = true; end = y2;
                    break;
                }
            } else if (line && line->attrs.prompt_kind == OUTPUT_START && found_prompt && !found_output) {
                found_output = true; start = y2;
            }
            y2++;
        }
    }

    if (found_next_prompt) {
        oo->num_lines = end >= start ? end - start : 0;
    } else if (found_output) {
        end = (direction < 0 ? MIN(init_y, downward_limit) : downward_limit) + 1;
        oo->num_lines = end >= start ? end - start : 0;
    } else return false;
    oo->start = start;
    return oo->num_lines > 0;
}

static PyObject*
cmd_output(Screen *self, PyObject *args) {
    unsigned int which = 0;
    RAII_PyObject(which_args, PyTuple_GetSlice(args, 0, 1));
    RAII_PyObject(as_text_args, PyTuple_GetSlice(args, 1, PyTuple_GET_SIZE(args)));
    if (!which_args || !as_text_args) return NULL;
    if (!PyArg_ParseTuple(which_args, "I", &which)) return NULL;
    if (self->linebuf != self->main_linebuf) Py_RETURN_NONE;
    OutputOffset oo = {.screen=self};
    bool found = false;

    switch (which) {
        case 0: // last run cmd
            // When scrolled, the starting point of the search for the last command output
            // is actually out of the screen, so add the number of scrolled lines
            found = find_cmd_output(self, &oo, self->cursor->y + self->scrolled_by, self->scrolled_by, -1, false);
            break;
        case 1: // first on screen
            found = find_cmd_output(self, &oo, 0, self->scrolled_by, 1, true);
            break;
        case 2: // last visited cmd
            if (self->last_visited_prompt.scrolled_by <= self->historybuf->count && self->last_visited_prompt.is_set) {
                found = find_cmd_output(self, &oo, self->last_visited_prompt.y, self->last_visited_prompt.scrolled_by, 0, false);
            } break;
        case 3: { // last non-empty output
            int y = self->cursor->y;
            Line *line;
            bool reached_upper_limit = false;
            while (!found && !reached_upper_limit) {
                line = checked_range_line(self, y);
                if (!line || (line->attrs.prompt_kind == OUTPUT_START && !line->attrs.is_continued)) {
                    int start = line ? y : y + 1; reached_upper_limit = !line;
                    int y2 = start; unsigned int num_lines = 0;
                    bool found_content = false;
                    while ((line = checked_range_line(self, y2)) && line->attrs.prompt_kind != PROMPT_START) {
                        if (!found_content) found_content = !line_is_empty(line);
                        num_lines++; y2++;
                    }
                    if (found_content) {
                        found = true;
                        oo.reached_upper_limit = reached_upper_limit;
                        oo.start = start; oo.num_lines = num_lines;
                        break;
                    }
                }
                y--;
            }
        } break;
        default:
            PyErr_Format(PyExc_KeyError, "%u is not a valid type of command", which);
            return NULL;
    }
    if (found) {
        RAII_PyObject(ret, as_text_generic(as_text_args, &oo, get_line_from_offset, oo.num_lines, &self->as_ansi_buf, false));
        if (!ret) return NULL;
    }
    if (oo.reached_upper_limit && self->linebuf == self->main_linebuf && OPT(scrollback_pager_history_size) > 0) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

bool
screen_set_last_visited_prompt(Screen *self, index_type y) {
    if (y >= self->lines) return false;
    self->last_visited_prompt.scrolled_by = self->scrolled_by;
    self->last_visited_prompt.y = y;
    self->last_visited_prompt.is_set = true;
    return true;
}

bool
screen_select_cmd_output(Screen *self, index_type y) {
    if (y >= self->lines) return false;
    OutputOffset oo = {.screen=self};
    if (!find_cmd_output(self, &oo, y, self->scrolled_by, 0, true)) return false;

    screen_start_selection(self, 0, y, true, false, EXTEND_LINE);
    Selection *s = self->selections.items;
#define S(which, offset_y, scrolled_by) \
    if (offset_y < 0) { \
        s->scrolled_by = -(offset_y); s->which.y = 0; \
    } else { \
        s->scrolled_by = 0; s->which.y = offset_y; \
    }
    S(start, oo.start, start_scrolled_by);
    S(end, oo.start + (int)oo.num_lines - 1, end_scrolled_by);
#undef S
    s->start.x = 0; s->start.in_left_half_of_cell = true;
    s->end.x = self->columns; s->end.in_left_half_of_cell = false;
    self->selections.in_progress = false;

    call_boss(set_primary_selection, NULL);
    return true;
}

static PyObject*
screen_truncate_point_for_length(PyObject UNUSED *self, PyObject *args) {
    PyObject *str; unsigned int num_cells, start_pos = 0;
    if (!PyArg_ParseTuple(args, "UI|I", &str, &num_cells, &start_pos)) return NULL;
    if (PyUnicode_READY(str) != 0) return NULL;
    int kind = PyUnicode_KIND(str);
    void *data = PyUnicode_DATA(str);
    Py_ssize_t len = PyUnicode_GET_LENGTH(str), i;
    char_type prev_ch = 0;
    int prev_width = 0;
    bool in_sgr = false;
    unsigned long width_so_far = 0;
    for (i = start_pos; i < len && width_so_far < num_cells; i++) {
        char_type ch = PyUnicode_READ(kind, data, i);
        if (in_sgr) {
            if (ch == 'm') in_sgr = false;
            continue;
        }
        if (ch == 0x1b && i + 1 < len && PyUnicode_READ(kind, data, i + 1) == '[') { in_sgr = true; continue; }
        if (ch == 0xfe0f) {
            if (is_emoji_presentation_base(prev_ch) && prev_width == 1) {
                width_so_far += 1;
                prev_width = 2;
            } else prev_width = 0;
        } else {
            int w = wcwidth_std(ch);
            switch(w) {
                case -1:
                case 0:
                    prev_width = 0; break;
                case 2:
                    prev_width = 2; break;
                default:
                    prev_width = 1; break;
            }
            if (width_so_far + prev_width > num_cells) { break; }
            width_so_far += prev_width;
        }
        prev_ch = ch;

    }
    return PyLong_FromUnsignedLong(i);
}


static PyObject*
line(Screen *self, PyObject *val) {
    unsigned long y = PyLong_AsUnsignedLong(val);
    if (y >= self->lines) { PyErr_SetString(PyExc_IndexError, "Out of bounds"); return NULL; }
    linebuf_init_line(self->linebuf, y);
    Py_INCREF(self->linebuf->line);
    return (PyObject*) self->linebuf->line;
}

Line*
screen_visual_line(Screen *self, index_type y) {
    if (y >= self->lines) return NULL;
    return visual_line_(self, y);
}

static PyObject*
visual_line(Screen *self, PyObject *args) {
    // The line corresponding to the yth visual line, taking into account scrolling
    unsigned int y;
    if (!PyArg_ParseTuple(args, "I", &y)) return NULL;
    if (y >= self->lines) { Py_RETURN_NONE; }
    return Py_BuildValue("O", visual_line_(self, y));
}

static PyObject*
draw(Screen *self, PyObject *src) {
    if (!PyUnicode_Check(src)) { PyErr_SetString(PyExc_TypeError, "A unicode string is required"); return NULL; }
    if (PyUnicode_READY(src) != 0) { return PyErr_NoMemory(); }
    Py_UCS4 *buf = PyUnicode_AsUCS4Copy(src);
    if (!buf) return NULL;
    draw_text(self, buf, PyUnicode_GetLength(src));
    PyMem_Free(buf);
    Py_RETURN_NONE;
}

static PyObject*
apply_sgr(Screen *self, PyObject *src) {
    if (!PyUnicode_Check(src)) { PyErr_SetString(PyExc_TypeError, "A unicode string is required"); return NULL; }
    if (PyUnicode_READY(src) != 0) { return PyErr_NoMemory(); }
    Py_ssize_t sz;
    const char *s = PyUnicode_AsUTF8AndSize(src, &sz);
    if (s == NULL) return NULL;
    if (!parse_sgr(self, (const uint8_t*)s, sz, "parse_sgr", false)) {
        PyErr_Format(PyExc_ValueError, "Invalid SGR: %s", PyUnicode_AsUTF8(src));
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject*
reset_mode(Screen *self, PyObject *args) {
    int private = false;
    unsigned int mode;
    if (!PyArg_ParseTuple(args, "I|p", &mode, &private)) return NULL;
    if (private) mode <<= 5;
    screen_reset_mode(self, mode);
    Py_RETURN_NONE;
}

static PyObject*
_select_graphic_rendition(Screen *self, PyObject *args) {
    int params[256] = {0};
    for (int i = 0; i < PyTuple_GET_SIZE(args); i++) { params[i] = PyLong_AsLong(PyTuple_GET_ITEM(args, i)); }
    select_graphic_rendition(self, params, PyTuple_GET_SIZE(args), false, NULL);
    Py_RETURN_NONE;
}

static PyObject*
set_mode(Screen *self, PyObject *args) {
    int private = false;
    unsigned int mode;
    if (!PyArg_ParseTuple(args, "I|p", &mode, &private)) return NULL;
    if (private) mode <<= 5;
    screen_set_mode(self, mode);
    Py_RETURN_NONE;
}

static PyObject*
reset_dirty(Screen *self, PyObject *a UNUSED) {
    screen_reset_dirty(self);
    Py_RETURN_NONE;
}

static PyObject*
set_window_char(Screen *self, PyObject *a) {
    const char *text = "";
    if (!PyArg_ParseTuple(a, "|s", &text)) return NULL;
    self->display_window_char = text[0];
    self->is_dirty = true;
    Py_RETURN_NONE;
}


static PyObject*
is_using_alternate_linebuf(Screen *self, PyObject *a UNUSED) {
    if (self->linebuf == self->alt_linebuf) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

WRAP1E(cursor_back, 1, -1)
WRAP1B(erase_in_line, 0)
WRAP1B(erase_in_display, 0)
WRAP0(scroll_until_cursor_prompt)
WRAP0(clear_scrollback)

#define MODE_GETSET(name, uname) \
    static PyObject* name##_get(Screen *self, void UNUSED *closure) { PyObject *ans = self->modes.m##uname ? Py_True : Py_False; Py_INCREF(ans); return ans; } \
    static int name##_set(Screen *self, PyObject *val, void UNUSED *closure) { if (val == NULL) { PyErr_SetString(PyExc_TypeError, "Cannot delete attribute"); return -1; } set_mode_from_const(self, uname, PyObject_IsTrue(val) ? true : false); return 0; }

MODE_GETSET(in_bracketed_paste_mode, BRACKETED_PASTE)
MODE_GETSET(focus_tracking_enabled, FOCUS_TRACKING)
MODE_GETSET(auto_repeat_enabled, DECARM)
MODE_GETSET(cursor_visible, DECTCEM)
MODE_GETSET(cursor_key_mode, DECCKM)

static PyObject* disable_ligatures_get(Screen *self, void UNUSED *closure) {
    const char *ans = NULL;
    switch(self->disable_ligatures) {
        case DISABLE_LIGATURES_NEVER:
            ans = "never";
            break;
        case DISABLE_LIGATURES_CURSOR:
            ans = "cursor";
            break;
        case DISABLE_LIGATURES_ALWAYS:
            ans = "always";
            break;
    }
    return PyUnicode_FromString(ans);
}

static int disable_ligatures_set(Screen *self, PyObject *val, void UNUSED *closure) {
    if (val == NULL) { PyErr_SetString(PyExc_TypeError, "Cannot delete attribute"); return -1; }
    if (!PyUnicode_Check(val)) { PyErr_SetString(PyExc_TypeError, "unicode string expected"); return -1; }
    if (PyUnicode_READY(val) != 0) return -1;
    const char *q = PyUnicode_AsUTF8(val);
    DisableLigature dl = DISABLE_LIGATURES_NEVER;
    if (strcmp(q, "always") == 0) dl = DISABLE_LIGATURES_ALWAYS;
    else if (strcmp(q, "cursor") == 0) dl = DISABLE_LIGATURES_CURSOR;
    if (dl != self->disable_ligatures) {
        self->disable_ligatures = dl;
        screen_dirty_sprite_positions(self);
    }
    return 0;
}

static PyObject*
render_unfocused_cursor_get(Screen *self, void UNUSED *closure) {
    if (self->cursor_render_info.render_even_when_unfocused) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static int
render_unfocused_cursor_set(Screen *self, PyObject *val, void UNUSED *closure) {
    if (val == NULL) { PyErr_SetString(PyExc_TypeError, "Cannot delete attribute"); return -1; }
    self->cursor_render_info.render_even_when_unfocused = PyObject_IsTrue(val);
    return 0;
}

static PyObject*
cursor_up(Screen *self, PyObject *args) {
    unsigned int count = 1;
    int do_carriage_return = false, move_direction = -1;
    if (!PyArg_ParseTuple(args, "|Ipi", &count, &do_carriage_return, &move_direction)) return NULL;
    screen_cursor_up(self, count, do_carriage_return, move_direction);
    Py_RETURN_NONE;
}

static PyObject*
update_selection(Screen *self, PyObject *args) {
    unsigned int x, y;
    int in_left_half_of_cell = 0, ended = 1, nearest = 0;
    if (!PyArg_ParseTuple(args, "II|ppp", &x, &y, &in_left_half_of_cell, &ended, &nearest)) return NULL;
    screen_update_selection(self, x, y, in_left_half_of_cell, (SelectionUpdate){.ended = ended, .set_as_nearest_extend=nearest});
    Py_RETURN_NONE;
}

static PyObject*
clear_selection_(Screen *s, PyObject *args UNUSED) {
    clear_selection(&s->selections);
    Py_RETURN_NONE;
}

static PyObject*
resize(Screen *self, PyObject *args) {
    unsigned int a=1, b=1;
    if(!PyArg_ParseTuple(args, "|II", &a, &b)) return NULL;
    screen_resize(self, a, b);
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
}

WRAP0x(index)
WRAP0(reverse_index)
WRAP0(reset)
WRAP0(set_tab_stop)
WRAP1(clear_tab_stop, 0)
WRAP0(backspace)
WRAP0(tab)
WRAP0(linefeed)
WRAP0(carriage_return)
WRAP2(set_margins, 1, 1)
WRAP2(detect_url, 0, 0)
WRAP0(rescale_images)

static PyObject*
current_key_encoding_flags(Screen *self, PyObject *args UNUSED) {
    unsigned long ans = screen_current_key_encoding_flags(self);
    return PyLong_FromUnsignedLong(ans);
}

static PyObject*
ignore_bells_for(Screen *self, PyObject *args) {
    double duration = 1;
    if (!PyArg_ParseTuple(args, "|d", &duration)) return NULL;
    self->ignore_bells.start = monotonic();
    self->ignore_bells.duration = s_double_to_monotonic_t(duration);
    Py_RETURN_NONE;
}

static PyObject*
start_selection(Screen *self, PyObject *args) {
    unsigned int x, y;
    int rectangle_select = 0, extend_mode = EXTEND_CELL, in_left_half_of_cell = 1;
    if (!PyArg_ParseTuple(args, "II|pip", &x, &y, &rectangle_select, &extend_mode, &in_left_half_of_cell)) return NULL;
    screen_start_selection(self, x, y, in_left_half_of_cell, rectangle_select, extend_mode);
    Py_RETURN_NONE;
}

static PyObject*
is_rectangle_select(Screen *self, PyObject *a UNUSED) {
    if (self->selections.count && self->selections.items[0].rectangle_select) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static PyObject*
copy_colors_from(Screen *self, Screen *other) {
    copy_color_profile(self->color_profile, other->color_profile);
    Py_RETURN_NONE;
}

static PyObject*
text_for_selections(Screen *self, Selections *selections, bool ansi, bool strip_trailing_whitespace) {
    PyObject *lines = NULL;
    for (size_t i = 0; i < selections->count; i++) {
        PyObject *temp = ansi ? ansi_for_range(self, selections->items +i, true, strip_trailing_whitespace) : text_for_range(self, selections->items + i, true, strip_trailing_whitespace);
        if (temp) {
            if (lines) {
                lines = extend_tuple(lines, temp);
                Py_DECREF(temp);
            } else lines = temp;
        } else break;
    }
    if (PyErr_Occurred()) { Py_CLEAR(lines); return NULL; }
    if (!lines) lines = PyTuple_New(0);
    return lines;
}

static PyObject*
text_for_selection(Screen *self, PyObject *args) {
    int ansi = 0, strip_trailing_whitespace = 0;
    if (!PyArg_ParseTuple(args, "|pp", &ansi, &strip_trailing_whitespace)) return NULL;
    return text_for_selections(self, &self->selections, ansi, strip_trailing_whitespace);
}

static PyObject*
text_for_marked_url(Screen *self, PyObject *args) {
    int ansi = 0, strip_trailing_whitespace = 0;
    if (!PyArg_ParseTuple(args, "|pp", &ansi, &strip_trailing_whitespace)) return NULL;
    return text_for_selections(self, &self->url_ranges, ansi, strip_trailing_whitespace);
}


bool
screen_selection_range_for_line(Screen *self, index_type y, index_type *start, index_type *end) {
    if (y >= self->lines) { return false; }
    Line *line = visual_line_(self, y);
    index_type xlimit = line->xnum, xstart = 0;
    while (xlimit > 0 && CHAR_IS_BLANK(line->cpu_cells[xlimit - 1].ch)) xlimit--;
    while (xstart < xlimit && CHAR_IS_BLANK(line->cpu_cells[xstart].ch)) xstart++;
    *start = xstart; *end = xlimit > 0 ? xlimit - 1 : 0;
    return true;
}

static bool
is_opt_word_char(char_type ch, bool forward) {
    if (forward && OPT(select_by_word_characters_forward)) {
        for (const char_type *p = OPT(select_by_word_characters_forward); *p; p++) {
            if (ch == *p) return true;
        }
        if (*OPT(select_by_word_characters_forward)) {
            return false;
        }
    }
    if (OPT(select_by_word_characters)) {
        for (const char_type *p = OPT(select_by_word_characters); *p; p++) {
            if (ch == *p) return true;
        }
    }
    return false;
}

static bool
is_char_ok_for_word_extension(Line* line, index_type x, bool forward) {
    char_type ch = line->cpu_cells[x].ch;
    if (is_word_char(ch) || is_opt_word_char(ch, forward)) return true;
    // pass : from :// so that common URLs are matched
    if (ch == ':' && x + 2 < line->xnum && line->cpu_cells[x+1].ch == '/' && line->cpu_cells[x+2].ch == '/') return true;
    return false;
}

bool
screen_selection_range_for_word(Screen *self, const index_type x, const index_type y, index_type *y1, index_type *y2, index_type *s, index_type *e, bool initial_selection) {
    if (y >= self->lines || x >= self->columns) return false;
    index_type start, end;
    Line *line = visual_line_(self, y);
    *y1 = y;
    *y2 = y;
#define is_ok(x, forward) is_char_ok_for_word_extension(line, x, forward)
    if (!is_ok(x, false)) {
        if (initial_selection) return false;
        *s = x; *e = x;
        return true;
    }
    start = x; end = x;
    while(true) {
        while(start > 0 && is_ok(start - 1, false)) start--;
        if (start > 0 || !line->attrs.is_continued || *y1 == 0) break;
        line = visual_line_(self, *y1 - 1);
        if (!is_ok(self->columns - 1, false)) break;
        (*y1)--; start = self->columns - 1;
    }
    line = visual_line_(self, *y2);
    while(true) {
        while(end < self->columns - 1 && is_ok(end + 1, true)) end++;
        if (end < self->columns - 1 || *y2 >= self->lines - 1) break;
        line = visual_line_(self, *y2 + 1);
        if (!line->attrs.is_continued || !is_ok(0, true)) break;
        (*y2)++; end = 0;
    }
    *s = start; *e = end;
    return true;
#undef is_ok
}

bool
screen_history_scroll(Screen *self, int amt, bool upwards) {
    switch(amt) {
        case SCROLL_LINE:
            amt = 1;
            break;
        case SCROLL_PAGE:
            amt = self->lines - 1;
            break;
        case SCROLL_FULL:
            amt = self->historybuf->count;
            break;
        default:
            amt = MAX(0, amt);
            break;
    }
    if (!upwards) {
        amt = MIN((unsigned int)amt, self->scrolled_by);
        amt *= -1;
    }
    if (amt == 0) return false;
    unsigned int new_scroll = MIN(self->scrolled_by + amt, self->historybuf->count);
    if (new_scroll != self->scrolled_by) {
        self->scrolled_by = new_scroll;
        dirty_scroll(self);
        return true;
    }
    return false;
}

static PyObject*
scroll(Screen *self, PyObject *args) {
    int amt, upwards;
    if (!PyArg_ParseTuple(args, "ip", &amt, &upwards)) return NULL;
    if (screen_history_scroll(self, amt, upwards)) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

static PyObject*
scroll_to_prompt(Screen *self, PyObject *args) {
    int num_of_prompts = -1;
    if (!PyArg_ParseTuple(args, "|i", &num_of_prompts)) return NULL;
    if (screen_history_scroll_to_prompt(self, num_of_prompts)) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}


bool
screen_is_selection_dirty(Screen *self) {
    IterationData q;
    if (self->scrolled_by != self->last_rendered.scrolled_by) return true;
    if (self->selections.last_rendered_count != self->selections.count || self->url_ranges.last_rendered_count != self->url_ranges.count) return true;
    for (size_t i = 0; i < self->selections.count; i++) {
        iteration_data(self->selections.items + i, &q, self->columns, 0, self->scrolled_by);
        if (memcmp(&q, &self->selections.items[i].last_rendered, sizeof(IterationData)) != 0) return true;
    }
    for (size_t i = 0; i < self->url_ranges.count; i++) {
        iteration_data(self->url_ranges.items + i, &q, self->columns, 0, self->scrolled_by);
        if (memcmp(&q, &self->url_ranges.items[i].last_rendered, sizeof(IterationData)) != 0) return true;
    }
    return false;
}

void
screen_start_selection(Screen *self, index_type x, index_type y, bool in_left_half_of_cell, bool rectangle_select, SelectionExtendMode extend_mode) {
    screen_pause_rendering(self, false, 0);
#define A(attr, val) self->selections.items->attr = val;
    ensure_space_for(&self->selections, items, Selection, self->selections.count + 1, capacity, 1, false);
    memset(self->selections.items, 0, sizeof(Selection));
    self->selections.count = 1;
    self->selections.in_progress = true;
    self->selections.extend_mode = extend_mode;
    self->selections.items[0].last_rendered.y = INT_MAX;
    A(start.x, x); A(end.x, x); A(start.y, y); A(end.y, y); A(start_scrolled_by, self->scrolled_by); A(end_scrolled_by, self->scrolled_by);
    A(rectangle_select, rectangle_select); A(start.in_left_half_of_cell, in_left_half_of_cell); A(end.in_left_half_of_cell, in_left_half_of_cell);
    A(input_start.x, x); A(input_start.y, y); A(input_start.in_left_half_of_cell, in_left_half_of_cell);
    A(input_current.x, x); A(input_current.y, y); A(input_current.in_left_half_of_cell, in_left_half_of_cell);
#undef A
}

static void
add_url_range(Screen *self, index_type start_x, index_type start_y, index_type end_x, index_type end_y, bool is_hyperlink) {
#define A(attr, val) r->attr = val;
    ensure_space_for(&self->url_ranges, items, Selection, self->url_ranges.count + 8, capacity, 8, false);
    Selection *r = self->url_ranges.items + self->url_ranges.count++;
    memset(r, 0, sizeof(Selection));
    r->last_rendered.y = INT_MAX;
    r->is_hyperlink = is_hyperlink;
    A(start.x, start_x); A(end.x, end_x); A(start.y, start_y); A(end.y, end_y);
    A(start_scrolled_by, self->scrolled_by); A(end_scrolled_by, self->scrolled_by);
    A(start.in_left_half_of_cell, true);
#undef A
}

void
screen_mark_url(Screen *self, index_type start_x, index_type start_y, index_type end_x, index_type end_y) {
    self->url_ranges.count = 0;
    if (start_x || start_y || end_x || end_y) add_url_range(self, start_x, start_y, end_x, end_y, false);
}

static bool
mark_hyperlinks_in_line(Screen *self, Line *line, hyperlink_id_type id, index_type y) {
    index_type start = 0;
    bool found = false;
    bool in_range = false;
    for (index_type x = 0; x < line->xnum; x++) {
        bool has_hyperlink = line->cpu_cells[x].hyperlink_id == id;
        if (in_range) {
            if (!has_hyperlink) {
                add_url_range(self, start, y, x - 1, y, true);
                in_range = false;
                start = 0;
            }
        } else {
            if (has_hyperlink) {
                start = x; in_range = true;
                found = true;
            }
        }
    }
    if (in_range) add_url_range(self, start, y, self->columns - 1, y, true);
    return found;
}

static void
sort_ranges(const Screen *self, Selections *s) {
    IterationData a;
    for (size_t i = 0; i < s->count; i++) {
        iteration_data(s->items + i, &a, self->columns, 0, 0);
        s->items[i].sort_x = a.first.x;
        s->items[i].sort_y = a.y;
    }
#define range_lt(a, b) ((a)->sort_y < (b)->sort_y || ((a)->sort_y == (b)->sort_y && (a)->sort_x < (b)->sort_x))
    QSORT(Selection, s->items, s->count, range_lt);
#undef range_lt
}

hyperlink_id_type
screen_mark_hyperlink(Screen *self, index_type x, index_type y) {
    self->url_ranges.count = 0;
    Line *line = screen_visual_line(self, y);
    hyperlink_id_type id = line->cpu_cells[x].hyperlink_id;
    if (!id) return 0;
    index_type ypos = y, last_marked_line = y;
    do {
        if (mark_hyperlinks_in_line(self, line, id, ypos)) last_marked_line = ypos;
        if (ypos == 0) break;
        ypos--;
        line = screen_visual_line(self, ypos);
    } while (last_marked_line - ypos < 5);
    ypos = y + 1; last_marked_line = y;
    while (ypos < self->lines - 1 && ypos - last_marked_line < 5) {
        line = screen_visual_line(self, ypos);
        if (mark_hyperlinks_in_line(self, line, id, ypos)) last_marked_line = ypos;
        ypos++;
    }
    if (self->url_ranges.count > 1) sort_ranges(self, &self->url_ranges);
    return id;
}

static index_type
continue_line_upwards(Screen *self, index_type top_line, SelectionBoundary *start, SelectionBoundary *end) {
    while (top_line > 0 && visual_line_(self, top_line)->attrs.is_continued) {
        if (!screen_selection_range_for_line(self, top_line - 1, &start->x, &end->x)) break;
        top_line--;
    }
    return top_line;
}

static index_type
continue_line_downwards(Screen *self, index_type bottom_line, SelectionBoundary *start, SelectionBoundary *end) {
    while (bottom_line < self->lines - 1 && visual_line_(self, bottom_line + 1)->attrs.is_continued) {
        if (!screen_selection_range_for_line(self, bottom_line + 1, &start->x, &end->x)) break;
        bottom_line++;
    }
    return bottom_line;
}

void
screen_update_selection(Screen *self, index_type x, index_type y, bool in_left_half_of_cell, SelectionUpdate upd) {
    if (!self->selections.count) return;
    self->selections.in_progress = !upd.ended;
    Selection *s = self->selections.items;
    s->input_current.x = x; s->input_current.y = y;
    s->input_current.in_left_half_of_cell = in_left_half_of_cell;
    SelectionBoundary start, end, *a = &s->start, *b = &s->end, abs_start, abs_end, abs_current_input;
#define set_abs(which, initializer, scrolled_by) which = initializer; which.y = scrolled_by + self->lines - 1 - which.y;
    set_abs(abs_start, s->start, s->start_scrolled_by);
    set_abs(abs_end, s->end, s->end_scrolled_by);
    set_abs(abs_current_input, s->input_current, self->scrolled_by);
    bool return_word_sel_to_start_line = false;
    if (upd.set_as_nearest_extend || self->selections.extension_in_progress) {
        self->selections.extension_in_progress = true;
        bool start_is_nearer = false;
        if (self->selections.extend_mode == EXTEND_LINE || self->selections.extend_mode == EXTEND_LINE_FROM_POINT || self->selections.extend_mode == EXTEND_WORD_AND_LINE_FROM_POINT) {
            if (abs_start.y == abs_end.y) {
                if (abs_current_input.y == abs_start.y) start_is_nearer = selection_boundary_less_than(&abs_start, &abs_end) ? (abs_current_input.x <= abs_start.x) : (abs_current_input.x <= abs_end.x);
                else start_is_nearer = selection_boundary_less_than(&abs_start, &abs_end) ? (abs_current_input.y > abs_start.y) : (abs_current_input.y < abs_end.y);
            } else {
                start_is_nearer = num_lines_between_selection_boundaries(&abs_start, &abs_current_input) < num_lines_between_selection_boundaries(&abs_end, &abs_current_input);
            }
        } else start_is_nearer = num_cells_between_selection_boundaries(self, &abs_start, &abs_current_input) < num_cells_between_selection_boundaries(self, &abs_end, &abs_current_input);
        if (start_is_nearer) s->adjusting_start = true;
    } else if (!upd.start_extended_selection && self->selections.extend_mode != EXTEND_CELL) {
        SelectionBoundary abs_initial_start, abs_initial_end;
        set_abs(abs_initial_start, s->initial_extent.start, s->initial_extent.scrolled_by);
        set_abs(abs_initial_end, s->initial_extent.end, s->initial_extent.scrolled_by);
        if (self->selections.extend_mode == EXTEND_WORD) {
            if (abs_current_input.y == abs_initial_start.y && abs_start.y != abs_end.y) {
                if (abs_start.y != abs_initial_start.y) s->adjusting_start = true;
                else if (abs_end.y != abs_initial_start.y) s->adjusting_start = false;
                else s->adjusting_start = selection_boundary_less_than(&abs_current_input, &abs_initial_end);
                return_word_sel_to_start_line = true;
            } else {
                if (s->adjusting_start) s->adjusting_start = selection_boundary_less_than(&abs_current_input, &abs_initial_end);
                else s->adjusting_start = selection_boundary_less_than(&abs_current_input, &abs_initial_start);
            }
        } else {
            const unsigned int initial_line = abs_initial_start.y;
            if (initial_line == abs_current_input.y) {
                s->adjusting_start = false;
                s->start = s->initial_extent.start; s->start_scrolled_by = s->initial_extent.scrolled_by;
                s->end = s->initial_extent.end; s->end_scrolled_by = s->initial_extent.scrolled_by;
            }
            else {
                s->adjusting_start = abs_current_input.y > initial_line;
            }
        }
    }
#undef set_abs
    bool adjusted_boundary_is_before;
    if (s->adjusting_start) adjusted_boundary_is_before = selection_boundary_less_than(&abs_start, &abs_end);
    else { adjusted_boundary_is_before = selection_boundary_less_than(&abs_end, &abs_start); }

    switch(self->selections.extend_mode) {
        case EXTEND_WORD: {
            if (!s->adjusting_start) { a = &s->end; b = &s->start; }
            const bool word_found_at_cursor = screen_selection_range_for_word(self, s->input_current.x, s->input_current.y, &start.y, &end.y, &start.x, &end.x, true);
            bool adjust_both_ends = is_selection_empty(s);
            if (return_word_sel_to_start_line) {
                index_type ox = a->x;
                if (s->adjusting_start) { *a = s->initial_extent.start; if (ox < a->x) a->x = ox; }
                else { *a = s->initial_extent.end; if (ox > a->x) a->x = ox; }
            } else if (word_found_at_cursor) {
                if (adjusted_boundary_is_before) {
                    *a = start; a->in_left_half_of_cell = true;
                    if (adjust_both_ends) { *b = end; b->in_left_half_of_cell = false; }
                } else {
                    *a = end; a->in_left_half_of_cell = false;
                    if (adjust_both_ends) { *b = start; b->in_left_half_of_cell = true; }
                }
                if (s->adjusting_start || adjust_both_ends) s->start_scrolled_by = self->scrolled_by;
                if (!s->adjusting_start || adjust_both_ends) s->end_scrolled_by = self->scrolled_by;
            } else {
                *a = s->input_current;
                if (s->adjusting_start) s->start_scrolled_by = self->scrolled_by; else s->end_scrolled_by = self->scrolled_by;
            }
            break;
        }
        case EXTEND_LINE_FROM_POINT:
        case EXTEND_WORD_AND_LINE_FROM_POINT:
        case EXTEND_LINE: {
            bool adjust_both_ends = is_selection_empty(s);
            if (s->adjusting_start || adjust_both_ends) s->start_scrolled_by = self->scrolled_by;
            if (!s->adjusting_start || adjust_both_ends) s->end_scrolled_by = self->scrolled_by;
            index_type top_line, bottom_line;
            SelectionBoundary up_start, up_end, down_start, down_end;
            if (adjust_both_ends) {
                // empty initial selection
                top_line = s->input_current.y; bottom_line = s->input_current.y;
                if (screen_selection_range_for_line(self, top_line, &up_start.x, &up_end.x)) {
#define S \
    s->start.y = top_line; s->end.y = bottom_line; \
    s->start.in_left_half_of_cell = true; s->end.in_left_half_of_cell = false; \
    s->start.x = up_start.x; s->end.x = bottom_line == top_line ? up_end.x : down_end.x;
                    down_start = up_start; down_end = up_end;
                    bottom_line = continue_line_downwards(self, bottom_line, &down_start, &down_end);
                    if (self->selections.extend_mode == EXTEND_LINE_FROM_POINT) {
                        if (x <= up_end.x) {
                            S; s->start.x = MAX(x, up_start.x);
                        }
                    } else if (self->selections.extend_mode == EXTEND_WORD_AND_LINE_FROM_POINT) {
                        if (x <= up_end.x) {
                            S; s->start.x = MAX(x, up_start.x);
                        }
                        const bool word_found_at_cursor = screen_selection_range_for_word(self, s->input_current.x, s->input_current.y, &start.y, &end.y, &start.x, &end.x, true);
                        if (word_found_at_cursor) {
                            *a = start; a->in_left_half_of_cell = true;
                        }
                    } else {
                        top_line = continue_line_upwards(self, top_line, &up_start, &up_end);
                        S;
                    }
                }
#undef S
            } else {
                // extending an existing selection
                top_line = s->input_current.y; bottom_line = s->input_current.y;
                if (screen_selection_range_for_line(self, top_line, &up_start.x, &up_end.x)) {
                    down_start = up_start; down_end = up_end;
                    top_line = continue_line_upwards(self, top_line, &up_start, &up_end);
                    bottom_line = continue_line_downwards(self, bottom_line, &down_start, &down_end);
                    if (!s->adjusting_start) { a = &s->end; b = &s->start; }
                    if (adjusted_boundary_is_before) {
                        a->in_left_half_of_cell = true; a->x = up_start.x; a->y = top_line;
                    } else {
                        a->in_left_half_of_cell = false; a->x = down_end.x; a->y = bottom_line;
                    }
                    // allow selecting whitespace at the start of the top line
                    if (a->y == top_line && s->input_current.y == top_line && s->input_current.x < a->x && adjusted_boundary_is_before) a->x = s->input_current.x;
                }
            }
        }
        break;
        case EXTEND_CELL:
            if (s->adjusting_start) b = &s->start;
            b->x = x; b->y = y; b->in_left_half_of_cell = in_left_half_of_cell;
            if (s->adjusting_start) s->start_scrolled_by = self->scrolled_by; else s->end_scrolled_by = self->scrolled_by;
            break;
    }
    if (!self->selections.in_progress) {
        s->adjusting_start = false;
        self->selections.extension_in_progress = false;
        call_boss(set_primary_selection, NULL);
    } else {
        if (upd.start_extended_selection && self->selections.extend_mode != EXTEND_CELL) {
            s->initial_extent.start = s->start; s->initial_extent.end = s->end;
            s->initial_extent.scrolled_by = s->start_scrolled_by;
        }
    }
}

static PyObject*
mark_as_dirty(Screen *self, PyObject *a UNUSED) {
    self->is_dirty = true;
    Py_RETURN_NONE;
}

static PyObject*
reload_all_gpu_data(Screen *self, PyObject *a UNUSED) {
    self->reload_all_gpu_data = true;
    Py_RETURN_NONE;
}


static PyObject*
current_char_width(Screen *self, PyObject *a UNUSED) {
#define current_char_width_doc "The width of the character under the cursor"
    return PyLong_FromUnsignedLong(screen_current_char_width(self));
}

static PyObject*
is_main_linebuf(Screen *self, PyObject *a UNUSED) {
    PyObject *ans = (self->linebuf == self->main_linebuf) ? Py_True : Py_False;
    Py_INCREF(ans);
    return ans;
}

static PyObject*
toggle_alt_screen(Screen *self, PyObject *a UNUSED) {
    screen_toggle_screen_buffer(self, true, true);
    Py_RETURN_NONE;
}

static PyObject*
send_escape_code_to_child(Screen *self, PyObject *args) {
    int code;
    PyObject *O;
    if (!PyArg_ParseTuple(args, "iO", &code, &O)) return NULL;
    bool written = false;
    if (PyBytes_Check(O)) written = write_escape_code_to_child(self, code, PyBytes_AS_STRING(O));
    else if (PyUnicode_Check(O)) {
        const char *t = PyUnicode_AsUTF8(O);
        if (t) written = write_escape_code_to_child(self, code, t);
        else return NULL;
    } else if (PyTuple_Check(O)) written = write_escape_code_to_child_python(self, code, O);
    else PyErr_SetString(PyExc_TypeError, "escape code must be str, bytes or tuple");
    if (PyErr_Occurred()) return NULL;
    if (written) { Py_RETURN_TRUE; } else { Py_RETURN_FALSE; }
}

static void
screen_mark_all(Screen *self) {
    for (index_type y = 0; y < self->main_linebuf->ynum; y++) {
        linebuf_init_line(self->main_linebuf, y);
        mark_text_in_line(self->marker, self->main_linebuf->line);
    }
    for (index_type y = 0; y < self->alt_linebuf->ynum; y++) {
        linebuf_init_line(self->alt_linebuf, y);
        mark_text_in_line(self->marker, self->alt_linebuf->line);
    }
    for (index_type y = 0; y < self->historybuf->count; y++) {
        historybuf_init_line(self->historybuf, y, self->historybuf->line);
        mark_text_in_line(self->marker, self->historybuf->line);
    }
    self->is_dirty = true;
}

static PyObject*
set_marker(Screen *self, PyObject *args) {
    PyObject *marker = NULL;
    if (!PyArg_ParseTuple(args, "|O", &marker)) return NULL;
    if (!marker) {
        if (self->marker) {
            Py_CLEAR(self->marker);
            screen_mark_all(self);
        }
        Py_RETURN_NONE;
    }
    if (!PyCallable_Check(marker)) {
        PyErr_SetString(PyExc_TypeError, "marker must be a callable");
        return NULL;
    }
    self->marker = marker;
    Py_INCREF(marker);
    screen_mark_all(self);
    Py_RETURN_NONE;
}


static PyObject*
scroll_to_next_mark(Screen *self, PyObject *args) {
    int backwards = 1;
    unsigned int mark = 0;
    if (!PyArg_ParseTuple(args, "|Ip", &mark, &backwards)) return NULL;
    if (!screen_has_marker(self) || self->linebuf == self->alt_linebuf) Py_RETURN_FALSE;
    if (backwards) {
        for (unsigned int y = self->scrolled_by; y < self->historybuf->count; y++) {
            historybuf_init_line(self->historybuf, y, self->historybuf->line);
            if (line_has_mark(self->historybuf->line, mark)) {
                screen_history_scroll(self, y - self->scrolled_by + 1, true);
                Py_RETURN_TRUE;
            }
        }
    } else {
        Line *line;
        for (unsigned int y = self->scrolled_by; y > 0; y--) {
            if (y > self->lines) {
                historybuf_init_line(self->historybuf, y - self->lines, self->historybuf->line);
                line = self->historybuf->line;
            } else {
                linebuf_init_line(self->linebuf, self->lines - y);
                line = self->linebuf->line;
            }
            if (line_has_mark(line, mark)) {
                screen_history_scroll(self, self->scrolled_by - y + 1, false);
                Py_RETURN_TRUE;
            }
        }
    }
    Py_RETURN_FALSE;
}

static PyObject*
marked_cells(Screen *self, PyObject *o UNUSED) {
    PyObject *ans = PyList_New(0);
    if (!ans) return ans;
    for (index_type y = 0; y < self->lines; y++) {
        linebuf_init_line(self->linebuf, y);
        for (index_type x = 0; x < self->columns; x++) {
            GPUCell *gpu_cell = self->linebuf->line->gpu_cells + x;
            const unsigned int mark = gpu_cell->attrs.mark;
            if (mark) {
                PyObject *t = Py_BuildValue("III", x, y, mark);
                if (!t) { Py_DECREF(ans); return NULL; }
                if (PyList_Append(ans, t) != 0) { Py_DECREF(t); Py_DECREF(ans); return NULL; }
                Py_DECREF(t);
            }
        }
    }
    return ans;
}

static PyObject*
paste_(Screen *self, PyObject *bytes, bool allow_bracketed_paste) {
    const char *data; Py_ssize_t sz;
    if (PyBytes_Check(bytes)) {
        data = PyBytes_AS_STRING(bytes); sz = PyBytes_GET_SIZE(bytes);
    } else if (PyMemoryView_Check(bytes)) {
        RAII_PyObject(mv, PyMemoryView_GetContiguous(bytes, PyBUF_READ, PyBUF_C_CONTIGUOUS));
        if (mv == NULL) return NULL;
        Py_buffer *buf = PyMemoryView_GET_BUFFER(mv);
        data = buf->buf;
        sz = buf->len;
    } else {
        PyErr_SetString(PyExc_TypeError, "Must paste() bytes"); return NULL;
    }
    if (allow_bracketed_paste && self->modes.mBRACKETED_PASTE) write_escape_code_to_child(self, ESC_CSI, BRACKETED_PASTE_START);
    write_to_child(self, data, sz);
    if (allow_bracketed_paste && self->modes.mBRACKETED_PASTE) write_escape_code_to_child(self, ESC_CSI, BRACKETED_PASTE_END);
    Py_RETURN_NONE;
}


static PyObject*
paste(Screen *self, PyObject *bytes) {
    return paste_(self, bytes, true);
}

static PyObject*
paste_bytes(Screen *self, PyObject *bytes) {
    return paste_(self, bytes, false);
}

static PyObject*
focus_changed(Screen *self, PyObject *has_focus_) {
    bool previous = self->has_focus;
    bool has_focus = PyObject_IsTrue(has_focus_) ? true : false;
    if (has_focus != previous) {
        self->has_focus = has_focus;
        if (has_focus) self->has_activity_since_last_focus = false;
        else if (screen_is_overlay_active(self)) deactivate_overlay_line(self);
        if (self->modes.mFOCUS_TRACKING) write_escape_code_to_child(self, ESC_CSI, has_focus ? "I" : "O");
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

static PyObject*
has_focus(Screen *self, PyObject *args UNUSED) {
    if (self->has_focus) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static PyObject*
has_activity_since_last_focus(Screen *self, PyObject *args UNUSED) {
    if (self->has_activity_since_last_focus) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

WRAP2(cursor_position, 1, 1)

#define COUNT_WRAP(name) WRAP1(name, 1)
COUNT_WRAP(insert_lines)
COUNT_WRAP(delete_lines)
COUNT_WRAP(insert_characters)
COUNT_WRAP(delete_characters)
COUNT_WRAP(erase_characters)
COUNT_WRAP(cursor_up1)
COUNT_WRAP(cursor_down)
COUNT_WRAP(cursor_down1)
COUNT_WRAP(cursor_forward)

static PyObject*
screen_is_emoji_presentation_base(PyObject UNUSED *self, PyObject *code_) {
    unsigned long code = PyLong_AsUnsignedLong(code_);
    if (is_emoji_presentation_base(code)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static PyObject*
hyperlink_at(Screen *self, PyObject *args) {
    unsigned int x, y;
    if (!PyArg_ParseTuple(args, "II", &x, &y)) return NULL;
    screen_mark_hyperlink(self, x, y);
    if (!self->url_ranges.count) Py_RETURN_NONE;
    hyperlink_id_type hid = hyperlink_id_for_range(self, self->url_ranges.items);
    if (!hid) Py_RETURN_NONE;
    const char *url = get_hyperlink_for_id(self->hyperlink_pool, hid, true);
    return Py_BuildValue("s", url);
}

static PyObject*
reverse_scroll(Screen *self, PyObject *args) {
    int fill_from_scrollback = 0;
    unsigned int amt;
    if (!PyArg_ParseTuple(args, "I|p", &amt, &fill_from_scrollback)) return NULL;
    _reverse_scroll(self, amt, fill_from_scrollback);
    Py_RETURN_NONE;
}


static PyObject*
scroll_prompt_to_bottom(Screen *self, PyObject *args UNUSED) {
    if (self->linebuf != self->main_linebuf || !self->historybuf->count) Py_RETURN_NONE;
    int q = screen_cursor_at_a_shell_prompt(self);
    index_type limit_y = q > -1 ? (unsigned int)q : self->cursor->y;
    index_type y = self->lines - 1;
    // not before prompt or cursor line
    while (y > limit_y) {
        Line *line = checked_range_line(self, y);
        if (!line || line_length(line)) break;
        y--;
    }
    // don't scroll back beyond the history buffer range
    unsigned int count = MIN(self->lines - (y + 1), self->historybuf->count);
    if (count > 0) {
        _reverse_scroll(self, count, true);
        screen_cursor_down(self, count);
    }
    // always scroll to the bottom
    if (self->scrolled_by != 0) {
        self->scrolled_by = 0;
        dirty_scroll(self);
    }
    Py_RETURN_NONE;
}

static PyObject*
dump_lines_with_attrs(Screen *self, PyObject *accum) {
    int y = (self->linebuf == self->main_linebuf) ? -self->historybuf->count : 0;
    PyObject *t;
    while (y < (int)self->lines) {
        Line *line = range_line_(self, y);
        t = PyUnicode_FromFormat("\x1b[31m%d: \x1b[39m", y++);
        if (t) {
            PyObject_CallFunctionObjArgs(accum, t, NULL);
            Py_DECREF(t);
        }
        switch (line->attrs.prompt_kind) {
            case UNKNOWN_PROMPT_KIND:
                break;
            case PROMPT_START:
                PyObject_CallFunction(accum, "s", "\x1b[32mprompt \x1b[39m");
                break;
            case SECONDARY_PROMPT:
                PyObject_CallFunction(accum, "s", "\x1b[32msecondary_prompt \x1b[39m");
                break;
            case OUTPUT_START:
                PyObject_CallFunction(accum, "s", "\x1b[33moutput \x1b[39m");
                break;
        }
        if (line->attrs.is_continued) PyObject_CallFunction(accum, "s", "continued ");
        if (line->attrs.has_dirty_text) PyObject_CallFunction(accum, "s", "dirty ");
        PyObject_CallFunction(accum, "s", "\n");
        t = line_as_unicode(line, false);
        if (t) {
            PyObject_CallFunctionObjArgs(accum, t, NULL);
            Py_DECREF(t);
        }
        PyObject_CallFunction(accum, "s", "\n");
    }
    Py_RETURN_NONE;
}

static PyObject*
cursor_at_prompt(Screen *self, PyObject *args UNUSED) {
    int y = screen_cursor_at_a_shell_prompt(self);
    if (y > -1) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

static PyObject*
line_edge_colors(Screen *self, PyObject *a UNUSED) {
    color_type left, right;
    if (!get_line_edge_colors(self, &left, &right)) { PyErr_SetString(PyExc_IndexError, "Line number out of range"); return NULL; }
    return Py_BuildValue("kk", (unsigned long)left, (unsigned long)right);
}

WRAP0(update_only_line_graphics_data)
WRAP0(bell)

#define MND(name, args) {#name, (PyCFunction)name, args, #name},
#define MODEFUNC(name) MND(name, METH_NOARGS) MND(set_##name, METH_O)

static PyObject*
test_create_write_buffer(Screen *screen UNUSED, PyObject *args UNUSED) {
    size_t s;
    uint8_t *buf = vt_parser_create_write_buffer(screen->vt_parser, &s);
    return PyMemoryView_FromMemory((char*)buf, s, PyBUF_WRITE);
}

static PyObject*
test_commit_write_buffer(Screen *screen, PyObject *args) {
    RAII_PY_BUFFER(srcbuf); RAII_PY_BUFFER(destbuf);
    if (!PyArg_ParseTuple(args, "y*y*", &srcbuf, &destbuf)) return NULL;
    size_t s = MIN(srcbuf.len, destbuf.len);
    memcpy(destbuf.buf, srcbuf.buf, s);
    vt_parser_commit_write(screen->vt_parser, s);
    return PyLong_FromSize_t(s);
}

static PyObject*
test_parse_written_data(Screen *screen, PyObject *args) {
    ParseData pd = {.now=monotonic()};
    if (!PyArg_ParseTuple(args, "|O", &pd.dump_callback)) return NULL;
    if (pd.dump_callback && pd.dump_callback != Py_None) parse_worker_dump(screen, &pd, true);
    else parse_worker(screen, &pd, true);
    Py_RETURN_NONE;
}

static PyMethodDef methods[] = {
    METHODB(test_create_write_buffer, METH_NOARGS),
    METHODB(test_commit_write_buffer, METH_VARARGS),
    METHODB(test_parse_written_data, METH_VARARGS),
    MND(line_edge_colors, METH_NOARGS)
    MND(line, METH_O)
    MND(dump_lines_with_attrs, METH_O)
    MND(cursor_at_prompt, METH_NOARGS)
    MND(visual_line, METH_VARARGS)
    MND(current_url_text, METH_NOARGS)
    MND(draw, METH_O)
    MND(apply_sgr, METH_O)
    MND(cursor_position, METH_VARARGS)
    MND(set_window_char, METH_VARARGS)
    MND(set_mode, METH_VARARGS)
    MND(reset_mode, METH_VARARGS)
    MND(reset, METH_NOARGS)
    MND(reset_dirty, METH_NOARGS)
    MND(is_using_alternate_linebuf, METH_NOARGS)
    MND(is_main_linebuf, METH_NOARGS)
    MND(cursor_back, METH_VARARGS)
    MND(erase_in_line, METH_VARARGS)
    MND(erase_in_display, METH_VARARGS)
    MND(clear_scrollback, METH_NOARGS)
    MND(scroll_until_cursor_prompt, METH_NOARGS)
    MND(hyperlinks_as_list, METH_NOARGS)
    MND(garbage_collect_hyperlink_pool, METH_NOARGS)
    MND(hyperlink_for_id, METH_O)
    MND(reverse_scroll, METH_VARARGS)
    MND(scroll_prompt_to_bottom, METH_NOARGS)
    METHOD(current_char_width, METH_NOARGS)
    MND(insert_lines, METH_VARARGS)
    MND(delete_lines, METH_VARARGS)
    MND(insert_characters, METH_VARARGS)
    MND(delete_characters, METH_VARARGS)
    MND(erase_characters, METH_VARARGS)
    MND(current_pointer_shape, METH_NOARGS)
    MND(change_pointer_shape, METH_VARARGS)
    MND(cursor_up, METH_VARARGS)
    MND(cursor_up1, METH_VARARGS)
    MND(cursor_down, METH_VARARGS)
    MND(cursor_down1, METH_VARARGS)
    MND(cursor_forward, METH_VARARGS)
    {"index", (PyCFunction)xxx_index, METH_VARARGS, ""},
    {"has_selection", (PyCFunction)has_selection, METH_VARARGS, ""},
    MND(as_text, METH_VARARGS)
    MND(as_text_non_visual, METH_VARARGS)
    MND(as_text_for_history_buf, METH_VARARGS)
    MND(as_text_alternate, METH_VARARGS)
    MND(cmd_output, METH_VARARGS)
    MND(tab, METH_NOARGS)
    MND(backspace, METH_NOARGS)
    MND(linefeed, METH_NOARGS)
    MND(carriage_return, METH_NOARGS)
    MND(set_tab_stop, METH_NOARGS)
    MND(clear_tab_stop, METH_VARARGS)
    MND(start_selection, METH_VARARGS)
    MND(update_selection, METH_VARARGS)
    {"clear_selection", (PyCFunction)clear_selection_, METH_NOARGS, ""},
    MND(reverse_index, METH_NOARGS)
    MND(mark_as_dirty, METH_NOARGS)
    MND(reload_all_gpu_data, METH_NOARGS)
    MND(resize, METH_VARARGS)
    MND(ignore_bells_for, METH_VARARGS)
    MND(set_margins, METH_VARARGS)
    MND(detect_url, METH_VARARGS)
    MND(rescale_images, METH_NOARGS)
    MND(current_key_encoding_flags, METH_NOARGS)
    MND(text_for_selection, METH_VARARGS)
    MND(text_for_marked_url, METH_VARARGS)
    MND(is_rectangle_select, METH_NOARGS)
    MND(scroll, METH_VARARGS)
    MND(scroll_to_prompt, METH_VARARGS)
    MND(send_escape_code_to_child, METH_VARARGS)
    MND(hyperlink_at, METH_VARARGS)
    MND(toggle_alt_screen, METH_NOARGS)
    MND(reset_callbacks, METH_NOARGS)
    MND(paste, METH_O)
    MND(paste_bytes, METH_O)
    MND(focus_changed, METH_O)
    MND(has_focus, METH_NOARGS)
    MND(has_activity_since_last_focus, METH_NOARGS)
    MND(copy_colors_from, METH_O)
    MND(set_marker, METH_VARARGS)
    MND(marked_cells, METH_NOARGS)
    MND(scroll_to_next_mark, METH_VARARGS)
    MND(update_only_line_graphics_data, METH_NOARGS)
    MND(bell, METH_NOARGS)
    {"select_graphic_rendition", (PyCFunction)_select_graphic_rendition, METH_VARARGS, ""},

    {NULL}  /* Sentinel */
};

static PyGetSetDef getsetters[] = {
    GETSET(in_bracketed_paste_mode)
    GETSET(auto_repeat_enabled)
    GETSET(focus_tracking_enabled)
    GETSET(cursor_visible)
    GETSET(cursor_key_mode)
    GETSET(disable_ligatures)
    GETSET(render_unfocused_cursor)
    {NULL}  /* Sentinel */
};

#if UINT_MAX == UINT32_MAX
#define T_COL T_UINT
#elif ULONG_MAX == UINT32_MAX
#define T_COL T_ULONG
#else
#error Neither int nor long is 4-bytes in size
#endif

static PyMemberDef members[] = {
    {"callbacks", T_OBJECT_EX, offsetof(Screen, callbacks), 0, "callbacks"},
    {"cursor", T_OBJECT_EX, offsetof(Screen, cursor), READONLY, "cursor"},
    {"vt_parser", T_OBJECT_EX, offsetof(Screen, vt_parser), READONLY, "vt_parser"},
    {"last_reported_cwd", T_OBJECT, offsetof(Screen, last_reported_cwd), READONLY, "last_reported_cwd"},
    {"grman", T_OBJECT_EX, offsetof(Screen, grman), READONLY, "grman"},
    {"color_profile", T_OBJECT_EX, offsetof(Screen, color_profile), READONLY, "color_profile"},
    {"linebuf", T_OBJECT_EX, offsetof(Screen, linebuf), READONLY, "linebuf"},
    {"main_linebuf", T_OBJECT_EX, offsetof(Screen, main_linebuf), READONLY, "main_linebuf"},
    {"historybuf", T_OBJECT_EX, offsetof(Screen, historybuf), READONLY, "historybuf"},
    {"scrolled_by", T_UINT, offsetof(Screen, scrolled_by), READONLY, "scrolled_by"},
    {"lines", T_UINT, offsetof(Screen, lines), READONLY, "lines"},
    {"columns", T_UINT, offsetof(Screen, columns), READONLY, "columns"},
    {"margin_top", T_UINT, offsetof(Screen, margin_top), READONLY, "margin_top"},
    {"margin_bottom", T_UINT, offsetof(Screen, margin_bottom), READONLY, "margin_bottom"},
    {"history_line_added_count", T_UINT, offsetof(Screen, history_line_added_count), 0, "history_line_added_count"},
    {NULL}
};

PyTypeObject Screen_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.Screen",
    .tp_basicsize = sizeof(Screen),
    .tp_dealloc = (destructor)dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Screen",
    .tp_methods = methods,
    .tp_members = members,
    .tp_new = new,
    .tp_getset = getsetters,
};

static PyMethodDef module_methods[] = {
    {"is_emoji_presentation_base", (PyCFunction)screen_is_emoji_presentation_base, METH_O, ""},
    {"truncate_point_for_length", (PyCFunction)screen_truncate_point_for_length, METH_VARARGS, ""},
    {NULL}  /* Sentinel */
};

INIT_TYPE(Screen)
// }}}
