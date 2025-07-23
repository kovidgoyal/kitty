/*
 * screen.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define EXTRA_INIT { \
    PyModule_AddIntMacro(module, SCROLL_LINE); PyModule_AddIntMacro(module, SCROLL_PAGE); PyModule_AddIntMacro(module, SCROLL_FULL); \
    PyModule_AddIntMacro(module, EXTEND_CELL); PyModule_AddIntMacro(module, EXTEND_WORD); PyModule_AddIntMacro(module, EXTEND_LINE); \
    PyModule_AddIntMacro(module, SCALE_BITS); PyModule_AddIntMacro(module, WIDTH_BITS); PyModule_AddIntMacro(module, SUBSCALE_BITS); \
    if (PyModule_AddFunctions(module, module_methods) != 0) return false; \
}

#include "data-types.h"
#include "control-codes.h"
#include "screen.h"
#include "state.h"
#include "iqsort.h"
#include "fonts.h"
#include "charsets.h"
#include "lineops.h"
#include "hyperlink.h"
#include <structmember.h>
#include <limits.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include "unicode-data.h"
#include "modes.h"
#include "char-props.h"
#include "wcswidth.h"
#include <stdalign.h>
#include "keys.h"
#include "vt-parser.h"
#include "resize.h"

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
clear_all_selections(Screen *self) { clear_selection(&self->selections); clear_selection(&self->url_ranges); }


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
new_screen_object(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
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
        self->text_cache = tc_alloc(); if (!self->text_cache) { Py_CLEAR(self); return PyErr_NoMemory(); }
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
        self->main_linebuf = alloc_linebuf(lines, columns, self->text_cache); self->alt_linebuf = alloc_linebuf(lines, columns, self->text_cache);
        self->linebuf = self->main_linebuf;
        self->historybuf = alloc_historybuf(MAX(scrollback, lines), columns, OPT(scrollback_pager_history_size), self->text_cache);
        self->main_grman = grman_alloc(false);
        self->alt_grman = grman_alloc(false);
        self->active_hyperlink_id = 0;

        self->grman = self->main_grman;
        self->disable_ligatures = OPT(disable_ligatures);
        self->main_tabstops = PyMem_Calloc(2 * self->columns, sizeof(bool));
        self->lc = alloc_list_of_chars();
        if (
            self->cursor == NULL || self->main_linebuf == NULL || self->alt_linebuf == NULL ||
            self->main_tabstops == NULL || self->historybuf == NULL || self->main_grman == NULL ||
            self->alt_grman == NULL || self->color_profile == NULL || self->lc == NULL
        ) {
            Py_CLEAR(self); return NULL;
        }
        grman_set_window_id(self->main_grman, self->window_id);
        grman_set_window_id(self->alt_grman, self->window_id);
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
    grman_clear(self->main_grman, false, self->cell_size);  // dont delete images in scrollback
    grman_clear(self->alt_grman, true, self->cell_size);
    self->modes = empty_modes;
    self->saved_modes = empty_modes;
    self->active_hyperlink_id = 0;
    zero_at_ptr(&self->color_profile->overridden);
    reset_vt_parser(self->vt_parser);
    zero_at_ptr(&self->charset);
    self->margin_top = 0; self->margin_bottom = self->lines - 1;
    screen_normal_keypad_mode(self);
    init_tabstops(self->main_tabstops, self->columns);
    init_tabstops(self->alt_tabstops, self->columns);
    cursor_reset(self->cursor);
    self->is_dirty = true;
    clear_all_selections(self);
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

typedef struct CursorTrack {
    index_type num_content_lines;
    bool is_beyond_content;
    struct { index_type x, y; } before;
    struct { index_type x, y; } after;
    struct { index_type x, y; } temp;
} CursorTrack;

static bool
rewrap(Screen *screen, unsigned int lines, unsigned int columns, index_type *nclb, index_type *ncla, CursorTrack *cursor, CursorTrack *main_saved_cursor, CursorTrack *alt_saved_cursor, bool main_is_active) {
    TrackCursor cursors[3];
    cursors[2].is_sentinel = true;
    cursors[0] = (TrackCursor){.x=main_saved_cursor->before.x, .y=main_saved_cursor->before.y};
    if (main_is_active) cursors[1] = (TrackCursor){.x=cursor->before.x, .y=cursor->before.y};
    else cursors[1].is_sentinel = true;
    ResizeResult mr = resize_screen_buffers(screen->main_linebuf, screen->historybuf, lines, columns, &screen->as_ansi_buf, cursors);
    if (!mr.ok) { PyErr_NoMemory(); return false; }
    main_saved_cursor->temp.x = cursors[0].dest_x; main_saved_cursor->temp.y = cursors[0].dest_y;
    if (main_is_active) { cursor->temp.x = cursors[1].dest_x; cursor->temp.y = cursors[1].dest_y; }

    cursors[0] = (TrackCursor){.x=alt_saved_cursor->before.x, .y=alt_saved_cursor->before.y};
    if (!main_is_active) cursors[1] = (TrackCursor){.x=cursor->before.x, .y=cursor->before.y};
    else cursors[1].is_sentinel = true;
    ResizeResult ar = resize_screen_buffers(screen->alt_linebuf, NULL, lines, columns, &screen->as_ansi_buf, cursors);
    if (!ar.ok) {
        Py_DecRef((PyObject*)mr.lb); Py_DecRef((PyObject*)mr.hb);
        PyErr_NoMemory(); return false;
    }
    alt_saved_cursor->temp.x = cursors[0].dest_x; alt_saved_cursor->temp.y = cursors[0].dest_y;
    if (!main_is_active) { cursor->temp.x = cursors[1].dest_x; cursor->temp.y = cursors[1].dest_y; }
    Py_CLEAR(screen->main_linebuf); Py_CLEAR(screen->alt_linebuf); Py_CLEAR(screen->historybuf);
    screen->main_linebuf = mr.lb; screen->historybuf = mr.hb; screen->alt_linebuf = ar.lb;
    screen->linebuf = main_is_active ? screen->main_linebuf : screen->alt_linebuf;
    if (main_is_active) {
        *nclb = mr.num_content_lines_before; *ncla = mr.num_content_lines_after;
    } else {
        *nclb = ar.num_content_lines_before; *ncla = ar.num_content_lines_after;
    }
    return true;
}

static bool
is_selection_empty(const Selection *s) {
    int start_y = (int)s->start.y - (int)s->start_scrolled_by, end_y = (int)s->end.y - (int)s->end_scrolled_by;
    return s->start.x == s->end.x && s->start.in_left_half_of_cell == s->end.in_left_half_of_cell && start_y == end_y;
}

static bool
selection_intersects_screen_lines(const Selections *selections, int a, int b) {
    if (a > b) SWAP(a, b);
    for (size_t i = 0; i < selections->count; i++) {
        const Selection *s = selections->items + i;
        if (!is_selection_empty(s)) {
            int start = (int)s->start.y - s->start_scrolled_by;
            int end = (int)s->end.y - s->end_scrolled_by;
            int top = MIN(start, end);
            int bottom = MAX(start, end);
            if ((top <= a && bottom >= a) || (top >= a && top <= b)) return true;
        }
    }
    return false;
}


static void
index_selection(const Screen *self, Selections *selections, bool up, index_type top, index_type bottom) {
    const bool needs_special_handling = self->linebuf == self->alt_linebuf && (top > 0 || bottom < self->lines - 1);
    for (size_t i = 0; i < selections->count; i++) {
        Selection *s = selections->items + i;
        if (needs_special_handling) {
            if (is_selection_empty(s)) continue;
            int start = (int)s->start.y - s->start_scrolled_by;
            int end = (int)s->end.y - s->end_scrolled_by;
            int stop = MIN(start, end);
            int sbottom = MAX(start, end);
            if (stop < (int)top) {
                if (sbottom < (int)top) continue;
                clear_selection(selections); return;
            } else {
                if (stop > (int)bottom) continue;
                if (sbottom > (int)bottom) { clear_selection(selections); return; }
            }
        }
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
    index_selection(self, &self->selections, false, top, bottom); \
    clear_selection(&self->url_ranges);


static void
nuke_in_line(CPUCell *cp, GPUCell *gp, index_type start, index_type x_limit, char_type ch) {
    for (index_type x = start; x < x_limit; x++) {
        cell_set_char(cp + x, ch); cp[x].is_multicell = false;
        clear_sprite_position(gp[x]);
    }
}

static void
nuke_multicell_char_at(Screen *self, index_type x_, index_type y_, bool replace_with_spaces) {
    CPUCell *cp; GPUCell *gp;
    linebuf_init_cells(self->linebuf, y_, &cp, &gp);
    index_type num_lines_above = cp[x_].y;
    index_type y_max_limit = MIN(self->lines, y_ + cp[x_].scale - num_lines_above);
    while (cp[x_].x && x_ > 0) x_--;
    index_type x_limit = MIN(self->columns, x_ + mcd_x_limit(&cp[x_]));
    char_type ch = replace_with_spaces ? ' ' : 0;
    for (index_type y = y_; y < y_max_limit; y++) {
        linebuf_init_cells(self->linebuf, y, &cp, &gp);
        nuke_in_line(cp, gp, x_, x_limit, ch); linebuf_mark_line_dirty(self->linebuf, y);
    }
    int y_min_limit = -1;
    if (self->linebuf == self->main_linebuf) y_min_limit = -(self->historybuf->count + 1);
    for (int y = (int)y_ - 1; y > y_min_limit && num_lines_above; y--, num_lines_above--) {
        Line *line = range_line_(self, y); cp = line->cpu_cells; gp = line->gpu_cells;
        nuke_in_line(cp, gp, x_, x_limit, ch);
        if (y > -1) linebuf_mark_line_dirty(self->linebuf, y);
        else historybuf_mark_line_dirty(self->historybuf, -(y + 1));
    }
    self->is_dirty = true;
}

static void
nuke_multiline_char_intersecting_with(Screen *self, index_type x_start, index_type x_limit, index_type y_start, index_type y_limit, bool replace_with_spaces) {
    for (index_type y = y_start; y < y_limit; y++) {
        CPUCell *cp; GPUCell *gp;
        linebuf_init_cells(self->linebuf, y, &cp, &gp);
        for (index_type x = x_start; x < x_limit; x++) {
            if (cp[x].is_multicell && cp[x].scale > 1) nuke_multicell_char_at(self, x, y, replace_with_spaces);
        }
    }
}

static void
nuke_multicell_char_intersecting_with(Screen *self, index_type x_start, index_type x_limit, index_type y_start, index_type y_limit, bool replace_with_spaces) {
    for (index_type y = y_start; y < y_limit; y++) {
        CPUCell *cp; GPUCell *gp;
        linebuf_init_cells(self->linebuf, y, &cp, &gp);
        for (index_type x = x_start; x < x_limit; x++) {
            if (cp[x].is_multicell) nuke_multicell_char_at(self, x, y, replace_with_spaces);
        }
    }
}


static void
nuke_split_multicell_char_at_left_boundary(Screen *self, index_type x, index_type y, bool replace_with_spaces) {
    CPUCell *cp = linebuf_cpu_cells_for_line(self->linebuf, y);
    if (cp[x].is_multicell && cp[x].x) {
        nuke_multicell_char_at(self, x, y, replace_with_spaces);  // remove split multicell char at left edge
    }
}

static void
nuke_split_multicell_char_at_right_boundary(Screen *self, index_type x, index_type y, bool replace_with_spaces) {
    CPUCell *cp = linebuf_cpu_cells_for_line(self->linebuf, y);
    CPUCell *c = cp + x;
    if (c->is_multicell) {
        unsigned max_x = mcd_x_limit(c) - 1;
        if (c->x < max_x) {
            nuke_multicell_char_at(self, x, y, replace_with_spaces);
        }
    }
}

static void
nuke_incomplete_single_line_multicell_chars_in_range(
    Screen *self, index_type start, index_type limit, index_type y, bool replace_with_spaces
) {
    CPUCell *cpu_cells; GPUCell *gpu_cells;
    linebuf_init_cells(self->linebuf, y, &cpu_cells, &gpu_cells);
    for (index_type x = start; x < limit; x++) {
        if (cpu_cells[x].is_multicell) {
            index_type mcd_x_limit = x + cpu_cells[x].width - cpu_cells[x].x;
            if (cpu_cells[x].x || mcd_x_limit > limit) nuke_in_line(cpu_cells, gpu_cells, x, MIN(mcd_x_limit, limit), replace_with_spaces ? ' ': 0);
            x = mcd_x_limit - 1;
        }
    }
}


static index_type
prevent_current_prompt_from_rewrapping(Screen *self, LineBuf *prompt_copy, index_type *num_of_prompt_lines_above_cursor) {
    index_type num_of_prompt_lines = 0; *num_of_prompt_lines_above_cursor = 0;
    if (!self->prompt_settings.redraws_prompts_at_all) return num_of_prompt_lines;
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
                return num_of_prompt_lines;
        }
        y--;
    }
found:
    if (y < 0) return num_of_prompt_lines;
    // we have identified a prompt at which the cursor is present, the shell
    // will redraw this prompt. However when doing so it gets confused if the
    // cursor vertical position relative to the first prompt line changes. This
    // can easily be seen for instance in zsh when a right side prompt is used
    // so when resizing, simply blank all lines after the current
    // prompt and trust the shell to redraw them.
    LineBuf *orig = self->linebuf; self->linebuf = self->main_linebuf;
    // technically only need to nuke partial multichar cells but since we dont
    // know what the shell will do in terms of clearing, best to be safe and
    // nuke all
    nuke_multiline_char_intersecting_with(self, 0, self->columns, y, self->main_linebuf->ynum, true);
    self->linebuf = orig;
    for (; y < (int)self->main_linebuf->ynum; y++) {
        linebuf_init_line(self->main_linebuf, y);
        linebuf_copy_line_to(prompt_copy, self->main_linebuf->line, num_of_prompt_lines++);
        linebuf_clear_line(self->main_linebuf, y, false);
        if (y <= (int)self->cursor->y) {
            linebuf_init_line(self->main_linebuf, y);
            // this is needed because screen_resize() checks to see if the cursor is beyond the content,
            // so insert some fake content
            cell_set_char(self->main_linebuf->line->cpu_cells, ' ');
            if (y < (int)self->cursor->y) (*num_of_prompt_lines_above_cursor)++;
        }
    }
    return num_of_prompt_lines;
}

static bool
linebuf_is_line_continued(LineBuf *linebuf, index_type y) {
    return y ? linebuf_line_ends_with_continuation(linebuf, y - 1) : false;
}

static bool
preserve_blank_output_start_line(Cursor *cursor, LineBuf *linebuf) {
    if (cursor->x == 0 && cursor->y < linebuf->ynum && !linebuf_is_line_continued(linebuf, cursor->y)) {
        linebuf_init_line(linebuf, cursor->y);
        if (!cell_has_text(linebuf->line->cpu_cells)) {
            // we have a blank output start line, we need it to be preserved by
            // reflow, so insert a dummy char
            cell_set_char(linebuf->line->cpu_cells + cursor->x++, '<');
            return true;
        }
    }
    return false;
}

static void
remove_blank_output_line_reservation_marker(Cursor *cursor, LineBuf *linebuf) {
    if (cursor->y < linebuf->ynum) {
        linebuf_init_line(linebuf, cursor->y);
        cell_set_char(linebuf->line->cpu_cells, 0);
        cursor->x = 0;
    }
}

static bool
screen_resize(Screen *self, unsigned int lines, unsigned int columns) {
    screen_pause_rendering(self, false, 0);
    lines = MAX(1u, lines); columns = MAX(1u, columns);

    bool is_main = self->linebuf == self->main_linebuf;
    index_type num_content_lines_before, num_content_lines_after;
    bool main_has_blank_line = false, alt_has_blank_line = false;
    if (is_main) {
        main_has_blank_line = preserve_blank_output_start_line(self->cursor, self->linebuf);
        if (self->alt_savepoint.is_valid) alt_has_blank_line = preserve_blank_output_start_line(&self->alt_savepoint.cursor, self->alt_linebuf);
    } else {
        if (self->main_savepoint.is_valid) main_has_blank_line = preserve_blank_output_start_line(&self->main_savepoint.cursor, self->main_linebuf);
        alt_has_blank_line = preserve_blank_output_start_line(self->cursor, self->linebuf);
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
    RAII_PyObject(prompt_copy, NULL);
    index_type num_of_prompt_lines = 0, num_of_prompt_lines_above_cursor = 0;
    if (is_main) {
        prompt_copy = (PyObject*)alloc_linebuf(self->lines, self->columns, self->text_cache);
        num_of_prompt_lines = prevent_current_prompt_from_rewrapping(self, (LineBuf*)prompt_copy, &num_of_prompt_lines_above_cursor);
    }
    if (!rewrap(self, lines, columns, &num_content_lines_before, &num_content_lines_after, &cursor, &main_saved_cursor, &alt_saved_cursor, is_main)) return false;
    setup_cursor(cursor);
    /* printf("old_cursor: (%u, %u) new_cursor: (%u, %u) beyond_content: %d\n", self->cursor->x, self->cursor->y, cursor.after.x, cursor.after.y, cursor.is_beyond_content); */
    setup_cursor(main_saved_cursor);
    grman_remove_all_cell_images(self->main_grman);
    grman_resize(self->main_grman, self->lines, lines, self->columns, columns, num_content_lines_before, num_content_lines_after);
    setup_cursor(alt_saved_cursor);
    grman_remove_all_cell_images(self->alt_grman);
    grman_resize(self->alt_grman, self->lines, lines, self->columns, columns, num_content_lines_before, num_content_lines_after);
