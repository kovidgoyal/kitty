/*
 * screen.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <structmember.h>
#include "unicode-data.h"
#include "tracker.h"
#include "modes.h"

static const ScreenModes empty_modes = {0, .mDECAWM=true, .mDECTCEM=true};

// Constructor/destructor {{{
static PyObject*
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    Screen *self;
    PyObject *callbacks = Py_None;
    unsigned int columns=80, lines=24;
    if (!PyArg_ParseTuple(args, "|OII", &callbacks, &lines, &columns)) return NULL;

    self = (Screen *)type->tp_alloc(type, 0);
    if (self != NULL) {
        self->current_charset = 2;
        self->g0_charset = translation_table('B');
        self->g1_charset = translation_table('0');
        self->columns = columns; self->lines = lines;
        self->modes = empty_modes;
        self->utf8_state = 0;
        self->margin_top = 0; self->margin_bottom = self->lines - 1;
        self->callbacks = callbacks; Py_INCREF(callbacks);
        self->cursor = alloc_cursor();
        self->main_linebuf = alloc_linebuf(lines, columns); self->alt_linebuf = alloc_linebuf(lines, columns);
        self->linebuf = self->main_linebuf;
        self->change_tracker = alloc_change_tracker(lines, columns);
        self->historybuf = alloc_historybuf(lines, columns);
        self->tabstops = PyMem_Calloc(self->columns, sizeof(bool));
        if (self->cursor == NULL || self->main_linebuf == NULL || self->alt_linebuf == NULL || self->change_tracker == NULL || self->tabstops == NULL || self->historybuf == NULL) {
            Py_CLEAR(self); return NULL;
        }
    }
    return (PyObject*) self;
}

void screen_reset(Screen *self) {
    if (self->linebuf == self->alt_linebuf) screen_toggle_screen_buffer(self);
    linebuf_clear(self->linebuf);
    self->current_charset = 2;
    self->g0_charset = translation_table('B');
    self->g1_charset = translation_table('0');
    self->modes = empty_modes;
    self->utf8_state = 0;
    self->margin_top = 0; self->margin_bottom = self->lines - 1;
    // In terminfo we specify the number of initial tabstops (it) as 8
    for (unsigned int t=0; t < self->columns; t++) self->tabstops[t] = t > 0 && (t+1) % 8 == 0;
    screen_normal_keypad_mode(self);
    cursor_reset(self->cursor);
    tracker_cursor_changed(self->change_tracker);
    screen_cursor_position(self, 1, 1);
    screen_change_default_color(self, FG, 0);
    screen_change_default_color(self, BG, 0);
    tracker_update_screen(self->change_tracker);
}
static inline HistoryBuf* realloc_hb(HistoryBuf *old, unsigned int lines, unsigned int columns) {
    HistoryBuf *ans = alloc_historybuf(lines, columns);
    if (ans == NULL) { PyErr_NoMemory(); return NULL; }
    historybuf_rewrap(old, ans);
    return ans;
}

static inline LineBuf* realloc_lb(LineBuf *old, unsigned int lines, unsigned int columns, int *cursor_y, HistoryBuf *hb) {
    LineBuf *ans = alloc_linebuf(lines, columns);
    if (ans == NULL) { PyErr_NoMemory(); return NULL; }
    linebuf_rewrap(old, ans, cursor_y, hb);
    return ans;
}

static bool screen_resize(Screen *self, unsigned int lines, unsigned int columns) {
    lines = MAX(1, lines); columns = MAX(1, columns);

    bool is_main = self->linebuf == self->main_linebuf;
    int cursor_y = -1;
    HistoryBuf *nh = realloc_hb(self->historybuf, lines, columns);
    if (nh == NULL) return false;
    Py_CLEAR(self->historybuf); self->historybuf = nh;
    LineBuf *n = realloc_lb(self->main_linebuf, lines, columns, &cursor_y, self->historybuf);
    if (n == NULL) return false;
    Py_CLEAR(self->main_linebuf); self->main_linebuf = n;
    if (is_main) self->cursor->y = MAX(0, cursor_y);
    cursor_y = -1;
    n = realloc_lb(self->alt_linebuf, lines, columns, &cursor_y, NULL);
    if (n == NULL) return false;
    Py_CLEAR(self->alt_linebuf); self->alt_linebuf = n;
    if (!is_main) self->cursor->y = MAX(0, cursor_y);
    self->linebuf = is_main ? self->main_linebuf : self->alt_linebuf;

    if (!tracker_resize(self->change_tracker, lines, columns)) return false;

    PyMem_Free(self->tabstops);
    self->tabstops = PyMem_Calloc(self->columns, sizeof(bool));
    if (self->tabstops == NULL) { PyErr_NoMemory(); return false; }

    self->lines = lines; self->columns = columns;
    self->margin_top = 0; self->margin_bottom = self->lines - 1;
    screen_reset_mode(self, DECOM);
    // TODO: resize history buf
    return true;
}

static bool screen_change_scrollback_size(Screen *self, unsigned int size) {
    return historybuf_resize(self->historybuf, size);
}


static void
dealloc(Screen* self) {
    Py_CLEAR(self->callbacks);
    Py_CLEAR(self->cursor); 
    Py_CLEAR(self->main_linebuf); 
    Py_CLEAR(self->alt_linebuf);
    Py_CLEAR(self->change_tracker);
    PyMem_Free(self->tabstops);
    Py_TYPE(self)->tp_free((PyObject*)self);
} // }}}

// Draw text {{{
 
void screen_shift_out(Screen *self, uint8_t UNUSED ch) {
    self->current_charset = 1;
    self->utf8_state = 0;
}

void screen_shift_in(Screen *self, uint8_t UNUSED ch) {
    self->current_charset = 0;
    self->utf8_state = 0;
}

void screen_define_charset(Screen *self, uint8_t code, uint8_t mode) {
    switch(mode) {
        case '(':
            self->g0_charset = translation_table(code);
            break;
        default:
            self->g1_charset = translation_table(code);
            break;
    }
}

void screen_select_other_charset(Screen *self, uint8_t code, uint8_t UNUSED unused) {
    switch(code) {
        case '@':
            self->current_charset = 0;
            break;
        default:
            self->current_charset = 2;
            self->utf8_state = 0;
    }
}

static inline unsigned int safe_wcwidth(uint32_t ch) {
    int ans = wcwidth(ch);
    if (ans < 0) ans = 1;
    return MIN(2, ans);
}

static inline void
draw_codepoint(Screen UNUSED *self, uint32_t ch) {
    if (is_ignored_char(ch)) return;
    unsigned int char_width = safe_wcwidth(ch);
    if (self->columns - self->cursor->x < char_width) {
        if (self->modes.mDECAWM) {
            screen_carriage_return(self, 13);
            screen_linefeed(self, 10);
            self->linebuf->continued_map[self->cursor->y] = true;
        } else {
            self->cursor->x = self->columns - char_width;
        }
    }
    if (char_width > 0) {
        unsigned int cx = self->cursor->x;
        linebuf_init_line(self->linebuf, self->cursor->y);
        if (self->modes.mIRM) {
            line_right_shift(self->linebuf->line, self->cursor->x, char_width);
        }
        line_set_char(self->linebuf->line, self->cursor->x, ch, char_width, self->cursor);
        self->cursor->x++;
        if (char_width == 2) {
            line_set_char(self->linebuf->line, self->cursor->x, 0, 0, self->cursor);
            self->cursor->x++;
        }
        unsigned int right = self->modes.mIRM ? self->columns - 1 : MIN((MAX(self->cursor->x, 1) - 1), self->columns - 1);
        tracker_update_cell_range(self->change_tracker, self->cursor->y, cx, right);
    } else if (is_combining_char(ch)) {
        if (self->cursor->x > 0) {
            linebuf_init_line(self->linebuf, self->cursor->y);
            line_add_combining_char(self->linebuf->line, ch, self->cursor->x - 1);
            tracker_update_cell_range(self->change_tracker, self->cursor->y, self->cursor->x - 1, self->cursor->x - 1);
        } else if (self->cursor->y > 0) {
            linebuf_init_line(self->linebuf, self->cursor->y - 1);
            line_add_combining_char(self->linebuf->line, ch, self->columns - 1);
            tracker_update_cell_range(self->change_tracker, self->cursor->y - 1, self->columns - 1, self->columns - 1);
        }
    }
}

static inline void 
screen_draw_utf8(Screen *self, uint8_t *buf, unsigned int buflen) {
    uint32_t prev = UTF8_ACCEPT, codepoint = 0;
    for (unsigned int i = 0; i < buflen; i++, prev = self->utf8_state) {
        switch (decode_utf8(&self->utf8_state, &codepoint, buf[i])) {
            case UTF8_ACCEPT:
                draw_codepoint(self, codepoint);
                break;
            case UTF8_REJECT:
                self->utf8_state = UTF8_ACCEPT;
                if (prev != UTF8_ACCEPT) i--;
                break;
        }
    }
}

static inline void 
screen_draw_charset(Screen *self, unsigned short *table, uint8_t *buf, unsigned int buflen) {
    for (unsigned int i = 0; i < buflen; i++) {
        draw_codepoint(self, table[buf[i]]);
    }
}

void screen_draw(Screen *self, uint8_t *buf, unsigned int buflen) {
    unsigned int x = self->cursor->x, y = self->cursor->y;
    switch(self->current_charset) {
        case 0:
            screen_draw_charset(self, self->g0_charset, buf, buflen); break;
        case 1:
            screen_draw_charset(self, self->g1_charset, buf, buflen); break;
        default:
            screen_draw_utf8(self, buf, buflen); break;
    }
    if (x != self->cursor->x || y != self->cursor->y) tracker_cursor_changed(self->change_tracker);
}
// }}}

// Graphics {{{

void screen_change_default_color(Screen *self, unsigned int which, uint32_t col) {
    if (self->callbacks == Py_None) return;
    if (col & 0xFF) PyObject_CallMethod(self->callbacks, "change_default_color", "s(III)", which == FG ? "fg" : "bg", 
            (col >> 24) & 0xFF, (col >> 16) & 0xFF, (col >> 8) & 0xFF);
    else PyObject_CallMethod(self->callbacks, "change_default_color", "sO", which == FG ? "fg" : "bg", Py_None);
    if (PyErr_Occurred()) PyErr_Print();
    PyErr_Clear(); 
}

void screen_alignment_display(Screen *self) {
    // http://www.vt100.net/docs/vt510-rm/DECALN.html 
    screen_cursor_position(self, 1, 1);
    self->margin_top = 0; self->margin_bottom = self->columns - 1;
    for (unsigned int y = 0; y < self->linebuf->ynum; y++) {
        linebuf_init_line(self->linebuf, y);
        line_clear_text(self->linebuf->line, 0, self->linebuf->xnum, 'E');
    }
}

void select_graphic_rendition(Screen *self, unsigned int *params, unsigned int count) {
#define SET_COLOR(which) \
    if (i < count) { \
        attr = params[i++];\
        switch(attr) { \
            case 5: \
                if (i < count) \
                    self->cursor->which = (params[i++] & 0xFF) << 8 | 2; \
                break; \
            case 2: \
                if (i < count - 2) { \
                    r = params[i++] & 0xFF; \
                    g = params[i++] & 0xFF; \
                    b = params[i++] & 0xFF; \
                    self->cursor->which = r << 24 | g << 16 | b << 8 | 3; \
                }\
                break; \
        } \
    } \
    break;

    unsigned int i = 0, attr;
    uint8_t r, g, b;
    if (!count) { params[0] = 0; count = 1; }
    while (i < count) {
        attr = params[i++];
        switch(attr) {
            case 0:
                cursor_reset_display_attrs(self->cursor);  break;
            case 1:
                self->cursor->bold = true;  break;
            case 3:
                self->cursor->italic = true;  break;
            case 4:
                self->cursor->decoration = 1;  break;
            case 7:
                self->cursor->reverse = true;  break;
            case 9:
                self->cursor->strikethrough = true;  break;
            case 22:
                self->cursor->bold = false;  break;
            case 23:
                self->cursor->italic = false;  break;
            case 24:
                self->cursor->decoration = 0;  break;
            case 27:
                self->cursor->reverse = false;  break;
            case 29:
                self->cursor->strikethrough = false;  break;
#pragma GCC diagnostic ignored "-Wpedantic"
            case 30 ... 37:
            case 39:
            case 90 ... 97:
                self->cursor->fg = (attr << 8) | 1;  break;
            case 40 ... 47:
            case 49:
            case 100 ... 107:
#pragma GCC diagnostic pop
                self->cursor->bg = (attr << 8) | 1;  break;
            case 38: 
                SET_COLOR(fg);
            case 48: 
                SET_COLOR(bg);
        }
    }
}

// }}}

// Modes {{{


void screen_toggle_screen_buffer(Screen *self) {
    screen_save_cursor(self);
    if (self->linebuf == self->main_linebuf) {
        self->linebuf = self->alt_linebuf;
    } else {
        self->linebuf = self->main_linebuf;
    }
    screen_restore_cursor(self);
    tracker_update_screen(self->change_tracker);
}

void screen_normal_keypad_mode(Screen UNUSED *self) {} // Not implemented as this is handled by the GUI
void screen_alternate_keypad_mode(Screen UNUSED *self) {}  // Not implemented as this is handled by the GUI

static inline void set_mode_from_const(Screen *self, unsigned int mode, bool val) {
    switch(mode) {
        case LNM: 
            self->modes.mLNM = val; break;
        case IRM: 
            self->modes.mIRM = val; break;
        case DECTCEM: 
            self->modes.mDECTCEM = val; break;
        case DECSCNM: 
            self->modes.mDECSCNM = val; break;
        case DECOM: 
            self->modes.mDECOM = val; break;
        case DECAWM: 
            self->modes.mDECAWM = val; break;
        case DECCOLM: 
            self->modes.mDECCOLM = val; break;
        case BRACKETED_PASTE: 
            self->modes.mBRACKETED_PASTE = val; break;
        case FOCUS_TRACKING: 
            self->modes.mFOCUS_TRACKING = val; break;
    }
}

void screen_set_mode(Screen *self, unsigned int mode) {
    if (mode == DECCOLM) {
        // When DECCOLM mode is set, the screen is erased and the cursor
        // moves to the home position.
        screen_erase_in_display(self, 2, false);
        screen_cursor_position(self, 1, 1);
    }
    // According to `vttest`, DECOM should also home the cursor, see
    // vttest/main.c:303.
    if (mode == DECOM) screen_cursor_position(self, 1, 1);

    if (mode == DECSCNM) {
        // Mark all displayed characters as reverse.
        linebuf_set_attribute(self->linebuf, REVERSE_SHIFT, 1);
        tracker_update_screen(self->change_tracker);
        self->cursor->reverse = true;
        tracker_cursor_changed(self->change_tracker);
    }

    if (mode == DECTCEM && self->cursor->hidden) {
        self->cursor->hidden = false;
        tracker_cursor_changed(self->change_tracker);
    }

    if (mode == ALTERNATE_SCREEN && self->linebuf == self->main_linebuf) { 
        screen_toggle_screen_buffer(self);
    }
    set_mode_from_const(self, mode, true);
}

static PyObject*
in_bracketed_paste_mode(Screen *self) {
#define in_bracketed_paste_mode_doc ""
    PyObject *ans = self->modes.mBRACKETED_PASTE ? Py_True : Py_False;
    Py_INCREF(ans);
    return ans;
}

static PyObject*
enable_focus_tracking(Screen *self) {
#define enable_focus_tracking_doc ""
    PyObject *ans = self->modes.mFOCUS_TRACKING ? Py_True : Py_False;
    Py_INCREF(ans);
    return ans;
}

void screen_reset_mode(Screen *self, unsigned int mode) {
    if (mode == DECCOLM) {
        // When DECCOLM mode is set, the screen is erased and the cursor
        // moves to the home position.
        screen_erase_in_display(self, 2, false);
        screen_cursor_position(self, 1, 1);
    }
    // According to `vttest`, DECOM should also home the cursor, see
    // vttest/main.c:303.
    if (mode == DECOM) screen_cursor_position(self, 1, 1);

    if (mode == DECSCNM) {
        // Mark all displayed characters as reverse.
        linebuf_set_attribute(self->linebuf, REVERSE_SHIFT, 0);
        tracker_update_screen(self->change_tracker);
        self->cursor->reverse = false;
        tracker_cursor_changed(self->change_tracker);
    }

    if (mode == DECTCEM && !self->cursor->hidden) {
        self->cursor->hidden = true;
        tracker_cursor_changed(self->change_tracker);
    }

    if (mode == ALTERNATE_SCREEN && self->linebuf != self->main_linebuf) { 
        screen_toggle_screen_buffer(self);
    }
 
    set_mode_from_const(self, mode, false);
}
// }}}

// Cursor {{{

void screen_backspace(Screen *self, uint8_t UNUSED ch) {
    screen_cursor_back(self, 1, -1);
}
void screen_tab(Screen *self, uint8_t UNUSED ch) {
    // Move to the next tab space, or the end of the screen if there aren't anymore left.
    unsigned int found = 0;
    for (unsigned int i = self->cursor->x + 1; i < self->columns; i++) {
        if (self->tabstops[i]) { found = i; break; }
    }
    if (!found) found = self->columns - 1;
    if (found != self->cursor->x) {
        self->cursor->x = found;
        tracker_cursor_changed(self->change_tracker);
    }
}

void screen_clear_tab_stop(Screen *self, unsigned int how) {
    switch(how) {
        case 0:
            if (self->cursor->x < self->columns) self->tabstops[self->cursor->x] = false;
            break;
        case 3:
            break;
            for (unsigned int i = 0; i < self->columns; i++) self->tabstops[i] = false;
    }
}

void screen_set_tab_stop(Screen *self) {
    if (self->cursor->x < self->columns)
        self->tabstops[self->cursor->x] = true;
}

void screen_cursor_back(Screen *self, unsigned int count/*=1*/, int move_direction/*=-1*/) {
    unsigned int x = self->cursor->x;
    if (count == 0) count = 1;
    if (move_direction < 0 && count > self->cursor->x) self->cursor->x = 0;
    else self->cursor->x += move_direction * count;
    screen_ensure_bounds(self, false);
    if (x != self->cursor->x) tracker_cursor_changed(self->change_tracker);
}

