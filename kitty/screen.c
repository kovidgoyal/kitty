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

#include "state.h"
#include "fonts.h"
#include "lineops.h"
#include "screen.h"
#include <structmember.h>
#include <limits.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include "unicode-data.h"
#include "modes.h"
#include "wcwidth-std.h"
#include "control-codes.h"
#include "charsets.h"

static const ScreenModes empty_modes = {0, .mDECAWM=true, .mDECTCEM=true, .mDECARM=true};
static Selection EMPTY_SELECTION = {0};
typedef struct {
    unsigned int x; int y;
} FullSelectionBoundary;

// Constructor/destructor {{{

static inline void
init_tabstops(bool *tabstops, index_type count) {
    // In terminfo we specify the number of initial tabstops (it) as 8
    for (unsigned int t=0; t < count; t++) {
        tabstops[t] = t % 8 == 0 ? true : false;
    }
}

static inline bool
init_overlay_line(Screen *self, index_type columns) {
    PyMem_Free(self->overlay_line.cpu_cells);
    PyMem_Free(self->overlay_line.gpu_cells);
    self->overlay_line.cpu_cells = PyMem_Calloc(columns, sizeof(CPUCell));
    self->overlay_line.gpu_cells = PyMem_Calloc(columns, sizeof(GPUCell));
    if (!self->overlay_line.cpu_cells || !self->overlay_line.gpu_cells) {
        PyErr_NoMemory(); return false;
    }
    self->overlay_line.is_active = false;
    self->overlay_line.xnum = 0;
    self->overlay_line.ynum = 0;
    self->overlay_line.xstart = 0;
    return true;
}

#define RESET_CHARSETS \
        self->g0_charset = translation_table(0); \
        self->g1_charset = self->g0_charset; \
        self->g_charset = self->g0_charset; \
        self->current_charset = 0; \
        self->utf8_state = 0; \
        self->utf8_codepoint = 0; \
        self->use_latin1 = false;
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
        if ((ret = pthread_mutex_init(&self->read_buf_lock, NULL)) != 0) {
            Py_CLEAR(self); PyErr_Format(PyExc_RuntimeError, "Failed to create Screen read_buf_lock mutex: %s", strerror(ret));
            return NULL;
        }
        if ((ret = pthread_mutex_init(&self->write_buf_lock, NULL)) != 0) {
            Py_CLEAR(self); PyErr_Format(PyExc_RuntimeError, "Failed to create Screen write_buf_lock mutex: %s", strerror(ret));
            return NULL;
        }
        self->cell_size.width = cell_width; self->cell_size.height = cell_height;
        self->columns = columns; self->lines = lines;
        self->write_buf = PyMem_RawMalloc(BUFSIZ);
        self->window_id = window_id;
        if (self->write_buf == NULL) { Py_CLEAR(self); return PyErr_NoMemory(); }
        self->write_buf_sz = BUFSIZ;
        self->modes = empty_modes;
        self->is_dirty = true;
        self->scroll_changed = false;
        self->margin_top = 0; self->margin_bottom = self->lines - 1;
        self->history_line_added_count = 0;
        RESET_CHARSETS;
        self->callbacks = callbacks; Py_INCREF(callbacks);
        self->test_child = test_child; Py_INCREF(test_child);
        self->cursor = alloc_cursor();
        self->color_profile = alloc_color_profile();
        self->main_linebuf = alloc_linebuf(lines, columns); self->alt_linebuf = alloc_linebuf(lines, columns);
        self->linebuf = self->main_linebuf;
        self->historybuf = alloc_historybuf(MAX(scrollback, lines), columns, OPT(scrollback_pager_history_size));
        self->main_grman = grman_alloc();
        self->alt_grman = grman_alloc();
        self->grman = self->main_grman;
        self->pending_mode.wait_time = 2.0;
        self->main_tabstops = PyMem_Calloc(2 * self->columns, sizeof(bool));
        if (self->cursor == NULL || self->main_linebuf == NULL || self->alt_linebuf == NULL || self->main_tabstops == NULL || self->historybuf == NULL || self->main_grman == NULL || self->alt_grman == NULL || self->color_profile == NULL) {
            Py_CLEAR(self); return NULL;
        }
        self->alt_tabstops = self->main_tabstops + self->columns * sizeof(bool);
        self->tabstops = self->main_tabstops;
        init_tabstops(self->main_tabstops, self->columns);
        init_tabstops(self->alt_tabstops, self->columns);
        if (!init_overlay_line(self, self->columns)) { Py_CLEAR(self); return NULL; }
    }
    return (PyObject*) self;
}

static void deactivate_overlay_line(Screen *self);
static inline Line* range_line_(Screen *self, int y);

void
screen_reset(Screen *self) {
    if (self->linebuf == self->alt_linebuf) screen_toggle_screen_buffer(self);
    if (self->overlay_line.is_active) deactivate_overlay_line(self);
    linebuf_clear(self->linebuf, BLANK_CHAR);
    historybuf_clear(self->historybuf);
    grman_clear(self->grman, false, self->cell_size);
    self->modes = empty_modes;
#define R(name) self->color_profile->overridden.name = 0
    R(default_fg); R(default_bg); R(cursor_color); R(highlight_fg); R(highlight_bg);
#undef R
    RESET_CHARSETS;
    self->margin_top = 0; self->margin_bottom = self->lines - 1;
    screen_normal_keypad_mode(self);
    init_tabstops(self->main_tabstops, self->columns);
    init_tabstops(self->alt_tabstops, self->columns);
    cursor_reset(self->cursor);
    self->is_dirty = true;
    self->selection = EMPTY_SELECTION;
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

static inline HistoryBuf*
realloc_hb(HistoryBuf *old, unsigned int lines, unsigned int columns) {
    HistoryBuf *ans = alloc_historybuf(lines, columns, 0);
    if (ans == NULL) { PyErr_NoMemory(); return NULL; }
    ans->pagerhist = old->pagerhist; old->pagerhist = NULL;
    historybuf_rewrap(old, ans);
    return ans;
}

static inline LineBuf*
realloc_lb(LineBuf *old, unsigned int lines, unsigned int columns, index_type *nclb, index_type *ncla, HistoryBuf *hb, index_type *x, index_type *y) {
    LineBuf *ans = alloc_linebuf(lines, columns);
    if (ans == NULL) { PyErr_NoMemory(); return NULL; }
    linebuf_rewrap(old, ans, nclb, ncla, hb, x, y);
    return ans;
}

static bool
screen_resize(Screen *self, unsigned int lines, unsigned int columns) {
    if (self->overlay_line.is_active) deactivate_overlay_line(self);
    lines = MAX(1, lines); columns = MAX(1, columns);

    bool is_main = self->linebuf == self->main_linebuf;
    index_type num_content_lines_before, num_content_lines_after, num_content_lines;
    unsigned int cursor_x = 0, cursor_y = 0;
    bool cursor_is_beyond_content = false;
#define setup_cursor() { \
        cursor_x = x; cursor_y = y; \
        cursor_is_beyond_content = num_content_lines_before > 0 && self->cursor->y >= num_content_lines_before; \
        num_content_lines = num_content_lines_after; \
}
    // Resize overlay line
    if (!init_overlay_line(self, columns)) return false;

    // Resize main linebuf
    HistoryBuf *nh = realloc_hb(self->historybuf, self->historybuf->ynum, columns);
    if (nh == NULL) return false;
    Py_CLEAR(self->historybuf); self->historybuf = nh;
    index_type x = self->cursor->x, y = self->cursor->y;
    LineBuf *n = realloc_lb(self->main_linebuf, lines, columns, &num_content_lines_before, &num_content_lines_after, self->historybuf, &x, &y);
    if (n == NULL) return false;
    Py_CLEAR(self->main_linebuf); self->main_linebuf = n;
    if (is_main) setup_cursor();
    grman_resize(self->main_grman, self->lines, lines, self->columns, columns);

    // Resize alt linebuf
    x = self->cursor->x, y = self->cursor->y;
    n = realloc_lb(self->alt_linebuf, lines, columns, &num_content_lines_before, &num_content_lines_after, NULL, &x, &y);
    if (n == NULL) return false;
    Py_CLEAR(self->alt_linebuf); self->alt_linebuf = n;
    if (!is_main) setup_cursor();
    grman_resize(self->alt_grman, self->lines, lines, self->columns, columns);
#undef setup_cursor

    self->linebuf = is_main ? self->main_linebuf : self->alt_linebuf;
    /* printf("\nold_size: (%u, %u) new_size: (%u, %u)\n", self->columns, self->lines, columns, lines); */
    self->lines = lines; self->columns = columns;
    self->margin_top = 0; self->margin_bottom = self->lines - 1;

    PyMem_Free(self->main_tabstops);
    self->main_tabstops = PyMem_Calloc(2*self->columns, sizeof(bool));
    if (self->main_tabstops == NULL) { PyErr_NoMemory(); return false; }
    self->alt_tabstops = self->main_tabstops + self->columns * sizeof(bool);
    self->tabstops = self->main_tabstops;
    init_tabstops(self->main_tabstops, self->columns);
    init_tabstops(self->alt_tabstops, self->columns);
    self->is_dirty = true;
    self->selection = EMPTY_SELECTION;
    self->url_range = EMPTY_SELECTION;
    self->selection_updated_once = false;
    /* printf("old_cursor: (%u, %u) new_cursor: (%u, %u) beyond_content: %d\n", self->cursor->x, self->cursor->y, cursor_x, cursor_y, cursor_is_beyond_content); */
    self->cursor->x = MIN(cursor_x, self->columns - 1);
    self->cursor->y = MIN(cursor_y, self->lines - 1);
    if (cursor_is_beyond_content) {
        self->cursor->y = num_content_lines;
        if (self->cursor->y >= self->lines) { self->cursor->y = self->lines - 1; screen_index(self); }
    }
    return true;
}