#undef setup_cursor
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
    clear_all_selections(self);
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
    if (main_has_blank_line) remove_blank_output_line_reservation_marker(is_main ? self->cursor : &self->main_savepoint.cursor, self->main_linebuf);
    if (alt_has_blank_line) remove_blank_output_line_reservation_marker(is_main ? &self->alt_savepoint.cursor : self->cursor, self->alt_linebuf);
    if (num_of_prompt_lines) {
        // Copy the old prompt lines without any reflow this prevents
        // flickering of prompt during resize. The flicker is caused by the
        // prompt being first cleared by kitty then sometime later redrawn by
        // the shell.
        LineBuf *src = (LineBuf*)prompt_copy;
        for (index_type
                src_line = 0,
                y = num_of_prompt_lines_above_cursor <= self->cursor->y ? self->cursor->y - num_of_prompt_lines_above_cursor : 0;

                src_line < num_of_prompt_lines && y < self->lines;

                y++, src_line++
        ) {
            linebuf_init_line(src, src_line);
            linebuf_copy_line_to(self->main_linebuf, src->line, y);
        }
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
    self->text_cache = tc_decref(self->text_cache);
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
    Py_CLEAR(self->paused_rendering.grman);
    free(self->selections.items);
    free(self->url_ranges.items);
    free(self->paused_rendering.url_ranges.items);
    free(self->paused_rendering.selections.items);
    free_hyperlink_pool(self->hyperlink_pool);
    free(self->as_ansi_buf.buf);
    free(self->last_rendered_window_char.canvas);
    if (self->lc) { cleanup_list_of_chars(self->lc); free(self->lc); self->lc = NULL; }
    Py_TYPE(self)->tp_free((PyObject*)self);
} // }}}