void screen_cursor_forward(Screen *self, unsigned int count/*=1*/) {
    screen_cursor_back(self, count, 1);
}

void screen_cursor_up(Screen *self, unsigned int count/*=1*/, bool do_carriage_return/*=false*/, int move_direction/*=-1*/) {
    unsigned int x = self->cursor->x, y = self->cursor->y;
    if (count == 0) count = 1;
    if (move_direction < 0 && count > self->cursor->y) self->cursor->y = 0;
    else self->cursor->y += move_direction * count;
    screen_ensure_bounds(self, true);
    if (do_carriage_return) self->cursor->x = 0;
    if (x != self->cursor->x || y != self->cursor->y) tracker_cursor_changed(self->change_tracker);
}

void screen_cursor_up1(Screen *self, unsigned int count/*=1*/) {
    screen_cursor_up(self, count, true, -1);
}

void screen_cursor_down(Screen *self, unsigned int count/*=1*/) {
    screen_cursor_up(self, count, false, 1);
}

void screen_cursor_down1(Screen *self, unsigned int count/*=1*/) {
    screen_cursor_up(self, count, true, 1);
}

void screen_cursor_to_column(Screen *self, unsigned int column) {
    unsigned int x = MAX(column, 1) - 1;
    if (x != self->cursor->x) {
        self->cursor->x = x;
        screen_ensure_bounds(self, false);
        tracker_cursor_changed(self->change_tracker);
    }
}

