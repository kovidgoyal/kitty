/*
 * screen.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define EXTRA_INIT                                                            \
    {                                                                         \
        PyModule_AddIntMacro(module, SCROLL_LINE);                            \
        PyModule_AddIntMacro(module, SCROLL_PAGE);                            \
        PyModule_AddIntMacro(module, SCROLL_FULL);                            \
        PyModule_AddIntMacro(module, EXTEND_CELL);                            \
        PyModule_AddIntMacro(module, EXTEND_WORD);                            \
        PyModule_AddIntMacro(module, EXTEND_LINE);                            \
        PyModule_AddIntMacro(module, SCALE_BITS);                             \
        PyModule_AddIntMacro(module, WIDTH_BITS);                             \
        PyModule_AddIntMacro(module, SUBSCALE_BITS);                          \
        if (PyModule_AddFunctions(module, module_methods) != 0) return false; \
    }

#include "data-types.h"
#include "control-codes.h"
#include "screen.h"
#include "vector-glyph.h"
#include "dnd.h"
#include "state.h"
#include "iqsort.h"
#include "fonts.h"
#include "charsets.h"
#include "lineops.h"
#include "hyperlink.h"
#include "gpu.h"
#include <structmember.h>
#include <limits.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include "unicode-data.h"
#include "modes.h"
#include "char-props.h"
#include "simd-string.h"
#include "wcswidth.h"
#include <stdalign.h>
#include <stdio.h>
#include "keys.h"
#include "vt-parser.h"
#include "resize.h"
#include "bidi.h"

static const ScreenModes empty_modes = {0, .mDECAWM = true, .mDECTCEM = true, .mDECARM = true};

#define CSI_REP_MAX_REPETITIONS 65535u
// Images at their natural size are at most 10000 pixels tall, so this is
// enough lines to scroll even the tallest such image fully into the history.
#define MAX_BLANK_LINES_SCROLLED_PAST_IMAGE 10000u

static void scroll_past_image(Screen *self, unsigned int count);

// Constructor/destructor {{{

static void
clear_selection(Selections *selections) {
    selections->in_progress = false;
    selections->extension_in_progress = false;
    selections->extend_mode = EXTEND_CELL;
    selections->count = 0;
}

static void
clear_all_selections(Screen *self) {
    clear_selection(&self->selections);
    clear_selection(&self->url_ranges);
}


static void
init_tabstops(bool *tabstops, index_type count) {
    // In terminfo we specify the number of initial tabstops (it) as 8
    for (unsigned int t = 0; t < count; t++) { tabstops[t] = t % 8 == 0 ? true : false; }
}

static bool
init_overlay_line(Screen *self, index_type columns, bool keep_active) {
    PyMem_Free(self->overlay_line.cpu_cells);
    PyMem_Free(self->overlay_line.render_cells);
    PyMem_Free(self->overlay_line.original_line.cpu_cells);
    PyMem_Free(self->overlay_line.original_line.render_cells);
    self->overlay_line.cpu_cells = PyMem_Calloc(columns, sizeof(CPUCell));
    self->overlay_line.render_cells = PyMem_Calloc(columns, sizeof(RenderCell));
    self->overlay_line.original_line.cpu_cells = PyMem_Calloc(columns, sizeof(CPUCell));
    self->overlay_line.original_line.render_cells = PyMem_Calloc(columns, sizeof(RenderCell));
    if (!self->overlay_line.cpu_cells || !self->overlay_line.render_cells || !self->overlay_line.original_line.cpu_cells ||
        !self->overlay_line.original_line.render_cells) {
        PyErr_NoMemory();
        return false;
    }
    if (!keep_active) {
        self->overlay_line.is_active = false;
        self->overlay_line.xnum = 0;
        self->overlay_line.preedit_cursor = -1;
    }
    self->overlay_line.is_dirty = true;
    self->overlay_line.ynum = 0;
    self->overlay_line.xstart = 0;
    self->overlay_line.cursor_x = 0;
    self->overlay_line.last_ime_pos.x = 0;
    self->overlay_line.last_ime_pos.y = 0;
    self->overlay_line.last_ime_cursor.valid = false;

    return true;
}

static void deactivate_overlay_line(Screen *self);
static void update_overlay_position(Screen *self);
static void render_overlay_line(Screen *self, Line *line, FONTS_DATA_HANDLE fonts_data);
static void update_overlay_line_data(Screen *self, uint8_t *data);

#define CALLBACK(...)                                                               \
    if (self->callbacks != Py_None) {                                               \
        PyObject *callback_ret = PyObject_CallMethod(self->callbacks, __VA_ARGS__); \
        if (callback_ret == NULL) PyErr_Print();                                    \
        else Py_DECREF(callback_ret);                                               \
    }

static PyObject *
new_screen_object(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    Screen *self;
    int ret = 0;
    PyObject *callbacks = Py_None, *test_child = Py_None;
    unsigned int columns = 80, lines = 24, scrollback = 0, cell_width = 10, cell_height = 20;
    id_type window_id = 0;
    if (!PyArg_ParseTuple(args, "|OIIIIIKO", &callbacks, &lines, &columns, &scrollback, &cell_width, &cell_height, &window_id, &test_child)) return NULL;

    self = (Screen *)type->tp_alloc(type, 0);
    if (self != NULL) {
        if ((ret = pthread_mutex_init(&self->write_buf_lock, NULL)) != 0) {
            Py_CLEAR(self);
            PyErr_Format(PyExc_RuntimeError, "Failed to create Screen write_buf_lock mutex: %s", strerror(ret));
            return NULL;
        }
        self->vt_parser = alloc_vt_parser(window_id);
        if (self->vt_parser == NULL) {
            Py_CLEAR(self);
            return PyErr_NoMemory();
        }
        self->text_cache = tc_alloc();
        if (!self->text_cache) {
            Py_CLEAR(self);
            return PyErr_NoMemory();
        }
        self->style_table = tc_style_table(self->text_cache);
        self->reload_all_gpu_data = true;
        self->cell_size.width = cell_width;
        self->cell_size.height = cell_height;
        self->columns = columns;
        self->lines = lines;
        self->write_buf_sz = BUFSIZ;
        self->write_buf = PyMem_RawMalloc(self->write_buf_sz);
        if (self->write_buf == NULL) {
            Py_CLEAR(self);
            return PyErr_NoMemory();
        }
        self->window_id = window_id;
        self->modes = empty_modes;
        self->saved_modes = empty_modes;
        self->is_dirty = true;
        self->scroll_changed = false;
        self->margin_top = 0;
        self->margin_bottom = self->lines - 1;
        reset_vt_parser(self->vt_parser);
        self->callbacks = callbacks;
        Py_INCREF(callbacks);
        self->track_activity = true;
        self->test_child = test_child;
        Py_INCREF(test_child);
        self->cursor = alloc_cursor();
        self->color_profile = alloc_color_profile();
        self->main_linebuf = alloc_linebuf(lines, columns, self->text_cache);
        self->alt_linebuf = alloc_linebuf(lines, columns, self->text_cache);
        self->linebuf = self->main_linebuf;
        self->historybuf = alloc_historybuf(MAX(scrollback, lines), columns, OPT(scrollback_pager_history_size), self->text_cache);
        self->main_grman = grman_alloc(false);
        self->alt_grman = grman_alloc(false);
        self->active_hyperlink_id = 0;

        self->grman = self->main_grman;
        self->disable_ligatures = OPT(disable_ligatures);
        self->main_tabstops = PyMem_Calloc(2 * self->columns, sizeof(bool));
        self->lc = alloc_list_of_chars();
        if (self->cursor == NULL || self->main_linebuf == NULL || self->alt_linebuf == NULL || self->main_tabstops == NULL || self->historybuf == NULL ||
            self->main_grman == NULL || self->alt_grman == NULL || self->color_profile == NULL || self->lc == NULL) {
            Py_CLEAR(self);
            return NULL;
        }
        grman_set_window_id(self->main_grman, self->window_id);
        grman_set_window_id(self->alt_grman, self->window_id);
        self->alt_tabstops = self->main_tabstops + self->columns;
        self->tabstops = self->main_tabstops;
        init_tabstops(self->main_tabstops, self->columns);
        init_tabstops(self->alt_tabstops, self->columns);
        self->key_encoding_flags = self->main_key_encoding_flags;
        if (!init_overlay_line(self, self->columns, false)) {
            Py_CLEAR(self);
            return NULL;
        }
        self->hyperlink_pool = alloc_hyperlink_pool();
        if (!self->hyperlink_pool) {
            Py_CLEAR(self);
            return PyErr_NoMemory();
        }
        self->as_ansi_buf.hyperlink_pool = self->hyperlink_pool;
    }
    return (PyObject *)self;
}

static Line *range_line_(Screen *self, int y);

static void reset_style_table_if_unused(Screen *self);

static void
clamp_scroll_position(Screen *self) {
    // Ensure the scroll position is valid after the scrollback has shrunk
    if (self->scrolled_by >= self->historybuf->count) {
        self->scrolled_by = self->historybuf->count;
        self->pixel_scroll_offset_y = 0;
    }
}

static void
do_screen_reset(Screen *self, bool is_hard_reset) {
    screen_pause_rendering(self, false, 0);
    screen_smooth_scroll_remove_all(self);
    self->dnd_chunking.active = false;
    self->extra_cursors.count = 0;
    zero_at_ptr(&self->extra_cursors.color);
    self->extra_cursors.dirty = true;
    self->main_pointer_shape_stack.count = 0;
    self->alternate_pointer_shape_stack.count = 0;
    if (is_hard_reset && self->linebuf == self->alt_linebuf) screen_toggle_screen_buffer(self, true, true);
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
    if (self->progress_state != PROGRESS_STATE_UNSET || self->progress_percent) {
        self->progress_previous_percent = self->progress_percent;
        self->progress_previous_state = self->progress_state;
        self->progress_changed_at = monotonic();
    }
    self->progress_state = PROGRESS_STATE_UNSET;
    self->progress_percent = 0;
    self->progress_indeterminate_anim_at = 0;
    self->prompt_settings.val = 0;
    self->last_graphic_char = 0;
    self->main_savepoint.is_valid = false;
    self->alt_savepoint.is_valid = false;
    if (is_hard_reset) {
        linebuf_clear(self->linebuf, BLANK_CHAR);
        historybuf_clear(self->historybuf);
        linebuf_clear(self->alt_linebuf, BLANK_CHAR);
        self->main_linebuf->bidi_stamped = self->alt_linebuf->bidi_stamped = false;
        bidi_maps_free(self->bidi_maps);
        self->bidi_maps = NULL;
        bidi_layout_moved(self);
        // all buffers are now empty
        self->multiline_chars_used = false;
        zero_at_ptr(&self->multiline_chars_cut_off_at_bottom);
        self->last_visited_prompt.is_set = false;
        self->scrolled_by = 0;
        self->pixel_scroll_offset_y = 0;
        self->scroll_changed = true;
        clear_hyperlink_pool(self->hyperlink_pool);
        glyph_registry_clear_all(tc_glyph_registry(self->text_cache));
        grman_clear(self->main_grman, false, self->cell_size); // dont delete images in scrollback
        grman_clear(self->alt_grman, true, self->cell_size);
    }
    self->modes = empty_modes;
    self->saved_modes = empty_modes;
    detailed_mouse_events_changed(self);
    zero_at_ptr(&self->bidi);
    screen_bidi_records_writes_changed(self);
    self->active_hyperlink_id = 0;
    zero_at_ptr(&self->color_profile->overridden);
    reset_vt_parser(self->vt_parser);
    zero_at_ptr(&self->charset);
    self->margin_top = 0;
    self->margin_bottom = self->lines - 1;
    screen_normal_keypad_mode(self);
    init_tabstops(self->main_tabstops, self->columns);
    init_tabstops(self->alt_tabstops, self->columns);
    cursor_reset(self->cursor);
    self->is_dirty = true;
    clear_all_selections(self);
    screen_cursor_position(self, 1, 1);
    set_dynamic_color(self, 111, NULL); // does default_bg_changed processing
    colorprofile_reset(self->color_profile);
    if (is_hard_reset) {
        reset_style_table_if_unused(self);
        // Release glyphs registered with the glyph protocol that were bound
        // to cells that no longer exist
        if (vg_live_glyph_memory()) screen_garbage_collect_text_cache(self);
    }
    CALLBACK("on_reset", "O", is_hard_reset ? Py_True : Py_False);
}

void
screen_reset(Screen *self) {
    do_screen_reset(self, true);
}

void
screen_soft_reset(Screen *self) {
    index_type x = self->cursor->x, y = self->cursor->y;
    do_screen_reset(self, false);
    self->cursor->x = x;
    self->cursor->y = y;
}

void
screen_dirty_sprite_positions(Screen *self) {
    self->is_dirty = true;
    for (index_type i = 0; i < self->lines; i++) {
        linebuf_mark_line_dirty(self->main_linebuf, i);
        linebuf_mark_line_dirty(self->alt_linebuf, i);
    }
    for (index_type i = 0; i < self->historybuf->count; i++) historybuf_mark_line_dirty(self->historybuf, i);
    for (unsigned r = 0; r < self->smooth_scroll.count; r++) {
        LineBuf *lb = self->smooth_scroll.regions[r].overflow;
        for (index_type i = 0; i < lb->ynum; i++) linebuf_mark_line_dirty(lb, i);
    }
}

typedef struct CursorTrack {
    index_type num_content_lines;
    bool is_beyond_content;
    struct {
        index_type x, y;
    } before;
    struct {
        index_type x, y;
    } after;
    struct {
        index_type x, y;
    } temp;
} CursorTrack;

// A line only becomes empty by an erase, a shift or a scroll, which is when prepare looks for a buffer left without a record
static inline void
bidi_note_maybe_unstamp(LineBuf *lb) {
    if (UNLIKELY(lb->bidi_stamped)) lb->bidi_maybe_unstamp = true;
}

static inline void
bidi_line_may_reorder_from_cells(Screen *self, LineBuf *lb, index_type y) {
    lb->line_attrs[y].bidi_may_reorder = bidi_cells_may_reorder(linebuf_cpu_cells_for_line(lb, y), lb->xnum, self->text_cache);
}

// Writes to a buffer without a stamp do not keep bidi_may_reorder, so it is recomputed for every row, and for the main buffer
// also for the history rows its row 0 continues, which its first paragraph takes in however far a view scrolled back reaches
void
screen_bidi_recompute_history_may_reorder(Screen *self) {
    self->bidi_history_bits_stale = false;
    HistoryBuf *hb = self->historybuf;
    for (index_type l = 0; l < hb->count && (l ? historybuf_is_line_continued(hb, l - 1) : history_buf_endswith_wrap(hb)); l++)
        historybuf_attrs(hb, l)->bidi_may_reorder = bidi_cells_may_reorder(historybuf_cpu_cells(hb, l), hb->xnum, self->text_cache);
}

static void
bidi_recompute_may_reorder(Screen *self, LineBuf *lb) {
    for (index_type y = 0; y < lb->ynum; y++) bidi_line_may_reorder_from_cells(self, lb, y);
    if (lb == self->main_linebuf) screen_bidi_recompute_history_may_reorder(self);
}

static void
bidi_buffer_gets_stamp(Screen *self, LineBuf *lb) {
    bidi_layout_moved(self);
    lb->bidi_maybe_unstamp = true;
    bidi_recompute_may_reorder(self, lb);
    lb->bidi_stamped = true;
    screen_bidi_records_writes_changed(self);
}

static inline void
bidi_buffer_stamped(Screen *self, LineBuf *lb) {
    if (LIKELY(lb->bidi_stamped)) return;
    bidi_buffer_gets_stamp(self, lb);
}

// A rewrap can pull rows holding a record, or a bit gone stale while the history kept them, from the history into a buffer
static void
bidi_buffer_rewrapped(Screen *self, LineBuf *lb) {
    if (lb->bidi_stamped) {
        bidi_recompute_may_reorder(self, lb);
        return;
    }
    bool stamped = lb == self->main_linebuf && bidi_main_continues_recorded_history(self);
    for (index_type y = 0; y < lb->ynum && !stamped; y++) stamped = line_has_bidi_bits(lb->line_attrs[y]);
    if (stamped) bidi_buffer_stamped(self, lb);
}

static bool history_reuse_disabled_for_tests = false;

static bool
rewrap(
    Screen *screen,
    unsigned int lines,
    unsigned int columns,
    index_type *nclb,
    index_type *ncla,
    CursorTrack *cursor,
    CursorTrack *main_saved_cursor,
    CursorTrack *alt_saved_cursor,
    bool main_is_active) {
    TrackCursor cursors[3];
    cursors[2].is_sentinel = true;
    // alt first as resizing main consumes the history buffer, so it must be
    // the last step that can fail
    cursors[0] = (TrackCursor){.x = alt_saved_cursor->before.x, .y = alt_saved_cursor->before.y};
    if (!main_is_active) cursors[1] = (TrackCursor){.x = cursor->before.x, .y = cursor->before.y};
    else cursors[1].is_sentinel = true;
    ResizeResult ar = resize_screen_buffer_without_rewrap(screen->alt_linebuf, lines, columns, cursors);
    if (!ar.ok) {
        Py_DecRef((PyObject *)ar.lb);
        PyErr_NoMemory();
        return false;
    }
    alt_saved_cursor->temp.x = cursors[0].dest_x;
    alt_saved_cursor->temp.y = cursors[0].dest_y;
    if (!main_is_active) {
        cursor->temp.x = cursors[1].dest_x;
        cursor->temp.y = cursors[1].dest_y;
    }

    cursors[0] = (TrackCursor){.x = main_saved_cursor->before.x, .y = main_saved_cursor->before.y};
    if (main_is_active) cursors[1] = (TrackCursor){.x = cursor->before.x, .y = cursor->before.y};
    else cursors[1].is_sentinel = true;
    ResizeResult mr = resize_screen_buffers(
        screen->main_linebuf,
        screen->historybuf,
        history_reuse_disabled_for_tests ? HISTORY_CONSUME_NO_REUSE : HISTORY_CONSUME,
        lines,
        columns,
        &screen->as_ansi_buf,
        cursors);
    if (!mr.ok) {
        Py_DecRef((PyObject *)ar.lb);
        PyErr_NoMemory();
        return false;
    }
    main_saved_cursor->temp.x = cursors[0].dest_x;
    main_saved_cursor->temp.y = cursors[0].dest_y;
    if (main_is_active) {
        cursor->temp.x = cursors[1].dest_x;
        cursor->temp.y = cursors[1].dest_y;
    }
    Py_CLEAR(screen->main_linebuf);
    Py_CLEAR(screen->alt_linebuf);
    Py_CLEAR(screen->historybuf);
    screen->main_linebuf = mr.lb;
    screen->historybuf = mr.hb;
    screen->alt_linebuf = ar.lb;
    screen->linebuf = main_is_active ? screen->main_linebuf : screen->alt_linebuf;
    screen_bidi_records_writes_changed(screen);
    bidi_buffer_rewrapped(screen, screen->main_linebuf);
    bidi_buffer_rewrapped(screen, screen->alt_linebuf);
    bidi_note_maybe_unstamp(screen->main_linebuf);
    bidi_note_maybe_unstamp(screen->alt_linebuf);
    if (main_is_active) {
        *nclb = mr.num_content_lines_before;
        *ncla = mr.num_content_lines_after;
    } else {
        *nclb = ar.num_content_lines_before;
        *ncla = ar.num_content_lines_after;
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
move_selection_by_one_row(const Screen *self, Selection *s, bool up) {
    // Move the selection with its text when the lines it is on move up or down by one row
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

static void
index_selection(const Screen *self, Selections *selections, bool up, index_type top, index_type bottom, bool via_history) {
    // Keep selections on the same text when the lines in [top, bottom] are
    // scrolled by one. via_history means the line scrolled off the top goes
    // into the scrollback (up) or the line scrolled in at the top comes from
    // it (down), so the scrollback rows move as well. Selections on the rows
    // that stay in place, including those in the scrollback when it does not
    // move, are left alone and selections that span moving and stationary rows
    // or are on the line that is discarded are cleared.
    const int first_moving = via_history ? INT_MIN : (int)top, last_moving = bottom;
    for (size_t i = 0; i < selections->count; i++) {
        Selection *s = selections->items + i;
        const int start = (int)s->start.y - (int)s->start_scrolled_by, end = (int)s->end.y - (int)s->end_scrolled_by;
        const int stop = MIN(start, end), sbottom = MAX(start, end);
        if (sbottom < first_moving || stop > last_moving) continue;
        const bool discarded = up ? (!via_history && stop == (int)top) : sbottom == last_moving;
        if (stop < first_moving || sbottom > last_moving || discarded) {
            clear_selection(selections);
            return;
        }
        move_selection_by_one_row(self, s, up);
    }
}

static void
last_visited_prompt_index(Screen *self, index_type top, index_type bottom, bool up, bool via_history) {
    // Keep the last visited prompt on the same content when the lines in
    // [top, bottom] of the main screen are scrolled by one. via_history means
    // the line scrolled off the top goes into the scrollback (up) or the line
    // scrolled in at the top comes from it (down), so the scrollback rows move too.
    if (!self->last_visited_prompt.is_set || self->linebuf != self->main_linebuf) return;
    int *row = &self->last_visited_prompt.row;
    const int t = top, b = bottom;
    if (*row > b) return;
    if (!via_history && *row < t) return;
    if (up) {
        if (!via_history && *row == t) self->last_visited_prompt.is_set = false;
        else {
            (*row)--;
            // a full scrollback drops its oldest line when one is added
            if (*row < -(int)self->historybuf->count) self->last_visited_prompt.is_set = false;
        }
    } else {
        if (*row == b) self->last_visited_prompt.is_set = false;
        else (*row)++;
    }
}

static void
last_visited_prompt_insert_or_delete_lines(Screen *self, index_type at, index_type bottom, index_type count, bool insert) {
    // Keep the last visited prompt on the same content when count lines are
    // inserted or deleted at row at, moving the lines in [at, bottom].
    if (!self->last_visited_prompt.is_set || self->linebuf != self->main_linebuf) return;
    int *row = &self->last_visited_prompt.row;
    if (*row < (int)at || *row > (int)bottom) return;
    const index_type r = *row;
    if (insert) {
        if (count > bottom - r) self->last_visited_prompt.is_set = false; // pushed out of the region
        else *row += count;
    } else {
        if (count > r - at) self->last_visited_prompt.is_set = false; // deleted
        else *row -= count;
    }
}

static bool
last_visited_prompt_viewport(const Screen *self, index_type *y, unsigned int *scrolled_by) {
    // Return the viewport position of the last visited prompt, showing it at
    // the row it was visited at if the scrollback allows it.
    if (!self->last_visited_prompt.is_set || self->linebuf != self->main_linebuf) return false;
    const int row = self->last_visited_prompt.row, history_count = self->historybuf->count;
    if (row < -history_count || row >= (int)self->lines) return false;
    const int sb = MAX(0, MIN((int)self->last_visited_prompt.preferred_y - row, history_count));
    *scrolled_by = sb;
    *y = row + sb;
    return true;
}

#define INDEX_GRAPHICS(amtv, histv)                                                          \
    {                                                                                        \
        if (UNLIKELY(grman_has_any_images(self->grman))) {                                   \
            bool is_main = self->linebuf == self->main_linebuf;                              \
            static ScrollData s;                                                             \
            s.amt = amtv;                                                                    \
            s.scroll_history = histv;                                                        \
            s.limit = is_main ? -self->historybuf->ynum : 0;                                 \
            s.has_margins = self->margin_top != 0 || self->margin_bottom != self->lines - 1; \
            s.margin_top = top;                                                              \
            s.margin_bottom = bottom;                                                        \
            grman_scroll_images(self->grman, &s, self->cell_size);                           \
        }                                                                                    \
    }


// Rows moved without being dirtied change the paragraphs on both sides of where they now meet, and the upload trusts the
// stored levels of clean rows
static void
bidi_mark_seam(Screen *self, index_type y) {
    LineBuf *lb = self->linebuf;
    if (LIKELY(!lb->bidi_stamped)) return;
    if (y && y <= lb->ynum) linebuf_mark_line_dirty(lb, y - 1);
    if (y < lb->ynum) linebuf_mark_line_dirty(lb, y);
}

// The columns a row keeps and the edges of its spans depend on the regions covering its screen row, so the stored levels of a
// row that moves between screen rows are only valid while no region is horizontal or narrower than the screen. Otherwise every
// row in [top, bottom] is marked to be laid out again.
static void
bidi_mark_rows_moved_near_regions(Screen *self, index_type top, index_type bottom) {
    if (LIKELY(!self->smooth_scroll.count)) return;
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) {
        const SmoothScrollRegion *r = self->smooth_scroll.regions + i;
        if (r->horizontal || r->left || r->right != self->columns) {
            LineBuf *lb = self->linebuf;
            for (index_type y = top; y <= bottom && y < lb->ynum; y++) linebuf_mark_line_dirty(lb, y);
            return;
        }
    }
}

// Before the rows [top, bottom] scroll up by one. An edit to a row going into the history is no longer seen, as the upload
// does not check rows above the view, so the row below it is marked instead. Only a stamped buffer has rows holding a record,
// so the history learns here that it gets one.
static inline void
bidi_index_up_seams(Screen *self, index_type top, index_type bottom, bool to_history) {
    LineBuf *lb = self->linebuf;
    if (LIKELY(!lb->bidi_stamped)) return;
    lb->bidi_maybe_unstamp = true;
    bidi_layout_moved(self);
    bidi_mark_rows_moved_near_regions(self, top, bottom);
    if (to_history) {
        // A record left on a line erased of its text is not pushed, so that it does not keep the history stamped
        LineAttrs *a = lb->line_attrs + top;
        if (a->bidi_stamp != BIDI_STAMP_NONE) {
            linebuf_init_line(lb, top);
            line_has_bidi_record(a, lb->line);
        }
        historybuf_note_bidi(self->historybuf, *a);
    }
    if (!to_history && top) linebuf_mark_line_dirty(lb, top - 1);
    if (top < bottom && (!to_history || lb->line_attrs[top].has_dirty_text)) linebuf_mark_line_dirty(lb, top + 1);
    linebuf_mark_line_dirty(lb, bottom);
    if (bottom + 1 < lb->ynum) linebuf_mark_line_dirty(lb, bottom + 1);
}

// A line back from the history in main buffer row y can hold a record, or continue a history line that holds one, while the main
// buffer holds none. Its bit is stale if it was written to the buffer without a stamp, and so are those of the history lines it
// continues, which the next upload recomputes once for any number of pops.
static void
bidi_note_line_from_history(Screen *self, index_type y) {
    LineBuf *lb = self->main_linebuf;
    if (lb->bidi_stamped) {
        bidi_line_may_reorder_from_cells(self, lb, y);
        if (history_buf_endswith_wrap(self->historybuf)) self->bidi_history_bits_stale = true;
    } else if (line_has_bidi_bits(lb->line_attrs[y]) || bidi_main_continues_recorded_history(self)) bidi_buffer_gets_stamp(self, lb);
}

static void
bidi_index_down_seams(Screen *self, index_type top, index_type bottom) {
    if (LIKELY(!self->linebuf->bidi_stamped)) return;
    self->linebuf->bidi_maybe_unstamp = true;
    bidi_layout_moved(self);
    bidi_mark_rows_moved_near_regions(self, top, bottom);
    bidi_mark_seam(self, top);
    bidi_mark_seam(self, top + 1);
    bidi_mark_seam(self, bottom + 1);
}

static void
clear_scrolled_in_line(Screen *self, index_type y) {
    // Marks are render data that is used without rendering, so the render
    // data can be left to be recomputed by rendering only without a marker
    if (LIKELY(self->marker == NULL)) linebuf_clear_line_text(self->linebuf, y);
    else linebuf_clear_line(self->linebuf, y, true);
}

static void ssr_lines_moved(Screen *self, index_type top, index_type bottom, bool up, bool via_history);

#define INDEX_DOWN(scroll_history)                                                                                      \
    if (UNLIKELY(self->smooth_scroll.count)) ssr_lines_moved(self, top, bottom, false, scroll_history);                 \
    linebuf_reverse_index(self->linebuf, top, bottom);                                                                  \
    clear_scrolled_in_line(self, top);                                                                                  \
    bidi_index_down_seams(self, top, bottom);                                                                           \
    last_visited_prompt_index(self, top, bottom, false, scroll_history);                                                \
    INDEX_GRAPHICS(1, scroll_history)                                                                                   \
    self->is_dirty = true;                                                                                              \
    if (UNLIKELY(self->selections.count)) index_selection(self, &self->selections, false, top, bottom, scroll_history); \
    if (UNLIKELY(self->url_ranges.count || self->url_ranges.in_progress)) clear_selection(&self->url_ranges);


static void
nuke_in_line(CPUCell *cp, index_type start, index_type x_limit, char_type ch) {
    // The line must be marked dirty after this
    for (index_type x = start; x < x_limit; x++) {
        cell_set_char(cp + x, ch);
        cell_clear_multicell(cp + x);
    }
}

typedef struct MulticellRows {
    int start, limit;
} MulticellRows;

static MulticellRows
multicell_char_rows(Screen *self, index_type x, index_type y) {
    // The rows [start, limit) occupied by the multicell char that has a cell
    // at (x, y), negative rows are in the history buffer. Multiline chars can
    // be partial, with some of their rows scrolled off the screen or out of
    // the history buffer, or torn, with some of their rows replaced by
    // unrelated lines. So rather than trusting the y and scale of the cell,
    // only the adjacent rows that actually continue the char are included.
    const CPUCell ref = linebuf_cpu_cells_for_line(self->linebuf, y)[x];
    MulticellRows ans = {.start = (int)y, .limit = (int)y + 1};
    if (!ref.is_multicell) return ans;
    const int min_y = self->linebuf == self->main_linebuf ? -(int)self->historybuf->count : 0;
    for (int r = (int)y - 1, ry = (int)ref.y - 1; ry >= 0 && r >= min_y; r--, ry--) {
        if (!continues_multicell_char(range_line_(self, r)->cpu_cells + x, &ref, ry)) break;
        ans.start = r;
    }
    for (index_type r = y + 1, ry = ref.y + 1u; ry < ref.scale && r < self->lines; r++, ry++) {
        if (!continues_multicell_char(linebuf_cpu_cells_for_line(self->linebuf, r) + x, &ref, ry)) break;
        ans.limit = (int)r + 1;
    }
    return ans;
}

static void
mark_range_line_dirty(Screen *self, int y) {
    if (y > -1) linebuf_mark_line_dirty(self->linebuf, y);
    else historybuf_mark_line_dirty(self->historybuf, -(y + 1));
}

static void ssr_nuke_overflow_parts(Screen *self, index_type x_start, index_type x_limit, MulticellRows rows, char_type ch);
static inline void reset_pixel_scroll(Screen *self, unsigned val);

static void
nuke_multicell_char_at(Screen *self, index_type x_, index_type y_, bool replace_with_spaces) {
    const MulticellRows rows = multicell_char_rows(self, x_, y_);
    const MulticellColumns cols = multicell_char_columns(linebuf_cpu_cells_for_line(self->linebuf, y_), self->columns, x_);
    x_ = cols.start;
    const index_type x_limit = cols.limit;
    const char_type ch = replace_with_spaces ? ' ' : 0;
    if (UNLIKELY(self->smooth_scroll.count)) ssr_nuke_overflow_parts(self, x_, x_limit, rows, ch);
    for (int y = rows.start; y < rows.limit; y++) {
        Line *line = range_line_(self, y);
        nuke_in_line(line->cpu_cells, x_, x_limit, ch);
        mark_range_line_dirty(self, y);
    }
    bidi_note_maybe_unstamp(self->linebuf);
    self->is_dirty = true;
}

static void
nuke_multiline_char_intersecting_with(Screen *self, index_type x_start, index_type x_limit, index_type y_start, index_type y_limit, bool replace_with_spaces) {
    for (index_type y = y_start; y < y_limit; y++) {
        CPUCell *cp;
        linebuf_init_cells(self->linebuf, y, &cp, NULL);
        for (index_type x = x_start; x < x_limit; x++) {
            if (cp[x].is_multicell && cp[x].scale > 1) nuke_multicell_char_at(self, x, y, replace_with_spaces);
        }
    }
}

static bool *
multiline_chars_cut_off_at_bottom(Screen *self) {
    return self->multiline_chars_cut_off_at_bottom + (self->linebuf == self->alt_linebuf ? 1 : 0);
}

static void
nuke_multiline_chars_extending_below(Screen *self, index_type bottom) {
    // Remove chars extending below the line bottom when a new line is about to come in below it, tearing
    // them. When bottom is the last line of the screen these are chars cut off at the bottom of the screen.
    bool *cut_off = multiline_chars_cut_off_at_bottom(self);
    const bool at_screen_bottom = bottom + 1 >= self->lines;
    if (at_screen_bottom && !*cut_off) return;
    const CPUCell *cp = linebuf_cpu_cells_for_line(self->linebuf, bottom);
    if (cells_have_multiline_chars(cp, self->columns)) {
        for (index_type x = 0; x < self->columns; x++) {
            if (cp[x].is_multicell && cp[x].y + 1u < cp[x].scale) nuke_multicell_char_at(self, x, bottom, false);
        }
    }
    if (at_screen_bottom) *cut_off = false;
}

static void
nuke_multiline_chars_torn_by_scroll(Screen *self, index_type top, index_type bottom, bool up, bool history_adjoins_top) {
    // Scrolling the region [top, bottom] moves its lines by one, removing the line
    // at one edge and bringing a new line in at the other. Multiline chars
    // that end up cut off at the edge of the screen (or of the history buffer)
    // are left alone, they are partially scrolled off and are rendered as
    // such. Chars that would end up torn, with the rows adjacent to the
    // remaining part of the char being from unrelated lines, are removed.
    // history_adjoins_top must be true when the line removed from (up) or
    // brought into (down) the top of the region is moved into or out of the
    // history buffer.
    if (!self->multiline_chars_used || top >= bottom || bottom >= self->lines) return;
#define has_multiline(y) cells_have_multiline_chars(linebuf_cpu_cells_for_line(self->linebuf, y), self->columns)
    if (up) {
        // The top line is removed. This cuts chars at the edge of the screen
        // only if there is nothing above it, i.e. on the alternate screen.
        // On the main screen, the line above the screen is the newest
        // history line.
        const bool at_edge = top == 0 && (history_adjoins_top || self->linebuf == self->alt_linebuf);
        if (!at_edge && has_multiline(top)) nuke_multiline_char_intersecting_with(self, 0, self->columns, top, top + 1, false);
        // A new line comes in at the bottom
        nuke_multiline_chars_extending_below(self, bottom);
    } else {
        // The bottom line is removed, cutting chars at the edge of the screen
        // if it is the last line of the screen. Rather than scanning for such
        // chars here, the flag is set unconditionally, the next scroll up scans
        // for them once and clears it.
        if (bottom + 1 < self->lines) {
            if (has_multiline(bottom)) nuke_multiline_char_intersecting_with(self, 0, self->columns, bottom, bottom + 1, false);
        } else *multiline_chars_cut_off_at_bottom(self) = true;
        // A new line comes in at the top, tearing chars that extend above the
        // top line unless the new line is the history line above the top line
        if (!(top == 0 && history_adjoins_top) && has_multiline(top)) {
            const CPUCell *cp = linebuf_cpu_cells_for_line(self->linebuf, top);
            for (index_type x = 0; x < self->columns; x++) {
                if (cp[x].is_multicell && cp[x].y > 0) nuke_multicell_char_at(self, x, top, false);
            }
        }
    }
#undef has_multiline
}

static bool
has_multicell_in_range(const CPUCell *cells, index_type x_start, index_type x_limit) {
    // Lines rarely contain multicell chars, so check for them before looking for them
    // cell by cell. This reads only the 32 bit word of each cell that contains the
    // is_multicell flag, via memcpy() to avoid aliasing issues, into independent
    // accumulators so that there is no dependency between consecutive cells.
    static_assert(sizeof(CPUCell) == 3 * sizeof(uint32_t), "has_multicell_in_range() needs updating");
    const CPUCell probe = {.is_multicell = true};
    uint32_t mask[3];
    memcpy(mask, &probe, sizeof(mask));
    const unsigned word = mask[0] ? 0 : (mask[1] ? 1 : 2);
    const uint8_t *p = (const uint8_t *)(cells + x_start) + word * sizeof(uint32_t);
    const uint8_t *limit = (const uint8_t *)(cells + x_limit) + word * sizeof(uint32_t);
    uint32_t a = 0, b = 0, c = 0, d = 0, v;
#define W(acc, i)                                     \
    memcpy(&v, p + (i) * sizeof(CPUCell), sizeof(v)); \
    acc |= v;
    for (; p + 4 * sizeof(CPUCell) <= limit; p += 4 * sizeof(CPUCell)) {
        W(a, 0);
        W(b, 1);
        W(c, 2);
        W(d, 3);
    }
    for (; p < limit; p += sizeof(CPUCell)) { W(a, 0); }
#undef W
    return ((a | b | c | d) & mask[word]) != 0;
}

static void
nuke_multicell_char_intersecting_with(Screen *self, index_type x_start, index_type x_limit, index_type y_start, index_type y_limit, bool replace_with_spaces) {
    for (index_type y = y_start; y < y_limit; y++) {
        CPUCell *cp;
        linebuf_init_cells(self->linebuf, y, &cp, NULL);
        if (!has_multicell_in_range(cp, x_start, x_limit)) continue;
        for (index_type x = x_start; x < x_limit; x++) {
            if (cp[x].is_multicell) nuke_multicell_char_at(self, x, y, replace_with_spaces);
        }
    }
}

// Smooth scroll regions {{{
// An application designates up to MAX_SMOOTH_SCROLL_REGIONS rectangles of the
// screen for smooth scrolling and then scrolls them by amounts in pixels,
// vertically or horizontally. The terminal moves the cells in a rectangle by
// whole rows (columns) and the rectangle is rendered shifted by the remaining
// fraction of a row (column), see SmoothScrollRegion. The row (column) that
// enters the rectangle in the direction of the scroll is always in the
// rectangle, so that the application can draw it before it becomes visible.
// The partially visible row (column) at the other edge comes from the overflow
// buffers. Rows (columns) that move out of the rectangle are pushed onto the
// overflow buffer on that side and rows (columns) that move into it are
// popped from the overflow buffer on their side, or are blank for the
// application to draw, if it is empty. When a vertically scrolled rectangle
// spans the full width of the main screen and starts at its top, the
// scrollback is the overflow buffer above it, just as when scrolling with SU,
// unless the application opts out. Below, before means above or to the left
// of a rectangle and after means below it or to its right.

static bool
ssr_is_full_width(const Screen *self, const SmoothScrollRegion *r) {
    return r->left == 0 && r->right == self->columns;
}

static bool
ssr_uses_history(const Screen *self, const SmoothScrollRegion *r) {
    return !r->horizontal && !r->private_overflow && r->top == 0 && ssr_is_full_width(self, r) && self->linebuf == self->main_linebuf &&
           self->historybuf->ynum > 0;
}

static unsigned
ssr_cell_image_region_rows(const Screen *self, const LineBuf *linebuf, uint32_t except, CellImageRegionRows *ans) {
    // The rows of the vertically scrolling regions on linebuf, other than
    // except. The cell images moving with them outside these rows are created
    // from the cells in their overflow buffers, see ssr_render_edge_line_graphics()
    unsigned n = 0;
    if (linebuf != self->smooth_scroll.linebuf) return 0;
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) {
        const SmoothScrollRegion *r = self->smooth_scroll.regions + i;
        if (!r->horizontal && r->id != except) ans[n++] = (CellImageRegionRows){.id = r->id, .top = (int32_t)r->top, .bottom = (int32_t)r->bottom};
    }
    return n;
}

static index_type
ssr_width(const SmoothScrollRegion *r) {
    return r->right - r->left;
}

static index_type
ssr_height(const SmoothScrollRegion *r) {
    return r->bottom - r->top;
}

static index_type
ssr_slot(const SmoothScrollRegion *r, bool before, index_type i) {
    // The row of the overflow buffer of a vertically scrolled region holding
    // the i-th nearest row above or below the rectangle
    return before ? i : r->capacity + i;
}

static void
ssr_overflow_row_cells(SmoothScrollRegion *r, bool before, index_type i, CPUCell **c, RenderCell **rc) {
    // The cells of the overflow buffer of a horizontally scrolled region for
    // row i of the rectangle, to the left of it, with the nearest last, or to
    // its right, with the nearest first
    linebuf_init_cells(r->overflow, before ? i : ssr_height(r) + i, c, rc);
}

static index_type
ssr_nearest_column(const SmoothScrollRegion *r, bool before) {
    // The cell of an overflow row of a horizontally scrolled region with the column nearest to the rectangle
    return before ? r->capacity - 1 : 0;
}

static SmoothScrollRegion *
ssr_for_id(Screen *self, uint32_t id) {
    for (unsigned i = 0; i < self->smooth_scroll.count; i++)
        if (self->smooth_scroll.regions[i].id == id) return self->smooth_scroll.regions + i;
    return NULL;
}

static bool
ssr_rows_intersect(const SmoothScrollRegion *r, index_type top, index_type bottom) {
    // Whether the rows [top, bottom] intersect the rectangle
    return r->top <= bottom && top < r->bottom;
}

static CPUCell *
ssr_overflow_cells(SmoothScrollRegion *r, index_type slot) {
    return linebuf_cpu_cells_for_line(r->overflow, slot);
}

static void
ssr_mark_row_dirty(Screen *self, index_type y) {
    linebuf_mark_line_dirty(self->linebuf, y);
    self->is_dirty = true;
}

// Vertical scrolling {{{
static inline void
ssr_copy_row_to_slot(Screen *self, SmoothScrollRegion *r, index_type y, index_type slot) {
    CPUCell *sc, *dc;
    RenderCell *sr, *dr;
    linebuf_init_cells(self->linebuf, y, &sc, &sr);
    linebuf_init_cells(r->overflow, slot, &dc, &dr);
    const index_type w = ssr_width(r);
    memcpy(dc, sc + r->left, w * sizeof(dc[0]));
    memcpy(dr, sr + r->left, w * sizeof(dr[0]));
    const LineAttrs src = self->linebuf->line_attrs[y];
    LineAttrs *dest = r->overflow->line_attrs + slot;
    if (ssr_is_full_width(self, r)) *dest = src;
    else {
        dest->val = 0;
        dest->has_image_placeholders = src.has_image_placeholders;
    }
    dest->has_dirty_text = true;
    if (LIKELY(!self->linebuf->bidi_stamped)) return;
    // The strip draws the kept row at the levels in its render cells, which a row of a paragraph changed since it was rendered
    // has for other text, and no walk reaches it. Its paragraph is read where it is, before the rows move.
    bidi_store_kept_row_levels(self, y, r->left, w, dr);
    // The kept row carries the line's settings, as that layout left them, and the frames keep their bidi maps while it is drawn
    const LineAttrs laid_out = self->linebuf->line_attrs[y];
    line_attrs_set_bidi(dest, laid_out);
    if (line_has_bidi_bits(laid_out)) r->overflow->bidi_stamped = true;
}

// A row of a region narrower than the screen that holds no text outside it takes the settings of the text moved onto it: the
// record of the row it came from, none when that has none. Blank cells moved in drop its record and keep the direction a leading
// mark set for the row's first text. A row with text outside keeps its own, so that the text the scroll did not move is laid out
// as before.
static void
ssr_carry_bidi_record(Screen *self, const SmoothScrollRegion *r, index_type y, const CPUCell *moved, LineAttrs src) {
    self->linebuf->line_attrs[y].bidi_may_reorder |= src.bidi_may_reorder;
    self->linebuf->bidi_maybe_unstamp = true;
    const CPUCell *c = linebuf_cpu_cells_for_line(self->linebuf, y);
    for (index_type x = 0; x < r->left; x++)
        if (c[x].ch_and_idx) return;
    for (index_type x = r->right; x < self->columns; x++)
        if (c[x].ch_and_idx) return;
    bool has_text = false;
    for (index_type x = 0; moved && x < ssr_width(r) && !has_text; x++) has_text = moved[x].ch_and_idx != 0;
    LineAttrs *a = self->linebuf->line_attrs + y;
    if (has_text && src.bidi_stamp != BIDI_STAMP_NONE) {
        line_attrs_set_bidi(a, src);
        bidi_buffer_stamped(self, self->linebuf);
    } else if (has_text || a->bidi_stamp != BIDI_STAMP_NONE) line_attrs_set_bidi(a, (LineAttrs){0});
}

static inline void
ssr_copy_slot_to_row(Screen *self, SmoothScrollRegion *r, index_type slot, index_type y) {
    CPUCell *sc, *dc;
    RenderCell *sr, *dr;
    linebuf_init_cells(r->overflow, slot, &sc, &sr);
    linebuf_init_cells(self->linebuf, y, &dc, &dr);
    const index_type w = ssr_width(r);
    memcpy(dc + r->left, sc, w * sizeof(dc[0]));
    memcpy(dr + r->left, sr, w * sizeof(dr[0]));
    const LineAttrs src = r->overflow->line_attrs[slot];
    LineAttrs *dest = self->linebuf->line_attrs + y;
    if (ssr_is_full_width(self, r)) *dest = src;
    else {
        dest->has_image_placeholders |= src.has_image_placeholders;
        if (UNLIKELY(self->linebuf->bidi_stamped || line_has_bidi_bits(src))) ssr_carry_bidi_record(self, r, y, sc, src);
    }
    // The slot's bit is stale when the row was kept while the buffer held no stamp
    if (UNLIKELY(self->linebuf->bidi_stamped) && !dest->bidi_may_reorder) dest->bidi_may_reorder = bidi_cells_may_reorder(sc, w, self->text_cache);
    ssr_mark_row_dirty(self, y);
}

static inline void
ssr_copy_row_to_row(Screen *self, SmoothScrollRegion *r, index_type src_y, index_type dest_y) {
    // Only used for rectangles narrower than the screen, full width rows are
    // moved by rotating the line map. The row is rendered again, as the
    // shaping of its cells can depend on the cells outside the rectangle.
    CPUCell *sc, *dc;
    RenderCell *sr, *dr;
    linebuf_init_cells(self->linebuf, src_y, &sc, &sr);
    linebuf_init_cells(self->linebuf, dest_y, &dc, &dr);
    const index_type w = ssr_width(r);
    memcpy(dc + r->left, sc + r->left, w * sizeof(dc[0]));
    memcpy(dr + r->left, sr + r->left, w * sizeof(dr[0]));
    self->linebuf->line_attrs[dest_y].has_image_placeholders |= self->linebuf->line_attrs[src_y].has_image_placeholders;
    if (UNLIKELY(self->linebuf->bidi_stamped)) ssr_carry_bidi_record(self, r, dest_y, sc + r->left, self->linebuf->line_attrs[src_y]);
    ssr_mark_row_dirty(self, dest_y);
}

static inline void
ssr_blank_row(Screen *self, SmoothScrollRegion *r, index_type y) {
    if (ssr_is_full_width(self, r)) clear_scrolled_in_line(self, y);
    else {
#if BLANK_CHAR != 0
#error This implementation is incorrect for BLANK_CHAR != 0
#endif
        CPUCell *c;
        RenderCell *rc;
        linebuf_init_cells(self->linebuf, y, &c, &rc);
        zero_at_ptr_count(c + r->left, ssr_width(r));
        zero_at_ptr_count(rc + r->left, ssr_width(r));
        if (UNLIKELY(self->linebuf->bidi_stamped)) ssr_carry_bidi_record(self, r, y, NULL, (LineAttrs){0});
    }
    ssr_mark_row_dirty(self, y);
}

static index_type
ssr_push_slot(SmoothScrollRegion *r, bool before) {
    // Make room for a new nearest row in an overflow buffer, discarding its
    // farthest row if it is full, and return the slot for the new row
    const index_type base = ssr_slot(r, before, 0);
    linebuf_reverse_index(r->overflow, base, base + r->capacity - 1);
    index_type *n = before ? &r->num_before : &r->num_after;
    if (*n < r->capacity) (*n)++;
    return base;
}

static void
ssr_pop_slot(SmoothScrollRegion *r, bool before) {
    // Remove the nearest row of an overflow buffer, after it has been copied out
    const index_type base = ssr_slot(r, before, 0);
    // Cleared so that it does not keep text cache entries and styles alive
    linebuf_clear_line(r->overflow, base, true);
    linebuf_index(r->overflow, base, base + r->capacity - 1);
    index_type *n = before ? &r->num_before : &r->num_after;
    if (*n) (*n)--;
    if (!r->num_before && !r->num_after) r->overflow->bidi_stamped = false;
}
// }}}

static void
ssr_clear_overflow(SmoothScrollRegion *r, bool before) {
    index_type *n = before ? &r->num_before : &r->num_after;
    if (r->horizontal) {
#if BLANK_CHAR != 0
#error This implementation is incorrect for BLANK_CHAR != 0
#endif
        const index_type start = before ? r->capacity - *n : 0;
        for (index_type i = 0; i < ssr_height(r) && *n; i++) {
            CPUCell *c;
            RenderCell *rc;
            ssr_overflow_row_cells(r, before, i, &c, &rc);
            zero_at_ptr_count(c + start, *n);
            zero_at_ptr_count(rc + start, *n);
        }
    } else
        for (index_type i = 0; i < *n; i++) linebuf_clear_line(r->overflow, ssr_slot(r, before, i), true);
    *n = 0;
    if (!r->num_before && !r->num_after) r->overflow->bidi_stamped = false;
}

// Multicell chars {{{
static void
ssr_nuke_overflow_parts(Screen *self, index_type x_start, index_type x_limit, MulticellRows rows, char_type ch) {
    // Remove the parts of a multicell char, whose cells on screen are in the
    // columns [x_start, x_limit) of rows, that are in the overflow buffers of
    // a smooth scroll region. Must be called before the cells of the char on
    // screen are removed.
    if (rows.start < 0) return; // the char extends into the scrollback, which is never the overflow buffer of a region it is in
    // The cells are in a screen buffer temporarily made current, which the regions are not on
    if (self->linebuf != self->smooth_scroll.linebuf) return;
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) {
        SmoothScrollRegion *r = self->smooth_scroll.regions + i;
        if (x_start < r->left || x_limit > r->right) continue;
        if (r->horizontal) {
            const index_type y_start = MAX((index_type)rows.start, r->top), y_limit = MIN((index_type)rows.limit, r->bottom);
            for (index_type y = y_start; y < y_limit; y++) {
                const CPUCell *cp = linebuf_cpu_cells_for_line(self->linebuf, y);
                CPUCell *oc;
                RenderCell *orc;
                if (x_start == r->left && r->num_before && cp[x_start].is_multicell) {
                    const CPUCell edge = cp[x_start];
                    ssr_overflow_row_cells(r, true, y - r->top, &oc, &orc);
                    for (index_type n = 0, cx = edge.x; n < r->num_before && cx > 0; n++, cx--) {
                        const index_type col = r->capacity - 1 - n;
                        if (!continues_multicell_char_horizontally(oc + col, &edge, cx - 1)) break;
                        nuke_in_line(oc, col, col + 1, ch);
                    }
                    linebuf_mark_line_dirty(r->overflow, y - r->top);
                }
                if (x_limit == r->right && r->num_after && cp[x_limit - 1].is_multicell) {
                    const CPUCell edge = cp[x_limit - 1];
                    ssr_overflow_row_cells(r, false, y - r->top, &oc, &orc);
                    for (index_type n = 0, cx = edge.x + 1u; n < r->num_after && cx < mcd_x_limit(&edge); n++, cx++) {
                        if (!continues_multicell_char_horizontally(oc + n, &edge, cx)) break;
                        nuke_in_line(oc, n, n + 1, ch);
                    }
                    linebuf_mark_line_dirty(r->overflow, ssr_height(r) + y - r->top);
                }
            }
            continue;
        }
        const index_type cx = x_start - r->left, cx_limit = x_limit - r->left;
        if ((index_type)rows.start == r->top && r->num_before) {
            const CPUCell edge = linebuf_cpu_cells_for_line(self->linebuf, r->top)[x_start];
            for (index_type n = 0, ry = edge.y; n < r->num_before && ry > 0; n++, ry--) {
                const index_type slot = ssr_slot(r, true, n);
                CPUCell *cells = ssr_overflow_cells(r, slot);
                if (!continues_multicell_char(cells + cx, &edge, ry - 1)) break;
                nuke_in_line(cells, cx, cx_limit, ch);
                linebuf_mark_line_dirty(r->overflow, slot);
            }
        }
        if ((index_type)rows.limit == r->bottom && r->num_after) {
            const CPUCell edge = linebuf_cpu_cells_for_line(self->linebuf, r->bottom - 1)[x_start];
            for (index_type n = 0, ry = edge.y + 1u; n < r->num_after && ry < edge.scale; n++, ry++) {
                const index_type slot = ssr_slot(r, false, n);
                CPUCell *cells = ssr_overflow_cells(r, slot);
                if (!continues_multicell_char(cells + cx, &edge, ry)) break;
                nuke_in_line(cells, cx, cx_limit, ch);
                linebuf_mark_line_dirty(r->overflow, slot);
            }
        }
    }
}

static bool
ssr_char_continues_into_overflow_below(Screen *self, const CPUCell *ref, index_type x, MulticellRows rows) {
    // Whether the multicell char, whose top row is the first of rows on screen
    // and whose cell in column x of it is ref, continues into the overflow
    // buffer below a vertically scrolled smooth scroll region
    if (!self->smooth_scroll.count || self->linebuf != self->smooth_scroll.linebuf || rows.start < 0) return false;
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) {
        SmoothScrollRegion *r = self->smooth_scroll.regions + i;
        if (r->horizontal || !r->num_after || rows.limit != (int)r->bottom || x < r->left || x >= r->right) continue;
        const CPUCell *nearest = ssr_overflow_cells(r, ssr_slot(r, false, 0));
        if (continues_multicell_char(nearest + x - r->left, ref, ref->y + (index_type)(rows.limit - rows.start))) return true;
    }
    return false;
}

static void
ssr_nuke_straddling_chars(Screen *self, SmoothScrollRegion *r) {
    // Remove multicell chars that cross the edges of the rectangle into cells
    // outside it, as moving the cells of the rectangle would tear them. Chars
    // that continue into the overflow buffers or, at the top of the main
    // screen, into the scrollback when it is the overflow buffer, are kept.
    for (index_type y = r->top; y < r->bottom; y++) {
        const CPUCell *cp = linebuf_cpu_cells_for_line(self->linebuf, y);
        if (r->left > 0 && cp[r->left].is_multicell && cp[r->left].x > 0 &&
            continues_multicell_char_horizontally(cp + r->left - 1, cp + r->left, cp[r->left].x - 1))
            nuke_multicell_char_at(self, r->left, y, false);
        cp = linebuf_cpu_cells_for_line(self->linebuf, y);
        const CPUCell *c = cp + r->right - 1;
        if (r->right < self->columns && c->is_multicell && c->x + 1u < mcd_x_limit(c) && continues_multicell_char_horizontally(c + 1, c, c->x + 1))
            nuke_multicell_char_at(self, r->right - 1, y, false);
    }
    if (!self->multiline_chars_used) return;
    // The row above the rectangle is on screen or, at the top of the main screen, in the scrollback
    const int above = (int)r->top - 1;
    const bool has_row_above = !ssr_uses_history(self, r) && (above >= 0 || (self->linebuf == self->main_linebuf && -above <= (int)self->historybuf->count));
    if (has_row_above) {
        for (index_type x = r->left; x < r->right; x++) {
            const CPUCell c = linebuf_cpu_cells_for_line(self->linebuf, r->top)[x];
            if (c.is_multicell && c.y > 0 && continues_multicell_char(range_line_(self, above)->cpu_cells + x, &c, c.y - 1))
                nuke_multicell_char_at(self, x, r->top, false);
        }
    }
    if (r->bottom < self->lines) {
        for (index_type x = r->left; x < r->right; x++) {
            const CPUCell c = linebuf_cpu_cells_for_line(self->linebuf, r->bottom - 1)[x];
            if (c.is_multicell && c.y + 1u < c.scale && continues_multicell_char(linebuf_cpu_cells_for_line(self->linebuf, r->bottom) + x, &c, c.y + 1))
                nuke_multicell_char_at(self, x, r->bottom - 1, false);
        }
    }
}

static void
ssr_nuke_chars_next_to_blank_row(Screen *self, SmoothScrollRegion *r, index_type y, bool blank_row_is_below) {
    // A blank row has come in next to row y of the rectangle, tearing the multiline chars that extend into it
    if (!self->multiline_chars_used || y < r->top || y >= r->bottom) return;
    for (index_type x = r->left; x < r->right; x++) {
        const CPUCell c = linebuf_cpu_cells_for_line(self->linebuf, y)[x];
        if (c.is_multicell && (blank_row_is_below ? c.y + 1u < c.scale : c.y > 0)) nuke_multicell_char_at(self, x, y, false);
    }
}

static void
ssr_nuke_chars_next_to_blank_column(Screen *self, SmoothScrollRegion *r, index_type x, bool blank_column_is_right) {
    // A blank column has come in next to column x of the rectangle, tearing the multicell chars that extend into it
    if (x < r->left || x >= r->right) return;
    for (index_type y = r->top; y < r->bottom; y++) {
        const CPUCell c = linebuf_cpu_cells_for_line(self->linebuf, y)[x];
        if (c.is_multicell && (blank_column_is_right ? c.x + 1u < mcd_x_limit(&c) : c.x > 0)) nuke_multicell_char_at(self, x, y, false);
    }
}

static void
ssr_nuke_chars_continuing_into_overflow(Screen *self, SmoothScrollRegion *r, bool before) {
    // The overflow buffer is about to be discarded, tearing the multicell chars at the edge of the rectangle that continue into it
    if (!(before ? r->num_before : r->num_after)) return;
    if (r->horizontal) {
        const index_type x = before ? r->left : r->right - 1, col = ssr_nearest_column(r, before);
        for (index_type y = r->top; y < r->bottom; y++) {
            const CPUCell c = linebuf_cpu_cells_for_line(self->linebuf, y)[x];
            if (!c.is_multicell) continue;
            CPUCell *oc;
            RenderCell *orc;
            ssr_overflow_row_cells(r, before, y - r->top, &oc, &orc);
            if (before ? (c.x > 0 && continues_multicell_char_horizontally(oc + col, &c, c.x - 1))
                       : (c.x + 1u < mcd_x_limit(&c) && continues_multicell_char_horizontally(oc + col, &c, c.x + 1)))
                nuke_multicell_char_at(self, x, y, false);
        }
        return;
    }
    if (!self->multiline_chars_used) return;
    const index_type y = before ? r->top : r->bottom - 1;
    const CPUCell *nearest = ssr_overflow_cells(r, ssr_slot(r, before, 0));
    for (index_type x = r->left; x < r->right; x++) {
        const CPUCell c = linebuf_cpu_cells_for_line(self->linebuf, y)[x];
        if (!c.is_multicell) continue;
        if (before ? (c.y > 0 && continues_multicell_char(nearest + x - r->left, &c, c.y - 1))
                   : (c.y + 1u < c.scale && continues_multicell_char(nearest + x - r->left, &c, c.y + 1)))
            nuke_multicell_char_at(self, x, y, false);
    }
}
// }}}

static void
move_selection_by_one_column(Selection *s, bool left) {
    // Move the selection with its text when its cells move left or right by one column
#define M(x)        \
    if (left) {     \
        if (x) x--; \
    } else x++;
    M(s->start.x);
    M(s->end.x);
    M(s->input_start.x);
    M(s->input_current.x);
    M(s->initial_extent.start.x);
    M(s->initial_extent.end.x);
#undef M
}

static void
ssr_move_selections(Screen *self, Selections *selections, const SmoothScrollRegion *r, bool forward, bool via_history) {
    // Selections inside the rectangle move with its cells, selections that
    // cross its edges or move out of it into an overflow buffer are cleared.
    // When the scrollback moves with the rows of the rectangle, via_history,
    // it is treated as part of the rectangle, as for scrolling with SU.
    const int top = via_history ? INT_MIN : (int)r->top;
    for (size_t i = 0; i < selections->count; i++) {
        Selection *s = selections->items + i;
        if (is_selection_empty(s)) continue;
        const int start = (int)s->start.y - (int)s->start_scrolled_by, end = (int)s->end.y - (int)s->end_scrolled_by;
        const int stop = MIN(start, end), sbottom = MAX(start, end);
        index_type xmin = 0, xmax = self->columns - 1;
        if (start == end || s->rectangle_select) {
            xmin = MIN(s->start.x, s->end.x);
            xmax = MAX(s->start.x, s->end.x);
        }
        if (sbottom < top || stop >= (int)r->bottom || xmax < r->left || xmin >= r->right) continue;
        const bool inside = stop >= top && sbottom < (int)r->bottom && xmin >= r->left && xmax < r->right;
        bool moves_out;
        if (r->horizontal) moves_out = forward ? xmin == r->left : xmax == r->right - 1;
        else moves_out = forward ? (stop == (int)r->top && !via_history) : sbottom == (int)r->bottom - 1;
        if (!inside || moves_out) {
            clear_selection(selections);
            return;
        }
        if (r->horizontal) move_selection_by_one_column(s, forward);
        else move_selection_by_one_row(self, s, forward);
    }
}

static void
ssr_move_images(Screen *self, SmoothScrollRegion *r, bool forward, bool via_history) {
    // via_history is true when the scrollback moves with the rows of the rectangle
    if (LIKELY(!grman_has_any_images(self->grman))) return;
    const index_type before_edge = r->horizontal ? r->left : r->top, after_edge = r->horizontal ? r->right : r->bottom;
    const SmoothScrollImageData d = {
        .region_id = r->id,
        .amt = forward ? -1 : 1,
        .horizontal = r->horizontal,
        .left = r->left,
        .right = r->right,
        .top = r->top,
        .bottom = r->bottom,
        // When the scrollback is the overflow buffer images in its last line are drawn with the region
        .before_limit = via_history ? (int32_t)r->top - 1 : (int32_t)before_edge - (int32_t)r->capacity,
        .after_limit = (int32_t)(after_edge + r->capacity),
        .history_limit = -(int32_t)self->historybuf->ynum,
        .uses_history = via_history,
    };
    grman_smooth_scroll_images(self->grman, &d, self->cell_size);
}

static void
ssr_shift_by_one_row(Screen *self, SmoothScrollRegion *r, bool up) {
    // Move the cells of the rectangle by one row, up when up is true
    const bool full_width = ssr_is_full_width(self, r), uses_history = ssr_uses_history(self, r);
    // Whether the scrollback moves with the rows of the rectangle, with a row
    // moving into it or being taken back from it. Only rows that moved into it
    // from the rectangle are taken back, so that scrolling back never takes
    // lines that were in the scrollback before, for example, the output of
    // commands run before the program.
    const bool via_history = uses_history && (up || (r->pushed_to_history && self->historybuf->count));
    const index_type top = r->top, last = r->bottom - 1;
    ssr_nuke_straddling_chars(self, r);
    if (UNLIKELY(self->selections.count)) ssr_move_selections(self, &self->selections, r, up, via_history);
    if (UNLIKELY(self->url_ranges.count || self->url_ranges.in_progress)) clear_selection(&self->url_ranges);
    if (full_width) last_visited_prompt_index(self, top, last, up, via_history);
    bool entered_blank;
    if (up) {
        // The top row leaves, a row enters at the bottom
        if (full_width) {
            if (!via_history) ssr_copy_row_to_slot(self, r, top, ssr_push_slot(r, true));
            bidi_index_up_seams(self, top, last, via_history);
            linebuf_index(self->linebuf, top, last);
            // The row that left is now at the bottom
            if (via_history) {
                linebuf_init_line(self->linebuf, last);
                historybuf_add_line(self->historybuf, self->linebuf->line, &self->as_ansi_buf);
                // The scrollback drops its oldest line when full
                r->pushed_to_history = MIN(r->pushed_to_history + 1, self->historybuf->ynum);
                // Keep a scrolled back viewport anchored on the same content
                if (self->scrolled_by) {
                    if (self->scrolled_by < self->historybuf->count) self->scrolled_by++;
                    if (self->scrolled_by >= self->historybuf->count && self->pixel_scroll_offset_y) {
                        reset_pixel_scroll(self, 0);
                        self->scroll_changed = true;
                    }
                }
            }
            // The rows moved intact, with their render data, as when scrolling
            // with SU, so they do not need to be rendered again
        } else {
            ssr_copy_row_to_slot(self, r, top, ssr_push_slot(r, true));
            for (index_type y = top; y < last; y++) ssr_copy_row_to_row(self, r, y + 1, y);
        }
        entered_blank = !r->num_after;
        if (entered_blank) ssr_blank_row(self, r, last);
        else {
            ssr_copy_slot_to_row(self, r, ssr_slot(r, false, 0), last);
            ssr_pop_slot(r, false);
        }
        if (entered_blank && last > top) ssr_nuke_chars_next_to_blank_row(self, r, last - 1, true);
    } else {
        // The bottom row leaves, a row enters at the top
        ssr_copy_row_to_slot(self, r, last, ssr_push_slot(r, false));
        if (full_width) {
            linebuf_reverse_index(self->linebuf, top, last);
            bidi_index_down_seams(self, top, last);
        } else {
            for (index_type y = last; y > top; y--) ssr_copy_row_to_row(self, r, y - 1, y);
        }
        entered_blank = true;
        if (via_history) {
            if (historybuf_pop_line(self->historybuf, self->alt_linebuf->line)) {
                r->pushed_to_history--;
                linebuf_copy_line_to(self->main_linebuf, self->alt_linebuf->line, top);
                bidi_note_line_from_history(self, top);
                ssr_mark_row_dirty(self, top);
                // Keep a scrolled back viewport anchored on the same content
                if (self->scrolled_by) self->scrolled_by--;
                entered_blank = false;
            }
        } else if (r->num_before) {
            ssr_copy_slot_to_row(self, r, ssr_slot(r, true, 0), top);
            ssr_pop_slot(r, true);
            entered_blank = false;
        }
        if (entered_blank) ssr_blank_row(self, r, top);
        if (entered_blank && last > top) ssr_nuke_chars_next_to_blank_row(self, r, top + 1, false);
    }
    ssr_move_images(self, r, up, via_history);
    if (UNLIKELY(self->linebuf->bidi_stamped)) {
        self->linebuf->bidi_maybe_unstamp = true;
        bidi_layout_moved(self);
    }
    self->is_dirty = true;
}

static void bidi_line_gets_text(Screen *self, index_type y);

// The walk recomputes the bit of a dirty row from the cells it holds, which left out those shifted onto the overflow
static void
ssr_bidi_cell_entered(Screen *self, index_type y, const CPUCell *c) {
    LineAttrs *a = self->linebuf->line_attrs + y;
    if (!a->bidi_may_reorder) a->bidi_may_reorder = bidi_cells_may_reorder(c, 1, self->text_cache);
}

static void
ssr_shift_by_one_column(Screen *self, SmoothScrollRegion *r, bool left) {
    // Move the cells of the rectangle by one column, left when left is true
#if BLANK_CHAR != 0
#error This implementation is incorrect for BLANK_CHAR != 0
#endif
    ssr_nuke_straddling_chars(self, r);
    if (UNLIKELY(self->selections.count)) ssr_move_selections(self, &self->selections, r, left, false);
    if (UNLIKELY(self->url_ranges.count || self->url_ranges.in_progress)) clear_selection(&self->url_ranges);
    const index_type w = ssr_width(r), k = r->capacity, first = r->left, last = r->right - 1;
    const bool entered_blank = left ? !r->num_after : !r->num_before;
    const bool stamped = self->linebuf->bidi_stamped;
    for (index_type i = 0; i < ssr_height(r); i++) {
        const index_type y = r->top + i;
        CPUCell *c, *cb, *ca;
        RenderCell *rc, *rcb, *rca;
        linebuf_init_cells(self->linebuf, y, &c, &rc);
        ssr_overflow_row_cells(r, true, i, &cb, &rcb);
        ssr_overflow_row_cells(r, false, i, &ca, &rca);
        if (left) {
            // The leftmost column leaves, onto the overflow buffer on the left, whose nearest column is its last
            if (k > 1) {
                memmove(cb, cb + 1, (k - 1) * sizeof(cb[0]));
                memmove(rcb, rcb + 1, (k - 1) * sizeof(rcb[0]));
            }
            cb[k - 1] = c[first], rcb[k - 1] = rc[first];
            memmove(c + first, c + first + 1, (w - 1) * sizeof(c[0]));
            memmove(rc + first, rc + first + 1, (w - 1) * sizeof(rc[0]));
            // A column enters on the right, from the overflow buffer on the right, whose nearest column is its first
            if (entered_blank) {
                zero_at_ptr(c + last);
                zero_at_ptr(rc + last);
            } else {
                if (UNLIKELY(stamped) && ca[0].ch_and_idx) bidi_line_gets_text(self, y);
                c[last] = ca[0], rc[last] = rca[0];
                if (UNLIKELY(stamped)) ssr_bidi_cell_entered(self, y, c + last);
                if (k > 1) {
                    memmove(ca, ca + 1, (k - 1) * sizeof(ca[0]));
                    memmove(rca, rca + 1, (k - 1) * sizeof(rca[0]));
                }
                zero_at_ptr(ca + k - 1);
                zero_at_ptr(rca + k - 1);
            }
        } else {
            // The rightmost column leaves, onto the overflow buffer on the right
            if (k > 1) {
                memmove(ca + 1, ca, (k - 1) * sizeof(ca[0]));
                memmove(rca + 1, rca, (k - 1) * sizeof(rca[0]));
            }
            ca[0] = c[last], rca[0] = rc[last];
            memmove(c + first + 1, c + first, (w - 1) * sizeof(c[0]));
            memmove(rc + first + 1, rc + first, (w - 1) * sizeof(rc[0]));
            // A column enters on the left, from the overflow buffer on the left
            if (entered_blank) {
                zero_at_ptr(c + first);
                zero_at_ptr(rc + first);
            } else {
                if (UNLIKELY(stamped) && cb[k - 1].ch_and_idx) bidi_line_gets_text(self, y);
                c[first] = cb[k - 1], rc[first] = rcb[k - 1];
                if (UNLIKELY(stamped)) ssr_bidi_cell_entered(self, y, c + first);
                if (k > 1) {
                    memmove(cb + 1, cb, (k - 1) * sizeof(cb[0]));
                    memmove(rcb + 1, rcb, (k - 1) * sizeof(rcb[0]));
                }
                zero_at_ptr(cb);
                zero_at_ptr(rcb);
            }
        }
        const bool has_image_placeholders = self->linebuf->line_attrs[y].has_image_placeholders;
        LineAttrs *ab = r->overflow->line_attrs + i, *aa = r->overflow->line_attrs + ssr_height(r) + i;
        ab->has_image_placeholders |= has_image_placeholders;
        aa->has_image_placeholders |= has_image_placeholders;
        ab->has_dirty_text = true;
        aa->has_dirty_text = true;
        ssr_mark_row_dirty(self, y);
    }
    index_type *pushed = left ? &r->num_before : &r->num_after, *popped = left ? &r->num_after : &r->num_before;
    if (*pushed < k) (*pushed)++;
    if (*popped) (*popped)--;
    if (entered_blank && w > 1) ssr_nuke_chars_next_to_blank_column(self, r, left ? last - 1 : first + 1, left);
    ssr_move_images(self, r, left, false);
    if (UNLIKELY(stamped)) bidi_layout_moved(self);
    self->is_dirty = true;
}

static void
ssr_release_images(Screen *self, SmoothScrollRegion *r, bool clip_before) {
    if (UNLIKELY(grman_has_any_images(self->grman)))
        grman_smooth_scroll_release_images(self->grman, r->id, r->left, r->top, r->right, r->bottom, r->horizontal, clip_before, self->cell_size);
}

static void
ssr_free(SmoothScrollRegion *r) {
    Py_CLEAR(r->overflow);
    zero_at_ptr(r);
}

static void
ssr_discard_overflow(Screen *self, SmoothScrollRegion *r) {
    // The rows (columns) in the rectangle no longer adjoin the rows (columns)
    // in the overflow buffers, so discard them and render the rectangle unshifted
    ssr_nuke_chars_continuing_into_overflow(self, r, true);
    ssr_nuke_chars_continuing_into_overflow(self, r, false);
    ssr_clear_overflow(r, true);
    ssr_clear_overflow(r, false);
    ssr_release_images(self, r, !ssr_uses_history(self, r));
    if (r->offset) {
        r->offset = 0;
        self->smooth_scroll.offsets_changed = true;
    }
}

static void
ssr_dirty_line_graphics(Screen *self, const SmoothScrollRegion *r) {
    // Images displayed using Unicode placeholders are split at the edges of
    // regions, see screen_render_line_graphics(), so render the lines with
    // placeholders again. Their cell images are replaced when they are
    // rendered, until then they move with the cells of the region.
    for (index_type y = r->top; y < r->bottom; y++) {
        if (self->linebuf->line_attrs[y].has_image_placeholders) {
            linebuf_mark_line_dirty(self->linebuf, y);
            self->is_dirty = true;
        }
    }
}

static void
ssr_dirty_bidi_rows(Screen *self, const SmoothScrollRegion *r) {
    // The cells of a horizontally scrolled region are not laid out by bidi,
    // and a wide char across the edge of a narrower region is fixed in its
    // columns, so the rows it covers are laid out again when it comes or goes
    if (!r->horizontal && ssr_is_full_width(self, r)) return;
    for (index_type y = r->top; y < r->bottom; y++) linebuf_mark_line_dirty(self->linebuf, y);
    self->is_dirty = true;
}

static void
ssr_remove_at(Screen *self, unsigned idx) {
    SmoothScrollRegion *r = self->smooth_scroll.regions + idx;
    self->smooth_scroll.offsets_changed = true;
    ssr_discard_overflow(self, r);
    ssr_dirty_line_graphics(self, r);
    if (self->bidi_maps && !ssr_is_full_width(self, r)) bidi_maps_edges_changed(self->bidi_maps);
    bidi_layout_moved(self);
    if (UNLIKELY(self->linebuf->bidi_stamped)) {
        self->linebuf->bidi_maybe_unstamp = true;
        ssr_dirty_bidi_rows(self, r);
    }
    ssr_free(r);
    SmoothScroll *ss = &self->smooth_scroll;
    ss->count--;
    if (idx < ss->count) {
        memmove(ss->regions + idx, ss->regions + idx + 1, (ss->count - idx) * sizeof(ss->regions[0]));
        zero_at_ptr(ss->regions + ss->count);
    }
}

void
screen_smooth_scroll_remove_all(Screen *self) {
    while (self->smooth_scroll.count) ssr_remove_at(self, self->smooth_scroll.count - 1);
}

bool
screen_smooth_scroll_remove(Screen *self, uint32_t id) {
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) {
        if (self->smooth_scroll.regions[i].id == id) {
            ssr_remove_at(self, i);
            return true;
        }
    }
    return false;
}

bool
screen_smooth_scroll_define(
    Screen *self,
    uint32_t id,
    index_type left,
    index_type top,
    index_type right,
    index_type bottom,
    index_type capacity,
    bool private_overflow,
    bool horizontal) {
    if (!id || left >= right || top >= bottom || right > self->columns || bottom > self->lines) return false;
    if (!capacity || capacity > (horizontal ? right - left : bottom - top)) return false;
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) {
        const SmoothScrollRegion *q = self->smooth_scroll.regions + i;
        if (q->id != id && left < q->right && q->left < right && top < q->bottom && q->top < bottom) return false;
    }
    screen_smooth_scroll_remove(self, id);
    if (self->smooth_scroll.count >= MAX_SMOOTH_SCROLL_REGIONS) return false;
    LineBuf *overflow =
        horizontal ? alloc_linebuf(2 * (bottom - top), capacity, self->text_cache) : alloc_linebuf(2 * capacity, right - left, self->text_cache);
    if (!overflow) {
        PyErr_Clear();
        return false;
    }
    self->smooth_scroll.linebuf = self->linebuf;
    SmoothScrollRegion *r = self->smooth_scroll.regions + self->smooth_scroll.count++;
    *r = (SmoothScrollRegion){
        .id = id,
        .left = left,
        .top = top,
        .right = right,
        .bottom = bottom,
        .capacity = capacity,
        .horizontal = horizontal,
        .private_overflow = private_overflow,
        .overflow = overflow};
    ssr_dirty_line_graphics(self, r);
    if (self->bidi_maps && !ssr_is_full_width(self, r)) bidi_maps_edges_changed(self->bidi_maps);
    bidi_layout_moved(self);
    if (UNLIKELY(self->linebuf->bidi_stamped)) {
        self->linebuf->bidi_maybe_unstamp = true;
        ssr_dirty_bidi_rows(self, r);
    }
    return true;
}

bool
screen_smooth_scroll(Screen *self, uint32_t id, int delta_pixels, int *cells_shifted) {
    // Scroll the region by delta_pixels, positive values move the content up
    // (left), that is, towards the end of the content, as for scroll wheel
    // events. On return cells_shifted is the number of rows (columns) by which
    // the cells were moved, positive for up (left). The rows (columns) that
    // entered the rectangle at the edge in the direction of the scroll are the
    // ones the application must draw.
    *cells_shifted = 0;
    SmoothScrollRegion *r = ssr_for_id(self, id);
    if (!r) return false;
    const int h = (int)MAX(1u, r->horizontal ? self->cell_size.width : self->cell_size.height);
    if (!delta_pixels) return true;
    // offset is the position of the first row (column) of the rectangle
    // relative to its top (left) edge. Moving the content by delta moves it
    // to offset - delta. The row (column) entering in the direction of the
    // scroll must be in the rectangle, so for scrolls forward the offset must
    // be in [0, h) and for scrolls backward in (-h, 0].
    const int64_t moved = (int64_t)r->offset - delta_pixels;
    int64_t shift;
    if (delta_pixels > 0) shift = moved < 0 ? (-moved + h - 1) / h : 0;
    else shift = moved > 0 ? -((moved + h - 1) / h) : 0;
    const int new_offset = (int)(moved + shift * h);
    if (new_offset != r->offset) {
        r->offset = new_offset;
        self->smooth_scroll.offsets_changed = true;
        // Images moving with the region are drawn shifted by the offset
        if (grman_has_any_images(self->grman)) grman_mark_layers_dirty(self->grman);
    }
    *cells_shifted = (int)MAX((int64_t)INT_MIN, MIN((int64_t)INT_MAX, shift));
    // Shifting by more than the rows (columns) in the rectangle and the
    // overflow buffer only moves blank ones. When the scrollback is the
    // overflow buffer it would fill it with blank rows, so stop when every row
    // of the rectangle has moved into it.
    const bool forward = shift > 0;
    const int64_t length = r->horizontal ? ssr_width(r) : ssr_height(r);
    const int64_t limit = (forward && ssr_uses_history(self, r)) ? length : length + r->capacity;
    for (int64_t n = MIN(forward ? shift : -shift, limit); n > 0; n--) {
        if (r->horizontal) ssr_shift_by_one_column(self, r, forward);
        else ssr_shift_by_one_row(self, r, forward);
    }
    self->is_dirty = true;
    return true;
}

static void
ssr_lines_moved(Screen *self, index_type top, index_type bottom, bool up, bool via_history) {
    // The lines [top, bottom] of the screen were scrolled by one line, or
    // lines were inserted or deleted in them. Regions whose rows were moved no
    // longer adjoin their overflow buffers, except when the lines are moved
    // up into the scrollback and it is the overflow buffer above the region,
    // in which case only the rows below the region are discarded.
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) {
        SmoothScrollRegion *r = self->smooth_scroll.regions + i;
        if (!ssr_rows_intersect(r, top, bottom)) continue;
        if (up && via_history && top == 0 && bottom + 1 >= r->bottom && ssr_uses_history(self, r)) {
            // The top row of the rectangle moves into the scrollback
            r->pushed_to_history = MIN(r->pushed_to_history + 1, self->historybuf->ynum);
            ssr_nuke_chars_continuing_into_overflow(self, r, false);
            ssr_clear_overflow(r, false);
            ssr_release_images(self, r, false);
            if (r->offset < 0) {
                r->offset = 0;
                self->smooth_scroll.offsets_changed = true;
            }
        } else ssr_discard_overflow(self, r);
    }
}

static void
ssr_row_cells_moved(Screen *self, index_type x, index_type y) {
    // The cells of row y from column x to the end of the row were moved
    // sideways, by inserting or deleting chars, so horizontally scrolled
    // regions containing them no longer adjoin the columns in their overflow buffers
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) {
        SmoothScrollRegion *r = self->smooth_scroll.regions + i;
        if (r->horizontal && r->top <= y && y < r->bottom && x < r->right) ssr_discard_overflow(self, r);
    }
}

static void
ssr_screen_erased(Screen *self) {
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) ssr_discard_overflow(self, self->smooth_scroll.regions + i);
}

unsigned
screen_bidi_span_edges(const Screen *self, index_type y, index_type *edges) {
    unsigned n = 0;
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) {
        const SmoothScrollRegion *r = self->smooth_scroll.regions + i;
        if (y < r->top || y >= r->bottom || ssr_is_full_width(self, r)) continue;
        const index_type cut[2] = {r->left, r->right};
        for (unsigned c = 0; c < 2; c++) {
            if (!cut[c] || cut[c] >= self->columns) continue;
            unsigned at = n;
            for (; at && edges[at - 1] > cut[c]; at--) edges[at] = edges[at - 1];
            edges[at] = cut[c];
            n++;
        }
    }
    return n;
}

void
screen_bidi_fixed_columns(const Screen *self, index_type y, BidiFixedColumns *ans) {
    ans->count = 0;
    ans->num_edges = screen_bidi_span_edges(self, y, ans->edges);
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) {
        const SmoothScrollRegion *r = self->smooth_scroll.regions + i;
        if (!r->horizontal || y < r->top || y >= r->bottom) continue;
        // Regions do not overlap
        unsigned at = ans->count++;
        for (; at && ans->at[2 * at - 2] > r->left; at--) {
            ans->at[2 * at] = ans->at[2 * at - 2];
            ans->at[2 * at + 1] = ans->at[2 * at - 1];
        }
        ans->at[2 * at] = r->left;
        ans->at[2 * at + 1] = r->right;
    }
}

bool
screen_bidi_strip_shows_recorded_history(const Screen *self) {
    if (!self->historybuf->bidi_stamped || !self->historybuf->count || historybuf_attrs(self->historybuf, 0)->bidi_stamp == BIDI_STAMP_NONE) return false;
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) {
        const SmoothScrollRegion *r = self->smooth_scroll.regions + i;
        if (r->offset && ssr_uses_history(self, r)) return true;
    }
    return false;
}

// Rendering {{{
static unsigned
ssr_live_render_regions(Screen *self, SmoothScrollRenderRegion *ans) {
    // The regions as they should be rendered now. Regions are shifted only
    // when the screen is not scrolled back, as their rectangles are in screen
    // coordinates. When it is scrolled back, they are only used to clip the
    // images moving with them to their rectangles.
    const int y_offset = (int)(self->scrolled_by * self->cell_size.height) + (live_pixel_scroll_enabled(self) ? (int)self->pixel_scroll_offset_y : 0);
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) {
        const SmoothScrollRegion *r = self->smooth_scroll.regions + i;
        ans[i] = (SmoothScrollRenderRegion){
            .id = r->id,
            .left = r->left,
            .top = r->top,
            .width = ssr_width(r),
            .height = ssr_height(r),
            .offset = y_offset ? 0 : r->offset,
            .y_offset = y_offset,
            .horizontal = r->horizontal,
            .uses_history = ssr_uses_history(self, r)};
    }
    return self->smooth_scroll.count;
}

static bool screen_has_marker(Screen *self);
static int paused_snapshot_row_offset(const Screen *self);

static bool
ssr_render_regions_equal(const SmoothScrollRenderRegion *a, const SmoothScrollRenderRegion *b) {
    return a->id == b->id && a->left == b->left && a->top == b->top && a->width == b->width && a->height == b->height && a->offset == b->offset &&
           a->y_offset == b->y_offset && a->base_cell == b->base_cell && a->horizontal == b->horizontal && a->uses_history == b->uses_history;
}

bool
screen_prepare_smooth_scroll_render(Screen *self) {
    // Compute how the smooth scroll regions are rendered in this frame,
    // returns true if that is different from the previous frame
    SmoothScrollRender *sr = &self->smooth_scroll_render;
    if (!sr->count && !self->smooth_scroll.count && !self->paused_rendering.smooth_scroll.count) return false;
    const SmoothScrollRender prev = *sr;
    if (self->paused_rendering.expires_at) {
        sr->count = self->paused_rendering.smooth_scroll.count;
        memcpy(sr->regions, self->paused_rendering.smooth_scroll.regions, sr->count * sizeof(sr->regions[0]));
    } else sr->count = ssr_live_render_regions(self, sr->regions);
    sr->num_strip_cells = 0;
    const unsigned base = render_lines_for_screen(self) * self->columns;
    for (unsigned i = 0; i < sr->count; i++) {
        SmoothScrollRenderRegion *rr = sr->regions + i;
        rr->base_cell = 0;
        if (smooth_scroll_render_region_is_shifted(rr)) {
            rr->base_cell = base + sr->num_strip_cells;
            sr->num_strip_cells += smooth_scroll_render_region_strip_height(rr) * smooth_scroll_render_region_strip_width(rr);
        }
    }
    bool changed = self->smooth_scroll.offsets_changed || prev.count != sr->count || prev.num_strip_cells != sr->num_strip_cells;
    for (unsigned i = 0; i < sr->count && !changed; i++) changed = !ssr_render_regions_equal(prev.regions + i, sr->regions + i);
    self->smooth_scroll.offsets_changed = false;
    return changed;
}

static void
ssr_render_line_if_dirty(Screen *self, Line *line, FONTS_DATA_HANDLE fonts_data, const Cursor *cursor, BidiMaps *b, bool fixed) {
    // Render a line that is drawn only in the strip of a region. It is never the cursor row. In a frame with bidi maps it is
    // rendered at the levels bidi_strip_line_levels() gives, which are stored for the order of its strip row.
    if (!line->attrs.has_dirty_text) return;
    const uint8_t *levels = UNLIKELY(b) ? bidi_strip_line_levels(b, line, fixed) : NULL;
    render_line(fonts_data, line, self->lines, (Cursor *)cursor, self->disable_ligatures, self->lc, levels);
    if (UNLIKELY(self->bidi_maps)) bidi_store_line_levels(line, levels);
    if (screen_has_marker(self)) mark_text_in_line(self->marker, line, &self->as_ansi_buf);
}

static void
ssr_render_overflow_line(Screen *self, SmoothScrollRegion *r, index_type y, Line *line, FONTS_DATA_HANDLE fonts_data, const Cursor *cursor, BidiMaps *b) {
    linebuf_init_line_at(r->overflow, y, line);
    ssr_render_line_if_dirty(self, line, fonts_data, cursor, b, false);
    linebuf_mark_line_clean(r->overflow, y);
}

static void
ssr_write_strip_cells_in_order(BidiMaps *b, const Line *line, index_type x, index_type width, CellGPUData *dest) {
    // The cells in the order the screen shows them, see bidi_row_order()
    const uint16_t *v2l = bidi_span_order(b, line->render_cells + x, width);
    if (v2l) cells_for_gpu_permuted(line->cpu_cells + x, line->render_cells + x, v2l, width, dest);
    else cells_for_gpu(line->cpu_cells + x, line->render_cells + x, width, dest);
}

static void
ssr_write_strip_cells(BidiMaps *b, const Line *line, index_type x, index_type width, CellGPUData *dest) {
    if (!line) memset(dest, 0, width * sizeof(dest[0]));
    else if (UNLIKELY(b)) ssr_write_strip_cells_in_order(b, line, x, width, dest);
    else cells_for_gpu(line->cpu_cells + x, line->render_cells + x, width, dest);
}

static void
ssr_update_strip_cell_data(Screen *self, uint8_t *address, FONTS_DATA_HANDLE fonts_data, BidiMaps *b) {
    // Write the cells of the strips of the shifted regions, see SmoothScrollRenderRegion
    const SmoothScrollRender *sr = &self->smooth_scroll_render;
    const bool paused = self->paused_rendering.expires_at != 0;
    const Cursor *cursor = paused ? &self->paused_rendering.cursor : self->cursor;
    LineBuf *lb = paused ? self->paused_rendering.linebuf : self->linebuf;
    const index_type row_offset = paused ? (index_type)paused_snapshot_row_offset(self) : 0;
    Line line = {.text_cache = self->text_cache};
    for (unsigned i = 0; i < sr->count; i++) {
        const SmoothScrollRenderRegion *rr = sr->regions + i;
        if (!smooth_scroll_render_region_is_shifted(rr)) continue;
        SmoothScrollRegion *r = paused ? self->paused_rendering.smooth_scroll.copies + i : ssr_for_id(self, rr->id);
        if (!r || !r->overflow) continue;
        CellGPUData *dest = (CellGPUData *)address + rr->base_cell;
        const index_type w = rr->width, sw = smooth_scroll_render_region_strip_width(rr);
        if (rr->horizontal) {
            for (index_type y = 0; y < rr->height; y++) {
                CellGPUData *row = dest + (size_t)y * sw;
                for (int edge = 0; edge < 2; edge++) {
                    const bool before = edge == 0;
                    const index_type n = before ? r->num_before : r->num_after;
                    ssr_render_overflow_line(self, r, before ? y : rr->height + y, &line, fonts_data, cursor, NULL);
                    ssr_write_strip_cells(b, n ? &line : NULL, ssr_nearest_column(r, before), 1, row + (before ? 0 : w + 1));
                }
                linebuf_init_line_at(lb, rr->top + y + row_offset, &line);
                ssr_write_strip_cells(b, &line, rr->left, w, row + 1);
            }
            continue;
        }
        for (int edge = 0; edge < 2; edge++) {
            const bool before = edge == 0;
            CellGPUData *row = dest + (before ? 0 : (size_t)(rr->height + 1) * w);
            const Line *lp = NULL;
            index_type x = 0;
            if (before && (paused ? self->paused_rendering.smooth_scroll.history_row_region == i + 1 : ssr_uses_history(self, r))) {
                if (paused) {
                    LineBuf *hr = self->paused_rendering.smooth_scroll.history_row;
                    linebuf_init_line_at(hr, 0, &line);
                    ssr_render_line_if_dirty(self, &line, fonts_data, cursor, b, !self->paused_rendering.pixel_scroll);
                    linebuf_mark_line_clean(hr, 0);
                    lp = &line;
                } else if (self->historybuf->count) {
                    if (historybuf_init_line_for_render(self->historybuf, 0, &line, render_lines_for_screen(self))) line.attrs.has_dirty_text = true;
                    line.xnum = self->columns;
                    // With pixel scrolling the line is on view, rendered at its levels. Without, it is drawn as with bidi mode
                    // off and stays dirty, so that a frame showing it on view does not take those levels as its own.
                    const bool fixed = !pixel_scroll_enabled(self);
                    ssr_render_line_if_dirty(self, &line, fonts_data, cursor, b, fixed);
                    if (UNLIKELY(b) && fixed) historybuf_mark_line_dirty(self->historybuf, 0);
                    else historybuf_mark_line_clean(self->historybuf, 0);
                    lp = &line;
                }
                x = rr->left;
            } else if (before ? r->num_before : r->num_after) {
                ssr_render_overflow_line(self, r, ssr_slot(r, before, 0), &line, fonts_data, cursor, b);
                lp = &line;
            }
            ssr_write_strip_cells(b, lp, x, w, row);
        }
        for (index_type y = 0; y < rr->height; y++) {
            linebuf_init_line_at(lb, rr->top + y + row_offset, &line);
            ssr_write_strip_cells(b, &line, rr->left, w, dest + (size_t)(y + 1) * w);
        }
    }
}

static void
ssr_copy_strip_row_selection(
    const Screen *self, const BidiMaps *b, const uint8_t *screen_data, const SmoothScrollRenderRegion *rr, index_type r, uint8_t *dest, size_t stride) {
    const uint8_t *src = screen_data + (size_t)r * self->columns * stride;
    if (b && b->active[r]) bidi_copy_row_bytes(b->v2l + (size_t)r * b->cols + rr->left, rr->width, src, dest, stride);
    else memcpy(dest, src + (size_t)rr->left * stride, (size_t)rr->width * stride);
}

static void
ssr_write_strip_selection_data(Screen *self, const BidiMaps *b, const uint8_t *screen_data, uint8_t *address, size_t stride) {
    // The selection data of the strips of the shifted regions, copied from
    // the data of the cells of the screen, which is in logical order. The rows
    // (columns) outside the rectangles are never selected. With maps b, the
    // cells of a reordered row are in the order the screen shows them, as the
    // strip's cells are: a region narrower than the screen is a span of its
    // own and the columns of a horizontal one keep their places.
    const SmoothScrollRender *sr = &self->smooth_scroll_render;
    const index_type row_offset = pixel_scroll_enabled(self);
    const size_t first_strip_cell = (size_t)render_lines_for_screen(self) * self->columns;
    for (unsigned i = 0; i < sr->count; i++) {
        const SmoothScrollRenderRegion *rr = sr->regions + i;
        if (!smooth_scroll_render_region_is_shifted(rr)) continue;
        uint8_t *dest = address + (rr->base_cell - first_strip_cell) * stride;
        const size_t row_sz = (size_t)rr->width * stride;
#define COPY_ROW(y, d) ssr_copy_strip_row_selection(self, b, screen_data, rr, rr->top + (y) + row_offset, d, stride)
        if (rr->horizontal) {
            for (index_type y = 0; y < rr->height; y++) {
                memset(dest, 0, stride);
                COPY_ROW(y, dest + stride);
                memset(dest + stride + row_sz, 0, stride);
                dest += row_sz + 2 * stride;
            }
            continue;
        }
        memset(dest, 0, row_sz);
        dest += row_sz;
        for (index_type y = 0; y < rr->height; y++, dest += row_sz) COPY_ROW(y, dest);
        memset(dest, 0, row_sz);
#undef COPY_ROW
    }
}

static LineBuf *
ssr_copy_linebuf(LineBuf *src, LineBuf *dest, TextCache *tc) {
    // Copy src into dest, which is reallocated if its size is different, returns NULL on failure
    if (!dest || dest->xnum != src->xnum || dest->ynum != src->ynum) {
        Py_CLEAR(dest);
        dest = alloc_linebuf(src->ynum, src->xnum, tc);
        if (!dest) {
            PyErr_Clear();
            return NULL;
        }
    }
    const size_t n = (size_t)src->xnum * src->ynum;
    memcpy(dest->cpu_cell_buf, src->cpu_cell_buf, n * sizeof(src->cpu_cell_buf[0]));
    memcpy(dest->render_cell_buf, src->render_cell_buf, n * sizeof(src->render_cell_buf[0]));
    memcpy(dest->line_map, src->line_map, src->ynum * sizeof(src->line_map[0]));
    memcpy(dest->line_attrs, src->line_attrs, src->ynum * sizeof(src->line_attrs[0]));
    return dest;
}

static void
ssr_capture_for_pause(Screen *self) {
    // Rendering is being paused, capture how the regions are rendered
    __typeof__(self->paused_rendering.smooth_scroll) *p = &self->paused_rendering.smooth_scroll;
    p->count = 0;
    p->history_row_region = 0;
    if (!self->smooth_scroll.count) return;
    const unsigned count = ssr_live_render_regions(self, p->regions);
    for (unsigned i = 0; i < count; i++) {
        SmoothScrollRegion *r = ssr_for_id(self, p->regions[i].id), *c = p->copies + i;
        LineBuf *overflow = ssr_copy_linebuf(r->overflow, c->overflow, self->text_cache);
        c->overflow = NULL;
        if (!overflow) return;
        *c = *r;
        c->overflow = overflow;
        if (ssr_uses_history(self, r) && self->historybuf->count && smooth_scroll_render_region_is_shifted(p->regions + i)) {
            if (!p->history_row || p->history_row->xnum != self->columns) {
                Py_CLEAR(p->history_row);
                p->history_row = alloc_linebuf(1, self->columns, self->text_cache);
                if (!p->history_row) {
                    PyErr_Clear();
                    return;
                }
            }
            // History lines have no render data of their own, the row is rendered as it is dirty
            Line l = {.text_cache = self->text_cache};
            historybuf_init_line(self->historybuf, 0, &l);
            linebuf_clear_line(p->history_row, 0, true);
            memcpy(p->history_row->cpu_cell_buf, l.cpu_cells, self->columns * sizeof(l.cpu_cells[0]));
            // Drawn as in the live frame: with its settings, and with pixel scrolling at the levels of the leading render row
            line_attrs_set_bidi(p->history_row->line_attrs, l.attrs);
            if (UNLIKELY(self->paused_rendering.linebuf->bidi_stamped) && self->paused_rendering.pixel_scroll) {
                linebuf_init_line(p->history_row, 0);
                bidi_store_levels(self->bidi_maps, 0, p->history_row->line);
            }
            linebuf_mark_line_dirty(p->history_row, 0);
            p->history_row_region = i + 1;
        }
    }
    p->count = count;
}

static void
ssr_release_pause_capture(Screen *self) {
    __typeof__(self->paused_rendering.smooth_scroll) *p = &self->paused_rendering.smooth_scroll;
    // The copies must not keep text cache entries alive
    for (unsigned i = 0; i < MAX_SMOOTH_SCROLL_REGIONS; i++)
        if (p->copies[i].overflow) linebuf_clear(p->copies[i].overflow, BLANK_CHAR);
    if (p->history_row) linebuf_clear(p->history_row, BLANK_CHAR);
    p->count = 0;
    p->history_row_region = 0;
}
// }}}

static void
ssr_reply_to_query(Screen *self, const SmoothScrollCommand *cmd) {
    // A query, a=q, replies with the maximum number of regions. A feature
    // query, a=q with e=<action>, replies with e and every key of the query
    // that has a non-default value, which is supported with that action. The
    // other keys and e itself are omitted from the reply when not supported.
    char buf[256];
    size_t pos = 0;
#define print(fmt, ...) \
    if (sizeof(buf) - 1 > pos) pos += snprintf(buf + pos, sizeof(buf) - pos, fmt, __VA_ARGS__)
    print("%d;a=q", SMOOTH_SCROLL_CODE);
    const char action = cmd->query_action;
    if (!action) {
        print(":n=%u", MAX_SMOOTH_SCROLL_REGIONS);
    } else if (strchr("dsrq", action)) {
        print(":e=%c", action);
        // Keys with default values are not echoed, zero means the default for all keys
#define ECHO_UINT(key, attr, default_value) \
    if (cmd->attr && cmd->attr != default_value) print(":%c=%u", key, cmd->attr)
        switch (action) {
            case 'd':
                ECHO_UINT('x', x, 1u);
                ECHO_UINT('y', y, 1u);
                ECHO_UINT('w', width, 0u);
                ECHO_UINT('h', height, 0u);
                ECHO_UINT('k', capacity, 1u);
                if (cmd->orientation == 'h') print(":o=%c", cmd->orientation);
                if (cmd->private_overflow == 1) print(":p=%u", 1u);
                break;
            case 's':
                if (cmd->delta) print(":d=%d", cmd->delta);
                break;
            default: break;
        }
#undef ECHO_UINT
    }
#undef print
    write_escape_code_to_child(self, ESC_OSC, buf);
}

void
screen_handle_smooth_scroll_command(Screen *self, const SmoothScrollCommand *cmd) {
    // See docs/smooth-scrolling-protocol.rst. Only queries reply, invalid commands are ignored.
    switch (cmd->action) {
        case 'd': {
            if (!cmd->id || cmd->private_overflow > 1) return;
            // Coordinates are one based, zero for the defaults
            const uint64_t left = cmd->x ? cmd->x - 1u : 0, top = cmd->y ? cmd->y - 1u : 0;
            if (left >= self->columns || top >= self->lines) return;
            const uint64_t right = cmd->width ? left + cmd->width : self->columns, bottom = cmd->height ? top + cmd->height : self->lines;
            if (right > self->columns || bottom > self->lines) return;
            const bool horizontal = cmd->orientation == 'h';
            const uint64_t length = horizontal ? right - left : bottom - top;
            const index_type capacity = (index_type)MAX(1u, MIN((uint64_t)cmd->capacity, length));
            screen_smooth_scroll_define(
                self, cmd->id, (index_type)left, (index_type)top, (index_type)right, (index_type)bottom, capacity, cmd->private_overflow == 1, horizontal);
        } break;
        case 's': {
            if (!cmd->id) return;
            int cells_shifted;
            screen_smooth_scroll(self, cmd->id, cmd->delta, &cells_shifted);
        } break;
        case 'r':
            if (cmd->id) screen_smooth_scroll_remove(self, cmd->id);
            else screen_smooth_scroll_remove_all(self);
            break;
        case 'q': ssr_reply_to_query(self, cmd); break;
        default: break;
    }
}
// }}}


static void
nuke_split_multicell_char_at_left_boundary(Screen *self, index_type x, index_type y, bool replace_with_spaces) {
    if (x >= self->columns) return;
    CPUCell *cp = linebuf_cpu_cells_for_line(self->linebuf, y);
    if (cp[x].is_multicell && cp[x].x) {
        nuke_multicell_char_at(self, x, y, replace_with_spaces); // remove split multicell char at left edge
    }
}

static void
nuke_split_multicell_char_at_right_boundary(Screen *self, index_type x, index_type y, bool replace_with_spaces) {
    CPUCell *cp = linebuf_cpu_cells_for_line(self->linebuf, y);
    CPUCell *c = cp + x;
    if (c->is_multicell) {
        unsigned max_x = mcd_x_limit(c) - 1;
        if (c->x < max_x) { nuke_multicell_char_at(self, x, y, replace_with_spaces); }
    }
}

static void
nuke_incomplete_single_line_multicell_chars_in_range(Screen *self, index_type start, index_type limit, index_type y, bool replace_with_spaces) {
    CPUCell *cpu_cells;
    linebuf_init_cells(self->linebuf, y, &cpu_cells, NULL);
    for (index_type x = start; x < limit; x++) {
        if (cpu_cells[x].is_multicell) {
            // The end of the char, at least x + 1, so that the loop always makes
            // progress, even for fragments of chars whose first cell is missing
            const index_type w = mcd_x_limit(cpu_cells + x);
            const index_type char_limit = x + (w > cpu_cells[x].x ? w - cpu_cells[x].x : 1);
            if (cpu_cells[x].x || char_limit > limit) {
                nuke_in_line(cpu_cells, x, MIN(char_limit, limit), replace_with_spaces ? ' ' : 0);
                linebuf_mark_line_dirty(self->linebuf, y);
            }
            x = char_limit - 1;
        }
    }
}


static index_type
prevent_current_prompt_from_rewrapping(Screen *self, LineBuf *prompt_copy, index_type *num_of_prompt_lines_above_cursor) {
    index_type num_of_prompt_lines = 0;
    *num_of_prompt_lines_above_cursor = 0;
    if (!self->prompt_settings.redraws_prompts_at_all) return num_of_prompt_lines;
    int y = self->cursor->y;
    while (y >= 0) {
        linebuf_init_line(self->main_linebuf, y);
        Line *line = self->linebuf->line;
        switch (line->attrs.prompt_kind) {
            case UNKNOWN_PROMPT_KIND: break;
            case PROMPT_START:
            case SECONDARY_PROMPT: goto found; break;
            case OUTPUT_START: return num_of_prompt_lines;
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
    LineBuf *orig = self->linebuf;
    self->linebuf = self->main_linebuf;
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
    // The cursor was moved past the marker, so the marker is just before it.
    // It is not necessarily at the start of the line, as rewrap places it
    // after the lower rows of multiline chars from the lines above.
    if (cursor->y < linebuf->ynum) {
        CPUCell *cells = linebuf_cpu_cells_for_line(linebuf, cursor->y);
#define is_marker(x) (!cells[x].is_multicell && cell_is_char(cells + (x), '<'))
        index_type x = cursor->x ? MIN(cursor->x, linebuf->xnum) - 1 : 0;
        if (!is_marker(x)) x = 0;
        if (is_marker(x)) cell_set_char(cells + x, 0);
#undef is_marker
        cursor->x = x;
    }
}

static bool
screen_resize(Screen *self, unsigned int lines, unsigned int columns) {
    screen_pause_rendering(self, false, 0);
    screen_smooth_scroll_remove_all(self);
    bidi_layout_moved(self);
    lines = MAX(1u, lines);
    columns = MAX(1u, columns);

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
#define setup_cursor(which)                                                                                    \
    {                                                                                                          \
        which.after.x = which.temp.x;                                                                          \
        which.after.y = which.temp.y;                                                                          \
        which.is_beyond_content = num_content_lines_before > 0 && self->cursor->y >= num_content_lines_before; \
        which.num_content_lines = num_content_lines_after;                                                     \
    }
    // Resize overlay and blank lines
    if (!init_overlay_line(self, columns, true)) return false;

    // Resize main linebuf
    RAII_PyObject(prompt_copy, NULL);
    index_type num_of_prompt_lines = 0, num_of_prompt_lines_above_cursor = 0;
    if (is_main) {
        prompt_copy = (PyObject *)alloc_linebuf(self->lines, self->columns, self->text_cache);
        num_of_prompt_lines = prevent_current_prompt_from_rewrapping(self, (LineBuf *)prompt_copy, &num_of_prompt_lines_above_cursor);
    }
    if (!rewrap(self, lines, columns, &num_content_lines_before, &num_content_lines_after, &cursor, &main_saved_cursor, &alt_saved_cursor, is_main))
        return false;
    setup_cursor(cursor);
    /* printf("old_cursor: (%u, %u) new_cursor: (%u, %u) beyond_content: %d\n", self->cursor->x, self->cursor->y, cursor.after.x, cursor.after.y,
     * cursor.is_beyond_content); */
    setup_cursor(main_saved_cursor);
    grman_remove_all_cell_images(self->main_grman);
    grman_resize(self->main_grman, self->lines, lines, self->columns, columns, num_content_lines_before, num_content_lines_after);
    setup_cursor(alt_saved_cursor);
    grman_remove_all_cell_images(self->alt_grman);
    grman_resize(self->alt_grman, self->lines, lines, self->columns, columns, num_content_lines_before, num_content_lines_after);
#undef setup_cursor
    /* printf("\nold_size: (%u, %u) new_size: (%u, %u)\n", self->columns, self->lines, columns, lines); */
    index_type old_columns_for_tabs = self->columns;
    self->lines = lines;
    self->columns = columns;
    self->margin_top = 0;
    self->margin_bottom = self->lines - 1;

    bool *old_tabstops = self->main_tabstops;
    bool *new_tabstops = PyMem_Calloc(2 * self->columns, sizeof(bool));
    if (new_tabstops == NULL) {
        PyErr_NoMemory();
        return false;
    }
    bool *new_main = new_tabstops;
    bool *new_alt = new_tabstops + self->columns;
    init_tabstops(new_main, self->columns);
    init_tabstops(new_alt, self->columns);
    if (old_tabstops && old_columns_for_tabs) {
        index_type to_copy = MIN(old_columns_for_tabs, self->columns);
        memcpy(new_main, old_tabstops, to_copy * sizeof(bool));
        memcpy(new_alt, old_tabstops + old_columns_for_tabs, to_copy * sizeof(bool));
    }
    PyMem_Free(old_tabstops);
    self->main_tabstops = new_main;
    self->alt_tabstops = new_alt;
    self->tabstops = is_main ? self->main_tabstops : self->alt_tabstops;
    self->is_dirty = true;
    clear_all_selections(self);
    self->last_visited_prompt.is_set = false;
#define S(c, w)                               \
    c->x = MIN(w.after.x, self->columns - 1); \
    c->y = MIN(w.after.y, self->lines - 1);
    S(self->cursor, cursor);
    S((&(self->main_savepoint.cursor)), main_saved_cursor);
    S((&(self->alt_savepoint.cursor)), alt_saved_cursor);
#undef S
    if (cursor.is_beyond_content) {
        self->cursor->y = cursor.num_content_lines;
        if (self->cursor->y >= self->lines) {
            self->cursor->y = self->lines - 1;
            screen_index(self);
        }
    }
    if (is_main && OPT(scrollback_fill_enlarged_window)) {
        const unsigned int top = 0, bottom = self->lines - 1;
        Savepoint *sp = is_main ? &self->main_savepoint : &self->alt_savepoint;
        while (self->cursor->y + 1 < self->lines && self->lines - self->cursor->y > lines_after_cursor_before_resize) {
            if (!self->historybuf->count) break;
            // must be done before popping the history line
            nuke_multiline_chars_torn_by_scroll(self, top, bottom, false, true);
            if (!historybuf_pop_line(self->historybuf, self->alt_linebuf->line)) break;
            INDEX_DOWN(true);
            linebuf_copy_line_to(self->main_linebuf, self->alt_linebuf->line, 0);
            bidi_note_line_from_history(self, 0);
            self->cursor->y++;
            sp->cursor.y = MIN(sp->cursor.y + 1, self->lines - 1);
        }
    }
    clamp_scroll_position(self);
    if (main_has_blank_line) remove_blank_output_line_reservation_marker(is_main ? self->cursor : &self->main_savepoint.cursor, self->main_linebuf);
    if (alt_has_blank_line) remove_blank_output_line_reservation_marker(is_main ? &self->alt_savepoint.cursor : self->cursor, self->alt_linebuf);
    if (num_of_prompt_lines) {
        // Copy the old prompt lines without any reflow this prevents
        // flickering of prompt during resize. The flicker is caused by the
        // prompt being first cleared by kitty then sometime later redrawn by
        // the shell.
        LineBuf *src = (LineBuf *)prompt_copy;
        for (index_type src_line = 0, y = num_of_prompt_lines_above_cursor <= self->cursor->y ? self->cursor->y - num_of_prompt_lines_above_cursor : 0;

             src_line < num_of_prompt_lines && y < self->lines;

             y++, src_line++) {
            linebuf_init_line(src, src_line);
            linebuf_copy_line_to(self->main_linebuf, src->line, y);
            // The copy takes the prompt line's attrs, whose bidi_may_reorder is not that of the cells the row now holds
            LineBuf *lb = self->main_linebuf;
            if (UNLIKELY(lb->bidi_stamped)) bidi_line_may_reorder_from_cells(self, lb, y);
            else if (UNLIKELY(line_has_bidi_bits(lb->line_attrs[y]))) bidi_buffer_stamped(self, lb);
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


static PyObject *
reset_callbacks(Screen *self, PyObject *a UNUSED) {
    Py_CLEAR(self->callbacks);
    self->callbacks = Py_None;
    Py_INCREF(self->callbacks);
    Py_RETURN_NONE;
}

static void
dealloc(Screen *self) {
    pthread_mutex_destroy(&self->write_buf_lock);
    free_vt_parser(self->vt_parser);
    self->vt_parser = NULL;
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
    PyMem_Free(self->overlay_line.render_cells);
    PyMem_Free(self->overlay_line.original_line.cpu_cells);
    PyMem_Free(self->overlay_line.original_line.render_cells);
    Py_CLEAR(self->overlay_line.overlay_text);
    PyMem_Free(self->main_tabstops);
    Py_CLEAR(self->paused_rendering.linebuf);
    Py_CLEAR(self->paused_rendering.grman);
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) Py_CLEAR(self->smooth_scroll.regions[i].overflow);
    for (unsigned i = 0; i < MAX_SMOOTH_SCROLL_REGIONS; i++) Py_CLEAR(self->paused_rendering.smooth_scroll.copies[i].overflow);
    Py_CLEAR(self->paused_rendering.smooth_scroll.history_row);
    free(self->selection_scratch);
    if (self->style_texture.texture) free_texture(&self->style_texture.texture);
    free(self->selections.items);
    free(self->url_ranges.items);
    free(self->paused_rendering.url_ranges.items);
    free(self->paused_rendering.selections.items);
    free_hyperlink_pool(self->hyperlink_pool);
    free(self->as_ansi_buf.buf);
    free(self->last_rendered_window_char.canvas);
    free(self->extra_cursors.locations);
    free(self->paused_rendering.extra_cursors.locations);
    if (self->lc) {
        cleanup_list_of_chars(self->lc);
        free(self->lc);
        self->lc = NULL;
    }
    bidi_maps_free(self->bidi_maps);
    Py_TYPE(self)->tp_free((PyObject *)self);
} // }}}

// Draw text {{{
typedef struct text_loop_state {
    bool image_placeholder_marked;
    const CPUCell cc;
    CPUCell *cp;
    GraphemeSegmentationResult seg;
    struct {
        index_type x, y;
        CPUCell *cc;
    } prev;
    // True when the line being drawn into is known to contain no multicell
    // cells, which lets the ASCII fast path skip checking for them. This is
    // the case for a line that was just cleared by scrolling, until something
    // other than the ASCII fast path, CR or HT, which never create multicell
    // cells, happens.
    bool line_has_no_multicell;
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
    if (UNLIKELY(self->selections.count) && selection_has_screen_line(&self->selections, y)) clear_selection(&self->selections);
    if (UNLIKELY(self->url_ranges.count) && selection_has_screen_line(&self->url_ranges, y)) clear_selection(&self->url_ranges);
}

static void
init_prev_cell(Screen *self, text_loop_state *s) {
    zero_at_ptr(&s->prev);
    // The pre-edit text does not combine with the cells before it, which can be on the row above
    if (UNLIKELY(self->overlay_line.drawing) && self->cursor->x <= self->overlay_line.draw_left) return;
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
        if (LIKELY(!s->prev.cc->ch_is_idx)) {
            // single codepoint in cell, no need for the ListOfChars machinery
            const char_type ch = s->prev.cc->ch_or_idx;
            if (LIKELY(' ' <= ch && ch < DEL)) {
                // every printable ASCII char steps from the reset state to this
                // same state, matching what the batched ASCII draw path uses
                s->seg = (GraphemeSegmentationResult){.grapheme_break = GBP_None};
            } else if (!ch) {
                // empty cell, common when the cursor is preceded by unwritten cells
                static GraphemeSegmentationResult empty_cell_seg;
                static bool have_empty_cell_seg = false;
                if (UNLIKELY(!have_empty_cell_seg)) {
                    empty_cell_seg = grapheme_segmentation_step(s->seg, char_props_for(0));
                    have_empty_cell_seg = true;
                }
                s->seg = empty_cell_seg;
            } else s->seg = grapheme_segmentation_step(s->seg, char_props_for(ch));
        } else {
            text_in_cell(s->prev.cc, self->text_cache, self->lc);
            for (index_type i = 0; i < self->lc->count; i++) s->seg = grapheme_segmentation_step(s->seg, char_props_for(self->lc->chars[i]));
        }
    }
}

static LineAttrs
current_bidi_record(const Screen *self) {
    LineAttrs ans = {0};
    if (!self->modes.mBDSM || OPT(force_ltr)) return ans;
    ans.bidi_stamp = BIDI_STAMP_IMPLICIT;
    ans.bidi_rtl = self->bidi.rtl;
    ans.bidi_auto = self->modes.mBIDI_AUTODETECT;
    return ans;
}

// A line without a record takes the record of the text written to it. With bidi mode off that record is empty, and the text drops
// the direction a leading mark set.
static void
stamp_line_for_bidi(Screen *self, index_type y, uint8_t record) {
    LineAttrs *a = self->linebuf->line_attrs + y;
    if (!record) {
        a->bidi_rtl = a->bidi_auto = false;
        return;
    }
    if (a->bidi_auto) {
        // the direction a leading mark set
        a->bidi_stamp = BIDI_STAMP_IMPLICIT;
        a->bidi_auto = false;
    } else a->val |= record;
    bidi_buffer_stamped(self, self->linebuf);
}

static inline void
record_written_line(Screen *self, index_type y, uint8_t record) {
    if (!self->linebuf->line_attrs[y].bidi_stamp) stamp_line_for_bidi(self, y, record);
}

static inline void
bidi_note_may_reorder(Screen *self, index_type y, bool may_reorder) {
    if (may_reorder) self->linebuf->line_attrs[y].bidi_may_reorder = true;
}

// After a batched run drawn on row y. Its chars are not looked at: the bit may be set for a row that cannot reorder, which the
// walk resolving the dirty row clears.
static inline void
bidi_note_run(Screen *self, index_type y) {
    LineAttrs *a = self->linebuf->line_attrs + y;
    if (!a->bidi_may_reorder) a->bidi_may_reorder = true;
}

// Called before text is stored on line y: a record the line kept while it held no text is not the record of that text
static void
bidi_line_gets_text(Screen *self, index_type y) {
    LineBuf *lb = self->linebuf;
    if (lb->line_attrs[y].bidi_stamp == BIDI_STAMP_NONE) return;
    linebuf_init_line(lb, y);
    line_has_bidi_record(lb->line_attrs + y, lb->line);
}

static inline void
draw_loop_line_gets_text(Screen *self, index_type y) {
    if (self->linebuf->line_attrs[y].bidi_stamp != BIDI_STAMP_NONE) bidi_line_gets_text(self, y);
}

static void
set_record_at_leading_mark(Screen *self, char_type ch, uint8_t record) {
    // A leading mark fixes the direction of a line that would otherwise take it from its text. A line without a record gets
    // none: its first text written in bidi mode takes the direction.
    if (!((LineAttrs){.val = record}).bidi_auto) return;
    // Main buffer row 0 continuing a history line starts no paragraph, as no other continuation row does, though the draw loop
    // has no previous cell for it
    if (!self->cursor->y && self->linebuf == self->main_linebuf && history_buf_endswith_wrap(self->historybuf)) return;
    LineAttrs *a = self->linebuf->line_attrs + self->cursor->y;
    a->bidi_auto = a->bidi_stamp == BIDI_STAMP_NONE;
    a->bidi_rtl = ch == 0x200f; // RLM
    bidi_buffer_stamped(self, self->linebuf);
}

// After a combining char was drawn, before is the text its cell held: the cell is the loop's previous cell now, which a widening
// can have moved to another row
static inline void
record_combining_write(Screen *self, const text_loop_state *s, char_type before, uint8_t record, bool may_reorder) {
    if (!s->prev.cc || s->prev.cc->ch_and_idx == before) return;
    record_written_line(self, s->prev.y, record);
    bidi_note_may_reorder(self, s->prev.y, may_reorder);
    // A zero width char at the start of a continuation row goes to the last cell of the row above
    if (s->prev.y != self->cursor->y) linebuf_mark_line_dirty(self->linebuf, s->prev.y);
}

static void
init_text_loop_line(Screen *self, text_loop_state *s) {
    // Also collect garbage in the text cache when starting a new line, not just
    // when starting to draw text, as a single draw can add a great many entries,
    // for example, when drawing a long stream of unique multi-codepoint cells,
    // making the cache slower to use the larger it grows.
    if (tc_should_gc(self->text_cache)) screen_garbage_collect_text_cache(self);
    linebuf_init_cells(self->linebuf, self->cursor->y, &s->cp, NULL);
    clear_intersecting_selections(self, self->cursor->y);
    linebuf_mark_line_dirty(self->linebuf, self->cursor->y);
    s->image_placeholder_marked = false;
    s->line_has_no_multicell = false;
    init_segmentation_state(self, s);
}

// Used when the cursor is moved after the current char has already been
// through grapheme segmentation, so the segmentation state must be preserved
static void
reinit_text_loop_line(Screen *self, text_loop_state *s) {
    const GraphemeSegmentationResult seg = s->seg;
    init_text_loop_line(self, s);
    s->seg = seg;
}

typedef Line *(linefunc_t)(Screen *, int);

static void
init_line_(Screen *self, index_type y, Line *line) {
    linebuf_init_line_at(self->linebuf, y, line);
}


static Line *
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

static Line *
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

static Line *
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

static Line *
checked_range_line(Screen *self, int y) {
    if (-(int)self->historybuf->count <= y && y < (int)self->lines) return range_line_(self, y);
    return NULL;
}

bool
range_line_is_continued(Screen *self, int y) {
    if (!(-(int)self->historybuf->count <= y && y < (int)self->lines)) return false;
    if (y < 0) return historybuf_is_line_continued(self->historybuf, -(y + 1));
    if (y) return linebuf_is_line_continued(self->linebuf, y);
    return self->linebuf == self->main_linebuf ? history_buf_endswith_wrap(self->historybuf) : false;
}

// The bidi record the text of range line y continues: that of the first line of its paragraph above it holding one, the
// scrollback pager history included, 0 for none. Serializing lines from y writes the paragraph under it, see
// ansi_bidi_continue().
static uint8_t
screen_bidi_record_above(Screen *self, int y) {
    HistoryBuf *hb = self->historybuf;
    const bool continues_history = self->linebuf == self->main_linebuf && hb->count;
    if (y <= 0 && !continues_history) return 0;
    // Only the rows of the active buffer and the history can be read, and a record can be on them only when their flags say so
    if (!self->linebuf->bidi_stamped && !(continues_history && (hb->bidi_stamped || historybuf_pagerhist_bidi_open(hb)))) return 0;
    uint8_t ans = 0;
    Line line = {.xnum = self->columns, .text_cache = self->text_cache};
    for (; range_line_is_continued(self, y); y--) {
        if (y == -(int)hb->count) {
            // the oldest history line continues the pager history, whose paragraph comes first
            const uint8_t p = historybuf_pagerhist_bidi_open(hb);
            if (p) ans = p;
            break;
        }
        if (y == 0 && !continues_history) break;
        const LineAttrs *a = y - 1 < 0 ? historybuf_attrs(hb, -y) : self->linebuf->line_attrs + y - 1;
        if (a->bidi_stamp == BIDI_STAMP_NONE) continue;
        range_line(self, y - 1, &line);
        const uint8_t rec = line_bidi_record_for_ansi(&line);
        if (rec) ans = rec;
    }
    return ans;
}

static void
insert_characters(Screen *self, index_type at, index_type num, index_type y, bool replace_with_spaces) {
    if (UNLIKELY(self->smooth_scroll.count)) ssr_row_cells_moved(self, at, y);
    // insert num chars at x=at setting them to the value of the num chars at [at, at + num)
    // multiline chars at x >= at are deleted and multicell chars split at x=at
    // and x=at + num - 1 are deleted
    nuke_multiline_char_intersecting_with(self, at, self->columns, y, y + 1, replace_with_spaces);
    nuke_split_multicell_char_at_left_boundary(self, at, y, replace_with_spaces);
    CPUCell *cp;
    linebuf_init_cells(self->linebuf, y, &cp, NULL);
    bidi_note_maybe_unstamp(self->linebuf);
    // right shift
    for (index_type i = self->columns - 1; i >= at + num; i--) cp[i] = cp[i - num];
    linebuf_mark_line_dirty(self->linebuf, y);
    nuke_incomplete_single_line_multicell_chars_in_range(self, at, at + num, y, replace_with_spaces);
    nuke_split_multicell_char_at_right_boundary(self, self->columns - 1, y, replace_with_spaces);
}

static void
halve_multicell_width(Screen *self, MulticellColumns cols, MulticellRows rows, index_type y_) {
    // Halve the width of the multicell char in the columns cols of rows,
    // whose top row is y_. Only called for complete chars, as found by
    // add_combining_chars(), which also provides cols and rows.
    const CPUCell *cp = linebuf_cpu_cells_for_line(self->linebuf, y_);
    const index_type x_ = cols.start;
    const unsigned new_width = cp[x_].width / 2;
    const index_type ws = mcd_x_limit(&cp[x_]);
    const index_type x_limit = cols.limit;
    const index_type half_x_limit = MIN(x_limit, x_ + ws / 2);
    for (int y = rows.start; y < rows.limit; y++) {
        Line *line = range_line_(self, y);
        CPUCell *c = line->cpu_cells;
        for (index_type x = x_; x < half_x_limit; x++) c[x].width = new_width;
        for (index_type x = half_x_limit; x < x_limit; x++) {
            // preserve the soft wrap marker, which lives in the last cell of the line
            c[x] = (CPUCell){.style_idx = c[x].style_idx, .next_char_was_wrapped = c[x].next_char_was_wrapped};
        }
        mark_range_line_dirty(self, y);
    }
    self->is_dirty = true;
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

static void
text_cache_gc_process_cells(TextCache *tc, TextCacheGCData *gc, CPUCell *cells, size_t count) {
    for (size_t i = 0; i < count; i++) {
        CPUCell *c = cells + i;
        if (!c->ch_is_idx) continue;
        char_type new_idx;
        if (tc_gc_map_index(tc, gc, c->ch_or_idx, &new_idx)) c->ch_or_idx = new_idx;
        else cell_set_char(c, 0); // stale index, should not happen
    }
}

static void
text_cache_gc_process_linebuf(TextCache *tc, TextCacheGCData *gc, LineBuf *lb) {
    if (lb) text_cache_gc_process_cells(tc, gc, lb->cpu_cell_buf, (size_t)lb->ynum * lb->xnum);
}

void
screen_garbage_collect_text_cache(Screen *self) {
    // The TextCache interns unique cell texts forever; remap every live cell
    // index onto a fresh cache so entries that scrolled out of the history
    // buffer are freed. Mirrors screen_garbage_collect_hyperlink_pool().
    TextCacheGCData *gc = tc_gc_begin(self->text_cache);
    if (!gc) return; // allocation failure, cache left unchanged
    if (self->historybuf->count) {
        for (index_type y = self->historybuf->count; y-- > 0;) {
            CPUCell *cells = historybuf_cpu_cells(self->historybuf, y);
            text_cache_gc_process_cells(self->text_cache, gc, cells, self->historybuf->xnum);
        }
    }
    text_cache_gc_process_linebuf(self->text_cache, gc, self->main_linebuf);
    text_cache_gc_process_linebuf(self->text_cache, gc, self->alt_linebuf);
    text_cache_gc_process_linebuf(self->text_cache, gc, self->paused_rendering.linebuf);
    for (unsigned i = 0; i < MAX_SMOOTH_SCROLL_REGIONS; i++)
        text_cache_gc_process_linebuf(self->text_cache, gc, self->paused_rendering.smooth_scroll.copies[i].overflow);
    text_cache_gc_process_linebuf(self->text_cache, gc, self->paused_rendering.smooth_scroll.history_row);
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) text_cache_gc_process_linebuf(self->text_cache, gc, self->smooth_scroll.regions[i].overflow);
    // The overlay buffers have columns cells, overlay_line.xnum is the length of the overlay text, which can be larger
    if (self->overlay_line.cpu_cells) text_cache_gc_process_cells(self->text_cache, gc, self->overlay_line.cpu_cells, self->columns);
    if (self->overlay_line.original_line.cpu_cells)
        text_cache_gc_process_cells(self->text_cache, gc, self->overlay_line.original_line.cpu_cells, self->columns);
    tc_gc_end(self->text_cache, gc);
    // the GC remaps all cache indices so the memoized tab indices and the hashes of cells are stale
    bidi_maps_invalidate_row_hashes(self);
    memset(&self->tab_cache, 0, sizeof(self->tab_cache));
    GlyphRegistry *gr = tc_glyph_registry(self->text_cache);
    memset(gr->bound_idx_plus_1, 0, sizeof(gr->bound_idx_plus_1));
}

static void
style_gc_process_cells(CellStyleTable *t, StyleTableGC *gc, CPUCell *cells, size_t count, bool quantize) {
    for (size_t i = 0; i < count; i++) cells[i].style_idx = style_table_gc_map(t, gc, cells[i].style_idx, quantize);
}

static void
style_gc_process_linebuf(CellStyleTable *t, StyleTableGC *gc, LineBuf *lb) {
    if (lb) style_gc_process_cells(t, gc, lb->cpu_cell_buf, (size_t)lb->ynum * lb->xnum, false);
}

static LineBuf *
paused_linebuf_in_use(const Screen *self) {
    // The snapshot of the screen taken when rendering was paused, NULL when
    // rendering is not paused. The snapshot is kept after rendering resumes,
    // but is unused then and entirely overwritten when rendering is next
    // paused, so its cells must not keep styles alive.
    return self->paused_rendering.expires_at ? self->paused_rendering.linebuf : NULL;
}

static bool
garbage_collect_style_table(Screen *self, unsigned quantize_bits, bool degraded_if_full) {
    // Remap the style index of every live cell onto a fresh table, so styles
    // that are no longer used are freed. With quantize_bits, styles of cells
    // in the scrollback get colors of reduced precision. Must only be called
    // when no style indices are held outside of cells.
    CellStyleTable *t = self->style_table;
    StyleTableGC *gc = style_table_gc_begin(t, quantize_bits);
    if (!gc) return false; // allocation failure, table left unchanged
    // Screen cells first, so they get exact styles even if the table overflows
    style_gc_process_linebuf(t, gc, self->main_linebuf);
    style_gc_process_linebuf(t, gc, self->alt_linebuf);
    style_gc_process_linebuf(t, gc, paused_linebuf_in_use(self));
    if (self->paused_rendering.expires_at) {
        for (unsigned i = 0; i < MAX_SMOOTH_SCROLL_REGIONS; i++) style_gc_process_linebuf(t, gc, self->paused_rendering.smooth_scroll.copies[i].overflow);
        style_gc_process_linebuf(t, gc, self->paused_rendering.smooth_scroll.history_row);
    }
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) style_gc_process_linebuf(t, gc, self->smooth_scroll.regions[i].overflow);
    // The overlay buffers have columns cells, overlay_line.xnum is the length of the overlay text
    if (self->overlay_line.cpu_cells) style_gc_process_cells(t, gc, self->overlay_line.cpu_cells, self->columns, false);
    if (self->overlay_line.original_line.cpu_cells) style_gc_process_cells(t, gc, self->overlay_line.original_line.cpu_cells, self->columns, false);
    for (index_type y = self->historybuf->count; y-- > 0;) {
        style_gc_process_cells(t, gc, historybuf_cpu_cells(self->historybuf, y), self->historybuf->xnum, true);
    }
    const bool still_full = t->count > style_table_max_count(t) - style_table_max_count(t) / 8;
    style_table_gc_end(t, gc, degraded_if_full && still_full);
    return true;
}

static bool
cells_use_styles(const CPUCell *cells, size_t count) {
    for (size_t i = 0; i < count; i++)
        if (cells[i].style_idx) return true;
    return false;
}

static void
reset_style_table_if_unused(Screen *self) {
    // When the scrollback is empty and no cell has a style, empty the style
    // table, which frees the memory used by styles from, for example, a burst
    // of output with many colors. Done only on hard resets and clearing of the
    // scrollback, not on erasing the screen, as full screen programs erase the
    // screen on every redraw, and resetting would then force all their styles
    // to be interned again and the style texture to be uploaded again every
    // frame. Small tables are not worth emptying for the same reason.
    if (self->historybuf->count || !style_table_is_worth_resetting(self->style_table)) return;
    LineBuf *bufs[3] = {self->main_linebuf, self->alt_linebuf, paused_linebuf_in_use(self)};
    for (unsigned i = 0; i < arraysz(bufs); i++) {
        if (bufs[i] && cells_use_styles(bufs[i]->cpu_cell_buf, (size_t)bufs[i]->xnum * bufs[i]->ynum)) return;
    }
    if (self->overlay_line.cpu_cells && cells_use_styles(self->overlay_line.cpu_cells, self->columns)) return;
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) {
        const LineBuf *lb = self->smooth_scroll.regions[i].overflow;
        if (cells_use_styles(lb->cpu_cell_buf, (size_t)lb->xnum * lb->ynum)) return;
    }
    if (self->paused_rendering.expires_at) {
        const LineBuf *paused[MAX_SMOOTH_SCROLL_REGIONS + 1] = {self->paused_rendering.smooth_scroll.history_row};
        for (unsigned i = 0; i < MAX_SMOOTH_SCROLL_REGIONS; i++) paused[i + 1] = self->paused_rendering.smooth_scroll.copies[i].overflow;
        for (unsigned i = 0; i < arraysz(paused); i++) {
            if (paused[i] && cells_use_styles(paused[i]->cpu_cell_buf, (size_t)paused[i]->xnum * paused[i]->ynum)) return;
        }
    }
    if (self->overlay_line.original_line.cpu_cells && cells_use_styles(self->overlay_line.original_line.cpu_cells, self->columns)) return;
    style_table_reset(self->style_table);
}

void
screen_garbage_collect_style_table(Screen *self) {
    // Called when the style table is full. Tries collecting without loss of
    // precision first and if that does not free at least an eighth of the
    // table, reduces the color precision of cells in the scrollback. Cells on
    // screen always keep their exact styles.
    CellStyleTable *t = self->style_table;
    const uint32_t threshold = style_table_max_count(t) - style_table_max_count(t) / 8;
    // If the last collection had to reduce precision, start there, as the
    // scrollback is likely still full of distinct styles
    unsigned bits = style_table_last_gc_quantize_bits(t);
    static const unsigned ladder[] = {0, 4, 3, 2};
    unsigned start = 0;
    for (unsigned i = 0; i < arraysz(ladder); i++)
        if (ladder[i] == bits) start = i;
    for (unsigned i = start; i < arraysz(ladder); i++) {
        const bool last = i + 1 == arraysz(ladder);
        if (!garbage_collect_style_table(self, ladder[i], last)) return;
        if (t->count <= threshold) break;
    }
}

// Glyph protocol print time binding: a cell with a codepoint from the
// registration block that has a registered glyph stores the glyph in its text
// cache entry, so that later changes to the registration do not affect it
static void
bind_registered_glyph(Screen *self, CPUCell *c, char_type first_char) {
    GlyphRegistry *r = tc_glyph_registry(self->text_cache);
    VGGlyph *g = glyph_registry_get(r, first_char);
    if (!g) return;
    const unsigned slot = first_char - GLYPH_BLOCK_FIRST;
    if (!c->ch_is_idx && r->bound_idx_plus_1[slot]) {
        // The common case of a cell with just the codepoint
        c->ch_or_idx = r->bound_idx_plus_1[slot] - 1;
        c->ch_is_idx = true;
        return;
    }
    RAII_ListOfChars(lc);
    text_in_cell(c, self->text_cache, &lc);
    c->ch_or_idx = tc_get_or_insert_chars_with_glyph(self->text_cache, &lc, g);
    c->ch_is_idx = true;
    if (lc.count == 1) r->bound_idx_plus_1[slot] = c->ch_or_idx + 1;
}

static bool
add_combining_chars(Screen *self, const char_type *chars, size_t num_chars, MulticellColumns cols, index_type y, MulticellRows *rows_of_char) {
    // Adds num_chars combining chars to the char whose cells in row y are in
    // the columns cols, as found by multicell_char_columns(), with a single
    // lookup in the text cache. When the char is a multicell char, its rows
    // are stored in rows_of_char, if not NULL.
    const index_type x = cols.start;
    CPUCell *cpu_cells = linebuf_cpu_cells_for_line(self->linebuf, y);
    CPUCell *cell = cpu_cells + x;
    if (!cell_has_text(cell) || (cell->is_multicell && cell->y)) return false; // don't allow adding combining chars to a null cell
    text_in_cell(cell, self->text_cache, self->lc);
    if (self->lc->count >= MAX_NUM_CODEPOINTS_PER_CELL) return false; // don't allow too many combining chars to prevent DoS attacks
    // must be computed before the char is changed
    const MulticellRows rows = cell->is_multicell ? multicell_char_rows(self, x, y) : (MulticellRows){0};
    // The text of a multicell char is in all its cells, so it can only be
    // changed if they are all present, rather than some of them being in the
    // overflow buffers of a smooth scroll region, which would leave cells
    // that no longer continue the char. A char cut off at the bottom of the
    // screen is fine, its rows below the screen are gone. Its top row is on
    // screen as cell->y is zero.
    if (cell->is_multicell && (!multicell_char_columns_are_complete(cpu_cells, cols) ||
                               (rows.limit - rows.start < (int)cell->scale && ssr_char_continues_into_overflow_below(self, cell, x, rows))))
        return false;
    num_chars = MIN(num_chars, MAX_NUM_CODEPOINTS_PER_CELL - self->lc->count);
    ensure_space_for_chars(self->lc, self->lc->count + num_chars);
    memcpy(self->lc->chars + self->lc->count, chars, num_chars * sizeof(chars[0]));
    self->lc->count += num_chars;
    // A glyph bound to the cell when it was printed stays bound
    cell->ch_or_idx = tc_get_or_insert_chars_with_glyph(self->text_cache, self->lc, cell_registered_glyph(cell, self->text_cache));
    cell->ch_is_idx = true;
    if (cell->is_multicell) {
        char_type ch_and_idx = cell->ch_and_idx;
        // the cell has y == 0 so rows.start == y, the lower rows can be cut off at the bottom of the screen
        for (int v = rows.start; v < rows.limit; v++) {
            cpu_cells = linebuf_cpu_cells_for_line(self->linebuf, v);
            for (index_type h = cols.start; h < cols.limit; h++) cpu_cells[h].ch_and_idx = ch_and_idx;
            linebuf_mark_line_dirty(self->linebuf, v);
        }
        if (rows_of_char) *rows_of_char = rows;
    } else {
        // The char can be on the row above the cursor, when the cursor is at
        // the start of a line that the char soft wrapped onto, and the text
        // loop only marks the cursor row dirty.
        linebuf_mark_line_dirty(self->linebuf, y);
    }
    return true;
}


static bool
has_multiline_cells_in_span(const CPUCell *cells, const index_type start, const index_type count) {
    for (index_type x = start; x < start + count; x++)
        if (cells[x].is_multicell && cells[x].y) return true;
    return false;
}

static void
nuke_multicell_chars_in_span(Screen *self, index_type start, index_type count) {
    // Remove all multicell chars intersecting the span of count cells at start
    // in the cursor line, so that the span can be overwritten without tearing them
    const CPUCell *cp = linebuf_cpu_cells_for_line(self->linebuf, self->cursor->y);
    for (index_type x = start; x < start + count; x++) {
        if (cp[x].is_multicell) nuke_multicell_char_at(self, x, self->cursor->y, cp[x].x != 0);
    }
}

static bool
linefeed_moves_to_new_line(const Screen *self) {
    // A linefeed scrolls when the cursor is on the bottom margin and otherwise
    // moves the cursor down, unless it is on the last line, below the bottom margin
    return self->cursor->y == self->margin_bottom || self->cursor->y + 1 < self->lines;
}

static bool
move_cursor_past_multicell(Screen *self, index_type required_width) {
    // Move the cursor to the first place at or after it where there are
    // required_width cells free of the lower rows of multiline chars, removing
    // any other multicell chars in those cells.
    if (required_width > self->columns) return false;
    while (true) {
        CPUCell *cp = linebuf_cpu_cells_for_line(self->linebuf, self->cursor->y);
        while (self->cursor->x + required_width <= self->columns) {
            if (!has_multiline_cells_in_span(cp, self->cursor->x, required_width)) {
                nuke_multicell_chars_in_span(self, self->cursor->x, required_width);
                return true;
            }
            self->cursor->x++;
        }
        if ((self->modes.mDECAWM || has_multiline_cells_in_span(cp, self->columns - required_width, required_width)) && linefeed_moves_to_new_line(self)) {
            continue_to_next_line(self);
        } else {
            // Either there is no auto wrap or there is no new line to move to,
            // as the cursor is on the last line below the bottom margin, so
            // make space at the end of the line
            self->cursor->x = self->columns - required_width;
            nuke_multicell_chars_in_span(self, self->cursor->x, required_width);
            return true;
        }
    }
}

static void
move_widened_char_past_multiline_chars(Screen *self, text_loop_state *s, CPUCell *cpu_cell, index_type xpos, index_type ypos) {
    index_type before = self->cursor->y;
    // Remove the char from its current cell before moving it, so that it is
    // not removed as a multicell char in the way and the cells it is moved to
    // can include its current cell
    const CPUCell c = *cpu_cell;
    *cpu_cell = (CPUCell){0};
    // Taken before the move, which can scroll the char's row up
    const bool may_reorder = self->linebuf->line_attrs[ypos].bidi_may_reorder;
    self->cursor->x = xpos;
    self->cursor->y = ypos;
    if (move_cursor_past_multicell(self, 2)) {
        CPUCell *cp;
        linebuf_init_cells(self->linebuf, self->cursor->y, &cp, NULL);
        linebuf_mark_line_dirty(self->linebuf, self->cursor->y);
        if (UNLIKELY(self->linebuf->bidi_stamped)) {
            bidi_line_gets_text(self, self->cursor->y);
            self->linebuf->line_attrs[self->cursor->y].bidi_may_reorder |= may_reorder;
        }
        cp[self->cursor->x] = c;
        self->cursor->x++;
        cp[self->cursor->x] = c;
        cp[self->cursor->x].x = 1;
        self->cursor->x++;
    }
    // A move from the bottom row scrolls, leaving the cursor on the same row number with s->cp pointing at the row above it
    if (self->cursor->y == before && linebuf_cpu_cells_for_line(self->linebuf, before) == s->cp) init_segmentation_state(self, s);
    else init_text_loop_line(self, s);
}

static void
widen_cell_to_two(Screen *self, text_loop_state *s, CPUCell *cp, index_type xpos) {
    CPUCell *cpu_cell = cp + xpos;
    cpu_cell->is_multicell = true;
    cpu_cell->width = 2;
    cpu_cell->natural_width = true;
    if (!cpu_cell->scale) cpu_cell->scale = 1;
    if (xpos + 1 < self->columns) {
        CPUCell *second = cp + xpos + 1;
        if (second->is_multicell) {
            if (second->y) {
                move_widened_char_past_multiline_chars(self, s, cpu_cell, xpos, s->prev.y);
                return;
            }
            nuke_multicell_char_at(self, xpos + 1, s->prev.y, false);
        }
        // both halves of the widened char have the style of the original cell
        self->cursor->x++;
        *second = *cpu_cell;
        second->x = 1;
    } else {
        move_widened_char_past_multiline_chars(self, s, cpu_cell, xpos, s->prev.y);
    }
}

static bool
is_emoji_presentation_base(char_type ch) {
    return char_props_for(ch).is_emoji_presentation_base == 1;
}

static void
draw_combining_char(Screen *self, text_loop_state *s, char_type ch) {
    CPUCell *cp;
    linebuf_init_cells(self->linebuf, s->prev.y, &cp, NULL);
    // the extent of the char is found once, and used for both adding the char and halving its width
    const MulticellColumns cols = multicell_char_columns(cp, self->columns, s->prev.x);
    const index_type xpos = cols.start;
    MulticellRows rows = {0};
    if (!add_combining_chars(self, &ch, 1, cols, s->prev.y, &rows) || self->lc->count < 2) return;
    unsigned base_pos = self->lc->count - 2;
    if (ch == VS16) { // emoji presentation variation marker makes default text presentation emoji (narrow emoji) into wide emoji
        if (self->lc->chars[base_pos + 1] == VS16 && !cp[xpos].is_multicell && is_emoji_presentation_base(self->lc->chars[base_pos])) {
            widen_cell_to_two(self, s, cp, xpos);
        }
    } else if (ch == VS15) {
        const CPUCell *cpu_cell = cp + xpos;
        // natural_width is false when the width was set explicitly by the text sizing
        // protocol, in which case the application's width wins over the variation selector,
        // matching how VS16 and Thai/Lao SARA AM leave such cells alone.
        if (self->lc->chars[base_pos + 1] == VS15 && cpu_cell->is_multicell && cpu_cell->natural_width && cpu_cell->width == 2 &&
            is_emoji_presentation_base(self->lc->chars[base_pos])) {
            const index_type old_limit = xpos + cpu_cell->scale * cpu_cell->width;
            const index_type new_limit = old_limit - (cpu_cell->scale * cpu_cell->width) / 2;
            halve_multicell_width(self, cols, rows, s->prev.y);
            // The cursor only needs to move if it is on the same line as the
            // narrowed char, the char can also be on the previous line when the
            // cursor is at the start of a line that the char soft wrapped onto.
            if (self->cursor->y == s->prev.y && self->cursor->x > new_limit) {
                if (self->cursor->x >= old_limit) self->cursor->x -= old_limit - new_limit;
                else self->cursor->x = new_limit;
            }
            init_segmentation_state(self, s);
        }
    } else if (s->seg.grapheme_break == GBP_SpacingMark && !cp[xpos].is_multicell && wcwidth_std(char_props_for(ch)) > 0) {
        // Thai/Lao SARA AM is a SpacingMark with non-zero width, it widens a narrow base cell.
        // s->seg was just stepped with ch, and grapheme_segmentation_step() copies the
        // grapheme break property of ch into it, so no extra char_props_for() lookup is
        // needed to reject the overwhelmingly common case of a zero width combining char.
        widen_cell_to_two(self, s, cp, xpos);
    }
}

static void
screen_on_input(Screen *self) {
    if (self->track_activity && !self->has_activity_since_last_focus && !self->has_focus && self->callbacks != Py_None) {
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
    switch (which) {
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
    switch (which) {
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

static bool batched_non_ascii_draw_disabled_for_tests = false;

static bool
is_plain_combining_char(char_type ch, GraphemeSegmentationResult seg, CharProps props) {
    // A combining char that only adds to the text of a cell, see draw_combining_char()
    return ch != VS15 && ch != VS16 && !(seg.grapheme_break == GBP_SpacingMark && wcwidth_std(props) > 0);
}

static inline __attribute__((always_inline)) size_t
draw_combining_char_run_(Screen *self, text_loop_state *s, char_type ch, CharProps props, const uint32_t *rest, size_t num_rest) {
    // ch has been through grapheme segmentation, which added it to the previous
    // cell. Plain combining chars directly following it are added along with it,
    // with a single lookup in the text cache, rather than one for each char.
    // Returns the number of chars from rest that were drawn.
#define MAX_RUN 32u
    char_type run[MAX_RUN];
    size_t n = 0;
    GraphemeSegmentationResult seg = s->seg;
    if (!batched_non_ascii_draw_disabled_for_tests && is_plain_combining_char(ch, seg, props)) {
        run[n++] = ch;
        for (size_t k = 0; k < num_rest && n < MAX_RUN; k++) {
            const char_type c = map_char(self, rest[k]);
            const CharProps p = char_props_for(c);
            if (p.is_invalid) break;
            const GraphemeSegmentationResult next = grapheme_segmentation_step(seg, p);
            if (!next.add_to_current_cell || !is_plain_combining_char(c, next, p)) break;
            seg = next;
            run[n++] = c;
        }
    }
#undef MAX_RUN
    if (n < 2) {
        draw_combining_char(self, s, ch);
        return 0;
    }
    CPUCell *cp;
    linebuf_init_cells(self->linebuf, s->prev.y, &cp, NULL);
    add_combining_chars(self, run, n, multicell_char_columns(cp, self->columns, s->prev.x), s->prev.y, NULL);
    s->seg = seg;
    return n - 1;
}

static size_t
draw_combining_char_run(Screen *self, text_loop_state *s, char_type ch, CharProps props, const uint32_t *rest, size_t num_rest) {
    return draw_combining_char_run_(self, s, ch, props, rest, num_rest);
}

static size_t
draw_combining_char_run_implicit(Screen *self, text_loop_state *s, char_type ch, CharProps props, const uint32_t *rest, size_t num_rest, uint8_t record) {
    const char_type before = s->prev.cc->ch_and_idx;
    const size_t n = draw_combining_char_run_(self, s, ch, props, rest, num_rest);
    bool may_reorder = bidi_char_sets_may_reorder(ch);
    for (size_t i = 0; i < n && !may_reorder; i++) may_reorder = bidi_char_sets_may_reorder(map_char(self, rest[i]));
    record_combining_write(self, s, before, record, may_reorder);
    return n;
}

static void
draw_control_char(Screen *self, text_loop_state *s, uint32_t ch) {
    switch (ch) {
        case BEL: screen_bell(self); break;
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
                } else if (self->columns > 0) {
                    self->cursor->x = self->columns - 1;
                    if (s->cp[self->cursor->x].is_multicell) {
                        if (s->cp[self->cursor->x].y) {
                            // The move can go to another row or scroll
                            move_cursor_past_multicell(self, 1);
                            init_text_loop_line(self, s);
                        } else replace_multicell_char_under_cursor_with_spaces(self);
                    }
                    screen_tab(self);
                }
            } else screen_tab(self);
            init_segmentation_state(self, s);
            break;
        case SI: screen_change_charset(self, 0); break;
        case SO: screen_change_charset(self, 1); break;
        case LF:
        case VT:
        case FF: {
            // When the cursor is on the bottom margin, the line feed scrolls
            // and the cursor ends up on the bottom line, which is cleared
            const bool scrolls = self->cursor->y == self->margin_bottom;
            screen_linefeed(self);
            init_text_loop_line(self, s);
            s->line_has_no_multicell = scrolls && self->cursor->y == self->margin_bottom;
        } break;
        case CR:
            screen_carriage_return(self);
            init_segmentation_state(self, s);
            break;
        default: break;
    }
    if (ch != LF && ch != VT && ch != FF && ch != CR && ch != HT) s->line_has_no_multicell = false;
}

static_assert(sizeof(CPUCell) == 3 * sizeof(uint32_t), "draw_non_ascii_run() needs updating");

static inline uint32_t
cell_word(const CPUCell *c, unsigned which) {
    uint32_t ans;
    memcpy(&ans, (const uint8_t *)c + which * sizeof(ans), sizeof(ans));
    return ans;
}

static inline uint64_t
pack_cell_words(uint32_t first, uint32_t second) {
    // Two consecutive 32 bit words of cell memory as one 64 bit value
#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
    return first | ((uint64_t)second << 32);
#else
    return ((uint64_t)first << 32) | second;
#endif
}

// The words of the two cells of a wide char except their first words, which are the char
typedef struct WideCellWords {
    uint32_t first1, first2;
    uint64_t second12;
} WideCellWords;

static inline WideCellWords
wide_cell_words(const CPUCell *cc) {
    // Built from constants, as building cells with bitfield assignments makes
    // compilers do partial stores to the stack and reload them with wider loads,
    // which stall on store forwarding. Only the hyperlink and style are taken from cc.
    static const CPUCell first = {.is_multicell = true, .width = 2, .scale = 1, .natural_width = true};
    static const CPUCell second = {.is_multicell = true, .width = 2, .scale = 1, .natural_width = true, .x = 1};
    static const CPUCell hyperlink = {.hyperlink_id = (hyperlink_id_type)~0u, .style_idx = MAX_NUM_OF_STYLES - 1};
#define W(cell, which) cell_word(cell, which)
#define HL(which) (W(cc, which) & W(&hyperlink, which))
    return (WideCellWords){
        .first1 = W(&first, 1) | HL(1),
        .first2 = W(&first, 2) | HL(2),
        .second12 = pack_cell_words(W(&second, 1) | HL(1), W(&second, 2) | HL(2)),
    };
#undef HL
#undef W
}

static inline void
write_wide_cells(CPUCell *dest, char_type ch, const WideCellWords *w) {
    // Writes the two cells of a wide char as 64 bit values built in registers
    const uint32_t ch_word = ch & 0x7fffffff;
    const uint64_t first = pack_cell_words(ch_word, w->first1), second = pack_cell_words(w->first2, ch_word);
    uint8_t *d = (uint8_t *)dest;
    memcpy(d, &first, sizeof(first));
    memcpy(d + sizeof(first), &second, sizeof(second));
    memcpy(d + 2 * sizeof(first), &w->second12, sizeof(w->second12));
}

// Not inlined, so that it gets its own register allocation rather than competing
// with the rest of draw_text_loop_() for registers. It is called once per run.
__attribute__((noinline)) static size_t
draw_non_ascii_run(Screen *self, text_loop_state *s, const uint32_t *chars, size_t num_chars) {
    // Batched fast path: draw a run of non-ASCII chars each of which starts a new cell
    // of width one or two in the current line, keeping all state in locals so it is
    // not reloaded for every char. Stops at the first char needing the scalar path:
    // ASCII, invalid, zero width, a char that combines with the previous cell, the
    // image placeholder, a glyph protocol codepoint, a char that does not fit in the
    // line or an existing multicell cell. The caller must ensure there is no charset translation or insert mode and
    // that the cursor is within the line. Returns the number of chars drawn.
    const index_type columns = self->columns;
    index_type x = self->cursor->x, last_x = x;
    CPUCell *cp = s->cp;
    // Cells are written from these templates as 64 bit values built in registers.
    // The first word of a cell is its char. Assembling cells as CPUCell values or
    // word arrays makes compilers build them on the stack with partial stores and
    // reload them with wider loads, which stall on store forwarding.
    // The words are kept in scalars rather than arrays, which compilers place on
    // the stack. The first word of a cell is its char, written separately.
    const uint32_t narrow1 = cell_word(&s->cc, 1), narrow2 = cell_word(&s->cc, 2);
    const WideCellWords wide = wide_cell_words(&s->cc);
    GraphemeSegmentationResult seg = s->seg;
    // The segmentation step depends only on the current state and the grapheme
    // segmentation property of the char, and in a run of text the same pair
    // repeats, so cache the last step. This breaks the chain of dependent table
    // lookups that otherwise links every char to the previous one.
    uint32_t cached_seg_key = UINT32_MAX;
    GraphemeSegmentationResult cached_seg = {0};
    size_t i = 0;
    for (; i < num_chars; i++) {
        const char_type ch = chars[i];
        if (ch < DEL || ch == IMAGE_PLACEHOLDER_CHAR || is_glyph_block_codepoint(ch)) break;
        const CharDrawInfo info = char_draw_info_for(ch);
        const index_type width = info.cells;
        if (width == 0 || x + width > columns || cp[x].is_multicell) break;
        if (width == 2 && cp[x + 1].is_multicell) break;
        const uint32_t seg_key = ((uint32_t)seg.val << 8) | info.grapheme_segmentation_property;
        if (seg_key != cached_seg_key) {
            cached_seg = grapheme_segmentation_step_for_property(seg, info.grapheme_segmentation_property);
            cached_seg_key = seg_key;
        }
        if (cached_seg.add_to_current_cell) break;
        seg = cached_seg;
        last_x = x;
        const uint32_t ch_word = ch & 0x7fffffff;
        uint8_t *dest = (uint8_t *)(cp + x);
        if (width == 1) {
            const uint64_t first = pack_cell_words(ch_word, narrow1);
            memcpy(dest, &first, sizeof(first));
            memcpy(dest + sizeof(first), &narrow2, sizeof(narrow2));
            x++;
        } else {
            write_wide_cells(cp + x, ch, &wide);
            x += 2;
        }
    }
    if (i) {
        self->cursor->x = x;
        self->last_graphic_char = chars[i - 1];
        s->seg = seg;
        s->prev.y = self->cursor->y;
        s->prev.x = last_x;
        s->prev.cc = cp + last_x;
    }
    return i;
}

static inline __attribute__((always_inline)) void
draw_text_loop_(Screen *self, const uint32_t *chars, size_t num_chars, text_loop_state *s, const bool implicit, const uint8_t record) {
    init_text_loop_line(self, s);
    if (implicit) draw_loop_line_gets_text(self, self->cursor->y);
    int char_width;
#define TEMPLATE_CELLS 16
    CPUCell cpu_template[TEMPLATE_CELLS];
    bool templates_initialized = false;
    for (size_t i = 0; i < num_chars; i++) {
        uint32_t ch = map_char(self, chars[i]);
        if (ch < DEL && s->seg.grapheme_break <= GBP_None) { // fast path for printable ASCII
            if (ch < ' ') {
                // A control char that leaves the cursor on its row stores no text there, or a tab cell after the line's check; a
                // line feed that scrolls leaves the cursor on a cleared line
                const index_type y = self->cursor->y;
                draw_control_char(self, s, ch);
                if (implicit && self->cursor->y != y) draw_loop_line_gets_text(self, self->cursor->y);
                continue;
            }
            if (LIKELY(!self->charset.current && !self->modes.mIRM && self->cursor->x < self->columns)) {
                // Batched fast path: write a run of printable ASCII chars into the
                // current line in one go, keeping all state in locals so it is not
                // reloaded for every char. Stops at the first char needing the
                // scalar path: non-ASCII, control char or an existing multicell cell.
                const size_t limit = MIN(num_chars - i, (size_t)(self->columns - self->cursor->x));
                CPUCell *cp = s->cp + self->cursor->x;
                size_t n = printable_ascii_run_length(chars + i, limit);
                // clamp the run at the first multicell cell, it needs the scalar path
                if (!s->line_has_no_multicell) {
                    size_t m = 0;
                    while (m + 4 <= n && !(cp[m].is_multicell | cp[m + 1].is_multicell | cp[m + 2].is_multicell | cp[m + 3].is_multicell)) m += 4;
                    while (m < n && !cp[m].is_multicell) m++;
                    n = m;
                }
                if (n) {
                    const CPUCell cc = s->cc;
                    // fill full blocks of cells from templates, the constant sized
                    // memcpy is inlined by the compiler as wide stores, the chars
                    // then need only a single 32-bit store per cell
                    if (n >= TEMPLATE_CELLS / 4 && !templates_initialized) {
                        templates_initialized = true;
                        for (unsigned k = 0; k < TEMPLATE_CELLS; k++) cpu_template[k] = cc;
                    }
#define copy_template(dest, template, elem)                                                                \
    {                                                                                                      \
        j = 0;                                                                                             \
        for (; j + TEMPLATE_CELLS <= n; j += TEMPLATE_CELLS) memcpy(dest + j, template, sizeof(template)); \
        if (j + TEMPLATE_CELLS / 2 <= n) {                                                                 \
            memcpy(dest + j, template, sizeof(template) / 2);                                              \
            j += TEMPLATE_CELLS / 2;                                                                       \
        }                                                                                                  \
        if (j + TEMPLATE_CELLS / 4 <= n) {                                                                 \
            memcpy(dest + j, template, sizeof(template) / 4);                                              \
            j += TEMPLATE_CELLS / 4;                                                                       \
        }                                                                                                  \
        for (; j < n; j++) dest[j] = elem;                                                                 \
    }
                    size_t j;
                    copy_template(cp, cpu_template, cc);
#undef copy_template
                    for (j = 0; j < n; j++) cell_set_char(cp + j, chars[i + j]);
                    self->last_graphic_char = chars[i + n - 1];
                    s->prev.y = self->cursor->y;
                    s->prev.x = self->cursor->x + n - 1;
                    s->prev.cc = cp + n - 1;
                    self->cursor->x += n;
                    if (implicit) record_written_line(self, self->cursor->y, record);
                    s->seg = (GraphemeSegmentationResult){.grapheme_break = GBP_None};
                    i += n - 1;
                    continue;
                }
                // n == 0: the cell under the cursor is a multicell, let the scalar path handle it
            }
            char_width = 1;
            s->seg = (GraphemeSegmentationResult){.grapheme_break = GBP_None};
            s->line_has_no_multicell = false;
        } else {
            s->line_has_no_multicell = false;
            if (ch > DEL && LIKELY(!self->charset.current && !self->modes.mIRM && self->cursor->x < self->columns) &&
                !batched_non_ascii_draw_disabled_for_tests) {
                const size_t n = draw_non_ascii_run(self, s, chars + i, num_chars - i);
                if (n) {
                    if (implicit) {
                        record_written_line(self, self->cursor->y, record);
                        bidi_note_run(self, self->cursor->y);
                    }
                    i += n - 1;
                    continue;
                }
            }
            CharProps cp = char_props_for(ch);
            if (cp.is_invalid) {
                if (ch < ' ') {
                    const index_type y = self->cursor->y;
                    draw_control_char(self, s, ch);
                    if (implicit && self->cursor->y != y) draw_loop_line_gets_text(self, self->cursor->y);
                }
                continue;
            }
            s->seg = grapheme_segmentation_step(s->seg, cp);
            if (UNLIKELY(s->seg.add_to_current_cell && s->prev.cc)) {
                if (implicit) i += draw_combining_char_run_implicit(self, s, ch, cp, chars + i + 1, num_chars - i - 1, record);
                else i += draw_combining_char_run(self, s, ch, cp, chars + i + 1, num_chars - i - 1);
                continue;
            }
            char_width = wcwidth_std(cp);
            if (UNLIKELY(char_width < 1)) {
                if (char_width == 0) {
                    // Preserve zero width chars as combining chars even though
                    // they were not added to the prev cell by grapheme segmentation.
                    // Zero width chars can only be represented as combining chars.
                    if (s->prev.cc) {
                        const char_type before = s->prev.cc->ch_and_idx;
                        draw_combining_char(self, s, ch);
                        if (implicit) record_combining_write(self, s, before, record, bidi_char_sets_may_reorder(ch));
                    } else if (implicit && (ch | 1) == 0x200f) { // LRM, RLM
                        set_record_at_leading_mark(self, ch, record);
                    }
                    continue;
                }
                char_width = 1;
            }
        }

        if (self->cursor->x < self->columns && s->cp[self->cursor->x].is_multicell) {
            if (s->cp[self->cursor->x].y) {
                move_cursor_past_multicell(self, 1);
                reinit_text_loop_line(self, s);
                if (implicit) draw_loop_line_gets_text(self, self->cursor->y);
            } else nuke_multicell_char_at(self, self->cursor->x, self->cursor->y, s->cp[self->cursor->x].x != 0);
        }

        self->last_graphic_char = ch;
        if (UNLIKELY(self->columns < self->cursor->x + (unsigned int)char_width)) {
            if ((unsigned)char_width > self->columns) continue; // discard too wide character
            if (self->modes.mDECAWM) {
                continue_to_next_line(self);
                reinit_text_loop_line(self, s);
                if (implicit) draw_loop_line_gets_text(self, self->cursor->y);
            } else self->cursor->x = self->columns - char_width;
            CPUCell *c = &s->cp[self->cursor->x];
            if (c->is_multicell) {
                if (c->y) {
                    // this also removes the multicell chars in the cells the char will occupy
                    move_cursor_past_multicell(self, char_width);
                    reinit_text_loop_line(self, s);
                    if (implicit) draw_loop_line_gets_text(self, self->cursor->y);
                } else nuke_multicell_char_at(self, self->cursor->x, self->cursor->y, c->x > 0);
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
                    reinit_text_loop_line(self, s);
                    if (implicit) draw_loop_line_gets_text(self, self->cursor->y);
                    fc = s->cp + self->cursor->x;
                    second = fc + 1;
                } else nuke_multicell_char_at(self, self->cursor->x + 1, self->cursor->y, true);
            }
            const WideCellWords wide = wide_cell_words(&s->cc);
            write_wide_cells(fc, ch, &wide);
            s->prev.y = self->cursor->y;
            s->prev.x = self->cursor->x;
            s->prev.cc = fc;
            self->cursor->x += 2;
        } else {
            *fc = s->cc;
            cell_set_char(fc, ch);
            if (UNLIKELY(is_glyph_block_codepoint(ch))) bind_registered_glyph(self, fc, ch);
            s->prev.y = self->cursor->y;
            s->prev.x = self->cursor->x;
            s->prev.cc = fc;
            self->cursor->x++;
            fc->is_multicell = false;
        }
        if (implicit) {
            record_written_line(self, s->prev.y, record);
            LineAttrs *a = self->linebuf->line_attrs + s->prev.y;
            if (!a->bidi_may_reorder && bidi_codepoint_may_reorder(ch)) a->bidi_may_reorder = true;
        }
    }
#undef init_line
#undef TEMPLATE_CELLS
}

#define PREPARE_FOR_DRAW_TEXT                                                                                         \
    if (tc_should_gc(self->text_cache)) screen_garbage_collect_text_cache(self);                                      \
    if (style_table_needs_gc(self->style_table)) screen_garbage_collect_style_table(self);                            \
    const bool force_underline = OPT(underline_hyperlinks) == UNDERLINE_ALWAYS && self->active_hyperlink_id != 0;     \
    CellStyle draw_style = self->cursor->style;                                                                       \
    uint32_t draw_style_idx;                                                                                          \
    if (force_underline) {                                                                                            \
        draw_style.attrs.decoration = OPT(url_style);                                                                 \
        draw_style.decoration_fg = ((OPT(url_color) & COL_MASK) << 8) | 2;                                            \
        draw_style_idx = style_table_intern_cached(self->style_table, &draw_style, &self->hyperlink_style_idx_cache); \
    } else draw_style_idx = screen_cursor_style_idx(self);                                                            \
    text_loop_state s = {                                                                                             \
        .cc = (CPUCell){.hyperlink_id = self->active_hyperlink_id, .style_idx = draw_style_idx},                      \
    };

static void
draw_text(Screen *self, const uint32_t *chars, size_t num_chars) {
    PREPARE_FOR_DRAW_TEXT;
    self->is_dirty = true;
    draw_text_loop_(self, chars, num_chars, &s, false, 0);
}

// Text records each line it is written to, with the empty record when bidi mode is off or under force_ltr, and drops a record
// its line kept while it held no text
static void
draw_text_implicit(Screen *self, const uint32_t *chars, size_t num_chars) {
    PREPARE_FOR_DRAW_TEXT;
    self->is_dirty = true;
    draw_text_loop_(self, chars, num_chars, &s, true, current_bidi_record(self).val);
}

static void
draw_text_in_mode(Screen *self, const uint32_t *chars, size_t num_chars) {
#ifdef DEBUG
    if ((self->modes.mBDSM || self->linebuf->bidi_stamped) && !self->bidi_records_writes) fatal("bidi: writes that must be recorded take the plain draw loop");
#endif
    if (UNLIKELY(self->bidi_records_writes)) draw_text_implicit(self, chars, num_chars);
    else draw_text(self, chars, num_chars);
}

void
screen_draw_text(Screen *self, const uint32_t *chars, size_t num_chars) {
    screen_on_input(self);
    draw_text_in_mode(self, chars, num_chars);
}

static void
draw_codepoint(Screen *self, char_type ch) {
    uint32_t lch = self->last_graphic_char;
    draw_text(self, &ch, 1);
    self->last_graphic_char = lch;
}

void
screen_align(Screen *self) {
    if (UNLIKELY(self->smooth_scroll.count)) ssr_screen_erased(self);
    self->margin_top = 0;
    self->margin_bottom = self->lines - 1;
    screen_cursor_position(self, 1, 1);
    linebuf_clear(self->linebuf, 'E');
    bidi_note_maybe_unstamp(self->linebuf);
}

static size_t
decode_utf8_safe_string(const uint8_t *src, size_t sz, uint32_t *dest) {
    // dest must be an array of size at least sz
    uint32_t codep = 0;
    UTF8State state = 0, prev = UTF8_ACCEPT;
    size_t i = 0, d = 0;
    for (; i < sz; i++) {
        switch (decode_utf8(&state, &codep, src[i])) {
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

static bool
multicell_may_reorder(unsigned scale, const ListOfChars *lc) {
    if (scale > 1) return true;
    for (size_t i = 0; i < lc->count; i++) {
        if (bidi_char_sets_may_reorder(lc->chars[i])) return true;
    }
    return false;
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
    mcd.style_idx = s.cc.style_idx;
    cell_set_chars(&mcd, self->text_cache, lc);
    if (lc->count && is_glyph_block_codepoint(lc->chars[0])) bind_registered_glyph(self, &mcd, lc->chars[0]);
    // The rows the char is written to are checked before the multicell chars in its way are removed: a row whose text the char
    // replaces keeps its record
    const index_type first_row = self->cursor->y;
    if (UNLIKELY(self->linebuf->bidi_stamped)) {
        for (index_type y = first_row; y < MIN(first_row + height, self->lines); y++) bidi_line_gets_text(self, y);
    }
    move_cursor_past_multicell(self, width);
    const bool moved_to_other_rows = self->cursor->y != first_row;
    if (height > 1) {
        if (self->cursor->y <= self->margin_bottom) {
            index_type available_height = self->margin_bottom - self->cursor->y + 1;
            if (height > available_height) {
                index_type extra_lines = height - available_height;
                screen_scroll(self, extra_lines);
                self->cursor->y -= extra_lines;
            }
        } else {
            // Cursor is below the scroll region, which cannot be scrolled, so
            // move the cursor up until the cell fits on screen. height <=
            // max_height <= lines so this cannot underflow.
            index_type available_height = self->lines - self->cursor->y;
            if (height > available_height) self->cursor->y -= height - available_height;
        }
    }
    if (self->modes.mIRM) {
        for (index_type y = self->cursor->y; y < self->cursor->y + height; y++) {
            if (self->modes.mIRM) insert_characters(self, self->cursor->x, width, y, true);
        }
    }
    // Only a record written in bidi mode sets the flag, so with the mode off it cannot change in the loop
    const bool records_rows = self->modes.mBDSM || self->linebuf->bidi_stamped;
    const bool may_reorder = UNLIKELY(records_rows) && multicell_may_reorder(mcd.scale, lc);
    for (index_type y = self->cursor->y; y < self->cursor->y + height; y++) {
        linebuf_init_cells(self->linebuf, y, &s.cp, NULL);
        linebuf_mark_line_dirty(self->linebuf, y);
        if (UNLIKELY(records_rows)) {
            if (self->linebuf->bidi_stamped && moved_to_other_rows) bidi_line_gets_text(self, y);
            // The first record written to a buffer is written while its flag is still unset
            record_written_line(self, y, current_bidi_record(self).val);
            bidi_note_may_reorder(self, y, may_reorder);
        }
        mcd.x = 0;
        mcd.y = y - self->cursor->y;
        for (index_type x = self->cursor->x; x < self->cursor->x + width; x++, mcd.x++) {
            if (s.cp[x].is_multicell) nuke_multicell_char_at(self, x, y, s.cp[x].x + s.cp[x].y > 0);
            s.cp[x] = mcd;
        }
    }
    self->cursor->x += width;
    self->is_dirty = true;
}

static void
handle_variable_width_multicell_command(Screen *self, CPUCell mcd, ListOfChars *lc) {
    ensure_space_for_chars(lc, lc->count + 1);
    lc->chars[lc->count] = 0;
    mcd.width = wcswidth_string(lc->chars);
    if (!mcd.width) {
        lc->count = 0;
        return;
    }
    handle_fixed_width_multicell_command(self, mcd, lc);
}

void
screen_handle_multicell_command(Screen *self, const MultiCellCommand *cmd, const uint8_t *payload) {
    screen_on_input(self);
    if (!cmd->payload_sz) return;
    ensure_space_for_chars(self->lc, cmd->payload_sz + 1);
    self->lc->count = decode_utf8_safe_string(payload, cmd->payload_sz, self->lc->chars);
    if (!self->lc->count) return;
#define M(x) ((1u << x) - 1u)
    CPUCell mcd = {
        .width = MIN(cmd->width, M(WIDTH_BITS)),
        .scale = MAX(1u, MIN(cmd->scale, M(SCALE_BITS))),
        .subscale_n = MIN(cmd->subscale_n, M(SUBSCALE_BITS)),
        .subscale_d = MIN(cmd->subscale_d, M(SUBSCALE_BITS)),
        .valign = MIN(cmd->vertical_align, M(VALIGN_BITS)),
        .halign = MIN(cmd->horizontal_align, M(HALIGN_BITS)),
        .is_multicell = true};
#undef M
    if (mcd.scale > 1) self->multiline_chars_used = true;
    if (mcd.width) handle_fixed_width_multicell_command(self, mcd, self->lc);
    else {
        RAII_ListOfChars(lc);
        GraphemeSegmentationResult s;
        grapheme_segmentation_reset(&s);
        mcd.natural_width = true;
        for (unsigned i = 0; i < self->lc->count; i++) {
            char_type ch = self->lc->chars[i];
            CharProps cp = char_props_for(ch);
            if (cp.is_invalid) continue;
            if ((s = grapheme_segmentation_step(s, cp)).add_to_current_cell || (wcwidth_std(cp) == 0 && lc.count)) {
                ensure_space_for_chars(&lc, lc.count + 1);
                lc.chars[lc.count++] = ch;
            } else {
                if (lc.count) handle_variable_width_multicell_command(self, mcd, &lc);
                switch (wcwidth_std(cp)) {
                    case 0:
                    case -1: lc.count = 0; break;
                    default:
                        lc.chars[0] = ch;
                        lc.count = 1;
                        break;
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
    if (UNLIKELY(self->smooth_scroll.count)) ssr_screen_erased(self);
    screen_cursor_position(self, 1, 1);
    self->margin_top = 0;
    self->margin_bottom = self->lines - 1;
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
            region.top += self->margin_top;
            region.bottom += self->margin_top;
        }
        region.left -= 1;
        region.top -= 1;
        region.right -= 1;
        region.bottom -= 1; // switch to zero based indexing
        if (self->modes.mDECSACE) {
            index_type x = MIN(region.left, self->columns - 1);
            index_type num = region.right >= x ? region.right - x + 1 : 0;
            num = MIN(num, self->columns - x);
            for (index_type y = region.top; y < MIN(region.bottom + 1, self->lines); y++) {
                linebuf_init_line(self->linebuf, y);
                apply_sgr_to_cells(self->style_table, self->linebuf->line->cpu_cells + x, num, params, count, is_group);
            }
        } else {
            index_type x, num;
            if (region.top == region.bottom) {
                if (region.top < self->lines) {
                    linebuf_init_line(self->linebuf, region.top);
                    x = MIN(region.left, self->columns - 1);
                    num = region.right >= x ? region.right - x + 1 : 0;
                    num = MIN(self->columns - x, num);
                    apply_sgr_to_cells(self->style_table, self->linebuf->line->cpu_cells + x, num, params, count, is_group);
                }
            } else {
                for (index_type y = region.top; y < MIN(region.bottom + 1, self->lines); y++) {
                    if (y == region.top) {
                        x = MIN(region.left, self->columns - 1);
                        num = self->columns - x;
                    } else if (y == region.bottom) {
                        x = 0;
                        num = MIN(region.right + 1, self->columns);
                    } else {
                        x = 0;
                        num = self->columns;
                    }
                    linebuf_init_line(self->linebuf, y);
                    apply_sgr_to_cells(self->style_table, self->linebuf->line->cpu_cells + x, num, params, count, is_group);
                }
            }
        }
    } else {
        cursor_from_sgr(self->cursor, params, count, is_group);
        self->sgr_blink_was_used |= self->cursor->style.attrs.blink;
    }
}

static void
write_to_test_child(Screen *self, const char *data, size_t sz) {
    PyObject *r = PyObject_CallMethod(self->test_child, "write", "y#", data, sz);
    if (r == NULL) PyErr_Print();
    Py_CLEAR(r);
}

static bool
write_to_child(Screen *self, const char *data, size_t sz) {
    bool written = false;
    if (self->window_id) written = schedule_write_to_child(self->window_id, 1, data, sz);
    if (self->test_child != Py_None) { write_to_test_child(self, data, sz); }
    return written;
}

static void
get_prefix_and_suffix_for_escape_code(unsigned char which, const char **prefix, const char **suffix) {
    *suffix = "\033\\";
    switch (which) {
        case ESC_DCS: *prefix = "\033P"; break;
        case ESC_CSI:
            *prefix = "\033[";
            *suffix = "";
            break;
        case ESC_OSC: *prefix = "\033]"; break;
        case ESC_PM: *prefix = "\033^"; break;
        case ESC_APC: *prefix = "\033_"; break;
        default: fatal("Unknown escape code to write: %u", which);
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

static void
send_visibility_report(Screen *self) {
    write_escape_code_to_child(self, ESC_CSI, self->visibility_state != 2 ? "?999;1n" : "?999;2n");
}

void
screen_visibility_changed(Screen *self, bool potentially_visible) {
    const uint8_t state = potentially_visible ? 1 : 2;
    if (self->visibility_state != state) {
        self->visibility_state = state;
        if (self->modes.mVISIBILITY_REPORTS) send_visibility_report(self);
    }
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

static inline void
reset_pixel_scroll(Screen *self, unsigned val) {
    self->pixel_scroll_offset_y = val;
}


// Remove all cell images from a portion of the screen and mark lines that
// contain image placeholders as dirty to make sure they are redrawn. This is
// needed when we perform commands that may move some lines without marking them
// as dirty (like screen_insert_lines) and at the same time don't move image
// references (i.e. unlike screen_scroll, which moves everything).
static void
screen_dirty_line_graphics(Screen *self, const unsigned int top, const unsigned int bottom, const bool main_buf) {
    bool need_to_remove = false;
    const unsigned int limit = MIN(bottom + 1, self->lines);
    LineBuf *linebuf = main_buf ? self->main_linebuf : self->alt_linebuf;
    for (unsigned int y = top; y < limit; y++) {
        if (linebuf->line_attrs[y].has_image_placeholders) {
            need_to_remove = true;
            linebuf_mark_line_dirty(linebuf, y);
            self->is_dirty = true;
        }
    }
    if (need_to_remove) {
        CellImageRegionRows kept[MAX_SMOOTH_SCROLL_REGIONS];
        const unsigned num_kept = ssr_cell_image_region_rows(self, linebuf, 0, kept);
        grman_remove_cell_images(main_buf ? self->main_grman : self->alt_grman, top, bottom, kept, num_kept);
    }
}

static void
ssr_dirty_overflow_line_graphics(Screen *self) {
    // Render the placeholders in the overflow buffers of the vertically
    // scrolling regions again, see ssr_render_edge_line_graphics()
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) {
        const SmoothScrollRegion *r = self->smooth_scroll.regions + i;
        if (ssr_uses_history(self, r) && self->historybuf->count) {
            historybuf_mark_line_dirty(self->historybuf, 0);
            self->is_dirty = true;
        }
        if (r->horizontal || !r->overflow) continue;
        for (index_type y = 0; y < r->overflow->ynum; y++) {
            LineAttrs *a = r->overflow->line_attrs + y;
            if (a->has_image_placeholders) {
                a->has_dirty_text = true;
                self->is_dirty = true;
            }
        }
    }
}

void
screen_handle_dnd_command(Screen *self, const DnDCommand *cmd_, const uint8_t *payload) {
    Window *w;
    if (!self->window_id || !(w = window_for_window_id(self->window_id))) return;
    const DnDCommand *cmd;
    DnDCommand copy;
    if (self->dnd_chunking.active) {
        copy = self->dnd_chunking.metadata;
        copy.more = cmd_->more;
        copy.payload_sz = cmd_->payload_sz;
        cmd = &copy;
        self->dnd_chunking.active = cmd->more != 0;
    } else {
        cmd = cmd_;
        if (cmd_->more) {
            self->dnd_chunking.active = true;
            self->dnd_chunking.metadata = *cmd_;
        }
    }
    switch (cmd->type) {
        case 'a':
            if (cmd->cell_x == 1) drop_register_machine_id(w, payload, cmd->payload_sz);
            else drop_register_window(w, payload, cmd->payload_sz, true, cmd->client_id, cmd->more);
            break;
        case 'A': drop_register_window(w, NULL, 0, false, cmd->client_id, cmd->more); break;
        case 'm': drop_set_status(w, cmd->operation, (const char *)payload, cmd->payload_sz, cmd->more); break;
        case 'r': {
            drop_enqueue_request(w, cmd->cell_x, cmd->cell_y, cmd->pixel_y, cmd->operation);
        } break;
        case 'o': {
            switch (cmd->cell_x) {
                case 1: drag_start_offerring(w, (const char *)payload, cmd->payload_sz); break;
                case 2: drag_stop_offerring(w); break;
                case 0: drag_add_mimes(w, (int)cmd->operation, cmd->client_id, (const char *)payload, cmd->payload_sz, cmd->more); break;
            }
        } break;
        case 'p': {
            if (cmd->cell_x >= 0) drag_add_pre_sent_data(w, cmd->cell_x, payload, cmd->payload_sz);
            else drag_add_image(w, -cmd->cell_x, cmd->cell_y, cmd->pixel_x, cmd->pixel_y, (int)cmd->operation, payload, cmd->payload_sz);
        } break;
        case 'P': {
            if (cmd->cell_x >= 0) drag_change_image(w, cmd->cell_x);
            else drag_start(w);
        } break;
        case 'e': {
            drag_process_item_data(w, cmd->cell_y, cmd->more, payload, cmd->payload_sz);
        } break;
        case 'E': {
            if (cmd->cell_y == -1) {
                drag_free_offer(w, true);
                if (global_state.drag_source.is_active && global_state.drag_source.from_window == w->id) { cancel_current_drag_source(); }
            } else drag_process_item_data(w, cmd->cell_y, -1, payload, cmd->payload_sz);
        } break;
        case 'k': {
            drag_remote_file_data(w, cmd->cell_x, cmd->cell_y, cmd->pixel_x, cmd->pixel_y, cmd->more != 0, payload, cmd->payload_sz);
        } break;
        case 'q': {
            dnd_query(w, cmd->client_id);
        } break;
    }
}

void
screen_handle_graphics_command(Screen *self, const GraphicsCommand *cmd, const uint8_t *payload) {
    unsigned int x = self->cursor->x, y = self->cursor->y;
    const char *response = grman_handle_command(self->grman, cmd, payload, self->cursor, &self->is_dirty, self->cell_size);
    if (response != NULL) write_escape_code_to_child(self, ESC_APC, response);
    if (x != self->cursor->x || y != self->cursor->y) {
        bool in_margins = cursor_within_margins(self);
        if (self->cursor->x >= self->columns) {
            self->cursor->x = 0;
            self->cursor->y++;
        }
        if (self->cursor->y > self->margin_bottom) scroll_past_image(self, self->cursor->y - self->margin_bottom);
        screen_ensure_bounds(self, false, in_margins);
    }
    if (cmd->unicode_placement) {
        // Make sure the placeholders are redrawn if we add or change a virtual placement.
        screen_dirty_line_graphics(self, 0, self->lines, self->linebuf == self->main_linebuf);
        ssr_dirty_overflow_line_graphics(self);
    }
}
// }}}

// Glyph protocol {{{

// The payload formats kitty supports, advertised in the reply to the s verb
#define GLYPH_SUPPORTED_FORMATS "vg"

static bool
glyph_is_registered(Screen *self, char_type cp) {
    return glyph_registry_get(tc_glyph_registry(self->text_cache), cp) != NULL;
}

static void
glyph_reply(Screen *self, const char *fmt, ...) {
    char buf[512];
    va_list args;
    va_start(args, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    if (n > 0 && (size_t)n < sizeof(buf)) write_escape_code_to_child(self, ESC_APC, buf);
}

static void
glyph_handle_query(Screen *self, const GlyphCommand *cmd) {
    if (cmd->has_cp == cmd->has_grapheme) {
        glyph_reply(self, GLYPH_PROTOCOL_PREFIX "q;reason=malformed_query");
        return;
    }
    if (cmd->has_grapheme) {
        // kitty does not support grapheme queries
        if (!cmd->grapheme_valid) {
            glyph_reply(self, GLYPH_PROTOCOL_PREFIX "q;reason=malformed_query");
            return;
        }
        // At most six hex digits and a comma per codepoint
        char hex[GLYPH_MAX_GRAPHEME_CODEPOINTS * 7 + 1];
        static_assert(sizeof("10ffff,") - 1 == 7, "fix the size of hex");
        size_t pos = 0;
        for (unsigned i = 0; i < cmd->grapheme_count && pos < sizeof(hex); i++) {
            const int n = snprintf(hex + pos, sizeof(hex) - pos, "%s%x", i ? "," : "", cmd->grapheme[i]);
            if (n < 0) return;
            pos += n;
        }
        if (pos >= sizeof(hex)) return;
        glyph_reply(self, GLYPH_PROTOCOL_PREFIX "q;grapheme=%s;reason=unsupported", hex);
        return;
    }
    if (!cmd->cp_valid) {
        glyph_reply(self, GLYPH_PROTOCOL_PREFIX "q;reason=malformed_query");
        return;
    }
    if (is_glyph_block_codepoint(cmd->cp)) {
        // No font assigns glyphs to codepoints in the block, so whether the
        // codepoint is covered is determined by the registrations alone.
        glyph_reply(self, GLYPH_PROTOCOL_PREFIX "q;cp=%x;status=%s", cmd->cp, glyph_is_registered(self, cmd->cp) ? "glossary" : "");
    } else {
        // Determining font coverage requires font fallback which is too slow
        // to do while parsing input, so kitty never does it.
        glyph_reply(self, GLYPH_PROTOCOL_PREFIX "q;cp=%x;reason=unknown", cmd->cp);
    }
}

// Reply to r and c, reason is NULL on success
static void
glyph_reply_status(Screen *self, const GlyphCommand *cmd, const char *reason) {
    if (cmd->reply == GLYPH_REPLY_NONE || (cmd->reply == GLYPH_REPLY_FAILURES && !reason)) return;
    char cp[32] = {0};
    if (cmd->has_cp && cmd->cp_valid) snprintf(cp, sizeof(cp), "cp=%x;", cmd->cp);
    if (reason) glyph_reply(self, GLYPH_PROTOCOL_PREFIX "%c;%sstatus=1;reason=%s", cmd->verb, cp, reason);
    else glyph_reply(self, GLYPH_PROTOCOL_PREFIX "%c;%sstatus=0", cmd->verb, cp);
}

// Whether the glyphs kept alive by this window are within the per window limits
static bool
glyph_window_within_limits(Screen *self, const VGGlyph *new_glyph) {
    const GlyphRegistry *r = tc_glyph_registry(self->text_cache);
    size_t count, memory;
#define within                                                \
    (tc_bound_glyph_usage(self->text_cache, &count, &memory), \
     count + r->num_registered + 1 <= vg_window_glyph_limit && memory + r->memory + new_glyph->memory_size <= vg_window_memory_limit)
    if (within) return true;
    // Text that used glyphs may have been erased or scrolled out of the
    // scrollback, garbage collect to release its glyphs. At most once a
    // second, as it is expensive with a large scrollback.
    const monotonic_t now = monotonic();
    if (tc_has_adds_since_last_gc(self->text_cache) && (!self->last_glyph_limit_gc_at || now - self->last_glyph_limit_gc_at > s_double_to_monotonic_t(1.0))) {
        self->last_glyph_limit_gc_at = now;
        screen_garbage_collect_text_cache(self);
        return within;
    }
#undef within
    return false;
}

static const char *
glyph_register(Screen *self, const GlyphCommand *cmd, const uint8_t *buf) {
    if (!cmd->has_cp || !cmd->cp_valid || !is_glyph_block_codepoint(cmd->cp)) return "out_of_namespace";
    if (cmd->fmt != GLYPH_FMT_VG) return "unsupported_format";
    if (!cmd->has_vb || !cmd->placement_valid) return "malformed_payload";
    if (cmd->payload_sz > GLYPH_MAX_PAYLOAD_SIZE) return "payload_too_large";
    VGError err;
    const char *err_msg;
    VGGlyph *g = vg_parse(buf + cmd->payload_start, cmd->payload_sz, &cmd->placement, &err, &err_msg);
    if (!g) {
        switch (err) {
            case VG_OK:
            case VG_MALFORMED: return "malformed_payload";
            case VG_TOO_LARGE: return "outline_too_large";
            case VG_OUT_OF_MEMORY: return "no_space";
        }
        return "malformed_payload";
    }
    // A new glyph that takes the memory used by all glyphs over the budget
    // is rejected, registering a glyph that already exists uses no memory
    // Checked regardless of whether the glyph already exists, so that the
    // result does not reveal whether other windows use it
    if (vg_live_glyph_memory() > VG_MEMORY_BUDGET || !glyph_window_within_limits(self, g)) {
        vg_decref(g);
        return "no_space";
    }
    glyph_registry_set(tc_glyph_registry(self->text_cache), cmd->cp, g);
    vg_decref(g);
    return NULL;
}

static const char *
glyph_clear(Screen *self, const GlyphCommand *cmd) {
    GlyphRegistry *r = tc_glyph_registry(self->text_cache);
    if (cmd->has_cp) {
        if (!cmd->cp_valid || !is_glyph_block_codepoint(cmd->cp)) return "out_of_namespace";
        glyph_registry_clear(r, cmd->cp);
    } else glyph_registry_clear_all(r);
    self->is_dirty = true;
    return NULL;
}

void
screen_handle_glyph_command(Screen *self, const GlyphCommand *cmd, const uint8_t *buf) {
    switch (cmd->verb) {
        case GLYPH_VERB_SUPPORT: glyph_reply(self, GLYPH_PROTOCOL_PREFIX "s;fmt=" GLYPH_SUPPORTED_FORMATS); break;
        case GLYPH_VERB_QUERY: glyph_handle_query(self, cmd); break;
        case GLYPH_VERB_REGISTER: glyph_reply_status(self, cmd, glyph_register(self, cmd, buf)); break;
        case GLYPH_VERB_CLEAR: glyph_reply_status(self, cmd, glyph_clear(self, cmd)); break;
    }
}
// }}}

// Modes {{{


void
screen_toggle_screen_buffer(Screen *self, bool save_cursor, bool clear_alt_screen) {
    bool to_alt = self->linebuf == self->main_linebuf;
    // The regions are on the screen being switched away from
    screen_smooth_scroll_remove_all(self);
    bidi_layout_moved(self);
    self->active_hyperlink_id = 0;
    reset_pixel_scroll(self, 0);
    if (to_alt) {
        if (clear_alt_screen) {
            linebuf_clear(self->alt_linebuf, BLANK_CHAR);
            bidi_note_maybe_unstamp(self->alt_linebuf);
            grman_clear(self->alt_grman, true, self->cell_size);
        }
        if (save_cursor) screen_save_cursor(self);
        self->bidi.main_stash.mBDSM = self->modes.mBDSM;
        self->bidi.main_stash.mBIDI_AUTODETECT = self->modes.mBIDI_AUTODETECT;
        self->bidi.main_stash.rtl = self->bidi.rtl;
        self->modes.mBDSM = self->modes.mBIDI_AUTODETECT = self->bidi.rtl = false;
        self->linebuf = self->alt_linebuf;
        screen_bidi_records_writes_changed(self);
        self->tabstops = self->alt_tabstops;
        self->key_encoding_flags = self->alt_key_encoding_flags;
        self->grman = self->alt_grman;
        screen_cursor_position(self, 1, 1);
        cursor_reset(self->cursor);
        self->alternate_screen.entered_at = monotonic();
    } else {
        self->alternate_screen.exited_at = monotonic();
        self->modes.mBDSM = self->bidi.main_stash.mBDSM;
        self->modes.mBIDI_AUTODETECT = self->bidi.main_stash.mBIDI_AUTODETECT;
        self->bidi.rtl = self->bidi.main_stash.rtl;
        self->linebuf = self->main_linebuf;
        screen_bidi_records_writes_changed(self);
        self->tabstops = self->main_tabstops;
        self->key_encoding_flags = self->main_key_encoding_flags;
        if (save_cursor) screen_restore_cursor(self);
        self->grman = self->main_grman;
    }
    screen_history_scroll(self, SCROLL_FULL, false);
    self->is_dirty = true;
    grman_mark_layers_dirty(self->grman);
    clear_all_selections(self);
    self->extra_cursors.count = 0;
    // Force re-upload of the selection buffer as the number of render lines
    // changes when pixel_scroll_enabled changes (which depends on which
    // linebuf is active). Without this, the selection buffer can be smaller
    // than the cell data buffer, causing OOB reads that produce cursor
    // artifacts (see #9725).
    self->extra_cursors.dirty = true;
    global_state.check_for_active_animated_images = true;
}

void
screen_normal_keypad_mode(Screen UNUSED *self) {} // Not implemented as this is handled by the GUI
void
screen_alternate_keypad_mode(Screen UNUSED *self) {} // Not implemented as this is handled by the GUI

static void
set_mode_from_const(Screen *self, unsigned int mode, bool val) {
#define SIMPLE_MODE(name) \
    case name: self->modes.m##name = val; break;

#define MOUSE_MODE(name, attr, value)        \
    case name:                               \
        self->modes.attr = val ? value : 0;  \
        detailed_mouse_events_changed(self); \
        break;

    bool private;
    switch (mode) {
        SIMPLE_MODE(LNM)
        SIMPLE_MODE(PASTE_EVENTS)
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

        case DETAILED_MOUSE_EVENTS:
            // The times of the events are relative to when the mode was turned on
            if (val && !self->modes.mDETAILED_MOUSE_EVENTS) {
                zero_at_ptr(&self->mouse_events);
                self->mouse_events.clock_origin = monotonic();
            }
            self->modes.mDETAILED_MOUSE_EVENTS = val;
            detailed_mouse_events_changed(self);
            break;
        case DECSCLM:
        case DECNRCM: break; // we ignore these modes
        case BDSM:
            self->modes.mBDSM = val;
            screen_bidi_records_writes_changed(self);
            break;
        case BIDI_AUTODETECT: self->modes.mBIDI_AUTODETECT = val; break;
        case DECCKM: self->modes.mDECCKM = val; break;
        case DECTCEM: self->modes.mDECTCEM = val; break;
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
        case DECAWM: self->modes.mDECAWM = val; break;
        case DECCOLM:
            self->modes.mDECCOLM = val;
            if (val) {
                // When DECCOLM mode is set, the screen is erased and the cursor
                // moves to the home position.
                screen_erase_in_display(self, 2, false);
                screen_cursor_position(self, 1, 1);
            }
            break;
        case CONTROL_CURSOR_BLINK: self->cursor->non_blinking = !val; break;
        case SAVE_CURSOR: screen_save_cursor(self); break;
        case TOGGLE_ALT_SCREEN_1:
        case TOGGLE_ALT_SCREEN_2:
        case ALTERNATE_SCREEN:
            if (val && self->linebuf == self->main_linebuf) screen_toggle_screen_buffer(self, mode == ALTERNATE_SCREEN, mode == ALTERNATE_SCREEN);
            else if (!val && self->linebuf != self->main_linebuf) screen_toggle_screen_buffer(self, mode == ALTERNATE_SCREEN, mode == ALTERNATE_SCREEN);
            break;
        case 7727 << 5: log_error("Application escape mode is not supported, the extended keyboard protocol should be used instead"); break;
        case PENDING_MODE << 5:
            if (!screen_pause_rendering(self, val, 0)) {
                log_error("Pending mode change to already current mode (%d) requested. Either pending mode expired or there is an application bug.", val);
            }
            break;
        case INBAND_RESIZE_NOTIFICATION:
            self->modes.mINBAND_RESIZE_NOTIFICATION = val;
            if (val) CALLBACK("notify_child_of_resize", NULL);
            break;
        case VISIBILITY_REPORTS:
            self->modes.mVISIBILITY_REPORTS = val;
            if (val) send_visibility_report(self);
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
screen_modify_other_keys(Screen *self, unsigned val, unsigned val2) {
    // Only report an error about modifyOtherKeys if the kitty keyboard
    // protocol is not in effect and the application is trying to turn it on.
    // There are some applications that try to enable both.
    if (self->test_child == Py_None && !screen_current_key_encoding_flags(self) && val == 4 && val2 != INT_MAX && val2 != 0) {
        log_error(
            "The application is trying to use xterm's modifyOtherKeys. This is superseded by the kitty keyboard protocol "
            "https://sw.kovidgoyal.net/kitty/keyboard-protocol. The application should be updated to use that.");
    }
}

uint8_t
screen_current_key_encoding_flags(Screen *self) {
    for (unsigned i = arraysz(self->main_key_encoding_flags); i-- > 0;) {
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
    for (unsigned i = arraysz(self->main_key_encoding_flags); i-- > 0;) {
        if (self->key_encoding_flags[i] & 0x80) {
            idx = i;
            break;
        }
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
    for (unsigned i = arraysz(self->main_key_encoding_flags); i-- > 0;) {
        if (self->key_encoding_flags[i] & 0x80) {
            current_idx = i;
            break;
        }
    }
    if (current_idx == sz - 1) memmove(self->key_encoding_flags, self->key_encoding_flags + 1, (sz - 1) * sizeof(self->main_key_encoding_flags[0]));
    else self->key_encoding_flags[current_idx++] |= 0x80;
    self->key_encoding_flags[current_idx] = 0x80 | q;
    debug_input("\x1b[35mPushed key encoding flags to: %u\x1b[39m\n", screen_current_key_encoding_flags(self));
}

void
screen_pop_key_encoding_flags(Screen *self, uint32_t num) {
    for (unsigned i = arraysz(self->main_key_encoding_flags); num && i-- > 0;) {
        if (self->key_encoding_flags[i] & 0x80) {
            num--;
            self->key_encoding_flags[i] = 0;
        }
    }
    debug_input("\x1b[35mPopped key encoding flags to: %u\x1b[39m\n", screen_current_key_encoding_flags(self));
}

// }}}

// Cursor {{{

MouseShape
screen_pointer_shape(Screen *self) {
    if (self->linebuf == self->main_linebuf) {
        if (self->main_pointer_shape_stack.count) return self->main_pointer_shape_stack.stack[self->main_pointer_shape_stack.count - 1];
    } else {
        if (self->alternate_pointer_shape_stack.count) return self->alternate_pointer_shape_stack.stack[self->alternate_pointer_shape_stack.count - 1];
    }
    return INVALID_POINTER;
}

static PyObject *
current_pointer_shape(Screen *self, PyObject *args UNUSED) {
    MouseShape s = screen_pointer_shape(self);
    const char *ans = "0";
    switch (s) {
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
        case GRABBING_POINTER:
            ans = "grabbing";
            break;
            /* end enum to css */
    }
    return PyUnicode_FromString(ans);
}

static PyObject *
change_pointer_shape(Screen *self, PyObject *args) {
    char op;
    const char *css_name, *b;
    if (!PyArg_ParseTuple(args, "ss", &b, &css_name)) return NULL;
    op = b[0];
    uint8_t *count, *stack;
    size_t stack_sz;
    if (self->main_linebuf == self->linebuf) {
        count = &self->main_pointer_shape_stack.count;
        stack = self->main_pointer_shape_stack.stack;
        stack_sz = arraysz(self->main_pointer_shape_stack.stack);
    } else {
        count = &self->alternate_pointer_shape_stack.count;
        stack = self->alternate_pointer_shape_stack.stack;
        stack_sz = arraysz(self->alternate_pointer_shape_stack.stack);
    }
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
        else if (strcmp("arrow", css_name) == 0) s = DEFAULT_POINTER;
        else if (strcmp("beam", css_name) == 0) s = TEXT_POINTER;
        /* end css to enum */
        if (s == INVALID_POINTER && css_name[0] != 0) {
            PyErr_Format(PyExc_KeyError, "Not a known pointer shape: %s", css_name);
            return NULL;
        }
        if (op == '=') {
            if (!*count) *count += 1;
            stack[*count - 1] = s;
        } else if (op == '>') {
            if (*count >= stack_sz) { remove_i_from_array(stack, 0, *count); }
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
    screen_cursor_move(self, 1, -1, true);
}

void
screen_tab(Screen *self) {
    // Move to the next tab space, or the end of the screen if there aren't anymore left.
    unsigned int found = 0;
    for (unsigned int i = self->cursor->x + 1; i < self->columns; i++) {
        if (self->tabstops[i]) {
            found = i;
            break;
        }
    }
    if (!found) found = self->columns - 1;
    if (found != self->cursor->x) {
        if (self->cursor->x < self->columns) {
            CPUCell *cpu_cell = linebuf_cpu_cells_for_line(self->linebuf, self->cursor->y) + self->cursor->x;
            combining_type diff = found - self->cursor->x;
            bool ok = true;
            for (combining_type i = 0; i < diff; i++) {
                CPUCell *c = cpu_cell + i;
                if (cell_has_text(c) && !cell_is_char(c, ' ')) {
                    ok = false;
                    break;
                }
            }
            if (ok) {
                for (combining_type i = 0; i < diff; i++) {
                    CPUCell *c = cpu_cell + i;
                    cell_set_char(c, ' ');
                }
                char_type idx;
                if (diff < arraysz(self->tab_cache.idx_plus_1) && self->tab_cache.idx_plus_1[diff]) idx = self->tab_cache.idx_plus_1[diff] - 1;
                else {
                    self->lc->count = 2;
                    self->lc->chars[0] = '\t';
                    // number of blank cells after the tab cell that the tab covers
                    self->lc->chars[1] = diff - 1;
                    idx = tc_get_or_insert_chars(self->text_cache, self->lc);
                    if (diff < arraysz(self->tab_cache.idx_plus_1)) self->tab_cache.idx_plus_1[diff] = idx + 1;
                }
                cpu_cell->ch_or_idx = idx;
                cpu_cell->ch_is_idx = true;
            }
        }
        self->cursor->x = found;
    }
}

void
screen_tabn(Screen *self, unsigned int count) {
    if (UNLIKELY(self->linebuf->bidi_stamped)) {
        // The tab cells are written outside the draw loop, which checks and marks dirty the rows it writes. A tab does not
        // take a leading mark's direction.
        bidi_line_gets_text(self, self->cursor->y);
        linebuf_mark_line_dirty(self->linebuf, self->cursor->y);
    }
    for (index_type i = 0; i < MAX(1u, count); i++) {
        index_type x = self->cursor->x;
        screen_tab(self);
        if (self->cursor->x == x) break;
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
            if (self->tabstops[i]) {
                self->cursor->x = i;
                break;
            }
        }
        if (i <= 0) self->cursor->x = 0;
    }
}

void
screen_clear_tab_stop(Screen *self, unsigned int how) {
    switch (how) {
        case 0:
            if (self->cursor->x < self->columns) self->tabstops[self->cursor->x] = false;
            break;
        case 2: break; // no-op
        case 3:
            for (unsigned int i = 0; i < self->columns; i++) self->tabstops[i] = false;
            break;
        default: log_error("%s %s %u", ERROR_PREFIX, "Unsupported clear tab stop mode: ", how); break;
    }
}

void
screen_set_tab_stop(Screen *self) {
    if (self->cursor->x < self->columns) self->tabstops[self->cursor->x] = true;
}

void
screen_reset_tab_stops(Screen *self) {
    init_tabstops(self->tabstops, self->columns);
}

void
screen_cursor_move(Screen *self, unsigned int count /*=1*/, int move_direction /*=-1*/, bool allow_move_to_previous_line) {
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
                    if (self->cursor->y == top || !allow_move_to_previous_line) count = 0;
                    else {
                        count--;
                        self->cursor->y--;
                        self->cursor->x = self->columns - 1;
                    }
                }
            }
        }
    }
}

void
screen_cursor_forward(Screen *self, unsigned int count /*=1*/) {
    screen_cursor_move(self, count, 1, false);
}

void
screen_cursor_up(Screen *self, unsigned int count /*=1*/, bool do_carriage_return /*=false*/, int move_direction /*=-1*/) {
    bool in_margins = cursor_within_margins(self);
    if (count == 0) count = 1;
    if (move_direction < 0 && count > self->cursor->y) self->cursor->y = 0;
    else self->cursor->y += move_direction * count;
    if (do_carriage_return) self->cursor->x = 0;
    screen_ensure_bounds(self, true, in_margins);
}

void
screen_cursor_up1(Screen *self, unsigned int count /*=1*/) {
    screen_cursor_up(self, count, true, -1);
}

void
screen_cursor_down(Screen *self, unsigned int count /*=1*/) {
    screen_cursor_up(self, count, false, 1);
}

void
screen_cursor_down1(Screen *self, unsigned int count /*=1*/) {
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

#define INDEX_UP(add_to_history)                                                                                       \
    if (UNLIKELY(self->smooth_scroll.count)) ssr_lines_moved(self, top, bottom, true, add_to_history);                 \
    nuke_multiline_chars_torn_by_scroll(self, top, bottom, true, add_to_history);                                      \
    bidi_index_up_seams(self, top, bottom, add_to_history);                                                            \
    linebuf_index(self->linebuf, top, bottom);                                                                         \
    INDEX_GRAPHICS(-1, add_to_history)                                                                                 \
    if (add_to_history) {                                                                                              \
        /* Only add to history when no top margin has been set */                                                      \
        linebuf_init_line(self->linebuf, bottom);                                                                      \
        historybuf_add_line(self->historybuf, self->linebuf->line, &self->as_ansi_buf);                                \
        /* Keep a scrolled back viewport anchored on the same content */                                               \
        if (self->scrolled_by) {                                                                                       \
            if (self->scrolled_by < self->historybuf->count) self->scrolled_by++;                                      \
            if (self->scrolled_by >= self->historybuf->count && self->pixel_scroll_offset_y) {                         \
                reset_pixel_scroll(self, 0);                                                                           \
                self->scroll_changed = true;                                                                           \
            }                                                                                                          \
        }                                                                                                              \
    }                                                                                                                  \
    last_visited_prompt_index(self, top, bottom, true, add_to_history);                                                \
    clear_scrolled_in_line(self, bottom);                                                                              \
    self->is_dirty = true;                                                                                             \
    if (UNLIKELY(self->selections.count)) index_selection(self, &self->selections, true, top, bottom, add_to_history); \
    if (UNLIKELY(self->url_ranges.count || self->url_ranges.in_progress)) clear_selection(&self->url_ranges);

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
    // Scrolling up by more than the number of lines on screen blanks the
    // entire scrolling region, so clamp to avoid a multi-billion iteration
    // busy-loop when a program emits e.g. CSI 2147483647 S. See _reverse_scroll
    // which caps count the same way.
    count = MIN(count, self->lines);
    while (count > 0) {
        count--;
        INDEX_UP(add_to_history);
    }
}

static void
scroll_past_image(Screen *self, unsigned int count) {
    // Scroll the screen up by count lines after an image taller than the
    // available space has been placed. Unlike screen_scroll() this does not
    // stop after the scroll region is blank, as images (and the text above
    // them in the history) must move by the full amount to end up above the
    // cursor.
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    const bool add_to_history = self->linebuf == self->main_linebuf && self->margin_top == 0;
    unsigned int n = MIN(count, self->lines);
    count -= n;
    screen_scroll(self, n);
    if (!count) return;
    // The scroll region is now blank so further scrolling only adds blank lines
    // to the history and moves images. Bound the number of blank lines as the
    // row count of an image is controlled by the client and the history can be
    // unlimited in size. Anything further up is gone anyway.
    if (add_to_history) {
        n = MIN(count, MIN(self->historybuf->ynum, MAX_BLANK_LINES_SCROLLED_PAST_IMAGE));
        count -= n;
        while (n-- > 0) { INDEX_UP(true); }
    }
    if (count) INDEX_GRAPHICS(-(int)MIN(count, (unsigned int)(INT32_MAX / 2)), add_to_history);
}

void
screen_reverse_index(Screen *self) {
    // Move cursor up one line, scrolling screen if needed
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (self->cursor->y == top) {
        nuke_multiline_chars_torn_by_scroll(self, top, bottom, false, false);
        INDEX_DOWN(false);
    } else screen_cursor_up(self, 1, false, -1);
}

static void
_reverse_scroll(Screen *self, unsigned int count, bool fill_from_scrollback) {
    // Scroll the screen down by count lines, not moving the cursor
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    // The scrollback only adjoins the scroll region when the region starts at
    // the top of the screen, otherwise the lines must come in blank, as with SD
    fill_from_scrollback = fill_from_scrollback && self->linebuf == self->main_linebuf && top == 0;
    if (fill_from_scrollback) {
        unsigned limit = MAX(self->lines, self->historybuf->count);
        count = MIN(limit, count);
    } else count = MIN(self->lines, count);
    while (count-- > 0) {
        bool copied = false;
        // must be done before popping the history line as removing chars
        // can modify the parts of them that are in the history buffer
        nuke_multiline_chars_torn_by_scroll(self, top, bottom, false, fill_from_scrollback && self->historybuf->count > 0);
        if (fill_from_scrollback) {
            copied = historybuf_pop_line(self->historybuf, self->alt_linebuf->line);
            // Keep a scrolled back viewport anchored on the same content
            if (copied && self->scrolled_by) self->scrolled_by--;
        }
        INDEX_DOWN(copied);
        if (copied) {
            linebuf_copy_line_to(self->main_linebuf, self->alt_linebuf->line, 0);
            bidi_note_line_from_history(self, 0);
        }
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

#define buffer_push(self, ans)                                                                                   \
    {                                                                                                            \
        ans = (self)->buf + (((self)->start_of_data + (self)->count) % SAVEPOINTS_SZ);                           \
        if ((self)->count == SAVEPOINTS_SZ) (self)->start_of_data = ((self)->start_of_data + 1) % SAVEPOINTS_SZ; \
        else (self)->count++;                                                                                    \
    }

#define buffer_pop(self, ans)                                                              \
    {                                                                                      \
        if ((self)->count == 0) ans = NULL;                                                \
        else {                                                                             \
            (self)->count--;                                                               \
            ans = (self)->buf + (((self)->start_of_data + (self)->count) % SAVEPOINTS_SZ); \
        }                                                                                  \
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
#define SIMPLE_MODE(name) \
    case name: dest->m##name = src->m##name; break;
#define SIDE_EFFECTS(name)                                                  \
    case name:                                                              \
        if (do_side_effects) set_mode_from_const(self, name, src->m##name); \
        else dest->m##name = src->m##name;                                  \
        break;

    const bool do_side_effects = dest == &self->modes;

    switch (mode) {
        SIMPLE_MODE(LNM) // kitty extension
        SIMPLE_MODE(IRM) // kitty extension
        SIMPLE_MODE(DECARM)
        SIMPLE_MODE(BRACKETED_PASTE)
        SIMPLE_MODE(FOCUS_TRACKING)
        SIMPLE_MODE(COLOR_PREFERENCE_NOTIFICATION)
        SIMPLE_MODE(PASTE_EVENTS)
        SIDE_EFFECTS(DETAILED_MOUSE_EVENTS)
        SIMPLE_MODE(INBAND_RESIZE_NOTIFICATION)
        SIMPLE_MODE(VISIBILITY_REPORTS)
        SIMPLE_MODE(DECCKM)
        SIMPLE_MODE(DECTCEM)
        SIMPLE_MODE(DECAWM)
        case MOUSE_BUTTON_TRACKING:
        case MOUSE_MOTION_TRACKING:
        case MOUSE_MOVE_TRACKING:
            dest->mouse_tracking_mode = src->mouse_tracking_mode;
            if (do_side_effects) detailed_mouse_events_changed(self);
            break;
        case MOUSE_UTF8_MODE:
        case MOUSE_SGR_MODE:
        case MOUSE_URXVT_MODE: dest->mouse_tracking_protocol = src->mouse_tracking_protocol; break;
        case DECSCLM:
        case DECNRCM: break; // we ignore these modes
        case DECSCNM:
            if (dest->mDECSCNM != src->mDECSCNM) {
                dest->mDECSCNM = src->mDECSCNM;
                if (do_side_effects) self->is_dirty = true;
            }
            break;
            SIDE_EFFECTS(DECOM)
            SIDE_EFFECTS(DECCOLM)
            SIDE_EFFECTS(BDSM) // kitty extension
            SIDE_EFFECTS(BIDI_AUTODETECT)
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
    copy_specific_mode(self, VISIBILITY_REPORTS, src, dest);
    copy_specific_mode(self, PASTE_EVENTS, src, dest);
    copy_specific_mode(self, DETAILED_MOUSE_EVENTS, src, dest);
    copy_specific_mode(self, DECCKM, src, dest);
    copy_specific_mode(self, DECTCEM, src, dest);
    copy_specific_mode(self, DECAWM, src, dest);
    copy_specific_mode(self, MOUSE_BUTTON_TRACKING, src, dest);
    copy_specific_mode(self, MOUSE_UTF8_MODE, src, dest);
    copy_specific_mode(self, DECSCNM, src, dest);
    copy_specific_mode(self, BDSM, src, dest);
    copy_specific_mode(self, BIDI_AUTODETECT, src, dest);
}

void
screen_save_modes(Screen *self) {
    // kitty extension to XTSAVE that saves a bunch of no side-effect modes
    copy_specific_modes(self, &self->modes, &self->saved_modes);
    self->bidi.saved_rtl = self->bidi.rtl;
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
    self->bidi.rtl = self->bidi.saved_rtl;
}

void
screen_ensure_bounds(Screen *self, bool force_use_margins /*=false*/, bool in_margins) {
    unsigned int top, bottom;
    if (in_margins && (force_use_margins || self->modes.mDECOM)) {
        top = self->margin_top;
        bottom = self->margin_bottom;
    } else {
        top = 0;
        bottom = self->lines - 1;
    }
    self->cursor->x = MIN(self->cursor->x, self->columns - 1);
    self->cursor->y = MAX(top, MIN(self->cursor->y, bottom));
}

void
screen_cursor_position(Screen *self, unsigned int line, unsigned int column) {
    bool in_margins = cursor_within_margins(self);
    line = (line == 0 ? 1 : line) - 1;
    column = (column == 0 ? 1 : column) - 1;
    if (self->modes.mDECOM) {
        line += self->margin_top;
        line = MAX(self->margin_top, MIN(line, self->margin_bottom));
    }
    self->cursor->position_changed_by_client_at = self->parsing_at;
    self->cursor->x = column;
    self->cursor->y = line;
    screen_ensure_bounds(self, false, in_margins);
}

void
screen_cursor_to_line(Screen *self, unsigned int line) {
    screen_cursor_position(self, line, self->cursor->x + 1);
}

int
screen_cursor_at_a_shell_prompt(const Screen *self) {
    if (self->cursor->y >= self->lines || self->linebuf != self->main_linebuf || !screen_is_cursor_visible(self)) return -1;
    for (index_type y = self->cursor->y + 1; y-- > 0;) {
        switch (self->linebuf->line_attrs[y].prompt_kind) {
            case OUTPUT_START: return -1;
            case PROMPT_START:
            case SECONDARY_PROMPT: return y;
            case UNKNOWN_PROMPT_KIND: break;
        }
    }
    return -1;
}

bool
screen_prompt_supports_click_events(const Screen *self, bool *is_relative) {
    *is_relative = (bool)self->prompt_settings.relative_click_events;
    return (bool)self->prompt_settings.supports_click_events;
}

bool
screen_fake_move_cursor_to_position(Screen *self, index_type start_x, index_type start_y) {
    SelectionBoundary a = {.x = start_x, .y = start_y}, b = {.x = self->cursor->x, .y = self->cursor->y};
    SelectionBoundary *start, *end;
    int key;
    if (a.y < b.y || (a.y == b.y && a.x < b.x)) {
        start = &a;
        end = &b;
        key = GLFW_FKEY_LEFT;
    } else {
        start = &b;
        end = &a;
        key = GLFW_FKEY_RIGHT;
    }
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
                if (!found_non_empty_cell) {
                    x++;
                    continue;
                }
                count += 1;
                break;
            }
            found_non_empty_cell = true;
            if (c->is_multicell) {
                x += mcd_x_limit(c);
            } else x++;
            count += 1; // zsh requires a single arrow press to move past dualwidth chars
        }
        if (!found_non_empty_cell) count++; // blank line
        x = 0;
    }
    if (count) {
        char output[KEY_BUFFER_SIZE + 1] = {0};
        if (self->prompt_settings.uses_special_keys_for_cursor_movement) {
            const char *k = key == GLFW_FKEY_RIGHT ? "1" : "1;1";
            int num = snprintf(output, KEY_BUFFER_SIZE, "\x1b[%su", k);
            for (unsigned i = 0; i < count; i++) write_to_child(self, output, num);
        } else {
            GLFWkeyevent ev = {.key = key, .action = GLFW_PRESS};
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
    switch (how) {
        case 0:
            s = self->cursor->x;
            n = self->columns - self->cursor->x;
            break;
        case 1: n = self->cursor->x + 1; break;
        case 2: n = self->columns; break;
        default: break;
    }
    if (n > 0) {
        bidi_note_maybe_unstamp(self->linebuf);
        nuke_multicell_char_intersecting_with(self, s, s + n, self->cursor->y, self->cursor->y + 1, false);
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
    bidi_layout_moved(self);
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) self->smooth_scroll.regions[i].pushed_to_history = 0;
    reset_pixel_scroll(self, 0);
    if (self->scrolled_by != 0) {
        self->scrolled_by = 0;
        dirty_scroll(self);
    }
    LineBuf *orig = self->linebuf;
    self->linebuf = self->main_linebuf;
    CPUCell *cells = linebuf_cpu_cells_for_line(self->linebuf, 0);
    for (index_type x = 0; x < self->columns; x++) {
        CPUCell *c = cells + x;
        if (c->is_multicell && c->y > 0) { // multiline char that extended into scrollback
            nuke_multicell_char_at(self, x, 0, false);
        }
    }
    bidi_mark_seam(self, 0);
    self->linebuf = orig;
    reset_style_table_if_unused(self);
}

static void
screen_move_into_scrollback(Screen *self) {
    if (self->linebuf != self->main_linebuf || self->margin_top != 0 || self->margin_bottom != self->lines - 1) return;
    unsigned int num_of_lines_to_move = self->lines;
    while (num_of_lines_to_move) {
        // the lines of the screen, not the visual lines, which are lines from
        // the scrollback when it is scrolled
        linebuf_init_line(self->linebuf, num_of_lines_to_move - 1);
        if (!line_is_empty(self->linebuf->line)) break;
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

static void
nuke_multiline_chars_split_by_erase(Screen *self, unsigned int how, index_type a, index_type b) {
    // remove chars crossing the erase boundary
    for (int top = 1; top >= 0; top--) {
        if (top ? how == 3 : how != 1) continue;
        CPUCell *cp;
        index_type y = top ? a : b - 1;
        linebuf_init_cells(self->linebuf, y, &cp, NULL);
        for (index_type x = 0; x < self->columns; x++) {
            if (!cp[x].is_multicell) continue;
            if (top ? cp[x].y > 0 : cp[x].y + 1 < cp[x].scale) nuke_multicell_char_at(self, x, y, false);
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
    bidi_note_maybe_unstamp(self->linebuf);
    switch (how) {
        case 0:
            a = self->cursor->y + 1;
            b = self->lines;
            break;
        case 1:
            a = 0;
            b = self->cursor->y;
            break;
        case 22:
            screen_move_into_scrollback(self);
            how = 2;
            /* fallthrough */
        case 2:
        case 3:
            if (UNLIKELY(self->smooth_scroll.count)) ssr_screen_erased(self);
            if (self->extra_cursors.count) {
                self->extra_cursors.count = 0;
                self->extra_cursors.dirty = true;
            }
            grman_clear(self->grman, how == 3, self->cell_size);
            a = 0;
            b = self->lines;
            break;
        default: return;
    }
    if (b > a) {
        // Multicell chars in smooth scroll regions can have parts in the
        // overflow buffers of the regions, which must be removed with them,
        // rather than being left to come back into the region later, no
        // longer continuing a char. Erasing the complete display discards the
        // overflow buffers above.
        if (how < 2 && UNLIKELY(self->smooth_scroll.count)) nuke_multicell_char_intersecting_with(self, 0, self->columns, a, b, false);
        if (how < 3) nuke_multiline_chars_split_by_erase(self, how, a, b);
        if (how != 3) screen_dirty_line_graphics(self, a, b, self->linebuf == self->main_linebuf);
        if (private) {
            for (unsigned int i = a; i < b; i++) {
                linebuf_init_line(self->linebuf, i);
                line_clear_text(self->linebuf->line, 0, self->columns, BLANK_CHAR);
                linebuf_set_last_char_as_continuation(self->linebuf, i, false);
                linebuf_clear_attrs_and_dirty(self->linebuf, i);
            }
        } else linebuf_clear_lines(self->linebuf, self->cursor, a, b);
        self->is_dirty = true;
        if (selection_intersects_screen_lines(&self->selections, a, b)) clear_selection(&self->selections);
        if (selection_intersects_screen_lines(&self->url_ranges, a, b)) clear_selection(&self->url_ranges);
    }
    if (how < 2) {
        screen_erase_in_line(self, how, private);
        if (how == 1) {
            // the record outlives the clear of the other attrs while the row holds text
            LineAttrs *a = self->linebuf->line_attrs + self->cursor->y;
            const LineAttrs record = *a;
            linebuf_clear_attrs_and_dirty(self->linebuf, self->cursor->y);
            if (UNLIKELY(self->linebuf->bidi_stamped)) {
                line_attrs_set_bidi(a, record);
                a->bidi_may_reorder = record.bidi_may_reorder;
            }
        }
    }
    if (how == 3 && self->linebuf == self->main_linebuf) { screen_clear_scrollback(self); }
    if (how == 3) reset_style_table_if_unused(self);
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
        const bool at_screen_bottom = bottom + 1 >= self->lines;
        // remove chars straddling the bottom margin, as the lines at the bottom
        // of the region are pushed out, tearing them
        if (self->multiline_chars_used && !at_screen_bottom) nuke_multiline_chars_extending_below(self, bottom);
        if (UNLIKELY(self->smooth_scroll.count)) ssr_lines_moved(self, self->cursor->y, bottom, false, false);
        screen_dirty_line_graphics(self, top, bottom, self->linebuf == self->main_linebuf);
        linebuf_insert_lines(self->linebuf, count, self->cursor->y, bottom);
        if (UNLIKELY(self->linebuf->bidi_stamped)) {
            self->linebuf->bidi_maybe_unstamp = true;
            bidi_layout_moved(self);
            bidi_mark_rows_moved_near_regions(self, self->cursor->y, bottom);
            bidi_mark_seam(self, self->cursor->y);
            bidi_mark_seam(self, self->cursor->y + MIN(count, bottom + 1 - self->cursor->y));
            bidi_mark_seam(self, bottom + 1);
        }
        last_visited_prompt_insert_or_delete_lines(self, self->cursor->y, bottom, count, true);
        self->is_dirty = true;
        clear_all_selections(self);
        screen_carriage_return(self);
        if (self->multiline_chars_used) {
            // Chars whose lower rows were pushed out of the region are now cut
            // off at its bottom. At the bottom of the screen they are partially
            // scrolled off, as when scrolling down, otherwise they are torn.
            if (at_screen_bottom) *multiline_chars_cut_off_at_bottom(self) = true;
            else nuke_multiline_chars_extending_below(self, bottom);
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
    if (add_to_scrollback)
        while (num_lines_to_scroll--) screen_index(self);
    else
        while (num_lines_to_scroll--) screen_index_without_adding_to_history(self);
    self->cursor->y = final_y;
    screen_ensure_bounds(self, false, in_margins);
}

static void
screen_delete_lines_impl(Screen *self, index_type start, index_type count, index_type top, index_type bottom) {
    index_type y = start;
    if (UNLIKELY(self->smooth_scroll.count)) ssr_lines_moved(self, start, bottom, true, false);
    nuke_multiline_char_intersecting_with(self, 0, self->columns, y, y + 1, false);
    y += count;
    y = MIN(bottom, y);
    nuke_multiline_char_intersecting_with(self, 0, self->columns, y, y + 1, false);
    // blank lines come in at the bottom, tearing chars that extend below it, which
    // includes chars that are cut off at the bottom of the screen
    if (self->multiline_chars_used) nuke_multiline_chars_extending_below(self, bottom);
    screen_dirty_line_graphics(self, top, bottom, self->linebuf == self->main_linebuf);
    linebuf_delete_lines(self->linebuf, count, start, bottom);
    if (UNLIKELY(self->linebuf->bidi_stamped)) {
        self->linebuf->bidi_maybe_unstamp = true;
        bidi_layout_moved(self);
        bidi_mark_rows_moved_near_regions(self, start, bottom);
        bidi_mark_seam(self, start);
        bidi_mark_seam(self, bottom + 1 - MIN(count, bottom + 1 - start));
        bidi_mark_seam(self, bottom + 1);
    }
    self->is_dirty = true;
    clear_all_selections(self);
}

void
screen_delete_lines(Screen *self, unsigned int count) {
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (count == 0) count = 1;
    if (top <= self->cursor->y && self->cursor->y <= bottom) {
        screen_delete_lines_impl(self, self->cursor->y, count, top, bottom);
        last_visited_prompt_insert_or_delete_lines(self, self->cursor->y, bottom, count, false);
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
        if (!num) return; // cursor is in pending wrap state
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
    if (UNLIKELY(self->smooth_scroll.count)) ssr_row_cells_moved(self, at, y);
    // delete num chars at x=at setting them to the value of the num chars at [at + num, at + num + num)
    // multiline chars at x >= at are deleted and multicell chars split at x=at
    // and x=at + num - 1 are deleted
    nuke_multiline_char_intersecting_with(self, at, self->columns, y, y + 1, replace_with_spaces);
    nuke_split_multicell_char_at_left_boundary(self, at, y, replace_with_spaces);
    CPUCell *cp;
    linebuf_init_cells(self->linebuf, y, &cp, NULL);
    // left shift
    for (index_type i = at; i < self->columns - num; i++) cp[i] = cp[i + num];
    linebuf_mark_line_dirty(self->linebuf, y);
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
        if (!num) return; // cursor is in pending wrap state
        bidi_note_maybe_unstamp(self->linebuf);
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
    bidi_note_maybe_unstamp(self->linebuf);
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

// Fire the custom shader bell event, independently of the visual bell, but
// only if the window is visible, i.e. in the active tab and not hidden by an
// overlay or the layout, as otherwise the shader has nothing to draw over.
static void
fire_bell_shader_event(id_type window_id) {
    for (size_t o = 0; o < global_state.num_os_windows; o++) {
        OSWindow *osw = global_state.os_windows + o;
        if (osw->active_tab >= osw->num_tabs) continue;
        Tab *tab = osw->tabs + osw->active_tab;
        for (size_t i = 0; i < tab->num_windows; i++) {
            if (tab->windows[i].id == window_id) {
                if (tab->windows[i].visible) {
                    osw->shader_anim_event_registry |= (1u << SHADER_ANIM_EVENT_BELL_IN_WINDOW);
                    osw->last_bell_window_id = window_id;
                    wakeup_main_loop();
                }
                return;
            }
        }
    }
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
    if (self->window_id) fire_bell_shader_event(self->window_id);
    CALLBACK("on_bell", NULL);
}

void
report_device_attributes(Screen *self, unsigned int mode, char start_modifier) {
    if (mode == 0) {
        switch (start_modifier) {
            case 0: CALLBACK("on_da1", NULL); break;
            case '>':
                write_escape_code_to_child(
                    self, ESC_CSI, ">1;" xstr(PRIMARY_VERSION) ";" xstr(SECONDARY_VERSION) "c"); // VT-220 + primary version + secondary version
                break;
        }
    }
}

void
screen_xtversion(Screen *self, unsigned int mode) {
    if (mode == 0) { write_escape_code_to_child(self, ESC_DCS, ">|kitty(" XT_VERSION ")"); }
}

void
screen_report_size(Screen *self, unsigned which, unsigned modifier) {
    char buf[32] = {0};
    unsigned code = 0, width = 0, height = 0;
    switch (which) {
        case 14:
            code = 4;
            width = self->cell_size.width * self->columns;
            height = self->cell_size.height * self->lines;
            if (modifier == 2 && self->window_id) {
                OSWindow *osw = os_window_for_kitty_window(self->window_id);
                if (osw) {
                    int w, h, fw, fh;
                    get_os_window_size(osw, &w, &h, &fw, &fh);
                    width = fw;
                    height = fh;
                }
            }
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
    CALLBACK(
        "manipulate_title_stack",
        "OOO",
        op == 23 ? Py_True : Py_False,
        which == 0 || which == 2 ? Py_True : Py_False,
        which == 0 || which == 1 ? Py_True : Py_False);
}

void
report_device_status(Screen *self, unsigned int which, bool private) {
    unsigned int x, y;
    static char buf[64];
    switch (which) {
        case 5: // device status
            write_escape_code_to_child(self, ESC_CSI, "0n");
            break;
        case 6: // cursor position
            x = self->cursor->x;
            y = self->cursor->y;
            if (x >= self->columns) {
                // A wrap at the bottom margin scrolls the region, leaving the cursor on the same row
                if (y < self->lines - 1 && y != self->margin_bottom) {
                    x = 0;
                    y++;
                } else x--;
            }
            if (self->modes.mDECOM) y -= MIN(y, self->margin_top);
            // 1-based indexing
            int sz = snprintf(buf, sizeof(buf) - 1, "%s%u;%uR", (private ? "?" : ""), y + 1, x + 1);
            if (sz > 0) write_escape_code_to_child(self, ESC_CSI, buf);
            break;
        case 996: // https://github.com/contour-terminal/contour/blob/master/docs/vt-extensions/color-palette-update-notifications.md
            if (private) { CALLBACK("report_color_scheme_preference", NULL); }
            break;
        case 998: // https://rockorager.dev/misc/visibility-reports/
            if (private) send_visibility_report(self);
            break;
    }
}

void
report_mode_status(Screen *self, unsigned int which, bool private) {
    unsigned int q = private ? which << 5 : which;
    unsigned int ans = 0;
    char buf[50] = {0};
    switch (q) {
#define KNOWN_MODE(x) \
    case x: ans = self->modes.m##x ? 1 : 2; break;
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
        KNOWN_MODE(VISIBILITY_REPORTS);
        KNOWN_MODE(INBAND_RESIZE_NOTIFICATION);
        KNOWN_MODE(PASTE_EVENTS);
        KNOWN_MODE(DETAILED_MOUSE_EVENTS);
#undef KNOWN_MODE
        case ALTERNATE_SCREEN: ans = self->linebuf == self->alt_linebuf ? 1 : 2; break;
        case MOUSE_BUTTON_TRACKING: ans = self->modes.mouse_tracking_mode == BUTTON_MODE ? 1 : 2; break;
        case MOUSE_MOTION_TRACKING: ans = self->modes.mouse_tracking_mode == MOTION_MODE ? 1 : 2; break;
        case MOUSE_MOVE_TRACKING: ans = self->modes.mouse_tracking_mode == ANY_MODE ? 1 : 2; break;
        case MOUSE_SGR_MODE: ans = self->modes.mouse_tracking_protocol == SGR_PROTOCOL ? 1 : 2; break;
        case MOUSE_UTF8_MODE: ans = self->modes.mouse_tracking_protocol == UTF8_PROTOCOL ? 1 : 2; break;
        case MOUSE_SGR_PIXEL_MODE: ans = self->modes.mouse_tracking_protocol == SGR_PIXEL_PROTOCOL ? 1 : 2; break;
        case PENDING_UPDATE: ans = self->paused_rendering.expires_at ? 1 : 2; break;
        case BDSM: ans = OPT(force_ltr) ? 4 : (self->modes.mBDSM ? 1 : 2); break;
        case BIDI_AUTODETECT: ans = OPT(force_ltr) ? 4 : (self->modes.mBIDI_AUTODETECT ? 1 : 2); break;
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
    top--;
    bottom--; // 1 based indexing
    if (bottom > top) {
        // Even though VT102 and VT220 require DECSTBM to ignore regions
        // of width less than 2, some programs (like aptitude for example)
        // rely on it. Practicality beats purity.
        self->margin_top = top;
        self->margin_bottom = bottom;
        // The cursor moves to the home position when the top and
        // bottom margins of the scrolling region (DECSTBM) changes.
        screen_cursor_position(self, 1, 1);
    }
}

void
screen_set_bidi_direction(Screen *self, unsigned int direction, unsigned int path_extent UNUSED) {
    if (direction > 2) return;
    self->bidi.rtl = direction == 2;
}

void
screen_set_cursor(Screen *self, unsigned int mode, uint8_t secondary) {
    uint8_t shape;
    bool blink;
    switch (secondary) {
        case 0: // DECLL
            break;
        case '"': // DECCSA
            break;
        case ' ': // DECSCUSR
            shape = 0;
            blink = true;
            if (mode > 0) {
                blink = mode % 2;
                shape = (mode < 3) ? CURSOR_BLOCK : (mode < 5) ? CURSOR_UNDERLINE : (mode < 7) ? CURSOR_BEAM : NO_CURSOR_SHAPE;
            }
            self->cursor->shape = shape;
            self->cursor->non_blinking = !blink;
            break;
    }
}

#define NAME multi_cursor_map
#define KEY_TY index_type
#define VAL_TY uint8_t
#include "kitty-verstable.h"

unsigned
screen_multi_cursor_count(const Screen *self) {
    return self->paused_rendering.expires_at ? self->paused_rendering.extra_cursors.count : self->extra_cursors.count;
}

void
screen_multi_cursor(Screen *self, int queried_shape, int *params, unsigned num_params) {
    // printf("%d;", queried_shape); for (unsigned i = 0; i < num_params; i++) {printf("%d:", params[i]);} printf("\n");
    if (!num_params) {
#define pr(...)                                                \
    {                                                          \
        int n = snprintf(p, sz - (p - buf), __VA_ARGS__);      \
        if (n >= 0 && (unsigned)n <= (sz - (p - buf))) p += n; \
    }
        if (params == NULL) {
            write_escape_code_to_child(self, ESC_CSI, ">1;2;3;29;30;40;100;101 q");
        } else if (queried_shape == 100) {
            size_t sz = self->extra_cursors.count * 32 + 64;
            RAII_ALLOC(char, buf, malloc(sz));
            sz -= 4;
            if (buf) {
                char *p = buf + snprintf(buf, sz, ">100;");
                for (unsigned i = 0; i < self->extra_cursors.count; i++) {
                    index_type cell = self->extra_cursors.locations[i].cell, shape = self->extra_cursors.locations[i].shape;
                    index_type y = cell / self->columns, x = cell - (y * self->columns);
                    pr("%d:2:%u:%u;", shape > 3 ? 29 : (int)shape, y + 1, x + 1);
                }
                if (*(p - 1) == ';') p--;
                *(p++) = ' ';
                *(p++) = 'q';
                *(p++) = 0;
                write_escape_code_to_child(self, ESC_CSI, buf);
            }
        } else if (queried_shape == 101) {
            char buf[64], *p = buf;
            size_t sz = sizeof(buf);
            pr(">101;30:");
            DynamicColor ecc = self->extra_cursors.color.text;
#define o()                                                                                                        \
    switch (ecc.type) {                                                                                            \
        case COLOR_NOT_SET: pr("0"); break;                                                                        \
        case COLOR_IS_SPECIAL: pr("1"); break;                                                                     \
        case COLOR_IS_INDEX: pr("5:%u", ecc.rgb & 0xff); break;                                                    \
        case COLOR_IS_RGB: pr("2:%u:%u:%u", (ecc.rgb >> 16) & 0xff, (ecc.rgb >> 8) & 0xff, ecc.rgb & 0xff); break; \
    }

            o();
            pr(";40:");
            ecc = self->extra_cursors.color.cursor;
            o();
#undef o
            pr(" q");
            write_escape_code_to_child(self, ESC_CSI, buf);
        }
        return;
#undef pr
    }
    if (queried_shape == 30 || queried_shape == 40) {
        DynamicColor *ecc = queried_shape == 40 ? &self->extra_cursors.color.cursor : &self->extra_cursors.color.text;
        self->extra_cursors.dirty = true;
        switch (params[0]) {
            case 0: ecc->type = COLOR_NOT_SET; break;
            case 1: ecc->type = COLOR_IS_SPECIAL; break;
            case 2:
                if (num_params > 3) {
                    ecc->type = COLOR_IS_RGB;
                    ecc->rgb = ((params[1] & 0xff) << 16) | ((params[2] & 0xff) << 8) | (params[3] & 0xff);
                }
                break;
            case 5:
                if (num_params > 1) {
                    ecc->type = COLOR_IS_INDEX;
                    ecc->rgb = params[1] & 0xff;
                }
                break;
        }
        return;
    }
    uint8_t shape = 0;
    switch (queried_shape) {
        case 29: shape = 4; break;
        case 0:
        case 1:
        case 2:
        case 3: shape = queried_shape; break;
        default: return;
    }
    self->extra_cursors.dirty = true;
    int type = params[0];
    params++;
    num_params--;
    int extra[2];
    switch (type) {
        case 0:
            extra[0] = MIN(self->cursor->y, self->lines - 1) + 1;
            extra[1] = MIN(self->cursor->x, self->columns - 1) + 1;
            params = extra;
            num_params = 2;
            /* fallthrough */
        case 2: {
            multi_cursor_map s;
            vt_init(&s);
            for (unsigned i = 0; i < self->extra_cursors.count; i++) {
                vt_insert(&s, self->extra_cursors.locations[i].cell, self->extra_cursors.locations[i].shape);
            }
            for (unsigned i = 0; i + 1 < num_params; i += 2) {
                index_type y = params[i] - 1, x = params[i + 1] - 1;
                if (!shape) {
                    vt_erase(&s, y * self->columns + x);
                } else if (y < self->lines && x < self->columns) vt_insert(&s, y * self->columns + x, shape);
            }
            self->extra_cursors.count = vt_size(&s);
            ensure_space_for(&self->extra_cursors, locations, ExtraCursor, self->extra_cursors.count, capacity, 20 * 80, false);
            self->extra_cursors.count = 0;
            vt_create_for_loop(multi_cursor_map_itr, i, &s) {
                self->extra_cursors.locations[self->extra_cursors.count++] = (ExtraCursor){.shape = i.data->val, .cell = i.data->key};
            }
            vt_cleanup(&s);
        } break;
        case 4: {
            if (num_params < 4) { // full screen
                switch (shape) {
                    default: self->extra_cursors.count = 0; break;
                    case 1:
                    case 2:
                    case 3:
                    case 4:
                        ensure_space_for(&self->extra_cursors, locations, ExtraCursor, self->lines * self->columns, capacity, 20 * 80, false);
                        self->extra_cursors.count = self->lines * self->columns;
                        for (index_type cell = 0; cell < self->lines * self->columns; cell++) {
                            self->extra_cursors.locations[cell].shape = shape;
                            self->extra_cursors.locations[cell].cell = cell;
                        }
                        break;
                }
                break;
            }
            unsigned count = 0;
            for (unsigned i = 0; i < self->extra_cursors.count; i++) {
                bool in_some_region = false;
                index_type y = self->extra_cursors.locations[i].cell / self->columns, x = self->extra_cursors.locations[i].cell - (self->columns * y);
                for (unsigned i = 0; i + 3 < num_params && !in_some_region; i += 4) {
                    index_type top = params[i] - 1, left = params[i + 1] - 1, bottom = params[i + 2] - 1, right = params[i + 3] - 1;
                    in_some_region = top <= y && y <= bottom && left <= x && x <= right;
                }
                if (!in_some_region) self->extra_cursors.locations[count++] = self->extra_cursors.locations[i];
            }
            self->extra_cursors.count = count;
            if (shape) {
                for (unsigned i = 0; i + 3 < num_params; i += 4) {
                    index_type top = params[i] - 1, left = params[i + 1] - 1, bottom = params[i + 2] - 1, right = params[i + 3] - 1;
                    bottom = MIN(bottom, self->lines - 1);
                    right = MIN(right, self->columns - 1);
                    if (right < left || bottom < top) continue;
                    size_t xnum = right + 1 - left, ynum = bottom + 1 - top;
                    ensure_space_for(&self->extra_cursors, locations, ExtraCursor, self->extra_cursors.count + xnum * ynum, capacity, 20 * 80, false);
                    for (index_type y = top; y <= bottom; y++) {
                        for (index_type x = left; x <= right; x++) {
                            self->extra_cursors.locations[self->extra_cursors.count++] = (ExtraCursor){.shape = shape, .cell = y * self->columns + x};
                        }
                    }
                }
            }
        } break;
    }
}

void
set_title(Screen *self, PyObject *title) {
    CALLBACK("title_changed", "O", title);
}

void
osc_context(Screen *self, PyObject *ctx) {
    CALLBACK("osc_context", "O", ctx);
}

void
program_status_report(Screen *self, PyObject *data) {
    CALLBACK("program_status_report", "O", data);
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
    if (color == NULL) {
        CALLBACK("set_dynamic_color", "I", code);
    } else {
        CALLBACK("set_dynamic_color", "IO", code, color);
    }
}

void
color_control(Screen *self, unsigned int code, PyObject *spec) {
    if (spec) CALLBACK("color_control", "IO", code, spec);
}

void
clipboard_control(Screen *self, int code, PyObject *data) {
    if (code == 52 || code == -52) {
        CALLBACK("clipboard_control", "OO", data, code == -52 ? Py_True : Py_False);
    } else {
        CALLBACK("clipboard_control", "OO", data, Py_None);
    }
}

void
file_transmission(Screen *self, PyObject *data) {
    CALLBACK("file_transmission", "O", data);
}

static void
parse_prompt_mark(Screen *self, char *buf, PromptKind *pk) {
    char *saveptr, *str = buf;
    while (true) {
        const char *token = strtok_r(str, ";", &saveptr);
        str = NULL;
        if (token == NULL) return;
        if (strcmp(token, "k=s") == 0) *pk = SECONDARY_PROMPT;
        else if (strcmp(token, "redraw=0") == 0) self->prompt_settings.redraws_prompts_at_all = 0;
        else if (strcmp(token, "special_key=1") == 0) self->prompt_settings.uses_special_keys_for_cursor_movement = 1;
        else if (strcmp(token, "click_events=1") == 0) {
            self->prompt_settings.supports_click_events = 1;
            self->prompt_settings.relative_click_events = 0;
        } else if (strcmp(token, "click_events=2") == 0) {
            self->prompt_settings.supports_click_events = 1;
            self->prompt_settings.relative_click_events = 1;
        }
    }
}

static void
mark_command_finished(Screen *self) {
    if (self->command_state.running) {
        self->command_state.running = false;
        self->command_state.finished_at = monotonic();
    }
}

void
shell_prompt_marking(Screen *self, char *buf) {
    if (self->cursor->y < self->lines) {
        char ch = buf[0];
        switch (ch) {
            case 'A': {
                PromptKind pk = PROMPT_START;
                self->prompt_settings.val = 0;
                self->prompt_settings.redraws_prompts_at_all = 1;
                parse_prompt_mark(self, buf + 1, &pk);
                self->linebuf->line_attrs[self->cursor->y].prompt_kind = pk;
                if (pk == PROMPT_START) {
                    mark_command_finished(self);
                    CALLBACK("cmd_output_marking", "O", Py_False);
                }
            } break;
            case 'C': {
                self->linebuf->line_attrs[self->cursor->y].prompt_kind = OUTPUT_START;
                self->command_state.running = true;
                self->command_state.started_at = monotonic();
                const char *cmdline = "";
                if (strstr(buf + 1, ";cmdline") == buf + 1) { cmdline = buf + 2; }
                RAII_PyObject(c, PyUnicode_DecodeUTF8(cmdline, strlen(cmdline), "replace"));
                if (c) {
                    CALLBACK("cmd_output_marking", "OO", Py_True, c);
                } else PyErr_Print();
            } break;
            case 'D': {
                const char *exit_status = buf[1] == ';' ? buf + 2 : "";
                mark_command_finished(self);
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
        index_type y;
        unsigned int scrolled_by;
        if (!last_visited_prompt_viewport(self, &y, &scrolled_by)) return false;
        self->scrolled_by = scrolled_by;
    } else {
        int delta = num_of_prompts_to_jump < 0 ? -1 : 1;
        num_of_prompts_to_jump = num_of_prompts_to_jump < 0 ? -num_of_prompts_to_jump : num_of_prompts_to_jump;
        const int oldest_y = -(int)self->historybuf->count;
        int y = -(int)self->scrolled_by;
#define ensure_y_ok \
    if (y >= (int)self->lines || y < oldest_y) return false;
        ensure_y_ok;
        y += scroll_offset;
        while (num_of_prompts_to_jump) {
            y += delta;
            ensure_y_ok;
            if (range_line_(self, y)->attrs.prompt_kind == PROMPT_START) { num_of_prompts_to_jump--; }
        }
#undef ensure_y_ok
        const int viewport_top = MAX(oldest_y, MIN(0, y - scroll_offset));
        self->scrolled_by = -viewport_top;
        const int prompt_y = y - viewport_top;
        // The context above the prompt can include another command's output.
        screen_set_last_visited_prompt(self, prompt_y >= 0 && prompt_y < (int)self->lines ? prompt_y : 0);
    }
    if (old != self->scrolled_by) {
        reset_pixel_scroll(self, 0);
        dirty_scroll(self);
    }
    return old != self->scrolled_by;
}

void
set_color_table_color(Screen *self, unsigned int code, PyObject *color) {
    if (color == NULL) {
        CALLBACK("set_color_table_color", "I", code);
    } else {
        CALLBACK("set_color_table_color", "IO", code, color);
    }
}

static void
set_last_reported_cwd(Screen *self, const char *data, size_t sz) {
    PyObject *x = PyBytes_FromStringAndSize(data, sz);
    if (x) {
        bool changed = !self->last_reported_cwd || PyBytes_GET_SIZE(self->last_reported_cwd) != (Py_ssize_t)sz ||
                       memcmp(PyBytes_AS_STRING(self->last_reported_cwd), data, sz) != 0;
        Py_CLEAR(self->last_reported_cwd);
        self->last_reported_cwd = x;
        if (changed) CALLBACK("on_cwd_change", "O", x);
    } else {
        PyErr_Clear();
    }
}

void
process_cwd_notification(Screen *self, unsigned int code, const char *data, size_t sz) {
    if (code == 7) set_last_reported_cwd(self, data, sz);
    else if (code == 9) {
        // ConEmu OSC 9;9;path where path is a plain, possibly quoted, path
        if (sz > 1 && data[0] == '"' && data[sz - 1] == '"') {
            data++;
            sz -= 2;
        }
        if (!sz || data[0] != '/') return; // only absolute paths are meaningful
        static const char prefix[] = "kitty-shell-cwd://";
        const size_t psz = sizeof(prefix) - 1;
        char *url = malloc(psz + sz);
        if (!url) {
            log_error("Out of memory processing OSC 9;9 cwd report");
            return;
        }
        memcpy(url, prefix, psz);
        memcpy(url + psz, data, sz);
        set_last_reported_cwd(self, url, psz + sz);
        free(url);
    }
    // we ignore OSC 6 document reporting as we dont have a use for it
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
        } else {
            PyErr_Print();
        }
    }
    return ret != 0;
}

void
screen_push_colors(Screen *self, unsigned int idx) {
    if (colorprofile_push_colors(self->color_profile, idx)) self->color_profile->dirty = true;
}

void
screen_pop_colors(Screen *self, unsigned int idx) {
    color_type bg_before =
        colorprofile_to_color(self->color_profile, self->color_profile->overridden.default_bg, self->color_profile->configured.default_bg).rgb;
    if (colorprofile_pop_colors(self->color_profile, idx)) {
        self->color_profile->dirty = true;
        color_type bg_after =
            colorprofile_to_color(self->color_profile, self->color_profile->overridden.default_bg, self->color_profile->configured.default_bg).rgb;
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

void
screen_handle_kitty_dcs(Screen *self, const char *callback_name, PyObject *cmd) {
    CALLBACK(callback_name, "O", cmd);
}

void
screen_request_capabilities(Screen *self, char c, const char *query) {
    static char buf[128];
    int shape = 0;
    switch (c) {
        case '+': {
            CALLBACK("request_capabilities", "s", query);
        } break;
        case '$':
            // report status DECRQSS
            if (strcmp(" q", query) == 0) {
                // cursor shape DECSCUSR
                switch (self->cursor->shape) {
                    case NO_CURSOR_SHAPE:
                    case CURSOR_HOLLOW:
                    case NUM_OF_CURSOR_SHAPES: shape = 1; break;
                    case CURSOR_BLOCK: shape = self->cursor->non_blinking ? 2 : 0; break;
                    case CURSOR_UNDERLINE: shape = self->cursor->non_blinking ? 4 : 3; break;
                    case CURSOR_BEAM: shape = self->cursor->non_blinking ? 6 : 5; break;
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
        if (!dest->items) {
            dest->capacity = 0;
            dest->count = 0;
            return false;
        }
        dest->capacity = src->count;
    }
    dest->count = src->count;
    for (unsigned i = 0; i < dest->count; i++) memcpy(dest->items + i, src->items + i, sizeof(dest->items[0]));
    dest->last_rendered_count = src->last_rendered_count;
    return true;
}

static Line *render_line_for_virtual_y(Screen *self, int y, Line *line, index_type *lnum, bool *is_history);

// For a frame without maps: the history rows rendered at levels are shown in logical order from now on
static void
bidi_frame_unmapped(Screen *self) {
    if (self->bidi_maps->live) historybuf_invalidate_render_cache(self->historybuf);
    self->bidi_maps->live = false;
    self->bidi_maps->valid = false;
    self->bidi_maps->reusable = false;
}

bool
screen_pause_rendering(Screen *self, bool pause, int for_in_ms) {
    if (!pause) {
        if (!self->paused_rendering.expires_at) return false;
        self->paused_rendering.expires_at = 0;
        // ensure cell data is updated on GPU
        self->is_dirty = true;
        // ensure selection data is updated on GPU
        self->selections.last_rendered_count = SIZE_MAX;
        self->url_ranges.last_rendered_count = SIZE_MAX;
        self->extra_cursors.dirty = true;
        // free grman data
        grman_pause_rendering(NULL, self->paused_rendering.grman);
        // free extra cursors
        free(self->paused_rendering.extra_cursors.locations);
        zero_at_ptr(&self->paused_rendering.extra_cursors);
        // The snapshot is kept for reuse, but its text must not keep text
        // cache entries, and the glyph protocol glyphs they hold, alive
        if (self->paused_rendering.linebuf) linebuf_clear(self->paused_rendering.linebuf, BLANK_CHAR);
        ssr_release_pause_capture(self);
        return true;
    }
    if (self->paused_rendering.expires_at) return false;
    if (!self->paused_rendering.grman) self->paused_rendering.grman = grman_alloc(true);
    if (!self->paused_rendering.grman) return false;
    if (for_in_ms <= 0) for_in_ms = 2000;
    self->paused_rendering.expires_at = monotonic() + ms_to_monotonic_t(for_in_ms);
    self->paused_rendering.inverted = self->modes.mDECSCNM;
    self->paused_rendering.scrolled_by = self->scrolled_by;
    self->paused_rendering.history_count = self->historybuf->count;
    self->paused_rendering.on_main_screen = self->linebuf == self->main_linebuf;
    self->paused_rendering.cell_data_updated = false;
    self->paused_rendering.cursor_visible = self->modes.mDECTCEM;
    // Preserve the pixel scroll geometry so that pausing does not cause the rendered content to jump, see #10794
    self->paused_rendering.pixel_scroll = live_pixel_scroll_enabled(self);
    self->paused_rendering.pixel_scroll_offset_y = self->paused_rendering.pixel_scroll ? self->pixel_scroll_offset_y : 0;
    memcpy(&self->paused_rendering.cursor, self->cursor, sizeof(self->paused_rendering.cursor));
    memcpy(&self->paused_rendering.color_profile, self->color_profile, sizeof(self->paused_rendering.color_profile));
    const index_type row_offset = self->paused_rendering.pixel_scroll, num_rows = self->lines + row_offset;
    if (!self->paused_rendering.linebuf || self->paused_rendering.linebuf->xnum != self->columns || self->paused_rendering.linebuf->ynum != num_rows) {
        if (self->paused_rendering.linebuf) Py_CLEAR(self->paused_rendering.linebuf);
        self->paused_rendering.linebuf = alloc_linebuf(num_rows, self->columns, self->text_cache);
        if (!self->paused_rendering.linebuf) {
            PyErr_Clear();
            self->paused_rendering.expires_at = 0;
            return false;
        }
    }
    // Mapped before the copy, which takes history rows missing from the render cache without marking them dirty
    const BidiMaps *b = bidi_live_frame_reorders(self) ? bidi_prepare_live(self, false) : NULL;
    if (!b && self->bidi_maps) bidi_frame_unmapped(self);
    self->paused_rendering.linebuf->bidi_stamped = b != NULL;
    Line line = {.text_cache = self->text_cache};
    for (index_type y = 0; y < num_rows; y++) {
        index_type lnum;
        bool is_history;
        Line *src = render_line_for_virtual_y(self, (int)y - (int)row_offset, &line, &lnum, &is_history);
        if (src) {
            linebuf_init_line(self->paused_rendering.linebuf, y);
            copy_line(src, self->paused_rendering.linebuf->line);
            self->paused_rendering.linebuf->line_attrs[y] = src->attrs;
        } else linebuf_clear_line(self->paused_rendering.linebuf, y, true);
    }
    copy_selections(&self->paused_rendering.selections, &self->selections);
    copy_selections(&self->paused_rendering.url_ranges, &self->url_ranges);
    if (self->extra_cursors.count) {
        self->paused_rendering.extra_cursors.locations = calloc(self->extra_cursors.count, sizeof(self->extra_cursors.locations[0]));
        if (self->paused_rendering.extra_cursors.locations) {
            self->paused_rendering.extra_cursors.count = self->extra_cursors.count;
            self->paused_rendering.extra_cursors.dirty = self->extra_cursors.dirty;
            memcpy(
                self->paused_rendering.extra_cursors.locations,
                self->extra_cursors.locations,
                sizeof(self->extra_cursors.locations[0]) * self->extra_cursors.count);
        }
    }
    grman_pause_rendering(self->grman, self->paused_rendering.grman);
    ssr_capture_for_pause(self);
    return true;
}

static color_type
effective_cell_edge_color(char_type ch, color_type fg, color_type bg, bool is_left_edge) {
    START_ALLOW_CASE_RANGE
    if (ch == 0x2588) return fg; // full block
    if (is_left_edge) {
        switch (ch) {
            case 0x2589 ... 0x258f: // left eighth blocks
            case 0xe0b0:
            case 0xe0b4:
            case 0xe0b8:
            case 0xe0bc:  // powerline blocks
            case 0x1fb6a: // 🭪
                return fg;
        }
    } else {
        switch (ch) {
            case 0x2590:              // right half block
            case 0x1fb87 ... 0x1fb8b: // eighth right blocks
            case 0xe0b2:
            case 0xe0b6:
            case 0xe0ba:
            case 0xe0be:
            case 0x1fb68: // 🭨
                return fg;
        }
    }
    return bg;
    END_ALLOW_CASE_RANGE
}


bool
get_line_edge_colors_at_row(Screen *self, index_type y, color_type *left, color_type *right, bool *left_is_default, bool *right_is_default) {
    // Return the color at the left and right edges of the specified row.
    // Any of the output pointers may be NULL if that value is not needed.
    Line *line = range_line_(self, y);
    if (!line) return false;
    color_type left_cell_fg = OPT(foreground), left_cell_bg = OPT(background), right_cell_bg = OPT(background), right_cell_fg = OPT(foreground);
    index_type cell_color_x = 0;
    char_type left_char = line_get_char(line, cell_color_x);
    bool reversed = false;
    colors_for_cell(line, self->color_profile, &cell_color_x, &left_cell_fg, &left_cell_bg, &reversed);
    if (left_is_default) *left_is_default = (line_cell_style(line, cell_color_x)->bg & 0xff) == 0;
    if (left) *left = effective_cell_edge_color(left_char, left_cell_fg, left_cell_bg, true);
    if (line->xnum > 0) cell_color_x = line->xnum - 1;
    char_type right_char = line_get_char(line, cell_color_x);
    reversed = false; // reset: colors_for_cell only sets this flag, never clears it
    colors_for_cell(line, self->color_profile, &cell_color_x, &right_cell_fg, &right_cell_bg, &reversed);
    if (right_is_default) *right_is_default = (line_cell_style(line, cell_color_x)->bg & 0xff) == 0;
    if (right) *right = effective_cell_edge_color(right_char, right_cell_fg, right_cell_bg, false);
    return true;
}

bool
get_line_edge_colors(Screen *self, color_type *left, color_type *right) {
    // Return the color at the left and right edges of the line with the cursor on it
    return get_line_edge_colors_at_row(self, self->cursor->y, left, right, NULL, NULL);
}


static void
update_line_data(Line *line, unsigned int dest_y, uint8_t *data) {
    CellGPUData *dest = (CellGPUData *)(data + sizeof(CellGPUData) * dest_y * line->xnum);
    cells_for_gpu(line->cpu_cells, line->render_cells, line->xnum, dest);
}

static void
update_line_data_permuted(Line *line, unsigned int dest_y, uint8_t *data, const uint16_t *v2l) {
    CellGPUData *dest = (CellGPUData *)(data + sizeof(CellGPUData) * dest_y * line->xnum);
    cells_for_gpu_permuted(line->cpu_cells, line->render_cells, v2l, line->xnum, dest);
}

static void
update_line_data_blank(unsigned xnum, unsigned int dest_y, uint8_t *data) {
    const size_t sz = xnum * sizeof(CellGPUData);
    memset(data + sz * dest_y, 0, sz);
}


static Line *
render_line_for_virtual_y(Screen *self, int y, Line *line, index_type *lnum, bool *is_history) {
    if (y < (int)self->scrolled_by) {
        int idx = (int)self->scrolled_by - 1 - y;
        if (idx >= 0 && (unsigned)idx < self->historybuf->count) {
            if (historybuf_init_line_for_render(self->historybuf, idx, line, render_lines_for_screen(self))) line->attrs.has_dirty_text = true;
            line->xnum = self->columns;
            line->ynum = (index_type)MIN(MAX(y, 0), (int)self->lines - 1);
            *lnum = (index_type)idx;
            *is_history = true;
            return line;
        }
        return NULL;
    }
    y -= self->scrolled_by;
    if (y >= 0 && y < (int)self->lines) {
        linebuf_init_line_at(self->linebuf, (index_type)y, line);
        *lnum = (index_type)y;
        *is_history = false;
        return line;
    }
    return NULL;
}


static void
screen_reset_dirty(Screen *self) {
    self->is_dirty = false;
}

static bool
screen_has_marker(Screen *self) {
    return self->marker != NULL;
}

static uint32_t
diacritic_to_rowcolumn(char_type c) {
    return diacritic_to_num(c);
}

static uint32_t
color_to_id(color_type c) {
    // Just take 24 most significant bits of the color. This works both for
    // 24-bit and 8-bit colors.
    return (c >> 8) & 0xffffff;
}

static bool
ssr_is_column_edge(const Screen *self, int32_t row, index_type x) {
    // Whether x is the left or right edge of the rectangle of a smooth scroll
    // region intersecting the row, the cells on either side of which move
    // independently
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) {
        const SmoothScrollRegion *r = self->smooth_scroll.regions + i;
        if ((int32_t)r->top <= row && row < (int32_t)r->bottom && (x == r->left || x == r->right)) return true;
    }
    return false;
}

static uint32_t
ssr_history_region_for_row(const Screen *self, int32_t row) {
    // The region whose overflow buffer above it is the scrollback, when row
    // is the last line of the scrollback and it moved there from the region.
    // Other lines of the scrollback, and their images, never move with it, see
    // ssr_shift_by_one_row().
    if (row != -1 || !self->historybuf->count) return 0;
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) {
        const SmoothScrollRegion *r = self->smooth_scroll.regions + i;
        if (ssr_uses_history(self, r)) return r->pushed_to_history ? r->id : 0;
    }
    return 0;
}

// Scan the line and create cell images in place of unicode placeholders
// reserved for image placement. The line is at row of the screen and starts
// at column x. When overflow_region is non-zero, the line is in the overflow
// buffer of that region and the images are created moving with it.
static void
render_line_graphics(Screen *self, Line *line, int32_t row, index_type x, uint32_t overflow_region) {
    // If there are no image placeholders now, no need to rescan the line.
    if (!line->attrs.has_image_placeholders) return;
    // Remove existing images.
    uint32_t region = overflow_region;
    if (overflow_region) grman_remove_region_cell_images(self->grman, row, overflow_region);
    else {
        // The images of the cells of the screen do not replace the images
        // in the overflow buffers of regions at the same row, except for the
        // scrollback, which is the overflow buffer of the region using it
        region = UNLIKELY(self->smooth_scroll.count) ? ssr_history_region_for_row(self, row) : 0;
        CellImageRegionRows kept[MAX_SMOOTH_SCROLL_REGIONS];
        const unsigned num_kept = UNLIKELY(self->smooth_scroll.count) ? ssr_cell_image_region_rows(self, self->linebuf, region, kept) : 0;
        grman_remove_cell_images(self->grman, row, row, kept, num_kept);
    }
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
        uint32_t cur_img_id_lower24bits = 0;
        uint32_t cur_placement_id = 0;
        uint32_t cur_img_id_higher8bits = 0;
        uint32_t cur_img_row = 0;
        uint32_t cur_img_col = 0;
        if (cell_first_char(cpu_cell, self->text_cache) == IMAGE_PLACEHOLDER_CHAR) {
            line->attrs.has_image_placeholders = true;
            // The lower 24 bits of the image id are encoded in the foreground
            // color, and the placement id is (optionally) in the underline color.
            const CellStyle *st = style_table_get(self->style_table, cpu_cell->style_idx);
            cur_img_id_lower24bits = color_to_id(st->fg);
            cur_placement_id = color_to_id(st->decoration_fg);
            text_in_cell(cpu_cell, self->text_cache, self->lc);
            // If the char has diacritics, use them as row and column indices.
            if (self->lc->count > 1 && self->lc->chars[1]) cur_img_row = diacritic_to_rowcolumn(self->lc->chars[1]);
            if (self->lc->count > 2 && self->lc->chars[2]) cur_img_col = diacritic_to_rowcolumn(self->lc->chars[2]);
            // The third diacritic is used to encode the higher 8 bits of the
            // image id (optional).
            if (self->lc->count > 3 && self->lc->chars[3]) cur_img_id_higher8bits = diacritic_to_rowcolumn(self->lc->chars[3]);
        }
        // The current run is continued if the lower 24 bits of the image id and
        // the placement id are the same as in the previous cell and everything
        // else is unknown or compatible with the previous cell.
        const bool continues_run = run_length > 0 && cur_img_id_lower24bits == prev_img_id_lower24bits && cur_placement_id == prev_placement_id &&
                                   (!cur_img_row || cur_img_row == prev_img_row) && (!cur_img_col || cur_img_col == prev_img_col + 1) &&
                                   (!cur_img_id_higher8bits || cur_img_id_higher8bits == prev_img_id_higher8bits);
        if (continues_run) {
            // If some values are unknown, infer them from the previous cell.
            cur_img_row = MAX(prev_img_row, 1u);
            cur_img_col = prev_img_col + 1;
            cur_img_id_higher8bits = MAX(prev_img_id_higher8bits, 1u);
        }
        // Runs are split at the edges of smooth scroll regions, so that the
        // parts of the image on either side move with their cells
        if (continues_run && !(UNLIKELY(self->smooth_scroll.count) && !overflow_region && ssr_is_column_edge(self, row, i))) {
            // This cell continues the current run.
            run_length++;
        } else {
            // This cell breaks the current run. Render the current run if it
            // has a non-zero length.
            if (run_length > 0) {
                uint32_t img_id = prev_img_id_lower24bits | (prev_img_id_higher8bits - 1) << 24;
                grman_put_cell_image(
                    self->grman,
                    row,
                    x + i - run_length,
                    img_id,
                    prev_placement_id,
                    prev_img_col - run_length,
                    prev_img_row - 1,
                    run_length,
                    1,
                    region,
                    self->cell_size);
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
        grman_put_cell_image(
            self->grman,
            row,
            x + i - run_length,
            img_id,
            prev_placement_id,
            prev_img_col - run_length,
            prev_img_row - 1,
            run_length,
            1,
            region,
            self->cell_size);
    }
}

static void
screen_render_line_graphics(Screen *self, Line *line, int32_t row) {
    render_line_graphics(self, line, row, 0, 0);
}

static void
ssr_render_edge_line_graphics(Screen *self, bool mark_clean) {
    // The images of the unicode placeholders in the partially visible rows at
    // the edges of the shifted vertically scrolling regions are created from
    // the cells of those rows, in their overflow buffers. The images moving
    // with the region are only replaced when the rows change, as they might
    // have been changed while in the rectangle without being rendered, for
    // example, when redrawn inside a synchronized update. The rows are marked
    // clean when their text is rendered, by ssr_update_strip_cell_data(),
    // unless mark_clean is true.
    if (UNLIKELY(self->paused_rendering.expires_at) || self->scrolled_by || !grman_has_any_images(self->grman)) return;
    Line line = {.text_cache = self->text_cache};
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) {
        SmoothScrollRegion *r = self->smooth_scroll.regions + i;
        if (r->horizontal || !r->offset || !r->overflow) continue;
        for (int edge = 0; edge < 2; edge++) {
            const bool before = edge == 0;
            if (before && ssr_uses_history(self, r)) {
                // With pixel scrolling the last line of the scrollback is rendered with the screen
                if (!pixel_scroll_enabled(self) && self->historybuf->count) {
                    historybuf_init_line(self->historybuf, 0, &line);
                    if (!line.attrs.has_dirty_text) continue;
                    line.xnum = self->columns;
                    screen_render_line_graphics(self, &line, -1);
                    if (mark_clean) historybuf_mark_line_clean(self->historybuf, 0);
                }
                continue;
            }
            if (!(before ? r->num_before : r->num_after)) continue;
            const index_type slot = ssr_slot(r, before, 0);
            linebuf_init_line_at(r->overflow, slot, &line);
            if (!line.attrs.has_dirty_text) continue;
            render_line_graphics(self, &line, before ? (int32_t)r->top - 1 : (int32_t)r->bottom, r->left, r->id);
            r->overflow->line_attrs[slot].has_image_placeholders = line.attrs.has_image_placeholders;
            if (mark_clean) linebuf_mark_line_clean(r->overflow, slot);
        }
    }
}

// This functions is similar to screen_update_cell_data, but it only updates
// line graphics (cell images) and then marks lines as clean. It's used
// exclusively for testing unicode placeholders.
static void
screen_update_only_line_graphics_data(Screen *self) {
    index_type lnum = 0;
    clamp_scroll_position(self);
    screen_reset_dirty(self);
    self->scroll_changed = false;
    const unsigned int render_lines = render_lines_for_screen(self);
    const int render_row_offset = pixel_scroll_enabled(self);
    // Rows marked clean here were not seen by a walk
    if (self->bidi_maps) self->bidi_maps->reusable = false;
    Line line = {.text_cache = self->text_cache};
    for (unsigned int render_row = 0; render_row < render_lines; render_row++) {
        const int virtual_y = (int)render_row - render_row_offset;
        bool is_history = false;
        Line *linep = render_line_for_virtual_y(self, virtual_y, &line, &lnum, &is_history);
        if (linep) {
            screen_render_line_graphics(self, linep, virtual_y - (int)self->scrolled_by);
            if (linep->attrs.has_dirty_text) {
                if (is_history) historybuf_mark_line_clean(self->historybuf, lnum);
                else linebuf_mark_line_clean(self->linebuf, lnum);
            }
        }
    }
    if (UNLIKELY(self->smooth_scroll.count)) ssr_render_edge_line_graphics(self, true);
}

// The paused rendering snapshot holds the rows that were rendered when
// rendering was paused: with pixel scrolling an extra leading row, then the
// rows of the screen, which show the scrollback if it was scrolled back. Row
// y of the linebuf, the coordinates of the cursor and of selections, is at
// snapshot row y + paused_snapshot_row_offset(), so negative values of y are
// scrollback rows.
static int
paused_snapshot_row_offset(const Screen *self) {
    return (int)self->paused_rendering.pixel_scroll + (int)self->paused_rendering.scrolled_by;
}

static Line *
paused_line_for_linebuf_row(Screen *self, int y) {
    // Must only be called while rendering is paused, NULL if the row is not in the snapshot
    const int row = y + paused_snapshot_row_offset(self);
    if (row < 0 || row >= (int)self->paused_rendering.linebuf->ynum) return NULL;
    linebuf_init_line(self->paused_rendering.linebuf, (index_type)row);
    return self->paused_rendering.linebuf->line;
}

Line *
screen_line_for_cursor(Screen *self, index_type x, index_type y, Line *overlay_line) {
    // The line, as rendered, with the cell under a cursor at (x, y) in linebuf
    // coordinates, or NULL if there is no such cell. While rendering is paused
    // that is a row of the snapshot. Otherwise it is the linebuf row, except
    // on the row of an active overlay, whose pre-edit text is drawn over the
    // linebuf only in the overlay cells, then it is overlay_line, set to the
    // linebuf row with the overlay cells. Other than overlay_line, the
    // returned line is the shared line object of the linebuf or the snapshot,
    // so it is only valid until the next linebuf_init_line() on them.
    if (x >= self->columns || y >= self->lines) return NULL;
    if (self->paused_rendering.expires_at) return paused_line_for_linebuf_row(self, (int)y);
    linebuf_init_line(self->linebuf, y);
    if (!screen_is_overlay_active(self) || y != self->overlay_line.ynum) return self->linebuf->line;
    *overlay_line = *self->linebuf->line;
    overlay_line->cpu_cells = self->overlay_line.cpu_cells;
    overlay_line->render_cells = self->overlay_line.render_cells;
    return overlay_line;
}

index_type
screen_multicell_char_rows_for_cursor(Screen *self, const CPUCell *ref, index_type x, index_type y) {
    // The number of rows, from row y down, of the multicell char whose cell,
    // as rendered, at (x, y) in linebuf coordinates is ref. Only the rows that
    // actually continue the char are counted, as the char can be cut off at
    // the bottom of the screen or split by a vertically scrolled smooth scroll
    // region, with its lower rows in the overflow buffer. Does not change the
    // shared line objects, so the line returned by screen_line_for_cursor()
    // stays valid.
    LineBuf *lb = self->linebuf;
    int offset = 0;
    if (self->paused_rendering.expires_at) {
        lb = self->paused_rendering.linebuf;
        offset = paused_snapshot_row_offset(self);
    }
    index_type n = 1;
    for (; ref->y + n < ref->scale; n++) {
        const int row = (int)(y + n) + offset;
        if (y + n >= self->lines || row < 0 || row >= (int)lb->ynum) break;
        if (!continues_multicell_char(linebuf_cpu_cells_for_line(lb, (index_type)row) + x, ref, ref->y + n)) break;
    }
    return n;
}

// Bidi upload {{{
static bool
screen_bidi_maps_usable(const Screen *self) {
    const BidiMaps *b = self->bidi_maps;
    const LineBuf *shown = self->paused_rendering.expires_at ? self->paused_rendering.linebuf : self->linebuf;
    return b && b->valid && b->cols == self->columns && b->rows == render_lines_for_screen(self) && b->source == shown;
}

static const BidiMaps *
selection_bidi_maps(Screen *self) {
    // The maps the selection data is put in visual order by, NULL when they do not describe the frame
    BidiMaps *b = self->bidi_maps;
    b->changed = false;
    return (b->selection_used_maps = screen_bidi_maps_usable(self)) ? b : NULL;
}

static void
copy_selection_in_visual_order(const BidiMaps *b, const uint8_t *src, uint8_t *dest, size_t stride) {
    const size_t row_size = (size_t)b->cols * stride;
    for (index_type r = 0; r < b->rows;) {
        if (b->active[r]) {
            bidi_copy_row_bytes(b->v2l + (size_t)r * b->cols, b->cols, src + r * row_size, dest + r * row_size, stride);
            r++;
            continue;
        }
        index_type end = r + 1;
        while (end < b->rows && !b->active[end]) end++;
        memcpy(dest + r * row_size, src + r * row_size, (end - r) * row_size);
        r = end;
    }
}

static bool
bidi_selection_dirty(const Screen *self) {
    const BidiMaps *b = self->bidi_maps;
    return (b->changed || screen_bidi_maps_usable(self) != b->selection_used_maps) &&
           (self->selections.count || self->url_ranges.count || self->extra_cursors.count);
}

void
screen_bidi_logical_click(Screen *self, index_type *x, index_type y, bool *in_left_half) {
    if (!screen_bidi_maps_usable(self)) return;
    const BidiMaps *b = self->bidi_maps;
    const index_type render_row = y + pixel_scroll_enabled(self);
    *x = bidi_logical_x(b, render_row, *x);
    // The left half of a right-to-left cell is drawn on its right
    if (bidi_cell_is_rtl(b, render_row, *x)) *in_left_half = !*in_left_half;
}

index_type
screen_bidi_visual_x(Screen *self, index_type x, index_type y) {
    if (!screen_bidi_maps_usable(self)) return x;
    return bidi_visual_x(self->bidi_maps, y + pixel_scroll_enabled(self), x, 1);
}

static inline index_type
cell_span(const CPUCell *c) {
    return c->is_multicell && c->x == 0 ? mcd_x_limit(c) : 1;
}

// Indexes the bidi maps and the paused snapshot
static inline index_type
render_row_of(const Screen *self, index_type y) {
    return y + rendered_scrolled_by(self) + pixel_scroll_enabled(self);
}

// For a beam of a right-to-left cell, the left edge of the column past its character
static index_type
cursor_cell_visual(Screen *self, index_type x, index_type y, CursorShape shape) {
    if (x >= self->columns || !screen_bidi_maps_usable(self)) return x;
    const BidiMaps *b = self->bidi_maps;
    const index_type render_row = render_row_of(self, y);
    if (render_row >= b->rows || !b->has_levels[render_row]) return x;
    const CPUCell *cells = self->paused_rendering.expires_at ? linebuf_cpu_cells_for_line(self->paused_rendering.linebuf, render_row)
                                                             : linebuf_cpu_cells_for_line(self->linebuf, y);
    const bool beam_past = shape == CURSOR_BEAM && bidi_cell_is_rtl(b, render_row, x);
    // Both cells of a wide character put the beam on the character's edge
    if (beam_past && cells[x].is_multicell) x -= MIN(x, (index_type)cells[x].x);
    const index_type span = cell_span(cells + x), visual = bidi_visual_x(b, render_row, x, span);
    return beam_past && visual + span < self->columns ? visual + span : visual;
}

static bool
screen_overlay_visual_start(Screen *self, index_type *start) {
    const OverlayLine *ol = &self->overlay_line;
    if (!ol->is_active || self->paused_rendering.expires_at || !screen_bidi_maps_usable(self)) return false;
    const BidiMaps *b = self->bidi_maps;
    const index_type render_row = render_row_of(self, ol->ynum);
    if (render_row >= b->rows || !b->has_levels[render_row]) return false;
    *start = MIN(cursor_cell_visual(self, ol->xstart, ol->ynum, CURSOR_BLOCK), self->columns - MIN(ol->text_len, self->columns));
    return true;
}

// Valid after the upload, when the maps are for the frame. A beam on an odd-level cell follows the text it would extend.
index_type
screen_cursor_drawn_x(Screen *self, index_type x, index_type y, CursorShape shape) {
    index_type start;
    // The pre-edit block is drawn left to right
    if (screen_overlay_visual_start(self, &start)) return start + self->overlay_line.cursor_x - screen_overlay_line_start(self);
    return cursor_cell_visual(self, x, y, shape);
}

index_type
screen_ime_anchor_x(Screen *self) {
    index_type x;
    if (screen_is_overlay_active(self)) return screen_overlay_visual_start(self, &x) ? x : screen_overlay_line_start(self);
    if (self->paused_rendering.expires_at) return self->cursor->x;
    return cursor_cell_visual(self, self->cursor->x, self->cursor->y, CURSOR_BLOCK);
}
// }}}

#ifdef DEBUG
static void
bidi_check_unmapped_levels(const Line *line) {
    for (index_type x = 0; x < line->xnum; x++) {
        if (line->render_cells[x].level) fatal("bidi: a row of a frame with no row mapped holds levels");
    }
}
#endif

void
screen_update_cell_data(Screen *self, void *address, FONTS_DATA_HANDLE fonts_data, bool cursor_has_moved) {
    if (self->paused_rendering.expires_at) {
        if (!self->paused_rendering.cell_data_updated) {
            LineBuf *linebuf = self->paused_rendering.linebuf;
            // The GPU buffer was invalidated so every row must be written. The
            // paused linebuf has exactly render_lines_for_screen() rows.
            const int row_offset = paused_snapshot_row_offset(self);
            // The map of the pause: no upload runs while paused
            BidiMaps *b = UNLIKELY(linebuf->bidi_stamped) ? bidi_maps_for_upload(self, linebuf, linebuf->ynum) : NULL;
            if (!b && self->bidi_maps) self->bidi_maps->valid = self->bidi_maps->reusable = false;
            for (index_type y = 0; y < linebuf->ynum; y++) {
                linebuf_init_line(linebuf, y);
                const uint8_t *levels = NULL;
                const uint16_t *v2l = NULL;
                const bool relevel = UNLIKELY(b) && bidi_row(b, y, &levels, &v2l);
                if (linebuf->line->attrs.has_dirty_text || relevel) {
                    // The extra leading row and scrollback rows are never the cursor row
                    const index_type lnum = (int)y < row_offset ? self->lines : y - (index_type)row_offset;
                    render_line(fonts_data, linebuf->line, lnum, &self->paused_rendering.cursor, self->disable_ligatures, self->lc, levels);
                    if (UNLIKELY(b)) bidi_store_levels(b, y, linebuf->line);
                    // Cell images are not rendered here: this would modify the live grman using snapshot row numbers
                    if (linebuf->line->attrs.has_dirty_text && screen_has_marker(self)) mark_text_in_line(self->marker, linebuf->line, &self->as_ansi_buf);
                    linebuf_mark_line_clean(linebuf, y);
                }
                if (UNLIKELY(v2l)) update_line_data_permuted(linebuf->line, y, address, v2l);
                else update_line_data(linebuf->line, y, address);
            }
            if (self->smooth_scroll_render.num_strip_cells) ssr_update_strip_cell_data(self, address, fonts_data, b);
        }
        return;
    }
    const bool is_overlay_active = screen_is_overlay_active(self);
    clamp_scroll_position(self);
    screen_reset_dirty(self);
    update_overlay_position(self);
    const bool force_history_render = pixel_scroll_enabled(self) && self->scroll_changed;
    self->scroll_changed = false;
    const unsigned int render_lines = render_lines_for_screen(self);
    const int render_row_offset = pixel_scroll_enabled(self);
    BidiMaps *b = UNLIKELY(bidi_live_frame_reorders(self)) ? bidi_prepare_live(self, true) : NULL;
    if (!b && self->bidi_maps) bidi_frame_unmapped(self);
    // With no row mapped the rows are uploaded as without maps, and the levels stored in their render cells are already 0
    const bool mapped = UNLIKELY(b) && b->mapped;
    Line line = {.text_cache = self->text_cache};
    const uint8_t *levels = NULL;
    const uint16_t *v2l = NULL;
    bool relevel = false;
    for (unsigned int render_row = 0; render_row < render_lines; render_row++) {
        const int virtual_y = (int)render_row - render_row_offset;
        bool is_history = false;
        index_type lnum = 0;
        Line *linep = render_line_for_virtual_y(self, virtual_y, &line, &lnum, &is_history);
        if (linep == NULL) {
            update_line_data_blank(self->columns, render_row, address);
            continue;
        }
        if (UNLIKELY(mapped)) {
            levels = NULL;
            v2l = NULL;
            relevel = bidi_row(b, render_row, &levels, &v2l);
        }
        if (is_history) {
            // we render line graphics even if the line is not dirty as graphics commands received after
            // the unicode placeholder was first scanned can alter it.
            screen_render_line_graphics(self, linep, virtual_y - (int)self->scrolled_by);
            if (force_history_render || linep->attrs.has_dirty_text || relevel) {
                render_line(fonts_data, linep, lnum, self->cursor, self->disable_ligatures, self->lc, levels);
                if (UNLIKELY(mapped)) bidi_store_levels(b, render_row, linep);
#ifdef DEBUG
                else if (b) bidi_check_unmapped_levels(linep);
#endif
                if (screen_has_marker(self)) mark_text_in_line(self->marker, linep, &self->as_ansi_buf);
                historybuf_mark_line_clean(self->historybuf, lnum);
            }
        } else {
            if (linep->attrs.has_dirty_text || (cursor_has_moved && (self->cursor->y == lnum || self->last_rendered.cursor.y == lnum)) || relevel) {
                render_line(fonts_data, linep, lnum, self->cursor, self->disable_ligatures, self->lc, levels);
                if (UNLIKELY(mapped)) bidi_store_levels(b, render_row, linep);
#ifdef DEBUG
                else if (b) bidi_check_unmapped_levels(linep);
#endif
                screen_render_line_graphics(self, linep, virtual_y - (int)self->scrolled_by);
                if (linep->attrs.has_dirty_text && screen_has_marker(self)) mark_text_in_line(self->marker, linep, &self->as_ansi_buf);
                if (is_overlay_active && lnum == self->overlay_line.ynum) render_overlay_line(self, linep, fonts_data);
                linebuf_mark_line_clean(self->linebuf, lnum);
            }
        }
        if (UNLIKELY(v2l)) update_line_data_permuted(linep, render_row, address, v2l);
        else update_line_data(linep, render_row, address);
    }
    if (is_overlay_active && self->overlay_line.ynum + self->scrolled_by < self->lines) {
        if (self->overlay_line.is_dirty) {
            linebuf_init_line(self->linebuf, self->overlay_line.ynum);
            render_overlay_line(self, self->linebuf->line, fonts_data);
        }
        update_overlay_line_data(self, address);
    }
    if (self->smooth_scroll_render.num_strip_cells) {
        ssr_render_edge_line_graphics(self, false);
        ssr_update_strip_cell_data(self, address, fonts_data, self->bidi_maps && self->bidi_maps->live ? self->bidi_maps : NULL);
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
    if (selection_boundary_less_than(a, b)) {
        before = a;
        after = b;
    } else {
        before = b;
        after = a;
    }
    index_type ans = 0;
    if (before->y + 1 < after->y) ans += self->columns * (after->y - before->y - 1);
    if (before->y == after->y) ans += after->x - before->x;
    else ans += (self->columns - before->x) + after->x;
    return ans;
}

static index_type
num_lines_between_selection_boundaries(const SelectionBoundary *a, const SelectionBoundary *b) {
    const SelectionBoundary *before, *after;
    if (selection_boundary_less_than(a, b)) {
        before = a;
        after = b;
    } else {
        before = b;
        after = a;
    }
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

        ans->y = MIN(start_y, end_y);
        ans->y_limit = MAX(start_y, end_y) + 1;
        index_type x, x_limit;
        bool left_to_right = selection_is_left_to_right(sel);

        if (start->x == end->x) {
            x = start->x;
            x_limit = start->x + 1;
        } else {
            if (left_to_right) {
                x = start->x + (start->in_left_half_of_cell ? 0 : 1);
                x_limit = 1 + end->x + (end->in_left_half_of_cell ? -1 : 0);
            } else {
                x = end->x + (end->in_left_half_of_cell ? 0 : 1);
                x_limit = 1 + start->x + (start->in_left_half_of_cell ? -1 : 0);
            }
        }
        ans->first.x = x;
        ans->body.x = x;
        ans->last.x = x;
        ans->first.x_limit = x_limit;
        ans->body.x_limit = x_limit;
        ans->last.x_limit = x_limit;
    } else {
        index_type line_limit = x_limit;

        if (start_y == end_y) {
            if (start->x == end->x) {
                if (start->in_left_half_of_cell && !end->in_left_half_of_cell) {
                    // single cell selection
                    ans->first.x = start->x;
                    ans->body.x = start->x;
                    ans->last.x = start->x;
                    ans->first.x_limit = start->x + 1;
                    ans->body.x_limit = start->x + 1;
                    ans->last.x_limit = start->x + 1;
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
        ans->y = MIN(start_y, end_y);
        ans->y_limit = MAX(start_y, end_y) + 1;
    }
    ans->y += add_scrolled_by;
    ans->y_limit += add_scrolled_by;
    ans->y = MAX(ans->y, min_y);
    ans->y_limit = MAX(ans->y, ans->y_limit); // iteration is from y to y_limit
}

static XRange
xrange_for_iteration(const IterationData *idata, const int y, const Line *line) {
    XRange ans = {.x_limit = xlimit_for_line(line)};
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
        // Extend the range to include all the cells of the multicell chars at
        // its ends, that are present in the line
        if (ans.x < line->xnum) ans.x = multicell_char_columns(line->cpu_cells, line->xnum, ans.x).start;
        if (ans.x_limit < line->xnum) ans.x_limit = multicell_char_columns(line->cpu_cells, line->xnum, ans.x_limit - 1).limit;
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
render_iteration_data(const Screen *self, const Selection *s, IterationData *ans) {
    // Must be used for both rendering and the dirty check so that they compare equal when nothing has changed
    iteration_data(s, ans, self->columns, -self->historybuf->count, 0);
}

static void
apply_selection(Screen *self, uint8_t *data, size_t stride, Selection *s, uint8_t set_mask, int extra_leading_rows, int scrolled_by) {
    render_iteration_data(self, s, &s->last_rendered);
    Line *line;
    const int y_min = MAX(-extra_leading_rows - scrolled_by, s->last_rendered.y), y_limit = MIN(s->last_rendered.y_limit, (int)self->lines - scrolled_by);
    for (int y = y_min; y < y_limit; y++) {
        if (self->paused_rendering.expires_at) {
            line = paused_line_for_linebuf_row(self, y);
            if (!line) continue;
        } else {
            line = checked_range_line(self, y);
            if (!line) continue;
        }
        const int y_in_data = (y + extra_leading_rows + scrolled_by);
        uint8_t *line_start = data + stride * self->columns * y_in_data;
        XRange xr = xrange_for_iteration_with_multicells(&s->last_rendered, y, line);
        for (index_type x = xr.x; x < xr.x_limit; x++) {
            line_start[stride * x] |= set_mask;
            CPUCell *c = &line->cpu_cells[x];
            if (c->is_multicell && c->scale > 1) {
                for (int ym = MAX(0, y_in_data - c->y); ym < y_in_data; ym++) data[stride * (self->columns * ym + x)] |= set_mask;
                for (int ym = y_in_data + 1; ym < MIN((int)self->lines + extra_leading_rows, y_in_data + c->scale - c->y); ym++)
                    data[stride * (self->columns * ym + x)] |= set_mask;
            }
        }
    }
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

bool
screen_is_cell_selected(Screen *self, index_type x, index_type y) {
    if (x >= self->columns || y >= self->lines || !self->selections.count) return false;
    const int row = (int)y - self->scrolled_by;
    const Line *queried_line = checked_range_line(self, row);
    if (!queried_line) return false;
    const CPUCell cell = queried_line->cpu_cells[x];
    // Every cell of a multi-cell character has the same selection highlight.
    const int first_row = cell.is_multicell ? row - cell.y : row;
    const int last_row = cell.is_multicell ? first_row + cell.scale : row + 1;
    const int visible_start = -(int)self->scrolled_by - live_pixel_scroll_enabled(self);
    const int visible_end = (int)self->lines - self->scrolled_by;
    for (size_t i = 0; i < self->selections.count; i++) {
        IterationData idata;
        iteration_data(self->selections.items + i, &idata, self->columns, -self->historybuf->count, 0);
        const int start = MAX(visible_start, MAX(first_row, idata.y)), end = MIN(visible_end, MIN(last_row, idata.y_limit));
        for (int r = start; r < end; r++) {
            const Line *line = checked_range_line(self, r);
            if (line) {
                const XRange xr = xrange_for_iteration_with_multicells(&idata, r, line);
                if (x >= xr.x && x < xr.x_limit) return true;
            }
        }
    }
    return false;
}

bool
screen_update_graphics_layers(Screen *self) {
    // While rendering is paused, the frozen image placements must be positioned using the
    // scroll position captured with the frozen text, not the live one, which new output may have changed
    GraphicsManager *grman = self->paused_rendering.expires_at ? self->paused_rendering.grman : self->grman;
    // Images moving with smooth scroll regions are drawn shifted with them
    static_assert(MAX_IMAGE_LAYER_REGIONS == MAX_SMOOTH_SCROLL_REGIONS, "Fix MAX_IMAGE_LAYER_REGIONS");
    ImageLayerRegion regions[MAX_SMOOTH_SCROLL_REGIONS];
    const SmoothScrollRender *sr = &self->smooth_scroll_render;
    for (unsigned i = 0; i < sr->count; i++)
        regions[i] = (ImageLayerRegion){
            .id = sr->regions[i].id,
            .horizontal = sr->regions[i].horizontal,
            .offset = (float)sr->regions[i].offset / (float)MAX(1u, sr->regions[i].horizontal ? self->cell_size.width : self->cell_size.height),
            .left = (int32_t)sr->regions[i].left,
            .top = (int32_t)sr->regions[i].top,
            .right = (int32_t)(sr->regions[i].left + sr->regions[i].width),
            .bottom = (int32_t)(sr->regions[i].top + sr->regions[i].height)};
    return grman_update_layers(
        grman,
        rendered_scrolled_by(self),
        scroll_offset_lines_for_screen(self),
        -1.f,
        -1.f,
        2.f / self->columns,
        2.f / self->lines,
        self->columns,
        self->lines,
        self->cell_size,
        regions,
        sr->count);
}

bool
screen_has_scrollbar(const Screen *self, bool is_hovering) {
    if (!rendered_on_main_screen(self) || !rendered_history_count(self)) return false;
    const bool scrolled = rendered_scrolled_by(self) > 0;
    switch (OPT(scrollbar)) {
        case SCROLLBAR_NEVER: return false;
        case SCROLLBAR_ALWAYS: return true;
        case SCROLLBAR_ON_SCROLLED: return scrolled;
        case SCROLLBAR_ON_HOVERED: return is_hovering;
        case SCROLLBAR_ON_SCROLL_AND_HOVER: return scrolled && is_hovering;
        case SCROLLBAR_ON_SCROLL_OR_HOVER: return scrolled || is_hovering;
    }
    return false;
}

void
screen_scrollbar_geometry(const Screen *self, float *handle_position, float *visible_fraction) {
    // handle_position is 0 at the bottom of the scrollback and 1 at the top
    const unsigned history_count = rendered_history_count(self);
    *handle_position = (float)((rendered_scrolled_by(self) + (double)scroll_offset_lines_for_screen(self)) / MAX(1u, history_count));
    *visible_fraction = (float)self->lines / (float)(self->lines + history_count);
}

void
screen_apply_selection(Screen *self, void *address_, size_t num_cells, size_t stride) {
    // address_ is write only memory when called by the renderer, so the data
    // is built in system memory and copied to it at the end, never read from it.
    uint8_t *const dest = address_, *strips = NULL;
    // The data for the strips of the smooth scroll regions is written only
    // when there is room for it, as when called by the renderer
    const size_t num_strip_cells = self->smooth_scroll_render.num_strip_cells;
    if (num_strip_cells && num_cells == (size_t)render_lines_for_screen(self) * self->columns + num_strip_cells) {
        num_cells -= num_strip_cells;
        strips = dest + num_cells * stride;
    }
    const size_t num_screen_cells = num_cells, sz = num_screen_cells * stride;
    if (!sz) {
        // There are no screen cells for the strips to be copied from
        if (strips) memset(strips, 0, num_strip_cells * stride);
        return;
    }
    if (self->selection_scratch_sz < sz) {
        uint8_t *n = realloc(self->selection_scratch, sz);
        if (!n) fatal("Out of memory");
        self->selection_scratch = n;
        self->selection_scratch_sz = sz;
    }
    uint8_t *const screen_data = self->selection_scratch, *address = screen_data;
    memset(address, 0, sz);
    const unsigned offset = pixel_scroll_enabled(self);
    const unsigned scrolled_by = rendered_scrolled_by(self);
    Selections *sel = self->paused_rendering.expires_at ? &self->paused_rendering.selections : &self->selections;
    for (size_t i = 0; i < sel->count; i++) apply_selection(self, address, stride, sel->items + i, 1, offset, scrolled_by);
    sel->last_rendered_count = sel->count;
    sel = self->paused_rendering.expires_at ? &self->paused_rendering.url_ranges : &self->url_ranges;
    for (size_t i = 0; i < sel->count; i++) {
        Selection *s = sel->items + i;
        if (OPT(underline_hyperlinks) == UNDERLINE_NEVER && s->is_hyperlink) continue;
        apply_selection(self, address, stride, s, 2, offset, scrolled_by);
    }
    sel->last_rendered_count = sel->count;
    address += (size_t)offset * self->columns * stride;
    num_cells -= (size_t)offset * self->columns;
    ExtraCursors *ec = self->paused_rendering.expires_at ? &self->paused_rendering.extra_cursors : &self->extra_cursors;
    for (unsigned i = 0; i < ec->count; i++) {
        if (ec->locations[i].cell < num_cells) address[(size_t)ec->locations[i].cell * stride] |= (ec->locations[i].shape & 7) << 2;
    }
    ec->dirty = false;
    const BidiMaps *b = self->bidi_maps ? selection_bidi_maps(self) : NULL;
    if (b) copy_selection_in_visual_order(b, screen_data, dest, stride);
    else memcpy(dest, screen_data, sz);
    if (strips) ssr_write_strip_selection_data(self, b, screen_data, strips, stride);
}

static index_type
limit_without_trailing_whitespace(const Line *line, index_type limit) {
    if (!limit) return limit;
    if (limit > line->xnum) limit = line->xnum;
    while (limit > 0) {
        const CPUCell *cell = line->cpu_cells + limit - 1;
        if (cell->is_multicell && (cell->x || cell->y)) {
            limit--;
            continue;
        }
        if (cell->ch_is_idx) break;
        switch (cell->ch_or_idx) {
            case ' ':
            case '\t':
            case '\n':
            case '\r':
            case 0: break;
            default: return limit;
        }
        limit--;
    }
    return limit;
}

// The cells whose text is extracted for a selection, one bit per cell for the lines in [y_start, y_limit)
typedef struct SelectedCells {
    int y_start, y_limit;
    index_type columns;
    uint8_t *bits;
} SelectedCells;

static void
free_selected_cells(SelectedCells *sc) {
    free(sc->bits);
    sc->bits = NULL;
}
#define RAII_SelectedCells(name) __attribute__((cleanup(free_selected_cells))) SelectedCells name = {0}

static inline size_t
selected_cell_pos(const SelectedCells *sc, int y, index_type x) {
    return (size_t)(y - sc->y_start) * sc->columns + x;
}

static inline bool
is_cell_selected(const SelectedCells *sc, int y, index_type x) {
    const size_t pos = selected_cell_pos(sc, y, x);
    return (sc->bits[pos >> 3] >> (pos & 7)) & 1;
}

static inline void
select_cell(SelectedCells *sc, int y, index_type x) {
    const size_t pos = selected_cell_pos(sc, y, x);
    sc->bits[pos >> 3] |= 1u << (pos & 7);
}

static bool
flag_selection_to_extract_text(Screen *self, const Selection *s, int *miny, int *y_limit, SelectedCells *sc) {
    // Find the cells whose text is in the selection. Returns false on allocation failure.
    IterationData idata;
    bool has_history = self->linebuf == self->main_linebuf;
    iteration_data(s, &idata, self->columns, has_history ? -self->historybuf->count : 0, 0);
    Line *line;
    *miny = idata.y;
    *y_limit = MIN(idata.y_limit, (int)self->lines);
    if (*miny >= *y_limit) return true;
    // Multiline chars can extend above the first line of the selection
    static const int max_scale = ((1u << SCALE_BITS) - 1u);
    sc->y_start = idata.y - max_scale;
    sc->y_limit = *y_limit;
    sc->columns = self->columns;
    sc->bits = calloc(((size_t)(sc->y_limit - sc->y_start) * sc->columns + 7) / 8, 1);
    if (!sc->bits) return false;
    Line temp = {.xnum = self->columns, .text_cache = self->text_cache};
    for (int y = idata.y; y < *y_limit; y++) {
        range_line(self, y, &temp);
        CPUCell *c;
        XRange xr = xrange_for_iteration_with_multicells(&idata, y, &temp);
        for (index_type x = xr.x; x < xr.x_limit; x++) {
            c = temp.cpu_cells + x;
            select_cell(sc, y, x);
            if (c->is_multicell && c->y) {
                for (int ym = y - c->y; ym < y; ym++) {
                    line = checked_range_line(self, ym);
                    if (line) {
                        select_cell(sc, ym, x);
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
            if (is_cell_selected(sc, *y_limit - 1, x) && temp.cpu_cells[x].ch_and_idx && (!temp.cpu_cells[x].is_multicell || !temp.cpu_cells[x].y)) return true;
        }
        (*y_limit)--;
    }
    return true;
}

static PyObject *
text_for_range(Screen *self, const Selection *sel, bool insert_newlines, bool strip_trailing_whitespace) {
    int min_y, y_limit;
    RAII_SelectedCells(sc);
    if (!flag_selection_to_extract_text(self, sel, &min_y, &y_limit, &sc)) return PyErr_NoMemory();
    if (min_y >= y_limit) return PyTuple_New(0);
    size_t before = self->as_ansi_buf.len;
    RAII_PyObject(ans, PyTuple_New(y_limit - min_y));
    RAII_PyObject(nl, PyUnicode_FromString("\n"));
    RAII_PyObject(empty, PyUnicode_FromString(""));
    if (!ans || !nl || !empty) return NULL;
    for (int i = 0, y = min_y; y < y_limit; y++, i++) {
        Line *line = range_line_(self, y);
        index_type x_limit = line->xnum, x_start = 0;
        while (x_limit && !is_cell_selected(&sc, y, x_limit - 1)) x_limit--;
        while (x_start < x_limit && !is_cell_selected(&sc, y, x_start)) x_start++;
        bool is_only_whitespace_line = false;
        // Don't strip trailing whitespace from soft-wrapped lines as those spaces
        // are part of the original text content that continues on the next line
        const bool line_is_continued = x_limit == line->xnum && line->cpu_cells[line->xnum - 1].next_char_was_wrapped;
        if (strip_trailing_whitespace && !line_is_continued) {
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
                while (end < x_limit && is_cell_selected(&sc, y, end)) end++;
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

static PyObject *
ansi_for_range(Screen *self, const Selection *sel, bool insert_newlines, bool strip_trailing_whitespace) {
    int min_y, y_limit;
    RAII_SelectedCells(sc);
    if (!flag_selection_to_extract_text(self, sel, &min_y, &y_limit, &sc)) return PyErr_NoMemory();
    if (min_y >= y_limit) return PyTuple_New(0);
    ANSILineState s = {.output_buf = &self->as_ansi_buf};
    s.output_buf->active_hyperlink_id = 0;
    s.output_buf->len = 0;
    RAII_PyObject(ans, PyTuple_New(y_limit - min_y + 1));
    RAII_PyObject(nl, PyUnicode_FromString("\n"));
    RAII_PyObject(empty_string, PyUnicode_FromString(""));
    if (!ans || !nl || !empty_string) return NULL;
    bool has_escape_codes = false;
    bool need_newline = false;
    ansi_bidi_continue(&s, screen_bidi_record_above(self, min_y), false);
    for (int i = 0, y = min_y; y < y_limit && i < PyTuple_GET_SIZE(ans) - 1; y++, i++) {
        const bool is_first_line = y == min_y;
        s.output_buf->len = 0;
        Line *line = range_line_(self, y);
        ansi_bidi_row_start(&s, line);
        const bool bidi_continued = line->cpu_cells[line->xnum - 1].next_char_was_wrapped && y + 1 < y_limit;
        index_type x_limit = line->xnum, x_start = 0;
        while (x_limit && !is_cell_selected(&sc, y, x_limit - 1)) x_limit--;
        while (x_start < x_limit && !is_cell_selected(&sc, y, x_start)) x_start++;
        bool is_only_whitespace_line = false;
        // Don't strip trailing whitespace from soft-wrapped lines as those spaces
        // are part of the original text content that continues on the next line
        const bool line_is_continued = x_limit == line->xnum && line->cpu_cells[line->xnum - 1].next_char_was_wrapped;
        if (strip_trailing_whitespace && !line_is_continued) {
            index_type new_limit = limit_without_trailing_whitespace(line, x_limit);
            if (new_limit != x_limit) {
                x_limit = new_limit;
                is_only_whitespace_line = new_limit <= x_start;
            }
        }

        if (x_limit <= x_start && (is_only_whitespace_line || line_is_empty(line))) {
            // we want a newline on only whitespace lines even if they are continued
            if (insert_newlines) need_newline = true;
            if (UNLIKELY(s.bidi_open)) {
                // No text of the paragraph is written here, so its controls are not opened here. Those written are reset before
                // the newline, which can be forced on a continued line, so that they are the defaults at every hard line break,
                // and opened again before the next text of the paragraph.
                const uint8_t record = s.bidi_open;
                const bool written = !s.bidi_prefix;
                if (written && (need_newline || !bidi_continued)) {
                    ansi_bidi_close(&s);
                    has_escape_codes = true;
                }
                if (need_newline) {
                    ensure_space_for(s.output_buf, buf, Py_UCS4, s.output_buf->len + 1, capacity, 2048, false);
                    s.output_buf->buf[s.output_buf->len++] = '\n';
                }
                if (bidi_continued) ansi_bidi_continue(&s, record, written && !need_newline);
                else s.bidi_open = s.bidi_prefix = 0;
            }
            if (s.output_buf->len) {
                PyObject *t = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, s.output_buf->buf, s.output_buf->len);
                if (!t) return NULL;
                PyTuple_SET_ITEM(ans, i, t);
            } else PyTuple_SET_ITEM(ans, i, Py_NewRef(need_newline ? nl : empty_string));
        } else {
            char_type prefix_char = need_newline ? '\n' : 0;
            while (x_start < x_limit) {
                index_type end = x_start;
                while (end < x_limit && is_cell_selected(&sc, y, end)) end++;
                if (line_as_ansi(line, &s, x_start, end, prefix_char, !is_first_line)) has_escape_codes = true;
                need_newline = insert_newlines && !line->cpu_cells[line->xnum - 1].next_char_was_wrapped;
                prefix_char = 0;
                x_start = MAX(x_start + 1, end);
            }
            if (UNLIKELY(s.bidi_open) && !bidi_continued) {
                ansi_bidi_close(&s);
                has_escape_codes = true;
            }
            PyObject *t = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, s.output_buf->buf, s.output_buf->len);
            if (!t) return NULL;
            PyTuple_SET_ITEM(ans, i, t);
        }
    }
    // A paragraph cut by the end of the selection
    s.output_buf->len = 0;
    if (s.bidi_open && !s.bidi_prefix) ansi_bidi_close(&s);
    RAII_PyObject(bidi_close, PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, s.output_buf->buf, s.output_buf->len));
    if (!bidi_close) return NULL;
    PyObject *t = PyUnicode_FromFormat("%U%s%s", bidi_close, has_escape_codes ? "\x1b[m" : "", s.output_buf->active_hyperlink_id ? "\x1b]8;;\x1b\\" : "");
    if (!t) return NULL;
    PyTuple_SET_ITEM(ans, PyTuple_GET_SIZE(ans) - 1, t);
    return Py_NewRef(ans);
}


static hyperlink_id_type
hyperlink_id_for_range(Screen *self, const Selection *sel) {
    IterationData idata;
    iteration_data(sel, &idata, self->columns, -self->historybuf->count, 0);
    for (int y = idata.y; y < idata.y_limit && y < (int)self->lines; y++) {
        Line *line = range_line_(self, y);
        XRange xr = xrange_for_iteration(&idata, y, line);
        for (index_type x = xr.x; x < xr.x_limit; x++) {
            if (line->cpu_cells[x].hyperlink_id) return line->cpu_cells[x].hyperlink_id;
        }
    }
    return 0;
}

static PyObject *
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

static PyObject *
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
                Py_CLEAR(ans);
                ans = t;
            } else ans = Py_NewRef(text);
        }
    }
    return Py_NewRef(ans ? ans : Py_None);
}


bool
screen_open_url(Screen *self, const char *callback) {
    if (!self->url_ranges.count) return false;
    hyperlink_id_type hid = hyperlink_id_for_range(self, self->url_ranges.items);
    if (hid) {
        const char *url = get_hyperlink_for_id(self->hyperlink_pool, hid, true);
        if (url) {
            CALLBACK(callback, "sH", url, hid);
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
        CALLBACK(callback, "OH", text, 0);
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
extend_url(
    Screen *screen, Line *line, index_type *x, index_type *y, char_type sentinel, bool newlines_allowed, index_type last_hostname_char_pos, index_type scale) {
    unsigned int count = 0;
    bool has_newline = false;
    index_type orig_y = *y;
    while (count++ < 20) {
        bool in_hostname = last_hostname_char_pos >= line->xnum;
        has_newline = !line->cpu_cells[line->xnum - 1].next_char_was_wrapped;
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
        *y += scale;
        *x = new_x;
    }
    if (sentinel && *x == 0 && *y > orig_y) {
        line = screen_visual_line(screen, *y);
        if (line && cell_is_char(line->cpu_cells, sentinel)) {
            *y -= scale;
            *x = line->xnum - 1;
            *x = multicell_char_columns(line->cpu_cells, line->xnum, *x).start;
        }
    }
}

// Detecting URLs using detect_url_regex {{{
#define DETECT_URL_REGEX_MAX_WRAPPED_LINES 3

typedef struct {
    index_type x, y;
} RegexCellPos;

// The text of the line being matched as UTF-8 along with the cell each byte comes from
static struct {
    struct {
        char *items;
        size_t capacity;
    } text;
    struct {
        RegexCellPos *items;
        size_t capacity;
    } positions;
    size_t len;
} regex_line = {0};

static void add_url_range(Screen *self, index_type start_x, index_type start_y, index_type end_x, index_type end_y, bool is_hyperlink);

static void
regex_line_append(const char *bytes, size_t num, index_type x, index_type y) {
    ensure_space_for(&regex_line.text, items, char, regex_line.len + num + 1, capacity, 1024, false);
    ensure_space_for(&regex_line.positions, items, RegexCellPos, regex_line.len + num, capacity, 1024, false);
    for (size_t i = 0; i < num; i++) {
        regex_line.text.items[regex_line.len] = bytes[i];
        regex_line.positions.items[regex_line.len++] = (RegexCellPos){.x = x, .y = y};
    }
}

static void
regex_line_append_row(Line *line, index_type y, ListOfChars *lc) {
    index_type limit = line->xnum;
    // Ignore trailing empty cells, they are either unused space at the end of
    // the line or space left over when a wide character is wrapped onto the next line
    while (limit && !line->cpu_cells[limit - 1].ch_and_idx) limit--;
    char utf8[8];
    for (index_type x = 0; x < limit; x++) {
        const CPUCell *c = line->cpu_cells + x;
        if (c->is_multicell && (c->x || c->y)) continue;
        text_in_cell(c, line->text_cache, lc);
        if (!lc->count || !lc->chars[0]) {
            regex_line_append(" ", 1, x, y);
        } else if (lc->chars[0] == '\t') {
            regex_line_append("\t", 1, x, y);
            unsigned num_cells_to_skip_for_tab = lc->count > 1 ? lc->chars[1] : 0;
            while (num_cells_to_skip_for_tab && x + 1 < limit && cell_is_char(line->cpu_cells + x + 1, ' ')) {
                x++;
                num_cells_to_skip_for_tab--;
            }
        } else {
            for (unsigned i = 0; i < lc->count; i++) {
                if (lc->chars[i]) regex_line_append(utf8, encode_utf8(lc->chars[i], utf8), x, y);
            }
        }
    }
}

static bool
detect_url_with_regex(Screen *self, index_type x, index_type y, TextCache *text_cache) {
    // Match against the soft wrapped line containing y, looking only a limited number of lines above and below y
    index_type top = y, bottom = y;
    while (top > 0 && y - top < DETECT_URL_REGEX_MAX_WRAPPED_LINES && visual_line_is_continued(self, top)) top--;
    while (bottom + 1 < self->lines && bottom - y < DETECT_URL_REGEX_MAX_WRAPPED_LINES && visual_line_is_continued(self, bottom + 1)) bottom++;
    Line line = {.xnum = self->columns, .text_cache = text_cache};
    regex_line.len = 0;
    for (index_type r = top; r <= bottom; r++) {
        visual_line(self, r, &line);
        regex_line_append_row(&line, r, self->lc);
    }
    size_t mouse_start = regex_line.len, mouse_end = 0;
    for (size_t i = 0; i < regex_line.len; i++) {
        const RegexCellPos p = regex_line.positions.items[i];
        if (p.x == x && p.y == y) {
            if (i < mouse_start) mouse_start = i;
            mouse_end = i + 1;
        }
    }
    if (mouse_start >= mouse_end) return false;
    const char *text = regex_line.text.items;
    regex_line.text.items[regex_line.len] = 0;
    for (size_t i = 0; i < OPT(detect_url_regex).count; i++) {
        const regex_t *re = OPT(detect_url_regex).items + i;
        size_t offset = 0;
        int eflags = 0;
        regmatch_t m;
        while (offset < mouse_end && regexec(re, text + offset, 1, &m, eflags) == 0) {
            const size_t start = offset + m.rm_so, end = offset + m.rm_eo;
            if (start >= mouse_end) break;
            if (end > mouse_start && end > start) {
                RegexCellPos s = regex_line.positions.items[start], e = regex_line.positions.items[end - 1];
                visual_line(self, e.y, &line);
                // end at the last cell of the char, that is present in the line
                e.x = multicell_char_columns(line.cpu_cells, line.xnum, e.x).limit - 1;
                self->url_ranges.count = 0;
                add_url_range(self, s.x, s.y, e.x, e.y, false);
                return true;
            }
            offset = end > start ? end : start + 1;
            // don't start matching in the middle of a UTF-8 encoded character
            while (offset < regex_line.len && (text[offset] & 0xc0) == 0x80) offset++;
            eflags = REG_NOTBOL;
        }
    }
    return false;
}
#undef DETECT_URL_REGEX_MAX_WRAPPED_LINES
// }}}

int
screen_detect_url(Screen *screen, unsigned int x, unsigned int y, bool mark) {
    bool has_url = false;
    index_type url_start, url_end = 0;
    Line *line = screen_visual_line(screen, y);
    if (!line || x >= screen->columns) return 0;
    if (line->cpu_cells[x].is_multicell && line->cpu_cells[x].scale > 1 && line->cpu_cells[x].y) {
        // Move to the top row of the char, following the rows that actually
        // continue it, as it can be split by a vertically scrolled smooth
        // scroll region, with its top rows in the overflow buffer
        const CPUCell ref = line->cpu_cells[x];
        index_type ry = ref.y;
        for (; ry && y; ry--, y--) {
            Line *above = screen_visual_line(screen, y - 1);
            if (!above || !continues_multicell_char(above->cpu_cells + x, &ref, ry - 1)) break;
        }
        if (ry) return 0;
        line = screen_visual_line(screen, y);
        if (!line) return 0;
    }
    x = multicell_char_columns(line->cpu_cells, line->xnum, x).start;
    hyperlink_id_type hid;
    if ((hid = line->cpu_cells[x].hyperlink_id)) {
        // Marking a hyperlink scans the surrounding lines, so skip it when not needed
        if (mark) screen_mark_hyperlink(screen, x, y);
        else screen_mark_url(screen, 0, 0, 0, 0);
        return hid;
    }
    char_type sentinel = 0;
    const bool newlines_allowed = !is_excluded_from_url('\n');
    index_type last_hostname_char_pos = screen->columns;
    url_start = line_url_start_at(line, x, screen->lc);
    Line scratch = {.xnum = line->xnum, .text_cache = line->text_cache};
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
    } else if (OPT(detect_url_regex).count && detect_url_with_regex(screen, x, y, line->text_cache)) {
        has_url = true;
    }
    if (!has_url || !mark) screen_mark_url(screen, 0, 0, 0, 0);
    return has_url ? -1 : 0;
}

// }}}

// IME Overlay {{{
bool
screen_is_overlay_active(Screen *self) {
    return self->overlay_line.is_active;
}

static char *
ansi_buf_tail_as_utf8(const ANSIBuf *buf, size_t start) {
    const size_t count = buf->len - start;
    char *ans = malloc(4 * count + 1);
    if (!ans) return NULL;
    size_t pos = 0;
    for (size_t i = 0; i < count; i++) pos += encode_utf8(buf->buf[start + i], ans + pos);
    ans[pos] = 0;
    return ans;
}

// Soft-wrapped rows are full by definition, so only the last row of a logical
// line has its unwritten trailing cells trimmed. Uses a caller supplied Line
// rather than the shared self->linebuf->line view, since input methods can
// query this from inside a key event, when something else may be using it.
static bool
append_row_to_ime_text(Screen *self, index_type y, index_type start, index_type limit, bool trim_trailing, Line *line, ANSIBuf *buf) {
    init_line_(self, y, line);
    limit = MIN(limit, trim_trailing ? xlimit_for_line(line) : line->xnum);
    start = MIN(start, line->xnum);
    if (start >= limit) return true;
    return unicode_in_range(line, start, limit, true, false, false, true, buf);
}

bool
screen_ime_text_around_cursor(Screen *self, char **before, char **after) {
    // The text on either side of the cursor, as UTF-8, for use by input
    // methods that need to know what surrounds the insertion point. The unit
    // is the logical line, that is, the cursor's row plus any rows it is
    // soft-wrapped across, since otherwise an input method would see nothing
    // before a cursor sitting at the start of a continuation row. The walk
    // stops at the top of the screen rather than descending into the
    // scrollback, truncating only the far end of before, which input methods
    // do not look at anyway.
    // Returns false only on allocation failure. A cursor in a degenerate
    // position simply yields empty text on both sides.
    *before = NULL;
    *after = NULL;
    ANSIBuf *buf = &self->as_ansi_buf;
    const size_t orig_len = buf->len;
    const bool have_line = self->linebuf && self->cursor->y < self->lines;
    const index_type cy = self->cursor->y;
    index_type top = cy, bottom = cy;
    if (have_line) {
        while (top > 0 && range_line_is_continued(self, top)) top--;
        while (bottom + 1 < self->lines && range_line_is_continued(self, bottom + 1)) bottom++;
    }
    // kitty defers line wrapping, so the cursor can sit one cell past the end of the row
    const index_type cursor_x = MIN(self->cursor->x, self->columns);
    Line line = {.xnum = self->columns, .text_cache = self->text_cache};
    bool ok = true;
    if (have_line) {
        for (index_type y = top; ok && y < cy; y++) ok = append_row_to_ime_text(self, y, 0, self->columns, false, &line, buf);
        if (ok) ok = append_row_to_ime_text(self, cy, 0, cursor_x, false, &line, buf);
    }
    if (ok && !(*before = ansi_buf_tail_as_utf8(buf, orig_len))) ok = false;
    buf->len = orig_len;
    if (have_line) {
        if (ok) ok = append_row_to_ime_text(self, cy, cursor_x, self->columns, cy == bottom, &line, buf);
        for (index_type y = cy + 1; ok && y <= bottom; y++) ok = append_row_to_ime_text(self, y, 0, self->columns, y == bottom, &line, buf);
    }
    if (ok && !(*after = ansi_buf_tail_as_utf8(buf, orig_len))) ok = false;
    buf->len = orig_len;
    if (!ok) {
        free(*before);
        free(*after);
        *before = NULL;
        *after = NULL;
    }
    return ok;
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
    self->overlay_line.preedit_cursor = -1;
}

static index_type
overlay_line_cursor_x(const Screen *self) {
    // The column at which the cursor is shown while the pre-edit text is
    // active: at the IME cursor if known, otherwise after the pre-edit text.
    // This is computed without drawing the pre-edit text as the cursor
    // position is collected for rendering before the overlay is drawn.
    const OverlayLine *ol = &self->overlay_line;
    const index_type columns_exceeded = ol->text_len <= self->columns ? 0 : ol->text_len - self->columns;
    const index_type start = screen_overlay_line_start(self);
    index_type width_before_cursor = ol->text_len;
    if (ol->overlay_text && ol->preedit_cursor >= 0 && ol->preedit_cursor < PyUnicode_GET_LENGTH(ol->overlay_text)) {
        RAII_PyObject(prefix, PyUnicode_Substring(ol->overlay_text, 0, ol->preedit_cursor));
        RAII_PyObject(width, prefix ? wcswidth_std(NULL, prefix) : NULL);
        if (width) {
            const long w = PyLong_AsLong(width);
            if (w >= 0) width_before_cursor = MIN((index_type)w, ol->text_len);
        }
        if (PyErr_Occurred()) PyErr_Print();
    }
    if (width_before_cursor < columns_exceeded) return 0;
    return MIN(start + width_before_cursor - columns_exceeded, self->columns);
}

void
screen_update_overlay_text(Screen *self, const char *utf8_text, int preedit_cursor) {
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
    self->overlay_line.preedit_cursor = preedit_cursor;
    self->overlay_line.cursor_x = overlay_line_cursor_x(self);
    self->overlay_line.ynum = self->cursor->y;
    cursor_copy_to(self->cursor, &(self->overlay_line.original_line.cursor));
    linebuf_mark_line_dirty(self->linebuf, self->overlay_line.ynum);
    self->is_dirty = true;
    // Since we are typing, scroll to the bottom
    if (self->scrolled_by != 0) {
        self->scrolled_by = 0;
        reset_pixel_scroll(self, 0);
        dirty_scroll(self);
    }
}

index_type
screen_overlay_line_start(const Screen *self) {
    // Right-align the overlay to ensure that the pre-edit text just entered is visible when the cursor is near the end of the line.
    const OverlayLine *ol = &self->overlay_line;
    index_type xstart = ol->text_len <= self->columns ? self->columns - ol->text_len : 0;
    return MIN(ol->xstart, xstart);
}

static void
screen_draw_overlay_line(Screen *self) {
    if (!self->overlay_line.overlay_text) return;
    // self->linebuf->line is a shared view that callers may not have pointed
    // at the overlay row (e.g. render_line_for_virtual_y inits a stack-local
    // Line instead). Without this, line->cpu_cells can be NULL or stale,
    // crashing the cell loops below.
    linebuf_init_line(self->linebuf, self->overlay_line.ynum);
    const index_type xstart = screen_overlay_line_start(self);
    index_type columns_exceeded = self->overlay_line.text_len <= self->columns ? 0 : self->overlay_line.text_len - self->columns;
    bool orig_line_wrap_mode = self->modes.mDECAWM;
    bool orig_cursor_enable_mode = self->modes.mDECTCEM;
    bool orig_insert_replace_mode = self->modes.mIRM;
    self->modes.mDECAWM = false;
    self->modes.mDECTCEM = false;
    self->modes.mIRM = false;
    Cursor *orig_cursor = self->cursor;
    self->cursor = &(self->overlay_line.original_line.cursor);
    // Mark the pre-edit text as distinct from committed text using
    // ime_preedit_style, by default italic, with a dashed underline in the
    // highlight color. Underline rather than reverse video matches what other
    // terminals do (VTE and foot both underline), and dashed avoids colliding
    // with the styles applications already use: curly for spell checking and
    // straight for hyperlinks. Saved and restored around the draw, like the
    // modes above.
    const CellStyle orig_style = self->cursor->style;
    if (OPT(ime_preedit_style).bold) self->cursor->style.attrs.bold = true;
    if (OPT(ime_preedit_style).dim) self->cursor->style.attrs.dim = true;
    if (OPT(ime_preedit_style).italic) self->cursor->style.attrs.italic = true;
    if (OPT(ime_preedit_style).strikethrough) self->cursor->style.attrs.strike = true;
    // Toggle rather than set, so that pre-edit text over reversed text still stands out
    if (OPT(ime_preedit_style).reverse) self->cursor->style.attrs.reverse ^= true;
    if (OPT(ime_preedit_style).underline == 0) {
        self->cursor->style.attrs.decoration = 0;
        self->cursor->style.decoration_fg = 0;
    } else if (OPT(ime_preedit_style).underline > 0) {
        self->cursor->style.attrs.decoration = OPT(ime_preedit_style).underline;
        const color_type underline_color = OPT(ime_preedit_style).has_underline_color ? OPT(ime_preedit_style).underline_color
                                                                                      : colorprofile_to_color_with_fallback(
                                                                                            self->color_profile,
                                                                                            self->color_profile->overridden.highlight_bg,
                                                                                            self->color_profile->configured.highlight_bg,
                                                                                            self->color_profile->overridden.default_fg,
                                                                                            self->color_profile->configured.default_fg);
        self->cursor->style.decoration_fg = ((underline_color & COL_MASK) << 8) | 2;
    }
    self->cursor->x = xstart;
    self->cursor->y = self->overlay_line.ynum;
    self->overlay_line.xnum = 0;
    if (xstart > 0) {
        // remove any multicell characters temporarily that intersect the left boundary,
        // the characters are not actually removed, just deleted on this line
        CPUCell *c = self->linebuf->line->cpu_cells + xstart;
        while (c->is_multicell && c->x && c < self->linebuf->line->cpu_cells + self->columns) {
            c->is_multicell = false;
            c->ch_or_idx = ' ';
            c->ch_is_idx = false;
            c++;
        }
    }
    // Chars of several rows in the cells the text covers are blanked on this row only. The draw would otherwise move the text
    // to another row past them, or remove them from all their rows.
    {
        CPUCell *cells = self->linebuf->line->cpu_cells;
        const index_type limit = MIN(self->columns, xstart + self->overlay_line.text_len);
        for (index_type x = xstart; x < limit; x++) {
            const CPUCell *c = cells + x;
            if (!c->is_multicell || (c->scale < 2 && !c->y)) continue;
            const index_type start = x - MIN(x, (index_type)c->x), end = MIN(self->columns, start + mcd_x_limit(c));
            for (index_type cx = MAX(start, xstart); cx < end; cx++) {
                const CPUCell old = cells[cx];
                cells[cx] = (CPUCell){.ch_or_idx = ' ', .hyperlink_id = old.hyperlink_id, .style_idx = old.style_idx};
            }
            x = MAX(x, end) - 1;
        }
    }
    self->overlay_line.drawing = true;
    self->overlay_line.draw_left = xstart;
    index_type before;
    const int kind = PyUnicode_KIND(self->overlay_line.overlay_text);
    const void *data = PyUnicode_DATA(self->overlay_line.overlay_text);
    const Py_ssize_t sz = PyUnicode_GET_LENGTH(self->overlay_line.overlay_text);
    for (Py_ssize_t pos = 0; pos < sz; pos++) {
        before = self->cursor->x;
        const char_type ch = PyUnicode_READ(kind, data, pos);
        // A control char would act on the screen: a line feed scrolls it
        if (ch < ' ' || (0x7f <= ch && ch < 0xa0)) continue;
        draw_codepoint(self, ch);
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
                                c->is_multicell = false;
                                c->ch_is_idx = false;
                                c->ch_or_idx = ' ';
                                if (!c->x) break;
                                c--;
                            } while (c->is_multicell && c >= self->linebuf->line->cpu_cells);
                        }
                    }
                }
            }
            self->cursor->x = len;
        }
        self->overlay_line.xnum += len;
    }
    self->overlay_line.drawing = false;
    self->overlay_line.cursor_x = overlay_line_cursor_x(self);
    self->cursor->style = orig_style;
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
            self->overlay_line.cursor_x = overlay_line_cursor_x(self);
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
    line_save_cells(line, 0, line->xnum, ol.original_line.render_cells, ol.original_line.cpu_cells);
    screen_draw_overlay_line(self);
    // The pre-edit text is shaped in the direction guessed from it, as with bidi mode off, also on a line with a record
    const uint8_t *levels = NULL;
    BidiMaps *b = self->bidi_maps;
    if (b) {
        ensure_space_for(b, row_levels, uint8_t, line->xnum, row_levels_cap, line->xnum, false);
        memset(b->row_levels, BIDI_LEVEL_FIXED, line->xnum);
        levels = b->row_levels;
    }
    render_line(fonts_data, line, ol.ynum, self->cursor, self->disable_ligatures, self->lc, levels);
    line_save_cells(line, 0, line->xnum, ol.render_cells, ol.cpu_cells);
    line_reset_cells(line, 0, line->xnum, ol.original_line.render_cells, ol.original_line.cpu_cells);
    ol.is_dirty = false;
    const index_type x = screen_ime_anchor_x(self), y = MIN(ol.ynum + self->scrolled_by, self->lines - 1);
    // The IME is anchored at the start of the pre-edit text, see prepare_ime_position_update_event()
    if (ol.last_ime_pos.x != x || ol.last_ime_pos.y != y) {
        ol.last_ime_pos.x = x;
        ol.last_ime_pos.y = y;
        update_ime_position_for_window(self->window_id, false, 0);
    }
#undef ol
}

static void
update_overlay_line_data(Screen *self, uint8_t *data) {
    const index_type render_row = render_row_of(self, self->overlay_line.ynum);
    CellGPUData *row = (CellGPUData *)(data + sizeof(CellGPUData) * render_row * self->columns);
    index_type start;
    if (screen_overlay_visual_start(self, &start)) {
        // The row was uploaded through its map, only the pre-edit block goes over it
        const index_type s = screen_overlay_line_start(self), n = MIN(self->overlay_line.text_len, self->columns);
        if (!n) return;
        cells_for_gpu(self->overlay_line.cpu_cells + s, self->overlay_line.render_cells + s, n, row + start);
        // The block can cut a wide character, whose other half the bidi-off upload blanks
        const CPUCell *cells = linebuf_cpu_cells_for_line(self->linebuf, self->overlay_line.ynum);
        if (start) bidi_blank_cut_half(self->bidi_maps, cells, render_row, row, start - 1, start);
        if (start + n < self->columns) bidi_blank_cut_half(self->bidi_maps, cells, render_row, row, start + n, start + n - 1);
        return;
    }
    cells_for_gpu(self->overlay_line.cpu_cells, self->overlay_line.render_cells, self->columns, row);
}

// }}}

// Python interface {{{
#define WRAP0(name)                                           \
    static PyObject *name(Screen *self, PyObject *a UNUSED) { \
        screen_##name(self);                                  \
        Py_RETURN_NONE;                                       \
    }
#define WRAP0x(name)                                                \
    static PyObject *xxx_##name(Screen *self, PyObject *a UNUSED) { \
        screen_##name(self);                                        \
        Py_RETURN_NONE;                                             \
    }
#define WRAP1(name, defval)                                 \
    static PyObject *name(Screen *self, PyObject *args) {   \
        unsigned int v = defval;                            \
        if (!PyArg_ParseTuple(args, "|I", &v)) return NULL; \
        screen_##name(self, v);                             \
        Py_RETURN_NONE;                                     \
    }
#define WRAP1B(name, defval)                                     \
    static PyObject *name(Screen *self, PyObject *args) {        \
        unsigned int v = defval;                                 \
        int b = false;                                           \
        if (!PyArg_ParseTuple(args, "|Ip", &v, &b)) return NULL; \
        screen_##name(self, v, b);                               \
        Py_RETURN_NONE;                                          \
    }
#define WRAP1E(name, defval, ...)                           \
    static PyObject *name(Screen *self, PyObject *args) {   \
        unsigned int v = defval;                            \
        if (!PyArg_ParseTuple(args, "|I", &v)) return NULL; \
        screen_##name(self, v, __VA_ARGS__);                \
        Py_RETURN_NONE;                                     \
    }
#define WRAP2(name, defval1, defval2)                            \
    static PyObject *name(Screen *self, PyObject *args) {        \
        unsigned int a = defval1, b = defval2;                   \
        if (!PyArg_ParseTuple(args, "|II", &a, &b)) return NULL; \
        screen_##name(self, a, b);                               \
        Py_RETURN_NONE;                                          \
    }
#define WRAP2B(name)                                                 \
    static PyObject *name(Screen *self, PyObject *args) {            \
        unsigned int a, b;                                           \
        int p;                                                       \
        if (!PyArg_ParseTuple(args, "IIp", &a, &b, &p)) return NULL; \
        screen_##name(self, a, b, (bool)p);                          \
        Py_RETURN_NONE;                                              \
    }

WRAP0(garbage_collect_hyperlink_pool)
WRAP0(garbage_collect_text_cache)

static PyObject *
text_cache_count(Screen *self, PyObject *a UNUSED) {
    return PyLong_FromUnsignedLong((unsigned long)tc_num_entries(self->text_cache));
}

static PyObject *
has_selection(Screen *self, PyObject *a UNUSED) {
    if (screen_has_selection(self)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static PyObject *
hyperlinks_as_set(Screen *self, PyObject *args UNUSED) {
    return screen_hyperlinks_as_set(self);
}

static PyObject *
hyperlink_for_id(Screen *self, PyObject *val) {
    unsigned long id = PyLong_AsUnsignedLong(val);
    if (id > HYPERLINK_MAX_NUMBER) {
        PyErr_SetString(PyExc_IndexError, "Out of bounds");
        return NULL;
    }
    return Py_BuildValue("s", get_hyperlink_for_id(self->hyperlink_pool, id, true));
}

static Line *
get_visual_line(void *x, int y) {
    return visual_line_(x, y);
}
static Line *
get_range_line(void *x, int y) {
    return range_line_(x, y);
}

static uint8_t
visual_bidi_above(void *x) {
    Screen *self = x;
    return screen_bidi_record_above(self, -(int)self->scrolled_by);
}

static uint8_t
range_bidi_above(void *x) {
    return screen_bidi_record_above(x, 0);
}

static PyObject *
as_text(Screen *self, PyObject *args) {
    return as_text_generic(args, self, get_visual_line, self->lines, &self->as_ansi_buf, false, visual_bidi_above, false);
}

static PyObject *
as_text_non_visual(Screen *self, PyObject *args) {
    return as_text_generic(args, self, get_range_line, self->lines, &self->as_ansi_buf, false, range_bidi_above, false);
}

static PyObject *
as_text_for_history_buf(Screen *self, PyObject *args) {
    return as_text_history_buf(self->historybuf, args, &self->as_ansi_buf);
}

static PyObject *
as_text_generic_wrapper(Screen *self, PyObject *args, get_line_func get_line) {
    return as_text_generic(args, self, get_line, self->lines, &self->as_ansi_buf, false, range_bidi_above, false);
}

static PyObject *
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

static Line *
get_line_from_offset(void *x, int y) {
    OutputOffset *r = x;
    return range_line_(r->screen, r->start + y);
}

static uint8_t
offset_bidi_above(void *x) {
    OutputOffset *r = x;
    return screen_bidi_record_above(r->screen, r->start);
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
        } else if (line && line->attrs.prompt_kind == OUTPUT_START) {
            found_output = true;
            start = y1;
            found_prompt = true;
            direction = 1;
        }
        y1--;
        y2++;
    }

    // find upwards
    if (direction <= 0) {
        // find around: only needs to find the first output start
        // find upwards: find prompt after the output, and the first output
        while (y1 >= upward_limit) {
            line = checked_range_line(self, y1);
            if (line && line->attrs.prompt_kind == PROMPT_START) {
                if (direction == 0) {
                    found_prompt = true;
                    break;
                }
                found_next_prompt = true;
                end = y1;
            } else if (line && line->attrs.prompt_kind == OUTPUT_START) {
                found_output = true;
                start = y1;
                found_prompt = true;
                break;
            }
            y1--;
        }
        if (y1 < upward_limit) {
            oo->reached_upper_limit = true;
            found_output = direction != 0;
            start = upward_limit;
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
                        found_next_prompt = true;
                        end = y2;
                        break;
                    }
                    found_prompt = true;
                } else if (!found_output) {
                    // skip fetching wrapped prompt lines
                    while (range_line_is_continued(self, y2)) { y2++; }
                } else if (!found_next_prompt) {
                    found_next_prompt = true;
                    end = y2;
                    break;
                }
            } else if (line && line->attrs.prompt_kind == OUTPUT_START && !found_output) {
                found_output = true;
                start = y2;
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

static void
remove_multicell_fragments_cut_off_above_screen(Screen *self, index_type num_lines_above_screen) {
    // Lines were deleted from the scrollback leaving num_lines_above_screen
    // lines between them and the top of the screen. Remove the parts of
    // multicell chars on screen whose top was in the deleted lines.
    for (index_type y = 0; y < self->lines; y++) {
        linebuf_init_line(self->linebuf, y);
        Line *line = self->linebuf->line;
        bool found = false;
        for (index_type x = 0; x < self->columns; x++) {
            CPUCell *c = line->cpu_cells + x;
            if (c->is_multicell && c->y > num_lines_above_screen + y) {
                found = true;
                cell_set_char(c, 0);
                cell_clear_multicell(c);
            }
        }
        if (!found) break; // a multicell char cannot skip a line
        linebuf_mark_line_dirty(self->linebuf, y);
    }
}

static PyObject *
erase_last_command(Screen *self, PyObject *args UNUSED) {
    if (self->linebuf != self->main_linebuf) Py_RETURN_FALSE;
    Line *line;
    // Erase the most recent command: the prompt block immediately above the
    // current (live) prompt, regardless of whether that command produced any
    // output. Commands without output (an empty Enter, a comment, cd, export,
    // ...) emit no OSC 133;C, so a search anchored on OUTPUT_START would skip
    // them and erase an older command instead. Selecting by prompt marks makes
    // every submitted command one unit, removed newest-first.
    // Range line numbers are relative to the live screen, independent of scrolled_by
    int y = self->cursor->y;
    bool found = false;
    for (; (line = checked_range_line(self, y)); y--) {
        if (line->attrs.prompt_kind == PROMPT_START) {
            found = true;
            break;
        }
    }
    if (!found) Py_RETURN_FALSE;
    const int live_prompt_start = y;
    found = false;
    for (y = live_prompt_start - 1; (line = checked_range_line(self, y)); y--) {
        if (line->attrs.prompt_kind == PROMPT_START) {
            found = true;
            break;
        }
    }
    if (!found) Py_RETURN_FALSE; // nothing above the current prompt to erase
    const int start = y;
    // The erased region is [start, live_prompt_start). Its part in the
    // scrollback is [start, history_end) and its part on screen is
    // [screen_start, live_prompt_start). Either can be empty, the screen part
    // is when a long live prompt has itself scrolled into the scrollback.
    const int history_end = MIN(live_prompt_start, 0), screen_start = MAX(start, 0);
    const index_type num_deleted_from_history = start < history_end ? (index_type)(history_end - start) : 0;
    const index_type num_lines_to_erase_in_screen = live_prompt_start > screen_start ? (index_type)(live_prompt_start - screen_start) : 0;
    // The lines of the live prompt that are in the scrollback, newer than the erased lines
    const index_type num_newer_in_history = (index_type)(-history_end);
    if (self->last_visited_prompt.is_set) {
        // Move the last visited prompt with the lines that remain: lines above
        // the erased region move down by the number of lines removed from the
        // scrollback, lines below it move up by the number removed from the screen.
        int *r = &self->last_visited_prompt.row;
        if (start <= *r && *r < live_prompt_start) self->last_visited_prompt.is_set = false;
        else *r += *r < start ? (int)num_deleted_from_history : -(int)num_lines_to_erase_in_screen;
    }
    // The line above the erased region no longer wraps into the line after it
    if ((line = checked_range_line(self, start - 1))) {
        line->cpu_cells[line->xnum - 1].next_char_was_wrapped = false;
        // its paragraph ends there now, which a clean row in the history would not show
        if (self->main_linebuf->bidi_stamped || self->historybuf->bidi_stamped) {
            mark_range_line_dirty(self, start - 1);
            self->historybuf->bidi_walked = 0;
        }
    }
    if (num_lines_to_erase_in_screen) {
        // Anchor the on-screen deletion at the top of the region, not at
        // cursor->y - count: a multi-line prompt or rows skipped above would
        // otherwise shift the deletion and leave residual lines on screen.
        screen_delete_lines_impl(self, (index_type)screen_start, num_lines_to_erase_in_screen, 0, self->lines - 1);
        self->cursor->y -= num_lines_to_erase_in_screen;
    }
    if (num_deleted_from_history) {
        if (num_newer_in_history) historybuf_delete_lines(self->historybuf, num_newer_in_history, num_deleted_from_history);
        else historybuf_delete_newest_lines(self->historybuf, num_deleted_from_history);
        if (!num_lines_to_erase_in_screen) remove_multicell_fragments_cut_off_above_screen(self, num_newer_in_history);
        clear_all_selections(self);
        // Keep a scrolled back viewport anchored on the same content: lines
        // above the removed ones move down, lines below them do not move. If
        // the top of the viewport was among the removed lines, there is
        // nothing to anchor to, so go to the bottom. Signal a redraw, otherwise
        // the deletion of off-screen lines is not reflected until the next
        // scroll event forces the history viewport to be recomputed.
        const int viewport_top = -(int)self->scrolled_by;
        if (viewport_top < start) self->scrolled_by -= num_deleted_from_history;
        else if (viewport_top < history_end) {
            self->scrolled_by = 0;
            reset_pixel_scroll(self, 0);
        }
        clamp_scroll_position(self);
        self->is_dirty = true;
        dirty_scroll(self);
    }
    // The line after the erased region, where it is now, starts a paragraph of its own
    if (self->main_linebuf->bidi_stamped || self->historybuf->bidi_stamped)
        mark_range_line_dirty(self, num_lines_to_erase_in_screen ? screen_start : live_prompt_start);
    Py_RETURN_TRUE;
}

static PyObject *
cmd_output(Screen *self, PyObject *args) {
    unsigned int which = 0;
    RAII_PyObject(which_args, PyTuple_GetSlice(args, 0, 1));
    RAII_PyObject(as_text_args, PyTuple_GetSlice(args, 1, PyTuple_GET_SIZE(args)));
    if (!which_args || !as_text_args) return NULL;
    if (!PyArg_ParseTuple(which_args, "I", &which)) return NULL;
    if (self->linebuf != self->main_linebuf) Py_RETURN_NONE;
    OutputOffset oo = {.screen = self};
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
        case 2: { // last visited cmd
            index_type y;
            unsigned int scrolled_by;
            if (last_visited_prompt_viewport(self, &y, &scrolled_by)) found = find_cmd_output(self, &oo, y, scrolled_by, 0, false);
        } break;
        case 3: { // last non-empty output
            int y = self->cursor->y;
            Line *line;
            bool reached_upper_limit = false;
            while (!found && !reached_upper_limit) {
                line = checked_range_line(self, y);
                if (!line || (line->attrs.prompt_kind == OUTPUT_START)) {
                    int start = line ? y : y + 1;
                    reached_upper_limit = !line;
                    int y2 = start;
                    unsigned int num_lines = 0;
                    bool found_content = false;
                    while ((line = checked_range_line(self, y2)) && line->attrs.prompt_kind != PROMPT_START) {
                        if (!found_content) found_content = !line_is_empty(line);
                        num_lines++;
                        y2++;
                    }
                    if (found_content) {
                        found = true;
                        oo.reached_upper_limit = reached_upper_limit;
                        oo.start = start;
                        oo.num_lines = num_lines;
                        break;
                    }
                }
                y--;
            }
        } break;
        default: PyErr_Format(PyExc_KeyError, "%u is not a valid type of command", which); return NULL;
    }
    // The caller then puts the scrollback pager history before the output
    const bool after_pagerhist = oo.reached_upper_limit && self->linebuf == self->main_linebuf && OPT(scrollback_pager_history_size) > 0;
    if (found) {
        RAII_PyObject(
            ret, as_text_generic(as_text_args, &oo, get_line_from_offset, oo.num_lines, &self->as_ansi_buf, false, offset_bidi_above, after_pagerhist));
        if (!ret) return NULL;
    }
    if (after_pagerhist) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

bool
screen_set_last_visited_prompt(Screen *self, index_type y) {
    if (y >= self->lines) return false;
    self->last_visited_prompt.row = (int)y - (int)self->scrolled_by;
    self->last_visited_prompt.preferred_y = y;
    self->last_visited_prompt.is_set = true;
    return true;
}

bool
screen_select_cmd_output(Screen *self, index_type y) {
    if (y >= self->lines) return false;
    OutputOffset oo = {.screen = self};
    if (!find_cmd_output(self, &oo, y, self->scrolled_by, 0, true)) return false;

    screen_start_selection(self, 0, y, true, false, EXTEND_LINE);
    Selection *s = self->selections.items;
#define S(which, offset_y, scrolled_by) \
    if (offset_y < 0) {                 \
        s->scrolled_by = -(offset_y);   \
        s->which.y = 0;                 \
    } else {                            \
        s->scrolled_by = 0;             \
        s->which.y = offset_y;          \
    }
    S(start, oo.start, start_scrolled_by);
    S(end, oo.start + (int)oo.num_lines - 1, end_scrolled_by);
#undef S
    s->start.x = 0;
    s->start.in_left_half_of_cell = true;
    s->end.x = self->columns;
    s->end.in_left_half_of_cell = false;
    self->selections.in_progress = false;

    call_boss(set_primary_selection, NULL);
    return true;
}

static PyObject *
screen_truncate_point_for_length(PyObject UNUSED *self, PyObject *args) {
    PyObject *str;
    unsigned int num_cells, start_pos = 0;
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
        if (ch == 0x1b && i + 1 < len && PyUnicode_READ(kind, data, i + 1) == '[') {
            in_sgr = true;
            continue;
        }
        if (ch == 0xfe0f) {
            if (is_emoji_presentation_base(prev_ch) && prev_width == 1) {
                width_so_far += 1;
                prev_width = 2;
            } else prev_width = 0;
        } else {
            int w = wcwidth_std(char_props_for(ch));
            switch (w) {
                case -1:
                case 0: prev_width = 0; break;
                case 2: prev_width = 2; break;
                default: prev_width = 1; break;
            }
            if (width_so_far + prev_width > num_cells) { break; }
            width_so_far += prev_width;
        }
        prev_ch = ch;
    }
    return PyLong_FromUnsignedLong(i);
}


static PyObject *
test_text_of_line_for_cursor(Screen *self, PyObject *args) {
    unsigned int x, y;
    if (!PyArg_ParseTuple(args, "II", &x, &y)) return NULL;
    Line overlay_line;
    Line *line = screen_line_for_cursor(self, x, y, &overlay_line);
    if (!line) Py_RETURN_NONE;
    RAII_ANSIBuf(buf);
    return line_as_unicode(line, false, &buf);
}

static PyObject *
line(Screen *self, PyObject *val) {
    unsigned long y = PyLong_AsUnsignedLong(val);
    if (y >= self->lines) {
        PyErr_SetString(PyExc_IndexError, "Out of bounds");
        return NULL;
    }
    linebuf_init_line(self->linebuf, y);
    Py_INCREF(self->linebuf->line);
    return (PyObject *)self->linebuf->line;
}

Line *
screen_visual_line(Screen *self, index_type y) {
    if (y >= self->lines) return NULL;
    return visual_line_(self, y);
}

static PyObject *
pyvisual_line(Screen *self, PyObject *args) {
    // The line corresponding to the yth visual line, taking into account scrolling
    unsigned int y;
    if (!PyArg_ParseTuple(args, "I", &y)) return NULL;
    if (y >= self->lines) { Py_RETURN_NONE; }
    return Py_BuildValue("O", visual_line_(self, y));
}

static PyObject *
draw(Screen *self, PyObject *src) {
    if (!PyUnicode_Check(src)) {
        PyErr_SetString(PyExc_TypeError, "A unicode string is required");
        return NULL;
    }
    if (PyUnicode_READY(src) != 0) { return PyErr_NoMemory(); }
    Py_UCS4 *buf = PyUnicode_AsUCS4Copy(src);
    if (!buf) return NULL;
    draw_text_in_mode(self, buf, PyUnicode_GetLength(src));
    PyMem_Free(buf);
    Py_RETURN_NONE;
}

static PyObject *
apply_sgr(Screen *self, PyObject *src) {
    if (!PyUnicode_Check(src)) {
        PyErr_SetString(PyExc_TypeError, "A unicode string is required");
        return NULL;
    }
    if (PyUnicode_READY(src) != 0) { return PyErr_NoMemory(); }
    Py_ssize_t sz;
    const char *s = PyUnicode_AsUTF8AndSize(src, &sz);
    if (s == NULL) return NULL;
    if (!parse_sgr(self, (const uint8_t *)s, sz, "parse_sgr", false)) {
        PyErr_Format(PyExc_ValueError, "Invalid SGR: %s", PyUnicode_AsUTF8(src));
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
reset_mode(Screen *self, PyObject *args) {
    int private = false;
    unsigned int mode;
    if (!PyArg_ParseTuple(args, "I|p", &mode, &private)) return NULL;
    if (private) mode <<= 5;
    screen_reset_mode(self, mode);
    Py_RETURN_NONE;
}

static PyObject *
_select_graphic_rendition(Screen *self, PyObject *args) {
    int params[256] = {0};
    for (int i = 0; i < PyTuple_GET_SIZE(args); i++) { params[i] = PyLong_AsLong(PyTuple_GET_ITEM(args, i)); }
    select_graphic_rendition(self, params, PyTuple_GET_SIZE(args), false, NULL);
    Py_RETURN_NONE;
}

static PyObject *
set_mode(Screen *self, PyObject *args) {
    int private = false;
    unsigned int mode;
    if (!PyArg_ParseTuple(args, "I|p", &mode, &private)) return NULL;
    if (private) mode <<= 5;
    screen_set_mode(self, mode);
    Py_RETURN_NONE;
}

static PyObject *
reset_dirty(Screen *self, PyObject *a UNUSED) {
    screen_reset_dirty(self);
    Py_RETURN_NONE;
}

static PyObject *
set_window_char(Screen *self, PyObject *a) {
    const char *text = "";
    if (!PyArg_ParseTuple(a, "|s", &text)) return NULL;
    self->display_window_char = text[0];
    self->is_dirty = true;
    Py_RETURN_NONE;
}

static PyObject *
set_progress(Screen *self, PyObject *a) {
    unsigned int state = 0, percent = 0;
    if (!PyArg_ParseTuple(a, "II", &state, &percent)) return NULL;
    ProgressBarState new_state = (ProgressBarState)(state > PROGRESS_STATE_PAUSED ? PROGRESS_STATE_UNSET : state);
    uint8_t new_percent = (uint8_t)(percent > 100 ? 100 : percent);
    if (self->progress_state != new_state || self->progress_percent != new_percent) {
        self->progress_previous_percent = self->progress_percent;
        self->progress_previous_state = self->progress_state;
        self->progress_state = new_state;
        self->progress_percent = new_percent;
        self->progress_changed_at = monotonic();
        // Start or stop indeterminate animation
        if (new_state == PROGRESS_STATE_INDETERMINATE && self->progress_indeterminate_anim_at == 0) {
            self->progress_indeterminate_anim_at = monotonic();
        } else if (new_state != PROGRESS_STATE_INDETERMINATE) {
            self->progress_indeterminate_anim_at = 0;
        }
        self->is_dirty = true;
    }
    Py_RETURN_NONE;
}

static PyObject *
is_using_alternate_linebuf(Screen *self, PyObject *a UNUSED) {
    if (self->linebuf == self->alt_linebuf) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

WRAP1E(cursor_move, 1, -1, true)
WRAP1B(erase_in_line, 0)
WRAP1B(erase_in_display, 0)
static PyObject *
scroll_until_cursor_prompt(Screen *self, PyObject *args) {
    int b = false;
    if (!PyArg_ParseTuple(args, "|p", &b)) return NULL;
    screen_scroll_until_cursor_prompt(self, b);
    Py_RETURN_NONE;
}

WRAP0(clear_scrollback)

#define MODE_GETSET(name, uname)                                               \
    static PyObject *name##_get(Screen *self, void UNUSED *closure) {          \
        PyObject *ans = self->modes.m##uname ? Py_True : Py_False;             \
        Py_INCREF(ans);                                                        \
        return ans;                                                            \
    }                                                                          \
    static int name##_set(Screen *self, PyObject *val, void UNUSED *closure) { \
        if (val == NULL) {                                                     \
            PyErr_SetString(PyExc_TypeError, "Cannot delete attribute");       \
            return -1;                                                         \
        }                                                                      \
        set_mode_from_const(self, uname, PyObject_IsTrue(val) ? true : false); \
        return 0;                                                              \
    }

MODE_GETSET(in_bracketed_paste_mode, BRACKETED_PASTE)
MODE_GETSET(focus_tracking_enabled, FOCUS_TRACKING)
MODE_GETSET(color_preference_notification, COLOR_PREFERENCE_NOTIFICATION)
MODE_GETSET(in_band_resize_notification, INBAND_RESIZE_NOTIFICATION)
MODE_GETSET(paste_events, PASTE_EVENTS)
MODE_GETSET(detailed_mouse_events, DETAILED_MOUSE_EVENTS)
MODE_GETSET(auto_repeat_enabled, DECARM)
MODE_GETSET(cursor_visible, DECTCEM)
MODE_GETSET(cursor_key_mode, DECCKM)

static PyObject *
disable_ligatures_get(Screen *self, void UNUSED *closure) {
    const char *ans = NULL;
    switch (self->disable_ligatures) {
        case DISABLE_LIGATURES_NEVER: ans = "never"; break;
        case DISABLE_LIGATURES_CURSOR: ans = "cursor"; break;
        case DISABLE_LIGATURES_ALWAYS: ans = "always"; break;
    }
    return PyUnicode_FromString(ans);
}

static int
disable_ligatures_set(Screen *self, PyObject *val, void UNUSED *closure) {
    if (val == NULL) {
        PyErr_SetString(PyExc_TypeError, "Cannot delete attribute");
        return -1;
    }
    if (!PyUnicode_Check(val)) {
        PyErr_SetString(PyExc_TypeError, "unicode string expected");
        return -1;
    }
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

static PyObject *
render_unfocused_cursor_get(Screen *self, void UNUSED *closure) {
    if (self->cursor_render_info.render_even_when_unfocused) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static int
render_unfocused_cursor_set(Screen *self, PyObject *val, void UNUSED *closure) {
    if (val == NULL) {
        PyErr_SetString(PyExc_TypeError, "Cannot delete attribute");
        return -1;
    }
    self->cursor_render_info.render_even_when_unfocused = PyObject_IsTrue(val);
    return 0;
}

static PyObject *
cursor_up(Screen *self, PyObject *args) {
    unsigned int count = 1;
    int do_carriage_return = false, move_direction = -1;
    if (!PyArg_ParseTuple(args, "|Ipi", &count, &do_carriage_return, &move_direction)) return NULL;
    screen_cursor_up(self, count, do_carriage_return, move_direction);
    Py_RETURN_NONE;
}

static PyObject *
update_selection(Screen *self, PyObject *args) {
    unsigned int x, y;
    int in_left_half_of_cell = 0, ended = 1, nearest = 0;
    if (!PyArg_ParseTuple(args, "II|ppp", &x, &y, &in_left_half_of_cell, &ended, &nearest)) return NULL;
    screen_update_selection(self, x, y, in_left_half_of_cell, (SelectionUpdate){.ended = ended, .set_as_nearest_extend = nearest});
    Py_RETURN_NONE;
}

static PyObject *
clear_selection_(Screen *s, PyObject *args UNUSED) {
    clear_selection(&s->selections);
    Py_RETURN_NONE;
}

static PyObject *
resize(Screen *self, PyObject *args) {
    unsigned int a = 1, b = 1;
    if (!PyArg_ParseTuple(args, "|II", &a, &b)) return NULL;
    screen_resize(self, a, b);
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
}

WRAP0x(index) WRAP0(reverse_index) static PyObject *reset(Screen *self, PyObject *args) {
    int hard = true;
    if (!PyArg_ParseTuple(args, "|p", &hard)) return NULL;
    if (hard) screen_reset(self);
    else screen_soft_reset(self);
    Py_RETURN_NONE;
}
WRAP0(set_tab_stop)
WRAP1(clear_tab_stop, 0)
WRAP0(reset_tab_stops)
WRAP0(backspace)
WRAP0(tab)
WRAP0(linefeed)
WRAP0(carriage_return)
WRAP2(set_margins, 1, 1)
static PyObject *
detect_url(Screen *self, PyObject *args) {
    unsigned int x = 0, y = 0;
    if (!PyArg_ParseTuple(args, "|II", &x, &y)) return NULL;
    screen_detect_url(self, x, y, true);
    Py_RETURN_NONE;
}
WRAP0(rescale_images)

static PyObject *
current_key_encoding_flags(Screen *self, PyObject *args UNUSED) {
    unsigned long ans = screen_current_key_encoding_flags(self);
    return PyLong_FromUnsignedLong(ans);
}

static PyObject *
ignore_bells_for(Screen *self, PyObject *args) {
    double duration = 1;
    if (!PyArg_ParseTuple(args, "|d", &duration)) return NULL;
    self->ignore_bells.start = monotonic();
    self->ignore_bells.duration = s_double_to_monotonic_t(duration);
    Py_RETURN_NONE;
}

static PyObject *
start_selection(Screen *self, PyObject *args) {
    unsigned int x, y;
    int rectangle_select = 0, extend_mode = EXTEND_CELL, in_left_half_of_cell = 1;
    if (!PyArg_ParseTuple(args, "II|pip", &x, &y, &rectangle_select, &extend_mode, &in_left_half_of_cell)) return NULL;
    screen_start_selection(self, x, y, in_left_half_of_cell, rectangle_select, extend_mode);
    Py_RETURN_NONE;
}

static PyObject *
is_rectangle_select(Screen *self, PyObject *a UNUSED) {
    if (self->selections.count && self->selections.items[0].rectangle_select) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static PyObject *
copy_colors_from(Screen *self, Screen *other) {
    copy_color_profile(self->color_profile, other->color_profile);
    Py_RETURN_NONE;
}

static PyObject *
text_for_selections(Screen *self, Selections *selections, bool ansi, bool strip_trailing_whitespace) {
    PyObject *lines = NULL;
    for (size_t i = 0; i < selections->count; i++) {
        PyObject *temp = ansi ? ansi_for_range(self, selections->items + i, true, strip_trailing_whitespace)
                              : text_for_range(self, selections->items + i, true, strip_trailing_whitespace);
        if (temp) {
            if (lines) {
                lines = extend_tuple(lines, temp);
                Py_DECREF(temp);
            } else lines = temp;
        } else break;
    }
    if (PyErr_Occurred()) {
        Py_CLEAR(lines);
        return NULL;
    }
    if (!lines) lines = PyTuple_New(0);
    return lines;
}

static PyObject *
text_for_selection(Screen *self, PyObject *args) {
    int ansi = 0, strip_trailing_whitespace = 0;
    if (!PyArg_ParseTuple(args, "|pp", &ansi, &strip_trailing_whitespace)) return NULL;
    return text_for_selections(self, &self->selections, ansi, strip_trailing_whitespace);
}

static PyObject *
text_for_marked_url(Screen *self, PyObject *args) {
    int ansi = 0, strip_trailing_whitespace = 0;
    if (!PyArg_ParseTuple(args, "|pp", &ansi, &strip_trailing_whitespace)) return NULL;
    return text_for_selections(self, &self->url_ranges, ansi, strip_trailing_whitespace);
}

static bool
cell_is_blank(const CPUCell *c) {
    return !cell_has_text(c) || cell_is_char(c, ' ');
}

static void
screen_selection_range_for_line_(Line *line, index_type *start, index_type *end) {
    index_type xlimit = line->xnum, xstart = 0;
    while (xlimit > 0 && cell_is_blank(line->cpu_cells + xlimit - 1)) xlimit--;
    while (xstart < xlimit && cell_is_blank(line->cpu_cells + xstart)) xstart++;
    *start = xstart;
    *end = xlimit > 0 ? xlimit - 1 : 0;
}

bool
screen_selection_range_for_line(Screen *self, index_type y, index_type *start, index_type *end) {
    if (y >= self->lines) { return false; }
    screen_selection_range_for_line_(visual_line_(self, y), start, end);
    return true;
}

static bool
is_opt_word_char(char_type ch, bool forward) {
    if (forward && OPT(select_by_word_characters_forward)) {
        for (const char_type *p = OPT(select_by_word_characters_forward); *p; p++) {
            if (ch == *p) return true;
        }
        if (*OPT(select_by_word_characters_forward)) { return false; }
    }
    if (OPT(select_by_word_characters)) {
        for (const char_type *p = OPT(select_by_word_characters); *p; p++) {
            if (ch == *p) return true;
        }
    }
    return false;
}

static bool
is_char_ok_for_word_extension(Line *line, index_type x, bool forward) {
    char_type ch = cell_first_char(line->cpu_cells + x, line->text_cache);
    if (char_props_for(ch).is_word_char || is_opt_word_char(ch, forward)) return true;
    // pass : from :// so that common URLs are matched
    return ch == ':' && x + 2 < line->xnum && cell_is_char(line->cpu_cells + x + 1, '/') && cell_is_char(line->cpu_cells + x + 2, '/');
}

bool
screen_selection_range_for_word(
    Screen *self, const index_type x, const index_type y, index_type *y1, index_type *y2, index_type *s, index_type *e, bool initial_selection) {
    if (y >= self->lines || x >= self->columns) return false;
    index_type start, end;
    Line *line = visual_line_(self, y);
    *y1 = y;
    *y2 = y;
#define is_ok(x, forward) is_char_ok_for_word_extension(line, x, forward)
    if (!is_ok(x, false)) {
        if (initial_selection) return false;
        *s = x;
        *e = x;
        return true;
    }
    start = x;
    end = x;
    while (true) {
        while (start > 0 && is_ok(start - 1, false)) start--;
        if (start > 0 || !visual_line_is_continued(self, y) || *y1 == 0) break;
        line = visual_line_(self, *y1 - 1);
        if (!is_ok(self->columns - 1, false)) break;
        (*y1)--;
        start = self->columns - 1;
    }
    line = visual_line_(self, *y2);
    while (true) {
        while (end < self->columns - 1 && is_ok(end + 1, true)) end++;
        if (end < self->columns - 1 || *y2 >= self->lines - 1) break;
        line = visual_line_(self, *y2 + 1);
        if (!visual_line_is_continued(self, *y2 + 1) || !is_ok(0, true)) break;
        (*y2)++;
        end = 0;
    }
    *s = start;
    *e = end;
    return true;
#undef is_ok
}

void
screen_history_scroll_to_absolute(Screen *self, double target_scrolled_by) {
    if (self->linebuf != self->main_linebuf || isnan(target_scrolled_by)) return;
    if (target_scrolled_by < 0) target_scrolled_by = 0;
    if (target_scrolled_by > self->historybuf->count) target_scrolled_by = self->historybuf->count;
    index_type target_scrolled_by_line = (index_type)target_scrolled_by;
    unsigned pixel_scroll_offset_y = (unsigned)((target_scrolled_by - target_scrolled_by_line) * self->cell_size.height);
    if (!OPT(pixel_scroll)) pixel_scroll_offset_y = 0;
    if (target_scrolled_by_line > self->historybuf->count) target_scrolled_by_line = self->historybuf->count;
    if (target_scrolled_by_line >= self->historybuf->count) pixel_scroll_offset_y = 0;
    if (target_scrolled_by_line != self->scrolled_by || self->pixel_scroll_offset_y != pixel_scroll_offset_y) {
        self->scrolled_by = target_scrolled_by_line;
        reset_pixel_scroll(self, pixel_scroll_offset_y);
        dirty_scroll(self);
    }
}

static bool
scroll_by_pixels(Screen *self, double delta_pixels) {
    const double cell_height = (double)self->cell_size.height;
    if (cell_height <= 0.0 || delta_pixels == 0.0 || isnan(delta_pixels)) return false;

    double total = self->pixel_scroll_offset_y + (double)self->scrolled_by * cell_height + delta_pixels;
    const double max_total = (double)self->historybuf->count * cell_height;
    if (total < 0.0) total = 0.0;
    if (total > max_total) total = max_total;
    const unsigned int new_scrolled_by = (unsigned int)floor(total / cell_height);
    const unsigned offset = (unsigned)(total - (double)new_scrolled_by * cell_height);
    bool changed = false;
    if (new_scrolled_by != self->scrolled_by) {
        self->scrolled_by = new_scrolled_by;
        changed = true;
    }

    if (offset != self->pixel_scroll_offset_y) {
        self->pixel_scroll_offset_y = offset;
        changed = true;
    }
    if (changed) dirty_scroll(self);
    return changed;
}

bool
screen_apply_pixel_scroll(Screen *self, double delta_pixels) {
    if (self->paused_rendering.expires_at || !live_pixel_scroll_enabled(self)) return false;
    if (!self->historybuf->count) return false;
    return scroll_by_pixels(self, delta_pixels);
}

bool
screen_history_scroll(Screen *self, int amt, bool upwards) {
    switch (amt) {
        case SCROLL_LINE: amt = 1; break;
        case SCROLL_PAGE: amt = self->lines - 1; break;
        case SCROLL_FULL: amt = self->historybuf->count; break;
        default: amt = MAX(0, amt); break;
    }
    if (!upwards) {
        amt = MIN((unsigned int)amt, self->scrolled_by);
        amt *= -1;
    }
    unsigned int new_scroll = MIN(self->scrolled_by + amt, self->historybuf->count);
    if (new_scroll != self->scrolled_by || (new_scroll == 0 && self->pixel_scroll_offset_y != 0)) {
        self->scrolled_by = new_scroll;
        reset_pixel_scroll(self, 0);
        dirty_scroll(self);
        return true;
    }
    return false;
}

static bool
screen_fractional_scroll(Screen *self, double amt) {
    if (amt == 0 || isnan(amt)) return false;
    double integral_part, fractional_part = modf(amt, &integral_part);
    double pixels = trunc(fractional_part * self->cell_size.height);
    if (fractional_part > 0) pixels = MAX(1, pixels);
    else if (fractional_part < 0) pixels = MIN(-1, pixels);
    // positive amt scrolls towards the bottom
    return scroll_by_pixels(self, -(integral_part * self->cell_size.height + pixels));
}

static PyObject *
fractional_scroll(Screen *self, PyObject *amt) {
    double y;
    if (PyFloat_Check(amt)) y = PyFloat_AS_DOUBLE(amt);
    else if (PyLong_Check(amt)) {
        y = PyLong_AsDouble(amt);
        if (y == -1.0 && PyErr_Occurred()) return NULL;
    } else {
        PyErr_SetString(PyExc_TypeError, "amt must be a float");
        return NULL;
    }
    return Py_NewRef(screen_fractional_scroll(self, y) ? Py_True : Py_False);
}

static PyObject *
scroll_to_absolute(Screen *self, PyObject *amt) {
    double y;
    if (PyFloat_Check(amt)) y = PyFloat_AS_DOUBLE(amt);
    else if (PyLong_Check(amt)) {
        y = PyLong_AsDouble(amt);
        if (y == -1.0 && PyErr_Occurred()) return NULL;
    } else {
        PyErr_SetString(PyExc_TypeError, "amt must be a number");
        return NULL;
    }
    screen_history_scroll_to_absolute(self, y);
    Py_RETURN_NONE;
}

static PyObject *
scroll(Screen *self, PyObject *args) {
    int amt, upwards;
    if (!PyArg_ParseTuple(args, "ip", &amt, &upwards)) return NULL;
    if (screen_history_scroll(self, amt, upwards)) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

static PyObject *
scroll_to_prompt(Screen *self, PyObject *args) {
    int num_of_prompts = -1;
    int scroll_offset = 0;
    if (!PyArg_ParseTuple(args, "|ii", &num_of_prompts, &scroll_offset)) return NULL;
    if (screen_history_scroll_to_prompt(self, num_of_prompts, scroll_offset)) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

static PyObject *
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
    if (self->bidi_maps && bidi_selection_dirty(self)) return true;
    if (self->selections.last_rendered_count != self->selections.count || self->url_ranges.last_rendered_count != self->url_ranges.count ||
        self->extra_cursors.dirty)
        return true;
    for (size_t i = 0; i < self->selections.count; i++) {
        render_iteration_data(self, self->selections.items + i, &q);
        if (memcmp(&q, &self->selections.items[i].last_rendered, sizeof(IterationData)) != 0) return true;
    }
    for (size_t i = 0; i < self->url_ranges.count; i++) {
        render_iteration_data(self, self->url_ranges.items + i, &q);
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
    A(start.x, x);
    A(end.x, x);
    A(start.y, y);
    A(end.y, y);
    A(start_scrolled_by, self->scrolled_by);
    A(end_scrolled_by, self->scrolled_by);
    A(rectangle_select, rectangle_select);
    A(start.in_left_half_of_cell, in_left_half_of_cell);
    A(end.in_left_half_of_cell, in_left_half_of_cell);
    A(input_start.x, x);
    A(input_start.y, y);
    A(input_start.in_left_half_of_cell, in_left_half_of_cell);
    A(input_current.x, x);
    A(input_current.y, y);
    A(input_current.in_left_half_of_cell, in_left_half_of_cell);
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
    A(start.x, start_x);
    A(end.x, end_x);
    A(start.y, start_y);
    A(end.y, end_y);
    A(start_scrolled_by, self->scrolled_by);
    A(end_scrolled_by, self->scrolled_by);
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
                start = x;
                in_range = true;
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
    if (!line || x >= self->columns) return 0;
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
    ypos = y + 1;
    last_marked_line = y;
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
continue_line_upwards_scrollback(Screen *self, int top_line, SelectionBoundary *start, SelectionBoundary *end) {
    index_type num_in_scrollback = 0;
    Line *line = NULL;
    while (range_line_is_continued(self, top_line) && (line = range_line_(self, top_line - 1))) {
        screen_selection_range_for_line_(line, &start->x, &end->x);
        top_line--;
        num_in_scrollback++;
    }
    return num_in_scrollback;
}


static index_type
continue_line_downwards(Screen *self, index_type bottom_line, SelectionBoundary *start, SelectionBoundary *end) {
    while (bottom_line + 1 < self->lines && visual_line_is_continued(self, bottom_line + 1)) {
        if (!screen_selection_range_for_line(self, bottom_line + 1, &start->x, &end->x)) break;
        bottom_line++;
    }
    return bottom_line;
}

static index_type
continue_line_downwards_offscreen(Screen *self, int bottom_line, SelectionBoundary *start, SelectionBoundary *end) {
    index_type num_offscreen = 0;
    Line *line = NULL;
    while ((line = checked_range_line(self, bottom_line + 1)) && range_line_is_continued(self, bottom_line + 1)) {
        screen_selection_range_for_line_(line, &start->x, &end->x);
        bottom_line++;
        num_offscreen++;
    }
    return num_offscreen;
}

static index_type
continue_word_upwards_scrollback(Screen *self, int range_y, index_type *start_x) {
    index_type num_in_scrollback = 0;
    Line *line = NULL;
    while (*start_x == 0 && range_line_is_continued(self, range_y) && (line = checked_range_line(self, range_y - 1))) {
        if (!is_char_ok_for_word_extension(line, self->columns - 1, false)) break;
        range_y--;
        num_in_scrollback++;
        index_type s = self->columns - 1;
        while (s > 0 && is_char_ok_for_word_extension(line, s - 1, false)) s--;
        *start_x = s;
    }
    return num_in_scrollback;
}

static index_type
continue_word_downwards_offscreen(Screen *self, int range_y, index_type *end_x) {
    index_type num_offscreen = 0;
    Line *line = NULL;
    while (*end_x >= self->columns - 1 && (line = checked_range_line(self, range_y + 1)) && range_line_is_continued(self, range_y + 1)) {
        if (!is_char_ok_for_word_extension(line, 0, true)) break;
        range_y++;
        num_offscreen++;
        index_type e = 0;
        while (e < self->columns - 1 && is_char_ok_for_word_extension(line, e + 1, true)) e++;
        *end_x = e;
    }
    return num_offscreen;
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
    if (current->scale == start->scale && current->subscale_n == start->subscale_n && current->subscale_d == start->subscale_d &&
        abs_current_top == abs_start_top)
        delta = abs_y - abs_start_y;
    return delta;
}

static void
do_update_selection(Screen *self, Selection *s, index_type x, index_type y, bool in_left_half_of_cell, SelectionUpdate upd) {
    s->input_current.x = x;
    s->input_current.y = y;
    s->input_current.in_left_half_of_cell = in_left_half_of_cell;
    SelectionBoundary start, end, *a = &s->start, *b = &s->end, abs_start, abs_end, abs_current_input;
#define set_abs(which, initializer, scrolled_by) \
    which = initializer;                         \
    which.y = scrolled_by + self->lines - 1 - which.y;
    set_abs(abs_start, s->start, s->start_scrolled_by);
    set_abs(abs_end, s->end, s->end_scrolled_by);
    set_abs(abs_current_input, s->input_current, self->scrolled_by);
    bool return_word_sel_to_start_line = false;
    if (upd.set_as_nearest_extend || self->selections.extension_in_progress) {
        self->selections.extension_in_progress = true;
        bool start_is_nearer = false;
        if (self->selections.extend_mode == EXTEND_LINE || self->selections.extend_mode == EXTEND_LINE_FROM_BEGIN ||
            self->selections.extend_mode == EXTEND_LINE_FROM_POINT || self->selections.extend_mode == EXTEND_WORD_AND_LINE_FROM_POINT) {
            if (abs_start.y == abs_end.y) {
                if (abs_current_input.y == abs_start.y)
                    start_is_nearer =
                        selection_boundary_less_than(&abs_start, &abs_end) ? (abs_current_input.x <= abs_start.x) : (abs_current_input.x <= abs_end.x);
                else
                    start_is_nearer =
                        selection_boundary_less_than(&abs_start, &abs_end) ? (abs_current_input.y > abs_start.y) : (abs_current_input.y < abs_end.y);
            } else {
                start_is_nearer = num_lines_between_selection_boundaries(&abs_start, &abs_current_input) <
                                  num_lines_between_selection_boundaries(&abs_end, &abs_current_input);
            }
        } else
            start_is_nearer = num_cells_between_selection_boundaries(self, &abs_start, &abs_current_input) <
                              num_cells_between_selection_boundaries(self, &abs_end, &abs_current_input);
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
                s->start = s->initial_extent.start;
                s->start_scrolled_by = s->initial_extent.scrolled_by;
                s->end = s->initial_extent.end;
                s->end_scrolled_by = s->initial_extent.scrolled_by;
            } else {
                s->adjusting_start = abs_current_input.y > initial_line;
            }
        }
    }
#undef set_abs
    bool adjusted_boundary_is_before;
    if (s->adjusting_start) adjusted_boundary_is_before = selection_boundary_less_than(&abs_start, &abs_end);
    else { adjusted_boundary_is_before = selection_boundary_less_than(&abs_end, &abs_start); }

    switch (self->selections.extend_mode) {
        case EXTEND_WORD: {
            if (!s->adjusting_start) {
                a = &s->end;
                b = &s->start;
            }
            const bool word_found_at_cursor =
                screen_selection_range_for_word(self, s->input_current.x, s->input_current.y, &start.y, &end.y, &start.x, &end.x, true);
            bool adjust_both_ends = is_selection_empty(s);
            if (return_word_sel_to_start_line) {
                index_type ox = a->x;
                if (s->adjusting_start) {
                    *a = s->initial_extent.start;
                    if (ox < a->x) a->x = ox;
                } else {
                    *a = s->initial_extent.end;
                    if (ox > a->x) a->x = ox;
                }
            } else if (word_found_at_cursor) {
                if (adjusted_boundary_is_before) {
                    *a = start;
                    a->in_left_half_of_cell = true;
                    if (adjust_both_ends) {
                        *b = end;
                        b->in_left_half_of_cell = false;
                    }
                } else {
                    *a = end;
                    a->in_left_half_of_cell = false;
                    if (adjust_both_ends) {
                        *b = start;
                        b->in_left_half_of_cell = true;
                    }
                }
                if (s->adjusting_start || adjust_both_ends) s->start_scrolled_by = self->scrolled_by;
                if (!s->adjusting_start || adjust_both_ends) s->end_scrolled_by = self->scrolled_by;
                // extend word into scrollback if needed
                if (start.y == 0 && self->linebuf == self->main_linebuf && (adjust_both_ends || adjusted_boundary_is_before)) {
                    index_type num_in_scrollback = continue_word_upwards_scrollback(self, 0, &start.x);
                    if (num_in_scrollback) {
                        s->start_scrolled_by += num_in_scrollback;
                        s->start.x = start.x;
                    }
                }
                // extend word below viewport if needed
                if (end.y >= self->lines - 1 && self->scrolled_by > 0 && self->linebuf == self->main_linebuf &&
                    (adjust_both_ends || !adjusted_boundary_is_before)) {
                    int range_bottom = (int)end.y - (int)self->scrolled_by;
                    index_type num_below_viewport = continue_word_downwards_offscreen(self, range_bottom, &end.x);
                    if (num_below_viewport) {
                        s->end_scrolled_by -= num_below_viewport;
                        s->end.x = end.x;
                    }
                }
            } else {
                *a = s->input_current;
                if (s->adjusting_start) s->start_scrolled_by = self->scrolled_by;
                else s->end_scrolled_by = self->scrolled_by;
            }
            break;
        }
        case EXTEND_LINE_FROM_BEGIN:
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
                top_line = s->input_current.y;
                bottom_line = s->input_current.y;
                if (screen_selection_range_for_line(self, top_line, &up_start.x, &up_end.x)) {
#define S                                 \
    s->start.y = top_line;                \
    s->end.y = bottom_line;               \
    s->start.in_left_half_of_cell = true; \
    s->end.in_left_half_of_cell = false;  \
    s->start.x = up_start.x;              \
    s->end.x = bottom_line == top_line ? up_end.x : down_end.x;
                    down_start = up_start;
                    down_end = up_end;
                    bottom_line = continue_line_downwards(self, bottom_line, &down_start, &down_end);
                    if (self->selections.extend_mode == EXTEND_LINE_FROM_BEGIN) {
                        S;
                        s->start.x = 0;
                    } else if (self->selections.extend_mode == EXTEND_LINE_FROM_POINT) {
                        if (x <= up_end.x) {
                            S;
                            s->start.x = MAX(x, up_start.x);
                        }
                    } else if (self->selections.extend_mode == EXTEND_WORD_AND_LINE_FROM_POINT) {
                        if (x <= up_end.x) {
                            S;
                            s->start.x = MAX(x, up_start.x);
                        }
                        const bool word_found_at_cursor =
                            screen_selection_range_for_word(self, s->input_current.x, s->input_current.y, &start.y, &end.y, &start.x, &end.x, true);
                        if (word_found_at_cursor) {
                            *a = start;
                            a->in_left_half_of_cell = true;
                        }
                    } else {
                        top_line = continue_line_upwards(self, top_line, &up_start, &up_end);
                        S;
                        // extend into scrollback if needed
                        if (top_line == 0 && self->linebuf == self->main_linebuf) {
                            index_type num_in_scrollback = continue_line_upwards_scrollback(self, top_line, &up_start, &up_end);
                            if (num_in_scrollback) {
                                s->start_scrolled_by += num_in_scrollback;
                                s->start.x = up_start.x;
                            }
                        }
                        // extend below viewport if needed
                        if (bottom_line >= self->lines - 1 && self->scrolled_by > 0 && self->linebuf == self->main_linebuf) {
                            int range_bottom = (int)bottom_line - (int)self->scrolled_by;
                            index_type num_below_viewport = continue_line_downwards_offscreen(self, range_bottom, &down_start, &down_end);
                            if (num_below_viewport) {
                                s->end_scrolled_by -= num_below_viewport;
                                s->end.x = down_end.x;
                            }
                        }
                    }
                }
#undef S
            } else {
                // extending an existing selection
                top_line = s->input_current.y;
                bottom_line = s->input_current.y;
                if (screen_selection_range_for_line(self, top_line, &up_start.x, &up_end.x)) {
                    down_start = up_start;
                    down_end = up_end;
                    top_line = continue_line_upwards(self, top_line, &up_start, &up_end);
                    bottom_line = continue_line_downwards(self, bottom_line, &down_start, &down_end);
                    if (!s->adjusting_start) {
                        a = &s->end;
                        b = &s->start;
                    }
                    if (adjusted_boundary_is_before) {
                        a->in_left_half_of_cell = true;
                        a->x = up_start.x;
                        a->y = top_line;
                        // extend into scrollback if needed
                        if (top_line == 0 && self->linebuf == self->main_linebuf) {
                            index_type num_in_scrollback = continue_line_upwards_scrollback(self, top_line, &up_start, &up_end);
                            if (num_in_scrollback) {
                                s->start_scrolled_by += num_in_scrollback;
                                s->start.x = up_start.x;
                            }
                        }
                    } else {
                        a->in_left_half_of_cell = false;
                        a->x = down_end.x;
                        a->y = bottom_line;
                        // extend below viewport if needed
                        if (bottom_line >= self->lines - 1 && self->scrolled_by > 0 && self->linebuf == self->main_linebuf) {
                            int range_bottom = (int)bottom_line - (int)self->scrolled_by;
                            index_type num_below_viewport = continue_line_downwards_offscreen(self, range_bottom, &down_start, &down_end);
                            if (num_below_viewport) {
                                s->end_scrolled_by -= num_below_viewport;
                                s->end.x = down_end.x;
                            }
                        }
                    }
                    // allow selecting whitespace at the start of the top line
                    if (a->y == top_line && s->input_current.y == top_line && s->input_current.x < a->x && adjusted_boundary_is_before)
                        a->x = s->input_current.x;
                }
            }
        } break;
        case EXTEND_CELL:
            if (s->adjusting_start) b = &s->start;
            b->x = x;
            b->y = y;
            b->in_left_half_of_cell = in_left_half_of_cell;
            if (s->adjusting_start) s->start_scrolled_by = self->scrolled_by;
            else s->end_scrolled_by = self->scrolled_by;
            break;
    }
    if (!self->selections.in_progress) {
        s->adjusting_start = false;
        self->selections.extension_in_progress = false;
        call_boss(set_primary_selection, NULL);
    } else {
        if (upd.start_extended_selection && self->selections.extend_mode != EXTEND_CELL) {
            s->initial_extent.start = s->start;
            s->initial_extent.end = s->end;
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
            y = 0;
            self->scrolled_by += -new_y;
        } else y = new_y;
    }
    do_update_selection(self, s, x, y, in_left_half_of_cell, upd);
    self->scrolled_by = orig;
}

static PyObject *
mark_as_dirty(Screen *self, PyObject *a UNUSED) {
    self->is_dirty = true;
    Py_RETURN_NONE;
}

static PyObject *
reload_all_gpu_data(Screen *self, PyObject *a UNUSED) {
    self->reload_all_gpu_data = true;
    Py_RETURN_NONE;
}


static PyObject *
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

static PyObject *
is_main_linebuf(Screen *self, PyObject *a UNUSED) {
    PyObject *ans = (self->linebuf == self->main_linebuf) ? Py_True : Py_False;
    Py_INCREF(ans);
    return ans;
}

static PyObject *
toggle_alt_screen(Screen *self, PyObject *a UNUSED) {
    screen_toggle_screen_buffer(self, true, true);
    Py_RETURN_NONE;
}

static PyObject *
smooth_scroll_define(Screen *self, PyObject *args) {
    unsigned int id, left, top, right, bottom, capacity = 1;
    int private_overflow = 0, horizontal = 0;
    if (!PyArg_ParseTuple(args, "IIIII|Ipp", &id, &left, &top, &right, &bottom, &capacity, &private_overflow, &horizontal)) return NULL;
    return Py_NewRef(screen_smooth_scroll_define(self, id, left, top, right, bottom, capacity, private_overflow, horizontal) ? Py_True : Py_False);
}

static PyObject *
smooth_scroll(Screen *self, PyObject *args) {
    unsigned int id;
    int delta, rows_shifted;
    if (!PyArg_ParseTuple(args, "Ii", &id, &delta)) return NULL;
    if (!screen_smooth_scroll(self, id, delta, &rows_shifted)) Py_RETURN_NONE;
    return PyLong_FromLong(rows_shifted);
}

static PyObject *
smooth_scroll_remove(Screen *self, PyObject *args) {
    unsigned int id;
    if (!PyArg_ParseTuple(args, "I", &id)) return NULL;
    return Py_NewRef(screen_smooth_scroll_remove(self, id) ? Py_True : Py_False);
}

static PyObject *
smooth_scroll_regions(Screen *self, PyObject *args UNUSED) {
    RAII_PyObject(ans, PyTuple_New(self->smooth_scroll.count));
    if (!ans) return NULL;
    for (unsigned i = 0; i < self->smooth_scroll.count; i++) {
        const SmoothScrollRegion *r = self->smooth_scroll.regions + i;
        PyObject *d = Py_BuildValue(
            "{sI sI sI sI sI sI si sI sI sO sO sO}",
            "id",
            r->id,
            "left",
            r->left,
            "top",
            r->top,
            "right",
            r->right,
            "bottom",
            r->bottom,
            "capacity",
            r->capacity,
            "offset",
            r->offset,
            "num_before",
            r->num_before,
            "num_after",
            r->num_after,
            "private_overflow",
            r->private_overflow ? Py_True : Py_False,
            "uses_history",
            ssr_uses_history(self, r) ? Py_True : Py_False,
            "horizontal",
            r->horizontal ? Py_True : Py_False);
        if (!d) return NULL;
        PyTuple_SET_ITEM(ans, i, d);
    }
    return Py_NewRef(ans);
}

static PyObject *
smooth_scroll_overflow(Screen *self, PyObject *args) {
    // The text of the rows in an overflow buffer of a region, nearest first
    unsigned int id;
    int above;
    if (!PyArg_ParseTuple(args, "Ip", &id, &above)) return NULL;
    SmoothScrollRegion *r = ssr_for_id(self, id);
    if (!r) {
        PyErr_Format(PyExc_KeyError, "No smooth scroll region with id: %u", id);
        return NULL;
    }
    const index_type n = above ? r->num_before : r->num_after;
    if (r->horizontal) {
        // The columns to the left or right of each row, in order from left to right
        RAII_PyObject(ans, PyTuple_New(ssr_height(r)));
        if (!ans) return NULL;
        for (index_type y = 0; y < ssr_height(r); y++) {
            Line line = {.text_cache = self->text_cache};
            linebuf_init_line_at(r->overflow, above ? y : ssr_height(r) + y, &line);
            if (above) {
                line.cpu_cells += r->capacity - n;
                line.render_cells += r->capacity - n;
            }
            line.xnum = n;
            PyObject *t = line_as_unicode(&line, false, &self->as_ansi_buf);
            if (!t) return NULL;
            PyTuple_SET_ITEM(ans, y, t);
        }
        return Py_NewRef(ans);
    }
    RAII_PyObject(ans, PyTuple_New(n));
    if (!ans) return NULL;
    for (index_type i = 0; i < n; i++) {
        linebuf_init_line(r->overflow, ssr_slot(r, above, i));
        PyObject *t = line_as_unicode(r->overflow->line, false, &self->as_ansi_buf);
        if (!t) return NULL;
        PyTuple_SET_ITEM(ans, i, t);
    }
    return Py_NewRef(ans);
}

static PyObject *
pause_rendering(Screen *self, PyObject *args) {
    int msec = 100;
    int pause = 1;
    if (!PyArg_ParseTuple(args, "|pi", &pause, &msec)) return NULL;
    if (screen_pause_rendering(self, pause, msec)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static PyObject *
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
    if (written) {
        Py_RETURN_TRUE;
    } else {
        Py_RETURN_FALSE;
    }
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
    // Marks are render data, history lines are marked when rendered
    for (index_type y = 0; y < self->historybuf->count; y++) historybuf_mark_line_dirty(self->historybuf, y);
    self->is_dirty = true;
}

static PyObject *
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


static PyObject *
scroll_to_next_mark(Screen *self, PyObject *args) {
    int backwards = 1;
    unsigned int mark = 0;
    if (!PyArg_ParseTuple(args, "|Ip", &mark, &backwards)) return NULL;
    if (!screen_has_marker(self) || self->linebuf == self->alt_linebuf) Py_RETURN_FALSE;
    // History lines have no render data and so no marks, compute them in a scratch buffer
    RAII_ALLOC(RenderCell, scratch, calloc(self->historybuf->xnum, sizeof(RenderCell)));
    if (!scratch) return PyErr_NoMemory();
    bool found;
#define history_line_has_mark(y)                                                  \
    (historybuf_init_line(self->historybuf, y, self->historybuf->line),           \
     self->historybuf->line->render_cells = scratch,                              \
     mark_text_in_line(self->marker, self->historybuf->line, &self->as_ansi_buf), \
     found = line_has_mark(self->historybuf->line, mark),                         \
     self->historybuf->line->render_cells = NULL,                                 \
     found)
    if (backwards) {
        for (unsigned int y = self->scrolled_by; y < self->historybuf->count; y++) {
            if (history_line_has_mark(y)) {
                screen_history_scroll(self, y - self->scrolled_by + 1, true);
                Py_RETURN_TRUE;
            }
        }
    } else {
        Line *line;
        for (unsigned int y = self->scrolled_by; y > 0; y--) {
            if (y > self->lines) {
                if (history_line_has_mark(y - self->lines)) {
                    screen_history_scroll(self, self->scrolled_by - y + 1, false);
                    Py_RETURN_TRUE;
                }
                continue;
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
#undef history_line_has_mark
    Py_RETURN_FALSE;
}

static PyObject *
marked_cells(Screen *self, PyObject *o UNUSED) {
    RAII_PyObject(ans, PyList_New(0));
    if (!ans) return ans;
    for (index_type y = 0; y < self->lines; y++) {
        linebuf_init_line(self->linebuf, y);
        for (index_type x = 0; x < self->columns; x++) {
            const unsigned int mark = self->linebuf->line->render_cells[x].mark;
            if (mark) {
                RAII_PyObject(t, Py_BuildValue("III", x, y, mark));
                if (!t) { return NULL; }
                if (PyList_Append(ans, t) != 0) return NULL;
            }
        }
    }
    return Py_NewRef(ans);
}

static PyObject *
paste_(Screen *self, PyObject *bytes, bool allow_bracketed_paste) {
    const char *data;
    Py_ssize_t sz;
    if (PyBytes_Check(bytes)) {
        data = PyBytes_AS_STRING(bytes);
        sz = PyBytes_GET_SIZE(bytes);
    } else if (PyMemoryView_Check(bytes)) {
        RAII_PyObject(mv, PyMemoryView_GetContiguous(bytes, PyBUF_READ, PyBUF_C_CONTIGUOUS));
        if (mv == NULL) return NULL;
        Py_buffer *buf = PyMemoryView_GET_BUFFER(mv);
        data = buf->buf;
        sz = buf->len;
    } else {
        PyErr_SetString(PyExc_TypeError, "Must paste() bytes");
        return NULL;
    }
    if (allow_bracketed_paste && self->modes.mBRACKETED_PASTE) write_escape_code_to_child(self, ESC_CSI, BRACKETED_PASTE_START);
    write_to_child(self, data, sz);
    if (allow_bracketed_paste && self->modes.mBRACKETED_PASTE) write_escape_code_to_child(self, ESC_CSI, BRACKETED_PASTE_END);
    Py_RETURN_NONE;
}


static PyObject *
paste(Screen *self, PyObject *bytes) {
    return paste_(self, bytes, true);
}

static PyObject *
paste_bytes(Screen *self, PyObject *bytes) {
    return paste_(self, bytes, false);
}

static PyObject *
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

static PyObject *
has_focus(Screen *self, PyObject *args UNUSED) {
    if (self->has_focus) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static PyObject *
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

static PyObject *
py_insert_characters(Screen *self, PyObject *count_) {
    if (!PyLong_Check(count_)) {
        PyErr_SetString(PyExc_TypeError, "count must be an integer");
        return NULL;
    }
    unsigned long count = PyLong_AsUnsignedLong(count_);
    screen_insert_characters(self, count);
    Py_RETURN_NONE;
}

static PyObject *
screen_is_emoji_presentation_base(PyObject UNUSED *self, PyObject *code_) {
    unsigned long code = PyLong_AsUnsignedLong(code_);
    if (is_emoji_presentation_base(code)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static PyObject *
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

static PyObject *
reverse_scroll(Screen *self, PyObject *args) {
    int fill_from_scrollback = 0;
    unsigned int amt;
    if (!PyArg_ParseTuple(args, "I|p", &amt, &fill_from_scrollback)) return NULL;
    _reverse_scroll(self, amt, fill_from_scrollback);
    Py_RETURN_NONE;
}


static PyObject *
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
        reset_pixel_scroll(self, 0);
        dirty_scroll(self);
    }
    Py_RETURN_NONE;
}

static void
dump_line_with_attrs(Screen *self, int y, PyObject *accum) {
    Line *line = range_line_(self, y);
    RAII_PyObject(u, PyUnicode_FromFormat("\x1b[31m%d: \x1b[39m", y));
    if (!u) return;
    RAII_PyObject(r1, PyObject_CallOneArg(accum, u));
    if (!r1) return;
#define call_string(s)                                            \
    {                                                             \
        RAII_PyObject(ret, PyObject_CallFunction(accum, "s", s)); \
        if (!ret) return;                                         \
    }
    switch (line->attrs.prompt_kind) {
        case UNKNOWN_PROMPT_KIND: break;
        case PROMPT_START: call_string("\x1b[32mprompt \x1b[39m"); break;
        case SECONDARY_PROMPT: call_string("\x1b[32msecondary_prompt \x1b[39m"); break;
        case OUTPUT_START: call_string("\x1b[33moutput \x1b[39m"); break;
    }
    if (range_line_is_continued(self, y)) call_string("continued ");
    if (line->attrs.has_dirty_text) call_string("dirty ");
    call_string("\n");
    RAII_PyObject(t, line_as_unicode(line, false, &self->as_ansi_buf));
    if (!t) return;
    RAII_PyObject(r2, PyObject_CallOneArg(accum, t));
    if (!r2) return;
    call_string("\n");
#undef call_string
}

static PyObject *
dump_lines_with_attrs(Screen *self, PyObject *args) {
    PyObject *accum;
    int which_screen = -1;
    if (!PyArg_ParseTuple(args, "O|i", &accum, &which_screen)) return NULL;
    LineBuf *orig = self->linebuf;
    switch (which_screen) {
        case 0: self->linebuf = self->main_linebuf; break;
        case 1: self->linebuf = self->alt_linebuf; break;
    }
    int y = (self->linebuf == self->main_linebuf) ? -self->historybuf->count : 0;
    while (y < (int)self->lines && !PyErr_Occurred()) dump_line_with_attrs(self, y++, accum);
    self->linebuf = orig;
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
}

static PyObject *
cursor_at_prompt(Screen *self, PyObject *args UNUSED) {
    int y = screen_cursor_at_a_shell_prompt(self);
    if (y > -1) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

static PyObject *
cursor_prompt_line(Screen *self, PyObject *args UNUSED) {
    return PyLong_FromLong(screen_cursor_at_a_shell_prompt(self));
}

static PyObject *
ime_text_around_cursor(Screen *self, PyObject *a UNUSED) {
    char *before, *after;
    if (!screen_ime_text_around_cursor(self, &before, &after)) return PyErr_NoMemory();
    PyObject *ans = Py_BuildValue("ss", before, after);
    free(before);
    free(after);
    return ans;
}

static PyObject *
line_edge_colors(Screen *self, PyObject *a UNUSED) {
    color_type left, right;
    if (!get_line_edge_colors(self, &left, &right)) {
        PyErr_SetString(PyExc_IndexError, "Line number out of range");
        return NULL;
    }
    return Py_BuildValue("kk", (unsigned long)left, (unsigned long)right);
}

// With strips true, the data of the strips, laid out as the renderer lays them out, follows that of the screen cells
static PyObject *
current_selections(Screen *self, PyObject *args) {
    int strips = 0;
    if (!PyArg_ParseTuple(args, "|p", &strips)) return NULL;
    if (strips) screen_prepare_smooth_scroll_render(self); // mimic what the renderer does
    const size_t num_cells = (size_t)render_lines_for_screen(self) * self->columns + (strips ? self->smooth_scroll_render.num_strip_cells : 0);
    PyObject *ans = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)num_cells);
    if (!ans) return NULL;
    screen_apply_selection(self, PyBytes_AS_STRING(ans), PyBytes_GET_SIZE(ans), 1);
    self->last_rendered.scrolled_by = rendered_scrolled_by(self); // mimic what the renderer does
    return ans;
}

static PyObject *
update_graphics_layers(Screen *self, PyObject *a UNUSED) {
    screen_prepare_smooth_scroll_render(self); // mimic what the renderer does
    screen_update_graphics_layers(self);
    return grman_render_data_as_python(self->paused_rendering.expires_at ? self->paused_rendering.grman : self->grman);
}

static PyObject *
rendered_scroll_state(Screen *self, PyObject *a UNUSED) {
    return Py_BuildValue("III", rendered_scrolled_by(self), rendered_pixel_scroll_offset_y(self), rendered_history_count(self));
}

static PyObject *
has_scrollbar(Screen *self, PyObject *is_hovering) {
    const int hovering = PyObject_IsTrue(is_hovering);
    if (hovering < 0) return NULL;
    return Py_NewRef(screen_has_scrollbar(self, hovering) ? Py_True : Py_False);
}

static PyObject *
scrollbar_geometry(Screen *self, PyObject *a UNUSED) {
    float handle_position, visible_fraction;
    screen_scrollbar_geometry(self, &handle_position, &visible_fraction);
    return Py_BuildValue("ff", handle_position, visible_fraction);
}

static PyObject *
is_selection_dirty(Screen *self, PyObject *a UNUSED) {
    if (screen_is_selection_dirty(self)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

WRAP0(update_only_line_graphics_data)
WRAP0(bell)

#define MND(name, args) {#name, (PyCFunction)name, args, #name},
#define MODEFUNC(name) MND(name, METH_NOARGS) MND(set_##name, METH_O)

static PyObject *
test_create_write_buffer(Screen *screen UNUSED, PyObject *args UNUSED) {
    size_t s;
    uint8_t *buf = vt_parser_create_write_buffer(screen->vt_parser, &s);
    return PyMemoryView_FromMemory((char *)buf, s, PyBUF_WRITE);
}

static PyObject *
overlay_line_start(Screen *self, PyObject *a UNUSED) {
    return PyLong_FromUnsignedLong(screen_overlay_line_start(self));
}

static PyObject *
test_draw_overlay_line(Screen *self, PyObject *args) {
    PyObject *text;
    unsigned int xstart, ynum;
    int preedit_cursor = -1;
    if (!PyArg_ParseTuple(args, "UII|i", &text, &xstart, &ynum, &preedit_cursor)) return NULL;
    if (ynum >= self->lines || xstart >= self->columns) {
        PyErr_SetString(PyExc_IndexError, "ynum or xstart out of range");
        return NULL;
    }
    RAII_PyObject(text_width, wcswidth_std(NULL, text));
    if (!text_width) return NULL;
    const long width = PyLong_AsLong(text_width);
    if (width < 0) {
        if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "pre-edit text has negative width");
        return NULL;
    }
    Py_INCREF(text);
    Py_XDECREF(self->overlay_line.overlay_text);
    self->overlay_line.overlay_text = text;
    self->overlay_line.text_len = (index_type)width;
    self->overlay_line.xstart = xstart;
    self->overlay_line.ynum = ynum;
    self->overlay_line.preedit_cursor = preedit_cursor;
    self->overlay_line.is_active = true;
    // As screen_update_overlay_text() does, so the text is drawn with the formatting at the cursor
    cursor_copy_to(self->cursor, &(self->overlay_line.original_line.cursor));
    screen_draw_overlay_line(self);
    return PyLong_FromUnsignedLong(self->overlay_line.cursor_x);
}

static PyObject *
test_update_overlay_text(Screen *self, PyObject *args) {
    const char *text;
    int preedit_cursor = -1;
    if (!PyArg_ParseTuple(args, "s|i", &text, &preedit_cursor)) return NULL;
    screen_update_overlay_text(self, text, preedit_cursor);
    // Nothing is drawn here, the cursor position must be correct without drawing
    return PyLong_FromUnsignedLong(self->overlay_line.cursor_x);
}

static PyObject *
test_commit_write_buffer(Screen *screen, PyObject *args) {
    RAII_PY_BUFFER(srcbuf);
    RAII_PY_BUFFER(destbuf);
    if (!PyArg_ParseTuple(args, "y*y*", &srcbuf, &destbuf)) return NULL;
    size_t s = MIN(srcbuf.len, destbuf.len);
    memcpy(destbuf.buf, srcbuf.buf, s);
    vt_parser_commit_write(screen->vt_parser, s);
    return PyLong_FromSize_t(s);
}

static bool
verify_styles_in_line(const CellStyleTable *t, const char *which, index_type y, const CPUCell *c, index_type xnum, PyObject *ans) {
    for (index_type x = 0; x < xnum; x++) {
        if (c[x].style_idx >= t->count) {
            RAII_PyObject(e, Py_BuildValue("sIII", which, y, x, (unsigned)c[x].style_idx));
            if (!e || PyList_Append(ans, e) != 0) return false;
            if (PyList_GET_SIZE(ans) > 16) return true;
        }
    }
    return true;
}

static PyObject *
test_verify_styles(Screen *self, PyObject *a UNUSED) {
    // Check that the style index of every cell is valid. Returns a list of invalid cells.
    RAII_PyObject(ans, PyList_New(0));
    if (!ans) return NULL;
    const CellStyleTable *t = self->style_table;
    LineBuf *bufs[3] = {self->main_linebuf, self->alt_linebuf, paused_linebuf_in_use(self)};
    const char *names[3] = {"main", "alt", "paused"};
    for (unsigned b = 0; b < arraysz(bufs); b++) {
        LineBuf *lb = bufs[b];
        if (!lb) continue;
        for (index_type y = 0; y < lb->ynum; y++) {
            if (!verify_styles_in_line(t, names[b], y, linebuf_cpu_cells_for_line(lb, y), lb->xnum, ans)) return NULL;
        }
    }
    for (index_type y = 0; y < self->historybuf->count; y++) {
        if (!verify_styles_in_line(t, "history", y, historybuf_cpu_cells(self->historybuf, y), self->historybuf->xnum, ans)) return NULL;
    }
    if (self->overlay_line.cpu_cells && !verify_styles_in_line(t, "overlay", 0, self->overlay_line.cpu_cells, self->columns, ans)) return NULL;
    if (self->overlay_line.original_line.cpu_cells &&
        !verify_styles_in_line(t, "overlay_original", 0, self->overlay_line.original_line.cpu_cells, self->columns, ans))
        return NULL;
    return Py_NewRef(ans);
}

static PyObject *
test_parse_written_data(Screen *screen, PyObject *args) {
    ParseData pd = {.now = monotonic()};
    if (!PyArg_ParseTuple(args, "|O", &pd.dump_callback)) return NULL;
    const bool had_url_highlight = screen->url_ranges.count > 0;
    if (pd.dump_callback && pd.dump_callback != Py_None) parse_worker_dump(screen, &pd, true);
    else parse_worker(screen, &pd, true);
    if (had_url_highlight && !screen->url_ranges.count) link_hover_cleared_by_output(screen);
    Py_RETURN_NONE;
}

static PyObject *
restore_scrollback(Screen *self, PyObject *data) {
    // Parse previously saved output as though it came from the child. Must only be called before the child is allowed to run,
    // as the I/O thread must be the only writer to the parser buffer while the child is running.
    RAII_PY_BUFFER(buf);
    if (PyObject_GetBuffer(data, &buf, PyBUF_SIMPLE) != 0) return NULL;
    const uint8_t *src = buf.buf;
    size_t remaining = buf.len;
    ParseData pd = {.now = monotonic()};
    while (remaining) {
        size_t space = 0;
        uint8_t *dest = vt_parser_create_write_buffer_if_none(self->vt_parser, &space);
        if (!dest) {
            PyErr_SetString(PyExc_RuntimeError, "Cannot restore scrollback as the child is already writing to the screen");
            return NULL;
        }
        const size_t sz = MIN(space, remaining);
        if (sz) memcpy(dest, src, sz);
        vt_parser_commit_write(self->vt_parser, sz);
        if (!sz) {
            PyErr_SetString(PyExc_RuntimeError, "Cannot restore scrollback as there is no space in the parser buffer");
            return NULL;
        }
        src += sz;
        remaining -= sz;
        parse_worker(self, &pd, true);
    }
    Py_RETURN_NONE;
}

static PyObject *
multicell_data_as_dict(CPUCell mcd) {
    return Py_BuildValue(
        "{sI sI sI sI sO sI sI}",
        "scale",
        (unsigned int)mcd.scale,
        "width",
        (unsigned int)mcd.width,
        "subscale_n",
        (unsigned int)mcd.subscale_n,
        "subscale_d",
        (unsigned int)mcd.subscale_d,
        "natural_width",
        mcd.natural_width ? Py_True : Py_False,
        "vertical_align",
        mcd.valign,
        "horizontal_align",
        mcd.halign);
}

static PyObject *
cpu_cell_as_dict(CPUCell *c, TextCache *tc, ListOfChars *lc, HYPERLINK_POOL_HANDLE h) {
    text_in_cell(c, tc, lc);
    RAII_PyObject(mcd, c->is_multicell ? multicell_data_as_dict(*c) : Py_NewRef(Py_None));
    if ((c->is_multicell && (c->x + c->y)) || (lc->count == 1 && lc->chars[0] == 0)) lc->count = 0;
    RAII_PyObject(text, PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, lc->chars, lc->count));
    const char *url = c->hyperlink_id ? get_hyperlink_for_id(h, c->hyperlink_id, false) : NULL;
    RAII_PyObject(hyperlink, url ? PyUnicode_FromString(url) : Py_NewRef(Py_None));
    return Py_BuildValue(
        "{sO sO sI sI sO sO}",
        "text",
        text,
        "hyperlink",
        hyperlink,
        "x",
        (unsigned int)c->x,
        "y",
        (unsigned int)c->y,
        "mcd",
        mcd,
        "next_char_was_wrapped",
        c->next_char_was_wrapped ? Py_True : Py_False);
}

static PyObject *
cpu_cells(Screen *self, PyObject *args) {
    int y, x = -1;
    if (!PyArg_ParseTuple(args, "i|i", &y, &x)) return NULL;
    if (y >= (int)self->lines) {
        PyErr_SetString(PyExc_IndexError, "y out of bounds");
        return NULL;
    }
    CPUCell *cells;
    if (y >= 0) cells = linebuf_cpu_cells_for_line(self->linebuf, y);
    else {
        Line *l = self->linebuf == self->main_linebuf ? checked_range_line(self, y) : NULL;
        if (!l) {
            PyErr_SetString(PyExc_IndexError, "y out of bounds");
            return NULL;
        }
        cells = l->cpu_cells;
    }
    if (x > -1) {
        if (x >= (int)self->columns) {
            PyErr_SetString(PyExc_IndexError, "x out of bounds");
            return NULL;
        }
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

static PyObject *
cell_style_idx(Screen *self, PyObject *args) {
    int y;
    unsigned int x;
    if (!PyArg_ParseTuple(args, "iI", &y, &x)) return NULL;
    if (y >= (int)self->lines || x >= self->columns) {
        PyErr_SetString(PyExc_IndexError, "out of bounds");
        return NULL;
    }
    CPUCell *cells;
    if (y >= 0) cells = linebuf_cpu_cells_for_line(self->linebuf, y);
    else {
        Line *l = self->linebuf == self->main_linebuf ? checked_range_line(self, y) : NULL;
        if (!l) {
            PyErr_SetString(PyExc_IndexError, "y out of bounds");
            return NULL;
        }
        cells = l->cpu_cells;
    }
    return PyLong_FromUnsignedLong(cells[x].style_idx);
}

static PyObject *
style_table_info(Screen *self, PyObject *a UNUSED) {
    return Py_BuildValue(
        "{sI sI sI sK sO}",
        "count",
        self->style_table->count,
        "max_count",
        style_table_max_count(self->style_table),
        "generation",
        self->style_table->generation,
        "gc_count",
        (unsigned long long)style_table_gc_count(self->style_table),
        "degraded",
        style_table_is_degraded(self->style_table) ? Py_True : Py_False);
}

static PyObject *
test_gc_style_table(Screen *self, PyObject *args) {
    unsigned int quantize_bits = 0;
    if (!PyArg_ParseTuple(args, "|I", &quantize_bits)) return NULL;
    if (quantize_bits > 7) {
        PyErr_SetString(PyExc_ValueError, "quantize_bits must be less than 8");
        return NULL;
    }
    if (!garbage_collect_style_table(self, quantize_bits, false)) return PyErr_NoMemory();
    Py_RETURN_NONE;
}

static PyObject *
test_set_style_table_limit(Screen *self, PyObject *val) {
    if (!PyLong_Check(val)) {
        PyErr_SetString(PyExc_TypeError, "limit must be an int");
        return NULL;
    }
    unsigned long limit = PyLong_AsUnsignedLong(val);
    if (PyErr_Occurred()) return NULL;
    style_table_set_max_count(self->style_table, limit > UINT32_MAX ? UINT32_MAX : (uint32_t)limit);
    Py_RETURN_NONE;
}

static PyObject *
test_bidi_line_record(Screen *self, PyObject *val) {
    unsigned long y = PyLong_AsUnsignedLong(val);
    if (PyErr_Occurred()) return NULL;
    if (y >= self->lines) {
        PyErr_SetString(PyExc_IndexError, "line out of range");
        return NULL;
    }
    LineAttrs a = self->linebuf->line_attrs[y];
    // A record kept by a line without text is not used, see line_has_bidi_record(). It is not dropped here, so that reading a
    // line before a write to it does not do the write's work.
    Line line;
    linebuf_init_line_at(self->linebuf, y, &line);
    if (a.bidi_stamp != BIDI_STAMP_NONE && line_is_empty(&line)) line_attrs_set_bidi(&a, (LineAttrs){0});
    return Py_BuildValue("iOO", (int)a.bidi_stamp, a.bidi_rtl ? Py_True : Py_False, a.bidi_auto ? Py_True : Py_False);
}

// The record of range line y as a serializer reads it, see line_bidi_record_for_ansi(), and whether the line continues the one
// above it
static PyObject *
test_bidi_range_line_record(Screen *self, PyObject *val) {
    const long y = PyLong_AsLong(val);
    if (PyErr_Occurred()) return NULL;
    if (y < -(long)self->historybuf->count || y >= (long)self->lines) {
        PyErr_SetString(PyExc_IndexError, "line out of range");
        return NULL;
    }
    Line line = {.xnum = self->columns, .text_cache = self->text_cache};
    range_line(self, (int)y, &line);
    const LineAttrs a = {.val = line_bidi_record_for_ansi(&line)};
    return Py_BuildValue(
        "(iOO)O",
        (int)a.bidi_stamp,
        a.bidi_rtl ? Py_True : Py_False,
        a.bidi_auto ? Py_True : Py_False,
        range_line_is_continued(self, (int)y) ? Py_True : Py_False);
}

static PyObject *
test_writes_are_recorded(Screen *self, PyObject *args UNUSED) {
    return PyBool_FromLong(self->bidi_records_writes);
}

static PyObject *
test_bidi_may_reorder(Screen *self, PyObject *val) {
    unsigned long y = PyLong_AsUnsignedLong(val);
    if (PyErr_Occurred()) return NULL;
    if (y >= self->lines) {
        PyErr_SetString(PyExc_IndexError, "line out of range");
        return NULL;
    }
    return Py_NewRef(self->linebuf->line_attrs[y].bidi_may_reorder ? Py_True : Py_False);
}

static PyObject *
test_bidi_v2l(Screen *self, PyObject *val) {
    const unsigned long r = PyLong_AsUnsignedLong(val);
    if (PyErr_Occurred()) return NULL;
    const BidiMaps *b = self->bidi_maps;
    // A row shaped at its levels has a map, the identity when they leave it in logical order
    if (!screen_bidi_maps_usable(self) || r >= b->rows || !b->has_levels[r]) Py_RETURN_NONE;
    PyObject *ans = PyTuple_New(b->cols);
    if (!ans) return NULL;
    for (index_type x = 0; x < b->cols; x++) PyTuple_SET_ITEM(ans, x, PyLong_FromUnsignedLong(bidi_logical_x(b, r, x)));
    return ans;
}

// The level each cell of a render row, or of the pre-edit overlay line, was last rendered at, None for a row without a line
static PyObject *
test_render_levels(Screen *self, PyObject *args) {
    unsigned int render_row;
    int overlay = 0;
    if (!PyArg_ParseTuple(args, "I|p", &render_row, &overlay)) return NULL;
    Line line = {.text_cache = self->text_cache};
    const RenderCell *rc = self->overlay_line.render_cells;
    if (!overlay) {
        index_type lnum;
        bool is_history;
        const Line *l = render_row < render_lines_for_screen(self)
                            ? render_line_for_virtual_y(self, (int)render_row - pixel_scroll_enabled(self), &line, &lnum, &is_history)
                            : NULL;
        if (!l) Py_RETURN_NONE;
        rc = l->render_cells;
    }
    PyObject *ans = PyBytes_FromStringAndSize(NULL, self->columns);
    if (!ans) return NULL;
    for (index_type x = 0; x < self->columns; x++) PyBytes_AS_STRING(ans)[x] = (char)rc[x].level;
    return ans;
}

static PyObject *
test_bidi_resolved(Screen *self, PyObject *a UNUSED) {
    if (!screen_bidi_maps_usable(self)) Py_RETURN_NONE;
    return PyLong_FromUnsignedLong(self->bidi_maps->resolved);
}

static PyObject *
test_bidi_walk_matches_full(Screen *self, PyObject *a UNUSED) {
    return PyBool_FromLong(bidi_walk_matches_full(self));
}

static PyObject *
test_bidi_walk_reused(Screen *self, PyObject *a UNUSED) {
    return PyBool_FromLong(screen_bidi_maps_usable(self) && self->bidi_maps->last_walk_reused);
}

// Uploads repeat frames without a GPU, with the font group of the given size and dpi, returning the cell data of the last
static PyObject *
test_update_cell_data(Screen *self, PyObject *args) {
    double font_sz_in_pts, dpi_x, dpi_y;
    unsigned int repeat = 1;
    if (!PyArg_ParseTuple(args, "ddd|I", &font_sz_in_pts, &dpi_x, &dpi_y, &repeat)) return NULL;
    FONTS_DATA_HANDLE fonts_data = load_fonts_data(font_sz_in_pts, dpi_x, dpi_y);
    screen_prepare_smooth_scroll_render(self); // mimic what the renderer does
    PyObject *ans = PyBytes_FromStringAndSize(
        NULL, (Py_ssize_t)(sizeof(CellGPUData) * (render_lines_for_screen(self) * self->columns + self->smooth_scroll_render.num_strip_cells)));
    if (!ans) return NULL;
    memset(PyBytes_AS_STRING(ans), 0, PyBytes_GET_SIZE(ans));
    for (unsigned int i = 0; i < repeat; i++) screen_update_cell_data(self, PyBytes_AS_STRING(ans), fonts_data, false);
    return ans;
}

static PyObject *
test_bidi_bracket_limit(Screen *self UNUSED, PyObject *a UNUSED) {
    return Py_BuildValue("Ns", PyBool_FromLong(bidi_n0_walk_is_slow()), fribidi_version_info);
}

// The logical cell and half of a click on the visual column x of screen row y, as the mouse code maps it
static PyObject *
test_bidi_logical_click(Screen *self, PyObject *args) {
    index_type x, y;
    int in_left_half;
    if (!PyArg_ParseTuple(args, "IIp", &x, &y, &in_left_half)) return NULL;
    bool left = in_left_half;
    screen_bidi_logical_click(self, &x, y, &left);
    return Py_BuildValue("IO", x, left ? Py_True : Py_False);
}

static PyObject *
test_hyperlink_under_mouse(Screen *self, PyObject *a UNUSED) {
    return Py_BuildValue("II", self->current_hyperlink_under_mouse.x, self->current_hyperlink_under_mouse.y);
}

// The drawn column of the cursor of the given shape, or of the pre-edit cursor while one is active, and the IME anchor column
static PyObject *
test_cursor_x(Screen *self, PyObject *args) {
    int shape = CURSOR_BLOCK;
    if (!PyArg_ParseTuple(args, "|i", &shape)) return NULL;
    const Cursor *c = self->paused_rendering.expires_at ? &self->paused_rendering.cursor : self->cursor;
    const bool overlay = screen_is_overlay_active(self);
    return Py_BuildValue(
        "II",
        screen_cursor_drawn_x(self, overlay ? self->overlay_line.cursor_x : c->x, overlay ? self->overlay_line.ynum : c->y, shape),
        screen_ime_anchor_x(self));
}

static PyObject *
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
    METHODB(test_verify_styles, METH_NOARGS),
    METHODB(cell_style_idx, METH_VARARGS),
    METHODB(style_table_info, METH_NOARGS),
    METHODB(test_set_style_table_limit, METH_O),
    METHODB(test_bidi_line_record, METH_O),
    METHODB(test_bidi_range_line_record, METH_O),
    METHODB(test_bidi_may_reorder, METH_O),
    METHODB(test_writes_are_recorded, METH_NOARGS),
    METHODB(test_bidi_v2l, METH_O),
    METHODB(test_render_levels, METH_VARARGS),
    METHODB(test_bidi_resolved, METH_NOARGS),
    METHODB(test_bidi_walk_matches_full, METH_NOARGS),
    METHODB(test_bidi_walk_reused, METH_NOARGS),
    METHODB(test_update_cell_data, METH_VARARGS),
    METHODB(test_bidi_bracket_limit, METH_NOARGS),
    METHODB(test_bidi_logical_click, METH_VARARGS),
    METHODB(test_hyperlink_under_mouse, METH_NOARGS),
    METHODB(test_cursor_x, METH_VARARGS),
    METHODB(test_gc_style_table, METH_VARARGS),
    METHODB(test_draw_overlay_line, METH_VARARGS),
    METHODB(test_update_overlay_text, METH_VARARGS),
    METHODB(restore_scrollback, METH_O),
    METHODB(cursor_prompt_line, METH_NOARGS),
    MND(overlay_line_start, METH_NOARGS) MND(line_edge_colors, METH_NOARGS) MND(ime_text_around_cursor, METH_NOARGS) MND(line, METH_O)
        MND(dump_lines_with_attrs, METH_VARARGS) MND(cpu_cells, METH_VARARGS)
            MND(cursor_at_prompt, METH_NOARGS){"visual_line", (PyCFunction)pyvisual_line, METH_VARARGS, ""},
    MND(current_url_text, METH_NOARGS) MND(draw, METH_O) MND(apply_sgr, METH_O) MND(cursor_position, METH_VARARGS) MND(erase_last_command, METH_NOARGS)
        MND(set_window_char, METH_VARARGS) MND(set_progress, METH_VARARGS) MND(set_mode, METH_VARARGS) MND(reset_mode, METH_VARARGS) MND(reset, METH_VARARGS)
            MND(reset_dirty, METH_NOARGS) MND(is_using_alternate_linebuf, METH_NOARGS) MND(is_main_linebuf, METH_NOARGS) MND(cursor_move, METH_VARARGS)
                MND(erase_in_line, METH_VARARGS) MND(erase_in_display, METH_VARARGS) MND(clear_scrollback, METH_NOARGS)
                    MND(scroll_until_cursor_prompt, METH_VARARGS) MND(hyperlinks_as_set, METH_NOARGS) MND(garbage_collect_hyperlink_pool, METH_NOARGS)
                        MND(garbage_collect_text_cache, METH_NOARGS) MND(text_cache_count, METH_NOARGS) MND(hyperlink_for_id, METH_O)
                            MND(reverse_scroll, METH_VARARGS) MND(scroll_prompt_to_bottom, METH_NOARGS) METHOD(current_char_width, METH_NOARGS)
                                MND(insert_lines, METH_VARARGS)
                                    MND(delete_lines, METH_VARARGS){"insert_characters", (PyCFunction)py_insert_characters, METH_O, ""},
    MND(delete_characters, METH_VARARGS) MND(erase_characters, METH_VARARGS) MND(current_pointer_shape, METH_NOARGS) MND(change_pointer_shape, METH_VARARGS)
        MND(cursor_up, METH_VARARGS) MND(cursor_up1, METH_VARARGS) MND(cursor_down, METH_VARARGS) MND(cursor_down1, METH_VARARGS)
            MND(cursor_forward, METH_VARARGS){"index", (PyCFunction)xxx_index, METH_VARARGS, ""},
    {"has_selection", (PyCFunction)has_selection, METH_VARARGS, ""},
    MND(as_text, METH_VARARGS) MND(as_text_non_visual, METH_VARARGS) MND(as_text_for_history_buf, METH_VARARGS) MND(as_text_alternate, METH_VARARGS)
        MND(cmd_output, METH_VARARGS) MND(tab, METH_NOARGS) MND(backspace, METH_NOARGS) MND(linefeed, METH_NOARGS) MND(carriage_return, METH_NOARGS)
            MND(set_tab_stop, METH_NOARGS) MND(clear_tab_stop, METH_VARARGS) MND(reset_tab_stops, METH_NOARGS) MND(start_selection, METH_VARARGS)
                MND(update_selection, METH_VARARGS){"clear_selection", (PyCFunction)clear_selection_, METH_NOARGS, ""},
    MND(reverse_index, METH_NOARGS) MND(mark_as_dirty, METH_NOARGS) MND(reload_all_gpu_data, METH_NOARGS) MND(resize, METH_VARARGS)
        MND(ignore_bells_for, METH_VARARGS) MND(set_margins, METH_VARARGS) MND(detect_url, METH_VARARGS) MND(rescale_images, METH_NOARGS)
            MND(current_key_encoding_flags, METH_NOARGS) MND(text_for_selection, METH_VARARGS) MND(text_for_marked_url, METH_VARARGS)
                MND(is_rectangle_select, METH_NOARGS) MND(scroll, METH_VARARGS) MND(scroll_to_absolute, METH_O) MND(fractional_scroll, METH_O)
                    MND(scroll_to_prompt, METH_VARARGS) MND(set_last_visited_prompt, METH_VARARGS) MND(send_escape_code_to_child, METH_VARARGS)
                        MND(pause_rendering, METH_VARARGS) MND(smooth_scroll_define, METH_VARARGS) MND(smooth_scroll, METH_VARARGS)
                            MND(smooth_scroll_remove, METH_VARARGS) MND(smooth_scroll_regions, METH_NOARGS) MND(smooth_scroll_overflow, METH_VARARGS)
                                MND(test_text_of_line_for_cursor, METH_VARARGS) MND(hyperlink_at, METH_VARARGS) MND(toggle_alt_screen, METH_NOARGS)
                                    MND(reset_callbacks, METH_NOARGS) MND(paste, METH_O) MND(paste_bytes, METH_O) MND(focus_changed, METH_O)
                                        MND(has_focus, METH_NOARGS) MND(has_activity_since_last_focus, METH_NOARGS) MND(copy_colors_from, METH_O)
                                            MND(set_marker, METH_VARARGS) MND(marked_cells, METH_NOARGS) MND(scroll_to_next_mark, METH_VARARGS)
                                                MND(update_only_line_graphics_data, METH_NOARGS) MND(bell, METH_NOARGS) MND(current_selections, METH_VARARGS)
                                                    MND(update_graphics_layers, METH_NOARGS) MND(rendered_scroll_state, METH_NOARGS)
                                                        MND(scrollbar_geometry, METH_NOARGS) MND(has_scrollbar, METH_O) MND(is_selection_dirty, METH_NOARGS){
                                                            "select_graphic_rendition", (PyCFunction)_select_graphic_rendition, METH_VARARGS, ""},

    {NULL} /* Sentinel */
};

static PyGetSetDef getsetters[] = {
    GETSET(in_bracketed_paste_mode) GETSET(color_preference_notification) GETSET(auto_repeat_enabled) GETSET(focus_tracking_enabled)
        GETSET(in_band_resize_notification) GETSET(paste_events) GETSET(detailed_mouse_events) GETSET(cursor_visible) GETSET(cursor_key_mode)
            GETSET(disable_ligatures) GETSET(render_unfocused_cursor){NULL} /* Sentinel */
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
    {"track_activity", T_BOOL, offsetof(Screen, track_activity), 0, "track_activity"},
    {"cursor", T_OBJECT_EX, offsetof(Screen, cursor), READONLY, "cursor"},
    {"vt_parser", T_OBJECT_EX, offsetof(Screen, vt_parser), READONLY, "vt_parser"},
    {"last_reported_cwd", T_OBJECT, offsetof(Screen, last_reported_cwd), READONLY, "last_reported_cwd"},
    {"grman", T_OBJECT_EX, offsetof(Screen, grman), READONLY, "grman"},
    {"color_profile", T_OBJECT_EX, offsetof(Screen, color_profile), READONLY, "color_profile"},
    {"linebuf", T_OBJECT_EX, offsetof(Screen, linebuf), READONLY, "linebuf"},
    {"main_linebuf", T_OBJECT_EX, offsetof(Screen, main_linebuf), READONLY, "main_linebuf"},
    {"historybuf", T_OBJECT_EX, offsetof(Screen, historybuf), READONLY, "historybuf"},
    {"command_running", T_BOOL, offsetof(Screen, command_state.running), READONLY, "command_running"},
    {"command_started_at", T_LONGLONG, offsetof(Screen, command_state.started_at), READONLY, "command_started_at"},
    {"command_finished_at", T_LONGLONG, offsetof(Screen, command_state.finished_at), READONLY, "command_finished_at"},
    {"alternate_screen_entered_at", T_LONGLONG, offsetof(Screen, alternate_screen.entered_at), READONLY, "alternate_screen_entered_at"},
    {"alternate_screen_exited_at", T_LONGLONG, offsetof(Screen, alternate_screen.exited_at), READONLY, "alternate_screen_exited_at"},
    {"scrolled_by", T_UINT, offsetof(Screen, scrolled_by), READONLY, "scrolled_by"},
    {"pixel_scroll_offset_y", T_UINT, offsetof(Screen, pixel_scroll_offset_y), READONLY, "pixel_scroll_offset_y"},
    {"lines", T_UINT, offsetof(Screen, lines), READONLY, "lines"},
    {"columns", T_UINT, offsetof(Screen, columns), READONLY, "columns"},
    {"margin_top", T_UINT, offsetof(Screen, margin_top), READONLY, "margin_top"},
    {"margin_bottom", T_UINT, offsetof(Screen, margin_bottom), READONLY, "margin_bottom"},
    {NULL}};

PyTypeObject Screen_Type = {
    PyVarObject_HEAD_INIT(NULL, 0).tp_name = "fast_data_types.Screen",
    .tp_basicsize = sizeof(Screen),
    .tp_dealloc = (destructor)dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Screen",
    .tp_methods = methods,
    .tp_members = members,
    .tp_new = new_screen_object,
    .tp_getset = getsetters,
};

static PyObject *
test_set_history_reuse(PyObject *self UNUSED, PyObject *val) {
    history_reuse_disabled_for_tests = !PyObject_IsTrue(val);
    Py_RETURN_NONE;
}

static PyObject *
test_set_batched_non_ascii_draw(PyObject *self UNUSED, PyObject *val) {
    batched_non_ascii_draw_disabled_for_tests = !PyObject_IsTrue(val);
    Py_RETURN_NONE;
}

static PyMethodDef module_methods[] = {
    {"is_emoji_presentation_base", (PyCFunction)screen_is_emoji_presentation_base, METH_O, ""},
    {"truncate_point_for_length", (PyCFunction)screen_truncate_point_for_length, METH_VARARGS, ""},
    {"test_ch_and_idx", test_ch_and_idx, METH_O, ""},
    {"test_set_history_reuse", test_set_history_reuse, METH_O, ""},
    {"test_set_batched_non_ascii_draw", test_set_batched_non_ascii_draw, METH_O, ""},
    {NULL} /* Sentinel */
};

INIT_TYPE(Screen)
// }}}
