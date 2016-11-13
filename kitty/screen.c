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
        self->main_linebuf = alloc_linebuf(); self->alt_linebuf = alloc_linebuf();
        self->linebuf = self->main_linebuf;
        self->main_savepoints = PyList_New(0); self->alt_savepoints = PyList_New(0);
        self->savepoints = self->main_savepoints;
        self->change_tracker = alloc_change_tracker();
        if (self->cursor == NULL || self->main_linebuf == NULL || self->alt_linebuf == NULL || self->main_savepoints == NULL || self->alt_savepoints == NULL || self->change_tracker == NULL) {
            Py_CLEAR(self); return NULL;
        }
    }
    return (PyObject*) self;
}

static void
dealloc(Screen* self) {
    Py_CLEAR(self->callbacks);
    Py_CLEAR(self->cursor); Py_CLEAR(self->main_linebuf); Py_CLEAR(self->alt_linebuf);
    Py_CLEAR(self->main_savepoints); Py_CLEAR(self->alt_savepoints); Py_CLEAR(self->change_tracker);
    Py_TYPE(self)->tp_free((PyObject*)self);
} // }}}

bool screen_bell(Screen UNUSED *self, uint8_t ch) {  // {{{
    FILE *f = fopen("/dev/tty", "w");
    if (f != NULL) {
        fwrite(&ch, 1, 1, f);
        fclose(f);
    }
    return true;
} // }}}


bool screen_linefeed(Screen UNUSED *self, uint8_t UNUSED ch) {
    // TODO: Implement this
    return true;
}

bool screen_carriage_return(Screen UNUSED *self, uint8_t UNUSED ch) {
    // TODO: Implement this
    return true;
}


// Draw text {{{

static inline int safe_wcwidth(uint32_t ch) {
    int ans = wcwidth(ch);
    if (ans < 0) ans = 1;
    return MIN(2, ans);
}

static inline bool
draw_codepoint(Screen UNUSED *self, uint32_t ch) {
    if (is_ignored_char(ch)) return true;
    int char_width = safe_wcwidth(ch);
    int space_left_in_line = self->columns - self->cursor->x;
    if (space_left_in_line < char_width) {
        if (self->modes.mDECAWM) {
            if (!screen_carriage_return(self, 13)) return false;
            if (!screen_linefeed(self, 10)) return false;
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
    return true;
}

static inline bool 
screen_draw_utf8(Screen *self, uint8_t *buf, unsigned int buflen) {
    uint32_t prev = UTF8_ACCEPT, codepoint = 0;
    for (unsigned int i = 0; i < buflen; i++, prev = self->utf8_state) {
        switch (decode_utf8(&self->utf8_state, &codepoint, buf[i])) {
            case UTF8_ACCEPT:
                if (!draw_codepoint(self, codepoint)) return false;
                break;
            case UTF8_REJECT:
                self->utf8_state = UTF8_ACCEPT;
                if (prev != UTF8_ACCEPT) i--;
                break;
        }
    }
    return true;
}

static inline bool 
screen_draw_charset(Screen *self, unsigned short *table, uint8_t *buf, unsigned int buflen) {
    for (unsigned int i = 0; i < buflen; i++) {
        if (!draw_codepoint(self, table[buf[i]])) return false;
    }
    return true;
}

bool screen_draw(Screen *self, uint8_t *buf, unsigned int buflen) {
    switch(self->current_charset) {
        case 0:
            return screen_draw_charset(self, self->g0_charset, buf, buflen);
            break;
        case 1:
            return screen_draw_charset(self, self->g1_charset, buf, buflen);
            break;
        default:
            return screen_draw_utf8(self, buf, buflen); break;
    }
}
// }}}

bool screen_backspace(Screen UNUSED *self, uint8_t UNUSED ch) {
    // TODO: Implement this
    return true;
}

bool screen_tab(Screen UNUSED *self, uint8_t UNUSED ch) {
    // TODO: Implement this
    return true;
}

bool screen_shift_out(Screen UNUSED *self, uint8_t UNUSED ch) {
    // TODO: Implement this
    return true;
}

bool screen_shift_in(Screen UNUSED *self, uint8_t UNUSED ch) {
    // TODO: Implement this
    return true;
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


// Modes {{{

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
        if (!screen_erase_in_display(self, 2, false)) return false;
        if (!screen_cursor_position(self, 1, 1)) return false;
    }
    // According to `vttest`, DECOM should also home the cursor, see
    // vttest/main.c:303.
    if (mode == DECOM) { if (!screen_cursor_position(self, 1, 1)) return false; }

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
        if (!screen_erase_in_display(self, 2, false)) return false;
        if (!screen_cursor_position(self, 1, 1)) return false;
    }
    // According to `vttest`, DECOM should also home the cursor, see
    // vttest/main.c:303.
    if (mode == DECOM) { if (!screen_cursor_position(self, 1, 1)) return false; }

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
        screen_reset_mode(self, DECOM);
    }
    return true;
}

bool screen_cursor_position(Screen UNUSED *self, unsigned int UNUSED line, unsigned int UNUSED column) {
    return true; // TODO: Implement this
}

// }}}

// Editing {{{
bool screen_erase_in_display(Screen UNUSED *self, unsigned int UNUSED how, bool UNUSED private) {
    return true; // TODO: Implement this
}
// }}}

bool screen_reset(Screen *self) {
    if (self->linebuf == self->alt_linebuf) {if (!screen_toggle_screen_buffer(self)) return false; }
    linebuf_clear(self->linebuf);
    // TODO: Implement this
    return true;
}

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
    if (!screen_draw(self, pybuf.buf, pybuf.len)) return NULL;
    Py_RETURN_NONE;
}
 
// Boilerplate {{{

static PyMethodDef methods[] = {
    METHOD(line, METH_O)
    METHOD(draw, METH_VARARGS)
    METHOD(enable_focus_tracking, METH_NOARGS)
    METHOD(in_bracketed_paste_mode, METH_NOARGS)

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