void screen_index(Screen *self) {
    // Move cursor down one line, scrolling screen if needed
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (self->cursor->y == bottom) {
        linebuf_index(self->linebuf, top, bottom);
        if (self->linebuf == self->main_linebuf && bottom == self->lines - 1) {
            // Only add to history when no page margins have been set
            linebuf_init_line(self->linebuf, bottom);
            historybuf_add_line(self->historybuf, self->linebuf->line);
            tracker_line_added_to_history(self->change_tracker);
        }
        linebuf_clear_line(self->linebuf, bottom);
        if (bottom - top > self->lines - 1) tracker_update_screen(self->change_tracker);
        else tracker_update_line_range(self->change_tracker, top, bottom);
    } else screen_cursor_down(self, 1);
}

void screen_reverse_index(Screen *self) {
    // Move cursor up one line, scrolling screen if needed
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (self->cursor->y == top) {
        linebuf_reverse_index(self->linebuf, top, bottom);
        linebuf_clear_line(self->linebuf, top);
        if (bottom - top > self->lines - 1) tracker_update_screen(self->change_tracker);
        else tracker_update_line_range(self->change_tracker, top, bottom);
    } else screen_cursor_up(self, 1, false, -1);
}


void screen_carriage_return(Screen *self, uint8_t UNUSED ch) {
    if (self->cursor->x != 0) {
        self->cursor->x = 0;
        tracker_cursor_changed(self->change_tracker);
    }
}