void
screen_rescale_images(Screen *self) {
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
    pthread_mutex_destroy(&self->read_buf_lock);
    pthread_mutex_destroy(&self->write_buf_lock);
    Py_CLEAR(self->main_grman);
    Py_CLEAR(self->alt_grman);
    PyMem_RawFree(self->write_buf);
    Py_CLEAR(self->callbacks);
    Py_CLEAR(self->test_child);
    Py_CLEAR(self->cursor);
    Py_CLEAR(self->main_linebuf);
    Py_CLEAR(self->alt_linebuf);
    Py_CLEAR(self->historybuf);
    Py_CLEAR(self->color_profile);
    PyMem_Free(self->overlay_line.cpu_cells);
    PyMem_Free(self->overlay_line.gpu_cells);
    PyMem_Free(self->main_tabstops);
    free(self->pending_mode.buf);
    Py_TYPE(self)->tp_free((PyObject*)self);
} // }}}

// Draw text {{{

void
screen_change_charset(Screen *self, uint32_t which) {
    switch(which) {
        case 0:
            self->current_charset = 0;
            self->g_charset = self->g0_charset;
            break;
        case 1:
            self->current_charset = 1;
            self->g_charset = self->g1_charset;
            break;
    }
}

void
screen_designate_charset(Screen *self, uint32_t which, uint32_t as) {
    switch(which) {
        case 0:
            self->g0_charset = translation_table(as);
            if (self->current_charset == 0) self->g_charset = self->g0_charset;
            break;
        case 1:
            self->g1_charset = translation_table(as);
            if (self->current_charset == 1) self->g_charset = self->g1_charset;
            break;
    }
}

static inline void
move_widened_char(Screen *self, CPUCell* cpu_cell, GPUCell *gpu_cell, index_type xpos, index_type ypos) {
    self->cursor->x = xpos; self->cursor->y = ypos;
    CPUCell src_cpu = *cpu_cell, *dest_cpu;
    GPUCell src_gpu = *gpu_cell, *dest_gpu;
    line_clear_text(self->linebuf->line, xpos, 1, BLANK_CHAR);

    if (self->modes.mDECAWM) {  // overflow goes onto next line
        screen_carriage_return(self);
        screen_linefeed(self);
        self->linebuf->line_attrs[self->cursor->y] |= CONTINUED_MASK;
        linebuf_init_line(self->linebuf, self->cursor->y);
        dest_cpu = self->linebuf->line->cpu_cells;
        dest_gpu = self->linebuf->line->gpu_cells;
        self->cursor->x = MIN(2, self->columns);
        linebuf_mark_line_dirty(self->linebuf, self->cursor->y);
    } else {
        dest_cpu = cpu_cell - 1;
        dest_gpu = gpu_cell - 1;
        self->cursor->x = self->columns;
    }
    *dest_cpu = src_cpu;
    *dest_gpu = src_gpu;
}

static inline bool
selection_has_screen_line(Selection *s, int y) {
    if (s->start_scrolled_by == s->end_scrolled_by && s->start_x == s->end_x && s->start_y == s->end_y) return false;
    int top = (int)s->start_y - s->start_scrolled_by;
    int bottom = (int)s->end_y - s->end_scrolled_by;
    return top <= y && y <= bottom;
}

static inline void
draw_combining_char(Screen *self, char_type ch) {
    bool has_prev_char = false;
    index_type xpos = 0, ypos = 0;
    if (self->cursor->x > 0) {
        ypos = self->cursor->y;
        linebuf_init_line(self->linebuf, ypos);
        xpos = self->cursor->x - 1;
        has_prev_char = true;
    } else if (self->cursor->y > 0) {
        ypos = self->cursor->y - 1;
        linebuf_init_line(self->linebuf, ypos);
        xpos = self->columns - 1;
        has_prev_char = true;
    }
    if (has_prev_char) {
        line_add_combining_char(self->linebuf->line, ch, xpos);
        self->is_dirty = true;
        if (selection_has_screen_line(&self->selection, ypos)) self->selection = EMPTY_SELECTION;
        linebuf_mark_line_dirty(self->linebuf, ypos);
        if (ch == 0xfe0f) {  // emoji presentation variation marker makes default text presentation emoji (narrow emoji) into wide emoji
            CPUCell *cpu_cell = self->linebuf->line->cpu_cells + xpos;
            GPUCell *gpu_cell = self->linebuf->line->gpu_cells + xpos;
            if ((gpu_cell->attrs & WIDTH_MASK) != 2 && cpu_cell->cc_idx[0] == VS16 && is_emoji_presentation_base(cpu_cell->ch)) {
                if (self->cursor->x <= self->columns - 1) line_set_char(self->linebuf->line, self->cursor->x, 0, 0, self->cursor, true);
                gpu_cell->attrs = (gpu_cell->attrs & !WIDTH_MASK) | 2;
                if (xpos == self->columns - 1) move_widened_char(self, cpu_cell, gpu_cell, xpos, ypos);
                else self->cursor->x++;
            }
        }
    }
}

void
screen_draw(Screen *self, uint32_t och) {
    if (is_ignored_char(och)) return;
    uint32_t ch = och < 256 ? self->g_charset[och] : och;
    bool is_cc = is_combining_char(ch);
    if (UNLIKELY(is_cc)) {
        draw_combining_char(self, ch);
        return;
    }
    int char_width = wcwidth_std(ch);
    if (UNLIKELY(char_width < 1)) {
        if (char_width == 0) return;
        char_width = 1;
    }
    if (UNLIKELY(self->columns - self->cursor->x < (unsigned int)char_width)) {
        if (self->modes.mDECAWM) {
            screen_carriage_return(self);
            screen_linefeed(self);
            self->linebuf->line_attrs[self->cursor->y] |= CONTINUED_MASK;
        } else {
            self->cursor->x = self->columns - char_width;
        }
    }

    linebuf_init_line(self->linebuf, self->cursor->y);
    if (self->modes.mIRM) {
        line_right_shift(self->linebuf->line, self->cursor->x, char_width);
    }
    line_set_char(self->linebuf->line, self->cursor->x, ch, char_width, self->cursor, false);
    self->cursor->x++;
    if (char_width == 2) {
        line_set_char(self->linebuf->line, self->cursor->x, 0, 0, self->cursor, true);
        self->cursor->x++;
    }
    self->is_dirty = true;
    if (selection_has_screen_line(&self->selection, self->cursor->y)) self->selection = EMPTY_SELECTION;
    linebuf_mark_line_dirty(self->linebuf, self->cursor->y);
}

