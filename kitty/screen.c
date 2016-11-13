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
    unsigned int columns, lines;
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
        self->main_savepoints = PyList_New(0); self->alt_savepoints = PyList_New(0);
        self->savepoints = self->main_savepoints;
        self->change_tracker = alloc_change_tracker(lines, columns);
        self->tabstops = PyMem_Calloc(self->columns, sizeof(bool));
        if (self->cursor == NULL || self->main_linebuf == NULL || self->alt_linebuf == NULL || self->main_savepoints == NULL || self->alt_savepoints == NULL || self->change_tracker == NULL || self->tabstops == NULL) {
            Py_CLEAR(self); return NULL;
        }
    }
    return (PyObject*) self;
}

bool screen_reset(Screen *self) {
    if (self->linebuf == self->alt_linebuf) {if (!screen_toggle_screen_buffer(self)) return false; }
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
    return true;
}


static void
dealloc(Screen* self) {
    Py_CLEAR(self->callbacks);
    Py_CLEAR(self->cursor); 
    Py_CLEAR(self->main_linebuf); 
    Py_CLEAR(self->alt_linebuf);
    Py_CLEAR(self->main_savepoints); Py_CLEAR(self->alt_savepoints); Py_CLEAR(self->change_tracker);
    PyMem_Free(self->tabstops);
    Py_TYPE(self)->tp_free((PyObject*)self);
} // }}}

void screen_bell(Screen UNUSED *self, uint8_t ch) {  // {{{
    FILE *f = fopen("/dev/tty", "w");
    if (f != NULL) {
        fwrite(&ch, 1, 1, f);
        fclose(f);
    }
} // }}}

// Draw text {{{

static inline unsigned int safe_wcwidth(uint32_t ch) {
    int ans = wcwidth(ch);
    if (ans < 0) ans = 1;
    return MIN(2, ans);
}