void screen_linefeed(Screen *self, uint8_t UNUSED ch) {
    screen_index(self);
    if (self->modes.mLNM) screen_carriage_return(self, 13);
    screen_ensure_bounds(self, false);
}

static inline Savepoint* savepoints_push(SavepointBuffer *self) {
    Savepoint *ans = self->buf + ((self->start_of_data + self->count) % SAVEPOINTS_SZ);
    if (self->count == SAVEPOINTS_SZ) self->start_of_data = (self->start_of_data + 1) % SAVEPOINTS_SZ;
    else self->count++;
    return ans;
}

static inline Savepoint* savepoints_pop(SavepointBuffer *self) {
    if (self->count == 0) return NULL;
    self->count--;
    return self->buf + ((self->start_of_data + self->count) % SAVEPOINTS_SZ);
}

void screen_save_cursor(Screen *self) {
    SavepointBuffer *pts = self->linebuf == self->main_linebuf ? &self->main_savepoints : &self->alt_savepoints;
    Savepoint *sp = savepoints_push(pts);
    cursor_copy_to(self->cursor, &(sp->cursor));
    sp->g0_charset = self->g0_charset;
    sp->g1_charset = self->g1_charset;
    sp->current_charset = self->current_charset;
    sp->mDECOM = self->modes.mDECOM;
    sp->mDECAWM = self->modes.mDECAWM;
    sp->utf8_state = self->utf8_state;
}