void
screen_draw_overlay_text(Screen *self, const char *utf8_text) {
    if (self->overlay_line.is_active) deactivate_overlay_line(self);
    if (!utf8_text || !utf8_text[0]) return;
    Line *line = range_line_(self, self->cursor->y);
    if (!line) return;
    line_save_cells(line, 0, self->columns, self->overlay_line.gpu_cells, self->overlay_line.cpu_cells);
    self->overlay_line.is_active = true;
    self->overlay_line.ynum = self->cursor->y;
    self->overlay_line.xstart = self->cursor->x;
    self->overlay_line.xnum = 0;
    uint32_t codepoint = 0, state = UTF8_ACCEPT;
    bool orig_line_wrap_mode = self->modes.mDECAWM;
    self->modes.mDECAWM = false;
    self->cursor->reverse ^= true;
    index_type before;
    while (*utf8_text) {
        switch(decode_utf8(&state, &codepoint, *(utf8_text++))) {
            case UTF8_ACCEPT:
                before = self->cursor->x;
                screen_draw(self, codepoint);
                self->overlay_line.xnum += self->cursor->x - before;
                break;
            case UTF8_REJECT:
                break;
        }
    }
    self->cursor->reverse ^= true;
    self->modes.mDECAWM = orig_line_wrap_mode;
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
    // http://www.vt100.net/docs/vt510-rm/DECALN.html
    screen_cursor_position(self, 1, 1);
    self->margin_top = 0; self->margin_bottom = self->lines - 1;
    for (unsigned int y = 0; y < self->linebuf->ynum; y++) {
        linebuf_init_line(self->linebuf, y);
        line_clear_text(self->linebuf->line, 0, self->linebuf->xnum, 'E');
        linebuf_mark_line_dirty(self->linebuf, y);
    }
}

void
select_graphic_rendition(Screen *self, unsigned int *params, unsigned int count, Region *region_) {
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
                apply_sgr_to_cells(self->linebuf->line->gpu_cells + x, num, params, count);
            }
        } else {
            index_type x, num;
            for (index_type y = region.top; y < MIN(region.bottom + 1, self->lines); y++) {
                if (y == region.top) { x = MIN(region.left, self->columns - 1); num = self->columns - x; }
                else if (y == region.bottom) { x = 0; num = MIN(region.right + 1, self->columns); }
                else { x = 0; num = self->columns; }
                linebuf_init_line(self->linebuf, y);
                apply_sgr_to_cells(self->linebuf->line->gpu_cells + x, num, params, count);
            }
        }
    } else cursor_from_sgr(self->cursor, params, count);
}

static inline void
write_to_test_child(Screen *self, const char *data, size_t sz) {
    PyObject *r = PyObject_CallMethod(self->test_child, "write", "y#", data, sz); if (r == NULL) PyErr_Print(); Py_CLEAR(r);
}

static inline void
write_to_child(Screen *self, const char *data, size_t sz) {
    if (self->window_id) schedule_write_to_child(self->window_id, 1, data, sz);
    if (self->test_child != Py_None) { write_to_test_child(self, data, sz); }
}

void
write_escape_code_to_child(Screen *self, unsigned char which, const char *data) {
    const char *prefix, *suffix = self->modes.eight_bit_controls ? "\x9c" : "\033\\";
    switch(which) {
        case DCS:
            prefix = self->modes.eight_bit_controls ? "\x90" : "\033P";
            break;
        case CSI:
            prefix = self->modes.eight_bit_controls ? "\x9b" : "\033["; suffix = "";
            break;
        case OSC:
            prefix = self->modes.eight_bit_controls ? "\x9d" : "\033]";
            break;
        case PM:
            prefix = self->modes.eight_bit_controls ? "\x9e" : "\033^";
            break;
        case APC:
            prefix = self->modes.eight_bit_controls ? "\x9f" : "\033_";
            break;
        default:
            fatal("Unknown escape code to write: %u", which);
    }
    if (self->window_id) {
        if (suffix[0]) {
            schedule_write_to_child(self->window_id, 3, prefix, strlen(prefix), data, strlen(data), suffix, strlen(suffix));
        } else {
            schedule_write_to_child(self->window_id, 2, prefix, strlen(prefix), data, strlen(data));
        }
    }
    if (self->test_child != Py_None) {
        write_to_test_child(self, prefix, strlen(prefix));
        write_to_test_child(self, data, strlen(data));
        if (suffix[0]) write_to_test_child(self, suffix, strlen(suffix));
    }
}

static inline bool
cursor_within_margins(Screen *self) {
    return self->margin_top <= self->cursor->y && self->cursor->y <= self->margin_bottom;
}

void
screen_handle_graphics_command(Screen *self, const GraphicsCommand *cmd, const uint8_t *payload) {
    unsigned int x = self->cursor->x, y = self->cursor->y;
    const char *response = grman_handle_command(self->grman, cmd, payload, self->cursor, &self->is_dirty, self->cell_size);
    if (response != NULL) write_escape_code_to_child(self, APC, response);
    if (x != self->cursor->x || y != self->cursor->y) {
        bool in_margins = cursor_within_margins(self);
        if (self->cursor->x >= self->columns) { self->cursor->x = 0; self->cursor->y++; }
        if (self->cursor->y > self->margin_bottom) screen_scroll(self, self->cursor->y - self->margin_bottom);
        screen_ensure_bounds(self, false, in_margins);
    }
}
// }}}

// Modes {{{


void
screen_toggle_screen_buffer(Screen *self) {
    bool to_alt = self->linebuf == self->main_linebuf;
    grman_clear(self->alt_grman, true, self->cell_size);  // always clear the alt buffer graphics to free up resources, since it has to be cleared when switching back to it anyway
    if (to_alt) {
        linebuf_clear(self->alt_linebuf, BLANK_CHAR);
        screen_save_cursor(self);
        self->linebuf = self->alt_linebuf;
        self->tabstops = self->alt_tabstops;
        self->grman = self->alt_grman;
        screen_cursor_position(self, 1, 1);
        cursor_reset(self->cursor);
    } else {
        self->linebuf = self->main_linebuf;
        self->tabstops = self->main_tabstops;
        screen_restore_cursor(self);
        self->grman = self->main_grman;
    }
    screen_history_scroll(self, SCROLL_FULL, false);
    self->is_dirty = true;
    self->selection = EMPTY_SELECTION;
}

void screen_normal_keypad_mode(Screen UNUSED *self) {} // Not implemented as this is handled by the GUI
void screen_alternate_keypad_mode(Screen UNUSED *self) {}  // Not implemented as this is handled by the GUI

static inline void
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
        SIMPLE_MODE(EXTENDED_KEYBOARD)
        SIMPLE_MODE(FOCUS_TRACKING)
        MOUSE_MODE(MOUSE_BUTTON_TRACKING, mouse_tracking_mode, BUTTON_MODE)
        MOUSE_MODE(MOUSE_MOTION_TRACKING, mouse_tracking_mode, MOTION_MODE)
        MOUSE_MODE(MOUSE_MOVE_TRACKING, mouse_tracking_mode, ANY_MODE)
        MOUSE_MODE(MOUSE_UTF8_MODE, mouse_tracking_protocol, UTF8_PROTOCOL)
        MOUSE_MODE(MOUSE_SGR_MODE, mouse_tracking_protocol, SGR_PROTOCOL)
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
            // vttest/main.c:303.
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
            self->cursor->blink = val;
            break;
        case ALTERNATE_SCREEN:
            if (val && self->linebuf == self->main_linebuf) screen_toggle_screen_buffer(self);
            else if (!val && self->linebuf != self->main_linebuf) screen_toggle_screen_buffer(self);
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
screen_set_8bit_controls(Screen *self, bool yes) {
    self->modes.eight_bit_controls = yes;
}

// }}}

// Cursor {{{

unsigned long
screen_current_char_width(Screen *self) {
    unsigned long ans = 1;
    if (self->cursor->x < self->columns - 1 && self->cursor->y < self->lines) {
        ans = linebuf_char_width_at(self->linebuf, self->cursor->x, self->cursor->y);
    }
    return ans;
}