static inline void
draw_codepoint(Screen UNUSED *self, uint32_t ch) {
    if (is_ignored_char(ch)) return;
    unsigned int char_width = safe_wcwidth(ch);
    if (self->columns - (unsigned int)self->cursor->x < char_width) {
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
        unsigned int right = self->modes.mIRM ? self->columns - 1 : MIN((unsigned int)(MAX(self->cursor->x, 1) - 1), self->columns - 1);
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
    switch(self->current_charset) {
        case 0:
            screen_draw_charset(self, self->g0_charset, buf, buflen); break;
        case 1:
            screen_draw_charset(self, self->g1_charset, buf, buflen); break;
        default:
            screen_draw_utf8(self, buf, buflen); break;
    }
}
// }}}

void screen_backspace(Screen UNUSED *self, uint8_t UNUSED ch) {
    // TODO: Implement this
}

void screen_tab(Screen UNUSED *self, uint8_t UNUSED ch) {
    // TODO: Implement this
}

void screen_shift_out(Screen UNUSED *self, uint8_t UNUSED ch) {
    // TODO: Implement this
}

void screen_shift_in(Screen UNUSED *self, uint8_t UNUSED ch) {
    // TODO: Implement this
}

bool screen_toggle_screen_buffer(Screen *self) {
    if (!screen_save_cursor(self)) return false;
    if (self->linebuf == self->main_linebuf) {
        self->linebuf = self->alt_linebuf;
        self->savepoints = self->alt_savepoints;
    } else {
        self->linebuf = self->main_linebuf;
        self->savepoints = self->main_savepoints;
    }
    screen_restore_cursor(self);
    tracker_update_screen(self->change_tracker);
    return true;
}

// Graphics {{{
void screen_change_default_color(Screen *self, unsigned int which, uint32_t col) {
    if (self->callbacks == Py_None) return;
    if (col & 0xFF) PyObject_CallMethod(self->callbacks, "change_default_color", "s(III)", which == FG ? "fg" : "bg", 
            (col >> 24) & 0xFF, (col >> 16) & 0xFF, (col >> 8) & 0xFF);
    else PyObject_CallMethod(self->callbacks, "change_default_color", "sO", which == FG ? "fg" : "bg", Py_None);
    if (PyErr_Occurred()) PyErr_Print();
    PyErr_Clear(); 
}
// }}}

// Modes {{{

void screen_normal_keypad_mode(Screen UNUSED *self) {} // Not implemented as this is handled by the GUI
void screen_alternate_keypad_mode(Screen UNUSED *self) {}  // Not implemented as this is handled by the GUI

static inline void set_mode_from_const(Screen *self, int mode, bool val) {
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

bool screen_set_mode(Screen *self, int mode) {
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
        if (!screen_toggle_screen_buffer(self)) return false;
    }
    set_mode_from_const(self, mode, true);
    return true;
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

bool screen_reset_mode(Screen *self, int mode) {
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
        if (!screen_toggle_screen_buffer(self)) return false;
    }
 
    set_mode_from_const(self, mode, false);
    return true;
}
// }}}

// Cursor {{{

void screen_cursor_back(Screen *self, unsigned int count/*=1*/, int move_direction/*=-1*/) {
    int x = self->cursor->x;
    if (count == 0) count = 1;
    self->cursor->x += move_direction * count;
    screen_ensure_bounds(self, false);
    if (x != self->cursor->x) tracker_cursor_changed(self->change_tracker);
}

void screen_cursor_forward(Screen *self, unsigned int count/*=1*/) {
    screen_cursor_back(self, count, 1);
}

void screen_cursor_up(Screen *self, unsigned int count/*=1*/, bool do_carriage_return/*=false*/, int move_direction/*=-1*/) {
    int x = self->cursor->x, y = self->cursor->y;
    if (count == 0) count = 1;
    self->cursor->y += move_direction * count;
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

void screen_index(Screen *self) {
    // Move cursor down one line, scrolling screen if needed
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if ((unsigned int)self->cursor->y == self->margin_bottom) {
        linebuf_index(self->linebuf, top, bottom);
        if (self->linebuf == self->main_linebuf) {
            // TODO: Add line to tophistorybuf
            tracker_line_added_to_history(self->change_tracker);
        }
        linebuf_clear_line(self->linebuf, bottom);
        if (bottom - top > self->lines - 1) tracker_update_screen(self->change_tracker);
        else tracker_update_line_range(self->change_tracker, top, bottom);
    } else screen_cursor_down(self, 1);
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

bool screen_save_cursor(Screen *self) {
    Savepoint *sp = alloc_savepoint();
    if (sp == NULL) return false;
    sp->cursor = cursor_copy(self->cursor);
    if (sp->cursor == NULL) { Py_CLEAR(sp); return NULL; }
    sp->g0_charset = self->g0_charset;
    sp->g1_charset = self->g1_charset;
    sp->current_charset = self->current_charset;
    sp->mDECOM = self->modes.mDECOM;
    sp->mDECAWM = self->modes.mDECAWM;
    sp->utf8_state = self->utf8_state;
    bool ret = PyList_Append(self->savepoints, (PyObject*)sp) == 0;
    Py_CLEAR(sp);
    return ret;
}

bool screen_restore_cursor(Screen *self) {
    Py_ssize_t sz = PyList_GET_SIZE(self->savepoints);
    if (sz > 0) {
        Savepoint *sp = (Savepoint*)PyList_GET_ITEM(self->savepoints, sz - 1);
        self->g0_charset = sp->g0_charset;
        self->g1_charset = sp->g1_charset;
        self->current_charset = sp->current_charset;
        self->utf8_state = sp->utf8_state;
        if (sp->mDECOM) screen_set_mode(self, DECOM);
        if (sp->mDECAWM) screen_set_mode(self, DECAWM);
        PyList_SetSlice(self->savepoints, sz-1, sz, NULL);
    } else {
        screen_cursor_position(self, 1, 1);
        tracker_cursor_changed(self->change_tracker);
        if (!screen_reset_mode(self, DECOM)) return false;
    }
    return true;
}

void screen_ensure_bounds(Screen *self, bool use_margins/*=false*/) {
    unsigned int top, bottom;
    if (use_margins || self->modes.mDECOM) {
        top = self->margin_top; bottom = self->margin_bottom;
    } else {
        top = 0; bottom = self->lines - 1;
    }
    self->cursor->x = MIN((unsigned int)MAX(0, self->cursor->x), self->columns - 1);
    self->cursor->y = MAX(top, MIN((unsigned int)MAX(0, self->cursor->y), bottom));
}

void screen_cursor_position(Screen *self, unsigned int line, unsigned int column) {
    line = (line || 1) - 1;
    column = (column || 1) - 1;
    if (self->modes.mDECOM) {
        line += self->margin_top;
        if (line < self->margin_bottom || line > self->margin_top) return;
    }
    int x = self->cursor->x, y = self->cursor->y;
    self->cursor->x = column; self->cursor->y = line;
    screen_ensure_bounds(self, false);
    if (x != self->cursor->x || y != self->cursor->y) tracker_cursor_changed(self->change_tracker);
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
    if(!screen_reset(self)) return NULL;
    Py_RETURN_NONE;
}

static PyObject*
reset_mode(Screen *self, PyObject *args) {
#define reset_mode_doc ""
    bool private = false;
    unsigned int mode;
    if (!PyArg_ParseTuple(args, "I|p", &mode, &private)) return NULL;
    if (private) mode <<= 5;
    if (!screen_reset_mode(self, mode)) return NULL;
    Py_RETURN_NONE;
}
 
static PyObject*
set_mode(Screen *self, PyObject *args) {
#define set_mode_doc ""
    bool private = false;
    unsigned int mode;
    if (!PyArg_ParseTuple(args, "I|p", &mode, &private)) return NULL;
    if (private) mode <<= 5;
    if (!screen_set_mode(self, mode)) return NULL;
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

    {NULL}  /* Sentinel */
};

static PyMemberDef members[] = {
    {"cursor", T_OBJECT_EX, offsetof(Screen, cursor), 0, "cursor"},
    {"linebuf", T_OBJECT_EX, offsetof(Screen, linebuf), 0, "linebuf"},
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