void screen_restore_cursor(Screen *self) {
    SavepointBuffer *pts = self->linebuf == self->main_linebuf ? &self->main_savepoints : &self->alt_savepoints;
    Savepoint *sp = savepoints_pop(pts);
    if (sp == NULL) {
        screen_cursor_position(self, 1, 1);
        tracker_cursor_changed(self->change_tracker);
        screen_reset_mode(self, DECOM);
        self->current_charset = 2;
        self->g0_charset = translation_table('B');
        self->g1_charset = translation_table('0');
    } else {
        self->g0_charset = sp->g0_charset;
        self->g1_charset = sp->g1_charset;
        self->current_charset = sp->current_charset;
        self->utf8_state = sp->utf8_state;
        if (sp->mDECOM) screen_set_mode(self, DECOM);
        if (sp->mDECAWM) screen_set_mode(self, DECAWM);
        cursor_copy_to(&(sp->cursor), self->cursor);
        screen_ensure_bounds(self, false);
    }
}

void screen_ensure_bounds(Screen *self, bool use_margins/*=false*/) {
    unsigned int top, bottom;
    if (use_margins || self->modes.mDECOM) {
        top = self->margin_top; bottom = self->margin_bottom;
    } else {
        top = 0; bottom = self->lines - 1;
    }
    self->cursor->x = MIN(self->cursor->x, self->columns - 1);
    self->cursor->y = MAX(top, MIN(self->cursor->y, bottom));
}

void screen_cursor_position(Screen *self, unsigned int line, unsigned int column) {
    line = (line == 0 ? 1 : line) - 1;
    column = (column == 0 ? 1: column) - 1;
    if (self->modes.mDECOM) {
        line += self->margin_top;
        if (line < self->margin_bottom || line > self->margin_top) return;
    }
    unsigned int x = self->cursor->x, y = self->cursor->y;
    self->cursor->x = column; self->cursor->y = line;
    screen_ensure_bounds(self, false);
    if (x != self->cursor->x || y != self->cursor->y) tracker_cursor_changed(self->change_tracker);
}

void screen_cursor_to_line(Screen *self, unsigned int line) {
    unsigned int y = MAX(line, 1) - 1;
    y += self->margin_top; 
    if (y != self->cursor->y) {
        self->cursor->y = y;
        screen_ensure_bounds(self, false); // TODO: should we also restrict the cursor to the scrolling region?
        tracker_cursor_changed(self->change_tracker);
    }
}

// }}}

// Editing {{{