bool
screen_is_cursor_visible(Screen *self) {
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
    screen_ensure_bounds(self, true, in_margins);
    if (do_carriage_return) self->cursor->x = 0;
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
    unsigned int x = MAX(column, 1) - 1;
    if (x != self->cursor->x) {
        self->cursor->x = x;
        screen_ensure_bounds(self, false, cursor_within_margins(self));
    }
}

static inline void
index_selection(Screen *self, Selection *s, bool up) {
    if (s->start_scrolled_by == s->end_scrolled_by && s->start_x == s->end_x && s->start_y == s->end_y) return;
    if (up) {
        if (s->start_y == 0) s->start_scrolled_by += 1;
        else s->start_y--;
        if (s->end_y == 0) s->end_scrolled_by += 1;
        else s->end_y--;
    } else {
        if (s->start_y >= self->lines - 1) s->start_scrolled_by -= 1;
        else s->start_y++;
        if (s->end_y >= self->lines - 1) s->end_scrolled_by -= 1;
        else s->end_y++;
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

#define INDEX_UP \
    if (self->overlay_line.is_active) deactivate_overlay_line(self); \
    linebuf_index(self->linebuf, top, bottom); \
    INDEX_GRAPHICS(-1) \
    if (self->linebuf == self->main_linebuf && bottom == self->lines - 1) { \
        /* Only add to history when no page margins have been set */ \
        linebuf_init_line(self->linebuf, bottom); \
        historybuf_add_line(self->historybuf, self->linebuf->line); \
        self->history_line_added_count++; \
    } \
    linebuf_clear_line(self->linebuf, bottom); \
    self->is_dirty = true; \
    index_selection(self, &self->selection, true);

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

#define INDEX_DOWN \
    if (self->overlay_line.is_active) deactivate_overlay_line(self); \
    linebuf_reverse_index(self->linebuf, top, bottom); \
    linebuf_clear_line(self->linebuf, top); \
    INDEX_GRAPHICS(1) \
    self->is_dirty = true; \
    index_selection(self, &self->selection, false);

void
screen_reverse_index(Screen *self) {
    // Move cursor up one line, scrolling screen if needed
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (self->cursor->y == top) {
        INDEX_DOWN;
    } else screen_cursor_up(self, 1, false, -1);
}

void
screen_reverse_scroll(Screen *self, unsigned int count) {
    // Scroll the screen down by count lines, not moving the cursor
    count = MIN(self->lines, count);
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    while (count > 0) {
        count--;
        INDEX_DOWN;
    }
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

#define COPY_CHARSETS(self, sp) \
    sp->utf8_state = self->utf8_state; \
    sp->utf8_codepoint = self->utf8_codepoint; \
    sp->g0_charset = self->g0_charset; \
    sp->g1_charset = self->g1_charset; \
    sp->current_charset = self->current_charset; \
    sp->use_latin1 = self->use_latin1;

void
screen_save_cursor(Screen *self) {
    SavepointBuffer *pts = self->linebuf == self->main_linebuf ? &self->main_savepoints : &self->alt_savepoints;
    Savepoint *sp;
    buffer_push(pts, sp);
    cursor_copy_to(self->cursor, &(sp->cursor));
    sp->mDECOM = self->modes.mDECOM;
    sp->mDECAWM = self->modes.mDECAWM;
    sp->mDECSCNM = self->modes.mDECSCNM;
    COPY_CHARSETS(self, sp);
}

void
screen_save_modes(Screen *self) {
    ScreenModes *m;
    buffer_push(&self->modes_savepoints, m);
    *m = self->modes;
}

void
screen_restore_cursor(Screen *self) {
    SavepointBuffer *pts = self->linebuf == self->main_linebuf ? &self->main_savepoints : &self->alt_savepoints;
    Savepoint *sp;
    buffer_pop(pts, sp);
    if (sp == NULL) {
        screen_cursor_position(self, 1, 1);
        screen_reset_mode(self, DECOM);
        RESET_CHARSETS;
        screen_reset_mode(self, DECSCNM);
    } else {
        COPY_CHARSETS(sp, self);
        self->g_charset = self->current_charset ? self->g1_charset : self->g0_charset;
        set_mode_from_const(self, DECOM, sp->mDECOM);
        set_mode_from_const(self, DECAWM, sp->mDECAWM);
        set_mode_from_const(self, DECSCNM, sp->mDECSCNM);
        cursor_copy_to(&(sp->cursor), self->cursor);
        screen_ensure_bounds(self, false, false);
    }
}

void
screen_restore_modes(Screen *self) {
    const ScreenModes *m;
    buffer_pop(&self->modes_savepoints, m);
    if (m == NULL) m = &empty_modes;
#define S(name) set_mode_from_const(self, name, m->m##name)
    S(DECTCEM); S(DECSCNM); S(DECSCNM); S(DECOM); S(DECAWM); S(DECARM); S(DECCKM);
    S(BRACKETED_PASTE); S(FOCUS_TRACKING); S(EXTENDED_KEYBOARD);
    self->modes.mouse_tracking_mode = m->mouse_tracking_mode;
    self->modes.mouse_tracking_protocol = m->mouse_tracking_protocol;
#undef S
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
        linebuf_init_line(self->linebuf, self->cursor->y);
        if (private) {
            line_clear_text(self->linebuf->line, s, n, BLANK_CHAR);
        } else {
            line_apply_cursor(self->linebuf->line, self->cursor, s, n, true);
        }
        self->is_dirty = true;
        if (selection_has_screen_line(&self->selection, self->cursor->y)) self->selection = EMPTY_SELECTION;
        linebuf_mark_line_dirty(self->linebuf, self->cursor->y);
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
            * ``3`` -- Erase complete display and scrollback buffer as well.
        :param bool private: when ``True`` character attributes are left unchanged
    */
    unsigned int a, b;
    switch(how) {
        case 0:
            a = self->cursor->y + 1; b = self->lines; break;
        case 1:
            a = 0; b = self->cursor->y; break;
        case 2:
        case 3:
            grman_clear(self->grman, how == 3, self->cell_size);
            a = 0; b = self->lines; break;
        default:
            return;
    }
    if (b > a) {
        for (unsigned int i=a; i < b; i++) {
            linebuf_init_line(self->linebuf, i);
            if (private) {
                line_clear_text(self->linebuf->line, 0, self->columns, BLANK_CHAR);
            } else {
                line_apply_cursor(self->linebuf->line, self->cursor, 0, self->columns, true);
            }
            linebuf_mark_line_dirty(self->linebuf, i);
        }
        self->is_dirty = true;
        self->selection = EMPTY_SELECTION;
    }
    if (how != 2) {
        screen_erase_in_line(self, how, private);
    }
    if (how == 3 && self->linebuf == self->main_linebuf) {
        historybuf_clear(self->historybuf);
        if (self->scrolled_by != 0) {
            self->scrolled_by = 0;
            self->scroll_changed = true;
        }
    }
}

void
screen_insert_lines(Screen *self, unsigned int count) {
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (count == 0) count = 1;
    if (top <= self->cursor->y && self->cursor->y <= bottom) {
        linebuf_insert_lines(self->linebuf, count, self->cursor->y, bottom);
        self->is_dirty = true;
        self->selection = EMPTY_SELECTION;
        screen_carriage_return(self);
    }
}

void
screen_scroll_until_cursor(Screen *self) {
    unsigned int num_lines_to_scroll = MIN(self->margin_bottom, self->cursor->y + 1);
    index_type y = self->cursor->y;
    self->cursor->y = self->margin_bottom;
    while (num_lines_to_scroll--) screen_index(self);
    self->cursor->y = y;
}

void
screen_delete_lines(Screen *self, unsigned int count) {
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (count == 0) count = 1;
    if (top <= self->cursor->y && self->cursor->y <= bottom) {
        linebuf_delete_lines(self->linebuf, count, self->cursor->y, bottom);
        self->is_dirty = true;
        self->selection = EMPTY_SELECTION;
        screen_carriage_return(self);
    }
}

void
screen_insert_characters(Screen *self, unsigned int count) {
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (count == 0) count = 1;
    if (top <= self->cursor->y && self->cursor->y <= bottom) {
        unsigned int x = self->cursor->x;
        unsigned int num = MIN(self->columns - x, count);
        linebuf_init_line(self->linebuf, self->cursor->y);
        line_right_shift(self->linebuf->line, x, num);
        line_apply_cursor(self->linebuf->line, self->cursor, x, num, true);
        linebuf_mark_line_dirty(self->linebuf, self->cursor->y);
        self->is_dirty = true;
        if (selection_has_screen_line(&self->selection, self->cursor->y)) self->selection = EMPTY_SELECTION;
    }
}

void
screen_delete_characters(Screen *self, unsigned int count) {
    // Delete characters, later characters are moved left
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (count == 0) count = 1;
    if (top <= self->cursor->y && self->cursor->y <= bottom) {
        unsigned int x = self->cursor->x;
        unsigned int num = MIN(self->columns - x, count);
        linebuf_init_line(self->linebuf, self->cursor->y);
        left_shift_line(self->linebuf->line, x, num);
        line_apply_cursor(self->linebuf->line, self->cursor, self->columns - num, num, true);
        linebuf_mark_line_dirty(self->linebuf, self->cursor->y);
        self->is_dirty = true;
        if (selection_has_screen_line(&self->selection, self->cursor->y)) self->selection = EMPTY_SELECTION;
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
    if (selection_has_screen_line(&self->selection, self->cursor->y)) self->selection = EMPTY_SELECTION;
}

// }}}

// Device control {{{

void
screen_use_latin1(Screen *self, bool on) {
    self->use_latin1 = on; self->utf8_state = 0; self->utf8_codepoint = 0;
    CALLBACK("use_utf8", "O", on ? Py_False : Py_True);
}

bool
screen_invert_colors(Screen *self) {
    bool inverted = false;
    if (self->start_visual_bell_at > 0) {
        if (monotonic() - self->start_visual_bell_at <= OPT(visual_bell_duration)) inverted = true;
        else self->start_visual_bell_at = 0;
    }
    if (self->modes.mDECSCNM) inverted = inverted ? false : true;
    return inverted;
}

void
screen_bell(Screen *self) {
    request_window_attention(self->window_id, OPT(enable_audio_bell));
    if (OPT(visual_bell_duration) > 0.0f) self->start_visual_bell_at = monotonic();
    CALLBACK("on_bell", NULL);
}

void
report_device_attributes(Screen *self, unsigned int mode, char start_modifier) {
    if (mode == 0) {
        switch(start_modifier) {
            case 0:
                write_escape_code_to_child(self, CSI, "?62;c");
                break;
            case '>':
                write_escape_code_to_child(self, CSI, ">1;" xstr(PRIMARY_VERSION) ";" xstr(SECONDARY_VERSION) "c");  // VT-220 + primary version + secondary version
                break;
        }
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
        write_escape_code_to_child(self, CSI, buf);
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
            write_escape_code_to_child(self, CSI, "0n");
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
            if (sz > 0) write_escape_code_to_child(self, CSI, buf);
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
        KNOWN_MODE(EXTENDED_KEYBOARD);
        KNOWN_MODE(FOCUS_TRACKING);
#undef KNOWN_MODE
    }
    int sz = snprintf(buf, sizeof(buf) - 1, "%s%u;%u$y", (private ? "?" : ""), which, ans);
    if (sz > 0) write_escape_code_to_child(self, CSI, buf);
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
            shape = 0; blink = false;
            if (mode > 0) {
                blink = mode % 2;
                shape = (mode < 3) ? CURSOR_BLOCK : (mode < 5) ? CURSOR_UNDERLINE : (mode < 7) ? CURSOR_BEAM : NO_CURSOR_SHAPE;
            }
            if (shape != self->cursor->shape || blink != self->cursor->blink) {
                self->cursor->shape = shape; self->cursor->blink = blink;
            }
            break;
    }
}

void
set_title(Screen *self, PyObject *title) {
    CALLBACK("title_changed", "O", title);
}

void
set_icon(Screen *self, PyObject *icon) {
    CALLBACK("icon_changed", "O", icon);
}

void
set_dynamic_color(Screen *self, unsigned int code, PyObject *color) {
    if (color == NULL) { CALLBACK("set_dynamic_color", "Is", code, ""); }
    else { CALLBACK("set_dynamic_color", "IO", code, color); }
}

void
clipboard_control(Screen *self, PyObject *data) {
    CALLBACK("clipboard_control", "O", data);
}

void
set_color_table_color(Screen *self, unsigned int code, PyObject *color) {
    if (color == NULL) { CALLBACK("set_color_table_color", "Is", code, ""); }
    else { CALLBACK("set_color_table_color", "IO", code, color); }
}

void
screen_handle_cmd(Screen *self, PyObject *cmd) {
    CALLBACK("handle_remote_cmd", "O", cmd);
}

void
screen_push_dynamic_colors(Screen *self) {
    colorprofile_push_dynamic_colors(self->color_profile);
}

void
screen_pop_dynamic_colors(Screen *self) {
    colorprofile_pop_dynamic_colors(self->color_profile);
}

void
screen_handle_print(Screen *self, PyObject *msg) {
    CALLBACK("handle_remote_print", "O", msg);
}

void
screen_request_capabilities(Screen *self, char c, PyObject *q) {
    static char buf[128];
    int shape = 0;
    const char *query;
    switch(c) {
        case '+':
            CALLBACK("request_capabilities", "O", q);
            break;
        case '$':
            // report status
            query = PyUnicode_AsUTF8(q);
            if (strcmp(" q", query) == 0) {
                // cursor shape
                switch(self->cursor->shape) {
                    case NO_CURSOR_SHAPE:
                    case NUM_OF_CURSOR_SHAPES:
                        shape = 1; break;
                    case CURSOR_BLOCK:
                        shape = self->cursor->blink ? 0 : 2; break;
                    case CURSOR_UNDERLINE:
                        shape = self->cursor->blink ? 3 : 4; break;
                    case CURSOR_BEAM:
                        shape = self->cursor->blink ? 5 : 6; break;
                }
                shape = snprintf(buf, sizeof(buf), "1$r%d q", shape);
            } else if (strcmp("m", query) == 0) {
                // SGR
                shape = snprintf(buf, sizeof(buf), "1$r%sm", cursor_as_sgr(self->cursor));
            } else if (strcmp("r", query) == 0) {
                shape = snprintf(buf, sizeof(buf), "1$r%u;%ur", self->margin_top + 1, self->margin_bottom + 1);
            } else {
                shape = snprintf(buf, sizeof(buf), "0$r%s", query);
            }
            if (shape > 0) write_escape_code_to_child(self, DCS, buf);
            break;
    }
}

// }}}

// Rendering {{{
static inline void
update_line_data(Line *line, unsigned int dest_y, uint8_t *data) {
    size_t base = dest_y * line->xnum * sizeof(GPUCell);
    memcpy(data + base, line->gpu_cells, line->xnum * sizeof(GPUCell));
}


static inline void
screen_reset_dirty(Screen *self) {
    self->is_dirty = false;
    self->history_line_added_count = 0;
}

void
screen_update_cell_data(Screen *self, void *address, FONTS_DATA_HANDLE fonts_data, bool cursor_has_moved) {
    unsigned int history_line_added_count = self->history_line_added_count;
    index_type lnum;
    bool was_dirty = self->is_dirty;
    if (self->scrolled_by) self->scrolled_by = MIN(self->scrolled_by + history_line_added_count, self->historybuf->count);
    screen_reset_dirty(self);
    self->scroll_changed = false;
    for (index_type y = 0; y < MIN(self->lines, self->scrolled_by); y++) {
        lnum = self->scrolled_by - 1 - y;
        historybuf_init_line(self->historybuf, lnum, self->historybuf->line);
        if (self->historybuf->line->has_dirty_text) {
            render_line(fonts_data, self->historybuf->line, lnum, self->cursor);
            historybuf_mark_line_clean(self->historybuf, lnum);
        }
        update_line_data(self->historybuf->line, y, address);
    }
    for (index_type y = self->scrolled_by; y < self->lines; y++) {
        lnum = y - self->scrolled_by;
        linebuf_init_line(self->linebuf, lnum);
        if (self->linebuf->line->has_dirty_text ||
            (cursor_has_moved && (self->cursor->y == lnum || self->last_rendered_cursor_y == lnum))) {
            render_line(fonts_data, self->linebuf->line, lnum, self->cursor);
            linebuf_mark_line_clean(self->linebuf, lnum);
        }
        update_line_data(self->linebuf->line, y, address);
    }
    if (was_dirty) {
        self->url_range = EMPTY_SELECTION;
    }
}


static inline bool
is_selection_empty(Screen *self, unsigned int start_x, unsigned int start_y, unsigned int end_x, unsigned int end_y) {
    return (start_x >= self->columns || start_y >= self->lines || end_x >= self->columns || end_y >= self->lines || (start_x == end_x && start_y == end_y)) ? true : false;
}

static inline void
selection_coord(Screen *self, unsigned int x, unsigned int y, unsigned int ydelta, SelectionBoundary *ans) {
    if (y + self->scrolled_by < ydelta) {
        ans->x = 0; ans->y = 0;
    } else {
        y = y - ydelta + self->scrolled_by;
        if (y >= self->lines) {
            ans->x = self->columns - 1; ans->y = self->lines - 1;
        } else {
            ans->x = x; ans->y = y;
        }
    }
}

static inline void
full_selection_coord(Screen *self, unsigned int x, unsigned int y, unsigned int ydelta, FullSelectionBoundary *ans) {
    ans->x = MIN(x, self->columns - 1);
    ans->y = y - ydelta;
    if (y >= self->lines) { ans->x = self->columns - 1; ans->y = self->lines - 1; }
}

#define selection_limits_(which, left, right) { \
    SelectionBoundary a, b; \
    selection_coord(self, self->which.start_x, self->which.start_y, self->which.start_scrolled_by, &a); \
    selection_coord(self, self->which.end_x, self->which.end_y, self->which.end_scrolled_by, &b); \
    if (a.y < b.y || (a.y == b.y && a.x <= b.x)) { *(left) = a; *(right) = b; } \
    else { *(left) = b; *(right) = a; } \
}

#define full_selection_limits_(which, left, right) { \
    FullSelectionBoundary a, b; \
    full_selection_coord(self, self->which.start_x, self->which.start_y, self->which.start_scrolled_by, &a); \
    full_selection_coord(self, self->which.end_x, self->which.end_y, self->which.end_scrolled_by, &b); \
    if (a.y < b.y || (a.y == b.y && a.x <= b.x)) { *(left) = a; *(right) = b; } \
    else { *(left) = b; *(right) = a; } \
}


static inline Line*
visual_line_(Screen *self, index_type y) {
    if (self->scrolled_by) {
        if (y < self->scrolled_by) {
            historybuf_init_line(self->historybuf, self->scrolled_by - 1 - y, self->historybuf->line);
            return self->historybuf->line;
        }
        y -= self->scrolled_by;
    }
    linebuf_init_line(self->linebuf, y);
    return self->linebuf->line;
}

static inline Line*
range_line_(Screen *self, int y) {
    if (y < 0) {
        historybuf_init_line(self->historybuf, -(y + 1), self->historybuf->line);
        return self->historybuf->line;
    }
    linebuf_init_line(self->linebuf, y);
    return self->linebuf->line;
}

#define iterate_over_rectangle(start, end, line_func, y_type) { \
    y_type min_y = MIN(start->y, end->y), max_y = MAX(start->y, end->y); \
    index_type min_x = MIN(start->x, end->x), max_x = MAX(start->x, end->x); \
    for (y_type y = min_y; y <= max_y; y++) { \
        Line *line = line_func(self, y); \
        index_type xlimit = xlimit_for_line(line); \
        xlimit = MIN(max_x + 1, xlimit); \
        index_type x_start = min_x;

#define iterate_over_region(start, end, line_func, y_type) { \
    for (y_type y = start->y; y <= end->y; y++) { \
        Line *line = line_func(self, y); \
        index_type xlimit = xlimit_for_line(line); \
        if (y == end->y) xlimit = MIN(end->x + 1, xlimit); \
        index_type x_start = y == start->y ? start->x : 0;


static inline void
apply_selection(Screen *self, uint8_t *data, SelectionBoundary *start, SelectionBoundary *end, uint8_t set_mask, bool rectangle_select) {
    if (is_selection_empty(self, start->x, start->y, end->x, end->y)) return;
    if (rectangle_select) {
        iterate_over_rectangle(start, end, visual_line_, index_type)
            uint8_t *line_start = data + self->columns * y;
            for (index_type x = x_start; x < xlimit; x++) line_start[x] |= set_mask;
        }}
    } else {
        iterate_over_region(start, end, visual_line_, index_type)
            uint8_t *line_start = data + self->columns * y;
            for (index_type x = x_start; x < xlimit; x++) line_start[x] |= set_mask;
        }}
    }

}