// Draw text {{{
typedef struct text_loop_state {
    bool image_placeholder_marked;
    const CPUCell cc; const GPUCell g;
    CPUCell *cp; GPUCell *gp;
    GraphemeSegmentationResult seg;
    struct {
        index_type x, y; CPUCell *cc;
    } prev;
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
clear_intersecting_selections(Screen *self, index_type y) {
    if (selection_has_screen_line(&self->selections, y)) clear_selection(&self->selections);
    if (selection_has_screen_line(&self->url_ranges, y)) clear_selection(&self->url_ranges);
}

static void
init_prev_cell(Screen *self, text_loop_state *s) {
    zero_at_ptr(&s->prev);
    if (self->cursor->x) {
        s->prev.y = self->cursor->y;
        s->prev.x = self->cursor->x - 1;
        s->prev.cc = linebuf_cpu_cell_at(self->linebuf, s->prev.x, s->prev.y);
    } else if (self->cursor->y) {
        s->prev.y = self->cursor->y - 1;
        s->prev.x = self->columns - 1;
        s->prev.cc = linebuf_cpu_cell_at(self->linebuf, s->prev.x, s->prev.y);
        if (!s->prev.cc->next_char_was_wrapped) s->prev.cc = NULL;
    }
}
static void
init_segmentation_state(Screen *self, text_loop_state *s) {
    init_prev_cell(self, s);
    grapheme_segmentation_reset(&s->seg);
    if (s->prev.cc) {
        text_in_cell(s->prev.cc, self->text_cache, self->lc);
        for (index_type i = 0; i < self->lc->count; i++) s->seg = grapheme_segmentation_step(s->seg, char_props_for(self->lc->chars[i]));
    }
}

static void
init_text_loop_line(Screen *self, text_loop_state *s) {
    linebuf_init_cells(self->linebuf, self->cursor->y, &s->cp, &s->gp);
    clear_intersecting_selections(self, self->cursor->y);
    linebuf_mark_line_dirty(self->linebuf, self->cursor->y);
    s->image_placeholder_marked = false;
    init_segmentation_state(self, s);
}

static void
zero_cells(text_loop_state *s, CPUCell *c, GPUCell *g) { *c = s->cc; *g = s->g; }

typedef Line*(linefunc_t)(Screen*, int);

static void
init_line_(Screen *self, index_type y, Line *line) {
    linebuf_init_line_at(self->linebuf, y, line);
}


static Line*
init_line(Screen *self, index_type y) {
    init_line_(self, y, self->linebuf->line);
    return self->linebuf->line;
}

static void
visual_line(Screen *self, int y_, Line *line) {
    index_type y = MAX(0, y_);
    if (self->scrolled_by) {
        if (y < self->scrolled_by) {
            historybuf_init_line(self->historybuf, self->scrolled_by - 1 - y, line);
            return;
        }
        y -= self->scrolled_by;
    }
    init_line_(self, y, line);
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

static bool
visual_line_is_continued(Screen *self, int y_) {
    index_type y = MAX(0, y_);
    if (self->scrolled_by) {
        if (y < self->scrolled_by) return historybuf_is_line_continued(self->historybuf, self->scrolled_by - 1 - y);
        y -= self->scrolled_by;
    }
    if (y) return linebuf_is_line_continued(self->linebuf, y);
    return self->linebuf == self->main_linebuf ? history_buf_endswith_wrap(self->historybuf) : false;
}

static Line*
range_line_(Screen *self, int y) {
    if (y < 0) {
        historybuf_init_line(self->historybuf, -(y + 1), self->historybuf->line);
        return self->historybuf->line;
    }
    return init_line(self, y);
}

static void
range_line(Screen *self, int y, Line *line) {
    if (y < 0) historybuf_init_line(self->historybuf, -(y + 1), line);
    else init_line_(self, y, line);
}

static Line*
checked_range_line(Screen *self, int y) {
    if (-(int)self->historybuf->count <= y && y < (int)self->lines) return range_line_(self, y);
    return NULL;
}

static bool
range_line_is_continued(Screen *self, int y) {
    if (!(-(int)self->historybuf->count <= y && y < (int)self->lines)) return false;
    if (y < 0) return historybuf_is_line_continued(self->historybuf, -(y + 1));
    if (y) return linebuf_is_line_continued(self->linebuf, y);
    return self->linebuf == self->main_linebuf ? history_buf_endswith_wrap(self->historybuf) : false;
}

static void
insert_characters(Screen *self, index_type at, index_type num, index_type y, bool replace_with_spaces) {
    // insert num chars at x=at setting them to the value of the num chars at [at, at + num)
    // multiline chars at x >= at are deleted and multicell chars split at x=at
    // and x=at + num - 1 are deleted
    nuke_multiline_char_intersecting_with(self, at, self->columns, y, y + 1, replace_with_spaces);
    nuke_split_multicell_char_at_left_boundary(self, at, y, replace_with_spaces);
    CPUCell *cp; GPUCell *gp;
    linebuf_init_cells(self->linebuf, y, &cp, &gp);
    // right shift
    for(index_type i = self->columns - 1; i >= at + num; i--) {
        cp[i] = cp[i - num]; gp[i] = gp[i - num];
    }
    nuke_incomplete_single_line_multicell_chars_in_range(self, at, at + num, y, replace_with_spaces);
    nuke_split_multicell_char_at_right_boundary(self, self->columns - 1, y, replace_with_spaces);
}

static bool
halve_multicell_width(Screen *self, index_type x_, index_type y_) {
    CPUCell *cp; GPUCell *gp;
    linebuf_init_cells(self->linebuf, y_, &cp, &gp);
    int y_min_limit = -1;
    if (self->linebuf == self->main_linebuf) y_min_limit = -(self->historybuf->count + 1);
    int expected_y_min_limit = ((int)y_) - cp[x_].scale;
    if (expected_y_min_limit < y_min_limit) return false;
    y_min_limit = expected_y_min_limit;
    unsigned new_width = cp[x_].width / 2;
    while (cp[x_].x && x_ > 0) x_--;
    const index_type ws = mcd_x_limit(&cp[x_]);
    const index_type x_limit = MIN(self->columns, x_ + ws);
    const index_type half_x_limit = MIN(self->columns, x_ + ws / 2);
    int y_max_limit = MIN(self->lines, y_ + cp[x_].scale);
    for (int y = y_min_limit + 1; y < y_max_limit; y++) {
        Line *line = range_line_(self, y); cp = line->cpu_cells; gp = line->gpu_cells;
        for (index_type x = x_; x < half_x_limit; x++) cp[x].width = new_width;
        for (index_type x = half_x_limit; x < x_limit; x++) {
            cp[x] = (CPUCell){0}; clear_sprite_position(gp[x]);
        }
        if (y > -1) linebuf_mark_line_dirty(self->linebuf, y);
    }
    self->is_dirty = true;
    return true;
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

static bool
add_combining_char(Screen *self, char_type ch, index_type x, index_type y) {
    CPUCell *cpu_cells = linebuf_cpu_cells_for_line(self->linebuf, y);
    CPUCell *cell = cpu_cells + x;
    if (!cell_has_text(cell) || (cell->is_multicell && cell->y)) return false; // don't allow adding combining chars to a null cell
    text_in_cell(cell, self->text_cache, self->lc);
    if (self->lc->count >= MAX_NUM_CODEPOINTS_PER_CELL) return false; // don't allow too many combining chars to prevent DoS attacks
    ensure_space_for_chars(self->lc, self->lc->count + 1);
    self->lc->chars[self->lc->count++] = ch;
    cell->ch_or_idx = tc_get_or_insert_chars(self->text_cache, self->lc);
    cell->ch_is_idx = true;
    if (cell->is_multicell) {
        char_type ch_and_idx = cell->ch_and_idx;
        while (cell->x && x) cell = cpu_cells + --x;
        index_type x_limit = MIN(x + mcd_x_limit(cell), self->columns);
        for (index_type v = y; v < y + cell->scale; v++) {
            cpu_cells = linebuf_cpu_cells_for_line(self->linebuf, v);
            for (index_type h = x; h < x_limit; h++) cpu_cells[h].ch_and_idx = ch_and_idx;
            linebuf_mark_line_dirty(self->linebuf, v);
        }
    }
    return true;
}


static bool
has_multiline_cells_in_span(const CPUCell *cells, const index_type start, const index_type count) {
    for (index_type x = start; x < start + count; x++) if (cells[x].y) return true;
    return false;
}

static bool
move_cursor_past_multicell(Screen *self, index_type required_width) {
    if (required_width > self->columns) return false;
    index_type orig_x = self->cursor->x, orig_y = self->cursor->y;
    while(true) {
        CPUCell *cp = linebuf_cpu_cells_for_line(self->linebuf, self->cursor->y);
        while (self->cursor->x + required_width <= self->columns) {
            if (!has_multiline_cells_in_span(cp, self->cursor->x, required_width)) {
                if (cp[self->cursor->x].is_multicell) nuke_multicell_char_at(self, self->cursor->x, self->cursor->y, cp[self->cursor->x].x != 0);
                return true;
            }
            self->cursor->x++;
        }
        if (self->modes.mDECAWM || has_multiline_cells_in_span(cp, self->columns - required_width, required_width)) {
            continue_to_next_line(self);
        } else {
            self->cursor->x = self->columns - required_width;
            if (cp[self->cursor->x].is_multicell) nuke_multicell_char_at(self, self->cursor->x, self->cursor->y, cp[self->cursor->x].x != 0);
            return true;
        }
    }
    self->cursor->x = orig_x; self->cursor->y = orig_y;
    return false;
}

static void
move_widened_char_past_multiline_chars(Screen *self, CPUCell* cpu_cell, GPUCell *gpu_cell, index_type xpos, index_type ypos) {
    self->cursor->x = xpos; self->cursor->y = ypos;
    if (move_cursor_past_multicell(self, 2)) {
        CPUCell *cp; GPUCell *gp;
        clear_sprite_position(*gpu_cell);
        linebuf_init_cells(self->linebuf, self->cursor->y, &cp, &gp);
        cp[self->cursor->x] = *cpu_cell; gp[self->cursor->x] = *gpu_cell;
        self->cursor->x++;
        cp[self->cursor->x] = *cpu_cell; gp[self->cursor->x] = *gpu_cell;
        cp[self->cursor->x].x = 1;
        self->cursor->x++;
    }
    *cpu_cell = (CPUCell){0}; *gpu_cell = (GPUCell){0};
}

static bool
is_emoji_presentation_base(char_type ch) {
    return char_props_for(ch).is_emoji_presentation_base == 1;
}

static void
draw_combining_char(Screen *self, text_loop_state *s, char_type ch) {
    CPUCell *cp; GPUCell *gp;
    linebuf_init_cells(self->linebuf, s->prev.y, &cp, &gp);
    index_type xpos = s->prev.x;
    while (xpos && cp[xpos].is_multicell && cp[xpos].x) xpos--;
    if (!add_combining_char(self, ch, xpos, s->prev.y) || self->lc->count < 2) return;
    unsigned base_pos = self->lc->count -  2;
    if (ch == VS16) {  // emoji presentation variation marker makes default text presentation emoji (narrow emoji) into wide emoji
        CPUCell *cpu_cell = cp + xpos;
        GPUCell *gpu_cell = gp + xpos;
        if (self->lc->chars[base_pos + 1] == VS16 && !cpu_cell->is_multicell && is_emoji_presentation_base(self->lc->chars[base_pos])) {
            cpu_cell->is_multicell = true;
            cpu_cell->width = 2;
            cpu_cell->natural_width = true;
            if (!cpu_cell->scale) cpu_cell->scale = 1;
            if (xpos + 1 < self->columns) {
                CPUCell *second = cp + xpos + 1;
                if (second->is_multicell) {
                    if (second->y) {
                        move_widened_char_past_multiline_chars(self, cpu_cell, gpu_cell, xpos, s->prev.y);
                        init_segmentation_state(self, s);
                        return;
                    }
                    nuke_multicell_char_at(self, xpos + 1, s->prev.y, false);
                }
                zero_cells(s, second, gp + xpos + 1);
                self->cursor->x++;
                *second = *cpu_cell; second->x = 1;
            } else {
                move_widened_char_past_multiline_chars(self, cpu_cell, gpu_cell, xpos, s->prev.y);
                init_segmentation_state(self, s);
            }
        }
    } else if (ch == VS15) {
        const CPUCell *cpu_cell = cp + xpos;
        if (self->lc->chars[base_pos + 1] == VS15 && cpu_cell->is_multicell && cpu_cell->width == 2 && is_emoji_presentation_base(self->lc->chars[base_pos])) {
            index_type deltax = (cpu_cell->scale * cpu_cell->width) / 2;
            if (halve_multicell_width(self, xpos, s->prev.y)) {
                self->cursor->x -= deltax;
                init_segmentation_state(self, s);
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
replace_multicell_char_under_cursor_with_spaces(Screen *self) {
    nuke_multicell_char_at(self, self->cursor->x, self->cursor->y, true);
}

static void
screen_change_charset(Screen *self, uint32_t which) {
    switch(which) {
        case 0:
            self->charset.current_num = 0;
            self->charset.current = self->charset.zero;
            break;
        case 1:
            self->charset.current_num = 1;
            self->charset.current = self->charset.one;
            break;
    }
}

void
screen_designate_charset(Screen *self, uint32_t which, uint32_t as) {
    switch(which) {
        case 0:
            self->charset.zero = translation_table(as);
            if (self->charset.current_num == 0) self->charset.current = self->charset.zero;
            break;
        case 1:
            self->charset.one = translation_table(as);
            if (self->charset.current_num == 1) self->charset.current = self->charset.one;
            break;
    }
}


static uint32_t
map_char(Screen *self, const uint32_t ch) {
    return UNLIKELY(self->charset.current && ch < 256) ? self->charset.current[ch] : ch;
}

static void
draw_control_char(Screen *self, text_loop_state *s, uint32_t ch) {
    switch (ch) {
        case BEL:
            screen_bell(self); break;
        case BS: {
            index_type before = self->cursor->y;
            screen_backspace(self);
            if (before == self->cursor->y) init_segmentation_state(self, s);
            else init_text_loop_line(self, s);
            } break;
        case HT:
            if (UNLIKELY(self->cursor->x >= self->columns)) {
                if (self->modes.mDECAWM) {
                    // xterm discards the TAB in this case so match its behavior
                    continue_to_next_line(self);
                    init_text_loop_line(self, s);
                } else if (self->columns > 0){
                    self->cursor->x = self->columns - 1;
                    if (s->cp[self->cursor->x].is_multicell) {
                        if (s->cp[self->cursor->x].y) move_cursor_past_multicell(self, 1);
                        else replace_multicell_char_under_cursor_with_spaces(self);
                    }
                    screen_tab(self);
                }
            } else screen_tab(self);
            init_segmentation_state(self, s);
            break;
        case SI:
            screen_change_charset(self, 0); break;
        case SO:
            screen_change_charset(self, 1); break;
        case LF:
        case VT:
        case FF:
            screen_linefeed(self); init_text_loop_line(self, s); break;
        case CR:
            screen_carriage_return(self); init_segmentation_state(self, s); break;
        default:
            break;
    }
}

static void
draw_text_loop(Screen *self, const uint32_t *chars, size_t num_chars, text_loop_state *s) {
    init_text_loop_line(self, s);
    int char_width;
    for (size_t i = 0; i < num_chars; i++) {
        uint32_t ch = map_char(self, chars[i]);
        if (ch < DEL && s->seg.grapheme_break == GBP_None) {  // fast path for printable ASCII
            if (ch < ' ') {
                draw_control_char(self, s, ch);
                continue;
            }
            char_width = 1;
            s->seg = (GraphemeSegmentationResult){.grapheme_break=GBP_None};
        } else {
            CharProps cp = char_props_for(ch);
            if (cp.is_invalid) {
                if (ch < ' ') draw_control_char(self, s, ch);
                continue;
            }
            s->seg = grapheme_segmentation_step(s->seg, cp);
            if (UNLIKELY(s->seg.add_to_current_cell && s->prev.cc)) {
                draw_combining_char(self, s, ch);
                continue;
            }
            char_width = wcwidth_std(cp);
            if (UNLIKELY(char_width < 1)) {
                if (char_width == 0) {
                    // Preserve zero width chars as combining chars even though
                    // they were not added to the prev cell by grapheme segmentation.
                    // Zero width chars can only be represented as combining chars.
                    if (s->prev.cc) draw_combining_char(self, s, ch);
                    continue;
                }
                char_width = 1;
            }
        }

        if (self->cursor->x < self->columns && s->cp[self->cursor->x].is_multicell) {
            if (s->cp[self->cursor->x].y) {
                move_cursor_past_multicell(self, 1);
                init_text_loop_line(self, s);
            } else nuke_multicell_char_at(self, self->cursor->x, self->cursor->y, s->cp[self->cursor->x].x != 0);
        }

        self->last_graphic_char = ch;
        if (UNLIKELY(self->columns < self->cursor->x + (unsigned int)char_width)) {
            if (self->modes.mDECAWM) {
                continue_to_next_line(self);
                init_text_loop_line(self, s);
            } else self->cursor->x = self->columns - char_width;
            CPUCell *c = &s->cp[self->cursor->x];
            if (c->is_multicell) {
                if (c->y) { move_cursor_past_multicell(self, char_width); init_text_loop_line(self, s); }
                nuke_multicell_char_at(self, self->cursor->x, self->cursor->y, c->x > 0);
            }
        }
        if (self->modes.mIRM) insert_characters(self, self->cursor->x, char_width, self->cursor->y, true);
        if (UNLIKELY(!s->image_placeholder_marked && ch == IMAGE_PLACEHOLDER_CHAR)) {
            linebuf_set_line_has_image_placeholders(self->linebuf, self->cursor->y, true);
            s->image_placeholder_marked = true;
        }
        CPUCell *fc = s->cp + self->cursor->x;
        if (char_width == 2) {
            CPUCell *second = fc + 1;
            if (second->is_multicell) {
                if (second->y) {
                    self->cursor->x++;
                    move_cursor_past_multicell(self, 2);
                    fc = s->cp + self->cursor->x; second = fc + 1;
                } else nuke_multicell_char_at(self, self->cursor->x + 1, self->cursor->y, true);
            }
            zero_cells(s, fc, s->gp + self->cursor->x);
            *fc = (CPUCell){.ch_or_idx=ch, .is_multicell=true, .width=2, .scale=1, .natural_width=true, .hyperlink_id=s->cc.hyperlink_id};
            *second = *fc; second->x = 1;
            s->gp[self->cursor->x + 1] = s->gp[self->cursor->x];
            s->prev.y = self->cursor->y; s->prev.x = self->cursor->x; s->prev.cc = fc;
            self->cursor->x += 2;
        } else {
            zero_cells(s, fc, s->gp + self->cursor->x);
            cell_set_char(fc, ch);
            s->prev.y = self->cursor->y; s->prev.x = self->cursor->x; s->prev.cc = fc;
            self->cursor->x++;
            fc->is_multicell = false;
        }
    }
#undef init_line
}

#define PREPARE_FOR_DRAW_TEXT \
    const bool force_underline = OPT(underline_hyperlinks) == UNDERLINE_ALWAYS && self->active_hyperlink_id != 0; \
    CellAttrs attrs = cursor_to_attrs(self->cursor); \
    if (force_underline) attrs.decoration = OPT(url_style); \
    text_loop_state s={ \
        .cc=(CPUCell){.hyperlink_id=self->active_hyperlink_id}, \
        .g=(GPUCell){ \
            .attrs=attrs, \
            .fg=self->cursor->fg & COL_MASK, .bg=self->cursor->bg & COL_MASK, \
            .decoration_fg=force_underline ? ((OPT(url_color) & COL_MASK) << 8) | 2 : self->cursor->decoration_fg & COL_MASK, \
        } \
    };

static void
draw_text(Screen *self, const uint32_t *chars, size_t num_chars) {
    PREPARE_FOR_DRAW_TEXT;
    self->is_dirty = true;
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

static size_t
decode_utf8_safe_string(const uint8_t *src, size_t sz, uint32_t *dest) {
    // dest must be an array of size at least sz
    uint32_t codep = 0;
    UTF8State state = 0, prev = UTF8_ACCEPT;
    size_t i = 0, d = 0;
    for (; i < sz; i++) {
        switch(decode_utf8(&state, &codep, src[i])) {
            case UTF8_ACCEPT:
                // Ignore C0 and C1 chars
                if (codep >= ' ' && !(DEL <= codep && codep <= 159)) dest[d++] = codep;
                break;
            case UTF8_REJECT:
                state = UTF8_ACCEPT;
                if (prev != UTF8_ACCEPT && i > 0) i--;
                break;
        }
        prev = state;
    }
    return d;
}

static void
handle_fixed_width_multicell_command(Screen *self, CPUCell mcd, ListOfChars *lc) {
    index_type width = mcd.width * mcd.scale;
    index_type height = mcd.scale;
    index_type max_height = self->margin_bottom - self->margin_top + 1;
    if (width > self->columns || height > max_height) return;
    lc->count = MIN(lc->count, MAX_NUM_CODEPOINTS_PER_CELL);
    PREPARE_FOR_DRAW_TEXT;
    mcd.hyperlink_id = s.cc.hyperlink_id;
    cell_set_chars(&mcd, self->text_cache, lc);
    move_cursor_past_multicell(self, width);
    if (height > 1) {
        index_type available_height = self->margin_bottom - self->cursor->y + 1;
        if (height > available_height) {
            index_type extra_lines = height - available_height;
            screen_scroll(self, extra_lines);
            self->cursor->y -= extra_lines;
        }
    }
    if (self->modes.mIRM) {
        for (index_type y = self->cursor->y; y < self->cursor->y + height; y++) {
            if (self->modes.mIRM) insert_characters(self, self->cursor->x, width, y, true);
        }
    }
    for (index_type y = self->cursor->y; y < self->cursor->y + height; y++) {
        linebuf_init_cells(self->linebuf, y, &s.cp, &s.gp);
        linebuf_mark_line_dirty(self->linebuf, y);
        mcd.x = 0; mcd.y = y - self->cursor->y;
        for (index_type x = self->cursor->x; x < self->cursor->x + width; x++, mcd.x++) {
            if (s.cp[x].is_multicell) nuke_multicell_char_at(self, x, y, s.cp[x].x + s.cp[x].y > 0);
            s.cp[x] = mcd; s.gp[x] = s.g;
        }
    }
    self->cursor->x += width;
    self->is_dirty = true;
}

static void
handle_variable_width_multicell_command(Screen *self, CPUCell mcd, ListOfChars *lc) {
    ensure_space_for_chars(lc, lc->count + 1); lc->chars[lc->count] = 0;
    mcd.width = wcswidth_string(lc->chars);
    if (!mcd.width) { lc->count = 0; return; }
    handle_fixed_width_multicell_command(self, mcd, lc);
}

void
screen_handle_multicell_command(Screen *self, const MultiCellCommand *cmd, const uint8_t *payload) {
    screen_on_input(self);
    if (!cmd->payload_sz) return;
    ensure_space_for_chars(self->lc, cmd->payload_sz + 1);
    self->lc->count = decode_utf8_safe_string(payload, cmd->payload_sz, self->lc->chars);
    if (!self->lc->count) return;
#define M(x) ( (1u << x) - 1u)
    CPUCell mcd = {
        .width=MIN(cmd->width, M(WIDTH_BITS)), .scale=MAX(1u, MIN(cmd->scale, M(SCALE_BITS))),
        .subscale_n=MIN(cmd->subscale_n, M(SUBSCALE_BITS)), .subscale_d=MIN(cmd->subscale_d, M(SUBSCALE_BITS)),
        .valign=MIN(cmd->vertical_align, M(VALIGN_BITS)), .halign=MIN(cmd->horizontal_align, M(HALIGN_BITS)),
        .is_multicell=true
    };
#undef M
    if (mcd.width) handle_fixed_width_multicell_command(self, mcd, self->lc);
    else {
        RAII_ListOfChars(lc);
        GraphemeSegmentationResult s; grapheme_segmentation_reset(&s);
        mcd.natural_width = true;
        for (unsigned i = 0; i < self->lc->count; i++) {
            char_type ch = self->lc->chars[i];
            CharProps cp = char_props_for(ch);
            if (cp.is_invalid) continue;
            if ((s = grapheme_segmentation_step(s, cp)).add_to_current_cell || (wcwidth_std(cp) == 0 && lc.count)) lc.chars[lc.count++] = ch;
            else {
                if (lc.count) handle_variable_width_multicell_command(self, mcd, &lc);
                switch(wcwidth_std(cp)) {
                    case 0: case -1: lc.count = 0; break;
                    default: lc.chars[0] = ch; lc.count = 1; break;
                }
            }
        }
        if (lc.count) handle_variable_width_multicell_command(self, mcd, &lc);
    }
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
    grman_mark_layers_dirty(self->grman);
    clear_all_selections(self);
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
        SIMPLE_MODE(COLOR_PREFERENCE_NOTIFICATION)
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
        case INBAND_RESIZE_NOTIFICATION:
            self->modes.mINBAND_RESIZE_NOTIFICATION = val;
            if (val) CALLBACK("notify_child_of_resize", NULL);
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

void
screen_modify_other_keys(Screen *self, unsigned int val) {
    // Only report an error about modifyOtherKeys if the kitty keyboard
    // protocol is not in effect and the application is trying to turn it on. There are some applications that try to enable both.
    debug_input("modifyOtherKeys: %u\n", val);
    if (!screen_current_key_encoding_flags(self) && val) {
        log_error("The application is trying to use xterm's modifyOtherKeys. This is superseded by the kitty keyboard protocol https://sw.kovidgoyal.net/kitty/keyboard-protocol. The application should be updated to use that.");
    }
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
    debug_input("\x1b[35mReporting key encoding flags: %u\x1b[39m\n", screen_current_key_encoding_flags(self));
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
    debug_input("\x1b[35mSet key encoding flags to: %u\x1b[39m\n", screen_current_key_encoding_flags(self));
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
    debug_input("\x1b[35mPushed key encoding flags to: %u\x1b[39m\n", screen_current_key_encoding_flags(self));
}

void
screen_pop_key_encoding_flags(Screen *self, uint32_t num) {
    for (unsigned i = arraysz(self->main_key_encoding_flags); num && i-- > 0; ) {
        if (self->key_encoding_flags[i] & 0x80) { num--; self->key_encoding_flags[i] = 0; }
    }
    debug_input("\x1b[35mPopped key encoding flags to: %u\x1b[39m\n", screen_current_key_encoding_flags(self));
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

bool
screen_is_cursor_visible(const Screen *self) {
    return self->paused_rendering.expires_at ? self->paused_rendering.cursor_visible : self->modes.mDECTCEM;
}

void
screen_backspace(Screen *self) {
    screen_cursor_move(self, 1, -1);
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
            CPUCell *cpu_cell = linebuf_cpu_cells_for_line(self->linebuf, self->cursor->y) + self->cursor->x;
            combining_type diff = found - self->cursor->x;
            bool ok = true;
            for (combining_type i = 0; i < diff; i++) {
                CPUCell *c = cpu_cell + i;
                if (cell_has_text(c) && !cell_is_char(c, ' ')) { ok = false; break; }
            }
            if (ok) {
                for (combining_type i = 0; i < diff; i++) {
                    CPUCell *c = cpu_cell + i;
                    cell_set_char(c, ' ');
                }
                self->lc->count = 2; self->lc->chars[0] = '\t'; self->lc->chars[1] = diff;
                cell_set_chars(cpu_cell, self->text_cache, self->lc);
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
screen_cursor_move(Screen *self, unsigned int count/*=1*/, int move_direction/*=-1*/) {
    if (count == 0) count = 1;
    bool in_margins = cursor_within_margins(self);
    if (move_direction > 0) {
        self->cursor->x += count;
        screen_ensure_bounds(self, false, in_margins);
    } else {
        index_type top = in_margins && self->modes.mDECOM ? self->margin_top : 0;
        while (count > 0) {
            if (count <= self->cursor->x) {
                self->cursor->x -= count;
                count = 0;
            } else {
                if (self->cursor->x > 0) {
                    count -= self->cursor->x;
                    self->cursor->x = 0;
                } else {
                    if (self->cursor->y == top) count = 0;
                    else {
                        count--; self->cursor->y--;
                        self->cursor->x = self->columns-1;
                    }
                }
            }
        }
    }
}

void
screen_cursor_forward(Screen *self, unsigned int count/*=1*/) {
    screen_cursor_move(self, count, 1);
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

#define INDEX_UP(add_to_history) \
    linebuf_index(self->linebuf, top, bottom); \
    INDEX_GRAPHICS(-1) \
    if (add_to_history) { \
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
    index_selection(self, &self->selections, true, top, bottom); \
    clear_selection(&self->url_ranges);

void
screen_index(Screen *self) {
    // Move cursor down one line, scrolling screen if needed
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (self->cursor->y == bottom) {
        const bool add_to_history = self->linebuf == self->main_linebuf && self->margin_top == 0;
        INDEX_UP(add_to_history);
    } else screen_cursor_down(self, 1);
}

static void
screen_index_without_adding_to_history(Screen *self) {
    // Move cursor down one line, scrolling screen if needed
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (self->cursor->y == bottom) {
        INDEX_UP(false);
    } else screen_cursor_down(self, 1);
}


void
screen_scroll(Screen *self, unsigned int count) {
    // Scroll the screen up by count lines, not moving the cursor
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    const bool add_to_history = self->linebuf == self->main_linebuf && self->margin_top == 0;
    while (count > 0) {
        count--;
        INDEX_UP(add_to_history);
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
    self->cursor->x = 0;
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
    memcpy(&sp->charset, &self->charset, sizeof(self->charset));
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
        SIMPLE_MODE(COLOR_PREFERENCE_NOTIFICATION)
        SIMPLE_MODE(INBAND_RESIZE_NOTIFICATION)
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
    copy_specific_mode(self, COLOR_PREFERENCE_NOTIFICATION, src, dest);
    copy_specific_mode(self, INBAND_RESIZE_NOTIFICATION, src, dest);
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
        zero_at_ptr(&self->charset);
    } else {
        set_mode_from_const(self, DECOM, sp->mDECOM);
        set_mode_from_const(self, DECAWM, sp->mDECAWM);
        set_mode_from_const(self, DECSCNM, sp->mDECSCNM);
        cursor_copy_to(&(sp->cursor), self->cursor);
        memcpy(&self->charset, &sp->charset, sizeof(self->charset));
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
    self->cursor->position_changed_by_client_at = self->parsing_at;
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
screen_prompt_supports_click_events(const Screen *self) {
    return (bool) self->prompt_settings.supports_click_events;
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
            const CPUCell *c = linebuf_cpu_cell_at(self->linebuf, x, y);
            if (!cell_has_text(c)) {
                // we only stop counting the cells in the line at an empty cell
                // if at least one non-empty cell is found. zsh uses empty cells
                // between the end of the text ad the right prompt. fish uses empty
                // cells at the start of a line when editing multiline text
                if (!found_non_empty_cell) { x++; continue; }
                count += 1;
                break;
            }
            found_non_empty_cell = true;
            if (c->is_multicell) {
                x += mcd_x_limit(c);
            } else x++;
            count += 1;  // zsh requires a single arrow press to move past dualwidth chars
        }
        if (!found_non_empty_cell) count++;  // blank line
        x = 0;
    }
    if (count) {
        char output[KEY_BUFFER_SIZE+1] = {0};
        if (self->prompt_settings.uses_special_keys_for_cursor_movement) {
            const char *k = key == GLFW_FKEY_RIGHT ? "1" : "1;1";
            int num = snprintf(output, KEY_BUFFER_SIZE, "\x1b[%su", k);
            for (unsigned i = 0; i < count; i++) write_to_child(self, output, num);
        } else {
            GLFWkeyevent ev = { .key = key, .action = GLFW_PRESS };
            int num = encode_glfw_key_event(&ev, false, 0, output);
            if (num != SEND_TEXT_TO_CHILD) {
                for (unsigned i = 0; i < count; i++) write_to_child(self, output, num);
            }
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
        nuke_multicell_char_intersecting_with(self, s, n, self->cursor->y, self->cursor->y + 1, false);
        screen_dirty_line_graphics(self, self->cursor->y, self->cursor->y, self->linebuf == self->main_linebuf);
        linebuf_init_line(self->linebuf, self->cursor->y);
        if (private) {
            line_clear_text(self->linebuf->line, s, n, BLANK_CHAR);
        } else {
            line_apply_cursor(self->linebuf->line, self->cursor, s, n, true);
        }
        self->is_dirty = true;
        clear_intersecting_selections(self, self->cursor->y);
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
    LineBuf *orig = self->linebuf; self->linebuf = self->main_linebuf;
    CPUCell *cells = linebuf_cpu_cells_for_line(self->linebuf, 0);
    for (index_type x = 0; x < self->columns; x++) {
        CPUCell *c = cells + x;
        if (c->is_multicell && c->y > 0) {  // multiline char that extended into scrollback
            nuke_multicell_char_at(self, x, 0, false);
        }
    }
    self->linebuf = orig;
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
        const bool add_to_history = self->linebuf == self->main_linebuf && self->margin_top == 0;
        for (; num_of_lines_to_move; num_of_lines_to_move--) {
            top = 0, bottom = num_of_lines_to_move - 1;
            INDEX_UP(add_to_history);
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
    bool nuke_multicell_chars = true;
    switch(how) {
        case 0:
            a = self->cursor->y + 1; b = self->lines; break;
        case 1:
            a = 0; b = self->cursor->y; break;
        case 22:
            screen_move_into_scrollback(self);
            nuke_multicell_chars = false;  // they have been moved into scrollback and we would get double deletions
            how = 2;
            /* fallthrough */
        case 2:
        case 3:
            grman_clear(self->grman, how == 3, self->cell_size);
            a = 0; b = self->lines; nuke_multicell_chars = false;
            break;
        default:
            return;
    }
    if (b > a) {
        if (how != 3) screen_dirty_line_graphics(self, a, b, self->linebuf == self->main_linebuf);
        if (private) {
            for (unsigned int i=a; i < b; i++) {
                linebuf_init_line(self->linebuf, i);
                line_clear_text(self->linebuf->line, 0, self->columns, BLANK_CHAR);
                linebuf_set_last_char_as_continuation(self->linebuf, i, false);
                linebuf_clear_attrs_and_dirty(self->linebuf, i);
            }
        } else linebuf_clear_lines(self->linebuf, self->cursor, a, b);
        if (nuke_multicell_chars) nuke_multicell_char_intersecting_with(self, 0, self->columns, a, b, false);
        self->is_dirty = true;
        if (selection_intersects_screen_lines(&self->selections, a, b)) clear_selection(&self->selections);
        if (selection_intersects_screen_lines(&self->url_ranges, a, b)) clear_selection(&self->url_ranges);
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
        // remove split multiline chars at top edge
        CPUCell *cells = linebuf_cpu_cells_for_line(self->linebuf, self->cursor->y);
        for (index_type x = 0; x < self->columns; x++) {
            if (cells[x].is_multicell && cells[x].y) nuke_multicell_char_at(self, x, self->cursor->y, false);
        }
        screen_dirty_line_graphics(self, top, bottom, self->linebuf == self->main_linebuf);
        linebuf_insert_lines(self->linebuf, count, self->cursor->y, bottom);
        self->is_dirty = true;
        clear_all_selections(self);
        screen_carriage_return(self);
        // remove split multiline chars at bottom of screen
        cells = linebuf_cpu_cells_for_line(self->linebuf, bottom);
        for (index_type x = 0; x < self->columns; x++) {
            if (cells[x].is_multicell) {
                index_type y_limit = cells[x].scale;
                if (cells[x].y + 1u < y_limit) {
                    index_type orig = self->lines;
                    self->lines = bottom + 1;
                    nuke_multicell_char_at(self, x, bottom, false);
                    self->lines = orig;
                }
            }
        }
    }
}

static void
screen_scroll_until_cursor_prompt(Screen *self, bool add_to_scrollback) {
    bool in_margins = cursor_within_margins(self);
    int q = screen_cursor_at_a_shell_prompt(self);
    unsigned int y = q > -1 ? (unsigned int)q : self->cursor->y;
    unsigned int num_lines_to_scroll = MIN(self->margin_bottom, y);
    unsigned int final_y = num_lines_to_scroll <= self->cursor->y ? self->cursor->y - num_lines_to_scroll : 0;
    self->cursor->y = self->margin_bottom;
    if (add_to_scrollback) while (num_lines_to_scroll--) screen_index(self);
    else while (num_lines_to_scroll--) screen_index_without_adding_to_history(self);
    self->cursor->y = final_y;
    screen_ensure_bounds(self, false, in_margins);
}

void
screen_delete_lines(Screen *self, unsigned int count) {
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (count == 0) count = 1;
    if (top <= self->cursor->y && self->cursor->y <= bottom) {
        index_type y = self->cursor->y;
        nuke_multiline_char_intersecting_with(self, 0, self->columns, y, y + 1, false);
        y += count;
        y = MIN(bottom, y);
        nuke_multiline_char_intersecting_with(self, 0, self->columns, y, y + 1, false);
        screen_dirty_line_graphics(self, top, bottom, self->linebuf == self->main_linebuf);
        linebuf_delete_lines(self->linebuf, count, self->cursor->y, bottom);
        self->is_dirty = true;
        clear_all_selections(self);
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
        insert_characters(self, x, num, self->cursor->y, false);
        linebuf_init_line(self->linebuf, self->cursor->y);
        line_apply_cursor(self->linebuf->line, self->cursor, x, num, true);
        linebuf_mark_line_dirty(self->linebuf, self->cursor->y);
        self->is_dirty = true;
        clear_intersecting_selections(self, self->cursor->y);
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

static void
remove_characters(Screen *self, index_type at, index_type num, index_type y, bool replace_with_spaces) {
    // delete num chars at x=at setting them to the value of the num chars at [at + num, at + num + num)
    // multiline chars at x >= at are deleted and multicell chars split at x=at
    // and x=at + num - 1 are deleted
    nuke_multiline_char_intersecting_with(self, at, self->columns, y, y + 1, replace_with_spaces);
    nuke_split_multicell_char_at_left_boundary(self, at, y, replace_with_spaces);
    CPUCell *cp; GPUCell *gp;
    linebuf_init_cells(self->linebuf, y, &cp, &gp);
    // left shift
    for (index_type i = at; i < self->columns - num; i++) {
        cp[i] = cp[i+num]; gp[i] = gp[i+num];
    }
    nuke_incomplete_single_line_multicell_chars_in_range(self, at, self->columns, y, replace_with_spaces);
}

void
screen_delete_characters(Screen *self, unsigned int count) {
    // Delete characters, later characters are moved left
    const unsigned int bottom = self->lines ? self->lines - 1 : 0;
    if (count == 0) count = 1;
    if (self->cursor->y <= bottom) {
        unsigned int x = self->cursor->x;
        unsigned int num = MIN(self->columns - x, count);
        remove_characters(self, x, num, self->cursor->y, false);
        linebuf_init_line(self->linebuf, self->cursor->y);
        line_apply_cursor(self->linebuf->line, self->cursor, self->columns - num, num, true);
        linebuf_mark_line_dirty(self->linebuf, self->cursor->y);
        self->is_dirty = true;
        clear_intersecting_selections(self, self->cursor->y);
    }
}

void
screen_erase_characters(Screen *self, unsigned int count) {
    // Delete characters clearing the cells
    if (count == 0) count = 1;
    unsigned int x = self->cursor->x;
    unsigned int num = MIN(self->columns - x, count);
    nuke_multicell_char_intersecting_with(self, x, x + num, self->cursor->y, self->cursor->y + 1, false);
    linebuf_init_line(self->linebuf, self->cursor->y);
    line_apply_cursor(self->linebuf->line, self->cursor, x, num, true);
    linebuf_mark_line_dirty(self->linebuf, self->cursor->y);
    self->is_dirty = true;
    clear_intersecting_selections(self, self->cursor->y);
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
                CALLBACK("on_da1", NULL);
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
        case 996: // https://github.com/contour-terminal/contour/blob/master/docs/vt-extensions/color-palette-update-notifications.md
            if (private) {
                CALLBACK("report_color_scheme_preference", NULL);
            } break;
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
        KNOWN_MODE(COLOR_PREFERENCE_NOTIFICATION);
        KNOWN_MODE(INBAND_RESIZE_NOTIFICATION);
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
color_control(Screen *self, unsigned int code, PyObject *spec) {
    if (spec) CALLBACK("color_control", "IO", code, spec);
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
        else if (strcmp(token, "special_key=1") == 0) self->prompt_settings.uses_special_keys_for_cursor_movement = 1;
        else if (strcmp(token, "click_events=1") == 0) self->prompt_settings.supports_click_events = 1;
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
                self->prompt_settings.uses_special_keys_for_cursor_movement = 0;
                parse_prompt_mark(self, buf+1, &pk);
                self->linebuf->line_attrs[self->cursor->y].prompt_kind = pk;
                if (pk == PROMPT_START) CALLBACK("cmd_output_marking", "O", Py_False);
            } break;
            case 'C': {
                self->linebuf->line_attrs[self->cursor->y].prompt_kind = OUTPUT_START;
                const char *cmdline = "";
                if (strstr(buf + 1, ";cmdline") == buf + 1) {
                    cmdline = buf + 2;
                }
                RAII_PyObject(c, PyUnicode_DecodeUTF8(cmdline, strlen(cmdline), "replace"));
                if (c) { CALLBACK("cmd_output_marking", "OO", Py_True, c); }
                else PyErr_Print();
            } break;
            case 'D': {
                const char *exit_status = buf[1] == ';' ? buf + 2 : "";
                CALLBACK("cmd_output_marking", "Os", Py_None, exit_status);
            } break;
        }
    }
}

static bool
screen_history_scroll_to_prompt(Screen *self, int num_of_prompts_to_jump, int scroll_offset) {
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
        y += scroll_offset;
        while (num_of_prompts_to_jump) {
            y += delta;
            ensure_y_ok;
            if (range_line_(self, y)->attrs.prompt_kind == PROMPT_START) {
                num_of_prompts_to_jump--;
            }
        }
        y -= scroll_offset;
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
                    case NO_CURSOR_SHAPE: case CURSOR_HOLLOW: case NUM_OF_CURSOR_SHAPES:
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
                const char *s = cursor_as_sgr(self->cursor);
                if (s && s[0]) shape = snprintf(buf, sizeof(buf), "1$r0;%sm", s);
                else shape = snprintf(buf, sizeof(buf), "1$rm");
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
    dest->last_rendered_count = src->last_rendered_count;
    return true;
}

bool
screen_pause_rendering(Screen *self, bool pause, int for_in_ms) {
    if (!pause) {
        if (!self->paused_rendering.expires_at) return false;
        self->paused_rendering.expires_at = 0;
        // ensure cell data is updated on GPU
        self->is_dirty = true;
        // ensure selection data is updated on GPU
        self->selections.last_rendered_count = SIZE_MAX; self->url_ranges.last_rendered_count = SIZE_MAX;
        // free grman data
        grman_pause_rendering(NULL, self->paused_rendering.grman);
        return true;
    }
    if (self->paused_rendering.expires_at) return false;
    if (!self->paused_rendering.grman) self->paused_rendering.grman = grman_alloc(true);
    if (!self->paused_rendering.grman) return false;
    if (for_in_ms <= 0) for_in_ms = 2000;
    self->paused_rendering.expires_at = monotonic() + ms_to_monotonic_t(for_in_ms);
    self->paused_rendering.inverted = self->modes.mDECSCNM;
    self->paused_rendering.scrolled_by = self->scrolled_by;
    self->paused_rendering.cell_data_updated = false;
    self->paused_rendering.cursor_visible = self->modes.mDECTCEM;
    memcpy(&self->paused_rendering.cursor, self->cursor, sizeof(self->paused_rendering.cursor));
    memcpy(&self->paused_rendering.color_profile, self->color_profile, sizeof(self->paused_rendering.color_profile));
    if (!self->paused_rendering.linebuf || self->paused_rendering.linebuf->xnum != self->columns || self->paused_rendering.linebuf->ynum != self->lines) {
        if (self->paused_rendering.linebuf) Py_CLEAR(self->paused_rendering.linebuf);
        self->paused_rendering.linebuf = alloc_linebuf(self->lines, self->columns, self->text_cache);
        if (!self->paused_rendering.linebuf) { PyErr_Clear(); self->paused_rendering.expires_at = 0; return false; }
    }
    for (index_type y = 0; y < self->lines; y++) {
        Line *src = visual_line_(self, y);
        linebuf_init_line(self->paused_rendering.linebuf, y);
        copy_line(src, self->paused_rendering.linebuf->line);
        self->paused_rendering.linebuf->line_attrs[y] = src->attrs;
    }
    copy_selections(&self->paused_rendering.selections, &self->selections);
    copy_selections(&self->paused_rendering.url_ranges, &self->url_ranges);
    grman_pause_rendering(self->grman, self->paused_rendering.grman);
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

static uint32_t diacritic_to_rowcolumn(char_type c) {
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
        if (cell_first_char(cpu_cell, self->text_cache) == IMAGE_PLACEHOLDER_CHAR) {
            line->attrs.has_image_placeholders = true;
            // The lower 24 bits of the image id are encoded in the foreground
            // color, and the placement id is (optionally) in the underline color.
            cur_img_id_lower24bits = color_to_id(gpu_cell->fg);
            cur_placement_id = color_to_id(gpu_cell->decoration_fg);
            text_in_cell(cpu_cell, self->text_cache, self->lc);
            // If the char has diacritics, use them as row and column indices.
            if (self->lc->count > 1 && self->lc->chars[1])
                cur_img_row = diacritic_to_rowcolumn(self->lc->chars[1]);
            if (self->lc->count > 2 && self->lc->chars[2])
                cur_img_col = diacritic_to_rowcolumn(self->lc->chars[2]);
            // The third diacritic is used to encode the higher 8 bits of the
            // image id (optional).
            if (self->lc->count > 3 && self->lc->chars[3])
                cur_img_id_higher8bits = diacritic_to_rowcolumn(self->lc->chars[3]);
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
            if (cell_first_char(cpu_cell, self->text_cache) == IMAGE_PLACEHOLDER_CHAR) {
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
                    render_line(fonts_data, linebuf->line, y, &self->paused_rendering.cursor, self->disable_ligatures, self->lc);
                    screen_render_line_graphics(self, linebuf->line, y);
                    if (linebuf->line->attrs.has_dirty_text && screen_has_marker(self)) mark_text_in_line(
                            self->marker, linebuf->line, &self->as_ansi_buf);
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
            render_line(fonts_data, self->historybuf->line, lnum, self->cursor, self->disable_ligatures, self->lc);
            if (screen_has_marker(self)) mark_text_in_line(self->marker, self->historybuf->line, &self->as_ansi_buf);
            historybuf_mark_line_clean(self->historybuf, lnum);
        }
        update_line_data(self->historybuf->line, y, address);
    }
    for (index_type y = self->scrolled_by; y < self->lines; y++) {
        lnum = y - self->scrolled_by;
        linebuf_init_line(self->linebuf, lnum);
        if (self->linebuf->line->attrs.has_dirty_text ||
            (cursor_has_moved && (self->cursor->y == lnum || self->last_rendered.cursor_y == lnum))) {
            render_line(fonts_data, self->linebuf->line, lnum, self->cursor, self->disable_ligatures, self->lc);
            screen_render_line_graphics(self, self->linebuf->line, y - self->scrolled_by);
            if (self->linebuf->line->attrs.has_dirty_text && screen_has_marker(self)) mark_text_in_line(
                    self->marker, self->linebuf->line, &self->as_ansi_buf);
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

static XRange
xrange_for_iteration_with_multicells(const IterationData *idata, const int y, const Line *line) {
    XRange ans = xrange_for_iteration(idata, y, line);
    if (ans.x_limit > ans.x) {
        CPUCell *c; index_type ml;
        if (ans.x && (c = &line->cpu_cells[ans.x])->is_multicell && c->x) ans.x = ans.x > c->x ? ans.x - c->x : 0;
        if (ans.x_limit < line->xnum && (c = &line->cpu_cells[ans.x_limit-1])->is_multicell && c->x + 1u < (ml = mcd_x_limit(c))) {
            ans.x_limit += ml - 1 - c->x; if (ans.x_limit > line->xnum) ans.x_limit = line->xnum;
        }
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
    const int y_min = MAX(0, s->last_rendered.y), y_limit = MIN(s->last_rendered.y_limit, (int)self->lines);
    for (int y = y_min; y < y_limit; y++) {
        if (self->paused_rendering.expires_at) {
            linebuf_init_line(self->paused_rendering.linebuf, y);
            line = self->paused_rendering.linebuf->line;
        } else line = visual_line_(self, y);
        uint8_t *line_start = data + self->columns * y;
        XRange xr = xrange_for_iteration_with_multicells(&s->last_rendered, y, line);
        for (index_type x = xr.x; x < xr.x_limit; x++) {
            line_start[x] |= set_mask;
            CPUCell *c = &line->cpu_cells[x];
            if (c->is_multicell && c->scale > 1) {
                for (int ym = MAX(0, y - c->y); ym < y; ym++) data[self->columns * ym + x] |= set_mask;
                for (int ym = y + 1; ym < MIN((int)self->lines, y + c->scale - c->y); ym++) data[self->columns * ym + x] |= set_mask;
            }
        }
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
        const CPUCell *cell = line->cpu_cells + limit - 1;
        if (cell->is_multicell && (cell->x || cell->y)) { limit--; continue; }
        if (cell->ch_is_idx) break;
        switch(cell->ch_or_idx) {
            case ' ': case '\t': case '\n': case '\r': case 0: break;
            default:
                return limit;
        }
        limit--;
    }
    return limit;
}

static void
flag_selection_to_extract_text(Screen *self, const Selection *s, int *miny, int *y_limit) {
    IterationData idata;
    bool has_history = self->linebuf == self->main_linebuf;
    iteration_data(s, &idata, self->columns, has_history ? -self->historybuf->count : 0, 0);
    Line *line;
    *miny = idata.y; *y_limit = MIN(idata.y_limit, (int)self->lines);
    if (*miny >= *y_limit) return;
    static const int max_scale = ( (1u << SCALE_BITS) - 1u);
    for (int y = idata.y - max_scale; y < *y_limit; y++) {
        line = checked_range_line(self, y);
        if (line) for (index_type x = 0; x < line->xnum; x++) line->cpu_cells[x].temp_flag = 0;
    }
    Line temp = {.xnum=self->columns, .text_cache=self->text_cache};
    for (int y = idata.y; y < *y_limit; y++) {
        range_line(self, y, &temp);
        CPUCell *c;
        XRange xr = xrange_for_iteration_with_multicells(&idata, y, &temp);
        for (index_type x = xr.x; x < xr.x_limit; x++) {
            c = temp.cpu_cells + x;
            c->temp_flag = 1;
            if (c->is_multicell && c->y) {
                for (int ym = y - c->y; ym < y; ym++) {
                    line = checked_range_line(self, ym);
                    if (line) {
                        line->cpu_cells[x].temp_flag = 1;
                        *miny = MIN(*miny, ym);
                    }
                }
            }
        }
    }
    // remove lines from bottom that contain only y > 0 cells from multicell
    while (*y_limit > *miny) {
        range_line(self, *y_limit - 1, &temp);
        for (index_type x = 0; x < temp.xnum; x++) {
            if (temp.cpu_cells[x].temp_flag && temp.cpu_cells[x].ch_and_idx && (!temp.cpu_cells[x].is_multicell || !temp.cpu_cells[x].y)) return;
        }
        (*y_limit)--;
    }
}

static PyObject*
text_for_range(Screen *self, const Selection *sel, bool insert_newlines, bool strip_trailing_whitespace) {
    int min_y, y_limit;
    flag_selection_to_extract_text(self, sel, &min_y, &y_limit);
    if (min_y >= y_limit) return PyTuple_New(0);
    size_t before = self->as_ansi_buf.len;
    RAII_PyObject(ans, PyTuple_New(y_limit - min_y));
    RAII_PyObject(nl, PyUnicode_FromString("\n"));
    RAII_PyObject(empty, PyUnicode_FromString(""));
    if (!ans || !nl || !empty) return NULL;
    for (int i = 0, y = min_y; y < y_limit; y++, i++) {
        Line *line = range_line_(self, y);
        index_type x_limit = line->xnum, x_start = 0;
        while (x_limit && !line->cpu_cells[x_limit - 1].temp_flag) x_limit--;
        while (x_start < x_limit && !line->cpu_cells[x_start].temp_flag) x_start++;
        bool is_only_whitespace_line = false;
        if (strip_trailing_whitespace) {
            index_type new_limit = limit_without_trailing_whitespace(line, x_limit);
            if (new_limit != x_limit) {
                x_limit = new_limit;
                is_only_whitespace_line = new_limit <= x_start;
            }
        }
        const bool is_first_line = y == min_y, is_last_line = y + 1 >= y_limit;
        const bool add_trailing_newline = insert_newlines && !is_last_line;
        PyObject *text = NULL;
        if (x_limit <= x_start && (is_only_whitespace_line || line_is_empty(line))) {
            // we want a newline on only whitespace lines even if they are continued
            text = add_trailing_newline ? nl : empty;
            text = Py_NewRef(text);
        } else {
            while (x_start < x_limit) {
                index_type end = x_start;
                while (end < x_limit && line->cpu_cells[end].temp_flag) end++;
                if (!unicode_in_range(line, x_start, end, true, add_trailing_newline, false, !is_first_line, &self->as_ansi_buf)) return PyErr_NoMemory();
                x_start = MAX(x_start + 1, end);
            }
            text = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, self->as_ansi_buf.buf + before, self->as_ansi_buf.len - before);
        }
        self->as_ansi_buf.len = before;
        if (!text) return NULL;
        PyTuple_SET_ITEM(ans, i, text);
    }
    return Py_NewRef(ans);
}

static PyObject*
ansi_for_range(Screen *self, const Selection *sel, bool insert_newlines, bool strip_trailing_whitespace) {
    int min_y, y_limit;
    flag_selection_to_extract_text(self, sel, &min_y, &y_limit);
    if (min_y >= y_limit) return PyTuple_New(0);
    ANSILineState s = {.output_buf=&self->as_ansi_buf};
    s.output_buf->active_hyperlink_id = 0; s.output_buf->len = 0;
    RAII_PyObject(ans, PyTuple_New(y_limit - min_y + 1));
    RAII_PyObject(nl, PyUnicode_FromString("\n"));
    RAII_PyObject(empty_string, PyUnicode_FromString(""));
    if (!ans || !nl || !empty_string) return NULL;
    bool has_escape_codes = false;
    bool need_newline = false;
    for (int i = 0, y = min_y; y < y_limit && i < PyTuple_GET_SIZE(ans) - 1; y++, i++) {
        const bool is_first_line = y == min_y;
        s.output_buf->len = 0;
        Line *line = range_line_(self, y);
        index_type x_limit = line->xnum, x_start = 0;
        while (x_limit && !line->cpu_cells[x_limit - 1].temp_flag) x_limit--;
        while (x_start < x_limit && !line->cpu_cells[x_start].temp_flag) x_start++;
        bool is_only_whitespace_line = false;
        if (strip_trailing_whitespace) {
            index_type new_limit = limit_without_trailing_whitespace(line, x_limit);
            if (new_limit != x_limit) {
                x_limit = new_limit;
                is_only_whitespace_line = new_limit <= x_start;
            }
        }

        if (x_limit <= x_start && (is_only_whitespace_line || line_is_empty(line))) {
            // we want a newline on only whitespace lines even if they are continued
            if (insert_newlines) need_newline = true;
            PyTuple_SET_ITEM(ans, i, Py_NewRef(need_newline ? nl : empty_string));
        } else {
            char_type prefix_char = need_newline ? '\n' : 0;
            while (x_start < x_limit) {
                index_type end = x_start;
                while (end < x_limit && line->cpu_cells[end].temp_flag) end++;
                if (line_as_ansi(line, &s, x_start, end, prefix_char, !is_first_line)) has_escape_codes = true;
                need_newline = insert_newlines && !line->cpu_cells[line->xnum-1].next_char_was_wrapped;
                prefix_char = 0;
                x_start = MAX(x_start + 1, end);
            }
            PyObject *t = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, s.output_buf->buf, s.output_buf->len);
            if (!t) return NULL;
            PyTuple_SET_ITEM(ans, i, t);
        }
    }
    PyObject *t = PyUnicode_FromFormat("%s%s", has_escape_codes ? "\x1b[m" : "", s.output_buf->active_hyperlink_id ? "\x1b]8;;\x1b\\" : "");
    if (!t) return NULL;
    PyTuple_SET_ITEM(ans, PyTuple_GET_SIZE(ans) - 1, t);
    return Py_NewRef(ans);
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
    RAII_PyObject(empty_string, PyUnicode_FromString(""));
    if (!empty_string) return NULL;
    RAII_PyObject(ans, NULL);
    for (size_t i = 0; i < self->url_ranges.count; i++) {
        Selection *s = self->url_ranges.items + i;
        if (!is_selection_empty(s)) {
            RAII_PyObject(temp, text_for_range(self, s, false, false));
            if (!temp) return NULL;
            RAII_PyObject(text, PyUnicode_Join(empty_string, temp));
            if (!text) return NULL;
            if (ans) {
                PyObject *t = PyUnicode_Concat(ans, text);
                if (!t) return NULL;
                Py_CLEAR(ans); ans = t;
            } else ans = Py_NewRef(text);
        }
    }
    return Py_NewRef(ans ? ans : Py_None);
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
static index_type
get_last_hostname_char_pos(Line *line, index_type url_start) {
    index_type slash_count = 0;
    while (url_start < line->xnum) {
        index_type pos = find_char(line, url_start, '/');
        if (pos >= line->xnum) return line->xnum;
        if (++slash_count > 2) return prev_char_pos(line, pos, 1);
        url_start = next_char_pos(line, pos, 1);
    }
    return line->xnum;
}

static void
extend_url(Screen *screen, Line *line, index_type *x, index_type *y, char_type sentinel, bool newlines_allowed, index_type last_hostname_char_pos, index_type scale) {
    unsigned int count = 0;
    bool has_newline = false;
    index_type orig_y = *y;
    while (count++ < 10) {
        bool in_hostname = last_hostname_char_pos >= line->xnum;
        has_newline = !line->cpu_cells[line->xnum-1].next_char_was_wrapped;
        if (next_char_pos(line, *x, 1) < line->xnum || (!newlines_allowed && has_newline)) break;
        bool next_line_starts_with_url_chars = false;
        line = screen_visual_line(screen, *y + 2 * scale);
        if (line) {
            next_line_starts_with_url_chars = line_startswith_url_chars(line, in_hostname, screen->lc);
            has_newline = !visual_line_is_continued(screen, *y + 2 * scale);
            if (next_line_starts_with_url_chars && has_newline && !newlines_allowed) next_line_starts_with_url_chars = false;
            if (sentinel && next_line_starts_with_url_chars && cell_is_char(line->cpu_cells, sentinel)) next_line_starts_with_url_chars = false;
        }
        line = screen_visual_line(screen, *y + scale);
        if (!line) break;
        if (in_hostname) {
            last_hostname_char_pos = find_char(line, 0, '/');
            if (last_hostname_char_pos < line->xnum) {
                last_hostname_char_pos = prev_char_pos(line, last_hostname_char_pos, 1);
                if (last_hostname_char_pos >= line->xnum) in_hostname = false;
            }
        }
        index_type new_x = line_url_end_at(line, 0, false, sentinel, next_line_starts_with_url_chars, in_hostname, last_hostname_char_pos, screen->lc);
        if (!new_x && !line_startswith_url_chars(line, in_hostname, screen->lc)) break;
        *y += scale; *x = new_x;
    }
    if (sentinel && *x == 0 && *y > orig_y) {
        line = screen_visual_line(screen, *y);
        if (line && cell_is_char(line->cpu_cells, sentinel)) {
            *y -= scale;
            *x = line->xnum - 1;
            if (line->cpu_cells[*x].is_multicell) *x -= line->cpu_cells[*x].x;
        }
    }
}

int
screen_detect_url(Screen *screen, unsigned int x, unsigned int y) {
    bool has_url = false;
    index_type url_start, url_end = 0;
    Line *line = screen_visual_line(screen, y);
    if (!line || x >= screen->columns) return 0;
    if (line->cpu_cells[x].is_multicell && line->cpu_cells[x].scale > 1 && line->cpu_cells[x].y) {
        if (line->cpu_cells[x].y > y) return 0;
        y -= line->cpu_cells[x].y;
        line = screen_visual_line(screen, y);
    }
    if (line->cpu_cells[x].is_multicell && line->cpu_cells[x].x) x = x > line->cpu_cells[x].x ? x - line->cpu_cells[x].x : 0;
    hyperlink_id_type hid;
    if ((hid = line->cpu_cells[x].hyperlink_id)) {
        screen_mark_hyperlink(screen, x, y);
        return hid;
    }
    char_type sentinel = 0;
    const bool newlines_allowed = !is_excluded_from_url('\n');
    index_type last_hostname_char_pos = screen->columns;
    url_start = line_url_start_at(line, x, screen->lc);
    Line scratch = {.xnum=line->xnum, .text_cache=line->text_cache};
    index_type scale = 1;
    if (url_start < line->xnum) {
        scale = cell_scale(line->cpu_cells + url_start);
        bool next_line_starts_with_url_chars = false;
        if (y + scale < screen->lines) {
            visual_line(screen, y + scale, &scratch);
            next_line_starts_with_url_chars = line_startswith_url_chars(&scratch, last_hostname_char_pos >= line->xnum, screen->lc);
            if (next_line_starts_with_url_chars && !newlines_allowed && !visual_line_is_continued(screen, y + scale)) next_line_starts_with_url_chars = false;
        }
        sentinel = get_url_sentinel(line, url_start);
        last_hostname_char_pos = get_last_hostname_char_pos(line, url_start);
        url_end = line_url_end_at(line, x, true, sentinel, next_line_starts_with_url_chars, x <= last_hostname_char_pos, last_hostname_char_pos, screen->lc);
    }
    has_url = url_end > url_start;
    if (has_url) {
        index_type y_extended = y;
        extend_url(screen, line, &url_end, &y_extended, sentinel, newlines_allowed, last_hostname_char_pos, scale);
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
        // remove any multicell characters temporarily that intersect the left boundary,
        // the characters are not actually removed, just deleted on this line
        CPUCell *c = self->linebuf->line->cpu_cells + xstart;
        while (c->is_multicell && c->x && c < self->linebuf->line->cpu_cells + self->columns) {
            c->is_multicell = false; c->ch_or_idx = ' '; c->ch_is_idx = false;
            c++;
        }
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
                    // When the last character is a split multicell, make sure the next character is visible.
                    CPUCell *c = self->linebuf->line->cpu_cells + len - 1;
                    if (c->is_multicell) {
                        if (c->x < mcd_x_limit(c) - 1) {
                            do {
                                c->is_multicell = false; c->ch_is_idx = false; c->ch_or_idx = ' ';
                                if (!c->x) break;
                                c--;
                            } while(c->is_multicell && c >= self->linebuf->line->cpu_cells);
                        }
                    }
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
    render_line(fonts_data, line, ol.ynum, self->cursor, self->disable_ligatures, self->lc);
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
hyperlinks_as_set(Screen *self, PyObject *args UNUSED) {
    return screen_hyperlinks_as_set(self);
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
        } else if (line && line->attrs.prompt_kind == OUTPUT_START && !range_line_is_continued(self, y1)) {
            found_output = true; start = y1;
            found_prompt = true;
            direction = 1;
        }
        y1--; y2++;
    }

    // find upwards
    if (direction <= 0) {
        // find around: only needs to find the first output start
        // find upwards: find prompt after the output, and the first output
        while (y1 >= upward_limit) {
            line = checked_range_line(self, y1);
            if (line && line->attrs.prompt_kind == PROMPT_START && !range_line_is_continued(self, y1)) {
                if (direction == 0) {
                    found_prompt = true;
                    break;
                }
                found_next_prompt = true; end = y1;
            } else if (line && line->attrs.prompt_kind == OUTPUT_START && !range_line_is_continued(self, y1)) {
                found_output = true; start = y1;
                found_prompt = true;
                break;
            }
            y1--;
        }
        if (y1 < upward_limit) {
            oo->reached_upper_limit = true;
            found_output = direction != 0; start = upward_limit;
            found_prompt = direction != 0;
        }
    }

    // find downwards
    if (direction >= 0) {
        while (y2 <= downward_limit) {
            if (on_screen_only && !found_output && y2 > screen_limit) break;
            line = checked_range_line(self, y2);
            if (line && line->attrs.prompt_kind == PROMPT_START) {
                if (!found_prompt) {
                    if (direction == 0) {
                        found_next_prompt = true; end = y2;
                        break;
                    }
                    found_prompt = true;
                } else if (found_prompt && !found_output) {
                    // skip fetching wrapped prompt lines
                    while (range_line_is_continued(self, y2)) {
                        y2++;
                    }
                } else if (found_output && !found_next_prompt) {
                    found_next_prompt = true; end = y2;
                    break;
                }
            } else if (line && line->attrs.prompt_kind == OUTPUT_START && !found_output) {
                found_output = true; start = y2;
                if (!found_prompt) found_prompt = true;
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
                if (!line || (line->attrs.prompt_kind == OUTPUT_START && !range_line_is_continued(self, y))) {
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
            int w = wcwidth_std(char_props_for(ch));
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
pyvisual_line(Screen *self, PyObject *args) {
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

WRAP1E(cursor_move, 1, -1)
WRAP1B(erase_in_line, 0)
WRAP1B(erase_in_display, 0)
static PyObject* scroll_until_cursor_prompt(Screen *self, PyObject *args) { int b=false; if(!PyArg_ParseTuple(args, "|p", &b)) return NULL; screen_scroll_until_cursor_prompt(self, b); Py_RETURN_NONE; }

WRAP0(clear_scrollback)

#define MODE_GETSET(name, uname) \
    static PyObject* name##_get(Screen *self, void UNUSED *closure) { PyObject *ans = self->modes.m##uname ? Py_True : Py_False; Py_INCREF(ans); return ans; } \
    static int name##_set(Screen *self, PyObject *val, void UNUSED *closure) { if (val == NULL) { PyErr_SetString(PyExc_TypeError, "Cannot delete attribute"); return -1; } set_mode_from_const(self, uname, PyObject_IsTrue(val) ? true : false); return 0; }

MODE_GETSET(in_bracketed_paste_mode, BRACKETED_PASTE)
MODE_GETSET(focus_tracking_enabled, FOCUS_TRACKING)
MODE_GETSET(color_preference_notification, COLOR_PREFERENCE_NOTIFICATION)
MODE_GETSET(in_band_resize_notification, INBAND_RESIZE_NOTIFICATION)
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

static bool
cell_is_blank(const CPUCell *c) {
    return !cell_has_text(c) || cell_is_char(c, ' ');
}

bool
screen_selection_range_for_line(Screen *self, index_type y, index_type *start, index_type *end) {
    if (y >= self->lines) { return false; }
    Line *line = visual_line_(self, y);
    index_type xlimit = line->xnum, xstart = 0;
    while (xlimit > 0 && cell_is_blank(line->cpu_cells + xlimit - 1)) xlimit--;
    while (xstart < xlimit && cell_is_blank(line->cpu_cells + xstart)) xstart++;
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
    char_type ch = cell_first_char(line->cpu_cells + x, line->text_cache);
    if (char_props_for(ch).is_word_char || is_opt_word_char(ch, forward)) return true;
    // pass : from :// so that common URLs are matched
    return ch == ':' && x + 2 < line->xnum && cell_is_char(line->cpu_cells + x + 1, '/') && cell_is_char(line->cpu_cells + x + 2,  '/');
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
        if (start > 0 || !visual_line_is_continued(self, y) || *y1 == 0) break;
        line = visual_line_(self, *y1 - 1);
        if (!is_ok(self->columns - 1, false)) break;
        (*y1)--; start = self->columns - 1;
    }
    line = visual_line_(self, *y2);
    while(true) {
        while(end < self->columns - 1 && is_ok(end + 1, true)) end++;
        if (end < self->columns - 1 || *y2 >= self->lines - 1) break;
        line = visual_line_(self, *y2 + 1);
        if (!visual_line_is_continued(self, *y2 + 1) || !is_ok(0, true)) break;
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
    int scroll_offset = 0;
    if (!PyArg_ParseTuple(args, "|ii", &num_of_prompts, &scroll_offset)) return NULL;
    if (screen_history_scroll_to_prompt(self, num_of_prompts, scroll_offset)) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

static PyObject*
set_last_visited_prompt(Screen *self, PyObject *args) {
    index_type visual_y = 0;
    if (!PyArg_ParseTuple(args, "|I", &visual_y)) return NULL;
    if (screen_set_last_visited_prompt(self, visual_y)) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

bool
screen_is_selection_dirty(Screen *self) {
    IterationData q;
    if (self->paused_rendering.expires_at) return false;
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
mark_hyperlinks_in_line(Screen *self, Line *line, hyperlink_id_type id, index_type y, bool *found_nonzero_multiline) {
    index_type start = 0;
    bool found = false;
    bool in_range = false;
    *found_nonzero_multiline = false;
    for (index_type x = 0; x < line->xnum; x++) {
        bool has_hyperlink = line->cpu_cells[x].hyperlink_id == id;
        bool is_nonzero_multiline = line->cpu_cells[x].is_multicell && line->cpu_cells[x].y > 0;
        if (has_hyperlink && is_nonzero_multiline) {
            has_hyperlink = false;
            *found_nonzero_multiline = true;
        }
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
    bool found_nonzero_multiline;
    do {
        if (mark_hyperlinks_in_line(self, line, id, ypos, &found_nonzero_multiline) || found_nonzero_multiline) last_marked_line = ypos;
        if (ypos == 0) break;
        ypos--;
        line = screen_visual_line(self, ypos);
    } while (last_marked_line - ypos < 5);
    ypos = y + 1; last_marked_line = y;
    while (ypos < self->lines - 1 && ypos - last_marked_line < 5) {
        line = screen_visual_line(self, ypos);
        if (mark_hyperlinks_in_line(self, line, id, ypos, &found_nonzero_multiline)) last_marked_line = ypos;
        ypos++;
    }
    if (self->url_ranges.count > 1) sort_ranges(self, &self->url_ranges);
    return id;
}

static index_type
continue_line_upwards(Screen *self, index_type top_line, SelectionBoundary *start, SelectionBoundary *end) {
    while (top_line > 0 && visual_line_is_continued(self, top_line)) {
        if (!screen_selection_range_for_line(self, top_line - 1, &start->x, &end->x)) break;
        top_line--;
    }
    return top_line;
}

static index_type
continue_line_downwards(Screen *self, index_type bottom_line, SelectionBoundary *start, SelectionBoundary *end) {
    while (bottom_line + 1 < self->lines && visual_line_is_continued(self, bottom_line + 1)) {
        if (!screen_selection_range_for_line(self, bottom_line + 1, &start->x, &end->x)) break;
        bottom_line++;
    }
    return bottom_line;
}

static int
clamp_selection_input_to_multicell(Screen *self, const Selection *s, index_type x, index_type y, bool in_left_half_of_cell) {
    int delta = 0;
    int abs_y = y - self->scrolled_by, abs_start_y = s->start.y - s->start_scrolled_by;
    if (abs_y == abs_start_y) return delta;
    Line *line = checked_range_line(self, abs_start_y);
    CPUCell *start, *current;
    if (!line || s->start.x >= line->xnum || !(start = &line->cpu_cells[s->start.x])->is_multicell || start->scale < 2) return delta;
    int abs_start_top = abs_start_y - start->y;
    line = checked_range_line(self, abs_y);
    if (x > s->start.x && in_left_half_of_cell) x--;
    else if (x < s->start.x && !in_left_half_of_cell) x++;
    if (!line || x >= line->xnum) return delta;
    current = line->cpu_cells + x;
    if (!current->is_multicell) return delta;
    int abs_current_top = abs_y - current->y;
    if (current->scale == start->scale && current->subscale_n == start->subscale_n && current->subscale_d == start->subscale_d && abs_current_top == abs_start_top) delta = abs_y - abs_start_y;
    return delta;
}

static void
do_update_selection(Screen *self, Selection *s, index_type x, index_type y, bool in_left_half_of_cell, SelectionUpdate upd) {
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

void
screen_update_selection(Screen *self, index_type x, index_type y, bool in_left_half_of_cell, SelectionUpdate upd) {
    if (!self->selections.count) return;
    self->selections.in_progress = !upd.ended;
    Selection *s = self->selections.items;
    int delta = clamp_selection_input_to_multicell(self, s, x, y, in_left_half_of_cell);
    index_type orig = self->scrolled_by;
    if (delta) {
        int new_y = y - delta;
        if (new_y < 0) {
            y = 0; self->scrolled_by += - new_y;
        } else y = new_y;
    }
    do_update_selection(self, s, x, y, in_left_half_of_cell, upd);
    self->scrolled_by = orig;
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
    unsigned long ans = 1;
    if (self->cursor->x < self->columns && self->cursor->y < self->lines) {
        const CPUCell *c = linebuf_cpu_cells_for_line(self->linebuf, self->cursor->y) + self->cursor->x;
        if (c->is_multicell) {
            if (c->x || c->y) ans = 0;
            else ans = c->width;
        }
    }
    return PyLong_FromUnsignedLong(ans);
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
pause_rendering(Screen *self, PyObject *args) {
    int msec = 100;
    int pause = 1;
    if (!PyArg_ParseTuple(args, "|pi", &msec)) return NULL;
    if (screen_pause_rendering(self, pause, msec)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
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
        mark_text_in_line(self->marker, self->main_linebuf->line, &self->as_ansi_buf);
    }
    for (index_type y = 0; y < self->alt_linebuf->ynum; y++) {
        linebuf_init_line(self->alt_linebuf, y);
        mark_text_in_line(self->marker, self->alt_linebuf->line, &self->as_ansi_buf);
    }
    for (index_type y = 0; y < self->historybuf->count; y++) {
        historybuf_init_line(self->historybuf, y, self->historybuf->line);
        mark_text_in_line(self->marker, self->historybuf->line, &self->as_ansi_buf);
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
    RAII_PyObject(ans, PyList_New(0));
    if (!ans) return ans;
    for (index_type y = 0; y < self->lines; y++) {
        linebuf_init_line(self->linebuf, y);
        for (index_type x = 0; x < self->columns; x++) {
            GPUCell *gpu_cell = self->linebuf->line->gpu_cells + x;
            const unsigned int mark = gpu_cell->attrs.mark;
            if (mark) {
                RAII_PyObject(t, Py_BuildValue("III", x, y, mark));
                if (!t) { return NULL; }
                if (PyList_Append(ans, t) != 0) return NULL;
            }
        }
    }
    return Py_NewRef(ans);
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
COUNT_WRAP(delete_characters)
COUNT_WRAP(erase_characters)
COUNT_WRAP(cursor_up1)
COUNT_WRAP(cursor_down)
COUNT_WRAP(cursor_down1)
COUNT_WRAP(cursor_forward)

static PyObject*
py_insert_characters(Screen *self, PyObject *count_) {
    if (!PyLong_Check(count_)) { PyErr_SetString(PyExc_TypeError, "count must be an integer"); return NULL; }
    unsigned long count = PyLong_AsUnsignedLong(count_);
    screen_insert_characters(self, count);
    Py_RETURN_NONE;
}

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

static void
dump_line_with_attrs(Screen *self, int y, PyObject *accum) {
    Line *line = range_line_(self, y);
    RAII_PyObject(u, PyUnicode_FromFormat("\x1b[31m%d: \x1b[39m", y++));
    if (!u) return;
    RAII_PyObject(r1, PyObject_CallOneArg(accum, u));
    if (!r1) return;
#define call_string(s) { RAII_PyObject(ret, PyObject_CallFunction(accum, "s", s)); if (!ret) return; }
    switch (line->attrs.prompt_kind) {
        case UNKNOWN_PROMPT_KIND: break;
        case PROMPT_START: call_string("\x1b[32mprompt \x1b[39m"); break;
        case SECONDARY_PROMPT: call_string("\x1b[32msecondary_prompt \x1b[39m"); break;
        case OUTPUT_START: call_string("\x1b[33moutput \x1b[39m"); break;
    }
    if (range_line_is_continued(self, y)) call_string("continued ");
    if (line->attrs.has_dirty_text) call_string("dirty ");
    call_string("\n");
    RAII_PyObject(t, line_as_unicode(line, false, &self->as_ansi_buf)); if (!t) return;
    RAII_PyObject(r2, PyObject_CallOneArg(accum, t)); if (!r2) return;
    call_string("\n");
#undef call_string
}

static PyObject*
dump_lines_with_attrs(Screen *self, PyObject *args) {
    PyObject *accum; int which_screen = -1;
    if (!PyArg_ParseTuple(args, "O|i", &accum, &which_screen)) return NULL;
    LineBuf *orig = self->linebuf;
    switch(which_screen) {
        case 0: self->linebuf = self->main_linebuf; break;
        case 1: self->linebuf = self->alt_linebuf; break;
    }
    int y = (self->linebuf == self->main_linebuf) ? -self->historybuf->count : 0;
    while (y < (int)self->lines && !PyErr_Occurred()) dump_line_with_attrs(self, y++, accum);
    self->linebuf = orig;
    if (PyErr_Occurred()) return NULL;
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

static PyObject*
current_selections(Screen *self, PyObject *a UNUSED) {
    PyObject *ans = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)self->lines * self->columns);
    if (!ans) return NULL;
    screen_apply_selection(self, PyBytes_AS_STRING(ans), PyBytes_GET_SIZE(ans));
    return ans;
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

static PyObject*
multicell_data_as_dict(CPUCell mcd) {
    return Py_BuildValue("{sI sI sI sI sO sI sI}",
            "scale", (unsigned int)mcd.scale, "width", (unsigned int)mcd.width,
            "subscale_n", (unsigned int)mcd.subscale_n, "subscale_d", (unsigned int)mcd.subscale_d,
            "natural_width", mcd.natural_width ? Py_True : Py_False, "vertical_align", mcd.valign, "horizontal_align", mcd.halign);
}

static PyObject*
cpu_cell_as_dict(CPUCell *c, TextCache *tc, ListOfChars *lc, HYPERLINK_POOL_HANDLE h) {
    text_in_cell(c, tc, lc);
    RAII_PyObject(mcd, c->is_multicell ? multicell_data_as_dict(*c) : Py_NewRef(Py_None));
    if ((c->is_multicell && (c->x + c->y)) || (lc->count == 1 && lc->chars[0] == 0)) lc->count = 0;
    RAII_PyObject(text, PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, lc->chars, lc->count));
    const char *url = c->hyperlink_id ? get_hyperlink_for_id(h, c->hyperlink_id, false) : NULL;
    RAII_PyObject(hyperlink, url ? PyUnicode_FromString(url) : Py_NewRef(Py_None));
    return Py_BuildValue("{sO sO sI sI sO sO}",
        "text", text, "hyperlink", hyperlink, "x", (unsigned int)c->x, "y", (unsigned int)c->y,
        "mcd", mcd, "next_char_was_wrapped", c->next_char_was_wrapped ? Py_True : Py_False
    );
}

static PyObject*
cpu_cells(Screen *self, PyObject *args) {
    int y, x = -1;
    if (!PyArg_ParseTuple(args, "i|i", &y, &x)) return NULL;
    if (y >= (int)self->lines) { PyErr_SetString(PyExc_IndexError, "y out of bounds"); return NULL; }
    CPUCell *cells;
    if (y >= 0) cells = linebuf_cpu_cells_for_line(self->linebuf, y);
    else {
        Line *l = self->linebuf == self->main_linebuf ? checked_range_line(self, y) : NULL;
        if (!l) { PyErr_SetString(PyExc_IndexError, "y out of bounds"); return NULL; }
        cells = l->cpu_cells;
    }
    if (x > -1) {
        if (x >= (int)self->columns) { PyErr_SetString(PyExc_IndexError, "x out of bounds"); return NULL; }
        return cpu_cell_as_dict(cells + x, self->text_cache, self->lc, self->hyperlink_pool);
    }
    index_type start_x = 0, x_limit = self->columns;
    RAII_PyObject(ans, PyTuple_New(x_limit - start_x));
    if (ans) {
        for (index_type x = start_x; x < x_limit; x++) {
            PyObject *d = cpu_cell_as_dict(cells + x, self->text_cache, self->lc, self->hyperlink_pool);
            if (!d) return NULL;
            PyTuple_SET_ITEM(ans, x, d);
        }
    }
    return Py_NewRef(ans);
}

static PyObject*
test_ch_and_idx(PyObject *self UNUSED, PyObject *val) {
    CPUCell c = {0};
    if (PyLong_Check(val)) {
        unsigned long x = PyLong_AsUnsignedLong(val);
        c.ch_and_idx = x;
    } else if (PyTuple_Check(val)) {
        c.ch_is_idx = PyLong_AsUnsignedLong(PyTuple_GET_ITEM(val, 0));
        c.ch_or_idx = PyLong_AsUnsignedLong(PyTuple_GET_ITEM(val, 1));
    }
    unsigned long is_idx = c.ch_is_idx, idx = c.ch_or_idx, ca = c.ch_and_idx;
    return Py_BuildValue("kkk", is_idx, idx, ca);
}

static PyMethodDef methods[] = {
    METHODB(test_create_write_buffer, METH_NOARGS),
    METHODB(test_commit_write_buffer, METH_VARARGS),
    METHODB(test_parse_written_data, METH_VARARGS),
    MND(line_edge_colors, METH_NOARGS)
    MND(line, METH_O)
    MND(dump_lines_with_attrs, METH_VARARGS)
    MND(cpu_cells, METH_VARARGS)
    MND(cursor_at_prompt, METH_NOARGS)
    {"visual_line", (PyCFunction)pyvisual_line, METH_VARARGS, ""},
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
    MND(cursor_move, METH_VARARGS)
    MND(erase_in_line, METH_VARARGS)
    MND(erase_in_display, METH_VARARGS)
    MND(clear_scrollback, METH_NOARGS)
    MND(scroll_until_cursor_prompt, METH_VARARGS)
    MND(hyperlinks_as_set, METH_NOARGS)
    MND(garbage_collect_hyperlink_pool, METH_NOARGS)
    MND(hyperlink_for_id, METH_O)
    MND(reverse_scroll, METH_VARARGS)
    MND(scroll_prompt_to_bottom, METH_NOARGS)
    METHOD(current_char_width, METH_NOARGS)
    MND(insert_lines, METH_VARARGS)
    MND(delete_lines, METH_VARARGS)
    {"insert_characters", (PyCFunction)py_insert_characters, METH_O, ""},
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
    MND(set_last_visited_prompt, METH_VARARGS)
    MND(send_escape_code_to_child, METH_VARARGS)
    MND(pause_rendering, METH_VARARGS)
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
    MND(current_selections, METH_NOARGS)
    {"select_graphic_rendition", (PyCFunction)_select_graphic_rendition, METH_VARARGS, ""},

    {NULL}  /* Sentinel */
};

static PyGetSetDef getsetters[] = {
    GETSET(in_bracketed_paste_mode)
    GETSET(color_preference_notification)
    GETSET(auto_repeat_enabled)
    GETSET(focus_tracking_enabled)
    GETSET(in_band_resize_notification)
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
    .tp_new = new_screen_object,
    .tp_getset = getsetters,
};

static PyMethodDef module_methods[] = {
    {"is_emoji_presentation_base", (PyCFunction)screen_is_emoji_presentation_base, METH_O, ""},
    {"truncate_point_for_length", (PyCFunction)screen_truncate_point_for_length, METH_VARARGS, ""},
    {"test_ch_and_idx", test_ch_and_idx, METH_O, ""},
    {NULL}  /* Sentinel */
};

INIT_TYPE(Screen)
// }}}