void screen_erase_in_line(Screen *self, unsigned int how, bool private) {
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
    unsigned int s, n;
    switch(how) {
        case 0:
            s = self->cursor->x;
            n = self->columns - self->cursor->x;
            break;
        case 1:
            s = 0; n = self->cursor->x + 1;
            break;
        case 2:
            s = 0; n = self->columns;
            break;
        default:
            return;
    }
    if (n > s) {
        linebuf_init_line(self->linebuf, self->cursor->y);
        if (private) {
            line_clear_text(self->linebuf->line, s, n, ' ');
        } else {
            line_apply_cursor(self->linebuf->line, self->cursor, s, n, true);
        }
        tracker_update_cell_range(self->change_tracker, self->cursor->y, s, MIN(s+n, self->columns) - 1);
    }
}

void screen_erase_in_display(Screen *self, unsigned int how, bool private) {
    /* Erases display in a specific way.

        :param int how: defines the way the line should be erased in:

            * ``0`` -- Erases from cursor to end of screen, including
              cursor position.
            * ``1`` -- Erases from beginning of screen to cursor,
              including cursor position.
            * ``2`` -- Erases complete display. All lines are erased
              and changed to single-width. Cursor does not move.
        :param bool private: when ``True`` character attributes are left unchanged
    */
    unsigned int a, b;
    switch(how) {
        case 0:
            a = self->cursor->y + 1; b = self->lines; break;
        case 1:
            a = 0; b = self->cursor->y; break;
        case 2:
            a = 0; b = self->lines; break;
        default:
            return;
    }
    if (b > a) {
        for (unsigned int i=a; i < b; i++) {
            linebuf_init_line(self->linebuf, i);
            if (private) {
                line_clear_text(self->linebuf->line, 0, self->columns, ' ');
            } else {
                line_apply_cursor(self->linebuf->line, self->cursor, 0, self->columns, true);
            }
        }
        tracker_update_line_range(self->change_tracker, a, b-1);
    }
    if (how != 2) {
        screen_erase_in_line(self, how, private);
    }
}

void screen_insert_lines(Screen *self, unsigned int count) {
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (count == 0) count = 1;
    if (top <= self->cursor->y && self->cursor->y <= bottom) {
        linebuf_insert_lines(self->linebuf, count, self->cursor->y, bottom);
        tracker_update_line_range(self->change_tracker, self->cursor->y, bottom);
        screen_carriage_return(self, 13);
    }
}

void screen_delete_lines(Screen *self, unsigned int count) {
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (count == 0) count = 1;
    if (top <= self->cursor->y && self->cursor->y <= bottom) {
        linebuf_delete_lines(self->linebuf, count, self->cursor->y, bottom);
        tracker_update_line_range(self->change_tracker, self->cursor->y, bottom);
        screen_carriage_return(self, 13);
    }
}

void screen_insert_characters(Screen *self, unsigned int count) {
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (count == 0) count = 1;
    if (top <= self->cursor->y && self->cursor->y <= bottom) {
        unsigned int x = self->cursor->x;
        unsigned int num = MIN(self->columns - x, count);
        linebuf_init_line(self->linebuf, self->cursor->y);
        line_right_shift(self->linebuf->line, x, num);
        line_apply_cursor(self->linebuf->line, self->cursor, x, num, true);
        tracker_update_cell_range(self->change_tracker, self->cursor->y, x, self->columns - 1);
    }
}

void screen_delete_characters(Screen *self, unsigned int count) {
    // Delete characters, later characters are moved left
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (count == 0) count = 1;
    if (top <= self->cursor->y && self->cursor->y <= bottom) {
        unsigned int x = self->cursor->x;
        unsigned int num = MIN(self->columns - x, count);
        linebuf_init_line(self->linebuf, self->cursor->y);
        left_shift_line(self->linebuf->line, x, num);
        line_apply_cursor(self->linebuf->line, self->cursor, self->columns - num, num, true);
        tracker_update_cell_range(self->change_tracker, self->cursor->y, x, self->columns - 1);
    }
}

void screen_erase_characters(Screen *self, unsigned int count) {
    // Delete characters replacing them by spaces
    if (count == 0) count = 1;
    unsigned int x = self->cursor->x;
    unsigned int num = MIN(self->columns - x, count);
    linebuf_init_line(self->linebuf, self->cursor->y);
    line_apply_cursor(self->linebuf->line, self->cursor, x, num, true);
    tracker_update_cell_range(self->change_tracker, self->cursor->y, x, MIN(x + num, self->columns) - 1);
}

// }}}

// Device control {{{

void screen_bell(Screen UNUSED *self, uint8_t ch) {  
    FILE *f = fopen("/dev/tty", "w");
    if (f != NULL) {
        fwrite(&ch, 1, 1, f);
        fclose(f);
    }
} 

static inline void callback(const char *name, Screen *self, const char *data, unsigned int sz) {
    if (sz) PyObject_CallMethod(self->callbacks, name, "y#", data, sz);
    else PyObject_CallMethod(self->callbacks, name, "y", data);
    if (PyErr_Occurred()) PyErr_Print();
    PyErr_Clear(); 
}