bool
screen_has_selection(Screen *self) {
    SelectionBoundary start, end;
    selection_limits_(selection, &start, &end);
    return !is_selection_empty(self, start.x, start.y, end.x, end.y);
}

void
screen_apply_selection(Screen *self, void *address, size_t size) {
    memset(address, 0, size);
    self->last_selection_scrolled_by = self->scrolled_by;
    self->selection_updated_once = true;
    selection_limits_(selection, &self->last_rendered_selection_start, &self->last_rendered_selection_end);
    apply_selection(self, address, &self->last_rendered_selection_start, &self->last_rendered_selection_end, 1, self->selection.rectangle_select);
    selection_limits_(url_range, &self->last_rendered_url_start, &self->last_rendered_url_end);
    apply_selection(self, address, &self->last_rendered_url_start, &self->last_rendered_url_end, 2, false);
}

#define text_for_range_action(ans, insert_newlines) { \
    char leading_char = (i > 0 && insert_newlines && !line->continued) ? '\n' : 0; \
    PyObject *text = unicode_in_range(line, x_start, xlimit, true, leading_char); \
    if (text == NULL) { Py_DECREF(ans); return PyErr_NoMemory(); } \
    PyTuple_SET_ITEM(ans, i++, text); \
}

#define text_for_range(ans, start, end, rectangle_select, insert_newlines, line_func, y_type) { \
    int num_of_lines = end.y - start.y + 1, i = 0; \
    ans = PyTuple_New(num_of_lines); \
    if (ans == NULL) return PyErr_NoMemory(); \
    if (rectangle_select) { \
        iterate_over_rectangle((&start), (&end), line_func, y_type) \
            text_for_range_action(ans, insert_newlines); \
    } }} else { \
        iterate_over_region((&start), (&end), line_func, y_type) \
            text_for_range_action(ans, insert_newlines); \
    } }} \
}