void report_device_attributes(Screen *self, unsigned int UNUSED mode, bool UNUSED secondary) {
    // Do the same as libvte, which gives the below response regardless of mode and secondary
    callback("write_to_child", self, "\x1b[?62c", 0);  // Corresponds to VT-220
}

void report_device_status(Screen *self, unsigned int which, bool UNUSED private) {
    // We dont implement the private device status codes, since I haven;t come
    // across any programs that use them
    unsigned int x, y;
    char buf[50] = {0};
    switch(which) {
        case 5:  // device status
            callback("write_to_child", self, "\x1b[0n", 0); 
            break;
        case 6:  // cursor position
            x = self->cursor->x; y = self->cursor->y;
            if (x >= self->columns) {
                if (y < self->lines - 1) { x = 0; y++; }
                else x--;
            }
            if (self->modes.mDECOM) y -= MAX(y, self->margin_top);
            x++; y++;  // 1-based indexing
            if (snprintf(buf, sizeof(buf) - 1, "\x1b[%u;%uR", y, x) > 0) callback("write_to_child", self, buf, 0);
            break;
    }
}

void screen_set_margins(Screen *self, unsigned int top, unsigned int bottom) {
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

void screen_set_cursor(Screen *self, unsigned int mode, uint8_t secondary) {
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
                shape = (mode < 3) ? CURSOR_BLOCK : (mode < 5) ? CURSOR_UNDERLINE : (mode < 7) ? CURSOR_BEAM : 0;
            }
            if (shape != self->cursor->shape || blink != self->cursor->blink) {
                self->cursor->shape = shape; self->cursor->blink = blink;
                tracker_cursor_changed(self->change_tracker);
            }
            break;
    }
}

void set_title(Screen *self, const char *buf, unsigned int sz) {
    callback("title_changed", self, buf, sz);
}

void set_icon(Screen *self, const char *buf, unsigned int sz) {
    callback("icon_changed", self, buf, sz);
}

void set_dynamic_color(Screen *self, unsigned int code, const char *buf, unsigned int sz) {
    PyObject_CallMethod(self->callbacks, "set_dynamic_color", "Iy#", code, buf, sz);
    if (PyErr_Occurred()) PyErr_Print();
    PyErr_Clear(); 
}

// }}}

// Python interface {{{
static PyObject*
line(Screen *self, PyObject *val) {
#define line_doc ""
    unsigned long y = PyLong_AsUnsignedLong(val);
    if (y >= self->lines) { PyErr_SetString(PyExc_IndexError, "Out of bounds"); return NULL; }
    linebuf_init_line(self->linebuf, y);
    Py_INCREF(self->linebuf->line);
    return (PyObject*) self->linebuf->line;
}

static PyObject*
draw(Screen *self, PyObject *args) {
#define draw_doc ""
    Py_buffer pybuf;
    if(!PyArg_ParseTuple(args, "y*", &pybuf)) return NULL;
    screen_draw(self, pybuf.buf, pybuf.len);
    Py_RETURN_NONE;
}

static PyObject*
reset(Screen *self) {
#define reset_doc ""
    screen_reset(self);
    Py_RETURN_NONE;
}

static PyObject*
reset_mode(Screen *self, PyObject *args) {
#define reset_mode_doc ""
    int private = false;
    unsigned int mode;
    if (!PyArg_ParseTuple(args, "I|p", &mode, &private)) return NULL;
    if (private) mode <<= 5;
    screen_reset_mode(self, mode);
    Py_RETURN_NONE;
}
 
static PyObject*
set_mode(Screen *self, PyObject *args) {
#define set_mode_doc ""
    int private = false;
    unsigned int mode;
    if (!PyArg_ParseTuple(args, "I|p", &mode, &private)) return NULL;
    if (private) mode <<= 5;
    screen_set_mode(self, mode);
    Py_RETURN_NONE;
}

static PyObject*
reset_dirty(Screen *self) {
#define reset_dirty_doc ""
    tracker_reset(self->change_tracker);
    Py_RETURN_NONE;
}

static PyObject*
consolidate_changes(Screen *self) {
#define consolidate_changes_doc ""
    return tracker_consolidate_changes(self->change_tracker);
}

static PyObject*
cursor_back(Screen *self, PyObject *args) {
#define cursor_back_doc ""
    unsigned int count = 1;
    if (!PyArg_ParseTuple(args, "|I", &count)) return NULL;
    screen_cursor_back(self, count, -1);
    Py_RETURN_NONE;
}

static PyObject*
erase_in_line(Screen *self, PyObject *args) {
#define erase_in_line_doc ""
    int private = false;
    unsigned int how = 0;
    if (!PyArg_ParseTuple(args, "|Ip", &how, &private)) return NULL;
    screen_erase_in_line(self, how, private);
    Py_RETURN_NONE;
}

static PyObject*
erase_in_display(Screen *self, PyObject *args) {
#define erase_in_display_doc ""
    int private = false;
    unsigned int how = 0;
    if (!PyArg_ParseTuple(args, "|Ip", &how, &private)) return NULL;
    screen_erase_in_display(self, how, private);
    Py_RETURN_NONE;
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
index(Screen *self) {
    screen_index(self);
    Py_RETURN_NONE;
}

static PyObject*
reverse_index(Screen *self) {
    screen_reverse_index(self);
    Py_RETURN_NONE;
}

static PyObject*
resize(Screen *self, PyObject *args) {
    unsigned int lines = 1, columns = 1;
    if (!PyArg_ParseTuple(args, "II", &lines, &columns)) return NULL;
    if (!screen_resize(self, lines, columns)) return NULL;
    Py_RETURN_NONE;
}

static PyObject*
change_scrollback_size(Screen *self, PyObject *args) {
    unsigned int count = 1; 
    if (!PyArg_ParseTuple(args, "|I", &count)) return NULL; 
    if (!screen_change_scrollback_size(self, MAX(100, count))) return NULL;
    Py_RETURN_NONE;
}

static PyObject*
screen_update_cell_data(Screen *self, PyObject *args) {
    SpriteMap *spm;
    ColorProfile *color_profile;
    PyObject *dp;
    unsigned int *data;
    unsigned long default_bg, default_fg;
    int force_screen_refresh;
    if (!PyArg_ParseTuple(args, "O!O!O!kkp", &SpriteMap_Type, &spm, &ColorProfile_Type, &color_profile, &PyLong_Type, &dp, &default_fg, &default_bg, &force_screen_refresh)) return NULL;
    data = PyLong_AsVoidPtr(dp);
    PyObject *cursor_changed = self->change_tracker->cursor_changed ? Py_True : Py_False;
    if (!tracker_update_cell_data(self->change_tracker, self->linebuf, spm, color_profile, data, default_fg, default_bg, (bool)force_screen_refresh)) return NULL;
    Py_INCREF(cursor_changed);
    return cursor_changed;
}

static PyObject* is_dirty(Screen *self) {
    PyObject *ans = self->change_tracker->dirty ? Py_True : Py_False;
    Py_INCREF(ans);
    return ans;
}

#define COUNT_WRAP(name) \
    static PyObject* name(Screen *self, PyObject *args) { \
    unsigned int count = 1; \
    if (!PyArg_ParseTuple(args, "|I", &count)) return NULL; \
    screen_##name(self, count); \
    Py_RETURN_NONE; }
COUNT_WRAP(insert_lines)
COUNT_WRAP(delete_lines)
COUNT_WRAP(insert_characters)
COUNT_WRAP(delete_characters)
COUNT_WRAP(erase_characters)
COUNT_WRAP(cursor_up1)
COUNT_WRAP(cursor_down)
COUNT_WRAP(cursor_down1)
COUNT_WRAP(cursor_forward)

#define MND(name, args) {#name, (PyCFunction)name, args, ""},

static PyMethodDef methods[] = {
    METHOD(line, METH_O)
    METHOD(draw, METH_VARARGS)
    METHOD(set_mode, METH_VARARGS)
    METHOD(reset_mode, METH_VARARGS)
    METHOD(enable_focus_tracking, METH_NOARGS)
    METHOD(in_bracketed_paste_mode, METH_NOARGS)
    METHOD(reset, METH_NOARGS)
    METHOD(reset_dirty, METH_NOARGS)
    METHOD(consolidate_changes, METH_NOARGS)
    METHOD(cursor_back, METH_VARARGS)
    METHOD(erase_in_line, METH_VARARGS)
    METHOD(erase_in_display, METH_VARARGS)
    MND(insert_lines, METH_VARARGS)
    MND(delete_lines, METH_VARARGS)
    MND(insert_characters, METH_VARARGS)
    MND(delete_characters, METH_VARARGS)
    MND(change_scrollback_size, METH_VARARGS)
    MND(erase_characters, METH_VARARGS)
    MND(cursor_up, METH_VARARGS)
    MND(cursor_up1, METH_VARARGS)
    MND(cursor_down, METH_VARARGS)
    MND(cursor_down1, METH_VARARGS)
    MND(cursor_forward, METH_VARARGS)
    MND(index, METH_NOARGS)
    MND(reverse_index, METH_NOARGS)
    MND(is_dirty, METH_NOARGS)
    MND(resize, METH_VARARGS)
    {"update_cell_data", (PyCFunction)screen_update_cell_data, METH_VARARGS, ""},

    {NULL}  /* Sentinel */
};

static PyMemberDef members[] = {
    {"callbacks", T_OBJECT_EX, offsetof(Screen, callbacks), 0, "callbacks"},
    {"cursor", T_OBJECT_EX, offsetof(Screen, cursor), 0, "cursor"},
    {"linebuf", T_OBJECT_EX, offsetof(Screen, linebuf), 0, "linebuf"},
    {"lines", T_UINT, offsetof(Screen, lines), 0, "lines"},
    {"columns", T_UINT, offsetof(Screen, columns), 0, "columns"},
    {"margin_top", T_UINT, offsetof(Screen, margin_top), 0, "margin_top"},
    {"margin_bottom", T_UINT, offsetof(Screen, margin_bottom), 0, "margin_bottom"},
    {"current_charset", T_UINT, offsetof(Screen, current_charset), 0, "current_charset"},
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
};

INIT_TYPE(Screen)
// }}}