bool
screen_open_url(Screen *self) {
    SelectionBoundary start, end;
    selection_limits_(url_range, &start, &end);
    if (is_selection_empty(self, start.x, start.y, end.x, end.y)) return false;
    PyObject *url;
    text_for_range(url, start, end, false, false, visual_line_, index_type);
    if (url) { call_boss(open_url_lines, "(O)", url); Py_CLEAR(url); }
    else PyErr_Print();
    return true;
}

static void
deactivate_overlay_line(Screen *self) {
    if (self->overlay_line.is_active && self->overlay_line.xnum && self->overlay_line.ynum < self->lines) {
        Line *line = range_line_(self, self->overlay_line.ynum);
        line_reset_cells(line, self->overlay_line.xstart, self->overlay_line.xnum, self->overlay_line.gpu_cells, self->overlay_line.cpu_cells);
        if (self->cursor->y == self->overlay_line.ynum) self->cursor->x = self->overlay_line.xstart;
        self->is_dirty = true;
        linebuf_mark_line_dirty(self->linebuf, self->overlay_line.ynum);
    }
    self->overlay_line.is_active = false;
    self->overlay_line.ynum = 0;
    self->overlay_line.xnum = 0;
    self->overlay_line.xstart = 0;
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

static PyObject*
set_pending_timeout(Screen *self, PyObject *val) {
    if (!PyFloat_Check(val)) { PyErr_SetString(PyExc_TypeError, "timeout must be a float"); return NULL; }
    PyObject *ans = PyFloat_FromDouble(self->pending_mode.wait_time);
    self->pending_mode.wait_time = PyFloat_AS_DOUBLE(val);
    return ans;
}

static PyObject*
as_text(Screen *self, PyObject *args) {
    as_text_generic(args, self, visual_line_, self->lines, self->columns);
}

static PyObject*
as_text_non_visual(Screen *self, PyObject *args) {
    as_text_generic(args, self, range_line_, self->lines, self->columns);
}

static inline PyObject*
as_text_generic_wrapper(Screen *self, PyObject *args, Line*(get_line)(Screen *, int)) {
    as_text_generic(args, self, get_line, self->lines, self->columns);
}

static PyObject*
as_text_alternate(Screen *self, PyObject *args) {
    LineBuf *original = self->linebuf;
    self->linebuf = original == self->main_linebuf ? self->alt_linebuf : self->main_linebuf;
    PyObject *ans = as_text_generic_wrapper(self, args, range_line_);
    self->linebuf = original;
    return ans;
}


static PyObject*
screen_wcswidth(PyObject UNUSED *self, PyObject *str) {
    if (PyUnicode_READY(str) != 0) return NULL;
    int kind = PyUnicode_KIND(str);
    void *data = PyUnicode_DATA(str);
    Py_ssize_t len = PyUnicode_GET_LENGTH(str), i;
    unsigned long ans = 0;
    char_type prev_ch = 0;
    int prev_width = 0;
    bool in_sgr = false;
    for (i = 0; i < len; i++) {
        char_type ch = PyUnicode_READ(kind, data, i);
        if (in_sgr) {
            if (ch == 'm') in_sgr = false;
            continue;
        }
        if (ch == 0x1b && i + 1 < len && PyUnicode_READ(kind, data, i + 1) == '[') { in_sgr = true; continue; }
        if (ch == 0xfe0f) {
            if (is_emoji_presentation_base(prev_ch) && prev_width == 1) {
                ans += 1;
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
            ans += prev_width;
        }
        prev_ch = ch;
    }
    return PyLong_FromUnsignedLong(ans);
}


static PyObject*
screen_truncate_point_for_length(PyObject UNUSED *self, PyObject *args) {
    PyObject *str; unsigned int num_cells, start_pos = 0;
    if (!PyArg_ParseTuple(args, "OI|I", &str, &num_cells, &start_pos)) return NULL;
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
    int kind = PyUnicode_KIND(src);
    void *buf = PyUnicode_DATA(src);
    Py_ssize_t sz = PyUnicode_GET_LENGTH(src);
    for (Py_ssize_t i = 0; i < sz; i++) screen_draw(self, PyUnicode_READ(kind, buf, i));
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
    unsigned int params[256] = {0};
    for (int i = 0; i < PyTuple_GET_SIZE(args); i++) { params[i] = PyLong_AsUnsignedLong(PyTuple_GET_ITEM(args, i)); }
    select_graphic_rendition(self, params, PyTuple_GET_SIZE(args), NULL);
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
is_using_alternate_linebuf(Screen *self, PyObject *a UNUSED) {
    if (self->linebuf == self->alt_linebuf) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

WRAP1E(cursor_back, 1, -1)
WRAP1B(erase_in_line, 0)
WRAP1B(erase_in_display, 0)
WRAP0(scroll_until_cursor)

#define MODE_GETSET(name, uname) \
    static PyObject* name##_get(Screen *self, void UNUSED *closure) { PyObject *ans = self->modes.m##uname ? Py_True : Py_False; Py_INCREF(ans); return ans; } \
    static int name##_set(Screen *self, PyObject *val, void UNUSED *closure) { if (val == NULL) { PyErr_SetString(PyExc_TypeError, "Cannot delete attribute"); return -1; } set_mode_from_const(self, uname, PyObject_IsTrue(val) ? true : false); return 0; }

MODE_GETSET(in_bracketed_paste_mode, BRACKETED_PASTE)
MODE_GETSET(extended_keyboard, EXTENDED_KEYBOARD)
MODE_GETSET(focus_tracking_enabled, FOCUS_TRACKING)
MODE_GETSET(auto_repeat_enabled, DECARM)
MODE_GETSET(cursor_visible, DECTCEM)
MODE_GETSET(cursor_key_mode, DECCKM)

static PyObject*
cursor_up(Screen *self, PyObject *args) {
    unsigned int count = 1;
    int do_carriage_return = false, move_direction = -1;
    if (!PyArg_ParseTuple(args, "|Ipi", &count, &do_carriage_return, &move_direction)) return NULL;
    screen_cursor_up(self, count, do_carriage_return, move_direction);
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
WRAP2(resize, 1, 1)
WRAP2(set_margins, 1, 1)
WRAP0(rescale_images)
WRAP2B(update_selection)

static PyObject*
start_selection(Screen *self, PyObject *args) {
    unsigned int x, y;
    int rectangle_select = 0, extend_mode = EXTEND_CELL;
    if (!PyArg_ParseTuple(args, "II|pi", &x, &y, &rectangle_select, &extend_mode)) return NULL;
    screen_start_selection(self, x, y, rectangle_select, extend_mode);
    Py_RETURN_NONE;
}

static PyObject*
is_rectangle_select(Screen *self, PyObject *a UNUSED) {
    PyObject *ans = self->selection.rectangle_select ? Py_True : Py_False;
    Py_INCREF(ans);
    return ans;
}

static PyObject*
text_for_selection(Screen *self, PyObject *a UNUSED) {
    FullSelectionBoundary start, end;
    full_selection_limits_(selection, &start, &end);
    PyObject *ans = NULL;
    if (start.y == end.y && start.x == end.x) ans = PyTuple_New(0);
    else text_for_range(ans, start, end, self->selection.rectangle_select, true, range_line_, int);
    return ans;
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

static inline bool
is_opt_word_char(char_type ch) {
    for (size_t i = 0; i < OPT(select_by_word_characters_count); i++) {
        if (OPT(select_by_word_characters[i]) == ch) return true;
    }
    return false;
}

bool
screen_selection_range_for_word(Screen *self, index_type x, index_type *y1, index_type *y2, index_type *s, index_type *e) {
    if (*y1 >= self->lines || x >= self->columns) return false;
    index_type start, end;
    Line *line = visual_line_(self, *y1);
    *y2 = *y1;
#define is_ok(x) (is_word_char((line->cpu_cells[x].ch)) || is_opt_word_char(line->cpu_cells[x].ch))
    if (!is_ok(x)) {
        start = x; end = x + 1;
    } else {
        start = x, end = x;
        while(true) {
            while(start > 0 && is_ok(start - 1)) start--;
            if (start > 0 || !line->continued || *y1 == 0) break;
            line = visual_line_(self, *y1 - 1);
            if (!is_ok(self->columns - 1)) break;
            (*y1)--; start = self->columns - 1;
        }
        line = visual_line_(self, *y2);
        while(true) {
            while(end < self->columns - 1 && is_ok(end + 1)) end++;
            if (end < self->columns - 1 || *y2 >= self->lines - 1) break;
            line = visual_line_(self, *y2 + 1);
            if (!line->continued || !is_ok(0)) break;
            (*y2)++; end = 0;
        }
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
        self->scroll_changed = true;
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

bool
screen_is_selection_dirty(Screen *self) {
    SelectionBoundary start, end;
    selection_limits_(selection, &start, &end);
    if (self->last_selection_scrolled_by != self->scrolled_by || start.x != self->last_rendered_selection_start.x || start.y != self->last_rendered_selection_start.y || end.x != self->last_rendered_selection_end.x || end.y != self->last_rendered_selection_end.y || !self->selection_updated_once) return true;
    selection_limits_(url_range, &start, &end);
    if (start.x != self->last_rendered_url_start.x || start.y != self->last_rendered_url_start.y || end.x != self->last_rendered_url_end.x || end.y != self->last_rendered_url_end.y) return true;
    return false;
}

void
screen_start_selection(Screen *self, index_type x, index_type y, bool rectangle_select, SelectionExtendMode extend_mode) {
#define A(attr, val) self->selection.attr = val;
    A(start_x, x); A(end_x, x); A(start_y, y); A(end_y, y); A(start_scrolled_by, self->scrolled_by); A(end_scrolled_by, self->scrolled_by);
    A(in_progress, true); A(rectangle_select, rectangle_select); A(extend_mode, extend_mode);
#undef A
}

void
screen_mark_url(Screen *self, index_type start_x, index_type start_y, index_type end_x, index_type end_y) {
#define A(attr, val) self->url_range.attr = val;
    A(start_x, start_x); A(end_x, end_x); A(start_y, start_y); A(end_y, end_y); A(start_scrolled_by, self->scrolled_by); A(end_scrolled_by, self->scrolled_by);
#undef A
}

void
screen_update_selection(Screen *self, index_type x, index_type y, bool ended) {
    self->selection.end_x = x; self->selection.end_y = y; self->selection.end_scrolled_by = self->scrolled_by;
    if (ended) self->selection.in_progress = false;
    index_type start, end;
    bool found = false;
    bool extending_leftwards = self->selection.end_y < self->selection.start_y || (self->selection.end_y == self->selection.start_y && self->selection.end_x < self->selection.start_x);
    switch(self->selection.extend_mode) {
        case EXTEND_WORD: {
            index_type y1 = y, y2;
            found = screen_selection_range_for_word(self, x, &y1, &y2, &start, &end);
            if (found) {
                if (extending_leftwards) {
                    self->selection.end_x = start; self->selection.end_y = y1;
                    y1 = self->selection.start_y;
                    found = screen_selection_range_for_word(self, self->selection.start_x, &y1, &y2, &start, &end);
                    if (found) {
                        self->selection.start_x = end; self->selection.start_y = y2;
                    }
                } else {
                    self->selection.end_x = end; self->selection.end_y = y2;
                    y1 = self->selection.start_y;
                    found = screen_selection_range_for_word(self, self->selection.start_x, &y1, &y2, &start, &end);
                    if (found) {
                        self->selection.start_x = start; self->selection.start_y = y1;
                    }

                }
            }
            break;
        }
        case EXTEND_LINE: {
            index_type top_line = extending_leftwards ? self->selection.end_y : self->selection.start_y;
            index_type bottom_line = extending_leftwards ? self->selection.start_y : self->selection.end_y;
            while(top_line > 0 && visual_line_(self, top_line)->continued) top_line--;
            while(bottom_line < self->lines - 1 && visual_line_(self, bottom_line + 1)->continued) bottom_line++;
            found = screen_selection_range_for_line(self, top_line, &start, &end);
            if (found) {
                if (extending_leftwards) {
                    self->selection.end_x = start; self->selection.end_y = top_line;
                } else {
                    self->selection.start_x = start; self->selection.start_y = top_line;
                }
            }
            found = screen_selection_range_for_line(self, bottom_line, &start, &end);
            if (found) {
                if (extending_leftwards) {
                    self->selection.start_x = end; self->selection.start_y = bottom_line;
                } else {
                    self->selection.end_x = end; self->selection.end_y = bottom_line;
                }
            }
            break;
        }
        case EXTEND_CELL:
            break;
    }
    if (!self->selection.in_progress) call_boss(set_primary_selection, NULL);
}

static PyObject*
mark_as_dirty(Screen *self, PyObject *a UNUSED) {
    self->is_dirty = true;
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
    screen_toggle_screen_buffer(self);
    Py_RETURN_NONE;
}

static PyObject*
send_escape_code_to_child(Screen *self, PyObject *args) {
    int code;
    char *text;
    if (!PyArg_ParseTuple(args, "is", &code, &text)) return NULL;
    write_escape_code_to_child(self, code, text);
    Py_RETURN_NONE;
}

static PyObject*
paste(Screen *self, PyObject *bytes) {
    if (self->modes.mBRACKETED_PASTE) write_escape_code_to_child(self, CSI, BRACKETED_PASTE_START);
    write_to_child(self, PyBytes_AS_STRING(bytes), PyBytes_GET_SIZE(bytes));
    if (self->modes.mBRACKETED_PASTE) write_escape_code_to_child(self, CSI, BRACKETED_PASTE_END);
    Py_RETURN_NONE;
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
wcwidth_wrap(PyObject UNUSED *self, PyObject *chr) {
    return PyLong_FromLong(wcwidth_std(PyLong_AsLong(chr)));
}


#define MND(name, args) {#name, (PyCFunction)name, args, #name},
#define MODEFUNC(name) MND(name, METH_NOARGS) MND(set_##name, METH_O)

static PyMethodDef methods[] = {
    MND(line, METH_O)
    MND(visual_line, METH_VARARGS)
    MND(draw, METH_O)
    MND(cursor_position, METH_VARARGS)
    MND(set_mode, METH_VARARGS)
    MND(reset_mode, METH_VARARGS)
    MND(reset, METH_NOARGS)
    MND(reset_dirty, METH_NOARGS)
    MND(is_using_alternate_linebuf, METH_NOARGS)
    MND(is_main_linebuf, METH_NOARGS)
    MND(cursor_back, METH_VARARGS)
    MND(erase_in_line, METH_VARARGS)
    MND(erase_in_display, METH_VARARGS)
    MND(scroll_until_cursor, METH_NOARGS)
    METHOD(current_char_width, METH_NOARGS)
    MND(insert_lines, METH_VARARGS)
    MND(delete_lines, METH_VARARGS)
    MND(insert_characters, METH_VARARGS)
    MND(delete_characters, METH_VARARGS)
    MND(erase_characters, METH_VARARGS)
    MND(cursor_up, METH_VARARGS)
    MND(cursor_up1, METH_VARARGS)
    MND(cursor_down, METH_VARARGS)
    MND(cursor_down1, METH_VARARGS)
    MND(cursor_forward, METH_VARARGS)
    {"index", (PyCFunction)xxx_index, METH_VARARGS, ""},
    MND(set_pending_timeout, METH_O)
    MND(as_text, METH_VARARGS)
    MND(as_text_non_visual, METH_VARARGS)
    MND(as_text_alternate, METH_VARARGS)
    MND(tab, METH_NOARGS)
    MND(backspace, METH_NOARGS)
    MND(linefeed, METH_NOARGS)
    MND(carriage_return, METH_NOARGS)
    MND(set_tab_stop, METH_NOARGS)
    MND(clear_tab_stop, METH_VARARGS)
    MND(start_selection, METH_VARARGS)
    MND(update_selection, METH_VARARGS)
    MND(reverse_index, METH_NOARGS)
    MND(mark_as_dirty, METH_NOARGS)
    MND(resize, METH_VARARGS)
    MND(set_margins, METH_VARARGS)
    MND(rescale_images, METH_NOARGS)
    MND(text_for_selection, METH_NOARGS)
    MND(is_rectangle_select, METH_NOARGS)
    MND(scroll, METH_VARARGS)
    MND(send_escape_code_to_child, METH_VARARGS)
    MND(toggle_alt_screen, METH_NOARGS)
    MND(reset_callbacks, METH_NOARGS)
    MND(paste, METH_O)
    {"select_graphic_rendition", (PyCFunction)_select_graphic_rendition, METH_VARARGS, ""},

    {NULL}  /* Sentinel */
};

static PyGetSetDef getsetters[] = {
    GETSET(in_bracketed_paste_mode)
    GETSET(extended_keyboard)
    GETSET(auto_repeat_enabled)
    GETSET(focus_tracking_enabled)
    GETSET(cursor_visible)
    GETSET(cursor_key_mode)
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
    {"grman", T_OBJECT_EX, offsetof(Screen, grman), READONLY, "grman"},
    {"color_profile", T_OBJECT_EX, offsetof(Screen, color_profile), READONLY, "color_profile"},
    {"linebuf", T_OBJECT_EX, offsetof(Screen, linebuf), READONLY, "linebuf"},
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
    {"wcwidth", (PyCFunction)wcwidth_wrap, METH_O, ""},
    {"wcswidth", (PyCFunction)screen_wcswidth, METH_O, ""},
    {"truncate_point_for_length", (PyCFunction)screen_truncate_point_for_length, METH_VARARGS, ""},
    {NULL}  /* Sentinel */
};

INIT_TYPE(Screen)
// }}}
